"""
인사팀 사번 발급 — /api/auth/issued-employee-ids/*
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_connection
from services.HR.issued_employee_id_service import (
    ISSUE_DEPARTMENT_CODES,
    delete_unused_issued_employee_id,
    ensure_issued_ids_table,
    generate_next_ids,
    normalize_employee_id,
    peek_upcoming_serial_digits,
)

router = APIRouter()


class GenerateIssuedIdsRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=50)
    department_code: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="입사 부서 코드(알파벳 3자리), 예: BHR, RDE",
    )


class GenerateIssuedBatchItem(BaseModel):
    department_code: str = Field(
        ...,
        min_length=3,
        max_length=3,
    )
    count: int = Field(ge=1, le=50)


class GenerateIssuedBatchRequest(BaseModel):
    """여러 부서·건수를 한 요청으로 발급 (동일 트랜잭션, 일련번호 연속)."""

    batches: list[GenerateIssuedBatchItem] = Field(
        ...,
        min_length=1,
        max_length=30,
    )


@router.get("/issued-employee-ids/upcoming-serials")
def get_upcoming_serials(count: int = Query(1, ge=1, le=200)):
    """다음 발급 시 사용될 일련 3자리(전역 카운터 기준, 부서와 무관). 일괄 발급 상한과 동일."""
    conn = get_connection()
    prev = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    try:
        ensure_issued_ids_table(cur)
        serials = peek_upcoming_serial_digits(cur, count)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"일련 번호 미리보기 실패: {str(exc)}",
        )
    finally:
        conn.autocommit = prev
        cur.close()
        conn.close()

    return {"count": count, "serials": serials}


@router.get("/issued-employee-ids/department-codes")
def get_issue_department_codes():
    """발급 시 선택 가능한 입사 부서 코드 목록."""
    # 순서: 메인 대시보드(data/departments.js CATEGORIES 내 부서 순)와 동일 — 알파벳 정렬 금지
    return {
        "items": [
            {"code": code, "name": name}
            for code, name in ISSUE_DEPARTMENT_CODES.items()
        ],
    }


@router.post("/issued-employee-ids/generate")
def post_generate_issued_ids(body: GenerateIssuedIdsRequest):
    conn = get_connection()
    prev = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    try:
        ensure_issued_ids_table(cur)
        generated = generate_next_ids(cur, body.count, body.department_code)
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"사번 발급 실패: {str(exc)}")
    finally:
        conn.autocommit = prev
        cur.close()
        conn.close()

    return {
        "total": len(generated),
        "items": [{"employee_id": eid} for eid in generated],
    }


@router.post("/issued-employee-ids/generate-batch")
def post_generate_issued_ids_batch(body: GenerateIssuedBatchRequest):
    total_planned = sum(b.count for b in body.batches)
    if total_planned > 200:
        raise HTTPException(
            status_code=400,
            detail="한 번에 발급 가능한 총 개수는 200건 이하입니다.",
        )
    conn = get_connection()
    prev = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    all_ids: list[str] = []
    summary: list[dict] = []
    try:
        ensure_issued_ids_table(cur)
        for b in body.batches:
            part = generate_next_ids(cur, b.count, b.department_code)
            all_ids.extend(part)
            dept_name = ISSUE_DEPARTMENT_CODES.get(
                b.department_code.strip().upper(),
                b.department_code,
            )
            summary.append(
                {
                    "department_code": b.department_code.strip().upper(),
                    "department_name": dept_name,
                    "count": len(part),
                    "employee_ids": part,
                }
            )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"사번 일괄 발급 실패: {str(exc)}")
    finally:
        conn.autocommit = prev
        cur.close()
        conn.close()

    return {
        "total": len(all_ids),
        "items": [{"employee_id": eid} for eid in all_ids],
        "summary": summary,
    }


@router.delete("/issued-employee-ids/{employee_id}")
def delete_issued_employee_id(employee_id: str):
    """미사용 발급만 삭제 처리(voided_at). 행은 유지·상태 삭제됨. 전역 일련 카운터는 줄어들지 않음."""
    raw = employee_id.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="사번이 비어 있습니다.")

    conn = get_connection()
    prev = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    try:
        ensure_issued_ids_table(cur)
        deleted = delete_unused_issued_employee_id(cur, raw)
        if not deleted:
            conn.rollback()
            raise HTTPException(
                status_code=404,
                detail="삭제할 수 없습니다. 미사용 발급만 삭제할 수 있습니다.",
            )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"사번 삭제 실패: {str(exc)}")
    finally:
        conn.autocommit = prev
        cur.close()
        conn.close()

    eid = normalize_employee_id(raw)
    return {
        "employee_id": eid,
        "message": "상태가 삭제됨으로 변경되었습니다.",
    }


@router.get("/issued-employee-ids")
def get_issued_employee_ids():
    conn = get_connection()
    cur = conn.cursor()
    try:
        ensure_issued_ids_table(cur)
        cur.execute(
            """
            SELECT employee_id, issued_at, used_at, voided_at
            FROM hr_issued_employee_ids
            ORDER BY issued_at DESC, employee_id DESC
            LIMIT 500
            """
        )
        rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"사번 목록 조회 실패: {str(exc)}")
    finally:
        cur.close()
        conn.close()

    def _status(r):
        u, v = r[2], r[3]
        if v is not None:
            return "voided"
        if u is not None:
            return "used"
        return "available"

    return {
        "total": len(rows),
        "items": [
            {
                "employee_id": row[0],
                "issued_at": str(row[1]),
                "used_at": str(row[2]) if row[2] is not None else None,
                "voided_at": str(row[3]) if row[3] is not None else None,
                "status": _status(row),
            }
            for row in rows
        ],
    }
