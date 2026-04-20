"""
마케팅 보도자료 라우터 — /api/marketing/press/*
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.marketing.mkt_press_service import generate_press

router = APIRouter()


class PressRequest(BaseModel):
    press_type:   str        # 신제품 | 이벤트 | 실적
    facts:        str
    quote_person: str = ""   # 인용구 주체 (CEO·임원 이름·직책)
    media_type:   str = "IT" # IT | 경제 | 생활


# ──────────────────────────────────────────────────────────────
# POST /api/marketing/press/generate
# ──────────────────────────────────────────────────────────────
@router.post("/generate")
def press_generate(body: PressRequest):
    """
    보도자료 전문 + 이메일 초안 + SNS 요약문을 생성합니다.

    Request : application/json { press_type, facts, quote_person?, media_type? }
    Response: { headline, release_date, body, quote,
                email_subject, email_body, sns_linkedin, sns_x }
    """
    if body.press_type not in ("신제품", "이벤트", "실적"):
        raise HTTPException(status_code=400, detail="press_type은 '신제품', '이벤트', '실적' 중 하나여야 합니다.")
    if not body.facts.strip():
        raise HTTPException(status_code=400, detail="핵심 팩트를 입력해 주세요.")

    try:
        result = generate_press(
            press_type=body.press_type,
            facts=body.facts,
            quote_person=body.quote_person,
            media_type=body.media_type,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 생성 실패: {str(e)}")

    return result
