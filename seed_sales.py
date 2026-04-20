"""
영업 실적 시드 스크립트 — 개발/데모용

실행: (backend/ 디렉토리에서)
    python -m seed_sales

기존 하드코딩된 MOCK_CRM_DATA 3기간(월간/분기/연간)을 DB에 등록합니다.
이미 존재하는 period_key는 덮어쓰기 됩니다.

실제 운영 배포 시엔 실행하지 마세요. 사원이 '영업 실적 등록' 페이지에서
직접 데이터를 입력하는 것이 정상 경로입니다.
"""
from services.sales.sales_performance_entry_service import upsert_performance


def seed() -> None:
    # 1) 2026-04 월간
    upsert_performance(
        period_type="month",
        year=2026,
        value=4,
        target_revenue=250_000_000,
        actual_revenue=187_000_000,
        prev_revenue=220_000_000,
        deal_count=8,
        win_count=3,
        note="시드 데이터 — 2026년 4월 영업 실적",
        pipeline=[
            {"stage_order": 1, "stage_name": "잠재 고객",   "stage_count": 24, "stage_amount": 380_000_000},
            {"stage_order": 2, "stage_name": "니즈 분석",   "stage_count": 12, "stage_amount": 210_000_000},
            {"stage_order": 3, "stage_name": "제안서 발송", "stage_count": 8,  "stage_amount": 145_000_000},
            {"stage_order": 4, "stage_name": "협상 중",     "stage_count": 4,  "stage_amount": 87_000_000},
            {"stage_order": 5, "stage_name": "계약 완료",   "stage_count": 3,  "stage_amount": 52_000_000},
        ],
        members=[
            {"member_name": "김민준", "revenue": 89_000_000, "deals": 3, "wins": 2},
            {"member_name": "이수연", "revenue": 62_000_000, "deals": 2, "wins": 1},
            {"member_name": "박지호", "revenue": 24_000_000, "deals": 2, "wins": 0},
            {"member_name": "최예린", "revenue": 12_000_000, "deals": 1, "wins": 0},
        ],
        created_by="seed",
        created_by_name="시드 스크립트",
    )

    # 2) 2026-Q1 분기
    upsert_performance(
        period_type="quarter",
        year=2026,
        value=1,
        target_revenue=750_000_000,
        actual_revenue=682_000_000,
        prev_revenue=590_000_000,
        deal_count=31,
        win_count=14,
        note="시드 데이터 — 2026년 Q1 영업 실적",
        pipeline=[
            {"stage_order": 1, "stage_name": "잠재 고객",   "stage_count": 67, "stage_amount": 1_200_000_000},
            {"stage_order": 2, "stage_name": "니즈 분석",   "stage_count": 38, "stage_amount": 680_000_000},
            {"stage_order": 3, "stage_name": "제안서 발송", "stage_count": 21, "stage_amount": 420_000_000},
            {"stage_order": 4, "stage_name": "협상 중",     "stage_count": 11, "stage_amount": 198_000_000},
            {"stage_order": 5, "stage_name": "계약 완료",   "stage_count": 14, "stage_amount": 182_000_000},
        ],
        members=[
            {"member_name": "김민준", "revenue": 289_000_000, "deals": 12, "wins": 6},
            {"member_name": "이수연", "revenue": 220_000_000, "deals": 9,  "wins": 5},
            {"member_name": "박지호", "revenue": 102_000_000, "deals": 6,  "wins": 2},
            {"member_name": "최예린", "revenue": 71_000_000,  "deals": 4,  "wins": 1},
        ],
        created_by="seed",
        created_by_name="시드 스크립트",
    )

    # 3) 2026-FY 연간
    upsert_performance(
        period_type="year",
        year=2026,
        value=0,
        target_revenue=3_000_000_000,
        actual_revenue=869_000_000,
        prev_revenue=710_000_000,
        deal_count=39,
        win_count=17,
        note="시드 데이터 — 2026년 연간 영업 실적 (4/14 시점 누적)",
        pipeline=[
            {"stage_order": 1, "stage_name": "잠재 고객",   "stage_count": 89, "stage_amount": 1_580_000_000},
            {"stage_order": 2, "stage_name": "니즈 분석",   "stage_count": 50, "stage_amount": 890_000_000},
            {"stage_order": 3, "stage_name": "제안서 발송", "stage_count": 29, "stage_amount": 565_000_000},
            {"stage_order": 4, "stage_name": "협상 중",     "stage_count": 15, "stage_amount": 285_000_000},
            {"stage_order": 5, "stage_name": "계약 완료",   "stage_count": 17, "stage_amount": 234_000_000},
        ],
        members=[
            {"member_name": "김민준", "revenue": 378_000_000, "deals": 15, "wins": 8},
            {"member_name": "이수연", "revenue": 282_000_000, "deals": 11, "wins": 6},
            {"member_name": "박지호", "revenue": 126_000_000, "deals": 8,  "wins": 2},
            {"member_name": "최예린", "revenue": 83_000_000,  "deals": 5,  "wins": 1},
        ],
        created_by="seed",
        created_by_name="시드 스크립트",
    )

    print("[seed_sales] 3개 기간 시드 완료 — 2026-04, 2026-Q1, 2026-FY")


if __name__ == "__main__":
    seed()
