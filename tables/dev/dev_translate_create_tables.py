"""
기술 용어 번역기 — 용어 통계 테이블 생성 스크립트
실행: python -m tables.dev.dev_translate_create_tables  (backend/ 디렉토리에서)
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

TABLES = [
    (
        "dev_translate_terms",
        """
        CREATE TABLE IF NOT EXISTS dev_translate_terms (
            id           SERIAL          PRIMARY KEY,
            term         VARCHAR(200)    NOT NULL,
            category     VARCHAR(50)     NOT NULL DEFAULT '개발',
            explanation  TEXT            NOT NULL DEFAULT '',
            analogy      TEXT            NOT NULL DEFAULT '',
            search_count INTEGER         NOT NULL DEFAULT 1,
            is_pinned    BOOLEAN         NOT NULL DEFAULT FALSE,
            auto_pinned  BOOLEAN         NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_dev_translate_terms_term UNIQUE (term)
        )
        """,
    ),
]

INDEXES = [
    (
        "idx_dev_translate_terms_pinned",
        "CREATE INDEX IF NOT EXISTS idx_dev_translate_terms_pinned "
        "ON dev_translate_terms (is_pinned, auto_pinned)",
    ),
    (
        "idx_dev_translate_terms_count",
        "CREATE INDEX IF NOT EXISTS idx_dev_translate_terms_count "
        "ON dev_translate_terms (search_count DESC)",
    ),
]


def create_tables() -> None:
    print(f"[기술 용어 번역기 DB] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

    conn = pg8000.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
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
        print("\n[완료] dev_translate_terms 테이블이 정상적으로 생성되었습니다.")
    except Exception as exc:
        print(f"\n[오류] 테이블 생성 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_tables()
