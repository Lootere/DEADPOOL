"""Keyless IMDb metadata provider used by Feature 46 notifications.

The long-standing ``utils.get_poster()`` helper scrapes IMDb through
Cinemagoer.  IMDb now serves the legacy search/reference pages to bots as an
empty document, so ``get_poster()`` returns ``None`` and notifications fall
back to file-name metadata only (title/year/quality).

This module keeps the same provider (IMDb) and adds a resilient path:

* title search via IMDb's public suggestion endpoint
* title details via IMDb's public GraphQL endpoint

Both endpoints are keyless.  Nothing is fabricated: every field is only
included when IMDb actually returned it.  All blocking I/O is exposed through
``asyncio.to_thread`` so callers never block the bot event loop.
"""
import asyncio
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

SUGGESTION_URL = "https://v3.sg.media-imdb.com/suggestion/x/{query}.json"
GRAPHQL_URL = "https://api.graphql.imdb.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
GRAPHQL_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/graphql+json, application/json",
    "User-Agent": USER_AGENT,
    "x-imdb-client-name": "imdb-web-next",
    "x-imdb-user-country": "US",
    "x-imdb-user-language": "en-US",
}
DEFAULT_TIMEOUT = 12
MAX_POSTER_BYTES = 10 * 1024 * 1024

SERIES_KINDS = {
    "tv series",
    "tv mini-series",
    "tv miniseries",
    "tvseries",
    "tvminiseries",
    "podcast series",
}
MOVIE_KINDS = {
    "feature",
    "movie",
    "tv movie",
    "tvmovie",
    "video",
    "short",
    "tv special",
    "tvspecial",
}

DETAILS_QUERY = """
query Feature46Title($id: ID!) {
  title(id: $id) {
    id
    titleText { text }
    originalTitleText { text }
    releaseYear { year }
    ratingsSummary { aggregateRating voteCount }
    genres { genres { text } }
    plot { plotText { plainText } }
    runtime { seconds }
    spokenLanguages { spokenLanguages { text } }
    primaryImage { url }
    titleType { id text }
  }
}
"""


class MetadataLookupError(RuntimeError):
    """Raised when the provider cannot be reached or returns unusable data."""


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if text.lower() in {"none", "null", "n/a", "na", "nan", "-", ""}:
        return ""
    return text


def _normalize_name(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _title_core(normalized: str) -> str:
    """Drop trailing/embedded year tokens so 'Akka 2026' matches 'Akka'."""
    tokens = [
        token
        for token in normalized.split()
        if not re.fullmatch(r"(18|19|20)\d{2}", token)
    ]
    return " ".join(tokens) or normalized


def _as_year(value: Any) -> Optional[int]:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _http_json(
    url: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=max(2, int(timeout))) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise MetadataLookupError(f"provider HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise MetadataLookupError(f"provider unreachable: {exc.reason}") from exc
    except Exception as exc:  # socket timeouts, TLS errors, ...
        raise MetadataLookupError(f"provider error: {exc}") from exc
    if not raw:
        raise MetadataLookupError("provider returned an empty response")
    try:
        parsed = json.loads(raw.decode("utf-8", "ignore"))
    except ValueError as exc:
        raise MetadataLookupError("provider returned malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise MetadataLookupError("provider returned an unexpected payload")
    return parsed


def _candidate_kind(entry: Dict[str, Any]) -> str:
    return _clean(entry.get("q") or entry.get("kind")).lower()


def _image_from_candidate(entry: Dict[str, Any]) -> str:
    image = entry.get("i")
    if isinstance(image, dict):
        url = _clean(image.get("imageUrl"))
        if url.startswith(("http://", "https://")):
            return url
    return ""


def search_titles(query: str, timeout: int = DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """Search IMDb titles. Raises MetadataLookupError on provider failure."""
    query = _clean(query)
    if not query:
        return []
    url = SUGGESTION_URL.format(query=urllib.parse.quote(query, safe=""))
    data = _http_json(url, timeout=timeout)
    results: List[Dict[str, Any]] = []
    for entry in data.get("d") or []:
        if not isinstance(entry, dict):
            continue
        title_id = _clean(entry.get("id"))
        if not title_id.startswith("tt"):
            continue
        results.append(
            {
                "imdb_id": title_id,
                "title": _clean(entry.get("l")),
                "year": _as_year(entry.get("y")),
                "kind": _candidate_kind(entry),
                "poster": _image_from_candidate(entry),
                "rank": int(entry.get("rank") or 0),
            }
        )
    return results


def select_best_match(
    candidates: List[Dict[str, Any]],
    title: str,
    year: Any = None,
    category: str = "movie",
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Pick a confident title match. Returns ``(candidate, reason)``.

    Ambiguous or weak matches are rejected instead of publishing wrong data.
    """
    wanted = _normalize_name(title)
    wanted_core = _title_core(wanted)
    wanted_year = _as_year(year)
    category = "series" if str(category).lower() == "series" else "movie"
    if not wanted:
        return None, "empty title"

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for candidate in candidates or []:
        if not _clean(candidate.get("imdb_id")).startswith("tt"):
            continue
        kind = _clean(candidate.get("kind")).lower()
        if category == "series":
            if kind and kind not in SERIES_KINDS:
                continue
        else:
            if kind and kind not in MOVIE_KINDS:
                continue

        candidate_title = _normalize_name(candidate.get("title"))
        if not candidate_title:
            continue
        candidate_core = _title_core(candidate_title)
        if candidate_core == wanted_core:
            title_score = 1.0
        else:
            wanted_tokens = set(wanted_core.split())
            candidate_tokens = set(candidate_core.split())
            union = wanted_tokens | candidate_tokens
            overlap = len(wanted_tokens & candidate_tokens) / len(union) if union else 0.0
            if overlap < 0.8:
                continue
            title_score = 0.5 + (overlap * 0.4)

        candidate_year = _as_year(candidate.get("year"))
        if wanted_year and candidate_year:
            difference = abs(wanted_year - candidate_year)
            if difference > 1:
                continue
            year_score = 1.0 if difference == 0 else 0.6
        elif wanted_year and not candidate_year:
            year_score = 0.3
        else:
            year_score = 0.5

        kind_score = 1.0 if kind else 0.7
        score = round((title_score * 0.65) + (year_score * 0.25) + (kind_score * 0.10), 4)
        scored.append((score, candidate))

    if not scored:
        return None, "no confident match"
    scored.sort(key=lambda item: (-item[0], -int(item[1].get("rank") or 0)))
    best_score, best = scored[0]
    if best_score < 0.70:
        return None, "low confidence match"
    if len(scored) > 1:
        runner_up_score, runner_up = scored[1]
        if (
            abs(runner_up_score - best_score) < 1e-4
            and runner_up.get("imdb_id") != best.get("imdb_id")
        ):
            return None, "ambiguous match"
    return best, ""


def _format_runtime(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _format_rating(value: Any) -> str:
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return ""
    if rating <= 0:
        return ""
    return f"{rating:.1f}"


def metadata_from_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an IMDb GraphQL ``title`` node into the notification shape."""
    if not isinstance(node, dict):
        return {}
    title = _clean((node.get("titleText") or {}).get("text")) or _clean(
        (node.get("originalTitleText") or {}).get("text")
    )
    year = _clean((node.get("releaseYear") or {}).get("year"))
    rating = _format_rating((node.get("ratingsSummary") or {}).get("aggregateRating"))
    genres = ", ".join(
        _clean(genre.get("text"))
        for genre in ((node.get("genres") or {}).get("genres") or [])
        if _clean(genre.get("text"))
    )
    plot = _clean(((node.get("plot") or {}).get("plotText") or {}).get("plainText"))
    languages = ", ".join(
        _clean(language.get("text"))
        for language in (
            (node.get("spokenLanguages") or {}).get("spokenLanguages") or []
        )
        if _clean(language.get("text"))
    )
    poster = _clean((node.get("primaryImage") or {}).get("url"))
    if poster and not poster.startswith(("http://", "https://")):
        poster = ""
    runtime = _format_runtime((node.get("runtime") or {}).get("seconds"))
    title_type = node.get("titleType") or {}
    kind = _clean(title_type.get("id")) or _clean(title_type.get("text"))
    imdb_id = _clean(node.get("id"))

    metadata: Dict[str, Any] = {}
    for key, value in (
        ("title", title),
        ("year", year),
        ("rating", rating),
        ("genres", genres),
        ("plot", plot[:600]),
        ("poster", poster),
        ("imdb_id", imdb_id),
        ("languages", languages),
        ("runtime", runtime),
        ("kind", kind),
    ):
        if value:
            metadata[key] = value
    return metadata


def fetch_metadata(imdb_id: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    imdb_id = _clean(imdb_id)
    if not imdb_id.startswith("tt"):
        return {}
    data = _http_json(
        GRAPHQL_URL,
        payload={"query": DETAILS_QUERY, "variables": {"id": imdb_id}},
        timeout=timeout,
        headers=GRAPHQL_HEADERS,
    )
    if data.get("errors"):
        raise MetadataLookupError("provider returned a GraphQL error")
    node = (data.get("data") or {}).get("title")
    return metadata_from_node(node) if isinstance(node, dict) else {}


def lookup_sync(
    title: str,
    year: Any = None,
    category: str = "movie",
    imdb_id: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> Tuple[Dict[str, Any], str]:
    """Blocking lookup. Returns ``(metadata, failure_reason)``."""
    category = "series" if str(category).lower() == "series" else "movie"
    if _clean(imdb_id).startswith("tt"):
        try:
            metadata = fetch_metadata(imdb_id, timeout=timeout)
        except MetadataLookupError as exc:
            return {}, str(exc)
        if not metadata:
            return {}, "no details for IMDb id"
        return metadata, ""

    query = _clean(" ".join(filter(None, [str(title or ""), str(_as_year(year) or "")])))
    try:
        candidates = search_titles(query, timeout=timeout)
    except MetadataLookupError as exc:
        return {}, str(exc)
    if not candidates:
        return {}, "no search results"

    match, reason = select_best_match(candidates, title, year, category)
    if not match:
        return {}, reason or "no confident match"
    try:
        metadata = fetch_metadata(match["imdb_id"], timeout=timeout)
    except MetadataLookupError as exc:
        return {}, str(exc)
    if not metadata:
        return {}, "no details for matched title"

    # Never return metadata for a different title/type than the one requested.
    provider_title = _title_core(_normalize_name(metadata.get("title")))
    if provider_title and provider_title != _title_core(_normalize_name(match.get("title"))):
        return {}, "provider title mismatch"
    kind = _clean(metadata.get("kind")).lower()
    if category == "series" and kind and "series" not in kind:
        return {}, "matched title is not a series"
    if category != "series" and kind and "series" in kind:
        return {}, "matched title is a series"

    # The suggestion image is a safe fallback when GraphQL omits primaryImage.
    if not metadata.get("poster") and match.get("poster"):
        metadata["poster"] = match["poster"]
    return metadata, ""


async def lookup(
    title: str,
    year: Any = None,
    category: str = "movie",
    imdb_id: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> Tuple[Dict[str, Any], str]:
    """Async wrapper with a hard timeout. Returns ``(metadata, reason)``."""
    timeout = max(3, int(timeout or DEFAULT_TIMEOUT))
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(lookup_sync, title, year, category, imdb_id, timeout),
            timeout=timeout + 1,
        )
    except asyncio.TimeoutError:
        return {}, "metadata provider timeout"
    except MetadataLookupError as exc:
        return {}, str(exc)
    except Exception as exc:  # defensive: never break notification processing
        return {}, f"metadata lookup failed: {exc}"


def _poster_check_sync(url: str, timeout: int = 5) -> Tuple[bool, str]:
    if not str(url or "").startswith(("http://", "https://")):
        return False, "invalid poster URL"
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=max(2, int(timeout))) as response:
            content_type = (response.headers.get_content_type() or "").lower()
            length = response.headers.get("Content-Length")
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 410}:
            return False, f"poster HTTP {exc.code}"
        # 403/405 etc. are inconclusive: let Telegram make the final call.
        return True, ""
    except Exception:
        return True, ""
    if content_type and not content_type.startswith("image/"):
        return False, f"poster is not an image ({content_type})"
    if length:
        try:
            if int(length) > MAX_POSTER_BYTES:
                return False, "poster exceeds Telegram photo limit"
        except ValueError:
            pass
    return True, ""


async def poster_is_usable(url: str, timeout: int = 5) -> Tuple[bool, str]:
    """Cheap validation so a broken poster never blocks the notification."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_poster_check_sync, url, timeout), timeout=timeout + 1
        )
    except Exception:
        # Inconclusive validation must not drop an otherwise valid poster.
        return True, ""


# ---------------------------------------------------------------------------
# Poster bytes: download + validate before re-uploading through Telegram.
# Telegram cannot always fetch a third-party image URL, so a failed URL send
# is retried with the validated image bytes instead of dropping the poster.
# ---------------------------------------------------------------------------
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg", "poster.jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "poster.png"),
    (b"GIF87a", "image/gif", "poster.gif"),
    (b"GIF89a", "image/gif", "poster.gif"),
)


def sniff_image_type(data: bytes) -> Tuple[str, str]:
    """Return ``(mime, filename)`` for a supported image, else ``("", "")``."""
    if not data:
        return "", ""
    for signature, mime, filename in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return mime, filename
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "poster.webp"
    return "", ""


def _image_size(data: bytes) -> Tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:
        return 0, 0


def validate_poster_bytes(data: bytes, content_type: str = "") -> Tuple[bool, str]:
    """Reject HTML error pages, oversized payloads and non-image bytes."""
    if not data:
        return False, "poster download returned no data"
    if len(data) > MAX_POSTER_BYTES:
        return False, "poster exceeds Telegram photo limit"
    declared = str(content_type or "").split(";")[0].strip().lower()
    if declared and not declared.startswith("image/"):
        return False, f"poster is not an image ({declared})"
    mime, _ = sniff_image_type(data)
    if not mime:
        return False, "poster bytes are not a supported image"
    width, height = _image_size(data)
    if width and height:
        if width <= 0 or height <= 0:
            return False, "poster has invalid dimensions"
        if width > 12000 or height > 12000:
            return False, "poster dimensions are too large"
    return True, ""


def _prepare_poster_bytes(data: bytes) -> Tuple[bytes, str]:
    """Return bytes Telegram accepts, converting uncommon formats to JPEG."""
    mime, filename = sniff_image_type(data)
    if mime in {"image/jpeg", "image/png"}:
        return data, filename
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            converted = image.convert("RGB")
            buffer = io.BytesIO()
            converted.save(buffer, format="JPEG", quality=90)
            return buffer.getvalue(), "poster.jpg"
    except Exception:
        return data, filename or "poster.jpg"


def _fetch_poster_bytes_sync(
    url: str, timeout: int = 10
) -> Tuple[bytes, str, str]:
    """Download a poster URL. Returns ``(data, filename, failure_reason)``."""
    if not str(url or "").startswith(("http://", "https://")):
        return b"", "", "invalid poster URL"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=max(2, int(timeout))) as response:
            status = getattr(response, "status", 200)
            content_type = response.headers.get_content_type() or ""
            declared_length = response.headers.get("Content-Length")
            if status and int(status) >= 400:
                return b"", "", f"poster HTTP {status}"
            if declared_length:
                try:
                    if int(declared_length) > MAX_POSTER_BYTES:
                        return b"", "", "poster exceeds Telegram photo limit"
                except ValueError:
                    pass
            data = response.read(MAX_POSTER_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return b"", "", f"poster HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return b"", "", f"poster unreachable: {exc.reason}"
    except Exception as exc:  # socket timeouts, TLS errors, ...
        return b"", "", f"poster download error: {exc}"
    usable, reason = validate_poster_bytes(data, content_type)
    if not usable:
        return b"", "", reason
    prepared, filename = _prepare_poster_bytes(data)
    return prepared, filename, ""


async def fetch_poster_bytes(url: str, timeout: int = 10) -> Tuple[bytes, str, str]:
    """Async wrapper around the poster download/validation helper."""
    timeout = max(3, int(timeout or 10))
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_poster_bytes_sync, url, timeout), timeout=timeout + 1
        )
    except asyncio.TimeoutError:
        return b"", "", "poster download timeout"
    except Exception as exc:
        return b"", "", f"poster download error: {exc}"
