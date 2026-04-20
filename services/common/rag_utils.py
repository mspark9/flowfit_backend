"""
공통 RAG 유틸리티 — 텍스트 청킹 / 토크나이징 / 키워드 검색 / 벡터 임베딩
hr_regulation_service : 키워드 기반 검색 사용
legal_chat_service    : 벡터 임베딩 기반 진짜 RAG 사용
"""
import re

import numpy as np
from openai import OpenAI

from config import settings

# OpenAI 임베딩 클라이언트 (legal RAG 전용)
_embed_client = OpenAI(api_key=settings.openai_api_key)

# 임베딩 모델 및 차원
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def _chunk_text(text: str, chunk_size: int = 1200) -> list[str]:
    """텍스트를 paragraph 단위로 분할하여 chunk_size 이하 청크 목록 반환"""
    paragraphs = [paragraph.strip() for paragraph in text.split("\n") if paragraph.strip()]
    chunks = []
    current = []
    current_len = 0

    for paragraph in paragraphs:
        if current and current_len + len(paragraph) + 1 > chunk_size:
            chunks.append("\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
            continue

        current.append(paragraph)
        current_len += len(paragraph) + 1

    if current:
        chunks.append("\n".join(current))

    return chunks or [text[:chunk_size]]


def _tokenize(text: str) -> list[str]:
    """한글·영문·숫자 2글자 이상 토큰 추출"""
    return re.findall(r"[0-9A-Za-z가-힣]{2,}", text.lower())


def _select_relevant_chunks(text: str, question: str, top_k: int = 5) -> list[str]:
    """단일 문서 텍스트에서 질문과 관련도 높은 청크 top_k개 선택"""
    chunks = _chunk_text(text)
    tokens = _tokenize(question)
    scored = []

    for index, chunk in enumerate(chunks):
        lowered = chunk.lower()
        score = 0
        for token in tokens:
            score += lowered.count(token) * 3
        if question.strip() and question.strip().lower() in lowered:
            score += 10
        score -= index * 0.01
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [chunk for score, chunk in scored[:top_k] if score > 0]
    return selected or chunks[: min(top_k, len(chunks))]


def _select_relevant_document_chunks(
    documents: list[dict], question: str, top_k: int = 5
) -> list[dict]:
    """여러 문서에서 질문과 관련도 높은 청크 top_k개 선택.
    각 document dict에는 'file_name' 과 'text_content' 키가 있어야 함."""
    tokens = _tokenize(question)
    scored = []

    for doc_index, document in enumerate(documents):
        chunks = _chunk_text(document["text_content"])
        for chunk_index, chunk in enumerate(chunks):
            lowered = chunk.lower()
            score = 0
            for token in tokens:
                score += lowered.count(token) * 3
            if question.strip() and question.strip().lower() in lowered:
                score += 10
            score -= doc_index * 0.01
            score -= chunk_index * 0.001
            scored.append(
                (
                    score,
                    {
                        "file_name": document["file_name"],
                        "chunk": chunk,
                    },
                )
            )

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [item for score, item in scored[:top_k] if score > 0]
    return selected or [item for _, item in scored[: min(top_k, len(scored))]]


# ── 벡터 임베딩 (진짜 RAG용) ─────────────────────────────────

def embed_text(text: str) -> list[float]:
    """단일 텍스트 → OpenAI 임베딩 벡터 (1536차원)"""
    response = _embed_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text.replace("\n", " "),  # 줄바꿈 제거 권장
    )
    return response.data[0].embedding


def embed_texts_batch(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    """다수 텍스트 배치 임베딩 — API 호출 횟수 최소화"""
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = [t.replace("\n", " ") for t in texts[i : i + batch_size]]
        response = _embed_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
        )
        # API 응답은 index 순서 보장 안 될 수 있으므로 정렬
        sorted_data = sorted(response.data, key=lambda d: d.index)
        all_embeddings.extend([d.embedding for d in sorted_data])
    return all_embeddings


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """두 벡터의 코사인 유사도 계산 (-1 ~ 1)"""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def select_top_chunks_by_vector(
    question_embedding: list[float],
    chunk_rows: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """
    벡터 유사도로 관련 청크 top_k 선택.
    chunk_rows 각 항목: {'file_name': str, 'chunk_text': str, 'embedding': list[float]}
    """
    scored = []
    for row in chunk_rows:
        sim = cosine_similarity(question_embedding, row["embedding"])
        scored.append((sim, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:top_k]]
