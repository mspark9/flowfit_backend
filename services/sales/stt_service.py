"""
STT 서비스 — services.common.stt_service로 이전됨.
하위 호환을 위해 re-export.
"""
from services.common.stt_service import (  # noqa: F401
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    transcribe_audio,
)
