# This code has been modified by @Looteredev
# Please do not remove this credit
import logging
from pyrogram.errors import InputUserDeactivated, UserNotParticipant, FloodWait, UserIsBlocked, PeerIdInvalid, ChatAdminRequired, MessageIdInvalid, EmoticonInvalid, ReactionInvalid
from info import *
from imdb import Cinemagoer 
import asyncio
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram import enums
from typing import Union
from Script import script
import pytz
import random 
from random import choice
from asyncio import sleep
import time
import re
import os
from datetime import datetime, timedelta, date, time
import string
from typing import List
from database.users_chats_db import db
from bs4 import BeautifulSoup
import requests
import aiohttp
from shortzy import Shortzy

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)

imdb = Cinemagoer()
BANNED = {}
SMART_OPEN = '“'
SMART_CLOSE = '”'
START_CHAR = ('\'', '"', SMART_OPEN)

# temp db for banned 
class temp(object):
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None
    CURRENT=int(os.environ.get("SKIP", 2))
    CANCEL = False
    MELCOW = {}
    U_NAME = None
    B_NAME = None
    SETTINGS = {}
    KEYWORD = {}
    GETALL = {}
    SPELL_CHECK = {}
    IMDB_CAP = {}
    CHAT = {}
    VIP_LOCK_MESSAGES = {}


VIP_LOCK_POPUP_MESSAGES = [
    "Ye sirf VIP ke liye hai 😉",
    "VIP ban jao bhai 😂",
    "Itni aasani se VIP access nahi milega 😎",
    "VIP membership le lo mere bhai ❤️",
    "Ye feature sirf khaas logon ke liye hai 🔥",
    "VIP nahi ho? Toh VIP ban jao 😁",
    "Free mein itna hi milega bhai 😂",
    "VIP users ke liye special treatment hai 👑",
    "Pehle VIP membership lo, phir maze karo 😜",
    "VIP club mein welcome hone ka time aa gaya 😎",
    "Ye button VIP members ke liye reserved hai 🔐",
    "Bhai VIP banne ka plan kab hai? 😂",
    "VIP access ke bina entry band hai 🚫",
    "Thoda VIP bano, phir try karo 😉",
    "VIP members are special ❤️",
]

SEARCH_BUTTON_POPUP_MESSAGES = [
    "Aww 😏 yeh search tumhari nahi hai, cutie.",
    "Oops baby 😂 apne search ke buttons dabao.",
    "Thoda sabr jaan 😜 yeh kisi aur ka result hai.",
    "Movie chahiye? Apni search bhejo 😉",
    "Yeh menu original requester ke liye hai 🔐",
    "Arey cutie, apne results par try karo 😘",
    "Request kisi aur ki hai, jaan 😅",
    "Apni movie search karo, phir maze 😉",
    "Wrong button, right cutie? 😏",
    "Aww, apni search se shuru karo ❤️",
]

VIP_LOCKED_RESOLUTION_PATTERN = re.compile(
    r"(?<!\d)(?:1080\s*p|1440\s*p|2160\s*p|4\s*k|uhd)(?!\w)",
    re.IGNORECASE,
)


def get_vip_lock_message(user_id):
    previous_message = temp.VIP_LOCK_MESSAGES.get(user_id)
    available_messages = [
        message for message in VIP_LOCK_POPUP_MESSAGES
        if message != previous_message
    ]
    message = random.choice(available_messages)
    temp.VIP_LOCK_MESSAGES[user_id] = message
    return message


def get_search_button_popup_message(user_id):
    previous_message = temp.VIP_LOCK_MESSAGES.get(("search", user_id))
    available_messages = [
        message for message in SEARCH_BUTTON_POPUP_MESSAGES
        if message != previous_message
    ]
    message = random.choice(available_messages)
    temp.VIP_LOCK_MESSAGES[("search", user_id)] = message
    return message


async def is_resolution_locked(value):
    if not await db.get_setting("RESOLUTION_LOCK", default=True):
        return False
    return bool(VIP_LOCKED_RESOLUTION_PATTERN.search(str(value or "")))


async def check_reset_time():
    tz = pytz.timezone('Asia/Kolkata')
    while True:
        now = datetime.now(tz)
        target_time = time(23, 59)
        target_datetime = tz.localize(datetime.combine(now.date(), target_time))
        if now > target_datetime:
            target_datetime += timedelta(days=1)
        time_diff = (target_datetime - now).total_seconds()
        hours = time_diff // 3600
        minutes = (time_diff % 3600) // 60
        seconds = time_diff % 60
        logging.info(f"Next reset in {int(hours)} hours, {int(minutes)} minutes, and {int(seconds)} seconds.")
        await asyncio.sleep(time_diff)
        await db.reset_all_files_count()
        await db.reset_allsend_files()
        logging.info("Files count and send count reset successfully")

async def get_seconds(time_string):
    def extract_value_and_unit(ts):
        value = ""
        unit = ""

        index = 0
        while index < len(ts) and ts[index].isdigit():
            value += ts[index]
            index += 1

        unit = ts[index:].lstrip()

        if value:
            value = int(value)

        return value, unit

    value, unit = extract_value_and_unit(time_string)

    if unit == 's':
        return value
    elif unit == 'min':
        return value * 60
    elif unit == 'hour':
        return value * 3600
    elif unit == 'day':
        return value * 86400
    elif unit == 'month':
        return value * 86400 * 30
    elif unit == 'year':
        return value * 86400 * 365
    else:
        return 0
        
async def is_req_subscribed(bot, query):
    if await db.find_join_req(query.from_user.id):
        return True
    try:
        user = await bot.get_chat_member(AUTH_CHANNEL, query.from_user.id)
    except UserNotParticipant:
        pass
    except Exception as e:
        print(e)
    else:
        if user.status != enums.ChatMemberStatus.BANNED:
            return True
    return False

async def is_subscribed(bot, user_id, channel_id):
    try:
        user = await bot.get_chat_member(channel_id, user_id)
    except UserNotParticipant:
        pass
    except Exception as e:
        pass
    else:
        if user.status != enums.ChatMemberStatus.BANNED:
            return True
    return False

async def get_poster(query, bulk=False, id=False, file=None):
    if not id:
        # https://t.me/GetTGLink/4183
        query = (query.strip()).lower()
        title = query
        year = re.findall(r'[1-2]\d{3}$', query, re.IGNORECASE)
        if year:
            year = list_to_str(year[:1])
            title = (query.replace(year, "")).strip()
        elif file is not None:
            year = re.findall(r'[1-2]\d{3}', file, re.IGNORECASE)
            if year:
                year = list_to_str(year[:1]) 
        else:
            year = None
        movieid = imdb.search_movie(title.lower(), results=10)
        if not movieid:
            return None
        if year:
            filtered=list(filter(lambda k: str(k.get('year')) == str(year), movieid))
            if not filtered:
                filtered = movieid
        else:
            filtered = movieid
        movieid=list(filter(lambda k: k.get('kind') in ['movie', 'tv series'], filtered))
        if not movieid:
            movieid = filtered
        if bulk:
            return movieid
        movieid = movieid[0].movieID
    else:
        movieid = query
    movie = imdb.get_movie(movieid)
    if movie.get("original air date"):
        date = movie["original air date"]
    elif movie.get("year"):
        date = movie.get("year")
    else:
        date = "N/A"
    plot = ""
    if not LONG_IMDB_DESCRIPTION:
        plot = movie.get('plot')
        if plot and len(plot) > 0:
            plot = plot[0]
    else:
        plot = movie.get('plot outline')
    if plot and len(plot) > 800:
        plot = plot[0:800] + "..."

    return {
        'title': movie.get('title'),
        'votes': movie.get('votes'),
        "aka": list_to_str(movie.get("akas")),
        "seasons": movie.get("number of seasons"),
        "box_office": movie.get('box office'),
        'localized_title': movie.get('localized title'),
        'kind': movie.get("kind"),
        "imdb_id": f"tt{movie.get('imdbID')}",
        "cast": list_to_str(movie.get("cast")),
        "runtime": list_to_str(movie.get("runtimes")),
        "countries": list_to_str(movie.get("countries")),
        "certificates": list_to_str(movie.get("certificates")),
        "languages": list_to_str(movie.get("languages")),
        "director": list_to_str(movie.get("director")),
        "writer":list_to_str(movie.get("writer")),
        "producer":list_to_str(movie.get("producer")),
        "composer":list_to_str(movie.get("composer")) ,
        "cinematographer":list_to_str(movie.get("cinematographer")),
        "music_team": list_to_str(movie.get("music department")),
        "distributors": list_to_str(movie.get("distributors")),
        'release_date': date,
        'year': movie.get('year'),
        'genres': list_to_str(movie.get("genres")),
        'poster': movie.get('full-size cover url'),
        'plot': plot,
        'rating': str(movie.get("rating")),
        'url':f'https://www.imdb.com/title/tt{movieid}'
    }
# https://github.com/odysseusmax/animated-lamp/blob/2ef4730eb2b5f0596ed6d03e7b05243d93e3415b/bot/utils/broadcast.py#L37

async def broadcast_messages(user_id, message):
    try:
        await message.copy(chat_id=user_id)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.x)
        return await broadcast_messages(user_id, message)
    except InputUserDeactivated:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id} - Removed from Database, since deleted account.")
        return False, "Deleted"
    except UserIsBlocked:
        logging.info(f"{user_id} - Blocked the bot.")
        return False, "Blocked"
    except PeerIdInvalid:
        await db.delete_user(int(user_id))
        logging.info(f"{user_id} - PeerIdInvalid")
        return False, "Error"
    except Exception as e:
        return False, "Error"

async def get_settings(group_id):
    settings = temp.SETTINGS.get(group_id)
    if not settings:
        settings = await db.get_settings(group_id)
        temp.SETTINGS[group_id] = settings
    return settings
    
async def save_group_settings(group_id, key, value):
    current = await get_settings(group_id)
    current[key] = value
    temp.SETTINGS[group_id] = current
    await db.update_settings(group_id, current)

def get_size(size):
    """Get size in readable format"""

    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units):
        i += 1
        size /= 1024.0
    return "%.2f %s" % (size, units[i])
    
def list_to_str(k): 
    if not k:
        return "N/A"
    elif len(k) == 1:
        return str(k[0])
    else:
        return ' '.join(f'{elem}, ' for elem in k)
        
def get_file_id(msg: Message):
    if msg.media:
        for message_type in (
            "photo",
            "animation",
            "audio",
            "document",
            "video",
            "video_note",
            "voice",
            "sticker"
        ):
            obj = getattr(msg, message_type)
            if obj:
                setattr(obj, "message_type", message_type)
                return obj

def extract_user(message: Message) -> Union[int, str]:
    """extracts the user from a message"""
    # https://github.com/SpEcHiDe/PyroGramBot/blob/f30e2cca12002121bad1982f68cd0ff9814ce027/pyrobot/helper_functions/extract_user.py#L7
    user_id = None
    user_first_name = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        user_first_name = message.reply_to_message.from_user.first_name

    elif len(message.command) > 1:
        if (
            len(message.entities) > 1 and
            message.entities[1].type == enums.MessageEntityType.TEXT_MENTION
        ):
           
            required_entity = message.entities[1]
            user_id = required_entity.user.id
            user_first_name = required_entity.user.first_name
        else:
            user_id = message.command[1]
            # don't want to make a request -_-
            user_first_name = user_id
        try:
            user_id = int(user_id)
        except ValueError:
            pass
    else:
        user_id = message.from_user.id
        user_first_name = message.from_user.first_name
    return (user_id, user_first_name)
         

async def stream_site(link, grp_id):
    try:
        settings = await get_settings(grp_id) if await get_settings(grp_id) else {}
        api_key, site_key = ('streamapi', 'streamsite')
        default_api, default_site = STREAM_API, STREAM_SITE
        
        api = settings.get(api_key, default_api)
        site = settings.get(site_key, default_site)

        shortzy = Shortzy(api, site)

        try:
            link = await shortzy.convert(link)
        except Exception:
            link = await shortzy.get_quick_link(link)
        return link
    except Exception as e:
        logger.error(e)

async def get_shortlink(link, grp_id, is_second_shortener=False, is_third_shortener=False):
    settings = await get_settings(grp_id) if await get_settings(grp_id) else {}
    if is_third_shortener:
        api_key, site_key = ('verify_api3', 'verify_3')
        default_api, default_site = VERIFY_API3, VERIFY_URL3
    elif is_second_shortener:
        api_key, site_key = ('verify_api2', 'verify_2')
        default_api, default_site = VERIFY_API2, VERIFY_URL2
    else:
        api_key, site_key = ('verify_api', 'verify')
        default_api, default_site = VERIFY_API, VERIFY_URL

    api = settings.get(api_key, default_api)
    site = settings.get(site_key, default_site)
    shortzy = Shortzy(api, site)
    try:
        link = await shortzy.convert(link)
    except Exception:
        link = await shortzy.get_quick_link(link)
    return link

async def get_users():
    count  = await user_col.count_documents({})
    cursor = user_col.find({})
    list   = await cursor.to_list(length=int(count))
    return count, list

async def get_text(settings, remaining_seconds, files, query, total_results, search):
    try:
        if settings["imdb"]:
            IMDB_CAP = temp.IMDB_CAP.get(query.from_user.id)
            CAPTION = f"☠️ ᴛɪᴛʟᴇ : <code>{search}</code>\n📂 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ : <code>{total_results}</code>\n📝 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : {query.from_user.first_name}\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds} Sᴇᴄᴏɴᴅs</code>\n\n</b>"
            if IMDB_CAP:
                cap = IMDB_CAP
                for file in files: #shortlink = false, imdb = true
                    cap += f"\n\n<b><a href='https://telegram.me/{temp.U_NAME}?start=files_{query.message.chat.id}_{file.file_id}'>📁 {get_size(file.file_size)} ▷ {file.file_name}</a></b>"
            else:
                imdb = await get_poster(search, file=(files[0]).file_name) if settings["imdb"] else None
                if imdb:
                    TEMPLATE = script.IMDB_TEMPLATE_TXT
                    cap = TEMPLATE.format(
                        qurey=search,
                        title=imdb['title'],
                        votes=imdb['votes'],
                        aka=imdb["aka"],
                        seasons=imdb["seasons"],
                        box_office=imdb['box_office'],
                        localized_title=imdb['localized_title'],
                        kind=imdb['kind'],
                        imdb_id=imdb["imdb_id"],
                        cast=imdb["cast"],
                        runtime=imdb["runtime"],
                        countries=imdb["countries"],
                        certificates=imdb["certificates"],
                        languages=imdb["languages"],
                        director=imdb["director"],
                        writer=imdb["writer"],
                        producer=imdb["producer"],
                        composer=imdb["composer"],
                        cinematographer=imdb["cinematographer"],
                        music_team=imdb["music_team"],
                        distributors=imdb["distributors"],
                        release_date=imdb['release_date'],
                        year=imdb['year'],
                        genres=imdb['genres'],
                        poster=imdb['poster'],
                        plot=imdb['plot'],
                        rating=imdb['rating'],
                        url=imdb['url'],
                        **locals()
                    )
                    for file in files:
                        cap += f"\n\n<b><a href='https://telegram.me/{temp.U_NAME}?start=files_{query.message.chat.id}_{file.file_id}'>📁 {get_size(file.file_size)} ▷ {file.file_name}</a></b>"
                else:
                    cap = f"{CAPTION}" #imdb = false
                    cap+="<b>📚 <u>Your Requested Files</u> 👇\n\n</b>"
                    for file in files:
                        cap += f"<b><a href='https://telegram.me/{temp.U_NAME}?start=files_{query.message.chat.id}_{file.file_id}'>📁 {get_size(file.file_size)} ▷ {file.file_name}\n\n</a></b>"
    
        else:
            #imdb = false
            cap = f"☠️ ᴛɪᴛʟᴇ : <code>{search}</code>\n📂 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ : <code>{total_results}</code>\n📝 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : {query.from_user.first_name}\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds}\n\n</b>"
            cap+="<b>📚 <u>Your Requested Files</u> 👇\n\n</b>"
            for file in files:
                cap += f"<b><a href='https://telegram.me/{temp.U_NAME}?start=files_{query.message.chat.id}_{file.file_id}'>📁 {get_size(file.file_size)} ▷ {file.file_name}\n\n</a></b>"
        return cap
    except Exception as e:
        await query.answer(f"{e}", show_alert=True)
        return cap
