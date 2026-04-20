"""
릴리즈 노트 생성 서비스
커밋 메시지 목록 → GPT-4o-mini → 사용자 친화적 릴리즈 노트
"""
import json

from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = (
    "당신은 소프트웨어 릴리즈 노트 작성 전문가입니다. "
    "커밋 메시지를 분석하여 사용자와 이해관계자가 읽기 쉬운 릴리즈 노트를 작성하세요. "
    "기술적인 내용은 비기술적인 언어로 바꾸고, 카테고리별로 분류하세요. "
    "응답은 반드시 JSON만 반환하세요."
)


def generate_release_note(
    commits: str,
    version: str = "",
    product_name: str = "",
    audience: str = "general",
) -> dict:
    """
    릴리즈 노트 생성:
    - commits: 커밋 메시지 목록 (한 줄에 하나 또는 번호 목록)
    - version: 버전명 (예: v1.2.0), 선택
    - product_name: 제품/서비스명, 선택
    - audience: 대상 독자 - general(일반) | developer(개발자) | manager(관리자)
    """
    if not commits.strip():
        raise ValueError("커밋 메시지를 입력해 주세요.")
    if len(commits) > 10000:
        raise ValueError("입력이 너무 깁니다. 10,000자 이하로 입력해 주세요.")

    audience_guide = {
        "general": "일반 사용자 대상 — 기술 용어 최소화, 기능 변화 중심",
        "developer": "개발자 대상 — API 변경, 기술 스펙, breaking changes 명시",
        "manager": "관리자/임원 대상 — 비즈니스 임팩트, KPI 연관성 중심",
    }.get(audience, "일반 사용자 대상")

    header_parts = []
    if product_name.strip():
        header_parts.append(f"제품명: {product_name.strip()}")
    if version.strip():
        header_parts.append(f"버전: {version.strip()}")
    header = "\n".join(header_parts)

    user_content = ""
    if header:
        user_content += f"{header}\n\n"
    user_content += f"[대상 독자]\n{audience_guide}\n\n[커밋 메시지]\n{commits.strip()}"

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
                    '  "title": "릴리즈 노트 제목",\n'
                    '  "summary": "이번 릴리즈 전체 요약 (2-3문장)",\n'
                    '  "sections": [\n'
                    '    {\n'
                    '      "category": "카테고리명 (예: 새 기능, 개선사항, 버그 수정, 보안, 주의사항)",\n'
                    '      "items": ["항목1", "항목2"]\n'
                    '    }\n'
                    '  ],\n'
                    '  "breaking_changes": ["하위 호환성 깨는 변경사항 (없으면 빈 배열)"],\n'
                    '  "notes": "추가 안내 사항 (없으면 빈 문자열)"\n'
                    "}"
                ),
            },
        ],
        max_tokens=1500,
        temperature=0.3,
    )

    payload = json.loads(response.choices[0].message.content)

    return {
        "title": payload.get("title", "릴리즈 노트"),
        "summary": payload.get("summary", ""),
        "sections": payload.get("sections", []),
        "breaking_changes": payload.get("breaking_changes", []),
        "notes": payload.get("notes", ""),
        "version": version.strip(),
        "product_name": product_name.strip(),
    }
