"""
HR 인사 평가 테이블 생성 스크립트
실행: python -m tables.HR.hr_evaluation_create_tables  (backend/ 디렉토리에서 실행)
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
        "hr_eval_periods",
        """
        CREATE TABLE IF NOT EXISTS hr_eval_periods (
            eval_key        VARCHAR(30)     PRIMARY KEY,
            eval_label      VARCHAR(100)    NOT NULL,
            eval_type       VARCHAR(10)     NOT NULL,
            start_date      DATE            NOT NULL,
            end_date        DATE            NOT NULL,
            department      VARCHAR(100),
            status          VARCHAR(20)     NOT NULL DEFAULT 'draft',
            criteria_config JSONB,
            created_by      VARCHAR(50),
            created_by_name VARCHAR(100),
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            CHECK (eval_type IN ('quarter','half','year')),
            CHECK (status IN ('draft','completed'))
        )
        """,
    ),
    (
        "hr_eval_departments",
        """
        CREATE TABLE IF NOT EXISTS hr_eval_departments (
            id                    SERIAL       PRIMARY KEY,
            eval_key              VARCHAR(30)  NOT NULL REFERENCES hr_eval_periods(eval_key) ON DELETE CASCADE,
            department            VARCHAR(100) NOT NULL,
            budget_total          BIGINT       DEFAULT 0,
            budget_spent          BIGINT       DEFAULT 0,
            budget_execution_rate NUMERIC(5,1) DEFAULT 0,
            sales_revenue         BIGINT       DEFAULT 0,
            sales_deals           INTEGER      DEFAULT 0,
            sales_wins            INTEGER      DEFAULT 0,
            target_achievement    NUMERIC(5,1) DEFAULT 0,
            project_completion    NUMERIC(5,1) DEFAULT 0,
            collaboration_score   NUMERIC(5,1) DEFAULT 0,
            headcount             INTEGER      DEFAULT 0,
            UNIQUE (eval_key, department)
        )
        """,
    ),
    (
        "hr_team_evaluations",
        """
        CREATE TABLE IF NOT EXISTS hr_team_evaluations (
            id                   SERIAL       PRIMARY KEY,
            evaluator_id         VARCHAR(50)  NOT NULL,
            evaluator_name       VARCHAR(100) NOT NULL,
            evaluator_department VARCHAR(100) NOT NULL,
            target_id            VARCHAR(50),
            target_name          VARCHAR(100) NOT NULL,
            target_department    VARCHAR(100) NOT NULL,
            target_position      VARCHAR(100),
            eval_year            INTEGER      NOT NULL,
            eval_quarter         INTEGER      NOT NULL,
            work_score           NUMERIC(5,1) DEFAULT 0,
            leadership_score     NUMERIC(5,1) DEFAULT 0,
            expertise_score      NUMERIC(5,1) DEFAULT 0,
            collaboration_score  NUMERIC(5,1) DEFAULT 0,
            comment              TEXT,
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE (evaluator_id, target_name, eval_year, eval_quarter)
        )
        """,
    ),
    (
        "hr_eval_individuals",
        """
        CREATE TABLE IF NOT EXISTS hr_eval_individuals (
            id                   SERIAL       PRIMARY KEY,
            eval_key             VARCHAR(30)  NOT NULL REFERENCES hr_eval_periods(eval_key) ON DELETE CASCADE,
            employee_id          VARCHAR(50),
            employee_name        VARCHAR(100) NOT NULL,
            department           VARCHAR(100) NOT NULL,
            position             VARCHAR(100),
            sales_revenue        BIGINT       DEFAULT 0,
            sales_wins           INTEGER      DEFAULT 0,
            evaluate_a1          NUMERIC(6,1) DEFAULT 0,
            evaluate_a2          NUMERIC(6,1) DEFAULT 0,
            evaluate_a3          NUMERIC(6,1) DEFAULT 0,
            evaluate_a4          NUMERIC(6,1) DEFAULT 0,
            evaluate_a5          NUMERIC(6,1) DEFAULT 0,
            evaluate_a6          NUMERIC(6,1) DEFAULT 0,
            evaluate_a7          NUMERIC(6,1) DEFAULT 0,
            evaluate_a8          NUMERIC(6,1) DEFAULT 0,
            overall_grade        VARCHAR(5),
            UNIQUE (eval_key, employee_name)
        )
        """,
    ),
]

# 기존 설치 환경에서 안전하게 새 컬럼으로 전환하기 위한 마이그레이션 SQL
MIGRATIONS = [
    # 평가 기간 테이블에 기준 설정 JSONB 추가
    "ALTER TABLE hr_eval_periods ADD COLUMN IF NOT EXISTS criteria_config JSONB",
    # 신규 평가 슬롯 a1~a8 추가
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a1 NUMERIC(6,1) DEFAULT 0",
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a2 NUMERIC(6,1) DEFAULT 0",
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a3 NUMERIC(6,1) DEFAULT 0",
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a4 NUMERIC(6,1) DEFAULT 0",
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a5 NUMERIC(6,1) DEFAULT 0",
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a6 NUMERIC(6,1) DEFAULT 0",
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a7 NUMERIC(6,1) DEFAULT 0",
    "ALTER TABLE hr_eval_individuals ADD COLUMN IF NOT EXISTS evaluate_a8 NUMERIC(6,1) DEFAULT 0",
    # 기존 데이터를 신규 슬롯으로 1회 복사 (a1=업무, a2=KPI, a3=리더십, a4=전문성, a5=협업)
    """
    UPDATE hr_eval_individuals
       SET evaluate_a1 = COALESCE(work_score, 0),
           evaluate_a2 = COALESCE(kpi_achievement, 0),
           evaluate_a3 = COALESCE(leadership_score, 0),
           evaluate_a4 = COALESCE(expertise_score, 0),
           evaluate_a5 = COALESCE(collaboration_score, 0)
     WHERE (evaluate_a1 = 0 AND evaluate_a2 = 0 AND evaluate_a3 = 0
            AND evaluate_a4 = 0 AND evaluate_a5 = 0)
       AND (COALESCE(work_score,0) > 0 OR COALESCE(kpi_achievement,0) > 0
            OR COALESCE(leadership_score,0) > 0 OR COALESCE(expertise_score,0) > 0
            OR COALESCE(collaboration_score,0) > 0)
    """,
    # 기존 컬럼 제거
    "ALTER TABLE hr_eval_individuals DROP COLUMN IF EXISTS work_score",
    "ALTER TABLE hr_eval_individuals DROP COLUMN IF EXISTS kpi_achievement",
    "ALTER TABLE hr_eval_individuals DROP COLUMN IF EXISTS leadership_score",
    "ALTER TABLE hr_eval_individuals DROP COLUMN IF EXISTS expertise_score",
    "ALTER TABLE hr_eval_individuals DROP COLUMN IF EXISTS collaboration_score",
]

INDEXES = [
    ("idx_hr_eval_periods_type", "CREATE INDEX IF NOT EXISTS idx_hr_eval_periods_type ON hr_eval_periods (eval_type, start_date DESC)"),
    ("idx_hr_eval_departments_key", "CREATE INDEX IF NOT EXISTS idx_hr_eval_departments_key ON hr_eval_departments (eval_key)"),
    ("idx_hr_team_eval_evaluator", "CREATE INDEX IF NOT EXISTS idx_hr_team_eval_evaluator ON hr_team_evaluations (evaluator_id, eval_year, eval_quarter)"),
    ("idx_hr_team_eval_target", "CREATE INDEX IF NOT EXISTS idx_hr_team_eval_target ON hr_team_evaluations (target_department, eval_year, eval_quarter)"),
    ("idx_hr_eval_individuals_key", "CREATE INDEX IF NOT EXISTS idx_hr_eval_individuals_key ON hr_eval_individuals (eval_key)"),
    ("idx_hr_eval_individuals_dept", "CREATE INDEX IF NOT EXISTS idx_hr_eval_individuals_dept ON hr_eval_individuals (eval_key, department)"),
]


def create_tables() -> None:
    print(f"[HR 인사평가 DB] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

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

        for ddl in MIGRATIONS:
            cur.execute(ddl)
        print(f"  [OK] 마이그레이션: evaluate_a1~a8 + criteria_config")

        for idx_name, ddl in INDEXES:
            cur.execute(ddl)
            print(f"  [OK] 인덱스: {idx_name}")

        print("\n[완료] HR 인사평가 테이블이 정상적으로 생성되었습니다.")
    except Exception as exc:
        print(f"\n[오류] 테이블 생성 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    create_tables()
