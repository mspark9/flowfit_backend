"""
법무/컴플라이언스 테이블 생성 스크립트
실행: python -m tables.legal.legal_create_tables  (backend/ 디렉토리에서 실행)
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
        "legal_documents",
        """
        CREATE TABLE IF NOT EXISTS legal_documents (
            id                      SERIAL          PRIMARY KEY,
            file_name               VARCHAR(255)    NOT NULL,
            file_type               VARCHAR(20)     NOT NULL,
            file_bytes              BYTEA           NOT NULL,
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
        "legal_document_chunks",
        """
        CREATE TABLE IF NOT EXISTS legal_document_chunks (
            id          SERIAL      PRIMARY KEY,
            document_id INTEGER     NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
            file_name   VARCHAR(255) NOT NULL,
            chunk_index INTEGER      NOT NULL,
            chunk_text  TEXT         NOT NULL,
            embedding   REAL[]       NOT NULL,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
        """,
    ),
]

INDEXES = [
    ("idx_legal_docs_active",      "CREATE INDEX IF NOT EXISTS idx_legal_docs_active      ON legal_documents       (is_active, deleted_at)"),
    ("idx_legal_docs_created_at",  "CREATE INDEX IF NOT EXISTS idx_legal_docs_created_at  ON legal_documents       (created_at DESC)"),
    ("idx_legal_chunks_doc_id",    "CREATE INDEX IF NOT EXISTS idx_legal_chunks_doc_id    ON legal_document_chunks (document_id)"),
]


def create_tables() -> None:
    print(f"[법무 DB] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

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

        print("\n[완료] 법무/컴플라이언스 관련 테이블이 정상적으로 생성되었습니다.")
    except Exception as exc:
        print(f"\n[오류] 테이블 생성 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_tables()
