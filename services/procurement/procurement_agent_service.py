"""
구매 AI 에이전트 서비스
OpenAI Function Calling + Tavily 상품 검색 + DB 예산 조회 + 주문서 생성
SSE 이벤트: tool_start / tool_done / token / done
"""
import json
from datetime import datetime
from typing import Generator

from openai import OpenAI
from config import settings
from database import get_connection

# ── OpenAI 클라이언트 ─────────────────────────────────────────
_openai = OpenAI(api_key=settings.openai_api_key)

# ── Tavily 지연 초기화 ────────────────────────────────────────
_tavily_client = None


def _get_tavily():
    global _tavily_client
    if _tavily_client is None:
        if not settings.tavily_api_key:
            raise ValueError("TAVILY_API_KEY가 .env에 설정되지 않았습니다.")
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=settings.tavily_api_key)
    return _tavily_client


# ── 시스템 프롬프트 ────────────────────────────────────────────
SYSTEM_PROMPT = """당신은 기업 총무/구매팀 AI 에이전트입니다.
사용자의 구매 요청을 분석하고, 아래 순서로 처리합니다.

1. search_products 툴로 구매할 상품의 시장 가격과 판매 링크를 검색합니다.
   - max_results는 반드시 8로 설정하여 충분한 결과를 확보합니다.

2. 검색 결과를 분석하여 가격·신뢰도·판매처를 기준으로 상위 3개 후보를 선별합니다.
   각 후보에 대해 아래 정보를 준비합니다:
   - rank: 순위 (1·2·3)
   - name: 상품명
   - price: 단가 (원, 숫자만 — 정확히 알 수 없으면 합리적으로 추정)
   - vendor: 판매처명
   - url: 구매 링크 (검색 결과의 url 그대로 사용)
   - reason: 추천 이유 (20자 내외)

3. check_budget 툴로 요청 부서의 예산 잔액을 확인합니다.

4. create_purchase_order 툴 호출 시 top_candidates 필드에 상위 3개 후보를 반드시 포함합니다.
   selected_candidate_rank는 가장 추천하는 후보의 순위(1·2·3)로 설정합니다.

최종 보고서에는 반드시 포함합니다:
- 상위 3개 상품 비교 (가격·판매처·추천 이유)
- 최종 추천 상품과 구매 링크
- 예산 잔액 및 구매 가능 여부
- 생성된 주문서 번호와 승인 절차 안내

예산이 부족하면 분할 구매·가격 협상·긴급 예산 신청 등 대안을 제시합니다."""

# ── 툴 스펙 ───────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Tavily로 상품 가격·판매처·구매 링크를 실시간 웹 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "검색 키워드 (예: '사무용 의자 추천 가격 구매', 'A4 용지 박스 최저가')"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "검색 결과 수 (1~10, 기본 8)",
                        "default": 8
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_budget",
            "description": "finance_budgets 테이블에서 부서의 예산 잔액을 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {
                        "type": "string",
                        "description": "부서명 (예: 총무/구매팀, 인사(HR)팀)"
                    },
                    "account_code": {
                        "type": "string",
                        "description": "계정과목 (소모품비·임차료·수수료비용·복리후생비·기타비용 등).",
                        "default": "소모품비"
                    }
                },
                "required": ["department"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_purchase_order",
            "description": "구매 주문서를 purchase_orders 테이블에 저장합니다. 반드시 top_candidates에 상위 3개 후보를 포함해야 합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "department":    {"type": "string",  "description": "구매 요청 부서"},
                    "item_name":     {"type": "string",  "description": "구매 품목명"},
                    "quantity":      {"type": "integer", "description": "수량", "default": 1},
                    "unit_price":    {"type": "integer", "description": "최종 선택 상품의 단가 (원, 숫자만)"},
                    "vendor":        {"type": "string",  "description": "최종 선택 공급업체명"},
                    "account_code":  {"type": "string",  "description": "계정과목"},
                    "notes":         {"type": "string",  "description": "비고 (선택)", "default": ""},
                    "top_candidates": {
                        "type": "array",
                        "description": "검색 결과에서 선별한 상위 3개 후보 상품 목록. 반드시 포함.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rank":   {"type": "integer", "description": "순위 (1·2·3)"},
                                "name":   {"type": "string",  "description": "상품명"},
                                "price":  {"type": "integer", "description": "단가 (원, 숫자만)"},
                                "vendor": {"type": "string",  "description": "판매처명"},
                                "url":    {"type": "string",  "description": "구매 링크 URL"},
                                "reason": {"type": "string",  "description": "추천 이유 (20자 내외)"}
                            },
                            "required": ["rank", "name", "price", "vendor", "url", "reason"]
                        },
                        "minItems": 1,
                        "maxItems": 3
                    },
                    "selected_candidate_rank": {
                        "type": "integer",
                        "description": "top_candidates 중 최종 선택한 후보의 rank 값 (1·2·3)",
                        "default": 1
                    }
                },
                "required": ["department", "item_name", "quantity", "unit_price", "vendor", "account_code", "top_candidates"]
            }
        }
    }
]


# ── SSE 직렬화 헬퍼 ──────────────────────────────────────────
def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


# ── 툴 실행 함수들 ────────────────────────────────────────────

def _exec_search_products(args: dict) -> dict:
    """Tavily로 상품 가격·판매처·구매 링크 검색"""
    tavily = _get_tavily()
    query = args.get("query", "")
    max_results = max(1, min(int(args.get("max_results", 8)), 10))

    result = tavily.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
    )

    items = []
    for r in result.get("results", []):
        items.append({
            "title":   r.get("title", ""),
            "url":     r.get("url", ""),
            "content": r.get("content", "")[:400],
        })

    return {"query": query, "results": items, "count": len(items)}


def _exec_check_budget(args: dict) -> dict:
    """finance_budgets 테이블 예산 조회"""
    department   = args.get("department", "")
    account_code = args.get("account_code", "소모품비")
    year         = datetime.now().year

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT account_code, budget_amount
            FROM finance_budgets
            WHERE department = %s AND fiscal_year = %s
            ORDER BY budget_amount DESC
            """,
            (department, year),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if not rows:
        return {
            "department":    department,
            "account_code":  account_code,
            "budget_amount": 0,
            "total_budget":  0,
            "all_budgets":   [],
            "message":       f"'{department}' 부서의 {year}년 예산 데이터가 없습니다.",
        }

    all_budgets   = [{"account_code": r[0], "budget_amount": r[1]} for r in rows]
    target_amount = next((r[1] for r in rows if r[0] == account_code), 0)
    total_amount  = sum(r[1] for r in rows)

    return {
        "department":    department,
        "account_code":  account_code,
        "budget_amount": target_amount,
        "total_budget":  total_amount,
        "all_budgets":   all_budgets[:6],
    }


def _exec_create_purchase_order(args: dict) -> dict:
    """purchase_orders 테이블에 주문서 저장 (없으면 자동 생성), 상위 3개 후보 포함"""
    department            = args.get("department", "")
    item_name             = args.get("item_name", "")
    quantity              = max(1, int(args.get("quantity", 1)))
    unit_price            = max(0, int(args.get("unit_price", 0)))
    vendor                = args.get("vendor", "")
    account_code          = args.get("account_code", "소모품비")
    notes                 = args.get("notes", "")
    top_candidates        = args.get("top_candidates", [])
    selected_rank         = int(args.get("selected_candidate_rank", 1))
    total_amount          = quantity * unit_price

    # top_candidates JSON 직렬화 (DB 저장용)
    candidates_json = json.dumps(top_candidates, ensure_ascii=False)

    conn = get_connection()
    try:
        cur = conn.cursor()

        # 테이블 없으면 자동 생성 (candidates 컬럼 포함)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id                     SERIAL        PRIMARY KEY,
                department             VARCHAR(100)  NOT NULL,
                item_name              VARCHAR(255)  NOT NULL,
                quantity               INTEGER       NOT NULL DEFAULT 1,
                unit_price             BIGINT        NOT NULL DEFAULT 0,
                total_amount           BIGINT        NOT NULL DEFAULT 0,
                vendor                 VARCHAR(255)  NOT NULL,
                account_code           VARCHAR(100)  NOT NULL,
                status                 VARCHAR(50)   NOT NULL DEFAULT '승인대기',
                notes                  TEXT,
                top_candidates         TEXT,
                selected_candidate_rank INTEGER,
                created_at             TIMESTAMPTZ   NOT NULL DEFAULT NOW()
            )
        """)

        # 기존 테이블에 컬럼이 없으면 추가 (마이그레이션 대응)
        cur.execute("""
            ALTER TABLE purchase_orders
                ADD COLUMN IF NOT EXISTS top_candidates TEXT,
                ADD COLUMN IF NOT EXISTS selected_candidate_rank INTEGER
        """)

        cur.execute(
            """
            INSERT INTO purchase_orders
                (department, item_name, quantity, unit_price, total_amount,
                 vendor, account_code, notes, top_candidates, selected_candidate_rank)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, status, created_at::text
            """,
            (department, item_name, quantity, unit_price, total_amount,
             vendor, account_code, notes, candidates_json, selected_rank),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    order_id, status, created_at = row

    return {
        "order_id":               order_id,
        "department":             department,
        "item_name":              item_name,
        "quantity":               quantity,
        "unit_price":             unit_price,
        "total_amount":           total_amount,
        "vendor":                 vendor,
        "account_code":           account_code,
        "status":                 status,
        "created_at":             created_at,
        "top_candidates":         top_candidates,
        "selected_candidate_rank": selected_rank,
        "message":                f"구매 주문서 #{order_id}가 생성되었습니다. 상태: {status}",
    }


TOOL_EXECUTORS = {
    "search_products":       _exec_search_products,
    "check_budget":          _exec_check_budget,
    "create_purchase_order": _exec_create_purchase_order,
}


# ── 에이전트 루프 ─────────────────────────────────────────────

def run_procurement_agent(message: str, department: str) -> Generator[str, None, None]:
    """
    구매 AI 에이전트 실행 — SSE 이벤트 generator

    SSE 이벤트:
      tool_start : { type, tool, args }
      tool_done  : { type, tool, result }
      token      : { type, content }
      done       : { type }
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"[요청 부서: {department}]\n{message}"},
    ]

    max_steps = 8

    for _ in range(max_steps):
        response = _openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        assistant_msg = response.choices[0].message

        # 툴 호출 없음 → 최종 응답 스트리밍
        if not assistant_msg.tool_calls:
            messages.append({"role": "assistant", "content": assistant_msg.content or ""})
            stream = _openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                stream=True,
            )
            for chunk in stream:
                delta_content = chunk.choices[0].delta.content
                if delta_content:
                    yield _sse("token", {"content": delta_content})

            yield _sse("done", {})
            return

        # 툴 호출 처리
        messages.append(assistant_msg)

        for tool_call in assistant_msg.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            call_id = tool_call.id  # OpenAI 고유 툴 호출 ID
            yield _sse("tool_start", {"tool": tool_name, "args": tool_args, "call_id": call_id})

            try:
                executor = TOOL_EXECUTORS.get(tool_name)
                if executor is None:
                    result = {"error": f"알 수 없는 툴: {tool_name}"}
                else:
                    result = executor(tool_args)
            except Exception as exc:
                result = {"error": str(exc)}

            yield _sse("tool_done", {"tool": tool_name, "result": result, "call_id": call_id})

            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      json.dumps(result, ensure_ascii=False),
            })

    # 최대 스텝 초과 시 안내
    yield _sse("token", {"content": "최대 처리 단계에 도달했습니다. 요청이 너무 복잡하거나 툴 호출이 반복되고 있습니다."})
    yield _sse("done", {})
