"""
CS 응답 초안 서비스 — 고객 문의 분류 + 정책 기반 응답 초안 생성
"""
import json
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

# ── 문의 유형 정의 ────────────────────────────────────────────
INQUIRY_TYPES = {
    "배송":    ["배송지연", "배송조회", "오배송", "배송지변경"],
    "반품/교환": ["반품신청", "교환신청", "반품진행상태", "교환진행상태"],
    "환불":    ["환불신청", "환불지연", "환불금액오류"],
    "결제":    ["결제오류", "중복결제", "결제수단변경", "현금영수증/세금계산서"],
    "상품":    ["상품불량", "상품정보문의", "재입고문의", "상품사용법"],
    "주문":    ["주문취소", "주문변경", "주문내역조회"],
    "회원/계정": ["회원가입", "로그인오류", "비밀번호분실", "회원탈퇴", "개인정보변경"],
    "혜택":    ["쿠폰/할인", "포인트", "멤버십", "이벤트"],
    "기타":    ["불편신고", "칭찬/제안", "기타문의"],
}

_TYPE_LIST = "\n".join(
    f'- "{main}": {" | ".join(f"{s}" for s in subs)}'
    for main, subs in INQUIRY_TYPES.items()
)

CLASSIFY_PROMPT = f"""
당신은 이커머스 CS 담당자 보조 AI입니다.
고객 문의 원문을 읽고 아래 JSON 구조로만 응답하세요. 다른 텍스트 없이 JSON만 반환하세요.

{{
  "main_type": "대분류",
  "sub_type":  "소분류",
  "escalation_needed": true | false,
  "escalation_reason": "에스컬레이션 필요 시 사유, 불필요하면 빈 문자열"
}}

문의 유형 목록 (대분류: 소분류들):
{_TYPE_LIST}

에스컬레이션 기준:
- 고객이 법적 조치 언급 (소송, 신고, 공정거래위원회 등)
- 심각한 신체·재산 피해 주장
- 반복 미해결로 극도로 감정적인 문의
- 담당자 권한 밖의 환불액 (30만원 초과)
"""

DRAFT_PROMPT = """
당신은 테크원(TechOne) CS 담당자입니다.
주어진 고객 문의에 대해 아래 조건에 맞는 응답 초안을 작성하세요.

조건:
- 어조: {tone}
- 문의 유형: {main_type} > {sub_type}
- 첫 줄은 고객 인사, 마지막 줄은 담당자 서명으로 마무리
- 구체적인 처리 절차나 기한을 포함하되 확정되지 않은 정보는 "[확인 필요]"로 표시
- 길이: 150~300자 이내

고객 문의:
{inquiry}

주문번호: {order_no}

응답 초안만 작성하세요 (JSON 불필요).
"""

TONE_MAP = {
    "formal":   "공식체 (격식 있고 정중하게)",
    "friendly": "친근체 (따뜻하고 부드럽게)",
}


def classify_and_draft(inquiry: str, order_no: str, tone: str) -> dict:
    """
    고객 문의를 분류하고 응답 초안을 생성합니다.

    Args:
        inquiry:  고객 문의 원문
        order_no: 주문번호 (없으면 빈 문자열)
        tone:     어조 ("formal" | "friendly")

    Returns:
        {
          "main_type": str,
          "sub_type":  str,
          "draft":     str,
          "escalation": {"needed": bool, "reason": str}
        }
    """
    # 1단계: 문의 유형 분류 + 에스컬레이션 판단
    classify_res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user",   "content": inquiry},
        ],
        max_tokens=200,
    )
    classify_data = json.loads(classify_res.choices[0].message.content)
    main_type = classify_data.get("main_type", "기타")
    sub_type  = classify_data.get("sub_type",  "기타문의")

    # 2단계: 응답 초안 생성
    draft_prompt = DRAFT_PROMPT.format(
        tone=TONE_MAP.get(tone, TONE_MAP["formal"]),
        main_type=main_type,
        sub_type=sub_type,
        inquiry=inquiry,
        order_no=order_no if order_no else "미제공",
    )
    draft_res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": draft_prompt},
        ],
        max_tokens=600,
    )
    draft = draft_res.choices[0].message.content.strip()

    return {
        "main_type": main_type,
        "sub_type":  sub_type,
        "draft":     draft,
        "escalation": {
            "needed": classify_data.get("escalation_needed", False),
            "reason": classify_data.get("escalation_reason", ""),
        },
    }
