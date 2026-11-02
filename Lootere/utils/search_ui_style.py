# Premium Colourful Search UI presentation layer for RKMOVIESZIP
import inspect
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

try:
    from pyrogram.types import InlineKeyboardButton
except Exception:  # pragma: no cover - safe fallback when pyrogram is mocked in tests
    InlineKeyboardButton = None  # type: ignore

logger = logging.getLogger(__name__)

# Visual role badges matching the RKMOVIESZIP PRD:
# - normal: Red / maroon (normal search actions & filter menus)
# - file: Blue (file results, title suggestions, selectable filter values)
# - navigation: Green (pagination, back, home, close, page counters)
# - vip: Gold / yellow (VIP Send All, VIP Season Pack, locked VIP resolutions)
ROLE_BADGES: Dict[str, str] = {
    "normal": "🔴",
    "file": "🔵",
    "navigation": "🟢",
    "vip": "🟡",
}

NATIVE_STYLE_MAPPING: Dict[str, str] = {
    "normal": "danger",
    "file": "primary",
    "navigation": "success",
    "vip": "warning",
}

_ALL_BADGE_PREFIXES = tuple(f"{badge} " for badge in ROLE_BADGES.values())
_MAX_BUTTON_TEXT_LEN = 64


def inspect_button_style_capabilities(button_cls: Any = None) -> Dict[str, Any]:
    """Inspect installed Pyrogram/Pyrofork InlineKeyboardButton capabilities.

    Standard Telegram Bot API and pyrofork==2.3.43 do not support arbitrary
    per-button background color parameters on InlineKeyboardButton. This helper
    inspects the runtime constructor signature and reports whether native style
    kwargs are supported or if the safe emoji/label presentation fallback is active.
    """
    target_cls = button_cls if button_cls is not None else InlineKeyboardButton
    if target_cls is None:
        return {
            "button_class": None,
            "native_style_param": None,
            "native_color_supported": False,
            "fallback_mode": "emoji_badge_labels",
            "limitation_note": (
                "Telegram Bot API / Pyrofork InlineKeyboardButton does not expose "
                "arbitrary per-button colors; using safe emoji/label styling."
            ),
        }

    native_param: Optional[str] = None
    try:
        sig = inspect.signature(target_cls.__init__)
        for candidate in ("style", "button_color", "color"):
            if candidate in sig.parameters:
                native_param = candidate
                break
    except (TypeError, ValueError):
        native_param = None

    return {
        "button_class": getattr(target_cls, "__name__", str(target_cls)),
        "native_style_param": native_param,
        "native_color_supported": bool(native_param),
        "fallback_mode": "native_with_emoji_fallback" if native_param else "emoji_badge_labels",
        "limitation_note": (
            "Native style parameter detected on InlineKeyboardButton."
            if native_param
            else (
                "pyrofork==2.3.43 / Telegram Bot API does not support arbitrary "
                "per-button background colors; using supported emoji/label visual distinction."
            )
        ),
    }


def classify_search_button(
    text: str,
    callback_data: Optional[str] = None,
    url: Optional[str] = None,
) -> str:
    """Classify a search UI button into 'vip', 'file', 'navigation', 'normal', or 'passthrough'."""
    raw_text = str(text or "").strip()
    cb = str(callback_data or "").strip()

    # Preserve external URL buttons (e.g. dynamic sponsor buttons) untouched
    if url and not cb:
        return "passthrough"

    if not cb:
        return "passthrough"

    # 1. VIP / Premium actions -> Gold / Yellow
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

    # 2. File result & title suggestion buttons -> Blue
    if (
        cb.startswith("files#")
        or cb.startswith("search_suggestion#")
        or cb.startswith("spol#")
        or cb.startswith("playlist_add#")
    ):
        return "file"

    # 3. Pagination & navigation controls -> Green
    if cb.startswith("next_") or cb == "pages" or cb == "close_data":
        return "navigation"

    if cb.startswith("epi2#"):
        return "navigation"

    # Submenu filter callbacks: lang#, seasons#, episode#, year#, sort#
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

    # 4. Main search filter triggers & episode back button
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


def format_search_button_text(
    text: str,
    role: str,
    callback_data: Optional[str] = None,
) -> str:
    """Format a search button label with its role badge idempotently."""
    raw_text = str(text or "")
    if role not in ROLE_BADGES:
        return raw_text

    stripped = raw_text.lstrip()
    if stripped.startswith(_ALL_BADGE_PREFIXES):
        return raw_text

    badge = ROLE_BADGES[role]
    cb = str(callback_data or "")

    # Add crown accent for VIP Send All when not already decorated
    if (
        role == "vip"
        and cb.startswith("sendfiles#")
        and "👑" not in stripped
        and "💎" not in stripped
        and "🔒" not in stripped
    ):
        decorated = f"{badge} 👑 {stripped}"
    else:
        decorated = f"{badge} {stripped}"

    if len(decorated) > _MAX_BUTTON_TEXT_LEN and cb.startswith("files#"):
        decorated = decorated[: _MAX_BUTTON_TEXT_LEN - 3].rstrip() + "..."
    return decorated


def style_search_button(button: Any, button_cls: Any = None) -> Any:
    """Apply supported styling and safe label fallback to a single InlineKeyboardButton."""
    if button is None:
        return button

    text = getattr(button, "text", None)
    callback_data = getattr(button, "callback_data", None)
    url = getattr(button, "url", None)

    if text is None:
        return button

    role = classify_search_button(text, callback_data=callback_data, url=url)
    if role == "passthrough":
        return button

    styled_text = format_search_button_text(text, role, callback_data=callback_data)
    target_cls: Optional[Callable[..., Any]] = (
        button_cls if button_cls is not None else type(button)
    )
    capabilities = inspect_button_style_capabilities(target_cls)
    native_param = capabilities.get("native_style_param")

    # If the button class supports a native style parameter, attempt it with safe fallback
    if native_param and target_cls is not None:
        kwargs: Dict[str, Any] = {"text": styled_text}
        if callback_data is not None:
            kwargs["callback_data"] = callback_data
        if url is not None:
            kwargs["url"] = url
        kwargs[native_param] = NATIVE_STYLE_MAPPING.get(role, "default")
        try:
            return target_cls(**kwargs)
        except Exception:
            logger.debug(
                "Native button style %r unsupported at runtime; falling back to label style",
                native_param,
            )

    try:
        button.text = styled_text
        return button
    except Exception:
        if target_cls is not None:
            kwargs = {"text": styled_text}
            if callback_data is not None:
                kwargs["callback_data"] = callback_data
            if url is not None:
                kwargs["url"] = url
            return target_cls(**kwargs)
        return button


def apply_search_keyboard_style(
    rows: Optional[Sequence[Sequence[Any]]],
    button_cls: Any = None,
) -> List[List[Any]]:
    """Apply Premium Colourful Search UI styling across a 2D inline keyboard."""
    if not rows:
        return list(rows) if rows is not None else []

    styled_rows: List[List[Any]] = []
    for row in rows:
        if not isinstance(row, Iterable) or isinstance(row, (str, bytes)):
            continue
        styled_rows.append([style_search_button(btn, button_cls=button_cls) for btn in row])
    return styled_rows
