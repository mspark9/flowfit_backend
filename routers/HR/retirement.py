"""
퇴사자 관리 라우터 — /api/auth/retirees, /api/auth/resign, /api/auth/rehire
퇴사 시 사번은 보존되며, info_employees 계정이 블락(is_active=FALSE)되고 resigned_at이 기록됩니다.
재입사 시 is_active=TRUE로 복구되고 resigned_at이 NULL 처리됩니다.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import get_connection
from services.HR.hr_notification_service import create_notification
from services.HR.issued_employee_id_service import normalize_employee_id

router = APIRouter()


def _ensure_resigned_at_column(cur) -> None:
    """info_employees 테이블에 resigned_at 컬럼이 없을 때 생성."""
    cur.execute(
        """
        ALTER TABLE info_employees
        ADD COLUMN IF NOT EXISTS resigned_at TIMESTAMPTZ
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_info_employees_resigned_at
        ON info_employees (resigned_at)
        """
    )


def _ensure_retirement_log(cur) -> None:
    """퇴사/재입사 이력 로그 테이블."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hr_retirement_log (
            id SERIAL PRIMARY KEY,
            decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            action VARCHAR(20) NOT NULL,
            employee_id VARCHAR(50) NOT NULL,
            name VARCHAR(100) NOT NULL,
            department VARCHAR(100),
            position VARCHAR(100),
            reason TEXT,
            CONSTRAINT chk_hr_retire_action CHECK (action IN ('resigned', 'rehired'))
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hr_retirement_decided_at
        ON hr_retirement_log (decided_at DESC)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hr_retirement_employee_id
        ON hr_retirement_log (employee_id)
        """
    )


class ResignRequest(BaseModel):
    employee_id: str
    reason: str = Field(default="", max_length=500)


class RehireRequest(BaseModel):
    employee_id: str
    department: Optional[str] = None
    position: Optional[str] = None
    reason: str = Field(default="", max_length=500)


@router.get("/retirees")
def list_retirees():
    """퇴사자 목록 (resigned_at 이 기록된 사원)."""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_resigned_at_column(cur)
        cur.execute(
            """
            SELECT employee_id, name, email, phone_number, birth_date, nickname,
                   department, position, is_verified, is_active,
                   created_at, updated_at, resigned_at
            FROM info_employees
            WHERE is_verified = TRUE
              AND resigned_at IS NOT NULL
            ORDER BY resigned_at DESC
            """
        )
        rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"퇴사자 목록 조회 실패: {str(exc)}")
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
                "resigned_at": str(row[12]) if row[12] is not None else None,
            }
            for row in rows
        ],
    }


@router.get("/retirement-log")
def list_retirement_log():
    """퇴사/재입사 이력 로그."""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_retirement_log(cur)
        cur.execute(
            """
            SELECT id, decided_at, action, employee_id, name, department, position, reason
            FROM hr_retirement_log
            ORDER BY decided_at DESC
            LIMIT 500
            """
        )
        rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"퇴사 이력 조회 실패: {str(exc)}")
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
                "department": row[5],
                "position": row[6],
                "reason": row[7],
            }
            for row in rows
        ],
    }


@router.post("/resign")
def resign_employee(body: ResignRequest):
    """사원을 퇴사 처리합니다. 사번·계정은 유지하되 is_active=FALSE 로 블락되어 로그인이 차단됩니다."""
    employee_id = normalize_employee_id(body.employee_id)
    reason = (body.reason or "").strip()

    if not employee_id:
        raise HTTPException(status_code=400, detail="사번이 비어 있습니다.")

    conn = get_connection()
    prev_autocommit = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    row = None

    try:
        _ensure_resigned_at_column(cur)
        _ensure_retirement_log(cur)

        cur.execute(
            """
            SELECT employee_id, name, department, position, is_verified, is_active, resigned_at
            FROM info_employees
            WHERE employee_id = %s
            """,
            (employee_id,),
        )
        current = cur.fetchone()
        if not current:
            conn.rollback()
            raise HTTPException(status_code=404, detail="사원 계정을 찾을 수 없습니다.")
        if not current[4]:
            conn.rollback()
            raise HTTPException(status_code=400, detail="승인되지 않은 계정은 퇴사 처리할 수 없습니다.")
        if current[6] is not None:
            conn.rollback()
            raise HTTPException(status_code=409, detail="이미 퇴사 처리된 사원입니다.")

        cur.execute(
            """
            UPDATE info_employees
               SET is_active = FALSE,
                   resigned_at = NOW(),
                   updated_at = NOW()
             WHERE employee_id = %s
            RETURNING employee_id, name, department, position, resigned_at
            """,
            (employee_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="퇴사 처리할 사원 계정을 찾을 수 없습니다.")

        cur.execute(
            """
            INSERT INTO hr_retirement_log (
                decided_at, action, employee_id, name, department, position, reason
            ) VALUES (NOW(), 'resigned', %s, %s, %s, %s, %s)
            """,
            (row[0], row[1], row[2], row[3], reason or None),
        )

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"퇴사 처리 실패: {str(exc)}")
    finally:
        conn.autocommit = prev_autocommit
        cur.close()
        conn.close()

    note_suffix = f" 사유: {reason}" if reason else ""
    create_notification(
        f"[{row[0]}] {row[1]}님이 퇴사 처리되었습니다.{note_suffix}",
        "퇴사자 관리",
    )

    return {
        "employee_id": row[0],
        "name": row[1],
        "department": row[2],
        "position": row[3],
        "resigned_at": str(row[4]),
        "message": "퇴사 처리가 완료되었습니다. 해당 계정은 로그인이 차단됩니다.",
    }


@router.post("/rehire")
def rehire_employee(body: RehireRequest):
    """퇴사자를 재입사 처리합니다. 기존 사번을 그대로 재활성화합니다."""
    employee_id = normalize_employee_id(body.employee_id)
    reason = (body.reason or "").strip()
    department = body.department.strip() if body.department else None
    position = body.position.strip() if body.position else None

    if not employee_id:
        raise HTTPException(status_code=400, detail="사번이 비어 있습니다.")

    conn = get_connection()
    prev_autocommit = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    row = None

    try:
        _ensure_resigned_at_column(cur)
        _ensure_retirement_log(cur)

        cur.execute(
            """
            SELECT employee_id, name, department, position, resigned_at
            FROM info_employees
            WHERE employee_id = %s
            """,
            (employee_id,),
        )
        current = cur.fetchone()
        if not current:
            conn.rollback()
            raise HTTPException(status_code=404, detail="사원 계정을 찾을 수 없습니다.")
        if current[4] is None:
            conn.rollback()
            raise HTTPException(status_code=400, detail="퇴사 상태가 아닌 계정입니다.")

        cur.execute(
            """
            UPDATE info_employees
               SET is_active = TRUE,
                   resigned_at = NULL,
                   department = COALESCE(%s, department),
                   position = COALESCE(%s, position),
                   updated_at = NOW()
             WHERE employee_id = %s
            RETURNING employee_id, name, department, position, is_active, updated_at
            """,
            (department, position, employee_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="재입사 처리할 사원 계정을 찾을 수 없습니다.")

        cur.execute(
            """
            INSERT INTO hr_retirement_log (
                decided_at, action, employee_id, name, department, position, reason
            ) VALUES (NOW(), 'rehired', %s, %s, %s, %s, %s)
            """,
            (row[0], row[1], row[2], row[3], reason or None),
        )

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"재입사 처리 실패: {str(exc)}")
    finally:
        conn.autocommit = prev_autocommit
        cur.close()
        conn.close()

    note_suffix = f" 사유: {reason}" if reason else ""
    create_notification(
        f"[{row[0]}] {row[1]}님이 재입사 처리되었습니다.{note_suffix}",
        "퇴사자 관리",
    )

    return {
        "employee_id": row[0],
        "name": row[1],
        "department": row[2],
        "position": row[3],
        "is_active": row[4],
        "updated_at": str(row[5]),
        "message": "재입사 처리가 완료되었습니다.",
    }
