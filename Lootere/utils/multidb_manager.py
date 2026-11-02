# This code has been created for Feature 3: Multi-MongoDB Storage Manager
# RKMOVIESZIP — Multi-MongoDB Storage Manager Adapter Layer
import re
import asyncio
import logging
from time import monotonic
from typing import Dict, List, Optional, Tuple, Any, Union
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    AsyncIOMotorClient = None

try:
    from pymongo.errors import DuplicateKeyError
except ImportError:
    class DuplicateKeyError(Exception):
        pass

try:
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
except ImportError:
    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

logger = logging.getLogger(__name__)


def mask_mongo_uri(uri: str) -> str:
    """Mask password and credentials in a MongoDB connection string.
    
    Protects sensitive credentials in logs, UI, callbacks, and exception strings.
    Example: mongodb+srv://admin:pass123@cluster0.p73yo98.mongodb.net/
          -> mongodb+srv://admin:****@cluster0.p73yo98.mongodb.net/
    """
    if not uri or not isinstance(uri, str):
        return ""
    
    def _mask_auth(match):
        prefix = match.group(1)
        user = match.group(2)
        password = match.group(3)
        rest = match.group(4)
        masked_pass = "*" * min(max(len(password), 4), 8)
        return f"{prefix}{user}:{masked_pass}{rest}"
    
    # Matches scheme://username:password@
    masked = re.sub(r'(mongodb(?:\+srv)?://)([^:@/]+):([^:@/]+)(@)', _mask_auth, uri)
    return masked


class MultiDBMediaDocument(dict):
    """Document wrapper that supports both dict and attribute access,
    fully compatible with umongo Media objects and dictionary-based lookups.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if '_id' in self and 'file_id' not in self:
            self['file_id'] = self['_id']
        elif 'file_id' in self and '_id' not in self:
            self['_id'] = self['file_id']

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        if name == 'file_id':
            return self.get('_id')
        if name == '_id':
            return self.get('file_id')
        raise AttributeError(f"'MultiDBMediaDocument' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value
        if name == 'file_id':
            self['_id'] = value
        elif name == '_id':
            self['file_id'] = value


class DatabaseNode:
    """Represents an individual MongoDB database connection node."""
    def __init__(
        self,
        node_id: str,
        name: str,
        uri: str,
        db_name: str,
        collection_name: str,
        is_enabled: bool = True,
        priority: int = 100,
        quota_mb: Optional[float] = 512.0,
        threshold_percent: float = 90.0,
        client: Optional[AsyncIOMotorClient] = None,
    ):
        self.id = node_id
        self.name = name
        self.uri = uri
        self.db_name = db_name
        self.collection_name = collection_name
        self.is_enabled = is_enabled
        self.priority = priority
        self.quota_mb = quota_mb
        self.threshold_percent = threshold_percent
        self.is_healthy: bool = True
        self.last_ping_ms: Optional[float] = None
        self.last_error: Optional[str] = None
        self.last_alert_triggered: bool = False
        
        # Initialize Motor client and collections
        if client is not None:
            self.client = client
        elif AsyncIOMotorClient is not None and uri:
            self.client = AsyncIOMotorClient(uri)
        else:
            self.client = None

        if self.client is not None:
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
        else:
            self.db = None
            self.collection = None

    @property
    def masked_uri(self) -> str:
        return mask_mongo_uri(self.uri)

    async def test_connection(self) -> Tuple[bool, Union[float, str]]:
        """Ping the database and measure latency in milliseconds."""
        start = monotonic()
        try:
            await asyncio.wait_for(self.db.command('ping'), timeout=5.0)
            latency = round((monotonic() - start) * 1000, 2)
            self.is_healthy = True
            self.last_ping_ms = latency
            self.last_error = None
            return True, latency
        except Exception as e:
            err_msg = mask_mongo_uri(str(e))
            self.is_healthy = False
            self.last_ping_ms = None
            self.last_error = err_msg
            logger.warning(f"Connection test failed for DB '{self.name}': {err_msg}")
            return False, err_msg

    async def get_storage_stats(self) -> dict:
        """Fetch authoritative storage statistics.
        
        If quota or storage cannot be reliably measured, reports usage_percent = None (Unknown).
        """
        try:
            stats = await self.db.command('dbStats')
            data_size = stats.get('dataSize', 0)
            storage_size = stats.get('storageSize', 0)
            index_size = stats.get('indexSize', 0)
            doc_count = stats.get('objects', 0)
            
            # Authoritative total footprint including storage and indexes
            total_bytes = storage_size + index_size if storage_size else data_size + index_size
            total_mb = round(total_bytes / (1024 * 1024), 2)
            
            if self.quota_mb and self.quota_mb > 0:
                usage_percent = round((total_mb / self.quota_mb) * 100, 1)
            else:
                usage_percent = None  # Unknown
                
            return {
                "status": "ok",
                "doc_count": doc_count,
                "data_size_mb": round(data_size / (1024 * 1024), 2),
                "storage_size_mb": round(storage_size / (1024 * 1024), 2),
                "index_size_mb": round(index_size / (1024 * 1024), 2),
                "total_mb": total_mb,
                "quota_mb": self.quota_mb,
                "usage_percent": usage_percent,
            }
        except Exception as e:
            logger.warning(f"Failed to fetch dbStats for '{self.name}': {mask_mongo_uri(str(e))}")
            return {
                "status": "error",
                "doc_count": 0,
                "data_size_mb": 0.0,
                "storage_size_mb": 0.0,
                "index_size_mb": 0.0,
                "total_mb": 0.0,
                "quota_mb": self.quota_mb,
                "usage_percent": None,  # Unknown
                "error": mask_mongo_uri(str(e)),
            }

    async def close(self):
        """Safely close client connections."""
        try:
            self.client.close()
        except Exception:
            pass


class MultiMongoDBManager:
    """Multi-MongoDB Storage Manager Layer.
    
    Routes new writes, coordinates cross-DB searches, performs deduplication,
    manages health/failover, and enforces storage thresholds.
    """
    def __init__(self):
        self.nodes: Dict[str, DatabaseNode] = {}
        self.active_target_id: str = "primary"
        self.threshold_percent: float = 90.0
        self.default_quota_mb: float = 512.0
        self.alert_callback: Optional[Any] = None
        self._initialized: bool = False
        self._lock = asyncio.Lock()

    def is_initialized(self) -> bool:
        return self._initialized

    def initialize(
        self,
        primary_uri: str,
        primary_db_name: str,
        primary_collection_name: str,
        primary_client: Optional[AsyncIOMotorClient] = None,
        secondary_uris: Optional[List[str]] = None,
        threshold_percent: float = 90.0,
        quota_mb: float = 512.0,
    ):
        """Initialize the storage manager with primary DB and optional secondary DBs."""
        self.threshold_percent = threshold_percent
        self.default_quota_mb = quota_mb

        # Primary node remains default and retains every existing record
        primary_node = DatabaseNode(
            node_id="primary",
            name="Primary DB (Cluster 1)",
            uri=primary_uri,
            db_name=primary_db_name,
            collection_name=primary_collection_name,
            is_enabled=True,
            priority=100,
            quota_mb=quota_mb,
            threshold_percent=threshold_percent,
            client=primary_client,
        )
        self.nodes["primary"] = primary_node
        self.active_target_id = "primary"

        # Register secondary URIs (up to 5 initial, extensible)
        if secondary_uris:
            for idx, uri in enumerate(secondary_uris, start=2):
                if not uri or not uri.strip():
                    continue
                node_id = f"db{idx}"
                priority = max(10, 100 - ((idx - 1) * 10))
                self.register_database(
                    node_id=node_id,
                    name=f"Secondary DB {idx}",
                    uri=uri.strip(),
                    db_name=primary_db_name,
                    collection_name=primary_collection_name,
                    is_enabled=True,
                    priority=priority,
                    quota_mb=quota_mb,
                )

        self._initialized = True
        logger.info(
            f"Multi-MongoDB Storage Manager initialized with {len(self.nodes)} node(s). "
            f"Active write target: '{self.active_target_id}'"
        )

    def register_database(
        self,
        node_id: str,
        name: str,
        uri: str,
        db_name: str,
        collection_name: str,
        is_enabled: bool = True,
        priority: int = 80,
        quota_mb: Optional[float] = 512.0,
        client: Optional[AsyncIOMotorClient] = None,
    ) -> DatabaseNode:
        """Dynamically add a new database connection."""
        node = DatabaseNode(
            node_id=node_id,
            name=name,
            uri=uri,
            db_name=db_name,
            collection_name=collection_name,
            is_enabled=is_enabled,
            priority=priority,
            quota_mb=quota_mb if quota_mb is not None else self.default_quota_mb,
            threshold_percent=self.threshold_percent,
            client=client,
        )
        self.nodes[node_id] = node
        logger.info(f"Registered DB node '{node_id}' ({name}) with priority {priority}")
        return node

    async def remove_database(self, node_id: str) -> Tuple[bool, str]:
        """Safely close and remove a secondary database node.
        
        The primary DB cannot be removed.
        """
        if node_id == "primary":
            return False, "Cannot remove the Primary database."
        if node_id not in self.nodes:
            return False, f"Database node '{node_id}' not found."

        node = self.nodes.pop(node_id)
        await node.close()
        
        # If active target was removed, reset to primary
        if self.active_target_id == node_id:
            self.active_target_id = "primary"
            
        logger.info(f"Removed DB node '{node_id}' ({node.name})")
        return True, f"Database '{node.name}' removed successfully."

    def get_node(self, node_id: str) -> Optional[DatabaseNode]:
        return self.nodes.get(node_id)

    def get_all_nodes(self) -> List[DatabaseNode]:
        return list(self.nodes.values())

    def get_enabled_nodes(self) -> List[DatabaseNode]:
        """Get all nodes with is_enabled == True."""
        return [node for node in self.nodes.values() if node.is_enabled]

    def has_multiple_active_dbs(self) -> bool:
        """Returns True if more than 1 enabled node is configured."""
        return len(self.get_enabled_nodes()) > 1

    def set_enabled(self, node_id: str, enabled: bool) -> Tuple[bool, str]:
        """Enable (ON) or Disable (OFF) a database node.
        
        OFF excludes from new indexing and search reads without deleting data.
        ON restores participation.
        """
        node = self.nodes.get(node_id)
        if not node:
            return False, f"Database node '{node_id}' not found."
        node.is_enabled = enabled
        status_str = "ON" if enabled else "OFF"
        
        # If active target was disabled, switch to next healthy enabled DB
        if not enabled and self.active_target_id == node_id:
            self.failover_to_next_target(exclude_id=node_id)
            
        logger.info(f"DB node '{node_id}' set to {status_str}")
        return True, f"Database '{node.name}' participation set to {status_str}."

    def set_priority(self, node_id: str, priority: int) -> Tuple[bool, str]:
        node = self.nodes.get(node_id)
        if not node:
            return False, f"Database node '{node_id}' not found."
        node.priority = priority
        logger.info(f"DB node '{node_id}' priority set to {priority}")
        return True, f"Database '{node.name}' priority updated to {priority}."

    def set_active_target(self, node_id: str) -> Tuple[bool, str]:
        """Manual indexing-target switch."""
        node = self.nodes.get(node_id)
        if not node:
            return False, f"Database node '{node_id}' not found."
        if not node.is_enabled:
            return False, f"Cannot set disabled DB '{node.name}' as active target."
        self.active_target_id = node_id
        logger.info(f"Manual indexing-target switched to '{node_id}' ({node.name})")
        return True, f"Active indexing target set to '{node.name}'."

    def get_active_target(self) -> Optional[DatabaseNode]:
        """Return the current active target, or failover if unhealthy/disabled."""
        target = self.nodes.get(self.active_target_id)
        if target and target.is_enabled and target.is_healthy:
            return target
        return self.failover_to_next_target()

    def get_write_candidates(self) -> List[DatabaseNode]:
        """Return enabled and healthy nodes sorted by priority descending."""
        candidates = [node for node in self.nodes.values() if node.is_enabled and node.is_healthy]
        active = self.nodes.get(self.active_target_id)
        
        # Place active target first if eligible, then sort remainder by priority
        sorted_candidates = []
        if active and active.is_enabled and active.is_healthy:
            sorted_candidates.append(active)
            
        remainder = [n for n in candidates if not active or n.id != active.id]
        remainder.sort(key=lambda n: n.priority, reverse=True)
        sorted_candidates.extend(remainder)
        return sorted_candidates

    def failover_to_next_target(self, exclude_id: Optional[str] = None) -> Optional[DatabaseNode]:
        """Select the next healthy enabled DB with highest priority."""
        candidates = [
            node for node in self.nodes.values()
            if node.is_enabled and node.is_healthy and (exclude_id is None or node.id != exclude_id)
        ]
        candidates.sort(key=lambda n: n.priority, reverse=True)
        if candidates:
            next_target = candidates[0]
            self.active_target_id = next_target.id
            logger.info(f"Failover selected '{next_target.id}' ({next_target.name}) as new active target")
            return next_target
        
        # Fallback to primary even if unhealthy if nothing else exists
        primary = self.nodes.get("primary")
        if primary:
            self.active_target_id = "primary"
            return primary
        return None

    async def check_node_threshold(self, node: DatabaseNode) -> bool:
        """Check 90% threshold for a node.
        
        At 90% of a known/configured threshold, sends one alert per threshold crossing
        and routes new indexing to the next enabled healthy DB.
        Does not repeat alerts until usage falls below threshold.
        """
        stats = await node.get_storage_stats()
        usage_percent = stats.get("usage_percent")
        
        if usage_percent is None:
            # Cannot measure reliably -> Report Unknown, do not guess
            return False

        if usage_percent >= node.threshold_percent:
            if not node.last_alert_triggered:
                # Trigger ONE alert
                node.last_alert_triggered = True
                new_target = self.failover_to_next_target(exclude_id=node.id)
                alert_text = (
                    f"⚠️ Storage Threshold Alert: DB '{node.name}' ({node.masked_uri}) has reached "
                    f"{usage_percent:.1f}% capacity (Threshold: {node.threshold_percent}%).\n"
                    f"New indexing automatically routed to: '{new_target.name if new_target else 'None'}'"
                )
                logger.warning(alert_text)
                if self.alert_callback:
                    try:
                        await self.alert_callback(node, usage_percent, new_target, alert_text)
                    except Exception as e:
                        logger.error(f"Alert callback error: {e}")
                return True
        else:
            # Usage is safely below threshold, reset hysteresis alert flag
            if node.last_alert_triggered:
                logger.info(f"DB '{node.name}' usage dropped to {usage_percent:.1f}%. Threshold alert reset.")
                node.last_alert_triggered = False
                
        return False

    async def save_media_file(
        self,
        media: Any,
        unpack_fn: Any,
        clean_name_fn: Any,
        check_dup_fn: Optional[Any] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Save a new media file into the active healthy database.
        
        Implements bounded retries (2), safe failover, idempotent writes,
        and duplicate detection across enabled DBs.
        """
        file_id, file_ref = unpack_fn(media.file_id)
        file_name = clean_name_fn(str(media.file_name))

        # 1. Check duplicate via duplicate cleaner if available
        if check_dup_fn:
            try:
                should_skip, existing_id = await check_dup_fn(file_name, media.file_size)
                if should_skip:
                    logger.info(f"{file_name} is already saved (smart duplicate check)")
                    return False, existing_id
            except Exception as e:
                logger.debug(f"Smart duplicate check skipped: {e}")

        # 2. Check if file_id already exists in any enabled DB
        for node in self.get_enabled_nodes():
            try:
                existing = await node.collection.find_one({"_id": file_id}, {"_id": 1})
                if existing:
                    logger.info(f"{file_name} already exists in DB '{node.name}'")
                    return False, file_id
            except Exception:
                continue

        caption = None
        if getattr(media, "caption", None):
            caption = media.caption.html if hasattr(media.caption, "html") else str(media.caption)

        doc = {
            "_id": file_id,
            "file_id": file_id,
            "file_ref": file_ref,
            "file_name": file_name,
            "file_size": media.file_size,
            "file_type": media.file_type,
            "mime_type": media.mime_type,
            "caption": caption,
        }

        # 3. Write with bounded retries and failover across write candidates
        candidates = self.get_write_candidates()
        if not candidates:
            logger.error("No enabled healthy databases available for saving media.")
            return False, None

        last_error = None
        for node in candidates:
            # Check 90% threshold before writing
            await self.check_node_threshold(node)
            
            # Bounded retry loop (max 2 attempts)
            for attempt in range(2):
                try:
                    await node.collection.insert_one(dict(doc))
                    logger.info(f"{file_name} successfully saved to DB '{node.name}'")
                    return True, file_id
                except DuplicateKeyError:
                    logger.warning(f"{file_name} already saved in DB '{node.name}' (DuplicateKeyError)")
                    return False, file_id
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"Write to '{node.name}' attempt {attempt + 1} failed: {mask_mongo_uri(str(e))}"
                    )
                    await asyncio.sleep(0.05 * (attempt + 1))

            # If node failed after retries, mark temporarily unhealthy and failover
            logger.error(f"Write to '{node.name}' failed after retries. Failing over to next DB.")
            node.is_healthy = False

        logger.error(f"Failed to save file across all candidate DBs: {last_error}")
        return False, None

    async def search_media(
        self,
        mongo_filter: dict,
        sort_fields: dict,
        sort_by: str,
        offset: int,
        max_results: int,
        banned_words: Optional[List[str]] = None,
        clean_display_fn: Optional[Any] = None,
        season_sort_fn: Optional[Any] = None,
    ) -> Tuple[List[MultiDBMediaDocument], Union[int, str], int]:
        """Search across all enabled DBs, merge and deduplicate results,
        and preserve existing pagination/result behavior.
        
        Handles partial outages gracefully.
        """
        enabled_nodes = [node for node in self.get_enabled_nodes() if node.is_healthy]
        if not enabled_nodes:
            enabled_nodes = self.get_enabled_nodes()

        # If only 1 DB is enabled, query directly
        if len(enabled_nodes) <= 1:
            target_node = enabled_nodes[0] if enabled_nodes else self.nodes.get("primary")
            if not target_node:
                return [], "", 0
            return await self._query_single_node(
                target_node, mongo_filter, sort_fields, sort_by, offset, max_results,
                banned_words, clean_display_fn, season_sort_fn
            )

        # Multi-DB concurrent search
        fetch_limit = offset + (max_results * 4)

        async def query_node(node: DatabaseNode):
            try:
                cursor = node.collection.find(mongo_filter)
                if sort_by in sort_fields and sort_fields[sort_by]:
                    cursor.sort(*sort_fields[sort_by])
                docs = await cursor.to_list(length=fetch_limit)
                count = await node.collection.count_documents(mongo_filter)
                return docs, count
            except Exception as e:
                logger.warning(f"Search query error on DB '{node.name}': {mask_mongo_uri(str(e))}")
                return [], 0

        tasks = [query_node(node) for node in enabled_nodes]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        all_docs = []
        seen_ids = set()
        total_matched = 0

        for resp in responses:
            if isinstance(resp, Exception):
                continue
            docs, count = resp
            total_matched += count
            for doc in docs:
                file_id = doc.get("_id") or doc.get("file_id")
                if file_id not in seen_ids:
                    seen_ids.add(file_id)
                    all_docs.append(MultiDBMediaDocument(doc))

        # Apply global sorting across merged results
        if sort_by == "title":
            all_docs.sort(key=lambda d: d.get("file_name", "").lower())
        elif sort_by == "size":
            all_docs.sort(key=lambda d: d.get("file_size", 0), reverse=True)
        elif sort_by == "size_asc":
            all_docs.sort(key=lambda d: d.get("file_size", 0))
        elif sort_by == "season" and season_sort_fn:
            all_docs.sort(key=lambda d: season_sort_fn(d.get("file_name", "")))

        # Clean display names and banned words
        for file in all_docs:
            name = file.get("file_name", "")
            if banned_words:
                for banned_word in banned_words:
                    pattern = re.compile(re.escape(banned_word), re.IGNORECASE)
                    name = pattern.sub('', name).strip()
            if clean_display_fn:
                name = clean_display_fn(name)
            file["file_name"] = name

        # Slice current page
        page_results = all_docs[offset : offset + max_results]
        next_offset = offset + max_results
        if next_offset >= len(all_docs) and next_offset >= total_matched:
            next_offset = ""

        return page_results, next_offset, max(total_matched, len(all_docs))

    async def _query_single_node(
        self,
        node: DatabaseNode,
        mongo_filter: dict,
        sort_fields: dict,
        sort_by: str,
        offset: int,
        max_results: int,
        banned_words: Optional[List[str]] = None,
        clean_display_fn: Optional[Any] = None,
        season_sort_fn: Optional[Any] = None,
    ) -> Tuple[List[MultiDBMediaDocument], Union[int, str], int]:
        """Query a single node with standard pagination."""
        try:
            total_results = await node.collection.count_documents(mongo_filter)
            cursor = node.collection.find(mongo_filter)
            if sort_by in sort_fields and sort_fields[sort_by]:
                cursor.sort(*sort_fields[sort_by])
            cursor.skip(offset).limit(max_results)
            raw_docs = await cursor.to_list(length=max_results)
            
            docs = [MultiDBMediaDocument(d) for d in raw_docs]
            for file in docs:
                name = file.get("file_name", "")
                if banned_words:
                    for banned_word in banned_words:
                        pattern = re.compile(re.escape(banned_word), re.IGNORECASE)
                        name = pattern.sub('', name).strip()
                if clean_display_fn:
                    name = clean_display_fn(name)
                file["file_name"] = name

            if sort_by == "season" and season_sort_fn:
                docs.sort(key=lambda d: season_sort_fn(d.get("file_name", "")))

            next_offset = offset + max_results
            if next_offset >= total_results:
                next_offset = ""
            return docs, next_offset, total_results
        except Exception as e:
            logger.exception(f"Single node query error on '{node.name}': {mask_mongo_uri(str(e))}")
            return [], "", 0

    async def get_file_details(self, file_id: str) -> Optional[List[MultiDBMediaDocument]]:
        """Lookup file details across enabled databases.
        
        Checks active target first, then remaining enabled nodes in parallel.
        """
        active = self.get_active_target()
        nodes_to_search = []
        if active:
            nodes_to_search.append(active)
        for n in self.get_enabled_nodes():
            if not active or n.id != active.id:
                nodes_to_search.append(n)

        for node in nodes_to_search:
            try:
                doc = await node.collection.find_one({"_id": file_id})
                if not doc:
                    doc = await node.collection.find_one({"file_id": file_id})
                if doc:
                    return [MultiDBMediaDocument(doc)]
            except Exception as e:
                logger.warning(f"File details lookup failed on DB '{node.name}': {mask_mongo_uri(str(e))}")
                continue
        return None

    async def count_documents(self, mongo_filter: dict) -> int:
        """Count matching documents across all enabled databases."""
        enabled_nodes = self.get_enabled_nodes()
        if not enabled_nodes:
            return 0
        tasks = [node.collection.count_documents(mongo_filter) for node in enabled_nodes]
        counts = await asyncio.gather(*tasks, return_exceptions=True)
        total = sum(c for c in counts if isinstance(c, int))
        return total

    async def test_all_connections(self) -> Dict[str, dict]:
        """Test latency and health of all registered databases."""
        results = {}
        for node_id, node in self.nodes.items():
            success, latency_or_err = await node.test_connection()
            results[node_id] = {
                "name": node.name,
                "masked_uri": node.masked_uri,
                "is_enabled": node.is_enabled,
                "is_healthy": success,
                "latency_ms": latency_or_err if success else None,
                "error": latency_or_err if not success else None,
                "is_active_target": (node_id == self.active_target_id),
                "priority": node.priority,
            }
        return results

    async def get_full_status_report(self) -> dict:
        """Fetch complete status and authoritative stats for admin dashboard."""
        node_reports = []
        for node_id, node in self.nodes.items():
            stats = await node.get_storage_stats()
            node_reports.append({
                "id": node.id,
                "name": node.name,
                "masked_uri": node.masked_uri,
                "is_enabled": node.is_enabled,
                "is_healthy": node.is_healthy,
                "is_active_target": (node_id == self.active_target_id),
                "priority": node.priority,
                "last_ping_ms": node.last_ping_ms,
                "doc_count": stats.get("doc_count", 0),
                "total_mb": stats.get("total_mb", 0.0),
                "quota_mb": stats.get("quota_mb"),
                "usage_percent": stats.get("usage_percent"),
                "status_label": "ACTIVE" if node_id == self.active_target_id else ("ENABLED" if node.is_enabled else "OFF"),
            })
        return {
            "total_dbs": len(self.nodes),
            "active_target_id": self.active_target_id,
            "threshold_percent": self.threshold_percent,
            "nodes": node_reports,
        }


# Global singleton instance
multi_db_manager = MultiMongoDBManager()


def format_multidb_dashboard_text(report: dict) -> str:
    """Format the Multi-MongoDB Storage Manager dashboard summary in clean HTML."""
    total_dbs = report.get("total_dbs", 0)
    active_target = report.get("active_target_id", "primary")
    threshold = report.get("threshold_percent", 90.0)
    nodes = report.get("nodes", [])

    lines = [
        "<b>Multi-MongoDB Storage Manager</b>\n",
        f"<b>Configured Clusters:</b> <code>{total_dbs}/5 (Extensible)</code>",
        f"<b>Active Indexing Target:</b> <code>{active_target.upper()}</code>",
        f"<b>Storage Alert Threshold:</b> <code>{threshold}%</code>\n",
    ]

    for node in nodes:
        node_id = node.get("id")
        name = node.get("name")
        masked_uri = node.get("masked_uri")
        status_label = node.get("status_label")
        priority = node.get("priority", 100)
        ping_ms = node.get("last_ping_ms")
        doc_count = node.get("doc_count", 0)
        total_mb = node.get("total_mb", 0.0)
        quota_mb = node.get("quota_mb")
        usage_pct = node.get("usage_percent")

        ping_str = f"{ping_ms}ms" if ping_ms is not None else "Not tested"
        if usage_pct is not None and quota_mb:
            storage_str = f"{total_mb:.1f} MB / {quota_mb:.1f} MB ({usage_pct}%)"
        elif total_mb > 0:
            storage_str = f"{total_mb:.1f} MB (Quota: Unknown)"
        else:
            storage_str = "Unknown"

        lines.append(
            f"<b>• {name}</b> [<code>{status_label}</code>]\n"
            f"  ├ <b>ID:</b> <code>{node_id}</code> | <b>Priority:</b> <code>{priority}</code>\n"
            f"  ├ <b>URI:</b> <code>{masked_uri}</code>\n"
            f"  ├ <b>Latency:</b> <code>{ping_str}</code>\n"
            f"  ├ <b>Indexed Records:</b> <code>{doc_count:,}</code> files\n"
            f"  └ <b>Storage Footprint:</b> <code>{storage_str}</code>\n"
        )

    lines.append("<i>Manage clusters using the controls below:</i>")
    return "\n".join(lines)


def build_multidb_main_keyboard():
    """Build main control keyboard with ZERO colour emojis in labels."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("TEST ALL DBS", callback_data="multidb#test_all"),
            InlineKeyboardButton("REFRESH", callback_data="multidb#main"),
        ],
        [
            InlineKeyboardButton("SWITCH TARGET", callback_data="multidb#switch_menu"),
            InlineKeyboardButton("ENABLE / DISABLE", callback_data="multidb#toggle_menu"),
        ],
        [
            InlineKeyboardButton("CLOSE", callback_data="multidb#close"),
        ],
    ])


def build_multidb_switch_target_keyboard(nodes: List[dict]):
    """Build keyboard to manually switch active indexing target with ZERO colour emojis."""
    buttons = []
    for node in nodes:
        if not node.get("is_enabled", True):
            continue
        node_id = node.get("id")
        name = node.get("name")
        is_active = node.get("is_active_target", False)
        prefix = "[ACTIVE] " if is_active else ""
        buttons.append([
            InlineKeyboardButton(
                f"{prefix}SET TARGET: {name}",
                callback_data=f"multidb#set_target#{node_id}",
            )
        ])
    buttons.append([InlineKeyboardButton("BACK", callback_data="multidb#main")])
    return InlineKeyboardMarkup(buttons)


def build_multidb_toggle_keyboard(nodes: List[dict]):
    """Build keyboard to toggle participation (ON/OFF) with ZERO colour emojis."""
    buttons = []
    for node in nodes:
        node_id = node.get("id")
        name = node.get("name")
        is_enabled = node.get("is_enabled", True)
        action_text = f"TURN OFF: {name}" if is_enabled else f"TURN ON: {name}"
        buttons.append([
            InlineKeyboardButton(
                action_text,
                callback_data=f"multidb#toggle_state#{node_id}",
            )
        ])
    buttons.append([InlineKeyboardButton("BACK", callback_data="multidb#main")])
    return InlineKeyboardMarkup(buttons)
