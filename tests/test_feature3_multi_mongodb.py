# Unit and Integration Tests for Feature 3: Multi-MongoDB Storage Manager
import unittest
import asyncio
import sys
import types
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = Path(__file__).resolve().parent.parent
if "Lootere" not in sys.modules:
    sys.modules["Lootere"] = types.ModuleType("Lootere")
if "Lootere.utils" not in sys.modules:
    sys.modules["Lootere.utils"] = types.ModuleType("Lootere.utils")

_MDB_PATH = _ROOT / "Lootere" / "utils" / "multidb_manager.py"
_MDB_SPEC = importlib.util.spec_from_file_location("Lootere.utils.multidb_manager", _MDB_PATH)
multidb_manager = importlib.util.module_from_spec(_MDB_SPEC)
assert _MDB_SPEC and _MDB_SPEC.loader
sys.modules["Lootere.utils.multidb_manager"] = multidb_manager
_MDB_SPEC.loader.exec_module(multidb_manager)

MultiMongoDBManager = multidb_manager.MultiMongoDBManager
DatabaseNode = multidb_manager.DatabaseNode
MultiDBMediaDocument = multidb_manager.MultiDBMediaDocument
mask_mongo_uri = multidb_manager.mask_mongo_uri
format_multidb_dashboard_text = multidb_manager.format_multidb_dashboard_text
build_multidb_main_keyboard = multidb_manager.build_multidb_main_keyboard
build_multidb_switch_target_keyboard = multidb_manager.build_multidb_switch_target_keyboard
build_multidb_toggle_keyboard = multidb_manager.build_multidb_toggle_keyboard


class MockMotorCollection:
    """Mock Motor collection simulating MongoDB async collection."""
    def __init__(self, name="Rkmovieszip", initial_docs=None):
        self.name = name
        self.docs = {doc.get("_id"): dict(doc) for doc in (initial_docs or [])}
        self.insert_calls = 0
        self.fail_writes = False

    async def find_one(self, filter_dict, projection=None):
        if "_id" in filter_dict:
            return self.docs.get(filter_dict["_id"])
        if "file_id" in filter_dict:
            for d in self.docs.values():
                if d.get("file_id") == filter_dict["file_id"]:
                    return d
        return None

    def find(self, filter_dict=None):
        results = list(self.docs.values())
        if filter_dict:
            for k, v in filter_dict.items():
                if k == "file_type":
                    results = [d for d in results if d.get("file_type") == v]
        
        class MockCursor:
            def __init__(self, data):
                self._data = list(data)

            def sort(self, field, direction):
                reverse = (direction == -1)
                self._data.sort(key=lambda x: x.get(field, ""), reverse=reverse)
                return self

            def skip(self, n):
                self._data = self._data[n:]
                return self

            def limit(self, n):
                self._data = self._data[:n]
                return self

            async def to_list(self, length=None):
                if length is not None:
                    return self._data[:length]
                return self._data

        return MockCursor(results)

    async def count_documents(self, filter_dict=None):
        if not filter_dict:
            return len(self.docs)
        count = 0
        for d in self.docs.values():
            match = True
            for k, v in filter_dict.items():
                if k == "file_type" and d.get("file_type") != v:
                    match = False
            if match:
                count += 1
        return count

    async def insert_one(self, doc):
        self.insert_calls += 1
        if self.fail_writes:
            raise RuntimeError("Simulated cluster connection failure")
        doc_id = doc.get("_id")
        DuplicateKeyError = getattr(multidb_manager, "DuplicateKeyError", Exception)
        if doc_id in self.docs:
            raise DuplicateKeyError(f"E11000 duplicate key error collection: {doc_id}")
        self.docs[doc_id] = dict(doc)
        return MagicMock(inserted_id=doc_id)



class MockMotorDatabase:
    """Mock Motor database simulating command ping and dbStats."""
    def __init__(self, name="Cluster0", collection=None):
        self.name = name
        self._collection = collection or MockMotorCollection()
        self.stats_return = {
            "dataSize": 150 * 1024 * 1024,
            "storageSize": 200 * 1024 * 1024,
            "indexSize": 25 * 1024 * 1024,
            "objects": 12000,
        }
        self.ping_succeeds = True

    def __getitem__(self, name):
        return self._collection

    async def command(self, cmd_name, *args, **kwargs):
        if cmd_name == "ping":
            if not self.ping_succeeds:
                raise RuntimeError("Cluster connection timeout")
            return {"ok": 1.0}
        if cmd_name == "dbStats":
            return self.stats_return
        return {}


def create_mock_node(node_id, name, uri, priority=100, quota_mb=512.0, initial_docs=None):
    collection = MockMotorCollection(initial_docs=initial_docs)
    db = MockMotorDatabase(collection=collection)
    client = MagicMock()
    client.close = MagicMock()
    node = DatabaseNode(
        node_id=node_id,
        name=name,
        uri=uri,
        db_name="Cluster0",
        collection_name="Rkmovieszip",
        priority=priority,
        quota_mb=quota_mb,
        client=client,
    )
    node.db = db
    node.collection = collection
    return node


class TestFeature3MultiMongoDBStorageManager(unittest.TestCase):

    def test_credential_masking_everywhere(self):
        """FR9: Secrets and passwords must be masked in URIs and logs."""
        raw_uri = "mongodb+srv://adminUser:MySecretPassword123@cluster0.p73yo98.mongodb.net/?retryWrites=true&w=majority"
        masked = mask_mongo_uri(raw_uri)
        self.assertNotIn("MySecretPassword123", masked)
        self.assertIn("adminUser", masked)
        self.assertIn("cluster0.p73yo98.mongodb.net", masked)
        self.assertTrue("****" in masked)

        # Standard mongodb:// protocol
        raw_uri2 = "mongodb://bot_user:TopSecret99@127.0.0.1:27017/movielist"
        masked2 = mask_mongo_uri(raw_uri2)
        self.assertNotIn("TopSecret99", masked2)
        self.assertIn("bot_user", masked2)

    def test_multidb_media_document_dict_and_attribute_access(self):
        """MultiDBMediaDocument must support both dict and attribute access like umongo Media."""
        doc = MultiDBMediaDocument({
            "_id": "FILE123",
            "file_name": "Inception 2010 1080p.mkv",
            "file_size": 2147483648,
            "file_type": "video",
        })
        # Attribute access
        self.assertEqual(doc.file_id, "FILE123")
        self.assertEqual(doc.file_name, "Inception 2010 1080p.mkv")
        self.assertEqual(doc.file_size, 2147483648)
        # Dict access
        self.assertEqual(doc["file_id"], "FILE123")
        self.assertEqual(doc["file_name"], "Inception 2010 1080p.mkv")
        self.assertEqual(doc["file_size"], 2147483648)
        # Mutation
        doc["file_name"] = "Inception Clean.mkv"
        self.assertEqual(doc.file_name, "Inception Clean.mkv")

    def test_legacy_single_db_mode_unchanged(self):
        """FR1: If only one DB is configured, manager operates in single DB mode."""
        manager = MultiMongoDBManager()
        primary_node = create_mock_node(
            "primary", "Primary DB", "mongodb+srv://user:pass@cluster0.mongodb.net/test"
        )
        manager.nodes["primary"] = primary_node
        manager.active_target_id = "primary"
        manager._initialized = True

        self.assertFalse(manager.has_multiple_active_dbs())
        self.assertEqual(len(manager.get_enabled_nodes()), 1)
        self.assertEqual(manager.get_active_target().id, "primary")

    def test_multi_db_registration_up_to_five_extensible(self):
        """Scope: Register up to 5 initial DBs, extensible design."""
        manager = MultiMongoDBManager()
        primary_node = create_mock_node("primary", "Primary DB", "mongodb+srv://user:pass@cluster1.mongodb.net/")
        manager.nodes["primary"] = primary_node
        manager.active_target_id = "primary"

        for i in range(2, 6):
            node = create_mock_node(f"db{i}", f"Cluster {i}", f"mongodb+srv://user:pass@cluster{i}.mongodb.net/", priority=100 - i * 10)
            manager.nodes[f"db{i}"] = node

        self.assertEqual(len(manager.nodes), 5)
        self.assertTrue(manager.has_multiple_active_dbs())
        self.assertEqual(len(manager.get_enabled_nodes()), 5)

        # Extensible: add 6th DB
        node6 = create_mock_node("db6", "Cluster 6", "mongodb+srv://user:pass@cluster6.mongodb.net/", priority=40)
        manager.nodes["db6"] = node6
        self.assertEqual(len(manager.nodes), 6)

    def test_cross_db_search_merging_and_deduplication(self):
        """FR4: Search enabled DBs, merge and deduplicate results by file_id."""
        async def run():
            manager = MultiMongoDBManager()
            
            # DB1 has File A and File B
            db1 = create_mock_node(
                "primary", "Primary DB", "mongodb+srv://user:pass@cluster1.mongodb.net/",
                initial_docs=[
                    {"_id": "FID_A", "file_name": "Avatar 2009 1080p.mkv", "file_size": 1000},
                    {"_id": "FID_B", "file_name": "Batman 2008 720p.mkv", "file_size": 800},
                ]
            )
            # DB2 has File B (duplicate copy) and File C (unique)
            db2 = create_mock_node(
                "db2", "Secondary DB 2", "mongodb+srv://user:pass@cluster2.mongodb.net/",
                initial_docs=[
                    {"_id": "FID_B", "file_name": "Batman 2008 720p.mkv", "file_size": 800},
                    {"_id": "FID_C", "file_name": "Gladiator 2000 1080p.mkv", "file_size": 1200},
                ]
            )
            manager.nodes["primary"] = db1
            manager.nodes["db2"] = db2
            manager.active_target_id = "primary"

            # Search across all enabled DBs
            files, next_offset, total = await manager.search_media(
                mongo_filter={},
                sort_fields={"size": ("file_size", -1)},
                sort_by="size",
                offset=0,
                max_results=10,
            )

            # Should merge DB1 and DB2 and deduplicate FID_B -> exactly 3 unique files (C, A, B)
            self.assertEqual(len(files), 3)
            self.assertEqual([f["_id"] for f in files], ["FID_C", "FID_A", "FID_B"])
            self.assertEqual(next_offset, "")
            self.assertGreaterEqual(total, 3)

        asyncio.run(run())

    def test_cross_db_pagination(self):
        """FR4: Multi-DB search pagination must accurately compute offset and next_offset."""
        async def run():
            manager = MultiMongoDBManager()
            docs1 = [{"_id": f"FID_{i}", "file_name": f"Movie {i}.mkv", "file_size": 100 * i} for i in range(1, 4)]
            docs2 = [{"_id": f"FID_{i}", "file_name": f"Movie {i}.mkv", "file_size": 100 * i} for i in range(4, 7)]
            
            db1 = create_mock_node("primary", "DB1", "mongodb://localhost/db1", initial_docs=docs1)
            db2 = create_mock_node("db2", "DB2", "mongodb://localhost/db2", initial_docs=docs2)
            manager.nodes["primary"] = db1
            manager.nodes["db2"] = db2

            # Page 1 (offset 0, max 2)
            page1, next_offset1, total1 = await manager.search_media(
                mongo_filter={}, sort_fields={"size": ("file_size", -1)}, sort_by="size", offset=0, max_results=2
            )
            self.assertEqual(len(page1), 2)
            self.assertEqual(next_offset1, 2)
            self.assertEqual(total1, 6)

            # Page 2 (offset 2, max 2)
            page2, next_offset2, total2 = await manager.search_media(
                mongo_filter={}, sort_fields={"size": ("file_size", -1)}, sort_by="size", offset=2, max_results=2
            )
            self.assertEqual(len(page2), 2)
            self.assertEqual(next_offset2, 4)

            # Page 3 (offset 4, max 2) -> last page
            page3, next_offset3, total3 = await manager.search_media(
                mongo_filter={}, sort_fields={"size": ("file_size", -1)}, sort_by="size", offset=4, max_results=2
            )
            self.assertEqual(len(page3), 2)
            self.assertEqual(next_offset3, "")

        asyncio.run(run())

    def test_enable_disable_participation_off_and_on(self):
        """FR5 & FR6: OFF excludes a DB from reads and writes without deleting data; ON restores it."""
        async def run():
            manager = MultiMongoDBManager()
            db1 = create_mock_node("primary", "DB1", "mongodb://localhost/db1", initial_docs=[{"_id": "F1", "file_name": "A.mkv"}])
            db2 = create_mock_node("db2", "DB2", "mongodb://localhost/db2", initial_docs=[{"_id": "F2", "file_name": "B.mkv"}])
            manager.nodes["primary"] = db1
            manager.nodes["db2"] = db2

            # Both ON: search returns 2 files
            files, _, _ = await manager.search_media({}, {}, "title", 0, 10)
            self.assertEqual(len(files), 2)

            # Turn DB2 OFF
            success, msg = manager.set_enabled("db2", False)
            self.assertTrue(success)
            self.assertFalse(db2.is_enabled)
            # DB2 data is NOT deleted:
            self.assertIn("F2", db2.collection.docs)

            # Search now excludes DB2: returns only F1
            files_off, _, _ = await manager.search_media({}, {}, "title", 0, 10)
            self.assertEqual(len(files_off), 1)
            self.assertEqual(files_off[0]["_id"], "F1")

            # Turn DB2 ON again: restores participation
            manager.set_enabled("db2", True)
            self.assertTrue(db2.is_enabled)
            files_on, _, _ = await manager.search_media({}, {}, "title", 0, 10)
            self.assertEqual(len(files_on), 2)

        asyncio.run(run())

    def test_partial_outage_handling(self):
        """FR10: Clear handling of partial outages — if 1 DB fails, search doesn't crash."""
        async def run():
            manager = MultiMongoDBManager()
            db1 = create_mock_node("primary", "DB1", "mongodb://localhost/db1", initial_docs=[{"_id": "F1", "file_name": "A.mkv"}])
            db2 = create_mock_node("db2", "DB2", "mongodb://localhost/db2")
            
            # Simulate db2 find raising an unexpected error
            db2.collection.find = MagicMock(side_effect=RuntimeError("Cluster network unreachable"))
            manager.nodes["primary"] = db1
            manager.nodes["db2"] = db2

            # Search should safely catch DB2 error and return results from DB1
            files, _, total = await manager.search_media({}, {}, "title", 0, 10)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["_id"], "F1")

        asyncio.run(run())

    def test_bounded_retries_and_write_failover(self):
        """FR3 & FR10: Bounded retries and safe failover to next healthy DB when write fails."""
        async def run():
            manager = MultiMongoDBManager()
            # Primary will fail writes
            primary = create_mock_node("primary", "Primary DB", "mongodb://localhost/primary", priority=100)
            primary.collection.fail_writes = True
            
            # Secondary DB2 is healthy
            db2 = create_mock_node("db2", "DB 2", "mongodb://localhost/db2", priority=90)
            manager.nodes["primary"] = primary
            manager.nodes["db2"] = db2
            manager.active_target_id = "primary"

            mock_media = MagicMock()
            mock_media.file_id = "TEST_MEDIA_ID"
            mock_media.file_name = "Interstellar.2014.1080p.mkv"
            mock_media.file_size = 3000000000
            mock_media.file_type = "video"
            mock_media.mime_type = "video/x-matroska"
            mock_media.caption = None

            success, fid = await manager.save_media_file(
                mock_media,
                unpack_fn=lambda x: ("UNPACKED_FID", "REF"),
                clean_name_fn=lambda x: x,
            )

            self.assertTrue(success)
            self.assertEqual(fid, "UNPACKED_FID")
            # Document must be saved on DB2 after failover
            self.assertIn("UNPACKED_FID", db2.collection.docs)
            self.assertEqual(primary.collection.insert_calls, 2)  # Bounded retries (2 attempts)

        asyncio.run(run())

    def test_90_percent_threshold_alert_and_hysteresis(self):
        """FR8: At 90% threshold, send ONE alert, switch target, and do not repeat until below threshold."""
        async def run():
            manager = MultiMongoDBManager()
            primary = create_mock_node("primary", "Primary DB", "mongodb://localhost/primary", quota_mb=100.0)
            db2 = create_mock_node("db2", "Secondary DB 2", "mongodb://localhost/db2", quota_mb=100.0, priority=90)
            manager.nodes["primary"] = primary
            manager.nodes["db2"] = db2
            manager.active_target_id = "primary"

            alert_calls = []
            async def alert_callback(node, usage_pct, new_target, msg):
                alert_calls.append((node.id, usage_pct, new_target.id if new_target else None))

            manager.alert_callback = alert_callback

            # 1. Primary usage is at 92MB out of 100MB (92.0%) >= 90%
            primary.db.stats_return = {
                "dataSize": 80 * 1024 * 1024,
                "storageSize": 85 * 1024 * 1024,
                "indexSize": 7 * 1024 * 1024,
                "objects": 5000,
            }
            # total = 85 + 7 = 92MB -> 92.0%

            alerted = await manager.check_node_threshold(primary)
            self.assertTrue(alerted)
            self.assertEqual(len(alert_calls), 1)
            self.assertTrue(primary.last_alert_triggered)
            # Automatic failover switched active target to db2
            self.assertEqual(manager.active_target_id, "db2")

            # 2. Re-checking while still above 90% must NOT repeat alert
            alerted_again = await manager.check_node_threshold(primary)
            self.assertFalse(alerted_again)
            self.assertEqual(len(alert_calls), 1)  # No duplicate alert!

            # 3. Usage drops back down to 50MB (50.0%)
            primary.db.stats_return = {
                "dataSize": 40 * 1024 * 1024,
                "storageSize": 45 * 1024 * 1024,
                "indexSize": 5 * 1024 * 1024,
                "objects": 2500,
            }
            await manager.check_node_threshold(primary)
            # Hysteresis reset:
            self.assertFalse(primary.last_alert_triggered)

        asyncio.run(run())

    def test_unknown_quota_reported_when_unmeasurable(self):
        """FR8: If quota/usage cannot be measured reliably, report Unknown rather than guessing."""
        async def run():
            node = create_mock_node("db1", "DB1", "mongodb://localhost/db1", quota_mb=None)
            stats = await node.get_storage_stats()
            self.assertIsNone(stats["usage_percent"])  # Must be None (Unknown)
            
            report = {
                "total_dbs": 1,
                "active_target_id": "db1",
                "threshold_percent": 90.0,
                "nodes": [{
                    "id": "db1",
                    "name": "Cluster 1",
                    "masked_uri": "mongodb://localhost/db1",
                    "status_label": "ACTIVE",
                    "priority": 100,
                    "last_ping_ms": 12.5,
                    "doc_count": 5000,
                    "total_mb": 150.0,
                    "quota_mb": None,
                    "usage_percent": None,
                }]
            }
            text = format_multidb_dashboard_text(report)
            self.assertIn("Quota: Unknown", text)

        asyncio.run(run())

    def test_zero_colour_emojis_in_admin_keyboards(self):
        """Strict Rule: ZERO colour emojis in button labels."""
        main_kb = build_multidb_main_keyboard()
        colour_emojis = ["🔴", "🟢", "🟡", "🔵", "🟣", "🟠", "⚪", "⚫", "🟥", "🟩", "🟨", "🟦"]
        
        for row in main_kb.inline_keyboard:
            for btn in row:
                for emoji in colour_emojis:
                    self.assertNotIn(emoji, btn.text, f"Found colour emoji {emoji} in button {btn.text}")

        nodes = [
            {"id": "primary", "name": "Primary DB", "is_enabled": True, "is_active_target": True},
            {"id": "db2", "name": "Secondary DB 2", "is_enabled": True, "is_active_target": False},
        ]
        target_kb = build_multidb_switch_target_keyboard(nodes)
        for row in target_kb.inline_keyboard:
            for btn in row:
                for emoji in colour_emojis:
                    self.assertNotIn(emoji, btn.text)

        toggle_kb = build_multidb_toggle_keyboard(nodes)
        for row in toggle_kb.inline_keyboard:
            for btn in row:
                for emoji in colour_emojis:
                    self.assertNotIn(emoji, btn.text)


if __name__ == "__main__":
    unittest.main()
