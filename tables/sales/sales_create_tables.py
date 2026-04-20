"""
영업(sales) 모듈 테이블 생성 스크립트.

실행: (backend/ 디렉토리에서)
    python -m tables.sales.sales_create_tables
    # 또는 uv 환경:
    uv run python -m tables.sales.sales_create_tables

실적 관련 정규화 3 테이블:
    1) sales_period_summary      — 기간 단위 요약 (1행/기간)
    2) sales_pipeline_stages     — 기간별 파이프라인 단계 (N행/기간)
    3) sales_member_performance  — 기간별 팀원 실적 (N행/기간)

제안서 RAG 테이블:
    4) sales_proposal_documents  — 성공 사례 문서 메타 (업종 필터)
    5) sales_proposal_chunks     — 청크 + OpenAI 임베딩 벡터

ON DELETE CASCADE로 '기간 덮어쓰기' / '문서 삭제' 시 하위 행을 한 번에 정리합니다.
"""
import os
import pg8000.dbapi as pg8000
from dotenv import load_dotenv

# backend/.env 로드
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(_env_path)

DB_HOST     = os.environ["DB_HOST"]
DB_PORT     = int(os.environ.get("DB_PORT", 5432))
DB_USER     = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_DATABASE = os.environ["DB_DATABASE"]

TABLES: list[tuple[str, str]] = [
    (
        "sales_period_summary",
        """
        CREATE TABLE IF NOT EXISTS sales_period_summary (
            period_key       VARCHAR(20)  PRIMARY KEY,                -- '2026-04' | '2026-Q1' | '2026-FY'
            period_label     VARCHAR(100) NOT NULL,                   -- UI 표시용 (예: '2026년 4월')
            period_type      VARCHAR(10)  NOT NULL,                   -- 'month' | 'quarter' | 'year'
            start_date       DATE         NOT NULL,
            end_date         DATE         NOT NULL,
            target_revenue   BIGINT       NOT NULL,
            actual_revenue   BIGINT       NOT NULL,
            prev_revenue     BIGINT       NOT NULL DEFAULT 0,
            deal_count       INTEGER      NOT NULL DEFAULT 0,
            win_count        INTEGER      NOT NULL DEFAULT 0,
            note             TEXT,                                    -- 비고 (선택)
            created_by       VARCHAR(50),                             -- 등록 사원 employee_id
            created_by_name  VARCHAR(100),                            -- 등록 사원 이름
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CHECK (period_type IN ('month','quarter','year'))
        )
        """,
    ),
    (
        "sales_pipeline_stages",
        """
        CREATE TABLE IF NOT EXISTS sales_pipeline_stages (
            id            SERIAL       PRIMARY KEY,
            period_key    VARCHAR(20)  NOT NULL REFERENCES sales_period_summary(period_key) ON DELETE CASCADE,
            stage_order   SMALLINT     NOT NULL,
            stage_name    VARCHAR(50)  NOT NULL,
            stage_count   INTEGER      NOT NULL DEFAULT 0,
            stage_amount  BIGINT       NOT NULL DEFAULT 0,
            UNIQUE (period_key, stage_order)
        )
        """,
    ),
    (
        "sales_member_performance",
        """
        CREATE TABLE IF NOT EXISTS sales_member_performance (
            id           SERIAL       PRIMARY KEY,
            period_key   VARCHAR(20)  NOT NULL REFERENCES sales_period_summary(period_key) ON DELETE CASCADE,
            member_name  VARCHAR(50)  NOT NULL,
            revenue      BIGINT       NOT NULL DEFAULT 0,
            deals        INTEGER      NOT NULL DEFAULT 0,
            wins         INTEGER      NOT NULL DEFAULT 0,
            UNIQUE (period_key, member_name)
        )
        """,
    ),
    (
        "sales_proposal_documents",
        """
        CREATE TABLE IF NOT EXISTS sales_proposal_documents (
            id                      SERIAL       PRIMARY KEY,
            industry                VARCHAR(30)  NOT NULL,   -- '제조업' | '유통·서비스' | 'IT'
            file_name               VARCHAR(255) NOT NULL,
            file_type               VARCHAR(20)  NOT NULL,
            file_bytes              BYTEA        NOT NULL,
            text_content            TEXT         NOT NULL,
            text_length             INTEGER      NOT NULL,
            preview                 TEXT,
            uploaded_by_employee_id VARCHAR(50),
            uploaded_by_name        VARCHAR(100),
            uploaded_by_department  VARCHAR(100),
            is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            deleted_at              TIMESTAMPTZ,
            CHECK (industry IN ('제조업','유통·서비스','IT'))
        )
        """,
    ),
    (
        "sales_proposal_chunks",
        """
        CREATE TABLE IF NOT EXISTS sales_proposal_chunks (
            id          SERIAL  PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES sales_proposal_documents(id) ON DELETE CASCADE,
            industry    VARCHAR(30)  NOT NULL,
            file_name   VARCHAR(255) NOT NULL,
            chunk_index INTEGER      NOT NULL,
            chunk_text  TEXT         NOT NULL,
            embedding   REAL[]       NOT NULL,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
        """,
    ),
]

INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_sales_period_summary_period_type ON sales_period_summary (period_type)",
    "CREATE INDEX IF NOT EXISTS idx_sales_period_summary_start_date  ON sales_period_summary (start_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sales_pipeline_stages_period     ON sales_pipeline_stages (period_key)",
    "CREATE INDEX IF NOT EXISTS idx_sales_member_performance_period  ON sales_member_performance (period_key)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_docs_active       ON sales_proposal_documents (is_active, deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_docs_industry     ON sales_proposal_documents (industry)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_docs_created_at   ON sales_proposal_documents (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_chunks_doc        ON sales_proposal_chunks (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_chunks_industry   ON sales_proposal_chunks (industry)",
]

# updated_at 자동 갱신 트리거
TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_sales_period_summary_updated_at') THEN
        CREATE TRIGGER trg_sales_period_summary_updated_at
        BEFORE UPDATE ON sales_period_summary
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
"""


def main() -> None:
    conn = pg8000.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD, database=DB_DATABASE,
    )
    conn.autocommit = True
    cur = conn.cursor()

    for name, ddl in TABLES:
        print(f"[sales] CREATE TABLE IF NOT EXISTS {name} ...")
        cur.execute(ddl)

    for idx_sql in INDEXES:
        cur.execute(idx_sql)

    cur.execute(TRIGGER_SQL)

    cur.close()
    conn.close()
    print("[sales] 테이블 생성 완료")


if __name__ == "__main__":
    main()
