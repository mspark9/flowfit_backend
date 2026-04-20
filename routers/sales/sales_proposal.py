"""
영업 제안서 라우터 — /api/sales/proposal/*
성공 사례 문서 RAG 업로드/목록/삭제 + 제안서 자동 생성
"""
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from services.sales.sales_proposal_service import (
    ALLOWED_INDUSTRIES,
    delete_proposal_document,
    generate_proposal,
    list_proposal_documents,
    save_proposal_document,
)

router = APIRouter()


class ProposalRequest(BaseModel):
    company_name: str
    industry:     str        # 제조업 | 유통·서비스 | IT
    company_size: str = ""   # 규모 (임직원 수, 매출 등)
    key_needs:    str        # 핵심 니즈


# ── 성공 사례 문서 목록 ───────────────────────────────────────

@router.get("/documents")
def get_proposal_documents(industry: Optional[str] = None):
    """성공 사례 문서 목록 (industry 쿼리로 업종 필터)"""
    if industry and industry not in ALLOWED_INDUSTRIES:
        raise HTTPException(status_code=400, detail="industry는 '제조업', '유통·서비스', 'IT' 중 하나여야 합니다.")
    try:
        return {"items": list_proposal_documents(industry)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(exc)}") from exc


# ── 성공 사례 문서 업로드 ─────────────────────────────────────

@router.post("/documents/upload")
async def upload_proposal_document(
    file: UploadFile = File(...),
    industry: str = Form(...),
    employee_id: Optional[str] = Form(default=None),
    uploader_name: Optional[str] = Form(default=None),
    uploader_department: Optional[str] = Form(default=None),
):
    """성공 사례 문서(pdf, docx, hwp, txt) 업로드 → 청킹 · 임베딩 · 저장"""
    allowed_extensions = (".hwp", ".docx", ".pdf", ".txt")

    if not file.filename or not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(status_code=400, detail="hwp, docx, pdf, txt 파일만 업로드할 수 있습니다.")

    if industry not in ALLOWED_INDUSTRIES:
        raise HTTPException(status_code=400, detail="industry는 '제조업', '유통·서비스', 'IT' 중 하나여야 합니다.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")

    try:
        item = save_proposal_document(
            filename=file.filename,
            file_bytes=file_bytes,
            industry=industry,
            uploader={
                "employee_id": employee_id.strip() if employee_id else None,
                "name": uploader_name.strip() if uploader_name else None,
                "department": uploader_department.strip() if uploader_department else None,
            },
        )
        return {"item": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 업로드 처리 실패: {str(exc)}") from exc


# ── 성공 사례 문서 삭제 ───────────────────────────────────────

@router.delete("/documents/{document_id}")
def delete_proposal_document_route(document_id: int):
    """지정 ID 성공 사례 문서 삭제 (청크 CASCADE 삭제)"""
    try:
        return delete_proposal_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 삭제 실패: {str(exc)}") from exc


# ── 제안서 자동 생성 ──────────────────────────────────────────

@router.post("/generate")
def proposal_generate(body: ProposalRequest):
    """
    고객사 맞춤형 영업 제안서 초안을 생성합니다.
    (업종별 성공 사례 문서를 벡터 RAG로 검색하여 참조)

    Request : { company_name, industry, company_size?, key_needs }
    Response: {
      executive_summary, situation_analysis, pain_points,
      solution, expected_benefits, success_case,
      implementation_schedule, investment, email_draft,
      sources
    }
    """
    if body.industry not in ALLOWED_INDUSTRIES:
        raise HTTPException(status_code=400, detail="industry는 '제조업', '유통·서비스', 'IT' 중 하나여야 합니다.")
    if not body.company_name.strip():
        raise HTTPException(status_code=400, detail="고객사명을 입력해 주세요.")
    if not body.key_needs.strip():
        raise HTTPException(status_code=400, detail="핵심 니즈를 입력해 주세요.")

    try:
        return generate_proposal(
            company_name=body.company_name,
            industry=body.industry,
            company_size=body.company_size,
            key_needs=body.key_needs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 생성 실패: {str(exc)}") from exc
