import importlib.util
from pathlib import Path
import sys
import types
import unittest

_ROOT = Path(__file__).resolve().parent.parent

if "Lootere" not in sys.modules:
    sys.modules["Lootere"] = types.ModuleType("Lootere")
if "Lootere.utils" not in sys.modules:
    sys.modules["Lootere.utils"] = types.ModuleType("Lootere.utils")


def _load_util_module(name: str, filename: str):
    path = _ROOT / "Lootere" / "utils" / filename
    spec = importlib.util.spec_from_file_location(f"Lootere.utils.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[f"Lootere.utils.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


button_typography = _load_util_module("button_typography", "button_typography.py")
search_ui_style = _load_util_module("search_ui_style", "search_ui_style.py")
subscription_manager = _load_util_module("subscription_manager", "subscription_manager.py")

APPROVED_TYPOGRAPHY_STYLES = button_typography.APPROVED_TYPOGRAPHY_STYLES
APPROVED_SYMBOLS = button_typography.APPROVED_SYMBOLS
FORBIDDEN_COLOUR_EMOJIS = button_typography.FORBIDDEN_COLOUR_EMOJIS
BUTTON_TYPOGRAPHY_CATALOG = button_typography.BUTTON_TYPOGRAPHY_CATALOG
apply_typography_style = button_typography.apply_typography_style
normalize_unicode_typography = button_typography.normalize_unicode_typography
get_button_label = button_typography.get_button_label
get_plain_fallback_label = button_typography.get_plain_fallback_label
validate_button_readability = button_typography.validate_button_readability

classify_search_button = search_ui_style.classify_search_button
apply_search_keyboard_style = search_ui_style.apply_search_keyboard_style
InlineKeyboardButton = subscription_manager.InlineKeyboardButton
InlineKeyboardMarkup = subscription_manager.InlineKeyboardMarkup
build_premium_hub_keyboard = subscription_manager.build_premium_hub_keyboard
build_dest_plans_keyboard = subscription_manager.build_dest_plans_keyboard
build_my_plans_keyboard = subscription_manager.build_my_plans_keyboard


class TestFeature44ButtonTypography(unittest.TestCase):
    """Comprehensive test suite for Feature 44 – RKMOVIESZIP Premium Typography & Unique Symbol Button Design System."""

    def test_01_all_19_approved_typography_styles_defined_and_functional(self):
        expected_styles = [
            "Royal Bold",
            "Modern Italic",
            "Classic Serif",
            "Double-Struck",
            "Bold Sans",
            "Bold Italic",
            "Monospace",
            "Decorative Frame",
            "Royal Frame",
            "Minimal Luxury",
            "Cinematic",
            "Premium Serif",
            "Bold Outline",
            "Stylish Navigation",
            "Elegant Divider",
            "Modern Frame",
            "Royal Gothic Accent",
            "Stylish Next",
            "Cinematic Premium",
        ]
        self.assertEqual(list(APPROVED_TYPOGRAPHY_STYLES), expected_styles)
        self.assertEqual(len(APPROVED_TYPOGRAPHY_STYLES), 19)

        for style in APPROVED_TYPOGRAPHY_STYLES:
            rendered = apply_typography_style("MOVIES", style)
            self.assertTrue(len(rendered) > 0, f"Style {style} returned empty string")
            normalized = normalize_unicode_typography(rendered).upper()
            self.assertIn("MOVIES", normalized, f"Style {style} did not preserve text semantics: {rendered}")

    def test_02_approved_symbol_collections(self):
        expected_categories = {"royal", "luxury", "decorative", "navigation", "frames", "cinematic"}
        self.assertEqual(set(APPROVED_SYMBOLS.keys()), expected_categories)
        self.assertIn("♛", APPROVED_SYMBOLS["royal"])
        self.assertIn("✦", APPROVED_SYMBOLS["luxury"])
        self.assertIn("꧁", APPROVED_SYMBOLS["decorative"])
        self.assertIn("➜", APPROVED_SYMBOLS["navigation"])
        self.assertIn("『", APPROVED_SYMBOLS["frames"])
        self.assertIn("🎬", APPROVED_SYMBOLS["cinematic"])

    def test_03_catalog_completeness_and_readability_validation(self):
        self.assertGreaterEqual(len(BUTTON_TYPOGRAPHY_CATALOG), 35)

        required_categories = {
            "main_menu",
            "premium_vip",
            "file_download",
            "navigation",
            "settings_filters",
            "special_exclusive",
        }
        found_categories = {entry["category"] for entry in BUTTON_TYPOGRAPHY_CATALOG.values()}
        self.assertTrue(required_categories.issubset(found_categories))

        for key, entry in BUTTON_TYPOGRAPHY_CATALOG.items():
            self.assertIn(entry["style"], APPROVED_TYPOGRAPHY_STYLES, f"Unapproved style on {key}")
            styled = entry["styled"]
            plain = entry["plain_fallback"]
            self.assertTrue(len(styled) > 0)
            self.assertTrue(len(plain) > 0)

            validation = validate_button_readability(styled)
            self.assertTrue(
                validation["is_valid"],
                f"Button '{key}' ({styled}) failed readability check: {validation}",
            )
            self.assertTrue(validation["zero_colour_emojis"])
            self.assertTrue(validation["valid_unicode_glyphs"])
            self.assertLessEqual(validation["char_length"], 64)

            fallback_validation = validate_button_readability(plain)
            self.assertTrue(fallback_validation["is_valid"])

    def test_04_no_color_indicator_emojis_anywhere_in_catalog(self):
        for key in BUTTON_TYPOGRAPHY_CATALOG:
            styled = get_button_label(key, use_plain_fallback=False)
            plain = get_button_label(key, use_plain_fallback=True)
            for forbidden in FORBIDDEN_COLOUR_EMOJIS:
                self.assertNotIn(forbidden, styled, f"Forbidden color emoji {forbidden} found in {key}")
                self.assertNotIn(forbidden, plain, f"Forbidden color emoji {forbidden} found in fallback {key}")

    def test_05_plain_fallback_mode_works_for_all_keys(self):
        self.assertEqual(get_button_label("main_premium_hub", use_plain_fallback=False), "♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』")
        self.assertEqual(get_button_label("main_premium_hub", use_plain_fallback=True), "PREMIUM HUB")
        self.assertEqual(get_plain_fallback_label("nav_next"), "NEXT")
        self.assertEqual(get_button_label("nav_page", use_plain_fallback=False), "⟦ 𝐏𝐀𝐆𝐄 ⟧")
        self.assertEqual(get_button_label("nav_page", use_plain_fallback=True), "PAGE")

    def test_06_main_menu_buttons_preserve_callbacks(self):
        main_menu_buttons = [
            InlineKeyboardButton(get_button_label("main_add_to_group"), url="http://t.me/testbot?startgroup=true"),
            InlineKeyboardButton(get_button_label("main_earn_money"), callback_data="shortlink_info"),
            InlineKeyboardButton(get_button_label("main_update_channel"), callback_data="channel_list"),
            InlineKeyboardButton(get_button_label("main_premium_hub"), callback_data="premium_hub"),
            InlineKeyboardButton(get_button_label("main_help"), callback_data="help"),
            InlineKeyboardButton(get_button_label("main_about"), callback_data="about"),
        ]
        self.assertEqual(main_menu_buttons[1].callback_data, "shortlink_info")
        self.assertEqual(main_menu_buttons[2].callback_data, "channel_list")
        self.assertEqual(main_menu_buttons[3].callback_data, "premium_hub")
        self.assertEqual(main_menu_buttons[4].callback_data, "help")
        self.assertEqual(main_menu_buttons[5].callback_data, "about")

        self.assertEqual(main_menu_buttons[3].text, "♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』")
        self.assertEqual(main_menu_buttons[4].text, "◈ 𝐇𝐄𝐋𝐏 ◈")
        self.assertEqual(main_menu_buttons[5].text, "『 𝐀𝐁𝐎𝐔𝐓 』")

    def test_07_search_result_and_filter_buttons_preserve_feature1_roles_and_callbacks(self):
        send_all_btn = InlineKeyboardButton(get_button_label("file_send_all"), callback_data="sendfiles#req#123")
        lang_btn = InlineKeyboardButton(get_button_label("filter_languages"), callback_data=" select_lang#req#123")
        qual_btn = InlineKeyboardButton(get_button_label("filter_qualities"), callback_data="quality#req#123")
        season_btn = InlineKeyboardButton(get_button_label("filter_seasons"), callback_data="seas#req#123")
        epi_btn = InlineKeyboardButton(get_button_label("filter_episodes"), callback_data="epi#s01#req#123")
        epi_back_btn = InlineKeyboardButton(get_button_label("nav_back"), callback_data="epi#s01#req#123")
        next_btn = InlineKeyboardButton(get_button_label("nav_next"), callback_data="next_1_2_123")
        back_btn = InlineKeyboardButton(get_button_label("nav_back"), callback_data=" next_1_0_123")
        page_btn = InlineKeyboardButton(f"{get_button_label('nav_page')} 1/5", callback_data="pages")
        vip_btn = InlineKeyboardButton(get_button_label("premium_buy"), callback_data="premium_info")
        file_btn = InlineKeyboardButton("[1.4 GB] Deadpool (2024) 1080p.mkv", callback_data="files#abc123")

        self.assertEqual(classify_search_button(send_all_btn.text, send_all_btn.callback_data), "vip")
        self.assertEqual(classify_search_button(lang_btn.text, lang_btn.callback_data), "normal")
        self.assertEqual(classify_search_button(qual_btn.text, qual_btn.callback_data), "normal")
        self.assertEqual(classify_search_button(season_btn.text, season_btn.callback_data), "normal")
        self.assertEqual(classify_search_button(epi_btn.text, epi_btn.callback_data), "normal")
        self.assertEqual(classify_search_button(epi_back_btn.text, epi_back_btn.callback_data), "navigation")
        self.assertEqual(classify_search_button(next_btn.text, next_btn.callback_data), "navigation")
        self.assertEqual(classify_search_button(back_btn.text, back_btn.callback_data), "navigation")
        self.assertEqual(classify_search_button(page_btn.text, page_btn.callback_data), "navigation")
        self.assertEqual(classify_search_button(vip_btn.text, vip_btn.callback_data), "vip")
        self.assertEqual(classify_search_button(file_btn.text, file_btn.callback_data), "file")

        rows = [
            [send_all_btn, lang_btn, qual_btn],
            [season_btn, epi_btn],
            [file_btn],
            [back_btn, page_btn, next_btn],
            [vip_btn],
        ]
        styled_rows = apply_search_keyboard_style(rows)
        self.assertEqual(len(styled_rows), 5)
        self.assertEqual(styled_rows[0][0].callback_data, "sendfiles#req#123")
        self.assertEqual(styled_rows[2][0].callback_data, "files#abc123")
        self.assertEqual(styled_rows[3][2].callback_data, "next_1_2_123")
        self.assertEqual(styled_rows[4][0].callback_data, "premium_info")

    def test_08_premium_hub_and_subscription_keyboards_preserve_callbacks(self):
        hub_kb = build_premium_hub_keyboard()
        callbacks = [btn.callback_data for row in hub_kb.inline_keyboard for btn in row]
        self.assertEqual(
            callbacks,
            [
                "premium_info",
                "dest_plans",
                "pm_reff",
                "my_plans_hub",
                "start",
            ],
        )
        labels = [btn.text for row in hub_kb.inline_keyboard for btn in row]
        self.assertEqual(labels[0], "♕ 『 𝐁𝐎𝐓 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』")
        self.assertEqual(labels[1], "♛ 『 𝐕𝐈𝐏 𝐃𝐄𝐒𝐓𝐈𝐍𝐀𝐓𝐈𝐎𝐍𝐒 』")
        self.assertEqual(labels[2], "✦ 𝐅𝐑𝐄𝐄 𝐓𝐑𝐈𝐀𝐋 & 𝐑𝐄𝐅𝐄𝐑𝐑𝐀𝐋𝐒 ✦")
        self.assertEqual(labels[3], "༺ 💎 𝐌𝐘 𝐀𝐂𝐓𝐈𝐕𝐄 𝐏𝐋𝐀𝐍𝐒 ༻")
        self.assertEqual(labels[4], "◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄")

        plans_kb = build_dest_plans_keyboard("Looteredev")
        plan_callbacks = [btn.callback_data for row in plans_kb.inline_keyboard for btn in row if btn.callback_data]
        self.assertEqual(
            plan_callbacks,
            ["pay_plan_choose#vip", "pay_upload_prompt", "dest_invites", "premium_hub", "start"],
        )

        my_plans_kb = build_my_plans_keyboard(has_dest_sub=True)
        my_callbacks = [btn.callback_data for row in my_plans_kb.inline_keyboard for btn in row]
        self.assertEqual(my_callbacks, ["dest_invites", "dest_plans", "premium_hub", "start"])

    def test_09_download_and_streaming_buttons_preserve_callbacks(self):
        dl_btn = InlineKeyboardButton(get_button_label("file_download_now"), url="https://example.com/dl/1")
        stream_btn = InlineKeyboardButton(get_button_label("file_stream_online"), url="https://example.com/watch/1")
        unlock_btn = InlineKeyboardButton(get_button_label("premium_remove_verify"), callback_data="seeplans")

        self.assertEqual(dl_btn.text, "⇩ 『 𝑫𝑶𝑾𝑵𝑳𝑶𝑨𝑫 』")
        self.assertEqual(stream_btn.text, "🎬 『 𝐒𝐓𝐑𝐄𝐀𝐌 』")
        self.assertEqual(unlock_btn.text, "✧ 𝙐𝙉𝙇𝙊𝘾𝙆 𝙑𝙄𝙋 ✧")
        self.assertEqual(unlock_btn.callback_data, "seeplans")


if __name__ == "__main__":
    unittest.main()
