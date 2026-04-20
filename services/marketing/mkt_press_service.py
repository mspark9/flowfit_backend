"""
마케팅 보도자료 작성 서비스 — 신제품 · 이벤트 · 실적 유형별 자동 생성
"""
import json
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

# ── 유형별 구조 프리셋 ────────────────────────────────────────

STRUCTURE_MAP = {
    "신제품": "헤드라인 → 리드(첫 문단) → 제품 상세 → 임원 인용 → 가용성·가격 → 회사 소개",
    "이벤트": "헤드라인 → 리드(첫 문단) → 이벤트 개요 → 일정·장소 → 참여 방법 → 문의처",
    "실적":   "헤드라인 → 리드(첫 문단) → 핵심 수치 → 성장 배경 → 임원 코멘트 → 전망 → 투자자 주의문",
}

PRESS_PROMPT = """
당신은 전문 PR 작가입니다.
아래 정보를 바탕으로 언론사 배포용 보도자료를 작성하세요.

유형: {press_type}
핵심 팩트: {facts}
인용구 주체: {quote_person}
배포 대상 매체: {media_type}
구조 프리셋: {structure}

작성 규칙:
- 언론사 표준 역피라미드 구조를 따르세요.
- 리드 문단에 육하원칙(누가·언제·어디서·무엇을·어떻게·왜)을 포함하세요.
- 임원 인용구는 직접 화법으로 작성하세요.
- 문체는 객관적·공식적으로 작성하세요.

JSON으로만 응답하세요:
{{
  "headline": "보도자료 헤드라인",
  "release_date": "배포일 (오늘 날짜 기준)",
  "body": "보도자료 전문 (단락 구분은 \\n\\n 사용)",
  "quote": "임원 인용구 초안 (큰따옴표 포함)",
  "email_subject": "배포 이메일 제목",
  "email_body": "배포 이메일 본문 (기자 대상, 3~4문장)",
  "sns_linkedin": "링크드인용 요약 발표문 (3~4문장, 공식적 어조)",
  "sns_x": "X(트위터)용 요약 발표문 (140자 이내)"
}}
"""


def generate_press(
    press_type: str,
    facts: str,
    quote_person: str,
    media_type: str,
) -> dict:
    """
    보도자료 전문 + 이메일 초안 + SNS 요약문을 생성합니다.

    Args:
        press_type:   '신제품' | '이벤트' | '실적'
        facts:        핵심 팩트 (출시일, 가격, 주요 수치 등)
        quote_person: 인용구 주체 (CEO 이름·직책 등)
        media_type:   'IT' | '경제' | '생활'

    Returns:
        {
          headline, release_date, body, quote,
          email_subject, email_body,
          sns_linkedin, sns_x
        }
    """
    structure = STRUCTURE_MAP.get(press_type, STRUCTURE_MAP["신제품"])

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": PRESS_PROMPT.format(
                press_type=press_type,
                facts=facts,
                quote_person=quote_person or "대표이사",
                media_type=media_type,
                structure=structure,
            ),
        }],
        max_tokens=1500,
    )

    return json.loads(res.choices[0].message.content)
