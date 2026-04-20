"""
CRM mock 저장소 — JSON 파일 기반 영업 기회 저장/조회

실제 Salesforce/HubSpot 연동 전 단계로, 미팅 요약의 CRM 초안을
'원클릭 반영' 시뮬레이션하기 위한 로컬 저장소입니다.

- 동시성: 파일 락으로 쓰기 보호 (스레드 수준)
- 소유자: 레코드마다 owner_id / owner_name 기록 (A안)
- 필터 : owner_id, company_name, 검색어(search), offset/limit (B안)
"""
import json
import os
import threading
import uuid
from datetime import datetime

# 저장 파일 경로 (uploads 폴더 재사용)
STORE_PATH = os.path.join("uploads", "crm_opportunities.json")

# 파일 I/O 동시성 보호
_lock = threading.Lock()

# 허용 단계
VALID_STAGES = {"리드 발굴", "니즈 분석", "제안서 발송", "협상 중", "계약 완료"}


def _load() -> list:
    """저장된 영업 기회 목록을 로드합니다. 파일이 없으면 빈 리스트."""
    if not os.path.exists(STORE_PATH):
        return []
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _dump(items: list) -> None:
    """영업 기회 목록을 파일에 저장합니다."""
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def save_opportunity(
    company_name: str,
    meeting_date: str,
    opportunity_name: str,
    stage: str,
    next_step: str,
    contact_role: str,
    description: str,
    owner_id: str = "",
    owner_name: str = "",
) -> dict:
    """
    영업 기회를 mock CRM 저장소에 저장합니다.

    Args:
        owner_id:   저장한 사원 ID (로그인 세션에서 전달). 비어 있으면 '미지정'.
        owner_name: 저장한 사원 이름 (표시용).

    Returns:
        저장된 레코드 (id, created_at 포함)
    """
    if stage not in VALID_STAGES:
        raise ValueError(f"지원하지 않는 단계입니다: {stage}")

    record = {
        "id":               str(uuid.uuid4())[:8],
        "company_name":     company_name,
        "meeting_date":     meeting_date,
        "opportunity_name": opportunity_name,
        "stage":            stage,
        "next_step":        next_step,
        "contact_role":     contact_role,
        "description":      description,
        "owner_id":         owner_id or "",
        "owner_name":       owner_name or "",
        "created_at":       datetime.now().isoformat(timespec="seconds"),
    }

    with _lock:
        items = _load()
        items.insert(0, record)  # 최신순
        _dump(items)

    return record


def list_opportunities(
    owner_id: str = "",
    company_name: str = "",
    search: str = "",
    offset: int = 0,
    limit: int = 10,
) -> dict:
    """
    저장된 영업 기회를 필터링하여 반환합니다.

    Args:
        owner_id:     특정 사원 ID만 조회 ("" = 전원)
        company_name: 고객사명 부분 일치 (대소문자 무시)
        search:       영업 기회명·설명·고객사명 부분 일치
        offset/limit: 페이지네이션

    Returns:
        {
          items:       [ 필터링된 최신순 레코드 ],
          total:       필터 조건에 해당하는 전체 건수,
          offset, limit
        }
    """
    with _lock:
        items = _load()

    # 필터 체인 (이미 최신순으로 저장되어 있음)
    def _match(rec: dict) -> bool:
        if owner_id and rec.get("owner_id", "") != owner_id:
            return False
        if company_name:
            if company_name.lower() not in (rec.get("company_name", "") or "").lower():
                return False
        if search:
            hay = " ".join([
                rec.get("opportunity_name", ""),
                rec.get("company_name", ""),
                rec.get("description", ""),
                rec.get("next_step", ""),
                rec.get("stage", ""),
                rec.get("owner_name", ""),
            ]).lower()
            if search.lower() not in hay:
                return False
        return True

    filtered = [r for r in items if _match(r)]
    total = len(filtered)

    # 페이지네이션
    off = max(int(offset), 0)
    lim = max(min(int(limit), 100), 1)
    page = filtered[off : off + lim]

    return {
        "items":  page,
        "total":  total,
        "offset": off,
        "limit":  lim,
    }
