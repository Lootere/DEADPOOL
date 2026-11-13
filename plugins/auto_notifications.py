"""Feature 46 - Admin Notification Manager (additive plugin).

Existing admin interface is command/callback based, so this module adds
`/notification` (primary), `/autonotif` plus `/autonotif_set` without touching
any existing menu.
"""
import logging
import re
from datetime import datetime, timezone as dt_timezone

from pyrogram import Client, filters, enums
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from info import ADMINS
from Lootere.utils import notification_engine as engine

logger = logging.getLogger(__name__)

MENU_CALLBACK = "autonotif#"

# Registered on every manager handler. `/notification` is the documented
# Feature 46 command; the rest stay as backwards-compatible aliases.
MANAGER_COMMANDS = (
    "notification",
    "autonotif",
    "auto_notifications",
    "notification_manager",
)

# Shown only in each admin's personal Telegram command menu (BotCommandScopeChat),
# never in the default scope, so ordinary users never see admin controls.
ADMIN_COMMAND_MENU = [
    ("notification", "Open Feature 46 auto notification manager"),
    ("autonotif", "Feature 46 auto notification manager (alias)"),
]


async def register_admin_commands(client) -> int:
    """Register the admin command menu for every configured admin.

    Idempotent and safe to call on every startup. A failure for one admin
    (for example an admin who never started the bot in private) never affects
    the others or the rest of the bot.
    """
    try:
        from pyrogram.types import BotCommand, BotCommandScopeChat
    except Exception:
        logger.error("Cannot register admin command menu: pyrogram types unavailable")
        return 0

    commands = [BotCommand(name, description) for name, description in ADMIN_COMMAND_MENU]
    registered = 0
    for admin in ADMINS:
        try:
            admin_id = int(admin)
        except (TypeError, ValueError):
            continue
        try:
            await client.set_bot_commands(
                commands, scope=BotCommandScopeChat(chat_id=admin_id)
            )
            registered += 1
        except Exception as exc:
            logger.info(
                "Admin command menu skipped for %s: %s", admin_id, type(exc).__name__
            )
    return registered


def _is_admin(user_id) -> bool:
    return str(user_id) in {str(admin) for admin in ADMINS}


def _status(value: bool) -> str:
    return "✅ ON" if value else "❌ OFF"


def _mask_destination(value) -> str:
    text = str(value or "").strip()
    return text or "not set"


def _menu_text(settings) -> str:
    channel = _mask_destination(settings.get("channel_id"))
    group = _mask_destination(settings.get("group_id"))
    button_url = str(settings.get("button_url") or "").strip() or "not set"
    return (
        "<b>🔔 AUTO NOTIFICATION MANAGER</b>\n\n"
        f"Auto notifications: {_status(bool(settings.get('enabled')))}\n"
        f"Channel: <code>{channel}</code> — {_status(bool(settings.get('channel_enabled') and settings.get('channel_id')))}\n"
        f"Group: <code>{group}</code> — {_status(bool(settings.get('group_enabled') and settings.get('group_id')))}\n\n"
        f"GET NOW text: <b>{settings.get('button_text')}</b>\n"
        f"GET NOW URL: <code>{button_url}</code>\n"
        f"Series batch window: <b>{int(settings.get('batch_window_seconds') or 300)}s</b>\n"
        f"Movie grouping: {_status(bool(settings.get('movie_quality_grouping')))} "
        f"(quiet {int(settings.get('movie_quiet_window_seconds') or 60)}s / max "
        f"{int(settings.get('movie_max_wait_seconds') or 120)}s)\n"
        f"Series grouping: {_status(bool(settings.get('series_episode_grouping')))} "
        f"(quiet {int(settings.get('series_quiet_window_seconds') or 60)}s / max "
        f"{int(settings.get('series_max_wait_seconds') or 120)}s)\n"
        f"Live update policy: <b>{settings.get('late_episode_update_policy')}</b>\n\n"
        f"Weekly digest: {_status(bool(settings.get('digest_enabled')))}\n"
        f"Digest time: <b>Sunday {settings.get('digest_time')}</b>\n"
        f"Timezone: <b>{settings.get('timezone')}</b>\n"
        f"IMDb/poster: {_status(bool(settings.get('poster_enabled')))}\n\n"
        "<i>Use the buttons below. Changes are audit-logged.</i>"
    )


def _menu_markup(settings) -> InlineKeyboardMarkup:
    master = "Turn OFF auto notifications" if settings.get("enabled") else "Turn ON auto notifications"
    digest = "Turn OFF weekly digest" if settings.get("digest_enabled") else "Turn ON weekly digest"
    rows = [
        [InlineKeyboardButton(master, callback_data="autonotif#toggle_master")],
        [
            InlineKeyboardButton("Set Channel", callback_data="autonotif#set_channel"),
            InlineKeyboardButton(
                "Channel ON/OFF", callback_data="autonotif#toggle_channel"
            ),
        ],
        [
            InlineKeyboardButton("Set Group", callback_data="autonotif#set_group"),
            InlineKeyboardButton("Group ON/OFF", callback_data="autonotif#toggle_group"),
        ],
        [
            InlineKeyboardButton("GET NOW Text", callback_data="autonotif#set_button_text"),
            InlineKeyboardButton("GET NOW URL", callback_data="autonotif#set_button_url"),
        ],
        [
            InlineKeyboardButton("Movie Caption", callback_data="autonotif#set_movie_caption"),
            InlineKeyboardButton("Series Caption", callback_data="autonotif#set_series_caption"),
        ],
        [
            InlineKeyboardButton("Batch Window", callback_data="autonotif#set_batch"),
        ],
        [
            InlineKeyboardButton(
                "Movie Group ON/OFF", callback_data="autonotif#toggle_movie_group"
            ),
            InlineKeyboardButton(
                "Series Group ON/OFF", callback_data="autonotif#toggle_series_group"
            ),
        ],
        [
            InlineKeyboardButton("Movie Quiet", callback_data="autonotif#set_movie_quiet"),
            InlineKeyboardButton("Series Quiet", callback_data="autonotif#set_series_quiet"),
        ],
        [
            InlineKeyboardButton("Max Wait", callback_data="autonotif#set_max_wait"),
            InlineKeyboardButton("Live Update", callback_data="autonotif#toggle_live_update"),
        ],
        [InlineKeyboardButton(digest, callback_data="autonotif#toggle_digest")],
        [
            InlineKeyboardButton("Digest Time", callback_data="autonotif#set_digest_time"),
            InlineKeyboardButton("Timezone", callback_data="autonotif#set_timezone"),
        ],
        [
            InlineKeyboardButton("Preview Movie", callback_data="autonotif#preview_movie"),
            InlineKeyboardButton("Preview Series", callback_data="autonotif#preview_series"),
        ],
        [
            InlineKeyboardButton("Send Test", callback_data="autonotif#test"),
            InlineKeyboardButton("Statistics", callback_data="autonotif#stats"),
        ],
        [
            InlineKeyboardButton("Failed", callback_data="autonotif#failed"),
            InlineKeyboardButton("Pending", callback_data="autonotif#pending"),
        ],
        [
            InlineKeyboardButton("Retry Failed", callback_data="autonotif#retry"),
            InlineKeyboardButton("Reset Templates", callback_data="autonotif#reset"),
        ],
        [
            InlineKeyboardButton("Digest History", callback_data="autonotif#history"),
            InlineKeyboardButton("Event History", callback_data="autonotif#event_history"),
        ],
        [InlineKeyboardButton("Publish Digest Now", callback_data="autonotif#digest_now")],
        [InlineKeyboardButton("Close", callback_data="autonotif#close")],
    ]
    return InlineKeyboardMarkup(rows)


async def _show_menu(message_or_query, settings=None, edit: bool = False):
    settings = settings or await engine.get_settings(force=True)
    text = _menu_text(settings)
    markup = _menu_markup(settings)
    if edit:
        await message_or_query.edit_text(
            text, parse_mode=enums.ParseMode.HTML, reply_markup=markup
        )
    else:
        await message_or_query.reply_text(
            text, parse_mode=enums.ParseMode.HTML, reply_markup=markup
        )


def _prompt(settings_key: str, example: str, description: str) -> str:
    return (
        f"<b>{description}</b>\n\n"
        f"Send:\n<code>/autonotif_set {settings_key} {example}</code>\n\n"
        "<i>Use /notification to return to the manager.</i>"
    )


@Client.on_message(filters.command(list(MANAGER_COMMANDS)) & filters.private)
async def auto_notification_manager(client, message):
    if not _is_admin(message.from_user.id):
        return await message.reply_text("This command is restricted to bot admins.")
    await _show_menu(message)


async def _set_destination(client, message, key: str, label: str) -> None:
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[2].strip():
        return await message.reply_text(
            f"Usage: <code>/autonotif_set {key} -1001234567890</code>"
        )
    value = parts[2].strip()
    ok, detail = await engine.check_destination(client, value)
    if not ok:
        return await message.reply_text(
            f"❌ {label} was not saved: {detail}\n\n"
            "Make sure the bot is an administrator with posting permission."
        )
    await engine.save_settings(
        message.from_user.id,
        **{key: value, f"{'channel' if key == 'channel_id' else 'group'}_enabled": True},
    )
    await message.reply_text(f"✅ {label} saved and validated: {detail}")
    await _show_menu(message)


@Client.on_message(
    filters.command(["autonotif_set", "auto_notifications_set"]) & filters.private
)
async def auto_notification_set(client, message):
    if not _is_admin(message.from_user.id):
        return await message.reply_text("This command is restricted to bot admins.")
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        return await message.reply_text(
            "Usage: <code>/autonotif_set &lt;key&gt; &lt;value&gt;</code>\n"
            "Keys: channel, group, button_text, button_url, movie_url, series_url, "
            "movie_caption, series_caption, digest_caption, batch, digest_time, timezone"
        )
    key = parts[1].strip().lower()
    value = parts[2].strip() if len(parts) > 2 else ""

    if key == "channel":
        return await _set_destination(client, message, "channel_id", "Channel")
    if key == "group":
        return await _set_destination(client, message, "group_id", "Group")
    if key == "button_text":
        await engine.save_settings(message.from_user.id, button_text=engine.normalize_button_text(value))
    elif key in {"button_url", "movie_url", "series_url"}:
        if not engine.validate_button_url(value):
            return await message.reply_text(
                "❌ Invalid URL. Use a complete http(s) link, e.g. https://t.me/yourgroup"
            )
        field = {
            "button_url": "button_url",
            "movie_url": "movie_button_url",
            "series_url": "series_button_url",
        }[key]
        await engine.save_settings(message.from_user.id, **{field: value})
    elif key in {"movie_caption", "series_caption", "digest_caption"}:
        if not value:
            return await message.reply_text("Caption template cannot be empty.")
        field = {
            "movie_caption": "movie_caption_template",
            "series_caption": "series_caption_template",
            "digest_caption": "digest_caption_template",
        }[key]
        await engine.save_settings(message.from_user.id, **{field: value})
    elif key == "batch":
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return await message.reply_text("Batch window must be a number of seconds.")
        if not 30 <= seconds <= 3600:
            return await message.reply_text("Batch window must be between 30 and 3600 seconds.")
        await engine.save_settings(message.from_user.id, batch_window_seconds=seconds)
    elif key in {"movie_quiet", "series_quiet"}:
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return await message.reply_text("Quiet window must be a number of seconds.")
        if not 10 <= seconds <= 3600:
            return await message.reply_text("Quiet window must be between 10 and 3600 seconds.")
        await engine.save_settings(
            message.from_user.id, **{f"{key}_window_seconds": seconds}
        )
    elif key in {"max_wait", "movie_max_wait", "series_max_wait"}:
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return await message.reply_text("Max wait must be a number of seconds.")
        if not 20 <= seconds <= 3600:
            return await message.reply_text("Max wait must be between 20 and 3600 seconds.")
        field = "max_wait_seconds" if key == "max_wait" else f"{key}_seconds"
        if key == "max_wait":
            await engine.save_settings(
                message.from_user.id,
                movie_max_wait_seconds=seconds,
                series_max_wait_seconds=seconds,
            )
        else:
            await engine.save_settings(message.from_user.id, **{field: seconds})
    elif key == "digest_time":
        if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", value):
            return await message.reply_text("Digest time must be HH:MM (24-hour), e.g. 21:00.")
        await engine.save_settings(message.from_user.id, digest_time=value)
    elif key == "timezone":
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(value)
        except Exception:
            return await message.reply_text(
                "Unknown timezone. Use an IANA name such as Asia/Kolkata."
            )
        await engine.save_settings(message.from_user.id, timezone=value)
    else:
        return await message.reply_text(f"Unknown key: {key}")
    await message.reply_text("✅ Setting saved.")
    await _show_menu(message)


@Client.on_message(
    filters.command(["autonotif_override", "auto_notifications_override"]) & filters.private
)
async def auto_notification_override(client, message):
    if not _is_admin(message.from_user.id):
        return await message.reply_text("This command is restricted to bot admins.")
    raw = (message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        return await message.reply_text(
            "Usage:\n<code>/autonotif_override Title | Year | Rating | Genres | Poster URL | Plot | movie|series</code>\n\n"
            "Only Title is required; omit a field to leave it empty."
        )
    parts = [part.strip() for part in raw[1].split("|")]
    parts += [""] * (7 - len(parts))
    title, year, rating, genres, poster, plot, category = parts[:7]
    if poster and not engine.validate_button_url(poster):
        return await message.reply_text("❌ Poster must be a valid http(s) image URL.")
    ok = await engine.override_metadata(
        title,
        year=year,
        rating=rating,
        genres=genres,
        poster=poster,
        plot=plot,
        category=category or "movie",
    )
    await message.reply_text(
        "✅ Metadata override saved." if ok else "❌ Could not save the override."
    )


@Client.on_callback_query(filters.regex(r"^autonotif#"))
async def auto_notification_callback(client, query: CallbackQuery):
    if not _is_admin(query.from_user.id):
        return await query.answer("Admins only.", show_alert=True)
    action = (query.data or "").split("#", 1)[1]
    settings = await engine.get_settings(force=True)

    if action == "close":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if action == "toggle_master":
        settings = await engine.save_settings(
            query.from_user.id, enabled=not bool(settings.get("enabled"))
        )
    elif action == "toggle_channel":
        settings = await engine.save_settings(
            query.from_user.id, channel_enabled=not bool(settings.get("channel_enabled"))
        )
    elif action == "toggle_group":
        settings = await engine.save_settings(
            query.from_user.id, group_enabled=not bool(settings.get("group_enabled"))
        )
    elif action == "toggle_digest":
        settings = await engine.save_settings(
            query.from_user.id, digest_enabled=not bool(settings.get("digest_enabled"))
        )
    elif action == "set_channel":
        await query.answer()
        return await query.message.reply_text(
            _prompt("channel", "-1001234567890", "Set notification channel")
        )
    elif action == "set_group":
        await query.answer()
        return await query.message.reply_text(
            _prompt("group", "-1001234567890", "Set notification group")
        )
    elif action == "set_button_text":
        await query.answer()
        return await query.message.reply_text(
            _prompt("button_text", "GET NOW", "Set GET NOW button text")
        )
    elif action == "set_button_url":
        await query.answer()
        return await query.message.reply_text(
            _prompt("button_url", "https://t.me/yourgroup", "Set GET NOW button URL")
        )
    elif action in {"set_movie_caption", "set_series_caption"}:
        await query.answer()
        key = "movie_caption" if action.endswith("movie_caption") else "series_caption"
        label = "movie" if key == "movie_caption" else "series"
        return await query.message.reply_text(
            f"<b>Edit {label} caption template</b>\n\n"
            f"Send:\n<code>/autonotif_set {key} &lt;your template&gt;</code>\n\n"
            "Supported tokens include {title_line}, {rating_line}, {genre_line}, "
            "{language_line}, {quality_line}, {description_line}, {episode_list}, "
            "{episode_count}. Empty fields are skipped automatically."
        )
    elif action == "set_batch":
        await query.answer()
        return await query.message.reply_text(
            _prompt("batch", "300", "Set series batch window (seconds)")
        )
    elif action == "toggle_movie_group":
        settings = await engine.save_settings(
            query.from_user.id,
            movie_quality_grouping=not bool(settings.get("movie_quality_grouping")),
        )
    elif action == "toggle_series_group":
        settings = await engine.save_settings(
            query.from_user.id,
            series_episode_grouping=not bool(settings.get("series_episode_grouping")),
        )
    elif action == "toggle_live_update":
        current = settings.get("late_episode_update_policy") or "edit"
        settings = await engine.save_settings(
            query.from_user.id,
            late_episode_update_policy="edit" if current != "edit" else "update_message",
            late_quality_update_policy="edit" if current != "edit" else "update_message",
        )
    elif action == "set_movie_quiet":
        await query.answer()
        return await query.message.reply_text(
            _prompt("movie_quiet", "60", "Movie quiet window (seconds, 10-3600)")
        )
    elif action == "set_series_quiet":
        await query.answer()
        return await query.message.reply_text(
            _prompt("series_quiet", "60", "Series quiet window (seconds, 10-3600)")
        )
    elif action == "set_max_wait":
        await query.answer()
        return await query.message.reply_text(
            "<b>Set absolute maximum batch wait</b>\n\n"
            "Send:\n<code>/autonotif_set max_wait 120</code>\n\n"
            "Applies to both movies and series. Must be longer than the quiet window."
        )
    elif action == "set_digest_time":
        await query.answer()
        return await query.message.reply_text(
            _prompt("digest_time", "21:00", "Set Sunday digest time (24-hour)")
        )
    elif action == "set_timezone":
        await query.answer()
        return await query.message.reply_text(
            _prompt("timezone", "Asia/Kolkata", "Set digest timezone")
        )
    elif action in {"preview_movie", "preview_series"}:
        await query.answer()
        kind = "movie" if action.endswith("movie") else "series"
        preview = await engine.preview_notification(kind)
        return await query.message.reply_text(
            f"<b>Preview ({kind})</b>\n\n{preview}",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
    elif action == "test":
        await query.answer("Sending test…")
        results = await engine.send_test_notification(client, query.from_user.id)
        lines = [f"{name}: {'✅' if ok else '❌'} {detail}" for name, ok, detail in results]
        return await query.message.reply_text(
            "<b>Test notification result</b>\n\n" + "\n".join(lines)
        )
    elif action == "stats":
        await query.answer()
        stats = await engine.get_statistics()
        last = stats.get("last_success")
        if isinstance(last, datetime):
            last = last.strftime("%Y-%m-%d %H:%M UTC")
        return await query.message.reply_text(
            "<b>📊 Notification statistics</b>\n\n"
            f"Events: <b>{stats['events']}</b>\n"
            f"Movie events: <b>{stats['movies']}</b>\n"
            f"Series batches: <b>{stats['series_batches']}</b>\n"
            f"Episodes: <b>{stats['episodes']}</b>\n"
            f"Channel posts sent: <b>{stats['channel_sent']}</b>\n"
            f"Group posts sent: <b>{stats['group_sent']}</b>\n"
            f"Failed: <b>{stats['failed']}</b>\n"
            f"Pending: <b>{stats['pending']}</b>\n"
            f"Retries: <b>{stats['retries']}</b>\n"
            f"Weekly digests: <b>{stats['digests']}</b>\n"
            f"Last success: <b>{last or 'never'}</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    elif action == "failed":
        await query.answer()
        failed = await engine.list_failed_notifications(10)
        if not failed:
            return await query.message.reply_text("No failed notifications. ✅")
        lines = [
            f"• {item.get('destination_type')} / {item.get('delivery_id')}: "
            f"{item.get('last_error') or 'unknown error'}"
            + (
                f" (poster: {item.get('poster_status')})"
                if item.get("poster_status")
                else ""
            )
            for item in failed
        ]
        return await query.message.reply_text(
            "<b>Failed notifications</b>\n\n" + "\n".join(lines),
            parse_mode=enums.ParseMode.HTML,
        )
    elif action == "pending":
        await query.answer()
        pending = await engine.list_pending_notifications(10)
        if not pending:
            return await query.message.reply_text("No pending notifications. ✅")
        lines = [
            f"• {item.get('destination_type')} / {item.get('delivery_id')} — "
            f"{item.get('status')} (attempts {item.get('attempts', 0)})"
            for item in pending
        ]
        return await query.message.reply_text(
            "<b>Pending notifications</b>\n\n" + "\n".join(lines),
            parse_mode=enums.ParseMode.HTML,
        )
    elif action == "retry":
        await query.answer("Retrying…")
        count = await engine.retry_failed_notifications()
        return await query.message.reply_text(
            f"✅ Queued <b>{count}</b> failed notification(s) for retry.",
            parse_mode=enums.ParseMode.HTML,
        )
    elif action == "history":
        await query.answer()
        history = await engine.get_digest_history(5)
        if not history:
            return await query.message.reply_text("No weekly digests have been published yet.")
        lines = []
        for item in history:
            start = item.get("period_start")
            end = item.get("period_end")
            if isinstance(start, datetime) and isinstance(end, datetime):
                period = f"{start:%d %b} – {end:%d %b}"
            else:
                period = str(item.get("period_key"))
            lines.append(f"• {period} — {item.get('page_count', 0)} page(s)")
        return await query.message.reply_text(
            "<b>Weekly digest history</b>\n\n" + "\n".join(lines),
            parse_mode=enums.ParseMode.HTML,
        )
    elif action == "event_history":
        await query.answer()
        events = await engine.get_recent_events(10)
        if not events:
            return await query.message.reply_text("No upload events recorded yet.")
        lines = []
        for event in events:
            indexed = event.get("indexed_at")
            when = indexed.strftime("%d %b %H:%M") if isinstance(indexed, datetime) else "?"
            code = event.get("episode_code") or ""
            note = ""
            if event.get("metadata_error"):
                note = " — ⚠️ metadata: " + engine.escape_text(
                    engine.safe_error_text(event.get("metadata_error"), 60)
                )
            elif event.get("metadata_source"):
                note = f" — {engine.escape_text(event.get('metadata_source'))}"
            lines.append(
                f"• {when} — {engine.escape_text(event.get('title'))} {code} "
                f"[{event.get('category')}]{note}"
            )
        return await query.message.reply_text(
            "<b>Recent upload events</b>\n\n" + "\n".join(lines),
            parse_mode=enums.ParseMode.HTML,
        )
    elif action == "reset":
        await engine.reset_templates(query.from_user.id)
        settings = await engine.get_settings(force=True)
    elif action == "digest_now":
        await query.answer("Publishing…")
        digest_id = await engine.force_publish_weekly_digest(client, query.from_user.id)
        return await query.message.reply_text(
            "✅ Weekly digest queued." if digest_id else "Could not queue the digest."
        )
    else:
        await query.answer("Unknown action.", show_alert=True)
        return

    await query.answer("Saved.")
    await _show_menu(query, settings=settings, edit=True)
