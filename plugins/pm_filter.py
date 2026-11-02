# This code has been modified by @Lootere
# Please do not remove this credit
import asyncio
import re
import ast
import math
import random
import os
import secrets
from collections import OrderedDict
from time import monotonic
lock = asyncio.Lock()
import pytz
from datetime import datetime, timedelta, date, time
from telegram import InputMediaPhoto
from pyrogram.errors.exceptions.bad_request_400 import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from Script import script
import pyrogram
from database.connections_mdb import active_connection, all_connections, delete_connection, if_active, make_active, \
    make_inactive
from info import *
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, InputMediaVideo
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from utils import get_size, is_subscribed, get_poster, temp, get_settings, save_group_settings, get_shortlink, stream_site, get_text, imdb, get_vip_lock_message, get_search_button_popup_message, get_flirty_interaction_message, is_resolution_locked, get_auto_delete_seconds, get_auto_delete_label, AUTO_DELETE_OPTIONS, get_sponsor_button
from database.users_chats_db import db
from database.Lootere_reffer import sdb
from database.ia_filterdb import Media, get_file_details, get_search_results, get_bad_files, get_search_suggestions

from fuzzywuzzy import process
TIMEZONE = "Asia/Kolkata"

import logging
from urllib.parse import quote_plus
from Lootere.utils.file_properties import get_name, get_hash, get_media_file_size

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

BUTTONS = {}
RESULT_SORTS = {}
SEARCH_FILTERS = {}
YEAR_FILTER_PREVIOUS = {}
SEARCH_SUGGESTIONS = OrderedDict()
SEARCH_SUGGESTION_TTL = 600


def _get_search_filter_context(query):
    key = f"{query.message.chat.id}-{query.message.id}"
    base_search = BUTTONS.get(key) or temp.KEYWORD.get(query.from_user.id)
    return key, base_search, dict(SEARCH_FILTERS.get(key, {}))


def _search_suggestion_buttons(suggestions, user_id, chat_id):
    buttons = []
    for suggestion in suggestions:
        token = secrets.token_urlsafe(6)
        SEARCH_SUGGESTIONS[token] = (
            int(user_id),
            int(chat_id),
            suggestion["title"],
            monotonic(),
        )
        SEARCH_SUGGESTIONS.move_to_end(token)
        while len(SEARCH_SUGGESTIONS) > 512:
            SEARCH_SUGGESTIONS.popitem(last=False)

        title = suggestion["title"]
        label = title if len(title) <= 60 else title[:57] + "..."
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"search_suggestion#{user_id}#{token}",
            )
        ])
    return buttons


def _append_year_sort_controls(buttons, user_id):
    buttons.insert(2, [
        InlineKeyboardButton("📅 Sᴀᴀʟ", callback_data=f"year#{user_id}"),
        InlineKeyboardButton("↕ Sᴏʀᴛ", callback_data=f"sort#{user_id}")
    ])


def _build_search_keyboard(
    files, user_id, key, next_offset, total_results, settings, sponsor_button=None
):
    buttons = []
    if not settings.get("button", SINGLE_BUTTON):
        buttons.extend([
            [InlineKeyboardButton(
                text=f"[{get_size(file.file_size)}] {file.file_name}",
                callback_data=f"files#{file.file_id}"
            )]
            for file in files
        ])

    buttons.extend([
        [InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")],
        [
            InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{user_id}"),
            InlineKeyboardButton("Qᴜᴀʟɪᴛʏ", callback_data=f"quality#{user_id}")
        ],
        [
            InlineKeyboardButton("📅 Sᴀᴀʟ", callback_data=f"year#{user_id}"),
            InlineKeyboardButton("↕ Sᴏʀᴛ", callback_data=f"sort#{user_id}")
        ],
        [
            InlineKeyboardButton("Sᴇᴀꜱᴏɴs", callback_data=f"seas#{user_id}"),
            InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{user_id}")
        ]
    ])
    if sponsor_button:
        buttons.append([sponsor_button])

    if next_offset != "":
        page_size = 10 if settings.get("max_btn", True) else int(MAX_B_TN)
        buttons.append([
            InlineKeyboardButton("1 / {}".format(math.ceil(total_results / page_size)), callback_data="pages"),
            InlineKeyboardButton("Nᴇxᴛ ➪", callback_data=f"next_{user_id}_{key}_{next_offset}")
        ])
    else:
        buttons.append([
            InlineKeyboardButton("Nᴏ Mᴏʀᴇ Pᴀɢᴇs", callback_data="pages")
        ])
    return buttons


async def _update_search_results_message(
    query, settings, files, search, total_results, buttons, caption=None
):
    markup = InlineKeyboardMarkup(buttons)
    if settings.get("button", SINGLE_BUTTON):
        if caption is None:
            caption = await get_text(settings, "0.00", files, query, total_results, search)
        if query.message.photo:
            await query.message.edit_caption(caption=caption, reply_markup=markup)
        else:
            await query.message.edit_text(text=caption, reply_markup=markup)
    else:
        await query.edit_message_reply_markup(reply_markup=markup)


async def _update_no_search_results_message(query):
    message = get_flirty_interaction_message(query.from_user.id, "no_results")
    try:
        if query.message.photo:
            await query.message.edit_caption(
                caption=message, reply_markup=query.message.reply_markup
            )
        else:
            await query.message.edit_text(
                text=message, reply_markup=query.message.reply_markup
            )
    except MessageNotModified:
        pass


RESOLUTION_LOCK_MESSAGES = [
    "{resolution} chahiye baby? 😘 Ye sirf VIP ke liye hai. 480p ya 720p try karo ❤️",
    "Oho jaan! {resolution} ki demand hai? 😉 VIP bano phir full quality ka maza lo 💋",
    "Darling, {resolution} chahiye? 😍 Ye VIP ka exclusive feature hai.",
    "Aww baby! {resolution} quality? 🥺 Pehle VIP bano jaan ❤️",
    "{resolution} par nazar hai cutie? 😈 Ye VIP members ke liye reserved hai.",
]


def _get_resolution_lock_message(user_id, resolution):
    key = ("resolution_lock", user_id)
    previous_message = temp.VIP_LOCK_MESSAGES.get(key)
    available_messages = [
        message for message in RESOLUTION_LOCK_MESSAGES
        if message != previous_message
    ]
    message_template = random.choice(available_messages)
    temp.VIP_LOCK_MESSAGES[key] = message_template
    return message_template.format(resolution=resolution)



@Client.on_callback_query(filters.regex(r"^streaming"))
async def stream_download(bot, query):
    try:
        _, file_id, grp_id = query.data.split('#', 2)
        user_id = query.from_user.id
        settings = await get_settings(int(grp_id))
        username =  query.from_user.mention
        msg = await bot.send_cached_media(
            chat_id=BIN_CHANNEL,
            file_id=file_id)
            
        online = f"{URL}watch/{str(msg.id)}/{quote_plus(get_name(msg))}?hash={get_hash(msg)}"
        download = f"{URL}{str(msg.id)}/{quote_plus(get_name(msg))}?hash={get_hash(msg)}"
        non_online = await stream_site(online, grp_id)
        non_download = await stream_site(download, grp_id)
        if not await db.has_premium_access(user_id) and settings.get('stream_mode', STREAM_MODE):
            await msg.reply_text(text=f"tg://openmessage?user_id={user_id}\n•• ᴜꜱᴇʀɴᴀᴍᴇ : {username} STREAM MODE ON",
                reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📥 ᴅᴏᴡɴʟᴏᴀᴅ 📥", url=non_download),
                        InlineKeyboardButton("🖥️ ꜱᴛʀᴇᴇᴍ 🖥️", url=non_online)]]))
            await query.answer("𝐍𝐨𝐭𝐞:\n𝐓𝐡𝐞 𝐀𝐝𝐬-𝐅𝐫𝐞𝐞 𝐒𝐞𝐫𝐯𝐢𝐜𝐞𝐬 𝐎𝐧𝐥𝐲 𝐅𝐨𝐫 𝐏𝐫𝐞𝐦𝐢𝐮𝐦 𝐔𝐬𝐞𝐫𝐬\n\n‼️Tᴏ ᴋɴᴏᴡ ᴍᴏʀᴇ, ᴄʜᴇᴀᴋ ʙᴇʟᴏᴡ..!!!", show_alert=True)
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📥 ᴅᴏᴡɴʟᴏᴀᴅ 📥", url=non_download),
                        InlineKeyboardButton("🖥️ ꜱᴛʀᴇᴇᴍ 🖥️", url=non_online)
                    ],[
                        InlineKeyboardButton('⁉️ Hᴏᴡ Tᴏ Dᴏᴡɴʟᴏᴀᴅ ⁉️', url=STREAM_HTO)]]))
            return
        else:
            await msg.reply_text(text=f"tg://openmessage?user_id={user_id}\n•• ᴜꜱᴇʀɴᴀᴍᴇ : {username} SHORT MODE OFF",
                reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📥 ᴅᴏᴡɴʟᴏᴀᴅ 📥", url=download),
                        InlineKeyboardButton("🖥️ ꜱᴛʀᴇᴇᴍ 🖥️", url=online)]]))
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📥 ᴅᴏᴡɴʟᴏᴀᴅ 📥", url=download),
                        InlineKeyboardButton("🖥️ ꜱᴛʀᴇᴇᴍ 🖥️", url=online)
                    ],[
                        InlineKeyboardButton('⁉️ ᴄʟᴏsᴇ ⁉️', callback_data='close_data')]]))
    except Exception as e:
        await query.answer(f'{e}', show_alert=True)             
        
@Client.on_message(filters.private & filters.command("stream"))
async def reply_stream(client, message):
    reply_message = message.reply_to_message
    user_id = message.from_user.id
    user_name =  message.from_user.mention 
    if not reply_message or not (reply_message.document or reply_message.video):
        return await message.reply_text("**Reply to a video or document file.**")

    file_id = reply_message.document or reply_message.video

    try:
        msg = await reply_message.forward(chat_id=BIN_CHANNEL)
        await client.send_message(text=f"<b>Streaming Link Gernated By </b>:{message.from_user.mention}  <code>{message.from_user.id}</code> 👁️✅",
                  chat_id=BIN_CHANNEL,
                  disable_web_page_preview=True)
    except Exception as e:
        return await message.reply_text(f"Error: {str(e)}")

    online = f"{URL}watch/{str(msg.id)}/{quote_plus(get_name(msg))}?hash={get_hash(msg)}"
    download = f"{URL}{str(msg.id)}/{quote_plus(get_name(msg))}?hash={get_hash(msg)}"
    non_online = await stream_site(online)
    non_download = await stream_site(download)

    file_name = file_id.file_name.replace("_", " ").replace(".mp4", "").replace(".mkv", "").replace(".", " ")
    if not await db.has_premium_access(user_id) and STREAM_MODE == True:  
        await message.reply_text(
            text=f"<b>𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !\n\n📂 Fɪʟᴇ ɴᴀᴍᴇ :</b> <a href={CHNL_LNK}>{file_name}</a>\n\n<b>📥 Dᴏᴡɴʟᴏᴀᴅ : {non_download}\n\n🖥WATCH  : {non_online}\n\n⚠️ Tʜᴇ ʟɪɴᴋ ᴡɪʟʟ ɴᴏᴛ ᴇxᴘɪʀᴇ ᴜɴᴛɪʟ ᴛʜᴇ ʙᴏᴛ'ꜱ ꜱᴇʀᴠᴇʀ ɪꜱ ᴄʜᴀɴɢᴇᴅ. 🔋\n\n𝐍𝐨𝐭𝐞:\n𝐓𝐡𝐞 𝐀𝐝𝐬-𝐅𝐫𝐞𝐞 𝐒𝐞𝐫𝐯𝐢𝐜𝐞𝐬 𝐎𝐧𝐥𝐲 𝐅𝐨𝐫 𝐏𝐫𝐞𝐦𝐢𝐮𝐦 𝐔𝐬𝐞𝐫𝐬\n\n‼️Tᴏ ᴋɴᴏᴡ ᴍᴏʀᴇ, ᴄʜᴇᴀᴋ ʙᴇʟᴏᴡ..!!!</b>",
            reply_markup=InlineKeyboardMarkup(
                [[
                  InlineKeyboardButton("📥 ᴅᴏᴡɴʟᴏᴀᴅ 📥", url=non_download),
                  InlineKeyboardButton("🖥️ ꜱᴛʀᴇᴇᴍ 🖥️", url=non_online)
                  ],[
                  InlineKeyboardButton('🔒 Hᴏᴡ Tᴏ Dᴏᴡɴʟᴏᴀᴅ 🔒', url=STREAMHTO)
                ],[
                 InlineKeyboardButton('✨ ʀᴇᴍᴏᴠᴇ ᴀᴅꜱ ✨', callback_data="premium_info")
                ]]),
                disable_web_page_preview=True
        )
    else:
        await message.reply_text(
            text=f"<b>𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !\n\n📂 Fɪʟᴇ ɴᴀᴍᴇ :</b> <a href={CHNL_LNK}>{file_name}</a>\n\n<b>📥 Dᴏᴡɴʟᴏᴀᴅ : {download}\n\n🖥WATCH  : {online}\n\n⚠️ Tʜᴇ ʟɪɴᴋ ᴡɪʟʟ ɴᴏᴛ ᴇxᴘɪʀᴇ ᴜɴᴛɪʟ ᴛʜᴇ ʙᴏᴛ'ꜱ ꜱᴇʀᴠᴇʀ ɪꜱ ᴄʜᴀɴɢᴇᴅ. 🔋</b>",
            reply_markup=InlineKeyboardMarkup(
                [[
                  InlineKeyboardButton("📥 ᴅᴏᴡɴʟᴏᴀᴅ 📥", url=download),
                  InlineKeyboardButton("🖥️ ꜱᴛʀᴇᴇᴍ 🖥️", url=online)
                ]]),
                disable_web_page_preview=True
        )

@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_text(bot, message):
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
    await message.react(emoji=random.choice(REACTION), big=True)
    if message.text.startswith("/") or message.text.startswith("#"): return
    if await db.get_setting("PM_FILTER", default=PM_FILTER) or await db.has_premium_access(message.from_user.id):
        await auto_filter(bot, message)
    else:
        await message.reply_text("<b>ɪғ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴛᴀᴋᴇ ᴀ ᴍᴏᴠɪᴇ ғʀᴏᴍ ᴛʜᴇ ʙᴏᴛ ᴛʜᴇɴ ʏᴏᴜ ᴡɪʟʟ ʜᴀᴠᴇ ᴛᴏ ᴘᴀʏ ᴛʜᴇ ᴘʀᴇᴍɪᴜᴍ ғᴏʀ ᴛʜᴇ ʙᴏᴛ, ᴏᴛʜᴇʀᴡɪsᴇ ʏᴏᴜ ᴄᴀɴ ᴛᴀᴋᴇ ᴛʜᴇ ᴍᴏᴠɪᴇ ғʀᴏᴍ ᴛʜᴇ ɢʀᴏᴜᴘ\n\nयदि आप बॉट से मूवी लेना चाहते हैं तो आपको बॉट का प्रीमियम लेना होगा\n\n 💸20 Rs Monthly ⏱️\n\nअन्यथा आप ग्रुप से मूवी ले सकते हैं.</b>", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Gʀᴏᴜᴘ Hᴇʀᴇ", url=GRP_LNK)],
            [InlineKeyboardButton('✨Bʏ Pʀᴇᴍɪᴜᴍ: Sᴇᴀʀᴄʜ Pᴍ 🔍 🚫✨', callback_data=f'premium_info')]]))



@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(bot, message):
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)  
    await message.react(emoji=random.choice(REACTION), big=True)
    is_verified = await db.check_group_verification(message.chat.id)
    is_rejected = await db.rejected_group(message.chat.id)
    user = await bot.get_chat_member(message.chat.id, message.from_user.id)
    total=await bot.get_chat_members_count(message.chat.id)
    owner=user.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] or str(message.from_user.id) in ADMINS
    if message.text.startswith("/") or message.text.startswith("#"): return 
    if not is_rejected:
        if is_verified:
            settings = await get_settings(message.chat.id)
            if settings['auto_ffilter']:
                await auto_filter(bot, message)
        else:
            if owner:
                await message.reply_text(text=f"Tʜɪs Gʀᴏᴜᴘ ɪs Nᴏᴛ Vᴇʀɪғɪᴇᴅ. Pʟᴇᴀsᴇ Usᴇ Tʜɪs /verify Cᴏᴍᴍᴀɴᴅ ᴛᴏ Vᴇʀɪғʏ Tʜᴇ Gʀᴏᴜᴘ.")
            else:
                await message.reply_text(text=f" I Cᴀɴɴᴏᴛ Gɪᴠᴇ Mᴏᴠɪᴇs ɪɴ Tʜɪs Gʀᴏᴜᴘ Bᴇᴄᴀᴜsᴇ Tʜɪs Gʀᴏᴜᴘ ɪs Nᴏᴛ Vᴇʀɪғɪᴇᴅ.")
    else:
        if owner:
            await message.reply_text(text=f"ʏᴏᴜʀ ɢʀᴏᴜᴘ ʜᴀs ʙᴇᴇɴ ʀᴇᴊᴇᴄᴛᴇᴅ. ᴄᴏɴᴛᴀᴄᴛ ᴍʏ ᴀᴅᴍɪɴ.\n@Looteredev")
        else:
            await message.reply_text(text=f"ᴛʜɪs ɢʀᴏᴜᴘ ɴᴏᴛ ᴠᴇʀɪғɪᴇᴅ")
        


@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    try:
        curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        ident, req, key, offset = query.data.split("_")
        if int(req) not in [query.from_user.id, 0]:
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        try:
            offset = int(offset)
        except:
            offset = 0
        search = BUTTONS.get(key)
        files, n_offset, total = await get_search_results(
            query.message.chat.id, search, offset=offset, filter=True,
            sort_by=RESULT_SORTS.get(key, "season"),
            filters=SEARCH_FILTERS.get(key, {}),
        )
        try:
            n_offset = int(n_offset)
        except:
            n_offset = 0
    
        if not files:
            return
        settings = await get_settings(query.message.chat.id)
        temp.GETALL[key] = files
        temp.CHAT[query.from_user.id] = query.message.chat.id
        if not settings['button']:
            btn = [
                [
                    InlineKeyboardButton(
                        text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'files#{file.file_id}'
                    ),
                ]
                for file in files
            ]
            btn.insert(0, [
                InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{req}"), 
                InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{req}")
            ])
            btn.insert(0, [
                InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{req}"),
                InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{req}")
            ])
            btn.insert(0, [
                InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
            ])
        else:
            btn = []
            btn.insert(0, [
                InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{req}"), 
                InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{req}")
            ])
            btn.insert(0, [
                InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{req}"),
                InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{req}")
            ])
            btn.insert(0, [
                InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
            ])
        _append_year_sort_controls(btn, req)
        sponsor_button = await get_sponsor_button()
        if sponsor_button:
            btn.append([sponsor_button])
        try:
            if settings['max_btn']:
                if 0 < offset <= 10:
                    off_set = 0
                elif offset == 0:
                    off_set = None
                else:
                    off_set = offset - 10
                if n_offset == 0:
                    btn.append(
                        [InlineKeyboardButton("⌫ 𝐁𝐀𝐂𝐊", callback_data=f"next_{req}_{key}_{off_set}"), InlineKeyboardButton(f"{math.ceil(int(offset)/10)+1} / {math.ceil(total/10)}", callback_data="pages")]
                    )
                elif off_set is None:
                    btn.append([InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(f"{math.ceil(int(offset)/10)+1} / {math.ceil(total/10)}", callback_data="pages"), InlineKeyboardButton("𝐍𝐄𝐗𝐓 ➪", callback_data=f"next_{req}_{key}_{n_offset}")])
                else:
                    btn.append(
                        [
                            InlineKeyboardButton("⌫ 𝐁𝐀𝐂𝐊", callback_data=f"next_{req}_{key}_{off_set}"),
                            InlineKeyboardButton(f"{math.ceil(int(offset)/10)+1} / {math.ceil(total/10)}", callback_data="pages"),
                            InlineKeyboardButton("𝐍𝐄𝐗𝐓 ➪", callback_data=f"next_{req}_{key}_{n_offset}")
                        ],
                    )
            else:
                if 0 < offset <= int(MAX_B_TN):
                    off_set = 0
                elif offset == 0:
                    off_set = None
                else:
                    off_set = offset - int(MAX_B_TN)
                if n_offset == 0:
                    btn.append(
                        [InlineKeyboardButton("⌫ 𝐁𝐀𝐂𝐊", callback_data=f"next_{req}_{key}_{off_set}"), InlineKeyboardButton(f"{math.ceil(int(offset)/int(MAX_B_TN))+1} / {math.ceil(total/int(MAX_B_TN))}", callback_data="pages")]
                    )
                elif off_set is None:
                    btn.append([InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(f"{math.ceil(int(offset)/int(MAX_B_TN))+1} / {math.ceil(total/int(MAX_B_TN))}", callback_data="pages"), InlineKeyboardButton("𝐍𝐄𝐗𝐓 ➪", callback_data=f"next_{req}_{key}_{n_offset}")])
                else:
                    btn.append(
                        [
                            InlineKeyboardButton("⌫ 𝐁𝐀𝐂𝐊", callback_data=f"next_{req}_{key}_{off_set}"),
                            InlineKeyboardButton(f"{math.ceil(int(offset)/int(MAX_B_TN))+1} / {math.ceil(total/int(MAX_B_TN))}", callback_data="pages"),
                            InlineKeyboardButton("𝐍𝐄𝐗𝐓 ➪", callback_data=f"next_{req}_{key}_{n_offset}")
                        ],
                    )
        except KeyError:
            await save_group_settings(query.message.chat.id, 'max_btn', True)
            if 0 < offset <= 10:
                off_set = 0
            elif offset == 0:
                off_set = None
            else:
                off_set = offset - 10
            if n_offset == 0:
                btn.append(
                    [InlineKeyboardButton("⌫ 𝐁𝐀𝐂𝐊", callback_data=f"next_{req}_{key}_{off_set}"), InlineKeyboardButton(f"{math.ceil(int(offset)/10)+1} / {math.ceil(total/10)}", callback_data="pages")]
                )
            elif off_set is None:
                btn.append([InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(f"{math.ceil(int(offset)/10)+1} / {math.ceil(total/10)}", callback_data="pages"), InlineKeyboardButton("𝐍𝐄𝐗𝐓 ➪", callback_data=f"next_{req}_{key}_{n_offset}")])
            else:
                btn.append(
                    [
                        InlineKeyboardButton("⌫ 𝐁𝐀𝐂𝐊", callback_data=f"next_{req}_{key}_{off_set}"),
                        InlineKeyboardButton(f"{math.ceil(int(offset)/10)+1} / {math.ceil(total/10)}", callback_data="pages"),
                        InlineKeyboardButton("𝐍𝐄𝐗𝐓 ➪", callback_data=f"next_{req}_{key}_{n_offset}")
                    ],
                )
        if settings.get("button", SINGLE_BUTTON):
            cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
            time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
            remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
            cap = await get_text(settings, remaining_seconds, files, query, total, search)
            try:
                await query.message.edit_text(text=cap, reply_markup=InlineKeyboardMarkup(btn))
            except MessageNotModified:
                pass
        else:
            try:
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
            except MessageNotModified:
                pass
            await query.answer()
    except Exception as e:
        await query.answer(f"error found out\n\n{e}", show_alert=True)
        return
    
@Client.on_callback_query(filters.regex(r"^lang#"))
async def language_check(bot, query):
    try:
        curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        _, userid, language = query.data.split("#")
        if int(userid) not in [query.from_user.id, 0]:
            return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
        if language == "unknown":
            return await query.answer()
        result_key, movie, search_filters = _get_search_filter_context(query)
        if not movie:
            return await query.answer("Pehle movie search karo jaan 😘", show_alert=True)
        if language == "home":
            search_filters.pop("language", None)
        else:
            search_filters["language"] = language
        SEARCH_FILTERS[result_key] = search_filters
        files, offset, total_results = await get_search_results(
            query.message.chat.id, movie, offset=0, filter=True,
            sort_by=RESULT_SORTS.get(result_key, "season"),
            filters=search_filters,
        )
        if files:
            settings = await get_settings(query.message.chat.id)
            key = f"{query.message.chat.id}-{query.message.id}"
            BUTTONS[key] = movie
            temp.GETALL[key] = files
            temp.CHAT[query.from_user.id] = query.message.chat.id
            if not settings['button']:
                btn = [
                    [
                        InlineKeyboardButton(
                            text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'files#{file.file_id}'
                        ),
                    ]
                    for file in files
                ]
                btn.insert(0, [
                    InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            else:
                btn = []
                btn.insert(0, [
                    InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            _append_year_sort_controls(btn, userid)
    
            if offset != "":
                BUTTONS[key] = movie
                req = userid
                try:
                    if settings['max_btn']:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
    
                    else:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/int(MAX_B_TN))}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
                except KeyError:
                    await save_group_settings(query.message.chat.id, 'max_btn', True)
                    btn.append(
                        [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                    )
            else:
                btn.append(
                    [InlineKeyboardButton(text="𝐍𝐎 𝐌𝐎𝐑𝐄 𝐏𝐀𝐆𝐄𝐒 𝐀𝐕𝐀𝐈𝐋𝐀𝐁𝐋𝐄",callback_data="pages")]
                )
            if settings.get("button", SINGLE_BUTTON):
                cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
                time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
                remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
                cap = await get_text(settings, remaining_seconds, files, query, total_results, movie)
                try:
                    await _update_search_results_message(
                        query, settings, files, movie, total_results, btn, caption=cap
                    )
                except MessageNotModified:
                    pass
            else:
                try:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
                except MessageNotModified:
                    pass
            await query.answer()
        else:
            await _update_no_search_results_message(query)
            return await query.answer()
    except Exception as e:
        logger.exception("Language filter callback failed")
        return await query.answer("Search error aa gaya jaan, thodi der baad try karo.", show_alert=True)
    
@Client.on_callback_query(filters.regex(r"^select_lang#"))
async def select_language(bot, query):
    _, userid = query.data.split("#")
    if int(userid) not in [query.from_user.id, 0]:
        return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
    btn = [[
        InlineKeyboardButton("Sᴇʟᴇᴄᴛ Yᴏᴜʀ Dᴇꜱɪʀᴇᴅ Lᴀɴɢᴜᴀɢᴇ ↓", callback_data=f"lang#{userid}#unknown")
    ],[
        InlineKeyboardButton("Eɴɢʟɪꜱʜ", callback_data=f"lang#{userid}#eng"),
        InlineKeyboardButton("Tᴀᴍɪʟ", callback_data=f"lang#{userid}#tam"),
        InlineKeyboardButton("Hɪɴᴅɪ", callback_data=f"lang#{userid}#hin")
    ],[
        InlineKeyboardButton("Kᴀɴɴᴀᴅᴀ", callback_data=f"lang#{userid}#kan"),
        InlineKeyboardButton("Tᴇʟᴜɢᴜ", callback_data=f"lang#{userid}#tel")
    ],[
        InlineKeyboardButton("Mᴀʟᴀʏᴀʟᴀᴍ", callback_data=f"lang#{userid}#mal")
    ],[
        InlineKeyboardButton("Gᴜᴊᴀʀᴀᴛɪ", callback_data=f"lang#{userid}#guj"),
        InlineKeyboardButton("Mᴀʀᴀᴛʜɪ", callback_data=f"lang#{userid}#mar"),
        InlineKeyboardButton("Pᴜɴᴊᴀʙɪ", callback_data=f"lang#{userid}#pun")
    ],[
        InlineKeyboardButton("Mᴜʟᴛɪ Aᴜᴅɪᴏ", callback_data=f"lang#{userid}#multi"),
        InlineKeyboardButton("Dᴜᴀʟ Aᴜᴅɪᴏ", callback_data=f"lang#{userid}#dual")
    ],[
        InlineKeyboardButton("Gᴏ Bᴀᴄᴋ", callback_data=f"lang#{userid}#home")
    ]]
    try:
       await query.edit_message_reply_markup(
           reply_markup=InlineKeyboardMarkup(btn)
       )
    except MessageNotModified:
        pass
    await query.answer()

@Client.on_callback_query(filters.regex(r"^year#"))
async def year_filter(bot, query):
    parts = query.data.split("#")
    userid = int(parts[1])
    if userid not in [query.from_user.id, 0]:
        return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

    if len(parts) == 2:
        key, _, search_filters = _get_search_filter_context(query)
        YEAR_FILTER_PREVIOUS[key] = search_filters
        years = range(2030, 1949, -1)
        buttons = []
        year_row = []
        for year in years:
            year_row.append(InlineKeyboardButton(str(year), callback_data=f"year#{userid}#{year}"))
            if len(year_row) == 3:
                buttons.append(year_row)
                year_row = []
        if year_row:
            buttons.append(year_row)
        buttons.append([InlineKeyboardButton("Sᴀʙʜɪ Sᴀᴀʟ", callback_data=f"year#{userid}#home")])
        buttons.append([InlineKeyboardButton("Gᴏ Bᴀᴄᴋ", callback_data=f"year#{userid}#back")])
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
        except MessageNotModified:
            pass
        await query.answer()
        return

    if len(parts) != 3:
        return await query.answer("Sᴀᴀʟ sᴇʟᴇᴄᴛ ᴋᴀʀᴏ 😏", show_alert=True)

    key, base_search, search_filters = _get_search_filter_context(query)
    if not base_search:
        return await query.answer("Pᴇʜʟᴇ ᴍᴏᴠɪᴇ sᴇᴀʀᴄʜ ᴋᴀʀᴏ 😏", show_alert=True)
    if parts[2] == "back":
        search_filters = YEAR_FILTER_PREVIOUS.get(key, search_filters)
        SEARCH_FILTERS[key] = search_filters
        settings = await get_settings(query.message.chat.id)
        files, next_offset, total_results = await get_search_results(
            query.message.chat.id,
            base_search,
            offset=0,
            filter=True,
            sort_by=RESULT_SORTS.get(key, "season"),
            filters=search_filters,
        )
        temp.GETALL[key] = files
        temp.CHAT[query.from_user.id] = query.message.chat.id
        BUTTONS[key] = base_search
        buttons = _build_search_keyboard(
            files,
            userid,
            key,
            next_offset,
            total_results,
            settings,
            sponsor_button=await get_sponsor_button(),
        )
        try:
            await _update_search_results_message(
                query, settings, files, base_search, total_results, buttons
            )
        except MessageNotModified:
            pass
        await query.answer()
        return
    if parts[2] != "home" and not re.fullmatch(r"(?:19[5-9]\d|20[0-2]\d|2030)", parts[2]):
        return await query.answer("1950 sᴇ 2030 ᴋᴇ ʙᴇᴇᴄʜ ᴋᴀ sᴀᴀʟ ᴄʜᴜɴᴏ 😏", show_alert=True)

    if parts[2] == "home":
        search_filters.pop("year", None)
    else:
        search_filters["year"] = parts[2]
    SEARCH_FILTERS[key] = search_filters
    sort_by = RESULT_SORTS.get(key, "season")
    files, next_offset, total_results = await get_search_results(
        query.message.chat.id, base_search, offset=0, filter=True,
        sort_by=sort_by, filters=search_filters
    )
    if not files:
        await _update_no_search_results_message(query)
        return await query.answer()

    settings = await get_settings(query.message.chat.id)
    temp.GETALL[key] = files
    temp.CHAT[query.from_user.id] = query.message.chat.id
    BUTTONS[key] = base_search
    RESULT_SORTS[key] = sort_by
    buttons = _build_search_keyboard(
        files,
        userid,
        key,
        next_offset,
        total_results,
        settings,
        sponsor_button=await get_sponsor_button(),
    )
    try:
        await _update_search_results_message(query, settings, files, base_search, total_results, buttons)
    except MessageNotModified:
        pass
    await query.answer()

@Client.on_callback_query(filters.regex(r"^sort#"))
async def sort_search_results(bot, query):
    parts = query.data.split("#")
    userid = int(parts[1])
    if userid not in [query.from_user.id, 0]:
        return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)

    options = {
        "season": "Sᴇᴀsᴏɴ / Eᴘɪsᴏᴅᴇ",
        "recent": "Nᴀʏᴀ Pᴇʜʟᴇ",
        "title": "Tɪᴛʟᴇ A–Z",
        "size": "Bᴀᴅɪ Fɪʟᴇ Pᴇʜʟᴇ",
    }
    if len(parts) == 2:
        buttons = [[
            InlineKeyboardButton(label, callback_data=f"sort#{userid}#{sort_by}")
        ] for sort_by, label in options.items()]
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
        except MessageNotModified:
            pass
        await query.answer()
        return

    if len(parts) != 3 or parts[2] not in options:
        return await query.answer("Sᴏʀᴛ ᴏᴘᴛɪᴏɴ ᴄʜᴜɴᴏ 😏", show_alert=True)

    key = f"{query.message.chat.id}-{query.message.id}"
    search = BUTTONS.get(key) or temp.KEYWORD.get(query.from_user.id)
    if not search:
        return await query.answer("Pᴇʜʟᴇ ᴍᴏᴠɪᴇ sᴇᴀʀᴄʜ ᴋᴀʀᴏ 😏", show_alert=True)
    sort_by = parts[2]
    files, next_offset, total_results = await get_search_results(
        query.message.chat.id, search, offset=0, filter=True, sort_by=sort_by,
        filters=SEARCH_FILTERS.get(key, {}),
    )
    if not files:
        return await query.answer("Kᴏɪ ғɪʟᴇ ɴᴀʜɪ ᴍɪʟɪ 😏", show_alert=True)

    settings = await get_settings(query.message.chat.id)
    temp.GETALL[key] = files
    temp.CHAT[query.from_user.id] = query.message.chat.id
    BUTTONS[key] = search
    RESULT_SORTS[key] = sort_by
    buttons = _build_search_keyboard(
        files,
        userid,
        key,
        next_offset,
        total_results,
        settings,
        sponsor_button=await get_sponsor_button(),
    )
    try:
        await _update_search_results_message(query, settings, files, search, total_results, buttons)
    except MessageNotModified:
        pass
    await query.answer()

@Client.on_callback_query(filters.regex(r"^lusifilms#"))
async def quality_check(bot, query):
    try:
        curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        _, userid, quality = query.data.split("#")
        if int(userid) not in [query.from_user.id, 0]:
            return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
        if quality == "unknown":
            return await query.answer()
        if await is_resolution_locked(quality) and not await db.has_premium_access(query.from_user.id):
            return await query.answer(
                text=_get_resolution_lock_message(query.from_user.id, quality),
                show_alert=True,
            )
        result_key, movie, search_filters = _get_search_filter_context(query)
        if not movie:
            return await query.answer("Pehle movie search karo jaan 😘", show_alert=True)
        if quality == "home":
            search_filters.pop("quality", None)
        else:
            search_filters["quality"] = quality
        SEARCH_FILTERS[result_key] = search_filters
        files, offset, total_results = await get_search_results(
            query.message.chat.id, movie, offset=0, filter=True,
            sort_by=RESULT_SORTS.get(result_key, "season"),
            filters=search_filters,
        )
        if files:
            settings = await get_settings(query.message.chat.id)
            key = f"{query.message.chat.id}-{query.message.id}"
            BUTTONS[key] = movie
            temp.GETALL[key] = files
            temp.CHAT[query.from_user.id] = query.message.chat.id
            if not settings['button']:
                btn = [
                    [
                        InlineKeyboardButton(
                            text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'files#{file.file_id}'
                        ),
                    ]
                    for file in files
                ]
                btn.insert(0, [
                    InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            else:
                btn = []
                btn.insert(0, [
                    InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            _append_year_sort_controls(btn, userid)
            if offset != "":
                BUTTONS[key] = movie
                req = userid
                try:
                    if settings['max_btn']:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
    
                    else:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/int(MAX_B_TN))}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
                except KeyError:
                    await save_group_settings(query.message.chat.id, 'max_btn', True)
                    btn.append(
                        [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                    )
            else:
                btn.append(
                    [InlineKeyboardButton(text="𝐍𝐎 𝐌𝐎𝐑𝐄 𝐏𝐀𝐆𝐄𝐒 𝐀𝐕𝐀𝐈𝐋𝐀𝐁𝐋𝐄",callback_data="pages")]
                )
            if settings.get("button", SINGLE_BUTTON):
                cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
                time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
                remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
                cap = await get_text(settings, remaining_seconds, files, query, total_results, movie)
                try:
                    await _update_search_results_message(
                        query, settings, files, movie, total_results, btn, caption=cap
                    )
                except MessageNotModified:
                    pass
            else:
                try:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
                except MessageNotModified:
                    pass
            await query.answer()
        else:
            await _update_no_search_results_message(query)
            return await query.answer()
    except Exception as e:
        logger.exception("Quality filter callback failed")
        return await query.answer("Search error aa gaya jaan, thodi der baad try karo.", show_alert=True)

@Client.on_callback_query(filters.regex(r"^quality#"))
async def select_quality(bot, query):
    _, userid = query.data.split("#")
    if int(userid) not in [query.from_user.id, 0]:
        return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
    resolution_lock = await db.get_setting("RESOLUTION_LOCK", default=True)
    lock_labels = resolution_lock and not await db.has_premium_access(query.from_user.id)

    def quality_label(quality):
        return f"🔒 {quality} VIP" if lock_labels else quality
    btn = [[
        InlineKeyboardButton("Sᴇʟᴇᴄᴛ Yᴏᴜʀ Dᴇꜱɪʀᴇᴅ Qᴜᴀʟɪᴛʏꜱ ↓", callback_data=f"lusifilms#{userid}#unknown")
    ],[
        InlineKeyboardButton("480p", callback_data=f"lusifilms#{userid}#480p"),
        InlineKeyboardButton("720p", callback_data=f"lusifilms#{userid}#720p")
    ],[
        InlineKeyboardButton(quality_label("1080p"), callback_data=f"lusifilms#{userid}#1080p"),
        InlineKeyboardButton(quality_label("1080p HQ"), callback_data=f"lusifilms#{userid}#1080p HQ")
    ],[
        InlineKeyboardButton(quality_label("1440p"), callback_data=f"lusifilms#{userid}#1440p"),
        InlineKeyboardButton(quality_label("2160p"), callback_data=f"lusifilms#{userid}#2160p")
    ],[
        InlineKeyboardButton("Gᴏ Bᴀᴄᴋ", callback_data=f"lusifilms#{userid}#home")
    ]]
    try:
       await query.edit_message_reply_markup(
           reply_markup=InlineKeyboardMarkup(btn)
       )
    except MessageNotModified:
        pass
    await query.answer()
    
@Client.on_callback_query(filters.regex(r"^seasons#"))
async def seasons_check(bot, query):
    try:
        curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        _, userid, seasons = query.data.split("#")
        if int(userid) not in [query.from_user.id, 0]:
            return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
        if seasons == "unknown":
            return await query.answer()
        result_key, movie, search_filters = _get_search_filter_context(query)
        if not movie:
            return await query.answer("Pehle movie search karo jaan 😘", show_alert=True)
        if seasons == "home":
            search_filters.pop("season", None)
        else:
            search_filters["season"] = seasons
        SEARCH_FILTERS[result_key] = search_filters
        files, offset, total_results = await get_search_results(
            query.message.chat.id, movie, offset=0, filter=True,
            sort_by=RESULT_SORTS.get(result_key, "season"),
            filters=search_filters,
        )
        if files:
            settings = await get_settings(query.message.chat.id)
            key = f"{query.message.chat.id}-{query.message.id}"
            BUTTONS[key] = movie
            temp.GETALL[key] = files
            temp.CHAT[query.from_user.id] = query.message.chat.id
            if not settings['button']:
                btn = [
                    [
                        InlineKeyboardButton(
                            text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'files#{file.file_id}'
                        ),
                    ]
                    for file in files
                ]
                btn.insert(0, [
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            else:
                btn = []
                btn.insert(0, [
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            _append_year_sort_controls(btn, userid)
            if offset != "":
                BUTTONS[key] = movie
                req = userid
                try:
                    if settings['max_btn']:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
    
                    else:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/int(MAX_B_TN))}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
                except KeyError:
                    await save_group_settings(query.message.chat.id, 'max_btn', True)
                    btn.append(
                        [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                    )
            else:
                btn.append(
                    [InlineKeyboardButton(text="𝐍𝐎 𝐌𝐎𝐑𝐄 𝐏𝐀𝐆𝐄𝐒 𝐀𝐕𝐀𝐈𝐋𝐀𝐁𝐋𝐄",callback_data="pages")]
                )
            if settings.get("button", SINGLE_BUTTON):
                cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
                time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
                remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
                cap = await get_text(settings, remaining_seconds, files, query, total_results, movie)
                try:
                    await _update_search_results_message(
                        query, settings, files, movie, total_results, btn, caption=cap
                    )
                except MessageNotModified:
                    pass
            else:
                try:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
                except MessageNotModified:
                    pass
            await query.answer()
        else:
            await _update_no_search_results_message(query)
            return await query.answer()
    except Exception as e:
        logger.exception("Season filter callback failed")
        return await query.answer("Search error aa gaya jaan, thodi der baad try karo.", show_alert=True)

@Client.on_callback_query(filters.regex(r"^seas#"))
async def select_seasons(bot, query):
    _, userid = query.data.split("#")
    if int(userid) not in [query.from_user.id, 0]:
        return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
    btn = [[
        InlineKeyboardButton("Sᴇʟᴇᴄᴛ Yᴏᴜʀ Dᴇꜱɪʀᴇᴅ Sᴇᴀꜱᴏɴꜱ ↓", callback_data=f"seasons#{userid}#unknown")
    ],[
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟷", callback_data=f"seasons#{userid}#s01"),
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟸", callback_data=f"seasons#{userid}#s02")
    ],[
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟹", callback_data=f"seasons#{userid}#s03"),
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟺", callback_data=f"seasons#{userid}#s04")
    ],[
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟻", callback_data=f"seasons#{userid}#s05"),
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟼", callback_data=f"seasons#{userid}#s06")
    ],[
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟽", callback_data=f"seasons#{userid}#s07"),
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟾", callback_data=f"seasons#{userid}#s08")
    ],[
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟿", callback_data=f"seasons#{userid}#s09"),
        InlineKeyboardButton("Sᴇᴀꜱᴏɴ 𝟷𝟶", callback_data=f"seasons#{userid}#s10")
    ],[
        InlineKeyboardButton("Gᴏ Bᴀᴄᴋ", callback_data=f"seasons#{userid}#home")
    ]]
    try:
       await query.edit_message_reply_markup(
           reply_markup=InlineKeyboardMarkup(btn)
       )
    except MessageNotModified:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^episode#"))
async def episode_check(bot, query):
    try:
        curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        _, userid, episode = query.data.split("#")
        if int(userid) not in [query.from_user.id, 0]:
            return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
        if episode == "unknown":
            return await query.answer()
        result_key, movie, search_filters = _get_search_filter_context(query)
        if not movie:
            return await query.answer("Pehle movie search karo jaan 😘", show_alert=True)
        if episode == "home":
            search_filters.pop("episode", None)
        else:
            search_filters["episode"] = episode
        SEARCH_FILTERS[result_key] = search_filters
        files, offset, total_results = await get_search_results(
            query.message.chat.id, movie, offset=0, filter=True,
            sort_by=RESULT_SORTS.get(result_key, "season"),
            filters=search_filters,
        )
        if files:
            settings = await get_settings(query.message.chat.id)
            key = f"{query.message.chat.id}-{query.message.id}"
            BUTTONS[key] = movie
            temp.GETALL[key] = files
            temp.CHAT[query.from_user.id] = query.message.chat.id
            if not settings['button']:
                btn = [
                    [
                        InlineKeyboardButton(
                            text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'files#{file.file_id}'
                        ),
                    ]
                    for file in files
                ]
                btn.insert(0, [
                    InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            else:
                btn = []
                btn.insert(0, [
                    InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{userid}"), 
                    InlineKeyboardButton("! Sᴇʟᴇᴄᴛ Aɢᴀɪɴ !", callback_data=f"epi#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"select_lang#{userid}"),
                    InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{userid}")
                ])
                btn.insert(0, [
                    InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}")
                ])
            _append_year_sort_controls(btn, userid)
            if offset != "":
                BUTTONS[key] = movie
                req = userid
                try:
                    if settings['max_btn']:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
    
                    else:
                        btn.append(
                            [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/int(MAX_B_TN))}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                        )
                except KeyError:
                    await save_group_settings(query.message.chat.id, 'max_btn', True)
                    btn.append(
                        [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                    )
            else:
                btn.append(
                    [InlineKeyboardButton(text="𝐍𝐎 𝐌𝐎𝐑𝐄 𝐏𝐀𝐆𝐄𝐒 𝐀𝐕𝐀𝐈𝐋𝐀𝐁𝐋𝐄",callback_data="pages")]
                )
            if settings.get("button", SINGLE_BUTTON):
                cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
                time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
                remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
                cap = await get_text(settings, remaining_seconds, files, query, total_results, movie)
                try:
                    await _update_search_results_message(
                        query, settings, files, movie, total_results, btn, caption=cap
                    )
                except MessageNotModified:
                    pass
            else:
                try:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
                except MessageNotModified:
                    pass
            await query.answer()
        else:
            await _update_no_search_results_message(query)
            return await query.answer()
    except Exception as e:
        logger.exception("Episode filter callback failed")
        return await query.answer("Search error aa gaya jaan, thodi der baad try karo.", show_alert=True)
            
@Client.on_callback_query(filters.regex(r"^epi2#"))
async def select_episode2(bot, query):
    _, userid = query.data.split("#")
    if int(userid) not in [query.from_user.id, 0]:
        return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
    btn = [[
        InlineKeyboardButton("Sᴇʟᴇᴄᴛ Yᴏᴜʀ Dᴇꜱɪʀᴇᴅ Eᴘɪsᴏᴅᴇs ↓", callback_data=f"episode#{userid}#unknown")
    ],[
         InlineKeyboardButton("ᴇᴘ 𝟷𝟼", callback_data=f"episode#{userid}#e16"),
        InlineKeyboardButton("ᴇᴘ 𝟷𝟽", callback_data=f"episode#{userid}#e17"), 
        InlineKeyboardButton("ᴇᴘ 𝟷𝟾", callback_data=f"episode#{userid}#e18"), 
        InlineKeyboardButton("ᴇᴘ 𝟷𝟿", callback_data=f"episode#{userid}#e19"), 
        InlineKeyboardButton("ᴇᴘ 𝟸𝟶", callback_data=f"episode#{userid}#e20")
    ],[
        InlineKeyboardButton("ᴇᴘ 𝟸𝟷", callback_data=f"episode#{userid}#e21"),
        InlineKeyboardButton("ᴇᴘ 𝟸𝟸", callback_data=f"episode#{userid}#e22"), 
        InlineKeyboardButton("ᴇᴘ 𝟸𝟹", callback_data=f"episode#{userid}#e23"), 
        InlineKeyboardButton("ᴇᴘ 𝟸𝟺", callback_data=f"episode#{userid}#e24"), 
        InlineKeyboardButton("ᴇᴘ 𝟸𝟻", callback_data=f"episode#{userid}#e25")
    ],[
        InlineKeyboardButton("ᴇᴘ 𝟸𝟼", callback_data=f"episode#{userid}#e26"),
        InlineKeyboardButton("ᴇᴘ 𝟸𝟽", callback_data=f"episode#{userid}#e27"), 
        InlineKeyboardButton("ᴇᴘ 𝟸𝟾", callback_data=f"episode#{userid}#e28"), 
        InlineKeyboardButton("ᴇᴘ 𝟸𝟿", callback_data=f"episode#{userid}#e29"), 
        InlineKeyboardButton("ᴇᴘ 𝟹𝟶", callback_data=f"episode#{userid}#e30")
    ],[
        InlineKeyboardButton("⥢ Bᴀᴄᴋ", callback_data=f"epi#{userid}"), 
        InlineKeyboardButton("≪Bᴀᴄᴋ ᴛᴏ Hᴏᴍᴇ≫", callback_data=f"episode#{userid}#home"),
    ]]
    try:
       await query.edit_message_reply_markup(
           reply_markup=InlineKeyboardMarkup(btn)
       )
    except MessageNotModified:
        pass
    await query.answer()
    
@Client.on_callback_query(filters.regex(r"^epi#"))
async def select_episode(bot, query):
    _, userid = query.data.split("#")
    if int(userid) not in [query.from_user.id, 0]:
        return await query.answer(get_search_button_popup_message(query.from_user.id), show_alert=True)
    btn = [[
        InlineKeyboardButton("Sᴇʟᴇᴄᴛ Yᴏᴜʀ Dᴇꜱɪʀᴇᴅ Eᴘɪsᴏᴅᴇs ↓", callback_data=f"episode#{userid}#unknown")
    ],[
        InlineKeyboardButton("ᴇᴘ 𝟷", callback_data=f"episode#{userid}#e01"),
        InlineKeyboardButton("ᴇᴘ 𝟸", callback_data=f"episode#{userid}#e02"), 
        InlineKeyboardButton("ᴇᴘ 𝟹", callback_data=f"episode#{userid}#e03"), 
        InlineKeyboardButton("ᴇᴘ 𝟺", callback_data=f"episode#{userid}#e04"), 
        InlineKeyboardButton("ᴇᴘ 𝟻", callback_data=f"episode#{userid}#e05")
    ],[
        InlineKeyboardButton("ᴇᴘ 𝟼", callback_data=f"episode#{userid}#e06"),
        InlineKeyboardButton("ᴇᴘ 𝟽", callback_data=f"episode#{userid}#e07"), 
        InlineKeyboardButton("ᴇᴘ 𝟾", callback_data=f"episode#{userid}#e08"), 
        InlineKeyboardButton("ᴇᴘ 𝟿", callback_data=f"episode#{userid}#e09"), 
        InlineKeyboardButton("ᴇᴘ 𝟷𝟶", callback_data=f"episode#{userid}#e10")
    ],[
        InlineKeyboardButton("ᴇᴘ 𝟷𝟷", callback_data=f"episode#{userid}#e11"),
        InlineKeyboardButton("ᴇᴘ 𝟷𝟸", callback_data=f"episode#{userid}#e12"), 
        InlineKeyboardButton("ᴇᴘ 𝟷𝟹", callback_data=f"episode#{userid}#e13"), 
        InlineKeyboardButton("ᴇᴘ 𝟷𝟺", callback_data=f"episode#{userid}#e14"), 
        InlineKeyboardButton("ᴇᴘ 𝟷𝟻", callback_data=f"episode#{userid}#e15")
    ],[
        InlineKeyboardButton("⥢ Bᴀᴄᴋ", callback_data=f"episode#{userid}#home"),
        InlineKeyboardButton("ɴᴇxᴛ ➮", callback_data=f"epi2#{userid}"),
    ]]
    try:
       await query.edit_message_reply_markup(
           reply_markup=InlineKeyboardMarkup(btn)
       )
    except MessageNotModified:
        pass
    await query.answer()

@Client.on_callback_query(filters.regex(r"^spol"))
async def pm_spoll_choker(bot, query):
    _, id, user = query.data.split('#')
    if int(user) != 0 and query.from_user.id != int(user):
        return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
    movie = await get_poster(id, id=True)
    search = movie.get('title')
    await query.answer('ᴄʜᴇᴄᴋɪɴɢ ɪɴ ᴍʏ ᴅᴀᴛᴀʙᴀꜱᴇ 🌚')
    files, offset, total_results = await get_search_results(query.message.chat.id, search)
    if files:
        k = (search, files, offset, total_results)
        await auto_filter(bot, query, k)
    else:
        try:
            reqstr1 = query.from_user.id if query.from_user else 0
            reqstr = await bot.get_users(reqstr1)
            if NO_RESULTS_MSG:
                Lootere = [[
                    InlineKeyboardButton('ɴᴏᴛ ʀᴇʟᴇᴀsᴇ 📅', callback_data=f"not_release:{reqstr1}:{search}"),
                    InlineKeyboardButton('ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ 🙅', callback_data=f"not_available:{reqstr1}:{search}")
                ],[
                    InlineKeyboardButton('ᴜᴘʟᴏᴀᴅᴇᴅ ✅', callback_data=f"uploaded:{reqstr1}:{search}")
                ],[
                    InlineKeyboardButton('ɪɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ🙅', callback_data=f"series:{reqstr1}:{search}"),
                    InlineKeyboardButton('sᴇʟʟ ᴍɪsᴛᴇᴋ✍️', callback_data=f"spelling_error:{reqstr1}:{search}")
                ],[
                    InlineKeyboardButton('⁉️ Close ⁉️', callback_data=f"close_data")
                ]]
                reply_markup = InlineKeyboardMarkup(Lootere)
                total=await bot.get_chat_members_count(query.message.chat.id)
                await bot.send_message(chat_id=LOG_CHANNEL, text=(script.NORSLTS.format(query.message.chat.title, query.message.chat.id, total, temp.B_NAME, reqstr.mention, search)), reply_markup=InlineKeyboardMarkup(Lootere))
            k = await query.message.edit(script.MVE_NT_FND)
            await asyncio.sleep(60)
            await k.delete()
            try:
                await query.message.reply_to_message.delete()
            except:
                pass
        except Exception as e:
            reqstr1 = query.from_user.id if query.from_user else 0
            reqstr = await bot.get_users(reqstr1)
            if NO_RESULTS_MSG:
                Lootere = [[
                    InlineKeyboardButton('ɴᴏᴛ ʀᴇʟᴇᴀsᴇ 📅', callback_data=f"not_release:{reqstr1}:{search}"),
                    InlineKeyboardButton('ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ 🙅', callback_data=f"not_available:{reqstr1}:{search}")
                ],[
                    InlineKeyboardButton('ᴜᴘʟᴏᴀᴅᴇᴅ ✅', callback_data=f"uploaded:{reqstr1}:{search}")
                ],[
                    InlineKeyboardButton('ɪɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ🙅', callback_data=f"series:{reqstr1}:{search}"),
                    InlineKeyboardButton('sᴇʟʟ ᴍɪsᴛᴇᴋ✍️', callback_data=f"spelling_error:{reqstr1}:{search}")
                ],[
                    InlineKeyboardButton('⦉ ᴄʟᴏsᴇ ⦊️', callback_data=f"close_data")
                ]]
                reply_markup = InlineKeyboardMarkup(Lootere)
                await bot.send_message(chat_id=LOG_CHANNEL, text=(script.PMNORSLTS.format(temp.B_NAME, reqstr.mention, search)), reply_markup=InlineKeyboardMarkup(Lootere))
            k = await query.message.edit(script.MVE_NT_FND)
            await asyncio.sleep(60)
            await k.delete()
            try:
                await query.message.reply_to_message.delete()
            except:
                pass

@Client.on_callback_query(filters.regex(r"^search_suggestion#"))
async def search_suggestion_callback(bot, query):
    answered = False
    try:
        _, owner_id, token = query.data.split("#", 2)
        owner_id = int(owner_id)
        if owner_id != query.from_user.id:
            return await query.answer(
                get_search_button_popup_message(query.from_user.id),
                show_alert=True,
            )

        suggestion = SEARCH_SUGGESTIONS.get(token)
        if not suggestion or suggestion[0] != owner_id:
            return await query.answer(
                "Aww jaan, ye suggestion expire ho gayi. Dobara search karo ❤️",
                show_alert=True,
            )
        _, chat_id, title, created_at = suggestion
        if query.message.chat.id != chat_id:
            return await query.answer(
                get_search_button_popup_message(query.from_user.id),
                show_alert=True,
            )
        if monotonic() - created_at > SEARCH_SUGGESTION_TTL:
            SEARCH_SUGGESTIONS.pop(token, None)
            return await query.answer(
                "Aww jaan, ye suggestion expire ho gayi. Dobara search karo ❤️",
                show_alert=True,
            )
        if not query.message.reply_to_message:
            return await query.answer(
                "Oops jaan, original search nahi mili. Dobara try karo ❤️",
                show_alert=True,
            )
        SEARCH_SUGGESTIONS.pop(token, None)

        files, offset, total_results = await get_search_results(
            chat_id,
            title,
            offset=0,
            filter=True,
        )
        if not files:
            return await query.answer(
                "Aww jaan, is naam ki file abhi nahi mili 🥺",
                show_alert=True,
            )
        await query.answer()
        answered = True
        await auto_filter(bot, query, (title, files, offset, total_results))
    except Exception:
        logger.exception(
            "Indexed title suggestion callback failed (chat_id=%s, user_id=%s)",
            getattr(getattr(query, "message", None), "chat", None).id
            if getattr(getattr(query, "message", None), "chat", None)
            else None,
            getattr(getattr(query, "from_user", None), "id", None),
        )
        if not answered:
            return await query.answer(
                "Aww jaan, search mein dikkat aa gayi. Dobara try karo ❤️",
                show_alert=True,
            )

@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    data = query.data
    if query.data == "close_data":
        await query.message.delete()
    
    elif "groupcb" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        act = query.data.split(":")[2]
        hr = await client.get_chat(int(group_id))
        title = hr.title
        user_id = query.from_user.id

        if act == "":
            stat = "CONNECT"
            cb = "connectcb"
        else:
            stat = "DISCONNECT"
            cb = "disconnect"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{stat}", callback_data=f"{cb}:{group_id}"),
             InlineKeyboardButton("DELETE", callback_data=f"deletecb:{group_id}")],
            [InlineKeyboardButton("BACK", callback_data="backcb")]
        ])

        await query.message.edit_text(
            f"Gʀᴏᴜᴘ Nᴀᴍᴇ : **{title}**\nGʀᴏᴜᴘ ID : `{group_id}`",
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return await query.answer(MSG_ALRT)
    elif "connectcb" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        hr = await client.get_chat(int(group_id))

        title = hr.title

        user_id = query.from_user.id

        mkact = await make_active(str(user_id), str(group_id))

        if mkact:
            await query.message.edit_text(
                f"Cᴏɴɴᴇᴄᴛᴇᴅ ᴛᴏ **{title}**",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            await query.message.edit_text('Sᴏᴍᴇ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ!!', parse_mode=enums.ParseMode.MARKDOWN)
        return await query.answer(MSG_ALRT)
    elif "disconnect" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        hr = await client.get_chat(int(group_id))

        title = hr.title
        user_id = query.from_user.id

        mkinact = await make_inactive(str(user_id))

        if mkinact:
            await query.message.edit_text(
                f"Dɪsᴄᴏɴɴᴇᴄᴛᴇᴅ ғʀᴏᴍ **{title}**",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            await query.message.edit_text(
                f"Sᴏᴍᴇ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ!!",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        return await query.answer(MSG_ALRT)
    elif "deletecb" in query.data:
        await query.answer()

        user_id = query.from_user.id
        group_id = query.data.split(":")[1]

        delcon = await delete_connection(str(user_id), str(group_id))

        if delcon:
            await query.message.edit_text(
                "Sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ᴄᴏɴɴᴇᴄᴛɪᴏɴ !"
            )
        else:
            await query.message.edit_text(
                f"Sᴏᴍᴇ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ!!",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        return await query.answer(MSG_ALRT)
    elif query.data == "backcb":
        await query.answer()

        userid = query.from_user.id

        groupids = await all_connections(str(userid))
        if groupids is None:
            await query.message.edit_text(
                "Tʜᴇʀᴇ ᴀʀᴇ ɴᴏ ᴀᴄᴛɪᴠᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴs!! Cᴏɴɴᴇᴄᴛ ᴛᴏ sᴏᴍᴇ ɢʀᴏᴜᴘs ғɪʀsᴛ.",
            )
            return await query.answer(MSG_ALRT)
        buttons = []
        for groupid in groupids:
            try:
                ttl = await client.get_chat(int(groupid))
                title = ttl.title
                active = await if_active(str(userid), str(groupid))
                act = " - ACTIVE" if active else ""
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"{title}{act}", callback_data=f"groupcb:{groupid}:{act}"
                        )
                    ]
                )
            except:
                pass
        if buttons:
            await query.message.edit_text(
                "Yᴏᴜʀ ᴄᴏɴɴᴇᴄᴛᴇᴅ ɢʀᴏᴜᴘ ᴅᴇᴛᴀɪʟs ;\n\n",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
    
    elif "alertmessage" in query.data:
        grp_id = query.message.chat.id
        i = query.data.split(":")[1]
        keyword = query.data.split(":")[2]
        reply_text, btn, alerts, fileid = await find_filter(grp_id, keyword)
        if alerts is not None:
            alerts = ast.literal_eval(alerts)
            alert = alerts[int(i)]
            alert = alert.replace("\\n", "\n").replace("\\t", "\t")
            await query.answer(alert, show_alert=True)
            
    elif query.data.startswith("files"):
        ident, file_id = query.data.split("#")
        user = query.message.reply_to_message.from_user.id
        if int(user) != 0 and query.from_user.id != int(user):
            return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        await query.answer(url=f"https://t.me/{temp.U_NAME}?start=files_{query.message.chat.id}_{file_id}")
                 
            
    elif query.data.startswith("sendfiles"):
        if not await db.has_premium_access(query.from_user.id):
            return await query.answer(get_vip_lock_message(query.from_user.id), show_alert=True)
        clicked = query.from_user.id
        ident, key = query.data.split("#") 
        settings = await get_settings(query.message.chat.id)
        try:
            await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=allfiles_{query.message.chat.id}_{key}")
            return
        except UserIsBlocked:
            await query.answer('Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴍᴀʜɴ !', show_alert=True)
        except PeerIdInvalid:
            await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles3_{key}")
        except Exception as e:
            logger.exception(e)
            await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles4_{key}")
            
            
    elif query.data == "pages":
        await query.answer()

    elif query.data.startswith("killfilesdq"):
        ident, keyword = query.data.split("#")
        await query.message.edit_text(f"<b>Fᴇᴛᴄʜɪɴɢ Fɪʟᴇs ғᴏʀ ʏᴏᴜʀ ᴏ̨ᴜᴇʀʏ {keyword} ᴏɴ DB... Pʟᴇᴀsᴇ ᴡᴀɪᴛ...</b>")
        files, total = await get_bad_files(keyword)
        await query.message.edit_text(f"<b>Fᴏᴜɴᴅ {total} Fɪʟᴇs ғᴏʀ ʏᴏᴜʀ ᴏ̨ᴜᴇʀʏ {keyword} !\n\nFɪʟᴇ ᴅᴇʟᴇᴛɪᴏɴ ᴘʀᴏᴄᴇss ᴡɪʟʟ sᴛᴀʀᴛ ɪɴ 5 sᴇᴄᴏɴᴅs!</b>")
        await asyncio.sleep(5)
        deleted = 0
        async with lock:
            try:
                for file in files:
                    file_ids = file.file_id
                    file_name = file.file_name
                    result = await Media.collection.delete_one({
                        '_id': file_ids,
                    })
                    if result.deleted_count:
                        logger.info(f'Fɪʟᴇ Fᴏᴜɴᴅ ғᴏʀ ʏᴏᴜʀ ᴏ̨ᴜᴇʀʏ {keyword}! Sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ {file_name} ғʀᴏᴍ ᴅᴀᴛᴀʙᴀsᴇ.')
                    deleted += 1
                    if deleted % 20 == 0:
                        await query.message.edit_text(f"<b>Pʀᴏᴄᴇss sᴛᴀʀᴛᴇᴅ ғᴏʀ ᴅᴇʟᴇᴛɪɴɢ ғɪʟᴇs ғʀᴏᴍ DB. Sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ {str(deleted)} ғɪʟᴇs ғʀᴏᴍ DB ғᴏʀ ʏᴏᴜʀ ᴏ̨ᴜᴇʀʏ {keyword} !\n\nPʟᴇᴀsᴇ ᴡᴀɪᴛ...</b>")
            except Exception as e:
                logger.exception(e)
                await query.message.edit_text(f'Eʀʀᴏʀ: {e}')
            else:
                await query.message.edit_text(f"<b>Pʀᴏᴄᴇss Cᴏᴍᴘʟᴇᴛᴇᴅ ғᴏʀ ғɪʟᴇ ᴅᴇʟᴇᴛɪᴏɴ !\n\nSᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ {str(deleted)} ғɪʟᴇs ғʀᴏᴍ DB ғᴏʀ ʏᴏᴜʀ ᴏ̨ᴜᴇʀʏ {keyword}.</b>")
    
    elif query.data.startswith("reset_grp_data"):
        grp_id = query.message.chat.id
        btn = [[
            InlineKeyboardButton('✂️ ᴄʟᴏsᴇ ✂️️', callback_data='close_data')
        ]]
        reply_markup=InlineKeyboardMarkup(btn)
        await save_group_settings(grp_id, 'verify', VERIFY_URL)
        await save_group_settings(grp_id, 'verify_api', VERIFY_API)
        await save_group_settings(grp_id, 'verify_2', VERIFY_URL2)
        await save_group_settings(grp_id, 'verify_api2', VERIFY_API2)
        await save_group_settings(grp_id, 'verify_3',  VERIFY_URL3)
        await save_group_settings(grp_id, 'verify_api3', VERIFY_API3)
        await save_group_settings(grp_id, 'verify_time', TWO_VERIFY_GAP)
        await save_group_settings(grp_id, 'verify_time2', THIRD_VERIFY_GAP)
        await save_group_settings(grp_id, 'template', IMDB_TEMPLATE)
        await save_group_settings(grp_id, 'tutorial', TUTORIAL)
        await save_group_settings(grp_id, 'tutorial2', TUTORIAL2)
        await save_group_settings(grp_id, 'tutorial3', TUTORIAL3)
        await save_group_settings(grp_id, 'caption', CUSTOM_FILE_CAPTION)
        await save_group_settings(grp_id, 'fsub_id', AUTH_CHANNEL)
        await save_group_settings(grp_id, 'log', LOG_CHANNEL)
        await save_group_settings(grp_id, 'file_limit', FILE_LIMITE)
        await save_group_settings(grp_id, 'streamapi', STREAM_API)
        await save_group_settings(grp_id, 'streamsite', STREAM_SITE)
        await save_group_settings(grp_id, 'all_limit', SEND_ALL_LIMITE)

        await query.answer('ꜱᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ʀᴇꜱᴇᴛ...')
        await query.message.edit_text("<b>ꜱᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ʀᴇꜱᴇᴛ ɢʀᴏᴜᴘ ꜱᴇᴛᴛɪɴɢꜱ...\n\nɴᴏᴡ ꜱᴇɴᴅ /details ᴀɢᴀɪɴ</b>", reply_markup=reply_markup)

    elif query.data.startswith("opnsetgrp"):
        ident, grp_id = query.data.split("#")
        userid = query.from_user.id if query.from_user else None
        st = await client.get_chat_member(grp_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
                and str(userid) not in ADMINS
        ):
            await query.answer("Yᴏᴜ Dᴏɴ'ᴛ Hᴀᴠᴇ Tʜᴇ Rɪɢʜᴛs Tᴏ Dᴏ Tʜɪs !", show_alert=True)
            return
        title = query.message.chat.title
        settings = await get_settings(grp_id)
        if settings is not None:
            buttons = [
                [
                    InlineKeyboardButton('Rᴇꜱᴜʟᴛ Pᴀɢᴇ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}'),
                    InlineKeyboardButton('Tᴇxᴛ' if settings["button"] else 'Bᴜᴛᴛᴏɴ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Iᴍᴅʙ', callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["imdb"] else '✘ Oғғ',
                                         callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["spell_check"] else '✘ Oғғ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ Msɢ', callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["welcome"] else '✘ Oғғ',
                                         callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ',
                                         callback_data=f'setgs#auto_delete_menu#0#{str(grp_id)}'),
                    InlineKeyboardButton(get_auto_delete_label(settings),
                                         callback_data=f'setgs#auto_delete_menu#0#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Aᴜᴛᴏ-Fɪʟᴛᴇʀ',
                                         callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["auto_ffilter"] else '✘ Oғғ',
                                         callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Mᴀx Bᴜᴛᴛᴏɴs',
                                         callback_data=f'setgs#max_btn#{settings["max_btn"]}#{str(grp_id)}'),
                    InlineKeyboardButton('10' if settings["max_btn"] else f'{MAX_B_TN}',
                                         callback_data=f'setgs#max_btn#{settings["max_btn"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Fɪʟᴇ Lɪᴍɪᴛ', 
                                        callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}'),
                    InlineKeyboardButton('ᴏɴ ✔️' if settings.get("filelock", LIMIT_MODE) else 'ᴏғғ ✗', 
                                        callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}')
                ],
                [  
                     InlineKeyboardButton('Sᴛʀᴇᴀᴍ Sʜᴏʀᴛ', 
                                        callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}'),
                    InlineKeyboardButton('✔ Oɴ' if settings.get("stream_mode", STREAM_MODE) else '✘ Oғғ', 
                                        callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}')
                ], 
                [
                    InlineKeyboardButton('Vᴇʀɪғʏ', 
                                        callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}'), 
                    InlineKeyboardButton('✔ Oɴ' if settings.get("is_verify", IS_VERIFY) else '✘ Oғғ', 
                                        callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.message.edit_text(
                text=f"<b>Cʜᴀɴɢᴇ Yᴏᴜʀ Sᴇᴛᴛɪɴɢs Fᴏʀ {title} As Yᴏᴜʀ Wɪsʜ ⚙</b>",
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
            await query.message.edit_reply_markup(reply_markup)
        
    elif query.data.startswith("opnsetpm"):
        ident, grp_id = query.data.split("#")
        userid = query.from_user.id if query.from_user else None
        st = await client.get_chat_member(grp_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
                and str(userid) not in ADMINS
        ):
            await query.answer("Yᴏᴜ Dᴏɴ'ᴛ Hᴀᴠᴇ Tʜᴇ Rɪɢʜᴛs Tᴏ Dᴏ Tʜɪs !", show_alert=True)
            return
        title = query.message.chat.title
        settings = await get_settings(grp_id)
        btn2 = [[
                 InlineKeyboardButton("Cʜᴇᴄᴋ PM", url=f"t.me/{temp.U_NAME}")
               ]]
        reply_markup = InlineKeyboardMarkup(btn2)
        await query.message.edit_text(f"<b>Yᴏᴜʀ sᴇᴛᴛɪɴɢs ᴍᴇɴᴜ ғᴏʀ {title} ʜᴀs ʙᴇᴇɴ sᴇɴᴛ ᴛᴏ ʏᴏᴜʀ PM</b>")
        await query.message.edit_reply_markup(reply_markup)
        if settings is not None:
            buttons = [
                [
                    InlineKeyboardButton('Rᴇꜱᴜʟᴛ Pᴀɢᴇ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}'),
                    InlineKeyboardButton('Tᴇxᴛ' if settings["button"] else 'Bᴜᴛᴛᴏɴ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Iᴍᴅʙ', callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["imdb"] else '✘ Oғғ',
                                         callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["spell_check"] else '✘ Oғғ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ Msɢ', callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["welcome"] else '✘ Oғғ',
                                         callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ',
                                         callback_data=f'setgs#auto_delete_menu#0#{str(grp_id)}'),
                    InlineKeyboardButton(get_auto_delete_label(settings),
                                         callback_data=f'setgs#auto_delete_menu#0#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Aᴜᴛᴏ-Fɪʟᴛᴇʀ',
                                         callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["auto_ffilter"] else '✘ Oғғ',
                                         callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Mᴀx Bᴜᴛᴛᴏɴs',
                                         callback_data=f'setgs#max_btn#{settings["max_btn"]}#{str(grp_id)}'),
                    InlineKeyboardButton('10' if settings["max_btn"] else f'{MAX_B_TN}',
                                         callback_data=f'setgs#max_btn#{settings["max_btn"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Fɪʟᴇ Lɪᴍɪᴛ', 
                                        callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}'),
                    InlineKeyboardButton('ᴏɴ ✔️' if settings.get("filelock", LIMIT_MODE) else 'ᴏғғ ✗', 
                                        callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}')
                ],
                [  
                     InlineKeyboardButton('Sᴛʀᴇᴀᴍ Sʜᴏʀᴛ', 
                                        callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}'),
                    InlineKeyboardButton('✔ Oɴ' if settings.get("stream_mode", STREAM_MODE) else '✘ Oғғ', 
                                        callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}')
                ], 
                [
                    InlineKeyboardButton('Vᴇʀɪғʏ', 
                                        callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}'), 
                    InlineKeyboardButton('✔ Oɴ' if settings.get("is_verify", IS_VERIFY) else '✘ Oғғ', 
                                        callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            await client.send_message(
                chat_id=userid,
                text=f"<b>Cʜᴀɴɢᴇ Yᴏᴜʀ Sᴇᴛᴛɪɴɢs Fᴏʀ {title} As Yᴏᴜʀ Wɪsʜ ⚙</b>",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
                reply_to_message_id=query.message.id
            )
    elif query.data == "start":
        buttons = [[
                    InlineKeyboardButton('☆ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ☆', url=f'http://telegram.me/{temp.U_NAME}?startgroup=true')
                ],[
                    InlineKeyboardButton('✪ ᴜᴘᴅᴀᴛᴇꜱ ✪', callback_data='channels'), 
                    InlineKeyboardButton('⚔️ғᴇᴀᴛᴜʀᴇs ⚔️', callback_data='features')
                ],[
                    InlineKeyboardButton('🍀 Hᴇʟᴘ 🍀', callback_data='help'),
                    InlineKeyboardButton('🤖 ᴀʙᴏᴜᴛ 🤖', callback_data='about')
                ],[
                    InlineKeyboardButton('🆓 ᴘʀᴇᴍɪᴜᴍ ✨', callback_data="pm_reff"),
                    InlineKeyboardButton('✨ ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ ✨', callback_data="premium_info")
                 ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await client.edit_message_media(
            query.message.chat.id, 
            query.message.id, 
            InputMediaPhoto(random.choice(PICS), has_spoiler=True)
        )
        await query.message.edit_text(
            text=script.START_TXT.format(query.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        await query.answer(MSG_ALRT)
        
    elif query.data == 'features':
        buttons = [[
            InlineKeyboardButton('⋞ ʙᴀᴄᴋ', callback_data='start')
        ]] 
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(                     
            text=script.FEATURES,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "show_pm":
        user_id = query.from_user.id
        total_referrals = sdb.get_refer_points(user_id)
        await query.answer(text=f'You Have: {total_referrals} Refferal Points', show_alert=True)
        
    elif query.data == "pm_reff":
        try:
            user_id = query.from_user.id
            total_referrals = sdb.get_refer_points(user_id)
            buttons = [[
                InlineKeyboardButton('Invite 🔗', url=f'https://t.me/share/url?url=%E0%A4%AF%E0%A5%87%20Bot%20%E0%A4%9F%E0%A5%87%E0%A4%B2%E0%A5%80%E0%A4%97%E0%A5%8D%E0%A4%B0%E0%A4%BE%E0%A4%AE%20%E0%A4%AA%E0%A4%B0%20%20%E0%A4%B8%E0%A4%AC%E0%A4%B8%E0%A5%87%20%E0%A4%AA%E0%A4%B9%E0%A4%B2%E0%A5%87%20%E0%A4%AE%E0%A5%82%E0%A4%B5%E0%A5%80%20%E0%A4%94%E0%A4%B0%20%E0%A4%B8%E0%A5%80%E0%A4%B0%E0%A5%80%E0%A4%9C%20%E0%A4%85%E0%A4%AA%E0%A4%B2%E0%A5%8B%E0%A4%A1%20%E0%A4%95%E0%A4%B0%20%E0%A4%A6%E0%A5%87%E0%A4%A4%E0%A4%BE%20%E0%A4%B9%E0%A5%88%20%0A%0A%E0%A4%85%E0%A4%97%E0%A4%B0%20%E0%A4%86%E0%A4%AA%20%E0%A4%AD%E0%A5%80%20%E0%A4%AE%E0%A5%82%E0%A4%B5%E0%A5%80%20%E0%A4%94%E0%A4%B0%20%E0%A4%B8%E0%A5%80%E0%A4%B0%E0%A5%80%E0%A4%9C%20%E0%A4%A6%E0%A5%87%E0%A4%96%E0%A4%A8%E0%A5%87%20%E0%A4%95%E0%A4%BE%20%E0%A4%B6%E0%A5%8C%E0%A4%95%20%E0%A4%B0%E0%A4%96%E0%A4%A4%E0%A5%87%20%E0%A4%B9%E0%A5%88%20%E0%A4%A4%E0%A5%8B%20%E0%A4%87%E0%A4%B8%20Bot%20%E0%A4%95%E0%A5%8B%20%E0%A4%B8%E0%A5%8D%E0%A4%9F%E0%A4%BE%E0%A4%B0%E0%A5%8D%E0%A4%9F%20%E0%A4%95%E0%A4%B0%E0%A5%87%E0%A4%82%0A%0ALink%3Dhttps://t.me/{temp.U_NAME}?start=reff_{user_id}'), 
                InlineKeyboardButton(text=f'⏳{total_referrals}', callback_data=f"show_pm"), 
                InlineKeyboardButton('⇚Back', callback_data='start')
            ]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await client.edit_message_media(
                query.message.chat.id, 
                query.message.id, 
                InputMediaPhoto(REFFER_PIC)
            )
            await query.message.edit_text(
                text=script.REFFER_TXT.format(temp.U_NAME, user_id),
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
        except Exception as e:
            await query.answer(f"{e}", show_alert=True)
                    
    elif query.data.startswith("not_available"):
        _, user_id, movie = data.split(":")
        try:
            Lootere = [[
                    InlineKeyboardButton(text=f"🗑 Delete Log ❌", callback_data = "close_data")
                    ]]
            reply_markup = InlineKeyboardMarkup(Lootere)
            await client.send_message(int(user_id), script.NOT_AVAILABLE_TXT.format(movie),parse_mode=enums.ParseMode.HTML)
            msg=await query.edit_message_text(text=f"Mᴇꜱꜱᴀɢᴇ Sᴇɴᴅ Sᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ✅\n\n⏳ꜱᴛᴀᴛᴜꜱ : Nᴏᴛ Aᴠᴀɪʟᴀʙʟᴇ 😒.\n🪪ᴜꜱᴇʀɪᴅ : `{user_id}`\n🎞ᴄᴏɴᴛᴇɴᴛ : `{movie}`", reply_markup=InlineKeyboardMarkup(Lootere))
        except Exception as e:
            print(e)
            await query.answer(f"{e}", show_alert=True)
            return
    elif data.startswith("uploaded"):
        _, user_id, movie = data.split(":")
        try:
            Lootere = [[
                    InlineKeyboardButton(text=f"🗑 Delete Log ❌", callback_data = "close_data")
                    ]]
            reply_markup = InlineKeyboardMarkup(Lootere)
            await client.send_message(int(user_id), script.UPLOADED_TXT.format(movie),parse_mode=enums.ParseMode.HTML)
            msg=await query.edit_message_text(text=f"Mᴇꜱꜱᴀɢᴇ Sᴇɴᴅ Sᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ✅\n\n⏳ꜱᴛᴀᴛᴜꜱ : Uᴘʟᴏᴀᴅᴇᴅ 🎊.\n🪪ᴜꜱᴇʀɪᴅ : `{user_id}`\n🎞ᴄᴏɴᴛᴇɴᴛ : `{movie}`", reply_markup=InlineKeyboardMarkup(Lootere))
        except Exception as e:
            print(e)
            await query.answer(f"{e}", show_alert=True)
            return
    elif data.startswith("not_release"):
        _, user_id, movie = data.split(":")
        try:
            Lootere = [[
                    InlineKeyboardButton(text=f"🗑 Delete Log ❌", callback_data = "close_data")
                    ]]
            reply_markup = InlineKeyboardMarkup(Lootere)
            await client.send_message(int(user_id), script.NOT_RELEASE_TXT.format(movie),parse_mode=enums.ParseMode.HTML)
            msg=await query.edit_message_text(text=f"Mᴇꜱꜱᴀɢᴇ Sᴇɴᴅ Sᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ✅\n\n⏳ꜱᴛᴀᴛᴜꜱ : ɴᴏᴛ ʀᴇʟᴇᴀsᴇ 🙅.\n🪪ᴜꜱᴇʀɪᴅ : `{user_id}`\n🎞ᴄᴏɴᴛᴇɴᴛ : `{movie}`", reply_markup=InlineKeyboardMarkup(Lootere))
        except Exception as e:
            print(e)
            await query.answer(f"{e}", show_alert=True)
            return
    elif data.startswith("spelling_error"):
        _, user_id, movie = data.split(":")
        try:
            Lootere = [[
                    InlineKeyboardButton(text=f"🗑 Delete Log ❌", callback_data = "close_data")
                    ]]
            reply_markup = InlineKeyboardMarkup(Lootere)
            await client.send_message(int(user_id), script.SPELL_TXT.format(movie),parse_mode=enums.ParseMode.HTML)
            msg=await query.edit_message_text(text=f"Mᴇꜱꜱᴀɢᴇ Sᴇɴᴅ Sᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ✅\n\n⏳ꜱᴛᴀᴛᴜꜱ : Sᴘᴇʟʟɪɴɢ Eʀʀᴏʀ 🕵️.\n🪪ᴜꜱᴇʀɪᴅ : `{user_id}`\n🎞ᴄᴏɴᴛᴇɴᴛ : `{movie}`", reply_markup=InlineKeyboardMarkup(Lootere))
        except Exception as e:
            print(e)
            await query.answer(f"{e}", show_alert=True)
            return
    elif data.startswith("series"):
        _, user_id, movie = data.split(":")
        try:
            Lootere = [[
                    InlineKeyboardButton(text=f"🗑 Delete Log ❌", callback_data = "close_data")
                    ]]
            reply_markup = InlineKeyboardMarkup(Lootere)
            await client.send_message(int(user_id), script.SERIES_FORMAT_TXT.format(movie),parse_mode=enums.ParseMode.HTML)
            msg=await query.edit_message_text(text=f"Mᴇꜱꜱᴀɢᴇ Sᴇɴᴅ Sᴜᴄᴄᴇꜱꜱғᴜʟʟʏ ✅\n\n⏳ꜱᴛᴀᴛᴜꜱ : Sᴇʀɪᴇs Eʀʀᴏʀ 🕵️.\n🪪ᴜꜱᴇʀɪᴅ : `{user_id}`\n🎞ᴄᴏɴᴛᴇɴᴛ : `{movie}`", reply_markup=InlineKeyboardMarkup(Lootere))
        except Exception as e:
            print(e) 
            await query.answer(f"{e}", show_alert=True)
            return
        
    elif query.data == "premium_info":
        buttons = [[
            InlineKeyboardButton('🔲 Qʀ', callback_data='qr_info'),
            InlineKeyboardButton('💳 Uᴘɪ', callback_data='upi_info')
        ],[
            InlineKeyboardButton('🚫 ᴄʟᴏꜱᴇ 🚫', callback_data='close_data')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.reply_photo(
            photo=(PREMIUM_PIC),
            caption=script.PREMIUM_CMD,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        
    elif query.data == "qr_info":
        buttons = [[
            InlineKeyboardButton('📸sᴇɴᴅ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ📸', url=f'https://t.me/{OWNER_USER_NAME}')
        ], [
            InlineKeyboardButton('🚫 ᴄʟᴏꜱᴇ 🚫', callback_data='close_data')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.reply_photo(QR_CODE, caption=script.QR_TXT, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)

    elif query.data == "upi_info":
        buttons = [[
            InlineKeyboardButton('📸sᴇɴᴅ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ📸', url=f'https://t.me/{OWNER_USER_NAME}')
        ], [
            InlineKeyboardButton('🚫 ᴄʟᴏꜱᴇ 🚫', callback_data='close_data')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.reply_text(script.UPI_TXT, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        
    elif query.data == "give_trial":
        user_id = query.from_user.id        
        await db.give_free_trial(user_id)
        await query.message.reply_text(
            text="ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ᴀᴅᴅᴇᴅ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀ ✨ ғᴏʀ 5 ᴍɪɴᴜᴛᴇs\n\nɴᴏᴡ ʏᴏᴜ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ғɪʟᴇs ᴡɪᴛʜᴏᴜᴛ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ\n\nsᴇᴇ ʏᴏᴜʀ ᴘʟᴀɴ /myplan",
            disable_web_page_preview=True
        )
        await query.message.delete()
        return    

  
    elif query.data == "channels":
        buttons = [[
            InlineKeyboardButton('Uᴘᴅᴀᴛᴇꜱ Cʜᴀɴɴᴇʟ', url=CHNL_LNK)
        ],[
            InlineKeyboardButton('⇇ ʙᴀᴄᴋ', callback_data='start')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.CHANNELS.format(query.from_user.mention),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "users":
        buttons = [[
            InlineKeyboardButton('⇋ ʙᴀᴄᴋ ⇋', callback_data='help')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.USERS_TXT,
            reply_markup=reply_markup, 
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "group":
        buttons = [[
            InlineKeyboardButton('⇋ ʙᴀᴄᴋ ⇋', callback_data='help')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.GROUP_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "admic":
        if query.from_user.id not in ADMINS:
            return await query.answer("⚠️ ʏᴏᴜ'ʀᴇ ɴᴏᴛ ᴀ ʙᴏᴛ ᴀᴅᴍɪɴ !", show_alert=True)        
        buttons = [[
            InlineKeyboardButton('⬅︎ ʙᴀᴄᴋ', callback_data='help'), 
            InlineKeyboardButton('ɴᴇxᴛ ➡︎', callback_data='admic2')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await client.edit_message_media(
            query.message.chat.id, 
            query.message.id, 
            InputMediaPhoto(random.choice(PICS), has_spoiler=True)
        )
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.ADMIC_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        
    elif query.data == "admic2":
        buttons = [[
            InlineKeyboardButton('⬅︎ ʙᴀᴄᴋ', callback_data='admic')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await client.edit_message_media(
            query.message.chat.id, 
            query.message.id, 
            InputMediaPhoto(random.choice(PICS), has_spoiler=True)
        )
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.ADMIC_TEX2T,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "help":
        buttons = [[
            InlineKeyboardButton('ᴀᴅᴍɪɴ - ᴄᴏᴍᴍᴀɴᴅꜱ', callback_data='admic')
        ], [
            InlineKeyboardButton('ᴜꜱᴇʀ - ᴄᴏᴍᴍᴀɴᴅꜱ', callback_data='users'),
            InlineKeyboardButton('ɢʀᴏᴜᴘ - ᴄᴏᴍᴍᴀɴᴅꜱ', callback_data='group')
        ], [
            InlineKeyboardButton('⇋ ʙᴀᴄᴋ ᴛᴏ ʜᴏᴍᴇ ⇋', callback_data='start')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await client.edit_message_media(
            query.message.chat.id, 
            query.message.id, 
            InputMediaPhoto(random.choice(PICS), has_spoiler=True)
        )
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.HELP_TXT.format(query.from_user.mention),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "about":
        buttons = [[
            InlineKeyboardButton('‼️ ᴅɪꜱᴄʟᴀɪᴍᴇʀ ‼️', callback_data='disclaimer'),
        ], [
            InlineKeyboardButton('⇋ ʙᴀᴄᴋ ᴛᴏ ʜᴏᴍᴇ ⇋', callback_data='start')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await client.edit_message_media(
            query.message.chat.id, 
            query.message.id, 
            InputMediaPhoto(random.choice(PICS), has_spoiler=True)
        )
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.ABOUT_TXT.format(temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )

    
    elif query.data == "disclaimer":
            btn = [[
                    InlineKeyboardButton("⇋ ʙᴀᴄᴋ ⇋", callback_data="about")
                  ]]
            reply_markup = InlineKeyboardMarkup(btn)
            await query.message.edit_text(
                text=(script.DISCLAIMER_TXT),
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML 
            )
    elif query.data == "stats":
        if query.from_user.id not in ADMINS:
            return await query.answer("⚠️ ʏᴏᴜ'ʀᴇ ɴᴏᴛ ᴀ ʙᴏᴛ ᴀᴅᴍɪɴ !", show_alert=True) 
        buttons = [[
            InlineKeyboardButton('⟸ Bᴀᴄᴋ', callback_data='start'),
            InlineKeyboardButton('⟲ Rᴇғʀᴇsʜ', callback_data='rfrsh')
        ]]
        await client.edit_message_media(
            query.message.chat.id, 
            query.message.id, 
            InputMediaPhoto(random.choice(PICS), has_spoiler=True)
        )
        reply_markup = InlineKeyboardMarkup(buttons)
        total = await Media.count_documents()
        users = await db.total_users_count()
        chats = await db.total_chat_count()
        monsize = await db.get_db_size()
        free = 536870912 - monsize
        monsize = get_size(monsize)
        free = get_size(free)
        await query.message.edit_text(
            text=script.STATUS_TXT.format(total, users, chats, monsize, free),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "rfrsh":
        await query.answer("Fetching MongoDb DataBase")
        buttons = [[
            InlineKeyboardButton('⟸ Bᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('⟲ Rᴇғʀᴇsʜ', callback_data='rfrsh')
        ]]
        await client.edit_message_media(
            query.message.chat.id, 
            query.message.id, 
            InputMediaPhoto(random.choice(PICS), has_spoiler=True)
        )
        reply_markup = InlineKeyboardMarkup(buttons)
        total = await Media.count_documents()
        users = await db.total_users_count()
        chats = await db.total_chat_count()
        monsize = await db.get_db_size()
        free = 536870912 - monsize
        monsize = get_size(monsize)
        free = get_size(free)
        await query.message.edit_text(
            text=script.STATUS_TXT.format(total, users, chats, monsize, free),
            reply_markup=reply_markup,
            
            parse_mode=enums.ParseMode.HTML
        )
    

    elif query.data.startswith("setgs"):
        ident, set_type, status, grp_id = query.data.split("#")
        grpid = await active_connection(str(query.from_user.id))

        if str(grp_id) != str(grpid) and query.from_user.id not in ADMINS:
            await query.message.edit("Yᴏᴜʀ Aᴄᴛɪᴠᴇ Cᴏɴɴᴇᴄᴛɪᴏɴ Hᴀs Bᴇᴇɴ Cʜᴀɴɢᴇᴅ. Gᴏ Tᴏ /connections ᴀɴᴅ ᴄʜᴀɴɢᴇ ʏᴏᴜʀ ᴀᴄᴛɪᴠᴇ ᴄᴏɴɴᴇᴄᴛɪᴏɴ.")
            return await query.answer(MSG_ALRT)

        if set_type == "auto_delete_menu":
            rows = []
            option_buttons = []
            for seconds, label in AUTO_DELETE_OPTIONS:
                option_buttons.append(
                    InlineKeyboardButton(
                        label,
                        callback_data=f"setgs#auto_delete_time#{seconds}#{grp_id}",
                    )
                )
                if len(option_buttons) == 2:
                    rows.append(option_buttons)
                    option_buttons = []
            if option_buttons:
                rows.append(option_buttons)
            rows.append([
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=f"setgs#auto_delete_back#0#{grp_id}",
                )
            ])
            await query.message.edit_reply_markup(InlineKeyboardMarkup(rows))
            return await query.answer()
        elif set_type == "auto_delete_time":
            try:
                seconds = int(status)
            except ValueError:
                return await query.answer("Invalid auto-delete timer.", show_alert=True)
            if seconds not in dict(AUTO_DELETE_OPTIONS):
                return await query.answer("Invalid auto-delete timer.", show_alert=True)
            await save_group_settings(grpid, "auto_delete_time", seconds)
            await save_group_settings(grpid, "auto_delete", bool(seconds))
        elif set_type == "auto_delete":
            enabled = status == "False"
            seconds = 600 if enabled else 0
            await save_group_settings(grpid, "auto_delete_time", seconds)
            await save_group_settings(grpid, "auto_delete", enabled)
        elif set_type != "auto_delete_back":
            await save_group_settings(grpid, set_type, status != "True")

        settings = await get_settings(grpid)

        if settings is not None:
            buttons = [
                [
                    InlineKeyboardButton('Rᴇꜱᴜʟᴛ Pᴀɢᴇ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}'),
                    InlineKeyboardButton('Tᴇxᴛ' if settings["button"] else 'Bᴜᴛᴛᴏɴ',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Iᴍᴅʙ', callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["imdb"] else '✘ Oғғ',
                                         callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Sᴘᴇʟʟ Cʜᴇᴄᴋ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["spell_check"] else '✘ Oғғ',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Wᴇʟᴄᴏᴍᴇ Msɢ', callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["welcome"] else '✘ Oғғ',
                                         callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ',
                                         callback_data=f'setgs#auto_delete_menu#0#{str(grp_id)}'),
                    InlineKeyboardButton(get_auto_delete_label(settings),
                                         callback_data=f'setgs#auto_delete_menu#0#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Aᴜᴛᴏ-Fɪʟᴛᴇʀ',
                                         callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✔ Oɴ' if settings["auto_ffilter"] else '✘ Oғғ',
                                         callback_data=f'setgs#auto_ffilter#{settings["auto_ffilter"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Mᴀx Bᴜᴛᴛᴏɴs',
                                         callback_data=f'setgs#max_btn#{settings["max_btn"]}#{str(grp_id)}'),
                    InlineKeyboardButton('10' if settings["max_btn"] else f'{MAX_B_TN}',
                                         callback_data=f'setgs#max_btn#{settings["max_btn"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Fɪʟᴇ Lɪᴍɪᴛ', 
                                        callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}'),
                    InlineKeyboardButton('ᴏɴ ✔️' if settings.get("filelock", LIMIT_MODE) else 'ᴏғғ ✗', 
                                        callback_data=f'setgs#filelock#{settings.get("filelock", LIMIT_MODE)}#{grp_id}')
                ], 
                [
                    InlineKeyboardButton('Sᴛʀᴇᴀᴍ Sʜᴏʀᴛ', 
                                        callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}'),
                    InlineKeyboardButton('✔ Oɴ' if settings.get("stream_mode", STREAM_MODE) else '✘ Oғғ', 
                                        callback_data=f'setgs#stream_mode#{settings.get("stream_mode", STREAM_MODE)}#{grp_id}')
                ], 
                [
                    InlineKeyboardButton('Vᴇʀɪғʏ', 
                                        callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}'), 
                    InlineKeyboardButton('✔ Oɴ' if settings.get("is_verify", IS_VERIFY) else '✘ Oғғ', 
                                        callback_data=f'setgs#is_verify#{settings.get("is_verify", IS_VERIFY)}#{grp_id}')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.message.edit_reply_markup(reply_markup)
    await query.answer(MSG_ALRT)

async def ai_spell_check(chat_id, wrong_name):
    try:  
        async def search_movie(wrong_name):
            search_results = imdb.search_movie(wrong_name)
            movie_list = [movie['title'] for movie in search_results]
            return movie_list
        movie_list = await search_movie(wrong_name)
        if not movie_list:
            return
        for _ in range(5):
            closest_match = process.extractOne(wrong_name, movie_list)
            if not closest_match or closest_match[1] <= 80:
                return 
            movie = closest_match[0]
            files, offset, total_results = await get_search_results(chat_id=chat_id, query=movie)
            if files:
                return movie
            movie_list.remove(movie)
        return
    except Exception as e:
        print('Got error while searching movie in ai_spell_check', e)
        
async def auto_filter(
    client,
    msg,
    spoll=False,
    preserve_search_message=False,
):
    message = msg.message.reply_to_message if spoll else msg
    pending_message = None
    stage = "preparing search"
    search_query = None
    try:
        curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        if not spoll:
            if message.text.startswith("/"): return  # ignore commands
            if re.findall(r"((^/|^,|^!|^\.|^[\U0001F600-\U000E007F]).*)", message.text):
                return
            if len(message.text) < 100:
                search = message.text
                stage = "sending search status"
                m=await message.reply_sticker(sticker="CAACAgIAAxkBAAEVugJljpdfkszexOUZu8hPjuPKty8ZmAACdxgAAqPjKEmMVSFmXGLogR4E",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🅿︎🅻︎🅴︎🅰︎🆂︎🅴︎  🆆︎🅰︎🅸︎🆃︎", url=CHNL_LNK)]]))
                pending_message = m
                search = search.lower()
                find = search.split(" ")
                search = ""
                removes = ["in","upload", "series", "full", "horror", "thriller", "mystery", "print", "file", "send", "chahiye", "chiye", "movi", "movie", "bhejo", "dijiye", "jaldi", "hd", "bollywood", "hollywood", "south", "karo"]
                for x in find:
                    if x in removes:
                        continue
                    else:
                        search = search + x + " "
                search = re.sub(r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|bro|bruh|broh|helo|that|find|dubbed|link|venum|iruka|pannunga|pannungga|anuppunga|anupunga|anuppungga|anupungga|film|undo|kitti|kitty|tharu|kittumo|kittum|movie|any(one)|with\ssubtitle(s)?)", "", search, flags=re.IGNORECASE)
                search = re.sub(r"\s+", " ", search).strip()
                search = search.replace("-", " ")
                search = search.replace(":","")
                search_query = search
                stage = "searching MongoDB"
                files, offset, total_results = await get_search_results(message.chat.id ,search, offset=0, filter=True)
                stage = "loading chat settings"
                settings = await get_settings(message.chat.id)
                if not files:
                    await m.delete()
                    pending_message = None
                    if settings.get("spell_check", SPELL_CHECK_REPLY):
                        stage = "searching indexed title suggestions"
                        fuzzy_suggestions = await get_search_suggestions(search)
                        if fuzzy_suggestions:
                            best_match = fuzzy_suggestions[0]
                            if best_match["score"] >= 78:
                                corrected_files, corrected_offset, corrected_total = (
                                    await get_search_results(
                                        message.chat.id,
                                        best_match["title"],
                                        offset=0,
                                        filter=True,
                                    )
                                )
                                if corrected_files:
                                    original_text = msg.text
                                    msg.text = best_match["title"]
                                    try:
                                        return await auto_filter(
                                            client,
                                            msg,
                                            preserve_search_message=True,
                                        )
                                    finally:
                                        msg.text = original_text

                            suggestion_buttons = _search_suggestion_buttons(
                                fuzzy_suggestions,
                                message.from_user.id,
                                message.chat.id,
                            )
                            await message.reply_text(
                                "Oops baby! Shayad tum ye movie dhoondh rahe ho 😉❤️",
                                reply_markup=InlineKeyboardMarkup(suggestion_buttons),
                                reply_to_message_id=message.id,
                            )
                            return

                        await message.reply_text(
                            get_flirty_interaction_message(
                                message.from_user.id, "no_results"
                            ),
                            reply_to_message_id=message.id,
                        )
                        return
                    else:
                        await message.reply_text(
                            get_flirty_interaction_message(
                                message.from_user.id, "no_results"
                            ),
                            reply_to_message_id=message.id,
                        )
                        return
            else:
                return
        else:
            message = msg.message.reply_to_message  # msg will be callback query
            search, files, offset, total_results = spoll[:4]
            search_query = search
            m=await message.reply_sticker(sticker="CAACAgIAAxkBAAEVugJljpdfkszexOUZu8hPjuPKty8ZmAACdxgAAqPjKEmMVSFmXGLogR4E",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🅿︎🅻︎🅴︎🅰︎🆂︎🅴︎  🆆︎🅰︎🅸︎🆃︎", url=CHNL_LNK)]]))
            settings = await get_settings(message.chat.id)
        pending_message = m
        stage = "building search results"
        key = f"{message.chat.id}-{message.id}"
        BUTTONS[key] = search
        SEARCH_FILTERS[key] = {}
        RESULT_SORTS[key] = "season"
        temp.GETALL[key] = files
        temp.CHAT[message.from_user.id] = message.chat.id
        temp.KEYWORD[message.from_user.id] = search
        if not settings.get("button", SINGLE_BUTTON):
            btn = [
                [
                    InlineKeyboardButton(
                        text=f"[{get_size(file.file_size)}] {file.file_name}", callback_data=f'files#{file.file_id}'
                    ),
                ]
                for file in files
            ]
            
            btn.insert(0, [
                InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{message.from_user.id}"), 
                InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{message.from_user.id}")
            ])
            btn.insert(0, [
                InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇs", callback_data=f"select_lang#{message.from_user.id}"),
                InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{message.from_user.id}"),
            ])
            btn.insert(0, [
                InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}"),
            ])
        else:
            btn = []
            btn.insert(0, [
                InlineKeyboardButton("Sᴇᴀꜱᴏɴꜱ", callback_data=f"seas#{message.from_user.id}"), 
                InlineKeyboardButton("Eᴘɪsᴏᴅᴇ", callback_data=f"epi#{message.from_user.id}")
            ])
            btn.insert(0, [
                InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇs", callback_data=f"select_lang#{message.from_user.id}"),
                InlineKeyboardButton("Qᴜᴀʟɪᴛʏꜱ", callback_data=f"quality#{message.from_user.id}"),
            ])
            btn.insert(0, [
                InlineKeyboardButton("VIP Send All", callback_data=f"sendfiles#{key}"),
            ])
        _append_year_sort_controls(btn, message.from_user.id)
        sponsor_button = await get_sponsor_button()
        if sponsor_button:
            btn.append([sponsor_button])
    
        if offset != "":
            key = f"{message.chat.id}-{message.id}"
            BUTTONS[key] = search
            req = message.from_user.id if message.from_user else 0
            try:
                if settings['max_btn']:
                    btn.append(
                        [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                    )
                else:
                    btn.append(
                        [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/int(MAX_B_TN))}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                    )
            except KeyError:
                await save_group_settings(message.chat.id, 'max_btn', True)
                btn.append(
                    [InlineKeyboardButton("𝐏𝐀𝐆𝐄", callback_data="pages"), InlineKeyboardButton(text=f"1/{math.ceil(int(total_results)/10)}",callback_data="pages"), InlineKeyboardButton(text="𝐍𝐄𝐗𝐓 ➪",callback_data=f"next_{req}_{key}_{offset}")]
                )
        else:
            btn.append(
                [InlineKeyboardButton(text="𝐍𝐎 𝐌𝐎𝐑𝐄 𝐏𝐀𝐆𝐄𝐒 𝐀𝐕𝐀𝐈𝐋𝐀𝐁𝐋𝐄",callback_data="pages")]
            )
        imdb = None
        if settings.get("imdb", IMDB):
            stage = "fetching optional IMDb details"
            try:
                imdb = await get_poster(search, file=files[0].file_name)
            except Exception:
                logger.exception("IMDb lookup failed; continuing with file search results")
        cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
        remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
        TEMPLATE = settings.get('template', IMDB_TEMPLATE)
        if imdb:
            format_values = {**imdb, **locals(), "query": search}
            try:
                cap = TEMPLATE.format(**format_values)
            except Exception:
                logger.exception("Configured IMDb template failed; using the built-in template")
                cap = script.IMDB_TEMPLATE_TXT.format(query=search, **imdb)
            temp.IMDB_CAP[message.from_user.id] = cap
            if settings.get("button", SINGLE_BUTTON):
                for file in files:
                    cap += f"<b>\n\n<a href='https://telegram.me/{temp.U_NAME}?start=files_{message.chat.id}_{file.file_id}'> 📁 {get_size(file.file_size)} ▷ {file.file_name}</a></b>"
        else:
            CAPTION = f"<b>☠️ ᴛɪᴛʟᴇ : <code>{search}</code>\n📂 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ : <code>{total_results}</code>\n📝 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : {message.from_user.first_name}\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds} Sᴇᴄᴏɴᴅs</code>\n\n📚 Your Requested Files 👇\n\n</b>"
            if not settings.get("button", SINGLE_BUTTON):
                cap = f"{CAPTION}"
            else:
                cap = f"{CAPTION}"
                for file in files:
                    cap += f"<b><a href='https://telegram.me/{temp.U_NAME}?start=files_{message.chat.id}_{file.file_id}'> 📁 {get_size(file.file_size)} ▷ {file.file_name}\n\n</a></b>"

        stage = "sending search results"
        if imdb and imdb.get('poster'):  
            try:
                hehe = await message.reply_photo(photo=imdb.get('poster'), caption=cap, reply_markup=InlineKeyboardMarkup(btn))
                await m.delete()
                pending_message = None
                auto_delete_seconds = get_auto_delete_seconds(settings)
                if auto_delete_seconds:
                    await asyncio.sleep(auto_delete_seconds)
                    await hehe.delete()
                    await message.delete()
            except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
                pic = imdb.get('poster')
                poster = pic.replace('.jpg', "._V1_UX360.jpg")
                hmm = await message.reply_photo(photo=poster, caption=cap, reply_markup=InlineKeyboardMarkup(btn))
                await m.delete()
                pending_message = None
                auto_delete_seconds = get_auto_delete_seconds(settings)
                if auto_delete_seconds:
                    await asyncio.sleep(auto_delete_seconds)
                    await hmm.delete()
                    await message.delete()
            except Exception as e:
                logger.exception(e)
                fek = await message.reply_text(text=cap, reply_markup=InlineKeyboardMarkup(btn))
                await m.delete()
                pending_message = None
                auto_delete_seconds = get_auto_delete_seconds(settings)
                if auto_delete_seconds:
                    await asyncio.sleep(auto_delete_seconds)
                    await fek.delete()
                    await message.delete()
        else:
            fuk = await message.reply_text(text=cap, reply_markup=InlineKeyboardMarkup(btn))
            if not preserve_search_message:
                await message.delete()
            await m.delete()
            pending_message = None
            auto_delete_seconds = get_auto_delete_seconds(settings)
            if auto_delete_seconds:
                await asyncio.sleep(auto_delete_seconds)
                await fuk.delete()
                await message.delete()
        if spoll:
            await msg.message.delete()
    except Exception:
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        logger.exception(
            "Auto-filter failed during %s (chat_id=%s, query=%r)",
            stage,
            chat_id,
            search_query,
        )
        if pending_message is not None:
            try:
                await pending_message.delete()
            except Exception:
                logger.warning("Could not remove the search status message", exc_info=True)
        try:
            await message.reply_text("Aww 😏 search mein dikkat aa gayi. Thodi der baad try karo.")
        except Exception:
            logger.exception("Could not send the search failure message")
        return

async def advantage_spell_chok(client, message):
    mv_id = message.id
    search = message.text
    chat_id = message.chat.id
    user = message.from_user.id
    settings = await get_settings(chat_id)
    find = search.split(" ")
    query = ""
    removes = ["in","upload", "series", "full", "horror", "thriller", "mystery", "print", "file", "send", "chahiye", "chiye", "movi", "movie", "bhejo", "dijiye", "jaldi", "hd", "bollywood", "hollywood", "south", "karo"]
    for x in find:
        if x in removes:
            continue
        else:
            query = query + x + " "
    query = re.sub(
        r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|br((o|u)h?)*|^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|file|that|find|und(o)*|kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|aya(k)*(um(o)*)?|full\smovie|any(one)|with\ssubtitle(s)?)",
        "", message.text, flags=re.IGNORECASE)
    query = query.strip() + " movie"
    try:
        movies = await get_poster(search, bulk=True)
    except Exception:
        logger.exception("IMDb spelling-suggestion lookup failed for query=%r", search)
        k = await message.reply_text(
            get_flirty_interaction_message(message.from_user.id, "no_results")
        )
        await asyncio.sleep(60)
        await k.delete()
        try:
            await message.delete()
        except:
            pass
        return
    if not movies:
        k = await message.reply_text(
            text=get_flirty_interaction_message(
                message.from_user.id, "no_results"
            ),
        )
        await asyncio.sleep(120)
        await k.delete()
        try:
            await message.delete()
        except:
            pass
        return
    user = message.from_user.id if message.from_user else 0
    buttons = [[
        InlineKeyboardButton(text=movie.get('title'), callback_data=f"spol#{movie.movieID}#{user}")
    ]
        for movie in movies
    ]
    buttons.append(
        [InlineKeyboardButton(text="🚫 ᴄʟᴏsᴇ 🚫", callback_data='close_data')]
    )
    d = await message.reply_text(text=script.CUDNT_FND.format(search), reply_markup=InlineKeyboardMarkup(buttons), reply_to_message_id=message.id)
    await asyncio.sleep(120)
    await d.delete()
    try:
        await message.delete()
    except:
        pass
                                     
# This code has been modified by Looteredev
# Please do not remove this credit
