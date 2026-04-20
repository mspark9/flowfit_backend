"""
일련 3자리 표기를 001 시작 → 000 시작으로 바꾼 뒤, 기존 next_seq와 맞추기 위한 1회 마이그레이션.

이전 규칙: 발급 시 n = (UPDATE 후 seq) % 1000  → 첫 번째가 001
이후 규칙: n = (seq - 1) % 1000              → 첫 번째가 000

이미 발급 이력이 있으면 next_seq를 1 올려 두면, 다음 발급 일련이 예전과 동일한 순서로 이어집니다.
(next_seq=0 인 신규 DB는 건드리지 않음)

백엔드 프로젝트 루트에서 실행:
  python tables/Employee_List/migrate_serial_seq_zero_start.py
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


def main() -> None:
    print(f"[migrate serial_seq zero-start] 접속: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")
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
        cur.execute(
            """
            UPDATE hr_employee_serial_seq
               SET next_seq = next_seq + 1
             WHERE id = 1
               AND next_seq >= 1
            """
        )
        print(f" [OK] next_seq 조정 (영향 행: {cur.rowcount})")
    finally:
        cur.close()
        conn.close()
    print("[완료] migrate_serial_seq_zero_start")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)
