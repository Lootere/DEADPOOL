# This code has been modified by @Looteredev
# Please do not remove this credit
import motor.motor_asyncio
from pymongo import ReturnDocument
from info import DATABASE_NAME, DATABASE_URI, IMDB, IMDB_TEMPLATE, MELCOW_NEW_USERS, SINGLE_BUTTON, SPELL_CHECK_REPLY, AUTO_DELETE, MAX_BTN, AUTO_FFILTER, TUTORIAL, TUTORIAL2, TUTORIAL3, REFERAL_TIME, STREAM_API, STREAM_SITE, VERIFY_URL, VERIFY_API, \
VERIFY_URL2, VERIFY_API2, VERIFY_URL3, VERIFY_API3, LIMIT_MODE, TWO_VERIFY_GAP, THIRD_VERIFY_GAP, STREAM_MODE, LOG_CHANNEL, IS_VERIFY, AUTH_CHANNEL, CUSTOM_FILE_CAPTION, FILE_LIMITE, SEND_ALL_LIMITE, STREAM_SITE, STREAM_API
from datetime import datetime, timedelta
import pytz
import re
import time
import hashlib
import random
import secrets
import string
    
class Database:
    
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups
        self.users = self.db.uersz
        self.codes = self.db.codes
        self.Lootere = self.db.Lootere
        self.req = self.db.requests
        self.links_col = self.db.links
        self.verify_id = self.db.verify_id
        self.settings_col = self.db.settings
        self.playlists_col = self.db.playlists
        
    def new_user(self, id, name):
        return dict(
            id = id,
            name = name,
            send_all=0,
            files_count=0,
            lifetime_files=0,
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )

    def new_group(self, id, title, owner_id):
        return dict(
            id = id,
            title = title,
            owner_id=owner_id, 
            is_verified=False,
            is_rejected=False, 
            chat_status=dict(
                is_disabled=False,
                reason="",
            ),
        )
        
    async def get_setting(self, key, default=None):
        setting = await self.settings_col.find_one({"name": key})
        return setting.get("value", default) if setting else default

    async def set_setting(self, key, value):
        await self.settings_col.update_one(
            {"name": key},
            {"$set": {"value": value}},
            upsert=True)

    @staticmethod
    def _series_key(title):
        return " ".join(re.sub(r"[^\w]+", " ", str(title).casefold()).split())

    async def get_user_series_tracks(self, user_id):
        user = await self.col.find_one(
            {"id": int(user_id)},
            {"tracked_series": 1},
        )
        return user.get("tracked_series", []) if user else []

    async def add_series_track(self, user_id, title, user_name):
        user_id = int(user_id)
        title = " ".join(str(title).split())
        series_key = self._series_key(title)
        if not title or len(title) > 80 or not series_key:
            raise ValueError("Series names must be between 1 and 80 characters")

        await self.col.update_one(
            {"id": user_id},
            {"$setOnInsert": self.new_user(user_id, user_name)},
            upsert=True,
        )
        user = await self.col.find_one(
            {"id": user_id, "tracked_series.series_key": series_key},
            {"_id": 1},
        )
        if user:
            return False

        result = await self.col.update_one(
            {
                "id": user_id,
                "$expr": {
                    "$lt": [
                        {"$size": {"$ifNull": ["$tracked_series", []]}},
                        20,
                    ]
                },
            },
            {
                "$addToSet": {
                    "tracked_series": {
                        "series_key": series_key,
                        "title": title,
                        "notified_episodes": [],
                    }
                }
            },
        )
        if result.modified_count == 1:
            return True

        user = await self.col.find_one({"id": user_id}, {"tracked_series": 1})
        if user and any(
            track.get("series_key") == series_key
            for track in user.get("tracked_series", [])
        ):
            return False
        raise ValueError("You can track up to 20 series")

    async def remove_series_track(self, user_id, title):
        series_key = self._series_key(title)
        result = await self.col.update_one(
            {"id": int(user_id), "tracked_series.series_key": series_key},
            {"$pull": {"tracked_series": {"series_key": series_key}}},
        )
        return result.modified_count == 1

    async def get_series_trackers(self, series_key):
        cursor = self.col.find(
            {"tracked_series.series_key": series_key},
            {"id": 1},
        )
        return [int(user["id"]) async for user in cursor]

    async def claim_series_episode_notification(self, user_id, series_key, episode_key):
        result = await self.col.update_one(
            {
                "id": int(user_id),
                "tracked_series": {
                    "$elemMatch": {
                        "series_key": series_key,
                        "notified_episodes": {"$ne": episode_key},
                    }
                },
            },
            {
                "$push": {
                    "tracked_series.$.notified_episodes": {
                        "$each": [episode_key],
                        "$slice": -200,
                    }
                }
            },
        )
        return result.modified_count == 1

    @staticmethod
    def _playlist_name_key(name):
        return " ".join(str(name).split()).casefold()

    async def get_user_playlists(self, user_id):
        cursor = self.playlists_col.find(
            {"user_id": int(user_id)},
            {"playlist_id": 1, "name": 1, "items": 1, "share_token": 1},
        ).sort("name", 1)
        return await cursor.to_list(length=20)

    async def create_playlist(self, user_id, name):
        user_id = int(user_id)
        name = " ".join(str(name).split())
        name_key = self._playlist_name_key(name)
        if not name or len(name) > 40:
            raise ValueError("Playlist names must be between 1 and 40 characters")
        existing = await self.playlists_col.find_one(
            {"user_id": user_id, "name_key": name_key}
        )
        if existing:
            raise ValueError("A playlist with that name already exists")
        if await self.playlists_col.count_documents({"user_id": user_id}) >= 20:
            raise ValueError("You can create up to 20 playlists")
        result = await self.playlists_col.insert_one(
            {
                "user_id": user_id,
                "playlist_id": secrets.token_urlsafe(9),
                "name": name,
                "name_key": name_key,
                "items": [],
                "share_token": None,
                "created_at": datetime.utcnow(),
            }
        )
        return await self.playlists_col.find_one({"_id": result.inserted_id})

    async def add_playlist_item(self, user_id, playlist_id, title):
        user_id = int(user_id)
        title = " ".join(str(title).split())
        if not title or len(title) > 120:
            raise ValueError("Movie titles must be between 1 and 120 characters")
        playlist = await self.playlists_col.find_one(
            {"playlist_id": playlist_id, "user_id": user_id}
        )
        if not playlist:
            raise ValueError("Playlist not found")
        if any(item.casefold() == title.casefold() for item in playlist.get("items", [])):
            return False
        if len(playlist.get("items", [])) >= 25:
            raise ValueError("Each playlist can contain up to 25 titles")
        result = await self.playlists_col.update_one(
            {
                "playlist_id": playlist_id,
                "user_id": user_id,
                "$expr": {
                    "$lt": [
                        {"$size": {"$ifNull": ["$items", []]}},
                        25,
                    ]
                },
            },
            {"$addToSet": {"items": title}},
        )
        if result.modified_count != 1:
            latest = await self.playlists_col.find_one(
                {"playlist_id": playlist_id, "user_id": user_id}
            )
            if latest and any(
                item.casefold() == title.casefold()
                for item in latest.get("items", [])
            ):
                return False
            if latest and len(latest.get("items", [])) >= 25:
                raise ValueError("Each playlist can contain up to 25 titles")
            raise RuntimeError("Unable to add title to playlist")
        return True

    async def remove_playlist_item(self, user_id, name, title):
        user_id = int(user_id)
        name_key = self._playlist_name_key(name)
        playlist = await self.playlists_col.find_one(
            {"user_id": user_id, "name_key": name_key}
        )
        if not playlist:
            return False
        match = next(
            (
                item for item in playlist.get("items", [])
                if item.casefold() == str(title).strip().casefold()
            ),
            None,
        )
        if match is None:
            return False
        result = await self.playlists_col.update_one(
            {"_id": playlist["_id"], "user_id": user_id},
            {"$pull": {"items": match}},
        )
        return result.modified_count == 1

    async def delete_playlist(self, user_id, name):
        result = await self.playlists_col.delete_one(
            {
                "user_id": int(user_id),
                "name_key": self._playlist_name_key(name),
            }
        )
        return result.deleted_count == 1

    async def get_playlist_share_token(self, user_id, name):
        playlist = await self.playlists_col.find_one(
            {
                "user_id": int(user_id),
                "name_key": self._playlist_name_key(name),
            }
        )
        if not playlist:
            return None
        token = playlist.get("share_token")
        if not token:
            token = secrets.token_urlsafe(9)
            await self.playlists_col.update_one(
                {
                    "_id": playlist["_id"],
                    "user_id": int(user_id),
                    "share_token": {"$in": [None, ""]},
                },
                {"$set": {"share_token": token}},
            )
            playlist = await self.playlists_col.find_one(
                {"_id": playlist["_id"], "user_id": int(user_id)}
            )
            token = playlist.get("share_token") if playlist else None
        return token

    async def get_shared_playlist(self, token):
        if not token or len(token) > 32:
            return None
        playlist = await self.playlists_col.find_one(
            {"share_token": token},
            {"_id": 0, "name": 1, "items": 1},
        )
        return playlist

    async def get_force_sub_channels(self):
        channels = await self.get_setting("FORCE_SUB_CHANNELS", default=[])
        if not isinstance(channels, list):
            raise ValueError("FORCE_SUB_CHANNELS must be stored as a list")
        return [int(channel) for channel in channels]

    async def add_force_sub_channel(self, channel_id):
        channel_id = int(channel_id)
        await self.settings_col.update_one(
            {"name": "FORCE_SUB_CHANNELS"},
            {"$addToSet": {"value": channel_id}},
            upsert=True,
        )

    async def remove_force_sub_channel(self, channel_id):
        channel_id = int(channel_id)
        result = await self.settings_col.update_one(
            {"name": "FORCE_SUB_CHANNELS"},
            {"$pull": {"value": channel_id}},
        )
        return result.modified_count > 0

    async def find_join_req(self, id):
        return bool(await self.req.find_one({'id': id}))
        
    async def add_join_req(self, id):
        await self.req.insert_one({'id': id})

    async def del_join_req(self):
        await self.req.drop()
        
    async def get_Lootere_user(self, user_id):
        user_id = int(user_id)
        user = await self.Lootere.find_one({"user_id": user_id})
        ist_timezone = pytz.timezone('Asia/Kolkata')
        if not user:
            res = {
                "user_id": user_id,
                "last_verified": datetime(2020, 5, 17, 0, 0, 0, tzinfo=ist_timezone),
                "second_verified": datetime(2019, 5, 17, 0, 0, 0, tzinfo=ist_timezone),
            }
            user = await self.Lootere.insert_one(res)
        return user

    async def update_Lootere_user(self, user_id, value:dict):
        user_id = int(user_id)
        myquery = {"user_id": user_id}
        newvalues = {"$set": value}
        return await self.Lootere.update_one(myquery, newvalues)

    async def is_user_verified(self, user_id):
        user = await self.get_Lootere_user(user_id)
        try:
            Lootereback = user["last_verified"]
        except Exception:
            user = await self.get_Lootere_user(user_id)
            Lootereback = user["last_verified"]
        ist_timezone = pytz.timezone('Asia/Kolkata')
        Lootereback = Lootereback.astimezone(ist_timezone)
        current_time = datetime.now(tz=ist_timezone)
        seconds_since_midnight = (current_time - datetime(current_time.year, current_time.month, current_time.day, 0, 0, 0, tzinfo=ist_timezone)).total_seconds()
        time_diff = current_time - Lootereback
        total_seconds = time_diff.total_seconds()
        return total_seconds <= seconds_since_midnight

    async def user_verified(self, user_id):
        user = await self.get_Lootere_user(user_id)
        try:
            Lootereback = user["second_verified"]
        except Exception:
            user = await self.get_Lootere_user(user_id)
            Lootereback = user["second_verified"]
        ist_timezone = pytz.timezone('Asia/Kolkata')
        Lootereback = Lootereback.astimezone(ist_timezone)
        current_time = datetime.now(tz=ist_timezone)
        seconds_since_midnight = (current_time - datetime(current_time.year, current_time.month, current_time.day, 0, 0, 0, tzinfo=ist_timezone)).total_seconds()
        time_diff = current_time - Lootereback
        total_seconds = time_diff.total_seconds()
        return total_seconds <= seconds_since_midnight

    async def use_second_shortener(self, user_id, time):
        user = await self.get_Lootere_user(user_id)
        if not user.get("second_verified"):
            ist_timezone = pytz.timezone('Asia/Kolkata')
            await self.update_Lootere_user(user_id, {"second_verified":datetime(2019, 5, 17, 0, 0, 0, tzinfo=ist_timezone)})
            user = await self.get_Lootere_user(user_id)
        if await self.is_user_verified(user_id):
            try:
                Lootereback = user["last_verified"]
            except Exception:
                user = await self.get_Lootere_user(user_id)
                Lootereback = user["last_verified"]
            ist_timezone = pytz.timezone('Asia/Kolkata')
            Lootereback = Lootereback.astimezone(ist_timezone)
            current_time = datetime.now(tz=ist_timezone)
            time_difference = current_time - Lootereback
            if time_difference > timedelta(seconds=time):
                Lootereback = user["last_verified"].astimezone(ist_timezone)
                second_time = user["second_verified"].astimezone(ist_timezone)
                return second_time < Lootereback
        return False
        
    async def use_third_shortener(self, user_id, time):
        user = await self.get_Lootere_user(user_id)
        if not user.get("third_verified"):
            ist_timezone = pytz.timezone('Asia/Kolkata')
            await self.update_Lootere_user(user_id, {"third_verified":datetime(2018, 5, 17, 0, 0, 0, tzinfo=ist_timezone)})
            user = await self.get_Lootere_user(user_id)
        if await self.user_verified(user_id):
            try:
                Lootereback = user["second_verified"]
            except Exception:
                user = await self.get_Lootere_user(user_id)
                Lootereback = user["second_verified"]
            ist_timezone = pytz.timezone('Asia/Kolkata')
            Lootereback = Lootereback.astimezone(ist_timezone)
            current_time = datetime.now(tz=ist_timezone)
            time_difference = current_time - Lootereback
            if time_difference > timedelta(seconds=time):
                Lootereback = user["second_verified"].astimezone(ist_timezone)
                second_time = user["third_verified"].astimezone(ist_timezone)
                return second_time < Lootereback
        return False
        
    async def create_verify_id(self, user_id: int, hash):
        res = {"user_id": user_id, "hash":hash, "verified":False}
        return await self.verify_id.insert_one(res)

    async def get_verify_id_info(self, user_id: int, hash):
        return await self.verify_id.find_one({"user_id": user_id, "hash": hash})

    async def update_verify_id_info(self, user_id, hash, value: dict):
        myquery = {"user_id": user_id, "hash": hash}
        newvalues = { "$set": value }
        return await self.verify_id.update_one(myquery, newvalues)
    
    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)

    async def is_user_exist(self, id):
        user = await self.col.find_one({'id': int(id)})
        return bool(user)
    
    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count

    @staticmethod
    def current_activity_week():
        week = datetime.now(pytz.timezone("Asia/Kolkata")).date().isocalendar()
        return f"{week.year}-W{week.week:02d}"

    async def record_weekly_activity(self, user_id, count=1):
        user_id = int(user_id)
        count = int(count)
        if count < 1:
            raise ValueError("Weekly activity count must be positive")

        week = self.current_activity_week()
        await self.col.update_one(
            {"id": user_id},
            {"$setOnInsert": self.new_user(user_id, "None")},
            upsert=True,
        )
        await self.col.update_one(
            {"id": user_id, "weekly_activity_week": {"$ne": week}},
            {
                "$set": {
                    "weekly_activity_week": week,
                    "weekly_activity_count": 0,
                }
            },
        )
        await self.col.update_one(
            {"id": user_id, "weekly_activity_week": week},
            {"$inc": {"weekly_activity_count": count}},
        )

    async def get_weekly_leaderboard(self, limit=10):
        limit = int(limit)
        if not 1 <= limit <= 50:
            raise ValueError("Leaderboard limit must be between 1 and 50")
        week = self.current_activity_week()
        cursor = self.col.find(
            {
                "weekly_activity_week": week,
                "weekly_activity_count": {"$gt": 0},
            },
            {
                "_id": 0,
                "id": 1,
                "name": 1,
                "weekly_activity_count": 1,
            },
        )
        cursor.sort([("weekly_activity_count", -1), ("name", 1)])
        return await cursor.limit(limit).to_list(length=limit)
    
    async def remove_ban(self, id):
        ban_status = dict(
            is_banned=False,
            ban_reason=''
        )
        await self.col.update_one({'id': id}, {'$set': {'ban_status': ban_status}})
    
    async def ban_user(self, user_id, ban_reason="No Reason"):
        ban_status = dict(
            is_banned=True,
            ban_reason=ban_reason
        )
        await self.col.update_one({'id': user_id}, {'$set': {'ban_status': ban_status}})

    async def get_ban_status(self, id):
        default = dict(
            is_banned=False,
            ban_reason=''
        )
        user = await self.col.find_one({'id':int(id)})
        if not user:
            return default
        return user.get('ban_status', default)

    async def get_all_users(self):
        return self.col.find({})
    

    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})


    async def get_banned(self):
        users = self.col.find({'ban_status.is_banned': True})
        chats = self.grp.find({'chat_status.is_disabled': True})
        b_chats = [chat['id'] async for chat in chats]
        b_users = [user['id'] async for user in users]
        return b_users, b_chats
   
    async def files_count(self, user_id, key):
        user = await self.col.find_one({"id": user_id})
        if user is None:
            await self.add_user(user_id, "None")
            return 0
        return user.get(key, 0)
        
    async def update_files(self, user_id, key, value):
        await self.col.update_one({"id": user_id}, {"$set": {key: value}})

    async def consume_daily_limit(self, user_id, key, limit):
        if key not in ("files_count", "send_all"):
            raise ValueError(f"Unsupported daily usage counter: {key}")
        limit = int(limit)
        if limit < 0:
            raise ValueError("Daily usage limits cannot be negative")

        user_id = int(user_id)
        usage_date = datetime.now(pytz.timezone("Asia/Kolkata")).date().isoformat()

        if limit > 0:
            fast_updated = await self.col.find_one_and_update(
                {
                    "id": user_id,
                    "daily_usage_date": usage_date,
                    key: {"$lt": limit},
                },
                {"$inc": {key: 1}},
                return_document=ReturnDocument.AFTER,
            )
            if fast_updated:
                return True, fast_updated[key]

        await self.col.update_one(
            {"id": user_id},
            {"$setOnInsert": self.new_user(user_id, "None")},
            upsert=True,
        )
        await self.col.update_one(
            {
                "id": user_id,
                "daily_usage_date": {"$exists": False},
            },
            {"$set": {"daily_usage_date": usage_date}},
        )
        await self.col.update_one(
            {"id": user_id, "daily_usage_date": {"$ne": usage_date}},
            {
                "$set": {
                    "daily_usage_date": usage_date,
                    "files_count": 0,
                    "send_all": 0,
                }
            },
        )
        await self.col.update_one(
            {
                "id": user_id,
                "daily_usage_date": usage_date,
                key: {"$exists": False},
            },
            {"$set": {key: 0}},
        )

        updated_user = await self.col.find_one_and_update(
            {
                "id": user_id,
                "daily_usage_date": usage_date,
                key: {"$lt": limit},
            },
            {"$inc": {key: 1}},
            return_document=ReturnDocument.AFTER,
        )
        if updated_user:
            return True, updated_user[key]

        user = await self.col.find_one(
            {"id": user_id, "daily_usage_date": usage_date},
            {"_id": 0, key: 1},
        )
        return False, user.get(key, 0) if user else 0
    
    async def reset_all_files_count(self):
        await self.col.update_many({}, {"$set": {"files_count": 0}})

    async def reset_allsend_files(self):
        await self.col.update_many({}, {"$set": {"send_all": 0}})
        
    async def reset_daily_files_count(self, user_id):
        user = await self.col.find_one({"id": user_id})
        if user is None:
            return
        await self.col.update_one({"id": user_id}, {"$set": {"files_count": 0}})

    async def add_chat(self, chat, title, owner_id):
        chat = self.new_group(chat, title, owner_id)
        await self.grp.insert_one(chat)
    
    async def get_chat(self, chat_id):
        chat = await self.grp.find_one({'id': int(chat_id)})
        return chat if chat else False
    
    
    async def re_enable_chat(self, id):
        chat_status=dict(
            is_disabled=False,
            reason="",
            )
        await self.grp.update_one({'id': int(id)}, {'$set': {'chat_status': chat_status}})
        
    async def update_settings(self, id, settings):
        await self.grp.update_one({'id': int(id)}, {'$set': {'settings': settings}})
            
    async def get_settings(self, id):
        default = {
            'button': SINGLE_BUTTON,
            'imdb': IMDB,
            'spell_check': SPELL_CHECK_REPLY,
            'welcome': MELCOW_NEW_USERS,
            'auto_delete': AUTO_DELETE,
            'auto_delete_time': 600 if AUTO_DELETE else 0,
            'auto_ffilter': AUTO_FFILTER,
            'max_btn': MAX_BTN,
            'template': IMDB_TEMPLATE,
            'verify': VERIFY_URL,
            'verify_api': VERIFY_API,
            'verify_2': VERIFY_URL2,
            'verify_api2': VERIFY_API2,
            'verify_3': VERIFY_URL3,
            'verify_api3': VERIFY_API3,
            'verify_time': TWO_VERIFY_GAP,
            'verify_time2': THIRD_VERIFY_GAP,
            'tutorial': TUTORIAL,
            'tutorial2': TUTORIAL2, 
            'tutorial3': TUTORIAL3, 
            'filelock': LIMIT_MODE, 
            'log': LOG_CHANNEL,
            'is_verify': IS_VERIFY,
            'fsub_id': AUTH_CHANNEL, 
            'file_limit': FILE_LIMITE, 
            'all_limit': SEND_ALL_LIMITE, 
            'stream_mode': STREAM_MODE,
            'streamapi': STREAM_API, 
            'streamsite': STREAM_SITE,
            'caption': CUSTOM_FILE_CAPTION
        }
        chat = await self.grp.find_one({'id':int(id)})
        if chat:
            return chat.get('settings', default)
        return default
 
               
    async def disable_chat(self, chat, reason="No Reason"):
        chat_status=dict(
            is_disabled=True,
            reason=reason,
            )
        await self.grp.update_one({'id': int(chat)}, {'$set': {'chat_status': chat_status}})

    async def verify_group(self, chat_id):
        await self.grp.update_one({'id': int(chat_id)}, {'$set': {'is_verified': True}})

    async def un_rejected(self, chat_id):
        await self.grp.update_one({'id': int(chat_id)}, {'$set': {'is_rejected': False}})

    async def reject_group(self, chat_id):
        await self.grp.update_one({'id': int(chat_id)}, {'$set': {'is_rejected': True}})

    async def check_group_verification(self, chat_id):
        chat = await self.get_chat(chat_id)
        if not chat:
            return False
        return chat.get('is_verified')

    async def rejected_group(self, chat_id):
        chat = await self.get_chat(chat_id)
        if not chat:
            return False
        return chat.get('is_rejected')

    async def get_all_groups(self):
        return await self.grp.find().to_list(None)

    async def delete_all_groups(self):
        await self.grp.delete_many({})

    async def total_chat_count(self):
        count = await self.grp.count_documents({})
        return count
    

    async def get_all_chats(self):
        return self.grp.find({})


    async def get_db_size(self):
        return (await self.db.command("dbstats"))['dataSize']
        
    async def get_user(self, user_id):
        user_data = await self.users.find_one({"id": user_id})
        return user_data
        
    async def update_user(self, user_data):
        await self.users.update_one({"id": user_data["id"]}, {"$set": user_data}, upsert=True)

    async def has_premium_access(self, user_id):
        user_data = await self.get_user(user_id)
        if user_data:
            expiry_time = user_data.get("expiry_time")
            if expiry_time is None:
                return False
            elif isinstance(expiry_time, datetime) and datetime.now() <= expiry_time:
                return True
            else:
                await self.users.update_one({"id": user_id}, {"$set": {"expiry_time": None}})
        return False
        
    async def update_one(self, filter_query, update_data):
        try:
            result = await self.users.update_one(filter_query, update_data)
            return result.matched_count == 1
        except Exception as e:
            print(f"Error updating document: {e}")
            return False

    async def get_expired(self, current_time):
        expired_users = []
        if data := self.users.find({"expiry_time": {"$lt": current_time}}):
            async for user in data:
                expired_users.append(user)
        return expired_users

    async def remove_premium_access(self, user_id):
        return await self.update_one(
            {"id": user_id}, {"$set": {"expiry_time": None}}
        )

    async def check_trial_status(self, user_id):
        user_data = await self.get_user(user_id)
        if user_data:
            return user_data.get("has_free_trial", False)
        return False

    async def give_free_trial(self, user_id):
        user_id = user_id
        seconds = 5*60         
        expiry_time = datetime.now() + timedelta(seconds=seconds)
        user_data = {"id": user_id, "expiry_time": expiry_time, "has_free_trial": True}
        await self.users.update_one({"id": user_id}, {"$set": user_data}, upsert=True)

    async def give_referal(self, userid):        
        user_id = userid
        seconds = REFERAL_TIME       
        expiry_time = datetime.now() + timedelta(seconds=seconds)
        user_data = {"id": user_id, "expiry_time": expiry_time, "has_free_trial": True}
        await self.users.update_one({"id": user_id}, {"$set": user_data}, upsert=True)

  

db = Database(DATABASE_URI, DATABASE_NAME)
