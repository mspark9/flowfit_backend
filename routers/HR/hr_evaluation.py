"""
HR 인사 평가 라우터 — /api/hr/evaluation/*
"""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services.HR.hr_evaluation_entry_service import (
    VALID_TYPES,
    list_departments,
    list_employees,
    list_eval_periods,
    fetch_auto_data,
    fetch_evaluation,
    fetch_my_evaluations,
    upsert_evaluation,
    publish_evaluation,
    delete_evaluation,
)
from services.HR.hr_evaluation_service import (
    analyze_evaluation,
    export_evaluation_to_excel,
)

router = APIRouter()


# ────────────────────────────────────────────────────────────
# 부서 / 직원 목록
# ────────────────────────────────────────────────────────────

@router.get("/departments")
def eval_departments():
    """활성 직원이 있는 부서 목록을 반환합니다."""
    return list_departments()


@router.get("/employees")
def eval_employees(department: str = ""):
    """직원 목록 (부서 필터 선택)."""
    return list_employees(department=department)


# ────────────────────────────────────────────────────────────
# 자동 데이터 조회
# ────────────────────────────────────────────────────────────

@router.get("/auto-data")
def eval_auto_data(
    department: str = Query(..., description="부서명"),
    start_date: str = Query(..., description="시작일 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="종료일 (YYYY-MM-DD)"),
):
    """
    재무/영업 DB에서 해당 부서·기간의 자동 데이터를 조회합니다.
    예산집행률, 영업 실적, 직원 목록을 반환합니다.
    """
    if not department.strip():
        raise HTTPException(status_code=400, detail="department가 필요합니다.")
    try:
        return fetch_auto_data(
            department=department.strip(),
            start_date=start_date.strip(),
            end_date=end_date.strip(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"자동 데이터 조회 실패: {str(e)}")


# ────────────────────────────────────────────────────────────
# 평가 등록 / 조회 / 삭제
# ────────────────────────────────────────────────────────────

class DepartmentKPIInput(BaseModel):
    department:          str
    budget_total:        int = 0
    budget_spent:        int = 0
    sales_revenue:       int = 0
    sales_deals:         int = 0
    sales_wins:          int = 0
    target_achievement:  float = Field(default=0, ge=0, le=200)
    project_completion:  float = Field(default=0, ge=0, le=100)
    collaboration_score: float = Field(default=0, ge=0, le=100)
    headcount:           int = 0


class IndividualEvalInput(BaseModel):
    employee_id:   str = ""
    employee_name: str
    department:    str
    position:      str = ""
    sales_revenue: int = 0
    sales_wins:    int = 0
    evaluate_a1:   float = Field(default=0, ge=0, le=999)
    evaluate_a2:   float = Field(default=0, ge=0, le=999)
    evaluate_a3:   float = Field(default=0, ge=0, le=999)
    evaluate_a4:   float = Field(default=0, ge=0, le=999)
    evaluate_a5:   float = Field(default=0, ge=0, le=999)
    evaluate_a6:   float = Field(default=0, ge=0, le=999)
    evaluate_a7:   float = Field(default=0, ge=0, le=999)
    evaluate_a8:   float = Field(default=0, ge=0, le=999)


class CriteriaItem(BaseModel):
    key:     str
    label:   str = ""
    weight:  float = 0
    enabled: bool = False
    max:     float = 100
    source:  str = ""


class CriteriaThresholds(BaseModel):
    A: float = 80
    B: float = 65
    C: float = 50


class CriteriaConfig(BaseModel):
    items:      list[CriteriaItem] = []
    thresholds: CriteriaThresholds = Field(default_factory=CriteriaThresholds)


class EvaluationEntryRequest(BaseModel):
    eval_type:       str                          # 'quarter' | 'half' | 'year'
    year:            int
    value:           int = 0                      # quarter: 1~4, half: 1~2
    department:      str = ""                     # "" = 전체 부서
    departments:     list[DepartmentKPIInput] = []
    individuals:     list[IndividualEvalInput] = []
    criteria_config: CriteriaConfig | None = None
    created_by:      str = ""
    created_by_name: str = ""


@router.get("/periods")
def eval_periods(eval_type: str = ""):
    """등록된 평가 기간 목록 (최신순)."""
    if eval_type and eval_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"eval_type은 {VALID_TYPES} 중 하나여야 합니다.")
    return list_eval_periods(eval_type=eval_type)


@router.post("/entry")
def eval_entry(body: EvaluationEntryRequest):
    """
    평가를 저장합니다 (같은 eval_key면 덮어쓰기).
    """
    if body.eval_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"eval_type은 {VALID_TYPES} 중 하나여야 합니다.")

    try:
        result = upsert_evaluation(
            eval_type=body.eval_type,
            year=body.year,
            value=body.value,
            department=body.department,
            departments=[d.model_dump() for d in body.departments],
            individuals=[i.model_dump() for i in body.individuals],
            criteria_config=body.criteria_config.model_dump() if body.criteria_config else None,
            created_by=body.created_by,
            created_by_name=body.created_by_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"평가 저장 실패: {str(e)}")

    return result


@router.get("/entry/{eval_key}")
def eval_entry_get(eval_key: str):
    """저장된 평가 원본을 조회합니다 (수정 화면 프리필용)."""
    data = fetch_evaluation(eval_key)
    if not data:
        raise HTTPException(status_code=404, detail="등록된 평가가 없습니다.")
    return data


@router.get("/my")
def eval_my(employee_id: str = "", employee_name: str = ""):
    """
    현재 로그인한 사원이 받은 평가 결과를 최신순으로 반환합니다.
    employee_id 우선, 없으면 employee_name으로 조회합니다.
    """
    if not employee_id.strip() and not employee_name.strip():
        raise HTTPException(status_code=400, detail="employee_id 또는 employee_name이 필요합니다.")
    try:
        items = fetch_my_evaluations(
            employee_id=employee_id,
            employee_name=employee_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"내 평가 조회 실패: {str(e)}")
    return {"total": len(items), "items": items}


@router.post("/publish/{eval_key}")
def eval_publish(eval_key: str):
    """평가 보고서를 등록(공개)합니다 — 등록 후 개인이 자신의 평가를 조회할 수 있습니다."""
    if not eval_key.strip():
        raise HTTPException(status_code=400, detail="eval_key가 필요합니다.")
    try:
        return publish_evaluation(eval_key.strip())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"등록 실패: {str(e)}")


@router.delete("/entry/{eval_key}")
def eval_entry_delete(eval_key: str):
    """평가 1건을 삭제합니다 (CASCADE로 부서·개인 데이터 정리)."""
    ok = delete_evaluation(eval_key)
    if not ok:
        raise HTTPException(status_code=404, detail="등록된 평가가 없습니다.")
    return {"eval_key": eval_key, "deleted": True}


# ────────────────────────────────────────────────────────────
# AI 분석 및 Excel 내보내기
# ────────────────────────────────────────────────────────────

class EvaluationAnalyzeRequest(BaseModel):
    eval_key:   str
    department: str = ""   # "" = 전체 부서


@router.post("/analyze")
def eval_analyze(body: EvaluationAnalyzeRequest):
    """
    저장된 평가 데이터를 분석하여 AI 리포트를 생성합니다.
    """
    if not body.eval_key.strip():
        raise HTTPException(status_code=400, detail="eval_key가 필요합니다.")

    try:
        result = analyze_evaluation(
            eval_key=body.eval_key.strip(),
            department=body.department,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 분석 실패: {str(e)}")

    return result


@router.get("/export/{eval_key}")
def eval_export(eval_key: str, department: str = ""):
    """평가 리포트를 Excel(xlsx)로 다운로드합니다."""
    if not eval_key.strip():
        raise HTTPException(status_code=400, detail="eval_key가 필요합니다.")
    try:
        xlsx_bytes = export_evaluation_to_excel(
            eval_key=eval_key.strip(),
            department=department,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Excel 생성 실패: {str(e)}")

    filename = f"hr_evaluation_{eval_key}.xlsx"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}",
    }
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
