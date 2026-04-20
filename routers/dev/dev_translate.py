"""
기술 용어 번역 라우터 — /api/dev/translate
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

from services.dev.dev_translate_service import (
    translate_tech_text,
    list_terms,
    toggle_pin,
    delete_term,
    get_stats,
    get_usage_stats,
)

router = APIRouter()


# ── 번역 ──────────────────────────────────────────────────────────────────────

class TranslateRequest(BaseModel):
    text: str
    audience: Literal["pm", "exec", "sales", "general"] = "general"


@router.post("/translate")
def translate_route(body: TranslateRequest):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="텍스트를 입력해 주세요.")
    try:
        return translate_tech_text(body.text, body.audience)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"번역 실패: {str(exc)}") from exc


# ── 용어집 조회 ───────────────────────────────────────────────────────────────

@router.get("/glossary")
def glossary_list_route(pinned_only: bool = False):
    try:
        return list_terms(pinned_only=pinned_only)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/glossary/stats")
def glossary_stats_route():
    try:
        return get_stats()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── 수동 고정/해제 ────────────────────────────────────────────────────────────

class PinRequest(BaseModel):
    is_pinned: bool


@router.patch("/glossary/{term_id}/pin")
def pin_route(term_id: int, body: PinRequest):
    try:
        return toggle_pin(term_id, body.is_pinned)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── 삭제 ──────────────────────────────────────────────────────────────────────

@router.delete("/glossary/{term_id}")
def delete_route(term_id: int):
    try:
        delete_term(term_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── 사용 통계 ─────────────────────────────────────────────────────────────────

@router.get("/usage-stats")
def usage_stats_route():
    try:
        return get_usage_stats()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
