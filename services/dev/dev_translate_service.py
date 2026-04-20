"""
기술 용어 번역 서비스
- 번역 후 감지된 용어를 dev_translate_terms 테이블에 upsert (검색 횟수 누적)
- 검색 횟수 PIN_THRESHOLD 이상 → auto_pinned = TRUE 자동 지정
- 번역 시 고정 용어집(is_pinned OR auto_pinned)을 프롬프트에 주입
"""
import json

from openai import OpenAI
from config import settings
from database import get_connection

client = OpenAI(api_key=settings.openai_api_key)

# 자동 고정 임계값 — 검색 횟수가 이 값 이상이면 auto_pinned = TRUE
PIN_THRESHOLD = 3

AUDIENCE_GUIDE = {
    "pm":      "기획자/PM — 기능 영향과 일정 중심으로 설명하세요.",
    "exec":    "임원/경영진 — 비즈니스 영향, 리스크, 비용 관점으로 한 문단으로 요약하세요.",
    "sales":   "영업팀 — 고객에게 어떤 영향을 주는지, 서비스 가용성 중심으로 설명하세요.",
    "general": "일반 직원 — 가장 쉬운 일상 언어로 비유를 들어 설명하세요.",
}

ALLOWED_CATEGORIES = {"인프라", "개발", "보안", "데이터", "운영", "네트워크"}

BASE_SYSTEM_PROMPT = """당신은 IT 기술 용어를 비전공자에게 쉽게 설명하는 전문 번역가입니다.
개발자가 사용하는 기술적 텍스트를 분석하여:
1. 텍스트 속 기술 용어를 모두 식별합니다.
2. 각 용어를 비전공자도 이해할 수 있도록 설명하고, 일상적인 비유를 덧붙입니다.
3. 전체 텍스트를 지정된 독자에 맞는 비즈니스 언어로 자연스럽게 번역합니다.
응답은 반드시 JSON만 반환하세요."""


# ── DB 헬퍼 ───────────────────────────────────────────────────────────────────

def _load_pinned_terms() -> list[dict]:
    """고정 용어집(is_pinned OR auto_pinned) 전체 로드"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, term, category, explanation, analogy, search_count,
                   is_pinned, auto_pinned
            FROM dev_translate_terms
            WHERE is_pinned = TRUE OR auto_pinned = TRUE
            ORDER BY search_count DESC
            """
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return [
        {
            "id":           row[0],
            "term":         row[1],
            "category":     row[2],
            "explanation":  row[3],
            "analogy":      row[4],
            "search_count": row[5],
            "is_pinned":    row[6],
            "auto_pinned":  row[7],
        }
        for row in rows
    ]


def _upsert_terms(terms: list[dict]) -> None:
    """
    번역 결과 용어 목록을 DB에 upsert:
    - 신규: INSERT
    - 기존: search_count +1, explanation/analogy 업데이트
    - search_count >= PIN_THRESHOLD → auto_pinned = TRUE 자동 설정
    """
    if not terms:
        return

    conn = get_connection()
    cur = conn.cursor()
    try:
        for t in terms:
            term      = t.get("term", "").strip()
            category  = t.get("category", "개발")
            if category not in ALLOWED_CATEGORIES:
                category = "개발"
            explanation = t.get("explanation", "")
            analogy     = t.get("analogy", "")

            if not term:
                continue

            cur.execute(
                """
                INSERT INTO dev_translate_terms
                    (term, category, explanation, analogy, search_count,
                     auto_pinned, updated_at)
                VALUES (%s, %s, %s, %s, 1,
                        CASE WHEN 1 >= %s THEN TRUE ELSE FALSE END,
                        NOW())
                ON CONFLICT (term) DO UPDATE SET
                    search_count = dev_translate_terms.search_count + 1,
                    explanation  = EXCLUDED.explanation,
                    analogy      = EXCLUDED.analogy,
                    category     = EXCLUDED.category,
                    auto_pinned  = CASE
                        WHEN dev_translate_terms.search_count + 1 >= %s THEN TRUE
                        ELSE dev_translate_terms.auto_pinned
                    END,
                    updated_at   = NOW()
                """,
                (term, category, explanation, analogy,
                 PIN_THRESHOLD, PIN_THRESHOLD),
            )
    finally:
        cur.close()
        conn.close()


def _record_history(text: str, audience: str, term_count: int, pinned_applied: int) -> None:
    """번역 실행 이력을 dev_translate_history에 저장"""
    preview = text.strip()[:150]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO dev_translate_history
                (text_preview, audience, term_count, pinned_applied)
            VALUES (%s, %s, %s, %s)
            """,
            (preview, audience, term_count, pinned_applied),
        )
    finally:
        cur.close()
        conn.close()


def _build_glossary_section(pinned: list[dict]) -> str:
    """고정 용어집을 시스템 프롬프트용 텍스트로 변환"""
    if not pinned:
        return ""
    lines = [
        f"- {item['term']} ({item['category']}): {item['explanation']}"
        for item in pinned
    ]
    return (
        "\n\n[고정 용어집 — 아래 용어는 반드시 해당 설명을 우선 적용하세요]\n"
        + "\n".join(lines)
    )


# ── 번역 ──────────────────────────────────────────────────────────────────────

def translate_tech_text(text: str, audience: str = "general") -> dict:
    """
    기술 텍스트 번역:
    1. 고정 용어집 로드 → 시스템 프롬프트에 주입
    2. GPT-4o-mini 번역 + 용어 추출
    3. 추출된 용어 DB upsert (검색 횟수 누적 / 자동 고정)
    """
    if not text.strip():
        raise ValueError("텍스트를 입력해 주세요.")
    if len(text) > 5000:
        raise ValueError("텍스트가 너무 깁니다. 5,000자 이하로 입력해 주세요.")
    if audience not in AUDIENCE_GUIDE:
        audience = "general"

    # 1. 고정 용어집 주입
    pinned = _load_pinned_terms()
    glossary_section = _build_glossary_section(pinned)
    system_prompt = BASE_SYSTEM_PROMPT + glossary_section

    audience_instruction = AUDIENCE_GUIDE[audience]

    # 2. GPT 번역
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"[번역 대상 독자]\n{audience_instruction}\n\n"
                    f"[원문 기술 텍스트]\n{text.strip()}\n\n"
                    "[반환 형식]\n"
                    "{\n"
                    '  "translated": "독자에 맞게 번역된 전체 텍스트 (2~5문장)",\n'
                    '  "terms": [\n'
                    "    {\n"
                    '      "term": "기술 용어 원문",\n'
                    '      "category": "인프라 | 개발 | 보안 | 데이터 | 운영 | 네트워크",\n'
                    '      "explanation": "비전공자용 한 문장 설명",\n'
                    '      "analogy": "일상적인 비유 한 문장 (없으면 빈 문자열)"\n'
                    "    }\n"
                    "  ]\n"
                    "}\n"
                    "terms 배열은 원문에 등장하는 기술 용어만 포함하며, 최대 10개까지 반환합니다."
                ),
            },
        ],
        max_tokens=2000,
        temperature=0.3,
    )

    payload = json.loads(response.choices[0].message.content)

    # 3. 용어 정규화
    terms = []
    for t in payload.get("terms", [])[:10]:
        cat = t.get("category", "개발")
        if cat not in ALLOWED_CATEGORIES:
            cat = "개발"
        terms.append({
            "term":        t.get("term", "").strip(),
            "category":    cat,
            "explanation": t.get("explanation", ""),
            "analogy":     t.get("analogy", ""),
        })

    # 4. DB upsert + 이력 저장
    _upsert_terms(terms)
    _record_history(text, audience, len(terms), len(pinned))

    return {
        "translated":     payload.get("translated", ""),
        "terms":          terms,
        "audience":       audience,
        "pinned_applied": len(pinned),
    }


# ── 용어집 관리 ───────────────────────────────────────────────────────────────

def list_terms(pinned_only: bool = False) -> list[dict]:
    """전체 또는 고정 용어만 목록 조회 (검색 횟수 내림차순)"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        if pinned_only:
            cur.execute(
                """
                SELECT id, term, category, explanation, analogy,
                       search_count, is_pinned, auto_pinned, created_at, updated_at
                FROM dev_translate_terms
                WHERE is_pinned = TRUE OR auto_pinned = TRUE
                ORDER BY search_count DESC
                """
            )
        else:
            cur.execute(
                """
                SELECT id, term, category, explanation, analogy,
                       search_count, is_pinned, auto_pinned, created_at, updated_at
                FROM dev_translate_terms
                ORDER BY search_count DESC, updated_at DESC
                """
            )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return [
        {
            "id":           row[0],
            "term":         row[1],
            "category":     row[2],
            "explanation":  row[3],
            "analogy":      row[4],
            "search_count": row[5],
            "is_pinned":    row[6],
            "auto_pinned":  row[7],
            "created_at":   row[8].isoformat() if row[8] else None,
            "updated_at":   row[9].isoformat() if row[9] else None,
        }
        for row in rows
    ]


def toggle_pin(term_id: int, is_pinned: bool) -> dict:
    """수동 고정/해제 토글"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE dev_translate_terms
            SET is_pinned = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id, term, is_pinned, auto_pinned, search_count
            """,
            (is_pinned, term_id),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row:
        raise ValueError(f"용어 ID {term_id}를 찾을 수 없습니다.")

    return {
        "id":           row[0],
        "term":         row[1],
        "is_pinned":    row[2],
        "auto_pinned":  row[3],
        "search_count": row[4],
    }


def delete_term(term_id: int) -> None:
    """용어 삭제"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM dev_translate_terms WHERE id = %s RETURNING id",
            (term_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row:
        raise ValueError(f"용어 ID {term_id}를 찾을 수 없습니다.")


def get_stats() -> dict:
    """용어 통계 요약"""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                COUNT(*)                                            AS total,
                COUNT(*) FILTER (WHERE is_pinned = TRUE)           AS manual_pinned,
                COUNT(*) FILTER (WHERE auto_pinned = TRUE)         AS auto_pinned,
                COUNT(*) FILTER (WHERE is_pinned OR auto_pinned)   AS pinned_total,
                COALESCE(MAX(search_count), 0)                     AS max_count
            FROM dev_translate_terms
            """
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    return {
        "total":         row[0],
        "manual_pinned": row[1],
        "auto_pinned":   row[2],
        "pinned_total":  row[3],
        "max_count":     row[4],
        "pin_threshold": PIN_THRESHOLD,
    }


def get_usage_stats() -> dict:
    """
    사용 통계 반환:
    - 총 번역 횟수 (전체 / 오늘)
    - 독자별 사용 현황
    - 최근 14일 일별 추이
    - 평균 감지 용어 수
    - 카테고리별 용어 분포
    - 상위 용어 Top 10
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # 1. 총 번역 횟수
        cur.execute(
            """
            SELECT
                COUNT(*)                                                        AS total,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE)             AS today,
                ROUND(AVG(term_count), 1)                                       AS avg_terms
            FROM dev_translate_history
            """
        )
        row = cur.fetchone()
        total_count  = row[0] or 0
        today_count  = row[1] or 0
        avg_terms    = float(row[2]) if row[2] else 0.0

        # 2. 독자별 사용 현황
        cur.execute(
            """
            SELECT audience, COUNT(*) AS cnt
            FROM dev_translate_history
            GROUP BY audience
            ORDER BY cnt DESC
            """
        )
        audience_rows = cur.fetchall()
        audience_map = {r[0]: r[1] for r in audience_rows}

        # 3. 최근 14일 일별 추이
        cur.execute(
            """
            SELECT
                TO_CHAR(d.day, 'MM-DD') AS label,
                COALESCE(h.cnt, 0)       AS cnt
            FROM (
                SELECT generate_series(
                    CURRENT_DATE - INTERVAL '13 days',
                    CURRENT_DATE,
                    INTERVAL '1 day'
                )::DATE AS day
            ) d
            LEFT JOIN (
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM dev_translate_history
                WHERE created_at >= CURRENT_DATE - INTERVAL '13 days'
                GROUP BY DATE(created_at)
            ) h ON h.day = d.day
            ORDER BY d.day
            """
        )
        daily_rows = cur.fetchall()
        daily = [{"label": r[0], "count": r[1]} for r in daily_rows]

        # 4. 카테고리별 용어 분포
        cur.execute(
            """
            SELECT category, COUNT(*) AS cnt
            FROM dev_translate_terms
            GROUP BY category
            ORDER BY cnt DESC
            """
        )
        category_rows = cur.fetchall()
        categories = [{"category": r[0], "count": r[1]} for r in category_rows]

        # 5. 상위 용어 Top 10
        cur.execute(
            """
            SELECT term, category, search_count, is_pinned, auto_pinned
            FROM dev_translate_terms
            ORDER BY search_count DESC
            LIMIT 10
            """
        )
        top_rows = cur.fetchall()
        top_terms = [
            {
                "term":         r[0],
                "category":     r[1],
                "search_count": r[2],
                "is_pinned":    r[3],
                "auto_pinned":  r[4],
            }
            for r in top_rows
        ]

    finally:
        cur.close()
        conn.close()

    audience_labels = {"pm": "기획자/PM", "exec": "임원/경영진", "sales": "영업팀", "general": "일반 직원"}
    audience_stats = [
        {
            "audience": k,
            "label":    audience_labels.get(k, k),
            "count":    audience_map.get(k, 0),
            "pct":      round(audience_map.get(k, 0) / total_count * 100) if total_count else 0,
        }
        for k in ["general", "pm", "exec", "sales"]
    ]

    return {
        "total_count":   total_count,
        "today_count":   today_count,
        "avg_terms":     avg_terms,
        "audience":      audience_stats,
        "daily":         daily,
        "categories":    categories,
        "top_terms":     top_terms,
        "pin_threshold": PIN_THRESHOLD,
    }
