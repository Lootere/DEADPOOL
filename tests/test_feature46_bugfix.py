"""Feature 46 post-implementation bug-fix tests.

Covers the three reported bugs:
1. missing IMDb metadata / poster in notifications
2. missing series metadata
3. missing `/notification` admin command registration

All tests are offline: provider HTTP is patched with deterministic doubles.
"""
import asyncio
import importlib.util
import os
import sys
import types
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

UTILS_DIR = ROOT / "Lootere" / "utils"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_lootere_pkg = sys.modules.setdefault("Lootere", types.ModuleType("Lootere"))
_lootere_pkg.__path__ = [str(ROOT / "Lootere")]
_utils_pkg = sys.modules.setdefault("Lootere.utils", types.ModuleType("Lootere.utils"))
_utils_pkg.__path__ = [str(UTILS_DIR)]

if "Lootere.utils.smart_search_engine" not in sys.modules:
    _load_module("Lootere.utils.smart_search_engine", UTILS_DIR / "smart_search_engine.py")

engine = _load_module(
    "Lootere.utils.notification_engine", UTILS_DIR / "notification_engine.py"
)
imdb = _load_module("Lootere.utils.imdb_metadata", UTILS_DIR / "imdb_metadata.py")
setattr(_utils_pkg, "notification_engine", engine)
setattr(_utils_pkg, "imdb_metadata", imdb)

SCRIPT = _load_module("Script", ROOT / "Script.py")
script = SCRIPT.script

GB = 1024 ** 3


class FakeMedia:
    def __init__(self, file_name, file_size=1 * GB, file_id="file-1", unique="unique-1"):
        self.file_name = file_name
        self.file_size = file_size
        self.file_id = file_id
        self.file_unique_id = unique


FULL_MOVIE_NODE = {
    "id": "tt1932660",
    "titleText": {"text": "Kongsi"},
    "originalTitleText": {"text": "Kongsi"},
    "releaseYear": {"year": 2011},
    "ratingsSummary": {"aggregateRating": 5.2, "voteCount": 153},
    "genres": {"genres": [{"text": "Action"}, {"text": "Comedy"}]},
    "plot": {"plotText": {"plainText": "A murderer is sent to curb secret societies in Kuala Lumpur."}},
    "runtime": {"seconds": 5400},
    "spokenLanguages": {"spokenLanguages": [{"text": "Malay"}]},
    "primaryImage": {"url": "https://m.media-amazon.com/images/M/poster.jpg"},
    "titleType": {"id": "movie", "text": "Movie"},
}

FULL_SERIES_NODE = {
    "id": "tt29625288",
    "titleText": {"text": "Akka"},
    "originalTitleText": {"text": "Akka"},
    "releaseYear": {"year": 2026},
    "ratingsSummary": {"aggregateRating": 7.4},
    "genres": {"genres": [{"text": "Crime"}, {"text": "Drama"}]},
    "plot": {"plotText": {"plainText": "A woman fights a powerful crime network."}},
    "runtime": {"seconds": 2700},
    "spokenLanguages": {"spokenLanguages": [{"text": "Hindi"}]},
    "primaryImage": {"url": "https://m.media-amazon.com/images/M/akka.jpg"},
    "titleType": {"id": "tvSeries", "text": "TV Series"},
}


def movie_event(file_name="Kongsi.2011.720p.Hindi.mkv", unique="movie-1"):
    return engine.build_event(FakeMedia(file_name, unique=unique))


# ---------------------------------------------------------------------------
# In-memory Mongo doubles
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, upserted_id=None, modified_count=0):
        self.upserted_id = upserted_id
        self.modified_count = modified_count


def _match(doc, query):
    for key, expected in (query or {}).items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            for op, value in expected.items():
                if op == "$in" and actual not in value:
                    return False
                if op == "$ne" and actual == value:
                    return False
                if op == "$lte" and not (actual is not None and actual <= value):
                    return False
                if op == "$lt" and not (actual is not None and actual < value):
                    return False
                if op == "$gte" and not (actual is not None and actual >= value):
                    return False
                if op == "$gt" and not (actual is not None and actual > value):
                    return False
        elif actual != expected:
            return False
    return True


class _Cursor:
    def __init__(self, docs, sort_spec=None):
        self._docs = [dict(doc) for doc in docs]
        if sort_spec:
            for key, direction in reversed(list(sort_spec)):
                self._docs.sort(
                    key=lambda doc: (doc.get(key) is None, doc.get(key)),
                    reverse=(direction < 0),
                )

    def limit(self, value):
        self._docs = self._docs[:value]
        return self

    def sort(self, spec, direction=None):
        if direction is not None:
            spec = [(spec, direction)]
        self._docs = _Cursor(self._docs, spec).to_list()
        return self

    def to_list(self):
        return self._docs

    def __aiter__(self):
        self._iter = iter([dict(doc) for doc in self._docs])
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self):
        self.docs = []
        self._counter = 0

    def _next_id(self):
        self._counter += 1
        return self._counter

    async def create_index(self, *args, **kwargs):
        return "idx"

    async def insert_one(self, doc):
        stored = dict(doc)
        stored.setdefault("_id", self._next_id())
        self.docs.append(stored)
        return _Result(upserted_id=stored["_id"])

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if _match(doc, query))

    def find(self, query=None, projection=None):
        return _Cursor([doc for doc in self.docs if _match(doc, query or {})])

    async def find_one(self, query, sort=None):
        docs = _Cursor([doc for doc in self.docs if _match(doc, query)], sort).to_list()
        return dict(docs[0]) if docs else None

    def _apply(self, doc, update):
        for key, value in (update.get("$set") or {}).items():
            doc[key] = value
        for key, value in (update.get("$setOnInsert") or {}).items():
            doc.setdefault(key, value)

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if _match(doc, query):
                self._apply(doc, update)
                return _Result(modified_count=1)
        if upsert:
            new_doc = {k: v for k, v in (query or {}).items() if not isinstance(v, dict)}
            new_doc["_id"] = self._next_id()
            self._apply(new_doc, update)
            self.docs.append(new_doc)
            return _Result(upserted_id=new_doc["_id"])
        return _Result()

    async def update_many(self, query, update):
        count = 0
        for doc in self.docs:
            if _match(doc, query):
                self._apply(doc, update)
                count += 1
        return _Result(modified_count=count)

    async def find_one_and_update(self, query, update, sort=None, return_document=True):
        docs = _Cursor([doc for doc in self.docs if _match(doc, query)], sort).to_list()
        if not docs:
            return None
        target = next(doc for doc in self.docs if doc["_id"] == docs[0]["_id"])
        self._apply(target, update)
        return dict(target)


class FakeDatabase(dict):
    def __init__(self):
        super().__init__()
        for name in (
            engine.EVENTS_COLLECTION,
            engine.DELIVERIES_COLLECTION,
            engine.BATCHES_COLLECTION,
            engine.METADATA_COLLECTION,
            engine.DIGESTS_COLLECTION,
            engine.AUDIT_COLLECTION,
            "settings",
        ):
            self[name] = FakeCollection()


class FakeMessage:
    def __init__(self, chat_id, text):
        self.chat_id = chat_id
        self.text = text
        self.replies = []
        self.sent = []
        self.message_id = 1

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return self

    async def edit_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return self

    async def delete(self):
        return True


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeQuery:
    def __init__(self, user_id, data="autonotif#stats"):
        self.from_user = FakeUser(user_id)
        self.data = data
        self.answers = []
        self.message = FakeMessage(user_id, "panel")

    async def answer(self, text="", show_alert=False):
        self.answers.append((text, show_alert))
        return True


class FakeBot:
    def __init__(self, failing_messages=(), failing_photos=()):
        self.failing_messages = {str(chat) for chat in failing_messages}
        self.failing_photos = {str(chat) for chat in failing_photos}
        self.messages = []
        self.photos = []
        self.username = "testbot"

    async def send_message(self, chat_id, text, **kwargs):
        if str(chat_id) in self.failing_messages:
            raise RuntimeError("chat unavailable")
        self.messages.append({"chat_id": str(chat_id), "text": text, **kwargs})

        class Message:
            id = len(self.messages)

        return Message()

    async def send_photo(self, chat_id, photo, caption, **kwargs):
        if str(chat_id) in self.failing_photos:
            raise RuntimeError("photo rejected")
        self.photos.append({"chat_id": str(chat_id), "photo": photo, "caption": caption, **kwargs})

        class Message:
            id = len(self.photos)

        return Message()


class FakeClient:
    def __init__(self):
        self.command_calls = []

    async def set_bot_commands(self, commands, scope=None):
        self.command_calls.append((list(commands), scope))


# ---------------------------------------------------------------------------
# Metadata provider tests
# ---------------------------------------------------------------------------
class MetadataProviderTests(unittest.TestCase):
    def test_complete_movie_metadata_is_mapped(self):
        metadata = imdb.metadata_from_node(FULL_MOVIE_NODE)
        self.assertEqual(metadata["title"], "Kongsi")
        self.assertEqual(metadata["year"], "2011")
        self.assertEqual(metadata["rating"], "5.2")
        self.assertEqual(metadata["genres"], "Action, Comedy")
        self.assertEqual(metadata["imdb_id"], "tt1932660")
        self.assertEqual(metadata["languages"], "Malay")
        self.assertEqual(metadata["runtime"], "1h 30m")
        self.assertEqual(metadata["poster"], "https://m.media-amazon.com/images/M/poster.jpg")
        self.assertIn("secret societies", metadata["plot"])

    def test_movie_caption_shows_every_available_field(self):
        event = movie_event()
        metadata = imdb.metadata_from_node(FULL_MOVIE_NODE)
        caption = engine.build_movie_caption(event, metadata, engine.DEFAULT_SETTINGS)
        for expected in (
            "NEW MOVIE UPLOADED",
            "Kongsi (2011)",
            "⭐ IMDb: 5.2/10",
            "🆔 IMDb: tt1932660",
            "🎬 Genre: Action, Comedy",
            "🌐 Language: Hindi",  # event language is kept when present
            "🎞️ Quality: 720p",
            "⏱️ Runtime: 1h 30m",
            "📝 Description:",
            "secret societies",
        ):
            self.assertIn(expected, caption)
        for forbidden in ("None", "N/A", "null"):
            self.assertNotIn(forbidden, caption)

    def test_payload_carries_official_poster(self):
        event = movie_event()
        metadata = imdb.metadata_from_node(FULL_MOVIE_NODE)
        payload = engine.build_payload(
            "owner", "movie", [event], metadata, engine.DEFAULT_SETTINGS
        )
        self.assertEqual(payload["poster"], metadata["poster"])
        self.assertEqual(payload["button_text"], "GET NOW")

    def test_movie_with_no_poster_stays_text_safe(self):
        metadata = imdb.metadata_from_node(FULL_MOVIE_NODE)
        metadata.pop("poster")
        payload = engine.build_payload(
            "owner", "movie", [movie_event()], metadata, engine.DEFAULT_SETTINGS
        )
        self.assertEqual(payload["poster"], "")
        self.assertIn("Kongsi", payload["captions"][0])

    def test_no_imdb_match_returns_reason(self):
        original = imdb.search_titles
        imdb.search_titles = lambda query, timeout=12: []
        try:
            metadata, reason = imdb.lookup_sync("Unknown Film", 1999, "movie")
        finally:
            imdb.search_titles = original
        self.assertEqual(metadata, {})
        self.assertEqual(reason, "no search results")

    def test_ambiguous_movie_title_is_rejected(self):
        candidates = [
            {
                "imdb_id": "tt0000001",
                "title": "Kongsi",
                "year": 2011,
                "kind": "feature",
                "rank": 100,
            },
            {
                "imdb_id": "tt0000002",
                "title": "Kongsi",
                "year": 2011,
                "kind": "feature",
                "rank": 100,
            },
        ]
        match, reason = imdb.select_best_match(candidates, "Kongsi", 2011, "movie")
        self.assertIsNone(match)
        self.assertEqual(reason, "ambiguous match")

    def test_series_match_prefers_series_and_builds_caption(self):
        candidates = [
            {"imdb_id": "tt9990000", "title": "Akka", "year": 2026, "kind": "feature", "rank": 50},
            {
                "imdb_id": "tt29625288",
                "title": "Akka 2026",
                "year": 2026,
                "kind": "tv series",
                "rank": 900,
            },
        ]
        match, reason = imdb.select_best_match(candidates, "Akka", 2026, "series")
        self.assertEqual(reason, "")
        self.assertEqual(match["imdb_id"], "tt29625288")

        events = [
            engine.build_event(
                FakeMedia(
                    f"Akka.2026.S01E{episode:02d}.1080p.Hindi.mkv", unique=f"ep-{episode}"
                )
            )
            for episode in range(1, 4)
        ]
        metadata = imdb.metadata_from_node(FULL_SERIES_NODE)
        captions = engine.build_series_captions(events, metadata, engine.DEFAULT_SETTINGS)
        text = "\n".join(captions)
        for expected in (
            "NEW SERIES EPISODES ADDED",
            "Akka (2026) — Season 1",
            "⭐ IMDb: 7.4/10",
            "🎬 Genre: Crime, Drama",
            "📝 Description:",
            "Total New Episodes: 3",
        ):
            self.assertIn(expected, text)
        for episode in range(1, 4):
            self.assertIn(f"E{episode:02d} S01", text)

    def test_provider_timeout_is_reported(self):
        original = imdb._http_json

        def failing(*args, **kwargs):
            raise imdb.MetadataLookupError("provider unreachable: timed out")

        imdb._http_json = failing
        try:
            metadata, reason = imdb.lookup_sync("Kongsi", 2011, "movie")
        finally:
            imdb._http_json = original
        self.assertEqual(metadata, {})
        self.assertIn("timed out", reason)

    def test_invalid_poster_url_is_rejected(self):
        usable, reason = imdb._poster_check_sync("not-a-url")
        self.assertFalse(usable)
        self.assertIn("invalid poster URL", reason)

        original = imdb.urllib.request.urlopen

        def missing(*args, **kwargs):
            raise urllib.error.HTTPError(
                "https://example.com/missing.jpg", 404, "Not Found", {}, None
            )

        imdb.urllib.request.urlopen = missing
        try:
            usable, reason = imdb._poster_check_sync("https://example.com/missing.jpg")
        finally:
            imdb.urllib.request.urlopen = original
        self.assertFalse(usable)
        self.assertIn("404", reason)

    def test_valid_poster_is_accepted(self):
        class _Headers:
            @staticmethod
            def get_content_type():
                return "image/jpeg"

            @staticmethod
            def get(key, default=None):
                return "image/jpeg" if key == "Content-Type" else default

        class Response:
            headers = _Headers()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        original = imdb.urllib.request.urlopen
        imdb.urllib.request.urlopen = lambda *a, **k: Response()
        try:
            usable, reason = imdb._poster_check_sync("https://example.com/poster.jpg")
        finally:
            imdb.urllib.request.urlopen = original
        self.assertTrue(usable)
        self.assertEqual(reason, "")


class MetadataCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDatabase()
        engine.set_database(self.db)
        self.settings = dict(engine.DEFAULT_SETTINGS)

    async def asyncTearDown(self):
        engine.set_database(None)

    async def test_cache_miss_then_hit(self):
        calls = []

        async def fake_cinemagoer(event, settings):
            calls.append("cinemagoer")
            return {}, "cinemagoer returned no metadata"

        original_cinemagoer = engine._lookup_cinemagoer
        original_public = engine._lookup_public_imdb
        engine._lookup_cinemagoer = fake_cinemagoer

        async def fake_public(event, settings):
            calls.append("imdb")
            return imdb.metadata_from_node(FULL_MOVIE_NODE), ""

        engine._lookup_public_imdb = fake_public
        try:
            event = movie_event()
            metadata = await engine.resolve_metadata(event, self.settings)
            self.assertEqual(metadata["imdb_id"], "tt1932660")
            self.assertEqual(event["metadata_source"], "imdb")
            cached = self.db[engine.METADATA_COLLECTION].docs
            self.assertEqual(len(cached), 1)
            self.assertEqual(cached[0]["source"], "imdb")

            second_event = movie_event(unique="movie-2")
            second = await engine.resolve_metadata(second_event, self.settings)
            self.assertEqual(second["rating"], "5.2")
            # Cache hits keep the original provider name as the metadata source.
            self.assertEqual(second_event["metadata_source"], "imdb")
            self.assertEqual(calls.count("imdb"), 1)
        finally:
            engine._lookup_cinemagoer = original_cinemagoer
            engine._lookup_public_imdb = original_public

    async def test_failure_reason_is_recorded_on_event(self):
        original_cinemagoer = engine._lookup_cinemagoer
        original_public = engine._lookup_public_imdb

        async def fake_cinemagoer(event, settings):
            return {}, "cinemagoer returned no metadata"

        async def fake_public(event, settings):
            return {}, "no search results"

        engine._lookup_cinemagoer = fake_cinemagoer
        engine._lookup_public_imdb = fake_public
        try:
            event = movie_event()
            metadata = await engine.resolve_metadata(event, self.settings)
        finally:
            engine._lookup_cinemagoer = original_cinemagoer
            engine._lookup_public_imdb = original_public

        self.assertEqual(metadata, {})
        self.assertIn("cinemagoer returned no metadata", event["metadata_error"])
        self.assertIn("no search results", event["metadata_error"])

    async def test_override_still_wins_over_providers(self):
        self.assertTrue(
            await engine.override_metadata(
                "Kongsi",
                year="2011",
                rating="9.9",
                poster="https://example.com/manual.jpg",
                plot="Admin corrected plot.",
            )
        )
        original_cinemagoer = engine._lookup_cinemagoer

        async def exploding(event, settings):
            raise AssertionError("provider must not run for an override")

        engine._lookup_cinemagoer = exploding
        try:
            metadata = await engine.resolve_metadata(movie_event(), self.settings)
        finally:
            engine._lookup_cinemagoer = original_cinemagoer
        self.assertEqual(metadata["rating"], "9.9")
        self.assertEqual(metadata["poster"], "https://example.com/manual.jpg")


# ---------------------------------------------------------------------------
# Admin command tests
# ---------------------------------------------------------------------------
def _load_admin_plugin():
    if "info" not in sys.modules:
        info_stub = types.ModuleType("info")
        info_stub.ADMINS = [111, 222]
        sys.modules["info"] = info_stub
    name = "plugins.auto_notifications"
    if name in sys.modules:
        return sys.modules[name]
    return _load_module(name, ROOT / "plugins" / "auto_notifications.py")


class AdminCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDatabase()
        engine.set_database(self.db)
        self.plugin = _load_admin_plugin()

    async def asyncTearDown(self):
        engine.set_database(None)

    def test_notification_is_a_registered_manager_command(self):
        self.assertIn("notification", self.plugin.MANAGER_COMMANDS)
        self.assertIn("autonotif", self.plugin.MANAGER_COMMANDS)
        self.assertTrue(callable(self.plugin.auto_notification_manager))
        self.assertTrue(callable(self.plugin.auto_notification_callback))

    def test_notification_is_in_admin_help_text(self):
        self.assertIn("/notification", script.ADMIC_TXT)

    async def test_command_registered_in_telegram_admin_menu(self):
        client = FakeClient()
        registered = await self.plugin.register_admin_commands(client)
        self.assertEqual(registered, 2)
        self.assertEqual(len(client.command_calls), 2)
        for commands, scope in client.command_calls:
            names = [command.command for command in commands]
            self.assertIn("notification", names)
            self.assertEqual(scope.type, "chat")
            self.assertIn(scope.chat_id, {111, 222})

    async def test_registration_is_restart_safe(self):
        client = FakeClient()
        await self.plugin.register_admin_commands(client)
        await self.plugin.register_admin_commands(client)
        self.assertEqual(len(client.command_calls), 4)

    def test_bot_startup_registers_admin_menu(self):
        source = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn("register_admin_commands", source)
        self.assertIn("plugins.auto_notifications", source)

    async def test_admin_can_open_manager(self):
        message = FakeMessage(111, "/notification")
        message.from_user = FakeUser(111)
        await self.plugin.auto_notification_manager(None, message)
        self.assertTrue(message.replies)
        self.assertIn("AUTO NOTIFICATION MANAGER", message.replies[0][0])

    async def test_unauthorized_user_is_denied(self):
        message = FakeMessage(999, "/notification")
        message.from_user = FakeUser(999)
        await self.plugin.auto_notification_manager(None, message)
        self.assertIn("restricted", message.replies[0][0])

    async def test_unauthorized_callback_is_denied(self):
        query = FakeQuery(999)
        await self.plugin.auto_notification_callback(None, query)
        self.assertEqual(query.answers[0][0], "Admins only.")
        self.assertTrue(query.answers[0][1])
        self.assertEqual(query.message.replies, [])

    def test_existing_admin_commands_are_not_removed(self):
        # The plugin must stay additive: no other plugin file was rewritten.
        plugin_files = {path.name for path in (ROOT / "plugins").glob("*.py")}
        for expected in (
            "commands.py",
            "broadcast.py",
            "channel.py",
            "index.py",
            "pm_filter.py",
        ):
            self.assertIn(expected, plugin_files)
        source = (ROOT / "plugins" / "auto_notifications.py").read_text(encoding="utf-8")
        self.assertIn("auto_notifications_set", source)
        self.assertIn("auto_notifications_override", source)


# ---------------------------------------------------------------------------
# Delivery regression tests
# ---------------------------------------------------------------------------
class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDatabase()
        self.previous_db = engine._db_handle
        self.previous_get_settings = engine.get_settings
        self.previous_resolve = engine.resolve_metadata
        self.previous_poster_usable = engine._poster_usable
        engine.set_database(self.db)
        self.settings = dict(engine.DEFAULT_SETTINGS)
        self.settings.update(
            {
                "enabled": True,
                "channel_id": "-100111",
                "channel_enabled": True,
                "group_id": "-100222",
                "group_enabled": True,
                "button_url": "https://t.me/examplegroup",
                "batch_window_seconds": 0,
            }
        )

        async def fake_get_settings(force=False):
            return dict(self.settings)

        async def fake_resolve(event, settings):
            event["metadata_source"] = "test"
            return imdb.metadata_from_node(FULL_MOVIE_NODE)

        async def poster_usable(poster):
            return True

        engine.get_settings = fake_get_settings
        engine.resolve_metadata = fake_resolve
        engine._poster_usable = poster_usable

    async def asyncTearDown(self):
        engine.set_database(self.previous_db)
        engine.get_settings = self.previous_get_settings
        engine.resolve_metadata = self.previous_resolve
        engine._poster_usable = self.previous_poster_usable

    async def _queue_movie(self, unique="movie-1"):
        await engine.record_upload_event(
            FakeMedia("Kongsi.2011.720p.Hindi.mkv", unique=unique)
        )
        await engine.process_once(FakeBot())

    async def test_photo_caption_and_button_reach_channel_and_group(self):
        bot = FakeBot()
        await engine.record_upload_event(FakeMedia("Kongsi.2011.720p.Hindi.mkv"))
        await engine.process_once(bot)
        self.assertEqual(len(bot.photos), 2)
        chat_ids = {photo["chat_id"] for photo in bot.photos}
        self.assertEqual(chat_ids, {"-100111", "-100222"})
        for photo in bot.photos:
            self.assertEqual(photo["photo"], FULL_MOVIE_NODE["primaryImage"]["url"])
            self.assertIn("Kongsi (2011)", photo["caption"])
            self.assertIsNotNone(photo["reply_markup"])
            button = photo["reply_markup"].inline_keyboard[0][0]
            self.assertEqual(button.text, "GET NOW")
            self.assertEqual(button.url, "https://t.me/examplegroup")

    async def test_channel_failure_does_not_block_group(self):
        bot = FakeBot(failing_photos={"-100111"})
        await engine.record_upload_event(FakeMedia("Kongsi.2011.720p.Hindi.mkv"))
        await engine.process_once(bot)
        # Channel photo failed, so it falls back to text; group must still be sent.
        self.assertIn("-100222", {photo["chat_id"] for photo in bot.photos})
        deliveries = self.db[engine.DELIVERIES_COLLECTION].docs
        group = [doc for doc in deliveries if doc["destination_type"] == "group"]
        self.assertEqual(group[0]["status"], "SENT")

    async def test_group_failure_does_not_block_channel(self):
        original_get_settings = engine.get_settings

        async def settings_with_broken_group(force=False):
            broken = dict(self.settings)
            broken["group_id"] = "-100999"
            return broken

        engine.get_settings = settings_with_broken_group
        try:
            bot = FakeBot(failing_messages={"-100999"})
            await engine.record_upload_event(FakeMedia("Kongsi.2011.720p.Hindi.mkv"))
            await engine.process_once(bot)
        finally:
            engine.get_settings = original_get_settings
        self.assertIn("-100111", {photo["chat_id"] for photo in bot.photos})
        deliveries = self.db[engine.DELIVERIES_COLLECTION].docs
        channel = [doc for doc in deliveries if doc["destination_type"] == "channel"]
        self.assertEqual(channel[0]["status"], "SENT")

    async def test_invalid_poster_falls_back_to_text(self):
        original_resolve = engine.resolve_metadata

        async def metadata_without_poster(event, settings):
            data = imdb.metadata_from_node(FULL_MOVIE_NODE)
            data["poster"] = "https://example.com/broken.jpg"
            return data

        async def unusable(poster):
            return False

        engine.resolve_metadata = metadata_without_poster
        engine._poster_usable = unusable
        try:
            bot = FakeBot()
            await engine.record_upload_event(FakeMedia("Kongsi.2011.720p.Hindi.mkv"))
            await engine.process_once(bot)
        finally:
            engine.resolve_metadata = original_resolve
        self.assertEqual(bot.photos, [])
        self.assertEqual(len(bot.messages), 2)
        self.assertIn("Kongsi (2011)", bot.messages[0]["text"])

    async def test_long_caption_is_sent_as_text_not_failed(self):
        bot = FakeBot()
        delivery = {
            "chat_id": "-100111",
            "caption": "x" * 1200,
            "poster": FULL_MOVIE_NODE["primaryImage"]["url"],
            "button_text": "GET NOW",
            "button_url": "https://t.me/examplegroup",
        }
        await engine._deliver(bot, delivery)
        self.assertEqual(bot.photos, [])
        self.assertEqual(len(bot.messages), 1)
        self.assertEqual(len(bot.messages[0]["text"]), 1200)

    async def test_send_photo_permanent_error_falls_back_to_text(self):
        class RejectingPhotoBot(FakeBot):
            async def send_photo(self, chat_id, photo, caption, **kwargs):
                raise RuntimeError("PHOTO_INVALID_DIMENSIONS")

        bot = RejectingPhotoBot()
        await engine.record_upload_event(FakeMedia("Kongsi.2011.720p.Hindi.mkv"))
        await engine.process_once(bot)
        self.assertEqual(bot.photos, [])
        self.assertEqual(len(bot.messages), 2)

    async def test_no_duplicate_notifications(self):
        bot = FakeBot()
        await engine.record_upload_event(FakeMedia("Kongsi.2011.720p.Hindi.mkv"))
        await engine.process_once(bot)
        sent_after_first = len(bot.photos)
        await engine.process_once(bot)
        self.assertEqual(len(bot.photos), sent_after_first)

    async def test_weekly_digest_still_works(self):
        await engine.record_upload_event(FakeMedia("Kongsi.2011.720p.Hindi.mkv"))
        await engine.process_once(FakeBot())
        bot = FakeBot()
        digest_id = await engine.force_publish_weekly_digest(bot, admin_id=111)
        self.assertTrue(digest_id)
        await engine.process_deliveries(bot)
        self.assertTrue(bot.messages)
        self.assertIn("WEEKLY UPLOAD REPORT", bot.messages[0]["text"])
        self.assertEqual(len(self.db[engine.DIGESTS_COLLECTION].docs), 1)


if __name__ == "__main__":
    unittest.main()
