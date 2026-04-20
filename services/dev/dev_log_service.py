"""
장애 로그 분석 서비스
에러 로그 / 스택트레이스 입력 → GPT-4o-mini로 원인 분석 + 조치 방안 제안
"""
import json

from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = (
    "당신은 백엔드/인프라 장애 분석 전문가입니다. "
    "제공된 에러 로그·스택트레이스를 분석하여 근본 원인과 해결 방법을 제시하세요. "
    "추측이 필요한 경우 명확히 표시하세요. "
    "응답은 반드시 JSON만 반환하세요."
)


def analyze_log(log_text: str, context: str = "") -> dict:
    """
    에러 로그 분석:
    - log_text: 분석할 로그·스택트레이스
    - context: 추가 컨텍스트 (서비스명, 환경 등, 선택)
    """
    if not log_text.strip():
        raise ValueError("로그를 입력해 주세요.")
    if len(log_text) > 20000:
        raise ValueError("로그가 너무 깁니다. 20,000자 이하로 입력해 주세요.")

    user_content = f"[에러 로그]\n{log_text.strip()}"
    if context.strip():
        user_content = f"[추가 컨텍스트]\n{context.strip()}\n\n" + user_content

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    user_content
                    + "\n\n[반환 형식]\n"
                    "{\n"
                    '  "summary": "한 줄 요약",\n'
                    '  "root_cause": "근본 원인 설명",\n'
                    '  "severity": "critical | high | medium | low",\n'
                    '  "actions": [\n'
                    '    {"step": 1, "title": "조치 제목", "description": "상세 설명"}\n'
                    "  ],\n"
                    '  "prevention": "재발 방지 방안",\n'
                    '  "related_components": ["관련 컴포넌트 목록"]\n'
                    "}"
                ),
            },
        ],
        max_tokens=1500,
        temperature=0.2,
    )

    payload = json.loads(response.choices[0].message.content)

    return {
        "summary": payload.get("summary", ""),
        "root_cause": payload.get("root_cause", ""),
        "severity": payload.get("severity", "medium"),
        "actions": payload.get("actions", []),
        "prevention": payload.get("prevention", ""),
        "related_components": payload.get("related_components", []),
    }
