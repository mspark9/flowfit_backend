"""
마케팅 카피라이팅 생성 서비스
"""
import json
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

COPY_PROMPT = """
당신은 전문 브랜드 카피라이터입니다.
아래 정보를 바탕으로 광고 카피를 A/B/C 3가지 버전으로 생성하세요.

제품명: {product_name}
핵심 특장점: {features}
캠페인 목표: {goal}
타겟 페르소나: {persona}
채널: {channel}
톤앤매너: {tone}

각 버전은 서로 다른 스타일로 작성하세요.
- A버전: 임팩트형 (강렬하고 간결, 기억에 남는 한 문장)
- B버전: 공감형 (고객의 감정과 일상에 공감, 따뜻한 어조)
- C버전: 기능형 (핵심 수치와 스펙 중심, 논리적 설득)

JSON으로만 응답하세요:
{{
  "versions": [
    {{"label": "A", "style": "임팩트형", "headline": "...", "subcopy": "...", "cta": "..."}},
    {{"label": "B", "style": "공감형",   "headline": "...", "subcopy": "...", "cta": "..."}},
    {{"label": "C", "style": "기능형",   "headline": "...", "subcopy": "...", "cta": "..."}}
  ],
  "slogans": ["슬로건1", "슬로건2", "슬로건3", "슬로건4", "슬로건5"],
  "banner": "배너·옥외광고용 15자 이내 축약 문구"
}}
"""


def generate_copy(
    product_name: str,
    features: str,
    goal: str,
    persona: str,
    channel: str,
    tone: str,
) -> dict:
    """
    광고 카피 A/B/C 3종 + 슬로건 5개 + 배너 문구를 생성합니다.

    Returns:
        {
          "versions": [{"label", "style", "headline", "subcopy", "cta"}, ...],
          "slogans":  [str, ...],
          "banner":   str
        }
    """
    prompt = COPY_PROMPT.format(
        product_name=product_name,
        features=features,
        goal=goal,
        persona=persona,
        channel=channel,
        tone=tone,
    )

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )

    data = json.loads(res.choices[0].message.content)

    # 필드 보장
    versions = data.get("versions", [])
    slogans  = data.get("slogans", [])
    banner   = data.get("banner", "")

    if len(versions) != 3:
        raise ValueError("카피 버전이 3종 생성되지 않았습니다. 다시 시도해 주세요.")

    return {"versions": versions, "slogans": slogans, "banner": banner}
