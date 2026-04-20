"""
일회성 마이그레이션 스크립트
uploads/ 폴더의 영수증 이미지를 receipt_images 테이블로 이전합니다.

실행법: python migrate_uploads.py
"""
import uuid
from pathlib import Path
from database import get_connection

UPLOAD_DIR  = Path("uploads")
IMAGE_EXTS  = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

EXT_TO_MIME = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}


def migrate():
    # ── receipt_images 테이블 보장 ────────────────────────────
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS receipt_images (
            id           UUID PRIMARY KEY,
            filename     TEXT,
            content_type TEXT,
            image_data   BYTEA,
            created_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.close()
    conn.close()

    if not UPLOAD_DIR.exists():
        print("uploads/ 폴더가 없습니다. 마이그레이션 대상 없음.")
        return

    image_files = [f for f in UPLOAD_DIR.iterdir() if f.suffix.lower() in IMAGE_EXTS]

    if not image_files:
        print("uploads/ 에 이미지 파일이 없습니다.")
        return

    print(f"총 {len(image_files)}개 파일 마이그레이션 시작...\n")
    migrated = 0
    skipped  = 0

    for img_path in image_files:
        filename = img_path.name
        ext      = img_path.suffix.lower()
        mime     = EXT_TO_MIME.get(ext, "image/jpeg")

        # 이미 마이그레이션된 파일인지 확인 (filename 기준)
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("SELECT id FROM receipt_images WHERE filename = %s", (filename,))
        existing = cur.fetchone()

        if existing:
            print(f"  SKIP  {filename} (이미 존재: {existing[0]})")
            cur.close()
            conn.close()
            skipped += 1
            continue

        # 이미지 읽기
        try:
            image_data = img_path.read_bytes()
        except Exception as e:
            print(f"  ERROR {filename}: 파일 읽기 실패 — {e}")
            cur.close()
            conn.close()
            continue

        # receipt_images INSERT
        new_id = str(uuid.uuid4())
        try:
            cur.execute(
                "INSERT INTO receipt_images (id, filename, content_type, image_data) VALUES (%s, %s, %s, %s)",
                (new_id, filename, mime, image_data),
            )
        except Exception as e:
            print(f"  ERROR {filename}: DB 저장 실패 — {e}")
            cur.close()
            conn.close()
            continue

        # finance_transactions image_path 업데이트
        old_path = f"uploads/{filename}"
        cur.execute(
            "UPDATE finance_transactions SET image_path = %s WHERE image_path = %s",
            (new_id, old_path),
        )
        updated_rows = cur.rowcount

        cur.close()
        conn.close()

        # 원본 파일 삭제
        try:
            img_path.unlink()
        except Exception as e:
            print(f"  WARN  {filename}: 파일 삭제 실패 — {e}")

        print(f"  OK    {filename} → {new_id}  (전표 {updated_rows}건 업데이트)")
        migrated += 1

    print(f"\n완료: {migrated}개 마이그레이션, {skipped}개 건너뜀")


if __name__ == "__main__":
    migrate()
