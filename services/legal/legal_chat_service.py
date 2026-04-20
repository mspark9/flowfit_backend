"""
법무 챗봇 서비스 — 벡터 임베딩 기반 진짜 RAG
문서 업로드 시 청크별 임베딩 생성·저장,
질문 시 코사인 유사도로 관련 청크 검색 후 GPT 답변
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

# ── DDL ──────────────────────────────────────────────────────

# 문서 메타데이터 테이블 (파일 원본 보관)
LEGAL_DOCUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS legal_documents (
    id                      SERIAL PRIMARY KEY,
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
    deleted_at              TIMESTAMPTZ
)
"""

# 청크 + 임베딩 벡터 테이블 (RAG 핵심)
LEGAL_CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS legal_document_chunks (
    id          SERIAL  PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES legal_documents(id) ON DELETE CASCADE,
    file_name   VARCHAR(255) NOT NULL,
    chunk_index INTEGER      NOT NULL,
    chunk_text  TEXT         NOT NULL,
    embedding   REAL[]       NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
)
"""

LEGAL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_legal_docs_active ON legal_documents (is_active, deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_legal_docs_created_at ON legal_documents (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_legal_chunks_doc_id ON legal_document_chunks (document_id)",
]

# 법무 전용 시스템 프롬프트
LEGAL_SYSTEM_PROMPT = (
    "당신은 사내 법무·컴플라이언스 전문 챗봇입니다. "
    "제공된 법률 문서·사규·계약서 내용만 근거로 답변하세요. "
    "법률 용어는 쉽게 풀어서 설명하고, 문서에 없는 내용은 추측하지 마세요. "
    "필요 시 법무팀 담당자에게 확인을 권고하세요. "
    "응답은 JSON만 반환하세요."
)


# ── 내부 헬퍼 ─────────────────────────────────────────────────

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


def _ensure_tables(cur) -> None:
    cur.execute(LEGAL_DOCUMENTS_DDL)
    cur.execute(LEGAL_CHUNKS_DDL)
    for ddl in LEGAL_INDEXES:
        cur.execute(ddl)


def _serialize_document_row(row) -> dict:
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


# ── 공개 서비스 함수 ──────────────────────────────────────────

def list_active_legal_documents() -> list[dict]:
    """활성 법무 문서 목록 + 청크 수 반환"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_tables(cur)
        cur.execute(
            """
            SELECT d.id, d.file_name, d.file_type, d.created_at, d.text_length, d.preview,
                   d.uploaded_by_employee_id, d.uploaded_by_name, d.uploaded_by_department,
                   COUNT(c.id) AS chunk_count
            FROM legal_documents d
            LEFT JOIN legal_document_chunks c ON c.document_id = d.id
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
        doc = _serialize_document_row(row[:9])
        doc["chunk_count"] = int(row[9] or 0)
        result.append(doc)
    return result


def save_legal_document(
    filename: str, file_bytes: bytes, uploader: dict | None = None
) -> dict:
    """
    법무 문서 업로드 처리:
    1. 텍스트 추출
    2. 청크 분할
    3. 배치 임베딩 생성 (OpenAI text-embedding-3-small)
    4. 문서 메타 + 청크 벡터 DB 저장
    """
    if not file_bytes:
        raise ValueError("파일이 비어 있습니다.")

    # 텍스트 추출
    extracted_text = extract_document_text(filename, file_bytes)
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
        _ensure_tables(cur)

        # 문서 메타 저장
        cur.execute(
            """
            INSERT INTO legal_documents (
                file_name, file_type, file_bytes, text_content, text_length, preview,
                uploaded_by_employee_id, uploaded_by_name, uploaded_by_department, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id, file_name, file_type, created_at, text_length, preview,
                      uploaded_by_employee_id, uploaded_by_name, uploaded_by_department
            """,
            (
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

        # 청크 + 임베딩 저장
        for chunk_index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            cur.execute(
                """
                INSERT INTO legal_document_chunks
                    (document_id, file_name, chunk_index, chunk_text, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (document_id, safe_filename, chunk_index, chunk_text, embedding),
            )

    finally:
        cur.close()
        conn.close()

    result = _serialize_document_row(doc_row)
    result["chunk_count"] = len(chunks)
    return result


def delete_legal_document(document_id: int) -> dict:
    """문서 삭제 — ON DELETE CASCADE로 청크도 자동 삭제"""
    conn = get_connection()
    cur = conn.cursor()

    try:
        _ensure_tables(cur)
        cur.execute(
            "SELECT id, file_name FROM legal_documents WHERE id = %s AND deleted_at IS NULL",
            (document_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("삭제할 법무 문서를 찾을 수 없습니다.")

        # 청크는 ON DELETE CASCADE로 자동 삭제
        cur.execute("DELETE FROM legal_documents WHERE id = %s", (document_id,))

    finally:
        cur.close()
        conn.close()

    remaining = list_active_legal_documents()
    return {
        "message": f"{row[1]} 문서를 삭제했습니다.",
        "deleted_document_id": row[0],
        "deleted_file_name": row[1],
        "items": remaining,
    }


def answer_legal_question(question: str) -> dict:
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
        _ensure_tables(cur)

        # 활성 문서 목록 확인
        cur.execute(
            """
            SELECT COUNT(*) FROM legal_documents
            WHERE deleted_at IS NULL AND is_active = TRUE
            """
        )
        doc_count = cur.fetchone()[0]
        if not doc_count:
            raise RuntimeError("먼저 법률 문서(hwp, docx, pdf)를 업로드해 주세요.")

        # 활성 문서의 모든 청크 + 임베딩 로드
        cur.execute(
            """
            SELECT c.file_name, c.chunk_text, c.embedding
            FROM legal_document_chunks c
            JOIN legal_documents d ON d.id = c.document_id
            WHERE d.deleted_at IS NULL AND d.is_active = TRUE
            ORDER BY c.document_id, c.chunk_index
            """
        )
        chunk_rows = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    if not chunk_rows:
        raise RuntimeError("업로드된 문서의 청크가 없습니다. 문서를 다시 업로드해 주세요.")

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

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": LEGAL_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"[참조 문서]\n{', '.join(source_files)}\n\n"
                    f"[사용자 질문]\n{question}\n\n"
                    f"[관련 문서 내용 (벡터 유사도 상위 5개 청크)]\n{context}\n\n"
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
        "answer": payload.get("answer", "법무 문서에서 답변을 생성하지 못했습니다."),
        "evidence": [str(e).strip() for e in evidence if str(e).strip()][:3],
        "sources": source_files,
    }
