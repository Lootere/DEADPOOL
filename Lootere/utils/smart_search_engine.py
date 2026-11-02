# Smart Search Result Engine for RKMOVIESZIP (Feature 2)
#
# Display-only, backward-compatible formatting layer.
# - Never mutates persisted database records or in-memory Media objects.
# - Conservatively removes promotional/channel branding, @usernames, uploader/leech
#   tags, and bracketed promo noise while preserving meaningful title words.
# - Extracts title, season/episode, year, quality, and language only when present;
#   never invents missing metadata.
# - Formats file sizes consistently in GB to two decimal places (e.g. 1.45GB, 0.62GB).
# - Supports 10 independent admin text styles for Movies (default=7 Metadata) and
#   Series (default=10 Double-Line) with Preview Before Apply (default=ON).

from copy import deepcopy
from dataclasses import dataclass
from html import escape as html_escape
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SMART_STYLE_SETTING_KEY = "SMART_SEARCH_STYLE_CONFIG"

DEFAULT_MOVIE_STYLE = 7       # 7 = Metadata
DEFAULT_SERIES_STYLE = 10     # 10 = Double-Line
DEFAULT_PREVIEW_ENABLED = True

STYLE_NAMES: Dict[int, str] = {
    1: "Quotation",
    2: "Bold",
    3: "Blockquote",
    4: "Code",
    5: "Numbered",
    6: "Emoji Separator",
    7: "Metadata",
    8: "Minimal",
    9: "Bracket",
    10: "Double-Line",
}

STYLE_NAME_TO_ID: Dict[str, int] = {
    name.lower().replace("-", "_").replace(" ", "_"): style_id
    for style_id, name in STYLE_NAMES.items()
}
STYLE_NAME_TO_ID.update({str(style_id): style_id for style_id in STYLE_NAMES})

# In-memory fallback store and pending preview state (keyed by scope/admin)
_MEMORY_STYLE_CONFIG: Dict[str, Dict[str, Any]] = {}
_PENDING_STYLE_PREVIEWS: Dict[Tuple[int, str], Dict[str, Any]] = {}

_FILE_EXTENSION_RE = re.compile(
    r"\.(?:mkv|mp4|avi|mov|webm|m4v|flv|ts|wmv|mpg|mpeg|m2ts|srt|ass|sub)$",
    flags=re.IGNORECASE,
)

# Bracketed promo tags that do NOT contain meaningful media metadata
_PROMO_BRACKET_KEYWORDS_RE = re.compile(
    r"(?i)(?:@\w+|t\.me/|telegram\.me/|https?://|www\.|\b(?:join|channel|official|"
    r"uploaded|uploader|leech|team|group|links?|movies?|series|request|backup|"
    r"index|bot|files?|cinema|rockers|tamilmv|blasters|bolly4u|vegamovies|"
    r"filmyzilla|filmywap|mp4moviez|pagalworld|kuttymovies|isaimini|moviesda)\b|"
    r"\.[a-z]{2,5}\b)"
)

_METADATA_KEEP_IN_BRACKETS_RE = re.compile(
    r"(?i)\b(?:s\d{1,2}\s*e\d{1,3}|e\d{1,3}\s*s\d{1,2}|season\s*\d+|episode\s*\d+|"
    r"480\s*p|720\s*p|1080\s*p|1440\s*p|2160\s*p|4\s*k|8\s*k|"
    r"hindi|english|tamil|telugu|malayalam|kannada|punjabi|marathi|gujarati|"
    r"bengali|dual\s*audio|multi\s*audio|(?:19[5-9]\d|20[0-2]\d|2030))\b"
)

_LEADING_SITE_OR_HANDLE_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_.]+\s*[-_.:|]*\s*|"
    r"(?:https?://)?(?:www\.)?[A-Za-z0-9-]+\.(?:com|org|net|in|me|to|cc|tf|wf|lol|xyz|live|club|site|info|pro|top|pw|pk|co)\s*[-_.:|]+\s*)+",
    flags=re.IGNORECASE,
)

_LEADING_PROMO_PREFIX_RE = re.compile(
    r"^(?i)\s*(?:[a-z0-9_.]*(?:movies?zip|rkmovies\w*|lootere\w*|deadpool\w*|"
    r"team|channel|uploads?|releases?|official)\s*[-_.:|]+\s*)+"
)

_INLINE_HANDLE_OR_URL_RE = re.compile(
    r"(?i)(?:(?<!\w)@[A-Za-z0-9_]{3,}\b|https?://\S+|t\.me/\S+|telegram\.me/\S+|"
    r"\bwww\.[A-Za-z0-9-]+\.[a-z]{2,6}\b)"
)

# Series Season/Episode patterns
_SERIES_PATTERNS = (
    # S21E01, S01.E02, S01_E02, S01 E02
    re.compile(
        r"(?:^|[\s._+\-\[\(])S(?P<season>\d{1,2})[\s._+\-]*E(?P<episode>\d{1,3})(?=$|[\s._+\-\]\)])",
        flags=re.IGNORECASE,
    ),
    # E01 S21, E01.S21, Ep01 S02
    re.compile(
        r"(?:^|[\s._+\-\[\(])(?:Episode|Ep|E)\s*0*(?P<episode>\d{1,3})[\s._+\-]*S(?:eason)?\s*0*(?P<season>\d{1,2})(?=$|[\s._+\-\]\)])",
        flags=re.IGNORECASE,
    ),
    # Season 21 Episode 01
    re.compile(
        r"(?:^|[\s._+\-\[\(])Season[\s._+\-]*0*(?P<season>\d{1,2})[\s._+\-]*(?:Episode|Ep|E)[\s._+\-]*0*(?P<episode>\d{1,3})(?=$|[\s._+\-\]\)])",
        flags=re.IGNORECASE,
    ),
    # 1x02
    re.compile(
        r"(?:^|[\s._+\-\[\(])(?P<season>\d{1,2})\s*[xX]\s*(?P<episode>\d{1,3})(?=$|[\s._+\-\]\)])",
        flags=re.IGNORECASE,
    ),
)

_STANDALONE_SEASON_RE = re.compile(
    r"(?:^|[\s._+\-\[\(])(?:Season[\s._+\-]*0*(?P<s_word>\d{1,2})|S0*(?P<s_code>\d{1,2}))(?=$|[\s._+\-\]\)])",
    flags=re.IGNORECASE,
)

_STANDALONE_EPISODE_RE = re.compile(
    r"(?:^|[\s._+\-\[\(])(?:Episode[\s._+\-]*0*(?P<e_word>\d{1,3})|Ep[\s._+\-]*0*(?P<e_short>\d{1,3})|E(?P<e_code>\d{2,3}))(?=$|[\s._+\-\]\)])",
    flags=re.IGNORECASE,
)

# Quality patterns (ordered from most specific to general)
_QUALITY_PATTERNS: Sequence[Tuple[re.Pattern, str]] = (
    (re.compile(r"(?:^|[\s._+\-\[\(])1080\s*p[\s._+\-]*hq(?=$|[\s._+\-\]\)])", re.I), "1080p HQ"),
    (re.compile(r"(?:^|[\s._+\-\[\(])2160\s*p(?=$|[\s._+\-\]\)])", re.I), "2160p"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:4\s*k|uhd)(?=$|[\s._+\-\]\)])", re.I), "4K"),
    (re.compile(r"(?:^|[\s._+\-\[\(])1440\s*p(?=$|[\s._+\-\]\)])", re.I), "1440p"),
    (re.compile(r"(?:^|[\s._+\-\[\(])1080\s*p(?=$|[\s._+\-\]\)])", re.I), "1080p"),
    (re.compile(r"(?:^|[\s._+\-\[\(])720\s*p(?=$|[\s._+\-\]\)])", re.I), "720p"),
    (re.compile(r"(?:^|[\s._+\-\[\(])480\s*p(?=$|[\s._+\-\]\)])", re.I), "480p"),
    (re.compile(r"(?:^|[\s._+\-\[\(])360\s*p(?=$|[\s._+\-\]\)])", re.I), "360p"),
)

# Language patterns (only matched in metadata zone or explicit bracket/trailing tokens)
_LANGUAGE_PATTERNS: Sequence[Tuple[re.Pattern, str]] = (
    (re.compile(r"(?:^|[\s._+\-\[\(])dual[\s._+\-]*audio(?=$|[\s._+\-\]\)])", re.I), "Dual Audio"),
    (re.compile(r"(?:^|[\s._+\-\[\(])multi[\s._+\-]*audio(?=$|[\s._+\-\]\)])", re.I), "Multi Audio"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:hindi|hin)(?=$|[\s._+\-\]\)])", re.I), "Hindi"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:english|eng)(?=$|[\s._+\-\]\)])", re.I), "English"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:tamil|tam)(?=$|[\s._+\-\]\)])", re.I), "Tamil"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:telugu|tel)(?=$|[\s._+\-\]\)])", re.I), "Telugu"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:malayalam|mal)(?=$|[\s._+\-\]\)])", re.I), "Malayalam"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:kannada|kan)(?=$|[\s._+\-\]\)])", re.I), "Kannada"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:punjabi|pun)(?=$|[\s._+\-\]\)])", re.I), "Punjabi"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:marathi|mar)(?=$|[\s._+\-\]\)])", re.I), "Marathi"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:gujarati|guj)(?=$|[\s._+\-\]\)])", re.I), "Gujarati"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:bengali|ben)(?=$|[\s._+\-\]\)])", re.I), "Bengali"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:korean|kor)(?=$|[\s._+\-\]\)])", re.I), "Korean"),
    (re.compile(r"(?:^|[\s._+\-\[\(])(?:japanese|jap|jpn)(?=$|[\s._+\-\]\)])", re.I), "Japanese"),
)

_YEAR_TOKEN_RE = re.compile(r"(?:^|[\s._+\-\[\(])(?P<year>19[5-9]\d|20[0-2]\d|2030)(?=$|[\s._+\-\]\)])")

# Technical codec/rip tokens removed when cleaning title/tail
_TECHNICAL_JUNK_RE = re.compile(
    r"(?i)(?:^|[\s._+\-\[\(])(?:"
    r"web[\s._+\-]*dl|webrip|web[\s._+\-]*rip|bluray|blu[\s._+\-]*ray|brrip|bdrip|"
    r"hdrip|hd[\s._+\-]*rip|dvdrip|hdtv|hdcam|camrip|predvd|pre[\s._+\-]*dvd|hdtc|hdts|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|10bit|10[\s._+\-]*bit|8bit|hdr|hdr10|dv|dolby[\s._+\-]*vision|"
    r"aac\d*(?:\.\d+)?|ddp?\s*\d*(?:\.\d+)?|ac3|eac3|dts|atmos|truehd|flac|mp3|"
    r"esubs?|esub|m?subs?|subtitles?|org|original|uncut|extended|remastered|proper|repack|"
    r"nf|amzn|dsnp|atvp|hmax|zee5|sonyliv|hotstar|jio|voot|ullu|mx|aha"
    r")(?=$|[\s._+\-\]\)])"
)


@dataclass(frozen=True)
class SmartMediaMetadata:
    raw_file_name: str
    cleaned_file_name: str
    category: str  # "movie" or "series"
    title: str
    year: Optional[str]
    season: Optional[int]
    episode: Optional[int]
    episode_code: Optional[str]
    quality: Optional[str]
    language: Optional[str]
    size_bytes: int
    size_gb: str
    file_id: Optional[str] = None


def format_size_gb(size_bytes: Any) -> str:
    """Format file size in GB consistently to two decimal places (e.g. '1.45GB', '0.62GB')."""
    try:
        numeric_bytes = max(0.0, float(size_bytes or 0))
    except (TypeError, ValueError):
        numeric_bytes = 0.0
    gb_value = numeric_bytes / float(1024 ** 3)
    return f"{gb_value:.2f}GB"


def clean_promotional_filename(file_name: str) -> str:
    """Conservatively remove promotional/channel branding, @usernames, and promo brackets
    from a display copy without removing meaningful title words or metadata."""
    if not file_name:
        return ""

    text = str(file_name)
    text = _FILE_EXTENSION_RE.sub("", text)

    # 1. Remove leading bracketed blocks if they don't hold media metadata
    while True:
        leading_bracket = re.match(r"^\s*[\[\(\{]([^\]\)\}]{1,80})[\]\)\}]\s*[-_.:|]*\s*", text)
        if not leading_bracket:
            break
        inner = leading_bracket.group(1)
        if _METADATA_KEEP_IN_BRACKETS_RE.search(inner) and not _PROMO_BRACKET_KEYWORDS_RE.search(inner):
            break
        text = text[leading_bracket.end():]

    # 2. Remove any bracketed block anywhere that clearly contains promo handles/domains
    def _strip_promo_bracket(match: re.Match) -> str:
        inner = match.group(1)
        if _PROMO_BRACKET_KEYWORDS_RE.search(inner) and not _METADATA_KEEP_IN_BRACKETS_RE.search(inner):
            return " "
        return match.group(0)

    text = re.sub(r"[\[\(\{]([^\]\)\}]{1,80})[\]\)\}]", _strip_promo_bracket, text)

    # 3. Strip leading @handles, domains, and uploader/channel prefixes
    text = _LEADING_SITE_OR_HANDLE_RE.sub("", text)
    text = _LEADING_PROMO_PREFIX_RE.sub("", text)

    # 4. Strip inline @handles and URLs
    text = _INLINE_HANDLE_OR_URL_RE.sub(" ", text)

    # 5. Normalize separators into single spaces
    text = re.sub(r"[_\.+]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -_.:|[](){}")
    return text or str(file_name).strip()


def _normalize_title_text(raw_title: str) -> str:
    cleaned = re.sub(r"[\[\(\{\]\)\}]", " ", raw_title)
    cleaned = re.sub(r"[\s._+\-]+", " ", cleaned).strip(" -_.:|•")
    if not cleaned:
        return ""
    # If the title is all lowercase or all uppercase (and >3 chars), apply smart title casing
    alpha_chars = [c for c in cleaned if c.isalpha()]
    if len(alpha_chars) >= 4 and (cleaned.islower() or cleaned.isupper()):
        cleaned = " ".join(
            word.upper() if re.fullmatch(r"(?:ii|iii|iv|vi|vii|viii|ix|xi|xii|uk|usa|tv)", word, re.I)
            else word.capitalize()
            for word in cleaned.split()
        )
    return cleaned


def parse_smart_media_item(
    file_or_name: Any,
    file_size: Optional[int] = None,
    caption: Optional[str] = None,
) -> SmartMediaMetadata:
    """Parse a media object or filename into conservative display metadata without mutating input."""
    if isinstance(file_or_name, str):
        raw_name = file_or_name
        resolved_size = int(file_size or 0)
        resolved_file_id = None
    elif isinstance(file_or_name, Mapping):
        raw_name = str(file_or_name.get("file_name") or "")
        resolved_size = int(
            file_size if file_size is not None else (file_or_name.get("file_size") or 0)
        )
        resolved_file_id = file_or_name.get("file_id") or file_or_name.get("_id")
    else:
        raw_name = str(getattr(file_or_name, "file_name", "") or "")
        resolved_size = int(
            file_size
            if file_size is not None
            else (getattr(file_or_name, "file_size", 0) or 0)
        )
        resolved_file_id = getattr(file_or_name, "file_id", None)

    cleaned = clean_promotional_filename(raw_name)

    # 1. Detect series Season / Episode
    season: Optional[int] = None
    episode: Optional[int] = None
    series_anchor_start: Optional[int] = None

    for pattern in _SERIES_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            season = int(m.group("season"))
            episode = int(m.group("episode"))
            series_anchor_start = m.start()
            break

    if season is None and episode is None:
        s_match = _STANDALONE_SEASON_RE.search(cleaned)
        e_match = _STANDALONE_EPISODE_RE.search(cleaned)
        if s_match:
            s_val = s_match.group("s_word") or s_match.group("s_code")
            season = int(s_val)
            series_anchor_start = s_match.start()
        if e_match:
            e_val = e_match.group("e_word") or e_match.group("e_short") or e_match.group("e_code")
            episode = int(e_val)
            if series_anchor_start is None or e_match.start() < series_anchor_start:
                series_anchor_start = e_match.start()

    is_series = season is not None or episode is not None
    category = "series" if is_series else "movie"

    if season is not None and episode is not None:
        episode_code: Optional[str] = f"E{episode:02d} S{season:02d}"
    elif episode is not None:
        episode_code = f"E{episode:02d}"
    elif season is not None:
        episode_code = f"S{season:02d}"
    else:
        episode_code = None

    # 2. Detect Quality (only if present)
    quality: Optional[str] = None
    quality_anchor_start: Optional[int] = None
    for q_pattern, q_label in _QUALITY_PATTERNS:
        qm = q_pattern.search(cleaned)
        if qm:
            quality = q_label
            if quality_anchor_start is None or qm.start() < quality_anchor_start:
                quality_anchor_start = qm.start()
            break

    # 3. Detect Year (conservatively, never stripping a numeric-only title like "1917" or "2012",
    #    and keeping title years like "Wonder Woman 1984" when a release year "2020" follows)
    year: Optional[str] = None
    year_anchor_start: Optional[int] = None
    year_matches = [
        ym
        for ym in _YEAR_TOKEN_RE.finditer(cleaned)
        if re.search(r"[A-Za-z0-9]", cleaned[:ym.start()].strip(" -_.:|[](){}"))
    ]
    if year_matches:
        non_year_anchors = [
            pos for pos in (series_anchor_start, quality_anchor_start) if pos is not None and pos > 0
        ]
        boundary = min(non_year_anchors) if non_year_anchors else len(cleaned)
        before_boundary = [ym for ym in year_matches if ym.start() < boundary]
        chosen_ym = before_boundary[-1] if before_boundary else year_matches[0]
        year = chosen_ym.group("year")
        year_anchor_start = chosen_ym.start()

    # 4. Determine where the Title zone ends and Metadata zone begins
    anchors = [
        pos
        for pos in (series_anchor_start, quality_anchor_start, year_anchor_start)
        if pos is not None and pos > 0
    ]
    tech_match = _TECHNICAL_JUNK_RE.search(cleaned)
    if tech_match and tech_match.start() > 0:
        anchors.append(tech_match.start())

    first_anchor = min(anchors) if anchors else None

    # 5. Extract Language ONLY from the metadata zone (or trailing tokens), never from inside the title phrase
    language_search_zone = cleaned[first_anchor:] if first_anchor is not None else ""
    if not language_search_zone:
        # Check if original raw name had bracketed language or trailing language after at least one title word
        tokens = cleaned.split()
        if len(tokens) >= 2:
            language_search_zone = " ".join(tokens[1:])

    detected_languages: List[str] = []
    for lang_pattern, lang_label in _LANGUAGE_PATTERNS:
        if lang_pattern.search(language_search_zone):
            if lang_label not in detected_languages:
                detected_languages.append(lang_label)

    if "Dual Audio" in detected_languages:
        language: Optional[str] = "Dual Audio"
    elif "Multi Audio" in detected_languages:
        language = "Multi Audio"
    elif detected_languages:
        language = " + ".join(detected_languages[:2])
    else:
        language = None

    # 6. Extract Clean Title
    if first_anchor is not None:
        raw_title_candidate = cleaned[:first_anchor]
    else:
        raw_title_candidate = cleaned
        # Strip any detected trailing language or technical tokens from raw_title_candidate
        for lang_pattern, _ in _LANGUAGE_PATTERNS:
            raw_title_candidate = lang_pattern.sub(" ", raw_title_candidate)
        raw_title_candidate = _TECHNICAL_JUNK_RE.sub(" ", raw_title_candidate)

    title = _normalize_title_text(raw_title_candidate)
    if not title:
        # Fallback to cleaned name stripped of obvious technical tags
        fallback = _TECHNICAL_JUNK_RE.sub(" ", cleaned)
        title = _normalize_title_text(fallback) or cleaned or "Media File"

    return SmartMediaMetadata(
        raw_file_name=raw_name,
        cleaned_file_name=cleaned,
        category=category,
        title=title,
        year=year,
        season=season,
        episode=episode,
        episode_code=episode_code,
        quality=quality,
        language=language,
        size_bytes=resolved_size,
        size_gb=format_size_gb(resolved_size),
        file_id=str(resolved_file_id) if resolved_file_id is not None else None,
    )


def format_smart_summary_line(item: SmartMediaMetadata) -> str:
    """Format the canonical metadata summary line matching the PRD target examples:
    - Movie:  `1.45GB | 1080p • Movie Name • 2025` (plus ` • Language` only if known)
    - Series: `0.62GB | E01 S21 • Roadies Rebirth 2026` (plus quality/language only if known)
    """
    bullet_parts: List[str] = []

    if item.category == "series":
        if item.episode_code:
            bullet_parts.append(item.episode_code)
        if item.quality:
            bullet_parts.append(item.quality)
        series_title = (
            f"{item.title} {item.year}".strip()
            if item.year and item.year not in item.title
            else item.title
        )
        if series_title:
            bullet_parts.append(series_title)
        if item.language:
            bullet_parts.append(item.language)
    else:
        if item.quality:
            bullet_parts.append(item.quality)
        if item.title:
            bullet_parts.append(item.title)
        if item.year and item.year not in item.title:
            bullet_parts.append(item.year)
        if item.language:
            bullet_parts.append(item.language)

    if not bullet_parts:
        return item.size_gb
    return f"{item.size_gb} | " + " • ".join(bullet_parts)


def _build_clickable_heading_text(item: SmartMediaMetadata, style_id: int) -> str:
    """Build the clickable heading label for Link Style.
    Every series episode gets its own distinct clickable title."""
    if item.category == "series":
        base_series = (
            f"{item.title} {item.year}".strip()
            if item.year and item.year not in item.title
            else item.title
        )
        if item.episode_code:
            if style_id == 7:
                return f"{base_series} ({item.episode_code})"
            return f"{base_series} • {item.episode_code}"
        return base_series

    # Movie heading
    if style_id == 10 and item.year and item.year not in item.title:
        return f"{item.title} ({item.year})"
    return item.title


def render_smart_result_entry(
    item: SmartMediaMetadata,
    file_url: str,
    style_id: Optional[int] = None,
    index: int = 1,
) -> str:
    """Render a single Movie or Series result in Link Style using one of the 10 text styles.
    Guarantees:
    - Clickable title heading (<a href="...">...</a>)
    - Plain metadata below
    - NO duplicate clickable download link
    - Each series episode has its own clickable title
    - Language shown only when known; uncertain/missing metadata omitted.
    """
    default_style = DEFAULT_SERIES_STYLE if item.category == "series" else DEFAULT_MOVIE_STYLE
    resolved_style = style_id if style_id in STYLE_NAMES else default_style

    heading_plain = _build_clickable_heading_text(item, resolved_style)
    heading_escaped = html_escape(heading_plain)
    safe_url = html_escape(str(file_url), quote=True)
    summary_plain = format_smart_summary_line(item)
    summary_escaped = html_escape(summary_plain)

    if resolved_style == 1:
        # 1. Quotation
        return (
            f"“<b><a href='{safe_url}'>{heading_escaped}</a></b>”\n"
            f"❝ {summary_escaped} ❞"
        )

    if resolved_style == 2:
        # 2. Bold
        return (
            f"<b><a href='{safe_url}'>{heading_escaped}</a></b>\n"
            f"<b>{summary_escaped}</b>"
        )

    if resolved_style == 3:
        # 3. Blockquote
        return (
            f"<blockquote><b><a href='{safe_url}'>{heading_escaped}</a></b>\n"
            f"{summary_escaped}</blockquote>"
        )

    if resolved_style == 4:
        # 4. Code
        return (
            f"<b><a href='{safe_url}'>{heading_escaped}</a></b>\n"
            f"<code>{summary_escaped}</code>"
        )

    if resolved_style == 5:
        # 5. Numbered
        return (
            f"<b>{index}. <a href='{safe_url}'>{heading_escaped}</a></b>\n"
            f"{summary_escaped}"
        )

    if resolved_style == 6:
        # 6. Emoji Separator
        lead_icon = "📺" if item.category == "series" else "🎬"
        parts: List[str] = [f"📦 {html_escape(item.size_gb)}"]
        if item.category == "series" and item.episode_code:
            parts.append(html_escape(item.episode_code))
        if item.quality:
            parts.append(html_escape(item.quality))
        title_token = (
            f"{item.title} {item.year}".strip()
            if item.category == "series" and item.year and item.year not in item.title
            else item.title
        )
        if title_token:
            parts.append(html_escape(title_token))
        if item.category == "movie" and item.year and item.year not in item.title:
            parts.append(html_escape(item.year))
        if item.language:
            parts.append(html_escape(item.language))
        meta_line = " 🔹 ".join(parts)
        return (
            f"{lead_icon} <b><a href='{safe_url}'>{heading_escaped}</a></b>\n"
            f"{meta_line}"
        )

    if resolved_style == 7:
        # 7. Metadata (Default for Movies)
        return (
            f"<b><a href='{safe_url}'>{heading_escaped}</a></b>\n"
            f"{summary_escaped}"
        )

    if resolved_style == 8:
        # 8. Minimal
        min_parts: List[str] = [item.size_gb]
        if item.category == "series" and item.episode_code:
            min_parts.append(item.episode_code)
        if item.quality:
            min_parts.append(item.quality)
        if item.category == "movie" and item.year and item.year not in item.title:
            min_parts.append(item.year)
        if item.language:
            min_parts.append(item.language)
        min_line = html_escape(" • ".join(min_parts))
        return (
            f"<a href='{safe_url}'>{heading_escaped}</a>\n"
            f"{min_line}"
        )

    if resolved_style == 9:
        # 9. Bracket
        bracket_parts: List[str] = [f"[{html_escape(item.size_gb)}]"]
        if item.category == "series" and item.episode_code:
            bracket_parts.append(f"[{html_escape(item.episode_code)}]")
        if item.quality:
            bracket_parts.append(f"[{html_escape(item.quality)}]")
        title_token = (
            f"{item.title} {item.year}".strip()
            if item.category == "series" and item.year and item.year not in item.title
            else item.title
        )
        if title_token:
            bracket_parts.append(f"[{html_escape(title_token)}]")
        if item.category == "movie" and item.year and item.year not in item.title:
            bracket_parts.append(f"[{html_escape(item.year)}]")
        if item.language:
            bracket_parts.append(f"[{html_escape(item.language)}]")
        return (
            f"<b><a href='{safe_url}'>[{heading_escaped}]</a></b>\n"
            f"{' '.join(bracket_parts)}"
        )

    # 10. Double-Line (Default for Series)
    return (
        f"<b><a href='{safe_url}'>{heading_escaped}</a></b>\n"
        f"{summary_escaped}"
    )


def normalize_style_id(value: Any, default: int) -> int:
    if isinstance(value, int) and value in STYLE_NAMES:
        return value
    if isinstance(value, str):
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        if key in STYLE_NAME_TO_ID:
            return STYLE_NAME_TO_ID[key]
    return default


def _normalize_style_config_dict(raw: Any) -> Dict[str, Any]:
    data = dict(raw) if isinstance(raw, Mapping) else {}
    return {
        "movie_style": normalize_style_id(data.get("movie_style"), DEFAULT_MOVIE_STYLE),
        "series_style": normalize_style_id(data.get("series_style"), DEFAULT_SERIES_STYLE),
        "preview_enabled": bool(
            data.get("preview_enabled", DEFAULT_PREVIEW_ENABLED)
            if "preview_enabled" in data
            else DEFAULT_PREVIEW_ENABLED
        ),
    }


async def get_smart_style_config(db_instance: Any = None, scope: str = "global") -> Dict[str, Any]:
    """Retrieve the active Smart Search style configuration (Movie style, Series style, Preview toggle)."""
    target_db = db_instance
    if target_db is None:
        try:
            from database.users_chats_db import db as default_db
            target_db = default_db
        except Exception:
            target_db = None

    setting_key = (
        SMART_STYLE_SETTING_KEY
        if scope == "global"
        else f"{SMART_STYLE_SETTING_KEY}:{scope}"
    )

    if target_db is not None and hasattr(target_db, "get_setting"):
        try:
            stored = await target_db.get_setting(setting_key, default=None)
            if isinstance(stored, Mapping):
                normalized = _normalize_style_config_dict(stored)
                _MEMORY_STYLE_CONFIG[setting_key] = deepcopy(normalized)
                return normalized
        except Exception:
            logger.debug("Falling back to in-memory smart style config", exc_info=True)

    if setting_key in _MEMORY_STYLE_CONFIG:
        return deepcopy(_MEMORY_STYLE_CONFIG[setting_key])

    return _normalize_style_config_dict({})


async def save_smart_style_config(
    config: Mapping[str, Any],
    db_instance: Any = None,
    scope: str = "global",
) -> Dict[str, Any]:
    """Persist the Smart Search style configuration."""
    normalized = _normalize_style_config_dict(config)
    setting_key = (
        SMART_STYLE_SETTING_KEY
        if scope == "global"
        else f"{SMART_STYLE_SETTING_KEY}:{scope}"
    )
    _MEMORY_STYLE_CONFIG[setting_key] = deepcopy(normalized)

    target_db = db_instance
    if target_db is None:
        try:
            from database.users_chats_db import db as default_db
            target_db = default_db
        except Exception:
            target_db = None

    if target_db is not None and hasattr(target_db, "set_setting"):
        try:
            await target_db.set_setting(setting_key, normalized)
        except Exception:
            logger.debug("Could not persist smart style config to DB; kept in memory", exc_info=True)

    return deepcopy(normalized)


async def select_smart_text_style(
    admin_id: int,
    category: str,
    style_value: Any,
    db_instance: Any = None,
    scope: str = "global",
) -> Dict[str, Any]:
    """Select a Movie or Series text style (1-10).
    - When `preview_enabled` is True (default), stores a pending preview without mutating
      the active setting and returns `status='preview_pending'` + rendered sample preview.
    - When `preview_enabled` is False, applies immediately and returns `status='applied'`.
    """
    cat = str(category or "").strip().lower()
    if cat not in ("movie", "series"):
        raise ValueError("Category must be 'movie' or 'series'")

    default_style = DEFAULT_MOVIE_STYLE if cat == "movie" else DEFAULT_SERIES_STYLE
    style_id = normalize_style_id(style_value, default=0)
    if style_id not in STYLE_NAMES:
        raise ValueError(f"Style must be between 1 and 10 (got {style_value!r})")

    current_config = await get_smart_style_config(db_instance=db_instance, scope=scope)
    preview_text = render_style_preview_sample(cat, style_id)

    if current_config["preview_enabled"]:
        _PENDING_STYLE_PREVIEWS[(int(admin_id), str(scope))] = {
            "category": cat,
            "style_id": style_id,
            "style_name": STYLE_NAMES[style_id],
        }
        return {
            "status": "preview_pending",
            "category": cat,
            "candidate_style_id": style_id,
            "candidate_style_name": STYLE_NAMES[style_id],
            "active_style_id": current_config[f"{cat}_style"],
            "active_style_name": STYLE_NAMES[current_config[f"{cat}_style"]],
            "preview_enabled": True,
            "preview_html": preview_text,
        }

    current_config[f"{cat}_style"] = style_id
    saved = await save_smart_style_config(current_config, db_instance=db_instance, scope=scope)
    _PENDING_STYLE_PREVIEWS.pop((int(admin_id), str(scope)), None)
    return {
        "status": "applied",
        "category": cat,
        "active_style_id": saved[f"{cat}_style"],
        "active_style_name": STYLE_NAMES[saved[f"{cat}_style"]],
        "preview_enabled": saved["preview_enabled"],
        "preview_html": preview_text,
    }


async def confirm_pending_style_preview(
    admin_id: int,
    db_instance: Any = None,
    scope: str = "global",
    category: Optional[str] = None,
    style_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Apply a previewed Movie or Series text style."""
    key = (int(admin_id), str(scope))
    pending = _PENDING_STYLE_PREVIEWS.pop(key, None)

    resolved_cat = (category or (pending["category"] if pending else "")).strip().lower()
    resolved_style = (
        normalize_style_id(style_id, default=0)
        if style_id is not None
        else (pending["style_id"] if pending else 0)
    )

    if resolved_cat not in ("movie", "series") or resolved_style not in STYLE_NAMES:
        current = await get_smart_style_config(db_instance=db_instance, scope=scope)
        return {
            "status": "no_pending_preview",
            "config": current,
        }

    current = await get_smart_style_config(db_instance=db_instance, scope=scope)
    current[f"{resolved_cat}_style"] = resolved_style
    saved = await save_smart_style_config(current, db_instance=db_instance, scope=scope)
    return {
        "status": "applied",
        "category": resolved_cat,
        "active_style_id": resolved_style,
        "active_style_name": STYLE_NAMES[resolved_style],
        "config": saved,
    }


async def cancel_pending_style_preview(
    admin_id: int,
    db_instance: Any = None,
    scope: str = "global",
) -> Dict[str, Any]:
    """Cancel a pending style preview and leave the previous setting completely unchanged."""
    key = (int(admin_id), str(scope))
    cancelled = _PENDING_STYLE_PREVIEWS.pop(key, None)
    current = await get_smart_style_config(db_instance=db_instance, scope=scope)
    return {
        "status": "cancelled",
        "cancelled_preview": cancelled,
        "config": current,
    }


async def set_style_preview_enabled(
    enabled: bool,
    db_instance: Any = None,
    scope: str = "global",
) -> Dict[str, Any]:
    """Toggle Preview Before Apply ON or OFF."""
    current = await get_smart_style_config(db_instance=db_instance, scope=scope)
    current["preview_enabled"] = bool(enabled)
    return await save_smart_style_config(current, db_instance=db_instance, scope=scope)


def render_style_preview_sample(category: str, style_id: int) -> str:
    """Render a realistic sample preview for a Movie or Series in the requested style (1-10)."""
    cat = str(category or "movie").strip().lower()
    if cat == "series":
        sample_item = SmartMediaMetadata(
            raw_file_name="Roadies.Rebirth.2026.S21E01.mkv",
            cleaned_file_name="Roadies Rebirth 2026 S21E01",
            category="series",
            title="Roadies Rebirth",
            year="2026",
            season=21,
            episode=1,
            episode_code="E01 S21",
            quality=None,
            language=None,
            size_bytes=int(round(0.62 * (1024 ** 3))),
            size_gb="0.62GB",
            file_id="sample_series_ep1",
        )
        return render_smart_result_entry(
            sample_item,
            file_url="https://telegram.me/RKMoviesBot?start=files_0_sample_series_ep1",
            style_id=style_id,
            index=1,
        )

    sample_item = SmartMediaMetadata(
        raw_file_name="Movie.Name.2025.1080p.WEB-DL.mkv",
        cleaned_file_name="Movie Name 2025 1080p",
        category="movie",
        title="Movie Name",
        year="2025",
        season=None,
        episode=None,
        episode_code=None,
        quality="1080p",
        language=None,
        size_bytes=int(round(1.45 * (1024 ** 3))),
        size_gb="1.45GB",
        file_id="sample_movie_1",
    )
    return render_smart_result_entry(
        sample_item,
        file_url="https://telegram.me/RKMoviesBot?start=files_0_sample_movie_1",
        style_id=style_id,
        index=1,
    )


async def format_smart_search_file_blocks(
    files: Sequence[Any],
    chat_id: Any,
    bot_username: Optional[str],
    settings: Optional[Mapping[str, Any]] = None,
    db_instance: Any = None,
) -> str:
    """Format a sequence of search result files into Link Style HTML blocks using the active
    Movie and Series text styles without mutating any file objects."""
    if not files:
        return ""

    config = await get_smart_style_config(db_instance=db_instance)
    movie_style = normalize_style_id(
        (settings or {}).get("smart_movie_style", config.get("movie_style")),
        DEFAULT_MOVIE_STYLE,
    )
    series_style = normalize_style_id(
        (settings or {}).get("smart_series_style", config.get("series_style")),
        DEFAULT_SERIES_STYLE,
    )

    uname = str(bot_username or "bot").lstrip("@")
    blocks: List[str] = []

    for idx, file_obj in enumerate(files, start=1):
        parsed = parse_smart_media_item(file_obj)
        file_id = parsed.file_id or getattr(file_obj, "file_id", "")
        file_url = f"https://telegram.me/{uname}?start=files_{chat_id}_{file_id}"
        chosen_style = series_style if parsed.category == "series" else movie_style
        blocks.append(
            render_smart_result_entry(
                parsed,
                file_url=file_url,
                style_id=chosen_style,
                index=idx,
            )
        )

    return "\n\n".join(blocks)
