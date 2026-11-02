# Genuine Telegram Button Styling layer for RKMOVIESZIP (Feature 1)
#
# Official Telegram Bot API (`InlineKeyboardButton.style`) and MTProto
# (`KeyboardButtonStyle#4fdd3430`, Layer 222+) support three background styles:
#   - "danger"  (bg_danger)  -> Red / Maroon (mapped to Normal buttons)
#   - "primary" (bg_primary) -> Blue         (mapped to File buttons)
#   - "success" (bg_success) -> Green        (mapped to Navigation buttons)
#
# Technical limitation:
#   - Telegram does NOT support a Gold / Yellow button background style in either
#     Bot API or MTProto. VIP buttons therefore use Telegram's default button style
#     (style=None) while preserving their original clean labels (no colour emojis).

import inspect
import logging
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore

try:
    from pyrogram import enums as pyrogram_enums
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
except Exception:  # pragma: no cover
    pyrogram_enums = None  # type: ignore
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore

logger = logging.getLogger(__name__)

# Official Telegram Bot API style names:
# https://core.telegram.org/bots/api#inlinekeyboardbutton
# Only "danger" (red), "primary" (blue), and "success" (green) exist in Telegram.
# Gold/yellow ("vip") is not supported by Telegram and maps to None (default style).
ROLE_TO_TELEGRAM_STYLE: Dict[str, Optional[str]] = {
    "normal": "danger",
    "file": "primary",
    "navigation": "success",
    "vip": None,
    "passthrough": None,
}

SUPPORTED_TELEGRAM_STYLES = frozenset({"danger", "primary", "success"})

# Regex to strip any legacy colour-indicator circle/square/diamond prefixes if present
_COLOUR_EMOJI_PREFIX_RE = re.compile(
    r"^\s*(?:[\U0001F534\U0001F535\U0001F7E2\U0001F7E1\U0001F7E0\U0001F7E3\U0001F7E4"
    r"\u26AA\u26AB\U0001F7E5\U0001F7E6\U0001F7E9\U0001F7E8\U0001F7E7\U0001F7EA\U0001F7EB"
    r"\U0001F536\U0001F537\U0001F538\U0001F539]+\s*)+"
)


def strip_colour_indicator_emojis(text: str) -> str:
    """Ensure zero colour-indicator emojis appear at the start of button labels."""
    raw = str(text or "")
    cleaned = _COLOUR_EMOJI_PREFIX_RE.sub("", raw)
    # Also remove any crown that was paired with a yellow circle on VIP Send All
    if cleaned.startswith("👑 VIP Send All"):
        cleaned = cleaned[len("👑 ") :]
    return cleaned


def inspect_button_style_capabilities(button_cls: Any = None) -> Dict[str, Any]:
    """Inspect installed Pyrogram/Pyrofork version and Telegram Bot API button style support."""
    target_cls = button_cls if button_cls is not None else InlineKeyboardButton
    native_param: Optional[str] = None
    has_button_style_enum = bool(
        pyrogram_enums is not None and hasattr(pyrogram_enums, "ButtonStyle")
    )

    if target_cls is not None:
        try:
            sig = inspect.signature(target_cls.__init__)
            for candidate in ("style", "button_color", "color"):
                if candidate in sig.parameters:
                    native_param = candidate
                    break
        except (TypeError, ValueError):
            native_param = None

    return {
        "button_class": getattr(target_cls, "__name__", str(target_cls)) if target_cls else None,
        "native_style_param": native_param,
        "native_color_supported": bool(native_param),
        "has_button_style_enum": has_button_style_enum,
        "supported_telegram_styles": sorted(SUPPORTED_TELEGRAM_STYLES),
        "unavailable_requested_colours": ["gold/yellow (VIP)"],
        "delivery_mechanism": (
            "native_mtproto_button_style"
            if native_param
            else "telegram_bot_api_reply_markup_style"
        ),
        "limitation_note": (
            "Telegram officially supports only 'danger' (red), 'primary' (blue), and "
            "'success' (green) on InlineKeyboardButton. Gold/yellow for VIP buttons is "
            "not supported by Telegram's API and uses the default button style."
        ),
    }


def classify_search_button(
    text: str,
    callback_data: Optional[str] = None,
    url: Optional[str] = None,
) -> str:
    """Classify a search UI button into 'vip', 'file', 'navigation', 'normal', or 'passthrough'."""
    raw_text = strip_colour_indicator_emojis(str(text or "").strip())
    cb = str(callback_data or "").strip()

    if url and not cb:
        return "passthrough"

    if not cb:
        return "passthrough"

    # 1. VIP / Premium actions
    if (
        cb.startswith("sendfiles#")
        or cb.startswith("season_pack#")
        or cb in ("premium_info", "give_trial")
    ):
        return "vip"

    if cb.startswith("lusifilms#"):
        parts = cb.split("#")
        target = parts[2].lower() if len(parts) >= 3 else ""
        if target == "unknown":
            return "normal"
        if target == "home":
            return "navigation"
        if "vip" in raw_text.lower() or "🔒" in raw_text:
            return "vip"
        return "file"

    # 2. File result & title suggestion buttons -> Blue ("primary")
    if (
        cb.startswith("files#")
        or cb.startswith("search_suggestion#")
        or cb.startswith("spol#")
        or cb.startswith("playlist_add#")
    ):
        return "file"

    # 3. Pagination & navigation controls -> Green ("success")
    if cb.startswith("next_") or cb == "pages" or cb == "close_data":
        return "navigation"

    if cb.startswith("epi2#"):
        return "navigation"

    for prefix in ("lang#", "seasons#", "episode#"):
        if cb.startswith(prefix):
            parts = cb.split("#")
            target = parts[2].lower() if len(parts) >= 3 else ""
            if target == "unknown":
                return "normal"
            if target in ("home", "back"):
                return "navigation"
            return "file"

    if cb.startswith("year#"):
        parts = cb.split("#")
        if len(parts) == 2:
            return "normal"
        target = parts[2].lower() if len(parts) >= 3 else ""
        if target in ("home", "back"):
            return "navigation"
        return "file"

    if cb.startswith("sort#"):
        parts = cb.split("#")
        if len(parts) == 2:
            return "normal"
        target = parts[2].lower() if len(parts) >= 3 else ""
        if target in ("home", "back"):
            return "navigation"
        return "file"

    # 4. Main search filter triggers & episode back button -> Red ("danger") or Green ("success")
    if cb.startswith("epi#"):
        lowered = raw_text.lower()
        if "back" in lowered or "ʙᴀᴄᴋ" in lowered or "⥢" in raw_text:
            return "navigation"
        return "normal"

    if (
        cb.startswith("select_lang#")
        or cb.startswith("quality#")
        or cb.startswith("seas#")
        or cb.startswith("playlist_save#")
    ):
        return "normal"

    return "passthrough"


def _resolve_native_style_value(telegram_style: Optional[str]) -> Any:
    """Resolve 'danger'/'primary'/'success' to pyrogram.enums.ButtonStyle when available."""
    if not telegram_style:
        return None
    if pyrogram_enums is not None and hasattr(pyrogram_enums, "ButtonStyle"):
        enum_cls = getattr(pyrogram_enums, "ButtonStyle")
        attr_name = telegram_style.upper()
        if hasattr(enum_cls, attr_name):
            return getattr(enum_cls, attr_name)
    return telegram_style


def style_search_button(button: Any, button_cls: Any = None) -> Any:
    """Apply genuine Telegram button style metadata without adding any colour emojis to text."""
    if button is None:
        return button

    text = getattr(button, "text", None)
    callback_data = getattr(button, "callback_data", None)
    url = getattr(button, "url", None)

    if text is None:
        return button

    clean_text = strip_colour_indicator_emojis(text)
    role = classify_search_button(clean_text, callback_data=callback_data, url=url)
    telegram_style = ROLE_TO_TELEGRAM_STYLE.get(role)

    target_cls: Optional[Callable[..., Any]] = (
        button_cls if button_cls is not None else type(button)
    )
    capabilities = inspect_button_style_capabilities(target_cls)
    native_param = capabilities.get("native_style_param")

    if native_param and target_cls is not None:
        kwargs: Dict[str, Any] = {"text": clean_text}
        if callback_data is not None:
            kwargs["callback_data"] = callback_data
        if url is not None:
            kwargs["url"] = url
        if telegram_style is not None:
            kwargs[native_param] = _resolve_native_style_value(telegram_style)
        try:
            styled_btn = target_cls(**kwargs)
            try:
                setattr(styled_btn, "button_role", role)
                if getattr(styled_btn, "style", None) is None and telegram_style is not None:
                    setattr(styled_btn, "style", telegram_style)
            except Exception:
                pass
            return styled_btn
        except Exception:
            logger.debug(
                "Native button style parameter %r rejected; falling back to Bot API style attribute",
                native_param,
            )

    try:
        button.text = clean_text
    except Exception:
        if target_cls is not None:
            kwargs = {"text": clean_text}
            if callback_data is not None:
                kwargs["callback_data"] = callback_data
            if url is not None:
                kwargs["url"] = url
            button = target_cls(**kwargs)

    try:
        setattr(button, "style", telegram_style)
        setattr(button, "button_role", role)
    except Exception:
        pass
    return button


def apply_search_keyboard_style(
    rows: Optional[Sequence[Sequence[Any]]],
    button_cls: Any = None,
) -> List[List[Any]]:
    """Apply genuine Telegram button styles across a 2D inline keyboard with zero colour emojis."""
    if not rows:
        return list(rows) if rows is not None else []

    styled_rows: List[List[Any]] = []
    for row in rows:
        if not isinstance(row, Iterable) or isinstance(row, (str, bytes)):
            continue
        styled_rows.append([style_search_button(btn, button_cls=button_cls) for btn in row])
    return styled_rows


def serialize_inline_keyboard_for_bot_api(
    rows: Optional[Sequence[Sequence[Any]]],
) -> Dict[str, List[List[Dict[str, Any]]]]:
    """Serialize a 2D list of styled InlineKeyboardButtons into Telegram Bot API JSON format."""
    styled_rows = apply_search_keyboard_style(rows)
    inline_keyboard: List[List[Dict[str, Any]]] = []

    for row in styled_rows:
        serialized_row: List[Dict[str, Any]] = []
        for btn in row:
            if btn is None:
                continue
            text = strip_colour_indicator_emojis(getattr(btn, "text", ""))
            entry: Dict[str, Any] = {"text": text}

            callback_data = getattr(btn, "callback_data", None)
            url = getattr(btn, "url", None)
            web_app = getattr(btn, "web_app", None)
            switch_inline = getattr(btn, "switch_inline_query", None)
            switch_inline_current = getattr(btn, "switch_inline_query_current_chat", None)

            if callback_data is not None:
                entry["callback_data"] = (
                    callback_data.decode("utf-8", errors="replace")
                    if isinstance(callback_data, bytes)
                    else str(callback_data)
                )
            elif url is not None:
                entry["url"] = str(url)
            elif web_app is not None and getattr(web_app, "url", None):
                entry["web_app"] = {"url": str(web_app.url)}
            elif switch_inline is not None:
                entry["switch_inline_query"] = str(switch_inline)
            elif switch_inline_current is not None:
                entry["switch_inline_query_current_chat"] = str(switch_inline_current)

            style_val = getattr(btn, "style", None)
            if style_val is not None:
                style_name = getattr(style_val, "name", str(style_val)).lower()
                if style_name in SUPPORTED_TELEGRAM_STYLES:
                    entry["style"] = style_name

            serialized_row.append(entry)
        if serialized_row:
            inline_keyboard.append(serialized_row)

    return {"inline_keyboard": inline_keyboard}


async def sync_bot_api_reply_markup(
    chat_id: Optional[int],
    message_id: Optional[int],
    rows: Optional[Sequence[Sequence[Any]]],
    bot_token: Optional[str] = None,
) -> bool:
    """Apply genuine Bot API button styles ('danger', 'primary', 'success') via editMessageReplyMarkup.

    When running under pyrofork==2.3.43 (MTProto Layer 186, which predates Layer 222+
    KeyboardButtonStyle#4fdd3430), calling Telegram's official Bot API endpoint applies
    the actual button background colors on Telegram's server without altering button text
    or callback payloads. Returns True if Bot API accepted the update, False otherwise.
    """
    if chat_id is None or message_id is None or not rows or aiohttp is None:
        return False

    # If the installed Pyrogram build natively supports MTProto KeyboardButtonStyle, no HTTP sync needed
    if inspect_button_style_capabilities().get("native_color_supported"):
        return True

    token = bot_token
    if not token:
        try:
            from info import BOT_TOKEN as CONFIG_BOT_TOKEN
            token = CONFIG_BOT_TOKEN
        except Exception:
            token = None

    if not token:
        return False

    reply_markup_payload = serialize_inline_keyboard_for_bot_api(rows)
    has_any_style = any(
        "style" in btn
        for row in reply_markup_payload.get("inline_keyboard", [])
        for btn in row
    )
    if not has_any_style:
        return False

    api_url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    payload = {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "reply_markup": reply_markup_payload,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return bool(data.get("ok"))
                # Ignore "message is not modified" (400) quietly
                return False
    except Exception:
        logger.debug("Bot API button style sync skipped/failed", exc_info=True)
        return False


async def edit_styled_reply_markup(
    query: Any,
    rows: Sequence[Sequence[Any]],
) -> Any:
    """Edit a callback query message's inline keyboard with genuine Telegram button styles."""
    styled_rows = apply_search_keyboard_style(rows)
    if InlineKeyboardMarkup is not None:
        result = await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(styled_rows)
        )
    else:
        result = await query.edit_message_reply_markup(reply_markup=styled_rows)

    msg = getattr(query, "message", None)
    chat_id = getattr(getattr(msg, "chat", None), "id", None)
    message_id = getattr(msg, "id", None)
    await sync_bot_api_reply_markup(chat_id, message_id, styled_rows)
    return result

