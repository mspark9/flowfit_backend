"""
개발/IT 인프라 문서 챗봇 서비스 — 벡터 임베딩 기반 RAG
hr_regulation_service 구조와 동일하게 구현
"""
import json
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
    embed_texts_batch,
    embed_text,
    select_top_chunks_by_vector,
)

client = OpenAI(api_key=settings.openai_api_key)

# ── DDL ───────────────────────────────────────────────────────────────────────

DEV_DOCS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS dev_documents (
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

DEV_DOCS_CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS dev_document_chunks (
    id          SERIAL      PRIMARY KEY,
    document_id INTEGER     NOT NULL REFERENCES dev_documents(id) ON DELETE CASCADE,
    file_name   VARCHAR(255) NOT NULL,
    chunk_index INTEGER      NOT NULL,
    chunk_text  TEXT         NOT NULL,
    embedding   REAL[]       NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
"""

DEV_DOCS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_dev_docs_active ON dev_documents (is_active, deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_dev_docs_created_at ON dev_documents (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_dev_chunks_doc_id ON dev_document_chunks (document_id)",
]

SYSTEM_PROMPT = (
    "당신은 개발/IT 인프라 전문 챗봇입니다. "
    "반드시 제공된 기술 문서 내용만 근거로 답변하세요. "
    "문서에 없는 내용은 추측하지 말고, 문서에서 확인되지 않는다고 명확히 말하세요. "
    "응답은 JSON만 반환하세요."
)

# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _ensure_tables(cur) -> None:
    cur.execute(DEV_DOCS_TABLE_DDL)
    cur.execute(DEV_DOCS_CHUNKS_DDL)
    for ddl in DEV_DOCS_INDEXES:
        cur.execute(ddl)


def _build_preview(text: str, max_lines: int = 3) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])[:500]


def _serialize_doc_row(row) -> dict:
    if not row:
        return {}
    return {
        "document_id": row[0],
        "file_name": row[1],
        "file_type": row[2],
        "uploaded_at": str(row[3]) if row[3] else "",
        "text_length": int(row[4] or 0),
        "preview": row[5] or "",
        "uploaded_by_employee_id": row[6] or "",
        "uploaded_by_name": row[7] or "",
        "uploaded_by_department": row[8] or "",
    }


# ── 공개 서비스 함수 ──────────────────────────────────────────────────────────

def list_dev_documents() -> list[dict]:
    """활성 문서 목록 + 청크 수 반환"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_tables(cur)
        cur.execute(
            """
            SELECT d.id, d.file_name, d.file_type, d.created_at, d.text_length, d.preview,
                   d.uploaded_by_employee_id, d.uploaded_by_name, d.uploaded_by_department,
                   COUNT(c.id) AS chunk_count
            FROM dev_documents d
            LEFT JOIN dev_document_chunks c ON c.document_id = d.id
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
        doc = _serialize_doc_row(row[:9])
        doc["chunk_count"] = int(row[9] or 0)
        result.append(doc)
    return result


def save_dev_document(filename: str, file_bytes: bytes, uploader: dict | None = None) -> dict:
    """문서 업로드 → 텍스트 추출 → 청크 임베딩 → DB 저장"""
    if not file_bytes:
        raise ValueError("파일이 비어 있습니다.")

    extracted_text = extract_document_text(filename, file_bytes)
    safe_filename = _sanitize_filename(filename)
    file_type = Path(safe_filename).suffix.lower().lstrip(".")
    preview = _build_preview(extracted_text)
    chunks = _chunk_text(extracted_text, chunk_size=800)
    embeddings = embed_texts_batch(chunks)

    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_tables(cur)
        cur.execute(
            """
            INSERT INTO dev_documents (
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

        for chunk_index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            cur.execute(
                """
                INSERT INTO dev_document_chunks
                    (document_id, file_name, chunk_index, chunk_text, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (document_id, safe_filename, chunk_index, chunk_text, embedding),
            )
    finally:
        cur.close()
        conn.close()

    result = _serialize_doc_row(doc_row)
    result["chunk_count"] = len(chunks)
    return result


def save_dev_documents(files: list[tuple[str, bytes]], uploader: dict | None = None) -> list[dict]:
    """다수 파일 업로드"""
    if not files:
        raise ValueError("업로드할 파일이 없습니다.")
    return [save_dev_document(filename, file_bytes, uploader=uploader) for filename, file_bytes in files]


def delete_dev_document(document_id: int) -> dict:
    """문서 삭제 (ON DELETE CASCADE로 청크 자동 삭제)"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_tables(cur)
        cur.execute(
            "SELECT id, file_name FROM dev_documents WHERE id = %s AND deleted_at IS NULL",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("삭제할 문서를 찾을 수 없습니다.")
        cur.execute("DELETE FROM dev_documents WHERE id = %s", (document_id,))
    finally:
        cur.close()
        conn.close()

    return {
        "message": f"{row[1]} 문서를 삭제했습니다.",
        "deleted_document_id": row[0],
        "deleted_file_name": row[1],
        "items": list_dev_documents(),
    }


def answer_dev_question(question: str) -> dict:
    """벡터 RAG 질의응답"""
    if not question.strip():
        raise ValueError("질문을 입력해 주세요.")

    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_tables(cur)
        cur.execute(
            "SELECT COUNT(*) FROM dev_documents WHERE deleted_at IS NULL AND is_active = TRUE"
        )
        if not cur.fetchone()[0]:
            raise RuntimeError("먼저 기술 문서(PDF, DOCX, HWP)를 업로드해 주세요.")

        cur.execute(
            """
            SELECT c.file_name, c.chunk_text, c.embedding
            FROM dev_document_chunks c
            JOIN dev_documents d ON d.id = c.document_id
            WHERE d.deleted_at IS NULL AND d.is_active = TRUE
            ORDER BY c.document_id, c.chunk_index
            """
        )
        chunk_rows = cur.fetchall()

        cur.execute(
            "SELECT id, file_name FROM dev_documents WHERE deleted_at IS NULL AND is_active = TRUE ORDER BY created_at DESC"
        )
        doc_rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if not chunk_rows:
        raise RuntimeError("업로드된 문서의 청크가 없습니다. 문서를 삭제 후 다시 업로드해 주세요.")

    question_embedding = embed_text(question)
    chunks = [{"file_name": r[0], "chunk_text": r[1], "embedding": list(r[2])} for r in chunk_rows]
    top_chunks = select_top_chunks_by_vector(question_embedding, chunks, top_k=5)

    context = "\n\n".join(
        f"[문서: {item['file_name']}]\n{item['chunk_text']}" for item in top_chunks
    )
    file_names = ", ".join(row[1] for row in doc_rows)
    source_files = list(dict.fromkeys(item["file_name"] for item in top_chunks))

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"[업로드 문서명]\n{file_names}\n\n"
                    f"[사용자 질문]\n{question}\n\n"
                    f"[관련 문서 내용 (상위 5개 청크)]\n{context}\n\n"
                    "[반환 형식]\n"
                    '{"answer": "한국어 답변", "evidence": ["근거 문장 1", "근거 문장 2"]}'
                ),
            },
        ],
        max_tokens=1200,
        temperature=0.2,
    )

    payload = json.loads(response.choices[0].message.content)
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []

    return {
        "answer": payload.get("answer", "문서에서 답변을 생성하지 못했습니다."),
        "evidence": [str(e).strip() for e in evidence if str(e).strip()][:3],
        "sources": source_files,
        "file_name": file_names,
        "document_ids": [row[0] for row in doc_rows],
    }
