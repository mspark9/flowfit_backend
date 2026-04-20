"""
재무팀 계정과목 추천 서비스 — 가맹점명·비고로 gpt-4o-mini가 계정과목 분류
"""
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

ACCOUNT_CODES = [
    '접대비', '복리후생비', '소모품비', '여비교통비', '통신비',
    '도서인쇄비', '수수료비용', '광고선전비', '교육훈련비', '임차료', '기타비용',
]


def suggest_account_code(vendor: str, notes: str) -> str:
    """
    가맹점명과 지출 내역을 바탕으로 가장 적절한 계정과목을 반환합니다.

    Args:
        vendor: 가맹점명
        notes:  지출내역/비고

    Returns:
        계정과목 문자열 (ACCOUNT_CODES 목록 중 하나)
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 ERP 회계 전문가입니다. "
                    "가맹점명과 지출 내역을 보고 아래 목록 중 가장 적절한 계정과목 하나만 반환하세요. "
                    "다른 텍스트나 설명 없이 계정과목명만 반환하세요.\n\n"
                    f"목록: {', '.join(ACCOUNT_CODES)}"
                ),
            },
            {
                "role": "user",
                "content": f"가맹점명: {vendor or '(없음)'}\n지출내역/비고: {notes or '(없음)'}",
            },
        ],
        max_tokens=20,
        temperature=0,
    )
    code = response.choices[0].message.content.strip()
    return code if code in ACCOUNT_CODES else '기타비용'
