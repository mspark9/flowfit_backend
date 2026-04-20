"""
총무/구매팀 라우터 — 구매 에이전트 / 견적 비교 / 정책 챗봇 / 자산 보고서
"""
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from services.procurement.procurement_agent_service import run_procurement_agent
from services.procurement.procurement_report_service import (
    generate_estimate_docx,
    generate_estimate_pdf,
)

router = APIRouter()


# ── 요청 모델 ─────────────────────────────────────────────────

class ProcurementAgentRequest(BaseModel):
    message:    str
    department: str = "총무/구매팀"


class CandidateItem(BaseModel):
    rank:   int
    name:   str
    price:  int  = 0
    vendor: str  = ""
    url:    str  = ""
    reason: str  = ""


class EstimateDownloadRequest(BaseModel):
    format:                  str           # "docx" | "pdf"
    report_text:             str           = ""
    order_id:                Optional[int] = None
    department:              str           = ""
    item_name:               str           = ""
    quantity:                int           = 1
    unit_price:              int           = 0
    total_amount:            int           = 0
    vendor:                  str           = ""
    account_code:            str           = ""
    status:                  str           = "승인대기"
    created_at:              str           = ""
    top_candidates:          List[CandidateItem] = []
    selected_candidate_rank: int           = 1


# ── 엔드포인트 ────────────────────────────────────────────────

@router.post("/agent")
def procurement_agent(body: ProcurementAgentRequest):
    """구매 AI 에이전트 — SSE 스트리밍 (tool_start / tool_done / token / done)"""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="구매 요청 내용을 입력해 주세요.")

    def generate():
        yield from run_procurement_agent(
            message=body.message.strip(),
            department=body.department or "총무/구매팀",
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/download")
def download_estimate(body: EstimateDownloadRequest):
    """구매견적서 DOCX / PDF 다운로드"""
    fmt = body.format.lower().strip()
    if fmt not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="format은 'docx' 또는 'pdf'이어야 합니다.")

    data = body.model_dump()
    # CandidateItem 리스트를 dict 리스트로 변환
    data["top_candidates"] = [c.model_dump() for c in body.top_candidates]

    try:
        if fmt == "docx":
            file_bytes = generate_estimate_docx(data)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            filename   = f"구매견적서_#{body.order_id or 'draft'}.docx"
        else:
            file_bytes = generate_estimate_pdf(data)
            media_type = "application/pdf"
            filename   = f"구매견적서_#{body.order_id or 'draft'}.pdf"
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"파일 생성 실패: {str(exc)}") from exc

    encoded_name = quote(filename)
    return Response(
        content=file_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


# TODO: 견적서 OCR 비교 — POST /api/procurement/quote
# TODO: 구매 정책 챗봇 — POST /api/procurement/chat
# TODO: 자산 실사 보고서 — POST /api/procurement/asset/report
