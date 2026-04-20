"""
HR 채용 요청/공고 생성 서비스
"""
import json

from openai import OpenAI

from config import settings
from database import get_connection

client = OpenAI(api_key=settings.openai_api_key)

HIRE_REQUEST_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS hr_hire_requests (
    id                           SERIAL          PRIMARY KEY,
    request_key                  VARCHAR(255)    NOT NULL UNIQUE,
    requester_employee_id        VARCHAR(50)     NOT NULL,
    requester_name               VARCHAR(100)    NOT NULL,
    request_department           VARCHAR(100)    NOT NULL,
    job_title                    VARCHAR(150)    NOT NULL,
    employment_type              VARCHAR(50)     NOT NULL,
    experience_level             VARCHAR(50)     NOT NULL,
    headcount                    INTEGER         NOT NULL,
    urgency                      VARCHAR(50)     NOT NULL,
    hiring_goal                  TEXT            NOT NULL,
    reason                       TEXT            NOT NULL,
    responsibilities             TEXT            NOT NULL,
    qualifications               TEXT            NOT NULL,
    preferred_qualifications     TEXT,
    status                       VARCHAR(50)     NOT NULL DEFAULT 'requested',
    generated_posting_at         TIMESTAMPTZ,
    created_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ     NOT NULL DEFAULT NOW()
)
"""

HIRE_REQUEST_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_hr_hire_requests_created_at ON hr_hire_requests (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_hr_hire_requests_department_status ON hr_hire_requests (request_department, status)",
]

JOB_POSTING_PROMPT = """
당신은 사내 채용 담당자를 돕는 HR 리크루팅 전문가입니다.
아래 채용 요청서를 바탕으로 실제 공고 게시에 바로 활용할 수 있는 한국어 채용 공고 초안을 작성하세요.

[채용 요청서]
- 요청 부서: {request_department}
- 요청자: {requester_name} ({requester_employee_id})
- 직무명: {job_title}
- 고용 형태: {employment_type}
- 경력 수준: {experience_level}
- 채용 인원: {headcount}명
- 긴급도: {urgency}
- 채용 목적: {hiring_goal}
- 요청 사유: {reason}
- 주요 업무: {responsibilities}
- 필수 요건: {qualifications}
- 우대 사항: {preferred_qualifications}

작성 규칙:
- 공고 문체는 명확하고 실무적이어야 합니다.
- 요청서 내용을 과장하지 말고 자연스럽게 구조화하세요.
- 각 리스트는 3~6개 항목으로 작성하세요.
- JSON으로만 응답하세요.

응답 형식:
{{
  "job_post_title": "채용 공고 제목",
  "hiring_summary": "공고 상단 요약 2~3문장",
  "team_intro": "부서/팀 소개 2~3문장",
  "responsibilities": ["주요 업무 1", "주요 업무 2"],
  "qualifications": ["필수 요건 1", "필수 요건 2"],
  "preferred_qualifications": ["우대 사항 1", "우대 사항 2"],
  "hiring_process": ["서류 전형", "1차 면접", "최종 합격"],
  "benefits": ["혜택 1", "혜택 2"],
  "application_deadline": "지원 마감 문구",
  "closing_message": "지원 독려 마무리 문구"
}}
"""


def _ensure_hire_request_table(cur) -> None:
    cur.execute(HIRE_REQUEST_TABLE_DDL)
    for ddl in HIRE_REQUEST_INDEXES:
        cur.execute(ddl)


def _serialize_hire_request_row(row) -> dict:
    return {
        "id": row[0],
        "request_key": row[1],
        "requester_employee_id": row[2],
        "requester_name": row[3],
        "request_department": row[4],
        "job_title": row[5],
        "employment_type": row[6],
        "experience_level": row[7],
        "headcount": row[8],
        "urgency": row[9],
        "hiring_goal": row[10],
        "reason": row[11],
        "responsibilities": row[12],
        "qualifications": row[13],
        "preferred_qualifications": row[14],
        "status": row[15],
        "generated_posting_at": str(row[16]) if row[16] else None,
        "created_at": str(row[17]) if row[17] else None,
        "updated_at": str(row[18]) if row[18] else None,
    }


def create_hire_request(
    *,
    request_key: str,
    requester_employee_id: str,
    requester_name: str,
    request_department: str,
    job_title: str,
    employment_type: str,
    experience_level: str,
    headcount: int,
    urgency: str,
    hiring_goal: str,
    reason: str,
    responsibilities: str,
    qualifications: str,
    preferred_qualifications: str,
) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_hire_request_table(cur)
        cur.execute(
            """
            INSERT INTO hr_hire_requests (
                request_key, requester_employee_id, requester_name, request_department,
                job_title, employment_type, experience_level, headcount, urgency,
                hiring_goal, reason, responsibilities, qualifications,
                preferred_qualifications
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, request_key, requester_employee_id, requester_name,
                      request_department, job_title, employment_type,
                      experience_level, headcount, urgency, hiring_goal, reason,
                      responsibilities, qualifications, preferred_qualifications,
                      status, generated_posting_at, created_at, updated_at
            """,
            (
                request_key,
                requester_employee_id,
                requester_name,
                request_department,
                job_title,
                employment_type,
                experience_level,
                headcount,
                urgency,
                hiring_goal,
                reason,
                responsibilities,
                qualifications,
                preferred_qualifications,
            ),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    return _serialize_hire_request_row(row)


def list_hire_requests() -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_hire_request_table(cur)
        cur.execute(
            """
            SELECT id, request_key, requester_employee_id, requester_name,
                   request_department, job_title, employment_type,
                   experience_level, headcount, urgency, hiring_goal, reason,
                   responsibilities, qualifications, preferred_qualifications,
                   status, generated_posting_at, created_at, updated_at
            FROM hr_hire_requests
            ORDER BY created_at DESC, id DESC
            """
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return [_serialize_hire_request_row(row) for row in rows]


def get_hire_request_by_id(request_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_hire_request_table(cur)
        cur.execute(
            """
            SELECT id, request_key, requester_employee_id, requester_name,
                   request_department, job_title, employment_type,
                   experience_level, headcount, urgency, hiring_goal, reason,
                   responsibilities, qualifications, preferred_qualifications,
                   status, generated_posting_at, created_at, updated_at
            FROM hr_hire_requests
            WHERE id = %s
            """,
            (request_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    return _serialize_hire_request_row(row) if row else None


def _normalize_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def generate_job_posting_from_request(request_id: int) -> dict:
    hire_request = get_hire_request_by_id(request_id)
    if not hire_request:
        raise ValueError("선택한 채용 요청서를 찾을 수 없습니다.")

    prompt = JOB_POSTING_PROMPT.format(
        request_department=hire_request["request_department"],
        requester_name=hire_request["requester_name"],
        requester_employee_id=hire_request["requester_employee_id"],
        job_title=hire_request["job_title"],
        employment_type=hire_request["employment_type"],
        experience_level=hire_request["experience_level"],
        headcount=hire_request["headcount"],
        urgency=hire_request["urgency"],
        hiring_goal=hire_request["hiring_goal"],
        reason=hire_request["reason"],
        responsibilities=hire_request["responsibilities"],
        qualifications=hire_request["qualifications"],
        preferred_qualifications=hire_request["preferred_qualifications"] or "없음",
    )

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1800,
    )

    data = json.loads(res.choices[0].message.content)
    posting = {
        "job_post_title": str(data.get("job_post_title", "")).strip(),
        "hiring_summary": str(data.get("hiring_summary", "")).strip(),
        "team_intro": str(data.get("team_intro", "")).strip(),
        "responsibilities": _normalize_list(data.get("responsibilities")),
        "qualifications": _normalize_list(data.get("qualifications")),
        "preferred_qualifications": _normalize_list(data.get("preferred_qualifications")),
        "hiring_process": _normalize_list(data.get("hiring_process")),
        "benefits": _normalize_list(data.get("benefits")),
        "application_deadline": str(data.get("application_deadline", "")).strip(),
        "closing_message": str(data.get("closing_message", "")).strip(),
    }

    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_hire_request_table(cur)
        cur.execute(
            """
            UPDATE hr_hire_requests
               SET status = 'posting_generated',
                   generated_posting_at = NOW(),
                   updated_at = NOW()
             WHERE id = %s
            """,
            (request_id,),
        )
    finally:
        cur.close()
        conn.close()

    refreshed_request = get_hire_request_by_id(request_id)
    return {
        "request": refreshed_request,
        "posting": posting,
    }
