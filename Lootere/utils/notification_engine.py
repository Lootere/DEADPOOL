"""Feature 46 - Smart Auto Upload Notification & Weekly Digest engine.

Additive, display/delivery-only layer. It never changes indexing, search,
file delivery, premium checks, Feature 43 locks or Feature 45 unlocks.

The engine is split into pure helpers (unit-testable without Telegram/Mongo)
and async persistence/delivery helpers used by the bot.
"""
import asyncio
import hashlib
import html
import io
import logging
import os
import re
import urllib.parse
from copy import deepcopy
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from Lootere.utils.smart_search_engine import parse_smart_media_item

logger = logging.getLogger(__name__)

SETTINGS_KEY = "FEATURE46_NOTIFICATION_SETTINGS"
SETTINGS_CACHE_TTL = 15
MAX_CAPTION_LENGTH = 3900
MAX_MESSAGE_LENGTH = 3800
DEFAULT_BATCH_WINDOW = 300
MAX_BATCH_WINDOW = 3600
MAX_DELIVERY_ATTEMPTS = 5
WORKER_INTERVAL = 15
# Hard caps so a slow/stalled Telegram photo upload can never wedge the single
# delivery worker. Text delivery is attempted as soon as the poster attempt
# ends, whether it succeeded, failed or timed out.
POSTER_ATTEMPT_TIMEOUT = 20
DELIVERY_ATTEMPT_TIMEOUT = 60
WORKER_CYCLE_TIMEOUT = 300

EVENTS_COLLECTION = "notification_events"
DELIVERIES_COLLECTION = "notification_deliveries"
BATCHES_COLLECTION = "notification_batches"
METADATA_COLLECTION = "notification_metadata_cache"
DIGESTS_COLLECTION = "weekly_digest_history"
AUDIT_COLLECTION = "notification_audit_log"

DEFAULT_MOVIE_TEMPLATE = (
    "<b>🔥 NEW MOVIE UPLOADED</b>\n\n"
    "<b>{title_line}</b>\n\n"
    "{rating_line}{imdb_line}{genre_line}{language_line}{quality_line}"
    "{runtime_line}{certification_line}{description_line}"
)

DEFAULT_SERIES_TEMPLATE = (
    "<b>📺 NEW SERIES EPISODES ADDED</b>\n\n"
    "<b>{title_line}</b>\n\n"
    "{rating_line}{imdb_line}{genre_line}{language_line}{quality_line}"
    "{runtime_line}{description_line}"
    "{new_episodes_block}\n<b>Total New Episodes: {episode_count}</b>"
)

DEFAULT_DIGEST_TEMPLATE = (
    "<b>🔥 RKMOVIESZIP WEEKLY UPLOAD REPORT</b>\n"
    "📅 {period}\n\n"
    "🎬 Movies: {movie_count}\n"
    "📺 Series: {series_count}\n"
    "📁 Episodes: {episode_count}\n"
    "📦 Total New Files: {file_count}\n"
    "{sections}"
)

_CHANNEL_DEFAULT = str(
    (os.environ.get("POST_CHANNELS", "-1002023191399").split(",") or [""])[0].strip()
)
_GROUP_DEFAULT = str(os.environ.get("AUTO_NOTIFY_GROUP_ID", "") or "")
_GROUP_URL_DEFAULT = str(os.environ.get("AUTO_NOTIFY_GROUP_URL", "") or "")
BOT_TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata") or "Asia/Kolkata"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "channel_id": _CHANNEL_DEFAULT,
    "channel_enabled": bool(_CHANNEL_DEFAULT),
    "group_id": _GROUP_DEFAULT,
    "group_enabled": bool(_GROUP_DEFAULT),
    "button_text": "GET NOW",
    "button_url": _GROUP_URL_DEFAULT,
    "movie_button_url": "",
    "series_button_url": "",
    "movie_caption_template": DEFAULT_MOVIE_TEMPLATE,
    "series_caption_template": DEFAULT_SERIES_TEMPLATE,
    "digest_caption_template": DEFAULT_DIGEST_TEMPLATE,
    "digest_button_text": "VIEW ALL UPLOADS",
    "batch_window_seconds": DEFAULT_BATCH_WINDOW,
    "digest_enabled": True,
    "digest_time": "21:00",
    "timezone": BOT_TIMEZONE or "Asia/Kolkata",
    "poster_enabled": True,
    "fallback_poster": "",
    "imdb_timeout": 12,
    "metadata_cache_days": 7,
    "metadata_failure_cache_minutes": 60,
    "max_delivery_attempts": MAX_DELIVERY_ATTEMPTS,
    "digest_last_published_at": "",
}

_db_handle = None
_worker_task = None
_settings_cache: Dict[str, Any] = {"value": None, "expires": 0.0}
_TECHNICAL_CLEAN_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:web[\s._-]*dl|webrip|blu[\s._-]*ray|bdrip|hdrip|"
    r"hdtv|x264|x265|hevc|avc|hdr(?:10)?|aac\d*|eac3|ac3|dts|atmos)(?![A-Za-z0-9])"
)
_INVITE_RE = re.compile(r"(https?://)?t\.me/(\+|joinchat/)[A-Za-z0-9_-]+")


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(dt_timezone.utc)


def safe_error_text(value: Any, limit: int = 300) -> str:
    """Return a log-safe error string (no private invite links)."""
    text = str(value or "").strip()
    text = _INVITE_RE.sub("t.me/<hidden-invite>", text)
    text = re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot<redacted>", text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def get_timezone(name: str):
    name = str(name or BOT_TIMEZONE or "Asia/Kolkata")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        try:
            import pytz

            return pytz.timezone(name)
        except Exception:
            from zoneinfo import ZoneInfo

            return ZoneInfo("UTC")


def parse_hhmm(value: str) -> Tuple[int, int]:
    match = re.match(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$", str(value or ""))
    if not match:
        return 21, 0
    return int(match.group(1)), int(match.group(2))


def validate_button_url(url: Any) -> bool:
    """Validate CTA URLs. Only http(s) links are accepted."""
    text = str(url or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    lower = text.lower()
    if lower.startswith(("javascript:", "data:", "file:", "tg:")):
        return False
    if not lower.startswith(("http://", "https://")):
        return False
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(text)
    except Exception:
        return False
    if not parts.scheme or not parts.netloc:
        return False
    host = parts.netloc.lower()
    if "t.me" in host or "telegram.me" in host or "telegram.dog" in host:
        return bool(parts.path.strip("/") or parts.query)
    return True


def normalize_button_text(value: Any, default: str = "GET NOW") -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return default
    return text[:64]


def _resolve_button_url(settings: Dict[str, Any], kind: str, bot=None) -> str:
    candidates = []
    if kind == "movie":
        candidates.append(settings.get("movie_button_url"))
    elif kind == "series":
        candidates.append(settings.get("series_button_url"))
    candidates.append(settings.get("button_url"))
    candidates.append(_GROUP_URL_DEFAULT)
    for candidate in candidates:
        if validate_button_url(candidate):
            return str(candidate).strip()
    username = getattr(bot, "username", None) if bot is not None else None
    if not username:
        try:
            from utils import temp

            username = temp.U_NAME
        except Exception:
            username = ""
    if username:
        return f"https://t.me/{str(username).lstrip('@')}"
    return ""


def classify_telegram_error(error: Any) -> str:
    """Return 'permanent', 'flood' or 'transient' for a Telegram error."""
    name = type(error).__name__
    if name == "FloodWait":
        return "flood"
    permanent = {
        "ChatAdminRequired",
        "ChatWriteForbidden",
        "ChannelInvalid",
        "ChannelPrivate",
        "ChatNotFound",
        "PeerIdInvalid",
        "UserBannedInChannel",
        "UserNotParticipant",
        "UsernameInvalid",
        "UsernameNotModified",
        "MessageTooLong",
        "MediaCaptionTooLong",
        "BotMethodInvalid",
    }
    if name in permanent:
        return "permanent"
    return "transient"


def retry_delay_seconds(attempts: int) -> int:
    attempts = max(0, int(attempts))
    return min(3600, 30 * (2 ** attempts))


def clean_metadata_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value if item is not None)
    text = html.unescape(str(value)).strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    if text.lower() in {"none", "null", "n/a", "na", "nan", "-", ""}:
        return ""
    return text


def _truncate_text(value: str, limit: int = 400) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return (cut or text[:limit].rstrip()) + "…"


def escape_text(value: Any) -> str:
    return html.escape(clean_metadata_value(value), quote=False)


def series_key(title: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(title or "").casefold()).split())


def _file_stem(file_name: str) -> str:
    name = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", str(file_name or ""))
    name = re.sub(r"[_\.+]+", " ", name)
    name = _TECHNICAL_CLEAN_RE.sub(" ", name)
    return " ".join(name.split()).strip(" -_.:|[](){}") or str(file_name or "Media File")


def build_event_id(source_db: str, media: Any) -> str:
    unique = (
        getattr(media, "file_unique_id", None)
        or getattr(media, "file_id", None)
        or getattr(media, "file_name", "")
    )
    ident = f"{source_db}|{unique}"
    return "evt_" + hashlib.sha256(ident.encode("utf-8", "ignore")).hexdigest()[:24]


def build_event(media: Any, source_db: str = "primary") -> Dict[str, Any]:
    file_name = str(getattr(media, "file_name", "") or "")
    try:
        size = int(getattr(media, "file_size", 0) or 0)
    except (TypeError, ValueError):
        size = 0
    parsed = parse_smart_media_item(file_name, file_size=size)
    title = clean_metadata_value(parsed.title) or _file_stem(file_name)
    now = _now()
    return {
        "event_id": build_event_id(source_db, media),
        "file_id": str(getattr(media, "file_id", "") or ""),
        "source_db": source_db,
        "category": parsed.category,
        "title": title,
        "year": parsed.year,
        "season": parsed.season,
        "episode": parsed.episode,
        "episode_code": parsed.episode_code,
        "quality": parsed.quality,
        "language": parsed.language,
        "file_name": file_name,
        "file_size": size,
        "series_key": series_key(title),
        "state": "PENDING",
        "indexed_at": now,
        "created_at": now,
        "updated_at": now,
    }


def episode_sort_key(code: Any) -> Tuple[int, int, str]:
    match = re.search(r"E(\d+)\s*S(\d+)", str(code or ""), re.IGNORECASE)
    if match:
        return int(match.group(2)), int(match.group(1)), str(code)
    match = re.search(r"S(\d+)\s*E(\d+)", str(code or ""), re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2)), str(code)
    return 999, 999, str(code)


def chunk_episodes(episodes: Sequence[str], per_page: int = 35) -> List[List[str]]:
    ordered = sorted({str(ep) for ep in episodes if str(ep or "").strip()}, key=episode_sort_key)
    if not ordered:
        return [[]]
    return [ordered[i: i + per_page] for i in range(0, len(ordered), per_page)]


def _quality_sort_key(value: str) -> Tuple[int, str]:
    match = re.search(r"(\d{3,4})\s*p", str(value or ""), re.IGNORECASE)
    if match:
        return int(match.group(1)), str(value)
    if re.search(r"\b4\s*k\b", str(value or ""), re.IGNORECASE):
        return 2160, str(value)
    return 9999, str(value)


def _safe_format(template: str, values: Dict[str, Any]) -> str:
    class SafeDict(dict):
        def __missing__(self, key):
            return ""

    try:
        return str(template or "").format_map(SafeDict(values))
    except Exception:
        return str(template or "")


def tidy_caption(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    cleaned: List[str] = []
    for line in lines:
        if not line.strip():
            if cleaned and cleaned[-1] == "":
                continue
            cleaned.append("")
        else:
            cleaned.append(line)
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def paginate_text(text: str, limit: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """Split text into <=limit chunks without dropping any line."""
    limit = max(200, int(limit))
    lines = str(text or "").splitlines()
    pages: List[str] = []
    current: List[str] = []
    length = 0
    for line in lines:
        while len(line) > limit:
            head, line = line[:limit], line[limit:]
            if current:
                pages.append("\n".join(current))
                current, length = [], 0
            pages.append(head)
        add = len(line) + (1 if current else 0)
        if current and length + add > limit:
            pages.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + (1 if len(current) > 1 else 0)
    if current:
        pages.append("\n".join(current))
    return [page for page in pages if page.strip()] or [""]


def _with_page_numbers(pages: List[str]) -> List[str]:
    if len(pages) <= 1:
        return pages
    total = len(pages)
    return [f"<i>(Page {index}/{total})</i>\n{page}" for index, page in enumerate(pages, 1)]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def _metadata_matches(event: Dict[str, Any], metadata: Dict[str, Any]) -> bool:
    if not metadata:
        return False
    event_title = series_key(event.get("title"))
    meta_title = series_key(metadata.get("title"))
    if event_title and meta_title:
        if event_title not in meta_title and meta_title not in event_title:
            event_tokens = set(event_title.split())
            meta_tokens = set(meta_title.split())
            union = event_tokens | meta_tokens
            overlap = len(event_tokens & meta_tokens) / len(union) if union else 0
            if overlap < 0.6:
                return False
    event_year = str(event.get("year") or "")
    meta_year = clean_metadata_value(metadata.get("year"))
    if event_year and meta_year and meta_year.isdigit():
        if abs(int(event_year) - int(meta_year)) > 1:
            return False
    kind = clean_metadata_value(metadata.get("kind")).lower()
    if kind:
        if event.get("category") == "series":
            if "series" not in kind:
                return False
        elif "series" in kind:
            return False
    return True


def normalize_metadata(metadata: Any) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    normalized: Dict[str, Any] = {}
    for key in (
        "title",
        "year",
        "rating",
        "genres",
        "plot",
        "poster",
        "imdb_id",
        "languages",
        "runtime",
        "certificates",
        "kind",
    ):
        value = clean_metadata_value(metadata.get(key))
        if value:
            normalized[key] = value
    poster = normalized.get("poster", "")
    if poster and not poster.lower().startswith(("http://", "https://")):
        normalized.pop("poster", None)
    return normalized


def metadata_cache_key(event: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(event.get("category") or ""),
            series_key(event.get("title")),
            str(event.get("year") or ""),
        ]
    )


async def _lookup_cinemagoer(
    event: Dict[str, Any], settings: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    """Original provider path, kept as a fallback for backwards compatibility."""
    title = clean_metadata_value(event.get("title"))
    if not title:
        return {}, "empty title"
    query = f"{title} {event.get('year')}" if event.get("year") else title
    timeout = max(3, int(settings.get("imdb_timeout") or 12))
    try:
        from utils import get_poster

        raw = await asyncio.wait_for(get_poster(query), timeout=timeout)
    except asyncio.TimeoutError:
        return {}, "cinemagoer timeout"
    except Exception as exc:
        return {}, f"cinemagoer error: {safe_error_text(exc)}"

    metadata = normalize_metadata(raw)
    if not metadata:
        return {}, "cinemagoer returned no metadata"
    if not _metadata_matches(event, metadata):
        return {}, "cinemagoer match rejected"
    return metadata, ""


async def _lookup_public_imdb(
    event: Dict[str, Any], settings: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    """Same-provider fallback: IMDb suggestion search + GraphQL details."""
    title = clean_metadata_value(event.get("title"))
    if not title:
        return {}, "empty title"
    try:
        from Lootere.utils import imdb_metadata

        timeout = max(3, int(settings.get("imdb_timeout") or 12))
        metadata, reason = await imdb_metadata.lookup(
            title=title,
            year=event.get("year"),
            category=event.get("category") or "movie",
            imdb_id=event.get("imdb_id") or "",
            timeout=timeout,
        )
    except Exception as exc:
        return {}, f"imdb provider error: {safe_error_text(exc)}"

    metadata = normalize_metadata(metadata)
    if not metadata:
        return {}, reason or "imdb returned no metadata"
    if not _metadata_matches(event, metadata):
        return {}, "imdb match rejected"
    return metadata, ""


async def _poster_from_search_provider(
    event: Dict[str, Any], settings: Dict[str, Any]
) -> str:
    """Reuse the provider that already powers search-result posters.

    Search results call ``utils.get_poster`` (Cinemagoer) and use its
    ``poster`` field directly.  The IMDb GraphQL metadata used by
    notifications does not always include ``primaryImage``, so this is a
    poster-only fallback for the exact same provider.  Never raises and is
    bounded by ``imdb_timeout``.
    """
    title = clean_metadata_value(event.get("title"))
    if not title:
        return ""
    query = f"{title} {event.get('year')}".strip() if event.get("year") else title
    timeout = max(3, int(settings.get("imdb_timeout") or 12))
    try:
        from utils import get_poster

        raw = await asyncio.wait_for(get_poster(query), timeout=timeout)
    except asyncio.TimeoutError:
        logger.info("Poster search fallback timed out for %r", title)
        return ""
    except Exception as exc:
        logger.info("Poster search fallback failed for %r: %s", title, safe_error_text(exc))
        return ""
    if not isinstance(raw, dict):
        return ""
    poster = clean_metadata_value(raw.get("poster"))
    if poster and poster.lower().startswith(("http://", "https://")):
        return poster
    return ""


async def resolve_metadata(event: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve IMDb metadata, recording the exact failure reason on the event.

    Metadata always resolves *before* the payload is built.  When a lookup
    fails the notification is still delivered without the missing fields, and a
    later lookup never edits or re-sends an already delivered post, so retries
    can never publish a duplicate notification.
    """
    handle = _database()
    cache_key = metadata_cache_key(event)
    now = _now()
    event["metadata_error"] = ""
    event["metadata_source"] = ""

    if handle is not None and cache_key:
        try:
            cached = await handle[METADATA_COLLECTION].find_one(
                {"cache_key": cache_key, "expires_at": {"$gt": now}}
            )
            if cached is not None:
                cached_metadata = normalize_metadata(cached.get("metadata"))
                if cached_metadata:
                    event["metadata_source"] = cached.get("source") or "cache"
                    return cached_metadata
                if cached.get("last_error"):
                    event["metadata_error"] = cached["last_error"]
                    return {}
                # Legacy failure entry written before failure reasons existed:
                # ignore it so the improved provider gets a fresh attempt.
        except Exception:
            logger.debug("Metadata cache read failed", exc_info=True)

    metadata: Dict[str, Any] = {}
    source = ""
    reasons: List[str] = []

    # The public IMDb path is tried first: it has strict title/type/year
    # matching and returns real details in the current IMDb environment.
    imdb_metadata, imdb_reason = await _lookup_public_imdb(event, settings)
    if imdb_metadata:
        metadata, source = imdb_metadata, "imdb"
    elif imdb_reason:
        reasons.append(imdb_reason)

    # Legacy Cinemagoer path remains as a fallback, never as the only source.
    if not metadata:
        cinemagoer_metadata, cinemagoer_reason = await _lookup_cinemagoer(event, settings)
        if cinemagoer_metadata:
            metadata, source = cinemagoer_metadata, "cinemagoer"
        elif cinemagoer_reason:
            reasons.append(cinemagoer_reason)

    if not metadata:
        event["metadata_error"] = "; ".join(reason for reason in reasons if reason)[:300]
        logger.info(
            "Notification metadata unavailable for %r (%s)",
            clean_metadata_value(event.get("title")),
            event["metadata_error"] or "unknown reason",
        )
    else:
        event["metadata_source"] = source
        if not clean_metadata_value(metadata.get("poster")):
            fallback_poster = await _poster_from_search_provider(event, settings)
            if fallback_poster:
                metadata["poster"] = fallback_poster
                logger.info(
                    "Poster resolved via search provider for %r",
                    clean_metadata_value(event.get("title")),
                )
        logger.info(
            "Metadata resolved via %s for %r (poster=%s)",
            source,
            clean_metadata_value(event.get("title")),
            _poster_label(metadata.get("poster")) or "none",
        )

    if handle is not None and cache_key:
        try:
            days = max(1, int(settings.get("metadata_cache_days") or 7))
            minutes = max(5, int(settings.get("metadata_failure_cache_minutes") or 60))
            expires = (
                now + timedelta(days=days) if metadata else now + timedelta(minutes=minutes)
            )
            await handle[METADATA_COLLECTION].update_one(
                {"cache_key": cache_key},
                {
                    "$set": {
                        "cache_key": cache_key,
                        "metadata": metadata or None,
                        "expires_at": expires,
                        "updated_at": now,
                        "source": source,
                        "last_error": "" if metadata else event["metadata_error"],
                    }
                },
                upsert=True,
            )
        except Exception:
            logger.debug("Metadata cache write failed", exc_info=True)
    return metadata


# ---------------------------------------------------------------------------
# Caption building
# ---------------------------------------------------------------------------
def _pick_language(event: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    value = clean_metadata_value(event.get("language"))
    if value:
        return value
    languages = clean_metadata_value(metadata.get("languages"))
    if not languages:
        return ""
    first = re.split(r"[,/|+]", languages)[0].strip()
    return first[:40]


def _display_title(event: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    return (
        clean_metadata_value(metadata.get("title"))
        or clean_metadata_value(event.get("title"))
        or _file_stem(event.get("file_name", ""))
    )


def build_movie_caption(
    event: Dict[str, Any], metadata: Optional[Dict[str, Any]], settings: Dict[str, Any]
) -> str:
    metadata = metadata or {}
    title = _display_title(event, metadata)
    year = clean_metadata_value(event.get("year")) or clean_metadata_value(metadata.get("year"))
    rating = clean_metadata_value(metadata.get("rating"))
    imdb_id = clean_metadata_value(metadata.get("imdb_id"))
    genre = clean_metadata_value(metadata.get("genres"))
    language = _pick_language(event, metadata)
    quality = clean_metadata_value(event.get("quality"))
    runtime = clean_metadata_value(metadata.get("runtime"))
    certification = clean_metadata_value(metadata.get("certificates"))
    description = _truncate_text(clean_metadata_value(metadata.get("plot")), 400)

    title_line = escape_text(title) + (f" ({escape_text(year)})" if year else "")
    values = {
        "title": escape_text(title),
        "title_line": title_line,
        "year": escape_text(year),
        "rating": escape_text(rating),
        "imdb_id": escape_text(imdb_id),
        "genre": escape_text(genre),
        "language": escape_text(language),
        "quality": escape_text(quality),
        "runtime": escape_text(runtime),
        "certification": escape_text(certification),
        "description": escape_text(description),
        "size": clean_metadata_value(event.get("file_size")),
        "rating_line": f"⭐ IMDb: {escape_text(rating)}/10\n" if rating else "",
        "imdb_line": f"🆔 IMDb: {escape_text(imdb_id)}\n" if imdb_id else "",
        "genre_line": f"🎬 Genre: {escape_text(genre)}\n" if genre else "",
        "language_line": f"🌐 Language: {escape_text(language)}\n" if language else "",
        "quality_line": f"🎞️ Quality: {escape_text(quality)}\n" if quality else "",
        "runtime_line": f"⏱️ Runtime: {escape_text(runtime)}\n" if runtime else "",
        "certification_line": (
            f"🔞 Certification: {escape_text(certification)}\n" if certification else ""
        ),
        "description_line": (
            f"📝 Description:\n{escape_text(description)}\n\n" if description else ""
        ),
    }
    template = settings.get("movie_caption_template") or DEFAULT_MOVIE_TEMPLATE
    return tidy_caption(_safe_format(template, values))


def build_series_captions(
    events: Sequence[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]],
    settings: Dict[str, Any],
) -> List[str]:
    metadata = metadata or {}
    if not events:
        return []
    first = events[0]
    title = _display_title(first, metadata)
    year = clean_metadata_value(first.get("year")) or clean_metadata_value(metadata.get("year"))
    rating = clean_metadata_value(metadata.get("rating"))
    imdb_id = clean_metadata_value(metadata.get("imdb_id"))
    genre = clean_metadata_value(metadata.get("genres"))
    language = _pick_language(first, metadata)
    runtime = clean_metadata_value(metadata.get("runtime"))
    description = _truncate_text(clean_metadata_value(metadata.get("plot")), 400)
    season = first.get("season")
    qualities = sorted(
        {clean_metadata_value(event.get("quality")) for event in events if event.get("quality")},
        key=_quality_sort_key,
    )
    quality_text = " / ".join(qualities)
    episode_codes = [event.get("episode_code") for event in events if event.get("episode_code")]
    total_episodes = len(episode_codes) or len(events)

    title_line = escape_text(title)
    if year:
        title_line += f" ({escape_text(year)})"
    if season is not None:
        title_line += f" — Season {int(season)}"

    chunks = chunk_episodes(episode_codes)
    captions: List[str] = []
    for chunk in chunks:
        block_lines = ["<b>New Episodes:</b>"] + [f"• {escape_text(code)}" for code in chunk]
        values = {
            "title": escape_text(title),
            "title_line": title_line,
            "year": escape_text(year),
            "rating": escape_text(rating),
            "imdb_id": escape_text(imdb_id),
            "genre": escape_text(genre),
            "language": escape_text(language),
            "quality": escape_text(quality_text),
            "qualities": escape_text(quality_text),
            "season": "" if season is None else str(int(season)),
            "episode_list": "\n".join(f"• {escape_text(code)}" for code in chunk),
            "new_episodes_block": "\n".join(block_lines),
            "episode_count": str(total_episodes),
            "runtime": escape_text(runtime),
            "description": escape_text(description),
            "rating_line": f"⭐ IMDb: {escape_text(rating)}/10\n" if rating else "",
            "imdb_line": f"🆔 IMDb: {escape_text(imdb_id)}\n" if imdb_id else "",
            "genre_line": f"🎬 Genre: {escape_text(genre)}\n" if genre else "",
            "language_line": f"🌐 Language: {escape_text(language)}\n" if language else "",
            "quality_line": f"🎞️ Quality: {escape_text(quality_text)}\n" if quality_text else "",
            "runtime_line": f"⏱️ Runtime: {escape_text(runtime)}\n" if runtime else "",
            "description_line": (
                f"📝 Description:\n{escape_text(description)}\n\n" if description else ""
            ),
        }
        template = settings.get("series_caption_template") or DEFAULT_SERIES_TEMPLATE
        captions.append(tidy_caption(_safe_format(template, values)))

    if len(captions) > 1:
        total = len(captions)
        captions = [
            tidy_caption(f"{caption}\n\n<i>(Part {index}/{total})</i>")
            for index, caption in enumerate(captions, 1)
        ]
    return [caption for caption in captions if caption]


def _poster_label(poster: Any) -> str:
    """Log-safe poster identifier: host+path only, never query strings."""
    value = str(poster or "")
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
    except Exception:
        return "invalid"
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:180]


def build_payload(
    owner_id: str,
    kind: str,
    events: Sequence[Dict[str, Any]],
    metadata: Optional[Dict[str, Any]],
    settings: Dict[str, Any],
    bot=None,
) -> Dict[str, Any]:
    if kind == "series":
        captions = build_series_captions(events, metadata, settings)
    else:
        captions = [build_movie_caption(events[0], metadata, settings)] if events else []
    poster = ""
    if settings.get("poster_enabled", True):
        poster = (
            clean_metadata_value((metadata or {}).get("poster"))
            # A poster stored on the event (manual override / older record) is
            # still usable when IMDb metadata is disabled or unavailable.
            or (clean_metadata_value(events[0].get("poster")) if events else "")
            or clean_metadata_value(settings.get("fallback_poster"))
        )
    if poster and not poster.lower().startswith(("http://", "https://")):
        poster = ""
    logger.info(
        "Notification payload %s: poster=%s (metadata_poster=%s fallback=%s)",
        owner_id,
        _poster_label(poster) or "none",
        bool(clean_metadata_value((metadata or {}).get("poster"))),
        bool(clean_metadata_value(settings.get("fallback_poster"))),
    )
    return {
        "owner_id": owner_id,
        "kind": kind,
        "captions": [caption for caption in captions if caption],
        "poster": poster,
        "button_text": normalize_button_text(settings.get("button_text"), "GET NOW"),
        "button_url": _resolve_button_url(settings, kind, bot),
        "created_at": _now(),
    }


# ---------------------------------------------------------------------------
# Digest helpers
# ---------------------------------------------------------------------------
def most_recent_sunday(now_local: datetime, scheduled_time: Tuple[int, int]) -> datetime:
    hour, minute = scheduled_time
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_since_sunday = (now_local.weekday() - 6) % 7
    candidate -= timedelta(days=days_since_sunday)
    if candidate > now_local:
        candidate -= timedelta(days=7)
    return candidate


def summarize_events(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    movies: Dict[Tuple[str, str], Dict[str, Any]] = {}
    series: Dict[str, Dict[str, Any]] = {}
    episodes = 0
    quality_counts: Dict[str, int] = {}
    language_counts: Dict[str, int] = {}

    for event in events:
        title = clean_metadata_value(event.get("title")) or _file_stem(event.get("file_name", ""))
        year = clean_metadata_value(event.get("year"))
        quality = clean_metadata_value(event.get("quality"))
        language = clean_metadata_value(event.get("language"))
        if quality:
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1

        if event.get("category") == "series":
            episodes += 1
            key = event.get("series_key") or series_key(title)
            entry = series.setdefault(key, {"title": title, "year": year, "episodes": 0})
            entry["episodes"] += 1
            if year and not entry.get("year"):
                entry["year"] = year
        else:
            key = (series_key(title), year)
            entry = movies.setdefault(key, {"title": title, "year": year, "quality": quality})
            if quality and not entry.get("quality"):
                entry["quality"] = quality

    return {
        "movie_count": len(movies),
        "series_count": len(series),
        "episode_count": episodes,
        "file_count": len(events),
        "movies": sorted(movies.values(), key=lambda item: (item["title"].lower(), item["year"])),
        "series": sorted(series.values(), key=lambda item: item["title"].lower()),
        "top_languages": sorted(language_counts.items(), key=lambda item: (-item[1], item[0]))[:5],
        "top_qualities": sorted(quality_counts.items(), key=lambda item: (-item[1], item[0]))[:5],
    }


def build_digest_caption(
    events: Sequence[Dict[str, Any]],
    period_start: datetime,
    period_end: datetime,
    settings: Dict[str, Any],
) -> str:
    summary = summarize_events(events)
    period = f"{period_start:%d %B} – {period_end:%d %B}"
    sections: List[str] = []

    sections.append("\n<b>NEW MOVIES</b>")
    if summary["movies"]:
        for index, movie in enumerate(summary["movies"], 1):
            line = f"{index}. {escape_text(movie['title'])}"
            if movie.get("year"):
                line += f" ({escape_text(movie['year'])})"
            if movie.get("quality"):
                line += f" — {escape_text(movie['quality'])}"
            sections.append(line)
    else:
        sections.append("• No new movies this week.")

    sections.append("\n<b>NEW SERIES</b>")
    if summary["series"]:
        for index, show in enumerate(summary["series"], 1):
            line = f"{index}. {escape_text(show['title'])}"
            if show.get("year"):
                line += f" ({escape_text(show['year'])})"
            line += f" — {int(show['episodes'])} Episode"
            line += "" if int(show["episodes"]) == 1 else "s"
            sections.append(line)
    else:
        sections.append("• No new series this week.")

    sections.append("\n<b>TOP LANGUAGES</b>")
    if summary["top_languages"]:
        sections.extend(f"• {escape_text(name)}" for name, _ in summary["top_languages"])
    else:
        sections.append("• Not available.")

    sections.append("\n<b>TOP QUALITIES</b>")
    if summary["top_qualities"]:
        sections.extend(f"• {escape_text(name)}" for name, _ in summary["top_qualities"])
    else:
        sections.append("• Not available.")

    template = settings.get("digest_caption_template") or DEFAULT_DIGEST_TEMPLATE
    text = _safe_format(
        template,
        {
            "period": escape_text(period),
            "movie_count": summary["movie_count"],
            "series_count": summary["series_count"],
            "episode_count": summary["episode_count"],
            "file_count": summary["file_count"],
            "sections": "\n".join(sections),
        },
    )
    return tidy_caption(text)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def set_database(db_handle):
    global _db_handle
    _db_handle = db_handle


def _database():
    if _db_handle is not None:
        return _db_handle
    try:
        from database.users_chats_db import db as bot_db

        return getattr(bot_db, "db", None)
    except Exception:
        return None


def _chat_ref(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return text.lstrip("@")


def _invalidate_settings_cache():
    _settings_cache["value"] = None
    _settings_cache["expires"] = 0.0


async def get_settings(force: bool = False) -> Dict[str, Any]:
    now = _now().timestamp()
    if (
        not force
        and _settings_cache["value"] is not None
        and now < _settings_cache["expires"]
    ):
        return deepcopy(_settings_cache["value"])

    merged = deepcopy(DEFAULT_SETTINGS)
    handle = _database()
    if handle is not None:
        try:
            stored = await handle["settings"].find_one({"name": SETTINGS_KEY})
            value = stored.get("value") if stored else None
            if isinstance(value, dict):
                merged.update(value)
        except Exception:
            logger.debug("Notification settings read failed", exc_info=True)
    _settings_cache["value"] = merged
    _settings_cache["expires"] = now + SETTINGS_CACHE_TTL
    return deepcopy(merged)


async def save_settings(admin_id: Optional[int] = None, **changes) -> Dict[str, Any]:
    handle = _database()
    current = await get_settings(force=True)
    updated = dict(current)
    updated.update({key: value for key, value in changes.items() if key in DEFAULT_SETTINGS})
    if handle is not None:
        try:
            await handle["settings"].update_one(
                {"name": SETTINGS_KEY}, {"$set": {"value": updated}}, upsert=True
            )
            await handle[AUDIT_COLLECTION].insert_one(
                {
                    "admin_id": int(admin_id) if admin_id is not None else None,
                    "changes": {key: updated[key] for key in changes if key in DEFAULT_SETTINGS},
                    "created_at": _now(),
                }
            )
        except Exception:
            logger.exception("Failed to persist Feature 46 settings")
    _invalidate_settings_cache()
    _settings_cache["value"] = updated
    _settings_cache["expires"] = _now().timestamp() + SETTINGS_CACHE_TTL
    return deepcopy(updated)


async def ensure_notification_indexes() -> None:
    handle = _database()
    if handle is None:
        return
    try:
        await handle[EVENTS_COLLECTION].create_index("event_id", unique=True)
        await handle[EVENTS_COLLECTION].create_index([("state", 1), ("indexed_at", 1)])
        await handle[EVENTS_COLLECTION].create_index("indexed_at")
        await handle[DELIVERIES_COLLECTION].create_index("delivery_id", unique=True)
        await handle[DELIVERIES_COLLECTION].create_index([("status", 1), ("next_retry_at", 1)])
        await handle[DELIVERIES_COLLECTION].create_index("owner_id")
        await handle[BATCHES_COLLECTION].create_index("batch_id", unique=True)
        await handle[BATCHES_COLLECTION].create_index([("state", 1), ("window_end", 1)])
        await handle[DIGESTS_COLLECTION].create_index("digest_id", unique=True)
        await handle[DIGESTS_COLLECTION].create_index("period_key", unique=True)
        await handle[METADATA_COLLECTION].create_index("cache_key", unique=True)
    except Exception:
        logger.exception("Failed to ensure Feature 46 indexes")


async def record_upload_event(media: Any, source_db: str = "primary") -> bool:
    """Register a successfully indexed file. Never raises into indexing code."""
    try:
        settings = await get_settings()
        if not settings.get("enabled"):
            return False
        handle = _database()
        if handle is None:
            return False
        event = build_event(media, source_db)
        if event.get("category") == "series" and event.get("episode_code"):
            event["state"] = "BATCH_PENDING"
        result = await handle[EVENTS_COLLECTION].update_one(
            {"event_id": event["event_id"]}, {"$setOnInsert": event}, upsert=True
        )
        if not getattr(result, "upserted_id", None):
            return False
        if event.get("category") == "series" and event.get("episode_code"):
            await _enqueue_series_event(event, settings)
        return True
    except Exception:
        logger.exception("Failed to register Feature 46 upload event")
        return False


async def _enqueue_series_event(event: Dict[str, Any], settings: Dict[str, Any]) -> None:
    handle = _database()
    if handle is None:
        return
    batch_window = int(settings.get("batch_window_seconds") or DEFAULT_BATCH_WINDOW)
    batch_window = max(30, min(MAX_BATCH_WINDOW, batch_window))
    key = event.get("series_key")
    season = event.get("season")
    now = _now()
    query = {"series_key": key, "season": season, "state": "OPEN"}
    existing = await handle[BATCHES_COLLECTION].find_one(query)
    if existing:
        cap = existing.get("max_window_end") or (now + timedelta(seconds=batch_window))
        window_end = min(now + timedelta(seconds=batch_window), cap)
        await handle[BATCHES_COLLECTION].update_one(
            {"_id": existing["_id"]},
            {
                "$addToSet": {"event_ids": event["event_id"]},
                "$set": {"window_end": window_end, "updated_at": now},
            },
        )
        return
    batch_id = "bat_" + hashlib.sha256(
        f"{key}|{season}|{now.timestamp()}".encode()
    ).hexdigest()[:20]
    doc = {
        "batch_id": batch_id,
        "series_key": key,
        "series_title": event.get("title"),
        "season": season,
        "event_ids": [event["event_id"]],
        "state": "OPEN",
        "window_end": now + timedelta(seconds=batch_window),
        "max_window_end": now + timedelta(seconds=max(batch_window * 6, 1800)),
        "created_at": now,
        "updated_at": now,
    }
    try:
        await handle[BATCHES_COLLECTION].insert_one(doc)
    except Exception:
        await handle[BATCHES_COLLECTION].update_one(
            query,
            {
                "$addToSet": {"event_ids": event["event_id"]},
                "$set": {"updated_at": now},
            },
        )


async def _create_deliveries(
    owner_id: str, payload: Dict[str, Any], settings: Dict[str, Any]
) -> int:
    handle = _database()
    if handle is None:
        return 0
    created = 0
    now = _now()
    logger.info(
        "Storing deliveries for %s with poster=%s",
        owner_id,
        _poster_label(payload.get("poster")) or "none",
    )
    for destination in ("channel", "group"):
        if not settings.get(f"{destination}_enabled"):
            continue
        chat_ref = _chat_ref(settings.get(f"{destination}_id"))
        if not chat_ref:
            continue
        for index, caption in enumerate(payload.get("captions") or []):
            delivery_id = f"dlv_{owner_id}_{destination}_{index}"
            doc = {
                "delivery_id": delivery_id,
                "owner_id": owner_id,
                "kind": payload.get("kind"),
                "destination_type": destination,
                "chat_id": str(chat_ref),
                "caption": caption,
                "poster": payload.get("poster") or "",
                "button_text": payload.get("button_text") or "GET NOW",
                "button_url": payload.get("button_url") or "",
                "status": "PENDING",
                "attempts": 0,
                "last_error": "",
                "next_retry_at": now,
                "created_at": now,
                "updated_at": now,
            }
            result = await handle[DELIVERIES_COLLECTION].update_one(
                {"delivery_id": delivery_id}, {"$setOnInsert": doc}, upsert=True
            )
            if getattr(result, "upserted_id", None):
                created += 1
    return created


async def _mark_event_state(event_id: str, state: str, **extra) -> None:
    handle = _database()
    if handle is None:
        return
    update = {"state": state, "updated_at": _now()}
    update.update(extra)
    await handle[EVENTS_COLLECTION].update_one({"event_id": event_id}, {"$set": update})


async def process_pending_events(bot=None, limit: int = 20) -> int:
    handle = _database()
    if handle is None:
        return 0
    settings = await get_settings()
    processed = 0
    cursor = handle[EVENTS_COLLECTION].find(
        {"state": "PENDING", "category": "movie"}
    ).limit(limit)
    async for event in cursor:
        claimed = await handle[EVENTS_COLLECTION].find_one_and_update(
            {"_id": event["_id"], "state": "PENDING"},
            {"$set": {"state": "PROCESSING", "processing_started_at": _now()}},
            return_document=True,
        )
        if not claimed:
            continue
        try:
            metadata = await resolve_metadata(claimed, settings)
            payload = build_payload(
                claimed["event_id"], "movie", [claimed], metadata, settings, bot
            )
            await _mark_event_state(
                claimed["event_id"],
                "READY",
                payload=payload,
                metadata_failed=not bool(metadata),
                metadata_title=(metadata or {}).get("title", ""),
                metadata_source=claimed.get("metadata_source") or "",
                metadata_error=claimed.get("metadata_error") or "",
            )
            await _create_deliveries(claimed["event_id"], payload, settings)
            processed += 1
        except Exception:
            logger.exception("Failed to prepare movie notification %s", claimed.get("event_id"))
            await _mark_event_state(claimed["event_id"], "FAILED", last_error="payload build failed")
    return processed


async def process_due_batches(bot=None, limit: int = 10) -> int:
    handle = _database()
    if handle is None:
        return 0
    settings = await get_settings()
    processed = 0
    for _ in range(limit):
        batch = await handle[BATCHES_COLLECTION].find_one_and_update(
            {"state": "OPEN", "window_end": {"$lte": _now()}},
            {"$set": {"state": "PROCESSING", "processing_started_at": _now()}},
            sort=[("window_end", 1)],
            return_document=True,
        )
        if not batch:
            break
        try:
            event_ids = batch.get("event_ids") or []
            events = []
            if event_ids:
                cursor = handle[EVENTS_COLLECTION].find({"event_id": {"$in": event_ids}})
                events = [event async for event in cursor]
            if not events:
                await handle[BATCHES_COLLECTION].update_one(
                    {"_id": batch["_id"]},
                    {"$set": {"state": "FINALIZED", "updated_at": _now(), "episode_count": 0}},
                )
                continue
            metadata = await resolve_metadata(events[0], settings)
            payload = build_payload(
                batch["batch_id"], "series", events, metadata, settings, bot
            )
            await handle[BATCHES_COLLECTION].update_one(
                {"_id": batch["_id"]},
                {
                    "$set": {
                        "state": "READY",
                        "payload": payload,
                        "metadata_failed": not bool(metadata),
                        "metadata_source": events[0].get("metadata_source") or "",
                        "metadata_error": events[0].get("metadata_error") or "",
                        "episode_count": len(events),
                        "updated_at": _now(),
                    }
                },
            )
            for event in events:
                await _mark_event_state(event["event_id"], "BATCHED", batch_id=batch["batch_id"])
            await _create_deliveries(batch["batch_id"], payload, settings)
            processed += 1
        except Exception:
            logger.exception("Failed to prepare series batch %s", batch.get("batch_id"))
            await handle[BATCHES_COLLECTION].update_one(
                {"_id": batch["_id"]},
                {"$set": {"state": "FAILED", "last_error": "batch build failed"}},
            )
    return processed


def _build_markup(delivery: Dict[str, Any]):
    try:
        from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        url = delivery.get("button_url") or ""
        if not validate_button_url(url):
            return None
        label = normalize_button_text(delivery.get("button_text"), "GET NOW")
        return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])
    except Exception:
        return None


async def _poster_usable(poster: str) -> bool:
    """Validate a poster before sending, without ever blocking delivery."""
    if not str(poster or "").lower().startswith(("http://", "https://")):
        return False
    try:
        from Lootere.utils.imdb_metadata import poster_is_usable

        usable, reason = await poster_is_usable(poster)
        if not usable:
            logger.info("Skipping unusable poster: %s", safe_error_text(reason))
        return bool(usable)
    except Exception:
        # Validation is best-effort; let Telegram attempt the photo.
        return True


async def _poster_image(poster: str) -> Tuple[bytes, str, str]:
    """Download and validate a poster for re-upload. Never raises."""
    try:
        from Lootere.utils.imdb_metadata import fetch_poster_bytes

        data, filename, reason = await fetch_poster_bytes(poster)
        if not data:
            logger.info("Poster download failed (%s): %s", _poster_label(poster), reason)
        return data, filename, reason
    except Exception as exc:
        logger.info("Poster download failed (%s): %s", _poster_label(poster), safe_error_text(exc))
        return b"", "", safe_error_text(exc)


async def _attempt_poster(
    bot,
    chat_ref: Any,
    poster: str,
    caption: str,
    photo_kwargs: Dict[str, Any],
    delivery: Dict[str, Any],
) -> Any:
    """Try to send the poster photo. Returns the message or ``None``.

    The poster is an optional enhancement: every failure path returns ``None``
    so the caller can still deliver the text notification. FloodWait is the
    only exception that propagates (the retry queue keeps its cooldown).
    """
    if not await _poster_usable(poster):
        delivery["poster_status"] = "not_usable"
        delivery["poster_error"] = "poster URL failed validation"
        return None
    try:
        message = await bot.send_photo(
            chat_id=chat_ref, photo=poster, caption=caption, **photo_kwargs
        )
        delivery["poster_status"] = "sent"
        delivery["poster_error"] = ""
        return message
    except Exception as exc:
        if classify_telegram_error(exc) == "flood":
            raise
        delivery["poster_status"] = "failed"
        delivery["poster_error"] = safe_error_text(exc)
        logger.warning(
            "Poster URL send failed at Telegram stage (%s): %s",
            delivery.get("destination_type") or "notification",
            safe_error_text(exc),
        )
    data, filename, reason = await _poster_image(poster)
    if not data:
        delivery["poster_status"] = "download_failed"
        delivery["poster_error"] = safe_error_text(reason) or "poster download failed"
        logger.info(
            "Poster unavailable at download stage (%s): %s",
            _poster_label(poster),
            reason or "unknown reason",
        )
        return None
    try:
        buffer = io.BytesIO(data)
        buffer.name = filename or "poster.jpg"
        message = await bot.send_photo(
            chat_id=chat_ref, photo=buffer, caption=caption, **photo_kwargs
        )
        delivery["poster_status"] = "sent"
        delivery["poster_error"] = ""
        return message
    except Exception as exc:
        if classify_telegram_error(exc) == "flood":
            raise
        delivery["poster_status"] = "failed"
        delivery["poster_error"] = safe_error_text(exc)
        logger.warning(
            "Poster upload failed at Telegram stage (%s): %s",
            delivery.get("destination_type") or "notification",
            safe_error_text(exc),
        )
        return None


async def _deliver(bot, delivery: Dict[str, Any]) -> Any:
    from pyrogram import enums

    chat_ref = _chat_ref(delivery.get("chat_id"))
    markup = _build_markup(delivery)
    caption = str(delivery.get("caption") or "")
    # NOTE: send_photo() does not accept disable_web_page_preview; passing it
    # raised TypeError and silently forced every notification back to text.
    photo_kwargs = {
        "parse_mode": enums.ParseMode.HTML,
        "reply_markup": markup,
    }
    text_kwargs = {
        "parse_mode": enums.ParseMode.HTML,
        "reply_markup": markup,
        "disable_web_page_preview": True,
    }
    delivery["poster_status"] = ""
    delivery["poster_error"] = ""
    poster = delivery.get("poster") or ""
    # Telegram photo captions are limited to 1024 characters. Longer captions
    # are still delivered, as text, instead of failing the whole notification.
    if poster and len(caption) > 1024:
        logger.info("Caption too long for a photo caption; sending text instead")
        poster = ""
        delivery["poster_status"] = "caption_too_long"
    if poster:
        logger.info(
            "Sending %s notification photo to %s (poster=%s)",
            delivery.get("destination_type") or "notification",
            chat_ref,
            _poster_label(poster),
        )
        try:
            message = await asyncio.wait_for(
                _attempt_poster(bot, chat_ref, poster, caption, photo_kwargs, delivery),
                timeout=POSTER_ATTEMPT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            message = None
            delivery["poster_status"] = "timeout"
            delivery["poster_error"] = (
                f"poster attempt timed out after {POSTER_ATTEMPT_TIMEOUT}s"
            )
            logger.warning(
                "Poster attempt timed out after %ss (%s); falling back to text",
                POSTER_ATTEMPT_TIMEOUT,
                delivery.get("destination_type") or "notification",
            )
        if message is not None:
            return message
    else:
        delivery["poster_status"] = delivery.get("poster_status") or "no_poster"
    # Text delivery is independent of the poster outcome and always carries the
    # GET NOW button.
    return await bot.send_message(chat_id=chat_ref, text=caption, **text_kwargs)


async def process_deliveries(bot, limit: int = 20) -> int:
    handle = _database()
    if handle is None or bot is None:
        return 0
    settings = await get_settings()
    max_attempts = max(1, int(settings.get("max_delivery_attempts") or MAX_DELIVERY_ATTEMPTS))
    sent_or_failed = 0
    for _ in range(limit):
        now = _now()
        delivery = await handle[DELIVERIES_COLLECTION].find_one_and_update(
            {
                "status": {"$in": ["PENDING", "RETRY_PENDING"]},
                "next_retry_at": {"$lte": now},
            },
            {"$set": {"status": "PROCESSING", "updated_at": now}},
            sort=[("next_retry_at", 1)],
            return_document=True,
        )
        if not delivery:
            break
        attempts = int(delivery.get("attempts") or 0)
        try:
            # The hard timeout is a watchdog: if Telegram (or a photo upload)
            # stalls, this delivery is released and the worker moves on to the
            # next one instead of wedging the whole notification queue.
            message = await asyncio.wait_for(
                _deliver(bot, delivery), timeout=DELIVERY_ATTEMPT_TIMEOUT
            )
        except Exception as exc:
            timed_out = isinstance(exc, asyncio.TimeoutError)
            attempts += 1
            category = "transient" if timed_out else classify_telegram_error(exc)
            if timed_out:
                error_text = (
                    f"delivery attempt timed out after {DELIVERY_ATTEMPT_TIMEOUT}s"
                )
            else:
                error_text = safe_error_text(exc)
            if category == "flood":
                wait = 30 if timed_out else int(getattr(exc, "x", 30) or 30)
                status = "RETRY_PENDING"
                next_retry = _now() + timedelta(seconds=max(5, wait))
            elif category == "permanent" or attempts >= max_attempts:
                status = "FAILED"
                next_retry = _now()
            else:
                status = "RETRY_PENDING"
                next_retry = _now() + timedelta(seconds=retry_delay_seconds(attempts))
            await handle[DELIVERIES_COLLECTION].update_one(
                {"_id": delivery["_id"]},
                {
                    "$set": {
                        "status": status,
                        "attempts": attempts,
                        "last_error": error_text,
                        "poster_status": delivery.get("poster_status") or "",
                        "poster_error": delivery.get("poster_error") or "",
                        "next_retry_at": next_retry,
                        "updated_at": _now(),
                    }
                },
            )
            if status == "FAILED":
                logger.error(
                    "Notification delivery permanently failed (%s/%s): %s",
                    delivery.get("destination_type"),
                    delivery.get("delivery_id"),
                    error_text,
                )
            sent_or_failed += 1
            continue
        await handle[DELIVERIES_COLLECTION].update_one(
            {"_id": delivery["_id"]},
            {
                "$set": {
                    "status": "SENT",
                    "message_id": getattr(message, "id", None),
                    "sent_at": _now(),
                    "updated_at": _now(),
                    "last_error": "",
                    "poster_status": delivery.get("poster_status") or "",
                    "poster_error": delivery.get("poster_error") or "",
                }
            },
        )
        sent_or_failed += 1
    return sent_or_failed


async def recover_pending_work(stale_minutes: int = 10) -> None:
    handle = _database()
    if handle is None:
        return
    stale = _now() - timedelta(minutes=max(0, int(stale_minutes)))
    try:
        await handle[DELIVERIES_COLLECTION].update_many(
            {"status": "PROCESSING", "updated_at": {"$lt": stale}},
            {"$set": {"status": "RETRY_PENDING", "next_retry_at": _now()}},
        )
        await handle[EVENTS_COLLECTION].update_many(
            {"state": "PROCESSING", "processing_started_at": {"$lt": stale}},
            {"$set": {"state": "PENDING"}},
        )
        await handle[BATCHES_COLLECTION].update_many(
            {"state": "PROCESSING", "processing_started_at": {"$lt": stale}},
            {"$set": {"state": "OPEN", "window_end": _now()}},
        )
    except Exception:
        logger.exception("Feature 46 recovery failed")


async def process_once(bot) -> Dict[str, int]:
    batches = await process_due_batches(bot)
    events = await process_pending_events(bot)
    deliveries = await process_deliveries(bot)
    return {"batches": batches, "events": events, "deliveries": deliveries}


# ---------------------------------------------------------------------------
# Weekly digest
# ---------------------------------------------------------------------------
async def maybe_publish_weekly_digest(bot) -> Optional[str]:
    handle = _database()
    if handle is None or bot is None:
        return None
    settings = await get_settings(force=True)
    if not settings.get("digest_enabled"):
        return None
    tz = get_timezone(settings.get("timezone"))
    now_local = _now().astimezone(tz)
    scheduled = most_recent_sunday(now_local, parse_hhmm(settings.get("digest_time")))
    last_raw = settings.get("digest_last_published_at") or ""
    last = None
    if last_raw:
        try:
            last = datetime.fromisoformat(str(last_raw))
            if last.tzinfo is None:
                last = last.replace(tzinfo=dt_timezone.utc)
        except ValueError:
            last = None
    if last is None:
        if now_local - scheduled <= timedelta(hours=24):
            last = scheduled.astimezone(dt_timezone.utc) - timedelta(days=7)
        else:
            baseline = scheduled.astimezone(dt_timezone.utc)
            await save_settings(digest_last_published_at=baseline.isoformat())
            return None
    if scheduled <= last:
        return None

    period_start = last
    period_end = _now()
    period_key = scheduled.date().isoformat()
    digest_id = "dig_" + hashlib.sha256(period_key.encode()).hexdigest()[:20]
    existing = await handle[DIGESTS_COLLECTION].find_one({"digest_id": digest_id})
    if existing:
        await save_settings(digest_last_published_at=scheduled.isoformat())
        return digest_id

    cursor = handle[EVENTS_COLLECTION].find(
        {
            "indexed_at": {"$gte": period_start, "$lt": period_end},
            "state": {"$ne": "CANCELLED"},
        }
    ).sort("indexed_at", 1)
    events = [event async for event in cursor]
    caption = build_digest_caption(events, period_start, period_end, settings)
    pages = _with_page_numbers(paginate_text(caption, MAX_MESSAGE_LENGTH))
    payload = {
        "owner_id": digest_id,
        "kind": "digest",
        "captions": pages,
        "poster": "",
        "button_text": normalize_button_text(
            settings.get("digest_button_text"), "VIEW ALL UPLOADS"
        ),
        "button_url": _resolve_button_url(settings, "digest", bot),
    }
    summary = summarize_events(events)
    try:
        await handle[DIGESTS_COLLECTION].insert_one(
            {
                "digest_id": digest_id,
                "period_key": period_key,
                "period_start": period_start,
                "period_end": period_end,
                "page_count": len(pages),
                "summary": summary,
                "created_at": _now(),
                "published_at": None,
            }
        )
    except Exception:
        return digest_id
    await _create_deliveries(digest_id, payload, settings)
    await save_settings(digest_last_published_at=scheduled.isoformat())
    logger.info("Weekly digest queued for period %s (%s events)", period_key, len(events))
    return digest_id


async def force_publish_weekly_digest(bot, admin_id: Optional[int] = None) -> Optional[str]:
    """Admin-requested digest (an explicit resend is allowed)."""
    handle = _database()
    if handle is None or bot is None:
        return None
    settings = await get_settings(force=True)
    tz = get_timezone(settings.get("timezone"))
    now_local = _now().astimezone(tz)
    scheduled = most_recent_sunday(now_local, parse_hhmm(settings.get("digest_time")))
    period_end = _now()
    period_start = scheduled.astimezone(dt_timezone.utc)
    period_key = f"{scheduled.date().isoformat()}-resend-{int(period_end.timestamp())}"
    digest_id = "dig_" + hashlib.sha256(period_key.encode()).hexdigest()[:20]
    cursor = handle[EVENTS_COLLECTION].find(
        {
            "indexed_at": {"$gte": period_start, "$lt": period_end},
            "state": {"$ne": "CANCELLED"},
        }
    ).sort("indexed_at", 1)
    events = [event async for event in cursor]
    caption = build_digest_caption(events, period_start, period_end, settings)
    pages = _with_page_numbers(paginate_text(caption, MAX_MESSAGE_LENGTH))
    payload = {
        "owner_id": digest_id,
        "kind": "digest",
        "captions": pages,
        "poster": "",
        "button_text": normalize_button_text(
            settings.get("digest_button_text"), "VIEW ALL UPLOADS"
        ),
        "button_url": _resolve_button_url(settings, "digest", bot),
    }
    try:
        await handle[DIGESTS_COLLECTION].insert_one(
            {
                "digest_id": digest_id,
                "period_key": period_key,
                "period_start": period_start,
                "period_end": period_end,
                "page_count": len(pages),
                "summary": summarize_events(events),
                "created_at": _now(),
                "published_at": None,
                "requested_by": int(admin_id) if admin_id is not None else None,
            }
        )
    except Exception:
        return None
    await _create_deliveries(digest_id, payload, settings)
    return digest_id


async def notification_worker_loop(bot) -> None:
    await recover_pending_work()
    while True:
        try:
            await asyncio.wait_for(process_once(bot), timeout=WORKER_CYCLE_TIMEOUT)
            await asyncio.wait_for(
                maybe_publish_weekly_digest(bot), timeout=WORKER_CYCLE_TIMEOUT
            )
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            logger.error(
                "Feature 46 worker cycle exceeded %ss; releasing stalled work",
                WORKER_CYCLE_TIMEOUT,
            )
            await recover_pending_work(stale_minutes=0)
        except Exception:
            logger.exception("Feature 46 worker iteration failed")
        await asyncio.sleep(WORKER_INTERVAL)


async def start_notification_services(bot) -> None:
    global _worker_task
    await ensure_notification_indexes()
    settings = await get_settings(force=True)
    # Booleans only: confirms the running process actually read the configured
    # switches without leaking destination IDs or secrets into the logs.
    logger.info(
        "Feature 46 config: enabled=%s channel=%s group=%s poster=%s",
        bool(settings.get("enabled")),
        bool(settings.get("channel_enabled") and settings.get("channel_id")),
        bool(settings.get("group_enabled") and settings.get("group_id")),
        bool(settings.get("poster_enabled")),
    )
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(notification_worker_loop(bot))
    logger.info("Feature 46 notification worker started")


# ---------------------------------------------------------------------------
# Admin-facing helpers
# ---------------------------------------------------------------------------
async def check_destination(bot, chat_id: Any) -> Tuple[bool, str]:
    if bot is None:
        return False, "Bot client unavailable."
    ref = _chat_ref(chat_id)
    if ref is None:
        return False, "Destination is not configured."
    try:
        from pyrogram import enums

        chat = await bot.get_chat(ref)
        me = await bot.get_me()
        member = await bot.get_chat_member(ref, me.id)
        status = getattr(member, "status", None)
        if status not in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
            "administrator",
            "creator",
        ):
            return False, "Bot must be an administrator in this chat."
        privileges = getattr(member, "privileges", None)
        chat_type = getattr(chat, "type", None)
        if chat_type in (enums.ChatType.CHANNEL, "channel") and privileges is not None:
            if not getattr(privileges, "can_post_messages", True):
                return False, "Bot lacks permission to post messages in this channel."
        return True, f"OK: {getattr(chat, 'title', ref)}"
    except Exception as exc:
        return False, safe_error_text(exc)


async def send_test_notification(bot, fallback_chat_id: int) -> List[Tuple[str, bool, str]]:
    settings = await get_settings(force=True)
    from pyrogram import enums
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    label = normalize_button_text(settings.get("button_text"), "GET NOW")
    url = _resolve_button_url(settings, "movie", bot)
    markup = (
        InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])
        if validate_button_url(url)
        else None
    )
    text = "<b>🔔 TEST NOTIFICATION</b>\n\nFeature 46 auto upload notifications are configured."
    results: List[Tuple[str, bool, str]] = []
    targets = []
    for destination in ("channel", "group"):
        if settings.get(f"{destination}_enabled") and settings.get(f"{destination}_id"):
            targets.append((destination, _chat_ref(settings.get(f"{destination}_id"))))
    if not targets:
        targets.append(("admin", fallback_chat_id))
    for name, chat_ref in targets:
        try:
            await bot.send_message(
                chat_ref,
                text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
            results.append((name, True, "sent"))
        except Exception as exc:
            results.append((name, False, safe_error_text(exc)))
    return results


async def preview_notification(kind: str) -> str:
    settings = await get_settings(force=True)
    if kind == "series":
        events = [
            {
                "event_id": "preview",
                "category": "series",
                "title": "Example Series",
                "year": "2026",
                "season": 1,
                "episode": index,
                "episode_code": f"E{index:02d} S01",
                "quality": "1080p" if index % 2 else "720p",
                "language": "Hindi",
                "file_name": "Example.Series.S01E01.1080p.Hindi.mkv",
                "series_key": "example series",
            }
            for index in range(1, 6)
        ]
        return "\n\n---\n\n".join(build_series_captions(events, {}, settings))
    event = {
        "event_id": "preview",
        "category": "movie",
        "title": "Example Movie",
        "year": "2025",
        "quality": "1080p",
        "language": "Hindi",
        "file_name": "Example.Movie.2025.1080p.Hindi.mkv",
        "series_key": "example movie",
    }
    return build_movie_caption(event, {}, settings)


async def get_statistics() -> Dict[str, Any]:
    handle = _database()
    stats: Dict[str, Any] = {
        "events": 0,
        "movies": 0,
        "series_batches": 0,
        "episodes": 0,
        "channel_sent": 0,
        "group_sent": 0,
        "failed": 0,
        "pending": 0,
        "retries": 0,
        "digests": 0,
        "last_success": None,
    }
    if handle is None:
        return stats
    try:
        stats["events"] = await handle[EVENTS_COLLECTION].count_documents({})
        stats["movies"] = await handle[EVENTS_COLLECTION].count_documents({"category": "movie"})
        stats["series_batches"] = await handle[BATCHES_COLLECTION].count_documents(
            {"state": {"$in": ["READY", "FINALIZED"]}}
        )
        stats["episodes"] = await handle[EVENTS_COLLECTION].count_documents({"category": "series"})
        stats["channel_sent"] = await handle[DELIVERIES_COLLECTION].count_documents(
            {"destination_type": "channel", "status": "SENT"}
        )
        stats["group_sent"] = await handle[DELIVERIES_COLLECTION].count_documents(
            {"destination_type": "group", "status": "SENT"}
        )
        stats["failed"] = await handle[DELIVERIES_COLLECTION].count_documents({"status": "FAILED"})
        stats["pending"] = await handle[DELIVERIES_COLLECTION].count_documents(
            {"status": {"$in": ["PENDING", "RETRY_PENDING", "PROCESSING"]}}
        )
        stats["digests"] = await handle[DIGESTS_COLLECTION].count_documents({})
        async for delivery in handle[DELIVERIES_COLLECTION].find(
            {"status": "SENT", "attempts": {"$gt": 0}}, {"attempts": 1}
        ):
            stats["retries"] += int(delivery.get("attempts") or 0)
        last = await handle[DELIVERIES_COLLECTION].find_one(
            {"status": "SENT"}, sort=[("sent_at", -1)]
        )
        if last:
            stats["last_success"] = last.get("sent_at")
    except Exception:
        logger.exception("Failed to compute Feature 46 statistics")
    return stats


async def list_failed_notifications(limit: int = 10) -> List[Dict[str, Any]]:
    handle = _database()
    if handle is None:
        return []
    try:
        cursor = handle[DELIVERIES_COLLECTION].find({"status": "FAILED"}).sort(
            [("updated_at", -1)]
        ).limit(limit)
        return [item async for item in cursor]
    except Exception:
        return []


async def list_pending_notifications(limit: int = 10) -> List[Dict[str, Any]]:
    handle = _database()
    if handle is None:
        return []
    try:
        cursor = handle[DELIVERIES_COLLECTION].find(
            {"status": {"$in": ["PENDING", "RETRY_PENDING", "PROCESSING"]}}
        ).sort([("created_at", 1)]).limit(limit)
        return [item async for item in cursor]
    except Exception:
        return []


async def override_metadata(
    title: str,
    year: Any = "",
    rating: Any = "",
    genres: Any = "",
    poster: Any = "",
    plot: Any = "",
    imdb_id: Any = "",
    category: str = "movie",
) -> bool:
    """Admin manual correction, stored in the metadata cache for a long period."""
    handle = _database()
    if handle is None or not clean_metadata_value(title):
        return False
    category = "series" if str(category).lower() == "series" else "movie"
    cache_key = "|".join([category, series_key(title), str(year or "")])
    metadata = normalize_metadata(
        {
            "title": title,
            "year": year,
            "rating": rating,
            "genres": genres,
            "poster": poster,
            "plot": plot,
            "imdb_id": imdb_id,
        }
    )
    try:
        await handle[METADATA_COLLECTION].update_one(
            {"cache_key": cache_key},
            {
                "$set": {
                    "cache_key": cache_key,
                    "metadata": metadata,
                    "expires_at": _now() + timedelta(days=3650),
                    "updated_at": _now(),
                    "overridden": True,
                }
            },
            upsert=True,
        )
        return True
    except Exception:
        logger.exception("Failed to store metadata override")
        return False


async def retry_failed_notifications() -> int:
    handle = _database()
    if handle is None:
        return 0
    try:
        result = await handle[DELIVERIES_COLLECTION].update_many(
            {"status": "FAILED"},
            {
                "$set": {
                    "status": "PENDING",
                    "attempts": 0,
                    "last_error": "",
                    "next_retry_at": _now(),
                    "updated_at": _now(),
                }
            },
        )
        return int(getattr(result, "modified_count", 0) or 0)
    except Exception:
        return 0


async def get_recent_events(limit: int = 10) -> List[Dict[str, Any]]:
    handle = _database()
    if handle is None:
        return []
    try:
        cursor = handle[EVENTS_COLLECTION].find({}).sort([("indexed_at", -1)]).limit(limit)
        return [item async for item in cursor]
    except Exception:
        return []


async def get_digest_history(limit: int = 5) -> List[Dict[str, Any]]:
    handle = _database()
    if handle is None:
        return []
    try:
        cursor = handle[DIGESTS_COLLECTION].find({}).sort([("created_at", -1)]).limit(limit)
        return [item async for item in cursor]
    except Exception:
        return []


async def reset_templates(admin_id: Optional[int] = None) -> None:
    await save_settings(
        admin_id,
        movie_caption_template=DEFAULT_MOVIE_TEMPLATE,
        series_caption_template=DEFAULT_SERIES_TEMPLATE,
        digest_caption_template=DEFAULT_DIGEST_TEMPLATE,
        button_text="GET NOW",
        digest_button_text="VIEW ALL UPLOADS",
    )
