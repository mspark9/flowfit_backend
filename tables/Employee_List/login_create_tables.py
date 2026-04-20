import sys
import os
import pg8000.dbapi as pg8000
from dotenv import load_dotenv

# .env 로드
load_dotenv()

DB_HOST     = os.environ.get("DB_HOST")
DB_PORT     = int(os.environ.get("DB_PORT", 5432))
DB_USER     = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_DATABASE = os.environ.get("DB_DATABASE")
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")

# ────────────────────────────────────────────────────────────
# 사원 정보 DDL 정의
# ────────────────────────────────────────────────────────────
TABLES: list[tuple[str, str]] = [
    (
        "info_employees",
        """
        CREATE TABLE IF NOT EXISTS info_employees (
            employee_id   VARCHAR(50)     PRIMARY KEY,          -- 사번 (기본키 및 로그인 ID)
            name          VARCHAR(100)    NOT NULL,             -- 이름
            email         VARCHAR(255)    UNIQUE NOT NULL,      -- 이메일 (중복 불가)
            password      VARCHAR(255)    NOT NULL,             -- 비밀번호 (해시값)
            phone_number  VARCHAR(20)     NOT NULL,             -- 전화번호
            birth_date    DATE,                                 -- 생년월일 (선택)
            department    VARCHAR(100),                         -- 부서 (인사팀 승인 후 지정)
            position      VARCHAR(100),                         -- 직급 (인사팀 승인 후 지정)
            nickname      VARCHAR(100),                         -- 닉네임
            is_verified   BOOLEAN         DEFAULT FALSE,        -- 사원 인증 여부
            is_active     BOOLEAN         DEFAULT FALSE,        -- 승인 전 비활성 상태
            created_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            verified_at   TIMESTAMPTZ                              -- 인사 승인(활성화) 시각
        )
        """,
    ),
]

INDEXES: list[tuple[str, str]] = [
    ("idx_info_employees_email", "CREATE INDEX IF NOT EXISTS idx_info_employees_email ON info_employees (email)"),
    ("idx_info_employees_dept", "CREATE INDEX IF NOT EXISTS idx_info_employees_dept ON info_employees (department)"),
    ("idx_info_employees_is_verified", "CREATE INDEX IF NOT EXISTS idx_info_employees_is_verified ON info_employees (is_verified)"),
]

TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$
"""

TRIGGERS: list[tuple[str, str]] = [
    (
        "trg_info_employees_updated_at",
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_info_employees_updated_at') THEN
                CREATE TRIGGER trg_info_employees_updated_at
                    BEFORE UPDATE ON info_employees
                    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$
        """,
    ),
]

def create_employee_db() -> None:
    print(f"[사원정보 DB] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

    conn = None
    try:
        conn = pg8000.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_DATABASE,
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT set_config('TimeZone', %s, false)", (APP_TIMEZONE,))
        cur.fetchone()

        # 1. 테이블 생성
        for table_name, ddl in TABLES:
            cur.execute(ddl)
            print(f" [OK] 테이블: {table_name}")

        # 2. 인덱스 생성
        for idx_name, ddl in INDEXES:
            cur.execute(ddl)
            print(f" [OK] 인덱스: {idx_name}")

        # 3. 트리거 설정
        cur.execute(TRIGGER_FUNCTION)
        for trig_name, ddl in TRIGGERS:
            cur.execute(ddl)
            print(f" [OK] 트리거: {trig_name}")

        print("\n[완료] 사원 정보 데이터베이스 생성이 완료되었습니다.")

    except Exception as e:
        print(f"\n[오류] 생성 실패: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    create_employee_db()