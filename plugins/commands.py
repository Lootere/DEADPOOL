# This code has been modified by @Looteredev
# Please do not remove this credit
import os
import sys
import logging
import random
import asyncio
import pytz
import time as t
from telegram import InputMediaPhoto
import requests
import string
from Script import script
from datetime import datetime, timedelta, date, time
from pyrogram import Client, filters, enums
from pyrogram.errors import ChatAdminRequired, FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from database.ia_filterdb import (
    Media,
    clear_search_results_cache,
    get_file_details,
    unpack_new_file_id,
    get_bad_files,
    get_search_results,
)
from database.users_chats_db import db
from database.Lootere_reffer import sdb
from info import *
from .pm_filter import auto_filter
from utils import get_settings, get_size, is_subscribed, is_req_subscribed, save_group_settings, temp, get_shortlink, get_seconds, get_vip_lock_message, is_resolution_locked, get_auto_delete_label, get_sponsor_button, is_valid_sponsor_button, get_premium_plans, format_premium_plans, is_valid_premium_plan, get_start_message, is_valid_welcome_message, get_search_strictness, SEARCH_STRICTNESS_LEVELS
from database.connections_mdb import active_connection
from Lootere.utils.smart_search_engine import (
    STYLE_NAMES,
    cancel_pending_style_preview,
    confirm_pending_style_preview,
    get_smart_style_config,
    select_smart_text_style,
    set_style_preview_enabled,
)
from Lootere.utils.duplicate_cleaner import (
    cancel_duplicate_cleanup,
    execute_duplicate_cleanup,
    format_duplicate_preview_text,
    get_duplicate_mode,
    scan_duplicates_preview,
    set_duplicate_mode,
)
from Lootere.utils.ad_unlock_manager import (
    ad_unlock_manager,
    build_ad_verified_delivery_keyboard,
    build_ad_verified_ready_text,
    build_daily_limit_exhausted_keyboard,
    build_daily_limit_exhausted_text,
)
import re
import json
import base64
from html import escape as html_escape
logger = logging.getLogger(__name__)

TIMEZONE = "Asia/KKolkata"


async def _send_all_vip_required(message):
    await message.reply_text(
        get_vip_lock_message(message.from_user.id),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("꧁ 👑 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 ꧂", callback_data="premium_info")
        ]])
    )


def _is_bot_admin(user_id):
    return user_id is not None and str(user_id) in {
        str(admin_id) for admin_id in ADMINS
    }


async def _get_force_sub_channel_id(client, message):
    try:
        channel_id = int(message.text.split(maxsplit=1)[1])
    except (IndexError, ValueError):
        await message.reply_text(
            "<b>Jaan, channel ID ke saath command bhejo 😉\n"
            "Example: <code>/add_fsub -1001234567890</code></b>"
        )
        return None

    try:
        channel = await client.get_chat(channel_id)
        if channel.type != enums.ChatType.CHANNEL:
            await message.reply_text(
                "<b>Sirf channel ID chalega jaan, group ID nahi ❤️</b>"
            )
            return None
        bot_member = await client.get_chat_member(channel_id, temp.ME)
    except Exception:
        logger.exception(
            "Force-sub channel validation failed (channel_id=%s, actor_id=%s)",
            channel_id,
            message.from_user.id,
        )
        await message.reply_text(
            "<b>Channel access nahi ho raha jaan. Bot ko channel mein admin banao, phir try karo ❤️</b>"
        )
        return None

    if bot_member.status not in (
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    ):
        await message.reply_text(
            "<b>Jaan, pehle bot ko us channel ka admin banao 👑</b>"
        )
        return None
    return channel_id, channel


async def _send_dynamic_force_sub_prompt(
    client, message, pre, grp_id, file_id, channels
):
    buttons = []
    for channel_id in channels:
        try:
            invite_link = await client.create_chat_invite_link(
                channel_id,
                creates_join_request=(channel_id == AUTH_REQ_CHANNEL),
            )
        except Exception:
            logger.exception(
                "Could not create force-sub invite (channel_id=%s, user_id=%s)",
                channel_id,
                message.from_user.id,
            )
            await client.send_message(
                chat_id=message.from_user.id,
                text=(
                    "<b>Jaan, abhi channel ka invite link nahi ban pa raha. "
                    "Thodi der baad try karo ya bot admin se contact karo ❤️</b>"
                ),
            )
            return

        buttons.append([
            InlineKeyboardButton("⛔️ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ ⛔️", url=invite_link.invite_link)
        ])

    if pre.startswith("allfiles"):
        retry_link = (
            f"https://t.me/{temp.U_NAME}?start=allfiles_{grp_id}_{file_id}"
        )
    else:
        retry_link = f"https://t.me/{temp.U_NAME}?start=files_{grp_id}_{file_id}"
    buttons.append([InlineKeyboardButton("♻️ ᴛʀʏ ᴀɢᴀɪɴ ♻️", url=retry_link)])
    await client.send_message(
        chat_id=message.from_user.id,
        text=script.FSUB_TXT.format(message.from_user.mention),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML,
    )


async def _get_unsubscribed_dynamic_channels(client, message):
    channels = await db.get_force_sub_channels()
    missing_channels = []
    for channel_id in channels:
        if channel_id == AUTH_REQ_CHANNEL and AUTH_REQ_CHANNEL:
            subscribed = await is_req_subscribed(client, message)
        else:
            subscribed = await is_subscribed(
                client,
                message.from_user.id,
                channel_id,
            )
        if not subscribed:
            missing_channels.append(channel_id)
    return missing_channels


async def _consume_daily_limit(
    message,
    settings,
    counter,
    setting_key,
    default_limit,
    text,
    file_id=None,
    grp_id=0,
    pre="files",
    is_premium=None,
):
    user_id = message.from_user.id
    if is_premium is None:
        is_premium = await db.has_premium_access(user_id)
    if is_premium:
        return True, None
    if not settings.get("filelock", LIMIT_MODE):
        return True, None

    limit = int(settings.get(setting_key, default_limit))
    allowed, count = await db.consume_daily_limit(
        user_id,
        counter,
        limit,
    )
    if not allowed:
        if counter == "files_count" and file_id:
            temp.CHAT[user_id] = int(grp_id or 0)
            ad_enabled = await ad_unlock_manager.is_enabled(user_db=db)
            kb = build_daily_limit_exhausted_keyboard(
                grp_id=int(grp_id or 0),
                canonical_file_id=str(file_id),
                pre=str(pre or "files"),
                ad_unlock_enabled=ad_enabled,
            )
            await message.reply_text(
                build_daily_limit_exhausted_text(),
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』",
                        callback_data="premium_info",
                    )
                ]]),
            )
    return allowed, count


async def _is_shortener_enabled(settings):
    if not settings.get("is_verify", IS_VERIFY):
        return False
    global_enabled = await db.get_setting("IS_VERIFY", default=IS_VERIFY)
    return bool(global_enabled)


async def _deny_resolution_locked_file(message, file_id, is_premium=None, file_details=None):
    user_id = message.from_user.id
    if is_premium is None:
        is_premium = await db.has_premium_access(user_id)
    if is_premium:
        return False
    if file_details is None:
        file_details = await get_file_details(file_id)
    file_name = file_details[0].file_name if file_details else None
    is_locked = await ad_unlock_manager.is_file_premium_locked(
        file_id,
        file_name=file_name,
        user_db=db,
        resolution_lock_checker=is_resolution_locked,
    )
    if not is_locked:
        return False
    await message.reply_text(
        get_vip_lock_message(user_id),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("꧁ 👑 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 ꧂", callback_data="premium_info")
        ]])
    )
    return True


async def execute_ad_unlocked_file_delivery(
    client,
    user_id: int,
    unlock_request_id: str,
    notify_callback,
):
    """Validate and deliver the exact single file unlocked via Feature 45 Watch Ad."""
    req = await ad_unlock_manager.get_request(unlock_request_id, user_db=db)
    if not req:
        return await notify_callback("Unlock request not found or expired.")

    file_id = req.get("canonical_file_id")
    grp_id = int(req.get("grp_id") or 0)
    pre = str(req.get("pre") or "files")

    files_ = await get_file_details(file_id)
    if not files_:
        return await notify_callback("Aww, ye file ab database mein available nahi hai.")
    file_obj = files_[0]

    settings = await get_settings(grp_id)
    fsub_id = settings.get("fsub_id", AUTH_CHANNEL)
    if fsub_id and int(fsub_id) != int(AUTH_REQ_CHANNEL or 0):
        try:
            if not await is_subscribed(client, user_id, int(fsub_id)):
                return await notify_callback("Pehle required update channel join karein, phir GET FILE dabayein!")
        except Exception:
            pass

    ok, msg, claimed_req = await ad_unlock_manager.begin_file_delivery(
        unlock_request_id=unlock_request_id,
        actor_user_id=user_id,
        user_db=db,
        file_name=file_obj.file_name,
        requested_file_id=file_id,
        resolution_lock_checker=is_resolution_locked,
    )
    if not ok:
        return await notify_callback(msg)

    try:
        caption_tpl = settings.get("caption", CUSTOM_FILE_CAPTION)
        f_caption = caption_tpl.format(
            file_name=file_obj.file_name,
            file_size=get_size(file_obj.file_size),
            file_caption=file_obj.caption,
        )
        f_caption += "\n\n<b>🔓 Uɴʟᴏᴄᴋᴇᴅ ᴠɪᴀ Wᴀᴛᴄʜ Aᴅ (1-Tɪᴍᴇ Fɪʟᴇ Aᴄᴄᴇss)</b>"

        button = [[
            InlineKeyboardButton(
                "『 🎬 𝐖𝐀𝐓𝐂𝐇 / 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』",
                callback_data=f"streaming#{file_id}#{grp_id}",
            )
        ]]
        sent_msg = await client.send_cached_media(
            chat_id=user_id,
            file_id=file_id,
            caption=f_caption,
            protect_content=True if pre == "filep" else False,
            reply_markup=InlineKeyboardMarkup(button),
        )
        await ad_unlock_manager.mark_delivery_consumed(
            unlock_request_id=unlock_request_id,
            delivery_reference=str(getattr(sent_msg, "id", "sent")),
            user_db=db,
        )
        await db.record_weekly_activity(user_id)
        return sent_msg
    except Exception as exc:
        logger.exception(
            "Telegram delivery failed for ad_unlock_request=%s user_id=%s",
            unlock_request_id,
            user_id,
        )
        await ad_unlock_manager.abort_delivery_for_retry(
            unlock_request_id=unlock_request_id,
            error_reason=str(exc),
            user_db=db,
        )
        return await notify_callback(
            "File bhejne mein temporary issue aaya. Aapka unlock safe hai—dobara GET FILE dabayein!"
        )


@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    try:
        try:
            await message.react(emoji=random.choice(REACTION), big=True)
        except Exception:
            pass
        user_id = message.from_user.id
        if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            buttons = [[
                        InlineKeyboardButton('✦ 𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✦', url=f'http://t.me/{temp.U_NAME}?startgroup=true')
                      ]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await message.reply_text(
                text="ᴏᴋ ɪ ᴄᴀɴ ʜᴇʟᴘ ʏᴏᴜ ᴊᴜsᴛ sᴛᴀʀᴛ ᴘᴍ", 
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            await asyncio.sleep(2)
            if not await db.get_chat(message.chat.id):
                total=await client.get_chat_members_count(message.chat.id)
                await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(temp.B_NAME, message.chat.title, message.chat.id, total, "Unknown"))       
                await db.add_chat(message.chat.id, message.chat.title, message.from_user.id)
            return 
        if not await db.is_user_exist(message.from_user.id):
            await db.add_user(message.from_user.id, message.from_user.first_name)
            try:
                await client.send_message(LOG_CHANNEL, script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention, temp.B_NAME))
            except Exception:
                pass
        if len(message.command) != 2:
            buttons = [[
                        InlineKeyboardButton('✦ 𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✦', url=f'http://telegram.me/{temp.U_NAME}?startgroup=true')
                    ],[
                        InlineKeyboardButton('『 🎬 𝐔𝐏𝐃𝐀𝐓𝐄𝐒 』', callback_data='channels'), 
                        InlineKeyboardButton('✦ 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒 ✦', callback_data='features')
                    ],[
                        InlineKeyboardButton('◈ 𝐇𝐄𝐋𝐏 ◈', callback_data='help'),
                        InlineKeyboardButton('『 𝐀𝐁𝐎𝐔𝐓 』', callback_data='about')
                    ],[
                        InlineKeyboardButton('♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』', callback_data="premium_hub")
                    ]]
            sponsor_button = await get_sponsor_button()
            if sponsor_button:
                buttons.append([sponsor_button])
            reply_markup = InlineKeyboardMarkup(buttons)
            try:
                m = await message.reply_sticker("CAACAgQAAxkBAAEKeqNlIpmeUoOEsEWOWEiPxPi3hH5q-QACbg8AAuHqsVDaMQeY6CcRojAE")
                await asyncio.sleep(1)
                await m.delete()
            except Exception:
                pass
            start_caption = await get_start_message(message.from_user.mention, temp.U_NAME, temp.B_NAME, user_id=user_id)
            try:
                await message.reply_photo(
                    photo=random.choice(PICS),
                    caption=start_caption,
                    reply_markup=reply_markup,
                    has_spoiler=True,
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                await message.reply_text(
                    text=start_caption,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            return
        if message.command[1].startswith("playlist_"):
            token = message.command[1][len("playlist_"):]
            playlist = await db.get_shared_playlist(token)
            if not playlist:
                return await message.reply_text(
                    "Ye shared playlist ab available nahi hai jaan 🥺"
                )
            header = (
                f"<b>💜 {html_escape(playlist['name'])}</b>\n"
                "<i>Shared playlist — titles only</i>\n\n"
            )
            chunks = []
            current = [header]
            for number, title in enumerate(playlist.get("items", []), start=1):
                row = f"{number}. {html_escape(str(title))}\n"
                if sum(map(len, current)) + len(row) > 3500:
                    chunks.append("".join(current))
                    current = []
                current.append(row)
            if current:
                chunks.append("".join(current))
            await message.reply_text(
                chunks[0],
                parse_mode=enums.ParseMode.HTML,
            )
            for chunk in chunks[1:]:
                await client.send_message(
                    message.chat.id,
                    chunk,
                    parse_mode=enums.ParseMode.HTML,
                )
            return
        if len(message.command) == 2 and message.command[1] in ["subscribe", "error", "okay", "help"]:
            buttons = [[
                        InlineKeyboardButton('✦ 𝐀𝐃𝐃 𝐌𝐄 𝐓𝐎 𝐘𝐎𝐔𝐑 𝐆𝐑𝐎𝐔𝐏 ✦', url=f'http://telegram.me/{temp.U_NAME}?startgroup=true')
                    ],[
                        InlineKeyboardButton('『 🎬 𝐔𝐏𝐃𝐀𝐓𝐄𝐒 』', callback_data='channels'), 
                        InlineKeyboardButton('✦ 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒 ✦', callback_data='features')
                    ],[
                        InlineKeyboardButton('◈ 𝐇𝐄𝐋𝐏 ◈', callback_data='help'),
                        InlineKeyboardButton('『 𝐀𝐁𝐎𝐔𝐓 』', callback_data='about')
                    ],[
                        InlineKeyboardButton('✦ 𝐅𝐑𝐄𝐄 𝐓𝐑𝐈𝐀𝐋 ✦', callback_data="pm_reff"), 
                        InlineKeyboardButton('꧁ 👑 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 ꧂', callback_data="premium_info")
                    ]]
            sponsor_button = await get_sponsor_button()
            if sponsor_button:
                buttons.append([sponsor_button])
            reply_markup = InlineKeyboardMarkup(buttons)
            try:
                m = await message.reply_sticker("CAACAgQAAxkBAAEKeqNlIpmeUoOEsEWOWEiPxPi3hH5q-QACbg8AAuHqsVDaMQeY6CcRojAE")
                await asyncio.sleep(1)
                await m.delete()
            except Exception:
                pass
            start_caption = await get_start_message(message.from_user.mention, temp.U_NAME, temp.B_NAME, user_id=user_id)
            try:
                await message.reply_photo(
                    photo=random.choice(PICS),
                    caption=start_caption,
                    reply_markup=reply_markup,
                    has_spoiler=True,
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception:
                await message.reply_text(
                    text=start_caption,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            return
        if len(message.command) == 2 and message.command[1] in ["Looteredev"]:
            buttons = [[
                        InlineKeyboardButton('⇩ 『 𝐒𝐄𝐍𝐃 𝐏𝐀𝐘𝐌𝐄𝐍𝐓 𝐏𝐑𝐎𝐎𝐅 』', url=f"https://t.me/{OWNER_USER_NAME}")
                      ],[
                        InlineKeyboardButton('『 ✕ 𝐂𝐋𝐎𝐒𝐄 』', callback_data='close_data')
                      ]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await message.reply_photo(
                photo=(PREMIUM_PIC),
                caption=format_premium_plans(await get_premium_plans()),
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
            return  
        if message.command[1].startswith('getfile'):
            data = message.command[1].split("-", 1)
            file_name = data[1].replace('-', ' ')
            message.text = file_name 
            await auto_filter(client, message)
            return
    
        if message.command[1].startswith("reff_"):
            try:
                user_id = int(message.command[1].split("_")[1])
            except ValueError:
                await message.reply_text("Invalid refer!")
                return
            if user_id == message.from_user.id:
                await message.reply_text("Hᴇʏ Dᴜᴅᴇ, Yᴏᴜ Cᴀɴ'ᴛ Rᴇғᴇʀ Yᴏᴜʀsᴇʟғ 🤣!\n\nsʜᴀʀᴇ ʟɪɴᴋ ʏᴏᴜʀ ғʀɪᴇɴᴅ ᴀɴᴅ ɢᴇᴛ 5 ʀᴇғᴇʀʀᴀʟ ᴘᴏɪɴᴛ ɪғ ʏᴏᴜ ᴀʀᴇ ᴄᴏʟʟᴇᴄᴛɪɴɢ 50 ʀᴇғᴇʀʀᴀʟ ᴘᴏɪɴᴛs ᴛʜᴇɴ ʏᴏᴜ ᴄᴀɴ ɢᴇᴛ 1 ᴍᴏɴᴛʜ ғʀᴇᴇ ᴘʀᴇᴍɪᴜᴍ ᴍᴇᴍʙᴇʀsʜɪᴘ.")
                return
            if sdb.is_user_in_list(message.from_user.id):
                await message.reply_text("Yᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ᴀʟʀᴇᴀᴅʏ ɪɴᴠɪᴛᴇᴅ ❗")
                return
            try:
                uss = await client.get_users(user_id)
            except Exception:
                return 	    
            sdb.add_user(message.from_user.id)
            fromuse = sdb.get_refer_points(user_id) + 10
            sdb.add_refer_points(user_id, fromuse)
            await message.reply_text(f"You have been successfully invited by {uss.mention}!")
            await client.send_message(user_id, f"𝗖𝗼𝗻𝗴𝗿𝗮𝘁𝘂𝗹𝗮𝘁𝗶𝗼𝗻𝘀! 𝗬𝗼𝘂 𝘄𝗼𝗻 𝟭𝟬 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹 𝗽𝗼𝗶𝗻𝘁 𝗯𝗲𝗰𝗮𝘂𝘀𝗲 𝗬𝗼𝘂 𝗵𝗮𝘃𝗲 𝗯𝗲𝗲𝗻 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆 𝗜𝗻𝘃𝗶𝘁𝗲𝗱 ☞{message.from_user.mention}!") 
            if fromuse == REFFER_POINT:
                await db.give_referal(user_id)
                sdb.add_refer_points(user_id, 0) 
                await client.send_message(chat_id=user_id,
                    text=f"<b>Hᴇʏ {uss.mention}\n\nYᴏᴜ ɢᴏᴛ 1 ᴍᴏɴᴛʜ ᴘʀᴇᴍɪᴜᴍ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ʙʏ ɪɴᴠɪᴛɪɴɢ 5 ᴜsᴇʀs ❗", disable_web_page_preview=True              
                    )
                for admin in ADMINS:
                    await client.send_message(chat_id=admin, text=f"Sᴜᴄᴄᴇss ғᴜʟʟʏ ᴛᴀsᴋ ᴄᴏᴍᴘʟᴇᴛᴇᴅ ʙʏ ᴛʜɪs ᴜsᴇʀ:\n\nuser Nᴀᴍᴇ: {uss.mention}\n\nUsᴇʀ ɪᴅ: {uss.id}!")	
                return
        Lootere = message
        user_id = Lootere.from_user.id  
        if len(Lootere.command) == 2:
            if Lootere.command[1].startswith(('verify', 'sendall')):
                if Lootere.command[1].startswith('sendall') and not await db.has_premium_access(message.from_user.id):
                    return await _send_all_vip_required(message)
                _, userid, verify_id, file_id = Lootere.command[1].split("_", 3)
                user_id = int(userid)
                grp_id = temp.CHAT.get(user_id, 0)
                settings = await get_settings(grp_id)         
                verify_id_info = await db.get_verify_id_info(user_id, verify_id)
                if not verify_id_info or verify_id_info["verified"]:
                    await message.reply("<b>ʟɪɴᴋ ᴇxᴘɪʀᴇᴅ ᴛʀʏ ᴀɢᴀɪɴ...</b>")
                    return
                if Lootere.command[1].startswith('verify') and await _deny_resolution_locked_file(message, file_id):
                    return
                
                ist_timezone = pytz.timezone('Asia/Kolkata')
                if await db.user_verified(user_id):
                    key = "third_verified"
                else:
                    key = "second_verified" if await db.is_user_verified(user_id) else "last_verified"
                current_time = datetime.now(tz=ist_timezone)
                result = await db.update_Lootere_user(user_id, {key:current_time})
                await db.update_verify_id_info(user_id, verify_id, {"verified":True})
                if key == "third_verified": 
                    num = 3 
                else: 
                    num =  2 if key == "second_verified" else 1
                if key == "third_verified":
                    msg = script.THIRDT_COMPLETE_TEXT
                else:
                    msg = script.SECOND_COMPLETE_TEXT if key == "second_verified" else script.VERIFY_COMPLETE_TEXT
                if Lootere.command[1].startswith('sendall'):
                    verify = f"https://telegram.me/{temp.U_NAME}?start=allfiles_{grp_id}_{file_id}"
                else:
                    verify = f"https://telegram.me/{temp.U_NAME}?start=files_{grp_id}_{file_id}"
                
                await client.send_message(settings['log'], script.VERIFIED_LOG_TEXT.format(Lootere.from_user.mention, user_id, datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d %B %Y'), num))
                btn = [[
                    InlineKeyboardButton("◈ 𝗦𝗘𝗡𝗗 𝗙𝗜𝗟𝗘 ◈", url=verify),
                ]]
                reply_markup=InlineKeyboardMarkup(btn)
                dlt=await Lootere.reply_photo(
                    photo=(VERIFY_IMG),
                    caption=msg.format(message.from_user.mention),
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML
                )
                await asyncio.sleep(600)
                await dlt.delete()
                return

            if Lootere.command[1].startswith("adverify_"):
                parts = Lootere.command[1].split("_", 2)
                if len(parts) != 3:
                    return await message.reply_text("<b>Invalid ad-unlock verification link.</b>")
                _, unlock_req_id, attempt_token = parts
                req_info = await ad_unlock_manager.get_request(unlock_req_id, user_db=db)
                file_name = None
                if req_info:
                    f_details = await get_file_details(req_info.get("canonical_file_id"))
                    if f_details:
                        file_name = f_details[0].file_name
                ok, status_msg, verified_req = await ad_unlock_manager.verify_unlock_request(
                    unlock_request_id=unlock_req_id,
                    actor_user_id=user_id,
                    verification_attempt_id=attempt_token,
                    user_db=db,
                    file_name=file_name,
                    resolution_lock_checker=is_resolution_locked,
                )
                if not ok:
                    return await message.reply_text(
                        f"<b>⚠️ {html_escape(status_msg)}</b>",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』", callback_data="premium_info")
                        ]]),
                        parse_mode=enums.ParseMode.HTML,
                    )
                expiry_secs = await ad_unlock_manager.get_expiry_seconds(user_db=db)
                display_name = verified_req.get("file_name") or verified_req.get("canonical_file_id")
                await message.reply_text(
                    build_ad_verified_ready_text(display_name, expiry_seconds=expiry_secs),
                    reply_markup=build_ad_verified_delivery_keyboard(unlock_req_id),
                    parse_mode=enums.ParseMode.HTML,
                )
                return

            if Lootere.command[1].startswith("addeliver_"):
                unlock_req_id = Lootere.command[1][len("addeliver_"):]
                await execute_ad_unlocked_file_delivery(
                    client=client,
                    user_id=user_id,
                    unlock_request_id=unlock_req_id,
                    notify_callback=lambda txt: message.reply_text(f"<b>{html_escape(txt)}</b>", parse_mode=enums.ParseMode.HTML),
                )
                return
        
        t_start = t.perf_counter()
        data = message.command[1]
        t_prem0 = t.perf_counter()
        is_premium = await db.has_premium_access(user_id)
        prem_check_ms = (t.perf_counter() - t_prem0) * 1000.0

        if data.startswith("allfiles_") and not is_premium:
            return await _send_all_vip_required(message)
        try:
            pre, grp_id, file_id = data.split('_', 2)
        except Exception:
            pre, grp_id, file_id = "", 0, data
        grp_id_int = int(grp_id) if str(grp_id).lstrip("-").isdigit() else 0
        settings = await get_settings(grp_id_int)
        missing_dynamic_channels = await _get_unsubscribed_dynamic_channels(
            client,
            message,
        )
        if missing_dynamic_channels:
            await _send_dynamic_force_sub_prompt(
                client,
                message,
                pre,
                grp_id,
                file_id,
                missing_dynamic_channels,
            )
            return

        if settings.get('fsub_id', AUTH_CHANNEL) == AUTH_REQ_CHANNEL:
            if AUTH_REQ_CHANNEL and not await is_req_subscribed(client, message):
                try:
                    invite_link = await client.create_chat_invite_link(int(AUTH_REQ_CHANNEL), creates_join_request=True)
                except ChatAdminRequired:
                    logger.error("Make sure Bot is admin in Forcesub channel")
                    return
                btn = [[
                    InlineKeyboardButton("『 𝐉𝐎𝐈𝐍 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 』", url=invite_link.invite_link)
                ]]
                if message.command[1] != "subscribe":
                    if data.startswith("allfiles"):
                        btn.append([InlineKeyboardButton("↻ 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍 ➜", url=f"https://t.me/{temp.U_NAME}?start=allfiles_{grp_id}_{file_id}")])
                    else:
                        btn.append([InlineKeyboardButton("↻ 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍 ➜", url=f"https://t.me/{temp.U_NAME}?start=files_{grp_id}_{file_id}")])
                await client.send_message(
                    chat_id=message.from_user.id,
                    text=script.FSUB_TXT.format(message.from_user.mention),
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML
                )
                return
        else:
            id = settings.get('fsub_id', AUTH_CHANNEL)
            channel = int(id)
            if settings.get('fsub_id', AUTH_CHANNEL) and not await is_subscribed(client, message.from_user.id, channel):
                invite_link = await client.create_chat_invite_link((channel), creates_join_request=True)
                btn = [[
                        InlineKeyboardButton("『 𝐉𝐎𝐈𝐍 𝐂𝐇𝐀𝐍𝐍𝐄𝐋 』", url=invite_link.invite_link)
                      ]]
                if message.command[1] != "subscribe":
                    if data.startswith("allfiles"):
                        btn.append([InlineKeyboardButton("↻ 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍 ➜", url=f"https://t.me/{temp.U_NAME}?start=allfiles_{grp_id}_{file_id}")])
                    else:
                        btn.append([InlineKeyboardButton("↻ 𝐓𝐑𝐘 𝐀𝐆𝐀𝐈𝐍 ➜", url=f"https://t.me/{temp.U_NAME}?start=files_{grp_id}_{file_id}")])
                await client.send_message(
                    chat_id=message.from_user.id,
                    text=script.FSUB_TXT.format(message.from_user.mention),
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML
                )
                return

        t_lookup0 = t.perf_counter()
        files_ = None if (data and data.startswith("allfiles")) else await get_file_details(file_id)
        file_lookup_ms = (t.perf_counter() - t_lookup0) * 1000.0

        if not data.startswith("allfiles") and await _deny_resolution_locked_file(
            message,
            file_id,
            is_premium=is_premium,
            file_details=files_,
        ):
            return

        if not is_premium:
            is_verify = await _is_shortener_enabled(settings)
            if is_verify:
                user_verified = await db.is_user_verified(user_id)
                is_second_shortener = await db.use_second_shortener(user_id, settings.get('verify_time', TWO_VERIFY_GAP))
                is_third_shortener = await db.use_third_shortener(user_id, settings.get('verify_time', THIRD_VERIFY_GAP))
                if not user_verified or is_second_shortener or is_third_shortener:
                    verify_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))
                    await db.create_verify_id(user_id, verify_id)
                    temp.CHAT[user_id] = grp_id_int
                    tutorial = settings.get('tutorial3', TUTORIAL3) if is_third_shortener else settings.get('tutorial2', TUTORIAL2) if is_second_shortener else settings.get('tutorial', TUTORIAL)

                    if Lootere.command[1].startswith('allfiles'):
                        verify = await get_shortlink(f"https://telegram.me/{temp.U_NAME}?start=sendall_{user_id}_{verify_id}_{file_id}", grp_id_int, is_second_shortener, is_third_shortener)
                    else:
                        verify = await get_shortlink(f"https://telegram.me/{temp.U_NAME}?start=verify_{user_id}_{verify_id}_{file_id}", grp_id_int, is_second_shortener, is_third_shortener)
                    if not await db.check_trial_status(user_id):
                        buttons = [[
                            InlineKeyboardButton("✧ 𝑪𝑶𝑵𝑭𝑰𝑹𝑴 & 𝑽𝑬𝑹𝑰𝑭𝒀 ✧", url=verify)
                        ],[
                            InlineKeyboardButton("『 𝐇𝐎𝐖 𝐓𝐎 𝐕𝐄𝐑𝐈𝐅𝐘 』", url=tutorial)
                        ],[
                            InlineKeyboardButton("✧ 𝟓𝐌𝐈𝐍 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐓𝐑𝐈𝐀𝐋 ✧", callback_data=f'give_trial')
                        ]]
                    else:
                        buttons = [[
                            InlineKeyboardButton("✧ 𝑪𝑶𝑵𝑭𝑰𝑹𝑴 & 𝑽𝑬𝑹𝑰𝑭𝒀 ✧", url=verify)
                        ],[
                            InlineKeyboardButton("『 𝐇𝐎𝐖 𝐓𝐎 𝐕𝐄𝐑𝐈𝐅𝐘 』", url=tutorial)
                        ],[
                            InlineKeyboardButton("✧ 𝙐𝙉𝙇𝙊𝘾𝙆 𝙑𝙄𝙋 ✧", callback_data=f'premium_info')
                        ]]
                    reply_markup=InlineKeyboardMarkup(buttons) 
                    if await db.user_verified(user_id): 
                        msg = script.THIRDT_VERIFICATION_TEXT   
                    else:        
                        msg = script.SECOND_VERIFICATION_TEXT if is_second_shortener else script.VERIFICATION_TEXT
                    d = await Lootere.reply_text(
                        text=msg.format(message.from_user.mention),
                        protect_content = False,
                        reply_markup=reply_markup,
                        parse_mode=enums.ParseMode.HTML
                    )
                    await asyncio.sleep(600) 
                    await d.delete()
                    await Lootere.delete()
                    return
        if data and data.startswith("allfiles"):
            files = temp.GETALL.get(file_id)
            if not files:
                return await message.reply('<b><i>Nᴏ Sᴜᴄʜ Fɪʟᴇ Eᴇxɪsᴛ.</b></i>')
            filesarr = []
            for file in files:
                file_id = file.file_id
                files_ = await get_file_details(file_id)
                if not files_:
                    logger.warning(
                        "Send-all file missing from database (user_id=%s)",
                        message.from_user.id,
                    )
                    continue
                files1 = files_[0]
                CAPTION = settings.get('caption', CUSTOM_FILE_CAPTION)
                f_caption = CAPTION.format(
                    file_name = files1.file_name,
                    file_size = get_size(files1.file_size),
                    file_caption=files1.caption
                )
                allowed, usage_count = await _consume_daily_limit(
                    message,
                    settings,
                    "send_all",
                    "all_limit",
                    SEND_ALL_LIMITE,
                    script.BUTTON_LIMIT,
                    is_premium=is_premium,
                )
                if not allowed:
                    if not filesarr:
                        return
                    break
                if usage_count is not None:
                    limit = int(settings.get("all_limit", SEND_ALL_LIMITE))
                    f_caption += (
                        f"<b>\n\nAʟʟ Bᴜᴛᴛᴏɴ Lɪᴍɪᴛ : "
                        f"{usage_count}/{limit}</b>"
                    )
                button = [[
                    InlineKeyboardButton("『 🎬 𝐖𝐀𝐓𝐂𝐇 / 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』", callback_data=f"streaming#{file_id}#{grp_id_int}")
                    ]]
                reply_markup=InlineKeyboardMarkup(button)
                msg = await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=file_id,
                    caption=f_caption,
                    protect_content=True if pre == 'filep' else False,
                    reply_markup=reply_markup
                )
                await db.record_weekly_activity(message.from_user.id)
                filesarr.append(msg)
            if await db.get_setting("AUTO_FILE_DELETE", default=AUTO_FILE_DELETE):
                k = await client.send_message(chat_id = message.from_user.id, text=f"<b><u>❗️❗️❗️IMPORTANT❗️️❗️❗️</u></b>\n\nThis Movie Files/Videos will be deleted in <b><u>10 mins</u> 🫥 <i></b>(Due to Copyright Issues)</i>.\n\n<b><i>Please forward this ALL Files/Videos to your Saved Messages and Start Download there</i></b>")
                await asyncio.sleep(900)
                for x in filesarr:
                    await x.delete()
                await k.edit_text("<b>Your All Files/Videos is successfully deleted!!!</b>")
            return
        if not files_:
            pre, file_id = ((base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))).decode("ascii")).split("_", 1)
            try:
                if await _deny_resolution_locked_file(message, file_id, is_premium=is_premium):
                    return
                allowed, usage_count = await _consume_daily_limit(
                    message,
                    settings,
                    "files_count",
                    "file_limit",
                    FILE_LIMITE,
                    script.FILE_LIMIT,
                    file_id=file_id,
                    grp_id=grp_id_int,
                    pre=pre,
                    is_premium=is_premium,
                )
                if not allowed:
                    return
                button = [[
                    InlineKeyboardButton("『 🎬 𝐖𝐀𝐓𝐂𝐇 / 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』", callback_data=f"streaming#{file_id}#{grp_id_int}")
                    ]]
                reply_markup=InlineKeyboardMarkup(button)
                msg = await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=file_id,
                    protect_content=True if pre == 'filep' else False,
                    reply_markup=reply_markup
                )
                await db.record_weekly_activity(message.from_user.id)
                filetype = msg.media
                file = getattr(msg, filetype.value)
                title = file.file_name
                size=get_size(file.file_size)
                f_caption = f"<code>{title}</code>"
                if CUSTOM_FILE_CAPTION:
                    try:
                        f_caption=CUSTOM_FILE_CAPTION.format(file_name= '' if title is None else title, file_size='' if size is None else size, file_caption='')
                    except Exception:
                        return
                if usage_count is not None:
                    limit = int(settings.get("file_limit", FILE_LIMITE))
                    f_caption += (
                        f"\n\n<b>Dᴀɪʟʏ Fɪʟᴇ Lɪᴍɪᴛ: "
                        f"{usage_count}/{limit}</b>"
                    )
                await msg.edit_caption(f_caption, reply_markup=reply_markup)
                return
            except Exception as exc:
                logger.exception(
                    "Legacy file delivery failed (user_id=%s, error_type=%s)",
                    message.from_user.id,
                    type(exc).__name__,
                )
                return await message.reply(
                    "Aww, file bhejne mein issue aa gaya. Dobara try karo."
                )

        # Check daily limit BEFORE building delivery buttons or sending media
        t_limit0 = t.perf_counter()
        allowed, usage_count = await _consume_daily_limit(
            message,
            settings,
            "files_count",
            "file_limit",
            FILE_LIMITE,
            script.FILE_LIMIT,
            file_id=file_id,
            grp_id=grp_id_int,
            pre=pre,
            is_premium=is_premium,
        )
        limit_check_ms = (t.perf_counter() - t_limit0) * 1000.0
        if not allowed:
            logger.info(
                "Daily limit exhausted routed to Feature 45 options (user_id=%s, prem_ms=%.1f, lookup_ms=%.1f, limit_ms=%.1f)",
                user_id,
                prem_check_ms,
                file_lookup_ms,
                limit_check_ms,
            )
            return

        files = files_[0]
        CAPTION = settings.get('caption', CUSTOM_FILE_CAPTION)
        f_caption = CAPTION.format(
            file_name = files.file_name,
            file_size = get_size(files.file_size),
            file_caption=files.caption
        )
        if usage_count is not None:
            limit = int(settings.get("file_limit", FILE_LIMITE))
            f_caption += (
                f"<b>\n\nDᴀɪʟʏ Fɪʟᴇ Lɪᴍɪᴛ: "
                f"{usage_count}/{limit}</b>"
            )
        button = [[
            InlineKeyboardButton("『 🎬 𝐖𝐀𝐓𝐂𝐇 / 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃 』", callback_data=f"streaming#{file_id}#{grp_id_int}")
            ]]
        reply_markup=InlineKeyboardMarkup(button)
        t_send0 = t.perf_counter()
        msg=await client.send_cached_media(
            chat_id=message.from_user.id,
            file_id=file_id,
            caption=f_caption,
            protect_content=True if pre == 'filep' else False,
            reply_markup=reply_markup
        )
        send_ms = (t.perf_counter() - t_send0) * 1000.0
        total_ms = (t.perf_counter() - t_start) * 1000.0
        logger.info(
            "File delivered (user_id=%s, count=%s, prem_ms=%.1f, lookup_ms=%.1f, limit_ms=%.1f, send_ms=%.1f, total_ms=%.1f)",
            user_id,
            usage_count,
            prem_check_ms,
            file_lookup_ms,
            limit_check_ms,
            send_ms,
            total_ms,
        )
        await db.record_weekly_activity(message.from_user.id)
        if await db.get_setting("AUTO_FILE_DELETE", default=AUTO_FILE_DELETE):
            del_msg=await message.reply("<b>⚠️ᴛʜɪs ғɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ᴀғᴛᴇʀ 10 ᴍɪɴᴜᴛᴇs\n\nᴘʟᴇᴀsᴇ ғᴏʀᴡᴀʀᴅ ᴛʜᴇ ғɪʟᴇ sᴏᴍᴇᴡʜᴇʀᴇ ʙᴇғᴏʀᴇ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ..</b>") 
            Lootere = msg
            await asyncio.sleep(900)
            await Lootere.delete() 
            await del_msg.edit_text("<b>ʏᴏᴜʀ ғɪʟᴇ ᴡᴀs ᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ ᴀғᴛᴇʀ 10 ᴍɪɴᴜᴛᴇs ᴛᴏ ᴀᴠᴏɪᴅ ᴄᴏᴘʏʀɪɢʜᴛ 📢</b>")
    except Exception as exc:
        logger.exception(
            "File delivery failed (user_id=%s, error_type=%s)",
            getattr(getattr(message, "from_user", None), "id", None),
            type(exc).__name__,
        )
        await message.reply(
            "Aww, file bhejne mein issue aa gaya. Thodi der baad try karo."
        )
        
@Client.on_message(filters.command("leaderboard"))
async def weekly_leaderboard(client, message):
    week = db.current_activity_week()
    users = await db.get_weekly_leaderboard(limit=10)
    if not users:
        return await message.reply_text(
            "Jaan, is hafte abhi koi file activity nahi hai. Pehli file bhejo ❤️"
        )

    rows = [
        "<b>🏆 Is hafte ke most active users 🏆</b>",
        f"<i>Week: {week} · Files delivered</i>",
        "",
    ]
    medals = ("🥇", "🥈", "🥉")
    for rank, user in enumerate(users, start=1):
        name = html_escape(str(user.get("name") or "User"))
        user_id = int(user["id"])
        count = int(user.get("weekly_activity_count", 0))
        medal = medals[rank - 1] if rank <= len(medals) else f"{rank}."
        rows.append(f"{medal} <a href=\"tg://user?id={user_id}\">{name}</a> — {count}")

    await message.reply_text(
        "\n".join(rows),
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


def _playlist_command_argument(message):
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


@Client.on_message(filters.private & filters.command("trackseries"))
async def track_series(client, message):
    title = _playlist_command_argument(message)
    if not title:
        return await message.reply_text(
            "Aise track karo jaan: <code>/trackseries The Boys</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        added = await db.add_series_track(
            message.from_user.id,
            title,
            message.from_user.first_name or "User",
        )
    except ValueError as error:
        return await message.reply_text(
            f"Oops jaan, {html_escape(str(error))} 😉",
            parse_mode=enums.ParseMode.HTML,
        )
    if added:
        return await message.reply_text(
            f"<b>{html_escape(title)}</b> track ho gayi jaan 💜 "
            "Naya episode index hote hi bataungi.",
            parse_mode=enums.ParseMode.HTML,
        )
    await message.reply_text("Ye series pehle se tumhari tracking list mein hai jaan 😉")


@Client.on_message(filters.private & filters.command("untrackseries"))
async def untrack_series(client, message):
    title = _playlist_command_argument(message)
    if not title:
        return await message.reply_text(
            "Aise band karo jaan: <code>/untrackseries The Boys</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await db.remove_series_track(message.from_user.id, title):
        return await message.reply_text("Ye series tumhari list mein nahi mili jaan 🥺")
    await message.reply_text(
        f"<b>{html_escape(title)}</b> ki tracking band kar di jaan ❤️",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.private & filters.command("myseries"))
async def list_tracked_series(client, message):
    tracks = await db.get_user_series_tracks(message.from_user.id)
    if not tracks:
        return await message.reply_text(
            "Abhi koi series track nahi ho rahi jaan 💜\n"
            "Shuru karo: <code>/trackseries The Boys</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    rows = ["<b>💜 Tumhari tracked series 💜</b>", ""]
    rows.extend(f"• {html_escape(track['title'])}" for track in tracks)
    rows.extend([
        "",
        "<code>/trackseries &lt;series name&gt;</code> — track karo",
        "<code>/untrackseries &lt;series name&gt;</code> — tracking band karo",
    ])
    await message.reply_text(
        "\n".join(rows),
        parse_mode=enums.ParseMode.HTML,
    )


async def _find_user_playlist(user_id, name):
    normalized_name = " ".join(name.split()).casefold()
    playlists = await db.get_user_playlists(user_id)
    return next(
        (
            playlist for playlist in playlists
            if " ".join(playlist["name"].split()).casefold() == normalized_name
        ),
        None,
    )


@Client.on_message(filters.private & filters.command("playlist"))
async def list_user_playlists(client, message):
    playlists = await db.get_user_playlists(message.from_user.id)
    if not playlists:
        return await message.reply_text(
            "Abhi koi playlist nahi hai jaan 💜\n"
            "Banao: <code>/playlist_new Watchlist</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    rows = ["<b>💜 Tumhari playlists 💜</b>", ""]
    rows.extend(
        f"• {html_escape(playlist['name'])} — "
        f"{len(playlist.get('items', []))}/25 titles"
        for playlist in playlists
    )
    rows.extend([
        "",
        "<code>/playlist_new Watchlist</code> — nayi list",
        "<code>/playlist_add Watchlist | Jailer</code> — title add karo",
        "<code>/playlist_remove Watchlist | Jailer</code> — title hatao",
        "<code>/playlist_delete Watchlist</code> — list delete karo",
        "<code>/playlist_view &lt;name&gt;</code> — titles dekho",
        "<code>/playlist_share &lt;name&gt;</code> — share link banao",
    ])
    await message.reply_text(
        "\n".join(rows),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.private & filters.command("playlist_new"))
async def create_user_playlist(client, message):
    name = _playlist_command_argument(message)
    if not name:
        return await message.reply_text(
            "Aise banao jaan: <code>/playlist_new Anime Watchlist</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        await db.create_playlist(message.from_user.id, name)
    except ValueError as error:
        return await message.reply_text(
            f"Oops jaan, {html_escape(str(error))} 😉",
            parse_mode=enums.ParseMode.HTML,
        )
    await message.reply_text(
        f"<b>Playlist “{html_escape(name)}” ban gayi 💜</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.private & filters.command("playlist_add"))
async def add_title_to_playlist(client, message):
    parts = _playlist_command_argument(message).split("|", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return await message.reply_text(
            "Aise add karo jaan:\n"
            "<code>/playlist_add Watchlist | Jailer</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    name, title = (part.strip() for part in parts)
    playlist = await _find_user_playlist(message.from_user.id, name)
    if not playlist:
        return await message.reply_text(
            "Pehle <code>/playlist_new Watchlist</code> se playlist banao jaan ❤️",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        added = await db.add_playlist_item(
            message.from_user.id,
            playlist["playlist_id"],
            title,
        )
    except ValueError as error:
        return await message.reply_text(
            f"Oops jaan, {html_escape(str(error))} 😉",
            parse_mode=enums.ParseMode.HTML,
        )
    result = "Playlist mein add ho gaya jaan 💜" if added else "Ye title pehle se hai jaan 😉"
    await message.reply_text(result)


@Client.on_message(filters.private & filters.command("playlist_remove"))
async def remove_title_from_playlist(client, message):
    parts = _playlist_command_argument(message).split("|", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return await message.reply_text(
            "Aise remove karo jaan:\n"
            "<code>/playlist_remove Watchlist | Jailer</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    name, title = (part.strip() for part in parts)
    if not await db.remove_playlist_item(message.from_user.id, name, title):
        return await message.reply_text("Playlist ya title nahi mila jaan 🥺")
    await message.reply_text("Title playlist se remove ho gaya jaan ❤️")


@Client.on_message(filters.private & filters.command("playlist_delete"))
async def delete_user_playlist(client, message):
    name = _playlist_command_argument(message)
    if not name:
        return await message.reply_text(
            "Aise delete karo jaan: <code>/playlist_delete Watchlist</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await db.delete_playlist(message.from_user.id, name):
        return await message.reply_text("Ye playlist nahi mili jaan 🥺")
    await message.reply_text("Playlist delete ho gayi jaan ❤️")


@Client.on_message(filters.private & filters.command("playlist_view"))
async def view_user_playlist(client, message):
    name = _playlist_command_argument(message)
    playlist = await _find_user_playlist(message.from_user.id, name) if name else None
    if not playlist:
        return await message.reply_text(
            "Playlist nahi mili jaan. <code>/playlist</code> se apni lists dekho.",
            parse_mode=enums.ParseMode.HTML,
        )
    chunks = [[f"<b>💜 {html_escape(playlist['name'])}</b>\n"]]
    for number, title in enumerate(playlist.get("items", []), start=1):
        row = f"{number}. {html_escape(str(title))}\n"
        if sum(map(len, chunks[-1])) + len(row) > 3500:
            chunks.append([])
        chunks[-1].append(row)
    for chunk in chunks:
        await message.reply_text(
            "".join(chunk),
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.private & filters.command("playlist_share"))
async def share_user_playlist(client, message):
    name = _playlist_command_argument(message)
    playlist = await _find_user_playlist(message.from_user.id, name) if name else None
    if not playlist:
        return await message.reply_text(
            "Aise share karo jaan: <code>/playlist_share Watchlist</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    if not playlist.get("items"):
        return await message.reply_text("Pehle playlist mein koi title add karo jaan 💜")
    token = await db.get_playlist_share_token(message.from_user.id, name)
    if not token:
        raise RuntimeError("Unable to create playlist share token")
    link = f"https://t.me/{temp.U_NAME}?start=playlist_{token}"
    await message.reply_text(
        f"<b>Yeh raha tumhara share link jaan 💜</b>\n<code>{link}</code>",
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
           
    """Send basic information of channel"""
    if isinstance(CHANNELS, (int, str)):
        channels = [CHANNELS]
    elif isinstance(CHANNELS, list):
        channels = CHANNELS
    else:
        raise ValueError("Uɴᴇxᴘᴇᴄᴛᴇᴅ ᴛʏᴘᴇ ᴏғ CHANNELS")

    text = '📑 **Iɴᴅᴇxᴇᴅ ᴄʜᴀɴɴᴇʟs/ɢʀᴏᴜᴘs**\n'
    for channel in channels:
        chat = await bot.get_chat(channel)
        if chat.username:
            text += '\n@' + chat.username
        else:
            text += '\n' + chat.title or chat.first_name

    text += f'\n\n**Total:** {len(CHANNELS)}'

    if len(text) < 4096:
        await message.reply(text)
    else:
        file = 'Indexed channels.txt'
        with open(file, 'w') as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)


@Client.on_message(filters.command('logs') & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    try:
        await message.reply_document('Logs.txt')
    except Exception as e:
        await message.reply(str(e))

@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    """Delete file from database"""
    reply = message.reply_to_message
    if reply and reply.media:
        msg = await message.reply("Pʀᴏᴄᴇssɪɴɢ...⏳", quote=True)
    else:
        await message.reply('Rᴇᴘʟʏ ᴛᴏ ғɪʟᴇ ᴡɪᴛʜ /delete ᴡʜɪᴄʜ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴇʟᴇᴛᴇ', quote=True)
        return

    for file_type in ("document", "video", "audio"):
        media = getattr(reply, file_type, None)
        if media is not None:
            break
    else:
        await msg.edit('Tʜɪs ɪs ɴᴏᴛ sᴜᴘᴘᴏʀᴛᴇᴅ ғɪʟᴇ ғᴏʀᴍᴀᴛ')
        return
    
    file_id, file_ref = unpack_new_file_id(media.file_id)

    result = await Media.collection.delete_one({
        '_id': file_id,
    })
    if result.deleted_count:
        await msg.edit('Fɪʟᴇ ɪs sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ғʀᴏᴍ ᴅᴀᴛᴀʙᴀsᴇ')
    else:
        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(media.file_name))
        result = await Media.collection.delete_many({
            'file_name': file_name,
            'file_size': media.file_size,
            'mime_type': media.mime_type
            })
        if result.deleted_count:
            await msg.edit('Fɪʟᴇ ɪs sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ғʀᴏᴍ ᴅᴀᴛᴀʙᴀsᴇ')
        else:
            # files indexed before https://github.com/EvamariaTG/EvaMaria/commit/f3d2a1bcb155faf44178e5d7a685a1b533e714bf#diff-86b613edf1748372103e94cacff3b578b36b698ef9c16817bb98fe9ef22fb669R39 
            # have original file name.
            result = await Media.collection.delete_many({
                'file_name': media.file_name,
                'file_size': media.file_size,
                'mime_type': media.mime_type
            })
            if result.deleted_count:
                await msg.edit('Fɪʟᴇ ɪs sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ғʀᴏᴍ ᴅᴀᴛᴀʙᴀsᴇ')
            else:
                await msg.edit('Fɪʟᴇ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ')
    if result.deleted_count:
        clear_search_results_cache()


@Client.on_message(filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_index(bot, message):
    await message.reply_text(
        'Tʜɪs ᴡɪʟʟ ᴅᴇʟᴇᴛᴇ ᴀʟʟ ɪɴᴅᴇxᴇᴅ ғɪʟᴇs.\nDᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ ?',
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Yᴇs", callback_data="autofilter_delete"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Cᴀɴᴄᴇʟ", callback_data="close_data"
                    )
                ],
            ]
        ),
        quote=True,
    )


@Client.on_callback_query(filters.regex(r'^autofilter_delete'))
async def delete_all_index_confirm(bot, message):
    await Media.collection.drop()
    clear_search_results_cache()
    await message.answer("Eᴠᴇʀʏᴛʜɪɴɢ's Gᴏɴᴇ")
    await message.message.edit('Sᴜᴄᴄᴇsғᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ Aʟʟ Tʜᴇ Iɴᴅᴇxᴇᴅ Fɪʟᴇs.')


@Client.on_message(filters.command('settings'))
async def settings(client, message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply(f"Yᴏᴜ ᴀʀᴇ ᴀɴᴏɴʏᴍᴏᴜs ᴀᴅᴍɪɴ. Usᴇ /connect {message.chat.id} ɪɴ PM")
    chat_type = message.chat.type

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if grpid is not None:
            grp_id = grpid
            try:
                chat = await client.get_chat(grpid)
                title = chat.title
            except:
                await message.reply_text("Mᴀᴋᴇ sᴜʀᴇ I'ᴍ ᴘʀᴇsᴇɴᴛ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ !", quote=True)
                return
        else:
            await message.reply_text("I'ᴍ ɴᴏᴛ ᴄᴏɴɴᴇᴄᴛᴇᴅ ᴛᴏ ᴀɴʏ ɢʀᴏᴜᴘs !", quote=True)
            return

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
        title = message.chat.title

    else:
        return

    st = await client.get_chat_member(grp_id, userid)
    if (
            st.status != enums.ChatMemberStatus.ADMINISTRATOR
            and st.status != enums.ChatMemberStatus.OWNER
            and str(userid) not in ADMINS
    ):
        return
    
    settings = await get_settings(grp_id)

    try:
        if settings['max_btn']:
            settings = await get_settings(grp_id)
    except KeyError:
        await save_group_settings(grp_id, 'max_btn', False)
        settings = await get_settings(grp_id)
    else:
        pass

    if settings is not None:
        buttons = [
            [
                InlineKeyboardButton('Rᴇꜱᴜʟᴛ Pᴀɢᴇ', callback_data=f'setgs#button#{settings["button"]}#{grp_id}',),
                InlineKeyboardButton('Tᴇxᴛ' if settings["button"] else 'Bᴜᴛᴛᴏɴ', callback_data=f'setgs#button#{settings["button"]}#{grp_id}',),
            ],
            [
                InlineKeyboardButton('Iᴍᴅʙ', callback_data=f'setgs#imdb#{settings["imdb"]}#{grp_id}',),
                InlineKeyboardButton('✔ Oɴ' if settings["imdb"] else '✘ Oғғ',callback_data=f'setgs#imdb#{settings["imdb"]}#{grp_id}',),
            ],
            [
                InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ', callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}',),
                InlineKeyboardButton('✔ Oɴ' if settings["spell_check"] else '✘ Oғғ', callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}',),
            ],
            [
                InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ Msɢ', callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}',),
                InlineKeyboardButton('✔ Oɴ' if settings["welcome"] else '✘ Oғғ',callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}',),
            ],
            [
                InlineKeyboardButton('Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ', callback_data=f'setgs#auto_delete_menu#0#{grp_id}',),
                InlineKeyboardButton(get_auto_delete_label(settings), callback_data=f'setgs#auto_delete_menu#0#{grp_id}',),
            ],
            [
                InlineKeyboardButton('Aᴜᴛᴏ-Fɪʟᴛᴇʀ', callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{grp_id}',),
                InlineKeyboardButton('✔ 𝕋𝕣𝕦𝕖' if settings["auto_ffilter"] else '✘ 𝔽𝕒𝕝𝕤𝕖', callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{grp_id}',),
            ],
            [
                InlineKeyboardButton('Mᴀx Bᴜᴛᴛᴏɴs', callback_data=f'setgs#max_btn#{settings["max_btn"]}#{grp_id}',),
                InlineKeyboardButton('10' if settings["max_btn"] else f'{MAX_B_TN}', callback_data=f'setgs#max_btn#{settings["max_btn"]}#{grp_id}',),
            ],
            [
                InlineKeyboardButton('Fɪʟᴇ Lɪᴍɪᴛ', callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}'),
                InlineKeyboardButton('✔ Oɴ' if settings.get("filelock", LIMIT_MODE) else '✘ Oғғ', callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}'),
            ], 
            [
                InlineKeyboardButton('Sᴛʀᴇᴀᴍ Sʜᴏʀᴛ', callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}'),
                InlineKeyboardButton('✔ Oɴ' if settings.get("stream_mode", STREAM_MODE) else '✘ Oғғ', callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}'),
            ], 
            [
                InlineKeyboardButton('Vᴇʀɪғʏ', callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}'),
                InlineKeyboardButton('✔ Oɴ' if settings.get("is_verify", IS_VERIFY) else '✘ Oғғ', callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}'),
            ],
        ]
        btn = [[
                InlineKeyboardButton("Oᴘᴇɴ Hᴇʀᴇ ↓", callback_data=f"opnsetgrp#{grp_id}"),
                InlineKeyboardButton("Oᴘᴇɴ Iɴ PM ⇲", callback_data=f"opnsetpm#{grp_id}")
              ]]

        reply_markup = InlineKeyboardMarkup(buttons)
        if chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            await message.reply_text(
                text="<b>Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴏᴘᴇɴ sᴇᴛᴛɪɴɢs ʜᴇʀᴇ ?</b>",
                reply_markup=InlineKeyboardMarkup(btn),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
                reply_to_message_id=message.id
            )
        else:
            await message.reply_text(
                text=f"<b>Cʜᴀɴɢᴇ Yᴏᴜʀ Sᴇᴛᴛɪɴɢs Fᴏʀ {title} As Yᴏᴜʀ Wɪsʜ ⚙</b>",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
                reply_to_message_id=message.id
            )

  
@Client.on_message(filters.command('set_tutorial')) 
async def set_tutorial_1(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text(f"<b>ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...\n\nGroup Name: {title}\nGroup ID: {grp_id}\nGroup Invite Link: {invite_link}</b>")
    try:
        tutorial = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text("<b>Command Incomplete!!\n\nuse like this -</b>\n\n<code>/set_tutorial https://t.me/Looterebotts</code>")
    await save_group_settings(grp_id, 'tutorial', tutorial)
    await message.reply_text(f"<b>Successfully changed tutorial for {title}</b>\n\nLink - {tutorial}", disable_web_page_preview=True)
    await client.send_message(LOG_CHANNEL, f"Tutorial for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")

@Client.on_message(filters.command('set_tutorial_2'))
async def set_tutorial_2(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        tutorial = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text("<b>Command Incomplete!!\n\nuse like this -</b>\n\n<code>/set_tutorial https://t.me/Looterebotts</code>")
    await save_group_settings(grp_id, 'tutorial2', tutorial)
    await message.reply_text(f"<b>Successfully changed tutorial for {title}</b>\n\nLink - {tutorial}", disable_web_page_preview=True)
    await client.send_message(LOG_CHANNEL, f"Tutorial 2 for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")

@Client.on_message(filters.command('set_tutorial_3'))
async def set_tutorial_3(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        tutorial = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text("<b>Command Incomplete!!\n\nuse like this -</b>\n\n<code>/set_tutorial https://t.me/Looterebotts</code>")
    await save_group_settings(grp_id, 'tutorial3', tutorial)
    await message.reply_text(f"<b>Successfully changed tutorial for {title}</b>\n\nLink - {tutorial}", disable_web_page_preview=True)
    await client.send_message(LOG_CHANNEL, f"Tutorial 2 for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")

@Client.on_message(filters.command('set_verify'))
async def set_verify(c, m):
    chat_type = m.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await m.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = m.chat.id
    title = m.chat.title
    user = await c.get_chat_member(m.chat.id, m.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await m.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')        
    if len(m.text.split()) == 1:
        await m.reply("<b>Use this command like this - \n\n`/set_shortner ziplinker.net c992d5c6d3a74f6ceccbf9bc34aa27c8487c11d2`</b>")
        return        
    sts = await m.reply("<b>♻️ ᴄʜᴇᴄᴋɪɴɢ...</b>")
    try:
        URL = m.command[1]
        API = m.command[2]
        resp = requests.get(f'https://{URL}/api?api={API}&url=https://telegram.dog/LootereBotts').json()
        if resp['status'] == 'success':
            SHORT_LINK = resp['shortenedUrl']
        await save_group_settings(grp_id, 'verify', URL)
        await save_group_settings(grp_id, 'verify_api', API)
        await sts.edit(f"<b><u>✅ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʏᴏᴜʀ sʜᴏʀᴛɴᴇʀ ɪs ᴀᴅᴅᴇᴅ</u>\n\nᴅᴇᴍᴏ - {SHORT_LINK}\n\nsɪᴛᴇ - `{URL}`\n\nᴀᴘɪ - `{API}`</b>")
        user_id = m.from_user.id
        user_info = f"@{m.from_user.username}" if m.from_user.username else f"{m.from_user.mention}"
        link = (await c.get_chat(m.chat.id)).invite_link
        grp_link = f"[{m.chat.title}]({link})"
        log_message = f"#New_Shortner_Set_For_1st_Verify\n\nName - {user_info}\nId - `{user_id}`\n\nDomain name - {URL}\nApi - `{API}`\nGroup link - {grp_link}   `{grp_id}`"
        await c.send_message(LOG_CHANNEL, log_message, disable_web_page_preview=True)
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await save_group_settings(grp_id, 'verify', VERIFY_URL)
        await save_group_settings(grp_id, 'verify_api', VERIFY_API)
        await sts.edit(f"<b><u>❌ ᴇʀʀᴏʀ ᴏᴄᴄᴏᴜʀᴇᴅ ❌</u>\n\nᴀᴜᴛᴏ ᴀᴅᴅᴇᴅ ᴅᴇꜰᴜʟᴛ sʜᴏʀᴛɴᴇʀ\n\nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀɴɢᴇ ᴛʜᴇɴ ᴜsᴇ ᴄᴏʀʀᴇᴄᴛ ꜰᴏʀᴍᴀᴛ ᴏʀ ᴀᴅᴅ ᴠᴀʟɪᴅ sʜᴏʀᴛʟɪɴᴋ ᴅᴏᴍᴀɪɴ ɴᴀᴍᴇ & ᴀᴘɪ\n\nʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ᴄᴏɴᴛᴀᴄᴛ ᴏᴜʀ <a href=https://t.me/Looteresuport>sᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ</a> ꜰᴏʀ sᴏʟᴠᴇ ᴛʜɪs ɪssᴜᴇ...\n\nʟɪᴋᴇ -\n\n`/set_verify droplink.co 5c6377b71bb8c36629bad14b3c67d9749c4f62e6`\n\n💔 ᴇʀʀᴏʀ - <code>{e}</code></b>")

@Client.on_message(filters.command('set_verify2'))
async def set_verify2(c, m):
    chat_type = m.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await m.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = m.chat.id
    title = m.chat.title
    user = await c.get_chat_member(m.chat.id, m.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await m.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    if len(m.text.split()) == 1:
        await m.reply("<b>Use this command like this - \n\n`/set_shortner_2 tnshort.net 06b24eb6bbb025713cd522fb3f696b6d5de11354`</b>")
        return
    sts = await m.reply("<b>♻️ ᴄʜᴇᴄᴋɪɴɢ...</b>")
    try:
        URL = m.command[1]
        API = m.command[2]
        resp = requests.get(f'https://{URL}/api?api={API}&url=https://telegram.dog/LootereBotts').json()
        if resp['status'] == 'success':
            SHORT_LINK = resp['shortenedUrl']
        await save_group_settings(grp_id, 'verify_2', URL)
        await save_group_settings(grp_id, 'verify_api2', API)
        await sts.edit(f"<b><u>✅ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʏᴏᴜʀ sʜᴏʀᴛɴᴇʀ ɪs ᴀᴅᴅᴇᴅ</u>\n\nᴅᴇᴍᴏ - {SHORT_LINK}\n\nsɪᴛᴇ - `{URL}`\n\nᴀᴘɪ - `{API}`</b>")
        user_id = m.from_user.id
        user_info = f"@{m.from_user.username}" if m.from_user.username else f"{m.from_user.mention}"
        link = (await c.get_chat(m.chat.id)).invite_link
        grp_link = f"[{m.chat.title}]({link})"
        log_message = f"#New_Shortner_Set_For_2nd_Verify\n\nName - {user_info}\nId - `{user_id}`\n\nDomain name - {URL}\nApi - `{API}`\nGroup link - {grp_link}   `{grp_id}`"
        await c.send_message(LOG_CHANNEL, log_message, disable_web_page_preview=True)
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await save_group_settings(grp_id, 'verify_2', VERIFY_URL2)
        await save_group_settings(grp_id, 'verify_api2', VERIFY_API2)
        await sts.edit(f"<b><u>❌ ᴇʀʀᴏʀ ᴏᴄᴄᴏᴜʀᴇᴅ ❌</u>\n\nᴀᴜᴛᴏ ᴀᴅᴅᴇᴅ ᴅᴇꜰᴜʟᴛ sʜᴏʀᴛɴᴇʀ\n\nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀɴɢᴇ ᴛʜᴇɴ ᴜsᴇ ᴄᴏʀʀᴇᴄᴛ ꜰᴏʀᴍᴀᴛ ᴏʀ ᴀᴅᴅ ᴠᴀʟɪᴅ sʜᴏʀᴛʟɪɴᴋ ᴅᴏᴍᴀɪɴ ɴᴀᴍᴇ & ᴀᴘɪ\n\nʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ᴄᴏɴᴛᴀᴄᴛ ᴏᴜʀ <a href=https://t.me/Looteresuport>sᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ</a> ꜰᴏʀ sᴏʟᴠᴇ ᴛʜɪs ɪssᴜᴇ...\n\nʟɪᴋᴇ -\n\n`/set_verify2 shortyfi.link 465d89bf8d7b71277a822b890f7cc3e2489acf73`\n\n💔 ᴇʀʀᴏʀ - <code>{e}</code></b>")

@Client.on_message(filters.command('set_verify3'))
async def set_verify3(c, m):
    chat_type = m.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await m.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = m.chat.id
    title = m.chat.title
    user = await c.get_chat_member(m.chat.id, m.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await m.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    if len(m.text.split()) == 1:
        await m.reply("<b>Use this command like this - \n\n`/set_shortner_2 tnshort.net 06b24eb6bbb025713cd522fb3f696b6d5de11354`</b>")
        return
    sts = await m.reply("<b>♻️ ᴄʜᴇᴄᴋɪɴɢ...</b>")
    try:
        URL = m.command[1]
        API = m.command[2]
        resp = requests.get(f'https://{URL}/api?api={API}&url=https://telegram.dog/LootereBotts').json()
        if resp['status'] == 'success':
            SHORT_LINK = resp['shortenedUrl']
        await save_group_settings(grp_id, 'verify_3', URL)
        await save_group_settings(grp_id, 'verify_api3', API)
        await sts.edit(f"<b><u>✅ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʏᴏᴜʀ sʜᴏʀᴛɴᴇʀ ɪs ᴀᴅᴅᴇᴅ</u>\n\nᴅᴇᴍᴏ - {SHORT_LINK}\n\nsɪᴛᴇ - `{URL}`\n\nᴀᴘɪ - `{API}`</b>")
        user_id = m.from_user.id
        user_info = f"@{m.from_user.username}" if m.from_user.username else f"{m.from_user.mention}"
        link = (await c.get_chat(m.chat.id)).invite_link
        grp_link = f"[{m.chat.title}]({link})"
        log_message = f"#New_Shortner_Set_For_3nd_Verify\n\nName - {user_info}\nId - `{user_id}`\n\nDomain name - {URL}\nApi - `{API}`\nGroup link - {grp_link}   `{grp_id}`"
        await c.send_message(LOG_CHANNEL, log_message, disable_web_page_preview=True)
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await save_group_settings(grp_id, 'verify_3', VERIFY_URL3)
        await save_group_settings(grp_id, 'verify_api3', VERIFY_API3)
        await sts.edit(f"<b><u>❌ ᴇʀʀᴏʀ ᴏᴄᴄᴏᴜʀᴇᴅ ❌</u>\n\nᴀᴜᴛᴏ ᴀᴅᴅᴇᴅ ᴅᴇꜰᴜʟᴛ sʜᴏʀᴛɴᴇʀ\n\nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀɴɢᴇ ᴛʜᴇɴ ᴜsᴇ ᴄᴏʀʀᴇᴄᴛ ꜰᴏʀᴍᴀᴛ ᴏʀ ᴀᴅᴅ ᴠᴀʟɪᴅ sʜᴏʀᴛʟɪɴᴋ ᴅᴏᴍᴀɪɴ ɴᴀᴍᴇ & ᴀᴘɪ\n\nʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ᴄᴏɴᴛᴀᴄᴛ ᴏᴜʀ <a href=https://t.me/Looteresuport>sᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ</a> ꜰᴏʀ sᴏʟᴠᴇ ᴛʜɪs ɪssᴜᴇ...\n\nʟɪᴋᴇ -\n\n`/set_verify3 sharedisklinks.com 587f94f0e0b1813a52aed61290af6ea79d6ee464`\n\n💔 ᴇʀʀᴏʀ - <code>{e}</code></b>")

@Client.on_message(filters.command('set_stream'))
async def set_stream(c, m):
    chat_type = m.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await m.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = m.chat.id
    title = m.chat.title
    user = await c.get_chat_member(m.chat.id, m.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await m.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    if len(m.text.split()) == 1:
        await m.reply("<b>Use this command like this - \n\n`/set_stream tnshort.net 06b24eb6bbb025713cd522fb3f696b6d5de11354`</b>")
        return
    sts = await m.reply("<b>♻️ ᴄʜᴇᴄᴋɪɴɢ...</b>")
    try:
        URL = m.command[1]
        API = m.command[2]
        resp = requests.get(f'https://{URL}/api?api={API}&url=https://telegram.dog/LootereBotts').json()
        if resp['status'] == 'success':
            SHORT_LINK = resp['shortenedUrl']
        await save_group_settings(grp_id, 'streamsite', URL)
        await save_group_settings(grp_id, 'streamapi', API)
        await sts.edit(f"<b><u>✅ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʏᴏᴜʀ sʜᴏʀᴛɴᴇʀ ɪs ᴀᴅᴅᴇᴅ</u>\n\nᴅᴇᴍᴏ - {SHORT_LINK}\n\nsɪᴛᴇ - `{URL}`\n\nᴀᴘɪ - `{API}`</b>")
        user_id = m.from_user.id
        user_info = f"@{m.from_user.username}" if m.from_user.username else f"{m.from_user.mention}"
        link = (await c.get_chat(m.chat.id)).invite_link
        grp_link = f"[{m.chat.title}]({link})"
        log_message = f"#New_Stream_link_set\n\nName - {user_info}\nId - `{user_id}`\n\nDomain name - {URL}\nApi - `{API}`\nGroup link - {grp_link}   `{grp_id}`"
        await c.send_message(LOG_CHANNEL, log_message, disable_web_page_preview=True)
    except Exception as e:
        await save_group_settings(grp_id, 'streamsite', STREAM_SITE)
        await save_group_settings(grp_id, 'streamapi', STREAM_API)
        await sts.edit(f"<b><u>❌ ᴇʀʀᴏʀ ᴏᴄᴄᴏᴜʀᴇᴅ ❌</u>\n\nᴀᴜᴛᴏ ᴀᴅᴅᴇᴅ ᴅᴇꜰᴜʟᴛ sʜᴏʀᴛɴᴇʀ\n\nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀɴɢᴇ ᴛʜᴇɴ ᴜsᴇ ᴄᴏʀʀᴇᴄᴛ ꜰᴏʀᴍᴀᴛ ᴏʀ ᴀᴅᴅ ᴠᴀʟɪᴅ sʜᴏʀᴛʟɪɴᴋ ᴅᴏᴍᴀɪɴ ɴᴀᴍᴇ & ᴀᴘɪ\n\nʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ᴄᴏɴᴛᴀᴄᴛ ᴏᴜʀ <a href=https://t.me/Looteresuport>sᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ</a> ꜰᴏʀ sᴏʟᴠᴇ ᴛʜɪs ɪssᴜᴇ...\n\nʟɪᴋᴇ -\n\n`/set_stream sharedisklinks.com 587f94f0e0b1813a52aed61290af6ea79d6ee464`\n\n💔 ᴇʀʀᴏʀ - <code>{e}</code></b>")
           
@Client.on_message(filters.command('set_caption'))
async def save_caption(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        caption = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text("<code>ɢɪᴠᴇ ᴍᴇ ᴀ ᴄᴀᴘᴛɪᴏɴ ᴀʟᴏɴɢ ᴡɪᴛʜ ɪᴛ.\n\nᴇxᴀᴍᴘʟᴇ -\n\nꜰᴏʀ ꜰɪʟᴇ ɴᴀᴍᴇ ꜱᴇɴᴅ <code>{file_name}</code>\nꜰᴏʀ ꜰɪʟᴇ ꜱɪᴢᴇ ꜱᴇɴᴅ <code>{file_size}</code>\n\n<code>/set_caption {file_name}</code></code>")
    await save_group_settings(grp_id, 'caption', caption)
    await message.reply_text(f"Successfully changed caption for {title}\n\nCaption - {caption}", disable_web_page_preview=True)
    await client.send_message(LOG_CHANNEL, f"Caption for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")

@Client.on_message(filters.command('set_fsub'))
async def set_fsub(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        channel_id = int(message.text.split(" ", 1)[1])
    except IndexError:
        return await message.reply_text("<b>ᴄᴏᴍᴍᴀɴᴅ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ\n\nꜱᴇɴᴅ ᴍᴇ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴡɪᴛʜ ᴄᴏᴍᴍᴀɴᴅ, ʟɪᴋᴇ <code>/set_fsub -100******</code></b>")
    except ValueError:
        return await message.reply_text('<b>ᴍᴀᴋᴇ ꜱᴜʀᴇ ᴛʜᴇ ɪᴅ ɪꜱ ᴀɴ ɪɴᴛᴇɢᴇʀ.</b>')
    try:
        chat = await client.get_chat(channel_id)
    except Exception as e:
        return await message.reply_text(f"<b><code>{channel_id}</code> ɪꜱ ɪɴᴠᴀʟɪᴅ. ᴍᴀᴋᴇ ꜱᴜʀᴇ <a href=https://t.me/{temp.B_LINK} ʙᴏᴛ</a> ɪꜱ ᴀᴅᴍɪɴ ɪɴ ᴛʜᴀᴛ ᴄʜᴀɴɴᴇʟ\n\n<code>{e}</code></b>")
    if chat.type != enums.ChatType.CHANNEL:
        return await message.reply_text(f"🫥 <code>{channel_id}</code> ᴛʜɪꜱ ɪꜱ ɴᴏᴛ ᴄʜᴀɴɴᴇʟ, ꜱᴇɴᴅ ᴍᴇ ᴏɴʟʏ ᴄʜᴀɴɴᴇʟ ɪᴅ ɴᴏᴛ ɢʀᴏᴜᴘ ɪᴅ</b>")
    await save_group_settings(grp_id, 'fsub_id', channel_id)
    mention = message.from_user.mention
    await client.send_message(LOG_CHANNEL, f"#Fsub_Channel_set\n\nUser - {mention} set the force channel for {title}:\n\nFsub channel - {chat.title}\nId - `{channel_id}`")
    await message.reply_text(f"<b>ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇᴛ ꜰᴏʀᴄᴇ ꜱᴜʙꜱᴄʀɪʙᴇ ᴄʜᴀɴɴᴇʟ ꜰᴏʀ {title}\n\nᴄʜᴀɴɴᴇʟ ɴᴀᴍᴇ - {chat.title}\nɪᴅ - <code>{channel_id}</code></b>")

@Client.on_message(filters.command("add_fsub"))
async def add_global_fsub(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text(
            "<b>Jaan, ye command sirf bot admins ke liye hai 👑</b>"
        )
    channel_info = await _get_force_sub_channel_id(client, message)
    if channel_info is None:
        return
    channel_id, channel = channel_info
    channels = await db.get_force_sub_channels()
    if channel_id in channels:
        return await message.reply_text(
            f"<b>{channel.title} pehle se force-sub list mein hai ❤️</b>"
        )
    await db.add_force_sub_channel(channel_id)
    logger.info(
        "Force-sub channel added (channel_id=%s, actor_id=%s)",
        channel_id,
        message.from_user.id,
    )
    await message.reply_text(
        f"<b>✅ {html_escape(channel.title)} force-sub list mein add ho gaya jaan ❤️</b>"
    )


@Client.on_message(filters.command("list_fsub"))
async def list_global_fsub(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text(
            "<b>Jaan, ye command sirf bot admins ke liye hai 👑</b>"
        )
    channels = await db.get_force_sub_channels()
    if not channels:
        return await message.reply_text(
            "<b>Abhi dynamic force-sub list khaali hai jaan ❤️</b>"
        )

    channel_lines = []
    for channel_id in channels:
        try:
            channel = await client.get_chat(channel_id)
            channel_lines.append(
                f"• {html_escape(channel.title)} — <code>{channel_id}</code>"
            )
        except Exception:
            logger.exception(
                "Could not read force-sub channel details (channel_id=%s)",
                channel_id,
            )
            channel_lines.append(f"• <code>{channel_id}</code> — unavailable")
    await message.reply_text(
        "<b>Dynamic Force-Subscribe channels 👇\n\n"
        + "\n".join(channel_lines)
        + "</b>"
    )


@Client.on_message(filters.command("sponsor_button"))
async def sponsor_button_status(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    config = await db.get_setting("SPONSOR_BUTTON", default={})
    if not isinstance(config, dict) or not is_valid_sponsor_button(
        config.get("text"), config.get("url")
    ):
        return await message.reply_text(
            "Sponsor button abhi set nahi hai jaan. "
            "/set_sponsor_button Button Text | https://example.com ❤️"
        )
    state = "ON" if config.get("enabled") else "OFF"
    await message.reply_text(
        f"Sponsor button: {state}\n"
        f"Text: {config['text']}\n"
        f"URL: {config['url']}"
    )


@Client.on_message(filters.command("set_sponsor_button"))
async def set_sponsor_button(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text(
            "Jaan, sponsor button PM mein configure karo ❤️"
        )
    try:
        _, value = message.text.split(maxsplit=1)
        text, url = (part.strip() for part in value.split("|", 1))
    except ValueError:
        return await message.reply_text(
            "Format: /set_sponsor_button Button Text | https://example.com"
        )
    if not is_valid_sponsor_button(text, url):
        return await message.reply_text(
            "Jaan, button text 1–64 characters ka aur URL valid http(s) link hona chahiye 😉"
        )

    await db.set_setting(
        "SPONSOR_BUTTON",
        {"enabled": True, "text": text, "url": url},
    )
    await message.reply_text("Sponsor button update ho gaya aur ON hai jaan ❤️")


@Client.on_message(filters.command("disable_sponsor_button"))
async def disable_sponsor_button(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    config = await db.get_setting("SPONSOR_BUTTON", default={})
    if not isinstance(config, dict):
        config = {}
    config["enabled"] = False
    await db.set_setting("SPONSOR_BUTTON", config)
    await message.reply_text("Sponsor button OFF kar diya jaan ❤️")


@Client.on_message(filters.command("enable_sponsor_button"))
async def enable_sponsor_button(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    config = await db.get_setting("SPONSOR_BUTTON", default={})
    if not isinstance(config, dict) or not is_valid_sponsor_button(
        config.get("text"), config.get("url")
    ):
        return await message.reply_text(
            "Pehle /set_sponsor_button se text aur URL set karo jaan ❤️"
        )
    config["enabled"] = True
    await db.set_setting("SPONSOR_BUTTON", config)
    await message.reply_text("Sponsor button phir se ON hai jaan ❤️")


@Client.on_message(filters.command("set_welcome"))
async def set_welcome_message(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("Jaan, welcome message PM mein update karo ❤️")
    try:
        _, template = message.text.split(maxsplit=1)
    except ValueError:
        return await message.reply_text(
            "Format: /set_welcome message text\n"
            "Placeholders: {user}, {bot_username}, {bot_name}"
        )
    if not is_valid_welcome_message(template):
        return await message.reply_text(
            "Jaan, message 1–3500 characters ka hona chahiye aur placeholders "
            "{user}, {bot_username}, {bot_name} mein se hone chahiye ❤️"
        )
    await db.set_setting("WELCOME_MESSAGE", template)
    await message.reply_text("Welcome message update ho gaya jaan ❤️")


@Client.on_message(filters.command("show_welcome"))
async def show_welcome_message(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    await message.reply_text(
        await get_start_message(
            message.from_user.mention if message.from_user else "",
            temp.U_NAME,
            temp.B_NAME,
        ),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("reset_welcome"))
async def reset_welcome_message(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("Jaan, welcome message PM mein reset karo ❤️")
    await db.set_setting("WELCOME_MESSAGE", None)
    await message.reply_text("Default welcome message restore ho gaya jaan ❤️")


@Client.on_message(filters.command("set_search_strictness"))
async def set_search_strictness(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("Jaan, search strictness PM mein update karo ❤️")
    try:
        _, strictness = message.text.split(maxsplit=1)
    except ValueError:
        strictness = ""
    strictness = strictness.strip().lower()
    if strictness not in SEARCH_STRICTNESS_LEVELS:
        return await message.reply_text(
            "Format: /set_search_strictness strict|normal|relaxed"
        )
    await db.set_setting("SEARCH_STRICTNESS", strictness)
    thresholds = SEARCH_STRICTNESS_LEVELS[strictness]
    await message.reply_text(
        f"Search strictness <b>{strictness}</b> set ho gayi jaan ❤️\n"
        f"Suggestion threshold: {thresholds['suggestion_score']}\n"
        f"Auto-correct threshold: {thresholds['auto_correct_score']}",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("search_strictness"))
async def show_search_strictness(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    strictness = await get_search_strictness()
    thresholds = SEARCH_STRICTNESS_LEVELS[strictness]
    await message.reply_text(
        f"Current search strictness: <b>{strictness}</b>\n"
        f"Suggestion threshold: {thresholds['suggestion_score']}\n"
        f"Auto-correct threshold: {thresholds['auto_correct_score']}",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("set_premium_plan"))
async def set_premium_plan(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("Jaan, premium plans PM mein manage karo ❤️")
    try:
        _, value = message.text.split(maxsplit=1)
        parts = [part.strip() for part in value.split("|", 4)]
    except ValueError:
        parts = []
    if len(parts) != 5:
        return await message.reply_text(
            "Format: /set_premium_plan id | name | price | duration | benefits"
        )
    plan = dict(zip(("id", "name", "price", "duration", "benefits"), parts))
    if not is_valid_premium_plan(plan):
        return await message.reply_text(
            "Jaan, ID 1–32 characters, name 48, price 24, duration 32, "
            "aur benefits 200 characters tak rakho ❤️"
        )

    plans = await get_premium_plans()
    existing_index = next(
        (index for index, current in enumerate(plans) if current["id"] == plan["id"]),
        None,
    )
    if existing_index is None:
        if len(plans) >= 10:
            return await message.reply_text(
                "Jaan, maximum 10 premium plans hi rakh sakte ho ❤️"
            )
        plans.append(plan)
        action = "add"
    else:
        plans[existing_index] = plan
        action = "update"
    await db.set_setting("PREMIUM_PLANS", plans)
    await message.reply_text(
        f"✅ Plan {plan['id']} {action} ho gaya jaan ❤️\n\n"
        + format_premium_plans(plans),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remove_premium_plan"))
async def remove_premium_plan(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("Jaan, premium plans PM mein manage karo ❤️")
    try:
        plan_id = message.text.split(maxsplit=1)[1].strip()
    except IndexError:
        return await message.reply_text("Format: /remove_premium_plan <id>")

    plans = await get_premium_plans()
    remaining = [plan for plan in plans if plan["id"] != plan_id]
    if len(remaining) == len(plans):
        return await message.reply_text("Ye plan ID nahi mili jaan. /list_premium_plans dekho ❤️")
    if not remaining:
        return await message.reply_text(
            "Jaan, kam se kam ek plan available rehna chahiye ❤️"
        )
    await db.set_setting("PREMIUM_PLANS", remaining)
    await message.reply_text(
        f"✅ Plan {html_escape(plan_id)} remove ho gaya jaan ❤️",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("list_premium_plans"))
async def list_premium_plans(client, message):
    if not _is_bot_admin(message.from_user.id if message.from_user else None):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    plans = await get_premium_plans()
    plan_ids = "\n\n".join(
        f"<code>{html_escape(plan['id'])}</code> — "
        f"{html_escape(plan['name'])} — {html_escape(plan['price'])} / "
        f"{html_escape(plan['duration'])}"
        for plan in plans
    )
    await message.reply_text(
        "<b>Premium plans 👇\n\n"
        + (plan_ids or "Koi plan nahi hai jaan.")
        + "\n\nSet/update: <code>/set_premium_plan id | name | price | duration | benefits</code>\n"
        + "Remove: <code>/remove_premium_plan id</code></b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command('remove_fsub'))
async def remove_fsub(client, message):
    if message.chat.type == enums.ChatType.PRIVATE:
        if not _is_bot_admin(message.from_user.id if message.from_user else None):
            return await message.reply_text(
                "<b>Jaan, ye command sirf bot admins ke liye hai 👑</b>"
            )
        try:
            channel_id = int(message.text.split(maxsplit=1)[1])
        except (IndexError, ValueError):
            return await message.reply_text(
                "<b>Jaan, channel ID ke saath command bhejo 😉\n"
                "Example: <code>/remove_fsub -1001234567890</code></b>"
            )
        removed = await db.remove_force_sub_channel(channel_id)
        if not removed:
            return await message.reply_text(
                "<b>Ye channel dynamic force-sub list mein nahi tha jaan ❤️</b>"
            )
        logger.info(
            "Force-sub channel removed (channel_id=%s, actor_id=%s)",
            channel_id,
            message.from_user.id,
        )
        return await message.reply_text(
            f"<b>✅ <code>{channel_id}</code> force-sub list se remove ho gaya jaan ❤️</b>"
        )

    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")       
    grp_id = message.chat.id
    title = message.chat.title
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    settings = await get_settings(grp_id)
    if settings["fsub_id"] == AUTH_CHANNEL:
        await message.reply_text("<b>ᴄᴜʀʀᴇɴᴛʟʏ ɴᴏ ᴀɴʏ ғᴏʀᴄᴇ ꜱᴜʙ ᴄʜᴀɴɴᴇʟ.... <code>[ᴅᴇғᴀᴜʟᴛ ᴀᴄᴛɪᴠᴀᴛᴇ]</code></b>")
    else:
        await save_group_settings(grp_id, 'fsub_id', AUTH_CHANNEL)
        mention = message.from_user.mention
        await client.send_message(LOG_CHANNEL, f"#Remove_Fsub_Channel\n\nUser - {mention} he remove fsub channel from {title}")
        await message.reply_text(f"<b>✅ ꜱᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ʀᴇᴍᴏᴠᴇᴅ ғᴏʀᴄᴇ ꜱᴜʙ ᴄʜᴀɴɴᴇʟ.</b>")         

@Client.on_message(filters.command('set_log'))
async def set_log(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    if len(message.text.split()) == 1:
        await message.reply("<b>Use this command like this - \n\n`/set_log -100******`</b>")
        return
    sts = await message.reply("<b>♻️ ᴄʜᴇᴄᴋɪɴɢ...</b>")
    await asyncio.sleep(1.2)
    await sts.delete()
    try:
        log = int(message.text.split(" ", 1)[1])
    except IndexError:
        return await message.reply_text("<b><u>ɪɴᴠᴀɪʟᴅ ꜰᴏʀᴍᴀᴛ!!</u>\n\nᴜsᴇ ʟɪᴋᴇ ᴛʜɪs - `/set_log -100xxxxxxxx`</b>")
    except ValueError:
        return await message.reply_text('<b>ᴍᴀᴋᴇ sᴜʀᴇ ɪᴅ ɪs ɪɴᴛᴇɢᴇʀ...</b>')
    try:
        t = await client.send_message(chat_id=log, text="<b>ʜᴇʏ ᴡʜᴀᴛ's ᴜᴘ!!</b>")
        await asyncio.sleep(3)
        await t.delete()
    except Exception as e:
        return await message.reply_text(f'<b><u>😐 ᴍᴀᴋᴇ sᴜʀᴇ ᴛʜɪs ʙᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜᴀᴛ ᴄʜᴀɴɴᴇʟ...</u>\n\n💔 ᴇʀʀᴏʀ - <code>{e}</code></b>')
    await save_group_settings(grp_id, 'log', log)
    await message.reply_text(f"<b>✅ sᴜᴄᴄᴇssꜰᴜʟʟʏ sᴇᴛ ʏᴏᴜʀ ʟᴏɢ ᴄʜᴀɴɴᴇʟ ꜰᴏʀ {title}\n\nɪᴅ - `{log}`</b>", disable_web_page_preview=True)
    user_id = message.from_user.id
    user_info = f"@{m.from_user.username}" if m.from_user.username else f"{m.from_user.mention}"
    link = (await client.get_chat(message.chat.id)).invite_link
    grp_link = f"[{message.chat.title}]({link})"
    log_message = f"#New_Log_Channel_Set\n\nName - {user_info}\nId - `{user_id}`\n\nLog channel id - `{log}`\nGroup link - {grp_link}   `{grp_id}`"
    await client.send_message(LOG_CHANNEL, log_message, disable_web_page_preview=True)  

@Client.on_message(filters.command('details'))
async def all_settings(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    settings = await get_settings(grp_id)
    text = f"""<b><u>⚙️ ʏᴏᴜʀ sᴇᴛᴛɪɴɢs ꜰᴏʀ -</u> {title}

<u>✅️ 1sᴛ ᴠᴇʀɪꜰʏ sʜᴏʀᴛɴᴇʀ ɴᴀᴍᴇ/ᴀᴘɪ</u>
ɴᴀᴍᴇ - `{settings.get("verify", VERIFY_URL)}`
ᴀᴘɪ - `{settings.get("verify_api", VERIFY_API)}`

<u>✅️ 2ɴᴅ ᴠᴇʀɪꜰʏ sʜᴏʀᴛɴᴇʀ ɴᴀᴍᴇ/ᴀᴘɪ</u>
ɴᴀᴍᴇ - `{settings.get("verify_2", VERIFY_URL2)}`
ᴀᴘɪ - `{settings.get("verify_api2", VERIFY_API2)}`

u>✅️ ᴛʜɪʀᴅ ᴠᴇʀɪꜰʏ sʜᴏʀᴛɴᴇʀ ɴᴀᴍᴇ/ᴀᴘɪ</u>
ɴᴀᴍᴇ - `{settings.get("verify_3", VERIFY_URL3)}`
ᴀᴘɪ - `{settings.get("verify_api3", VERIFY_API3)}`

🧭 2ɴᴅ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴛɪᴍᴇ ɢᴀᴘ - `{settings.get("verify_time", TWO_VERIFY_GAP)}`

🧭 ᴛʜɪʀᴅ ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ ᴛɪᴍᴇ ɢᴀᴘ - `{settings.get("verify_time2", THIRD_VERIFY_GAP)}`

📝 ʟᴏɢ ᴄʜᴀɴɴᴇʟ ɪᴅ - `{settings.get('log', LOG_CHANNEL)}`

🌀 ғᴏʀᴄᴇ ᴄʜᴀɴɴᴇʟ - `{settings.get('fsub_id', AUTH_CHANNEL)}`

1️⃣ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ 1 - {settings.get('tutorial', TUTORIAL)}

2️⃣ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ 2 - {settings.get('tutorial2', TUTORIAL2)}

3️⃣ ᴛᴜᴛᴏʀɪᴀʟ ʟɪɴᴋ 3 - {settings.get('tutorial3', TUTORIAL3)}

📂 ꜰɪʟᴇ ᴄᴀᴘᴛɪᴏɴ - `{settings.get('caption', CUSTOM_FILE_CAPTION)}`

📁 ᴅᴀɪʟʏ ғɪʟᴇ ʟɪᴍɪᴛ - `{settings.get('file_limit', FILE_LIMITE)}`

📀 sᴇᴅɴ ᴀʟʟ ʙᴜᴛᴛᴏɴ ʟɪᴍɪᴛ - `{settings.get('all_limit', SEND_ALL_LIMITE)}`

🎯 ɪᴍᴅʙ ᴛᴇᴍᴘʟᴀᴛᴇ - `{settings.get('template', IMDB_TEMPLATE)}`"""

    
    btn = [[
        InlineKeyboardButton("ʀᴇꜱᴇᴛ ᴅᴀᴛᴀ", callback_data="reset_grp_data")
    ],[
        InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_data")
    ]]
    reply_markup=InlineKeyboardMarkup(btn)
    dlt=await message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    await asyncio.sleep(300)
    await dlt.delete()

@Client.on_message(filters.command('verify_gap'))
async def verify_gap(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")       
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        time = int(message.text.split(" ", 1)[1])
    except:
        return await message.reply_text("<b>ᴄᴏᴍᴍᴀɴᴅ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ\n\nᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ʟɪᴋᴇ ᴛʜɪꜱ - <code>/verify_gap 600</code> [ ᴛɪᴍᴇ ᴍᴜꜱᴛ ʙᴇ ɪɴ ꜱᴇᴄᴏɴᴅꜱ ]</b>")   
    await save_group_settings(grp_id, 'verify_time', time)
    await message.reply_text(f"<b>✅️ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇᴛ 2ɴᴅ ᴠᴇʀɪꜰʏ ᴛɪᴍᴇ ꜰᴏʀ {title}\n\nᴛɪᴍᴇ - <code>{time}</code></b>")
    await client.send_message(LOG_CHANNEL, f"2nd verify time for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")

@Client.on_message(filters.command('verify_gap2'))
async def verify_gap2(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")       
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        time = int(message.text.split(" ", 1)[1])
    except:
        return await message.reply_text("<b>ᴄᴏᴍᴍᴀɴᴅ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ\n\nᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ʟɪᴋᴇ ᴛʜɪꜱ - <code>/verify_gap2 600</code> [ ᴛɪᴍᴇ ᴍᴜꜱᴛ ʙᴇ ɪɴ ꜱᴇᴄᴏɴᴅꜱ ]</b>")   
    await save_group_settings(grp_id, 'verify_time2', time)
    await message.reply_text(f"<b>✅️ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇᴛ ᴛʜɪʀᴅ ᴠᴇʀɪꜰʏ ᴛɪᴍᴇ ꜰᴏʀ {title}\n\nᴛɪᴍᴇ - <code>{time}</code></b>")
    await client.send_message(LOG_CHANNEL, f"third verify time for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")


@Client.on_message(filters.command('set_file_limit'))
async def set_file_limit(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")       
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        limit = int(message.text.split(" ", 1)[1])
    except:
        return await message.reply_text("<b>ᴄᴏᴍᴍᴀɴᴅ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ\n\nᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ʟɪᴋᴇ ᴛʜɪꜱ - <code>/set_file_limit 15</code></b>")   
    if limit < 0:
        return await message.reply_text("<b>ғɪʟᴇ ʟɪᴍɪᴛ ᴄᴀɴɴᴏᴛ ʙᴇ ɴᴇɢᴀᴛɪᴠᴇ.</b>")
    await save_group_settings(grp_id, 'file_limit', limit)
    await message.reply_text(f"<b>✅️ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇᴛ ғɪʟᴇ ʟɪᴍɪᴛ ꜰᴏʀ {title}\n\nғɪʟᴇ ʟɪᴍɪᴛ - <u><code>{limit}</code></u></b>")
    await client.send_message(LOG_CHANNEL, f"file limit seted <b>`{limit}`</b> for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")

@Client.on_message(filters.command('set_send_limit'))
async def set_send_limit(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")       
    grp_id = message.chat.id
    title = message.chat.title
    invite_link = await client.export_chat_invite_link(grp_id)
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        limit = int(message.text.split(" ", 1)[1])
    except:
        return await message.reply_text("<b>ᴄᴏᴍᴍᴀɴᴅ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ\n\nᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ʟɪᴋᴇ ᴛʜɪꜱ - <code>/set_allfiles_limit 3</code></b>")   
    if limit < 0:
        return await message.reply_text("<b>sᴇɴᴅ ᴀʟʟ ʟɪᴍɪᴛ ᴄᴀɴɴᴏᴛ ʙᴇ ɴᴇɢᴀᴛɪᴠᴇ.</b>")
    await save_group_settings(grp_id, 'all_limit', limit)
    await message.reply_text(f"<b>✅️ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ꜱᴇᴛ sᴇɴᴅ ʙᴜᴛᴛᴏɴ ʟɪᴍɪᴛ ꜰᴏʀ {title}\n\nsᴇɴᴅ ʙᴜᴛᴛᴏɴ ʟɪᴍɪᴛ - <u><code>{limit}</code></u></b>")
    await client.send_message(LOG_CHANNEL, f"send button limit seted <b>`{limit}`</b> for {title} (Group ID: {grp_id}, Invite Link: {invite_link}) has been updated by {message.from_user.username}")

@Client.on_message(filters.command('set_template'))
async def save_template(client, message):
    chat_type = message.chat.type
    if chat_type not in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return await message.reply_text("<b>ᴜꜱᴇ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪɴ ɢʀᴏᴜᴘ...</b>")
    grp_id = message.chat.id
    title = message.chat.title
    user = await client.get_chat_member(message.chat.id, message.from_user.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if not owner:
        return await message.reply_text('<b>ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪꜱ ɢʀᴏᴜᴘ</b>')
    try:
        template = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text("Command Incomplete!")    
    await save_group_settings(grp_id, 'template', template)
    await message.reply_text(f"Successfully changed template for {title} to\n\n{template}", disable_web_page_preview=True)
    
@Client.on_message(filters.command('del_template'))
async def delete_template(client, message):
    sts = await message.reply("Dᴇʟᴇᴛɪɴɢ ᴛᴇᴍᴘʟᴀᴛᴇ...")
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply(f"Yᴏᴜ ᴀʀᴇ ᴀɴᴏɴʏᴍᴏᴜs ᴀᴅᴍɪɴ. Usᴇ /connect {message.chat.id} ɪɴ PM")
    chat_type = message.chat.type

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if grpid is not None:
            grp_id = grpid
            try:
                chat = await client.get_chat(grpid)
                title = chat.title
            except:
                await message.reply_text("Mᴀᴋᴇ sᴜʀᴇ I'ᴍ ᴘʀᴇsᴇɴᴛ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ!!", quote=True)
                return
        else:
            await message.reply_text("I'ᴍ ɴᴏᴛ ᴄᴏɴɴᴇᴄᴛᴇᴅ ᴛᴏ ᴀɴʏ ɢʀᴏᴜᴘs!", quote=True)
            return

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
        title = message.chat.title

    else:
        return

    st = await client.get_chat_member(grp_id, userid)
    if (
            st.status != enums.ChatMemberStatus.ADMINISTRATOR
            and st.status != enums.ChatMemberStatus.OWNER
            and str(userid) not in ADMINS
    ):
        return

    # Reset the template to the default or remove it
    await save_group_settings(grp_id, 'template', IMDB_TEMPLATE)
    await sts.edit(f"Sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ᴛᴇᴍᴘʟᴀᴛᴇ ғᴏʀ {title}.")

@Client.on_message(filters.command("send") & filters.user(ADMINS))
async def send_msg(bot, message):
    if message.reply_to_message:
        target_id = message.text.split(" ", 1)[1]
        out = "Usᴇʀs Sᴀᴠᴇᴅ Iɴ DB Aʀᴇ:\n\n"
        success = False
        try:
            user = await bot.get_users(target_id)
            users = await db.get_all_users()
            async for usr in users:
                out += f"{usr['id']}"
                out += '\n'
            if str(user.id) in str(out):
                await message.reply_to_message.copy(int(user.id))
                success = True
            else:
                success = False
            if success:
                await message.reply_text(f"<b>Yᴏᴜʀ ᴍᴇssᴀɢᴇ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssғᴜʟʟʏ sᴇɴᴅ ᴛᴏ {user.mention}.</b>")
            else:
                await message.reply_text("<b>Tʜɪs ᴜsᴇʀ ᴅɪᴅɴ'ᴛ sᴛᴀʀᴛᴇᴅ ᴛʜɪs ʙᴏᴛ ʏᴇᴛ!</b>")
        except Exception as e:
            await message.reply_text(f"<b>Eʀʀᴏʀ: {e}</b>")
    else:
        await message.reply_text("<b>Usᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴀs ᴀ ʀᴇᴘʟʏ ᴛᴏ ᴀɴʏ ᴍᴇssᴀɢᴇ ᴜsɪɴɢ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴄʜᴀᴛ ɪᴅ. Fᴏʀ ᴇɢ: /send ᴜsᴇʀɪᴅ</b>")

@Client.on_message(filters.command("deletefiles") & filters.user(ADMINS))
async def deletemultiplefiles(bot, message):
    chat_type = message.chat.type
    if chat_type != enums.ChatType.PRIVATE:
        return await message.reply_text(f"<b>Hᴇʏ {message.from_user.mention}, Tʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏɴ'ᴛ ᴡᴏʀᴋ ɪɴ ɢʀᴏᴜᴘs. Iᴛ ᴏɴʟʏ ᴡᴏʀᴋs ᴏɴ ᴍʏ PM!</b>")
    else:
        pass
    try:
        keyword = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text(f"<b>Hᴇʏ {message.from_user.mention}, Gɪᴠᴇ ᴍᴇ ᴀ ᴋᴇʏᴡᴏʀᴅ ᴀʟᴏɴɢ ᴡɪᴛʜ ᴛʜᴇ ᴄᴏᴍᴍᴀɴᴅ ᴛᴏ ᴅᴇʟᴇᴛᴇ ғɪʟᴇs.</b>")
    btn = [[
       InlineKeyboardButton("Yᴇs, Cᴏɴᴛɪɴᴜᴇ !", callback_data=f"killfilesdq#{keyword}")
       ],[
       InlineKeyboardButton("Nᴏ, Aʙᴏʀᴛ ᴏᴘᴇʀᴀᴛɪᴏɴ !", callback_data="close_data")
    ]]
    await message.reply_text(
        text="<b>Aʀᴇ ʏᴏᴜ sᴜʀᴇ? Dᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ?\n\nNᴏᴛᴇ:- Tʜɪs ᴄᴏᴜʟᴅ ʙᴇ ᴀ ᴅᴇsᴛʀᴜᴄᴛɪᴠᴇ ᴀᴄᴛɪᴏɴ!</b>",
        reply_markup=InlineKeyboardMarkup(btn),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def stop_button(bot, message):
    msg = await bot.send_message(text="<b><i>ʙᴏᴛ ɪꜱ ʀᴇꜱᴛᴀʀᴛɪɴɢ</i></b>", chat_id=message.chat.id)       
    await asyncio.sleep(3)
    await msg.edit("<b><i><u>ʙᴏᴛ ɪꜱ ʀᴇꜱᴛᴀʀᴛᴇᴅ</u> ✅</i></b>")
    os.execl(sys.executable, sys.executable, *sys.argv)

@Client.on_message(filters.command("set_value") & filters.user(ADMINS))
async def set_mode(client, message):
    try:
        args = message.text.split()   
        if len(args) == 3:
            mode_name = args[1]
            value = args[2].lower() == 'true'  # Convert string to boolean     
            valid_modes = ["PM_FILTER", "IS_VERIFY", "LIMIT_MODE", "AUTO_FILE_DELETE", "RESOLUTION_LOCK"]
            if mode_name in valid_modes:
                await db.set_setting(mode_name, value)
                await message.reply(f"{mode_name} has been set to {value}.")
            else:
                await message.reply("Invalid mode name. Please use one of the following:\n\nPM_FILTER\n\nIS_VERIFY\nLIMIT_MODE\nAUTO_FILE_DELETE\nRESOLUTION_LOCK")
        else:
            await message.reply("Please specify the mode name and 'True' or 'False'. Example: /set_value RESOLUTION_LOCK False")
    except Exception as e:
        await message.reply(f"An error occurred: {e}")


def _build_smart_style_dashboard_text(config):
    movie_id = config["movie_style"]
    series_id = config["series_style"]
    preview_on = config["preview_enabled"]
    return (
        "<b>🎨 Smart Search Result Style Settings</b>\n\n"
        f"🎬 <b>Movie Text Style:</b> <code>{movie_id} — {STYLE_NAMES[movie_id]}</code>\n"
        f"📺 <b>Series Text Style:</b> <code>{series_id} — {STYLE_NAMES[series_id]}</code>\n"
        f"👁 <b>Preview Before Apply:</b> <code>{'ON' if preview_on else 'OFF'}</code>\n\n"
        "<i>Note: Delivery mode (Link / Button) is a separate setting in /settings.</i>"
    )


def _build_smart_style_dashboard_keyboard(config):
    movie_id = config["movie_style"]
    series_id = config["series_style"]
    preview_on = config["preview_enabled"]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🎬 Movie: {movie_id}. {STYLE_NAMES[movie_id]}",
                callback_data="smartstyle#pick#movie",
            )
        ],
        [
            InlineKeyboardButton(
                f"📺 Series: {series_id}. {STYLE_NAMES[series_id]}",
                callback_data="smartstyle#pick#series",
            )
        ],
        [
            InlineKeyboardButton(
                f"👁 Preview Before Apply: {'✔ ON' if preview_on else '✘ OFF'}",
                callback_data="smartstyle#toggle_preview",
            )
        ],
        [InlineKeyboardButton("🚫 Close", callback_data="close_data")],
    ])


def _build_style_picker_keyboard(category, active_style_id):
    rows = []
    pair = []
    for style_id, style_name in STYLE_NAMES.items():
        marker = "✓ " if style_id == active_style_id else ""
        pair.append(
            InlineKeyboardButton(
                f"{marker}{style_id}. {style_name}",
                callback_data=f"smartstyle#select#{category}#{style_id}",
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="smartstyle#menu")])
    return InlineKeyboardMarkup(rows)


@Client.on_message(filters.command(["search_style", "result_style"]))
async def smart_search_style_menu(client, message):
    actor_id = message.from_user.id if message.from_user else None
    if not _is_bot_admin(actor_id):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    config = await get_smart_style_config(db_instance=db)
    await message.reply_text(
        _build_smart_style_dashboard_text(config),
        reply_markup=_build_smart_style_dashboard_keyboard(config),
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command(["movie_style", "set_movie_style"]))
async def set_movie_style_command(client, message):
    actor_id = message.from_user.id if message.from_user else None
    if not _is_bot_admin(actor_id):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        styles_list = "\n".join(f"<code>{sid}</code> — {sname}" for sid, sname in STYLE_NAMES.items())
        return await message.reply_text(
            f"<b>Usage:</b> <code>/movie_style &lt;1-10&gt;</code>\n\n{styles_list}",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        outcome = await select_smart_text_style(actor_id, "movie", parts[1], db_instance=db)
    except ValueError as err:
        return await message.reply_text(str(err))

    if outcome["status"] == "preview_pending":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Apply",
                    callback_data=f"smartstyle#apply#movie#{outcome['candidate_style_id']}",
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="smartstyle#cancel#movie",
                ),
            ]
        ])
        return await message.reply_text(
            f"<b>👁 Preview — Movie Style {outcome['candidate_style_id']} ({outcome['candidate_style_name']})</b>\n"
            f"<i>Current active style: {outcome['active_style_id']} ({outcome['active_style_name']})</i>\n\n"
            f"{outcome['preview_html']}",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )

    await message.reply_text(
        f"✅ Movie text style updated to <b>{outcome['active_style_id']} — {outcome['active_style_name']}</b>\n\n"
        f"{outcome['preview_html']}",
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command(["series_style", "set_series_style"]))
async def set_series_style_command(client, message):
    actor_id = message.from_user.id if message.from_user else None
    if not _is_bot_admin(actor_id):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        styles_list = "\n".join(f"<code>{sid}</code> — {sname}" for sid, sname in STYLE_NAMES.items())
        return await message.reply_text(
            f"<b>Usage:</b> <code>/series_style &lt;1-10&gt;</code>\n\n{styles_list}",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        outcome = await select_smart_text_style(actor_id, "series", parts[1], db_instance=db)
    except ValueError as err:
        return await message.reply_text(str(err))

    if outcome["status"] == "preview_pending":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Apply",
                    callback_data=f"smartstyle#apply#series#{outcome['candidate_style_id']}",
                ),
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="smartstyle#cancel#series",
                ),
            ]
        ])
        return await message.reply_text(
            f"<b>👁 Preview — Series Style {outcome['candidate_style_id']} ({outcome['candidate_style_name']})</b>\n"
            f"<i>Current active style: {outcome['active_style_id']} ({outcome['active_style_name']})</i>\n\n"
            f"{outcome['preview_html']}",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )

    await message.reply_text(
        f"✅ Series text style updated to <b>{outcome['active_style_id']} — {outcome['active_style_name']}</b>\n\n"
        f"{outcome['preview_html']}",
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command("search_style_preview"))
async def toggle_search_style_preview_command(client, message):
    actor_id = message.from_user.id if message.from_user else None
    if not _is_bot_admin(actor_id):
        return await message.reply_text("Jaan, ye command sirf bot admins ke liye hai 👑")
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip().lower() not in ("on", "off", "true", "false"):
        return await message.reply_text("Format: <code>/search_style_preview on|off</code>", parse_mode=enums.ParseMode.HTML)
    enabled = parts[1].strip().lower() in ("on", "true")
    saved = await set_style_preview_enabled(enabled, db_instance=db)
    await message.reply_text(
        f"✅ Preview Before Apply set to <b>{'ON' if saved['preview_enabled'] else 'OFF'}</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^smartstyle#"))
async def smart_style_callback_handler(client, query):
    actor_id = query.from_user.id if query.from_user else None
    if not _is_bot_admin(actor_id):
        return await query.answer("Sirf bot admins ke liye hai 👑", show_alert=True)

    parts = query.data.split("#")
    action = parts[1] if len(parts) > 1 else "menu"

    if action == "menu":
        config = await get_smart_style_config(db_instance=db)
        await query.message.edit_text(
            _build_smart_style_dashboard_text(config),
            reply_markup=_build_smart_style_dashboard_keyboard(config),
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return await query.answer()

    if action == "toggle_preview":
        config = await get_smart_style_config(db_instance=db)
        updated = await set_style_preview_enabled(not config["preview_enabled"], db_instance=db)
        await query.message.edit_text(
            _build_smart_style_dashboard_text(updated),
            reply_markup=_build_smart_style_dashboard_keyboard(updated),
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return await query.answer(
            f"Preview Before Apply: {'ON' if updated['preview_enabled'] else 'OFF'}"
        )

    if action == "pick" and len(parts) >= 3:
        category = parts[2].lower()
        config = await get_smart_style_config(db_instance=db)
        active_id = config["series_style"] if category == "series" else config["movie_style"]
        label = "Series" if category == "series" else "Movie"
        await query.message.edit_text(
            f"<b>🎨 Select {label} Text Style (1–10)</b>\n"
            f"Current: <code>{active_id} — {STYLE_NAMES[active_id]}</code>",
            reply_markup=_build_style_picker_keyboard(category, active_id),
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return await query.answer()

    if action == "select" and len(parts) >= 4:
        category = parts[2].lower()
        style_id = int(parts[3])
        outcome = await select_smart_text_style(actor_id, category, style_id, db_instance=db)
        label = "Series" if category == "series" else "Movie"
        if outcome["status"] == "preview_pending":
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Apply",
                        callback_data=f"smartstyle#apply#{category}#{outcome['candidate_style_id']}",
                    ),
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data=f"smartstyle#cancel#{category}",
                    ),
                ]
            ])
            await query.message.edit_text(
                f"<b>👁 Preview — {label} Style {outcome['candidate_style_id']} ({outcome['candidate_style_name']})</b>\n"
                f"<i>Current active style: {outcome['active_style_id']} ({outcome['active_style_name']})</i>\n\n"
                f"{outcome['preview_html']}",
                reply_markup=kb,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return await query.answer("Preview ready! Click Apply to save or Cancel to keep old style.")

        config = await get_smart_style_config(db_instance=db)
        await query.message.edit_text(
            _build_smart_style_dashboard_text(config),
            reply_markup=_build_smart_style_dashboard_keyboard(config),
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return await query.answer(f"{label} style updated to {outcome['active_style_name']}!")

    if action == "apply" and len(parts) >= 4:
        category = parts[2].lower()
        style_id = int(parts[3])
        applied = await confirm_pending_style_preview(
            actor_id, db_instance=db, category=category, style_id=style_id
        )
        config = applied["config"]
        await query.message.edit_text(
            _build_smart_style_dashboard_text(config),
            reply_markup=_build_smart_style_dashboard_keyboard(config),
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return await query.answer("New style applied!")

    if action == "cancel":
        cancelled = await cancel_pending_style_preview(actor_id, db_instance=db)
        config = cancelled["config"]
        await query.message.edit_text(
            _build_smart_style_dashboard_text(config),
            reply_markup=_build_smart_style_dashboard_keyboard(config),
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return await query.answer("Preview cancelled. Previous style kept unchanged.")


def _build_duplicate_cleaner_keyboard(session_id: str, mode: str, total_duplicates: int) -> InlineKeyboardMarkup:
    mode_text = f"Mode: {mode.title()}"
    if total_duplicates > 0:
        buttons = [
            [InlineKeyboardButton("Clean Duplicates", callback_data=f"dupclean#confirm#{session_id}")],
            [
                InlineKeyboardButton(mode_text, callback_data=f"dupclean#toggle#{session_id}"),
                InlineKeyboardButton("Cancel", callback_data=f"dupclean#cancel#{session_id}"),
            ],
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton(mode_text, callback_data="dupclean#toggle#none"),
                InlineKeyboardButton("Close", callback_data="dupclean#close#none"),
            ]
        ]
    return InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command(["dupscan", "duplicates", "dupclean"]) & filters.private)
async def dupscan_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    query = None
    if len(message.command) > 1:
        query = message.text.split(None, 1)[1].strip()

    status_msg = await message.reply_text("<b>🔍 Scanning database for duplicate files... Please wait.</b>")
    mode = await get_duplicate_mode(db_instance=db)
    preview = await scan_duplicates_preview(db_instance=db, query=query)
    text = format_duplicate_preview_text(preview, mode)
    kb = _build_duplicate_cleaner_keyboard(preview["session_id"], mode, preview["total_duplicates"])
    await status_msg.edit_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^dupclean#"))
async def duplicate_cleaner_callback(client: Client, query: CallbackQuery):
    actor_id = query.from_user.id
    if not _is_bot_admin(actor_id):
        return await query.answer("This setting can only be modified by Bot Admins.", show_alert=True)

    data = query.data or ""
    parts = data.split("#")
    action = parts[1] if len(parts) > 1 else ""
    session_id = parts[2] if len(parts) > 2 else ""

    if action == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return await query.answer("Closed.")

    if action == "cancel":
        cancel_duplicate_cleanup(session_id)
        await query.message.edit_text(
            "<b>❌ Duplicate cleanup cancelled.</b>\n<i>No files were deleted from the database.</i>",
            parse_mode=enums.ParseMode.HTML,
        )
        return await query.answer("Duplicate cleanup cancelled.")

    if action == "confirm":
        await query.answer("Cleaning duplicates... please wait.", show_alert=False)
        res = await execute_duplicate_cleanup(session_id, admin_id=actor_id, db_instance=db)
        if res.get("status") == "error":
            return await query.message.edit_text(
                f"<b>⚠️ Duplicate Cleanup Error:</b>\n{res.get('message', 'Unknown error')}",
                parse_mode=enums.ParseMode.HTML,
            )
        deleted = res.get("deleted_count", 0)
        reclaimed_gb = res.get("reclaimed_gb", "0.00GB")
        await query.message.edit_text(
            f"<b>✅ Duplicate Cleanup Completed!</b>\n\n"
            f"• <b>Files Deleted:</b> <code>{deleted}</code> duplicate records\n"
            f"• <b>Space Reclaimed:</b> <code>{reclaimed_gb}</code>\n\n"
            f"<i>All canonical winner files remain safe and indexed in the database.</i>",
            parse_mode=enums.ParseMode.HTML,
        )
        return

    if action == "toggle":
        curr_mode = await get_duplicate_mode(db_instance=db)
        next_mode = {
            "preview": "auto_exact",
            "auto_exact": "off",
            "off": "preview",
        }.get(curr_mode, "preview")
        await set_duplicate_mode(next_mode, db_instance=db)

        preview = await scan_duplicates_preview(db_instance=db)
        text = format_duplicate_preview_text(preview, next_mode)
        kb = _build_duplicate_cleaner_keyboard(preview["session_id"], next_mode, preview["total_duplicates"])
        await query.message.edit_text(text, reply_markup=kb, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        return await query.answer(f"Duplicate mode set to: {next_mode.title()}")


# =========================================================================
# Feature 3: Multi-MongoDB Storage Manager Admin Controls & Interactive UI
# =========================================================================
from Lootere.utils.multidb_manager import (
    multi_db_manager,
    mask_mongo_uri,
    format_multidb_dashboard_text,
    build_multidb_main_keyboard,
    build_multidb_switch_target_keyboard,
    build_multidb_toggle_keyboard,
)


@Client.on_message(filters.command(["multidb", "dbstatus"]))
async def multidb_status_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    report = await multi_db_manager.get_full_status_report()
    text = format_multidb_dashboard_text(report)
    keyboard = build_multidb_main_keyboard()
    await message.reply_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)


@Client.on_message(filters.command(["add_db", "adddb"]))
async def add_database_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    args = message.text.split()[1:]
    if not args:
        return await message.reply_text(
            "<b>Usage:</b> <code>/add_db &lt;mongo_uri&gt; [name] [priority]</code>\n\n"
            "<i>Example:</i> <code>/add_db mongodb+srv://user:pass@cluster2.mongodb.net Cluster-2 80</code>"
        )

    uri = args[0].strip()
    name = args[1].strip() if len(args) > 1 else f"Secondary DB {len(multi_db_manager.nodes) + 1}"
    priority = int(args[2].strip()) if len(args) > 2 and args[2].isdigit() else 80

    node_id = f"db{len(multi_db_manager.nodes) + 1}"
    node = multi_db_manager.register_database(
        node_id=node_id,
        name=name,
        uri=uri,
        db_name=multi_db_manager.nodes.get("primary", node).db_name if multi_db_manager.nodes else "Cluster0",
        collection_name=multi_db_manager.nodes.get("primary", node).collection_name if multi_db_manager.nodes else "Rkmovieszip",
        is_enabled=True,
        priority=priority,
    )
    
    masked = mask_mongo_uri(uri)
    await message.reply_text(
        f"<b>Database Added Successfully!</b>\n\n"
        f"• <b>ID:</b> <code>{node_id}</code>\n"
        f"• <b>Name:</b> <code>{name}</code>\n"
        f"• <b>URI:</b> <code>{masked}</code>\n"
        f"• <b>Priority:</b> <code>{priority}</code>\n"
        f"• <b>Status:</b> <code>ENABLED (ON)</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["del_db", "deldb"]))
async def remove_database_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    args = message.text.split()[1:]
    if not args:
        return await message.reply_text("<b>Usage:</b> <code>/del_db &lt;db_id&gt;</code>")

    node_id = args[0].strip().lower()
    success, msg = await multi_db_manager.remove_database(node_id)
    await message.reply_text(f"<b>{msg}</b>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command(["switch_db", "switchdb"]))
async def switch_database_target_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    args = message.text.split()[1:]
    if not args:
        return await message.reply_text("<b>Usage:</b> <code>/switch_db &lt;db_id&gt;</code>")

    node_id = args[0].strip().lower()
    success, msg = multi_db_manager.set_active_target(node_id)
    await message.reply_text(f"<b>{msg}</b>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command(["toggle_db", "toggledb"]))
async def toggle_database_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    args = message.text.split()[1:]
    if not args:
        return await message.reply_text("<b>Usage:</b> <code>/toggle_db &lt;db_id&gt; [on/off]</code>")

    node_id = args[0].strip().lower()
    node = multi_db_manager.get_node(node_id)
    if not node:
        return await message.reply_text(f"<b>Database node <code>{node_id}</code> not found.</b>")

    if len(args) > 1:
        new_state = args[1].strip().lower() in ("on", "true", "1", "enable")
    else:
        new_state = not node.is_enabled

    success, msg = multi_db_manager.set_enabled(node_id, new_state)
    await message.reply_text(f"<b>{msg}</b>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command(["set_db_priority", "setpriority"]))
async def set_priority_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    args = message.text.split()[1:]
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply_text("<b>Usage:</b> <code>/set_db_priority &lt;db_id&gt; &lt;priority_number&gt;</code>")

    node_id = args[0].strip().lower()
    priority = int(args[1].strip())
    success, msg = multi_db_manager.set_priority(node_id, priority)
    await message.reply_text(f"<b>{msg}</b>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command(["test_db", "testdb"]))
async def test_database_command(client: Client, message: Message):

    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")

    status_msg = await message.reply_text("<b>Testing database latency... Please wait.</b>")
    results = await multi_db_manager.test_all_connections()
    lines = ["<b>Database Connection Health:</b>\n"]
    for nid, res in results.items():
        name = res.get("name")
        healthy = res.get("is_healthy")
        latency = res.get("latency_ms")
        err = res.get("error")
        lat_str = f"<code>{latency}ms</code>" if healthy else f"<code>Failed ({err})</code>"
        lines.append(f"• <b>{name}</b> (<code>{nid}</code>): {lat_str}")
    await status_msg.edit_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)


@Client.on_callback_query(filters.regex(r"^multidb#"))
async def multidb_callback_handler(client: Client, query: CallbackQuery):
    actor_id = query.from_user.id
    if not _is_bot_admin(actor_id):
        return await query.answer("This setting can only be modified by Bot Admins.", show_alert=True)

    data = query.data or ""
    parts = data.split("#")
    action = parts[1] if len(parts) > 1 else ""

    if action == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return await query.answer("Closed.")

    if action == "main":
        report = await multi_db_manager.get_full_status_report()
        text = format_multidb_dashboard_text(report)
        keyboard = build_multidb_main_keyboard()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        return await query.answer("Refreshed.")

    if action == "test_all":
        await query.answer("Testing all connections...", show_alert=False)
        await multi_db_manager.test_all_connections()
        report = await multi_db_manager.get_full_status_report()
        text = format_multidb_dashboard_text(report)
        keyboard = build_multidb_main_keyboard()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        return await query.answer("Latency tested.")

    if action == "switch_menu":
        report = await multi_db_manager.get_full_status_report()
        kb = build_multidb_switch_target_keyboard(report.get("nodes", []))
        await query.message.edit_text(
            "<b>Select the cluster you wish to designate as the Active Indexing Target:</b>\n\n"
            "<i>All new indexed files will be routed to this cluster.</i>",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
        )
        return await query.answer()

    if action == "set_target":
        target_id = parts[2] if len(parts) > 2 else "primary"
        success, msg = multi_db_manager.set_active_target(target_id)
        await query.answer(msg, show_alert=True)
        report = await multi_db_manager.get_full_status_report()
        text = format_multidb_dashboard_text(report)
        keyboard = build_multidb_main_keyboard()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        return

    if action == "toggle_menu":
        report = await multi_db_manager.get_full_status_report()
        kb = build_multidb_toggle_keyboard(report.get("nodes", []))
        await query.message.edit_text(
            "<b>Select a cluster to toggle participation (ON / OFF):</b>\n\n"
            "<i>Turning OFF excludes the cluster from search reads and new indexing without deleting any records.</i>",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
        )
        return await query.answer()

    if action == "toggle_state":
        target_id = parts[2] if len(parts) > 2 else "primary"
        node = multi_db_manager.get_node(target_id)
        if node:
            success, msg = multi_db_manager.set_enabled(target_id, not node.is_enabled)
            await query.answer(msg, show_alert=True)
        report = await multi_db_manager.get_full_status_report()
        text = format_multidb_dashboard_text(report)
        keyboard = build_multidb_main_keyboard()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        return


# ===========================================================================
# FEATURE 45 – WATCH AD TO UNLOCK FILE & FEATURE 43 PERSONAL FILE LOCK ADMIN
# ===========================================================================

@Client.on_message(filters.command(["ad_unlock_stats", "adunlockstats"]))
async def ad_unlock_stats_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    enabled = await ad_unlock_manager.is_enabled(user_db=db)
    expiry = await ad_unlock_manager.get_expiry_seconds(user_db=db)
    locked_files = await ad_unlock_manager.get_personal_locked_files(user_db=db)
    metrics = ad_unlock_manager.get_metrics_summary()
    text = (
        "<b>📊 Feature 45 – Watch Ad to Unlock Status</b>\n\n"
        f"• <b>Status:</b> <code>{'ENABLED' if enabled else 'DISABLED'}</code>\n"
        f"• <b>Pending Expiry Window:</b> <code>{expiry}s</code>\n"
        f"• <b>Feature 43 Locked Files:</b> <code>{len(locked_files)}</code>\n\n"
        "<b>Operational Counters:</b>\n"
        f"• Requests Created: <code>{metrics['requests_created']}</code>\n"
        f"• Verifications Succeeded: <code>{metrics['verifications_succeeded']}</code>\n"
        f"• Verifications Failed: <code>{metrics['verifications_failed']}</code>\n"
        f"• Verifications Expired: <code>{metrics['verifications_expired']}</code>\n"
        f"• Single-File Deliveries Succeeded: <code>{metrics['deliveries_succeeded']}</code>\n"
        f"• Delivery Failures (Safe Retries): <code>{metrics['deliveries_failed']}</code>\n"
        f"• Replay / Cross-User Blocks: <code>{metrics['replay_attempts_blocked']}</code>\n"
        f"• Premium Lock Precedence Blocks: <code>{metrics['premium_lock_blocks']}</code>"
    )
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command(["ad_unlock_toggle", "adunlocktoggle"]))
async def ad_unlock_toggle_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    args = message.text.split()[1:]
    current = await ad_unlock_manager.is_enabled(user_db=db)
    if args:
        new_state = args[0].strip().lower() in ("on", "true", "1", "enable", "enabled")
    else:
        new_state = not current
    await ad_unlock_manager.set_enabled(new_state, user_db=db)
    await message.reply_text(
        f"<b>Watch Ad to Unlock is now <code>{'ENABLED' if new_state else 'DISABLED'}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["ad_unlock_expiry", "adunlockexpiry"]))
async def ad_unlock_expiry_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    args = message.text.split()[1:]
    if not args or not args[0].isdigit():
        return await message.reply_text("<b>Usage:</b> <code>/ad_unlock_expiry &lt;seconds&gt;</code> (min 60)")
    new_secs = await ad_unlock_manager.set_expiry_seconds(int(args[0]), user_db=db)
    await message.reply_text(
        f"<b>Watch Ad pending authorization expiry set to <code>{new_secs}s</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["lock_file", "lockfile"]))
async def lock_personal_file_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    args = message.text.split()[1:]
    if not args:
        return await message.reply_text("<b>Usage:</b> <code>/lock_file &lt;file_id&gt;</code>")
    for fid in args:
        await ad_unlock_manager.lock_personal_file(fid.strip(), user_db=db)
    await message.reply_text(
        f"<b>Locked {len(args)} file(s) as Premium-exclusive (Feature 43 precedence).</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["unlock_file", "unlockfile"]))
async def unlock_personal_file_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    args = message.text.split()[1:]
    if not args:
        return await message.reply_text("<b>Usage:</b> <code>/unlock_file &lt;file_id&gt;</code>")
    for fid in args:
        await ad_unlock_manager.unlock_personal_file(fid.strip(), user_db=db)
    await message.reply_text(
        f"<b>Unlocked {len(args)} file(s) from Personal Lock.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["locked_files", "lockedfiles"]))
async def list_locked_files_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    locked = sorted(await ad_unlock_manager.get_personal_locked_files(user_db=db))
    bulk = sorted(await ad_unlock_manager.get_bulk_locked_patterns(user_db=db))
    if not locked and not bulk:
        return await message.reply_text("<b>No individually or bulk locked files configured.</b>")
    lines = [f"<b>🔒 Feature 43 Personal Locked Files ({len(locked)}) & Bulk Patterns ({len(bulk)}):</b>\n"]
    if locked:
        lines.append("<b>Individual File IDs:</b>")
        lines.extend(f"• <code>{html_escape(fid)}</code>" for fid in locked[:30])
    if bulk:
        lines.append("\n<b>Bulk Lock Patterns:</b>")
        lines.extend(f"• <code>{html_escape(pat)}</code>" for pat in bulk[:30])
    await message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command(["lock_bulk", "lockbulk"]))
async def lock_bulk_pattern_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.reply_text("<b>Usage:</b> <code>/lock_bulk &lt;keyword_or_pattern&gt;</code>")
    pattern = args[1].strip()
    await ad_unlock_manager.lock_bulk_pattern(pattern, user_db=db)
    await message.reply_text(
        f"<b>Bulk locked pattern <code>{html_escape(pattern)}</code> as Premium-exclusive (Feature 43 precedence).</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["unlock_bulk", "unlockbulk"]))
async def unlock_bulk_pattern_command(client: Client, message: Message):
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text("<b>This command is only for Bot Admins.</b>")
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.reply_text("<b>Usage:</b> <code>/unlock_bulk &lt;keyword_or_pattern&gt;</code>")
    pattern = args[1].strip()
    await ad_unlock_manager.unlock_bulk_pattern(pattern, user_db=db)
    await message.reply_text(
        f"<b>Unlocked bulk pattern <code>{html_escape(pattern)}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )