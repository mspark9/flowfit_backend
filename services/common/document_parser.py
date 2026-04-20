"""
공통 문서 파서 — HWP / DOCX / PDF / TXT 텍스트 추출 + 이미지 Base64 인코딩
hr_regulation_service 및 legal_chat_service 등에서 공유 사용
"""
import base64
import re
import zlib
from io import BytesIO
from pathlib import Path

# Vision API 지원 이미지 확장자 → MIME 타입 매핑
IMAGE_MIME_TYPES = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".gif":  "image/gif",
}

# HWP BodyText 레코드 태그 ID
HWP_TEXT_TAG_ID = 67


# ── 지연 임포트 헬퍼 ───────────────────────────────────────────

def _get_olefile_module():
    try:
        import olefile
    except ImportError as exc:
        raise RuntimeError(
            "HWP 업로드 기능을 사용하려면 olefile 패키지가 필요합니다. "
            "python -m pip install olefile 후 다시 시도해 주세요."
        ) from exc
    return olefile


def _get_docx_document():
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError(
            "DOCX 업로드 기능을 사용하려면 python-docx 패키지가 필요합니다. "
            "python -m pip install python-docx 후 다시 시도해 주세요."
        ) from exc
    return Document


def _get_pdf_reader():
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF 업로드 기능을 사용하려면 pypdf 패키지가 필요합니다. "
            "python -m pip install pypdf 후 다시 시도해 주세요."
        ) from exc
    return PdfReader


# ── 텍스트 정규화 / 파일명 정제 ───────────────────────────────

def _normalize_text(text: str) -> str:
    """제어 문자 제거, 연속 공백·줄바꿈 정리"""
    cleaned = text.replace("\r", "\n").replace("\x00", "")
    cleaned = re.sub(r"[\x01-\x08\x0b-\x1f\x7f]", " ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _sanitize_filename(filename: str) -> str:
    """파일명에서 특수문자 제거"""
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", filename or "document.pdf")
    return safe or "document.pdf"


# ── HWP 내부 헬퍼 ─────────────────────────────────────────────

def _read_utf16_stream(ole, stream_name: str) -> str:
    data = ole.openstream(stream_name).read()
    for encoding in ("utf-16-le", "utf-16", "utf-8"):
        try:
            text = data.decode(encoding)
            normalized = _normalize_text(text)
            if normalized:
                return normalized
        except UnicodeDecodeError:
            continue
    return ""


def _extract_preview_text(ole) -> str:
    if ole.exists("PrvText"):
        return _read_utf16_stream(ole, "PrvText")
    return ""


def _maybe_decompress(data: bytes) -> bytes:
    for wbits in (-15, zlib.MAX_WBITS):
        try:
            return zlib.decompress(data, wbits)
        except zlib.error:
            continue
    return data


def _extract_body_text(ole) -> str:
    section_names = []
    for entry in ole.listdir():
        if len(entry) == 2 and entry[0] == "BodyText" and entry[1].startswith("Section"):
            section_names.append("/".join(entry))

    texts = []
    for stream_name in sorted(section_names):
        raw = ole.openstream(stream_name).read()
        data = _maybe_decompress(raw)
        offset = 0

        while offset + 4 <= len(data):
            header = int.from_bytes(data[offset:offset + 4], "little")
            tag_id = header & 0x3FF
            size = (header >> 20) & 0xFFF
            offset += 4

            if size == 0xFFF:
                if offset + 4 > len(data):
                    break
                size = int.from_bytes(data[offset:offset + 4], "little")
                offset += 4

            record = data[offset:offset + size]
            offset += size

            if tag_id != HWP_TEXT_TAG_ID or not record:
                continue

            try:
                text = record.decode("utf-16-le", errors="ignore")
            except UnicodeDecodeError:
                continue

            normalized = _normalize_text(text)
            if normalized:
                texts.append(normalized)

    return "\n".join(texts).strip()


# ── 공개 추출 함수 ─────────────────────────────────────────────

def extract_hwp_text(hwp_bytes: bytes) -> str:
    """HWP 바이트 → 텍스트 추출"""
    olefile = _get_olefile_module()
    buffer = BytesIO(hwp_bytes)
    if not olefile.isOleFile(buffer):
        raise ValueError("올바른 HWP 파일 형식이 아닙니다.")

    buffer.seek(0)
    with olefile.OleFileIO(buffer) as ole:
        preview_text = _extract_preview_text(ole)
        body_text = _extract_body_text(ole)

    extracted = body_text if len(body_text) >= len(preview_text) else preview_text
    extracted = _normalize_text(extracted)

    if len(extracted) < 20:
        raise ValueError("HWP 문서에서 읽을 수 있는 텍스트를 추출하지 못했습니다.")

    return extracted


def extract_docx_text(docx_bytes: bytes) -> str:
    """DOCX 바이트 → 텍스트 추출"""
    Document = _get_docx_document()
    document = Document(BytesIO(docx_bytes))

    paragraphs = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text and paragraph.text.strip()
    ]
    extracted = _normalize_text("\n".join(paragraphs))

    if len(extracted) < 20:
        raise ValueError("DOCX 문서에서 읽을 수 있는 텍스트를 추출하지 못했습니다.")

    return extracted


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """PDF 바이트 → 텍스트 추출"""
    PdfReader = _get_pdf_reader()
    reader = PdfReader(BytesIO(pdf_bytes))

    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        normalized = _normalize_text(text)
        if normalized:
            pages.append(normalized)

    extracted = "\n\n".join(pages).strip()
    if len(extracted) < 20:
        raise ValueError("PDF 문서에서 읽을 수 있는 텍스트를 추출하지 못했습니다.")

    return extracted


def extract_txt_text(txt_bytes: bytes) -> str:
    """TXT 바이트 → 텍스트 추출 (UTF-8 / CP949 순으로 시도)"""
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            text = txt_bytes.decode(encoding)
            extracted = _normalize_text(text)
            if len(extracted) >= 20:
                return extracted
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError("TXT 파일을 읽지 못했습니다. UTF-8 또는 CP949 인코딩을 확인해 주세요.")


def extract_document_text(filename: str, file_bytes: bytes) -> str:
    """파일 확장자에 따라 적절한 추출 함수 호출 (hwp / docx / pdf / txt)"""
    extension = Path(filename or "").suffix.lower()

    if extension == ".hwp":
        return extract_hwp_text(file_bytes)
    if extension == ".docx":
        return extract_docx_text(file_bytes)
    if extension == ".pdf":
        return extract_pdf_text(file_bytes)
    if extension == ".txt":
        return extract_txt_text(file_bytes)

    raise ValueError("지원하지 않는 파일 형식입니다. hwp, docx, pdf, txt만 업로드할 수 있습니다.")


def is_image_file(filename: str) -> bool:
    """파일명이 Vision API 지원 이미지 확장자인지 확인"""
    ext = Path(filename or "").suffix.lower()
    return ext in IMAGE_MIME_TYPES


def encode_image_base64(filename: str, file_bytes: bytes) -> tuple[str, str]:
    """
    이미지 바이트 → Base64 인코딩.
    반환: (base64_string, mime_type)  e.g. ("iVBOR...", "image/png")
    """
    ext = Path(filename or "").suffix.lower()
    mime = IMAGE_MIME_TYPES.get(ext)
    if not mime:
        raise ValueError(f"지원하지 않는 이미지 형식입니다: {ext}")
    return base64.b64encode(file_bytes).decode("utf-8"), mime
