"""
전략/기획팀 라우터
POST /api/strategy/competitor/stream   — SSE 스트리밍
POST /api/strategy/competitor/download — PPTX 반환
POST /api/strategy/ticker/search       — 종목 코드 탐색
POST /api/strategy/financial           — 재무 지표 조회
"""
from typing import List
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from services.strategy.competitor_research_service import (
    ALL_CATEGORIES,
    stream_competitor_research,
)
from services.strategy.strategy_pptx_service import generate_research_pptx

router = APIRouter()


class CompanyItem(BaseModel):
    name:     str
    articles: list = []
    analysis: dict = {}


class ResearchStreamRequest(BaseModel):
    companies:  List[str]         # 경쟁사 이름 목록 (1~3개)
    categories: List[str] = []    # 빈 리스트면 전체 카테고리 사용


class ResearchDownloadRequest(BaseModel):
    companies:      List[CompanyItem]
    summary:        str  = ""
    categories:     List[str] = []
    financial_data: dict = {}   # { ticker: { metric: value } }
    ticker_map:     dict = {}   # { company_name: { ticker, exchange, found } }


class TickerSearchRequest(BaseModel):
    company_name: str


class FinancialDataRequest(BaseModel):
    tickers: List[str]

class CompetitorSuggestRequest(BaseModel):
    company_name: str


@router.post("/competitor/stream")
def competitor_stream(body: ResearchStreamRequest):
    """경쟁사 동향 리서치 SSE 스트리밍"""
    companies = [c.strip() for c in body.companies if c.strip()]
    if not companies:
        raise HTTPException(status_code=400, detail="경쟁사 이름을 1개 이상 입력해 주세요.")
    if len(companies) > 3:
        raise HTTPException(status_code=400, detail="경쟁사는 최대 3개까지 입력할 수 있습니다.")

    categories = [c for c in body.categories if c in ALL_CATEGORIES] or ALL_CATEGORIES

    def generate():
        yield from stream_competitor_research(companies, categories)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/competitor/download")
def competitor_download(body: ResearchDownloadRequest):
    """경쟁사 리서치 결과 PPTX 다운로드"""
    if not body.companies:
        raise HTTPException(status_code=400, detail="리서치 결과가 없습니다.")

    categories = body.categories or ALL_CATEGORIES
    company_names = "_".join(c.name for c in body.companies[:3])

    try:
        pptx_bytes = generate_research_pptx({
            "companies":      [c.model_dump() for c in body.companies],
            "summary":        body.summary,
            "categories":     categories,
            "financial_data": body.financial_data,
            "ticker_map":     body.ticker_map,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PPTX 생성 실패: {str(exc)}") from exc

    filename     = f"경쟁사_동향_리서치_{company_names}.pptx"
    encoded_name = quote(filename)
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.post("/ticker/search")
def ticker_search(body: TickerSearchRequest):
    """회사명으로 주식 종목 코드 자동 탐색"""
    from services.strategy.ticker_search_service import search_ticker
    company = body.company_name.strip()
    if not company:
        raise HTTPException(status_code=400, detail="회사명을 입력해 주세요.")
    return search_ticker(company)


@router.post("/financial")
def financial_data(body: FinancialDataRequest):
    """종목 코드 목록으로 재무 지표 조회"""
    from services.strategy.financial_data_service import get_financial_data
    tickers = [t.strip() for t in body.tickers if t.strip()]
    if not tickers:
        return {}
    return get_financial_data(tickers)


@router.post("/competitor/suggest")
def competitor_suggest(body: CompetitorSuggestRequest):
    """회사명 기반 경쟁사 AI 추천 (GPT, 최대 5개)"""
    import json
    from openai import OpenAI
    from config import settings

    company = body.company_name.strip()
    if not company:
        raise HTTPException(status_code=400, detail="회사명을 입력해 주세요.")

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 기업 전략 분석 전문가입니다. "
                        "주어진 회사의 실제 경쟁사를 5개 추천해주세요. "
                        "반드시 JSON 배열 형식으로만 응답하세요. "
                        "예시: [\"삼성전자\", \"LG전자\", \"SK하이닉스\", \"인텔\", \"TSMC\"]"
                    ),
                },
                {
                    "role": "user",
                    "content": f"'{company}'의 주요 경쟁사 5개를 JSON 배열로 추천해주세요. 회사 이름만 포함하세요.",
                },
            ],
            temperature=0.3,
            max_tokens=200,
        )
        content = response.choices[0].message.content.strip()
        # 마크다운 코드블록 제거
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        suggestions = json.loads(content.strip())
        if not isinstance(suggestions, list):
            raise ValueError("배열 형식이 아닙니다.")
        # 문자열만 필터링, 최대 5개, 자기 자신 제외
        suggestions = [s for s in suggestions if isinstance(s, str) and s.strip() != company][:5]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"경쟁사 추천 실패: {str(exc)}") from exc

    return {"suggestions": suggestions}
