"""
hr_account_decision_log 테이블 생성 및 기존 승인 계정 백필.

백엔드 프로젝트 루트에서:
  python tables/Employee_List/migrate_account_decision_log.py
"""
import os
import sys

import pg8000.dbapi as pg8000
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.environ.get("DB_HOST")
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_DATABASE = os.environ.get("DB_DATABASE")
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")


DDL = """
CREATE TABLE IF NOT EXISTS hr_account_decision_log (
    id SERIAL PRIMARY KEY,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action VARCHAR(20) NOT NULL,
    employee_id VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    department VARCHAR(100),
    position VARCHAR(100),
    registered_at TIMESTAMPTZ,
    reason TEXT,
    CONSTRAINT chk_hr_acct_action CHECK (action IN ('approved', 'rejected'))
);
CREATE INDEX IF NOT EXISTS idx_hr_acct_decision_at ON hr_account_decision_log (decided_at DESC);
"""

ALTER_REASON = """
ALTER TABLE hr_account_decision_log ADD COLUMN IF NOT EXISTS reason TEXT;
"""

BACKFILL = """
INSERT INTO hr_account_decision_log (
    decided_at, action, employee_id, name, email, department, position, registered_at, reason
)
SELECT
    COALESCE(e.verified_at, e.updated_at),
    'approved',
    e.employee_id,
    e.name,
    e.email,
    e.department,
    e.position,
    e.created_at,
    NULL
FROM info_employees e
WHERE e.is_verified = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM hr_account_decision_log h
    WHERE h.employee_id = e.employee_id AND h.action = 'approved'
  );
"""


def main() -> None:
    print(f"[migrate account_decision_log] 접속: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")
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
        cur.execute("SELECT set_config('TimeZone', %s, false)", (APP_TIMEZONE,))
        cur.fetchone()
        for stmt in DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        cur.execute(ALTER_REASON.strip())
        print(" [OK] 테이블 hr_account_decision_log 준비")
        cur.execute(BACKFILL)
        print(" [OK] 기존 승인 계정 백필 완료")
    finally:
        cur.close()
        conn.close()
    print("[완료] migrate_account_decision_log")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)
