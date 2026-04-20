"""
재무 테스트 데이터 삽입 스크립트
실행: uv run python seed_finance.py
"""
from database import get_connection

SEED_TRANSACTIONS = [
    # 인사팀
    {"department": "인사팀",   "item": "임직원 식대 지원",      "amount": 280000,  "tax_amount": 28000,  "account_code": "복리후생비", "vendor": "구내식당",      "receipt_date": "2026-01-15", "ai_confidence": 96.5},
    {"department": "인사팀",   "item": "채용 공고 게재비",       "amount": 550000,  "tax_amount": 55000,  "account_code": "광고선전비", "vendor": "잡코리아",      "receipt_date": "2026-01-22", "ai_confidence": 91.2},
    {"department": "인사팀",   "item": "교육 훈련 세미나",       "amount": 1200000, "tax_amount": 120000, "account_code": "교육훈련비", "vendor": "HRD코리아",     "receipt_date": "2026-02-05", "ai_confidence": 88.7},
    {"department": "인사팀",   "item": "사무용품 구매",          "amount": 95000,   "tax_amount": 9500,   "account_code": "소모품비",   "vendor": "오피스디포",    "receipt_date": "2026-02-18", "ai_confidence": 99.1},
    {"department": "인사팀",   "item": "임직원 건강검진",        "amount": 3200000, "tax_amount": 0,      "account_code": "복리후생비", "vendor": "강남세브란스",  "receipt_date": "2026-03-10", "ai_confidence": 94.3},
    {"department": "인사팀",   "item": "노무 컨설팅 수수료",     "amount": 800000,  "tax_amount": 80000,  "account_code": "수수료비용", "vendor": "노무법인한울",  "receipt_date": "2026-03-25", "ai_confidence": 87.6},
    # 마케팅팀
    {"department": "마케팅팀", "item": "SNS 광고 집행",          "amount": 5000000, "tax_amount": 500000, "account_code": "광고선전비", "vendor": "메타코리아",    "receipt_date": "2026-01-08", "ai_confidence": 95.0},
    {"department": "마케팅팀", "item": "홍보물 인쇄",            "amount": 320000,  "tax_amount": 32000,  "account_code": "도서인쇄비", "vendor": "프린팅아이",    "receipt_date": "2026-01-20", "ai_confidence": 92.4},
    {"department": "마케팅팀", "item": "브랜드 콘텐츠 제작",     "amount": 2800000, "tax_amount": 280000, "account_code": "광고선전비", "vendor": "크리에이티브랩", "receipt_date": "2026-02-14", "ai_confidence": 89.8},
    {"department": "마케팅팀", "item": "전시회 참가비",          "amount": 1500000, "tax_amount": 150000, "account_code": "광고선전비", "vendor": "코엑스",        "receipt_date": "2026-02-28", "ai_confidence": 93.1},
    {"department": "마케팅팀", "item": "고객 설문 툴 구독료",    "amount": 450000,  "tax_amount": 45000,  "account_code": "수수료비용", "vendor": "서베이몽키",    "receipt_date": "2026-03-05", "ai_confidence": 97.2},
    {"department": "마케팅팀", "item": "인플루언서 마케팅",      "amount": 3500000, "tax_amount": 350000, "account_code": "광고선전비", "vendor": "인플루언서팀",  "receipt_date": "2026-03-20", "ai_confidence": 85.5},
    # 개발팀
    {"department": "개발팀",   "item": "AWS 클라우드 이용료",    "amount": 4200000, "tax_amount": 420000, "account_code": "임차료",     "vendor": "Amazon AWS",    "receipt_date": "2026-01-31", "ai_confidence": 98.9},
    {"department": "개발팀",   "item": "GitHub Enterprise 구독", "amount": 890000,  "tax_amount": 89000,  "account_code": "수수료비용", "vendor": "GitHub Inc.",   "receipt_date": "2026-01-15", "ai_confidence": 99.0},
    {"department": "개발팀",   "item": "개발 장비 구매(모니터)", "amount": 2100000, "tax_amount": 210000, "account_code": "소모품비",   "vendor": "삼성전자",      "receipt_date": "2026-02-03", "ai_confidence": 90.5},
    {"department": "개발팀",   "item": "기술 세미나 참가",       "amount": 600000,  "tax_amount": 60000,  "account_code": "교육훈련비", "vendor": "AWS Summit",    "receipt_date": "2026-02-20", "ai_confidence": 88.3},
    {"department": "개발팀",   "item": "소프트웨어 라이선스",    "amount": 3800000, "tax_amount": 380000, "account_code": "수수료비용", "vendor": "JetBrains",     "receipt_date": "2026-03-01", "ai_confidence": 96.7},
    {"department": "개발팀",   "item": "보안 취약점 점검 용역",  "amount": 5500000, "tax_amount": 550000, "account_code": "수수료비용", "vendor": "시큐어웍스",    "receipt_date": "2026-03-18", "ai_confidence": 82.1},
    # 영업팀
    {"department": "영업팀",   "item": "고객사 접대 식사",       "amount": 480000,  "tax_amount": 48000,  "account_code": "접대비",     "vendor": "강남 한정식",   "receipt_date": "2026-01-12", "ai_confidence": 94.6},
    {"department": "영업팀",   "item": "출장 교통비(KTX)",        "amount": 125000,  "tax_amount": 0,      "account_code": "여비교통비", "vendor": "한국철도공사",  "receipt_date": "2026-01-19", "ai_confidence": 99.5},
    {"department": "영업팀",   "item": "고객 선물 구매",         "amount": 750000,  "tax_amount": 75000,  "account_code": "접대비",     "vendor": "신세계백화점",  "receipt_date": "2026-02-09", "ai_confidence": 91.8},
    {"department": "영업팀",   "item": "영업 활동 차량 주유비",  "amount": 220000,  "tax_amount": 0,      "account_code": "여비교통비", "vendor": "SK에너지",      "receipt_date": "2026-02-22", "ai_confidence": 97.3},
    {"department": "영업팀",   "item": "파트너사 골프 접대",     "amount": 980000,  "tax_amount": 98000,  "account_code": "접대비",     "vendor": "레이크힐스CC",  "receipt_date": "2026-03-08", "ai_confidence": 86.4},
    {"department": "영업팀",   "item": "영업 자료 인쇄",         "amount": 85000,   "tax_amount": 8500,   "account_code": "도서인쇄비", "vendor": "킨코스",        "receipt_date": "2026-03-22", "ai_confidence": 98.2},
    # 운영팀
    {"department": "운영팀",   "item": "사무실 소모품",          "amount": 180000,  "tax_amount": 18000,  "account_code": "소모품비",   "vendor": "이마트",        "receipt_date": "2026-01-06", "ai_confidence": 95.8},
    {"department": "운영팀",   "item": "건물 시설 보수 공사",    "amount": 3200000, "tax_amount": 320000, "account_code": "수수료비용", "vendor": "현대건설",      "receipt_date": "2026-01-25", "ai_confidence": 83.7},
    {"department": "운영팀",   "item": "복합기 임대료",          "amount": 250000,  "tax_amount": 25000,  "account_code": "임차료",     "vendor": "신도리코",      "receipt_date": "2026-02-01", "ai_confidence": 99.3},
    {"department": "운영팀",   "item": "인터넷/전화 통신비",     "amount": 320000,  "tax_amount": 32000,  "account_code": "통신비",     "vendor": "KT",            "receipt_date": "2026-02-28", "ai_confidence": 98.7},
    {"department": "운영팀",   "item": "청소 용역비",            "amount": 550000,  "tax_amount": 55000,  "account_code": "수수료비용", "vendor": "깨끗한나라",    "receipt_date": "2026-03-07", "ai_confidence": 92.0},
    {"department": "운영팀",   "item": "직원 간식 구매",         "amount": 150000,  "tax_amount": 15000,  "account_code": "복리후생비", "vendor": "GS25",          "receipt_date": "2026-03-28", "ai_confidence": 96.1},
]

SEED_BUDGETS = [
    (2026, "인사팀",   "복리후생비", 8000000),
    (2026, "인사팀",   "교육훈련비", 5000000),
    (2026, "인사팀",   "광고선전비", 3000000),
    (2026, "인사팀",   "소모품비",   1000000),
    (2026, "인사팀",   "수수료비용", 2000000),
    (2026, "마케팅팀", "광고선전비", 20000000),
    (2026, "마케팅팀", "수수료비용", 3000000),
    (2026, "마케팅팀", "도서인쇄비", 1000000),
    (2026, "개발팀",   "임차료",     15000000),
    (2026, "개발팀",   "수수료비용", 25000000),
    (2026, "개발팀",   "소모품비",   5000000),
    (2026, "개발팀",   "교육훈련비", 3000000),
    (2026, "영업팀",   "접대비",     5000000),
    (2026, "영업팀",   "여비교통비", 3000000),
    (2026, "영업팀",   "도서인쇄비", 500000),
    (2026, "운영팀",   "소모품비",   2000000),
    (2026, "운영팀",   "수수료비용", 6000000),
    (2026, "운영팀",   "임차료",     3000000),
    (2026, "운영팀",   "통신비",     1500000),
    (2026, "운영팀",   "복리후생비", 2000000),
]

def main():
    conn = get_connection()
    cur  = conn.cursor()

    ins_tx = 0
    for tx in SEED_TRANSACTIONS:
        cur.execute(
            "SELECT COUNT(*) FROM finance_transactions WHERE vendor=%s AND receipt_date=%s AND item=%s",
            (tx["vendor"], tx["receipt_date"], tx["item"]),
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                """
                INSERT INTO finance_transactions
                    (receipt_date, item, amount, tax_amount, account_code, department, vendor, ai_confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (tx["receipt_date"], tx["item"], tx["amount"], tx["tax_amount"],
                 tx["account_code"], tx["department"], tx["vendor"], tx["ai_confidence"]),
            )
            ins_tx += 1

    ins_bgt = 0
    for b in SEED_BUDGETS:
        cur.execute(
            """
            INSERT INTO finance_budgets (fiscal_year, department, account_code, budget_amount)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (fiscal_year, department, account_code) DO NOTHING
            """,
            b,
        )
        ins_bgt += 1

    cur.close()
    conn.close()
    print(f"transactions 삽입: {ins_tx}건")
    print(f"budgets 삽입: {ins_bgt}건")

if __name__ == "__main__":
    main()
