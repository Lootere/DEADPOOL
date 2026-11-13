import importlib.util
import os
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
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
    _load_module(
        "Lootere.utils.smart_search_engine",
        UTILS_DIR / "smart_search_engine.py",
    )

engine = _load_module(
    "Lootere.utils.notification_engine",
    UTILS_DIR / "notification_engine.py",
)

GB = 1024 ** 3


class FakeMedia:
    def __init__(self, file_name, file_size=1 * GB, file_id="file-1", unique="unique-1"):
        self.file_name = file_name
        self.file_size = file_size
        self.file_id = file_id
        self.file_unique_id = unique


class EventTests(unittest.TestCase):
    def test_event_id_is_deterministic_and_unique(self):
        media = FakeMedia("Example.Movie.2025.1080p.Hindi.mkv")
        first = engine.build_event(media)
        second = engine.build_event(media)
        self.assertEqual(first["event_id"], second["event_id"])
        other = engine.build_event(FakeMedia("Other.Movie.2025.mkv", unique="unique-2"))
        self.assertNotEqual(first["event_id"], other["event_id"])

    def test_movie_event_classification(self):
        event = engine.build_event(FakeMedia("Example.Movie.2025.1080p.Hindi.mkv"))
        self.assertEqual(event["category"], "movie")
        self.assertEqual(event["title"], "Example Movie")
        self.assertEqual(event["quality"], "1080p")
        self.assertEqual(event["language"], "Hindi")
        self.assertEqual(event["year"], "2025")

    def test_series_event_has_episode_identity(self):
        event = engine.build_event(FakeMedia("Akka.2026.S01E02.720p.Hindi.mkv"))
        self.assertEqual(event["category"], "series")
        self.assertEqual(event["season"], 1)
        self.assertEqual(event["episode"], 2)
        self.assertEqual(event["episode_code"], "E02 S01")
        self.assertEqual(event["series_key"], "akka")

    def test_file_stem_fallback(self):
        event = engine.build_event(FakeMedia("2025.mkv"))
        self.assertTrue(event["title"])


class CaptionTests(unittest.TestCase):
    def full_metadata(self):
        return {
            "title": "Example Movie",
            "year": "2025",
            "rating": "7.8",
            "genres": "Action, Thriller",
            "languages": "Hindi, English",
            "plot": "A short and informative movie description.",
            "poster": "https://example.com/poster.jpg",
            "imdb_id": "tt1234567",
            "runtime": "2h 10m",
            "certificates": "UA",
        }

    def test_movie_caption_contains_available_metadata(self):
        event = engine.build_event(FakeMedia("Example.Movie.2025.1080p.Hindi.mkv"))
        caption = engine.build_movie_caption(event, self.full_metadata(), engine.DEFAULT_SETTINGS)
        for value in (
            "NEW MOVIE DROP",
            "Example Movie (2025)",
            "7.8/10",
            "Action, Thriller",
            "Hindi",
            "1080p",
            "A short and informative movie description.",
            "tt1234567",
        ):
            self.assertIn(value, caption)

    def test_movie_caption_omits_unknown_fields(self):
        event = engine.build_event(FakeMedia("Plain.Movie.2025.mkv"))
        caption = engine.build_movie_caption(event, {}, engine.DEFAULT_SETTINGS)
        self.assertNotIn("None", caption)
        self.assertNotIn("N/A", caption)
        self.assertNotIn("null", caption)
        self.assertNotIn("⭐ IMDb:", caption)
        self.assertIn("Plain Movie", caption)

    def test_metadata_matching_rejects_wrong_year_and_title(self):
        event = engine.build_event(FakeMedia("Example.Movie.2025.1080p.mkv"))
        self.assertTrue(engine._metadata_matches(event, {"title": "Example Movie", "year": "2025"}))
        self.assertFalse(engine._metadata_matches(event, {"title": "Example Movie", "year": "1999"}))
        self.assertFalse(
            engine._metadata_matches(event, {"title": "Completely Different", "year": "2025"})
        )

    def test_series_caption_lists_all_episodes(self):
        events = [
            engine.build_event(
                FakeMedia(f"Akka.2026.S01E{index:02d}.{'720p' if index % 2 else '1080p'}.Hindi.mkv",
                          unique=f"u{index}")
            )
            for index in range(1, 6)
        ]
        captions = engine.build_series_captions(events, {}, engine.DEFAULT_SETTINGS)
        text = "\n".join(captions)
        self.assertIn("NEW SERIES EPISODES DROP", text)
        self.assertIn("Akka", text)
        for index in range(1, 6):
            self.assertIn(f"E{index:02d} S01", text)
        self.assertIn("Total New Episodes: 5", text)
        self.assertIn("720p / 1080p", text)

    def test_large_series_batch_is_paginated_without_omissions(self):
        events = [
            {
                "event_id": f"e{index}",
                "category": "series",
                "title": "Long Show",
                "year": "2025",
                "season": 1,
                "episode": index,
                "episode_code": f"E{index:02d} S01",
                "quality": "1080p",
                "language": "Hindi",
                "file_name": "Long.Show.S01E01.1080p.Hindi.mkv",
                "series_key": "long show",
            }
            for index in range(1, 121)
        ]
        captions = engine.build_series_captions(events, {}, engine.DEFAULT_SETTINGS)
        self.assertGreater(len(captions), 1)
        found = set()
        for caption in captions:
            self.assertLessEqual(len(caption), 4096)
            found.update(re.findall(r"E\d{2,3} S01", caption))
        self.assertEqual(len(found), 120)
        self.assertIn("Part 1/", captions[0])

    def test_preview_builders(self):
        # preview_notification is async; build the same sample synchronously here.
        series_events = [
            {
                "event_id": "p",
                "category": "series",
                "title": "Example Series",
                "year": "2026",
                "season": 1,
                "episode": 1,
                "episode_code": "E01 S01",
                "quality": "1080p",
                "language": "Hindi",
                "file_name": "Example.Series.S01E01.1080p.Hindi.mkv",
                "series_key": "example series",
            }
        ]
        self.assertIn("Example Series", engine.build_series_captions(
            series_events, {}, engine.DEFAULT_SETTINGS)[0])


class DigestTests(unittest.TestCase):
    def build_events(self):
        events = []
        for index in range(3):
            events.append(
                {
                    "event_id": f"m{index}",
                    "category": "movie",
                    "title": f"Movie {chr(65 + index)}",
                    "year": "2025",
                    "quality": "1080p" if index % 2 == 0 else "720p",
                    "language": "Hindi",
                    "file_name": "x.mkv",
                }
            )
        for index in range(1, 6):
            events.append(
                {
                    "event_id": f"s{index}",
                    "category": "series",
                    "title": "Series C",
                    "year": "2026",
                    "season": 1,
                    "episode": index,
                    "episode_code": f"E{index:02d} S01",
                    "quality": "720p",
                    "language": "English",
                    "file_name": "y.mkv",
                    "series_key": "series c",
                }
            )
        return events

    def test_summary_counts(self):
        summary = engine.summarize_events(self.build_events())
        self.assertEqual(summary["movie_count"], 3)
        self.assertEqual(summary["series_count"], 1)
        self.assertEqual(summary["episode_count"], 5)
        self.assertEqual(summary["file_count"], 8)
        self.assertEqual(summary["top_qualities"][0][0], "720p")

    def test_digest_caption_reports_every_section(self):
        start = datetime(2026, 11, 9, tzinfo=timezone.utc)
        end = start + timedelta(days=7)
        caption = engine.build_digest_caption(
            self.build_events(), start, end, engine.DEFAULT_SETTINGS
        )
        self.assertIn("WEEKLY UPLOAD REPORT", caption)
        self.assertIn("Movies: 3", caption)
        self.assertIn("Series: 1", caption)
        self.assertIn("Episodes: 5", caption)
        self.assertIn("Total New Files: 8", caption)
        self.assertIn("Movie A", caption)
        self.assertIn("Series C", caption)
        self.assertIn("TOP LANGUAGES", caption)

    def test_empty_period_still_renders(self):
        caption = engine.build_digest_caption(
            [],
            datetime(2026, 11, 9, tzinfo=timezone.utc),
            datetime(2026, 11, 16, tzinfo=timezone.utc),
            engine.DEFAULT_SETTINGS,
        )
        self.assertIn("Movies: 0", caption)
        self.assertIn("No new movies this week.", caption)

    def test_pagination_never_drops_lines(self):
        lines = [f"Line {index}" for index in range(500)]
        pages = engine.paginate_text("\n".join(lines), limit=500)
        self.assertGreater(len(pages), 1)
        rejoined = "\n".join(pages)
        for index in range(500):
            self.assertIn(f"Line {index}", rejoined)
        for page in pages:
            self.assertLessEqual(len(page), 500)

    def test_most_recent_sunday(self):
        tz = engine.get_timezone("Asia/Kolkata")
        now = datetime(2026, 11, 10, 12, 0, tzinfo=tz)  # Tuesday
        sunday = engine.most_recent_sunday(now, (21, 0))
        self.assertEqual(sunday.weekday(), 6)
        self.assertLessEqual(sunday, now)
        self.assertEqual(sunday.hour, 21)

    def test_digest_period_boundaries_across_timezones(self):
        tz = engine.get_timezone("America/New_York")
        now = datetime(2026, 11, 8, 22, 0, tzinfo=tz)  # Sunday after 21:00
        sunday = engine.most_recent_sunday(now, (21, 0))
        self.assertEqual(sunday.date().isoformat(), "2026-11-08")


class DeliveryPolicyTests(unittest.TestCase):
    def test_url_validation(self):
        valid = (
            "https://t.me/examplegroup",
            "https://telegram.me/example",
            "http://example.com/page",
        )
        invalid = (
            "",
            "javascript:alert(1)",
            "tg://resolve?domain=x",
            "ftp://example.com",
            "https://",
            "not a url",
        )
        for url in valid:
            self.assertTrue(engine.validate_button_url(url), url)
        for url in invalid:
            self.assertFalse(engine.validate_button_url(url), url)

    def test_button_text_normalization(self):
        self.assertEqual(engine.normalize_button_text("  GET   NOW "), "GET NOW")
        self.assertEqual(engine.normalize_button_text(""), "GET NOW")
        self.assertEqual(len(engine.normalize_button_text("x" * 100)), 64)

    def test_error_classification(self):
        class FloodWait(Exception):
            pass

        class ChatAdminRequired(Exception):
            pass

        class NetworkError(Exception):
            pass

        self.assertEqual(engine.classify_telegram_error(FloodWait()), "flood")
        self.assertEqual(engine.classify_telegram_error(ChatAdminRequired()), "permanent")
        self.assertEqual(engine.classify_telegram_error(NetworkError()), "transient")

    def test_backoff_is_bounded(self):
        previous = 0
        for attempt in range(1, 8):
            delay = engine.retry_delay_seconds(attempt)
            self.assertGreaterEqual(delay, previous)
            self.assertLessEqual(delay, 3600)
            previous = delay
        self.assertEqual(engine.retry_delay_seconds(99), 3600)

    def test_error_text_hides_invite_links(self):
        text = engine.safe_error_text("failed https://t.me/+PrivateInvite123 and bot123:secret")
        self.assertNotIn("PrivateInvite123", text)
        self.assertNotIn("secret", text)

    def test_episode_sorting(self):
        ordered = sorted(["E10 S02", "E01 S02", "E02 S01"], key=engine.episode_sort_key)
        self.assertEqual(ordered, ["E02 S01", "E01 S02", "E10 S02"])

    def test_metadata_value_cleanup(self):
        for value in (None, "None", "N/A", "null", "  "):
            self.assertEqual(engine.clean_metadata_value(value), "")
        self.assertEqual(engine.clean_metadata_value("  Action ,  Thriller "), "Action , Thriller")


class IntegrationAuditTests(unittest.TestCase):
    def test_indexing_hooks_present(self):
        channel = (ROOT / "plugins" / "channel.py").read_text(encoding="utf-8")
        index = (ROOT / "plugins" / "index.py").read_text(encoding="utf-8")
        self.assertIn("record_upload_event(media)", channel)
        self.assertIn("record_upload_event(media)", index)
        self.assertLess(channel.index("await save_file(media)"), channel.index("record_upload_event(media)"))
        self.assertLess(index.index("await save_file(media)"), index.index("record_upload_event(media)"))

    def test_service_started_from_bot_init(self):
        bot_source = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn("start_notification_services", bot_source)
        self.assertIn("set_notification_database", bot_source)

    def test_search_button_formatter_untouched(self):
        source = (ROOT / "plugins" / "pm_filter.py").read_text(encoding="utf-8")
        self.assertEqual(
            source.count("format_file_result_button(file.file_name, file.file_size)"),
            source.count("files#{file.file_id}"),
        )
        self.assertNotIn("notification_engine", source)

    def test_no_duplicate_digest_engine(self):
        hits = [
            path
            for path in (ROOT / "plugins").glob("*.py")
            if "weekly_digest_history" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(hits, [])

    def test_admin_manager_admin_gated(self):
        source = (ROOT / "plugins" / "auto_notifications.py").read_text(encoding="utf-8")
        self.assertIn("_is_admin(query.from_user.id)", source)
        self.assertIn("_is_admin(message.from_user.id)", source)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# In-memory persistence double (exercises the async queue without MongoDB)
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
    def __init__(self, docs, sort_spec=None, limit=None):
        docs = [dict(doc) for doc in docs]
        if sort_spec:
            for key, direction in reversed(list(sort_spec)):
                docs.sort(
                    key=lambda doc: (doc.get(key) is None, doc.get(key)),
                    reverse=(direction < 0),
                )
        if limit:
            docs = docs[:limit]
        self._docs = docs

    def limit(self, value):
        self._docs = self._docs[:value]
        return self

    def sort(self, spec):
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
        cursor = _Cursor([doc for doc in self.docs if _match(doc, query)], sort)
        docs = cursor.to_list()
        return dict(docs[0]) if docs else None

    def _apply(self, doc, update):
        for key, value in (update.get("$set") or {}).items():
            doc[key] = value
        for key, value in (update.get("$setOnInsert") or {}).items():
            doc.setdefault(key, value)
        for key, value in (update.get("$addToSet") or {}).items():
            doc.setdefault(key, [])
            if value not in doc[key]:
                doc[key].append(value)

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if _match(doc, query):
                self._apply(doc, update)
                return _Result(modified_count=1)
        if upsert:
            new_doc = {key: value for key, value in (query or {}).items() if not isinstance(value, dict)}
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
        cursor = _Cursor([doc for doc in self.docs if _match(doc, query)], sort)
        docs = cursor.to_list()
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


class FakeBot:
    def __init__(self, failing_chats=()):
        self.failing_chats = set(str(chat) for chat in failing_chats)
        self.sent = []
        self.username = "testbot"

    async def send_message(self, chat_id, text, **kwargs):
        if str(chat_id) in self.failing_chats:
            raise RuntimeError("chat unavailable")
        self.sent.append((str(chat_id), text))

        class Message:
            id = len(self.sent)

        return Message()

    async def send_photo(self, chat_id, photo, caption, **kwargs):
        return await self.send_message(chat_id, caption, **kwargs)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = FakeDatabase()
        self._previous_db = engine._db_handle
        self._previous_get_settings = engine.get_settings
        self._previous_resolve = engine.resolve_metadata
        self.settings = dict(engine.DEFAULT_SETTINGS)
        self.settings.update(
            {
                "enabled": True,
                "channel_id": "-100111",
                "channel_enabled": True,
                "group_id": "-100222",
                "group_enabled": True,
                "button_url": "https://t.me/examplegroup",
                "batch_window_seconds": 300,
            }
        )

        async def fake_get_settings(force=False):
            return dict(self.settings)

        async def fake_resolve(event, settings):
            return {}

        engine.set_database(self.db)
        engine.get_settings = fake_get_settings
        engine.resolve_metadata = fake_resolve

    async def asyncTearDown(self):
        engine.set_database(self._previous_db)
        engine.get_settings = self._previous_get_settings
        engine.resolve_metadata = self._previous_resolve

    async def test_duplicate_indexing_creates_one_event(self):
        media = FakeMedia("Example.Movie.2025.1080p.Hindi.mkv")
        self.assertTrue(await engine.record_upload_event(media))
        self.assertFalse(await engine.record_upload_event(media))
        self.assertEqual(len(self.db[engine.EVENTS_COLLECTION].docs), 1)

    async def test_series_episodes_grouped_and_series_not_merged(self):
        for episode in (1, 2, 3):
            await engine.record_upload_event(
                FakeMedia(
                    f"Akka.2026.S01E{episode:02d}.720p.Hindi.mkv",
                    unique=f"akka-{episode}",
                )
            )
        for episode in (1, 2):
            await engine.record_upload_event(
                FakeMedia(
                    f"Other.Show.2026.S01E{episode:02d}.720p.Hindi.mkv",
                    unique=f"other-{episode}",
                )
            )
        batches = self.db[engine.BATCHES_COLLECTION].docs
        self.assertEqual(len(batches), 2)
        akka = next(batch for batch in batches if batch["series_key"] == "akka")
        other = next(batch for batch in batches if batch["series_key"] == "other show")
        self.assertEqual(len(akka["event_ids"]), 3)
        self.assertEqual(len(other["event_ids"]), 2)

    async def test_late_episode_after_finalized_creates_new_batch(self):
        await engine.record_upload_event(
            FakeMedia("Akka.2026.S01E01.720p.Hindi.mkv", unique="a1")
        )
        self.db[engine.BATCHES_COLLECTION].docs[0]["state"] = "FINALIZED"
        await engine.record_upload_event(
            FakeMedia("Akka.2026.S01E02.720p.Hindi.mkv", unique="a2")
        )
        states = [batch["state"] for batch in self.db[engine.BATCHES_COLLECTION].docs]
        self.assertEqual(states.count("FINALIZED"), 1)
        self.assertEqual(states.count("OPEN"), 1)

    async def test_destination_failure_does_not_block_other_destination(self):
        payload = {
            "owner_id": "owner1",
            "kind": "movie",
            "captions": ["<b>Test</b>"],
            "poster": "",
            "button_text": "GET NOW",
            "button_url": "https://t.me/examplegroup",
        }
        await engine._create_deliveries("owner1", payload, self.settings)
        bot = FakeBot(failing_chats={"-100111"})
        await engine.process_deliveries(bot)
        deliveries = self.db[engine.DELIVERIES_COLLECTION].docs
        channel = next(item for item in deliveries if item["destination_type"] == "channel")
        group = next(item for item in deliveries if item["destination_type"] == "group")
        self.assertEqual(group["status"], "SENT")
        self.assertIn(channel["status"], {"RETRY_PENDING", "FAILED"})

    async def test_successful_delivery_is_not_repeated(self):
        payload = {
            "owner_id": "owner2",
            "kind": "movie",
            "captions": ["<b>Test</b>"],
            "poster": "",
            "button_text": "GET NOW",
            "button_url": "https://t.me/examplegroup",
        }
        await engine._create_deliveries("owner2", payload, self.settings)
        bot = FakeBot()
        await engine.process_deliveries(bot)
        first_count = len(bot.sent)
        await engine.process_deliveries(bot)
        self.assertEqual(len(bot.sent), first_count)
        for delivery in self.db[engine.DELIVERIES_COLLECTION].docs:
            self.assertEqual(delivery["status"], "SENT")

    async def test_transient_failure_is_retried_then_succeeds(self):
        payload = {
            "owner_id": "owner3",
            "kind": "movie",
            "captions": ["<b>Test</b>"],
            "poster": "",
            "button_text": "GET NOW",
            "button_url": "https://t.me/examplegroup",
        }
        await engine._create_deliveries("owner3", payload, self.settings)

        class FlakyBot(FakeBot):
            def __init__(self):
                super().__init__()
                self.failed_once = False

            async def send_message(self, chat_id, text, **kwargs):
                if not self.failed_once:
                    self.failed_once = True
                    raise RuntimeError("temporary network error")
                return await super().send_message(chat_id, text, **kwargs)

        bot = FlakyBot()
        await engine.process_deliveries(bot)
        pending = [
            doc for doc in self.db[engine.DELIVERIES_COLLECTION].docs
            if doc["status"] == "RETRY_PENDING"
        ]
        self.assertTrue(pending)
        for doc in pending:
            doc["next_retry_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        await engine.process_deliveries(bot)
        sent = [
            doc for doc in self.db[engine.DELIVERIES_COLLECTION].docs
            if doc["status"] == "SENT"
        ]
        self.assertTrue(sent)

    async def test_admin_metadata_override_is_used(self):
        engine.resolve_metadata = self._previous_resolve
        event = engine.build_event(
            FakeMedia("Example.Movie.2025.1080p.Hindi.mkv", unique="override-1")
        )
        self.assertTrue(
            await engine.override_metadata(
                "Example Movie",
                year="2025",
                rating="8.1",
                genres="Action",
                poster="https://example.com/poster.jpg",
                plot="Corrected plot.",
            )
        )
        metadata = await engine.resolve_metadata(event, self.settings)
        self.assertEqual(metadata.get("rating"), "8.1")
        self.assertEqual(metadata.get("poster"), "https://example.com/poster.jpg")

    async def test_movie_event_delivers_to_both_destinations(self):
        await engine.record_upload_event(
            FakeMedia("Example.Movie.2025.1080p.Hindi.mkv", unique="movie-1")
        )
        bot = FakeBot()
        await engine.process_once(bot)
        deliveries = self.db[engine.DELIVERIES_COLLECTION].docs
        self.assertEqual(
            {item["destination_type"] for item in deliveries}, {"channel", "group"}
        )
        self.assertEqual(len([item for item in deliveries if item["status"] == "SENT"]), 2)
        self.assertTrue(bot.sent)

    async def test_both_destinations_disabled_creates_no_delivery(self):
        self.settings["channel_enabled"] = False
        self.settings["group_enabled"] = False
        payload = {
            "owner_id": "owner4",
            "kind": "movie",
            "captions": ["<b>Test</b>"],
            "poster": "",
            "button_text": "GET NOW",
            "button_url": "https://t.me/examplegroup",
        }
        created = await engine._create_deliveries("owner4", payload, self.settings)
        self.assertEqual(created, 0)
        self.assertEqual(self.db[engine.DELIVERIES_COLLECTION].docs, [])
