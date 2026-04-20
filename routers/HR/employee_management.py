"""
인사 계정 승인/부서 관리 라우터 — /api/auth/*
"""
from datetime import date

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import get_connection
from services.HR.hr_notification_service import create_notification
from services.HR.issued_employee_id_service import (
    ensure_issued_ids_table,
    mark_employee_id_used,
    normalize_employee_id,
    release_employee_id_after_reject,
)

router = APIRouter()


def _ensure_account_decision_log(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hr_account_decision_log (
            id SERIAL PRIMARY KEY,
            decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            action VARCHAR(20) NOT NULL,
            employee_id VARCHAR(50) NOT NULL,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(255),
            department VARCHAR(100),
            position VARCHAR(100),
            registered_at TIMESTAMPTZ,
            reason TEXT,
            CONSTRAINT chk_hr_acct_action CHECK (action IN ('approved', 'rejected'))
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hr_acct_decision_at
        ON hr_account_decision_log (decided_at DESC)
        """
    )
    cur.execute(
        """
        ALTER TABLE hr_account_decision_log
        ADD COLUMN IF NOT EXISTS reason TEXT
        """
    )


def _ensure_info_employees_verified_at(cur) -> None:
    """기존 DB에 verified_at 컬럼이 없을 때 추가 (login_create_tables만으로는 컬럼이 생기지 않음)."""
    cur.execute(
        """
        ALTER TABLE info_employees
        ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ
        """
    )
    cur.execute(
        """
        UPDATE info_employees
           SET verified_at = updated_at
         WHERE is_verified = TRUE
           AND verified_at IS NULL
        """
    )


def _ensure_resigned_at(cur) -> None:
    """퇴사자 관리용 resigned_at 컬럼 보장."""
    cur.execute(
        """
        ALTER TABLE info_employees
        ADD COLUMN IF NOT EXISTS resigned_at TIMESTAMPTZ
        """
    )


class ApproveEmployeeRequest(BaseModel):
    employee_id: str
    department: str
    position: str


class RejectEmployeeRequest(BaseModel):
    employee_id: str
    reason: str = Field(default="정보 불일치", max_length=500)


class UpdateEmployeeDepartmentRequest(BaseModel):
    department: str
    reason: str
    position: Optional[str] = None


@router.post("/reject")
def reject_employee(body: RejectEmployeeRequest):
    employee_id = normalize_employee_id(body.employee_id)

    if not employee_id:
        raise HTTPException(status_code=400, detail="사번이 비어 있습니다.")

    reason = (body.reason or "정보 불일치").strip() or "정보 불일치"

    conn = get_connection()
    prev_autocommit = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    row = None

    try:
        _ensure_account_decision_log(cur)
        cur.execute(
            """
            SELECT employee_id, name, email, created_at
            FROM info_employees
            WHERE employee_id = %s AND is_verified = FALSE
            """,
            (employee_id,),
        )
        pending = cur.fetchone()
        if not pending:
            conn.rollback()
            raise HTTPException(status_code=404, detail="거절할 승인 대기 계정을 찾을 수 없습니다.")

        cur.execute(
            """
            INSERT INTO hr_account_decision_log (
                decided_at, action, employee_id, name, email, department, position, registered_at, reason
            ) VALUES (NOW(), 'rejected', %s, %s, %s, NULL, NULL, %s, %s)
            """,
            (pending[0], pending[1], pending[2], pending[3], reason),
        )
        cur.execute(
            """
            DELETE FROM info_employees
            WHERE employee_id = %s AND is_verified = FALSE
            """,
            (employee_id,),
        )
        if cur.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=404, detail="거절할 승인 대기 계정을 찾을 수 없습니다.")
        ensure_issued_ids_table(cur)
        release_employee_id_after_reject(cur, employee_id)
        conn.commit()
        row = (pending[0], pending[1])
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"가입 거절 처리 실패: {str(exc)}")
    finally:
        conn.autocommit = prev_autocommit
        cur.close()
        conn.close()

    create_notification(
        f"({row[0]}) 계정의 승인 요청이 거부되었습니다. 사유: {reason}",
        "계정 승인 관리",
    )

    return {
        "employee_id": row[0],
        "name": row[1],
        "reason": reason,
        "message": "가입 요청이 거절되었습니다.",
    }


@router.get("/employees")
def list_employees():
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_info_employees_verified_at(cur)
        _ensure_resigned_at(cur)
        cur.execute(
            """
            SELECT employee_id, name, email, phone_number, birth_date, nickname,
                   department, position, is_verified, is_active,
                   created_at, updated_at, verified_at
            FROM info_employees
            WHERE is_verified = TRUE
              AND resigned_at IS NULL
            ORDER BY department ASC NULLS LAST, name ASC
            """
        )
        rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"사원 목록 조회 실패: {str(exc)}")
    finally:
        cur.close()
        conn.close()

    return {
        "total": len(rows),
        "items": [
            {
                "employee_id": row[0],
                "name": row[1],
                "email": row[2],
                "phone_number": row[3],
                "birth_date": row[4].isoformat() if isinstance(row[4], date) else None,
                "nickname": row[5],
                "department": row[6],
                "position": row[7],
                "is_verified": row[8],
                "is_active": row[9],
                "created_at": str(row[10]),
                "updated_at": str(row[11]),
                "verified_at": str(row[12]) if row[12] is not None else None,
            }
            for row in rows
        ],
    }


@router.get("/account-decisions")
def list_account_decisions():
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_account_decision_log(cur)
        cur.execute(
            """
            SELECT id, decided_at, action, employee_id, name, email, department, position, registered_at, reason
            FROM hr_account_decision_log
            ORDER BY decided_at DESC
            LIMIT 500
            """
        )
        rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"승인·거절 내역 조회 실패: {str(exc)}"
        )
    finally:
        cur.close()
        conn.close()

    return {
        "total": len(rows),
        "items": [
            {
                "id": row[0],
                "decided_at": str(row[1]),
                "action": row[2],
                "employee_id": row[3],
                "name": row[4],
                "email": row[5],
                "department": row[6],
                "position": row[7],
                "registered_at": str(row[8]) if row[8] is not None else None,
                "reason": row[9],
            }
            for row in rows
        ],
    }


@router.put("/employees/{employee_id}/department")
def update_employee_department(employee_id: str, body: UpdateEmployeeDepartmentRequest):
    employee_id = normalize_employee_id(employee_id)
    department = body.department.strip()
    reason = body.reason.strip()
    position = body.position.strip() if body.position else None

    if not employee_id or not department or not reason:
        raise HTTPException(status_code=400, detail="사번, 변경할 부서, 변경 사유는 모두 필수입니다.")

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT name, department
            FROM info_employees
            WHERE employee_id = %s
              AND is_verified = TRUE
            """,
            (employee_id,),
        )
        current_row = cur.fetchone()
        if not current_row:
            raise HTTPException(status_code=404, detail="부서를 변경할 사원 계정을 찾을 수 없습니다.")

        previous_department = current_row[1]
        cur.execute(
            """
            UPDATE info_employees
               SET department = %s,
                   position = COALESCE(%s, position),
                   updated_at = NOW()
             WHERE employee_id = %s
               AND is_verified = TRUE
            RETURNING employee_id, name, department, position, updated_at
            """,
            (department, position, employee_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="부서를 변경할 사원 계정을 찾을 수 없습니다.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"부서 변경 실패: {str(exc)}")
    finally:
        cur.close()
        conn.close()

    create_notification(
        f"{row[1]}님의 부서를 '{previous_department}'에서 '{row[2]}'으로 변경했습니다.  변경 사유: {reason}",
        "부서",
    )

    return {
        "employee_id": row[0],
        "name": row[1],
        "department": row[2],
        "position": row[3],
        "updated_at": str(row[4]),
        "message": "사원 부서가 변경되었습니다.",
    }



@router.get("/pending")
def list_pending_employees():
    conn = get_connection()
    cur = conn.cursor()

    try:
        ensure_issued_ids_table(cur)
        conn.commit()
        cur.execute(
            """
            SELECT e.employee_id, e.name, e.email, e.phone_number, e.birth_date,
                   e.nickname, e.is_verified, e.is_active, e.created_at,
                   CASE WHEN h.employee_id IS NOT NULL AND h.voided_at IS NULL
                        THEN TRUE ELSE FALSE END AS was_issued
            FROM info_employees e
            LEFT JOIN hr_issued_employee_ids h
                   ON h.employee_id = e.employee_id
            WHERE e.is_verified = FALSE
            ORDER BY e.created_at DESC
            """
        )
        rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"승인 대기 목록 조회 실패: {str(exc)}")
    finally:
        cur.close()
        conn.close()

    return {
        "total": len(rows),
        "items": [
            {
                "employee_id": row[0],
                "name": row[1],
                "email": row[2],
                "phone_number": row[3],
                "birth_date": row[4].isoformat() if isinstance(row[4], date) else None,
                "nickname": row[5],
                "is_verified": row[6],
                "is_active": row[7],
                "created_at": str(row[8]),
                "was_issued": row[9],
            }
            for row in rows
        ],
    }


@router.post("/approve")
def approve_employee(body: ApproveEmployeeRequest):
    employee_id = normalize_employee_id(body.employee_id)
    department = body.department.strip()
    position = body.position.strip()

    if not employee_id or not department or not position:
        raise HTTPException(status_code=400, detail="사번, 부서, 직급은 모두 필수입니다.")

    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_account_decision_log(cur)
        _ensure_info_employees_verified_at(cur)
    finally:
        cur.close()

    prev_autocommit = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    row = None

    try:
        cur.execute(
            """
            UPDATE info_employees
               SET department = %s,
                   position = %s,
                   is_verified = TRUE,
                   is_active = TRUE,
                   verified_at = CASE WHEN is_verified = FALSE THEN NOW() ELSE verified_at END,
                   updated_at = NOW()
             WHERE employee_id = %s
            RETURNING employee_id, name, email, department, position, is_verified, is_active,
                      updated_at, verified_at, created_at
            """,
            (department, position, employee_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="승인할 사원 계정을 찾을 수 없습니다.")

        decided_at = row[8] if row[8] is not None else row[7]
        cur.execute(
            """
            INSERT INTO hr_account_decision_log (
                decided_at, action, employee_id, name, email, department, position, registered_at, reason
            ) VALUES (%s, 'approved', %s, %s, %s, %s, %s, %s, NULL)
            """,
            (decided_at, row[0], row[1], row[2], row[3], row[4], row[9]),
        )

        mark_employee_id_used(cur, employee_id)

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"승인 처리 실패: {str(exc)}")
    finally:
        conn.autocommit = prev_autocommit
        cur.close()
        conn.close()

    create_notification(f"[{row[0]}] 계정이 승인되었습니다.", "계정 승인 관리")

    return {
        "employee_id": row[0],
        "name": row[1],
        "department": row[3],
        "position": row[4],
        "is_verified": row[5],
        "is_active": row[6],
        "updated_at": str(row[7]),
        "verified_at": str(row[8]) if row[8] is not None else None,
        "message": "인사팀 승인과 부서·직급 배정이 완료되었습니다.",
    }
