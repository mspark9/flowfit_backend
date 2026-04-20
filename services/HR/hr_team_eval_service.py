"""
팀원 평가 서비스 - 같은 부서 팀원에게 점수를 부여하고 조회

- 로그인 사용자의 부서 기준으로 같은 부서 팀원 목록 조회
- 팀원 평가 점수 저장 (upsert)
- 본인이 제출한 평가 이력 조회
"""
from database import get_connection


def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def get_team_members(evaluator_id: str, department: str) -> list[dict]:
    """같은 부서 소속 직원 목록 (본인 제외)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT employee_id, name, department, position "
            "FROM info_employees "
            "WHERE department = %s AND is_active = TRUE AND employee_id != %s "
            "ORDER BY name",
            (department, evaluator_id),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [
        {"employee_id": r[0], "name": r[1], "department": r[2] or "", "position": r[3] or ""}
        for r in rows
    ]


def upsert_team_evaluations(
    evaluator_id: str,
    evaluator_name: str,
    evaluator_department: str,
    eval_year: int,
    eval_quarter: int,
    evaluations: list[dict],
) -> dict:
    """
    팀원 평가를 일괄 저장합니다.

    evaluations: [{
        target_id, target_name, target_department, target_position,
        work_score, leadership_score, expertise_score, collaboration_score, comment
    }, ...]
    """
    conn = get_connection()
    conn.autocommit = False
    saved = 0
    try:
        cur = conn.cursor()
        for ev in evaluations:
            cur.execute(
                """
                INSERT INTO hr_team_evaluations (
                    evaluator_id, evaluator_name, evaluator_department,
                    target_id, target_name, target_department, target_position,
                    eval_year, eval_quarter,
                    work_score, leadership_score, expertise_score, collaboration_score,
                    comment
                ) VALUES (%s,%s,%s, %s,%s,%s,%s, %s,%s, %s,%s,%s,%s, %s)
                ON CONFLICT (evaluator_id, target_name, eval_year, eval_quarter) DO UPDATE SET
                    target_id            = EXCLUDED.target_id,
                    target_department    = EXCLUDED.target_department,
                    target_position      = EXCLUDED.target_position,
                    work_score           = EXCLUDED.work_score,
                    leadership_score     = EXCLUDED.leadership_score,
                    expertise_score      = EXCLUDED.expertise_score,
                    collaboration_score  = EXCLUDED.collaboration_score,
                    comment              = EXCLUDED.comment,
                    updated_at           = NOW()
                """,
                (
                    evaluator_id, evaluator_name, evaluator_department,
                    str(ev.get("target_id", ""))[:50] or None,
                    str(ev["target_name"])[:100],
                    str(ev.get("target_department", ""))[:100],
                    str(ev.get("target_position", ""))[:100] or None,
                    eval_year, eval_quarter,
                    _safe_float(ev.get("work_score", 0)),
                    _safe_float(ev.get("leadership_score", 0)),
                    _safe_float(ev.get("expertise_score", 0)),
                    _safe_float(ev.get("collaboration_score", 0)),
                    str(ev.get("comment", ""))[:2000] or None,
                ),
            )
            saved += 1
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True
        conn.close()

    return {"saved": saved, "eval_year": eval_year, "eval_quarter": eval_quarter}


def fetch_my_evaluations(
    evaluator_id: str,
    eval_year: int,
    eval_quarter: int,
) -> list[dict]:
    """본인이 제출한 해당 분기 평가 목록 조회."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT target_id, target_name, target_department, target_position, "
            "  work_score, leadership_score, expertise_score, collaboration_score, "
            "  comment, created_at, updated_at "
            "FROM hr_team_evaluations "
            "WHERE evaluator_id = %s AND eval_year = %s AND eval_quarter = %s "
            "ORDER BY target_name",
            (evaluator_id, eval_year, eval_quarter),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {
            "target_id": r[0] or "",
            "target_name": r[1],
            "target_department": r[2] or "",
            "target_position": r[3] or "",
            "work_score": _safe_float(r[4]),
            "leadership_score": _safe_float(r[5]),
            "expertise_score": _safe_float(r[6]),
            "collaboration_score": _safe_float(r[7]),
            "comment": r[8] or "",
            "created_at": r[9].isoformat() if r[9] else "",
            "updated_at": r[10].isoformat() if r[10] else "",
        }
        for r in rows
    ]


def fetch_team_eval_summary(
    department: str,
    eval_year: int,
    eval_quarter: int,
) -> list[dict]:
    """
    특정 부서·분기의 팀원 평가 집계 (HR 관리자용).
    각 대상자별 평균 점수와 평가자 수를 반환합니다.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT target_name, target_position, "
            "  COUNT(*) AS eval_count, "
            "  ROUND(AVG(work_score)::numeric, 1) AS avg_work, "
            "  ROUND(AVG(leadership_score)::numeric, 1) AS avg_leadership, "
            "  ROUND(AVG(expertise_score)::numeric, 1) AS avg_expertise, "
            "  ROUND(AVG(collaboration_score)::numeric, 1) AS avg_collaboration "
            "FROM hr_team_evaluations "
            "WHERE target_department = %s AND eval_year = %s AND eval_quarter = %s "
            "GROUP BY target_name, target_position "
            "ORDER BY avg_work DESC",
            (department, eval_year, eval_quarter),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [
        {
            "target_name": r[0],
            "target_position": r[1] or "",
            "eval_count": int(r[2]),
            "avg_work": _safe_float(r[3]),
            "avg_leadership": _safe_float(r[4]),
            "avg_expertise": _safe_float(r[5]),
            "avg_collaboration": _safe_float(r[6]),
        }
        for r in rows
    ]


def fetch_my_received_evaluations(
    target_name: str,
    eval_year: int,
    eval_quarter: int,
) -> dict:
    """
    나에 대한 평가 결과를 조회합니다.
    평균 점수 + 익명 코멘트 목록을 반환합니다 (평가자 정보 제외).
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        # 평균 점수 + 평가자 수
        cur.execute(
            "SELECT COUNT(*) AS eval_count, "
            "  ROUND(AVG(work_score)::numeric, 1) AS avg_work, "
            "  ROUND(AVG(leadership_score)::numeric, 1) AS avg_leadership, "
            "  ROUND(AVG(expertise_score)::numeric, 1) AS avg_expertise, "
            "  ROUND(AVG(collaboration_score)::numeric, 1) AS avg_collaboration "
            "FROM hr_team_evaluations "
            "WHERE target_name = %s AND eval_year = %s AND eval_quarter = %s",
            (target_name, eval_year, eval_quarter),
        )
        row = cur.fetchone()

        if not row or int(row[0]) == 0:
            cur.close()
            return {"eval_count": 0, "scores": None, "comments": []}

        scores = {
            "eval_count": int(row[0]),
            "avg_work": _safe_float(row[1]),
            "avg_leadership": _safe_float(row[2]),
            "avg_expertise": _safe_float(row[3]),
            "avg_collaboration": _safe_float(row[4]),
        }

        # 익명 코멘트 (평가자 정보 제외, 빈 코멘트 제외)
        cur.execute(
            "SELECT comment, created_at "
            "FROM hr_team_evaluations "
            "WHERE target_name = %s AND eval_year = %s AND eval_quarter = %s "
            "  AND comment IS NOT NULL AND TRIM(comment) != '' "
            "ORDER BY created_at DESC",
            (target_name, eval_year, eval_quarter),
        )
        comments = [
            {
                "comment": r[0],
                "created_at": r[1].isoformat() if r[1] else "",
            }
            for r in cur.fetchall()
        ]

        cur.close()
    finally:
        conn.close()

    return {"eval_count": scores["eval_count"], "scores": scores, "comments": comments}
