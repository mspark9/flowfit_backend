"""
경쟁사 동향 리서치 서비스
Tavily로 회사별 최신 뉴스 수집 → GPT로 카테고리별 정리 → SSE 스트리밍
"""
import json
from typing import Generator

from openai import OpenAI
from config import settings

_openai = OpenAI(api_key=settings.openai_api_key)

# ── Tavily 지연 초기화 ────────────────────────────────────────
_tavily = None

def _get_tavily():
    global _tavily
    if _tavily is None:
        if not settings.tavily_api_key:
            raise ValueError("TAVILY_API_KEY가 .env에 설정되지 않았습니다.")
        from tavily import TavilyClient
        _tavily = TavilyClient(api_key=settings.tavily_api_key)
    return _tavily


# ── 지원 카테고리 ─────────────────────────────────────────────
ALL_CATEGORIES = ["신제품/서비스", "가격·프로모션", "인사·조직", "전략·투자"]

# ── SSE 헬퍼 ─────────────────────────────────────────────────
def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


# ── 분석 프롬프트 ─────────────────────────────────────────────
ANALYSIS_PROMPT = """다음은 '{company}' 관련 최신 뉴스/동향 기사들입니다.

{articles}

위 내용을 바탕으로 아래 카테고리별로 핵심 동향을 한국어로 정리하세요.
분석할 카테고리: {categories}

없는 내용은 '해당 없음'으로 표시하고, 있는 내용은 2~4문장으로 구체적으로 작성하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  {category_keys}
}}"""

SUMMARY_PROMPT = """다음은 경쟁사 동향 리서치 결과입니다.

{research_content}

위 내용을 바탕으로 전략/기획팀 관점에서 종합 시사점을 작성하세요:
1. 각 경쟁사의 핵심 움직임 요약 (1~2문장씩)
2. 공통 트렌드 및 업계 방향성
3. 우리 회사가 주목해야 할 기회와 위협
4. 즉시 검토 필요한 전략적 액션 아이템 (3개)

한국어로 구체적이고 실용적으로 작성하세요."""


def _search_company(company: str) -> list[dict]:
    """Tavily로 회사 최신 뉴스·동향 검색"""
    tavily = _get_tavily()
    result = tavily.search(
        query=f"{company} 최신 뉴스 동향 전략 제품 2024 2025",
        max_results=8,
        search_depth="basic",
    )
    articles = []
    for r in result.get("results", []):
        articles.append({
            "title":   r.get("title", ""),
            "content": r.get("content", "")[:400],
            "url":     r.get("url", ""),
        })
    return articles


def _analyze_company(company: str, articles: list[dict], categories: list[str]) -> dict:
    """GPT로 카테고리별 동향 분석"""
    articles_text = "\n\n".join(
        f"[{i+1}] {a['title']}\n{a['content']}" for i, a in enumerate(articles)
    )

    # JSON 키 템플릿 생성
    category_keys = ", ".join(f'"{c}": "..."' for c in categories)

    prompt = ANALYSIS_PROMPT.format(
        company=company,
        articles=articles_text or "검색 결과 없음",
        categories=", ".join(categories),
        category_keys=category_keys,
    )

    response = _openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=800,
    )

    try:
        analysis = json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, AttributeError):
        analysis = {c: "분석 실패" for c in categories}

    # 누락된 카테고리 보완
    for cat in categories:
        if cat not in analysis:
            analysis[cat] = "해당 없음"

    return analysis


def stream_competitor_research(
    companies: list[str],
    categories: list[str],
) -> Generator[str, None, None]:
    """
    경쟁사 리서치 SSE 스트리밍

    이벤트:
      status         : { type, company, index, total, phase }
      company_result : { type, company, articles, analysis }
      token          : { type, content }
      done           : { type }
    """
    if not categories:
        categories = ALL_CATEGORIES

    # 검색·분석 결과 누적 (종합 시사점에 사용)
    all_results = []

    total = len(companies)

    for idx, company in enumerate(companies):
        # 1단계: 검색 시작
        yield _sse("status", {"company": company, "index": idx, "total": total, "phase": "searching"})

        try:
            articles = _search_company(company)
        except Exception as exc:
            articles = []
            yield _sse("status", {"company": company, "index": idx, "total": total, "phase": "search_error", "error": str(exc)})

        # 2단계: 분석 시작
        yield _sse("status", {"company": company, "index": idx, "total": total, "phase": "analyzing"})

        try:
            analysis = _analyze_company(company, articles, categories)
        except Exception as exc:
            analysis = {c: "분석 실패" for c in categories}
            yield _sse("status", {"company": company, "index": idx, "total": total, "phase": "analysis_error", "error": str(exc)})

        # 3단계: 회사별 결과 전송
        yield _sse("company_result", {
            "company":  company,
            "index":    idx,
            "articles": articles[:5],  # 최대 5개 기사
            "analysis": analysis,
        })

        all_results.append({
            "company":  company,
            "articles": articles,
            "analysis": analysis,
        })

    # 4단계: 종합 시사점 스트리밍
    research_content = ""
    for r in all_results:
        research_content += f"\n## {r['company']}\n"
        for cat, content in r["analysis"].items():
            research_content += f"- {cat}: {content}\n"

    summary_messages = [
        {"role": "user", "content": SUMMARY_PROMPT.format(research_content=research_content)}
    ]

    stream = _openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=summary_messages,
        stream=True,
        max_tokens=600,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield _sse("token", {"content": delta})

    yield _sse("done", {})
