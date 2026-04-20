"""
CS 정책 라우터 — /api/cs/policy/*
정책 문서(docx) 업로드 → FAQ 영향 분석 → 수정 초안 저장
"""
from fastapi import APIRouter, HTTPException, UploadFile, File

from services.CS.cs_policy_service import analyze_policy_impact
from database import get_connection

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# POST /api/cs/policy/upload  — 정책 문서 업로드 → FAQ 자동 플래그
# ──────────────────────────────────────────────────────────────
@router.post("/upload")
async def upload_policy(file: UploadFile = File(...)):
    """
    정책 문서(docx)를 업로드하면 기존 FAQ와 비교하여
    수정이 필요한 FAQ를 flagged = true로 표시하고 수정 초안을 저장합니다.

    Request : multipart/form-data { file(.docx) }
    Response: { updated_count: int, flagged_faqs: [{id, question, suggested_answer, reason}] }
    """
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="docx 파일만 업로드할 수 있습니다.")

    docx_bytes = await file.read()
    if not docx_bytes:
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")

    # 1. DB에서 전체 FAQ 로드
    conn = get_connection()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT id, category, question, answer FROM cs_faqs ORDER BY id")
        rows = cur.fetchall()
    except Exception as e:
        cur.close()
        conn.close()
        raise HTTPException(status_code=500, detail=f"FAQ 조회 실패: {str(e)}")

    faqs = [
        {"id": r[0], "category": r[1], "question": r[2], "answer": r[3]}
        for r in rows
    ]

    if not faqs:
        cur.close()
        conn.close()
        return {"updated_count": 0, "flagged_faqs": [], "message": "저장된 FAQ가 없습니다."}

    # 2. 정책 분석
    try:
        results = analyze_policy_impact(docx_bytes, faqs)
    except RuntimeError as e:
        cur.close()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        cur.close()
        conn.close()
        raise HTTPException(status_code=502, detail=f"AI 분석 실패: {str(e)}")

    if not results:
        cur.close()
        conn.close()
        return {"updated_count": 0, "flagged_faqs": [], "message": "정책과 불일치하는 FAQ가 없습니다."}

    # 3. DB 업데이트 — flagged=true + suggested_answer 저장
    faq_map = {f["id"]: f for f in faqs}
    flagged_faqs = []

    try:
        for item in results:
            faq_id   = item["faq_id"]
            if faq_id not in faq_map:
                continue
            cur.execute(
                """
                UPDATE cs_faqs
                SET flagged = TRUE, suggested_answer = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (item["suggested_answer"], faq_id),
            )
            flagged_faqs.append({
                "id":               faq_id,
                "question":         faq_map[faq_id]["question"],
                "suggested_answer": item["suggested_answer"],
                "reason":           item["reason"],
            })
    except Exception as e:
        cur.close()
        conn.close()
        raise HTTPException(status_code=500, detail=f"DB 업데이트 실패: {str(e)}")
    finally:
        cur.close()
        conn.close()

    return {
        "updated_count": len(flagged_faqs),
        "flagged_faqs":  flagged_faqs,
    }
