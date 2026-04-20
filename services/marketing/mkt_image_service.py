"""
마케팅 캠페인 이미지 생성 서비스 — DALL-E 3
법무 문서(표시·광고의 공정화에 관한 법률)를 참조하여 규정 준수 이미지 생성
"""
import json

from openai import OpenAI

from config import settings
from database import get_connection
from services.common.rag_utils import embed_text, select_top_chunks_by_vector

client = OpenAI(api_key=settings.openai_api_key)


def _fetch_ad_law_guidelines(product_name: str, description: str) -> str:
    """
    법무 DB에서 광고 관련 법률 청크를 벡터 검색하여
    GPT로 이미지 생성 시 준수해야 할 가이드라인을 요약한다.
    문서가 없으면 빈 문자열을 반환한다.
    """
    conn = get_connection()
    cur = conn.cursor()

    try:
        # 활성 청크 로드
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
        return ""

    # 광고 규정 관련 청크 검색
    query = f"광고 이미지 규정 표시광고 공정화 허위 과장 기만 {product_name}"
    query_embedding = embed_text(query)

    chunks = [
        {
            "file_name": row[0],
            "chunk_text": row[1],
            "embedding": list(row[2]),
        }
        for row in chunk_rows
    ]
    top_chunks = select_top_chunks_by_vector(query_embedding, chunks, top_k=5)

    if not top_chunks:
        return ""

    context = "\n\n".join(
        f"[{item['file_name']}]\n{item['chunk_text']}"
        for item in top_chunks
    )

    # GPT로 이미지 생성 가이드라인 요약
    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 광고 법률 전문가입니다. "
                    "제공된 법률 문서를 참고하여 마케팅 이미지 생성 시 "
                    "반드시 준수해야 할 핵심 가이드라인을 추출하세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"[제품/캠페인]\n{product_name}\n{description}\n\n"
                    f"[관련 법률 문서]\n{context}\n\n"
                    "[요청]\n"
                    "위 법률 문서를 참고하여 이 제품의 광고 이미지를 AI로 생성할 때 "
                    "주의해야 할 사항을 JSON으로 반환하세요.\n"
                    "{\n"
                    '  "guidelines": "이미지 생성 시 주의사항을 한 문단으로 요약 (한국어, 200자 이내)",\n'
                    '  "prohibited": ["금지 표현1", "금지 표현2", ...],\n'
                    '  "sources": ["참조 법률 문서명"]\n'
                    "}"
                ),
            },
        ],
        max_tokens=500,
        temperature=0.2,
    )

    return json.loads(res.choices[0].message.content)


def generate_image(
    product_name: str,
    description: str,
    style: str,
    size: str,
) -> dict:
    """
    캠페인 정보를 기반으로 DALL-E 3 이미지를 생성합니다.
    법무 문서의 광고 규정을 자동 참조하여 규정 준수 프롬프트를 구성합니다.

    Returns:
        {"image_url": str, "revised_prompt": str, "legal_guidelines": dict|None}
    """
    # 1) 법무 DB에서 광고 규정 가이드라인 조회
    legal = None
    guidelines_text = ""
    try:
        legal = _fetch_ad_law_guidelines(product_name, description)
        if legal and isinstance(legal, dict):
            guidelines_text = legal.get("guidelines", "")
            prohibited = legal.get("prohibited", [])
            if prohibited:
                guidelines_text += " 금지 표현: " + ", ".join(prohibited) + "."
    except Exception:
        # 법무 문서 조회 실패해도 이미지 생성은 진행
        legal = None

    # 2) DALL-E 프롬프트 구성
    prompt = (
        f"마케팅 캠페인용 고퀄리티 광고 이미지를 생성해주세요.\n"
        f"제품명: {product_name}\n"
        f"설명: {description}\n"
        f"스타일: {style}\n"
        f"텍스트나 글자는 절대 포함하지 마세요. "
        f"깔끔하고 전문적인 광고 비주얼로 제작해주세요."
    )

    if guidelines_text:
        prompt += (
            f"\n\n[광고 법률 준수 사항]\n{guidelines_text}\n"
            f"위 규정을 준수하여 허위·과장·기만적 표현이 없는 이미지를 생성하세요."
        )

    # 3) DALL-E 이미지 생성
    res = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        n=1,
        size=size,
        quality="standard",
    )

    image_data = res.data[0]
    return {
        "image_url": image_data.url,
        "legal_guidelines": legal if isinstance(legal, dict) else None,
    }
