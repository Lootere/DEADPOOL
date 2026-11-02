import asyncio
import importlib.util
from pathlib import Path
import re
import unittest
from dataclasses import dataclass
from typing import Any, List, Optional

_STYLE_PATH = Path(__file__).resolve().parent.parent / "Lootere" / "utils" / "search_ui_style.py"
_SPEC = importlib.util.spec_from_file_location("search_ui_style", _STYLE_PATH)
search_ui_style = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(search_ui_style)

ROLE_TO_TELEGRAM_STYLE = search_ui_style.ROLE_TO_TELEGRAM_STYLE
SUPPORTED_TELEGRAM_STYLES = search_ui_style.SUPPORTED_TELEGRAM_STYLES
apply_search_keyboard_style = search_ui_style.apply_search_keyboard_style
classify_search_button = search_ui_style.classify_search_button
edit_styled_reply_markup = search_ui_style.edit_styled_reply_markup
inspect_button_style_capabilities = search_ui_style.inspect_button_style_capabilities
serialize_inline_keyboard_for_bot_api = search_ui_style.serialize_inline_keyboard_for_bot_api
strip_colour_indicator_emojis = search_ui_style.strip_colour_indicator_emojis

FORBIDDEN_COLOUR_EMOJI_RE = re.compile(
    r"[\U0001F534\U0001F535\U0001F7E2\U0001F7E1\U0001F7E0\U0001F7E3\U0001F7E4"
    r"\u26AA\u26AB\U0001F7E5\U0001F7E6\U0001F7E9\U0001F7E8\U0001F7E7\U0001F7EA\U0001F7EB"
    r"\U0001F536\U0001F537\U0001F538\U0001F539]"
)


@dataclass
class DummyButton:
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None
    style: Optional[str] = None
    button_role: Optional[str] = None


class PyroforkLayer186Button:
    """Simulates pyrofork==2.3.43 InlineKeyboardButton without a native style parameter."""

    def __init__(
        self,
        text: str,
        callback_data: Optional[str] = None,
        url: Optional[str] = None,
    ):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class Layer222StyledButton:
    """Simulates Layer 222+ InlineKeyboardButton with native style support."""

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


class TestFeature1GenuineButtonStyling(unittest.TestCase):
    def test_capability_inspection_and_supported_styles(self):
        caps_layer186 = inspect_button_style_capabilities(PyroforkLayer186Button)
        self.assertFalse(caps_layer186["native_color_supported"])
        self.assertIsNone(caps_layer186["native_style_param"])
        self.assertEqual(
            caps_layer186["delivery_mechanism"],
            "telegram_bot_api_reply_markup_style",
        )
        self.assertEqual(
            caps_layer186["supported_telegram_styles"],
            ["danger", "primary", "success"],
        )
        self.assertIn("gold/yellow (VIP)", caps_layer186["unavailable_requested_colours"])

        caps_layer222 = inspect_button_style_capabilities(Layer222StyledButton)
        self.assertTrue(caps_layer222["native_color_supported"])
        self.assertEqual(caps_layer222["native_style_param"], "style")
        self.assertEqual(
            caps_layer222["delivery_mechanism"],
            "native_mtproto_button_style",
        )

    def test_role_to_official_telegram_style_mapping(self):
        self.assertEqual(ROLE_TO_TELEGRAM_STYLE["normal"], "danger")
        self.assertEqual(ROLE_TO_TELEGRAM_STYLE["file"], "primary")
        self.assertEqual(ROLE_TO_TELEGRAM_STYLE["navigation"], "success")
        # Gold/Yellow is not supported by Telegram Bot API or MTProto; must be None (default)
        self.assertIsNone(ROLE_TO_TELEGRAM_STYLE["vip"])
        self.assertIsNone(ROLE_TO_TELEGRAM_STYLE["passthrough"])

    def test_button_role_classification(self):
        # Normal search actions -> Red ("danger")
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

        # File & selectable filter actions -> Blue ("primary")
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

        # Navigation & pagination -> Green ("success")
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

        # VIP actions -> classified as "vip" (which maps to style=None, clean label)
        self.assertEqual(classify_search_button("VIP Send All", "sendfiles#chat-1"), "vip")
        self.assertEqual(classify_search_button("💎 VIP Season Pack", "season_pack#101"), "vip")
        self.assertEqual(classify_search_button("🔒 1080p VIP", "lusifilms#101#1080p"), "vip")
        self.assertEqual(classify_search_button("🔒 2160p VIP", "lusifilms#101#2160p"), "vip")

        # External / sponsor URL buttons -> passthrough
        self.assertEqual(
            classify_search_button("Sponsor Channel", callback_data=None, url="https://example.com"),
            "passthrough",
        )

    def test_zero_colour_emojis_in_button_labels_and_genuine_style_assignment(self):
        sponsor = PyroforkLayer186Button(text="Join Sponsor", url="https://example.com")
        keyboard = [
            [PyroforkLayer186Button(text="[1.20 GB] Deadpool.2024.1080p.mkv", callback_data="files#f1")],
            [PyroforkLayer186Button(text="VIP Send All", callback_data="sendfiles#100-1")],
            [
                PyroforkLayer186Button(text="Lᴀɴɢᴜᴀɢᴇ", callback_data="select_lang#42"),
                PyroforkLayer186Button(text="Qᴜᴀʟɪᴛʏ", callback_data="quality#42"),
            ],
            [
                PyroforkLayer186Button(text="📅 Sᴀᴀʟ", callback_data="year#42"),
                PyroforkLayer186Button(text="↕ Sᴏʀᴛ", callback_data="sort#42"),
            ],
            [
                PyroforkLayer186Button(text="Sᴇᴀꜱᴏɴs", callback_data="seas#42"),
                PyroforkLayer186Button(text="Eᴘɪsᴏᴅᴇ", callback_data="epi#42"),
            ],
            [sponsor],
            [
                PyroforkLayer186Button(text="⌫ 𝐁𝐀𝐂𝐊", callback_data="next_42_100-1_0"),
                PyroforkLayer186Button(text="2 / 3", callback_data="pages"),
                PyroforkLayer186Button(text="Nᴇxᴛ ➪", callback_data="next_42_100-1_20"),
            ],
        ]

        styled = apply_search_keyboard_style(keyboard, button_cls=PyroforkLayer186Button)

        # Verify ZERO colour-indicator emojis anywhere in any button text
        for row in styled:
            for btn in row:
                self.assertIsNone(
                    FORBIDDEN_COLOUR_EMOJI_RE.search(btn.text),
                    f"Forbidden colour emoji found in button text: {btn.text!r}",
                )

        # File button -> clean label + style="primary" (Blue)
        self.assertEqual(styled[0][0].text, "[1.20 GB] Deadpool.2024.1080p.mkv")
        self.assertEqual(styled[0][0].callback_data, "files#f1")
        self.assertEqual(styled[0][0].style, "primary")

        # VIP button -> clean label + style=None (Telegram has no gold/yellow style)
        self.assertEqual(styled[1][0].text, "VIP Send All")
        self.assertEqual(styled[1][0].callback_data, "sendfiles#100-1")
        self.assertIsNone(styled[1][0].style)

        # Normal buttons -> clean labels + style="danger" (Red / Maroon)
        self.assertEqual(styled[2][0].text, "Lᴀɴɢᴜᴀɢᴇ")
        self.assertEqual(styled[2][0].style, "danger")
        self.assertEqual(styled[2][1].text, "Qᴜᴀʟɪᴛʏ")
        self.assertEqual(styled[2][1].style, "danger")
        self.assertEqual(styled[3][0].text, "📅 Sᴀᴀʟ")
        self.assertEqual(styled[3][0].style, "danger")
        self.assertEqual(styled[3][1].text, "↕ Sᴏʀᴛ")
        self.assertEqual(styled[3][1].style, "danger")
        self.assertEqual(styled[4][0].text, "Sᴇᴀꜱᴏɴs")
        self.assertEqual(styled[4][0].style, "danger")
        self.assertEqual(styled[4][1].text, "Eᴘɪsᴏᴅᴇ")
        self.assertEqual(styled[4][1].style, "danger")

        # Sponsor URL button -> unchanged + style=None
        self.assertEqual(styled[5][0].text, "Join Sponsor")
        self.assertEqual(styled[5][0].url, "https://example.com")
        self.assertIsNone(styled[5][0].style)

        # Navigation buttons -> clean labels + style="success" (Green)
        self.assertEqual(styled[6][0].text, "⌫ 𝐁𝐀𝐂𝐊")
        self.assertEqual(styled[6][0].style, "success")
        self.assertEqual(styled[6][1].text, "2 / 3")
        self.assertEqual(styled[6][1].style, "success")
        self.assertEqual(styled[6][2].text, "Nᴇxᴛ ➪")
        self.assertEqual(styled[6][2].style, "success")

    def test_bot_api_serialization_and_strip_legacy_colour_emojis(self):
        # Verify that even if legacy colour emojis were passed in, they are stripped
        self.assertEqual(strip_colour_indicator_emojis("\U0001F534 Lᴀɴɢᴜᴀɢᴇ"), "Lᴀɴɢᴜᴀɢᴇ")
        self.assertEqual(strip_colour_indicator_emojis("\U0001F7E2 Nᴇxᴛ ➪"), "Nᴇxᴛ ➪")
        self.assertEqual(strip_colour_indicator_emojis("\U0001F7E1 \U0001F451 VIP Send All"), "VIP Send All")
        self.assertEqual(strip_colour_indicator_emojis("\U0001F535 [1.2 GB] File.mkv"), "[1.2 GB] File.mkv")

        rows = [
            [PyroforkLayer186Button(text="[1.2 GB] File.mkv", callback_data="files#f1")],
            [PyroforkLayer186Button(text="VIP Send All", callback_data="sendfiles#100-1")],
            [
                PyroforkLayer186Button(text="Lᴀɴɢᴜᴀɢᴇ", callback_data="select_lang#42"),
                PyroforkLayer186Button(text="Qᴜᴀʟɪᴛʏ", callback_data="quality#42"),
            ],
            [
                PyroforkLayer186Button(text="1 / 3", callback_data="pages"),
                PyroforkLayer186Button(text="Nᴇxᴛ ➪", callback_data="next_42_100-1_10"),
            ],
        ]
        payload = serialize_inline_keyboard_for_bot_api(rows)
        ikb = payload["inline_keyboard"]

        self.assertEqual(
            ikb[0][0],
            {"text": "[1.2 GB] File.mkv", "callback_data": "files#f1", "style": "primary"},
        )
        self.assertEqual(
            ikb[1][0],
            {"text": "VIP Send All", "callback_data": "sendfiles#100-1"},
        )
        self.assertEqual(
            ikb[2][0],
            {"text": "Lᴀɴɢᴜᴀɢᴇ", "callback_data": "select_lang#42", "style": "danger"},
        )
        self.assertEqual(
            ikb[2][1],
            {"text": "Qᴜᴀʟɪᴛʏ", "callback_data": "quality#42", "style": "danger"},
        )
        self.assertEqual(
            ikb[3][0],
            {"text": "1 / 3", "callback_data": "pages", "style": "success"},
        )
        self.assertEqual(
            ikb[3][1],
            {"text": "Nᴇxᴛ ➪", "callback_data": "next_42_100-1_10", "style": "success"},
        )

    def test_edit_styled_reply_markup_calls_pyrogram_edit(self):
        captured: List[Any] = []

        class DummyChat:
            id = 12345

        class DummyMsg:
            id = 678
            chat = DummyChat()

        class DummyQuery:
            message = DummyMsg()

            async def edit_message_reply_markup(self, reply_markup: Any = None):
                captured.append(reply_markup)
                return "edited"

        rows = [
            [DummyButton(text="Lᴀɴɢᴜᴀɢᴇ", callback_data="select_lang#42")],
            [DummyButton(text="Gᴏ Bᴀᴄᴋ", callback_data="lang#42#home")],
        ]
        res = asyncio.run(edit_styled_reply_markup(DummyQuery(), rows))
        self.assertEqual(res, "edited")
        self.assertEqual(len(captured), 1)


if __name__ == "__main__":
    unittest.main()
