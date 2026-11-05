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


class _FakeDailyQuotaDB:
    """In-memory mock of user daily limit & premium access for testing."""

    def __init__(self, daily_limit: int = 2) -> None:
        self.daily_limit = daily_limit
        self.usage: dict[int, int] = {}
        self.premium_users: set[int] = set()
        self.settings: dict[str, object] = {}

    async def has_premium_access(self, user_id: int) -> bool:
        return user_id in self.premium_users

    def consume_free_file(self, user_id: int) -> tuple[bool, int]:
        if user_id in self.premium_users:
            return True, 0
        current = self.usage.get(user_id, 0)
        if current >= self.daily_limit:
            return False, current
        self.usage[user_id] = current + 1
        return True, self.usage[user_id]

    async def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    async def set_setting(self, key: str, value):
        self.settings[key] = value


class TestFeature45WatchAdUnlock(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.mgr = AdUnlockManager()
        self.fake_db = _FakeDailyQuotaDB(daily_limit=2)

    # 1. Free user below daily limit receives eligible files normally
    async def test_01_free_user_below_daily_limit_receives_normal_delivery(self):
        user_id = 1001
        ok1, count1 = self.fake_db.consume_free_file(user_id)
        ok2, count2 = self.fake_db.consume_free_file(user_id)
        self.assertTrue(ok1)
        self.assertEqual(count1, 1)
        self.assertTrue(ok2)
        self.assertEqual(count2, 2)

    # 2 & 3. Free user at daily limit sees Buy Premium, Watch Ad & Unlock, and Back
    async def test_02_daily_limit_exhausted_ui_and_buy_premium_destination(self):
        user_id = 1002
        self.fake_db.consume_free_file(user_id)
        self.fake_db.consume_free_file(user_id)
        ok3, _ = self.fake_db.consume_free_file(user_id)
        self.assertFalse(ok3)

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
        self.assertEqual(buttons[2].text, "◁ 𝐁𝐀𝐂𝐊")
        self.assertEqual(buttons[2].callback_data, "start")

        for b in buttons:
            res = validate_button_readability(b.text)
            self.assertTrue(res["is_valid"])
            self.assertTrue(res["zero_colour_emojis"])

    # 4, 5, 6, 7. One verified ad unlocks ONLY 1 selected file, one-time only, without resetting daily quota
    async def test_03_one_verified_ad_unlocks_single_file_once_and_preserves_exhausted_quota(self):
        user_id = 1003
        # Exhaust quota
        self.fake_db.consume_free_file(user_id)
        self.fake_db.consume_free_file(user_id)
        self.assertFalse(self.fake_db.consume_free_file(user_id)[0])

        # Create request for FILE_001
        ok, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_001",
            grp_id=0,
            file_name="Deadpool.2024.1080p.mkv",
            user_db=self.fake_db,
        )
        self.assertTrue(ok)
        req_id = req["unlock_request_id"]
        token = req["verification_attempt_id"]

        # Complete verification
        v_ok, _, v_req = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id=token,
            user_db=self.fake_db,
        )
        self.assertTrue(v_ok)
        self.assertEqual(v_req["authorization_status"], STATE_VERIFIED)

        # Deliver the single file
        d_ok, _, d_req = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            user_db=self.fake_db,
        )
        self.assertTrue(d_ok)
        self.assertEqual(d_req["canonical_file_id"], "FILE_001")
        await self.mgr.mark_delivery_consumed(req_id, delivery_reference="msg_999", user_db=self.fake_db)

        # Attempt second delivery with the same unlock_request_id -> MUST FAIL (one-time only)
        d2_ok, d2_msg, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            user_db=self.fake_db,
        )
        self.assertFalse(d2_ok)
        self.assertIn("pehle hi use ho chuka", d2_msg)

        # Daily free quota MUST still be exhausted (not reset) and user MUST NOT have Premium
        self.assertFalse(self.fake_db.consume_free_file(user_id)[0])
        self.assertFalse(await self.fake_db.has_premium_access(user_id))

        # Requesting a second file FILE_002 requires a brand new ad verification
        ok_b, _, req_b = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_002",
            grp_id=0,
            file_name="Wolverine.2024.720p.mkv",
            user_db=self.fake_db,
        )
        self.assertTrue(ok_b)
        self.assertNotEqual(req_b["unlock_request_id"], req_id)
        self.assertEqual(req_b["authorization_status"], STATE_PENDING_VERIFICATION)

    # 8. Incomplete, failed, or Merely Clicked ad does not unlock any file
    async def test_04_incomplete_or_failed_verification_blocks_delivery(self):
        user_id = 1004
        ok, _, req = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_UNVERIFIED",
            user_db=self.fake_db,
        )
        self.assertTrue(ok)
        req_id = req["unlock_request_id"]

        # Merely created / clicked ad URL without completing verification
        d_ok, d_msg, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            user_db=self.fake_db,
        )
        self.assertFalse(d_ok)
        self.assertIn("verification abhi poora nahi hua", d_msg)

        # Wrong verification token fails closed
        v_ok, _, _ = await self.mgr.verify_unlock_request(
            unlock_request_id=req_id,
            actor_user_id=user_id,
            verification_attempt_id="WRONG_TOKEN_123",
            user_db=self.fake_db,
        )
        self.assertFalse(v_ok)
        updated = await self.mgr.get_request(req_id, user_db=self.fake_db)
        self.assertEqual(updated["authorization_status"], STATE_FAILED)

    # 8b. Expired verification / authorization does not unlock any file
    async def test_05_expired_unlock_authorization_blocks_delivery(self):
        user_id = 1005
        ok, _, req = await self.mgr.create_unlock_request(
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

    # 9. Shared verification link/token from another user does not unlock a file
    async def test_06_shared_verification_link_rejected_for_different_user(self):
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

        # Attacker tries to claim owner's verified delivery
        d_ok_attacker, _, _ = await self.mgr.begin_file_delivery(
            unlock_request_id=req_id,
            actor_user_id=attacker_id,
            user_db=self.fake_db,
        )
        self.assertFalse(d_ok_attacker)

    # 10 & 11. Concurrent button clicks cannot deliver more than one file
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

    # 12. Telegram delivery failure does not unfairly consume a verified unlock before expiry
    async def test_08_telegram_delivery_failure_preserves_unlock_for_safe_retry(self):
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

        # First attempt begins delivery, then Telegram raises FloodWait / network error
        ok1, _, _ = await self.mgr.begin_file_delivery(req_id, user_id, user_db=self.fake_db)
        self.assertTrue(ok1)
        await self.mgr.abort_delivery_for_retry(req_id, "FloodWait: retry after 3s", user_db=self.fake_db)

        doc_after_err = await self.mgr.get_request(req_id, user_db=self.fake_db)
        self.assertEqual(doc_after_err["authorization_status"], STATE_VERIFIED)
        self.assertIsNone(doc_after_err["consumed_at"])

        # User retries within expiry window -> succeeds and marks CONSUMED
        ok2, _, _ = await self.mgr.begin_file_delivery(req_id, user_id, user_db=self.fake_db)
        self.assertTrue(ok2)
        await self.mgr.mark_delivery_consumed(req_id, delivery_reference="msg_retry_ok", user_db=self.fake_db)
        doc_final = await self.mgr.get_request(req_id, user_db=self.fake_db)
        self.assertEqual(doc_final["authorization_status"], STATE_CONSUMED)

    # 13, 14, 15. Feature 43 Personal File Lock & Resolution Lock take strict precedence
    async def test_09_feature43_personal_lock_and_resolution_lock_precedence(self):
        user_id = 5001
        # Lock specific file via Feature 43
        await self.mgr.lock_personal_file("FILE_VIP_PERSONAL", user_db=self.fake_db)

        ok_personal, msg_personal, _ = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_VIP_PERSONAL",
            file_name="Movie.720p.mkv",
            user_db=self.fake_db,
        )
        self.assertFalse(ok_personal)
        self.assertIn("Premium", msg_personal)

        # Lock via resolution (e.g. 2160p 4K)
        ok_res, msg_res, _ = await self.mgr.create_unlock_request(
            telegram_user_id=user_id,
            canonical_file_id="FILE_4K",
            file_name="Avatar.2160p.UHD.mkv",
            user_db=self.fake_db,
            resolution_lock_checker=lambda name: "2160p" in name,
        )
        self.assertFalse(ok_res)
        self.assertIn("Premium", msg_res)

        # Scenario 15: File becomes locked while user is mid-verification
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

    # 18. Database/persistence unavailability fails closed
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

    # UI keyboards for verification & delivery follow Feature 44 readability rules
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


if __name__ == "__main__":
    unittest.main()
