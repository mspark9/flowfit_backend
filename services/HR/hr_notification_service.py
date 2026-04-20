"""
HR 알림 서비스 — DB 저장 / 조회 / 읽음 처리
"""
from __future__ import annotations

from uuid import uuid4

from database import get_connection
from services.HR.hr_regulation_service import get_regulation_conflicts

HISTORY_DAYS = 50
HISTORY_MAX_COUNT = 200

NOTIFICATION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS hr_notifications (
    id                SERIAL          PRIMARY KEY,
    notification_key  VARCHAR(255)    NOT NULL UNIQUE,
    source            VARCHAR(100)    NOT NULL,
    message           TEXT            NOT NULL,
    notification_type VARCHAR(50)     NOT NULL DEFAULT 'event',
    is_active         BOOLEAN         NOT NULL DEFAULT TRUE,
    read_at           TIMESTAMPTZ,
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
)
"""

NOTIFICATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_hr_notifications_active_read ON hr_notifications (is_active, read_at)",
    "CREATE INDEX IF NOT EXISTS idx_hr_notifications_created_at ON hr_notifications (created_at DESC)",
]


def _ensure_notification_table(cur) -> None:
    cur.execute(NOTIFICATION_TABLE_DDL)
    for ddl in NOTIFICATION_INDEXES:
        cur.execute(ddl)


def _prune_notifications(cur) -> None:
    cur.execute(
        f"""
        DELETE FROM hr_notifications
        WHERE created_at < NOW() - INTERVAL '{HISTORY_DAYS} days'
        """
    )
    cur.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (ORDER BY created_at DESC, id DESC) AS row_num
            FROM hr_notifications
        )
        DELETE FROM hr_notifications AS target
        USING ranked
        WHERE target.id = ranked.id
          AND ranked.row_num > %s
        """,
        (HISTORY_MAX_COUNT,),
    )


def _serialize_notification_row(row) -> dict:
    return {
        "id": row[0],
        "notification_key": row[1],
        "source": row[2],
        "message": row[3],
        "notification_type": row[4],
        "is_active": row[5],
        "read_at": str(row[6]) if row[6] else None,
        "created_at": str(row[7]) if row[7] else None,
        "updated_at": str(row[8]) if row[8] else None,
    }


def _fetch_notification_by_key(cur, notification_key: str):
    cur.execute(
        """
        SELECT id, notification_key, source, message, notification_type,
               is_active, read_at, created_at, updated_at
        FROM hr_notifications
        WHERE notification_key = %s
        """,
        (notification_key,),
    )
    return cur.fetchone()


def _insert_notification(cur, *, notification_key: str, source: str, message: str, notification_type: str, is_active: bool):
    cur.execute(
        """
        INSERT INTO hr_notifications (
            notification_key, source, message, notification_type, is_active
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, notification_key, source, message, notification_type,
                  is_active, read_at, created_at, updated_at
        """,
        (notification_key, source, message, notification_type, is_active),
    )
    return cur.fetchone()


def _update_notification(cur, *, notification_key: str, source: str, message: str, notification_type: str, is_active: bool, reset_read: bool):
    if reset_read:
        cur.execute(
            """
            UPDATE hr_notifications
               SET source = %s,
                   message = %s,
                   notification_type = %s,
                   is_active = %s,
                   read_at = NULL,
                   created_at = NOW(),
                   updated_at = NOW()
             WHERE notification_key = %s
            RETURNING id, notification_key, source, message, notification_type,
                      is_active, read_at, created_at, updated_at
            """,
            (source, message, notification_type, is_active, notification_key),
        )
    else:
        cur.execute(
            """
            UPDATE hr_notifications
               SET source = %s,
                   message = %s,
                   notification_type = %s,
                   is_active = %s,
                   updated_at = NOW()
             WHERE notification_key = %s
            RETURNING id, notification_key, source, message, notification_type,
                      is_active, read_at, created_at, updated_at
            """,
            (source, message, notification_type, is_active, notification_key),
        )
    return cur.fetchone()


def _upsert_dynamic_notification(cur, *, notification_key: str, source: str, message: str, notification_type: str = "dynamic", is_active: bool = True):
    row = _fetch_notification_by_key(cur, notification_key)
    if not row and not is_active:
        return None
    if not row:
        return _insert_notification(
            cur,
            notification_key=notification_key,
            source=source,
            message=message,
            notification_type=notification_type,
            is_active=is_active,
        )

    message_changed = row[3] != message
    reactivated = (not row[5]) and is_active

    if row[2] == source and row[3] == message and row[4] == notification_type and row[5] == is_active:
        return row

    return _update_notification(
        cur,
        notification_key=notification_key,
        source=source,
        message=message,
        notification_type=notification_type,
        is_active=is_active,
        reset_read=message_changed or reactivated,
    )


def create_notification(message: str, source: str, notification_type: str = "event") -> dict | None:
    message = (message or "").strip()
    source = (source or "").strip() or "기타"
    if not message:
        return None

    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_notification_table(cur)
        row = _insert_notification(
            cur,
            notification_key=f"event-{uuid4()}",
            source=source,
            message=message,
            notification_type=notification_type,
            is_active=True,
        )
        _prune_notifications(cur)
    finally:
        cur.close()
        conn.close()

    return _serialize_notification_row(row)


def _sync_pending_notification(cur) -> None:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM info_employees
        WHERE is_verified = FALSE
        """
    )
    count = int(cur.fetchone()[0] or 0)

    if count > 0:
        _upsert_dynamic_notification(
            cur,
            notification_key="pending-approval",
            source="계정 승인 관리",
            message=f"{count}건의 계정 승인 요청이 있습니다.",
            is_active=True,
        )
        return

    _upsert_dynamic_notification(
        cur,
        notification_key="pending-approval",
        source="계정 승인 관리",
        message="0건의 계정 승인 요청이 있습니다.",
        is_active=False,
    )


def _sync_regulation_conflict_notification(cur) -> None:
    try:
        payload = get_regulation_conflicts()
    except Exception:
        payload = {"has_conflict": False, "items": []}

    items = payload.get("items") or []
    if items:
        top = items[0]
        file_names = ", ".join(f"'{name}'" for name in (top.get("file_names") or []))
        clause_titles = ", ".join(f"'{name}'" for name in (top.get("clause_titles") or []))
        _upsert_dynamic_notification(
            cur,
            notification_key="regulation-conflict",
            source="규정 문서 업로드",
            message=f"{file_names} 파일의 규정이 충돌합니다. 확인이 필요합니다. 충돌 규정: {clause_titles}",
            is_active=True,
        )
        return

    _upsert_dynamic_notification(
        cur,
        notification_key="regulation-conflict",
        source="규정 문서 업로드",
        message="규정 충돌 없음",
        is_active=False,
    )


def sync_dynamic_notifications() -> None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_notification_table(cur)
        _sync_pending_notification(cur)
        _sync_regulation_conflict_notification(cur)
        _prune_notifications(cur)
    finally:
        cur.close()
        conn.close()


def list_notifications() -> list[dict]:
    sync_dynamic_notifications()

    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_notification_table(cur)
        _prune_notifications(cur)
        cur.execute(
            """
            SELECT id, notification_key, source, message, notification_type,
                   is_active, read_at, created_at, updated_at
            FROM hr_notifications
            ORDER BY created_at DESC, id DESC
            """
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    return [_serialize_notification_row(row) for row in rows]


def mark_notification_read(notification_id: int) -> dict | None:
    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_notification_table(cur)
        cur.execute(
            """
            UPDATE hr_notifications
               SET read_at = NOW(),
                   updated_at = NOW()
             WHERE id = %s
            RETURNING id, notification_key, source, message, notification_type,
                      is_active, read_at, created_at, updated_at
            """,
            (notification_id,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    return _serialize_notification_row(row) if row else None


def mark_notifications_read(notification_ids: list[int]) -> int:
    notification_ids = [int(item) for item in notification_ids if str(item).strip()]
    if not notification_ids:
        return 0

    conn = get_connection()
    cur = conn.cursor()
    try:
        _ensure_notification_table(cur)
        placeholders = ", ".join(["%s"] * len(notification_ids))
        cur.execute(
            f"""
            UPDATE hr_notifications
               SET read_at = NOW(),
                   updated_at = NOW()
             WHERE id IN ({placeholders})
            """,
            tuple(notification_ids),
        )
        updated_count = cur.rowcount or 0
    finally:
        cur.close()
        conn.close()

    return int(updated_count)
