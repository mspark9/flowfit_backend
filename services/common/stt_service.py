"""
공통 STT 서비스 — 오디오 파일을 텍스트로 변환 (OpenAI Whisper)
sales/meeting · CS/response 등 여러 모듈에서 공유 사용
"""
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

# Whisper API 지원 포맷
ALLOWED_EXTENSIONS = {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "ogg"}

# Whisper API 파일 크기 상한 (25MB)
MAX_FILE_SIZE = 25 * 1024 * 1024


def transcribe_audio(file_bytes: bytes, filename: str, language: str = "ko") -> str:
    """
    오디오 파일을 텍스트로 변환합니다.

    Args:
        file_bytes: 오디오 파일 바이너리
        filename:   원본 파일명 (확장자 판별용)
        language:   ISO-639-1 코드 (기본 'ko')

    Returns:
        변환된 텍스트
    """
    res = client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, file_bytes),
        language=language,
        response_format="text",
    )
    return res if isinstance(res, str) else getattr(res, "text", "")
