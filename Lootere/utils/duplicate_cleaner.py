# Smart Duplicate Cleaner Engine for RKMOVIESZIP (Feature 3)
#
# Safe duplicate detection and cleanup layer.
# - Conservative exact-duplicate and near-duplicate grouping.
# - Strict non-collision rules: different resolutions (480p vs 720p vs 1080p),
#   different episodes (S01E01 vs S01E02), different seasons, or different audio
#   languages are NEVER treated as duplicates.
# - Winner selection: keeps the best/earliest indexed record and only marks
#   redundant copies as removable duplicate candidates.
# - Default mode = Preview / Dry-Run Only (never auto-deletes without explicit
#   admin confirmation).
# - Supports optional auto-skip for exact duplicates on index if enabled by admin.

import asyncio
from dataclasses import dataclass, field
from html import escape as html_escape
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from Lootere.utils.smart_search_engine import (
    clean_promotional_filename,
    format_size_gb,
    parse_smart_media_item,
    SmartMediaMetadata,
)

logger = logging.getLogger(__name__)

DUPLICATE_MODE_SETTING_KEY = "DUPLICATE_CLEANER_MODE"
DEFAULT_DUPLICATE_MODE = "preview"  # Options: "preview", "auto_exact", "off"

# In-memory storage for settings and pending cleanup preview sessions
_MEMORY_DUPLICATE_MODE: str = DEFAULT_DUPLICATE_MODE
_PENDING_CLEANUP_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_TTL_SECONDS = 1800  # 30 minutes


@dataclass
class DuplicateItem:
    file_id: str
    file_name: str
    file_size: int
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    caption: Optional[str] = None
    file_ref: Optional[str] = None
    parsed: Optional[SmartMediaMetadata] = None


@dataclass
class DuplicateGroup:
    group_id: str
    group_type: str  # "exact" or "near"
    canonical_title: str
    winner: DuplicateItem
    duplicates: List[DuplicateItem] = field(default_factory=list)
    reclaimable_bytes: int = 0
    reclaimable_gb: str = "0.00GB"


def normalize_filename_key(filename: str) -> str:
    """Normalize filename for exact duplicate comparison (ignoring promotional noise, punctuation/spacing/case)."""
    if not filename:
        return ""
    cleaned = clean_promotional_filename(filename)
    text = str(cleaned or filename).lower()
    # Strip file extension
    text = re.sub(r"\.(?:mkv|mp4|avi|mov|webm|m4v|flv|ts|wmv|mpg|mpeg)$", "", text)
    # Normalize separators into single spaces
    text = re.sub(r"[\s._+\-]+", " ", text).strip()
    return text



def normalize_title_key(title: str) -> str:
    """Normalize title string for near duplicate clustering."""
    if not title:
        return ""
    text = str(title).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def to_duplicate_item(record: Any) -> DuplicateItem:
    """Convert a database record or dict/object to a DuplicateItem."""
    if isinstance(record, Mapping):
        f_id = str(record.get("_id") or record.get("file_id") or "")
        f_name = str(record.get("file_name") or "")
        f_size = int(record.get("file_size") or 0)
        f_type = record.get("file_type")
        m_type = record.get("mime_type")
        cap = record.get("caption")
        f_ref = record.get("file_ref")
    else:
        f_id = str(getattr(record, "file_id", "") or getattr(record, "_id", "") or "")
        f_name = str(getattr(record, "file_name", "") or "")
        f_size = int(getattr(record, "file_size", 0) or 0)
        f_type = getattr(record, "file_type", None)
        m_type = getattr(record, "mime_type", None)
        cap = getattr(record, "caption", None)
        f_ref = getattr(record, "file_ref", None)

    parsed = parse_smart_media_item(f_name, file_size=f_size)
    return DuplicateItem(
        file_id=f_id,
        file_name=f_name,
        file_size=f_size,
        file_type=f_type,
        mime_type=m_type,
        caption=cap,
        file_ref=f_ref,
        parsed=parsed,
    )


def classify_duplicate_pair(item_a: DuplicateItem, item_b: DuplicateItem) -> Optional[str]:
    """Classify the relationship between two media items.
    Returns:
      'exact': Identical file_id, or identical normalized filename + identical size.
      'near': Same title, category, season/episode, year, identical resolution,
              identical language, and size within 2% tolerance.
      None: Not a duplicate (e.g. different resolution, episode, language, or size).
    """
    # 1. Exact duplicate check
    if item_a.file_id and item_b.file_id and item_a.file_id == item_b.file_id:
        return "exact"

    norm_a = normalize_filename_key(item_a.file_name)
    norm_b = normalize_filename_key(item_b.file_name)
    if norm_a and norm_a == norm_b and item_a.file_size == item_b.file_size:
        return "exact"

    # 2. Near duplicate evaluation
    meta_a = item_a.parsed or parse_smart_media_item(item_a.file_name, file_size=item_a.file_size)
    meta_b = item_b.parsed or parse_smart_media_item(item_b.file_name, file_size=item_b.file_size)

    # Category must match ("movie" vs "series")
    if meta_a.category != meta_b.category:
        return None

    # Title must match
    title_a = normalize_title_key(meta_a.title)
    title_b = normalize_title_key(meta_b.title)
    if not title_a or not title_b or title_a != title_b:
        return None

    # Series safety check: Season and Episode MUST BE IDENTICAL
    if meta_a.category == "series" or meta_b.category == "series":
        if meta_a.season != meta_b.season or meta_a.episode != meta_b.episode:
            return None
        # If both are series but neither has an episode detected, do not group as near-duplicate
        if meta_a.episode is None and meta_b.episode is None:
            return None

    # Year safety check: If both have year, they must match
    if meta_a.year and meta_b.year and meta_a.year != meta_b.year:
        return None

    # Quality safety check: DIFFERENT RESOLUTIONS ARE NEVER DUPLICATES!
    # (e.g. 720p vs 1080p vs 4K vs 480p)
    if meta_a.quality or meta_b.quality:
        if meta_a.quality != meta_b.quality:
            return None

    # Language safety check: DIFFERENT AUDIO LANGUAGES ARE NEVER DUPLICATES!
    # (e.g. Hindi vs Tamil vs Dual Audio)
    if meta_a.language or meta_b.language:
        if meta_a.language != meta_b.language:
            return None

    # Size tolerance check: files must be within 2.5% size difference
    max_size = max(item_a.file_size, item_b.file_size)
    if max_size <= 0:
        return None
    size_diff_ratio = abs(item_a.file_size - item_b.file_size) / float(max_size)
    if size_diff_ratio <= 0.025:
        return "near"

    return None


def select_canonical_winner(items: Sequence[DuplicateItem]) -> Tuple[DuplicateItem, List[DuplicateItem]]:
    """Select the best canonical winner to keep, returning (winner, duplicates_to_remove).
    Winner preference:
      1. Item with non-empty file_ref / valid metadata
      2. Item with caption
      3. First/earliest indexed item (stable ordering)
    """
    if not items:
        raise ValueError("Cannot select winner from empty list")
    if len(items) == 1:
        return items[0], []

    def score_item(index: int, item: DuplicateItem) -> Tuple[int, int, int]:
        has_ref = 1 if item.file_ref else 0
        has_caption = 1 if item.caption else 0
        # Lower index is preferred for stable FIFO earliest preservation
        return (has_ref, has_caption, -index)

    ranked_indices = sorted(
        range(len(items)),
        key=lambda idx: score_item(idx, items[idx]),
        reverse=True,
    )
    winner_idx = ranked_indices[0]
    winner = items[winner_idx]
    duplicates = [items[i] for i in range(len(items)) if i != winner_idx]
    return winner, duplicates


def find_duplicate_groups(records: Sequence[Any]) -> List[DuplicateGroup]:
    """Analyze a collection of media records and group duplicates conservatively."""
    if not records:
        return []

    items = [to_duplicate_item(r) for r in records]

    # Pass 1: Exact duplicate grouping by (normalized_filename, exact_file_size)
    exact_buckets: Dict[Tuple[str, int], List[DuplicateItem]] = {}
    grouped_item_ids: Set[str] = set()

    for item in items:
        norm_name = normalize_filename_key(item.file_name)
        if norm_name and item.file_size > 0:
            key = (norm_name, item.file_size)
            exact_buckets.setdefault(key, []).append(item)

    duplicate_groups: List[DuplicateGroup] = []

    for (norm_name, size), bucket in exact_buckets.items():
        if len(bucket) > 1:
            winner, dups = select_canonical_winner(bucket)
            reclaim_bytes = sum(d.file_size for d in dups)
            duplicate_groups.append(
                DuplicateGroup(
                    group_id=f"exact_{len(duplicate_groups)+1}",
                    group_type="exact",
                    canonical_title=winner.parsed.title if winner.parsed else winner.file_name,
                    winner=winner,
                    duplicates=dups,
                    reclaimable_bytes=reclaim_bytes,
                    reclaimable_gb=format_size_gb(reclaim_bytes),
                )
            )
            for it in bucket:
                if it.file_id:
                    grouped_item_ids.add(it.file_id)

    # Pass 2: Near duplicate grouping for remaining items
    remaining_items = [it for it in items if it.file_id not in grouped_item_ids]

    near_buckets: Dict[Tuple[Any, ...], List[DuplicateItem]] = {}
    for item in remaining_items:
        meta = item.parsed or parse_smart_media_item(item.file_name, file_size=item.file_size)
        title_key = normalize_title_key(meta.title)
        if not title_key:
            continue
        # Bucket by strict attributes so different quality/episodes/languages are NEVER grouped
        bucket_key = (
            meta.category,
            title_key,
            meta.year or "",
            meta.season if meta.category == "series" else 0,
            meta.episode if meta.category == "series" else 0,
            (meta.quality or "").lower(),
            (meta.language or "").lower(),
        )
        near_buckets.setdefault(bucket_key, []).append(item)

    for bucket_key, candidates in near_buckets.items():
        if len(candidates) < 2:
            continue

        # Sub-cluster by size tolerance (within 2.5%)
        clusters: List[List[DuplicateItem]] = []
        for cand in candidates:
            placed = False
            for cl in clusters:
                # Compare cand against cluster anchor
                if classify_duplicate_pair(cl[0], cand) == "near":
                    cl.append(cand)
                    placed = True
                    break
            if not placed:
                clusters.append([cand])

        for cl in clusters:
            if len(cl) > 1:
                winner, dups = select_canonical_winner(cl)
                reclaim_bytes = sum(d.file_size for d in dups)
                duplicate_groups.append(
                    DuplicateGroup(
                        group_id=f"near_{len(duplicate_groups)+1}",
                        group_type="near",
                        canonical_title=winner.parsed.title if winner.parsed else winner.file_name,
                        winner=winner,
                        duplicates=dups,
                        reclaimable_bytes=reclaim_bytes,
                        reclaimable_gb=format_size_gb(reclaim_bytes),
                    )
                )

    return duplicate_groups


async def get_duplicate_mode(db_instance: Any = None) -> str:
    """Get the current duplicate cleaner mode ('preview', 'auto_exact', or 'off')."""
    global _MEMORY_DUPLICATE_MODE
    if db_instance and hasattr(db_instance, "get_setting"):
        try:
            val = await db_instance.get_setting(DUPLICATE_MODE_SETTING_KEY, default=None)
            if val in ("preview", "auto_exact", "off"):
                _MEMORY_DUPLICATE_MODE = val
                return val
        except Exception:
            pass
    return _MEMORY_DUPLICATE_MODE


async def set_duplicate_mode(mode: str, db_instance: Any = None) -> str:
    """Set duplicate cleaner mode ('preview', 'auto_exact', or 'off')."""
    global _MEMORY_DUPLICATE_MODE
    if mode not in ("preview", "auto_exact", "off"):
        mode = "preview"
    _MEMORY_DUPLICATE_MODE = mode
    if db_instance and hasattr(db_instance, "set_setting"):
        try:
            await db_instance.set_setting(DUPLICATE_MODE_SETTING_KEY, mode)
        except Exception:
            pass
    return mode


async def should_auto_skip_exact_duplicate(
    file_name: str,
    file_size: int,
    db_instance: Any = None,
) -> Tuple[bool, Optional[str]]:
    """Check if a file being saved is an exact duplicate and auto_exact mode is active."""
    mode = await get_duplicate_mode(db_instance=db_instance)
    if mode != "auto_exact":
        return False, None

    try:
        from database.ia_filterdb import Media
        cleaned_name = re.sub(r"(_|\-|\.|\+)", " ", str(file_name))
        existing = await Media.collection.find_one({
            "file_name": cleaned_name,
            "file_size": file_size,
        })
        if existing:
            return True, str(existing.get("_id") or existing.get("file_id"))
    except Exception as exc:
        logger.debug("Error checking auto_skip duplicate: %s", exc)
    return False, None


def clean_expired_sessions() -> None:
    """Clean up expired pending cleanup preview sessions."""
    now = time.time()
    expired = [
        sid for sid, sess in _PENDING_CLEANUP_SESSIONS.items()
        if now - sess.get("created_at", 0) > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _PENDING_CLEANUP_SESSIONS.pop(sid, None)


async def scan_duplicates_preview(
    db_instance: Any = None,
    query: Optional[str] = None,
    limit: int = 5000,
    max_groups: int = 50,
) -> Dict[str, Any]:
    """Scan database records and generate a dry-run preview session."""
    clean_expired_sessions()
    session_id = str(uuid.uuid4())[:8]

    # Fetch records
    records: List[Any] = []
    try:
        from database.ia_filterdb import Media
        mongo_filter: Dict[str, Any] = {}
        if query and query.strip():
            mongo_filter["file_name"] = re.compile(re.escape(query.strip()), re.I)
        cursor = Media.find(mongo_filter).limit(limit)
        records = await cursor.to_list(length=limit)
    except Exception as exc:
        logger.warning("Could not query Media collection for duplicates scan: %s", exc)

    groups = find_duplicate_groups(records)
    if max_groups and len(groups) > max_groups:
        display_groups = groups[:max_groups]
    else:
        display_groups = groups

    total_dups = sum(len(g.duplicates) for g in groups)
    exact_count = sum(len(g.duplicates) for g in groups if g.group_type == "exact")
    near_count = sum(len(g.duplicates) for g in groups if g.group_type == "near")
    total_reclaim = sum(g.reclaimable_bytes for g in groups)

    session_data = {
        "session_id": session_id,
        "created_at": time.time(),
        "query": query,
        "total_scanned": len(records),
        "total_groups": len(groups),
        "total_duplicates": total_dups,
        "exact_duplicates": exact_count,
        "near_duplicates": near_count,
        "reclaimable_bytes": total_reclaim,
        "reclaimable_gb": format_size_gb(total_reclaim),
        "groups": groups,
    }
    _PENDING_CLEANUP_SESSIONS[session_id] = session_data

    return {
        "session_id": session_id,
        "status": "preview_ready",
        "total_scanned": len(records),
        "total_groups": len(groups),
        "total_duplicates": total_dups,
        "exact_duplicates": exact_count,
        "near_duplicates": near_count,
        "reclaimable_bytes": total_reclaim,
        "reclaimable_gb": format_size_gb(total_reclaim),
        "display_groups": display_groups,
    }


async def execute_duplicate_cleanup(
    session_id: str,
    admin_id: int,
    db_instance: Any = None,
) -> Dict[str, Any]:
    """Execute confirmed cleanup of duplicates for an active preview session."""
    session = _PENDING_CLEANUP_SESSIONS.pop(session_id, None)
    if not session:
        return {
            "status": "error",
            "message": "Session expired or invalid. Please run /dupscan again.",
        }

    groups: List[DuplicateGroup] = session.get("groups", [])
    duplicate_ids: List[str] = []
    for g in groups:
        for d in g.duplicates:
            if d.file_id:
                duplicate_ids.append(d.file_id)

    if not duplicate_ids:
        return {
            "status": "success",
            "deleted_count": 0,
            "reclaimed_bytes": 0,
            "reclaimed_gb": "0.00GB",
        }

    deleted_count = 0
    try:
        from database.ia_filterdb import Media, clear_search_results_cache
        res = await Media.collection.delete_many({"_id": {"$in": duplicate_ids}})
        deleted_count = res.deleted_count if res else len(duplicate_ids)
        clear_search_results_cache()
    except Exception as exc:
        logger.error("Error deleting duplicates: %s", exc)
        return {
            "status": "error",
            "message": f"Database deletion failed: {exc}",
        }

    reclaim_bytes = session.get("reclaimable_bytes", 0)
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "reclaimed_bytes": reclaim_bytes,
        "reclaimed_gb": format_size_gb(reclaim_bytes),
    }


def cancel_duplicate_cleanup(session_id: str) -> bool:
    """Cancel a pending cleanup preview session."""
    return _PENDING_CLEANUP_SESSIONS.pop(session_id, None) is not None


def format_duplicate_preview_text(preview: Dict[str, Any], mode: str) -> str:
    """Format human-readable Telegram preview message for admin."""
    total_groups = preview.get("total_groups", 0)
    total_dups = preview.get("total_duplicates", 0)
    reclaim_gb = preview.get("reclaimable_gb", "0.00GB")
    exact_count = preview.get("exact_duplicates", 0)
    near_count = preview.get("near_duplicates", 0)
    total_scanned = preview.get("total_scanned", 0)

    mode_label = {
        "preview": "Preview (Dry-Run)",
        "auto_exact": "Auto-Skip Exact on Index",
        "off": "Off",
    }.get(mode, mode)

    lines = [
        "<b>🧹 Smart Duplicate Cleaner Dashboard</b>",
        f"<b>Current Mode:</b> <code>{mode_label}</code>",
        f"<b>Files Scanned:</b> <code>{total_scanned}</code>",
        "",
    ]

    if total_dups == 0:
        lines.append("✅ <b>No duplicate files found! Database is clean.</b>")
        return "\n".join(lines)

    lines.extend([
        f"<b>Found:</b> <code>{total_dups}</code> duplicates in <code>{total_groups}</code> groups",
        f"• <b>Exact Duplicates:</b> <code>{exact_count}</code>",
        f"• <b>Near Duplicates:</b> <code>{near_count}</code>",
        f"<b>Estimated Space to Reclaim:</b> <code>{reclaim_gb}</code>",
        "",
        "<b>Preview Top Groups (Winner vs Duplicate):</b>",
    ])

    display_groups: List[DuplicateGroup] = preview.get("display_groups", [])
    for idx, grp in enumerate(display_groups[:5], start=1):
        lines.append(f"<b>Group #{idx} [{grp.group_type.upper()}]:</b> <i>{html_escape(grp.canonical_title)}</i>")
        lines.append(f"  👑 <b>Winner [KEPT]:</b> <code>{html_escape(grp.winner.file_name[:40])}</code> ({format_size_gb(grp.winner.file_size)})")
        for dup in grp.duplicates[:2]:
            lines.append(f"  ❌ <b>Duplicate [REMOVE]:</b> <code>{html_escape(dup.file_name[:40])}</code> ({format_size_gb(dup.file_size)})")
        if len(grp.duplicates) > 2:
            lines.append(f"  ... +{len(grp.duplicates)-2} more duplicate(s)")
        lines.append("")

    lines.append("<i>Safety Guarantee: Different resolutions (480p vs 720p vs 1080p), languages, and episodes are never grouped as duplicates.</i>")
    return "\n".join(lines)
