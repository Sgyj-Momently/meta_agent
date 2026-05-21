"""Generate Naver-blog focused metadata from finalised Markdown."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

DEFAULT_META_MODEL = "qwen2.5:14b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120

TITLE_MIN_LEN = 18
TITLE_MAX_LEN = 40
META_DESC_MAX_LEN = 155
HASHTAG_MAX_COUNT = 10
CRANK_BODY_CHAR_THRESHOLD = 1500
CRANK_IMAGE_COUNT_THRESHOLD = 5

DEFAULT_CATEGORY = "일상"
CATEGORY_KEYWORDS = (
    ("맛집", "맛집"),
    ("카페", "맛집"),
    ("여행", "여행"),
    ("리뷰", "리뷰"),
    ("후기", "리뷰"),
    ("육아", "육아"),
    ("일기", "일상"),
    ("기록", "일상"),
)


def generate_meta(payload: dict[str, Any]) -> dict[str, Any]:
    markdown = str(payload.get("final_markdown") or "").strip()
    raw_keywords = payload.get("target_keywords")
    photos = payload.get("photos") or []

    keywords = _parse_keywords(raw_keywords)
    body_title = _extract_body_title(markdown)

    llm_meta: dict[str, Any] | None = None
    llm_error: str | None = None
    if markdown and not _llm_disabled():
        try:
            llm_meta = _generate_with_ollama(markdown, keywords)
        except Exception as exc:
            logger.warning("Ollama meta generation failed: %s", exc)
            llm_error = str(exc)

    title_candidates = _build_title_candidates(llm_meta, body_title, markdown, keywords)
    hashtags = _build_hashtags(llm_meta, keywords, body_title)
    meta_description = _build_meta_description(llm_meta, markdown, keywords)
    recommended_category = _build_recommended_category(llm_meta, markdown)
    meta_signals = _compute_meta_signals(markdown, photos, keywords)

    if llm_error:
        meta_status = "ok_fallback"
    elif not keywords:
        meta_status = "ok_no_keywords"
    else:
        meta_status = "ok"

    return {
        "meta_status": meta_status,
        "title_candidates": title_candidates,
        "hashtags": hashtags,
        "meta_description": meta_description,
        "recommended_category": recommended_category,
        "meta_signals": meta_signals,
    }


def _llm_disabled() -> bool:
    return os.getenv("META_DISABLE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_keywords(raw: Any) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    parts = re.split(r"[,\n;/·]+", text)
    seen: list[str] = []
    for part in parts:
        token = part.strip()
        if token and token not in seen:
            seen.append(token)
    return seen


def _extract_body_title(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _generate_with_ollama(markdown: str, keywords: list[str]) -> dict[str, Any]:
    model_name = os.getenv("META_MODEL", DEFAULT_META_MODEL)
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
    timeout_seconds = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS)))

    prompt = _build_meta_prompt(markdown, keywords)
    body = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    http_request = urllib_request.Request(
        url=f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(http_request, timeout=timeout_seconds) as response:
        response_payload = json.loads(response.read().decode("utf-8"))

    raw = str(response_payload.get("response") or "").strip()
    if not raw:
        raise ValueError("empty Ollama response")
    raw = _strip_markdown_fence(raw)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Ollama response is not a JSON object")
    return parsed


def _build_meta_prompt(markdown: str, keywords: list[str]) -> str:
    keyword_line = (
        f"주력 검색어: {', '.join(keywords)} (제목·해시태그·메타 디스크립션에 자연스럽게 포함하라)"
        if keywords
        else "주력 검색어가 지정되지 않았으므로 본문 핵심 주제어를 추론해서 활용하라"
    )
    return f"""당신은 한국어 네이버 블로그 SEO 메타 작성자다.
아래 마크다운 본문을 읽고 네이버 C-Rank/D.I.A 검색 노출에 유리한 메타데이터를 JSON으로만 반환하라.

{keyword_line}

규칙:
- titles: 정확히 3개. 각 18~40자 한국어 제목. 낚시성 표현 금지. 이모지는 최대 1개.
- hashtags: 5~10개. # 기호 없이 순수 단어만. 주력 검색어와 의미 연관어, 위치/카테고리 태그 혼합.
- meta_description: 155자 이내 한 문장. 본문 핵심을 압축하고 첫 문장에 주력 검색어 포함.
- recommended_category: 다음 중 하나 — 맛집, 여행, 리뷰, 일상, 육아.
- 키워드 스터핑(같은 검색어 4회 이상 반복) 금지.
- 반드시 한국어로만 작성. 다른 언어 혼용 금지.

반드시 다음 JSON 스키마로만 응답하라. 설명·마크다운 코드블록·주석 금지:
{{
  "titles": ["...", "...", "..."],
  "hashtags": ["...", "..."],
  "meta_description": "...",
  "recommended_category": "..."
}}

본문 마크다운:
{markdown}""".strip()


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json|markdown|md)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _build_title_candidates(
    llm_meta: dict[str, Any] | None,
    body_title: str,
    markdown: str,
    keywords: list[str],
) -> list[dict[str, Any]]:
    candidates: list[str] = []
    if llm_meta:
        for raw in llm_meta.get("titles") or []:
            text = _clean_title(raw)
            if text and text not in candidates:
                candidates.append(text)

    primary_keyword = keywords[0] if keywords else ""
    fallback_seed = body_title or _first_sentence(markdown) or "오늘의 기록"

    suffix_pool = ["솔직 후기 한 줄 정리", "다녀온 기록과 추천 포인트", "직접 가본 솔직 리뷰"]
    suffix_index = 0
    while len(candidates) < 3 and suffix_index < len(suffix_pool) * 2:
        fallback = _make_fallback_title(fallback_seed, primary_keyword, suffix_pool, suffix_index)
        if fallback and fallback not in candidates:
            candidates.append(fallback)
        suffix_index += 1

    return [_describe_title(text, keywords) for text in candidates[:3]]


def _clean_title(raw: Any) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"^[#\-\*\d\.\)\s]+", "", text)
    text = text.strip().strip("\"'")
    return text[:60]


def _first_sentence(markdown: str) -> str:
    body = re.sub(r"^#+\s.*$", "", markdown, flags=re.MULTILINE).strip()
    parts = re.split(r"[.!?。\n]", body, maxsplit=1)
    return parts[0].strip() if parts else ""


def _make_fallback_title(
    seed: str,
    primary_keyword: str,
    suffix_pool: list[str],
    index: int,
) -> str:
    suffix = suffix_pool[index % len(suffix_pool)]
    base = seed.strip() or "오늘의 기록"
    if primary_keyword and primary_keyword not in base:
        title = f"{primary_keyword} {base} {suffix}"
    else:
        title = f"{base} {suffix}"
    return title[:TITLE_MAX_LEN]


def _describe_title(title: str, keywords: list[str]) -> dict[str, Any]:
    contains_primary = bool(keywords) and any(
        kw.lower() in title.lower() for kw in keywords[:1]
    )
    contains_any = bool(keywords) and any(kw.lower() in title.lower() for kw in keywords)
    length = len(title)
    if length < TITLE_MIN_LEN:
        intent = "짧음 — 검색 노출 약함"
    elif length > TITLE_MAX_LEN:
        intent = "긺 — 모바일 잘림 위험"
    elif contains_primary:
        intent = "주력 검색어 포함"
    elif contains_any:
        intent = "보조 검색어 포함"
    else:
        intent = "검색어 미반영"
    return {
        "title": title,
        "length": length,
        "contains_primary_keyword": contains_primary,
        "contains_any_keyword": contains_any,
        "intent_note": intent,
    }


def _build_hashtags(
    llm_meta: dict[str, Any] | None,
    keywords: list[str],
    body_title: str,
) -> list[str]:
    tags: list[str] = []
    if llm_meta:
        for raw in llm_meta.get("hashtags") or []:
            token = _clean_hashtag(raw)
            if token and token not in tags:
                tags.append(token)

    for kw in keywords:
        token = _clean_hashtag(kw)
        if token and token not in tags:
            tags.append(token)

    if body_title:
        for word in re.findall(r"[가-힣A-Za-z0-9]+", body_title):
            token = _clean_hashtag(word)
            if token and token not in tags and len(token) >= 2:
                tags.append(token)

    if not tags:
        tags = ["일상기록"]

    return tags[:HASHTAG_MAX_COUNT]


def _clean_hashtag(raw: Any) -> str:
    text = str(raw or "").strip().lstrip("#").strip()
    text = re.sub(r"\s+", "", text)
    return text[:30]


def _build_meta_description(
    llm_meta: dict[str, Any] | None,
    markdown: str,
    keywords: list[str],
) -> str:
    text = ""
    if llm_meta:
        text = str(llm_meta.get("meta_description") or "").strip()
    if not text:
        text = _first_sentence(markdown)
    if not text:
        text = "오늘의 기록을 한 줄로 정리한 글입니다."
    if keywords and keywords[0].lower() not in text.lower():
        text = f"{keywords[0]} — {text}"
    return text[:META_DESC_MAX_LEN]


def _build_recommended_category(llm_meta: dict[str, Any] | None, markdown: str) -> str:
    if llm_meta:
        raw = str(llm_meta.get("recommended_category") or "").strip()
        if raw:
            return raw
    for needle, category in CATEGORY_KEYWORDS:
        if needle in markdown:
            return category
    return DEFAULT_CATEGORY


def _compute_meta_signals(
    markdown: str,
    photos: list[Any],
    keywords: list[str],
) -> dict[str, Any]:
    body_char_count = len(re.sub(r"\s+", "", markdown))
    image_count = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown))

    own_photo_count = 0
    total_photo_count = 0
    for photo in photos:
        if not isinstance(photo, dict):
            continue
        total_photo_count += 1
        if photo.get("has_exif") or photo.get("captured_at") or photo.get("has_gps"):
            own_photo_count += 1
    owned_ratio = round(own_photo_count / total_photo_count, 2) if total_photo_count else None

    lowered = markdown.lower()
    keyword_occurrences = {kw: lowered.count(kw.lower()) for kw in keywords}

    warnings: list[str] = []
    if body_char_count < CRANK_BODY_CHAR_THRESHOLD:
        warnings.append(
            f"본문 글자수 {body_char_count}자 — 권장 {CRANK_BODY_CHAR_THRESHOLD}자 이상"
        )
    if image_count < CRANK_IMAGE_COUNT_THRESHOLD:
        warnings.append(
            f"이미지 {image_count}장 — 권장 {CRANK_IMAGE_COUNT_THRESHOLD}장 이상"
        )
    if owned_ratio is not None and owned_ratio < 0.5:
        warnings.append("자체 촬영 추정 비율 50% 미만 — C-Rank 신뢰도 가중치 약화 가능")
    if keywords and all(occ == 0 for occ in keyword_occurrences.values()):
        warnings.append("주력 검색어가 본문에 한 번도 등장하지 않음")

    return {
        "body_char_count": body_char_count,
        "image_count": image_count,
        "owned_photo_ratio": owned_ratio,
        "keyword_occurrences": keyword_occurrences,
        "warnings": warnings,
    }
