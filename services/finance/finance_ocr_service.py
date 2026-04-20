"""
재무팀 OCR 서비스 — 영수증 이미지를 분석해 ERP 호환 JSON 반환
"""
import base64
import json
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """
당신은 ERP 회계 전문 AI입니다. 영수증 이미지를 분석하여 아래 JSON 구조로만 응답하세요.
다른 텍스트 없이 JSON 객체만 반환하세요.

{
  "receipt_date": "YYYY-MM-DD",
  "vendor": "거래처명",
  "items": [
    {
      "item": "항목명",
      "amount": 공급가액(정수, 부가세 제외),
      "tax_amount": 부가세(정수, 없으면 0),
      "account_code": "계정과목",
      "memo": "적요(없으면 빈 문자열)",
      "confidence": 신뢰도(0.0~100.0 실수)
    }
  ]
}

계정과목 분류 기준:
- 식대·회식·음식 → 복리후생비
- 택시·버스·기차·주차 → 여비교통비
- 고객 접대·선물 → 접대비
- 사무용품·소모품 → 소모품비
- 통신·인터넷·전화 → 통신비
- 책·신문·인쇄물 → 도서인쇄비
- 수수료·용역 → 수수료비용
- 광고·홍보 → 광고선전비
- 교육·세미나 → 교육훈련비
- 임대료·리스 → 임차료
- 기타 → 기타비용

날짜가 불명확하면 오늘 날짜를 사용하세요.
부가세가 포함된 금액이면 공급가액과 부가세를 분리하세요(부가세율 10%).
"""


def analyze_receipt(file_bytes: bytes, content_type: str) -> dict:
    """
    영수증 파일을 OpenAI GPT-4o로 분석하여 ERP 구조 JSON 반환

    Args:
        file_bytes: 파일 바이너리
        content_type: MIME 타입 (image/jpeg, image/png, application/pdf 등)

    Returns:
        {receipt_date, vendor, items: [{item, amount, tax_amount, account_code, memo, confidence}]}
    """
    # PDF는 Vision이 직접 지원하지 않으므로 이미지 MIME으로 처리
    if content_type == "application/pdf":
        content_type = "image/png"

    b64 = base64.b64encode(file_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{b64}",
                            "detail": "high",
                        },
                    },
                    {"type": "text", "text": "이 영수증을 분석해 주세요."},
                ],
            },
        ],
        max_tokens=1500,
    )

    raw = response.choices[0].message.content
    return json.loads(raw)
