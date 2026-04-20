"""
마케팅 캠페인 이미지 생성 라우터 — /api/marketing/image/*
"""
import urllib.parse
import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.marketing.mkt_image_service import generate_image

router = APIRouter()


class ImageRequest(BaseModel):
    product_name: str
    description: str
    style: str = "모던하고 세련된"  # 스타일 프리셋
    size: str = "1024x1024"       # 1024x1024 | 1024x1792 | 1792x1024


# ──────────────────────────────────────────────────────────────
# POST /api/marketing/image/generate
# ──────────────────────────────────────────────────────────────
@router.post("/generate")
def image_generate(body: ImageRequest):
    """
    캠페인 정보를 기반으로 마케팅 이미지를 생성합니다.

    Request : { product_name, description, style?, size? }
    Response: { image_url, revised_prompt }
    """
    if not body.product_name.strip():
        raise HTTPException(status_code=400, detail="제품명을 입력해 주세요.")
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="이미지 설명을 입력해 주세요.")

    valid_sizes = ("1024x1024", "1024x1792", "1792x1024")
    if body.size not in valid_sizes:
        raise HTTPException(
            status_code=400,
            detail=f"size는 {', '.join(valid_sizes)} 중 하나여야 합니다.",
        )

    try:
        result = generate_image(
            product_name=body.product_name,
            description=body.description,
            style=body.style,
            size=body.size,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"이미지 생성 실패: {str(e)}")

    return result


# ──────────────────────────────────────────────────────────────
# GET /api/marketing/image/download?url=...&filename=...
# ──────────────────────────────────────────────────────────────
@router.get("/download")
def image_download(
    url: str = Query(..., description="다운로드할 이미지 URL"),
    filename: str = Query("campaign_image.png", description="저장 파일명"),
):
    """외부 이미지 URL을 프록시하여 브라우저에서 다운로드할 수 있도록 제공"""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except Exception:
        raise HTTPException(status_code=502, detail="이미지 다운로드에 실패했습니다.")

    # RFC 5987 인코딩 — 한글 파일명 포함 모든 유니코드 지원
    encoded_name = urllib.parse.quote(filename.encode("utf-8"), safe="")
    content_disposition = (
        f"attachment; filename=\"campaign_image.png\"; "
        f"filename*=UTF-8''{encoded_name}"
    )

    return StreamingResponse(
        iter([resp.content]),
        media_type="image/png",
        headers={"Content-Disposition": content_disposition},
    )
