"""
CS팀 테이블 생성 스크립트 — .env의 DB 정보로 PostgreSQL에 테이블을 생성합니다.
실행: python -m tables.CS.cs_create_tables  (backend/ 디렉토리에서 실행)
"""
import sys
import os
import pg8000.dbapi as pg8000
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

DB_HOST     = os.environ["DB_HOST"]
DB_PORT     = int(os.environ.get("DB_PORT", 5432))
DB_USER     = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_DATABASE = os.environ["DB_DATABASE"]
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")

# ────────────────────────────────────────────────────────────
# DDL 정의
# ────────────────────────────────────────────────────────────
TABLES: list[tuple[str, str]] = [
    (
        "cs_inquiries",
        """
        CREATE TABLE IF NOT EXISTS cs_inquiries (
            id                  SERIAL          PRIMARY KEY,
            inquiry_text        TEXT            NOT NULL,
            order_no            VARCHAR(100),
            tone                VARCHAR(20)     NOT NULL DEFAULT 'formal',
            main_type           VARCHAR(50),
            sub_type            VARCHAR(50),
            sentiment           VARCHAR(10),
            draft               TEXT,
            final_response      TEXT,
            escalation_needed   BOOLEAN         NOT NULL DEFAULT FALSE,
            escalation_reason   TEXT,
            status              VARCHAR(20)     NOT NULL DEFAULT '대기',
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "cs_faqs",
        """
        CREATE TABLE IF NOT EXISTS cs_faqs (
            id          SERIAL          PRIMARY KEY,
            category    VARCHAR(50)     NOT NULL,
            question    TEXT            NOT NULL,
            answer      TEXT            NOT NULL,
            flagged     BOOLEAN         NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
        """,
    ),
    (
        "cs_voc_reports",
        """
        CREATE TABLE IF NOT EXISTS cs_voc_reports (
            id              SERIAL          PRIMARY KEY,
            period          VARCHAR(50)     NOT NULL,
            total_count     INTEGER         NOT NULL,
            prev_count      INTEGER,
            sentiment_json  JSONB           NOT NULL,
            top_issues_json JSONB           NOT NULL,
            summary         TEXT            NOT NULL,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
        """,
    ),
]

INDEXES: list[tuple[str, str]] = [
    ("idx_cs_inquiries_main_type",   "CREATE INDEX IF NOT EXISTS idx_cs_inquiries_main_type   ON cs_inquiries (main_type)"),
    ("idx_cs_inquiries_sub_type",    "CREATE INDEX IF NOT EXISTS idx_cs_inquiries_sub_type    ON cs_inquiries (sub_type)"),
    ("idx_cs_inquiries_status",      "CREATE INDEX IF NOT EXISTS idx_cs_inquiries_status      ON cs_inquiries (status)"),
    ("idx_cs_inquiries_escalation",  "CREATE INDEX IF NOT EXISTS idx_cs_inquiries_escalation  ON cs_inquiries (escalation_needed)"),
    ("idx_cs_inquiries_created_at",  "CREATE INDEX IF NOT EXISTS idx_cs_inquiries_created_at  ON cs_inquiries (created_at)"),
    ("idx_cs_faqs_category",        "CREATE INDEX IF NOT EXISTS idx_cs_faqs_category        ON cs_faqs (category)"),
    ("idx_cs_faqs_flagged",         "CREATE INDEX IF NOT EXISTS idx_cs_faqs_flagged         ON cs_faqs (flagged)"),
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

# 기존 테이블에 컬럼이 없을 경우 추가 (멱등 마이그레이션)
MIGRATIONS: list[tuple[str, str]] = [
    ("cs_inquiries.main_type",      "ALTER TABLE cs_inquiries ADD COLUMN IF NOT EXISTS main_type       VARCHAR(50)"),
    ("cs_inquiries.sub_type",       "ALTER TABLE cs_inquiries ADD COLUMN IF NOT EXISTS sub_type        VARCHAR(50)"),
    ("cs_inquiries.sentiment",      "ALTER TABLE cs_inquiries ADD COLUMN IF NOT EXISTS sentiment       VARCHAR(10)"),
    ("cs_inquiries.final_response", "ALTER TABLE cs_inquiries ADD COLUMN IF NOT EXISTS final_response  TEXT"),
    ("cs_inquiries.status",         "ALTER TABLE cs_inquiries ADD COLUMN IF NOT EXISTS status          VARCHAR(20) NOT NULL DEFAULT '대기'"),
    ("cs_faqs.suggested_answer",    "ALTER TABLE cs_faqs ADD COLUMN IF NOT EXISTS suggested_answer     TEXT"),
]

TRIGGERS: list[tuple[str, str]] = [
    (
        "trg_cs_faqs_updated_at",
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_cs_faqs_updated_at') THEN
                CREATE TRIGGER trg_cs_faqs_updated_at
                    BEFORE UPDATE ON cs_faqs
                    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$
        """,
    ),
]


# ────────────────────────────────────────────────────────────
# 실행
# ────────────────────────────────────────────────────────────
def create_tables() -> None:
    print(f"[CS팀 DB] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

    conn = pg8000.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD, database=DB_DATABASE,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT set_config('TimeZone', %s, false)", (APP_TIMEZONE,))
    cur.fetchone()

    try:
        # 1. 테이블 생성
        for table_name, ddl in TABLES:
            cur.execute(ddl)
            print(f"  [OK] 테이블: {table_name}")

        # 2. 마이그레이션 (컬럼 추가)
        for col_name, ddl in MIGRATIONS:
            cur.execute(ddl)
            print(f"  [OK] 마이그레이션: {col_name}")

        for idx_name, ddl in INDEXES:
            cur.execute(ddl)
            print(f"  [OK] 인덱스: {idx_name}")

        cur.execute(TRIGGER_FUNCTION)
        print("  [OK] 함수: set_updated_at()")

        for trig_name, ddl in TRIGGERS:
            cur.execute(ddl)
            print(f"  [OK] 트리거: {trig_name}")

        print("\n[완료] CS팀 테이블이 정상적으로 생성되었습니다.")

    except Exception as e:
        print(f"\n[오류] 테이블 생성 실패: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_tables()
