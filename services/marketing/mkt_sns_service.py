"""
마케팅 SNS 콘텐츠 자동화 서비스 — 인스타그램 · 블로그 동시 생성
"""
import json
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

INSTAGRAM_PROMPT = """
당신은 인스타그램 콘텐츠 전문 마케터입니다.
아래 정보를 바탕으로 인스타그램 포스팅용 콘텐츠를 작성하세요.

주제: {topic}
핵심 메시지: {message}
추가 정보: {extra}

JSON으로만 응답하세요:
{{
  "hook": "첫 1~2문장 훅 (스크롤을 멈추게 하는 강렬한 도입)",
  "body": "본문 (감성적이고 공감가는 내용, 3~5문장)",
  "cta": "CTA 문구 (댓글·저장·공유 유도)",
  "hashtags": {{
    "popular": ["인기태그1", "인기태그2", ...],
    "niche": ["틈새태그1", "틈새태그2", ...],
    "brand": ["브랜드태그1", "브랜드태그2"]
  }}
}}

popular 10개, niche 15개, brand 5개로 구성하세요. # 기호 포함해서 작성하세요.
"""

BLOG_PROMPT = """
당신은 SEO 전문 블로그 작가입니다.
아래 정보를 바탕으로 블로그 포스트 초안을 작성하세요.

주제: {topic}
핵심 메시지: {message}
SEO 키워드: {keywords}
추가 정보: {extra}

JSON으로만 응답하세요:
{{
  "seo_title": "SEO 최적화 제목 (30~60자, 키워드 포함)",
  "meta_description": "메타 설명 (160자 이내, 핵심 내용 요약)",
  "sections": [
    {{
      "heading": "H2 소제목",
      "content": "해당 섹션 본문 (3~5문장)"
    }}
  ],
  "internal_link_suggestions": ["추천 내부 링크 주제1", "추천 내부 링크 주제2"]
}}

sections는 도입부 포함 4~5개로 구성하세요.
"""


def generate_sns(
    topic: str,
    message: str,
    channel: str,
    keywords: str,
    extra: str,
) -> dict:
    """
    채널에 따라 인스타그램·블로그 콘텐츠를 생성합니다.

    Args:
        topic:    콘텐츠 주제
        message:  핵심 메시지
        channel:  'instagram' | 'blog' | 'both'
        keywords: SEO 타겟 키워드 (블로그용)
        extra:    참고 정보 (제품 스펙 등)

    Returns:
        {
          "instagram"?: { hook, body, cta, hashtags: { popular, niche, brand } },
          "blog"?:      { seo_title, meta_description, sections, internal_link_suggestions }
        }
    """
    result = {}

    if channel in ("instagram", "both"):
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": INSTAGRAM_PROMPT.format(
                    topic=topic,
                    message=message,
                    extra=extra or "없음",
                ),
            }],
            max_tokens=800,
        )
        result["instagram"] = json.loads(res.choices[0].message.content)

    if channel in ("blog", "both"):
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": BLOG_PROMPT.format(
                    topic=topic,
                    message=message,
                    keywords=keywords or "미지정",
                    extra=extra or "없음",
                ),
            }],
            max_tokens=1200,
        )
        result["blog"] = json.loads(res.choices[0].message.content)

    return result
