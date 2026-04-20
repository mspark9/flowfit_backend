"""
고객 미팅 요약 라우터 — /api/sales/meeting/*
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from services.sales.crm_store import (
    VALID_STAGES,
    list_opportunities,
    save_opportunity,
)
from services.sales.sales_meeting_service import summarize_meeting
from services.sales.stt_service import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    transcribe_audio,
)

router = APIRouter()


class MeetingRequest(BaseModel):
    company_name:  str
    meeting_date:  str        # YYYY-MM-DD
    meeting_notes: str        # 미팅 내용/메모 (자유 형식)


@router.post("/summarize")
def meeting_summarize(body: MeetingRequest):
    """
    미팅 메모/녹취 텍스트를 구조화하여 요약합니다.

    Request : { company_name, meeting_date, meeting_notes }
    Response: {
      meeting_title, key_discussions, customer_needs,
      concerns, action_items, next_agenda, crm_draft
    }
    """
    if not body.company_name.strip():
        raise HTTPException(status_code=400, detail="고객사명을 입력해 주세요.")
    if not body.meeting_notes.strip():
        raise HTTPException(status_code=400, detail="미팅 내용을 입력해 주세요.")

    try:
        result = summarize_meeting(
            company_name=body.company_name,
            meeting_date=body.meeting_date,
            meeting_notes=body.meeting_notes,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 요약 실패: {str(e)}")

    return result


@router.post("/transcribe")
async def meeting_transcribe(file: UploadFile = File(...)):
    """
    미팅 녹취 오디오 파일을 텍스트로 변환합니다 (Whisper).

    Request : multipart/form-data, file: 오디오 파일
    Response: { text: "변환된 텍스트" }
    """
    # 파일 확장자 검증
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. ({', '.join(sorted(ALLOWED_EXTENSIONS))})",
        )

    # 파일 크기 검증
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기는 최대 25MB까지 가능합니다. (현재 {len(file_bytes) // (1024*1024)}MB)",
        )

    try:
        text = transcribe_audio(file_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"음성 변환 실패: {str(e)}")

    if not text or not text.strip():
        raise HTTPException(status_code=422, detail="변환된 텍스트가 비어 있습니다. 녹음 품질을 확인해 주세요.")

    return {"text": text.strip()}


class CrmSaveRequest(BaseModel):
    company_name:     str
    meeting_date:     str = ""
    opportunity_name: str
    stage:            str
    next_step:        str = ""
    contact_role:     str = ""
    description:      str = ""
    owner_id:         str = ""
    owner_name:       str = ""


@router.post("/crm-save")
def meeting_crm_save(body: CrmSaveRequest):
    """
    미팅 요약의 CRM 초안을 mock CRM 저장소에 저장합니다 (원클릭 반영).

    Request : { company_name, meeting_date, opportunity_name, stage, ... }
    Response: 저장된 레코드 (id, created_at 포함)
    """
    if not body.company_name.strip():
        raise HTTPException(status_code=400, detail="고객사명이 필요합니다.")
    if not body.opportunity_name.strip():
        raise HTTPException(status_code=400, detail="영업 기회명이 필요합니다.")
    if body.stage not in VALID_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"단계는 다음 중 하나여야 합니다: {', '.join(sorted(VALID_STAGES))}",
        )

    try:
        record = save_opportunity(
            company_name=body.company_name.strip(),
            meeting_date=body.meeting_date.strip(),
            opportunity_name=body.opportunity_name.strip(),
            stage=body.stage,
            next_step=body.next_step.strip(),
            contact_role=body.contact_role.strip(),
            description=body.description.strip(),
            owner_id=body.owner_id.strip(),
            owner_name=body.owner_name.strip(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CRM 저장 실패: {str(e)}")

    return record


@router.get("/crm-list")
def meeting_crm_list(
    owner_id:     str = "",
    company_name: str = "",
    search:       str = "",
    offset:       int = 0,
    limit:        int = 10,
):
    """
    저장된 영업 기회 목록을 필터링하여 반환합니다 (mock CRM).

    Query params:
        owner_id     — 특정 사원 ID만 조회 ("" = 전원)
        company_name — 고객사명 부분 일치
        search       — 영업 기회명·고객사·설명·다음 단계 부분 일치
        offset/limit — 페이지네이션 (기본 offset=0, limit=10)

    Response: { items: [...], total, offset, limit }
    """
    return list_opportunities(
        owner_id=owner_id,
        company_name=company_name,
        search=search,
        offset=offset,
        limit=limit,
    )
