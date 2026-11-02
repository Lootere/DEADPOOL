import asyncio
import importlib.util
from pathlib import Path
import unittest
from dataclasses import dataclass
from typing import Any, Dict, Optional

_ENGINE_PATH = (
    Path(__file__).resolve().parent.parent / "Lootere" / "utils" / "smart_search_engine.py"
)
_SPEC = importlib.util.spec_from_file_location("smart_search_engine", _ENGINE_PATH)
smart_search_engine = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(smart_search_engine)

DEFAULT_MOVIE_STYLE = smart_search_engine.DEFAULT_MOVIE_STYLE
DEFAULT_PREVIEW_ENABLED = smart_search_engine.DEFAULT_PREVIEW_ENABLED
DEFAULT_SERIES_STYLE = smart_search_engine.DEFAULT_SERIES_STYLE
STYLE_NAMES = smart_search_engine.STYLE_NAMES
cancel_pending_style_preview = smart_search_engine.cancel_pending_style_preview
clean_promotional_filename = smart_search_engine.clean_promotional_filename
confirm_pending_style_preview = smart_search_engine.confirm_pending_style_preview
format_size_gb = smart_search_engine.format_size_gb
format_smart_search_file_blocks = smart_search_engine.format_smart_search_file_blocks
format_smart_summary_line = smart_search_engine.format_smart_summary_line
get_smart_style_config = smart_search_engine.get_smart_style_config
parse_smart_media_item = smart_search_engine.parse_smart_media_item
render_smart_result_entry = smart_search_engine.render_smart_result_entry
select_smart_text_style = smart_search_engine.select_smart_text_style
set_style_preview_enabled = smart_search_engine.set_style_preview_enabled


class FakeDB:
    def __init__(self):
        self.store: Dict[str, Any] = {}

    async def get_setting(self, key: str, default: Any = None) -> Any:
        return self.store.get(key, default)

    async def set_setting(self, key: str, value: Any) -> None:
        self.store[key] = value


@dataclass
class FakeMediaRecord:
    file_id: str
    file_name: str
    file_size: int
    caption: Optional[str] = None
    file_ref: Optional[str] = "ref_123"


class TestFeature2SmartSearchEngine(unittest.TestCase):
    def test_prd_target_examples_exact_match(self):
        # Movie target example: `1.45GB | 1080p • Movie Name • 2025`
        movie_bytes = int(round(1.45 * (1024 ** 3)))
        movie_item = parse_smart_media_item(
            "[Join @RKMoviesZip] Movie.Name.2025.1080p.WEB-DL.x264.mkv",
            file_size=movie_bytes,
        )
        self.assertEqual(movie_item.category, "movie")
        self.assertEqual(movie_item.size_gb, "1.45GB")
        self.assertEqual(movie_item.quality, "1080p")
        self.assertEqual(movie_item.title, "Movie Name")
        self.assertEqual(movie_item.year, "2025")
        self.assertIsNone(movie_item.language)
        self.assertEqual(
            format_smart_summary_line(movie_item),
            "1.45GB | 1080p • Movie Name • 2025",
        )

        # Series target example: `0.62GB | E01 S21 • Roadies Rebirth 2026`
        series_bytes = int(round(0.62 * (1024 ** 3)))
        series_item = parse_smart_media_item(
            "@Lootere_Uploads Roadies.Rebirth.2026.S21E01.WEB-DL.x264.mkv",
            file_size=series_bytes,
        )
        self.assertEqual(series_item.category, "series")
        self.assertEqual(series_item.size_gb, "0.62GB")
        self.assertEqual(series_item.episode_code, "E01 S21")
        self.assertIsNone(series_item.quality)
        self.assertIsNone(series_item.language)
        self.assertEqual(
            format_smart_summary_line(series_item),
            "0.62GB | E01 S21 • Roadies Rebirth 2026",
        )

    def test_conservative_cleaning_and_numeric_title_preservation(self):
        # Numeric movie title with release year
        item_1917 = parse_smart_media_item(
            "[www.1TamilMV.tf] 1917 (2019) 1080p BluRay x264.mkv",
            file_size=int(round(2.10 * (1024 ** 3))),
        )
        self.assertEqual(item_1917.title, "1917")
        self.assertEqual(item_1917.year, "2019")
        self.assertEqual(item_1917.quality, "1080p")
        self.assertIsNone(item_1917.language)
        self.assertEqual(
            format_smart_summary_line(item_1917),
            "2.10GB | 1080p • 1917 • 2019",
        )

        # Numeric movie title without release year must NOT lose its title
        item_1917_no_year = parse_smart_media_item(
            "1917.720p.WEB-DL.mkv",
            file_size=int(round(0.95 * (1024 ** 3))),
        )
        self.assertEqual(item_1917_no_year.title, "1917")
        self.assertIsNone(item_1917_no_year.year)
        self.assertEqual(item_1917_no_year.quality, "720p")
        self.assertEqual(
            format_smart_summary_line(item_1917_no_year),
            "0.95GB | 720p • 1917",
        )

        # Title containing a year-like number + actual release year
        ww84 = parse_smart_media_item(
            "Wonder.Woman.1984.2020.1080p.Hindi.mkv",
            file_size=int(round(1.80 * (1024 ** 3))),
        )
        self.assertEqual(ww84.title, "Wonder Woman 1984")
        self.assertEqual(ww84.year, "2020")
        self.assertEqual(ww84.quality, "1080p")
        self.assertEqual(ww84.language, "Hindi")

        # Title containing word "English" must not fabricate language when no audio language tag exists
        johnny = parse_smart_media_item(
            "Johnny.English.2003.720p.BluRay.mkv",
            file_size=int(round(1.10 * (1024 ** 3))),
        )
        self.assertEqual(johnny.title, "Johnny English")
        self.assertEqual(johnny.year, "2003")
        self.assertIsNone(johnny.language)

    def test_persisted_records_never_mutated(self):
        record = FakeMediaRecord(
            file_id="f_immutable_1",
            file_name="[Join @PromoChannel] Pushpa.2.2024.1080p.Hindi.mkv",
            file_size=int(round(2.50 * (1024 ** 3))),
            caption="Original Caption",
            file_ref="original_ref",
        )
        snapshot = (
            record.file_id,
            record.file_name,
            record.file_size,
            record.caption,
            record.file_ref,
        )

        parsed = parse_smart_media_item(record)
        self.assertEqual(parsed.title, "Pushpa 2")
        self.assertEqual(parsed.language, "Hindi")

        rendered = asyncio.run(
            format_smart_search_file_blocks(
                [record],
                chat_id=-10012345,
                bot_username="RKMoviesBot",
                db_instance=FakeDB(),
            )
        )
        self.assertIn("2.50GB | 1080p • Pushpa 2 • 2024 • Hindi", rendered)

        # Confirm persisted record attributes were never mutated
        self.assertEqual(
            (
                record.file_id,
                record.file_name,
                record.file_size,
                record.caption,
                record.file_ref,
            ),
            snapshot,
        )

    def test_all_10_styles_for_movies_and_series_and_single_link_rule(self):
        self.assertEqual(len(STYLE_NAMES), 10)
        self.assertEqual(DEFAULT_MOVIE_STYLE, 7)
        self.assertEqual(DEFAULT_SERIES_STYLE, 10)
        self.assertTrue(DEFAULT_PREVIEW_ENABLED)

        movie_item = parse_smart_media_item(
            "Movie.Name.2025.1080p.mkv",
            file_size=int(round(1.45 * (1024 ** 3))),
        )
        ep1_item = parse_smart_media_item(
            "Roadies.Rebirth.2026.S21E01.mkv",
            file_size=int(round(0.62 * (1024 ** 3))),
        )
        ep2_item = parse_smart_media_item(
            "Roadies.Rebirth.2026.S21E02.mkv",
            file_size=int(round(0.64 * (1024 ** 3))),
        )

        for style_id in range(1, 11):
            m_html = render_smart_result_entry(
                movie_item,
                file_url="https://telegram.me/Bot?start=files_1_m1",
                style_id=style_id,
                index=1,
            )
            s1_html = render_smart_result_entry(
                ep1_item,
                file_url="https://telegram.me/Bot?start=files_1_s1",
                style_id=style_id,
                index=1,
            )
            s2_html = render_smart_result_entry(
                ep2_item,
                file_url="https://telegram.me/Bot?start=files_1_s2",
                style_id=style_id,
                index=2,
            )

            # Exactly one clickable link per result (no duplicate download link)
            self.assertEqual(m_html.count("<a "), 1, f"Style {style_id} movie has duplicate links")
            self.assertEqual(s1_html.count("<a "), 1, f"Style {style_id} series has duplicate links")
            self.assertIn("1.45GB", m_html)
            self.assertIn("0.62GB", s1_html)

            # Each series episode has its own distinct clickable title
            s1_first_line = s1_html.splitlines()[0]
            s2_first_line = s2_html.splitlines()[0]
            self.assertNotEqual(s1_first_line, s2_first_line)
            self.assertIn("E01 S21", s1_first_line)
            self.assertIn("E02 S21", s2_first_line)

    def test_preview_before_apply_and_cancel_preserves_previous_setting(self):
        fake_db = FakeDB()
        scope = "test_scope"

        async def _run_workflow():
            initial = await get_smart_style_config(db_instance=fake_db, scope=scope)
            self.assertEqual(initial["movie_style"], 7)
            self.assertEqual(initial["series_style"], 10)
            self.assertTrue(initial["preview_enabled"])

            # 1. Select Movie style 3 while preview is ON -> should NOT apply yet
            preview_res = await select_smart_text_style(
                admin_id=999,
                category="movie",
                style_value=3,
                db_instance=fake_db,
                scope=scope,
            )
            self.assertEqual(preview_res["status"], "preview_pending")
            self.assertEqual(preview_res["candidate_style_id"], 3)
            self.assertEqual(preview_res["active_style_id"], 7)

            # Active config must still be 7
            during_preview = await get_smart_style_config(db_instance=fake_db, scope=scope)
            self.assertEqual(during_preview["movie_style"], 7)

            # 2. Cancel preview -> active style must remain 7
            cancel_res = await cancel_pending_style_preview(
                admin_id=999,
                db_instance=fake_db,
                scope=scope,
            )
            self.assertEqual(cancel_res["status"], "cancelled")
            self.assertEqual(cancel_res["config"]["movie_style"], 7)

            # 3. Select Movie style 4 and confirm/apply -> active style becomes 4
            await select_smart_text_style(
                admin_id=999,
                category="movie",
                style_value=4,
                db_instance=fake_db,
                scope=scope,
            )
            apply_res = await confirm_pending_style_preview(
                admin_id=999,
                db_instance=fake_db,
                scope=scope,
            )
            self.assertEqual(apply_res["status"], "applied")
            self.assertEqual(apply_res["active_style_id"], 4)
            self.assertEqual(apply_res["config"]["movie_style"], 4)
            # Series style must remain independent (still 10)
            self.assertEqual(apply_res["config"]["series_style"], 10)

            # 4. Disable preview -> selecting Series style 6 applies immediately
            await set_style_preview_enabled(False, db_instance=fake_db, scope=scope)
            direct_res = await select_smart_text_style(
                admin_id=999,
                category="series",
                style_value=6,
                db_instance=fake_db,
                scope=scope,
            )
            self.assertEqual(direct_res["status"], "applied")
            self.assertEqual(direct_res["active_style_id"], 6)

        asyncio.run(_run_workflow())


if __name__ == "__main__":
    unittest.main()
