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

FORBIDDEN_TECH_TOKENS = (
    "WEB-DL",
    "WEBRip",
    "BluRay",
    "BDRip",
    "HDRip",
    "HDTV",
    "HDR",
    "HEVC",
    "x264",
    "x265",
    "AVC",
    "DV",
    "AAC",
)


class SizeAlwaysGigabytesTests(unittest.TestCase):
    def test_reference_sizes_are_gb_two_decimals(self):
        cases = {
            int(80.72 * MB): "0.08 GB",
            int(96.67 * MB): "0.09 GB",
            int(315.51 * MB): "0.31 GB",
            int(486.71 * MB): "0.48 GB",
            int(820.44 * MB): "0.80 GB",
            int(1.45 * GB): "1.45 GB",
        }
        for size_bytes, expected in cases.items():
            label = format_file_result_button("Sample.Movie.2025.mkv", size_bytes)
            self.assertTrue(
                label.startswith(f"{expected} | "),
                f"{size_bytes} -> {label!r}",
            )

    def test_never_displays_megabytes(self):
        for size_mb in (10, 99, 100, 500, 999, 1023):
            label = format_file_result_button(
                "Sample.Movie.2025.720p.Hindi.mkv", int(size_mb * MB)
            )
            self.assertNotIn("MB", label)
            self.assertRegex(label, r"^\d+\.\d{2} GB")

    def test_rounding_half_up(self):
        label = format_file_result_button("Movie.2025.mkv", int(486.714 * MB))
        self.assertTrue(label.startswith("0.48 GB | "), label)

    def test_size_is_always_first_segment(self):
        label = format_file_result_button(
            "Example.Movie.2025.1080p.WEB-DL.Hindi.mkv", int(1.45 * GB)
        )
        self.assertRegex(label, r"^\d+\.\d{2} GB \| ")


class ResolutionOnlyTests(unittest.TestCase):
    def test_movie_exact_reference_layout(self):
        label = format_file_result_button(
            "Example.Movie.2025.1080p.WEB-DL.Hindi.mkv", int(1.45 * GB)
        )
        self.assertEqual(label, "1.45 GB | 1080p | Example Movie 2025 [Hindi]")

    def test_series_exact_reference_layout(self):
        label = format_file_result_button(
            "Akka.2026.S01E01.1080p.Hindi.mkv", int(0.66 * GB)
        )
        self.assertEqual(
            label, "0.66 GB | 1080p | E01 S01 • Akka 2026 Season 1 [Hindi]"
        )

    def test_series_second_reference_layout(self):
        label = format_file_result_button(
            "Akka.2026.S01E02.720p.Hindi.mkv", int(0.46 * GB)
        )
        self.assertEqual(
            label, "0.46 GB | 720p | E02 S01 • Akka 2026 Season 1 [Hindi]"
        )

    def test_source_and_codec_tags_are_never_visible(self):
        names = (
            "Example.Movie.2025.1080p.WEB-DL.Hindi.mkv",
            "Example.Movie.2025.1080p.WEBRip.Hindi.mkv",
            "Example.Movie.2025.1080p.BluRay.HEVC.Hindi.mkv",
            "Example.Movie.2025.1080p.BDRip.x264.Hindi.mkv",
            "Example.Movie.2025.720p.HDRip.AVC.Hindi.mkv",
            "Example.Movie.2025.720p.HDTV.Hindi.mkv",
            "Example.Movie.2025.2160p.HDR.DV.x265.Hindi.mkv",
        )
        for name in names:
            label = format_file_result_button(name, int(1.1 * GB))
            for token in FORBIDDEN_TECH_TOKENS:
                self.assertNotIn(token, label, f"{token} leaked into {label!r}")

    def test_only_allowed_resolutions_appear(self):
        cases = {
            "Movie.2025.480p.Hindi.mkv": "480p",
            "Movie.2025.720p.Hindi.mkv": "720p",
            "Movie.2025.1080p.Hindi.mkv": "1080p",
            "Movie.2025.2160p.Hindi.mkv": "2160p",
            "Movie.2025.4K.Hindi.mkv": "4K",
        }
        for name, expected in cases.items():
            label = format_file_result_button(name, int(1.0 * GB))
            self.assertIn(f"| {expected} |", label)

    def test_missing_resolution_is_omitted(self):
        label = format_file_result_button(
            "Example.Movie.2025.Hindi.mkv", int(1.2 * GB)
        )
        self.assertEqual(label, "1.20 GB | Example Movie 2025 [Hindi]")
        self.assertNotIn("|  |", label)

    def test_1080p_hq_is_reduced_to_resolution(self):
        label = format_file_result_button(
            "Example.Movie.2025.1080p.HQ.Hindi.mkv", int(1.2 * GB)
        )
        self.assertIn("| 1080p |", label)
        self.assertNotIn("HQ", label)


class MovieFormatTests(unittest.TestCase):
    def test_movie_720p_two_languages(self):
        label = format_file_result_button(
            "Example.Movie.2024.720p.Hindi.English.mkv", int(0.85 * GB)
        )
        self.assertEqual(
            label, "0.85 GB | 720p | Example Movie 2024 [Hindi + English]"
        )

    def test_movie_missing_year(self):
        label = format_file_result_button(
            "Example.Movie.1080p.Hindi.mkv", int(1.2 * GB)
        )
        self.assertEqual(label, "1.20 GB | 1080p | Example Movie [Hindi]")

    def test_movie_missing_language(self):
        label = format_file_result_button(
            "Example.Movie.2025.1080p.mkv", int(1.2 * GB)
        )
        self.assertEqual(label, "1.20 GB | 1080p | Example Movie 2025")

    def test_movie_missing_quality_and_language(self):
        label = format_file_result_button("Example.Movie.2025.mkv", int(0.5 * GB))
        self.assertEqual(label, "0.50 GB | Example Movie 2025")

    def test_multi_audio(self):
        label = format_file_result_button(
            "Example.Movie.2025.2160p.BluRay.HEVC.HDR.Multi.Audio.mkv",
            int(2.30 * GB),
        )
        self.assertEqual(
            label, "2.30 GB | 2160p | Example Movie 2025 [Multi Audio]"
        )

    def test_title_numbers_and_special_characters(self):
        label = format_file_result_button(
            "Spider-Man.No.Way.Home.2021.1080p.Hindi.mkv", int(1.1 * GB)
        )
        self.assertIn("Spider Man No Way Home 2021 [Hindi]", label)

    def test_title_year_is_not_lost(self):
        label = format_file_result_button(
            "Wonder.Woman.1984.2020.1080p.BluRay.English.mkv", int(1.2 * GB)
        )
        self.assertIn("Wonder Woman 1984 2020 [English]", label)

    def test_numeric_title_is_not_treated_as_year(self):
        label = format_file_result_button(
            "1917.2019.1080p.Hindi.mkv", int(1.1 * GB)
        )
        self.assertEqual(label, "1.10 GB | 1080p | 1917 2019 [Hindi]")


class SeriesFormatTests(unittest.TestCase):
    def test_s01e01_episode_and_season_preserved(self):
        label = format_file_result_button(
            "Akka.The.Protectors.S01E01.1080p.2026.Hindi.mkv",
            int(820.44 * MB),
        )
        self.assertLessEqual(len(label), MAX_BUTTON_TEXT_LENGTH)
        self.assertTrue(label.startswith("0.80 GB | 1080p | E01 S01 • Akka The Prot"))
        self.assertTrue(label.endswith("2026 Season 1 [Hindi]"))

    def test_s01e02_is_distinct(self):
        label = format_file_result_button(
            "Akka.The.Protectors.S01E02.1080p.2026.Hindi.mkv",
            int(820.44 * MB),
        )
        self.assertIn("E02 S01", label)
        self.assertNotIn("E01 S01", label)

    def test_multiple_seasons(self):
        label = format_file_result_button(
            "Show.Name.S02.E03.2025.720p.Hindi.mkv", int(300 * MB)
        )
        self.assertEqual(
            label, "0.29 GB | 720p | E03 S02 • Show Name 2025 Season 2 [Hindi]"
        )

    def test_spelled_season_episode(self):
        label = format_file_result_button(
            "Show.Name.Season.1.Episode.2.2025.720p.Hindi.mkv",
            int(300 * MB),
        )
        self.assertIn("E02 S01", label)
        self.assertIn("Season 1", label)

    def test_series_missing_metadata(self):
        label = format_file_result_button("Show.Name.S01E01.mkv", int(500 * MB))
        self.assertEqual(label, "0.49 GB | E01 S01 • Show Name Season 1")

    def test_series_never_shows_source_tags(self):
        label = format_file_result_button(
            "Show.Name.S02.E03.2025.WEB-DL.HEVC.English.mkv", int(1.2 * GB)
        )
        self.assertNotIn("WEB-DL", label)
        self.assertNotIn("HEVC", label)
        self.assertIn("E03 S02", label)


class LabelSafetyTests(unittest.TestCase):
    def test_never_exceeds_telegram_limit(self):
        label = format_file_result_button(
            "A.Very.Long.Movie.Title.That.Keeps.Going.And.Going.2025.1080p.WEB-DL.Hindi.English.mkv",
            int(1.45 * GB),
        )
        self.assertLessEqual(len(label), MAX_BUTTON_TEXT_LENGTH)

    def test_long_series_keeps_episode_identifier(self):
        name = (
            "An.Extremely.Long.Series.Title.That.Will.Not.Fit.In.One.Button."
            "S03E11.1080p.WEB-DL.Hindi.mkv"
        )
        label = format_file_result_button(name, int(1.45 * GB))
        self.assertLessEqual(len(label), MAX_BUTTON_TEXT_LENGTH)
        self.assertIn("E11 S03", label)

    def test_no_empty_or_unknown_brackets(self):
        for name in (
            "Movie.Name.mkv",
            "Movie.Name.Hindi.mkv",
            "Movie.Name.1080p.mkv",
        ):
            label = format_file_result_button(name, int(700 * MB))
            self.assertNotIn("[]", label)
            self.assertNotIn("|  |", label)
            self.assertNotIn("N/A", label)
            self.assertNotIn("Unknown", label)

    def test_fallback_is_gb_only_on_bad_metadata(self):
        label = format_file_result_button("", int(700 * MB))
        self.assertEqual(label, "0.68 GB | Media File")


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
                re.search(
                    r"text\s*=\s*format_file_result_button\(file\.file_name, file\.file_size\)",
                    line,
                )
                or "def " in line
                or "import" in line
            )


if __name__ == "__main__":
    unittest.main()
