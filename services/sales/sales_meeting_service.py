"""
고객 미팅 요약 서비스 — 메모/녹취 텍스트 → 구조화 요약 + CRM 입력 초안
"""
import json
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

MEETING_PROMPT = """
당신은 영업 어시스턴트입니다.
아래 미팅 내용을 분석하여 구조화된 요약본과 CRM 입력 초안을 작성하세요.

고객사명: {company_name}
미팅 날짜: {meeting_date}
미팅 내용/메모:
{meeting_notes}

작성 규칙:
- 액션아이템은 담당자와 기한을 명확하게 작성하세요. (메모에 없으면 합리적으로 추론)
- 고객 우려사항은 솔직하게 기술하세요.
- CRM 입력 초안은 영업 기회 관리 스타일로 작성하세요.
- 메모에 없는 내용을 억지로 만들지 마세요.

JSON으로만 응답하세요:
{{
  "meeting_title": "미팅 제목 (고객사명 + 주제, 15자 이내)",
  "key_discussions": ["핵심 논의 1", "핵심 논의 2", "핵심 논의 3"],
  "customer_needs": ["고객 니즈 1", "고객 니즈 2"],
  "concerns": ["우려사항 1", "우려사항 2"],
  "action_items": [
    {{"owner": "담당자", "action": "할 일", "due": "기한"}},
    {{"owner": "담당자", "action": "할 일", "due": "기한"}}
  ],
  "next_agenda": ["다음 미팅 의제 1", "다음 미팅 의제 2"],
  "crm_draft": {{
    "opportunity_name": "영업 기회명",
    "stage": "리드 발굴 또는 니즈 분석 또는 제안서 발송 또는 협상 중 또는 계약 완료 중 하나",
    "next_step": "다음 단계 요약 (1문장)",
    "contact_role": "고객 담당자 역할 (있으면 기입, 없으면 빈 문자열)",
    "description": "미팅 요약 (CRM 설명란용, 3~4문장)"
  }}
}}
"""


def summarize_meeting(
    company_name: str,
    meeting_date: str,
    meeting_notes: str,
) -> dict:
    """
    미팅 메모/녹취 텍스트를 구조화하여 요약합니다.

    Args:
        company_name:  고객사명
        meeting_date:  미팅 날짜 (YYYY-MM-DD)
        meeting_notes: 미팅 내용/메모 (자유 형식)

    Returns:
        {
          meeting_title, key_discussions, customer_needs,
          concerns, action_items, next_agenda, crm_draft
        }
    """
    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": MEETING_PROMPT.format(
                company_name=company_name,
                meeting_date=meeting_date,
                meeting_notes=meeting_notes,
            ),
        }],
        max_tokens=1500,
    )

    return json.loads(res.choices[0].message.content)
