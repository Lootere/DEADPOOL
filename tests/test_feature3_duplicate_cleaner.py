import asyncio
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent

# Register Lootere and Lootere.utils if not present
if "Lootere" not in sys.modules:
    sys.modules["Lootere"] = types.ModuleType("Lootere")
if "Lootere.utils" not in sys.modules:
    sys.modules["Lootere.utils"] = types.ModuleType("Lootere.utils")

# Load smart_search_engine
_SSE_PATH = _ROOT / "Lootere" / "utils" / "smart_search_engine.py"
_SSE_SPEC = importlib.util.spec_from_file_location("Lootere.utils.smart_search_engine", _SSE_PATH)
smart_search_engine = importlib.util.module_from_spec(_SSE_SPEC)
assert _SSE_SPEC and _SSE_SPEC.loader
sys.modules["Lootere.utils.smart_search_engine"] = smart_search_engine
_SSE_SPEC.loader.exec_module(smart_search_engine)

# Load duplicate_cleaner
_DC_PATH = _ROOT / "Lootere" / "utils" / "duplicate_cleaner.py"
_DC_SPEC = importlib.util.spec_from_file_location("Lootere.utils.duplicate_cleaner", _DC_PATH)
duplicate_cleaner = importlib.util.module_from_spec(_DC_SPEC)
assert _DC_SPEC and _DC_SPEC.loader
sys.modules["Lootere.utils.duplicate_cleaner"] = duplicate_cleaner
_DC_SPEC.loader.exec_module(duplicate_cleaner)

cancel_duplicate_cleanup = duplicate_cleaner.cancel_duplicate_cleanup
classify_duplicate_pair = duplicate_cleaner.classify_duplicate_pair
execute_duplicate_cleanup = duplicate_cleaner.execute_duplicate_cleanup
find_duplicate_groups = duplicate_cleaner.find_duplicate_groups
format_duplicate_preview_text = duplicate_cleaner.format_duplicate_preview_text
get_duplicate_mode = duplicate_cleaner.get_duplicate_mode
normalize_filename_key = duplicate_cleaner.normalize_filename_key
normalize_title_key = duplicate_cleaner.normalize_title_key
scan_duplicates_preview = duplicate_cleaner.scan_duplicates_preview
select_canonical_winner = duplicate_cleaner.select_canonical_winner
set_duplicate_mode = duplicate_cleaner.set_duplicate_mode
should_auto_skip_exact_duplicate = duplicate_cleaner.should_auto_skip_exact_duplicate
to_duplicate_item = duplicate_cleaner.to_duplicate_item
DuplicateItem = duplicate_cleaner.DuplicateItem


@dataclass
class MockMedia:
    file_id: str
    file_name: str
    file_size: int
    caption: Optional[str] = None
    file_ref: Optional[str] = "ref_123"
    file_type: str = "video"
    mime_type: str = "video/mp4"


class MockCollection:
    def __init__(self, docs: List[Dict[str, Any]]):
        self.docs = docs

    async def delete_many(self, query: Dict[str, Any]):
        in_ids = query.get("_id", {}).get("$in", [])
        before = len(self.docs)
        self.docs = [d for d in self.docs if (d.get("_id") or d.get("file_id")) not in in_ids]
        deleted = before - len(self.docs)
        return type("DeleteResult", (), {"deleted_count": deleted})()

    async def find_one(self, query: Dict[str, Any]):
        for d in self.docs:
            match = True
            for k, v in query.items():
                if d.get(k) != v:
                    match = False
                    break
            if match:
                return d
        return None


class MockMediaModel:
    collection = MockCollection([])

    @classmethod
    def find(cls, query: Optional[Dict[str, Any]] = None):
        cls_docs = cls.collection.docs
        if query and "file_name" in query:
            pat = query["file_name"]
            filtered = [d for d in cls_docs if pat.search(d.get("file_name", ""))]
        else:
            filtered = list(cls_docs)

        class MockCursor:
            def __init__(self, data):
                self.data = data

            def limit(self, n):
                return MockCursor(self.data[:n])

            async def to_list(self, length=1000):
                return self.data[:length]

        return MockCursor(filtered)


class MockDB:
    def __init__(self):
        self.settings: Dict[str, Any] = {}

    async def get_setting(self, key: str, default: Any = None):
        return self.settings.get(key, default)

    async def set_setting(self, key: str, value: Any):
        self.settings[key] = value


class TestFeature3DuplicateCleaner(unittest.TestCase):
    def test_exact_duplicate_classification(self):
        # Exact duplicate by file_id
        item1 = to_duplicate_item(MockMedia("id_1", "Inception 2010 1080p.mkv", 2000000000))
        item2 = to_duplicate_item(MockMedia("id_1", "Inception 2010 1080p.mkv", 2000000000))
        self.assertEqual(classify_duplicate_pair(item1, item2), "exact")

        # Exact duplicate by normalized filename and exact file size
        item3 = to_duplicate_item(MockMedia("id_2", "Inception.2010.1080p.mkv", 2000000000))
        item4 = to_duplicate_item(MockMedia("id_3", "[Join @RKMovies] Inception 2010 1080p.mkv", 2000000000))
        self.assertEqual(classify_duplicate_pair(item3, item4), "exact")

    def test_near_duplicate_classification(self):
        # Same movie, same year, same resolution (1080p), same language (Hindi), size within 2%
        size_a = 2000000000
        size_b = int(size_a * 1.01)  # 1% difference
        item_a = to_duplicate_item(MockMedia("id_a", "Jawan 2023 1080p Hindi HDRip x264.mkv", size_a))
        item_b = to_duplicate_item(MockMedia("id_b", "[@Channel] Jawan (2023) 1080p Hindi WEB-DL x264.mkv", size_b))
        self.assertEqual(classify_duplicate_pair(item_a, item_b), "near")

    def test_strict_non_collision_rules(self):
        base_size = 2000000000

        # Rule 1: Different resolutions (1080p vs 720p vs 480p) must NEVER be duplicates!
        item_1080p = to_duplicate_item(MockMedia("f1", "Interstellar 2014 1080p BluRay.mkv", base_size))
        item_720p = to_duplicate_item(MockMedia("f2", "Interstellar 2014 720p BluRay.mkv", base_size))
        item_480p = to_duplicate_item(MockMedia("f3", "Interstellar 2014 480p BluRay.mkv", base_size))
        item_4k = to_duplicate_item(MockMedia("f4", "Interstellar 2014 4K UHD.mkv", base_size))

        self.assertIsNone(classify_duplicate_pair(item_1080p, item_720p))
        self.assertIsNone(classify_duplicate_pair(item_1080p, item_480p))
        self.assertIsNone(classify_duplicate_pair(item_720p, item_4k))

        # Rule 2: Different episodes (S01E01 vs S01E02) must NEVER be duplicates!
        ep1 = to_duplicate_item(MockMedia("ep1", "Breaking Bad S01E01 720p.mkv", 500000000))
        ep2 = to_duplicate_item(MockMedia("ep2", "Breaking Bad S01E02 720p.mkv", 500000000))
        self.assertIsNone(classify_duplicate_pair(ep1, ep2))

        # Rule 3: Different seasons (S01E01 vs S02E01) must NEVER be duplicates!
        s1e1 = to_duplicate_item(MockMedia("s1", "Loki S01E01 1080p.mkv", 900000000))
        s2e1 = to_duplicate_item(MockMedia("s2", "Loki S02E01 1080p.mkv", 900000000))
        self.assertIsNone(classify_duplicate_pair(s1e1, s2e1))

        # Rule 4: Different languages (Hindi vs Tamil vs English) must NEVER be duplicates!
        hin = to_duplicate_item(MockMedia("l1", "Leo 2023 1080p Hindi.mkv", base_size))
        tam = to_duplicate_item(MockMedia("l2", "Leo 2023 1080p Tamil.mkv", base_size))
        dual = to_duplicate_item(MockMedia("l3", "Leo 2023 1080p Dual Audio.mkv", base_size))
        self.assertIsNone(classify_duplicate_pair(hin, tam))
        self.assertIsNone(classify_duplicate_pair(hin, dual))

        # Rule 5: Large size difference (>2.5%) must NOT be near duplicates
        small = to_duplicate_item(MockMedia("s", "Dune 2021 1080p.mkv", 1000000000))
        large = to_duplicate_item(MockMedia("l", "Dune 2021 1080p.mkv", 3500000000))
        self.assertIsNone(classify_duplicate_pair(small, large))

    def test_canonical_winner_selection(self):
        doc1 = to_duplicate_item(MockMedia("w1", "KGF Chapter 2 2022 1080p.mkv", 2000000000, caption="Official", file_ref="valid_ref"))
        doc2 = to_duplicate_item(MockMedia("w2", "KGF Chapter 2 2022 1080p.mkv", 2000000000, caption=None, file_ref=None))
        doc3 = to_duplicate_item(MockMedia("w3", "KGF Chapter 2 2022 1080p.mkv", 2000000000, caption=None, file_ref="valid_ref"))

        winner, dups = select_canonical_winner([doc1, doc2, doc3])
        # doc1 has both caption and file_ref, so it must win
        self.assertEqual(winner.file_id, "w1")
        self.assertEqual({d.file_id for d in dups}, {"w2", "w3"})

    def test_find_duplicate_groups(self):
        records = [
            # Exact duplicate pair
            MockMedia("id_1", "Pushpa 2 2024 1080p Hindi.mkv", 1800000000),
            MockMedia("id_2", "Pushpa.2.2024.1080p.Hindi.mkv", 1800000000),
            # Single distinct file (720p)
            MockMedia("id_3", "Pushpa 2 2024 720p Hindi.mkv", 900000000),
            # Near duplicate pair (size within 1%)
            MockMedia("id_4", "Animal 2023 1080p Hindi WEB-DL.mkv", 2500000000),
            MockMedia("id_5", "[@Promo] Animal 2023 1080p Hindi HDRip.mkv", 2510000000),
            # Single episode
            MockMedia("id_6", "Farzi S01E01 1080p.mkv", 1200000000),
            MockMedia("id_7", "Farzi S01E02 1080p.mkv", 1200000000),
        ]

        groups = find_duplicate_groups(records)
        # Must have exactly 2 duplicate groups (Pushpa 2 exact, Animal near)
        # id_3 (720p) and Farzi ep1/ep2 must NEVER be in any duplicate group!
        self.assertEqual(len(groups), 2)
        group_types = {g.group_type for g in groups}
        self.assertEqual(group_types, {"exact", "near"})

        for g in groups:
            # Winner must be distinct and not in duplicates
            self.assertNotIn(g.winner.file_id, [d.file_id for d in g.duplicates])
            # None of the 720p or series episode files can be duplicates
            all_ids = {g.winner.file_id} | {d.file_id for d in g.duplicates}
            self.assertNotIn("id_3", all_ids)
            self.assertNotIn("id_6", all_ids)
            self.assertNotIn("id_7", all_ids)

    def test_dry_run_preview_and_cleanup_workflow(self):
        async def _run():
            fake_db = MockDB()

            # Verify default mode is preview
            mode = await get_duplicate_mode(db_instance=fake_db)
            self.assertEqual(mode, "preview")

            # Toggle modes
            await set_duplicate_mode("auto_exact", db_instance=fake_db)
            self.assertEqual(await get_duplicate_mode(db_instance=fake_db), "auto_exact")
            await set_duplicate_mode("preview", db_instance=fake_db)

            # Test preview generation
            records = [
                {"_id": "doc1", "file_name": "Avatar 2009 1080p.mkv", "file_size": 3000000000},
                {"_id": "doc2", "file_name": "Avatar.2009.1080p.mkv", "file_size": 3000000000},
            ]
            groups = find_duplicate_groups(records)
            self.assertEqual(len(groups), 1)

            # Cancel cleanup test
            session_id = "test_sess_1"
            from Lootere.utils import duplicate_cleaner
            duplicate_cleaner._PENDING_CLEANUP_SESSIONS[session_id] = {
                "session_id": session_id,
                "groups": groups,
                "reclaimable_bytes": 3000000000,
            }
            self.assertTrue(cancel_duplicate_cleanup(session_id))
            self.assertNotIn(session_id, duplicate_cleaner._PENDING_CLEANUP_SESSIONS)

            # Preview formatting check
            preview_data = {
                "total_scanned": 100,
                "total_groups": 1,
                "total_duplicates": 1,
                "exact_duplicates": 1,
                "near_duplicates": 0,
                "reclaimable_gb": "2.79GB",
                "display_groups": groups,
            }
            preview_text = format_duplicate_preview_text(preview_data, mode="preview")
            self.assertIn("Smart Duplicate Cleaner Dashboard", preview_text)
            self.assertIn("Winner [KEPT]", preview_text)
            self.assertIn("Duplicate [REMOVE]", preview_text)
            # Ensure zero colour-indicator circle/square emojis in generated text
            for emoji in ("🔴", "🔵", "🟢", "🟡"):
                self.assertNotIn(emoji, preview_text)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
