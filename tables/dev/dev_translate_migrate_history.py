"""
기술 용어 번역기 — 번역 이력 테이블 추가 마이그레이션
실행: python -m tables.dev.dev_translate_migrate_history  (backend/ 디렉토리에서)
"""
import sys
import os
import pg8000.dbapi as pg8000
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

DB_HOST      = os.environ["DB_HOST"]
DB_PORT      = int(os.environ.get("DB_PORT", 5432))
DB_USER      = os.environ["DB_USER"]
DB_PASSWORD  = os.environ["DB_PASSWORD"]
DB_DATABASE  = os.environ["DB_DATABASE"]
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")

TABLES = [
    (
        "dev_translate_history",
        """
        CREATE TABLE IF NOT EXISTS dev_translate_history (
            id            SERIAL        PRIMARY KEY,
            text_preview  VARCHAR(150)  NOT NULL,
            audience      VARCHAR(20)   NOT NULL DEFAULT 'general',
            term_count    SMALLINT      NOT NULL DEFAULT 0,
            pinned_applied SMALLINT     NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        )
        """,
    ),
]

INDEXES = [
    (
        "idx_dev_translate_history_created",
        "CREATE INDEX IF NOT EXISTS idx_dev_translate_history_created "
        "ON dev_translate_history (created_at DESC)",
    ),
    (
        "idx_dev_translate_history_audience",
        "CREATE INDEX IF NOT EXISTS idx_dev_translate_history_audience "
        "ON dev_translate_history (audience, created_at DESC)",
    ),
]


def migrate() -> None:
    print(f"[번역 이력 마이그레이션] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")
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
        print("\n[완료] dev_translate_history 테이블이 생성되었습니다.")
    except Exception as exc:
        print(f"\n[오류] 마이그레이션 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    migrate()
