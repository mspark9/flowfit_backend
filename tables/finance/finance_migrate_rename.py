"""
재무팀 테이블 이름 마이그레이션 — transactions → finance_transactions 등
실행: python -m tables.finance.finance_migrate_rename  (backend/ 디렉토리에서 실행)
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

# (구 이름, 새 이름) — 의존성 순서 주의 (audit_logs → transactions 참조)
RENAMES = [
    ("audit_logs",   "finance_audit_logs"),
    ("transactions", "finance_transactions"),
    ("budgets",      "finance_budgets"),
]


def table_exists(cur, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
        (name,),
    )
    return cur.fetchone() is not None


def migrate() -> None:
    print(f"[마이그레이션] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

    conn = pg8000.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_DATABASE,
    )
    conn.autocommit = True
    cur = conn.cursor()

    try:
        for old_name, new_name in RENAMES:
            if not table_exists(cur, old_name):
                print(f"  [SKIP] {old_name} 테이블 없음 (이미 마이그레이션 완료됐거나 미생성)")
                continue
            if table_exists(cur, new_name):
                print(f"  [SKIP] {new_name} 이미 존재")
                continue
            cur.execute(f"ALTER TABLE {old_name} RENAME TO {new_name}")
            print(f"  [OK] {old_name} → {new_name}")

        print("\n[완료] 마이그레이션이 완료됐습니다.")

    except Exception as e:
        print(f"\n[오류] 마이그레이션 실패: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    migrate()
