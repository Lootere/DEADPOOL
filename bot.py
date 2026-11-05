# This code has been modified by Looteredev
# Please do not remove this credit
import logging
import logging.config

# Get logging configurations
logging.config.fileConfig('logging.conf')
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("imdbpy").setLevel(logging.ERROR)
logging.getLogger("cinemagoer").setLevel(logging.ERROR)

from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from database.ia_filterdb import Media
from database.users_chats_db import db
from info import SESSION, API_ID, API_HASH, BOT_TOKEN, LOG_STR, LOG_CHANNEL, PORT, BIN_CHANNEL, ON_HEROKU, VIP_GROUP_ID, VIP_CHANNEL1_ID, VIP_CHANNEL2_ID, ADMINS, PAYMENT_LOG_CHANNEL
from typing import Union, Optional, AsyncGenerator
from pyrogram import types
from Script import script 
from datetime import date, datetime 
import pytz
from utils import temp
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("aiohttp").setLevel(logging.ERROR)
logging.getLogger("aiohttp.web").setLevel(logging.ERROR)
import asyncio
import sys
import importlib
import glob
from pathlib import Path
from aiohttp import web
from pyrogram import idle
from Lootere.template import web_server
from Lootere.utils import LootereBot
from Lootere.utils.keepalive import ping_server
from Lootere.utils.clients import initialize_clients
from plugins.Dev_Feature.Premium import check_expired_premium

ppath = "plugins/*.py"
files = glob.glob(ppath)
LootereBot.start()
loop = asyncio.get_event_loop()


async def start():
    print('\n')
    print('Initalizing Your Bot')
    bot_info = await LootereBot.get_me()
    LootereBot.username = bot_info.username
    await initialize_clients()
    for name in files:
        with open(name) as a:
            patt = Path(a.name)
            plugin_name = patt.stem.replace(".py", "")
            plugins_dir = Path(f"plugins/{plugin_name}.py")
            import_path = "plugins.{}".format(plugin_name)
            spec = importlib.util.spec_from_file_location(import_path, plugins_dir)
            load = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(load)
            sys.modules["plugins." + plugin_name] = load
            print("All Files Imported => " + plugin_name)
    if ON_HEROKU:
        asyncio.create_task(ping_server())
    b_users, b_chats = await db.get_banned()
    temp.BANNED_USERS = b_users
    temp.BANNED_CHATS = b_chats
    await Media.ensure_indexes()
    try:
        from Lootere.utils.subscription_manager import subscription_manager
        subscription_manager.set_db(getattr(db, "db", None))
        await subscription_manager.dest_mgr.initialize(
            default_group_id=VIP_GROUP_ID,
            default_channel1_id=VIP_CHANNEL1_ID,
            default_channel2_id=VIP_CHANNEL2_ID,
        )
    except Exception as e:
        logging.error(f"Failed to initialize subscription_manager: {e}")
    try:
        from Lootere.utils.payment_manager import payment_manager
        payment_manager.set_db(getattr(db, "db", None))
        if PAYMENT_LOG_CHANNEL:
            payment_manager.set_review_channel(PAYMENT_LOG_CHANNEL)
        payment_manager.set_authorized_reviewers(ADMINS)
    except Exception as e:
        logging.error(f"Failed to initialize payment_manager: {e}")
    me = await LootereBot.get_me()
    temp.ME = me.id
    temp.U_NAME = me.username
    temp.B_NAME = me.first_name
    LootereBot.username = '@' + me.username
    LootereBot.loop.create_task(check_expired_premium(LootereBot))
    logging.info(f"{me.first_name} with for Pyrogram v{__version__} (Layer {layer}) started on {me.username}.")
    logging.info(LOG_STR)
    logging.info(script.LOGO)
    tz = pytz.timezone('Asia/Kolkata')
    today = date.today()
    now = datetime.now(tz)
    time = now.strftime("%H:%M:%S %p")
    app = web.AppRunner(await web_server())
    await app.setup()
    bind_address = "0.0.0.0"
    await web.TCPSite(app, bind_address, PORT).start()
    await idle()
    await LootereBot.send_message(chat_id=LOG_CHANNEL, text=script.RESTART_TXT.format(temp.U_NAME, temp.B_NAME, today, time))


if __name__ == '__main__':
    try:
        loop.run_until_complete(start())
    except KeyboardInterrupt:
        logging.info('Service Stopped Bye 👋')