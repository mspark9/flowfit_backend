"""
기존 DB에 info_employees.verified_at 컬럼 추가 및 기존 승인 계정 백필.

백엔드 프로젝트 루트에서 실행:
  python tables/Employee_List/migrate_add_verified_at.py
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


def main() -> None:
    print(f"[migrate verified_at] 접속: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")
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
        cur.execute(
            """
            ALTER TABLE info_employees
            ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ
            """
        )
        cur.execute(
            """
            UPDATE info_employees
               SET verified_at = updated_at
             WHERE is_verified = TRUE
               AND verified_at IS NULL
            """
        )
        print(" [OK] 기존 승인 계정에 verified_at 백필 완료")
    finally:
        cur.close()
        conn.close()
    print("[완료] migrate_add_verified_at")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)
