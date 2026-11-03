# This code has been modified by @Looteredev
# Please do not remove this credit
import os
from pyrogram import Client, filters, enums
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant, MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from info import IMDB_TEMPLATE, TIMEZONE
from utils import extract_user, get_file_id, get_poster
import time
from datetime import date, datetime
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import logging
import pytz
from .custom_poster import fetch_custom_poster
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)


def _release_countdown_text(release_date, today=None):
    """Return a countdown only for a reliable, exact ISO release date."""
    try:
        release_day = date.fromisoformat(str(release_date))
    except (TypeError, ValueError):
        return None
    today = today or datetime.now(pytz.timezone(TIMEZONE)).date()
    days_remaining = (release_day - today).days
    if days_remaining < 0:
        return None
    if days_remaining == 0:
        return "⏳ <b>Releases today!</b>"
    return f"⏳ <b>Release countdown:</b> {days_remaining} days to go"


def _release_response(metadata, today=None):
    release_date = metadata.get("release_date")
    countdown = _release_countdown_text(release_date, today=today)
    if countdown:
        status = "UPCOMING RELEASE"
    else:
        try:
            release_day = date.fromisoformat(str(release_date))
        except (TypeError, ValueError):
            release_day = None
        if release_day is None:
            status = "DATE UNCONFIRMED"
        elif release_day < (today or datetime.now(pytz.timezone(TIMEZONE)).date()):
            status = "RELEASED"
        else:
            status = "DATE UNCONFIRMED"

    safe_title = html_escape(str(metadata.get("title") or "Unknown title"))
    year = metadata.get("year")
    date_line = (
        f"Release Date: <b>{html_escape(str(release_date))}</b>"
        if status != "DATE UNCONFIRMED"
        else "Release date not officially confirmed yet."
    )
    countdown_line = f"\n\n{countdown}" if countdown else ""
    return (
        f"🎬 <b>{safe_title}"
        f"{f' ({html_escape(str(year))})' if year else ''}</b>\n\n"
        f"Status: <b>{status}</b>\n{date_line}{countdown_line}\n\n"
        "Source: IMDb. Release type/platform not listed."
    )


@Client.on_message(filters.command("release"))
async def release_search(client, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        return await message.reply_text(
            "Usage: <code>/release Movie or Series Name</code>\n"
            "Example: <code>/release Stranger Things</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    status = await message.reply_text("IMDb par release details dhoondh rahi hoon…")
    try:
        movies = await get_poster(parts[1].strip(), bulk=True)
    except Exception:
        logger.exception("IMDb release search failed")
        return await status.edit("Release details abhi nahi mil pa rahi hain. Thodi der baad try karein.")
    if not movies:
        return await status.edit("Is title ke IMDb results nahi mile.")
    buttons = [
        [InlineKeyboardButton(
            text=f"{movie.get('title', 'Unknown')} - {movie.get('year', 'Year N/A')}",
            callback_data=f"release#{movie.movieID}",
        )]
        for movie in movies[:10]
    ]
    await status.edit(
        "Sahi movie ya series choose karein:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex(r"^release#"))
async def release_callback(client, query):
    movie_id = query.data.split("#", 1)[1]
    try:
        metadata = await get_poster(query=movie_id, id=True)
    except Exception:
        logger.exception("IMDb release details fetch failed (id=%s)", movie_id)
        return await query.message.edit_text(
            "Release details abhi available nahi hain. Baad mein dobara try karein."
        )
    if not metadata:
        return await query.message.edit_text("Is title ki release details nahi mili.")
    response = _release_response(metadata)
    await query.message.edit_text(
        response,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await query.answer()


@Client.on_message(filters.command('id'))
async def showid(client, message):
    chat_type = message.chat.type
    if chat_type == enums.ChatType.PRIVATE:
        user_id = message.chat.id
        first = message.from_user.first_name
        last = message.from_user.last_name or ""
        username = message.from_user.username
        dc_id = message.from_user.dc_id or ""
        await message.reply_text(
            f"<b>➲ First Name:</b> {first}\n<b>➲ Last Name:</b> {last}\n<b>➲ Username:</b> {username}\n<b>➲ Telegram ID:</b> <code>{user_id}</code>\n<b>➲ Data Centre:</b> <code>{dc_id}</code>",
            quote=True
        )

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        _id = ""
        _id += (
            "<b>➲ Chat ID</b>: "
            f"<code>{message.chat.id}</code>\n"
        )
        if message.reply_to_message:
            _id += (
                "<b>➲ User ID</b>: "
                f"<code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n"
                "<b>➲ Replied User ID</b>: "
                f"<code>{message.reply_to_message.from_user.id if message.reply_to_message.from_user else 'Anonymous'}</code>\n"
            )
            file_info = get_file_id(message.reply_to_message)
        else:
            _id += (
                "<b>➲ User ID</b>: "
                f"<code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n"
            )
            file_info = get_file_id(message)
        if file_info:
            _id += (
                f"<b>{file_info.message_type}</b>: "
                f"<code>{file_info.file_id}</code>\n"
            )
        await message.reply_text(
            _id,
            quote=True
        )

@Client.on_message(filters.command(["info"]))
async def who_is(client, message):
    # https://github.com/SpEcHiDe/PyroGramBot/blob/master/pyrobot/plugins/admemes/whois.py#L19
    status_message = await message.reply_text(
        "`Fetching user info...`"
    )
    await status_message.edit(
        "`Processing user info...`"
    )
    from_user = None
    from_user_id, _ = extract_user(message)
    try:
        from_user = await client.get_users(from_user_id)
    except Exception as error:
        await status_message.edit(str(error))
        return
    if from_user is None:
        return await status_message.edit("no valid user_id / message specified")
    message_out_str = ""
    message_out_str += f"<b>➲First Name:</b> {from_user.first_name}\n"
    last_name = from_user.last_name or "<b>None</b>"
    message_out_str += f"<b>➲Last Name:</b> {last_name}\n"
    message_out_str += f"<b>➲Telegram ID:</b> <code>{from_user.id}</code>\n"
    username = from_user.username or "<b>None</b>"
    dc_id = from_user.dc_id or "[User Doesn't Have A Valid DP]"
    message_out_str += f"<b>➲Data Centre:</b> <code>{dc_id}</code>\n"
    message_out_str += f"<b>➲User Name:</b> @{username}\n"
    message_out_str += f"<b>➲User 𝖫𝗂𝗇𝗄:</b> <a href='tg://user?id={from_user.id}'><b>Click Here</b></a>\n"
    if message.chat.type in ((enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL)):
        try:
            chat_member_p = await message.chat.get_member(from_user.id)
            joined_date = (
                chat_member_p.joined_date or datetime.now()
            ).strftime("%Y.%m.%d %H:%M:%S")
            message_out_str += (
                "<b>➲Joined this Chat on:</b> <code>"
                f"{joined_date}"
                "</code>\n"
            )
        except UserNotParticipant:
            pass
    chat_photo = from_user.photo
    if chat_photo:
        local_user_photo = await client.download_media(
            message=chat_photo.big_file_id
        )
        buttons = [[
            InlineKeyboardButton('🔐 Close', callback_data='close_data')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_photo(
            photo=local_user_photo,
            quote=True,
            reply_markup=reply_markup,
            caption=message_out_str,
            parse_mode=enums.ParseMode.HTML,
            disable_notification=True
        )
        os.remove(local_user_photo)
    else:
        buttons = [[
            InlineKeyboardButton('🔐 Close', callback_data='close_data')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_text(
            text=message_out_str,
            reply_markup=reply_markup,
            quote=True,
            parse_mode=enums.ParseMode.HTML,
            disable_notification=True
        )
    await status_message.delete()

@Client.on_message(filters.command(["imdb", 'search']))
async def imdb_search(client, message):
    if ' ' in message.text:
        k = await message.reply('Searching ImDB')
        r, title = message.text.split(None, 1)
        movies = await get_poster(title, bulk=True)
        if not movies:
            return await message.reply("No results Found")
        btn = [
            [
                InlineKeyboardButton(
                    text=f"{movie.get('title')} - {movie.get('year')}",
                    callback_data=f"imdb#{movie.movieID}",
                )
            ]
            for movie in movies
        ]
        await k.edit('Here is what i found on IMDb', reply_markup=InlineKeyboardMarkup(btn))
    else:
        await message.reply('Give me a movie / series Name')

@Client.on_callback_query(filters.regex('^imdb'))
async def imdb_callback(bot: Client, quer_y: CallbackQuery):
    i, movie = quer_y.data.split('#')
    imdb = await get_poster(query=movie, id=True)
    btn = [
            [
                InlineKeyboardButton(
                    text=f"{imdb.get('title')}",
                    url=imdb['url'],
                )
            ]
        ]
    message = quer_y.message.reply_to_message or quer_y.message
    if imdb:
        caption = IMDB_TEMPLATE.format(
            query = imdb['title'],
            title = imdb['title'],
            votes = imdb['votes'],
            aka = imdb["aka"],
            seasons = imdb["seasons"],
            box_office = imdb['box_office'],
            localized_title = imdb['localized_title'],
            kind = imdb['kind'],
            imdb_id = imdb["imdb_id"],
            cast = imdb["cast"],
            runtime = imdb["runtime"],
            countries = imdb["countries"],
            certificates = imdb["certificates"],
            languages = imdb["languages"],
            director = imdb["director"],
            writer = imdb["writer"],
            producer = imdb["producer"],
            composer = imdb["composer"],
            cinematographer = imdb["cinematographer"],
            music_team = imdb["music_team"],
            distributors = imdb["distributors"],
            release_date = imdb['release_date'],
            year = imdb['year'],
            genres = imdb['genres'],
            poster = imdb['poster'],
            plot = imdb['plot'],
            rating = imdb['rating'],
            url = imdb['url'],
            **locals()
        )
        countdown = _release_countdown_text(imdb.get("release_date"))
        if countdown:
            caption += f"\n\n{countdown}"
    else:
        caption = "No Results"
    if imdb.get('poster'):
        custom_poster = await fetch_custom_poster(imdb)
        try:
            await quer_y.message.reply_photo(
                photo=custom_poster or imdb['poster'],
                caption=caption,
                reply_markup=InlineKeyboardMarkup(btn),
            )
        except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
            if custom_poster:
                raise
            pic = imdb.get('poster')
            poster = pic.replace('.jpg', "._V1_UX360.jpg")
            await quer_y.message.reply_photo(photo=poster, caption=caption, reply_markup=InlineKeyboardMarkup(btn))
        except Exception as e:
            logger.exception(e)
            await quer_y.message.reply(caption, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=False)
        await quer_y.message.delete()
    else:
        await quer_y.message.edit(caption, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=False)
    await quer_y.answer()
        

        
