"""
마케팅 카피라이팅 라우터 — /api/marketing/copy/*
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.marketing.mkt_copy_service import generate_copy

router = APIRouter()


class CopyRequest(BaseModel):
    product_name: str
    features:     str
    goal:         str        # 인지 | 전환 | 리텐션
    persona:      str  = ""
    channel:      str  = ""  # 온라인광고 | 인스타그램 | 옥외광고 | 등
    tone:         str  = "공식체"  # 공식체 | 친근체 | MZ감성


# ──────────────────────────────────────────────────────────────
# POST /api/marketing/copy/generate
# ──────────────────────────────────────────────────────────────
@router.post("/generate")
def copy_generate(body: CopyRequest):
    """
    광고 카피 A/B/C 3종 + 슬로건 5개 + 배너 문구를 생성합니다.

    Request : application/json { product_name, features, goal, persona?, channel?, tone? }
    Response: { versions: [{label, style, headline, subcopy, cta}], slogans: [str], banner: str }
    """
    if not body.product_name.strip():
        raise HTTPException(status_code=400, detail="제품명을 입력해 주세요.")
    if not body.features.strip():
        raise HTTPException(status_code=400, detail="핵심 특장점을 입력해 주세요.")
    if body.goal not in ("인지", "전환", "리텐션"):
        raise HTTPException(status_code=400, detail="goal은 '인지', '전환', '리텐션' 중 하나여야 합니다.")

    try:
        result = generate_copy(
            product_name=body.product_name,
            features=body.features,
            goal=body.goal,
            persona=body.persona,
            channel=body.channel,
            tone=body.tone,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 생성 실패: {str(e)}")

    return result
