"""
릴리즈 노트 생성 라우터 — /api/dev/release
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.dev.dev_release_service import generate_release_note

router = APIRouter()


class ReleaseNoteRequest(BaseModel):
    commits: str
    version: str = ""
    product_name: str = ""
    audience: str = "general"


@router.post("/generate")
def generate(body: ReleaseNoteRequest):
    if not body.commits.strip():
        raise HTTPException(status_code=400, detail="커밋 메시지를 입력해 주세요.")
    try:
        return generate_release_note(
            body.commits,
            version=body.version,
            product_name=body.product_name,
            audience=body.audience,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"릴리즈 노트 생성 실패: {str(exc)}") from exc
