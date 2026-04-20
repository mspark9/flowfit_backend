"""
마케팅 SNS 콘텐츠 자동화 라우터 — /api/marketing/sns/*
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.marketing.mkt_sns_service import generate_sns

router = APIRouter()


class SnsRequest(BaseModel):
    topic:    str
    message:  str
    channel:  str = "both"   # instagram | blog | both
    keywords: str = ""       # SEO 타겟 키워드 (블로그용)
    extra:    str = ""       # 참고 정보


# ──────────────────────────────────────────────────────────────
# POST /api/marketing/sns/generate
# ──────────────────────────────────────────────────────────────
@router.post("/generate")
def sns_generate(body: SnsRequest):
    """
    인스타그램·블로그 콘텐츠를 동시 생성합니다.

    Request : application/json { topic, message, channel?, keywords?, extra? }
    Response: { instagram?: {...}, blog?: {...} }
    """
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="콘텐츠 주제를 입력해 주세요.")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="핵심 메시지를 입력해 주세요.")
    if body.channel not in ("instagram", "blog", "both"):
        raise HTTPException(status_code=400, detail="channel은 'instagram', 'blog', 'both' 중 하나여야 합니다.")

    try:
        result = generate_sns(
            topic=body.topic,
            message=body.message,
            channel=body.channel,
            keywords=body.keywords,
            extra=body.extra,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 생성 실패: {str(e)}")

    return result
