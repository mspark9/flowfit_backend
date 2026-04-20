"""
CS VOC 분석 서비스 — 주간 문의 로그 감성 분석 + 이상 감지 + 리포트 생성
"""
import csv
import io
import json
from collections import Counter
from openai import OpenAI
from config import settings

client = OpenAI(api_key=settings.openai_api_key)

SENTIMENT_PROMPT = """
다음 고객 문의를 읽고 감성을 분류하세요.
반드시 아래 셋 중 하나만 값으로 사용하세요: 긍정, 중립, 부정
JSON으로만 응답하세요. 예시: {{"sentiment": "부정"}}

문의: {inquiry}
"""

INQUIRY_TYPE_PROMPT = """
다음 고객 문의의 유형을 분류하세요.
반드시 아래 목록 중 하나만 값으로 사용하세요: 배송, 반품/교환, 환불, 결제, 상품, 주문, 회원/계정, 혜택, 기타
JSON으로만 응답하세요. 예시: {{"type": "반품/교환"}}

문의: {inquiry}
"""

VALID_TYPES = {"배송", "반품/교환", "환불", "결제", "상품", "주문", "회원/계정", "혜택", "기타"}

REPORT_SUMMARY_PROMPT = """
아래 CS VOC 분석 결과를 바탕으로 팀장 보고용 요약을 작성하세요.

분석 결과:
- 총 문의 건수: {total_count}건
- 전주 대비: {change_str}
- 부정 감성 비율: {negative_pct}%
- 주요 급증 이슈: {top_issues_str}

작성 형식 (각 항목은 빈 줄로 구분, 번호·항목명 없이 자연스러운 문장으로):
1. 전체 현황 요약 — 총 건수·전주 대비 증감·부정 감성 비율을 2~3문장으로
2. 급증 이슈 종합 — 이슈들을 개별 나열하지 말고, 전체 흐름과 공통 원인을 2~3문장으로 요약
3. 조치 제안 — 우선순위 중심으로 1~2문장
"""


def _classify_batch(inquiries: list[str], prompt_template: str, key: str) -> list[str]:
    """문의 목록을 배치로 분류 (비용 절감: 최대 50개 샘플링)"""
    sample = inquiries[:50]
    results = []
    for text in sample:
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt_template.format(inquiry=text[:300])}],
                max_tokens=50,
            )
            data  = json.loads(res.choices[0].message.content)
            value = data.get(key, "")
            # GPT가 선택지 전체 문자열을 반환하는 경우 정규화
            if key == "sentiment":
                if "부정" in value:
                    value = "부정"
                elif "긍정" in value:
                    value = "긍정"
                else:
                    value = "중립"
            elif key == "type":
                if value not in VALID_TYPES:
                    # 유효한 유형 중 포함된 것 탐색
                    matched = next((t for t in VALID_TYPES if t in value), "기타")
                    value = matched
            results.append(value or ("기타" if key == "type" else "중립"))
        except Exception:
            results.append("기타" if key == "type" else "중립")

    # 50개 초과분은 비율 기반 확장
    if len(inquiries) > 50:
        ratio      = len(inquiries) / len(sample)
        type_count = Counter(results)
        expanded   = []
        for label, cnt in type_count.items():
            expanded.extend([label] * round(cnt * ratio))
        return expanded[:len(inquiries)]

    return results


def _parse_csv(csv_bytes: bytes) -> list[str]:
    """CSV에서 문의 텍스트 컬럼을 찾아 추출"""
    text   = csv_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows   = list(reader)
    if not rows:
        return []

    # 헤더 행 전체를 스캔해 문의 텍스트 컬럼 인덱스 탐색
    # "유형", "분류" 등 카테고리 컬럼은 제외하고 탐색
    INQUIRY_KEYWORDS = ["고객문의원문", "문의원문", "문의내용", "원문", "inquiry_text", "inquiry", "text", "내용", "질문"]
    EXCLUDE_KEYWORDS = ["유형", "분류", "타입", "type"]
    inquiry_col = 0
    has_header  = False
    for i, col in enumerate(rows[0]):
        col_stripped = col.strip()
        if any(ex in col_stripped for ex in EXCLUDE_KEYWORDS):
            continue
        if any(kw in col_stripped for kw in INQUIRY_KEYWORDS):
            inquiry_col = i
            has_header  = True
            break

    start = 1 if has_header else 0
    return [
        row[inquiry_col].strip()
        for row in rows[start:]
        if len(row) > inquiry_col and row[inquiry_col].strip()
    ]


def analyze_voc(
    current_csv: bytes,
    prev_csv: bytes | None,
    threshold: int,
) -> dict:
    """
    주간 VOC 분석 리포트를 생성합니다.

    Args:
        current_csv: 이번 주 문의 로그 CSV
        prev_csv:    이전 주 문의 로그 CSV (없으면 None)
        threshold:   이상 감지 임계값 (전주 대비 %, 예: 30)

    Returns:
        {
          "period": str,
          "total_count": int,
          "prev_count": int | None,
          "sentiment": {"positive": int, "neutral": int, "negative": int},
          "top_issues": [{"type": str, "count": int, "change_pct": float | None, "cause": str}],
          "summary": str
        }
    """
    inquiries      = _parse_csv(current_csv)
    total_count    = len(inquiries)

    if total_count == 0:
        raise ValueError("문의 로그가 비어 있습니다.")

    prev_inquiries = _parse_csv(prev_csv) if prev_csv else []
    prev_count     = len(prev_inquiries) if prev_inquiries else None

    # 감성 분석
    sentiments    = _classify_batch(inquiries, SENTIMENT_PROMPT, "sentiment")
    sent_counter  = Counter(sentiments)
    total_analyzed = len(sentiments)

    def pct(label: str) -> int:
        return round(sent_counter.get(label, 0) / total_analyzed * 100)

    sentiment_result = {
        "positive": pct("긍정"),
        "neutral":  pct("중립"),
        "negative": pct("부정"),
    }

    # 유형 분류
    types        = _classify_batch(inquiries, INQUIRY_TYPE_PROMPT, "type")
    type_counter = Counter(types)

    # 이전 주 유형 카운트 (증감 계산용)
    prev_type_counter: Counter = Counter()
    if prev_inquiries:
        prev_types       = _classify_batch(prev_inquiries, INQUIRY_TYPE_PROMPT, "type")
        prev_type_counter = Counter(prev_types)

    # 이상 감지 + Top 이슈 추출 (건수 많은 순 Top 3)
    top_issues = []
    for issue_type, count in type_counter.most_common(3):
        prev_cnt   = prev_type_counter.get(issue_type, 0)
        change_pct = None
        if prev_cnt > 0:
            change_pct = round((count - prev_cnt) / prev_cnt * 100, 1)

        # 이상 감지 시 원인 추정
        cause = ""
        if change_pct is not None and abs(change_pct) >= threshold:
            cause_res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": (
                        f"CS 문의에서 '{issue_type}' 유형이 전주 대비 {change_pct:+.1f}% 변동했습니다. "
                        f"가능한 원인을 1문장으로 추정해 주세요."
                    ),
                }],
                max_tokens=100,
            )
            cause = cause_res.choices[0].message.content.strip()

        top_issues.append({
            "type":       issue_type,
            "count":      count,
            "change_pct": change_pct,
            "cause":      cause,
        })

    # 팀장 보고 요약
    change_str = f"{((total_count - prev_count) / prev_count * 100):+.1f}%" if prev_count else "비교 데이터 없음"

    top_issues_str = ", ".join(
        f"{i['type']} {i['count']}건({i['change_pct']:+.1f}%)" if i["change_pct"] is not None
        else f"{i['type']} {i['count']}건"
        for i in top_issues
    ) or "해당 없음"

    summary_res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": REPORT_SUMMARY_PROMPT.format(
                total_count=total_count,
                change_str=change_str,
                negative_pct=sentiment_result["negative"],
                top_issues_str=top_issues_str,
            ),
        }],
        max_tokens=600,
    )
    summary = summary_res.choices[0].message.content.strip()

    return {
        "period":      "이번 주",
        "total_count": total_count,
        "prev_count":  prev_count,
        "sentiment":   sentiment_result,
        "top_issues":  top_issues,
        "summary":     summary,
    }
