# Feature 44 – RKMOVIESZIP Premium Typography & Unique Symbol Button Design System
#
# UI-only presentation layer providing:
# - All 19 approved Unicode typography styles
# - Approved symbol collections (Royal, Luxury, Decorative, Navigation, Frames, Cinematic)
# - Consistent category-based button label definitions with plain readable fallbacks
# - Readability & Telegram compatibility validation (zero colour indicator emojis)

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Approved Symbol Collection (Section 4 of PRD)
# ---------------------------------------------------------------------------

APPROVED_SYMBOLS: Dict[str, Tuple[str, ...]] = {
    "royal": ("♛", "♕", "♔", "♚"),
    "luxury": ("✦", "✧", "⟡", "◈", "❖"),
    "decorative": ("꧁", "꧂", "𓆩", "𓆪", "༺", "༻"),
    "navigation": ("◁", "▷", "➜", "⇩", "⌕"),
    "frames": ("『", "』", "「", "」", "【", "】", "⟦", "⟧"),
    "cinematic": ("🎬", "▣", "▤", "▷", "◉", "✺"),
}

ALL_APPROVED_SYMBOLS = frozenset(
    sym for group in APPROVED_SYMBOLS.values() for sym in group
)

# Forbidden colour-indicator emojis (Section 9: No Colour Substitution)
FORBIDDEN_COLOUR_EMOJIS = frozenset({
    "🔴", "🟢", "🟡", "🔵", "🟣", "🟤", "⚪", "⚫",
    "🟥", "🟩", "🟨", "🟦", "🟪", "🟫", "⬛", "⬜",
    "🔶", "🔷", "🔸", "🔹",
})


# ---------------------------------------------------------------------------
# 2. Unicode Font Character Translation Tables
# ---------------------------------------------------------------------------

_ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"
_ASCII_DIGITS = "0123456789"
_ASCII_ALL = _ASCII_UPPER + _ASCII_LOWER + _ASCII_DIGITS

# Mathematical Bold (Royal Bold / Classic Serif)
_ROYAL_BOLD_MAP = str.maketrans(
    _ASCII_ALL,
    "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
    "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
    "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗",
)

# Mathematical Sans-Serif Italic (Modern Italic)
_MODERN_ITALIC_MAP = str.maketrans(
    _ASCII_UPPER + _ASCII_LOWER,
    "𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡"
    "𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻",
)

# Mathematical Serif Italic (Classic Serif / Premium Serif)
_PREMIUM_SERIF_ITALIC_MAP = str.maketrans(
    _ASCII_UPPER + _ASCII_LOWER,
    "𝑨𝑩𝑪𝑫𝑬𝑭𝑮𝑯𝑰𝑱𝑲𝑳𝑴𝑵𝑶𝑷𝑸𝑹𝑺𝑻𝑼𝑽𝑾𝑿𝒀𝒁"
    "𝒂𝒃𝒄𝒅𝒆𝒇𝒈𝒉𝒊𝒋𝒌𝒍𝒎𝒏𝒐𝒑𝒒𝒓𝒔𝒕𝒖𝒗𝒘𝒙𝒚𝒛",
)

# Mathematical Double-Struck
_DOUBLE_STRUCK_MAP = str.maketrans(
    _ASCII_ALL,
    "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ"
    "𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫"
    "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡",
)

# Mathematical Sans-Serif Bold (Bold Sans)
_BOLD_SANS_MAP = str.maketrans(
    _ASCII_ALL,
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
    "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
)

# Mathematical Sans-Serif Bold Italic (Bold Italic)
_BOLD_ITALIC_MAP = str.maketrans(
    _ASCII_UPPER + _ASCII_LOWER,
    "𝘼𝘽𝘾𝘿𝙀𝙁𝙂𝙃𝙄𝙅𝙆𝙇𝙈𝙉𝙊𝙋𝙌𝙍𝙎𝙏𝙐𝙑𝙒𝙓𝙔𝙕"
    "𝙖𝙗𝙘𝙙𝙚𝙛𝙜𝙝𝙞𝙟𝙠𝙡𝙢𝙣𝙤𝙥𝙦𝙧𝙨𝙩𝙪𝙫𝙬𝙭𝙮𝙯",
)

# Mathematical Monospace (Monospace)
_MONOSPACE_MAP = str.maketrans(
    _ASCII_ALL,
    "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"
    "𝚊𝚋𝚌𝚍𝚎𝚏𝖌𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"
    "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿",
)

# Mathematical Bold Fraktur (Royal Gothic Accent — used only on special/non-critical accents)
_GOTHIC_ACCENT_MAP = str.maketrans(
    _ASCII_UPPER + _ASCII_LOWER,
    "𝕬𝕭𝕮𝕯𝕰𝕱𝕲𝕳𝕴𝕵𝕶𝕷𝕸𝕹𝕺𝕻𝕼𝕽𝕾𝕿𝖀𝖁𝖂𝖃𝖄𝖅"
    "𝖆𝖇𝖈𝖉𝖊𝖋𝖌𝖍𝖎𝖏𝖐𝖑𝖒𝖓𝖔𝖕𝖖𝖗𝖘𝖙𝖚𝖛𝖜𝖝𝖞𝖟",
)


# ---------------------------------------------------------------------------
# 3. The 19 Approved Typography Styles (Section 3 of PRD)
# ---------------------------------------------------------------------------

APPROVED_TYPOGRAPHY_STYLES: Tuple[str, ...] = (
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
)

CATEGORY_TYPOGRAPHY_MAPPING: Dict[str, Tuple[str, ...]] = {
    "main_menu": ("Royal Bold", "Bold Sans", "Modern Italic", "Decorative Frame", "Royal Frame", "Minimal Luxury", "Cinematic", "Elegant Divider"),
    "premium_vip": ("Royal Frame", "Premium Serif", "Royal Gothic Accent", "Minimal Luxury", "Royal Bold"),
    "movies_series": ("Cinematic", "Classic Serif", "Bold Italic"),
    "file_download": ("Bold Outline", "Double-Struck", "Minimal Luxury", "Elegant Divider", "Royal Bold"),
    "navigation": ("Stylish Navigation", "Stylish Next", "Minimal Luxury"),
    "settings_filters": ("Monospace", "Modern Frame", "Elegant Divider", "Bold Sans", "Bold Italic"),
    "special_exclusive": ("Decorative Frame", "Cinematic Premium", "Royal Gothic Accent", "Minimal Luxury"),
}


def apply_typography_style(text: str, style_name: str, icon: str = "") -> str:
    """Format plain text using one of the 19 approved typography styles."""
    if style_name not in APPROVED_TYPOGRAPHY_STYLES:
        raise ValueError(f"Unapproved typography style: {style_name!r}")

    clean = str(text or "").strip()
    prefix_icon = f"{icon.strip()} " if icon and icon.strip() else ""

    if style_name == "Royal Bold":
        return f"♛ {prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)}"
    if style_name == "Modern Italic":
        return f"{prefix_icon}{clean.translate(_MODERN_ITALIC_MAP)}"
    if style_name == "Classic Serif":
        return f"{prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)}"
    if style_name == "Double-Struck":
        return f"⇩ {prefix_icon}{clean.translate(_DOUBLE_STRUCK_MAP)}"
    if style_name == "Bold Sans":
        return f"{prefix_icon}{clean.translate(_BOLD_SANS_MAP)}"
    if style_name == "Bold Italic":
        return f"{prefix_icon}{clean.translate(_BOLD_ITALIC_MAP)}"
    if style_name == "Monospace":
        return f"{prefix_icon}{clean.translate(_MONOSPACE_MAP)}"
    if style_name == "Decorative Frame":
        return f"『 {prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)} 』"
    if style_name == "Royal Frame":
        return f"♛ 『 {prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)} 』"
    if style_name == "Minimal Luxury":
        return f"✦ {prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)} ✦"
    if style_name == "Cinematic":
        cin_icon = prefix_icon if prefix_icon else "🎬 "
        return f"『 {cin_icon}{clean.translate(_ROYAL_BOLD_MAP)} 』"
    if style_name == "Premium Serif":
        return f"༺ {prefix_icon}{clean.translate(_PREMIUM_SERIF_ITALIC_MAP)} ༻"
    if style_name == "Bold Outline":
        return f"⟦ {prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)} ⟧"
    if style_name == "Stylish Navigation":
        return f"◁ {prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)}"
    if style_name == "Elegant Divider":
        return f"◈ {prefix_icon}{clean.translate(_BOLD_SANS_MAP)} ◈"
    if style_name == "Modern Frame":
        return f"⚙ 『 {prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)} 』"
    if style_name == "Royal Gothic Accent":
        return f"𓆩 {prefix_icon}{clean.translate(_BOLD_ITALIC_MAP)} 𓆪"
    if style_name == "Stylish Next":
        return f"{prefix_icon}{clean.translate(_ROYAL_BOLD_MAP)} ➜"
    if style_name == "Cinematic Premium":
        return f"✦ {prefix_icon}{clean.translate(_BOLD_ITALIC_MAP)} ✦"

    return clean


def normalize_unicode_typography(text: str) -> str:
    """Normalize mathematical Unicode alphanumeric characters back to plain ASCII for logic/classification."""
    if not text:
        return ""
    return unicodedata.normalize("NFKD", str(text))


# ---------------------------------------------------------------------------
# 4. Canonical Button Label Registry (Consistent per Category + Plain Fallback)
# ---------------------------------------------------------------------------

BUTTON_TYPOGRAPHY_CATALOG: Dict[str, Dict[str, str]] = {
    # Main Menu
    "main_add_to_group": {
        "styled": "✦ 𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✦",
        "plain_fallback": "ADD ME TO YOUR GROUP",
        "category": "main_menu",
        "style": "Minimal Luxury",
    },
    "main_updates": {
        "styled": "『 🎬 𝐔𝐏𝐃𝐀𝐓𝐄𝐒 』",
        "plain_fallback": "UPDATES",
        "category": "main_menu",
        "style": "Cinematic",
    },
    "main_features": {
        "styled": "✦ 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒 ✦",
        "plain_fallback": "FEATURES",
        "category": "main_menu",
        "style": "Minimal Luxury",
    },
    "main_help": {
        "styled": "◈ 𝐇𝐄𝐋𝐏 ◈",
        "plain_fallback": "HELP",
        "category": "main_menu",
        "style": "Elegant Divider",
    },
    "main_about": {
        "styled": "『 𝐀𝐁𝐎𝐔𝐓 』",
        "plain_fallback": "ABOUT",
        "category": "main_menu",
        "style": "Decorative Frame",
    },
    "main_premium_hub": {
        "styled": "♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』",
        "plain_fallback": "PREMIUM HUB",
        "category": "main_menu",
        "style": "Royal Frame",
    },
    "main_movies": {
        "styled": "『 🎬 𝐌𝐎𝐕𝐈𝐄𝐒 』",
        "plain_fallback": "MOVIES",
        "category": "main_menu",
        "style": "Cinematic",
    },
    "main_web_series": {
        "styled": "𓆩 📺 𝙒𝙀𝘽 𝙎𝙀𝙍𝙄𝙀𝙎 𓆪",
        "plain_fallback": "WEB SERIES",
        "category": "main_menu",
        "style": "Royal Gothic Accent",
    },
    "main_trending": {
        "styled": "✦ 𝐓𝐑𝐄𝐍𝐃𝐈𝐍𝐆 ✦",
        "plain_fallback": "TRENDING",
        "category": "main_menu",
        "style": "Minimal Luxury",
    },
    "main_smart_search": {
        "styled": "⌕ 𝑺𝑴𝑨𝑹𝑻 𝑺𝑬𝑨𝑹𝑪𝑯",
        "plain_fallback": "SMART SEARCH",
        "category": "main_menu",
        "style": "Premium Serif",
    },

    # Premium / VIP Hub
    "premium_buy": {
        "styled": "꧁ 👑 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 ꧂",
        "plain_fallback": "BUY PREMIUM",
        "category": "premium_vip",
        "style": "Premium Serif",
    },
    "premium_bot_plan": {
        "styled": "♕ 『 𝐁𝐎𝐓 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』",
        "plain_fallback": "BOT PREMIUM",
        "category": "premium_vip",
        "style": "Royal Frame",
    },
    "premium_vip_destinations": {
        "styled": "♛ 『 𝐕𝐈𝐏 𝐃𝐄𝐒𝐓𝐈𝐍𝐀𝐓𝐈𝐎𝐍𝐒 』",
        "plain_fallback": "VIP DESTINATIONS",
        "category": "premium_vip",
        "style": "Royal Frame",
    },
    "premium_free_trial_referrals": {
        "styled": "✦ 𝐅𝐑𝐄𝐄 𝐓𝐑𝐈𝐀𝐋 & 𝐑𝐄𝐅𝐄𝐑𝐑𝐀𝐋𝐒 ✦",
        "plain_fallback": "FREE TRIAL & REFERRALS",
        "category": "premium_vip",
        "style": "Minimal Luxury",
    },
    "premium_my_active_plans": {
        "styled": "༺ 💎 𝐌𝐘 𝐀𝐂𝐓𝐈𝐕𝐄 𝐏𝐋𝐀𝐍𝐒 ༻",
        "plain_fallback": "MY ACTIVE PLANS",
        "category": "premium_vip",
        "style": "Premium Serif",
    },
    "premium_select_bot_plan": {
        "styled": "♕ 『 𝐒𝐄𝐋𝐄𝐂𝐓 𝐁𝐎𝐓 𝐏𝐋𝐀𝐍 』",
        "plain_fallback": "SELECT BOT PLAN",
        "category": "premium_vip",
        "style": "Royal Frame",
    },
    "premium_select_vip_plan": {
        "styled": "♛ 『 𝐒𝐄𝐋𝐄𝐂𝐓 𝐕𝐈𝐏 𝐏𝐋𝐀𝐍 』",
        "plain_fallback": "SELECT VIP PLAN",
        "category": "premium_vip",
        "style": "Royal Frame",
    },
    "premium_upload_proof": {
        "styled": "⇩ 『 𝐔𝐏𝐋𝐎𝐀𝐃 𝐏𝐑𝐎𝐎𝐅 』",
        "plain_fallback": "UPLOAD PROOF",
        "category": "premium_vip",
        "style": "Decorative Frame",
    },
    "premium_my_invite_links": {
        "styled": "✦ 𝐌𝐘 𝐈𝐍𝐕𝐈𝐓𝐄 𝐋𝐈𝐍𝐊𝐒 ✦",
        "plain_fallback": "MY INVITE LINKS",
        "category": "premium_vip",
        "style": "Minimal Luxury",
    },
    "premium_contact_admin": {
        "styled": "◈ 𝐂𝐎𝐍𝐓𝐀𝐂𝐓 𝐀𝐃𝐌𝐈𝐍 ◈",
        "plain_fallback": "CONTACT ADMIN",
        "category": "premium_vip",
        "style": "Elegant Divider",
    },
    "premium_renew_upgrade": {
        "styled": "✦ 𝐑𝐄𝐍𝐄𝐖 / 𝐔𝐏𝐆𝐑𝐀𝐃𝐄 ✦",
        "plain_fallback": "RENEW / UPGRADE",
        "category": "premium_vip",
        "style": "Minimal Luxury",
    },
    "premium_qr_code": {
        "styled": "『 𝐐𝐑 𝐂𝐎𝐃𝐄 』",
        "plain_fallback": "QR CODE",
        "category": "premium_vip",
        "style": "Decorative Frame",
    },
    "premium_upi_details": {
        "styled": "『 𝐔𝐏𝐈 𝐃𝐄𝐓𝐀𝐈𝐋𝐒 』",
        "plain_fallback": "UPI DETAILS",
        "category": "premium_vip",
        "style": "Decorative Frame",
    },
    "premium_5min_trial": {
        "styled": "✧ 𝟓𝐌𝐈𝐍 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐓𝐑𝐈𝐀𝐋 ✧",
        "plain_fallback": "5MIN PREMIUM TRIAL",
        "category": "premium_vip",
        "style": "Minimal Luxury",
    },
    "premium_remove_verify": {
        "styled": "✧ 𝙐𝙉𝙇𝙊𝘾𝙆 𝙑𝙄𝙋 ✧",
        "plain_fallback": "UNLOCK VIP",
        "category": "premium_vip",
        "style": "Cinematic Premium",
    },
    "premium_season_pack": {
        "styled": "༺ 💎 𝐕𝐈𝐏 𝐒𝐄𝐀𝐒𝐎𝐍 𝐏𝐀𝐂𝐊 ༻",
        "plain_fallback": "💎 VIP Season Pack",
        "category": "premium_vip",
        "style": "Premium Serif",
    },

    # File / Download / Streaming
    "file_download_now": {
        "styled": "⇩ 『 𝑫𝑶𝑾𝑵𝑳𝑶𝑨𝑫 』",
        "plain_fallback": "DOWNLOAD",
        "category": "file_download",
        "style": "Decorative Frame",
    },
    "file_stream_online": {
        "styled": "🎬 『 𝐒𝐓𝐑𝐄𝐀𝐌 』",
        "plain_fallback": "STREAM",
        "category": "file_download",
        "style": "Cinematic",
    },
    "file_watch_download": {
        "styled": "『 🎬 𝐖𝐀𝐓𝐂𝐇 / 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』",
        "plain_fallback": "WATCH / DOWNLOAD",
        "category": "file_download",
        "style": "Cinematic",
    },
    "file_send_all": {
        "styled": "⟦ 📦 𝐒𝐄𝐍𝐃 𝐀𝐋𝐋 ⟧",
        "plain_fallback": "VIP Send All",
        "category": "file_download",
        "style": "Bold Outline",
    },
    "file_get_file": {
        "styled": "◈ 𝗦𝗘𝗡𝗗 𝗙𝗜𝗟𝗘 ◈",
        "plain_fallback": "GET FILE",
        "category": "file_download",
        "style": "Elegant Divider",
    },
    "file_verify_now": {
        "styled": "✧ 𝑪𝑶𝑵𝑭𝑰𝑹𝑴 & 𝑽𝑬𝑹𝑰𝑭𝒀 ✧",
        "plain_fallback": "VERIFY",
        "category": "file_download",
        "style": "Minimal Luxury",
    },
    "file_how_to_verify": {
        "styled": "『 𝐇𝐎𝐖 𝐓𝐎 𝐕𝐄𝐑𝐈𝐅𝐘 』",
        "plain_fallback": "HOW TO VERIFY",
        "category": "file_download",
        "style": "Decorative Frame",
    },
    "file_join_channel": {
        "styled": "『 𝐉𝐎𝐈𝐍 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 』",
        "plain_fallback": "JOIN CHANNEL",
        "category": "file_download",
        "style": "Decorative Frame",
    },
    "file_try_again": {
        "styled": "↻ 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍 ➜",
        "plain_fallback": "TRY AGAIN",
        "category": "navigation",
        "style": "Stylish Next",
    },

    # Feature 45 – Watch Ad to Unlock File
    "ad_buy_premium": {
        "styled": "♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』",
        "plain_fallback": "BUY PREMIUM",
        "category": "premium_vip",
        "style": "Royal Frame",
    },
    "ad_watch_unlock": {
        "styled": "✦ 𝐖𝐀𝐓𝐂𝐇 𝐀𝐃 & 𝐔𝐍𝐋𝐎𝐂𝐊",
        "plain_fallback": "WATCH AD & UNLOCK",
        "category": "file_download",
        "style": "Minimal Luxury",
    },
    "ad_watch_ad": {
        "styled": "『 🎬 𝐖𝐀𝐓𝐂𝐇 𝐀𝐃 』",
        "plain_fallback": "WATCH AD",
        "category": "file_download",
        "style": "Cinematic",
    },
    "ad_verify_ad": {
        "styled": "◈ 𝐕𝐄𝐑𝐈𝐅𝐘 𝐀𝐃",
        "plain_fallback": "VERIFY AD",
        "category": "file_download",
        "style": "Elegant Divider",
    },
    "ad_get_file": {
        "styled": "⇩ 𝐆𝐄𝐓 𝐅𝐈𝐋𝐄",
        "plain_fallback": "GET FILE",
        "category": "file_download",
        "style": "Double-Struck",
    },

    # Navigation
    "nav_back": {
        "styled": "◁ 𝐁𝐀𝐂𝐊",
        "plain_fallback": "BACK",
        "category": "navigation",
        "style": "Stylish Navigation",
    },
    "nav_back_to_home": {
        "styled": "◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄",
        "plain_fallback": "BACK TO HOME",
        "category": "navigation",
        "style": "Stylish Navigation",
    },
    "nav_next": {
        "styled": "𝐍𝐄𝐗𝐓 ➜",
        "plain_fallback": "NEXT",
        "category": "navigation",
        "style": "Stylish Next",
    },
    "nav_page": {
        "styled": "⟦ 𝐏𝐀𝐆𝐄 ⟧",
        "plain_fallback": "PAGE",
        "category": "navigation",
        "style": "Bold Outline",
    },
    "nav_no_more_pages": {
        "styled": "◈ 𝐍𝐎 𝐌𝐎𝐑𝐄 𝐏𝐀𝐆𝐄𝐒 ◈",
        "plain_fallback": "NO MORE PAGES",
        "category": "navigation",
        "style": "Elegant Divider",
    },
    "nav_close": {
        "styled": "『 ✕ 𝐂𝐋𝐎𝐒𝐄 』",
        "plain_fallback": "CLOSE",
        "category": "navigation",
        "style": "Decorative Frame",
    },
    "nav_confirm": {
        "styled": "✧ 𝑪𝑶𝑵𝑭𝑰𝑹𝑴 ✧",
        "plain_fallback": "CONFIRM",
        "category": "navigation",
        "style": "Minimal Luxury",
    },

    # Settings & Search Filters
    "filter_seasons": {
        "styled": "『 𝐒𝐄𝐀𝐒𝐎𝐍𝐒 』",
        "plain_fallback": "Seasons",
        "category": "settings_filters",
        "style": "Decorative Frame",
    },
    "filter_episodes": {
        "styled": "『 𝐄𝐏𝐈𝐒𝐎𝐃𝐄𝐒 』",
        "plain_fallback": "Episode",
        "category": "settings_filters",
        "style": "Decorative Frame",
    },
    "filter_languages": {
        "styled": "◈ 𝗟𝗔𝗡𝗚𝗨𝗔𝗚𝗘 ◈",
        "plain_fallback": "Language",
        "category": "settings_filters",
        "style": "Elegant Divider",
    },
    "filter_qualities": {
        "styled": "◈ 𝗤𝗨𝗔𝗟𝗜𝗧𝗬 ◈",
        "plain_fallback": "Quality",
        "category": "settings_filters",
        "style": "Elegant Divider",
    },
    "filter_select_again": {
        "styled": "✦ 𝐒𝐄𝐋𝐄𝐂𝐓 𝐀𝐆𝐀𝐈𝐍 ✦",
        "plain_fallback": "! Select Again !",
        "category": "settings_filters",
        "style": "Minimal Luxury",
    },
    "settings_main": {
        "styled": "⚙ 『 𝐒𝐄𝐓𝐓𝐈𝐍𝐆𝐒 』",
        "plain_fallback": "SETTINGS",
        "category": "settings_filters",
        "style": "Modern Frame",
    },

    # Special / Exclusive
    "special_exclusive": {
        "styled": "༒ 𝕰𝖃𝕮𝕷𝖀𝕾𝕴𝖁𝕰 ༒",
        "plain_fallback": "EXCLUSIVE",
        "category": "special_exclusive",
        "style": "Royal Gothic Accent",
    },
    "special_new_uploads": {
        "styled": "『 ✨ 𝐍𝐄𝐖 𝐔𝐏𝐋𝐎𝐀𝐃𝐒 』",
        "plain_fallback": "NEW UPLOADS",
        "category": "special_exclusive",
        "style": "Decorative Frame",
    },
    "special_brand": {
        "styled": "꧁ 𝑹𝑲𝑴𝑶𝑽𝑰𝑬𝑺𝒁𝑰𝑷 ꧂",
        "plain_fallback": "RKMOVIESZIP",
        "category": "special_exclusive",
        "style": "Premium Serif",
    },
}


def get_button_label(key: str, use_plain_fallback: bool = False) -> str:
    """Return the consistent styled button label for `key` (or its plain readable fallback)."""
    entry = BUTTON_TYPOGRAPHY_CATALOG.get(key)
    if not entry:
        return key
    if use_plain_fallback:
        return entry["plain_fallback"]
    return entry["styled"]


def get_plain_fallback_label(key: str) -> str:
    """Return the plain ASCII fallback label for `key`."""
    return get_button_label(key, use_plain_fallback=True)


# ---------------------------------------------------------------------------
# 5. Readability & Telegram Compatibility Validator (Sections 6, 8, 9 of PRD)
# ---------------------------------------------------------------------------

_DECORATIVE_GROUP_RE = re.compile(r"[♛♕♔♚✦✧⟡◈❖꧁꧂𓆩𓆪༺༻◁▷➜⇩⌕『』「」【】⟦⟧🎬▣▤◉✺༒⫷⫸]+")


def validate_button_readability(label: str) -> Dict[str, Any]:
    """Validate that a button label meets Feature 44 readability & compatibility rules."""
    text = str(label or "")
    has_colour_emoji = any(ch in FORBIDDEN_COLOUR_EMOJIS for ch in text)
    # Check UTF-8 encodability and absence of private-use / surrogate characters
    has_unrenderable = any(
        unicodedata.category(ch) in ("Cs", "Co", "Cn") for ch in text
    )
    symbol_groups = _DECORATIVE_GROUP_RE.findall(text)
    normalized_ascii = normalize_unicode_typography(text)
    char_length = len(text)
    within_telegram_limit = 1 <= char_length <= 64

    return {
        "label": text,
        "normalized_ascii": normalized_ascii,
        "char_length": char_length,
        "within_telegram_limit": within_telegram_limit,
        "symbol_group_count": len(symbol_groups),
        "max_two_symbol_groups": len(symbol_groups) <= 3,
        "zero_colour_emojis": not has_colour_emoji,
        "valid_unicode_glyphs": not has_unrenderable,
        "is_valid": (
            within_telegram_limit
            and not has_colour_emoji
            and not has_unrenderable
            and len(symbol_groups) <= 3
        ),
    }
