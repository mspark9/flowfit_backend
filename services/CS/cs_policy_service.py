"""
CS 정책 문서 분석 서비스 — docx 파싱 → FAQ 영향 분석 → 수정 초안 생성
의존: python-docx (uv add python-docx)
"""
import json
from io import BytesIO
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

POLICY_CHECK_PROMPT = """
다음은 CS 운영 정책 문서 전문입니다.

[정책 문서]
{policy_text}

아래는 현재 DB에 저장된 FAQ 목록입니다.
각 FAQ가 위 정책 내용과 불일치하거나 업데이트가 필요한지 분석하세요.

[FAQ 목록]
{faq_list}

분석 결과를 아래 JSON 형식으로만 반환하세요. 다른 텍스트 없이 JSON만 반환하세요.
needs_update가 false인 항목은 flagged 배열에 포함하지 마세요.

{{
  "flagged": [
    {{
      "faq_id": <정수>,
      "suggested_answer": "정책 기준에 맞게 수정된 답변 (2~4문장, CS 담당자 말투)",
      "reason": "수정이 필요한 이유 (1문장)"
    }}
  ]
}}
"""


def extract_policy_text(docx_bytes: bytes) -> str:
    """docx 바이너리에서 텍스트 추출"""
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx가 설치되지 않았습니다. uv add python-docx 실행 후 재시도하세요.")

    doc = Document(BytesIO(docx_bytes))
    lines = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def analyze_policy_impact(docx_bytes: bytes, faqs: list[dict]) -> list[dict]:
    """
    정책 문서와 FAQ 목록을 비교하여 수정이 필요한 FAQ와 수정 초안을 반환합니다.

    Args:
        docx_bytes: docx 파일 바이너리
        faqs: [{"id": int, "category": str, "question": str, "answer": str}, ...]

    Returns:
        [{"faq_id": int, "suggested_answer": str, "reason": str}, ...]
    """
    if not faqs:
        return []

    policy_text = extract_policy_text(docx_bytes)

    faq_list_str = "\n".join(
        f'- ID {f["id"]} [{f["category"]}] Q: {f["question"]} / A: {f["answer"]}'
        for f in faqs
    )

    prompt = POLICY_CHECK_PROMPT.format(
        policy_text=policy_text,
        faq_list=faq_list_str,
    )

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "당신은 CS 정책 분석 전문가입니다. 정책 문서와 FAQ를 비교하여 불일치 항목을 찾아 수정 초안을 작성합니다.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=3000,
    )

    raw = json.loads(res.choices[0].message.content)

    # {"flagged": [...]} 형태 또는 GPT가 다른 키를 쓸 경우 방어 처리
    if isinstance(raw, dict):
        flagged = raw.get("flagged") or raw.get("results") or raw.get("items") or []
        for v in raw.values():
            if isinstance(v, list):
                flagged = v
                break
    else:
        flagged = raw if isinstance(raw, list) else []

    return [
        {
            "faq_id":           item["faq_id"],
            "suggested_answer": item.get("suggested_answer", ""),
            "reason":           item.get("reason", ""),
        }
        for item in flagged
        if isinstance(item, dict) and item.get("faq_id")
    ]
