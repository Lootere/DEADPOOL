import importlib.util
import os
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

UTILS_DIR = ROOT / "Lootere" / "utils"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_lootere_pkg = sys.modules.setdefault("Lootere", types.ModuleType("Lootere"))
_lootere_pkg.__path__ = [str(ROOT / "Lootere")]
_utils_pkg = sys.modules.setdefault("Lootere.utils", types.ModuleType("Lootere.utils"))
_utils_pkg.__path__ = [str(UTILS_DIR)]

if "Lootere.utils.smart_search_engine" not in sys.modules:
    _load_module(
        "Lootere.utils.smart_search_engine",
        UTILS_DIR / "smart_search_engine.py",
    )

_formatter = _load_module(
    "Lootere.utils.file_button_formatter",
    UTILS_DIR / "file_button_formatter.py",
)
MAX_BUTTON_TEXT_LENGTH = _formatter.MAX_BUTTON_TEXT_LENGTH
format_file_result_button = _formatter.format_file_result_button

MB = 1024 ** 2
GB = 1024 ** 3


class MovieButtonTests(unittest.TestCase):
    def test_mb_size_two_decimals_and_720p(self):
        label = format_file_result_button(
            "Movie.Name.2024.720p.mkv", int(700 * MB)
        )
        self.assertEqual(label, "[700.00 MB] [720p] Movie Name [2024]")

    def test_gb_size_two_decimals(self):
        label = format_file_result_button(
            "Example.Movie.2025.1080p.WEB-DL.Hindi.mkv", int(1.45 * GB)
        )
        self.assertEqual(
            label,
            "[1.45 GB] [1080p WEB-DL] Example Movie [2025] [Hindi]",
        )

    def test_1080p_dual_language(self):
        label = format_file_result_button(
            "Example.Movie.2025.1080p.Hindi.English.mkv", int(1.4 * GB)
        )
        self.assertIn("[1080p]", label)
        self.assertIn("[Hindi + English]", label)

    def test_2160p_bluray(self):
        label = format_file_result_button(
            "Example.Movie.2025.2160p.BluRay.HEVC.HDR.Multi.Audio.mkv",
            int(2.30 * GB),
        )
        self.assertTrue(label.startswith("[2.30 GB] [2160p BluRay"))
        self.assertIn("Example Movie", label)
        self.assertIn("[2025]", label)
        self.assertIn("[Multi Audio]", label)

    def test_missing_year(self):
        label = format_file_result_button(
            "Example.Movie.1080p.WEB-DL.Hindi.mkv", int(1.2 * GB)
        )
        self.assertEqual(label, "[1.20 GB] [1080p WEB-DL] Example Movie [Hindi]")

    def test_missing_language(self):
        label = format_file_result_button(
            "Example.Movie.2025.1080p.mkv", int(1.2 * GB)
        )
        self.assertEqual(label, "[1.20 GB] [1080p] Example Movie [2025]")

    def test_missing_quality(self):
        label = format_file_result_button(
            "Example.Movie.2025.Hindi.mkv", int(700 * MB)
        )
        self.assertEqual(label, "[700.00 MB] Example Movie [2025] [Hindi]")

    def test_title_numbers_and_special_characters(self):
        label = format_file_result_button(
            "Spider-Man.No.Way.Home.2021.1080p.Hindi.mkv", int(1.1 * GB)
        )
        self.assertIn("Spider-Man No Way Home", label)
        self.assertIn("[2021]", label)

    def test_title_year_is_not_lost(self):
        label = format_file_result_button(
            "Wonder.Woman.1984.2020.1080p.BluRay.English.mkv", int(1.2 * GB)
        )
        self.assertIn("Wonder Woman 1984", label)
        self.assertIn("[2020]", label)


class SeriesButtonTests(unittest.TestCase):
    def test_s01e01(self):
        label = format_file_result_button(
            "Akka.The.Protectors.S01E01.1080p.2026.Hindi.mkv",
            int(820.44 * MB),
        )
        self.assertEqual(
            label,
            "[820.44 MB] [1080p] Akka The Protectors S01E01 [2026] [Hindi]",
        )

    def test_s01e02_is_distinct(self):
        label = format_file_result_button(
            "Akka.The.Protectors.S01E02.1080p.2026.Hindi.mkv",
            int(820.44 * MB),
        )
        self.assertIn("S01E02", label)
        self.assertNotIn("S01E01", label)

    def test_multiple_seasons(self):
        label = format_file_result_button(
            "Show.Name.S02.E03.2025.720p.Hindi.mkv", int(300 * MB)
        )
        self.assertIn("Show Name S02E03", label)
        self.assertIn("[2025]", label)

    def test_spelled_season_episode(self):
        label = format_file_result_button(
            "Show.Name.Season.1.Episode.2.2025.720p.Hindi.mkv",
            int(300 * MB),
        )
        self.assertIn("Show Name S01E02", label)

    def test_series_gb_size(self):
        label = format_file_result_button(
            "Show.Name.S02.E03.2025.WEB-DL.English.mkv", int(1.2 * GB)
        )
        self.assertTrue(label.startswith("[1.20 GB] [WEB-DL]"))
        self.assertIn("Show Name S02E03", label)

    def test_series_missing_metadata(self):
        label = format_file_result_button(
            "Show.Name.S01E01.mkv", int(500 * MB)
        )
        self.assertEqual(label, "[500.00 MB] Show Name S01E01")


class LabelSafetyTests(unittest.TestCase):
    def test_never_exceeds_telegram_limit(self):
        label = format_file_result_button(
            "A.Very.Long.Movie.Title.That.Keeps.Going.And.Going.2025.1080p.WEB-DL.Hindi.English.mkv",
            int(1.45 * GB),
        )
        self.assertLessEqual(len(label), MAX_BUTTON_TEXT_LENGTH)

    def test_no_empty_or_unknown_brackets(self):
        for name in (
            "Movie.Name.mkv",
            "Movie.Name.Hindi.mkv",
            "Movie.Name.1080p.mkv",
        ):
            label = format_file_result_button(name, int(700 * MB))
            self.assertNotIn("[]", label)
            self.assertNotIn("N/A", label)
            self.assertNotIn("Unknown", label)

    def test_size_rounding(self):
        label = format_file_result_button(
            "Movie.2025.mkv", int(486.714 * MB)
        )
        self.assertTrue(label.startswith("[486.71 MB]"))


class ScopeAuditTests(unittest.TestCase):
    def test_only_file_result_buttons_use_formatter(self):
        source = (ROOT / "plugins" / "pm_filter.py").read_text(encoding="utf-8")
        self.assertNotIn(
            'text=f"[{get_size(file.file_size)}] {file.file_name}"', source
        )
        self.assertEqual(
            source.count("format_file_result_button(file.file_name, file.file_size)"),
            source.count("files#{file.file_id}"),
        )

    def test_non_file_button_builders_are_not_touched(self):
        source = (ROOT / "plugins" / "pm_filter.py").read_text(encoding="utf-8")
        formatter_lines = [
            line for line in source.splitlines() if "format_file_result_button(" in line
        ]
        for line in formatter_lines:
            self.assertTrue(
                re.search(r"text\s*=\s*format_file_result_button\(file\.file_name, file\.file_size\)", line)
                or "def " in line
                or "import" in line
            )


if __name__ == "__main__":
    unittest.main()
