"""
HR 인사 평가 등록 서비스 — DB 저장/조회/삭제 + 자동 데이터 조회 (PostgreSQL)

책임:
- eval_key 자동 생성 (EVAL-2026-Q1 / EVAL-2026-H1 / EVAL-2026-FY)
- 등록(upsert): period UPSERT + departments/individuals DELETE+INSERT (단일 트랜잭션)
- 목록/단건 조회, 삭제
- 재무·영업 DB에서 부서/개인 데이터 자동 조회 (fetch_auto_data)
"""
from datetime import date
from calendar import monthrange
import json

from database import get_connection

VALID_TYPES = {"quarter", "half", "year"}

EVAL_SLOTS = [f"evaluate_a{i}" for i in range(1, 9)]   # a1..a8

DEFAULT_CRITERIA = {
    "items": [
        {"key": "evaluate_a1", "label": "업무 점수",  "weight": 30, "enabled": True, "max": 100, "source": "peer_work"},
        {"key": "evaluate_a2", "label": "KPI 달성률", "weight": 30, "enabled": True, "max": 200, "source": "sales_kpi"},
        {"key": "evaluate_a3", "label": "리더십",     "weight": 13, "enabled": True, "max": 100, "source": "peer_leadership"},
        {"key": "evaluate_a4", "label": "전문성",     "weight": 13, "enabled": True, "max": 100, "source": "peer_expertise"},
        {"key": "evaluate_a5", "label": "협업",       "weight": 14, "enabled": True, "max": 100, "source": "peer_collaboration"},
        {"key": "evaluate_a6", "label": "",           "weight": 0,  "enabled": False, "max": 100, "source": ""},
        {"key": "evaluate_a7", "label": "",           "weight": 0,  "enabled": False, "max": 100, "source": ""},
        {"key": "evaluate_a8", "label": "",           "weight": 0,  "enabled": False, "max": 100, "source": ""},
    ],
    "thresholds": {"A": 80, "B": 65, "C": 50},
}


def calc_overall_grade(scores: dict, criteria: dict | None = None) -> str:
    """평가 기준(criteria_config)에 따라 종합 등급을 계산합니다.
    criteria가 없으면 DEFAULT_CRITERIA를 사용합니다.
    """
    cfg = criteria or DEFAULT_CRITERIA
    enabled = [i for i in cfg.get("items", []) if i.get("enabled")]
    total_weight = sum(_safe_float(i.get("weight", 0)) for i in enabled) or 1.0
    combined = 0.0
    for it in enabled:
        raw = _safe_float(scores.get(it["key"], 0))
        cap = _safe_float(it.get("max", 100)) or 100.0
        norm = min(100.0, raw / cap * 100.0)
        combined += norm * (_safe_float(it.get("weight", 0)) / total_weight)

    t = cfg.get("thresholds", {}) or {}
    if combined >= _safe_float(t.get("A", 80)):
        return "A"
    if combined >= _safe_float(t.get("B", 65)):
        return "B"
    if combined >= _safe_float(t.get("C", 50)):
        return "C"
    return "D"


# ────────────────────────────────────────────────────────────
# eval_key 생성
# ────────────────────────────────────────────────────────────

def build_eval_key(eval_type: str, year: int, value: int = 0) -> dict:
    if eval_type not in VALID_TYPES:
        raise ValueError(f"eval_type은 {VALID_TYPES} 중 하나여야 합니다.")

    if eval_type == "quarter":
        if not (1 <= value <= 4):
            raise ValueError("quarter는 1~4 사이여야 합니다.")
        sm = (value - 1) * 3 + 1
        em = sm + 2
        return {
            "eval_key":   f"EVAL-{year}-Q{value}",
            "eval_label": f"{year}년 {value}분기 인사평가",
            "eval_type":  "quarter",
            "start_date": date(year, sm, 1),
            "end_date":   date(year, em, monthrange(year, em)[1]),
        }

    if eval_type == "half":
        if not (1 <= value <= 2):
            raise ValueError("half는 1~2 사이여야 합니다.")
        sm = 1 if value == 1 else 7
        em = 6 if value == 1 else 12
        label = "상반기" if value == 1 else "하반기"
        return {
            "eval_key":   f"EVAL-{year}-H{value}",
            "eval_label": f"{year}년 {label} 인사평가",
            "eval_type":  "half",
            "start_date": date(year, sm, 1),
            "end_date":   date(year, em, monthrange(year, em)[1]),
        }

    # year
    return {
        "eval_key":   f"EVAL-{year}-FY",
        "eval_label": f"{year}년 연간 인사평가",
        "eval_type":  "year",
        "start_date": date(year, 1, 1),
        "end_date":   date(year, 12, 31),
    }


# ────────────────────────────────────────────────────────────
# 부서/직원 목록
# ────────────────────────────────────────────────────────────

def list_departments() -> list[str]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT department FROM info_employees "
            "WHERE department IS NOT NULL AND is_active = TRUE "
            "  AND department != '기타(관리자)' "
            "ORDER BY department"
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [r[0] for r in rows]


def list_employees(department: str = "") -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        if department:
            cur.execute(
                "SELECT employee_id, name, department, position "
                "FROM info_employees "
                "WHERE department = %s AND is_active = TRUE "
                "ORDER BY name",
                (department,),
            )
        else:
            cur.execute(
                "SELECT employee_id, name, department, position "
                "FROM info_employees "
                "WHERE is_active = TRUE "
                "ORDER BY department, name"
            )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [
        {"employee_id": r[0], "name": r[1], "department": r[2] or "", "position": r[3] or ""}
        for r in rows
    ]


# ────────────────────────────────────────────────────────────
# 재무·영업 자동 데이터 조회
# ────────────────────────────────────────────────────────────

def _safe_int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (ValueError, TypeError):
        return 0


def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def fetch_auto_data(department: str, start_date: str, end_date: str) -> dict:
    """
    재무/영업 DB에서 해당 부서·기간의 자동 데이터를 조회합니다.

    Returns:
        {
            finance: { budget_total, budget_spent, budget_execution_rate },
            sales: { total_revenue, total_deals, total_wins },
            employees: [ { employee_id, name, department, position } ],
            individual_sales: { "이름": { revenue, wins } }
        }
    """
    conn = get_connection()
    result = {
        "finance": {"budget_total": 0, "budget_spent": 0, "budget_execution_rate": 0.0},
        "sales": {"total_revenue": 0, "total_deals": 0, "total_wins": 0},
        "employees": [],
        "individual_sales": {},
        "peer_evaluations": {},
    }

    try:
        cur = conn.cursor()

        # 1. 직원 목록
        cur.execute(
            "SELECT employee_id, name, department, position "
            "FROM info_employees "
            "WHERE department = %s AND is_active = TRUE "
            "ORDER BY name",
            (department,),
        )
        result["employees"] = [
            {"employee_id": r[0], "name": r[1], "department": r[2] or "", "position": r[3] or ""}
            for r in cur.fetchall()
        ]

        # 2. 재무 — 예산 (연간 예산을 평가 기간에 비례하여 산출)
        fiscal_year = int(start_date[:4]) if start_date else 2026
        cur.execute(
            "SELECT COALESCE(SUM(budget_amount), 0) "
            "FROM finance_budgets "
            "WHERE department = %s AND fiscal_year = %s",
            (department, fiscal_year),
        )
        row = cur.fetchone()
        annual_budget = _safe_int(row[0]) if row else 0

        # 평가 기간 개월 수로 연간 예산을 비례 배분
        try:
            from datetime import date as _date
            sd = _date.fromisoformat(start_date)
            ed = _date.fromisoformat(end_date)
            period_months = (ed.year - sd.year) * 12 + (ed.month - sd.month) + 1
        except (ValueError, TypeError):
            period_months = 12
        budget_total = round(annual_budget * period_months / 12)
        result["finance"]["budget_total"] = budget_total

        # 3. 재무 — 지출
        cur.execute(
            "SELECT COALESCE(SUM(total_amount), 0) "
            "FROM finance_transactions "
            "WHERE department = %s AND receipt_date >= %s AND receipt_date <= %s",
            (department, start_date, end_date),
        )
        row = cur.fetchone()
        budget_spent = _safe_int(row[0]) if row else 0
        result["finance"]["budget_spent"] = budget_spent
        result["finance"]["budget_execution_rate"] = (
            round(budget_spent / budget_total * 100, 1) if budget_total > 0 else 0.0
        )

        # 4. 영업 — 부서 직원들의 영업 실적 (이름 매칭)
        employee_names = [e["name"] for e in result["employees"]]
        if employee_names:
            placeholders = ",".join(["%s"] * len(employee_names))
            cur.execute(
                f"SELECT smp.member_name, "
                f"  COALESCE(SUM(smp.revenue), 0), "
                f"  COALESCE(SUM(smp.deals), 0), "
                f"  COALESCE(SUM(smp.wins), 0) "
                f"FROM sales_member_performance smp "
                f"INNER JOIN sales_period_summary sps ON sps.period_key = smp.period_key "
                f"WHERE smp.member_name IN ({placeholders}) "
                f"  AND sps.start_date >= %s AND sps.end_date <= %s "
                f"GROUP BY smp.member_name",
                (*employee_names, start_date, end_date),
            )
            total_rev, total_deals, total_wins = 0, 0, 0
            for r in cur.fetchall():
                name = r[0]
                rev = _safe_int(r[1])
                deals = _safe_int(r[2])
                wins = _safe_int(r[3])
                result["individual_sales"][name] = {"revenue": rev, "wins": wins}
                total_rev += rev
                total_deals += deals
                total_wins += wins
            result["sales"] = {
                "total_revenue": total_rev,
                "total_deals": total_deals,
                "total_wins": total_wins,
            }

        # 5. 상호평가 — 팀원 평가에서 받은 평균 점수 (0~5 별점)
        if employee_names:
            # 평가 기간에 해당하는 분기 계산
            try:
                from datetime import date as _d
                sd = _d.fromisoformat(start_date)
                ed = _d.fromisoformat(end_date)
                quarters = set()
                for m in range(sd.month, ed.month + 1):
                    quarters.add((sd.year, (m - 1) // 3 + 1))
                if not quarters:
                    quarters.add((sd.year, (sd.month - 1) // 3 + 1))
            except (ValueError, TypeError):
                quarters = set()

            if quarters:
                q_conditions = " OR ".join(
                    f"(eval_year = %s AND eval_quarter = %s)" for _ in quarters
                )
                q_params = []
                for y, q in quarters:
                    q_params.extend([y, q])

                placeholders_names = ",".join(["%s"] * len(employee_names))
                cur.execute(
                    f"SELECT target_name, "
                    f"  COUNT(*) AS eval_count, "
                    f"  ROUND(AVG(work_score)::numeric, 1) AS avg_work, "
                    f"  ROUND(AVG(leadership_score)::numeric, 1) AS avg_leadership, "
                    f"  ROUND(AVG(expertise_score)::numeric, 1) AS avg_expertise, "
                    f"  ROUND(AVG(collaboration_score)::numeric, 1) AS avg_collaboration "
                    f"FROM hr_team_evaluations "
                    f"WHERE target_name IN ({placeholders_names}) "
                    f"  AND ({q_conditions}) "
                    f"GROUP BY target_name",
                    (*employee_names, *q_params),
                )
                for r in cur.fetchall():
                    name = r[0]
                    avg_all = (
                        _safe_float(r[2]) + _safe_float(r[3])
                        + _safe_float(r[4]) + _safe_float(r[5])
                    ) / 4
                    result["peer_evaluations"][name] = {
                        "eval_count": int(r[1]),
                        "avg_work": _safe_float(r[2]),
                        "avg_leadership": _safe_float(r[3]),
                        "avg_expertise": _safe_float(r[4]),
                        "avg_collaboration": _safe_float(r[5]),
                        "avg_total": round(avg_all, 1),
                    }

        # 6. 프로젝트 완수율 — 타 오피스 완료 건수 집계
        total_items = 0
        completed_items = 0

        # CS: 문의 완료율
        try:
            cur.execute(
                "SELECT COUNT(*), "
                "  COUNT(*) FILTER (WHERE status = '완료') "
                "FROM cs_inquiries "
                "WHERE created_at >= %s AND created_at <= %s",
                (start_date, end_date),
            )
            row = cur.fetchone()
            if row and row[0]:
                total_items += int(row[0])
                completed_items += int(row[1])
        except Exception:
            pass

        # 재무: 거래 확인율
        try:
            cur.execute(
                "SELECT COUNT(*), "
                "  COUNT(*) FILTER (WHERE status = 'confirmed') "
                "FROM finance_transactions "
                "WHERE receipt_date >= %s AND receipt_date <= %s "
                "  AND department = %s",
                (start_date, end_date, department),
            )
            row = cur.fetchone()
            if row and row[0]:
                total_items += int(row[0])
                completed_items += int(row[1])
        except Exception:
            pass

        # HR: 채용 요청 완수율
        try:
            cur.execute(
                "SELECT COUNT(*), "
                "  COUNT(*) FILTER (WHERE status = 'posting_generated') "
                "FROM hr_hire_requests "
                "WHERE request_department = %s "
                "  AND created_at >= %s AND created_at <= %s",
                (department, start_date, end_date),
            )
            row = cur.fetchone()
            if row and row[0]:
                total_items += int(row[0])
                completed_items += int(row[1])
        except Exception:
            pass

        # 영업: 수주 달성률
        try:
            if employee_names:
                placeholders_names2 = ",".join(["%s"] * len(employee_names))
                cur.execute(
                    f"SELECT COALESCE(SUM(smp.deals), 0), "
                    f"  COALESCE(SUM(smp.wins), 0) "
                    f"FROM sales_member_performance smp "
                    f"INNER JOIN sales_period_summary sps ON sps.period_key = smp.period_key "
                    f"WHERE smp.member_name IN ({placeholders_names2}) "
                    f"  AND sps.start_date >= %s AND sps.end_date <= %s",
                    (*employee_names, start_date, end_date),
                )
                row = cur.fetchone()
                if row and row[0]:
                    total_items += int(row[0])
                    completed_items += int(row[1])
        except Exception:
            pass

        result["project_completion"] = (
            round(completed_items / total_items * 100, 1) if total_items > 0 else 0.0
        )

        cur.close()
    except Exception:
        # 테이블이 없을 경우 graceful fallback
        pass
    finally:
        conn.close()

    return result


# ────────────────────────────────────────────────────────────
# 등록 (upsert)
# ────────────────────────────────────────────────────────────

def upsert_evaluation(
    eval_type: str,
    year: int,
    value: int,
    department: str,
    departments: list,
    individuals: list,
    created_by: str = "",
    created_by_name: str = "",
    criteria_config: dict | None = None,
) -> dict:
    meta = build_eval_key(eval_type, year, value)
    cfg = criteria_config or DEFAULT_CRITERIA
    cfg_json = json.dumps(cfg, ensure_ascii=False)

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()

        # 1. period upsert
        cur.execute(
            """
            INSERT INTO hr_eval_periods (
                eval_key, eval_label, eval_type, start_date, end_date,
                department, status, criteria_config, created_by, created_by_name
            ) VALUES (%s,%s,%s,%s,%s, %s,'draft',%s,%s,%s)
            ON CONFLICT (eval_key) DO UPDATE SET
                eval_label      = EXCLUDED.eval_label,
                eval_type       = EXCLUDED.eval_type,
                start_date      = EXCLUDED.start_date,
                end_date        = EXCLUDED.end_date,
                department      = EXCLUDED.department,
                criteria_config = EXCLUDED.criteria_config,
                created_by      = EXCLUDED.created_by,
                created_by_name = EXCLUDED.created_by_name,
                updated_at      = NOW()
            """,
            (
                meta["eval_key"], meta["eval_label"], meta["eval_type"],
                meta["start_date"], meta["end_date"],
                department or None, cfg_json, created_by, created_by_name,
            ),
        )

        # 2. 기존 부서/개인 제거 후 재삽입
        cur.execute("DELETE FROM hr_eval_departments WHERE eval_key = %s", (meta["eval_key"],))
        cur.execute("DELETE FROM hr_eval_individuals WHERE eval_key = %s", (meta["eval_key"],))

        for d in departments:
            budget_total = _safe_int(d.get("budget_total", 0))
            budget_spent = _safe_int(d.get("budget_spent", 0))
            exec_rate = round(budget_spent / budget_total * 100, 1) if budget_total > 0 else 0.0
            cur.execute(
                """
                INSERT INTO hr_eval_departments (
                    eval_key, department,
                    budget_total, budget_spent, budget_execution_rate,
                    sales_revenue, sales_deals, sales_wins,
                    target_achievement, project_completion, collaboration_score, headcount
                ) VALUES (%s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,%s)
                """,
                (
                    meta["eval_key"], str(d["department"])[:100],
                    budget_total, budget_spent, exec_rate,
                    _safe_int(d.get("sales_revenue", 0)),
                    _safe_int(d.get("sales_deals", 0)),
                    _safe_int(d.get("sales_wins", 0)),
                    _safe_float(d.get("target_achievement", 0)),
                    _safe_float(d.get("project_completion", 0)),
                    _safe_float(d.get("collaboration_score", 0)),
                    _safe_int(d.get("headcount", 0)),
                ),
            )

        for ind in individuals:
            scores = {slot: _safe_float(ind.get(slot, 0)) for slot in EVAL_SLOTS}
            grade = calc_overall_grade(scores, cfg)
            cur.execute(
                """
                INSERT INTO hr_eval_individuals (
                    eval_key, employee_id, employee_name, department, position,
                    sales_revenue, sales_wins,
                    evaluate_a1, evaluate_a2, evaluate_a3, evaluate_a4,
                    evaluate_a5, evaluate_a6, evaluate_a7, evaluate_a8,
                    overall_grade
                ) VALUES (%s,%s,%s,%s,%s, %s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s)
                """,
                (
                    meta["eval_key"],
                    str(ind.get("employee_id", ""))[:50] or None,
                    str(ind["employee_name"])[:100],
                    str(ind["department"])[:100],
                    str(ind.get("position", ""))[:100] or None,
                    _safe_int(ind.get("sales_revenue", 0)),
                    _safe_int(ind.get("sales_wins", 0)),
                    scores["evaluate_a1"], scores["evaluate_a2"],
                    scores["evaluate_a3"], scores["evaluate_a4"],
                    scores["evaluate_a5"], scores["evaluate_a6"],
                    scores["evaluate_a7"], scores["evaluate_a8"],
                    grade,
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
        "eval_key":   meta["eval_key"],
        "eval_label": meta["eval_label"],
        "eval_type":  meta["eval_type"],
        "start_date": meta["start_date"].isoformat(),
        "end_date":   meta["end_date"].isoformat(),
    }


# ────────────────────────────────────────────────────────────
# 조회
# ────────────────────────────────────────────────────────────

def list_eval_periods(eval_type: str = "") -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        if eval_type and eval_type in VALID_TYPES:
            cur.execute(
                "SELECT eval_key, eval_label, eval_type, start_date, end_date, department, status "
                "FROM hr_eval_periods WHERE eval_type = %s "
                "ORDER BY start_date DESC, eval_key DESC",
                (eval_type,),
            )
        else:
            cur.execute(
                "SELECT eval_key, eval_label, eval_type, start_date, end_date, department, status "
                "FROM hr_eval_periods "
                "ORDER BY start_date DESC, eval_key DESC"
            )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {
            "eval_key":   r[0],
            "eval_label": r[1],
            "eval_type":  r[2],
            "start_date": r[3].isoformat() if r[3] else "",
            "end_date":   r[4].isoformat() if r[4] else "",
            "department": r[5] or "",
            "status":     r[6],
        }
        for r in rows
    ]


def fetch_evaluation(eval_key: str) -> dict | None:
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT eval_key, eval_label, eval_type, start_date, end_date, "
            "  department, status, criteria_config, created_by, created_by_name "
            "FROM hr_eval_periods WHERE eval_key = %s",
            (eval_key,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return None

        criteria_raw = row[7]
        if isinstance(criteria_raw, str):
            try:
                criteria_raw = json.loads(criteria_raw)
            except (ValueError, TypeError):
                criteria_raw = None

        period = {
            "eval_key": row[0], "eval_label": row[1], "eval_type": row[2],
            "start_date": row[3].isoformat() if row[3] else "",
            "end_date": row[4].isoformat() if row[4] else "",
            "department": row[5] or "", "status": row[6],
            "criteria_config": criteria_raw or DEFAULT_CRITERIA,
            "created_by": row[8] or "", "created_by_name": row[9] or "",
        }

        cur.execute(
            "SELECT department, budget_total, budget_spent, budget_execution_rate, "
            "  sales_revenue, sales_deals, sales_wins, "
            "  target_achievement, project_completion, collaboration_score, headcount "
            "FROM hr_eval_departments WHERE eval_key = %s ORDER BY department",
            (eval_key,),
        )
        departments = [
            {
                "department": r[0],
                "budget_total": _safe_int(r[1]),
                "budget_spent": _safe_int(r[2]),
                "budget_execution_rate": _safe_float(r[3]),
                "sales_revenue": _safe_int(r[4]),
                "sales_deals": _safe_int(r[5]),
                "sales_wins": _safe_int(r[6]),
                "target_achievement": _safe_float(r[7]),
                "project_completion": _safe_float(r[8]),
                "collaboration_score": _safe_float(r[9]),
                "headcount": _safe_int(r[10]),
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT employee_id, employee_name, department, position, "
            "  sales_revenue, sales_wins, "
            "  evaluate_a1, evaluate_a2, evaluate_a3, evaluate_a4, "
            "  evaluate_a5, evaluate_a6, evaluate_a7, evaluate_a8, "
            "  overall_grade "
            "FROM hr_eval_individuals WHERE eval_key = %s "
            "ORDER BY department, employee_name",
            (eval_key,),
        )
        individuals = [
            {
                "employee_id": r[0] or "",
                "employee_name": r[1],
                "department": r[2],
                "position": r[3] or "",
                "sales_revenue": _safe_int(r[4]),
                "sales_wins": _safe_int(r[5]),
                "evaluate_a1": _safe_float(r[6]),
                "evaluate_a2": _safe_float(r[7]),
                "evaluate_a3": _safe_float(r[8]),
                "evaluate_a4": _safe_float(r[9]),
                "evaluate_a5": _safe_float(r[10]),
                "evaluate_a6": _safe_float(r[11]),
                "evaluate_a7": _safe_float(r[12]),
                "evaluate_a8": _safe_float(r[13]),
                "overall_grade": r[14] or "",
            }
            for r in cur.fetchall()
        ]

        cur.close()
    finally:
        conn.close()

    return {"period": period, "departments": departments, "individuals": individuals}


def fetch_my_evaluations(employee_id: str = "", employee_name: str = "") -> list[dict]:
    """특정 사원이 받은 모든 인사평가 결과를 최신순으로 반환합니다."""
    eid = (employee_id or "").strip()
    ename = (employee_name or "").strip()
    if not eid and not ename:
        raise ValueError("employee_id 또는 employee_name이 필요합니다.")

    base_sql = """
        SELECT p.eval_key, p.eval_label, p.eval_type,
               p.start_date, p.end_date, p.status, p.criteria_config,
               i.employee_id, i.employee_name, i.department, i.position,
               i.sales_revenue, i.sales_wins,
               i.evaluate_a1, i.evaluate_a2, i.evaluate_a3, i.evaluate_a4,
               i.evaluate_a5, i.evaluate_a6, i.evaluate_a7, i.evaluate_a8,
               i.overall_grade
        FROM hr_eval_individuals i
        INNER JOIN hr_eval_periods p ON p.eval_key = i.eval_key
        WHERE p.status = 'completed' AND
    """

    conn = get_connection()
    try:
        cur = conn.cursor()
        if eid:
            cur.execute(
                base_sql + " i.employee_id = %s ORDER BY p.start_date DESC, p.eval_key DESC",
                (eid,),
            )
        else:
            cur.execute(
                base_sql + " i.employee_name = %s ORDER BY p.start_date DESC, p.eval_key DESC",
                (ename,),
            )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    items = []
    for r in rows:
        cfg_raw = r[6]
        if isinstance(cfg_raw, str):
            try:
                cfg_raw = json.loads(cfg_raw)
            except (ValueError, TypeError):
                cfg_raw = None
        cfg = cfg_raw or DEFAULT_CRITERIA

        scores = {
            "evaluate_a1": _safe_float(r[13]),
            "evaluate_a2": _safe_float(r[14]),
            "evaluate_a3": _safe_float(r[15]),
            "evaluate_a4": _safe_float(r[16]),
            "evaluate_a5": _safe_float(r[17]),
            "evaluate_a6": _safe_float(r[18]),
            "evaluate_a7": _safe_float(r[19]),
            "evaluate_a8": _safe_float(r[20]),
        }

        # 종합 점수 — criteria의 가중치로 정규화한 값
        enabled = [i for i in cfg.get("items", []) if i.get("enabled")]
        total_w = sum(_safe_float(i.get("weight", 0)) for i in enabled) or 1.0
        combined = 0.0
        for it in enabled:
            raw = scores.get(it["key"], 0.0)
            cap = _safe_float(it.get("max", 100)) or 100.0
            norm = min(100.0, raw / cap * 100.0)
            combined += norm * (_safe_float(it.get("weight", 0)) / total_w)

        items.append({
            "eval_key": r[0],
            "eval_label": r[1],
            "eval_type": r[2],
            "start_date": r[3].isoformat() if r[3] else "",
            "end_date": r[4].isoformat() if r[4] else "",
            "status": r[5],
            "criteria_config": cfg,
            "employee_id": r[7] or "",
            "employee_name": r[8],
            "department": r[9],
            "position": r[10] or "",
            "sales_revenue": _safe_int(r[11]),
            "sales_wins": _safe_int(r[12]),
            **scores,
            "combined_score": round(combined, 1),
            "overall_grade": r[21] or "",
        })
    return items


def publish_evaluation(eval_key: str) -> dict:
    """평가 보고서를 등록(공개)합니다 — status를 'completed'로 변경.
    등록 후에야 개인이 본인 평가 결과 페이지에서 조회할 수 있습니다.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE hr_eval_periods SET status = 'completed', updated_at = NOW() "
            "WHERE eval_key = %s RETURNING eval_key, status",
            (eval_key,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    if not row:
        raise ValueError("등록된 평가가 없습니다.")
    return {"eval_key": row[0], "status": row[1]}


def delete_evaluation(eval_key: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM hr_eval_periods WHERE eval_key = %s", (eval_key,))
        deleted = cur.rowcount > 0
        cur.close()
    finally:
        conn.close()
    return deleted
