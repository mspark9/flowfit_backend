"""yfinance 재무 지표 수집 서비스"""

_INFO_KEYS = [
    "currentPrice",
    "fiftyTwoWeekHigh",
    "fiftyTwoWeekLow",
    "marketCap",
    "totalRevenue",
    "operatingIncome",
    "netIncomeToCommon",
    "trailingPE",
    "priceToBook",
    "currency",
]


def _safe_float(val):
    """NaN·None·inf 걸러내고 float 반환. 불가능하면 None."""
    try:
        f = float(val)
        if f != f or abs(f) == float("inf"):  # NaN / inf 체크
            return None
        return f
    except Exception:
        return None


def get_financial_data(tickers: list[str]) -> dict:
    """
    종목 코드 목록으로 재무 지표 수집.
    반환: { ticker: { metric: value, ... }, ... }
    실패 항목은 빈 dict. 예외 전파 없음.
    """
    import yfinance as yf

    result = {}
    for code in tickers:
        try:
            t = yf.Ticker(code)
            info = t.info or {}
            data: dict = {}

            for key in _INFO_KEYS:
                raw = info.get(key)
                if raw is None:
                    continue
                if key == "currency":
                    data[key] = str(raw)
                else:
                    v = _safe_float(raw)
                    if v is not None:
                        data[key] = v

            # operatingIncome 보완 — financials 테이블
            if "operatingIncome" not in data:
                try:
                    fin = t.financials
                    if fin is not None and not fin.empty:
                        for label in ("Operating Income", "Total Operating Income As Reported"):
                            if label in fin.index:
                                v = _safe_float(fin.loc[label].iloc[0])
                                if v is not None:
                                    data["operatingIncome"] = v
                                break
                except Exception:
                    pass

            # netIncomeToCommon 보완
            if "netIncomeToCommon" not in data:
                try:
                    fin = t.financials
                    if fin is not None and not fin.empty:
                        for label in ("Net Income", "Net Income Common Stockholders"):
                            if label in fin.index:
                                v = _safe_float(fin.loc[label].iloc[0])
                                if v is not None:
                                    data["netIncomeToCommon"] = v
                                break
                except Exception:
                    pass

            result[code] = data
        except Exception:
            result[code] = {}

    return result
