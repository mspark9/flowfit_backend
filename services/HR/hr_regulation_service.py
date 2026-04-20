"""
인사 규정 서비스 - 벡터 임베딩 기반 진짜 RAG (legal_chat_service 구조 참고)
문서 업로드 시 청크별 임베딩 생성·저장,
질문 시 코사인 유사도로 관련 청크 검색 후 GPT 답변
규정 충돌 감지는 기존 조문 비교 방식 유지
"""
import json
import re
from datetime import datetime
from itertools import combinations
from pathlib import Path

from openai import OpenAI

from config import settings
from database import get_connection
from services.common.document_parser import (
    _sanitize_filename,
    extract_document_text as extract_regulation_text,
)
from services.common.rag_utils import (
    _chunk_text,
    embed_texts_batch,
    embed_text,
    select_top_chunks_by_vector,
)

client = OpenAI(api_key=settings.openai_api_key)


# DDL 

# 문서 메타데이터 테이블 (원본 파일 미저장 - 벡터만 보관)
REGULATION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS hr_regulation_documents (
    id                      SERIAL          PRIMARY KEY,
    file_name               VARCHAR(255)    NOT NULL,
    file_type               VARCHAR(20)     NOT NULL,
    text_content            TEXT            NOT NULL,
    text_length             INTEGER         NOT NULL,
    preview                 TEXT,
    uploaded_by_employee_id VARCHAR(50),
    uploaded_by_name        VARCHAR(100),
    uploaded_by_department  VARCHAR(100),
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ
)
"""

# 청크 + 임베딩 벡터 테이블 (RAG 핵심)
REGULATION_CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS hr_regulation_document_chunks (
    id          SERIAL  PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES hr_regulation_documents(id) ON DELETE CASCADE,
    file_name   VARCHAR(255) NOT NULL,
    chunk_index INTEGER      NOT NULL,
    chunk_text  TEXT         NOT NULL,
    embedding   REAL[]       NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
"""

REGULATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_hr_reg_docs_active ON hr_regulation_documents (is_active, deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_hr_reg_docs_created_at ON hr_regulation_documents (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_hr_reg_chunks_doc_id ON hr_regulation_document_chunks (document_id)",
]

# 인사 규정 전용 시스템 프롬프트
HR_REGULATION_SYSTEM_PROMPT = (
    "당신은 사내 인사 규정 안내 챗봇입니다. "
    "반드시 제공된 규정 문서 내용만 근거로 답변하세요. "
    "문서에 없는 내용은 추측하지 말고, 문서에서 확인되지 않는다고 분명히 말하세요. "
    "응답은 JSON만 반환하세요."
)

CLAUSE_PATTERN = re.compile(r"^제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]+\))?", re.MULTILINE)



# 내부 헬퍼
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


def _ensure_regulation_table(cur) -> None:
    cur.execute(REGULATION_TABLE_DDL)
    cur.execute(REGULATION_CHUNKS_DDL)
    for ddl in REGULATION_INDEXES:
        cur.execute(ddl)
    # 마이그레이션: 구 스키마의 file_bytes 컬럼 제거 (벡터 RAG 방식으로 전환됨)
    cur.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'hr_regulation_documents'
                AND column_name = 'file_bytes'
            ) THEN
                ALTER TABLE hr_regulation_documents DROP COLUMN file_bytes;
            END IF;
        END $$;
        """
    )


def _serialize_status_row(row) -> dict:
    if not row:
        return {
            "ready": False,
            "document_id": None,
            "file_name": "",
            "file_type": "",
            "uploaded_at": "",
            "text_length": 0,
            "preview": "",
            "uploaded_by_employee_id": "",
            "uploaded_by_name": "",
            "uploaded_by_department": "",
        }
    return {
        "ready": True,
        "document_id": row[0],
        "file_name": row[1],
        "file_type": row[2],
        "uploaded_at": _format_datetime_value(row[3]),
        "text_length": int(row[4] or 0),
        "preview": row[5] or "",
        "uploaded_by_employee_id": row[6] or "",
        "uploaded_by_name": row[7] or "",
        "uploaded_by_department": row[8] or "",
    }


def _fetch_active_document_row(cur):
    cur.execute(
        """
        SELECT id, file_name, file_type, created_at, text_length, preview,
               uploaded_by_employee_id, uploaded_by_name, uploaded_by_department
        FROM hr_regulation_documents
        WHERE deleted_at IS NULL AND is_active = TRUE
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    return cur.fetchone()



# 공개 서비스 함수
def list_active_regulation_documents() -> list[dict]:
    """활성 인사 규정 문서 목록 + 청크 수 반환"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_regulation_table(cur)
        cur.execute(
            """
            SELECT d.id, d.file_name, d.file_type, d.created_at, d.text_length, d.preview,
                   d.uploaded_by_employee_id, d.uploaded_by_name, d.uploaded_by_department,
                   COUNT(c.id) AS chunk_count
            FROM hr_regulation_documents d
            LEFT JOIN hr_regulation_document_chunks c ON c.document_id = d.id
            WHERE d.deleted_at IS NULL AND d.is_active = TRUE
            GROUP BY d.id
            ORDER BY d.created_at DESC, d.id DESC
            """
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    result = []
    for row in rows:
        doc = _serialize_status_row(row[:9])
        doc["chunk_count"] = int(row[9] or 0)
        result.append(doc)
    return result


def get_regulation_status() -> dict:
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_regulation_table(cur)
        row = _fetch_active_document_row(cur)
    finally:
        cur.close()
        conn.close()

    return _serialize_status_row(row)


def save_regulation_document(filename: str, file_bytes: bytes, uploader: dict | None = None) -> dict:
    """
    인사 규정 문서 업로드 처리:
    1. 텍스트 추출
    2. 청크 분할
    3. 배치 임베딩 생성 (OpenAI text-embedding-3-small)
    4. 문서 메타 + 청크 벡터 DB 저장
    """
    if not file_bytes:
        raise ValueError("파일이 비어 있습니다.")

    extracted_text = extract_regulation_text(filename, file_bytes)
    safe_filename = _sanitize_filename(filename)
    file_type = Path(safe_filename).suffix.lower().lstrip(".")
    preview = _build_preview(extracted_text)

    # 청크 분할
    chunks = _chunk_text(extracted_text, chunk_size=800)

    # 배치 임베딩 생성 (API 호출 최소화)
    embeddings = embed_texts_batch(chunks)

    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_regulation_table(cur)

        # 문서 메타 저장 (원본 파일 바이너리 제외)
        cur.execute(
            """
            INSERT INTO hr_regulation_documents (
                file_name, file_type, text_content, text_length, preview,
                uploaded_by_employee_id, uploaded_by_name, uploaded_by_department, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id, file_name, file_type, created_at, text_length, preview,
                      uploaded_by_employee_id, uploaded_by_name, uploaded_by_department
            """,
            (
                safe_filename,
                file_type,
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

        # 청크 + 임베딩 저장
        for chunk_index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            cur.execute(
                """
                INSERT INTO hr_regulation_document_chunks
                    (document_id, file_name, chunk_index, chunk_text, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (document_id, safe_filename, chunk_index, chunk_text, embedding),
            )

    finally:
        cur.close()
        conn.close()

    result = _serialize_status_row(doc_row)
    result["chunk_count"] = len(chunks)
    return result


def save_regulation_documents(files: list[tuple[str, bytes]], uploader: dict | None = None) -> list[dict]:
    """다수 파일 업로드 - 각 파일에 대해 청크 임베딩 생성 후 저장"""
    if not files:
        raise ValueError("업로드할 파일이 없습니다.")

    results = []
    for filename, file_bytes in files:
        result = save_regulation_document(filename, file_bytes, uploader=uploader)
        results.append(result)
    return results


def delete_regulation_document(document_id: int) -> dict:
    """문서 삭제 - ON DELETE CASCADE로 청크도 자동 삭제"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_regulation_table(cur)
        cur.execute(
            "SELECT id, file_name FROM hr_regulation_documents WHERE id = %s AND deleted_at IS NULL",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("삭제할 규정 문서를 찾을 수 없습니다.")

        # 청크는 ON DELETE CASCADE로 자동 삭제
        cur.execute("DELETE FROM hr_regulation_documents WHERE id = %s", (document_id,))

    finally:
        cur.close()
        conn.close()

    remaining = list_active_regulation_documents()
    return {
        "message": f"{row[1]} 문서를 삭제했습니다.",
        "deleted_document_id": row[0],
        "deleted_file_name": row[1],
        "items": remaining,
    }


def delete_current_regulation_document() -> dict:
    """현재 활성 문서 삭제 후 이전 문서 복원"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_regulation_table(cur)
        active_row = _fetch_active_document_row(cur)
        if not active_row:
            raise ValueError("삭제할 규정 문서가 없습니다.")

        deleted_document_id = active_row[0]
        deleted_file_name = active_row[1]

        cur.execute(
            """
            UPDATE hr_regulation_documents
               SET is_active = FALSE,
                   deleted_at = NOW(),
                   updated_at = NOW()
             WHERE id = %s
            """,
            (deleted_document_id,),
        )

        cur.execute(
            """
            SELECT id
            FROM hr_regulation_documents
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        )
        fallback = cur.fetchone()
        if fallback:
            cur.execute(
                """
                UPDATE hr_regulation_documents
                   SET is_active = TRUE,
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (fallback[0],),
            )

        next_status = _serialize_status_row(_fetch_active_document_row(cur))
    finally:
        cur.close()
        conn.close()

    return {
        "message": f"{deleted_file_name} 문서를 삭제했습니다.",
        "deleted_document_id": deleted_document_id,
        "deleted_file_name": deleted_file_name,
        "current_status": next_status,
    }


# 규정 충돌 감지 (조문 비교 방식 유지)
def _normalize_clause_body(text: str) -> str:
    normalized = re.sub(r"\s+", "", text or "")
    normalized = re.sub(r"[^\w가-힣]", "", normalized)
    return normalized.lower()


def _extract_regulation_clauses(text: str) -> list[dict]:
    matches = list(CLAUSE_PATTERN.finditer(text or ""))
    if not matches:
        return []

    clauses = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = (text[start:end] or "").strip()
        if not chunk:
            continue

        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue

        title = lines[0][:160]
        body = "\n".join(lines[1:]).strip()
        normalized_body = _normalize_clause_body(body)
        if not normalized_body:
            continue

        clauses.append(
            {
                "title": title,
                "body": body,
                "normalized_body": normalized_body,
            }
        )

    return clauses


def get_regulation_conflicts() -> dict:
    """활성 문서들 간 조문 충돌 감지 (키워드 비교 방식 유지)"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_regulation_table(cur)
        cur.execute(
            """
            SELECT id, file_name, text_content
            FROM hr_regulation_documents
            WHERE deleted_at IS NULL AND is_active = TRUE
            ORDER BY created_at DESC, id DESC
            """
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    documents = [
        {"document_id": row[0], "file_name": row[1], "text_content": (row[2] or "").strip()}
        for row in rows
        if (row[2] or "").strip()
    ]

    if not documents:
        raise RuntimeError("먼저 인사 규정 문서(hwp, docx, pdf)를 업로드해 주세요.")

    if len(documents) < 2:
        return {"has_conflict": False, "items": []}

    conflict_items = []
    for left_doc, right_doc in combinations(documents, 2):
        left_clauses = {
            clause["title"]: clause for clause in _extract_regulation_clauses(left_doc["text_content"])
        }
        right_clauses = {
            clause["title"]: clause for clause in _extract_regulation_clauses(right_doc["text_content"])
        }

        shared_titles = sorted(set(left_clauses) & set(right_clauses))
        conflicting_titles = [
            title
            for title in shared_titles
            if left_clauses[title]["normalized_body"] != right_clauses[title]["normalized_body"]
        ]

        if conflicting_titles:
            conflict_items.append(
                {
                    "file_names": [left_doc["file_name"], right_doc["file_name"]],
                    "clause_titles": conflicting_titles[:5],
                    "clause_count": len(conflicting_titles),
                }
            )

    return {
        "has_conflict": bool(conflict_items),
        "items": conflict_items,
    }


# RAG 질의응답 (벡터 코사인 유사도 방식)

def answer_regulation_question(question: str) -> dict:
    """
    벡터 RAG 질의응답:
    1. 질문 임베딩 생성
    2. DB에서 모든 활성 청크 로드
    3. 코사인 유사도로 관련 청크 top-5 선택
    4. GPT-4o-mini에 컨텍스트로 전달 후 답변 생성
    """
    if not question.strip():
        raise ValueError("질문을 입력해 주세요.")

    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_regulation_table(cur)

        # 활성 문서 수 확인
        cur.execute(
            """
            SELECT COUNT(*) FROM hr_regulation_documents
            WHERE deleted_at IS NULL AND is_active = TRUE
            """
        )
        doc_count = cur.fetchone()[0]
        if not doc_count:
            raise RuntimeError("먼저 인사 규정 문서(hwp, docx, pdf)를 업로드해 주세요.")

        # 활성 문서의 모든 청크 + 임베딩 로드
        cur.execute(
            """
            SELECT c.file_name, c.chunk_text, c.embedding
            FROM hr_regulation_document_chunks c
            JOIN hr_regulation_documents d ON d.id = c.document_id
            WHERE d.deleted_at IS NULL AND d.is_active = TRUE
            ORDER BY c.document_id, c.chunk_index
            """
        )
        chunk_rows = cur.fetchall()

        # 활성 문서명 목록
        cur.execute(
            """
            SELECT id, file_name FROM hr_regulation_documents
            WHERE deleted_at IS NULL AND is_active = TRUE
            ORDER BY created_at DESC, id DESC
            """
        )
        doc_rows = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    if not chunk_rows:
        raise RuntimeError(
            "업로드된 문서의 청크가 없습니다. "
            "기존 문서를 삭제 후 다시 업로드해 주세요."
        )

    # 질문 임베딩
    question_embedding = embed_text(question)

    # 벡터 유사도로 관련 청크 선택
    chunks = [
        {
            "file_name": row[0],
            "chunk_text": row[1],
            "embedding": list(row[2]),  # pg8000 REAL[] → list
        }
        for row in chunk_rows
    ]
    top_chunks = select_top_chunks_by_vector(question_embedding, chunks, top_k=5)

    # GPT 컨텍스트 구성
    context = "\n\n".join(
        f"[문서: {item['file_name']}]\n{item['chunk_text']}"
        for item in top_chunks
    )
    source_files = list(dict.fromkeys(item["file_name"] for item in top_chunks))
    file_names = ", ".join(row[1] for row in doc_rows)
    document_ids = [row[0] for row in doc_rows]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": HR_REGULATION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"[업로드 문서명]\n{file_names}\n\n"
                    f"[사용자 질문]\n{question}\n\n"
                    f"[관련 규정 내용 (벡터 유사도 상위 5개 청크)]\n{context}\n\n"
                    "[반환 형식]\n"
                    "{\n"
                    '  "answer": "질문에 대한 한국어 답변",\n'
                    '  "evidence": ["답변 근거가 된 문장 또는 핵심 구절", "..."]\n'
                    "}"
                ),
            },
        ],
        max_tokens=1200,
        temperature=0.2,
    )

    payload = json.loads(response.choices[0].message.content)
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []

    return {
        "answer": payload.get("answer", "규정 문서에서 답변을 생성하지 못했습니다."),
        "evidence": [str(item).strip() for item in evidence if str(item).strip()][:3],
        "sources": source_files,
        "file_name": file_names,
        "document_ids": document_ids,
    }
