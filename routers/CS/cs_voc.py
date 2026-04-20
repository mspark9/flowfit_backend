"""
CS VOC 분석 라우터 — /api/cs/voc/*
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from services.CS.cs_voc_service import analyze_voc

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# POST /api/cs/voc/analyze
# ──────────────────────────────────────────────────────────────
@router.post("/analyze")
async def voc_analyze(
    file:      UploadFile        = File(...),
    prev_file: Optional[UploadFile] = File(default=None),
    threshold: int               = Form(default=30),
):
    """
    주간 문의 로그를 분석하여 VOC 리포트를 생성합니다.

    Request : multipart/form-data { file(csv), prev_file?(csv), threshold?(int) }
    Response: {
      period, total_count, prev_count,
      sentiment: { positive, neutral, negative },
      top_issues: [{ type, count, change_pct, cause }],
      summary
    }
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="CSV 파일만 업로드할 수 있습니다.")

    if threshold < 1 or threshold > 500:
        raise HTTPException(status_code=400, detail="threshold는 1~500 사이여야 합니다.")

    current_bytes = await file.read()
    if not current_bytes:
        raise HTTPException(status_code=400, detail="파일이 비어 있습니다.")

    prev_bytes = None
    if prev_file and prev_file.filename:
        prev_bytes = await prev_file.read()

    try:
        report = analyze_voc(
            current_csv=current_bytes,
            prev_csv=prev_bytes,
            threshold=threshold,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 분석 실패: {str(e)}")

    return report
