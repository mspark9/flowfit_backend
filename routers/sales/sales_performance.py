"""
영업 실적 분석·등록 라우터 — /api/sales/performance/*
"""
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from services.sales.sales_performance_entry_service import (
    VALID_TYPES,
    delete_performance,
    fetch_performance,
    upsert_performance,
)
from services.sales.sales_performance_service import (
    analyze_performance,
    export_performance_to_excel,
    get_performance_compare,
    get_performance_trend,
    get_periods,
    get_team_members,
)

router = APIRouter()


# ────────────────────────────────────────────────────────────
# 분석 (기존)
# ────────────────────────────────────────────────────────────

class PerformanceRequest(BaseModel):
    period_key: str              # 예: '2026-04'
    member_id:  str = "all"      # 'all' 또는 member_name


@router.get("/members")
def performance_members(period_key: str = ""):
    """
    팀원 목록 — period_key 주어지면 해당 기간 등록 팀원만, 아니면 전체 기간 DISTINCT.
    """
    return get_team_members(period_key)


@router.get("/periods")
def performance_periods(period_type: str = ""):
    """
    분석 가능한 기간 목록 (최신순).

    Query: period_type = '' | 'month' | 'quarter' | 'year'
    Response: [ { period_key, period_label, period_type, start_date, end_date }, ... ]
    """
    if period_type and period_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"period_type은 {VALID_TYPES} 중 하나여야 합니다.")
    return get_periods(period_type=period_type)


@router.get("/trend")
def performance_trend(period_type: str = "month", limit: int = 6):
    """
    기간 타입별 최근 N개 기간의 실적 추세 (달성률·성장률 차트용).

    Query: period_type = 'month' | 'quarter' | 'year', limit = 1~24
    Response: [{ period_key, period_label, target_revenue, actual_revenue,
                 achievement_rate, growth_rate, win_rate, ... }, ...]
    """
    if period_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"period_type은 {VALID_TYPES} 중 하나여야 합니다.")
    if limit < 1 or limit > 24:
        raise HTTPException(status_code=400, detail="limit는 1~24 범위여야 합니다.")
    try:
        return get_performance_trend(period_type=period_type, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"추세 조회 실패: {str(e)}")


@router.get("/compare/{period_key}")
def performance_compare(period_key: str):
    """
    선택 기간과 직전 기간(전월·전분기·전년) 요약 지표를 나란히 반환.

    Response: { current, previous, previous_key, delta }
    """
    if not period_key.strip():
        raise HTTPException(status_code=400, detail="period_key가 필요합니다.")
    try:
        return get_performance_compare(period_key.strip())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비교 조회 실패: {str(e)}")


@router.get("/export/{period_key}")
def performance_export(period_key: str, member_id: str = "all"):
    """
    실적 분석 리포트를 Excel(xlsx) 파일로 다운로드합니다.
    """
    if not period_key.strip():
        raise HTTPException(status_code=400, detail="period_key가 필요합니다.")
    try:
        xlsx_bytes = export_performance_to_excel(period_key=period_key.strip(), member_id=member_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Excel 생성 실패: {str(e)}")

    filename = f"sales_report_{period_key}.xlsx"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}",
    }
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/analyze")
def performance_analyze(body: PerformanceRequest):
    """
    CRM 실적 데이터를 분석하여 리포트를 생성합니다.

    Request : { period_key, member_id? }
    Response: {
      metrics, pipeline, conversion_rates, members, anomalies,
      summary, achievement_comment,
      pipeline_insight, top_performer, risk_deals, recommendations
    }
    """
    if not body.period_key.strip():
        raise HTTPException(status_code=400, detail="period_key가 필요합니다.")

    try:
        result = analyze_performance(
            period_key=body.period_key.strip(),
            member_id=body.member_id,
        )
    except ValueError as e:
        # 기간이 DB에 없는 경우
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 분석 실패: {str(e)}")

    return result


# ────────────────────────────────────────────────────────────
# 등록/조회/삭제 (신규)
# ────────────────────────────────────────────────────────────

class PipelineStageInput(BaseModel):
    stage_order:  int
    stage_name:   str
    stage_count:  int
    stage_amount: int


class MemberInput(BaseModel):
    member_name: str
    revenue:     int
    deals:       int
    wins:        int


class PerformanceEntryRequest(BaseModel):
    period_type:     str                          # 'month' | 'quarter' | 'year'
    year:            int                          # 예) 2026
    value:           int = 0                      # month: 1~12, quarter: 1~4, year: 무시
    target_revenue:  int
    actual_revenue:  int
    prev_revenue:    int = 0
    deal_count:      int = 0
    win_count:       int = 0
    note:            str = ""
    pipeline:        list[PipelineStageInput] = []
    members:         list[MemberInput] = []
    created_by:      str = ""
    created_by_name: str = ""


@router.post("/entry")
def performance_entry(body: PerformanceEntryRequest):
    """
    영업 실적을 DB에 등록합니다 (같은 period_key면 덮어쓰기).

    Response: { period_key, period_label, period_type, start_date, end_date }
    """
    if body.period_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"period_type은 {VALID_TYPES} 중 하나여야 합니다.")
    if body.target_revenue < 0 or body.actual_revenue < 0:
        raise HTTPException(status_code=400, detail="매출은 0 이상이어야 합니다.")
    if body.deal_count < 0 or body.win_count < 0:
        raise HTTPException(status_code=400, detail="딜/수주 수는 0 이상이어야 합니다.")
    if body.win_count > body.deal_count:
        raise HTTPException(status_code=400, detail="수주 건수는 전체 딜 수를 초과할 수 없습니다.")

    try:
        result = upsert_performance(
            period_type=body.period_type,
            year=body.year,
            value=body.value,
            target_revenue=body.target_revenue,
            actual_revenue=body.actual_revenue,
            prev_revenue=body.prev_revenue,
            deal_count=body.deal_count,
            win_count=body.win_count,
            pipeline=[s.model_dump() for s in body.pipeline],
            members=[m.model_dump() for m in body.members],
            note=body.note,
            created_by=body.created_by,
            created_by_name=body.created_by_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"실적 등록 실패: {str(e)}")

    return result


@router.get("/entry/{period_key}")
def performance_entry_get(period_key: str):
    """
    등록된 실적 원본(수정 화면 프리필용) — 요약·파이프라인·팀원 일괄 반환.
    """
    data = fetch_performance(period_key)
    if not data:
        raise HTTPException(status_code=404, detail="등록된 실적이 없습니다.")
    return data


@router.delete("/entry/{period_key}")
def performance_entry_delete(period_key: str):
    """등록된 실적 1건 삭제 (CASCADE로 하위 테이블 정리)."""
    ok = delete_performance(period_key)
    if not ok:
        raise HTTPException(status_code=404, detail="등록된 실적이 없습니다.")
    return {"period_key": period_key, "deleted": True}
