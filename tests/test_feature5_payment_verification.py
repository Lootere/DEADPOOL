# Unit and Integration Tests for Manual Payment Screenshot Approval System
import unittest
import sys
import types
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if "Lootere" not in sys.modules:
    sys.modules["Lootere"] = types.ModuleType("Lootere")
if "Lootere.utils" not in sys.modules:
    sys.modules["Lootere.utils"] = types.ModuleType("Lootere.utils")

# Load subscription_manager
_SUB_PATH = _ROOT / "Lootere" / "utils" / "subscription_manager.py"
_SUB_SPEC = importlib.util.spec_from_file_location("Lootere.utils.subscription_manager", _SUB_PATH)
subscription_manager_mod = importlib.util.module_from_spec(_SUB_SPEC)
assert _SUB_SPEC and _SUB_SPEC.loader
sys.modules["Lootere.utils.subscription_manager"] = subscription_manager_mod
_SUB_SPEC.loader.exec_module(subscription_manager_mod)

# Load payment_manager
_PAY_PATH = _ROOT / "Lootere" / "utils" / "payment_manager.py"
_PAY_SPEC = importlib.util.spec_from_file_location("Lootere.utils.payment_manager", _PAY_PATH)
payment_manager_mod = importlib.util.module_from_spec(_PAY_SPEC)
assert _PAY_SPEC and _PAY_SPEC.loader
sys.modules["Lootere.utils.payment_manager"] = payment_manager_mod
_PAY_SPEC.loader.exec_module(payment_manager_mod)

DestinationManager = subscription_manager_mod.DestinationManager
SubscriptionManager = subscription_manager_mod.SubscriptionManager
PaymentManager = payment_manager_mod.PaymentManager
build_admin_review_keyboard = payment_manager_mod.build_admin_review_keyboard
build_rejection_reasons_keyboard = payment_manager_mod.build_rejection_reasons_keyboard
format_review_message_caption = payment_manager_mod.format_review_message_caption
format_user_payment_instructions = payment_manager_mod.format_user_payment_instructions

COLOUR_EMOJIS = {"🔴", "🟢", "🟡", "🔵", "🟣", "🟤", "⚪", "⚫", "🟥", "🟩", "🟨", "🟦", "🟪", "🟫", "⬛", "⬜"}


class MockBotPremiumDB:
    def __init__(self):
        self.users = {}

    async def get_user(self, user_id):
        return self.users.get(int(user_id))

    async def update_user(self, data):
        uid = int(data["id"])
        self.users[uid] = dict(data)


class MockTelegramClient:
    def __init__(self):
        self.sent_messages = []
        self.created_links = []
        self.fail_dm_users = set()

    async def send_message(self, chat_id, text, reply_markup=None):
        if int(chat_id) in self.fail_dm_users:
            raise Exception("403 Forbidden: bot was blocked by the user")
        self.sent_messages.append((int(chat_id), text, reply_markup))

    async def create_chat_invite_link(self, chat_id, name=None, member_limit=1):
        class InviteLink:
            def __init__(self, url):
                self.invite_link = url
        url = f"https://t.me/+vip_{abs(chat_id)}_{len(self.created_links)}"
        self.created_links.append((chat_id, url, member_limit))
        return InviteLink(url)

    async def get_chat_member(self, chat_id, user_id):
        class Priv:
            can_post_messages = True
        class Member:
            status = "administrator"
            privileges = Priv()
        return Member()

    async def get_chat(self, chat_id):
        class Chat:
            title = "Payment Review Log"
        return Chat()


class TestPaymentVerificationSystem(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.dest_mgr = DestinationManager()
        await self.dest_mgr.initialize(
            default_group_id="-1002244316214",
            default_channel1_id="-1002148604082",
            default_channel2_id="-1002023191399",
        )
        self.sub_mgr = SubscriptionManager(destination_mgr=self.dest_mgr)
        self.bot_db = MockBotPremiumDB()
        self.pay_mgr = PaymentManager(review_channel_id=-100999888, authorized_reviewers=[777, 888])
        self.client = MockTelegramClient()

    def test_1_review_keyboards_and_zero_colour_emojis(self):
        """Admin review buttons must include APPROVE, REJECT, CUSTOM MESSAGE with zero colour emojis."""
        review_kb = build_admin_review_keyboard("PAY_12345_ABC")
        reject_kb = build_rejection_reasons_keyboard("PAY_12345_ABC")

        labels = []
        for kb in [review_kb, reject_kb]:
            for row in kb.inline_keyboard:
                for btn in row:
                    labels.append(btn.text)
                    for emoji in COLOUR_EMOJIS:
                        self.assertNotIn(emoji, btn.text)

        self.assertIn("APPROVE", labels)
        self.assertIn("REJECT", labels)
        self.assertIn("CUSTOM MESSAGE", labels)

    async def test_2_user_payment_submission_does_not_auto_activate(self):
        """Submitting a screenshot stores pending request and never activates entitlement before approval."""
        user_id = 10101
        ok, msg, req = await self.pay_mgr.create_payment_request(
            user_id=user_id,
            username="rahul_user",
            first_name="Rahul",
            product_type="bot_premium",
            plan_id="month_1",
            plan_name="1 Month Bot Premium",
            duration_days=30,
            amount="₹49",
            screenshot_file_id="FILE_ID_PHOTO_123",
        )
        self.assertTrue(ok)
        self.assertEqual(req["status"], "pending")
        self.assertTrue(req["request_id"].startswith("PAY_"))

        # Verify neither Bot Premium nor Group VIP is active yet
        self.assertIsNone(await self.bot_db.get_user(user_id))
        self.assertIsNone(await self.sub_mgr.get_user_subscription(user_id))

        # Prevent duplicate pending submission from same user
        ok_dup, msg_dup, _ = await self.pay_mgr.create_payment_request(
            user_id=user_id,
            username="rahul_user",
            first_name="Rahul",
            product_type="bot_premium",
            plan_id="month_1",
            plan_name="1 Month Bot Premium",
            duration_days=30,
            amount="₹49",
            screenshot_file_id="FILE_ID_PHOTO_456",
        )
        self.assertFalse(ok_dup)
        self.assertIn("already have a pending payment request", msg_dup)

    async def test_3_bot_premium_approval_grants_only_bot_premium(self):
        """Approving Bot Premium activates Bot Premium only and never Group/Channel VIP."""
        user_id = 20202
        _, _, req = await self.pay_mgr.create_payment_request(
            user_id=user_id,
            username="amit",
            first_name="Amit",
            product_type="bot_premium",
            plan_id="1_month",
            plan_name="1 Month Bot Premium",
            duration_days=30,
            amount="₹59",
            screenshot_file_id="PHOTO_BOT_1",
        )
        req_id = req["request_id"]

        ok, msg, updated_req = await self.pay_mgr.approve_payment_request(
            client=self.client,
            request_id=req_id,
            admin_id=777,
            user_db=self.bot_db,
            sub_mgr=self.sub_mgr,
        )
        self.assertTrue(ok)
        self.assertEqual(updated_req["status"], "approved")
        self.assertEqual(updated_req["reviewed_by"], 777)

        # Bot Premium is active
        bot_user = await self.bot_db.get_user(user_id)
        self.assertIsNotNone(bot_user)
        self.assertIsNotNone(bot_user.get("expiry_time"))

        # Group/Channel VIP is NOT active
        vip_sub = await self.sub_mgr.get_user_subscription(user_id)
        self.assertIsNone(vip_sub)

        # Prevent double approval of the same request
        ok_second, msg_second, _ = await self.pay_mgr.approve_payment_request(
            client=self.client,
            request_id=req_id,
            admin_id=888,
            user_db=self.bot_db,
            sub_mgr=self.sub_mgr,
        )
        self.assertFalse(ok_second)
        self.assertIn("already APPROVED", msg_second)

    async def test_4_group_vip_approval_grants_only_mapped_destinations(self):
        """Approving Group/Channel VIP activates only mapped destinations and never Bot Premium."""
        user_id = 30303
        _, _, req = await self.pay_mgr.create_payment_request(
            user_id=user_id,
            username="priya",
            first_name="Priya",
            product_type="group_premium",
            plan_id="gold",
            plan_name="Gold VIP",
            duration_days=30,
            amount="₹199",
            screenshot_file_id="PHOTO_VIP_GOLD",
        )
        req_id = req["request_id"]

        ok, msg, updated_req = await self.pay_mgr.approve_payment_request(
            client=self.client,
            request_id=req_id,
            admin_id=777,
            user_db=self.bot_db,
            sub_mgr=self.sub_mgr,
        )
        self.assertTrue(ok)
        self.assertEqual(updated_req["status"], "approved")

        # Bot Premium must remain None
        self.assertIsNone(await self.bot_db.get_user(user_id))

        # Group/Channel VIP must be active with Gold destinations (dest_group1, dest_channel1)
        vip_sub = await self.sub_mgr.get_user_subscription(user_id)
        self.assertIsNotNone(vip_sub)
        self.assertEqual(vip_sub["status"], "active")
        self.assertEqual(vip_sub["destinations"], ["dest_group1", "dest_channel1"])
        self.assertEqual(len(self.client.created_links), 2)

        # Caption formatting must never expose invite links
        caption = format_review_message_caption(updated_req)
        self.assertNotIn("t.me/+", caption)

    async def test_5_rejection_flow_records_reason_and_grants_nothing(self):
        """Rejecting a payment notifies user with reason and grants no entitlement."""
        user_id = 40404
        _, _, req = await self.pay_mgr.create_payment_request(
            user_id=user_id,
            username="fake_payer",
            first_name="Fake",
            product_type="group_premium",
            plan_id="vip",
            plan_name="All-Access Diamond VIP",
            duration_days=30,
            amount="₹299",
            screenshot_file_id="FAKE_SCREENSHOT",
        )
        req_id = req["request_id"]

        ok, msg, rej_req = await self.pay_mgr.reject_payment_request(
            client=self.client,
            request_id=req_id,
            admin_id=888,
            reason="Invalid / Fake transaction screenshot",
        )
        self.assertTrue(ok)
        self.assertEqual(rej_req["status"], "rejected")
        self.assertEqual(rej_req["reviewed_by"], 888)
        self.assertEqual(rej_req["reject_reason"], "Invalid / Fake transaction screenshot")

        # Neither entitlement is granted
        self.assertIsNone(await self.bot_db.get_user(user_id))
        self.assertIsNone(await self.sub_mgr.get_user_subscription(user_id))

        # User received rejection DM containing reason
        user_dms = [m for m in self.client.sent_messages if m[0] == user_id]
        self.assertEqual(len(user_dms), 1)
        self.assertIn("Invalid / Fake transaction screenshot", user_dms[0][1])

    async def test_6_custom_message_preserves_pending_state(self):
        """Custom message sends DM to user but keeps payment request pending for later approval/rejection."""
        user_id = 50505
        _, _, req = await self.pay_mgr.create_payment_request(
            user_id=user_id,
            username="utr_blur",
            first_name="Karan",
            product_type="bot_premium",
            plan_id="1_month",
            plan_name="1 Month Bot Premium",
            duration_days=30,
            amount="₹59",
            screenshot_file_id="BLURRY_PIC",
        )
        req_id = req["request_id"]

        ok, dm_status = await self.pay_mgr.send_custom_message(
            client=self.client,
            request_id=req_id,
            admin_id=777,
            message_text="Please send a clearer image where the 12-digit UTR number is visible.",
        )
        self.assertTrue(ok)

        # Request is STILL pending and can be approved afterwards
        current = await self.pay_mgr.get_request(req_id)
        self.assertEqual(current["status"], "pending")
        self.assertIsNone(await self.bot_db.get_user(user_id))

        # Now approve it
        ok_app, _, _ = await self.pay_mgr.approve_payment_request(
            client=self.client,
            request_id=req_id,
            admin_id=777,
            user_db=self.bot_db,
            sub_mgr=self.sub_mgr,
        )
        self.assertTrue(ok_app)
        self.assertIsNotNone(await self.bot_db.get_user(user_id))

    async def test_7_dm_failure_recording_and_reviewer_authorization(self):
        """If user blocked the bot, record dm_delivery_failed; verify reviewer authorization check."""
        self.assertTrue(self.pay_mgr.is_authorized_reviewer(777))
        self.assertFalse(self.pay_mgr.is_authorized_reviewer(99999))

        user_id = 60606
        self.client.fail_dm_users.add(user_id)
        _, _, req = await self.pay_mgr.create_payment_request(
            user_id=user_id,
            username="blocked_user",
            first_name="Blocked",
            product_type="bot_premium",
            plan_id="1_month",
            plan_name="1 Month Bot Premium",
            duration_days=30,
            amount="₹59",
            screenshot_file_id="PIC_BLOCKED",
        )
        ok, _, updated = await self.pay_mgr.approve_payment_request(
            client=self.client,
            request_id=req["request_id"],
            admin_id=777,
            user_db=self.bot_db,
            sub_mgr=self.sub_mgr,
        )
        self.assertTrue(ok)
        self.assertTrue(updated["dm_delivery_failed"])


if __name__ == "__main__":
    unittest.main()
