import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from .smart_search_engine import parse_smart_media_item

MAX_BUTTON_TEXT_LENGTH = 64

_ALLOWED_RESOLUTIONS = {
    "360p": "360p",
    "480p": "480p",
    "576p": "576p",
    "720p": "720p",
    "1080p": "1080p",
    "1440p": "1440p",
    "2160p": "2160p",
    "4k": "4K",
    "uhd": "4K",
}

_RESOLUTION_SCAN_RE = re.compile(
    r"\b(360|480|576|720|1080|1440|2160)\s*p\b|\b(4\s*k|uhd)\b",
    re.IGNORECASE,
)

# Source / codec / container tags that must never appear in a file-result label.
_SOURCE_CODEC_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"web[\s._-]*dl|web[\s._-]*rip|webrip|blu[\s._-]*ray|brrip|bdrip|"
    r"hd[\s._-]*rip|hdtv|x264|x265|h\.?264|h\.?265|hevc|avc|hdr(?:10)?|"
    r"dolby[\s._-]*vision|dv|aac\d*|eac3|ac3|dts|atmos|truehd|flac|mp3"
    r")(?![A-Za-z0-9])"
)

_SPACING_RE = re.compile(r"\s{2,}")


def _format_size(size_bytes) -> str:
    """Always render file size in GB with exactly two decimals (binary units)."""
    try:
        size = Decimal(str(int(size_bytes)))
    except (TypeError, ValueError, ArithmeticError):
        return ""
    if size <= 0:
        return ""
    gb = Decimal(1024 ** 3)
    rounded = (size / gb).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:.2f} GB"


def _canonical_resolution(value) -> str:
    if not value:
        return ""
    match = _RESOLUTION_SCAN_RE.search(str(value))
    if not match:
        return ""
    if match.group(1):
        return _ALLOWED_RESOLUTIONS.get(f"{int(match.group(1))}p", "")
    token = re.sub(r"\s+", "", match.group(2)).lower()
    return _ALLOWED_RESOLUTIONS.get(token, "")


def _resolution_only(quality, cleaned_name) -> str:
    label = _canonical_resolution(quality)
    if label:
        return label
    return _canonical_resolution(cleaned_name)


def _clean_title(title) -> str:
    text = _SOURCE_CODEC_RE.sub(" ", str(title or ""))
    text = re.sub(r"[_\.+]+", " ", text)
    text = _SPACING_RE.sub(" ", text)
    return text.strip(" -_.:|[](){}")


def _contains_year(title: str, year: str) -> bool:
    return bool(re.search(rf"(?<!\d){re.escape(str(year))}(?!\d)", title))


def _truncate(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len == 1:
        return "…"
    return f"{text[:max_len - 1].rstrip()}…"


def _build_label(
    size_label: str,
    quality: str,
    title: str,
    year,
    language,
    category: str,
    season,
    episode_code,
) -> str:
    prefix_parts = [part for part in (size_label, quality) if part]
    if category == "series" and episode_code:
        prefix_parts.append(str(episode_code))
    prefix = " | ".join(prefix_parts)

    suffix_parts = []
    if year and not _contains_year(title, str(year)):
        suffix_parts.append(str(year))
    if category == "series" and season is not None:
        suffix_parts.append(f"Season {int(season)}")
    if language:
        suffix_parts.append(f"[{language}]")
    suffix = " ".join(suffix_parts)

    separator = " • " if category == "series" else " | "
    if not prefix:
        separator = ""

    suffix_block = f" {suffix}" if suffix else ""
    fixed_len = len(prefix) + len(separator) + len(suffix_block)
    title_budget = MAX_BUTTON_TEXT_LENGTH - fixed_len
    display_title = _truncate(title, title_budget)

    label = f"{prefix}{separator}{display_title}{suffix_block}".strip()
    if len(label) > MAX_BUTTON_TEXT_LENGTH:
        label = f"{label[:MAX_BUTTON_TEXT_LENGTH - 1].rstrip()}…"
    return label


@lru_cache(maxsize=4096)
def _format_cached(file_name: str, file_size: int) -> str:
    parsed = parse_smart_media_item(file_name, file_size=file_size)

    size_label = _format_size(file_size or getattr(parsed, "size_bytes", 0))
    cleaned_name = getattr(parsed, "cleaned_file_name", "") or file_name
    quality = _resolution_only(getattr(parsed, "quality", None), cleaned_name)

    title = _clean_title(getattr(parsed, "title", "") or cleaned_name)
    if not title:
        title = _clean_title(file_name)

    language = getattr(parsed, "language", None)
    if language and title.strip().casefold() == str(language).strip().casefold():
        language = None

    label = _build_label(
        size_label=size_label,
        quality=quality,
        title=title,
        year=getattr(parsed, "year", None),
        language=language,
        category=getattr(parsed, "category", "movie"),
        season=getattr(parsed, "season", None),
        episode_code=getattr(parsed, "episode_code", None),
    )
    return label or _safe_fallback(file_name, file_size)


def _safe_fallback(file_name, file_size) -> str:
    name = str(file_name or "").strip()
    size_label = _format_size(file_size)
    if size_label and name:
        return f"{size_label} | {name}"
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
