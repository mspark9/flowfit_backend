"""
CS FAQ 라우터 — /api/cs/faq/*
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

from services.CS.cs_faq_service import generate_faqs_from_csv
from database import get_connection

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# 요청 스키마
# ──────────────────────────────────────────────────────────────
class FaqUpdateRequest(BaseModel):
    category:         Optional[str]  = None
    question:         Optional[str]  = None
    answer:           Optional[str]  = None
    flagged:          Optional[bool] = None
    suggested_answer: Optional[str]  = None  # None이면 유지, "" 빈 문자열이면 초기화


# ──────────────────────────────────────────────────────────────
# POST /api/cs/faq/generate  — CSV 업로드 → FAQ 자동 생성
# ──────────────────────────────────────────────────────────────
@router.post("/generate")
async def generate_faq(
    file:  UploadFile = File(...),
    top_n: int        = Query(default=10, ge=1, le=50),
):
    """
    문의 로그 CSV를 클러스터링하여 FAQ top_n개를 생성합니다.

    Request : multipart/form-data { file(csv), top_n? }
    Response: { faqs: [{ category, question, answer }] }
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSV 파일만 업로드할 수 있습니다.")

    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")

    try:
        faqs = generate_faqs_from_csv(csv_bytes, top_n)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 처리 실패: {str(e)}")

    return {"faqs": faqs}


# ──────────────────────────────────────────────────────────────
# GET /api/cs/faq  — DB에 저장된 FAQ 목록 조회
# ──────────────────────────────────────────────────────────────
@router.get("/")
def list_faqs(
    category: Optional[str] = Query(default=None),
    flagged:  Optional[bool] = Query(default=None),
    limit:    int            = Query(default=50, le=200),
    offset:   int            = Query(default=0, ge=0),
):
    """
    DB에 저장된 FAQ 목록을 반환합니다.

    Query params:
      category (str, optional)  — 카테고리 필터
      flagged  (bool, optional) — 업데이트 필요 항목만 조회
      limit    (int, default 50)
      offset   (int, default 0)
    Response: { total, items: [...] }
    """
    where_clauses = []
    params = []

    if category:
        where_clauses.append("category = %s")
        params.append(category)
    if flagged is not None:
        where_clauses.append("flagged = %s")
        params.append(flagged)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM cs_faqs {where_sql}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT id, category, question, answer, flagged, suggested_answer, created_at, updated_at
            FROM cs_faqs
            {where_sql}
            ORDER BY flagged DESC, category, created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"조회 실패: {str(e)}")
    finally:
        cur.close()
        conn.close()

    return {
        "total": total,
        "items": [
            {
                "id":               r[0],
                "category":         r[1],
                "question":         r[2],
                "answer":           r[3],
                "flagged":          r[4],
                "suggested_answer": r[5],
                "created_at":       str(r[6]),
                "updated_at":       str(r[7]),
            }
            for r in rows
        ],
    }


# ──────────────────────────────────────────────────────────────
# POST /api/cs/faq/save  — 생성된 FAQ를 DB에 저장
# ──────────────────────────────────────────────────────────────
class FaqSaveItem(BaseModel):
    category: str
    question: str
    answer:   str

class FaqSaveRequest(BaseModel):
    faqs: list[FaqSaveItem]

@router.post("/save", status_code=201)
def save_faqs(body: FaqSaveRequest):
    """
    생성된 FAQ 목록을 DB에 저장합니다.

    Request : application/json { faqs: [{ category, question, answer }] }
    Response: { saved_count: int }
    """
    if not body.faqs:
        raise HTTPException(status_code=400, detail="저장할 FAQ가 없습니다.")

    conn = get_connection()
    cur  = conn.cursor()
    try:
        for faq in body.faqs:
            cur.execute(
                """
                INSERT INTO cs_faqs (category, question, answer)
                VALUES (%s, %s, %s)
                """,
                (faq.category, faq.question, faq.answer),
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB 저장 실패: {str(e)}")
    finally:
        cur.close()
        conn.close()

    return {"saved_count": len(body.faqs)}


# ──────────────────────────────────────────────────────────────
# PUT /api/cs/faq/{faq_id}  — FAQ 수정
# ──────────────────────────────────────────────────────────────
@router.put("/{faq_id}")
def update_faq(faq_id: int, body: FaqUpdateRequest):
    """
    FAQ를 수정합니다.

    Request : application/json { category?, question?, answer?, flagged? }
    Response: { id, category, question, answer, flagged, updated_at }
    """
    set_clauses = []
    params      = []

    if body.category is not None:
        set_clauses.append("category = %s");          params.append(body.category)
    if body.question is not None:
        set_clauses.append("question = %s");          params.append(body.question)
    if body.answer is not None:
        set_clauses.append("answer = %s");            params.append(body.answer)
    if body.flagged is not None:
        set_clauses.append("flagged = %s");           params.append(body.flagged)
    if body.suggested_answer is not None:
        set_clauses.append("suggested_answer = %s");  params.append(body.suggested_answer or None)

    if not set_clauses:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다.")

    params.append(faq_id)
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE cs_faqs
            SET {', '.join(set_clauses)}, updated_at = NOW()
            WHERE id = %s
            RETURNING id, category, question, answer, flagged, suggested_answer, updated_at
            """,
            params,
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="FAQ를 찾을 수 없습니다.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"수정 실패: {str(e)}")
    finally:
        cur.close()
        conn.close()

    return {
        "id":               row[0],
        "category":         row[1],
        "question":         row[2],
        "answer":           row[3],
        "flagged":          row[4],
        "suggested_answer": row[5],
        "updated_at":       str(row[6]),
    }
