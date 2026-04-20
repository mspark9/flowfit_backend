"""
종목 코드 자동 탐색 서비스
처리 순서:
  1. GPT → 영문명 + 종목코드 직접 제시 (잘 알려진 회사)
  2. GPT가 제시한 ticker → yfinance 존재 검증
  3. 검증 실패 → GPT english_name으로 yfinance.Search
  4. 모두 실패 → found: false
"""
import json

from openai import OpenAI
from config import settings

_openai = OpenAI(api_key=settings.openai_api_key)

# GPT 변환 프롬프트 — 잘 알려진 회사는 ticker 직접 반환, 모르면 빈 문자열
_GPT_PROMPT = """주식 종목 전문가입니다.
아래 회사명을 보고 주식 정보를 반환하세요.

회사명: {company_name}

규칙:
- 잘 알려진 상장사라면 ticker와 exchange를 직접 작성하세요.
- 모르거나 비상장이라면 ticker와 exchange는 빈 문자열("")로 두세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{"english_name": "영문회사명", "ticker": "종목코드(모르면빈문자열)", "exchange": "거래소코드(모르면빈문자열)"}}

예시:
- 삼성전자  → {{"english_name": "Samsung Electronics", "ticker": "005930.KS", "exchange": "KRX"}}
- 현대차    → {{"english_name": "Hyundai Motor",       "ticker": "005380.KS", "exchange": "KRX"}}
- 애플      → {{"english_name": "Apple Inc",            "ticker": "AAPL",      "exchange": "NMS"}}
- 테슬라    → {{"english_name": "Tesla Inc",            "ticker": "TSLA",      "exchange": "NMS"}}
- 아마존    → {{"english_name": "Amazon.com Inc",       "ticker": "AMZN",      "exchange": "NMS"}}
- LG에너지솔루션 → {{"english_name": "LG Energy Solution", "ticker": "373220.KS", "exchange": "KRX"}}"""


def _validate_ticker(ticker: str) -> bool:
    """yfinance .info로 종목 존재 여부 검증. 빈 dict 또는 예외면 False."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return bool(info.get("symbol") or info.get("quoteType"))
    except Exception:
        return False


def _search_by_name(query: str) -> dict | None:
    """영문 회사명으로 yfinance.Search → EQUITY 우선, 없으면 첫 결과 반환."""
    try:
        import yfinance as yf
        search = yf.Search(query, max_results=5, news_count=0)
        quotes = getattr(search, "quotes", []) or []

        # EQUITY 타입 우선
        for q in quotes:
            if q.get("quoteType", "").upper() == "EQUITY" and q.get("symbol"):
                return {
                    "ticker":       q["symbol"],
                    "exchange":     q.get("exchange", ""),
                    "company_name": q.get("longname") or q.get("shortname", query),
                }
        # EQUITY 없으면 첫 결과
        if quotes and quotes[0].get("symbol"):
            q = quotes[0]
            return {
                "ticker":       q["symbol"],
                "exchange":     q.get("exchange", ""),
                "company_name": q.get("longname") or q.get("shortname", query),
            }
    except Exception:
        pass
    return None


def search_ticker(company_name: str) -> dict:
    """
    회사명(한글/영문)으로 주식 종목 코드 탐색.
    반환: { ticker, exchange, company_name, found: bool }
    실패 시 found=false (예외 전파 없음).
    """
    _empty = {"found": False, "company_name": company_name, "ticker": "", "exchange": ""}

    try:
        # ── 1단계: GPT에 영문명 + ticker 변환 요청 ──────────────
        response = _openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": _GPT_PROMPT.format(company_name=company_name)}],
            response_format={"type": "json_object"},
            max_tokens=120,
        )
        gpt = json.loads(response.choices[0].message.content)
        english_name = gpt.get("english_name", "").strip()
        gpt_ticker   = gpt.get("ticker",       "").strip()
        gpt_exchange = gpt.get("exchange",      "").strip()

        # ── 2단계: GPT가 ticker 제시 → yfinance 검증 ────────────
        if gpt_ticker:
            if _validate_ticker(gpt_ticker):
                return {
                    "found":        True,
                    "ticker":       gpt_ticker,
                    "exchange":     gpt_exchange,
                    "company_name": english_name or company_name,
                }
            # 검증 실패 → 영문명으로 Search 재시도

        # ── 3단계: yfinance.Search (영문명 우선, 없으면 원문) ────
        search_query = english_name or company_name
        found = _search_by_name(search_query)
        if found:
            return {"found": True, **found}

        # 영문명과 원문이 다른 경우 원문으로도 한 번 더 시도
        if english_name and english_name != company_name:
            found = _search_by_name(company_name)
            if found:
                return {"found": True, **found}

        return _empty

    except Exception:
        return _empty
