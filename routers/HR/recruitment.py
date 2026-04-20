"""
채용 요청서/채용 공고 생성 라우터 — /api/hr/*
"""
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.HR.hr_notification_service import create_notification
from services.HR.hr_recruitment_service import (
    create_hire_request,
    generate_job_posting_from_request,
    list_hire_requests,
)

router = APIRouter()


class HireRequestCreateRequest(BaseModel):
    requester_employee_id: str
    requester_name: str
    request_department: str
    job_title: str
    employment_type: str
    experience_level: str
    headcount: int
    urgency: str
    hiring_goal: str
    reason: str
    responsibilities: str
    qualifications: str
    preferred_qualifications: str = ""


class JobPostGenerateRequest(BaseModel):
    request_id: int


@router.get("/hire-requests")
def get_hire_requests():
    try:
        items = list_hire_requests()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"채용 요청서 목록 조회 실패: {str(exc)}")

    return {
        "total": len(items),
        "items": items,
    }


@router.post("/hire-requests")
def create_hire_request_endpoint(body: HireRequestCreateRequest):
    if not body.requester_employee_id.strip():
        raise HTTPException(status_code=400, detail="요청자 사번이 필요합니다.")
    if not body.requester_name.strip():
        raise HTTPException(status_code=400, detail="요청자 이름이 필요합니다.")
    if not body.request_department.strip():
        raise HTTPException(status_code=400, detail="요청 부서를 확인할 수 없습니다.")
    if not body.job_title.strip():
        raise HTTPException(status_code=400, detail="직무명을 입력해 주세요.")
    if body.headcount <= 0:
        raise HTTPException(status_code=400, detail="채용 인원은 1명 이상이어야 합니다.")
    if not body.hiring_goal.strip() or not body.reason.strip():
        raise HTTPException(status_code=400, detail="채용 목적과 요청 사유를 모두 입력해 주세요.")
    if not body.responsibilities.strip() or not body.qualifications.strip():
        raise HTTPException(status_code=400, detail="주요 업무와 필수 요건을 모두 입력해 주세요.")

    try:
        item = create_hire_request(
            request_key=f"hire-request-{uuid4()}",
            requester_employee_id=body.requester_employee_id.strip(),
            requester_name=body.requester_name.strip(),
            request_department=body.request_department.strip(),
            job_title=body.job_title.strip(),
            employment_type=body.employment_type.strip(),
            experience_level=body.experience_level.strip(),
            headcount=body.headcount,
            urgency=body.urgency.strip(),
            hiring_goal=body.hiring_goal.strip(),
            reason=body.reason.strip(),
            responsibilities=body.responsibilities.strip(),
            qualifications=body.qualifications.strip(),
            preferred_qualifications=body.preferred_qualifications.strip(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"채용 요청서 저장 실패: {str(exc)}")

    job_title = item["job_title"]
    notice_message = f"({job_title}) 채용 요청이 등록되었습니다."

    create_notification(notice_message, "채용 요청서 작성")

    return {
        "item": item,
        "message": notice_message,
    }


@router.post("/job-post/generate")
def generate_job_post_endpoint(body: JobPostGenerateRequest):
    if body.request_id <= 0:
        raise HTTPException(status_code=400, detail="올바른 요청서 ID가 필요합니다.")

    try:
        result = generate_job_posting_from_request(body.request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"채용 공고 생성 실패: {str(exc)}")

    return result
