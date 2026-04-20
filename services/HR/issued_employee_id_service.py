"""
형식: 입사부서코드(3자)+년도(2자리) + ASCII 하이픈(-) + 일련(3자리)+랜덤(2자리). 구분자는 U+002D 만 사용.
예: BHR26-00047
화면 일련번호(3자리)는 000~999 순환(첫 발급 000). 전역 발급 카운터(next_seq)는 단조 증가하며, 미사용 행 삭제 시 롤백되지 않음.
예전에 n=seq%1000 규칙으로 쓰던 DB는 migrate_serial_seq_zero_start.py 로 next_seq를 한 번 맞출 것.
레거시: EMP-연도-일련(3자리) — 기존 사원 호환(정규화 없이 문자열 그대로 조회)
"""
import re
import secrets
from datetime import datetime

from fastapi import HTTPException

# 인사 발급 시 선택 가능한 입사 부서 코드 (알파벳 3자리)
# 삽입 순서 = 메인 대시보드 부서 카드 순서(경영지원→사업/영업→기술)와 동일하게 유지할 것
# 표시명은 frontend/src/data/departments.js 각 부서 label 과 동일하게 유지
ISSUE_DEPARTMENT_CODES: dict[str, str] = {
    "BHR": "인사(HR)팀",
    "BFI": "재무/회계팀",
    "BLG": "법무/컴플라이언스팀",
    "BGA": "총무/구매팀",
    "FST": "전략/기획팀",
    "FSL": "영업/영업관리팀",
    "FMK": "마케팅/PR팀",
    "FCS": "CS/고객지원팀",
    "RDE": "개발/IT운영팀",
    "RQA": "QA/품질관리팀",
    "RDS": "디자인/UX팀",
    "XYZ": "기타(관리자)",
}

# CCCYY-NNNRR (랜덤 2자리)
_H = "-"  # U+002D 하이픈만 사번 구분에 사용
_RE_NEW = re.compile(r"^([A-Z]{3})(\d{2})-(\d{3})(\d{2})$")


def _ascii_hyphen_employee_id(s: str) -> str:
    """복사·입력으로 섞인 유니코드 대시/마이너스를 ASCII 하이픈(-)으로 통일."""
    t = s
    for bad in (
        "\u2010",
        "\u2011",
        "\u2012",
        "\u2013",
        "\u2014",
        "\u2015",
        "\u2212",
        "\uff0d",
        "\u00ad",
    ):
        t = t.replace(bad, _H)
    return t


def ensure_issued_ids_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hr_issued_employee_ids (
          employee_id VARCHAR(50) PRIMARY KEY,
          issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          used_at TIMESTAMPTZ,
          voided_at TIMESTAMPTZ
        )
        """
    )
    cur.execute(
        """
        ALTER TABLE hr_issued_employee_ids
        ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ
        """
    )
    cur.execute("DROP INDEX IF EXISTS idx_hr_issued_unused")
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hr_issued_unused
        ON hr_issued_employee_ids (used_at)
        WHERE used_at IS NULL AND voided_at IS NULL
        """
    )
    cur.execute(
        """
        INSERT INTO hr_issued_employee_ids (employee_id, issued_at, used_at)
        SELECT e.employee_id, e.created_at, e.created_at
        FROM info_employees e
        WHERE e.is_verified = TRUE
          AND NOT EXISTS (
            SELECT 1 FROM hr_issued_employee_ids h WHERE h.employee_id = e.employee_id
          )
        """
    )


def ensure_serial_sequence_table(cur) -> None:
    """전역 발급 일련 카운터(단조 증가, 삭제·표시 순환과 무관)."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hr_employee_serial_seq (
          id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          next_seq BIGINT NOT NULL DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        INSERT INTO hr_employee_serial_seq (id, next_seq) VALUES (1, 0)
        ON CONFLICT (id) DO NOTHING
        """
    )


def _bootstrap_next_seq(cur) -> None:
    """최초 1회: 기존 hr_issued 행으로 카운터 하한을 맞춤."""
    cur.execute("SELECT next_seq FROM hr_employee_serial_seq WHERE id = 1")
    row = cur.fetchone()
    if not row:
        return
    if row[0] and row[0] > 0:
        return
    m = 0
    cnt = 0
    cur.execute("SELECT employee_id FROM hr_issued_employee_ids")
    for (eid,) in cur.fetchall():
        if not eid:
            continue
        s = _parse_new_serial(eid)
        if s is not None:
            cnt += 1
            m = max(m, s)
    # n = (seq-1)%1000 일 때, 일련 정수 S(000→0)는 seq=S+1 에 대응. 발급 이력이 있으면 next_seq = m+1 로 맞춤.
    if cnt == 0:
        start = 0
    else:
        start = m + 1
    cur.execute(
        "UPDATE hr_employee_serial_seq SET next_seq = %s WHERE id = 1",
        (start,),
    )


def normalize_employee_id(employee_id: str) -> str:
    """회원가입·검증 시 사번을 DB와 동일한 정규형으로 맞춤 (신규 형식은 대문자 부서코드)."""
    s = _ascii_hyphen_employee_id(employee_id.strip())
    u = s.upper()
    m = _RE_NEW.match(u)
    if m:
        return f"{m.group(1)}{m.group(2)}{_H}{m.group(3)}{m.group(4)}"
    return s


def _parse_new_serial(eid: str) -> int | None:
    u = _ascii_hyphen_employee_id(eid.strip()).upper()
    m = _RE_NEW.match(u)
    if m:
        return int(m.group(3))
    return None


def assert_issued_and_unused(cur, employee_id: str) -> None:
    ensure_issued_ids_table(cur)
    eid = normalize_employee_id(employee_id)
    cur.execute(
        """
        SELECT used_at, voided_at FROM hr_issued_employee_ids
        WHERE employee_id = %s
        """,
        (eid,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(
            status_code=403,
            detail="인사팀에서 발급한 사번으로만 가입할 수 있습니다. 사번을 확인하거나 인사팀에 문의하세요.",
        )
    used_at, voided_at = row[0], row[1]
    if voided_at is not None:
        raise HTTPException(
            status_code=403,
            detail="삭제 처리된 사번입니다. 인사팀에 문의하세요.",
        )
    if used_at is not None:
        raise HTTPException(status_code=409, detail="이미 사용된 사번입니다.")


def mark_employee_id_used(cur, employee_id: str) -> None:
    eid = normalize_employee_id(employee_id)
    cur.execute(
        """
        UPDATE hr_issued_employee_ids
           SET used_at = NOW()
         WHERE employee_id = %s AND used_at IS NULL AND voided_at IS NULL
        """,
        (eid,),
    )


def release_employee_id_after_reject(cur, employee_id: str) -> None:
    """승인 거절로 계정이 삭제되면 동일 사번으로 재가입 가능하도록 비움."""
    ensure_issued_ids_table(cur)
    eid = normalize_employee_id(employee_id)
    cur.execute(
        """
        UPDATE hr_issued_employee_ids
           SET used_at = NULL
         WHERE employee_id = %s AND voided_at IS NULL
        """,
        (eid,),
    )


def delete_unused_issued_employee_id(cur, employee_id: str) -> bool:
    """선택 삭제: 미사용 행에 voided_at 설정(행 유지). 전역 next_seq는 감소하지 않음."""
    ensure_issued_ids_table(cur)
    eid = normalize_employee_id(employee_id)
    cur.execute(
        """
        UPDATE hr_issued_employee_ids
           SET voided_at = NOW()
         WHERE employee_id = %s
           AND used_at IS NULL
           AND voided_at IS NULL
        RETURNING employee_id
        """,
        (eid,),
    )
    return cur.fetchone() is not None


def peek_upcoming_serial_digits(cur, count: int) -> list[str]:
    """다음 발급에 쓰일 일련 3자리(000~999) 목록. generate_next_ids와 동일: (next_seq+i)%1000."""
    if count < 1:
        return []
    ensure_issued_ids_table(cur)
    ensure_serial_sequence_table(cur)
    _bootstrap_next_seq(cur)
    cur.execute("SELECT next_seq FROM hr_employee_serial_seq WHERE id = 1")
    row = cur.fetchone()
    s = int(row[0]) if row and row[0] is not None else 0
    return [f"{(s + i) % 1000:03d}" for i in range(count)]


def _random_suffix() -> int:
    return secrets.randbelow(100)


def _insert_issued_id(cur, eid: str) -> None:
    cur.execute(
        """
        INSERT INTO hr_issued_employee_ids (employee_id)
        VALUES (%s)
        """,
        (eid,),
    )


def generate_next_ids(cur, count: int, dept_code: str) -> list[str]:
    ensure_issued_ids_table(cur)
    ensure_serial_sequence_table(cur)
    dept = dept_code.strip().upper()
    if dept not in ISSUE_DEPARTMENT_CODES:
        raise HTTPException(
            status_code=400,
            detail="유효하지 않은 입사 부서 코드입니다.",
        )
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (91234501,))
    _bootstrap_next_seq(cur)
    yy = datetime.now().year % 100
    out: list[str] = []
    for _ in range(count):
        inserted = False
        for _attempt in range(80):
            cur.execute(
                """
                UPDATE hr_employee_serial_seq
                   SET next_seq = next_seq + 1
                 WHERE id = 1
                RETURNING next_seq
                """
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=500,
                    detail="일련 카운터를 읽을 수 없습니다.",
                )
            seq = int(row[0])
            n = (seq - 1) % 1000
            rnd = _random_suffix()
            eid = f"{dept}{yy:02d}{_H}{n:03d}{rnd:02d}"
            cur.execute("SAVEPOINT sp_issue_try")
            try:
                _insert_issued_id(cur, eid)
                cur.execute("RELEASE SAVEPOINT sp_issue_try")
                out.append(eid)
                inserted = True
                break
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT sp_issue_try")
                err = str(exc).lower()
                if (
                    "unique" in err
                    or "duplicate" in err
                    or "primary key" in err
                    or "violates unique constraint" in err
                ):
                    continue
                raise
        if not inserted:
            raise HTTPException(
                status_code=500,
                detail="사번 발급 중 충돌이 반복되었습니다. 다시 시도해 주세요.",
            )
    return out
