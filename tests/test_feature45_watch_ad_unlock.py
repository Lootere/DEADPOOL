import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = Path(__file__).resolve().parent.parent

if "Lootere" not in sys.modules:
    sys.modules["Lootere"] = types.ModuleType("Lootere")
if "Lootere.utils" not in sys.modules:
    sys.modules["Lootere.utils"] = types.ModuleType("Lootere.utils")


def _load_util_module(name: str, filename: str):
    path = _ROOT / "Lootere" / "utils" / filename
    spec = importlib.util.spec_from_file_location(f"Lootere.utils.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[f"Lootere.utils.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


button_typography = _load_util_module("button_typography", "button_typography.py")
ad_unlock_mod = _load_util_module("ad_unlock_manager", "ad_unlock_manager.py")

AdUnlockManager = ad_unlock_mod.AdUnlockManager
STATE_CONSUMED = ad_unlock_mod.STATE_CONSUMED
STATE_EXPIRED = ad_unlock_mod.STATE_EXPIRED
STATE_FAILED = ad_unlock_mod.STATE_FAILED
STATE_PENDING_VERIFICATION = ad_unlock_mod.STATE_PENDING_VERIFICATION
STATE_VERIFIED = ad_unlock_mod.STATE_VERIFIED
build_ad_verification_keyboard = ad_unlock_mod.build_ad_verification_keyboard
build_ad_verification_prompt_text = ad_unlock_mod.build_ad_verification_prompt_text
build_ad_verified_delivery_keyboard = ad_unlock_mod.build_ad_verified_delivery_keyboard
build_ad_verified_ready_text = ad_unlock_mod.build_ad_verified_ready_text
build_daily_limit_exhausted_keyboard = ad_unlock_mod.build_daily_limit_exhausted_keyboard
build_daily_limit_exhausted_text = ad_unlock_mod.build_daily_limit_exhausted_text
validate_button_readability = button_typography.validate_button_readability


class _FakeMongoCollection:
    """In-memory mock of MongoDB collection (`ad_unlock_requests`) across bot restarts."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.indexes: list[tuple] = []

    async def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))
        return "idx_ok"

    async def update_one(self, query: dict, update: dict, upsert: bool = False):
        req_id = query.get("unlock_request_id")
        if req_id in self.docs or upsert:
            existing = dict(self.docs.get(req_id, {}))
            existing.update(update.get("$set", {}))
            self.docs[req_id] = existing

    async def find_one(self, query: dict):
        req_id = query.get("unlock_request_id")
        doc = self.docs.get(req_id)
        return dict(doc) if doc else None


class _FakeRawDB:
    def __init__(self) -> None:
        self.ad_unlock_requests = _FakeMongoCollection()


class _FakeDailyQuotaDB:
    """In-memory mock of user daily limit, verify_id store, settings, and MongoDB persistence."""

    def __init__(self, daily_limit: int = 2) -> None:
        self.daily_limit = daily_limit
        self.usage: dict[tuple[int, str], int] = {}
        self.current_date: str = "2026-11-05"
        self.premium_users: set[int] = set()
        self.settings: dict[str, object] = {}
        self.verify_ids: dict[tuple[int, str], dict] = {}
        self.db = _FakeRawDB()

    async def has_premium_access(self, user_id: int) -> bool:
        return user_id in self.premium_users

    def consume_free_file(self, user_id: int) -> tuple[bool, int]:
        if user_id in self.premium_users:
            return True, 0
        key = (user_id, self.current_date)
        current = self.usage.get(key, 0)
        if current >= self.daily_limit:
            return False, current
        self.usage[key] = current + 1
        return True, self.usage[key]

    async def create_verify_id(self, user_id: int, hash_token: str):
        self.verify_ids[(int(user_id), str(hash_token))] = {
            "user_id": int(user_id),
            "hash": str(hash_token),
            "verified": False,
        }

    async def get_verify_id_info(self, user_id: int, hash_token: str):
        return self.verify_ids.get((int(user_id), str(hash_token)))

    async def update_verify_id_info(self, user_id: int, hash_token: str, value: dict):
        rec = self.verify_ids.get((int(user_id), str(hash_token)))
        if rec is not None:
            rec.update(value)

    async def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    async def set_setting(self, key: str, value):
        self.settings[key] = value


class TestFeature45WatchAdUnlock(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.mgr = AdUnlockManager()
        self.fake_db = _FakeDailyQuotaDB(daily_limit=2)

    # 1. Daily limits: Below-limit Free user, At-limit Free user, Daily reset unchanged, Premium user unchanged
    async def test_01_daily_limits_free_reset_and_premium_unchanged(self):
        free_user = 1001
        prem_user = 1099
        self.fake_db.premium_users.add(prem_user)

        # Free user below daily limit receives eligible files normally
        ok1, c1 = self.fake_db.consume_free_file(free_user)
        ok2, c2 = self.fake_db.consume_free_file(free_user)
        self.assertTrue(ok1)
        self.assertEqual(c1, 1)
        self.assertTrue(ok2)
        self.assertEqual(c2, 2)

        # At limit -> blocked
        ok3, c3 = self.fake_db.consume_free_file(free_user)
        self.assertFalse(ok3)
        self.assertEqual(c3, 2)

        # Daily reset on next IST date works unchanged
        self.fake_db.current_date = "2026-11-06"
        ok_next_day, c_next = self.fake_db.consume_free_file(free_user)
        self.assertTrue(ok_next_day)
        self.assertEqual(c_next, 1)

        # Premium user bypasses daily limit completely
        for _ in range(10):
            p_ok, _ = self.fake_db.consume_free_file(prem_user)
            self.assertTrue(p_ok)

    # 2 & 3. Free user at daily limit sees Buy Premium, Watch Ad & Unlock, and Back
    async def test_02_daily_limit_exhausted_ui_and_buy_premium_destination(self):
        text = build_daily_limit_exhausted_text()
        self.assertIn("⚠️ 𝐃𝐀𝐈𝐋𝐘 𝐋𝐈𝐌𝐈𝐓 𝐑𝐄𝐀𝐂𝐇𝐄𝐃", text)
        self.assertIn("Aaj ki free file limit khatam ho gayi hai!", text)
        self.assertIn("File chahiye? Premium le lo, ya ek ad verify karke apni selected file unlock kar lo.", text)

        kb = build_daily_limit_exhausted_keyboard(grp_id=-100123, canonical_file_id="FILE_ABC", pre="files")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        self.assertEqual(len(buttons), 3)
        self.assertEqual(buttons[0].text, "♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』")
        self.assertEqual(buttons[0].callback_data, "premium_info")
        self.assertEqual(buttons[1].text, "✦ 𝐖𝐀𝐓𝐂𝐇 𝐀𝐃 & 𝐔𝐍𝐋𝐎𝐂𝐊")
        self.assertEqual(buttons[1].callback_data, "ad_unlock_start#-100123#files#FILE_ABC")
        self.assertLessEqual(len(buttons[1].callback_data.encode("utf-8")), 64)
        parsed_grp, parsed_pre, parsed_fid = self.mgr.parse_unlock_start_callback(
            buttons[1].callback_data, default_grp_id=-100123
        )
        self.assertEqual((parsed_grp, parsed_pre, parsed_fid), (-100123, "files", "FILE_ABC"))
        self.assertEqual(buttons[2].text, "◁ 𝐁𝐀𝐂𝐊")
        self.assertEqual(buttons[2].callback_data, "start")

        for b in buttons:
            res = validate_button_readability(b.text)
            self.assertTrue(res["is_valid"])
            self.assertTrue(res["zero_colour_emojis"])

    # 4, 5, 6, 7. File Binding: Verified file A succeeds once, File B fails using File A's auth, quota remains exhausted
    async def test_03_file_binding_and_one_time_consumption(self):
        user_id = 1003
        self.fake_db.consume_free_file(user_id)
        self.fake_db.consume_free_file(user_id)
        self.assertFalse(self.fake_db.consume_free_file(user_id)[0])

        # Create request for FILE_A
        ok, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_A",
            grp_id=0,
            file_name="Deadpool.2024.1080p.mkv",
            user_db=self.fake_db,
        )
        self.assertTrue(ok)
        req_id = req["unlock_request_id"]
        token = req["verification_attempt_id"]

        # Verify that verify_id record was created in existing verify_id store
        v_info = await self.fake_db.get_verify_id_info(user_id, token)
        self.assertIsNotNone(v_info)
        self.assertFalse(v_info["verified"])

        # Complete verification
        v_ok, _, v_req = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id=token,
            user_db=self.fake_db,
        )
        self.assertTrue(v_ok)
        self.assertEqual(v_req["authorization_status"], STATE_VERIFIED)
        v_info_after = await self.fake_db.get_verify_id_info(user_id, token)
        self.assertTrue(v_info_after["verified"])

        # Attempting to redeem FILE_A's authorization for FILE_B MUST FAIL
        wrong_file_ok, wrong_file_msg, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            requested_file_id="FILE_B",
            user_db=self.fake_db,
        )
        self.assertFalse(wrong_file_ok)
        self.assertIn("doosri file ke liye nahi", wrong_file_msg)

        # Deliver FILE_A -> succeeds once
        d_ok, _, d_req = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            requested_file_id="FILE_A",
            user_db=self.fake_db,
        )
        self.assertTrue(d_ok)
        self.assertEqual(d_req["canonical_file_id"], "FILE_A")
        await self.mgr.mark_delivery_consumed(req_id, delivery_reference="msg_999", user_db=self.fake_db)

        # Second request for FILE_A using the same authorization -> MUST FAIL (one-time only)
        d2_ok, d2_msg, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            requested_file_id="FILE_A",
            user_db=self.fake_db,
        )
        self.assertFalse(d2_ok)
        self.assertIn("pehle hi use ho chuka", d2_msg)

        # Daily free quota MUST still be exhausted (not reset) and user MUST NOT have Premium
        self.assertFalse(self.fake_db.consume_free_file(user_id)[0])
        self.assertFalse(await self.fake_db.has_premium_access(user_id))

        # Requesting a second file FILE_B requires a brand new ad verification
        ok_b, _, req_b = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_B",
            grp_id=0,
            file_name="Wolverine.2024.720p.mkv",
            user_db=self.fake_db,
        )
        self.assertTrue(ok_b)
        self.assertNotEqual(req_b["unlock_request_id"], req_id)
        self.assertEqual(req_b["authorization_status"], STATE_PENDING_VERIFICATION)

    # 8. Direct callback bypass / Incomplete / Failed / Untrusted verification signal
    async def test_04_direct_callback_bypass_and_failed_verification_blocked(self):
        user_id = 1004
        ok, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_UNVERIFIED",
            user_db=self.fake_db,
        )
        self.assertTrue(ok)
        req_id = req["unlock_request_id"]

        # Direct callback bypass attempt (`ad_deliver#<req_id>`) without completing verification
        d_ok, d_msg, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            user_db=self.fake_db,
        )
        self.assertFalse(d_ok)
        self.assertIn("verification abhi poora nahi hua", d_msg)

        # Untrusted / forged verification token fails closed
        v_ok, _, _ = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id="FORGED_SIGNAL_999",
            user_db=self.fake_db,
        )
        self.assertFalse(v_ok)
        updated = await self.mgr.get_request(req_id, user_db=self.fake_db)
        self.assertEqual(updated["authorization_status"], STATE_FAILED)

    # 9. Expired verification / authorization does not unlock any file
    async def test_05_expired_unlock_authorization_blocks_delivery(self):
        user_id = 1005
        _, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_EXP",
            user_db=self.fake_db,
        )
        req_id = req["unlock_request_id"]
        token = req["verification_attempt_id"]

        v_ok, _, v_req = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id=token,
            user_db=self.fake_db,
        )
        self.assertTrue(v_ok)

        # Force expiration in the past
        v_req["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=10)
        await self.mgr._save_request_record(v_req, user_db=self.fake_db)

        d_ok, d_msg, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            user_db=self.fake_db,
        )
        self.assertFalse(d_ok)
        self.assertIn("khatam ho gaya", d_msg)
        expired_doc = await self.mgr.get_request(req_id, user_db=self.fake_db)
        self.assertEqual(expired_doc["authorization_status"], STATE_EXPIRED)

    # 10. Shared verification link/token from another user & token replay
    async def test_06_shared_verification_link_and_token_replay_rejected(self):
        owner_id = 2001
        attacker_id = 2002
        _, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=owner_id,
            canonical_file_id="FILE_SHARED",
            user_db=self.fake_db,
        )
        req_id = req["unlock_request_id"]
        token = req["verification_attempt_id"]

        # Attacker tries to verify owner's link
        v_ok, v_msg, _ = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=attacker_id,
            verification_attempt_id=token,
            user_db=self.fake_db,
        )
        self.assertFalse(v_ok)
        self.assertIn("kisi aur user ka hai", v_msg)

        # Owner verifies legitimately
        v_ok_owner, _, _ = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=owner_id,
            verification_attempt_id=token,
            user_db=self.fake_db,
        )
        self.assertTrue(v_ok_owner)

        # Owner replays verification link a second time -> blocked
        v_replay_ok, _, _ = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=owner_id,
            verification_attempt_id=token,
            user_db=self.fake_db,
        )
        self.assertFalse(v_replay_ok)

        # Attacker tries to claim owner's verified delivery
        d_ok_attacker, _, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=attacker_id,
            user_db=self.fake_db,
        )
        self.assertFalse(d_ok_attacker)

    # 11. Concurrent button clicks cannot deliver more than one file
    async def test_07_concurrent_delivery_clicks_only_allow_one_claim(self):
        user_id = 3001
        _, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_RACE",
            user_db=self.fake_db,
        )
        req_id = req["unlock_request_id"]
        await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id=req["verification_attempt_id"],
            user_db=self.fake_db,
        )

        results = await asyncio.gather(
            self.mgr.begin_file_delivery(req_id, user_id, user_db=self.fake_db),
            self.mgr.begin_file_delivery(req_id, user_id, user_db=self.fake_db),
            self.mgr.begin_file_delivery(req_id, user_id, user_db=self.fake_db),
        )
        successes = [r for r in results if r[0] is True]
        failures = [r for r in results if r[0] is False]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 2)

    # 12. Telegram delivery failure preserves unlock for safe retry + Bot restart persistence
    async def test_08_telegram_delivery_failure_retry_and_bot_restart_persistence(self):
        user_id = 4001
        _, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_RETRY",
            user_db=self.fake_db,
        )
        req_id = req["unlock_request_id"]
        await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id=req["verification_attempt_id"],
            user_db=self.fake_db,
        )

        # Simulate bot restart by creating a brand new AdUnlockManager backed by the same DB
        restarted_mgr = AdUnlockManager()

        # First attempt begins delivery on restarted_mgr, then Telegram raises FloodWait / network error
        ok1, _, _ = await restarted_mgr.begin_file_delivery(req_id, user_id, user_db=self.fake_db)
        self.assertTrue(ok1)
        await restarted_mgr.abort_delivery_for_retry(req_id, "FloodWait: retry after 3s", user_db=self.fake_db)

        doc_after_err = await restarted_mgr.get_request(req_id, user_db=self.fake_db)
        self.assertEqual(doc_after_err["authorization_status"], STATE_VERIFIED)
        self.assertIsNone(doc_after_err["consumed_at"])

        # User retries within expiry window -> succeeds and marks CONSUMED
        ok2, _, _ = await restarted_mgr.begin_file_delivery(req_id, user_db=self.fake_db, actor_user_id=user_id)
        self.assertTrue(ok2)
        await restarted_mgr.mark_delivery_consumed(req_id, delivery_reference="msg_retry_ok", user_db=self.fake_db)
        doc_final = await restarted_mgr.get_request(req_id, user_db=self.fake_db)
        self.assertEqual(doc_final["authorization_status"], STATE_CONSUMED)

        # Verify indexes were ensured on the collection
        self.assertGreaterEqual(len(self.fake_db.db.ad_unlock_requests.indexes), 3)

    # 13, 14, 15. Feature 43 Individual Lock, Bulk Lock, Resolution Lock, and Mid-Verification Lock
    async def test_09_feature43_individual_bulk_and_mid_verification_lock_precedence(self):
        user_id = 5001
        # 1. Feature 43 Individual file lock
        await self.mgr.lock_personal_file("FILE_VIP_PERSONAL", user_db=self.fake_db)
        ok_personal, msg_personal, _ = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_VIP_PERSONAL",
            file_name="Movie.720p.mkv",
            user_db=self.fake_db,
        )
        self.assertFalse(ok_personal)
        self.assertIn("Premium", msg_personal)

        # 2. Feature 43 Bulk pattern lock (e.g. locking an entire exclusive series/batch)
        await self.mgr.lock_bulk_pattern("Mirzapur.S03", user_db=self.fake_db)
        ok_bulk, msg_bulk, _ = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_SERIES_EP1",
            file_name="Mirzapur.S03E01.1080p.mkv",
            user_db=self.fake_db,
        )
        self.assertFalse(ok_bulk)
        self.assertIn("Premium", msg_bulk)

        # 3. Resolution lock (e.g. 2160p 4K)
        ok_res, msg_res, _ = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_4K",
            file_name="Avatar.2160p.UHD.mkv",
            user_db=self.fake_db,
            resolution_lock_checker=lambda name: "2160p" in name,
        )
        self.assertFalse(ok_res)
        self.assertIn("Premium", msg_res)

        # 4. Lock added AFTER verification but BEFORE delivery
        ok_mid, _, req_mid = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_MID_LOCK",
            file_name="Normal.720p.mkv",
            user_db=self.fake_db,
        )
        self.assertTrue(ok_mid)
        req_id = req_mid["unlock_request_id"]
        await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id=req_mid["verification_attempt_id"],
            user_db=self.fake_db,
        )

        # Admin locks FILE_MID_LOCK before user clicks GET FILE
        await self.mgr.lock_personal_file("FILE_MID_LOCK", user_db=self.fake_db)
        d_ok, d_msg, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            user_db=self.fake_db,
        )
        self.assertFalse(d_ok)
        self.assertIn("Premium-only lock", d_msg)

    # 16. Database/persistence unavailability fails closed
    async def test_10_database_unavailability_fails_closed(self):
        user_id = 6001
        self.mgr._simulate_db_unavailable = True
        try:
            ok, msg, req = await self.mgr.create_unlock_request(
                telegram_user_id=user_id,
                canonical_file_id="FILE_DB_DOWN",
                user_db=self.fake_db,
            )
            self.assertFalse(ok)
            self.assertIsNone(req)
            self.assertIn("unavailable", msg.lower())
        finally:
            self.mgr._simulate_db_unavailable = False

    # 17. UI keyboards for verification & delivery follow Feature 44 readability rules
    async def test_11_verification_and_delivery_keyboards_match_feature44(self):
        v_kb = build_ad_verification_keyboard("https://short.example/abc", "https://t.me/tutorial/1")
        v_btns = [b for row in v_kb.inline_keyboard for b in row]
        self.assertEqual([b.text for b in v_btns], [
            "◈ 𝐕𝐄𝐑𝐈𝐅𝐘 𝐀𝐃",
            "『 𝐇𝐎𝐖 𝐓𝐎 𝐕𝐄𝐑𝐈𝐅𝐘 』",
            "♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』",
            "◁ 𝐁𝐀𝐂𝐊",
        ])
        for b in v_btns:
            self.assertTrue(validate_button_readability(b.text)["is_valid"])

        d_kb = build_ad_verified_delivery_keyboard("ADU12345")
        d_btns = [b for row in d_kb.inline_keyboard for b in row]
        self.assertEqual(len(d_btns), 1)
        self.assertEqual(d_btns[0].text, "⇩ 𝐆𝐄𝐓 𝐅𝐈𝐋𝐄")
        self.assertEqual(d_btns[0].callback_data, "ad_deliver#ADU12345")
        self.assertTrue(validate_button_readability(d_btns[0].text)["is_valid"])

        p_txt = build_ad_verification_prompt_text("Pushpa.2.1080p.mkv", 600)
        self.assertIn("1 Verified Ad = 1 Selected File", p_txt)
        r_txt = build_ad_verified_ready_text("Pushpa.2.1080p.mkv", 600)
        self.assertIn("𝐀𝐃 𝐕𝐄𝐑𝐈𝐅𝐈𝐂𝐀𝐓𝐈𝐎𝐍 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃", r_txt)

    # 18. Exact Screenshot Reproduction (14/15 -> 15/15 -> exhausted at 15/15 + 64-byte callback safety + timings)
    async def test_12_exact_screenshot_reproduction_14_to_15_and_64_byte_callback_safety_and_timings(self):
        import time

        quota_15_db = _FakeDailyQuotaDB(daily_limit=15)
        user_id = 6661494944
        real_grp_id = -1002148604082
        # Realistic 36-char unpacked Telegram file_id (used in indexed media DB)
        unpacked_36_file_id = "BQACAgUAAx0CfatN9gACDf5nK1a9b2c3d4e5"
        # Realistic 62-char full raw Telegram file_id (edge case)
        long_raw_file_id = "BQACAgUAAxkBAAIB2WcrVrt1234567890abcdefghijklmnopqrstuvwxyzABCD"

        # Step 1: Set test Free user at 14/15
        quota_15_db.usage[(user_id, quota_15_db.current_date)] = 14

        # Step 2: Request 15th file (Akka The Protectors S01E05) -> confirm normal allowed delivery (15/15)
        t0 = time.perf_counter()
        prem_access = await quota_15_db.has_premium_access(user_id)
        t_prem = (time.perf_counter() - t0) * 1000.0
        self.assertFalse(prem_access)

        t1 = time.perf_counter()
        allowed_15, count_15 = quota_15_db.consume_free_file(user_id)
        t_limit_15 = (time.perf_counter() - t1) * 1000.0
        self.assertTrue(allowed_15)
        self.assertEqual(count_15, 15)

        # Step 3 & 4: User is now at 15/15. Request another file -> confirm exhausted (False, 15)
        t2 = time.perf_counter()
        allowed_16, count_16 = quota_15_db.consume_free_file(user_id)
        t_limit_16 = (time.perf_counter() - t2) * 1000.0
        self.assertFalse(allowed_16)
        self.assertEqual(count_16, 15)

        # Step 5: Confirm BUY PREMIUM and WATCH AD & UNLOCK appear and callback_data <= 64 bytes (no BUTTON_DATA_INVALID)
        kb_36 = build_daily_limit_exhausted_keyboard(
            grp_id=real_grp_id, canonical_file_id=unpacked_36_file_id, pre="files"
        )
        btns_36 = [b for row in kb_36.inline_keyboard for b in row]
        self.assertEqual(btns_36[0].text, "♛ 『 𝐁𝐔𝐘 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』")
        self.assertEqual(btns_36[1].text, "✦ 𝐖𝐀𝐓𝐂𝐇 𝐀𝐃 & 𝐔𝐍𝐋𝐎𝐂𝐊")
        cb_36_bytes = len(btns_36[1].callback_data.encode("utf-8"))
        self.assertLessEqual(cb_36_bytes, 64, f"Callback exceeded 64 bytes: {cb_36_bytes}")
        p_grp, p_pre, p_fid = self.mgr.parse_unlock_start_callback(
            btns_36[1].callback_data, default_grp_id=real_grp_id
        )
        self.assertEqual((p_grp, p_pre, p_fid), (real_grp_id, "files", unpacked_36_file_id))

        # Also verify 62-char long raw file_id with custom prefix 'filep' stays <= 64 bytes
        kb_long = build_daily_limit_exhausted_keyboard(
            grp_id=real_grp_id, canonical_file_id=long_raw_file_id, pre="filep"
        )
        btns_long = [b for row in kb_long.inline_keyboard for b in row]
        cb_long_bytes = len(btns_long[1].callback_data.encode("utf-8"))
        self.assertLessEqual(cb_long_bytes, 64, f"Long callback exceeded 64 bytes: {cb_long_bytes}")
        p_grp_l, p_pre_l, p_fid_l = self.mgr.parse_unlock_start_callback(
            btns_long[1].callback_data, default_grp_id=0
        )
        self.assertEqual((p_grp_l, p_pre_l, p_fid_l), (real_grp_id, "filep", long_raw_file_id))

        # Step 6: Complete verification -> confirm 1 selected file is delivered
        t3 = time.perf_counter()
        ok_req, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id=unpacked_36_file_id,
            grp_id=real_grp_id,
            file_name="Akka The Protectors S01E06 720p NF WEB DL.mkv",
            user_db=quota_15_db,
        )
        self.assertTrue(ok_req)
        req_id = req["unlock_request_id"]
        v_ok, _, _ = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id=req["verification_attempt_id"],
            user_db=quota_15_db,
        )
        self.assertTrue(v_ok)
        d_ok, _, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            requested_file_id=unpacked_36_file_id,
            user_db=quota_15_db,
        )
        self.assertTrue(d_ok)
        await self.mgr.mark_delivery_consumed(req_id, delivery_reference="msg_ep06", user_db=quota_15_db)
        t_f45_ms = (time.perf_counter() - t3) * 1000.0

        # Step 7: Confirm a second file still requires a new authorization
        still_exhausted, count_after = quota_15_db.consume_free_file(user_id)
        self.assertFalse(still_exhausted)
        self.assertEqual(count_after, 15)
        d_second_ok, _, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            requested_file_id="BQACAgUAAx0CfatN9gACDf5nK1a9b2c3d4e6",
            user_db=quota_15_db,
        )
        self.assertFalse(d_second_ok)

        # Step 8: Test Premium delivery separately
        prem_uid = 7777777777
        quota_15_db.premium_users.add(prem_uid)
        for _ in range(20):
            p_allowed, p_cnt = quota_15_db.consume_free_file(prem_uid)
            self.assertTrue(p_allowed)
            self.assertEqual(p_cnt, 0)

        # Ensure all local stage timings are sub-10ms
        self.assertLess(t_prem, 10.0)
        self.assertLess(t_limit_15, 10.0)
        self.assertLess(t_limit_16, 10.0)
        self.assertLess(t_f45_ms, 50.0)


if __name__ == "__main__":
    unittest.main()

