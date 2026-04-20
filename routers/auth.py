"""
인증 라우터: /api/auth/*
"""
import hashlib
import hmac
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_connection
from services.HR.issued_employee_id_service import (
    assert_issued_and_unused,
    normalize_employee_id,
)

router = APIRouter()


def hash_password(employee_id: str, password: str) -> str:
    """
    사번을 salt처럼 사용해 비밀번호를 해시합니다.
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        employee_id.encode("utf-8"),
        100_000,
    ).hex()


class RegisterEmployeeRequest(BaseModel):
    employee_id: str
    name: str
    email: str
    password: str
    phone_number: str
    birth_date: Optional[date] = None
    nickname: Optional[str] = None


class LoginRequest(BaseModel):
    employee_id: str
    password: str


class UpdateProfileRequest(BaseModel):
    employee_id: str
    name: str
    email: str
    phone_number: str
    birth_date: Optional[date] = None
    nickname: Optional[str] = None
    password: Optional[str] = None


@router.get("/profile/{employee_id}")
def get_profile(employee_id: str):
    employee_id = normalize_employee_id(employee_id)

    if not employee_id:
        raise HTTPException(status_code=400, detail="사번이 비어 있습니다.")

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT employee_id, name, email, phone_number, birth_date, nickname,
                   department, position, is_verified, is_active, updated_at
            FROM info_employees
            WHERE employee_id = %s
            """,
            (employee_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="사원 정보를 찾을 수 없습니다.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"사원 정보 조회 실패: {str(exc)}")
    finally:
        cur.close()
        conn.close()

    return {
        "employee": {
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
        },
        "approval_status": "approved" if row[8] else "pending_approval",
        "updated_at": str(row[10]),
    }


@router.post("/register", status_code=201)
def register_employee(body: RegisterEmployeeRequest):
    employee_id = normalize_employee_id(body.employee_id)
    name = body.name.strip()
    email = body.email.strip().lower()
    password = body.password
    phone_number = body.phone_number.strip()
    nickname = body.nickname.strip() if body.nickname else None

    if not employee_id or not name or not email or not password or not phone_number:
        raise HTTPException(status_code=400, detail="필수 회원가입 정보가 비어 있습니다.")

    conn = get_connection()
    prev_autocommit = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT employee_id, email
            FROM info_employees
            WHERE employee_id = %s OR email = %s
            """,
            (employee_id, email),
        )
        duplicated = cur.fetchone()
        if duplicated:
            if duplicated[0] == employee_id:
                raise HTTPException(status_code=409, detail="이미 사용 중인 사번입니다.")
            raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다.")

        # 발급되지 않은 아이디(사번)도 가입 가능 - was_issued 플래그로 구분해 응답하고, 프론트에서 색상으로 구분
        was_issued = True
        try:
            assert_issued_and_unused(cur, employee_id)
        except HTTPException as issue_exc:
            if issue_exc.status_code == 403:
                # 미발급 또는 voided 사번: 가입은 진행, 플래그만 기록
                was_issued = False
            else:
                # 409 이미 사용된 사번 등은 그대로 차단
                raise

        cur.execute(
            """
            INSERT INTO info_employees
                (employee_id, name, email, password, phone_number, birth_date, nickname,
                 department, position, is_verified, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL, FALSE, FALSE)
            RETURNING employee_id, created_at
            """,
            (
                employee_id,
                name,
                email,
                hash_password(employee_id, password),
                phone_number,
                body.birth_date,
                nickname,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"회원가입 처리 실패: {str(exc)}")
    finally:
        conn.autocommit = prev_autocommit
        cur.close()
        conn.close()

    return {
        "employee_id": row[0],
        "created_at": str(row[1]),
        "status": "pending_approval",
        "was_issued": was_issued,
        "message": (
            "회원가입 요청이 완료되었습니다. 인사팀 승인 후 로그인할 수 있습니다."
            if was_issued
            else "미발급 사번으로 회원가입이 요청되었습니다. 인사팀 승인 시 별도 확인이 필요합니다."
        ),
    }


@router.put("/profile")
def update_profile(body: UpdateProfileRequest):
    employee_id = normalize_employee_id(body.employee_id)
    name = body.name.strip()
    email = body.email.strip().lower()
    phone_number = body.phone_number.strip()
    nickname = body.nickname.strip() if body.nickname else None

    if not employee_id or not name or not email or not phone_number:
        raise HTTPException(status_code=400, detail="이름, 이메일, 전화번호는 필수입니다.")

    conn = get_connection()
    prev_autocommit = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT employee_id
            FROM info_employees
            WHERE email = %s AND employee_id <> %s
            """,
            (email, employee_id),
        )
        duplicated = cur.fetchone()
        if duplicated:
            raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다.")

        if body.password:
            cur.execute(
                """
                UPDATE info_employees
                   SET name = %s,
                       email = %s,
                       phone_number = %s,
                       birth_date = %s,
                       nickname = %s,
                       password = %s,
                       updated_at = NOW()
                 WHERE employee_id = %s
                RETURNING employee_id, name, email, phone_number, birth_date, nickname,
                          department, position, is_verified, is_active, updated_at
                """,
                (
                    name,
                    email,
                    phone_number,
                    body.birth_date,
                    nickname,
                    hash_password(employee_id, body.password),
                    employee_id,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE info_employees
                   SET name = %s,
                       email = %s,
                       phone_number = %s,
                       birth_date = %s,
                       nickname = %s,
                       updated_at = NOW()
                 WHERE employee_id = %s
                RETURNING employee_id, name, email, phone_number, birth_date, nickname,
                          department, position, is_verified, is_active, updated_at
                """,
                (
                    name,
                    email,
                    phone_number,
                    body.birth_date,
                    nickname,
                    employee_id,
                ),
            )

        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="수정할 계정을 찾을 수 없습니다.")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"내 정보 수정 실패: {str(exc)}")
    finally:
        conn.autocommit = prev_autocommit
        cur.close()
        conn.close()

    return {
        "employee": {
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
        },
        "approval_status": "approved" if row[8] else "pending_approval",
        "updated_at": str(row[10]),
        "message": "내 정보가 수정되었습니다.",
    }


@router.post("/login")
def login_employee(body: LoginRequest):
    employee_id = normalize_employee_id(body.employee_id)
    password = body.password

    if not employee_id or not password:
        raise HTTPException(status_code=400, detail="사번과 비밀번호를 모두 입력해 주세요.")

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT employee_id, name, email, password, department, position,
                   is_verified, is_active, birth_date, nickname, phone_number
            FROM info_employees
            WHERE employee_id = %s
            """,
            (employee_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="사번 또는 비밀번호가 올바르지 않습니다.")

        stored_password = row[3]
        expected_password = hash_password(employee_id, password)
        if not hmac.compare_digest(stored_password, expected_password):
            raise HTTPException(status_code=401, detail="사번 또는 비밀번호가 올바르지 않습니다.")

        is_verified = row[6]
        is_active = row[7]

        # 비활성화된 승인 계정은 로그인 차단
        if is_verified and not is_active:
            raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"로그인 처리 실패: {str(exc)}")
    finally:
        cur.close()
        conn.close()

    birth_date = row[8]
    department = row[4]
    position = row[5]
    approval_status = "approved" if row[6] else "pending_approval"

    if approval_status == "pending_approval":
        message = f"{row[1]}님, 로그인되었습니다. 현재 인사팀 승인 대기 상태입니다."
    elif not department or not position:
        message = f"{row[1]}님, 로그인되었습니다. 부서/직급이 아직 배정되지 않았습니다."
    else:
        message = f"{row[1]}님, 로그인되었습니다."

    return {
        "employee": {
            "employee_id": row[0],
            "name": row[1],
            "email": row[2],
            "phone_number": row[10],
            "department": row[4],
            "position": row[5],
            "is_verified": row[6],
            "is_active": row[7],
            "birth_date": birth_date.isoformat() if isinstance(birth_date, date) else None,
            "nickname": row[9],
        },
        "approval_status": approval_status,
        "message": message,
        "redirectTo": "/",
    }
