"""
법무 라우터 — /api/legal/*
문서 업로드·조회·삭제 / RAG 챗봇 / 계약서 검토 / 계약서 초안 생성 / DOCX 다운로드
"""
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from services.legal.legal_chat_service import (
    answer_legal_question,
    delete_legal_document,
    list_active_legal_documents,
    save_legal_document,
)
from services.legal.legal_contract_service import (
    draft_to_docx,
    generate_contract_draft,
    review_contract,
)

router = APIRouter()


class LegalChatRequest(BaseModel):
    question: str


class ContractDraftRequest(BaseModel):
    contract_type: str
    party_a: str
    party_b: str
    purpose: str
    amount: str = ""
    start_date: str = ""
    end_date: str = ""
    extra: str = ""


class ContractDocxRequest(BaseModel):
    draft: str
    filename: str = "계약서"


# ── 문서 목록 ────────────────────────────────────────────────

@router.get("/documents")
def get_legal_documents():
    """활성 법무 문서 목록 반환"""
    try:
        return {"items": list_active_legal_documents()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(exc)}") from exc


# ── 문서 업로드 ───────────────────────────────────────────────

@router.post("/documents/upload")
async def upload_legal_document(
    file: UploadFile = File(...),
    employee_id: Optional[str] = Form(default=None),
    uploader_name: Optional[str] = Form(default=None),
    uploader_department: Optional[str] = Form(default=None),
):
    """법무 문서(pdf, docx, hwp) 업로드 및 DB 저장"""
    allowed_extensions = (".hwp", ".docx", ".pdf")

    if not file.filename or not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(status_code=400, detail="hwp, docx, pdf 파일만 업로드할 수 있습니다.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")

    try:
        item = save_legal_document(
            file.filename,
            file_bytes,
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


# ── 문서 삭제 ─────────────────────────────────────────────────

@router.delete("/documents/{document_id}")
def delete_legal_document_route(document_id: int):
    """지정 ID 법무 문서 삭제"""
    try:
        return delete_legal_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 삭제 실패: {str(exc)}") from exc


# ── RAG 챗봇 질의응답 ─────────────────────────────────────────

@router.post("/chat")
def legal_chat(body: LegalChatRequest):
    """업로드된 법무 문서 기반 질의응답"""
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="질문을 입력해 주세요.")

    try:
        return answer_legal_question(body.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 답변 생성 실패: {str(exc)}") from exc


# ── 계약서 AI 검토 ────────────────────────────────────────────

@router.post("/review")
async def review_contract_route(file: UploadFile = File(...)):
    """계약서 파일(pdf, docx, txt) 업로드 → AI 리스크 분석"""
    allowed_extensions = (".pdf", ".docx", ".txt", ".hwp", ".jpg", ".jpeg", ".png", ".webp", ".gif")

    if not file.filename or not file.filename.lower().endswith(allowed_extensions):
        raise HTTPException(status_code=400, detail="pdf, docx, txt, hwp, jpg, png, webp 파일만 지원합니다.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")

    try:
        return review_contract(file.filename, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"계약서 분석 실패: {str(exc)}") from exc


# ── 계약서 초안 생성 ──────────────────────────────────────────

@router.post("/draft")
def draft_contract_route(body: ContractDraftRequest):
    """계약 조건 입력 → AI 계약서 초안 생성"""
    try:
        return generate_contract_draft(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"계약서 생성 실패: {str(exc)}") from exc


# ── 계약서 DOCX 다운로드 ──────────────────────────────────────

@router.post("/draft/download")
def download_draft_docx(body: ContractDocxRequest):
    """생성된 계약서 초안 텍스트 → DOCX 파일 반환"""
    if not body.draft.strip():
        raise HTTPException(status_code=400, detail="계약서 내용이 비어 있습니다.")

    try:
        docx_bytes = draft_to_docx(body.draft, body.filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DOCX 생성 실패: {str(exc)}") from exc

    # 파일명 URL 인코딩 (한글 포함 시 latin-1 오류 방지)
    encoded_name = quote((body.filename or "계약서") + ".docx")
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )
