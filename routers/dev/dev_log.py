"""
개발/IT 장애 로그 분석 라우터 — /api/dev/log
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.dev.dev_log_service import analyze_log

router = APIRouter()


class LogAnalysisRequest(BaseModel):
    log_text: str
    context: str = ""


@router.post("/analyze")
def analyze_log_route(body: LogAnalysisRequest):
    if not body.log_text.strip():
        raise HTTPException(status_code=400, detail="로그를 입력해 주세요.")
    try:
        return analyze_log(body.log_text, body.context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"분석 실패: {str(exc)}") from exc
