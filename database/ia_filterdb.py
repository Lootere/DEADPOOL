# This code has been modified by @Looteredev
# Please do not remove this credit
import logging
from struct import pack
import re
import base64
import copy
from collections.abc import Mapping
from collections import OrderedDict
from difflib import SequenceMatcher
from time import monotonic
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import (
    DATABASE_URI, DATABASE_NAME, COLLECTION_NAME, USE_CAPTION_FILTER, MAX_B_TN,
    DATABASE_URI2, DATABASE_URI3, DATABASE_URI4, DATABASE_URI5, MULTIPLE_DATABASES,
    MULTIDB_STORAGE_THRESHOLD, MULTIDB_QUOTA_MB,
)
from utils import get_settings, save_group_settings
from fuzzywuzzy import process
from Script import script

# Set up logging
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SEARCH_RESULTS_CACHE = OrderedDict()
SEARCH_RESULTS_CACHE_TTL = 60
SEARCH_RESULTS_CACHE_MAX_ENTRIES = 256
SEARCH_RESULTS_CACHE_GENERATION = 0

QUALITY_SORT_PATTERNS = (
    (6, r"(?:^|[\s._+\-])(?:2160\s*p|4\s*k|uhd)(?=$|[\s._+\-])"),
    (5, r"(?:^|[\s._+\-])1440\s*p(?=$|[\s._+\-])"),
    (4, r"(?:^|[\s._+\-])1080\s*p(?=$|[\s._+\-])"),
    (3, r"(?:^|[\s._+\-])720\s*p(?=$|[\s._+\-])"),
    (2, r"(?:^|[\s._+\-])480\s*p(?=$|[\s._+\-])"),
)
LANGUAGE_SORT_PATTERNS = (
    (1, r"(?:^|[\s._+\-])dual[\s._+\-]*audio(?=$|[\s._+\-])"),
    (2, r"(?:^|[\s._+\-])(?:eng|english)(?=$|[\s._+\-])"),
    (3, r"(?:^|[\s._+\-])(?:guj|gujarati)(?=$|[\s._+\-])"),
    (4, r"(?:^|[\s._+\-])(?:hin|hindi)(?=$|[\s._+\-])"),
    (5, r"(?:^|[\s._+\-])(?:kan|kannada)(?=$|[\s._+\-])"),
    (6, r"(?:^|[\s._+\-])(?:mal|malayalam)(?=$|[\s._+\-])"),
    (7, r"(?:^|[\s._+\-])(?:mar|marathi)(?=$|[\s._+\-])"),
    (8, r"(?:^|[\s._+\-])multi[\s._+\-]*audio(?=$|[\s._+\-])"),
    (9, r"(?:^|[\s._+\-])(?:pun|punjabi)(?=$|[\s._+\-])"),
    (10, r"(?:^|[\s._+\-])(?:tam|tamil)(?=$|[\s._+\-])"),
    (11, r"(?:^|[\s._+\-])(?:tel|telugu)(?=$|[\s._+\-])"),
)


def clear_search_results_cache():
    global SEARCH_RESULTS_CACHE_GENERATION
    SEARCH_RESULTS_CACHE.clear()
    SEARCH_RESULTS_CACHE_GENERATION += 1


def _search_results_cache_key(query, file_type, max_results, offset, sort_by, filters):
    normalized_filters = tuple(sorted(
        (str(name).casefold(), str(value).strip().casefold())
        for name, value in (filters or {}).items()
    ))
    return (
        SEARCH_RESULTS_CACHE_GENERATION,
        query.casefold(),
        file_type,
        max_results,
        offset,
        sort_by,
        normalized_filters,
    )


def _get_cached_search_results(key):
    entry = SEARCH_RESULTS_CACHE.get(key)
    if entry is None:
        return None
    expires_at, results = entry
    if monotonic() >= expires_at:
        SEARCH_RESULTS_CACHE.pop(key, None)
        return None
    SEARCH_RESULTS_CACHE.move_to_end(key)
    return copy.deepcopy(results)


def _cache_search_results(key, results):
    SEARCH_RESULTS_CACHE[key] = (
        monotonic() + SEARCH_RESULTS_CACHE_TTL,
        copy.deepcopy(results),
    )
    SEARCH_RESULTS_CACHE.move_to_end(key)
    while len(SEARCH_RESULTS_CACHE) > SEARCH_RESULTS_CACHE_MAX_ENTRIES:
        SEARCH_RESULTS_CACHE.popitem(last=False)


def _clean_display_file_name(file_name):
    """Clean common promotional prefixes for display without changing stored names."""
    if not file_name:
        return ""
    text = str(file_name)
    metadata = re.compile(
        r"(?i)\b(?:s\d+\s*e\d+|season\s*\d+|episode\s*\d+|\d{3,4}p|4k|8k|"
        r"hdr|hevc|x264|x265|hindi|english|tamil|telugu|malayalam|kannada|"
        r"dual\s*audio|multi\s*audio|20\d{2})\b"
    )
    while True:
        prefix = re.match(r"\s*[\[\(\{]([^\]\)\}]+)[\]\)\}]\s*[-_. ]*", text)
        if not prefix or metadata.search(prefix.group(1)):
            break
        text = text[prefix.end():]
    text = re.sub(r"^\s*@[\w.]+\s*[-_.:]*\s*", "", text)
    text = re.sub(
        r"(?i)^\s*[\w.-]*(?:team|group|channel|uploads?|releases?)\s*[-_.:]+\s*",
        "",
        text,
    )
    text = re.sub(r"[_\.+]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ._+-")
    return text or str(file_name)


def _season_sort_key(file_name):
    """Sort season packs first, then episode numbers naturally."""
    text = _clean_display_file_name(file_name).lower()
    combined_episode = re.search(r"\bs0*(\d+)\s*e0*(\d+)\b", text)
    season_match = re.search(r"\b(?:season|s)\s*0*(\d+)\b", text)
    episode_match = re.search(r"\b(?:episode|ep|e)\s*0*(\d+)\b", text)
    if combined_episode:
        season = int(combined_episode.group(1))
        episode = int(combined_episode.group(2))
        is_season_pack = 1
    else:
        season = int(season_match.group(1)) if season_match else 9999
        episode = int(episode_match.group(1)) if episode_match else 9999
        is_season_pack = 0 if season_match and not episode_match else 1
    return (is_season_pack, season, episode, text)


def _metadata_sort_expression(patterns, default_rank):
    return {
        "$switch": {
            "branches": [
                {
                    "case": {
                        "$regexMatch": {
                            "input": {"$ifNull": ["$file_name", ""]},
                            "regex": pattern,
                            "options": "i",
                        }
                    },
                    "then": rank,
                }
                for rank, pattern in patterns
            ],
            "default": default_rank,
        }
    }


def _search_term_pattern(term):
    """Match common filename spellings for episode, language, and resolution filters."""
    episode = re.fullmatch(r"(?:e|ep|episode)0*(\d+)", term, flags=re.IGNORECASE)
    if episode:
        number = int(episode.group(1))
        return (
            r"(?:e0*{0}|ep0*{0}|episode\s*0*{0}|s\d+[\s._+-]*e0*{0})"
        ).format(number)

    language_aliases = {
        "eng": ("eng", "english"),
        "hin": ("hin", "hindi"),
        "tam": ("tam", "tamil"),
        "tel": ("tel", "telugu"),
        "kan": ("kan", "kannada"),
        "mal": ("mal", "malayalam"),
        "guj": ("guj", "gujarati"),
        "mar": ("mar", "marathi"),
        "pun": ("pun", "punjabi"),
    }
    aliases = language_aliases.get(term.lower())
    if aliases:
        return r"(?:{})".format("|".join(re.escape(alias) for alias in aliases))

    if term.lower() in ("2160p", "4k", "uhd"):
        return r"(?:2160\s*p|4\s*k|uhd)"

    return re.escape(term)


def _filter_term_pattern(filter_name, value):
    value = str(value).strip().lower()
    token_start = r"(?:^|[\s._+\-])"
    token_end = r"(?=$|[\s._+\-])"
    if filter_name == "language":
        language_aliases = {
            "eng": ("eng", "english"),
            "hin": ("hin", "hindi"),
            "tam": ("tam", "tamil"),
            "tel": ("tel", "telugu"),
            "kan": ("kan", "kannada"),
            "mal": ("mal", "malayalam"),
            "guj": ("guj", "gujarati"),
            "mar": ("mar", "marathi"),
            "pun": ("pun", "punjabi"),
            "multi": ("multi audio", "multiaudio"),
            "dual": ("dual audio", "dualaudio"),
        }
        aliases = language_aliases.get(value, (value,))
        alternatives = "|".join(
            re.escape(alias).replace(r"\ ", r"[\s._+\-]*")
            for alias in aliases
        )
        return token_start + r"(?:" + alternatives + r")" + token_end

    if filter_name == "quality":
        quality_patterns = {
            "480p": r"480\s*p",
            "720p": r"720\s*p",
            "1080p": r"1080\s*p",
            "1080p hq": r"1080\s*p[\s._+\-]*hq",
            "1440p": r"1440\s*p",
            "2160p": r"(?:2160\s*p|4\s*k|uhd)",
            "4k": r"(?:2160\s*p|4\s*k|uhd)",
        }
        pattern = quality_patterns.get(value, re.escape(value))
        return token_start + r"(?:" + pattern + r")" + token_end

    if filter_name == "season":
        season = re.fullmatch(r"s0*(\d+)", value)
        if season:
            number = int(season.group(1))
            return token_start + rf"(?:s0*{number}(?=[\s._+\-]*e)|season[\s._+\-]*0*{number})"

    if filter_name == "episode":
        return token_start + _search_term_pattern(value) + token_end

    if filter_name == "year" and re.fullmatch(r"(?:19[5-9]\d|20[0-2]\d|2030)", value):
        return rf"(?<!\d){re.escape(value)}(?!\d)"

    raise ValueError(f"Unsupported search filter: {filter_name}")


def _build_search_filter(query, file_type=None, filters=None):
    terms = query.split()
    search_fields = ["file_name", "caption"] if USE_CAPTION_FILTER else ["file_name"]

    def searchable_pattern(pattern):
        if len(search_fields) == 1:
            return {search_fields[0]: pattern}
        return {"$or": [{field: pattern} for field in search_fields]}

    query_conditions = []
    for term in terms:
        raw_pattern = (
            r"(?:^|[\s\.\+\-_])"
            + _search_term_pattern(term)
            + r"(?=$|[\s\.\+\-_])"
        )
        query_conditions.append(
            searchable_pattern(re.compile(raw_pattern, flags=re.IGNORECASE))
        )
    for filter_name, value in (filters or {}).items():
        pattern = re.compile(
            _filter_term_pattern(filter_name, value), flags=re.IGNORECASE
        )
        query_conditions.append(searchable_pattern(pattern))

    mongo_filter = (
        {"$and": query_conditions}
        if len(query_conditions) > 1
        else query_conditions[0]
    )
    if file_type:
        mongo_filter["file_type"] = file_type
    return mongo_filter


def _suggestion_title(file_name):
    title = _clean_display_file_name(file_name)
    title = re.sub(r"\.(?:mkv|mp4|avi|mov|webm)$", "", title, flags=re.IGNORECASE)
    metadata = re.compile(
        r"(?i)(?:\b(?:s\d{1,2}\s*e\d{1,3}|season\s*\d+|episode\s*\d+|"
        r"\d{3,4}\s*p|4\s*k|8\s*k|hdrip|brrip|webrip|web[\s._-]*dl|"
        r"blu[\s._-]*ray|hdtv|dvdrip|x26[45]|h\.?26[45]|hevc|avc|"
        r"hindi|english|tamil|telugu|kannada|malayalam|gujarati|marathi|"
        r"punjabi|multi[\s._-]*audio|dual[\s._-]*audio|aac|ddp\d*|"
        r"ac3|dts|esub|subtitles?)\b|(?<!\d)(?:19|20)\d{2}(?!\d))"
    )
    match = metadata.search(title)
    if match:
        title = title[:match.start()]
    title = re.sub(r"[\s._+\-]+", " ", title).strip(" ()[]{}")
    return title or _clean_display_file_name(file_name)


def extract_series_episode(file_name):
    match = re.search(
        r"\bS(?P<s_season>\d{1,2})[\s._-]*E(?P<s_episode>\d{1,3})\b"
        r"|\b(?P<x_season>\d{1,2})\s*[xX]\s*(?P<x_episode>\d{1,3})\b"
        r"|\bSeason\s*(?P<w_season>\d{1,2})[\s._-]*"
        r"(?:Episode|Ep|E)\s*(?P<w_episode>\d{1,3})\b",
        str(file_name or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    season = next(
        int(match.group(name))
        for name in ("s_season", "x_season", "w_season")
        if match.group(name) is not None
    )
    episode = next(
        int(match.group(name))
        for name in ("s_episode", "x_episode", "w_episode")
        if match.group(name) is not None
    )
    series_name = _suggestion_title(str(file_name)[:match.start()])
    if not series_name:
        return None
    return {
        "title": series_name,
        "season": season,
        "episode": episode,
        "episode_key": f"s{season:02d}e{episode:02d}",
    }


def _normalized_suggestion_text(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def _suggestion_similarity(query, title):
    query_text = _normalized_suggestion_text(query)
    title_text = _normalized_suggestion_text(title)
    if not query_text or not title_text:
        return 0

    query_compact = query_text.replace(" ", "")
    title_compact = title_text.replace(" ", "")
    ratio = SequenceMatcher(None, query_compact, title_compact).ratio()
    if len(query_compact) <= len(title_compact):
        shorter, longer = query_compact, title_compact
    else:
        shorter, longer = title_compact, query_compact
    min_window = max(1, len(shorter) - 2)
    max_window = min(len(longer), len(shorter) + 2)
    partial = max(
        (
            SequenceMatcher(
                None,
                shorter,
                longer[start:start + window_length],
            ).ratio()
            for window_length in range(min_window, max_window + 1)
            for start in range(len(longer) - window_length + 1)
        ),
        default=0,
    )
    token_ratio = SequenceMatcher(
        None,
        " ".join(sorted(query_text.split())),
        " ".join(sorted(title_text.split())),
    ).ratio()
    combined_word_score = 0
    numeric_title_query = re.fullmatch(r"([a-z]+)(\d+)", query_compact)
    if numeric_title_query:
        title_tokens = set(title_text.split())
        if (
            numeric_title_query.group(1) in title_tokens
            and numeric_title_query.group(2) in title_tokens
        ):
            combined_word_score = 0.9
    return round(
        100 * max(ratio, partial * 0.92, token_ratio, combined_word_score)
    )


async def get_search_suggestions(query, limit=8, candidate_limit=500, min_score=65):
    """Return bounded, fuzzy-ranked title suggestions from indexed filenames."""
    normalized_query = _normalized_suggestion_text(query)
    first_token = normalized_query.split(" ")[0] if normalized_query else ""
    if len(first_token) < 2:
        return []

    def case_insensitive_character(character):
        if character.isalpha():
            return f"[{character.lower()}{character.upper()}]"
        return re.escape(character)

    indexed_prefix = re.compile(
        "^"
        + case_insensitive_character(first_token[0])
        + r".{0,2}"
        + case_insensitive_character(first_token[1])
    )
    logger.info(
        "Indexed title suggestion search started (collection=%s, query=%r, limit=%s)",
        COLLECTION_NAME,
        normalized_query,
        candidate_limit,
    )

    async def get_ranked_titles(pattern):
        cursor = Media.find({"file_name": pattern})
        cursor.sort("file_name", 1).limit(candidate_limit)
        candidate_documents = await cursor.to_list(length=candidate_limit)

        titles = {}
        for document in candidate_documents:
            file_name = (
                document.get("file_name")
                if isinstance(document, Mapping)
                else getattr(document, "file_name", None)
            )
            title = _suggestion_title(file_name)
            normalized_title = _normalized_suggestion_text(title)
            if not normalized_title:
                continue
            score = _suggestion_similarity(normalized_query, title)
            if normalized_title not in titles or score > titles[normalized_title]["score"]:
                titles[normalized_title] = {"title": title, "score": score}

        ranked_titles = sorted(
            (
                suggestion
                for suggestion in titles.values()
                if suggestion["score"] >= min_score
            ),
            key=lambda suggestion: suggestion["score"],
            reverse=True,
        )[:limit]
        return candidate_documents, ranked_titles

    documents, suggestions = await get_ranked_titles(indexed_prefix)
    if not suggestions:
        token_prefix = re.compile(
            r"(?:^|[\s._+\-])"
            + re.escape(first_token[0])
            + r".{0,2}"
            + re.escape(first_token[1]),
            flags=re.IGNORECASE,
        )
        documents, suggestions = await get_ranked_titles(token_prefix)

    logger.info(
        "Indexed title suggestion search completed (collection=%s, query=%r, candidates=%s, suggestions=%s)",
        COLLECTION_NAME,
        normalized_query,
        len(documents),
        len(suggestions),
    )
    return suggestions


client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

@instance.register
class Media(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)

    class Meta:
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME


# Feature 3: Multi-MongoDB Storage Manager Adapter Initialization
from Lootere.utils.multidb_manager import multi_db_manager, MultiDBMediaDocument, mask_mongo_uri

_secondary_uris = []
for _u in (DATABASE_URI2, DATABASE_URI3, DATABASE_URI4, DATABASE_URI5):
    if _u and _u.strip():
        _secondary_uris.append(_u.strip())
if MULTIPLE_DATABASES:
    for _u in re.split(r'[,;\s]+', MULTIPLE_DATABASES.strip()):
        if _u and _u.strip() and _u.strip() not in _secondary_uris and _u.strip() != DATABASE_URI:
            _secondary_uris.append(_u.strip())

multi_db_manager.initialize(
    primary_uri=DATABASE_URI,
    primary_db_name=DATABASE_NAME,
    primary_collection_name=COLLECTION_NAME,
    primary_client=client,
    secondary_uris=_secondary_uris,
    threshold_percent=MULTIDB_STORAGE_THRESHOLD,
    quota_mb=MULTIDB_QUOTA_MB,
)


async def save_file(media):
    """Save file in database with Multi-MongoDB support and legacy single-DB compatibility."""
    if multi_db_manager.has_multiple_active_dbs():
        check_dup_fn = None
        try:
            from Lootere.utils.duplicate_cleaner import should_auto_skip_exact_duplicate
            check_dup_fn = should_auto_skip_exact_duplicate
        except Exception:
            pass
        success, fid = await multi_db_manager.save_media_file(
            media,
            unpack_fn=unpack_new_file_id,
            clean_name_fn=lambda name: re.sub(r"(_|\-|\.|\+)", " ", str(name)),
            check_dup_fn=check_dup_fn,
        )
        if success:
            clear_search_results_cache()
        return success, fid

    # Legacy Single DB write (100% untouched)
    file_id, file_ref = unpack_new_file_id(media.file_id)
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))

    try:
        from Lootere.utils.duplicate_cleaner import should_auto_skip_exact_duplicate
        should_skip, existing_id = await should_auto_skip_exact_duplicate(file_name, media.file_size)
        if should_skip:
            logger.info(f'{getattr(media, "file_name", "NO_FILE")} is already saved in database')
            return False, existing_id
    except Exception:
        pass

    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
        )
    except ValidationError:
        logger.exception('Error occurred while saving file in database')
        return False, None
    else:
        try:
            await file.commit()
        except DuplicateKeyError:      
            logger.warning(
                f'{getattr(media, "file_name", "NO_FILE")} is already saved in database'
            )

            return False, file_id
        else:
            logger.info(f'{getattr(media, "file_name", "NO_FILE")} is saved to database')
            clear_search_results_cache()
            return True, file_id



async def get_search_results(
    chat_id,
    query,
    file_type=None,
    max_results=10,
    offset=0,
    filter=False,
    sort_by="season",
    filters=None,
):
    """For given query return (results, next_offset)"""
    sort_fields = {
        "season": ("$natural", -1),
        "recent": ("$natural", -1),
        "title": ("file_name", 1),
        "size": ("file_size", -1),
        "size_asc": ("file_size", 1),
        "quality": None,
        "language": None,
    }
    if sort_by not in sort_fields:
        raise ValueError(f"Unsupported search sort option: {sort_by}")
    query = re.sub(r"[\s._+\-]+", " ", str(query or "")).strip()
    logger.info(
        "Media search started (collection=%s, chat_id=%s, query=%r, offset=%s, sort=%s)",
        COLLECTION_NAME,
        chat_id,
        query,
        offset,
        sort_by,
    )
    if not query:
        logger.info(
            "Media search completed (collection=%s, query=%r, matched=0, retrieved=0)",
            COLLECTION_NAME,
            query,
        )
        return [], "", 0
    operation = "preparing search"
    try:
        banned_words = script.BLACKLIST
        if chat_id is not None:
            operation = "loading chat settings"
            settings = await get_settings(int(chat_id))
            try:
                if settings['max_btn']:
                    max_results = 10
                else:
                    max_results = int(MAX_B_TN)
            except KeyError:
                await save_group_settings(int(chat_id), 'max_btn', False)
                settings = await get_settings(int(chat_id))
                if settings['max_btn']:
                    max_results = 10
                else:
                    max_results = int(MAX_B_TN)

        cache_key = _search_results_cache_key(
            query, file_type, max_results, offset, sort_by, filters
        )
        cached_results = _get_cached_search_results(cache_key)
        if cached_results is not None:
            logger.debug(
                "Media search cache hit (collection=%s, query=%r, offset=%s, sort=%s)",
                COLLECTION_NAME,
                query,
                offset,
                sort_by,
            )
            return cached_results

        operation = "building database query"
        mongo_filter = _build_search_filter(query, file_type, filters)

        logger.info(
            "Media search filters prepared (collection=%s, query=%r, filters=%s)",
            COLLECTION_NAME,
            query,
            filters or {},
        )

        if multi_db_manager.has_multiple_active_dbs():
            operation = "multi-database searching and merging"
            files, next_offset, total_results = await multi_db_manager.search_media(
                mongo_filter=mongo_filter,
                sort_fields=sort_fields,
                sort_by=sort_by,
                offset=offset,
                max_results=max_results,
                banned_words=banned_words,
                clean_display_fn=_clean_display_file_name,
                season_sort_fn=_season_sort_key if sort_by == "season" else None,
            )
            search_results = (files, next_offset, total_results)
            _cache_search_results(cache_key, search_results)
            return search_results

        operation = "counting matching documents"
        total_results = await Media.count_documents(mongo_filter)
        logger.info(
            "Media search count completed (collection=%s, query=%r, matched=%s)",
            COLLECTION_NAME,
            query,
            total_results,
        )

        next_offset = offset + max_results

        if next_offset >= total_results:
            next_offset = ''

        operation = "retrieving result page"
        if sort_by in ("quality", "language"):
            rank_expression = _metadata_sort_expression(
                QUALITY_SORT_PATTERNS if sort_by == "quality" else LANGUAGE_SORT_PATTERNS,
                0 if sort_by == "quality" else 99,
            )
            pipeline = [
                {"$match": mongo_filter},
                {"$addFields": {"_smart_sort_rank": rank_expression}},
                {
                    "$sort": {
                        "_smart_sort_rank": -1 if sort_by == "quality" else 1,
                        "file_name": 1,
                        "_id": 1,
                    }
                },
                {"$skip": offset},
                {"$limit": max_results},
                {
                    "$project": {
                        "_id": 0,
                        "file_id": "$_id",
                    }
                },
            ]
            ranked_ids = await Media.collection.aggregate(pipeline).to_list(
                length=max_results
            )
            file_ids = [document["file_id"] for document in ranked_ids]
            cursor = Media.find({"file_id": {"$in": file_ids}})
            files_by_id = {
                file.file_id: file
                for file in await cursor.to_list(length=max_results)
            }
            files = [
                files_by_id[file_id]
                for file_id in file_ids
                if file_id in files_by_id
            ]
        else:
            cursor = Media.find(mongo_filter)
            cursor.sort(*sort_fields[sort_by])
            cursor.skip(offset).limit(max_results)
            files = await cursor.to_list(length=max_results)
        logger.info(
            "Media search page retrieved (collection=%s, query=%r, retrieved=%s, offset=%s, page_size=%s)",
            COLLECTION_NAME,
            query,
            len(files),
            offset,
            max_results,
        )
        for file in files:
            for banned_word in banned_words:
                pattern = re.compile(re.escape(banned_word), re.IGNORECASE)
                file['file_name'] = pattern.sub('', file['file_name']).strip()
            file['file_name'] = _clean_display_file_name(file['file_name'])

        if sort_by == "season":
            files.sort(key=lambda file: _season_sort_key(file['file_name']))
        search_results = (files, next_offset, total_results)
        _cache_search_results(cache_key, search_results)
    except Exception:
        logger.exception(
            "Media search failed during %s (collection=%s, chat_id=%s, query=%r)",
            operation,
            COLLECTION_NAME,
            chat_id,
            query,
        )
        raise
    return search_results

async def get_all_files():
    cursor = Media.find() 
    all_files = await cursor.to_list(length=10000)  
    return [file['file_name'] for file in all_files]

async def get_bad_files(query, file_type=None, filter=False):
    """For given query return (results, next_offset)"""
    query = query.strip()
    #if filter:
        #better ?
        #query = query.replace(' ', r'(\s|\.|\+|\-|_)')
        #raw_pattern = r'(\s|_|\-|\.|\+)' + query + r'(\s|_|\-|\.|\+)'
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_]')
    
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except:
        return []

    if USE_CAPTION_FILTER:
        filter = {'$or': [{'file_name': regex}, {'caption': regex}]}
    else:
        filter = {'file_name': regex}

    if file_type:
        filter['file_type'] = file_type

    total_results = await Media.count_documents(filter)

    cursor = Media.find(filter)
    # Sort by recent
    cursor.sort('$natural', -1)
    # Get list of files
    files = await cursor.to_list(length=total_results)
    for file in files:
        file['file_name'] = _clean_display_file_name(file['file_name'])
    files.sort(key=lambda file: _season_sort_key(file['file_name']))

    return files, total_results

async def get_file_details(query):
    try:
        banned_words = script.BLACKLIST
        filter = {'file_id': query}
        cursor = Media.find(filter)
        filedetails = await cursor.to_list(length=1)
        if not filedetails and multi_db_manager.has_multiple_active_dbs():
            filedetails = await multi_db_manager.get_file_details(query)
            
        if filedetails:
            file = filedetails[0]
            original_file_name = getattr(file, 'file_name', '')
            modified_file_name = original_file_name
            for banned_word in banned_words:
                pattern = re.compile(re.escape(banned_word), re.IGNORECASE)
                modified_file_name = pattern.sub('', modified_file_name).strip()
            modified_file_name = _clean_display_file_name(modified_file_name)
            if not modified_file_name:
                modified_file_name = "DefaultFileName"
            setattr(file, 'file_name', modified_file_name)
        return filedetails
    except Exception as e:
        logger.error(f"An error occurred in get_file_details: {e}", exc_info=True)
        return None

def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0

    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0

            r += bytes([i])

    return base64.urlsafe_b64encode(r).decode().rstrip("=")


def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")


def unpack_new_file_id(new_file_id):
    """Return file_id, file_ref"""
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref


__all__ = [
    'Media',
    'save_file',
    'get_file_details',
    'get_search_results',
    'get_bad_files',
    'get_all_files',
    'clear_search_results_cache',
    'unpack_new_file_id',
    'multi_db_manager',
    'mask_mongo_uri',
]
