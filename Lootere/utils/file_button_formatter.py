import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from typing import Optional

from .smart_search_engine import parse_smart_media_item

MAX_BUTTON_TEXT_LENGTH = 64
_MAX_SOURCE_TOKENS = 3

_SOURCE_GROUPS = (
    ("WEB-DL", re.compile(r"\bweb[\s._-]*dl\b", re.IGNORECASE)),
    ("WEBRip", re.compile(r"\bweb[\s._-]*rip\b", re.IGNORECASE)),
    ("BluRay", re.compile(r"\b(?:blu[\s._-]*ray|brrip|bdrip)\b", re.IGNORECASE)),
    ("HDRip", re.compile(r"\bhd[\s._-]*rip\b", re.IGNORECASE)),
    ("HDTV", re.compile(r"\bhdtv\b", re.IGNORECASE)),
    ("HEVC", re.compile(r"\b(?:hevc|x265|h[\s._-]*265)\b", re.IGNORECASE)),
    ("x264", re.compile(r"\b(?:x264|h[\s._-]*264|avc)\b", re.IGNORECASE)),
    ("HDR", re.compile(r"\bhdr(?:10)?\b", re.IGNORECASE)),
    ("DV", re.compile(r"\b(?:dv|dolby[\s._-]*vision)\b", re.IGNORECASE)),
)

_EPISODE_RE = re.compile(r"\bS\d{1,2}E\d{1,3}\b", re.IGNORECASE)
_QUALITY_TOKEN_RE = re.compile(
    r"\b(?:360|480|576|720|1080|1440|2160)\s*p\b|\b(?:4k|uhd)\b",
    re.IGNORECASE,
)
_LANGUAGE_TOKEN_RE = re.compile(
    r"\b(?:hindi|hin|english|eng|tamil|tam|telugu|tel|malayalam|mal|"
    r"kannada|kan|bengali|ben|marathi|mar|punjabi|pun|gujarati|guj|"
    r"korean|kor|japanese|jap|jpn|dual[\s._-]*audio|multi[\s._-]*audio)\b",
    re.IGNORECASE,
)
_SERIES_MARKER_RE = re.compile(
    r"(?:S\d{1,2}[\s._-]*E\d{1,3}|"
    r"(?:Season|S)\s*\d{1,2}[\s._-]*(?:Episode|Ep|E)\s*\d{1,3}|"
    r"\d{1,2}\s*[xX]\s*\d{1,3}|"
    r"Season\s*\d{1,2}|Episode\s*\d{1,3}|Ep\s*\d{1,3}|\bE\d{2,3}\b)",
    re.IGNORECASE,
)


def _format_size(size_bytes) -> str:
    try:
        size = Decimal(str(int(size_bytes)))
    except (TypeError, ValueError, ArithmeticError):
        return ""
    if size <= 0:
        return ""
    gb = Decimal(1024 ** 3)
    mb = Decimal(1024 ** 2)
    if size >= gb:
        value = size / gb
        unit = "GB"
    else:
        value = size / mb
        unit = "MB"
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:.2f} {unit}"


def _extract_sources(cleaned_name: str):
    found = []
    for label, pattern in _SOURCE_GROUPS:
        if len(found) >= _MAX_SOURCE_TOKENS:
            break
        if pattern.search(cleaned_name) and label.lower() not in {
            item.lower() for item in found
        }:
            found.append(label)
    return found


def _quality_variants(quality: Optional[str], cleaned_name: str):
    base = str(quality).strip() if quality else ""
    sources = _extract_sources(cleaned_name)
    variants = []
    if base:
        for count in range(len(sources), -1, -1):
            label = " ".join([base] + sources[:count]).strip()
            if label not in variants:
                variants.append(label)
    else:
        for count in range(len(sources), 0, -1):
            label = " ".join(sources[:count]).strip()
            if label not in variants:
                variants.append(label)
    if not variants:
        variants.append("")
    return variants


def _strip_leading_quality(title: str, quality_label: str) -> str:
    if not title or not quality_label:
        return title
    tokens = [token for token in quality_label.split() if token]
    changed = True
    while changed:
        changed = False
        for token in tokens:
            if title.lower().startswith(f"{token.lower()} "):
                title = title[len(token):].lstrip(" -_.:|")
                changed = True
                break
    return title.strip()


def _normalize_title(title: str) -> str:
    title = re.sub(r"[_\.+]+", " ", str(title or ""))
    title = re.sub(r"\s{2,}", " ", title)
    return title.strip(" -_.:|[](){}")


def _metadata_anchors(cleaned_name: str, parsed) -> list:
    anchors = []
    year = getattr(parsed, "year", None)
    if year:
        for match in re.finditer(rf"(?<!\d){re.escape(str(year))}(?!\d)", cleaned_name):
            if match.start() > 0:
                anchors.append(match.start())
    patterns = [_QUALITY_TOKEN_RE, _LANGUAGE_TOKEN_RE]
    patterns.extend(pattern for _, pattern in _SOURCE_GROUPS)
    for pattern in patterns:
        for match in pattern.finditer(cleaned_name):
            if match.start() > 0:
                anchors.append(match.start())
    return anchors


def _extract_title(parsed, cleaned_name: str, quality_label: str) -> str:
    cleaned_name = str(cleaned_name or "")
    raw_title = cleaned_name
    if getattr(parsed, "category", "") == "series":
        series_anchors = []
        marker = _SERIES_MARKER_RE.search(cleaned_name)
        if marker and marker.start() > 0:
            series_anchors.append(marker.start())
        year = getattr(parsed, "year", None)
        if year:
            for match in re.finditer(
                rf"(?<!\d){re.escape(str(year))}(?!\d)", cleaned_name
            ):
                if match.start() > 0:
                    series_anchors.append(match.start())
        if series_anchors:
            raw_title = cleaned_name[:min(series_anchors)]
    else:
        anchors = _metadata_anchors(cleaned_name, parsed)
        if anchors:
            raw_title = cleaned_name[:min(anchors)]
    title = _normalize_title(raw_title)
    title = _strip_leading_quality(title, quality_label)
    if not title:
        title = _normalize_title(
            getattr(parsed, "title", "") or cleaned_name
        )
    return title


def _episode_suffix(parsed) -> str:
    if getattr(parsed, "category", "") != "series":
        return ""
    season = getattr(parsed, "season", None)
    episode = getattr(parsed, "episode", None)
    if season is not None and episode is not None:
        return f"S{int(season):02d}E{int(episode):02d}"
    if episode is not None:
        return f"E{int(episode):02d}"
    if season is not None:
        return f"S{int(season):02d}"
    return ""


def _contains_year(title: str, year: str) -> bool:
    return bool(re.search(rf"(?<!\d){re.escape(str(year))}(?!\d)", title))


def _truncate_title(title: str, max_len: int, suffix: str = "") -> str:
    if max_len <= 0:
        return ""
    if len(title) <= max_len:
        return title
    if suffix and title.lower().endswith(suffix.lower()):
        prefix = title[:-len(suffix)].rstrip()
        room = max_len - len(suffix) - 2
        if room >= 3:
            return f"{prefix[:room].rstrip()}… {suffix}"
    if max_len == 1:
        return "…"
    return f"{title[:max_len - 1].rstrip()}…"


def _assemble_label(parts, title: str, suffix: str) -> str:
    fixed = [part for part in parts if part]
    label = " ".join(fixed)
    if len(label) <= MAX_BUTTON_TEXT_LENGTH:
        return label
    other_len = len(label) - len(title)
    max_title_len = MAX_BUTTON_TEXT_LENGTH - other_len
    shortened = _truncate_title(title, max_title_len, suffix)
    new_parts = []
    for part in parts:
        new_parts.append(shortened if part == title else part)
    label = " ".join(part for part in new_parts if part)
    if len(label) > MAX_BUTTON_TEXT_LENGTH:
        label = f"{label[:MAX_BUTTON_TEXT_LENGTH - 1].rstrip()}…"
    return label


@lru_cache(maxsize=4096)
def _format_cached(file_name: str, file_size: int) -> str:
    parsed = parse_smart_media_item(file_name, file_size=file_size)
    size_label = _format_size(file_size or getattr(parsed, "size_bytes", 0))
    cleaned_name = getattr(parsed, "cleaned_file_name", "") or file_name
    quality_variants = _quality_variants(
        getattr(parsed, "quality", None), cleaned_name
    )

    title = _extract_title(parsed, cleaned_name or file_name, quality_variants[0])
    if not title:
        title = _normalize_title(cleaned_name or file_name)

    suffix = _episode_suffix(parsed)
    if suffix and not _EPISODE_RE.search(title):
        title = f"{title} {suffix}".strip()

    year = getattr(parsed, "year", None)
    year_label = ""
    if year and not _contains_year(title, str(year)):
        year_label = str(year)

    language = getattr(parsed, "language", None)
    if language and title.strip().casefold() == str(language).strip().casefold():
        language = None

    def compose(quality_label):
        parts = [
            f"[{size_label}]" if size_label else "",
            f"[{quality_label}]" if quality_label else "",
            title,
            f"[{year_label}]" if year_label else "",
            f"[{language}]" if language else "",
        ]
        return parts, " ".join(part for part in parts if part)

    for quality_label in quality_variants:
        _, candidate = compose(quality_label)
        if len(candidate) <= MAX_BUTTON_TEXT_LENGTH:
            return candidate or _safe_fallback(file_name, file_size)

    parts, _ = compose(quality_variants[-1])
    label = _assemble_label(parts, title, suffix)
    return label or _safe_fallback(file_name, file_size)


def _safe_fallback(file_name, file_size) -> str:
    name = str(file_name or "").strip()
    size_label = _format_size(file_size)
    if size_label and name:
        return f"[{size_label}] {name}"
    return name or "Media File"


def format_file_result_button(file_name, file_size) -> str:
    try:
        name = str(file_name or "")
    except Exception:
        name = ""
    try:
        size = int(file_size or 0)
    except (TypeError, ValueError, OverflowError):
        size = 0
    try:
        return _format_cached(name, size)
    except Exception:
        return _safe_fallback(name, size)
