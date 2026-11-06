# Genuine Global Telegram Button Styling System for RKMOVIESZIP (Feature 1)
#
# Official Telegram Bot API (`InlineKeyboardButton.style`) and MTProto
# (`KeyboardButtonStyle#4fdd3430`, Layer 222+) support three background styles:
#   - "danger"  (bg_danger)  -> Red / Maroon (mapped to Normal menu & general actions)
#   - "primary" (bg_primary) -> Blue         (mapped to File / Movie / Stream / Download & VIP fallback)
#   - "success" (bg_success) -> Green        (mapped to Navigation actions: Back, Next, Close, Cancel, Try Again)
#
# Technical limitation (documented honestly per Feature 1 Section 5 & Section 12):
#   - Telegram's official Bot API and MTProto schema do NOT support a native Gold / Yellow
#     button background style; only "danger" (Red), "primary" (Blue), and "success" (Green) exist.
#   - Premium / VIP actions (`Premium Hub`, `Buy Premium`, `VIP plans`, `VIP Send All`, etc.)
#     therefore use the official "primary" (Blue) button background style as their supported
#     fallback treatment while preserving their exact labels and Feature 44 Unicode typography
#     (with strictly zero colour-indicator emojis).

import asyncio
from collections import OrderedDict
import functools
import inspect
import json
import logging
import re
import unicodedata
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore

try:
    import pyrogram
    from pyrogram import enums as pyrogram_enums
    from pyrogram.types import (
        CallbackQuery as PyrogramCallbackQuery,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Message as PyrogramMessage,
    )
except Exception:  # pragma: no cover
    pyrogram = None  # type: ignore
    pyrogram_enums = None  # type: ignore
    PyrogramCallbackQuery = None  # type: ignore
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore
    PyrogramMessage = None  # type: ignore

logger = logging.getLogger(__name__)

# Official Telegram Bot API style names:
# https://core.telegram.org/bots/api#inlinekeyboardbutton
# Only "danger" (red), "primary" (blue), and "success" (green) exist in Telegram.
# Because Telegram does not support native gold/yellow, "vip" maps to "primary" (Blue)
# as the explicit supported fallback treatment across all menus.
ROLE_TO_TELEGRAM_STYLE: Dict[str, Optional[str]] = {
    "normal": "danger",
    "file": "primary",
    "navigation": "success",
    "vip": "primary",
    "passthrough": None,
}

SUPPORTED_TELEGRAM_STYLES = frozenset({"danger", "primary", "success"})

# Regex to strip any legacy colour-indicator circle/square/diamond prefixes if present
_COLOUR_EMOJI_PREFIX_RE = re.compile(
    r"^\s*(?:[\U0001F534\U0001F535\U0001F7E2\U0001F7E1\U0001F7E0\U0001F7E3\U0001F7E4"
    r"\u26AA\u26AB\U0001F7E5\U0001F7E6\U0001F7E9\U0001F7E8\U0001F7E7\U0001F7EA\U0001F7EB"
    r"\U0001F536\U0001F537\U0001F538\U0001F539]+\s*)+"
)

# Navigation keywords checked after normalizing Unicode typography
_NAVIGATION_WORD_RE = re.compile(
    r"(?:^|\b)(?:"
    r"back|go\s+back|back\s+to\s+home|next|previous|prev|close|cancel|return|"
    r"try\s+again|delete\s+log|no,\s*abort"
    r")(?:\b|$)",
    re.IGNORECASE,
)

# Small-caps navigation tokens used in legacy keyboards
_SMALLCAPS_NAV_TOKENS = (
    "ʙᴀᴄᴋ",
    "ɴᴇxᴛ",
    "ᴄʟᴏsᴇ",
    "ᴄʟᴏꜱᴇ",
    "ᴄᴀɴᴄᴇʟ",
    "ᴛʀʏ ᴀɢᴀɪɴ",
    "ᴛʀʏ ᴀɢɪɴ",
)

# Per-message Bot API sync cache: (chat_id, message_id) -> serialized_json_str
# Cleared whenever an MTProto edit occurs on (chat_id, message_id) so subsequent syncs re-apply styles.
_LAST_SYNCED_MARKUP: "OrderedDict[Tuple[int, int], str]" = OrderedDict()
_MAX_SYNC_CACHE_SIZE = 1024

# Shared aiohttp session per running event loop for fast Bot API sync calls
_LOOP_SESSIONS: Dict[int, Any] = {}


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
        "vip_fallback_style": ROLE_TO_TELEGRAM_STYLE.get("vip"),
        "delivery_mechanism": (
            "native_mtproto_button_style"
            if native_param
            else "telegram_bot_api_reply_markup_style"
        ),
        "limitation_note": (
            "Telegram officially supports only 'danger' (red), 'primary' (blue), and "
            "'success' (green) on InlineKeyboardButton. Native gold/yellow for VIP/Premium "
            "buttons is not supported by Telegram's API, so VIP/Premium buttons use 'primary' "
            "(blue) as the supported fallback style."
        ),
    }


def _is_navigation_label(raw_text: str, norm_text: str) -> bool:
    """Return True if the button label represents a navigation action (Back, Next, Close, Cancel, Try Again)."""
    stripped = raw_text.strip()
    if not stripped:
        return False

    # Leading back/return arrows
    if stripped.startswith(("◁", "⌫", "⥢", "⬅", "«", "≪")):
        return True
    # Trailing next arrows
    if stripped.endswith(("➪", "➮", "➜")) and ("next" in norm_text or "ɴᴇxᴛ" in stripped.lower()):
        return True

    lowered_raw = stripped.lower()
    if any(tok in lowered_raw for tok in _SMALLCAPS_NAV_TOKENS):
        return True

    if _NAVIGATION_WORD_RE.search(norm_text):
        return True

    return False


def classify_search_button(
    text: str,
    callback_data: Optional[str] = None,
    url: Optional[str] = None,
) -> str:
    """Classify any inline keyboard button globally into 'vip', 'file', 'navigation', 'normal', or 'passthrough'.

    Official Role Mapping:
      - 'normal'      -> 'danger'  (Red)   : General menu & action buttons
      - 'file'        -> 'primary' (Blue)  : Movie/file selection, stream, download, verify ad
      - 'navigation'  -> 'success' (Green) : Back, Next, Close, Cancel, Return, Try Again, Page
      - 'vip'         -> 'primary' (Blue)  : Premium Hub, Buy Premium, VIP plans, VIP Send All
      - 'passthrough' -> None              : Sponsor / placeholder buttons
    """
    raw_text = strip_colour_indicator_emojis(str(text or "").strip())
    cb = str(callback_data or "").strip()
    url_str = str(url or "").strip()

    if not cb and not url_str:
        return "passthrough"

    norm_text = unicodedata.normalize("NFKD", raw_text).lower()
    raw_lower = raw_text.lower()

    # -------------------------------------------------------------------------
    # A. Existing Search-Result Keyboard Classifications (Preserved 100%)
    # -------------------------------------------------------------------------
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
        if "vip" in norm_text or "🔒" in raw_text:
            return "vip"
        return "file"

    if (
        cb.startswith("files#")
        or cb.startswith("search_suggestion#")
        or cb.startswith("spol#")
        or cb.startswith("playlist_add#")
    ):
        return "file"

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

    if cb.startswith("epi#"):
        if "back" in norm_text or "ʙᴀᴄᴋ" in raw_lower or "⥢" in raw_text or "◁" in raw_text:
            return "navigation"
        return "normal"

    if (
        cb.startswith("select_lang#")
        or cb.startswith("quality#")
        or cb.startswith("seas#")
        or cb.startswith("playlist_save#")
    ):
        return "normal"

    # -------------------------------------------------------------------------
    # B. Sponsor / External Placeholder Passthrough
    # -------------------------------------------------------------------------
    if url_str and not cb:
        if "sponsor" in norm_text or url_str.rstrip("/") == "https://example.com":
            return "passthrough"

    # -------------------------------------------------------------------------
    # C. Global Navigation Buttons -> Green ("success")
    #    (Back, Next, Previous, Close, Cancel, Return, Try Again)
    # -------------------------------------------------------------------------
    if (
        cb in ("start", "backcb", "index_cancel", "nxt", "nxt+0", "multidb#close")
        or cb.startswith(
            (
                "pay_cancel#",
                "dupclean#cancel#",
                "dupclean#close#",
                "smartstyle#cancel#",
                "setgs#auto_delete_back#",
                "checksub",
            )
        )
    ):
        return "navigation"

    if _is_navigation_label(raw_text, norm_text):
        return "navigation"

    # -------------------------------------------------------------------------
    # D. Global Premium / VIP Buttons -> Blue ("primary" fallback)
    #    (Premium Hub, Buy Premium, Bot/VIP Plans, My Active Plans, Upload Proof)
    # -------------------------------------------------------------------------
    if (
        cb
        in (
            "premium_hub",
            "premium_info",
            "premium_pm",
            "dest_plans",
            "my_plans_hub",
            "dest_invites",
            "pm_reff",
            "give_trial",
            "pay_upload_prompt",
        )
        or cb.startswith(("pay_plan_choose#", "pay_sel#"))
    ):
        return "vip"

    if any(
        phrase in norm_text
        for phrase in (
            "buy premium",
            "premium hub",
            "premium plans",
            "vip plans",
            "select bot plan",
            "select vip plan",
            "my active plans",
            "private vip invite",
            "upload proof",
            "payment proof",
            "unlock vip",
            "𝑝𝑟𝑒𝑚𝑖𝑢𝑚",
            "ᴘʀᴇᴍɪᴜᴍ",
        )
    ):
        return "vip"

    if url_str and not cb:
        # Private VIP destination invite links generated in dest_invites ("JOIN <DEST>")
        if (
            norm_text.startswith("join ")
            and "channel" not in norm_text
            and "group" not in norm_text
            and "update" not in norm_text
        ):
            return "vip"

    # -------------------------------------------------------------------------
    # E. Global File / Stream / Download / Ad-Verify Action Buttons -> Blue ("primary")
    # -------------------------------------------------------------------------
    if cb.startswith(("streaming#", "ad_deliver#", "imdb#", "release#")):
        return "file"

    if "how to" not in norm_text and any(
        phrase in norm_text or phrase in raw_lower
        for phrase in (
            "watch / download",
            "download",
            "ᴅᴏᴡɴʟᴏᴀᴅ",
            "stream",
            "ꜱᴛʀᴇᴇᴍ",
            "sᴛʀᴇᴇᴍ",
            "send file",
            "get file",
            "search episode",
            "confirm & verify",
            "verify ad",
        )
    ):
        # Exclude admin settings toggle label "Sᴛʀᴇᴀᴍ Sʜᴏʀᴛ" (callback setgs#stream_mode#...)
        if not cb.startswith("setgs#"):
            return "file"

    # -------------------------------------------------------------------------
    # F. Global Normal Menu & General Action Buttons -> Red ("danger")
    #    (/start menu: Add Me to Your Group, Updates, Features, Help, About;
    #     Help/About submenus, Admin Panel, Force Subscribe Join Channel,
    #     Watch Ad & Unlock, How to Verify/Download, QR Code, UPI Details, etc.)
    # -------------------------------------------------------------------------
    return "normal"


# Alias for global usage
classify_button = classify_search_button


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


style_button = style_search_button


def extract_inline_keyboard_rows(
    rows_or_markup: Optional[Union[Sequence[Sequence[Any]], Any]],
) -> Optional[List[List[Any]]]:
    """Extract a 2D list of InlineKeyboardButton rows from either rows or InlineKeyboardMarkup."""
    if rows_or_markup is None:
        return None
    inline_kb = getattr(rows_or_markup, "inline_keyboard", None)
    if inline_kb is not None:
        rows_or_markup = inline_kb
    if not isinstance(rows_or_markup, Iterable) or isinstance(rows_or_markup, (str, bytes, dict)):
        return None
    result: List[List[Any]] = []
    for row in rows_or_markup:
        if not isinstance(row, Iterable) or isinstance(row, (str, bytes, dict)):
            continue
        result.append(list(row))
    return result


def apply_search_keyboard_style(
    rows: Optional[Union[Sequence[Sequence[Any]], Any]],
    button_cls: Any = None,
) -> List[List[Any]]:
    """Apply genuine Telegram button styles across a 2D inline keyboard with zero colour emojis."""
    extracted = extract_inline_keyboard_rows(rows)
    if not extracted:
        return []

    styled_rows: List[List[Any]] = []
    for row in extracted:
        styled_rows.append([style_search_button(btn, button_cls=button_cls) for btn in row])
    return styled_rows


apply_global_keyboard_style = apply_search_keyboard_style


def style_inline_keyboard_markup(reply_markup: Any, button_cls: Any = None) -> Any:
    """Style an InlineKeyboardMarkup (or 2D button list) in-place and return it."""
    if reply_markup is None:
        return None
    inline_kb = getattr(reply_markup, "inline_keyboard", None)
    if inline_kb is not None:
        styled_rows = apply_search_keyboard_style(inline_kb, button_cls=button_cls)
        try:
            reply_markup.inline_keyboard = styled_rows
        except Exception:
            if InlineKeyboardMarkup is not None and isinstance(reply_markup, InlineKeyboardMarkup):
                return InlineKeyboardMarkup(styled_rows)
        return reply_markup
    if isinstance(reply_markup, list):
        return apply_search_keyboard_style(reply_markup, button_cls=button_cls)
    return reply_markup


def serialize_inline_keyboard_for_bot_api(
    rows: Optional[Union[Sequence[Sequence[Any]], Any]],
) -> Dict[str, List[List[Dict[str, Any]]]]:
    """Serialize a 2D list of styled InlineKeyboardButtons (or InlineKeyboardMarkup) into Bot API JSON format."""
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
            copy_text = getattr(btn, "copy_text", None)

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
            elif copy_text is not None:
                copy_val = getattr(copy_text, "text", copy_text)
                entry["copy_text"] = {"text": str(copy_val)}

            style_val = getattr(btn, "style", None)
            if style_val is not None:
                style_name = getattr(style_val, "name", str(style_val)).lower()
                if style_name in SUPPORTED_TELEGRAM_STYLES:
                    entry["style"] = style_name

            serialized_row.append(entry)
        if serialized_row:
            inline_keyboard.append(serialized_row)

    return {"inline_keyboard": inline_keyboard}


def invalidate_synced_markup(chat_id: Any, message_id: Any) -> None:
    """Clear the cached Bot API markup state for (chat_id, message_id) before an MTProto edit."""
    try:
        if chat_id is not None and message_id is not None:
            _LAST_SYNCED_MARKUP.pop((int(chat_id), int(message_id)), None)
    except (TypeError, ValueError):
        pass


def _record_synced_markup(chat_id: int, message_id: int, signature: str) -> None:
    key = (int(chat_id), int(message_id))
    _LAST_SYNCED_MARKUP[key] = signature
    _LAST_SYNCED_MARKUP.move_to_end(key)
    while len(_LAST_SYNCED_MARKUP) > _MAX_SYNC_CACHE_SIZE:
        _LAST_SYNCED_MARKUP.popitem(last=False)


async def _get_bot_api_http_session() -> Any:
    """Return a reusable aiohttp.ClientSession bound to the current running event loop."""
    if aiohttp is None:
        return None
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    session = _LOOP_SESSIONS.get(loop_id)
    if session is None or getattr(session, "closed", True):
        timeout = aiohttp.ClientTimeout(total=4)
        session = aiohttp.ClientSession(timeout=timeout)
        _LOOP_SESSIONS[loop_id] = session
    return session


async def sync_bot_api_reply_markup(
    chat_id: Optional[Union[int, str]],
    message_id: Optional[int],
    rows: Optional[Union[Sequence[Sequence[Any]], Any]],
    bot_token: Optional[str] = None,
) -> bool:
    """Apply genuine Bot API button styles ('danger', 'primary', 'success') via editMessageReplyMarkup.

    When running under pyrofork==2.3.43 (MTProto Layer 186, which predates Layer 222+
    KeyboardButtonStyle#4fdd3430), calling Telegram's official Bot API endpoint applies
    the actual button background colors on Telegram's server without altering button text
    or callback payloads. Returns True if Bot API accepted the update, False otherwise.
    """
    extracted_rows = extract_inline_keyboard_rows(rows)
    if chat_id is None or message_id is None or not extracted_rows or aiohttp is None:
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

    reply_markup_payload = serialize_inline_keyboard_for_bot_api(extracted_rows)
    has_any_style = any(
        "style" in btn
        for row in reply_markup_payload.get("inline_keyboard", [])
        for btn in row
    )
    if not has_any_style:
        return False

    try:
        resolved_chat_id: Union[int, str] = int(chat_id)
    except (TypeError, ValueError):
        resolved_chat_id = str(chat_id)

    resolved_msg_id = int(message_id)
    signature = json.dumps(reply_markup_payload, sort_keys=True, ensure_ascii=False)

    if isinstance(resolved_chat_id, int):
        cache_key = (resolved_chat_id, resolved_msg_id)
        if _LAST_SYNCED_MARKUP.get(cache_key) == signature:
            return True

    api_url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    payload = {
        "chat_id": resolved_chat_id,
        "message_id": resolved_msg_id,
        "reply_markup": reply_markup_payload,
    }
    try:
        session = await _get_bot_api_http_session()
        if session is None:
            return False

        async with session.post(api_url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                ok = bool(data.get("ok"))
                if ok and isinstance(resolved_chat_id, int):
                    _record_synced_markup(resolved_chat_id, resolved_msg_id, signature)
                return ok
            if resp.status == 400:
                # If Telegram reports "message is not modified", the styled markup is already active
                try:
                    err_data = await resp.json()
                    desc = str(err_data.get("description", "")).lower()
                    if "message is not modified" in desc and isinstance(resolved_chat_id, int):
                        _record_synced_markup(resolved_chat_id, resolved_msg_id, signature)
                        return True
                except Exception:
                    pass
                return False
            if resp.status == 429:
                try:
                    err_data = await resp.json()
                    retry_after = float(
                        err_data.get("parameters", {}).get("retry_after", 1)
                    )
                    if 0 < retry_after <= 3.0:
                        await asyncio.sleep(retry_after)
                        async with session.post(api_url, json=payload) as retry_resp:
                            if retry_resp.status == 200:
                                retry_data = await retry_resp.json()
                                ok = bool(retry_data.get("ok"))
                                if ok and isinstance(resolved_chat_id, int):
                                    _record_synced_markup(
                                        resolved_chat_id, resolved_msg_id, signature
                                    )
                                return ok
                except Exception:
                    pass
            return False
    except Exception:
        logger.debug("Bot API button style sync skipped/failed", exc_info=True)
        return False


async def edit_styled_reply_markup(
    query: Any,
    rows: Union[Sequence[Sequence[Any]], Any],
) -> Any:
    """Edit a callback query message's inline keyboard with genuine Telegram button styles."""
    styled_rows = apply_search_keyboard_style(rows)
    msg = getattr(query, "message", None)
    chat_id = getattr(getattr(msg, "chat", None), "id", None)
    message_id = getattr(msg, "id", None)
    invalidate_synced_markup(chat_id, message_id)

    if InlineKeyboardMarkup is not None:
        result = await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(styled_rows)
        )
    else:
        result = await query.edit_message_reply_markup(reply_markup=styled_rows)

    await sync_bot_api_reply_markup(chat_id, message_id, styled_rows)
    return result


def _extract_chat_and_message_id(
    result: Any,
    fallback_chat_id: Any = None,
    fallback_message_id: Any = None,
) -> Tuple[Optional[Union[int, str]], Optional[int]]:
    """Extract (chat_id, message_id) from a Pyrogram Message result or fallback arguments."""
    chat_id = getattr(getattr(result, "chat", None), "id", None)
    if chat_id is None:
        chat_id = fallback_chat_id
    msg_id = getattr(result, "id", None)
    if msg_id is None:
        msg_id = getattr(result, "message_id", None)
    if msg_id is None:
        msg_id = fallback_message_id
    return chat_id, msg_id


def _bind_positional_arg(
    func: Callable[..., Any],
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    param_name: str,
) -> Any:
    """Look up a parameter value by name from kwargs or positional args."""
    if param_name in kwargs:
        return kwargs[param_name]
    try:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        if param_name in params:
            idx = params.index(param_name)
            if idx < len(args):
                return args[idx]
    except Exception:
        pass
    return None


def _wrap_client_send_method(method: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(method, "_rk_global_button_style_wrapped", False):
        return method

    @functools.wraps(method)
    async def _wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        reply_markup = _bind_positional_arg(method, args, kwargs, "reply_markup")
        if reply_markup is not None:
            style_inline_keyboard_markup(reply_markup)
        result = await method(self, *args, **kwargs)
        if reply_markup is not None:
            rows = extract_inline_keyboard_rows(reply_markup)
            if rows:
                fallback_chat_id = _bind_positional_arg(method, args, kwargs, "chat_id")
                chat_id, msg_id = _extract_chat_and_message_id(
                    result, fallback_chat_id=fallback_chat_id
                )
                bot_token = getattr(self, "bot_token", None)
                await sync_bot_api_reply_markup(
                    chat_id, msg_id, rows, bot_token=bot_token
                )
        return result

    setattr(_wrapped, "_rk_global_button_style_wrapped", True)
    return _wrapped


def _wrap_client_edit_method(method: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(method, "_rk_global_button_style_wrapped", False):
        return method

    @functools.wraps(method)
    async def _wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        fallback_chat_id = _bind_positional_arg(method, args, kwargs, "chat_id")
        fallback_msg_id = _bind_positional_arg(method, args, kwargs, "message_id")
        invalidate_synced_markup(fallback_chat_id, fallback_msg_id)

        reply_markup = _bind_positional_arg(method, args, kwargs, "reply_markup")
        if reply_markup is not None:
            style_inline_keyboard_markup(reply_markup)

        result = await method(self, *args, **kwargs)
        if reply_markup is not None:
            rows = extract_inline_keyboard_rows(reply_markup)
            if rows:
                chat_id, msg_id = _extract_chat_and_message_id(
                    result,
                    fallback_chat_id=fallback_chat_id,
                    fallback_message_id=fallback_msg_id,
                )
                bot_token = getattr(self, "bot_token", None)
                await sync_bot_api_reply_markup(
                    chat_id, msg_id, rows, bot_token=bot_token
                )
        return result

    setattr(_wrapped, "_rk_global_button_style_wrapped", True)
    return _wrapped


def install_global_client_button_styling(target: Any = None) -> None:
    """Install global InlineKeyboardMarkup styling and Bot API sync hooks on Pyrogram Client classes/instances."""
    # 1. Hook InlineKeyboardMarkup.__init__ so every InlineKeyboardMarkup(rows) styles its buttons automatically
    if InlineKeyboardMarkup is not None and not getattr(
        InlineKeyboardMarkup, "_rk_init_style_wrapped", False
    ):
        orig_init = InlineKeyboardMarkup.__init__

        @functools.wraps(orig_init)
        def _styled_markup_init(self: Any, inline_keyboard: Any, *a: Any, **kw: Any) -> None:
            styled_rows = apply_search_keyboard_style(inline_keyboard)
            orig_init(self, styled_rows, *a, **kw)

        try:
            InlineKeyboardMarkup.__init__ = _styled_markup_init  # type: ignore[assignment]
            setattr(InlineKeyboardMarkup, "_rk_init_style_wrapped", True)
        except Exception:
            logger.debug("Could not wrap InlineKeyboardMarkup.__init__", exc_info=True)

    # 2. Wrap Client send_* and edit_message_* methods so every sent or edited keyboard syncs via Bot API
    targets: List[Any] = []
    if target is not None:
        targets.append(target)
    if pyrogram is not None and hasattr(pyrogram, "Client"):
        targets.append(pyrogram.Client)

    send_methods = (
        "send_message",
        "send_photo",
        "send_video",
        "send_document",
        "send_cached_media",
        "send_animation",
        "send_audio",
        "copy_message",
    )
    edit_methods = (
        "edit_message_text",
        "edit_message_caption",
        "edit_message_media",
        "edit_message_reply_markup",
    )

    for obj in targets:
        if obj is None:
            continue
        cls = obj if isinstance(obj, type) else type(obj)
        for m_name in send_methods:
            orig_m = getattr(cls, m_name, None)
            if callable(orig_m) and not getattr(orig_m, "_rk_global_button_style_wrapped", False):
                try:
                    setattr(cls, m_name, _wrap_client_send_method(orig_m))
                except Exception:
                    pass
        for m_name in edit_methods:
            orig_m = getattr(cls, m_name, None)
            if callable(orig_m) and not getattr(orig_m, "_rk_global_button_style_wrapped", False):
                try:
                    setattr(cls, m_name, _wrap_client_edit_method(orig_m))
                except Exception:
                    pass


# Automatically install on import if Pyrogram is available
install_global_client_button_styling()
