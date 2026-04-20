"""
HR 규정 문서 테이블 생성 스크립트
실행: python -m tables.HR.hr_create_tables  (backend/ 디렉토리에서 실행)
"""
import sys
import os
import pg8000.dbapi as pg8000
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_DATABASE = os.environ["DB_DATABASE"]
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")

TABLES = [
    (
        "hr_regulation_documents",
        """
        CREATE TABLE IF NOT EXISTS hr_regulation_documents (
            id                      SERIAL          PRIMARY KEY,
            file_name               VARCHAR(255)    NOT NULL,
            file_type               VARCHAR(20)     NOT NULL,
            text_content            TEXT            NOT NULL,
            text_length             INTEGER         NOT NULL,
            preview                 TEXT,
            uploaded_by_employee_id VARCHAR(50),
            uploaded_by_name        VARCHAR(100),
            uploaded_by_department  VARCHAR(100),
            is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            deleted_at              TIMESTAMPTZ
        )
        """,
    ),
    (
        "hr_notifications",
        """
        CREATE TABLE IF NOT EXISTS hr_notifications (
            id                SERIAL          PRIMARY KEY,
            notification_key  VARCHAR(255)    NOT NULL UNIQUE,
            source            VARCHAR(100)    NOT NULL,
            message           TEXT            NOT NULL,
            notification_type VARCHAR(50)     NOT NULL DEFAULT 'event',
            is_active         BOOLEAN         NOT NULL DEFAULT TRUE,
            read_at           TIMESTAMPTZ,
            created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "hr_hire_requests",
        """
        CREATE TABLE IF NOT EXISTS hr_hire_requests (
            id                           SERIAL          PRIMARY KEY,
            request_key                  VARCHAR(255)    NOT NULL UNIQUE,
            requester_employee_id        VARCHAR(50)     NOT NULL,
            requester_name               VARCHAR(100)    NOT NULL,
            request_department           VARCHAR(100)    NOT NULL,
            job_title                    VARCHAR(150)    NOT NULL,
            employment_type              VARCHAR(50)     NOT NULL,
            experience_level             VARCHAR(50)     NOT NULL,
            headcount                    INTEGER         NOT NULL,
            urgency                      VARCHAR(50)     NOT NULL,
            hiring_goal                  TEXT            NOT NULL,
            reason                       TEXT            NOT NULL,
            responsibilities             TEXT            NOT NULL,
            qualifications               TEXT            NOT NULL,
            preferred_qualifications     TEXT,
            status                       VARCHAR(50)     NOT NULL DEFAULT 'requested',
            generated_posting_at         TIMESTAMPTZ,
            created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
        """,
    ),
]

INDEXES = [
    ("idx_hr_reg_docs_active", "CREATE INDEX IF NOT EXISTS idx_hr_reg_docs_active ON hr_regulation_documents (is_active, deleted_at)"),
    ("idx_hr_reg_docs_created_at", "CREATE INDEX IF NOT EXISTS idx_hr_reg_docs_created_at ON hr_regulation_documents (created_at DESC)"),
    ("idx_hr_notifications_active_read", "CREATE INDEX IF NOT EXISTS idx_hr_notifications_active_read ON hr_notifications (is_active, read_at)"),
    ("idx_hr_notifications_created_at", "CREATE INDEX IF NOT EXISTS idx_hr_notifications_created_at ON hr_notifications (created_at DESC)"),
    ("idx_hr_hire_requests_created_at", "CREATE INDEX IF NOT EXISTS idx_hr_hire_requests_created_at ON hr_hire_requests (created_at DESC)"),
    ("idx_hr_hire_requests_department_status", "CREATE INDEX IF NOT EXISTS idx_hr_hire_requests_department_status ON hr_hire_requests (request_department, status)"),
]


def create_tables() -> None:
    print(f"[HR 규정 DB] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

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

    try:
        for table_name, ddl in TABLES:
            cur.execute(ddl)
            print(f"  [OK] 테이블: {table_name}")

        for idx_name, ddl in INDEXES:
            cur.execute(ddl)
            print(f"  [OK] 인덱스: {idx_name}")

        print("\n[완료] HR 관련 테이블이 정상적으로 생성되었습니다.")
    except Exception as exc:
        print(f"\n[오류] 테이블 생성 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_tables()
