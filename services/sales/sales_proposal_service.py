"""
영업 제안서 자동 생성 서비스 — 업종별 구조 프리셋 + 성공 사례 벡터 RAG
legal_chat_service 패턴을 따라 실제 임베딩 기반 RAG로 동작합니다.
"""
import json
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from config import settings
from database import get_connection
from services.common.document_parser import (
    _sanitize_filename,
    extract_document_text,
)
from services.common.rag_utils import (
    _chunk_text,
    embed_text,
    embed_texts_batch,
    select_top_chunks_by_vector,
)

client = OpenAI(api_key=settings.openai_api_key)

ALLOWED_INDUSTRIES = ("제조업", "유통·서비스", "IT")

# 업종별 구조 프리셋
INDUSTRY_PRESETS = {
    "제조업": {
        "structure": "경영 현황 분석 → 생산성 Pain Point → AI 자동화 솔루션 → 도입 ROI → 유사 제조사 성공 사례 → 구축 일정 → 투자 비용",
        "focus": "생산 효율화, 불량률 감소, 예지 정비, SCM 최적화",
    },
    "유통·서비스": {
        "structure": "고객 현황 분석 → 운영 비효율 Pain Point → AI 고객경험 솔루션 → 매출 증대 효과 → 유사 유통사 성공 사례 → 구축 일정 → 투자 비용",
        "focus": "고객 이탈 방지, 재구매율 향상, 수요 예측, 개인화 추천",
    },
    "IT": {
        "structure": "기술 스택 현황 분석 → 개발/운영 Pain Point → AI DevOps 솔루션 → 생산성 향상 수치 → 유사 IT기업 성공 사례 → 구축 일정 → 투자 비용",
        "focus": "코드 품질 자동화, 장애 예측, 고객 지원 자동화, 데이터 파이프라인",
    },
}

PROPOSAL_PROMPT = """
당신은 테크원(TechOne) 영업팀의 AI Hub 솔루션 전문 영업 대표입니다.
아래 고객사 정보와 성공 사례를 참고하여 고객 맞춤형 제안서 초안을 작성하세요.

고객사명: {company_name}
업종: {industry}
규모: {company_size}
핵심 니즈: {key_needs}

업종별 구조 프리셋: {structure}
핵심 가치 포인트: {focus}

[참조 성공 사례 문서 - 벡터 유사도 상위 청크]
{success_cases}

작성 규칙:
- 고객사 이름을 본문 전체에 걸쳐 직접 언급하여 맞춤형 느낌을 살리세요.
- 모든 수치는 구체적인 숫자로 작성하세요. 예: "약 40%", "연간 1.2억 원 절감", "3주 → 1주".
- 각 섹션을 충분히 풍부하게 작성하세요. 특히 situation_analysis(5~7문장), solution(7~10문장).
- pain_points는 4~5개, 각 항목은 1~2문장의 구체적인 내용으로 작성하세요.
- expected_benefits의 before/after는 반드시 "숫자+단위" 형식으로 작성하세요.
  올바른 예시: {{"metric": "제안서 작성 시간", "before": "건당 4~8시간", "after": "건당 1시간 미만"}}
  잘못된 예시: {{"metric": "작업 시간", "before": "도입 전", "after": "도입 후"}}
- success_case는 위의 참조 성공 사례 문서에서 가장 유사한 사례를 기반으로 구성하세요.
- 투자 비용은 "문의 후 확정" 방식으로 범위만 제시하세요.
- 문체는 격식체(~합니다) 사용.

JSON으로만 응답하세요:
{{
  "executive_summary": "경영진 요약 (4~5문장, 고객사명·핵심 Pain Point·기대 ROI 포함)",
  "situation_analysis": "현황 분석 (고객사 업종·규모·시장 상황 기반, 5~7문장, 구체적 수치 포함)",
  "pain_points": [
    "Pain Point 1 — 구체적 문제와 비용/시간 손실 수치 포함 (1~2문장)",
    "Pain Point 2 — 구체적 문제와 비용/시간 손실 수치 포함 (1~2문장)",
    "Pain Point 3 — 구체적 문제와 비용/시간 손실 수치 포함 (1~2문장)",
    "Pain Point 4 — 구체적 문제와 비용/시간 손실 수치 포함 (1~2문장)"
  ],
  "solution": "AI Hub 솔루션 제안 (핵심 기능 4~5가지를 각각 구체적으로 설명, 7~10문장)",
  "expected_benefits": [
    {{"metric": "측정 지표명", "before": "숫자+단위 (예: 건당 6시간)", "after": "숫자+단위 (예: 건당 45분)"}},
    {{"metric": "측정 지표명", "before": "숫자+단위", "after": "숫자+단위"}},
    {{"metric": "측정 지표명", "before": "숫자+단위", "after": "숫자+단위"}},
    {{"metric": "측정 지표명", "before": "숫자+단위", "after": "숫자+단위"}}
  ],
  "success_case": {{
    "company": "유사 고객사명 (업종·규모 포함)",
    "issue": "도입 전 구체적 문제 (수치 포함)",
    "solution": "적용한 AI Hub 솔루션 기능",
    "result": "도입 후 성과 (수치 포함)"
  }},
  "implementation_schedule": [
    {{"phase": "1단계", "duration": "N주", "content": "구체적 작업 내용"}},
    {{"phase": "2단계", "duration": "N주", "content": "구체적 작업 내용"}},
    {{"phase": "3단계", "duration": "N주", "content": "구체적 작업 내용"}}
  ],
  "investment": "투자 비용 안내 (규모별 범위 제시, 3~4문장)",
  "email_draft": "영업 담당자 발송용 이메일 초안 (제목 1줄 + 본문 400자 이내, 고객사명 직접 언급)"
}}
"""


# ── DDL (최초 호출 시 테이블 자동 생성 보장) ──────────────────

PROPOSAL_DOCS_DDL = """
CREATE TABLE IF NOT EXISTS sales_proposal_documents (
    id                      SERIAL       PRIMARY KEY,
    industry                VARCHAR(30)  NOT NULL,
    file_name               VARCHAR(255) NOT NULL,
    file_type               VARCHAR(20)  NOT NULL,
    file_bytes              BYTEA        NOT NULL,
    text_content            TEXT         NOT NULL,
    text_length             INTEGER      NOT NULL,
    preview                 TEXT,
    uploaded_by_employee_id VARCHAR(50),
    uploaded_by_name        VARCHAR(100),
    uploaded_by_department  VARCHAR(100),
    is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ,
    CHECK (industry IN ('제조업','유통·서비스','IT'))
)
"""

PROPOSAL_CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS sales_proposal_chunks (
    id          SERIAL  PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES sales_proposal_documents(id) ON DELETE CASCADE,
    industry    VARCHAR(30)  NOT NULL,
    file_name   VARCHAR(255) NOT NULL,
    chunk_index INTEGER      NOT NULL,
    chunk_text  TEXT         NOT NULL,
    embedding   REAL[]       NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
"""

PROPOSAL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_docs_active     ON sales_proposal_documents (is_active, deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_docs_industry   ON sales_proposal_documents (industry)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_docs_created_at ON sales_proposal_documents (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_chunks_doc      ON sales_proposal_chunks (document_id)",
    "CREATE INDEX IF NOT EXISTS idx_sales_proposal_chunks_industry ON sales_proposal_chunks (industry)",
]


# ── 내부 헬퍼 ─────────────────────────────────────────────────

def _ensure_tables(cur) -> None:
    cur.execute(PROPOSAL_DOCS_DDL)
    cur.execute(PROPOSAL_CHUNKS_DDL)
    for ddl in PROPOSAL_INDEXES:
        cur.execute(ddl)


def _format_datetime_value(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text[:19] if len(text) >= 19 else text


def _build_preview(text: str, max_lines: int = 3) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])[:500]


def _serialize_document_row(row) -> dict:
    if not row:
        return {}
    return {
        "document_id": row[0],
        "industry": row[1],
        "file_name": row[2],
        "file_type": row[3],
        "uploaded_at": _format_datetime_value(row[4]),
        "text_length": int(row[5] or 0),
        "preview": row[6] or "",
        "uploaded_by_employee_id": row[7] or "",
        "uploaded_by_name": row[8] or "",
        "uploaded_by_department": row[9] or "",
    }


# ── 공개 서비스 함수: 문서 관리 ───────────────────────────────

def list_proposal_documents(industry: str | None = None) -> list[dict]:
    """활성 제안서 성공 사례 문서 목록 + 청크 수 반환"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_tables(cur)

        base_sql = """
            SELECT d.id, d.industry, d.file_name, d.file_type, d.created_at,
                   d.text_length, d.preview,
                   d.uploaded_by_employee_id, d.uploaded_by_name, d.uploaded_by_department,
                   COUNT(c.id) AS chunk_count
            FROM sales_proposal_documents d
            LEFT JOIN sales_proposal_chunks c ON c.document_id = d.id
            WHERE d.deleted_at IS NULL AND d.is_active = TRUE
        """
        params: tuple = ()
        if industry:
            base_sql += " AND d.industry = %s"
            params = (industry,)
        base_sql += " GROUP BY d.id ORDER BY d.created_at DESC, d.id DESC"

        cur.execute(base_sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    result = []
    for row in rows:
        doc = _serialize_document_row(row[:10])
        doc["chunk_count"] = int(row[10] or 0)
        result.append(doc)
    return result


def save_proposal_document(
    filename: str,
    file_bytes: bytes,
    industry: str,
    uploader: dict | None = None,
) -> dict:
    """
    성공 사례 문서 업로드 처리:
    1. 텍스트 추출
    2. 청크 분할
    3. 배치 임베딩 생성 (OpenAI text-embedding-3-small)
    4. 문서 메타 + 청크 벡터 DB 저장
    """
    if industry not in ALLOWED_INDUSTRIES:
        raise ValueError("industry는 '제조업', '유통·서비스', 'IT' 중 하나여야 합니다.")
    if not file_bytes:
        raise ValueError("파일이 비어 있습니다.")

    extracted_text = extract_document_text(filename, file_bytes)
    safe_filename = _sanitize_filename(filename)
    file_type = Path(safe_filename).suffix.lower().lstrip(".")
    preview = _build_preview(extracted_text)

    chunks = _chunk_text(extracted_text, chunk_size=800)
    if not chunks:
        raise ValueError("문서에서 텍스트를 추출하지 못했습니다.")

    embeddings = embed_texts_batch(chunks)

    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_tables(cur)

        cur.execute(
            """
            INSERT INTO sales_proposal_documents (
                industry, file_name, file_type, file_bytes, text_content, text_length, preview,
                uploaded_by_employee_id, uploaded_by_name, uploaded_by_department, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id, industry, file_name, file_type, created_at, text_length, preview,
                      uploaded_by_employee_id, uploaded_by_name, uploaded_by_department
            """,
            (
                industry,
                safe_filename,
                file_type,
                file_bytes,
                extracted_text,
                len(extracted_text),
                preview,
                (uploader or {}).get("employee_id"),
                (uploader or {}).get("name"),
                (uploader or {}).get("department"),
            ),
        )
        doc_row = cur.fetchone()
        document_id = doc_row[0]

        for chunk_index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            cur.execute(
                """
                INSERT INTO sales_proposal_chunks
                    (document_id, industry, file_name, chunk_index, chunk_text, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (document_id, industry, safe_filename, chunk_index, chunk_text, embedding),
            )

    finally:
        cur.close()
        conn.close()

    result = _serialize_document_row(doc_row)
    result["chunk_count"] = len(chunks)
    return result


def delete_proposal_document(document_id: int) -> dict:
    """문서 삭제 — ON DELETE CASCADE로 청크도 자동 삭제"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_tables(cur)
        cur.execute(
            "SELECT id, file_name FROM sales_proposal_documents WHERE id = %s AND deleted_at IS NULL",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("삭제할 제안서 문서를 찾을 수 없습니다.")

        cur.execute("DELETE FROM sales_proposal_documents WHERE id = %s", (document_id,))
    finally:
        cur.close()
        conn.close()

    remaining = list_proposal_documents()
    return {
        "message": f"{row[1]} 문서를 삭제했습니다.",
        "deleted_document_id": row[0],
        "deleted_file_name": row[1],
        "items": remaining,
    }


# ── 공개 서비스 함수: 제안서 생성 ─────────────────────────────

def _retrieve_success_cases(
    industry: str,
    query: str,
    top_k: int = 3,
) -> tuple[str, list[str]]:
    """
    업종 필터 + 벡터 유사도로 관련 성공 사례 청크 top_k 선택.
    Returns: (컨텍스트 문자열, 참조 파일명 목록)
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_tables(cur)
        cur.execute(
            """
            SELECT c.file_name, c.chunk_text, c.embedding
            FROM sales_proposal_chunks c
            JOIN sales_proposal_documents d ON d.id = c.document_id
            WHERE d.deleted_at IS NULL AND d.is_active = TRUE
              AND c.industry = %s
            ORDER BY c.document_id, c.chunk_index
            """,
            (industry,),
        )
        chunk_rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if not chunk_rows:
        return "", []

    question_embedding = embed_text(query)

    chunks = [
        {
            "file_name": row[0],
            "chunk_text": row[1],
            "embedding": list(row[2]),
        }
        for row in chunk_rows
    ]
    top_chunks = select_top_chunks_by_vector(question_embedding, chunks, top_k=top_k)

    context = "\n\n".join(
        f"[문서: {item['file_name']}]\n{item['chunk_text']}"
        for item in top_chunks
    )
    sources = list(dict.fromkeys(item["file_name"] for item in top_chunks))
    return context, sources


def generate_proposal(
    company_name: str,
    industry: str,
    company_size: str,
    key_needs: str,
) -> dict:
    """
    고객사 맞춤형 영업 제안서 초안을 생성합니다.
    업종 필터 + 벡터 유사도로 성공 사례를 검색하여 프롬프트에 주입합니다.
    """
    if industry not in ALLOWED_INDUSTRIES:
        raise ValueError("industry는 '제조업', '유통·서비스', 'IT' 중 하나여야 합니다.")

    preset = INDUSTRY_PRESETS[industry]

    # 고객 니즈 + 업종 focus를 query로 사용
    query = f"{industry} {preset['focus']} {key_needs}".strip()
    cases_text, sources = _retrieve_success_cases(industry, query, top_k=3)

    if not cases_text:
        raise RuntimeError(
            f"'{industry}' 업종의 성공 사례 문서가 없습니다. "
            "먼저 성공 사례 문서를 업로드해 주세요."
        )

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": PROPOSAL_PROMPT.format(
                company_name=company_name,
                industry=industry,
                company_size=company_size,
                key_needs=key_needs,
                structure=preset["structure"],
                focus=preset["focus"],
                success_cases=cases_text,
            ),
        }],
        max_tokens=3000,
    )

    payload = json.loads(res.choices[0].message.content)
    payload["sources"] = sources
    return payload
