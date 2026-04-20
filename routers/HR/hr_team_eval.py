"""
팀원 평가 라우터 — /api/hr/team-eval/*
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.HR.hr_team_eval_service import (
    get_team_members,
    upsert_team_evaluations,
    fetch_my_evaluations,
    fetch_team_eval_summary,
    fetch_my_received_evaluations,
)

router = APIRouter()


@router.get("/members")
def team_members(evaluator_id: str = "", department: str = ""):
    """같은 부서 팀원 목록 (본인 제외)."""
    if not evaluator_id or not department:
        raise HTTPException(status_code=400, detail="evaluator_id와 department가 필요합니다.")
    return get_team_members(evaluator_id=evaluator_id, department=department)


class TeamEvalItem(BaseModel):
    target_id:           str = ""
    target_name:         str
    target_department:   str = ""
    target_position:     str = ""
    work_score:          float = Field(default=0, ge=0, le=5)
    leadership_score:    float = Field(default=0, ge=0, le=5)
    expertise_score:     float = Field(default=0, ge=0, le=5)
    collaboration_score: float = Field(default=0, ge=0, le=5)
    comment:             str = ""


class TeamEvalRequest(BaseModel):
    evaluator_id:         str
    evaluator_name:       str
    evaluator_department: str
    eval_year:            int
    eval_quarter:         int
    evaluations:          list[TeamEvalItem]


@router.post("/submit")
def submit_team_eval(body: TeamEvalRequest):
    """팀원 평가를 저장합니다 (같은 대상·분기면 덮어쓰기)."""
    if not body.evaluator_id:
        raise HTTPException(status_code=400, detail="evaluator_id가 필요합니다.")
    if not body.evaluations:
        raise HTTPException(status_code=400, detail="평가 대상이 없습니다.")
    if not (1 <= body.eval_quarter <= 4):
        raise HTTPException(status_code=400, detail="eval_quarter는 1~4 사이여야 합니다.")

    try:
        result = upsert_team_evaluations(
            evaluator_id=body.evaluator_id,
            evaluator_name=body.evaluator_name,
            evaluator_department=body.evaluator_department,
            eval_year=body.eval_year,
            eval_quarter=body.eval_quarter,
            evaluations=[e.model_dump() for e in body.evaluations],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"평가 저장 실패: {str(e)}")

    return result


@router.get("/my")
def my_evaluations(evaluator_id: str = "", eval_year: int = 0, eval_quarter: int = 0):
    """본인이 제출한 해당 분기 평가 목록."""
    if not evaluator_id or not eval_year or not eval_quarter:
        raise HTTPException(status_code=400, detail="evaluator_id, eval_year, eval_quarter가 필요합니다.")
    return fetch_my_evaluations(
        evaluator_id=evaluator_id,
        eval_year=eval_year,
        eval_quarter=eval_quarter,
    )


@router.get("/summary")
def team_eval_summary(department: str = "", eval_year: int = 0, eval_quarter: int = 0):
    """부서·분기별 팀원 평가 집계 (HR 관리자용)."""
    if not department or not eval_year or not eval_quarter:
        raise HTTPException(status_code=400, detail="department, eval_year, eval_quarter가 필요합니다.")
    return fetch_team_eval_summary(
        department=department,
        eval_year=eval_year,
        eval_quarter=eval_quarter,
    )


@router.get("/received")
def my_received_evaluations(target_name: str = "", eval_year: int = 0, eval_quarter: int = 0):
    """나에 대한 평가 결과 (평균 점수 + 익명 코멘트)."""
    if not target_name or not eval_year or not eval_quarter:
        raise HTTPException(status_code=400, detail="target_name, eval_year, eval_quarter가 필요합니다.")
    return fetch_my_received_evaluations(
        target_name=target_name,
        eval_year=eval_year,
        eval_quarter=eval_quarter,
    )
