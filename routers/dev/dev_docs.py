"""
개발/IT 인프라 문서 챗봇 라우터 — /api/dev/docs
"""
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from services.dev.dev_docs_service import (
    answer_dev_question,
    delete_dev_document,
    list_dev_documents,
    save_dev_documents,
)

router = APIRouter()


class DevChatRequest(BaseModel):
    question: str


@router.get("")
def list_documents():
    try:
        return {"items": list_dev_documents()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 목록 조회 실패: {str(exc)}") from exc


@router.post("/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    employee_id: Optional[str] = Form(default=None),
    uploader_name: Optional[str] = Form(default=None),
    uploader_department: Optional[str] = Form(default=None),
):
    allowed = (".hwp", ".docx", ".pdf")
    if not files:
        raise HTTPException(status_code=400, detail="업로드할 파일이 없습니다.")

    payloads: list[tuple[str, bytes]] = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(allowed):
            raise HTTPException(status_code=400, detail="hwp, docx, pdf 파일만 업로드할 수 있습니다.")
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")
        payloads.append((file.filename, file_bytes))

    try:
        items = save_dev_documents(
            payloads,
            uploader={
                "employee_id": employee_id.strip() if employee_id else None,
                "name": uploader_name.strip() if uploader_name else None,
                "department": uploader_department.strip() if uploader_department else None,
            },
        )
        return {"items": items}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 업로드 실패: {str(exc)}") from exc


@router.delete("/{document_id}")
def delete_document(document_id: int):
    try:
        return delete_dev_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"문서 삭제 실패: {str(exc)}") from exc


@router.post("/chat")
def chat(body: DevChatRequest):
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="질문을 입력해 주세요.")
    try:
        return answer_dev_question(body.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 답변 생성 실패: {str(exc)}") from exc
