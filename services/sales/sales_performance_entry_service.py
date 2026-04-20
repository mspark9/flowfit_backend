"""
영업 실적 등록 서비스 — DB 저장/조회/삭제 (PostgreSQL)

책임:
- period_key 자동 생성 (type + 날짜 → '2026-04' / '2026-Q1' / '2026-FY')
- 등록(upsert): summary UPSERT + stages/members DELETE+INSERT (단일 트랜잭션)
- 목록 조회: DB에 존재하는 period 목록 반환 (최신순)
- 단건 조회: period_key 로 요약·파이프라인·팀원 일괄 반환
"""
from datetime import date
from calendar import monthrange

from database import get_connection

# ────────────────────────────────────────────────────────────
# period_key 생성 / 파싱
# ────────────────────────────────────────────────────────────

VALID_TYPES = {"month", "quarter", "year"}


def build_period_key(period_type: str, year: int, value: int = 0) -> dict:
    """
    타입 + 연도 + (월/분기) 로 period_key · label · 경계일을 생성합니다.

    Args:
        period_type: 'month' | 'quarter' | 'year'
        year:        예) 2026
        value:       month(1~12) 또는 quarter(1~4). year일 땐 무시.

    Returns:
        { period_key, period_label, period_type, start_date, end_date }
    """
    if period_type not in VALID_TYPES:
        raise ValueError(f"period_type은 {VALID_TYPES} 중 하나여야 합니다.")

    if period_type == "month":
        if not (1 <= value <= 12):
            raise ValueError("month는 1~12 사이여야 합니다.")
        start = date(year, value, 1)
        end = date(year, value, monthrange(year, value)[1])
        return {
            "period_key":   f"{year}-{value:02d}",
            "period_label": f"{year}년 {value}월",
            "period_type":  "month",
            "start_date":   start,
            "end_date":     end,
        }

    if period_type == "quarter":
        if not (1 <= value <= 4):
            raise ValueError("quarter는 1~4 사이여야 합니다.")
        start_month = (value - 1) * 3 + 1
        end_month = start_month + 2
        start = date(year, start_month, 1)
        end = date(year, end_month, monthrange(year, end_month)[1])
        return {
            "period_key":   f"{year}-Q{value}",
            "period_label": f"{year}년 Q{value}",
            "period_type":  "quarter",
            "start_date":   start,
            "end_date":     end,
        }

    # year
    return {
        "period_key":   f"{year}-FY",
        "period_label": f"{year}년 연간",
        "period_type":  "year",
        "start_date":   date(year, 1, 1),
        "end_date":     date(year, 12, 31),
    }


def previous_period_key(period_key: str) -> str | None:
    """
    주어진 period_key의 직전 기간 key를 반환합니다.
    - 'YYYY-MM'  → 이전 월 (연 경계 처리)
    - 'YYYY-QN'  → 이전 분기 (연 경계 처리)
    - 'YYYY-FY'  → 직전 연도
    파싱 실패 시 None.
    """
    if not period_key:
        return None

    try:
        # 연간
        if period_key.endswith("-FY"):
            year = int(period_key[:4])
            return f"{year - 1}-FY"

        # 분기
        if "-Q" in period_key:
            year_str, q_str = period_key.split("-Q")
            year = int(year_str)
            q = int(q_str)
            if q <= 1:
                return f"{year - 1}-Q4"
            return f"{year}-Q{q - 1}"

        # 월
        year_str, month_str = period_key.split("-")
        year = int(year_str)
        month = int(month_str)
        if month <= 1:
            return f"{year - 1}-12"
        return f"{year}-{month - 1:02d}"
    except (ValueError, IndexError):
        return None


# ────────────────────────────────────────────────────────────
# 등록 (upsert)
# ────────────────────────────────────────────────────────────

def upsert_performance(
    period_type:     str,
    year:            int,
    value:           int,
    target_revenue:  int,
    actual_revenue:  int,
    prev_revenue:    int,
    deal_count:      int,
    win_count:       int,
    pipeline:        list,   # [{stage_order, stage_name, stage_count, stage_amount}, ...]
    members:         list,   # [{member_name, revenue, deals, wins}, ...]
    note:            str = "",
    created_by:      str = "",
    created_by_name: str = "",
) -> dict:
    """
    한 기간의 실적을 upsert 합니다.
    summary: INSERT ... ON CONFLICT UPDATE
    stages/members: 해당 period 의 기존 행 DELETE 후 재-INSERT
    모든 작업은 단일 트랜잭션.
    """
    meta = build_period_key(period_type, year, value)

    conn = get_connection()
    conn.autocommit = False  # 트랜잭션 수동 제어
    try:
        cur = conn.cursor()

        # 1. summary upsert
        cur.execute(
            """
            INSERT INTO sales_period_summary (
                period_key, period_label, period_type, start_date, end_date,
                target_revenue, actual_revenue, prev_revenue,
                deal_count, win_count, note, created_by, created_by_name
            ) VALUES (%s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s)
            ON CONFLICT (period_key) DO UPDATE SET
                period_label    = EXCLUDED.period_label,
                period_type     = EXCLUDED.period_type,
                start_date      = EXCLUDED.start_date,
                end_date        = EXCLUDED.end_date,
                target_revenue  = EXCLUDED.target_revenue,
                actual_revenue  = EXCLUDED.actual_revenue,
                prev_revenue    = EXCLUDED.prev_revenue,
                deal_count      = EXCLUDED.deal_count,
                win_count       = EXCLUDED.win_count,
                note            = EXCLUDED.note,
                created_by      = EXCLUDED.created_by,
                created_by_name = EXCLUDED.created_by_name,
                updated_at      = NOW()
            """,
            (
                meta["period_key"], meta["period_label"], meta["period_type"],
                meta["start_date"], meta["end_date"],
                target_revenue, actual_revenue, prev_revenue,
                deal_count, win_count, note, created_by, created_by_name,
            ),
        )

        # 2. 기존 stages/members 제거 후 재삽입 (덮어쓰기)
        cur.execute("DELETE FROM sales_pipeline_stages    WHERE period_key = %s", (meta["period_key"],))
        cur.execute("DELETE FROM sales_member_performance WHERE period_key = %s", (meta["period_key"],))

        for s in pipeline:
            cur.execute(
                """
                INSERT INTO sales_pipeline_stages (period_key, stage_order, stage_name, stage_count, stage_amount)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    meta["period_key"],
                    int(s["stage_order"]),
                    str(s["stage_name"])[:50],
                    int(s["stage_count"]),
                    int(s["stage_amount"]),
                ),
            )

        for m in members:
            cur.execute(
                """
                INSERT INTO sales_member_performance (period_key, member_name, revenue, deals, wins)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    meta["period_key"],
                    str(m["member_name"])[:50],
                    int(m["revenue"]),
                    int(m["deals"]),
                    int(m["wins"]),
                ),
            )

        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True
        conn.close()

    return {
        "period_key":   meta["period_key"],
        "period_label": meta["period_label"],
        "period_type":  meta["period_type"],
        "start_date":   meta["start_date"].isoformat(),
        "end_date":     meta["end_date"].isoformat(),
    }


# ────────────────────────────────────────────────────────────
# 조회
# ────────────────────────────────────────────────────────────

def list_periods(period_type: str = "") -> list:
    """
    등록된 기간 목록을 최신순으로 반환합니다.

    Args:
        period_type: '' | 'month' | 'quarter' | 'year'
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        if period_type and period_type in VALID_TYPES:
            cur.execute(
                """
                SELECT period_key, period_label, period_type, start_date, end_date
                FROM sales_period_summary
                WHERE period_type = %s
                ORDER BY start_date DESC, period_key DESC
                """,
                (period_type,),
            )
        else:
            cur.execute(
                """
                SELECT period_key, period_label, period_type, start_date, end_date
                FROM sales_period_summary
                ORDER BY start_date DESC, period_key DESC
                """
            )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {
            "period_key":   r[0],
            "period_label": r[1],
            "period_type":  r[2],
            "start_date":   r[3].isoformat() if r[3] else "",
            "end_date":     r[4].isoformat() if r[4] else "",
        }
        for r in rows
    ]


def fetch_performance(period_key: str) -> dict | None:
    """
    단건 조회 — 요약·파이프라인·팀원 일괄 반환. 없으면 None.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT period_key, period_label, period_type, start_date, end_date,
                   target_revenue, actual_revenue, prev_revenue,
                   deal_count, win_count, note, created_by, created_by_name
            FROM sales_period_summary
            WHERE period_key = %s
            """,
            (period_key,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return None

        summary = {
            "period_key":      row[0],
            "period_label":    row[1],
            "period_type":     row[2],
            "start_date":      row[3].isoformat() if row[3] else "",
            "end_date":        row[4].isoformat() if row[4] else "",
            "target_revenue":  int(row[5]),
            "actual_revenue":  int(row[6]),
            "prev_revenue":    int(row[7]),
            "deal_count":      int(row[8]),
            "win_count":       int(row[9]),
            "note":            row[10] or "",
            "created_by":      row[11] or "",
            "created_by_name": row[12] or "",
        }

        cur.execute(
            """
            SELECT stage_order, stage_name, stage_count, stage_amount
            FROM sales_pipeline_stages
            WHERE period_key = %s
            ORDER BY stage_order ASC
            """,
            (period_key,),
        )
        pipeline = [
            {"stage_order": r[0], "stage_name": r[1], "stage_count": int(r[2]), "stage_amount": int(r[3])}
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT member_name, revenue, deals, wins
            FROM sales_member_performance
            WHERE period_key = %s
            ORDER BY revenue DESC
            """,
            (period_key,),
        )
        members = [
            {"member_name": r[0], "revenue": int(r[1]), "deals": int(r[2]), "wins": int(r[3])}
            for r in cur.fetchall()
        ]

        cur.close()
    finally:
        conn.close()

    return {"summary": summary, "pipeline": pipeline, "members": members}


def delete_performance(period_key: str) -> bool:
    """period_key 한 건을 삭제합니다 (CASCADE로 하위 테이블도 정리)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sales_period_summary WHERE period_key = %s", (period_key,))
        deleted = cur.rowcount > 0
        cur.close()
    finally:
        conn.close()
    return deleted
