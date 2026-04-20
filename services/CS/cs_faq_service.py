"""
CS FAQ 서비스 — 문의 로그 클러스터링 + FAQ Q&A 자동 생성
의존: openai, scikit-learn (pip install scikit-learn)
"""
import csv
import io
import json
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

EMBEDDING_MODEL = "text-embedding-3-small"

FAQ_GEN_PROMPT = """
아래 고객 문의들은 같은 유형으로 묶인 클러스터입니다.
이 문의들을 대표하는 FAQ Q&A를 JSON으로 작성하세요. 다른 텍스트 없이 JSON만 반환하세요.

{{
  "category": "카테고리명 (배송 / 반품/교환 / 환불 / 결제 / 상품 / 주문 / 회원/계정 / 혜택 / 기타 중 하나)",
  "question":  "고객 관점에서 자연스러운 질문 (1문장)",
  "answer":    "CS 담당자 관점의 명확한 답변 (2~4문장)"
}}

문의 목록:
{inquiries}
"""


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 임베딩 벡터로 변환"""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def _kmeans_cluster(vectors: list[list[float]], k: int) -> list[int]:
    """K-Means 클러스터링 — scikit-learn 사용"""
    try:
        from sklearn.cluster import KMeans
        import numpy as np
    except ImportError:
        raise RuntimeError("scikit-learn이 설치되지 않았습니다. pip install scikit-learn 실행 후 재시도하세요.")

    arr = np.array(vectors)
    km  = KMeans(n_clusters=k, random_state=42, n_init="auto")
    km.fit(arr)
    return km.labels_.tolist()


def _generate_faq(cluster_inquiries: list[str]) -> dict:
    """클러스터 내 문의들로 FAQ Q&A 1개 생성"""
    sample = cluster_inquiries[:10]  # 클러스터당 최대 10개 샘플
    prompt = FAQ_GEN_PROMPT.format(inquiries="\n".join(f"- {q}" for q in sample))

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
    )
    return json.loads(res.choices[0].message.content)


def generate_faqs_from_csv(csv_bytes: bytes, top_n: int = 10) -> list[dict]:
    """
    문의 로그 CSV에서 FAQ top_n개를 자동 생성합니다.

    CSV 형식: 첫 번째 컬럼이 문의 원문 (헤더 행 자동 감지)

    Args:
        csv_bytes: CSV 파일 바이너리
        top_n:     생성할 FAQ 개수

    Returns:
        [{"category": str, "question": str, "answer": str}, ...]
    """
    # CSV 파싱
    text     = csv_bytes.decode("utf-8-sig")
    reader   = csv.reader(io.StringIO(text))
    rows     = list(reader)

    if not rows:
        raise ValueError("CSV 파일이 비어 있습니다.")

    # 헤더 행 자동 감지 (첫 행이 '문의' 또는 '내용' 등 문자면 skip)
    start = 1 if any(kw in rows[0][0] for kw in ["문의", "내용", "질문", "inquiry", "text"]) else 0
    inquiries = [row[0].strip() for row in rows[start:] if row and row[0].strip()]

    if len(inquiries) < top_n:
        raise ValueError(f"문의 건수({len(inquiries)})가 요청한 FAQ 수({top_n})보다 적습니다.")

    # 임베딩
    embeddings = _embed_texts(inquiries)

    # K-Means 클러스터링
    k       = min(top_n, len(inquiries))
    labels  = _kmeans_cluster(embeddings, k)

    # 클러스터별 문의 그룹화
    clusters: dict[int, list[str]] = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(label, []).append(inquiries[idx])

    # 각 클러스터에서 FAQ 생성
    faqs = []
    for cluster_id in sorted(clusters.keys()):
        faq = _generate_faq(clusters[cluster_id])
        faqs.append(faq)

    return faqs
