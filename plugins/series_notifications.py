import logging
import re
from html import escape as html_escape

from pyrogram import enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.ia_filterdb import extract_series_episode
from database.users_chats_db import db
from utils import temp

logger = logging.getLogger(__name__)


async def notify_series_trackers(bot, media):
    episode = extract_series_episode(getattr(media, "file_name", ""))
    if not episode:
        return

    series_key = db._series_key(episode["title"])
    trackers = await db.get_series_trackers(series_key)
    if not trackers:
        return

    episode_label = f"S{episode['season']:02d}E{episode['episode']:02d}"
    safe_title = re.sub(r"[^A-Za-z0-9]+", "-", episode["title"]).strip("-")
    search_token = (
        f"getfile-{safe_title[:42]}-{episode_label}"
        if safe_title else f"getfile-{episode_label}"
    )
    link = f"https://t.me/{temp.U_NAME}?start={search_token}"
    text = (
        f"📺 Naya episode aa gaya jaan: "
        f"<b>{html_escape(episode['title'])} {episode_label}</b>"
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔎 Search episode", url=link)
    ]])

    for user_id in trackers:
        try:
            claimed = await db.claim_series_episode_notification(
                user_id,
                series_key,
                episode["episode_key"],
            )
            if not claimed:
                continue
            await bot.send_message(
                user_id,
                text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception(
                "Failed to send new episode notification (user_id=%s, series=%r, episode=%s)",
                user_id,
                episode["title"],
                episode_label,
            )
