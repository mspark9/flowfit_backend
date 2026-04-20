"""
finance_transactions에 emp_id 컬럼 추가 마이그레이션
(department 컬럼은 최초 DDL에 이미 존재)
실행: python -m tables.finance.finance_migrate_add_emp_id  (backend/ 디렉토리에서)
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

MIGRATIONS = [
    (
        "emp_id 컬럼 추가",
        "ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS emp_id VARCHAR(50)",
    ),
    (
        "idx_finance_transactions_emp_id 인덱스",
        "CREATE INDEX IF NOT EXISTS idx_finance_transactions_emp_id ON finance_transactions (emp_id)",
    ),
]


def migrate() -> None:
    print(f"[마이그레이션] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")
    conn = pg8000.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=DB_DATABASE,
    )
    conn.autocommit = True
    cur = conn.cursor()
    try:
        for name, ddl in MIGRATIONS:
            cur.execute(ddl)
            print(f"  [OK] {name}")
        print("\n[완료] emp_id 마이그레이션이 완료됐습니다.")
    except Exception as e:
        print(f"\n[오류] 마이그레이션 실패: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    migrate()
