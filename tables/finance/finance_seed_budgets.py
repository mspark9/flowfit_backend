"""
finance_budgets 시드 데이터 스크립트
- 기존 데이터 전체 삭제 후 11개 부서 × 11개 계정과목 × 2025~2026년 데이터 재편성
- 실행: python -m tables.finance.finance_seed_budgets  (backend/ 디렉토리에서 실행)
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

# ── 계정 승인 화면과 동일한 11개 부서 ─────────────────────────
DEPARTMENTS = [
    "인사(HR)팀",
    "재무/회계팀",
    "법무/컴플라이언스팀",
    "총무/구매팀",
    "전략/기획팀",
    "영업/영업관리팀",
    "마케팅/PR팀",
    "CS/고객지원팀",
    "개발/IT운영팀",
    "QA/품질관리팀",
    "디자인/UX팀",
]

# ── 재무팀 계정과목 11종 ─────────────────────────────────────
ACCOUNT_CODES = [
    "접대비",
    "복리후생비",
    "소모품비",
    "여비교통비",
    "통신비",
    "도서인쇄비",
    "수수료비용",
    "광고선전비",
    "교육훈련비",
    "임차료",
    "기타비용",
]

# ── 부서별 연간 예산 기준 (단위: 원) ─────────────────────────
# 부서 성격에 맞게 계정과목별 비중을 다르게 편성
BUDGET_MATRIX: dict[str, dict[str, int]] = {
    "인사(HR)팀": {
        "접대비":    800_000,
        "복리후생비": 3_000_000,
        "소모품비":   500_000,
        "여비교통비": 600_000,
        "통신비":     300_000,
        "도서인쇄비": 400_000,
        "수수료비용": 1_200_000,
        "광고선전비": 500_000,
        "교육훈련비": 2_000_000,
        "임차료":     0,
        "기타비용":   500_000,
    },
    "재무/회계팀": {
        "접대비":    600_000,
        "복리후생비": 2_000_000,
        "소모품비":   400_000,
        "여비교통비": 500_000,
        "통신비":     300_000,
        "도서인쇄비": 600_000,
        "수수료비용": 3_000_000,
        "광고선전비": 0,
        "교육훈련비": 1_500_000,
        "임차료":     0,
        "기타비용":   400_000,
    },
    "법무/컴플라이언스팀": {
        "접대비":    500_000,
        "복리후생비": 1_500_000,
        "소모품비":   300_000,
        "여비교통비": 800_000,
        "통신비":     200_000,
        "도서인쇄비": 1_000_000,
        "수수료비용": 5_000_000,
        "광고선전비": 0,
        "교육훈련비": 2_000_000,
        "임차료":     0,
        "기타비용":   500_000,
    },
    "총무/구매팀": {
        "접대비":    400_000,
        "복리후생비": 2_500_000,
        "소모품비":   3_000_000,
        "여비교통비": 800_000,
        "통신비":     500_000,
        "도서인쇄비": 300_000,
        "수수료비용": 1_000_000,
        "광고선전비": 0,
        "교육훈련비": 800_000,
        "임차료":     5_000_000,
        "기타비용":   1_000_000,
    },
    "전략/기획팀": {
        "접대비":    1_500_000,
        "복리후생비": 1_500_000,
        "소모품비":   300_000,
        "여비교통비": 1_200_000,
        "통신비":     300_000,
        "도서인쇄비": 800_000,
        "수수료비용": 2_000_000,
        "광고선전비": 500_000,
        "교육훈련비": 1_500_000,
        "임차료":     0,
        "기타비용":   600_000,
    },
    "영업/영업관리팀": {
        "접대비":    5_000_000,
        "복리후생비": 2_000_000,
        "소모품비":   500_000,
        "여비교통비": 3_000_000,
        "통신비":     800_000,
        "도서인쇄비": 200_000,
        "수수료비용": 1_500_000,
        "광고선전비": 2_000_000,
        "교육훈련비": 1_000_000,
        "임차료":     0,
        "기타비용":   800_000,
    },
    "마케팅/PR팀": {
        "접대비":    1_200_000,
        "복리후생비": 1_500_000,
        "소모품비":   400_000,
        "여비교통비": 1_000_000,
        "통신비":     500_000,
        "도서인쇄비": 800_000,
        "수수료비용": 2_000_000,
        "광고선전비": 10_000_000,
        "교육훈련비": 1_000_000,
        "임차료":     0,
        "기타비용":   800_000,
    },
    "CS/고객지원팀": {
        "접대비":    300_000,
        "복리후생비": 2_000_000,
        "소모품비":   600_000,
        "여비교통비": 400_000,
        "통신비":     1_500_000,
        "도서인쇄비": 300_000,
        "수수료비용": 800_000,
        "광고선전비": 500_000,
        "교육훈련비": 1_200_000,
        "임차료":     0,
        "기타비용":   500_000,
    },
    "개발/IT운영팀": {
        "접대비":    300_000,
        "복리후생비": 2_500_000,
        "소모품비":   1_000_000,
        "여비교통비": 600_000,
        "통신비":     2_000_000,
        "도서인쇄비": 800_000,
        "수수료비용": 5_000_000,
        "광고선전비": 0,
        "교육훈련비": 3_000_000,
        "임차료":     0,
        "기타비용":   1_000_000,
    },
    "QA/품질관리팀": {
        "접대비":    200_000,
        "복리후생비": 1_500_000,
        "소모품비":   500_000,
        "여비교통비": 400_000,
        "통신비":     500_000,
        "도서인쇄비": 400_000,
        "수수료비용": 1_000_000,
        "광고선전비": 0,
        "교육훈련비": 2_000_000,
        "임차료":     0,
        "기타비용":   400_000,
    },
    "디자인/UX팀": {
        "접대비":    300_000,
        "복리후생비": 1_500_000,
        "소모품비":   800_000,
        "여비교통비": 500_000,
        "통신비":     400_000,
        "도서인쇄비": 600_000,
        "수수료비용": 1_500_000,
        "광고선전비": 1_000_000,
        "교육훈련비": 1_500_000,
        "임차료":     0,
        "기타비용":   500_000,
    },
}

FISCAL_YEARS = [2025, 2026]


def seed_budgets() -> None:
    print(f"[재무 예산 시드] 접속 중: {DB_HOST}:{DB_PORT}/{DB_DATABASE}")

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
        # ── 기존 데이터 전체 삭제 ──────────────────────────────
        cur.execute("DELETE FROM finance_budgets")
        print("  [OK] 기존 finance_budgets 데이터 삭제 완료")

        # ── 새 데이터 INSERT ──────────────────────────────────
        inserted = 0
        for year in FISCAL_YEARS:
            for dept in DEPARTMENTS:
                budgets = BUDGET_MATRIX.get(dept, {})
                for account_code in ACCOUNT_CODES:
                    amount = budgets.get(account_code, 0)
                    if amount == 0:
                        continue  # 예산 0은 저장하지 않음
                    cur.execute(
                        """
                        INSERT INTO finance_budgets
                            (fiscal_year, department, account_code, budget_amount)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (fiscal_year, department, account_code)
                        DO UPDATE SET budget_amount = EXCLUDED.budget_amount
                        """,
                        (year, dept, account_code, amount),
                    )
                    inserted += 1

        print(f"  [OK] {inserted}건 INSERT 완료 ({len(FISCAL_YEARS)}개 연도 × {len(DEPARTMENTS)}개 부서)")
        print("\n[완료] finance_budgets 시드 데이터 편성이 완료되었습니다.")

        # ── 요약 출력 ─────────────────────────────────────────
        cur.execute("SELECT fiscal_year, COUNT(*) FROM finance_budgets GROUP BY fiscal_year ORDER BY fiscal_year")
        rows = cur.fetchall()
        for row in rows:
            print(f"  {row[0]}년: {row[1]}건")

    except Exception as exc:
        print(f"\n[오류] 시드 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    seed_budgets()
