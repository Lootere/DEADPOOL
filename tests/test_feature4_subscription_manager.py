# Feature 4 Tests: Premium Hub + Premium Group/Channel Subscription Manager
import unittest
import asyncio
import sys
import types
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta

_ROOT = Path(__file__).resolve().parent.parent
if "Lootere" not in sys.modules:
    sys.modules["Lootere"] = types.ModuleType("Lootere")
if "Lootere.utils" not in sys.modules:
    sys.modules["Lootere.utils"] = types.ModuleType("Lootere.utils")

_SUB_PATH = _ROOT / "Lootere" / "utils" / "subscription_manager.py"
_SUB_SPEC = importlib.util.spec_from_file_location("Lootere.utils.subscription_manager", _SUB_PATH)
subscription_manager_mod = importlib.util.module_from_spec(_SUB_SPEC)
assert _SUB_SPEC and _SUB_SPEC.loader
sys.modules["Lootere.utils.subscription_manager"] = subscription_manager_mod
_SUB_SPEC.loader.exec_module(subscription_manager_mod)

DestinationManager = subscription_manager_mod.DestinationManager
SubscriptionManager = subscription_manager_mod.SubscriptionManager
build_premium_hub_keyboard = subscription_manager_mod.build_premium_hub_keyboard
build_dest_plans_keyboard = subscription_manager_mod.build_dest_plans_keyboard
build_my_plans_keyboard = subscription_manager_mod.build_my_plans_keyboard
format_dest_plans_text = subscription_manager_mod.format_dest_plans_text
format_my_plans_text = subscription_manager_mod.format_my_plans_text
IST = subscription_manager_mod.IST

COLOUR_EMOJIS = {"🔴", "🟢", "🟡", "🔵", "🟣", "🟤", "⚪", "⚫", "🟥", "🟩", "🟨", "🟦", "🟪", "🟫", "⬛", "⬜"}


class MockTelegramClient:
    def __init__(self):
        self.kicked_members = []
        self.unbanned_members = []
        self.revoked_links = []
        self.created_links = []
        self.sent_messages = []
        self.fail_dm_for_users = set()

    async def get_chat_member(self, chat_id, user_id):
        class Privileges:
            can_invite_users = True
            can_restrict_members = True

        class ChatMember:
            status = "administrator"
            privileges = Privileges()

        return ChatMember()

    async def ban_chat_member(self, chat_id, user_id):
        self.kicked_members.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id):
        self.unbanned_members.append((chat_id, user_id))

    async def revoke_chat_invite_link(self, chat_id, url):
        self.revoked_links.append((chat_id, url))

    async def create_chat_invite_link(self, chat_id, name=None, member_limit=1):
        class InviteResult:
            def __init__(self, link):
                self.invite_link = link

        link = f"https://t.me/+inv_{abs(chat_id)}_{len(self.created_links)}"
        self.created_links.append((chat_id, link, member_limit))
        return InviteResult(link)

    async def send_message(self, chat_id, text, reply_markup=None):
        if chat_id in self.fail_dm_for_users:
            raise Exception("User has blocked the bot (DM failure)")
        self.sent_messages.append((chat_id, text))


class TestFeature4SubscriptionManager(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.dest_mgr = DestinationManager()
        self.sub_mgr = SubscriptionManager(destination_mgr=self.dest_mgr)
        self.client = MockTelegramClient()

    async def asyncSetUp(self):
        await self.dest_mgr.initialize(
            default_group_id="-1002244316214",
            default_channel1_id="-1002148604082",
            default_channel2_id="-1002023191399",
        )

    def test_fr1_zero_colour_emojis_in_premium_hub_keyboards(self):
        """FR1 & Anti-Colour-Emoji: Hub keyboards must have strictly zero colour emojis."""
        hub_kb = build_premium_hub_keyboard()
        plan_kb = build_dest_plans_keyboard()
        my_plans_kb = build_my_plans_keyboard(has_dest_sub=True)

        for kb in [hub_kb, plan_kb, my_plans_kb]:
            for row in kb.inline_keyboard:
                for btn in row:
                    for emoji in COLOUR_EMOJIS:
                        self.assertNotIn(
                            emoji, btn.text,
                            f"Button '{btn.text}' must not contain colour emoji {emoji}"
                        )

        # Check expected navigation entries are preserved
        button_callbacks = [
            btn.callback_data
            for row in hub_kb.inline_keyboard
            for btn in row
            if btn.callback_data
        ]
        self.assertIn("premium_info", button_callbacks, "Must preserve BOT PREMIUM")
        self.assertIn("dest_plans", button_callbacks, "Must include VIP DESTINATIONS")
        self.assertIn("pm_reff", button_callbacks, "Must preserve FREE TRIAL & REFERRALS")
        self.assertIn("my_plans_hub", button_callbacks, "Must include MY ACTIVE PLANS")
        self.assertIn("start", button_callbacks, "Must preserve BACK TO HOME")

    def test_fr2_independent_entitlements_separation(self):
        """FR2: Bot Premium and Group/Channel VIP are strictly separate models and states."""
        # Bot Premium user data model (legacy)
        bot_user = {
            "id": 11111,
            "expiry_time": datetime.now(IST) + timedelta(days=10),
        }
        # VIP Destination subscription (independent)
        dest_sub = {
            "user_id": 11111,
            "plan_id": "silver",
            "status": "active",
            "destinations": ["dest_group1"],
            "expiry_time": datetime.now(IST) + timedelta(days=30),
        }

        # Verify formatting displays them as two distinct products
        overview = format_my_plans_text(bot_user, dest_sub, self.dest_mgr._destinations)
        self.assertIn("1. Bot Premium (Search & Stream):", overview)
        self.assertIn("2. Community VIP (Private Groups & Channels):", overview)
        self.assertIn("Silver VIP", overview)

        # Verify user without destination VIP has inactive community status even if bot premium is active
        overview_only_bot = format_my_plans_text(bot_user, None, self.dest_mgr._destinations)
        self.assertIn("1. Bot Premium (Search & Stream):", overview_only_bot)
        self.assertIn("NOT ACTIVE", overview_only_bot)

    async def test_fr3_destination_crud_and_permission_test(self):
        """FR3: Admin destination manager supports add, toggle, remove, and permission test."""
        # Add new destination
        ok, msg = await self.dest_mgr.add_destination(
            dest_id="dest_extra",
            name="VIP Anime Hub",
            chat_id=-100999888,
            dest_type="channel",
        )
        self.assertTrue(ok)
        self.assertIsNotNone(self.dest_mgr.get_destination("dest_extra"))

        # Test permissions
        perm = await self.sub_mgr.test_destination_permissions(self.client, "dest_extra")
        self.assertTrue(perm["success"])
        self.assertTrue(perm["can_invite_users"])
        self.assertTrue(perm["can_restrict_members"])

        # Toggle status
        ok, _ = await self.dest_mgr.toggle_destination("dest_extra")
        self.assertTrue(ok)
        self.assertEqual(self.dest_mgr.get_destination("dest_extra")["status"], "disabled")

        # Remove destination
        ok, _ = await self.dest_mgr.remove_destination("dest_extra")
        self.assertTrue(ok)
        self.assertIsNone(self.dest_mgr.get_destination("dest_extra"))

    async def test_fr4_plans_mapped_to_destinations(self):
        """FR4: Plans map to explicit destinations (e.g. Silver=group; Gold=group+ch1; VIP=all three)."""
        silver = self.dest_mgr.get_plan("silver")
        gold = self.dest_mgr.get_plan("gold")
        vip = self.dest_mgr.get_plan("vip")

        self.assertEqual(silver["destinations"], ["dest_group1"])
        self.assertEqual(gold["destinations"], ["dest_group1", "dest_channel1"])
        self.assertEqual(vip["destinations"], ["dest_group1", "dest_channel1", "dest_channel2"])

        # Format plans text
        plan_text = format_dest_plans_text(self.dest_mgr.list_plans(), self.dest_mgr._destinations)
        self.assertIn("Silver VIP", plan_text)
        self.assertIn("Gold VIP", plan_text)
        self.assertIn("All-Access Diamond VIP", plan_text)

    async def test_fr5_and_fr7_activation_and_renewal_rules(self):
        """FR5 & FR7: Activation, before-expiry extension vs after-expiry reset."""
        user_id = 998877

        # 1. First Activation: 30 days
        ok, _, sub = await self.sub_mgr.activate_subscription(
            user_id=user_id, plan_id="silver", duration_days=30, admin_id=123
        )
        self.assertTrue(ok)
        first_expiry = sub["expiry_time"]
        self.assertEqual(sub["status"], "active")

        # 2. Before-expiry renewal (extension): adds 15 days to existing expiry
        ok, _, renewed_sub = await self.sub_mgr.renew_subscription(
            user_id=user_id, duration_days=15, admin_id=123
        )
        self.assertTrue(ok)
        expected_expiry = first_expiry + timedelta(days=15)
        # Should match within 2 seconds
        diff = abs((renewed_sub["expiry_time"] - expected_expiry).total_seconds())
        self.assertLess(diff, 2)

        # 3. After-expiry renewal: if expired, starts a new period from now
        current_sub = await self.sub_mgr.get_user_subscription(user_id)
        current_sub["expiry_time"] = datetime.now(IST) - timedelta(days=5)
        current_sub["status"] = "expired"

        ok, _, restored_sub = await self.sub_mgr.renew_subscription(
            user_id=user_id, duration_days=30, admin_id=123
        )
        self.assertTrue(ok)
        self.assertEqual(restored_sub["status"], "active")
        expected_new_expiry = datetime.now(IST) + timedelta(days=30)
        diff2 = abs((restored_sub["expiry_time"] - expected_new_expiry).total_seconds())
        self.assertLess(diff2, 2)

    async def test_fr8_unique_invite_links_and_join_verification(self):
        """FR8: Generate unique per-user/per-destination invites with member_limit=1 and verify join."""
        user_id = 554433
        await self.sub_mgr.activate_subscription(
            user_id=user_id, plan_id="gold", duration_days=30
        )

        invites = await self.sub_mgr.generate_user_invites(self.client, user_id)
        # Gold has 2 destinations: dest_group1, dest_channel1
        self.assertEqual(len(invites), 2)
        for dest_id, link_info in invites.items():
            self.assertIn("invite_link", link_info)
            self.assertFalse(link_info["joined"])

        # Check client was called with member_limit=1
        for call in self.client.created_links:
            self.assertEqual(call[2], 1, "Must enforce member_limit=1 where supported")

        # Verify subscriber check before join
        chat_id_group = self.dest_mgr.get_destination("dest_group1")["chat_id"]
        is_allowed = await self.sub_mgr.is_user_subscribed_to_destination(user_id, chat_id_group)
        self.assertTrue(is_allowed)

        # Non-subscriber should be denied
        unauthorized = await self.sub_mgr.is_user_subscribed_to_destination(999999, chat_id_group)
        self.assertFalse(unauthorized)

        # Verify join and mark joined
        joined_ok = await self.sub_mgr.verify_and_record_join(user_id, chat_id_group)
        self.assertTrue(joined_ok)
        sub = await self.sub_mgr.get_user_subscription(user_id)
        self.assertTrue(sub["active_invite_links"]["dest_group1"]["joined"])

    async def test_fr9_and_fr10_expiry_enforcement_and_revocation(self):
        """FR9 & FR10: Remove access at expiry if not renewed, revoke invite links."""
        user_id = 778899
        await self.sub_mgr.activate_subscription(
            user_id=user_id, plan_id="vip", duration_days=30
        )
        await self.sub_mgr.generate_user_invites(self.client, user_id)

        # Fast forward expiry to past
        sub = await self.sub_mgr.get_user_subscription(user_id)
        sub["expiry_time"] = datetime.now(IST) - timedelta(hours=1)

        result = await self.sub_mgr.reconcile_expiries_and_reminders(self.client)
        self.assertEqual(result["expiries_processed"], 1)
        self.assertEqual(sub["status"], "expired")

        # User must have been kicked from all 3 destinations
        kicked_chat_ids = [c[0] for c in self.client.kicked_members if c[1] == user_id]
        self.assertEqual(len(kicked_chat_ids), 3)

        # Active invite links must have been revoked
        self.assertGreaterEqual(len(self.client.revoked_links), 3)

    async def test_fr11_and_fr12_reminders_and_dm_resilience(self):
        """FR11 & FR12: Reminders 1 day before and on expiry day; handle DM failures gracefully."""
        # User 1: 1 day before expiry
        u1 = 10001
        await self.sub_mgr.activate_subscription(u1, "silver", 10)
        sub1 = await self.sub_mgr.get_user_subscription(u1)
        sub1["expiry_time"] = datetime.now(IST) + timedelta(hours=23)

        # User 2: on expiry day (under 12 hours left)
        u2 = 10002
        await self.sub_mgr.activate_subscription(u2, "silver", 10)
        sub2 = await self.sub_mgr.get_user_subscription(u2)
        sub2["expiry_time"] = datetime.now(IST) + timedelta(hours=5)

        # User 3: blocked bot (DM failure test)
        u3 = 10003
        self.client.fail_dm_for_users.add(u3)
        await self.sub_mgr.activate_subscription(u3, "silver", 10)
        sub3 = await self.sub_mgr.get_user_subscription(u3)
        sub3["expiry_time"] = datetime.now(IST) + timedelta(hours=5)

        result = await self.sub_mgr.reconcile_expiries_and_reminders(self.client)

        self.assertGreaterEqual(result["reminders_sent"], 2)
        self.assertEqual(result["dm_failures"], 1, "Must handle DM failure without crashing")
        self.assertTrue(sub1["reminded_day_before"])
        self.assertTrue(sub2["reminded_expiry_day"])


if __name__ == "__main__":
    unittest.main()
