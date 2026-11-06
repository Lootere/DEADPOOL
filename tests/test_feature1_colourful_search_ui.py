import asyncio
import importlib.util
from pathlib import Path
import re
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
install_global_client_button_styling = search_ui_style.install_global_client_button_styling
invalidate_synced_markup = search_ui_style.invalidate_synced_markup
serialize_inline_keyboard_for_bot_api = search_ui_style.serialize_inline_keyboard_for_bot_api
strip_colour_indicator_emojis = search_ui_style.strip_colour_indicator_emojis
style_inline_keyboard_markup = search_ui_style.style_inline_keyboard_markup

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


@dataclass
class DummyMarkup:
    inline_keyboard: List[List[Any]]


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
        self.assertEqual(caps_layer186["vip_fallback_style"], "primary")

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
        # Native Gold/Yellow is not supported by Telegram Bot API or MTProto;
        # VIP/Premium uses "primary" (Blue) as the documented supported fallback.
        self.assertEqual(ROLE_TO_TELEGRAM_STYLE["vip"], "primary")
        self.assertIsNone(ROLE_TO_TELEGRAM_STYLE["passthrough"])

    def test_search_button_role_classification(self):
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

        # VIP actions -> classified as "vip" (maps to style="primary" fallback, clean label)
        self.assertEqual(classify_search_button("VIP Send All", "sendfiles#chat-1"), "vip")
        self.assertEqual(classify_search_button("💎 VIP Season Pack", "season_pack#101"), "vip")
        self.assertEqual(classify_search_button("🔒 1080p VIP", "lusifilms#101#1080p"), "vip")
        self.assertEqual(classify_search_button("🔒 2160p VIP", "lusifilms#101#2160p"), "vip")

        # External / sponsor URL buttons -> passthrough
        self.assertEqual(
            classify_search_button("Sponsor Channel", callback_data=None, url="https://example.com"),
            "passthrough",
        )

    def test_global_menus_and_keyboards_classification(self):
        # 4.1 /start Menu
        start_rows = [
            [PyroforkLayer186Button("✦ 𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✦", url="http://telegram.me/Bot?startgroup=true")],
            [
                PyroforkLayer186Button("『 🎬 𝐔𝐏𝐃𝐀𝐓𝐄𝐒 』", callback_data="channels"),
                PyroforkLayer186Button("✦ 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒 ✦", callback_data="features"),
            ],
            [
                PyroforkLayer186Button("◈ 𝐇𝐄𝐋𝐏 ◈", callback_data="help"),
                PyroforkLayer186Button("『 𝐀𝐁𝐎𝐔𝐓 』", callback_data="about"),
            ],
            [PyroforkLayer186Button("♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』", callback_data="premium_hub")],
        ]
        start_payload = serialize_inline_keyboard_for_bot_api(start_rows)["inline_keyboard"]
        self.assertEqual(start_payload[0][0]["style"], "danger")
        self.assertEqual(start_payload[1][0]["style"], "danger")
        self.assertEqual(start_payload[1][1]["style"], "danger")
        self.assertEqual(start_payload[2][0]["style"], "danger")
        self.assertEqual(start_payload[2][1]["style"], "danger")
        self.assertEqual(start_payload[3][0]["style"], "primary")

        # 4.2 Help, About, Features, Updates Menus
        help_rows = [
            [PyroforkLayer186Button("♛ 『 𝐀𝐃𝐌𝐈𝐍 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 』", callback_data="admic")],
            [
                PyroforkLayer186Button("✦ 𝐔𝐒𝐄𝐑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 ✦", callback_data="users"),
                PyroforkLayer186Button("◈ 𝐆𝐑𝐎𝐔𝐏 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 ◈", callback_data="group"),
            ],
            [PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄", callback_data="start")],
        ]
        help_payload = serialize_inline_keyboard_for_bot_api(help_rows)["inline_keyboard"]
        self.assertEqual(help_payload[0][0]["style"], "danger")
        self.assertEqual(help_payload[1][0]["style"], "danger")
        self.assertEqual(help_payload[1][1]["style"], "danger")
        self.assertEqual(help_payload[2][0]["style"], "success")

        about_rows = [
            [PyroforkLayer186Button("『 𝐃𝐈𝐒𝐂𝐋𝐀𝐈𝐌𝐄𝐑 』", callback_data="disclaimer")],
            [PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄", callback_data="start")],
        ]
        about_payload = serialize_inline_keyboard_for_bot_api(about_rows)["inline_keyboard"]
        self.assertEqual(about_payload[0][0]["style"], "danger")
        self.assertEqual(about_payload[1][0]["style"], "success")

        channels_rows = [
            [PyroforkLayer186Button("『 📢 𝐔𝐏𝐃𝐀𝐓𝐄𝐒 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 』", url="https://t.me/rkmovieszip")],
            [PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊", callback_data="start")],
        ]
        channels_payload = serialize_inline_keyboard_for_bot_api(channels_rows)["inline_keyboard"]
        self.assertEqual(channels_payload[0][0]["style"], "danger")
        self.assertEqual(channels_payload[1][0]["style"], "success")

        # 4.3 Premium Hub & Buy Premium Menus
        hub_rows = [
            [PyroforkLayer186Button("♕ 『 𝐁𝐎𝐓 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐏𝐋𝐀𝐍𝐒 』", callback_data="premium_info")],
            [PyroforkLayer186Button("♛ 『 𝐆𝐑𝐎𝐔𝐏 / 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 𝐕𝐈𝐏 𝐏𝐋𝐀𝐍𝐒 』", callback_data="dest_plans")],
            [PyroforkLayer186Button("༺ 💎 𝐌𝐘 𝐀𝐂𝐓𝐈𝐕𝐄 𝐏𝐋𝐀𝐍𝐒 ༻", callback_data="my_plans_hub")],
            [PyroforkLayer186Button("✦ 𝐑𝐄𝐅𝐄𝐑 & 𝐄𝐀𝐑𝐍 ✦", callback_data="pm_reff")],
            [PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄", callback_data="start")],
        ]
        hub_payload = serialize_inline_keyboard_for_bot_api(hub_rows)["inline_keyboard"]
        self.assertEqual(hub_payload[0][0]["style"], "primary")
        self.assertEqual(hub_payload[1][0]["style"], "primary")
        self.assertEqual(hub_payload[2][0]["style"], "primary")
        self.assertEqual(hub_payload[3][0]["style"], "primary")
        self.assertEqual(hub_payload[4][0]["style"], "success")

        buy_prem_rows = [
            [
                PyroforkLayer186Button("♕ 『 𝐒𝐄𝐋𝐄𝐂𝐓 𝐁𝐎𝐓 𝐏𝐋𝐀𝐍 』", callback_data="pay_plan_choose#bot"),
                PyroforkLayer186Button("⇩ 『 𝐔𝐏𝐋𝐎𝐀𝐃 𝐏𝐑𝐎𝐎𝐅 』", callback_data="pay_upload_prompt"),
            ],
            [
                PyroforkLayer186Button("『 𝐐𝐑 𝐂𝐎𝐃𝐄 』", callback_data="qr_info"),
                PyroforkLayer186Button("『 𝐔𝐏𝐈 𝐃𝐄𝐓𝐀𝐈𝐋𝐒 』", callback_data="upi_info"),
            ],
            [
                PyroforkLayer186Button("♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』", callback_data="premium_hub"),
                PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊", callback_data="start"),
            ],
            [PyroforkLayer186Button("『 ✕ 𝐂𝐋𝐎𝐒𝐄 』", callback_data="close_data")],
        ]
        buy_payload = serialize_inline_keyboard_for_bot_api(buy_prem_rows)["inline_keyboard"]
        self.assertEqual(buy_payload[0][0]["style"], "primary")
        self.assertEqual(buy_payload[0][1]["style"], "primary")
        self.assertEqual(buy_payload[1][0]["style"], "danger")
        self.assertEqual(buy_payload[1][1]["style"], "danger")
        self.assertEqual(buy_payload[2][0]["style"], "primary")
        self.assertEqual(buy_payload[2][1]["style"], "success")
        self.assertEqual(buy_payload[3][0]["style"], "success")

        # 4.4 Force Subscribe & Channel Join Keyboards
        fsub_rows = [
            [PyroforkLayer186Button("『 📢 𝐉𝐎𝐈𝐍 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 』", url="https://t.me/rkmovieszip")],
            [PyroforkLayer186Button("↻ 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍", callback_data="checksub##files#f123")],
        ]
        fsub_payload = serialize_inline_keyboard_for_bot_api(fsub_rows)["inline_keyboard"]
        self.assertEqual(fsub_payload[0][0]["style"], "danger")
        self.assertEqual(fsub_payload[1][0]["style"], "success")

        # 4.5 File Delivery, Stream/Download & Feature 45 Watch Ad Keyboards
        delivery_rows = [
            [PyroforkLayer186Button("『 🎬 𝐖𝐀𝐓𝐂𝐇 / 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』", callback_data="streaming#f123#-1001")],
            [
                PyroforkLayer186Button("⇩ 『 𝑫𝑶𝑾𝑵𝑳𝑶𝑨𝑫 』", url="https://dl.example.com/1"),
                PyroforkLayer186Button("🎬 『 𝐒𝐓𝐑𝐄𝐀𝐌 』", url="https://watch.example.com/1"),
            ],
            [PyroforkLayer186Button("『 𝐇𝐎𝐖 𝐓𝐎 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』", url="https://t.me/tutorial/1")],
            [
                PyroforkLayer186Button("♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』", callback_data="premium_hub"),
                PyroforkLayer186Button("✦ 𝐖𝐀𝐓𝐂𝐇 𝐀𝐃 & 𝐔𝐍𝐋𝐎𝐂𝐊", callback_data="ad_unlock_start#f123"),
            ],
            [
                PyroforkLayer186Button("✦ 𝐕𝐄𝐑𝐈𝐅𝐘 𝐀𝐃", url="https://short.example.com/v"),
                PyroforkLayer186Button("『 𝐇𝐎𝐖 𝐓𝐎 𝐕𝐄𝐑𝐈𝐅𝐘 』", url="https://t.me/tutorial/2"),
            ],
            [PyroforkLayer186Button("『 🎬 𝐒𝐄𝐍𝐃 𝐅𝐈𝐋𝐄 𝐍𝐎𝐖 』", callback_data="ad_deliver#req1")],
            [PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊", callback_data="close_data")],
        ]
        deliv_payload = serialize_inline_keyboard_for_bot_api(delivery_rows)["inline_keyboard"]
        self.assertEqual(deliv_payload[0][0]["style"], "primary")
        self.assertEqual(deliv_payload[1][0]["style"], "primary")
        self.assertEqual(deliv_payload[1][1]["style"], "primary")
        self.assertEqual(deliv_payload[2][0]["style"], "danger")
        self.assertEqual(deliv_payload[3][0]["style"], "primary")
        self.assertEqual(deliv_payload[3][1]["style"], "danger")
        self.assertEqual(deliv_payload[4][0]["style"], "primary")
        self.assertEqual(deliv_payload[4][1]["style"], "danger")
        self.assertEqual(deliv_payload[5][0]["style"], "primary")
        self.assertEqual(deliv_payload[6][0]["style"], "success")

        # 4.7 Admin, Settings, Multi-DB & Payment Review Keyboards
        admin_rows = [
            [
                PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊", callback_data="help"),
                PyroforkLayer186Button("𝐍𝐄𝐗𝐓 ➜", callback_data="admic2"),
            ],
            [PyroforkLayer186Button("🗄️ Multi-DB Status", callback_data="multidb#main")],
            [
                PyroforkLayer186Button("✅ APPROVE", callback_data="pay_app#req1"),
                PyroforkLayer186Button("❌ REJECT", callback_data="pay_rej#req1"),
            ],
            [PyroforkLayer186Button("◁ 𝐁𝐀𝐂𝐊", callback_data="pay_cancel#req1")],
        ]
        admin_payload = serialize_inline_keyboard_for_bot_api(admin_rows)["inline_keyboard"]
        self.assertEqual(admin_payload[0][0]["style"], "success")
        self.assertEqual(admin_payload[0][1]["style"], "success")
        self.assertEqual(admin_payload[1][0]["style"], "danger")
        self.assertEqual(admin_payload[2][0]["style"], "danger")
        self.assertEqual(admin_payload[2][1]["style"], "danger")
        self.assertEqual(admin_payload[3][0]["style"], "success")

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

        # VIP button -> clean label + style="primary" (Blue fallback)
        self.assertEqual(styled[1][0].text, "VIP Send All")
        self.assertEqual(styled[1][0].callback_data, "sendfiles#100-1")
        self.assertEqual(styled[1][0].style, "primary")

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
            {"text": "VIP Send All", "callback_data": "sendfiles#100-1", "style": "primary"},
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

    def test_global_client_wrapper_styles_sends_and_edits_automatically(self):
        synced_calls: List[Dict[str, Any]] = []

        orig_sync = search_ui_style.sync_bot_api_reply_markup

        async def _fake_sync(chat_id, message_id, rows, bot_token=None):
            payload = serialize_inline_keyboard_for_bot_api(rows)
            synced_calls.append(
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "payload": payload,
                }
            )
            return True

        search_ui_style.sync_bot_api_reply_markup = _fake_sync
        try:
            class FakeChat:
                def __init__(self, cid: int):
                    self.id = cid

            class FakeMessage:
                def __init__(self, cid: int, mid: int):
                    self.chat = FakeChat(cid)
                    self.id = mid

            class FakeClient:
                bot_token = "123:FAKE"

                async def send_photo(self, chat_id: int, photo: str, caption: str = "", reply_markup: Any = None):
                    return FakeMessage(chat_id, 901)

                async def edit_message_text(self, chat_id: int, message_id: int, text: str, reply_markup: Any = None):
                    return FakeMessage(chat_id, message_id)

            install_global_client_button_styling(FakeClient)
            client = FakeClient()

            start_markup = DummyMarkup(
                inline_keyboard=[
                    [DummyButton("✦ 𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✦", url="https://t.me/Bot?startgroup=true")],
                    [
                        DummyButton("◈ 𝐇𝐄𝐋𝐏 ◈", callback_data="help"),
                        DummyButton("♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』", callback_data="premium_hub"),
                    ],
                ]
            )
            asyncio.run(client.send_photo(chat_id=555, photo="pic.jpg", caption="hi", reply_markup=start_markup))
            self.assertEqual(len(synced_calls), 1)
            self.assertEqual(synced_calls[0]["chat_id"], 555)
            self.assertEqual(synced_calls[0]["message_id"], 901)
            ikb0 = synced_calls[0]["payload"]["inline_keyboard"]
            self.assertEqual(ikb0[0][0]["style"], "danger")
            self.assertEqual(ikb0[1][0]["style"], "danger")
            self.assertEqual(ikb0[1][1]["style"], "primary")

            # Editing the same message into Help menu must re-apply styles for the edited menu
            help_markup = DummyMarkup(
                inline_keyboard=[
                    [DummyButton("✦ 𝐔𝐒𝐄𝐑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒 ✦", callback_data="users")],
                    [DummyButton("◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄", callback_data="start")],
                ]
            )
            asyncio.run(client.edit_message_text(chat_id=555, message_id=901, text="Help", reply_markup=help_markup))
            self.assertEqual(len(synced_calls), 2)
            ikb1 = synced_calls[1]["payload"]["inline_keyboard"]
            self.assertEqual(ikb1[0][0]["style"], "danger")
            self.assertEqual(ikb1[1][0]["style"], "success")
        finally:
            search_ui_style.sync_bot_api_reply_markup = orig_sync


if __name__ == "__main__":
    unittest.main()
