import importlib.util
from pathlib import Path
import unittest
from dataclasses import dataclass
from typing import Optional

_STYLE_PATH = Path(__file__).resolve().parent.parent / "Lootere" / "utils" / "search_ui_style.py"
_SPEC = importlib.util.spec_from_file_location("search_ui_style", _STYLE_PATH)
search_ui_style = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(search_ui_style)

ROLE_BADGES = search_ui_style.ROLE_BADGES
apply_search_keyboard_style = search_ui_style.apply_search_keyboard_style
classify_search_button = search_ui_style.classify_search_button
format_search_button_text = search_ui_style.format_search_button_text
inspect_button_style_capabilities = search_ui_style.inspect_button_style_capabilities


@dataclass
class DummyButton:
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None


class NativeStyledButton:
    def __init__(
        self,
        text: str,
        callback_data: Optional[str] = None,
        url: Optional[str] = None,
        style: Optional[str] = None,
    ):
        self.text = text
        self.callback_data = callback_data
        self.url = url
        self.style = style


class RejectingNativeStyledButton:
    def __init__(
        self,
        text: str,
        callback_data: Optional[str] = None,
        url: Optional[str] = None,
        style: Optional[str] = None,
    ):
        if style is not None:
            raise TypeError("Telegram client rejected style parameter")
        self.text = text
        self.callback_data = callback_data
        self.url = url


class TestFeature1ColourfulSearchUI(unittest.TestCase):
    def test_capability_inspection_standard_and_native(self):
        caps_standard = inspect_button_style_capabilities(DummyButton)
        self.assertFalse(caps_standard["native_color_supported"])
        self.assertIsNone(caps_standard["native_style_param"])
        self.assertEqual(caps_standard["fallback_mode"], "emoji_badge_labels")

        caps_native = inspect_button_style_capabilities(NativeStyledButton)
        self.assertTrue(caps_native["native_color_supported"])
        self.assertEqual(caps_native["native_style_param"], "style")

    def test_button_role_classification(self):
        # Normal search actions -> Red
        self.assertEqual(classify_search_button("Lᴀɴɢᴜᴀɢᴇ", "select_lang#101"), "normal")
        self.assertEqual(classify_search_button("Qᴜᴀʟɪᴛʏ", "quality#101"), "normal")
        self.assertEqual(classify_search_button("📅 Sᴀᴀʟ", "year#101"), "normal")
        self.assertEqual(classify_search_button("↕ Sᴏʀᴛ", "sort#101"), "normal")
        self.assertEqual(classify_search_button("Sᴇᴀꜱᴏɴs", "seas#101"), "normal")
        self.assertEqual(classify_search_button("Eᴘɪsᴏᴅᴇ", "epi#101"), "normal")
        self.assertEqual(classify_search_button("💾 Save to playlist", "playlist_save#101"), "normal")
        self.assertEqual(
            classify_search_button("Sᴇʟᴇᴄᴛ Yᴏᴜʀ Dᴇꜱɪʀᴇᴅ Lᴀɴɢᴜᴀɢᴇ ↓", "lang#101#unknown"),
            "normal",
        )

        # File & selectable filter actions -> Blue
        self.assertEqual(classify_search_button("[1.45 GB] Movie.mkv", "files#abc123"), "file")
        self.assertEqual(classify_search_button("Movie Title", "search_suggestion#101#tok"), "file")
        self.assertEqual(classify_search_button("Movie Title", "spol#tt12345#101"), "file")
        self.assertEqual(classify_search_button("➕ Watchlist", "playlist_add#101#5#pl1"), "file")
        self.assertEqual(classify_search_button("Hɪɴᴅɪ", "lang#101#hin"), "file")
        self.assertEqual(classify_search_button("720p", "lusifilms#101#720p"), "file")
        self.assertEqual(classify_search_button("1080p", "lusifilms#101#1080p"), "file")
        self.assertEqual(classify_search_button("Sᴇᴀꜱᴏɴ 𝟷", "seasons#101#s01"), "file")
        self.assertEqual(classify_search_button("ᴇᴘ 𝟷", "episode#101#e01"), "file")
        self.assertEqual(classify_search_button("2025", "year#101#2025"), "file")
        self.assertEqual(classify_search_button("Sᴇᴀsᴏɴ / Eᴘɪsᴏᴅᴇ", "sort#101#season"), "file")

        # Navigation & pagination -> Green
        self.assertEqual(classify_search_button("Nᴇxᴛ ➪", "next_101_key_10"), "navigation")
        self.assertEqual(classify_search_button("⌫ 𝐁𝐀𝐂𝐊", "next_101_key_0"), "navigation")
        self.assertEqual(classify_search_button("1 / 5", "pages"), "navigation")
        self.assertEqual(classify_search_button("Nᴏ Mᴏʀᴇ Pᴀɢᴇs", "pages"), "navigation")
        self.assertEqual(classify_search_button("Gᴏ Bᴀᴄᴋ", "lang#101#home"), "navigation")
        self.assertEqual(classify_search_button("Gᴏ Bᴀᴄᴋ", "lusifilms#101#home"), "navigation")
        self.assertEqual(classify_search_button("Gᴏ Bᴀᴄᴋ", "seasons#101#home"), "navigation")
        self.assertEqual(classify_search_button("⥢ Bᴀᴄᴋ", "episode#101#home"), "navigation")
        self.assertEqual(classify_search_button("⥢ Bᴀᴄᴋ", "epi#101"), "navigation")
        self.assertEqual(classify_search_button("ɴᴇxᴛ ➮", "epi2#101"), "navigation")
        self.assertEqual(classify_search_button("Sᴀʙʜɪ Sᴀᴀʟ", "year#101#home"), "navigation")
        self.assertEqual(classify_search_button("Gᴏ Bᴀᴄᴋ", "year#101#back"), "navigation")
        self.assertEqual(classify_search_button("🚫 ᴄʟᴏsᴇ 🚫", "close_data"), "navigation")

        # VIP actions -> Gold / Yellow
        self.assertEqual(classify_search_button("VIP Send All", "sendfiles#chat-1"), "vip")
        self.assertEqual(classify_search_button("💎 VIP Season Pack", "season_pack#101"), "vip")
        self.assertEqual(classify_search_button("🔒 1080p VIP", "lusifilms#101#1080p"), "vip")
        self.assertEqual(classify_search_button("🔒 2160p VIP", "lusifilms#101#2160p"), "vip")

        # External / sponsor URL buttons -> passthrough
        self.assertEqual(
            classify_search_button("Sponsor Channel", callback_data=None, url="https://example.com"),
            "passthrough",
        )

    def test_keyboard_styling_preserves_callbacks_urls_and_is_idempotent(self):
        sponsor = DummyButton(text="Join Sponsor", url="https://example.com")
        keyboard = [
            [DummyButton(text="[1.20 GB] Deadpool.2024.1080p.mkv", callback_data="files#f1")],
            [DummyButton(text="VIP Send All", callback_data="sendfiles#100-1")],
            [
                DummyButton(text="Lᴀɴɢᴜᴀɢᴇ", callback_data="select_lang#42"),
                DummyButton(text="Qᴜᴀʟɪᴛʏ", callback_data="quality#42"),
            ],
            [
                DummyButton(text="📅 Sᴀᴀʟ", callback_data="year#42"),
                DummyButton(text="↕ Sᴏʀᴛ", callback_data="sort#42"),
            ],
            [sponsor],
            [
                DummyButton(text="1 / 3", callback_data="pages"),
                DummyButton(text="Nᴇxᴛ ➪", callback_data="next_42_100-1_10"),
            ],
        ]

        styled_once = apply_search_keyboard_style(keyboard, button_cls=DummyButton)
        self.assertTrue(styled_once[0][0].text.startswith(f"{ROLE_BADGES['file']} "))
        self.assertEqual(styled_once[0][0].callback_data, "files#f1")

        self.assertEqual(styled_once[1][0].text, "🟡 👑 VIP Send All")
        self.assertEqual(styled_once[1][0].callback_data, "sendfiles#100-1")

        self.assertEqual(styled_once[2][0].text, "🔴 Lᴀɴɢᴜᴀɢᴇ")
        self.assertEqual(styled_once[2][0].callback_data, "select_lang#42")
        self.assertEqual(styled_once[2][1].text, "🔴 Qᴜᴀʟɪᴛʏ")
        self.assertEqual(styled_once[2][1].callback_data, "quality#42")

        # Sponsor URL button must remain completely unchanged
        self.assertEqual(styled_once[4][0].text, "Join Sponsor")
        self.assertEqual(styled_once[4][0].url, "https://example.com")

        self.assertEqual(styled_once[5][0].text, "🟢 1 / 3")
        self.assertEqual(styled_once[5][0].callback_data, "pages")
        self.assertEqual(styled_once[5][1].text, "🟢 Nᴇxᴛ ➪")
        self.assertEqual(styled_once[5][1].callback_data, "next_42_100-1_10")

        # Idempotency check (calling a second time must not double-prefix)
        snapshots = [[(b.text, b.callback_data, b.url) for b in row] for row in styled_once]
        styled_twice = apply_search_keyboard_style(styled_once, button_cls=DummyButton)
        snapshots_after = [[(b.text, b.callback_data, b.url) for b in row] for row in styled_twice]
        self.assertEqual(snapshots, snapshots_after)

    def test_native_style_support_and_graceful_fallback(self):
        row = [[NativeStyledButton(text="VIP Send All", callback_data="sendfiles#k1")]]
        styled = apply_search_keyboard_style(row, button_cls=NativeStyledButton)
        self.assertEqual(styled[0][0].style, "warning")
        self.assertEqual(styled[0][0].callback_data, "sendfiles#k1")
        self.assertEqual(styled[0][0].text, "🟡 👑 VIP Send All")

        rejecting_row = [[RejectingNativeStyledButton(text="VIP Send All", callback_data="sendfiles#k1")]]
        fallback_styled = apply_search_keyboard_style(
            rejecting_row, button_cls=RejectingNativeStyledButton
        )
        self.assertEqual(fallback_styled[0][0].callback_data, "sendfiles#k1")
        self.assertEqual(fallback_styled[0][0].text, "🟡 👑 VIP Send All")


if __name__ == "__main__":
    unittest.main()
