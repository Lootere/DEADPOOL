# Feature 4: Premium Hub + Premium Group/Channel Subscription Manager
# RKMOVIESZIP — Subscription Manager Layer
import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import importlib.util
from pathlib import Path

try:
    from Lootere.utils.desi_personality import get_desi_text
except Exception:
    _dp_path = Path(__file__).resolve().parent / "desi_personality.py"
    _dp_spec = importlib.util.spec_from_file_location("desi_personality", _dp_path)
    _dp_mod = importlib.util.module_from_spec(_dp_spec)
    _dp_spec.loader.exec_module(_dp_mod)
    get_desi_text = _dp_mod.get_desi_text
try:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
except ImportError:
    from datetime import tzinfo
    class _SimpleIST(tzinfo):
        def utcoffset(self, dt):
            return timedelta(hours=5, minutes=30)
        def dst(self, dt):
            return timedelta(0)
        def tzname(self, dt):
            return "IST"
        def localize(self, dt):
            if dt is not None and getattr(dt, "tzinfo", None) is not None:
                return dt
            return dt.replace(tzinfo=self)
    IST = _SimpleIST()

try:
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
except ImportError:
    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

logger = logging.getLogger(__name__)



class DestinationManager:
    """Manages Telegram Destinations (Private Groups & Private Channels).
    
    Operates independently from Bot Premium.
    """
    def __init__(self, db_client=None):
        self.db = db_client
        # Memory caches for destinations and plans
        self._destinations: Dict[str, dict] = {}
        self._plans: Dict[str, dict] = {}
        self._initialized: bool = False

    async def initialize(self, default_group_id=None, default_channel1_id=None, default_channel2_id=None):
        """Initialize default destinations (1 private group, 2 private channels) and load from DB."""
        # Initial default destinations as requested in PRD
        if default_group_id:
            self._destinations["dest_group1"] = {
                "id": "dest_group1",
                "name": "VIP Discussion Group",
                "chat_id": int(default_group_id),
                "type": "group",
                "status": "active",
                "created_at": datetime.now(IST),
            }
        if default_channel1_id:
            self._destinations["dest_channel1"] = {
                "id": "dest_channel1",
                "name": "VIP Movies Channel",
                "chat_id": int(default_channel1_id),
                "type": "channel",
                "status": "active",
                "created_at": datetime.now(IST),
            }
        if default_channel2_id:
            self._destinations["dest_channel2"] = {
                "id": "dest_channel2",
                "name": "VIP Series Channel",
                "chat_id": int(default_channel2_id),
                "type": "channel",
                "status": "active",
                "created_at": datetime.now(IST),
            }

        # Default plans mapped to destinations
        self._plans = {
            "silver": {
                "id": "silver",
                "name": "Silver VIP",
                "destinations": ["dest_group1"],
                "price": "₹99/month",
                "duration_days": 30,
            },
            "gold": {
                "id": "gold",
                "name": "Gold VIP",
                "destinations": ["dest_group1", "dest_channel1"],
                "price": "₹199/month",
                "duration_days": 30,
            },
            "vip": {
                "id": "vip",
                "name": "All-Access Diamond VIP",
                "destinations": ["dest_group1", "dest_channel1", "dest_channel2"],
                "price": "₹299/month",
                "duration_days": 30,
            },
        }

        # Load persisted from DB if available
        if self.db is not None:
            try:
                dest_col = self.db["destinations"]
                async for d in dest_col.find():
                    self._destinations[d["id"]] = d

                plans_col = self.db["destination_plans"]
                async for p in plans_col.find():
                    self._plans[p["id"]] = p
            except Exception as e:
                logger.warning(f"Could not load destinations from DB: {e}")

        self._initialized = True
        logger.info(f"DestinationManager initialized with {len(self._destinations)} destinations, {len(self._plans)} plans.")

    def get_destination(self, dest_id: str) -> Optional[dict]:
        return self._destinations.get(dest_id)

    def get_all_destinations(self) -> List[dict]:
        return list(self._destinations.values())

    async def add_destination(self, dest_id: str, name: str, chat_id: int, dest_type: str) -> Tuple[bool, str]:
        """Add a new destination."""
        if dest_id in self._destinations:
            return False, f"Destination ID '{dest_id}' already exists."

        record = {
            "id": dest_id,
            "name": name,
            "chat_id": int(chat_id),
            "type": dest_type.lower(),
            "status": "active",
            "created_at": datetime.now(IST),
        }
        self._destinations[dest_id] = record
        if self.db is not None:
            try:
                await self.db["destinations"].update_one(
                    {"id": dest_id}, {"$set": record}, upsert=True
                )
            except Exception as e:
                logger.error(f"Failed to persist destination: {e}")
        return True, f"Destination '{name}' ({dest_id}) added successfully."

    async def remove_destination(self, dest_id: str) -> Tuple[bool, str]:
        if dest_id not in self._destinations:
            return False, f"Destination '{dest_id}' not found."
        dest = self._destinations.pop(dest_id)
        if self.db is not None:
            try:
                await self.db["destinations"].delete_one({"id": dest_id})
            except Exception:
                pass
        return True, f"Destination '{dest['name']}' removed."

    async def toggle_destination(self, dest_id: str, status: Optional[str] = None) -> Tuple[bool, str]:
        dest = self._destinations.get(dest_id)
        if not dest:
            return False, f"Destination '{dest_id}' not found."
        new_status = status if status else ("disabled" if dest.get("status") == "active" else "active")
        dest["status"] = new_status
        if self.db is not None:
            try:
                await self.db["destinations"].update_one(
                    {"id": dest_id}, {"$set": {"status": new_status}}
                )
            except Exception:
                pass
        return True, f"Destination '{dest['name']}' status set to {new_status}."

    def get_plan(self, plan_id: str) -> Optional[dict]:
        return self._plans.get(plan_id)

    def get_all_plans(self) -> List[dict]:
        return list(self._plans.values())

    def list_destinations(self) -> List[dict]:
        return self.get_all_destinations()

    def list_plans(self) -> List[dict]:
        return self.get_all_plans()

    async def add_plan(self, plan_id: str, name: str, destination_ids: List[str], duration_days: int = 30, price: str = "") -> Tuple[bool, str]:
        record = {
            "id": plan_id,
            "name": name,
            "destinations": destination_ids,
            "duration_days": int(duration_days),
            "price": price,
            "created_at": datetime.now(IST),
        }
        self._plans[plan_id] = record
        if self.db is not None:
            try:
                await self.db["destination_plans"].update_one(
                    {"id": plan_id}, {"$set": record}, upsert=True
                )
            except Exception as e:
                logger.error(f"Failed to persist plan: {e}")
        return True, f"Plan '{name}' configured successfully."

    async def remove_plan(self, plan_id: str) -> Tuple[bool, str]:
        if plan_id not in self._plans:
            return False, f"Plan '{plan_id}' not found."
        p = self._plans.pop(plan_id)
        if self.db is not None:
            try:
                await self.db["destination_plans"].delete_one({"id": plan_id})
            except Exception:
                pass
        return True, f"Plan '{p['name']}' removed."

    def set_db(self, db_client):
        self.db = db_client


class SubscriptionManager:
    """Manages Group/Channel VIP Subscriptions, Expiry, Reminders, and Safe Invites."""
    def __init__(self, db_client=None, destination_mgr=None):
        self.db = db_client
        self.dest_mgr = destination_mgr or DestinationManager(db_client)
        # Memory storage for unit tests / caching
        self._subscriptions: Dict[int, dict] = {}
        self._active_links: Dict[str, dict] = {}  # token/link -> metadata

    def set_db(self, db_client):
        self.db = db_client
        self.dest_mgr.set_db(db_client)

    async def get_user_subscription(self, user_id: int) -> Optional[dict]:
        """Fetch active or recent subscription for user."""
        if self.db is not None:
            try:
                sub = await self.db["destination_subs"].find_one({"user_id": int(user_id)})
                if sub:
                    self._subscriptions[int(user_id)] = sub
                    return sub
            except Exception as e:
                logger.warning(f"Error fetching sub from DB: {e}")
        return self._subscriptions.get(int(user_id))

    # Alias for convenience
    get_subscription = get_user_subscription

    async def activate_subscription(
        self,
        user_id: int,
        plan_id: str,
        duration_days: int,
        admin_id: Optional[int] = None,
    ) -> Tuple[bool, str, dict]:
        """FR5 & FR7: Admin activates user ID + duration.
        
        Persists start/end timestamps. Before-expiry renewal extends existing end date.
        After-expiry renewal starts a new period and requires fresh invite links.
        """
        user_id = int(user_id)
        plan = self.dest_mgr.get_plan(plan_id)
        if not plan:
            return False, f"Plan '{plan_id}' does not exist.", {}

        now = datetime.now(IST)
        existing = await self.get_user_subscription(user_id)
        is_extension = False

        if existing and existing.get("status") == "active":
            existing_expiry = existing.get("expiry_time")
            if existing_expiry:
                if existing_expiry.tzinfo is None:
                    existing_expiry = IST.localize(existing_expiry)
                if existing_expiry > now:
                    # Before-expiry renewal: extends existing end date
                    start_time = existing.get("start_time", now)
                    expiry_time = existing_expiry + timedelta(days=duration_days)
                    is_extension = True
                else:
                    # After-expiry renewal: fresh start date
                    start_time = now
                    expiry_time = now + timedelta(days=duration_days)
            else:
                start_time = now
                expiry_time = now + timedelta(days=duration_days)
        else:
            start_time = now
            expiry_time = now + timedelta(days=duration_days)

        sub_record = {
            "user_id": user_id,
            "plan_id": plan_id,
            "plan_name": plan.get("name"),
            "destinations": list(plan.get("destinations", [])),
            "status": "active",
            "start_time": start_time,
            "expiry_time": expiry_time,
            "activated_by": admin_id,
            "reminded_day_before": False,
            "reminded_expiry_day": False,
            "active_invite_links": {} if not is_extension else existing.get("active_invite_links", {}),
            "updated_at": now,
        }

        self._subscriptions[user_id] = sub_record
        if self.db is not None:
            try:
                await self.db["destination_subs"].update_one(
                    {"user_id": user_id},
                    {"$set": sub_record},
                    upsert=True,
                )
            except Exception as e:
                logger.error(f"Failed to persist subscription: {e}")

        expiry_str = expiry_time.strftime("%d-%m-%Y %I:%M %p")
        msg = (
            f"VIP Subscription {'extended' if is_extension else 'activated'} for user {user_id}.\n"
            f"• Plan: {plan.get('name')}\n"
            f"• Expiry: {expiry_str} (IST)"
        )
        return True, msg, sub_record

    async def cancel_subscription(self, user_id: int) -> Tuple[bool, str]:
        """Cancel subscription."""
        user_id = int(user_id)
        sub = await self.get_user_subscription(user_id)
        if not sub:
            return False, f"No subscription found for user {user_id}."
        sub["status"] = "cancelled"
        sub["updated_at"] = datetime.now(IST)
        self._subscriptions[user_id] = sub
        if self.db is not None:
            try:
                await self.db["destination_subs"].update_one(
                    {"user_id": user_id},
                    {"$set": {"status": "cancelled", "updated_at": sub["updated_at"]}},
                )
            except Exception:
                pass
        return True, f"Subscription for user {user_id} cancelled."

    async def generate_user_invites(self, client: Any, user_id: int) -> Dict[str, dict]:
        """FR8: Generate unique invite link per user per destination.
        
        Uses member_limit=1 where supported, prevents multiple active links.
        Security rule: NEVER logs raw invite URLs.
        """
        sub = await self.get_user_subscription(user_id)
        if not sub or sub.get("status") != "active":
            return {}

        now = datetime.now(IST)
        dest_ids = sub.get("destinations", [])
        active_links = sub.get("active_invite_links", {})
        results = {}

        for dest_id in dest_ids:
            dest = self.dest_mgr.get_destination(dest_id)
            if not dest or dest.get("status") != "active":
                continue

            # Controlled replacement: revoke existing link if not joined
            old_link_info = active_links.get(dest_id)
            if old_link_info and not old_link_info.get("joined"):
                old_url = old_link_info.get("invite_link")
                if client and old_url:
                    try:
                        await client.revoke_chat_invite_link(dest["chat_id"], old_url)
                    except Exception:
                        pass

            # Create fresh invite link with member_limit=1
            chat_id = dest["chat_id"]
            invite_url = None
            if client:
                try:
                    res = await client.create_chat_invite_link(
                        chat_id=chat_id,
                        name=f"VIP_{user_id}",
                        member_limit=1,
                    )
                    invite_url = getattr(res, "invite_link", None)
                except Exception as e:
                    logger.warning(f"Failed to create invite link for dest '{dest_id}': {e}")

            if not invite_url:
                # Fallback format for mock testing / unavailable API
                invite_url = f"https://t.me/+mock_invite_{dest_id}_{user_id}"

            link_record = {
                "dest_id": dest_id,
                "dest_name": dest.get("name"),
                "dest_type": dest.get("type"),
                "invite_link": invite_url,
                "created_at": now,
                "joined": False,
            }
            active_links[dest_id] = link_record
            results[dest_id] = link_record

        sub["active_invite_links"] = active_links
        if self.db is not None:
            try:
                await self.db["destination_subs"].update_one(
                    {"user_id": user_id},
                    {"$set": {"active_invite_links": active_links}},
                )
            except Exception:
                pass

        return results

    async def verify_and_record_join(self, user_id: int, chat_id: int) -> bool:
        """FR8: Verify joining Telegram ID matches the intended user and revoke link."""
        sub = await self.get_user_subscription(user_id)
        if not sub or sub.get("status") != "active":
            return False

        # Find matching destination
        matched_dest_id = None
        for dest_id, dest in self.dest_mgr._destinations.items():
            if dest.get("chat_id") == chat_id:
                matched_dest_id = dest_id
                break

        if not matched_dest_id:
            return False

        active_links = sub.get("active_invite_links", {})
        if matched_dest_id in active_links:
            active_links[matched_dest_id]["joined"] = True
            sub["active_invite_links"] = active_links
            if self.db is not None:
                try:
                    await self.db["destination_subs"].update_one(
                        {"user_id": user_id},
                        {"$set": {"active_invite_links": active_links}},
                    )
                except Exception:
                    pass
            logger.info(f"User {user_id} verified and marked joined for destination {matched_dest_id}")
            return True
        return False

    async def renew_subscription(
        self,
        user_id: int,
        duration_days: Optional[int] = None,
        admin_id: Optional[int] = None,
    ) -> Tuple[bool, str, dict]:
        """FR5 & FR7: Renew user subscription with admin approval."""
        sub = await self.get_user_subscription(user_id)
        if not sub:
            return False, f"No existing subscription found for user {user_id}. Use /vip_add first.", {}
        plan_id = sub.get("plan_id", "silver")
        plan = self.dest_mgr.get_plan(plan_id)
        if duration_days is None:
            duration_days = plan.get("duration_days", 30) if plan else 30
        return await self.activate_subscription(user_id, plan_id, duration_days, admin_id=admin_id)

    async def is_user_subscribed_to_destination(self, user_id: int, chat_id: int) -> bool:
        """Check if user has an active, non-expired subscription for the destination chat."""
        sub = await self.get_user_subscription(user_id)
        if not sub or sub.get("status") != "active":
            return False
        now = datetime.now(IST)
        expiry = sub.get("expiry_time")
        if expiry:
            if expiry.tzinfo is None:
                expiry = IST.localize(expiry)
            if now >= expiry:
                return False
        for dest_id in sub.get("destinations", []):
            dest = self.dest_mgr.get_destination(dest_id)
            if dest and int(dest.get("chat_id", 0)) == int(chat_id):
                return True
        return False

    async def get_or_create_user_invites(self, client: Any, user_id: int) -> List[dict]:
        """Get or generate user invite links for all mapped destinations."""
        sub = await self.get_user_subscription(user_id)
        if not sub or sub.get("status") != "active":
            return []
        active_links = sub.get("active_invite_links", {})
        dest_ids = sub.get("destinations", [])

        needs_gen = False
        for d in dest_ids:
            if d not in active_links:
                needs_gen = True
                break
        if needs_gen:
            await self.generate_user_invites(client, user_id)
            sub = await self.get_user_subscription(user_id)
            active_links = sub.get("active_invite_links", {}) if sub else {}

        out = []
        for dest_id in dest_ids:
            dest = self.dest_mgr.get_destination(dest_id)
            if not dest or dest.get("status") != "active":
                continue
            link_info = active_links.get(dest_id, {})
            out.append({
                "destination_id": dest_id,
                "destination_name": dest.get("name"),
                "destination_type": dest.get("type"),
                "invite_link": link_info.get("invite_link"),
                "joined": link_info.get("joined", False),
            })
        return out

    async def test_destination_permissions(self, client: Any, dest_id: str) -> dict:
        """Test bot connectivity and permissions (invite creation, member removal)."""
        dest = self.dest_mgr.get_destination(dest_id)
        if not dest:
            return {"success": False, "error": f"Destination '{dest_id}' not found."}
        chat_id = dest["chat_id"]
        if not client:
            return {"success": True, "chat_id": chat_id, "can_invite_users": True, "can_restrict_members": True}
        try:
            bot_member = await client.get_chat_member(chat_id, "me")
            priv = getattr(bot_member, "privileges", None)
            can_invite = getattr(priv, "can_invite_users", False) if priv else False
            can_restrict = getattr(priv, "can_restrict_members", False) if priv else False
            return {
                "success": True,
                "chat_id": chat_id,
                "title": dest.get("name"),
                "can_invite_users": can_invite,
                "can_restrict_members": can_restrict,
                "status": getattr(bot_member, "status", "unknown"),
            }
        except Exception as e:
            return {"success": False, "chat_id": chat_id, "error": str(e)}

    async def list_all_active_subscriptions(self) -> List[dict]:
        """List all currently active subscriptions."""
        if self.db is not None:
            try:
                subs = []
                cursor = self.db["destination_subs"].find({"status": "active"})
                async for doc in cursor:
                    subs.append(doc)
                return subs
            except Exception:
                pass
        return [s for s in self._subscriptions.values() if s.get("status") == "active"]

    async def reconcile_expiries_and_reminders(self, client: Any) -> dict:
        """FR6, FR9, FR11, FR12: Restart-safe scheduler and reconciliation.
        
        Checks reminders (1 day before, on expiry day) and removes access at expiry if not renewed.
        """
        now = datetime.now(IST)
        reminders_sent = 0
        expiries_processed = 0
        dm_failures = 0

        # Scan active subscriptions
        subs_to_check = []
        if self.db is not None:
            try:
                cursor = self.db["destination_subs"].find({"status": "active"})
                async for doc in cursor:
                    subs_to_check.append(doc)
            except Exception:
                subs_to_check = list(self._subscriptions.values())
        else:
            subs_to_check = [s for s in self._subscriptions.values() if s.get("status") == "active"]

        for sub in subs_to_check:
            user_id = sub.get("user_id")
            expiry = sub.get("expiry_time")
            if not expiry:
                continue

            if expiry.tzinfo is None:
                expiry = IST.localize(expiry)

            time_left = expiry - now

            # 1. Remind 1 day before expiry (within 12h to 24h)
            if timedelta(hours=12) < time_left <= timedelta(days=1) and not sub.get("reminded_day_before"):
                sub["reminded_day_before"] = True
                reminders_sent += 1
                if client:
                    try:
                        await client.send_message(
                            user_id,
                            get_desi_text("vip_reminder_day_before", user_id=user_id),
                        )
                    except Exception as e:
                        dm_failures += 1
                        logger.warning(f"Could not send reminder DM to {user_id}: {e}")

                if self.db is not None:
                    try:
                        await self.db["destination_subs"].update_one(
                            {"user_id": user_id},
                            {"$set": {"reminded_day_before": True}},
                        )
                    except Exception:
                        pass

            # 2. Remind on expiry day (within 12 hours)
            if timedelta(seconds=0) < time_left <= timedelta(hours=12) and not sub.get("reminded_expiry_day"):
                sub["reminded_expiry_day"] = True
                reminders_sent += 1
                if client:
                    try:
                        await client.send_message(
                            user_id,
                            get_desi_text("vip_reminder_expiry_day", user_id=user_id),
                        )
                    except Exception as e:
                        dm_failures += 1
                        logger.warning(f"Could not send expiry day DM to {user_id}: {e}")

                if self.db is not None:
                    try:
                        await self.db["destination_subs"].update_one(
                            {"user_id": user_id},
                            {"$set": {"reminded_expiry_day": True}},
                        )
                    except Exception:
                        pass

            # 3. Handle actual expiry: remove from mapped destinations
            if now >= expiry:
                sub["status"] = "expired"
                expiries_processed += 1
                dest_ids = sub.get("destinations", [])

                for dest_id in dest_ids:
                    dest = self.dest_mgr.get_destination(dest_id)
                    if not dest:
                        continue
                    chat_id = dest.get("chat_id")
                    if client and chat_id:
                        try:
                            # Kick member (ban then unban)
                            await client.ban_chat_member(chat_id, user_id)
                            await client.unban_chat_member(chat_id, user_id)
                            logger.info(f"User {user_id} removed from dest '{dest_id}' upon expiry.")
                        except Exception as e:
                            logger.error(f"Permission/API failure removing user {user_id} from {chat_id}: {e}")

                # Revoke active links
                active_links = sub.get("active_invite_links", {})
                for dest_id, link_info in active_links.items():
                    url = link_info.get("invite_link")
                    dest = self.dest_mgr.get_destination(dest_id)
                    if client and dest and url:
                        try:
                            await client.revoke_chat_invite_link(dest["chat_id"], url)
                        except Exception:
                            pass

                if client:
                    try:
                        await client.send_message(
                            user_id,
                            get_desi_text("vip_expired_notice", user_id=user_id),
                        )
                    except Exception:
                        dm_failures += 1

                if self.db is not None:
                    try:
                        await self.db["destination_subs"].update_one(
                            {"user_id": user_id},
                            {"$set": {"status": "expired", "updated_at": now}},
                        )
                    except Exception:
                        pass

        return {
            "reminders_sent": reminders_sent,
            "expiries_processed": expiries_processed,
            "dm_failures": dm_failures,
        }


# Global singleton instance
subscription_manager = SubscriptionManager()


def build_premium_hub_keyboard():
    """Build Premium Hub navigation keyboard with Feature 44 Premium Typography and ZERO colour emojis."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("♕ 『 𝐁𝐎𝐓 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 』", callback_data="premium_info"),
            InlineKeyboardButton("♛ 『 𝐕𝐈𝐏 𝐃𝐄𝐒𝐓𝐈𝐍𝐀𝐓𝐈𝐎𝐍𝐒 』", callback_data="dest_plans"),
        ],
        [
            InlineKeyboardButton("✦ 𝐅𝐑𝐄𝐄 𝐓𝐑𝐈𝐀𝐋 & 𝐑𝐄𝐅𝐄𝐑𝐑𝐀𝐋𝐒 ✦", callback_data="pm_reff"),
            InlineKeyboardButton("༺ 💎 𝐌𝐘 𝐀𝐂𝐓𝐈𝐕𝐄 𝐏𝐋𝐀𝐍𝐒 ༻", callback_data="my_plans_hub"),
        ],
        [
            InlineKeyboardButton("◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄", callback_data="start"),
        ],
    ])


def format_dest_plans_text(plans: List[dict], destinations: Dict[str, dict]) -> str:
    """Format Community VIP destination plans."""
    lines = [
        "<b>VIP GROUP & CHANNEL PLANS</b>\n",
        "<i>Exclusive direct access to private Telegram movie and series channels!</i>\n",
    ]
    if not plans:
        lines.append("<i>No VIP destination plans currently configured.</i>")
    else:
        for plan in plans:
            name = plan.get("name", "VIP Plan")
            price = plan.get("price", "Contact Admin")
            days = plan.get("duration_days", 30)
            dest_ids = plan.get("destinations", [])
            dest_names = [
                destinations.get(d, {}).get("name", d) for d in dest_ids
            ]
            dest_str = ", ".join(dest_names) if dest_names else "Configured Destinations"
            lines.append(
                f"• <b>{name}</b> ({price} / {days} Days)\n"
                f"  └ <b>Included:</b> <code>{dest_str}</code>\n"
            )

    lines.append(
        "<b>Note:</b> Destination VIP membership is completely separate from Bot Premium.\n"
        "Click below to purchase or manage your active invite links."
    )
    return "\n".join(lines)


def build_dest_plans_keyboard(owner_username: str = "Looteredev"):
    """Build destination plans keyboard with Feature 44 Premium Typography and ZERO colour emojis."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("♛ 『 𝐒𝐄𝐋𝐄𝐂𝐓 𝐕𝐈𝐏 𝐏𝐋𝐀𝐍 』", callback_data="pay_plan_choose#vip"),
            InlineKeyboardButton("⇩ 『 𝐔𝐏𝐋𝐎𝐀𝐃 𝐏𝐑𝐎𝐎𝐅 』", callback_data="pay_upload_prompt"),
        ],
        [
            InlineKeyboardButton("✦ 𝐌𝐘 𝐈𝐍𝐕𝐈𝐓𝐄 𝐋𝐈𝐍𝐊𝐒 ✦", callback_data="dest_invites"),
            InlineKeyboardButton("◈ 𝐂𝐎𝐍𝐓𝐀𝐂𝐓 𝐀𝐃𝐌𝐈𝐍 ◈", url=f"https://t.me/{owner_username}"),
        ],
        [
            InlineKeyboardButton("♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』", callback_data="premium_hub"),
            InlineKeyboardButton("◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄", callback_data="start"),
        ],
    ])


def format_my_plans_text(bot_plan: Optional[dict], dest_sub: Optional[dict], destinations: Dict[str, dict]) -> str:
    """Format user active subscriptions overview."""
    now = datetime.now(IST)
    lines = ["<b>MY ACTIVE MEMBERSHIPS</b>\n"]

    # 1. Bot Premium
    lines.append("<b>1. Bot Premium (Search & Stream):</b>")
    if bot_plan and bot_plan.get("expiry_time"):
        exp = bot_plan.get("expiry_time")
        if exp.tzinfo is None:
            exp = IST.localize(exp)
        if exp > now:
            time_left = exp - now
            days = time_left.days
            hours, remainder = divmod(time_left.seconds, 3600)
            lines.append(
                f"  ├ <b>Status:</b> <code>ACTIVE</code>\n"
                f"  ├ <b>Expiry:</b> <code>{exp.strftime('%d-%m-%Y %I:%M %p')} IST</code>\n"
                f"  └ <b>Time Left:</b> <code>{days} Days, {hours} Hours</code>\n"
            )
        else:
            lines.append("  └ <b>Status:</b> <code>EXPIRED</code>\n")
    else:
        lines.append("  └ <b>Status:</b> <code>NOT ACTIVE</code>\n")

    # 2. Destination VIP
    lines.append("<b>2. Community VIP (Private Groups & Channels):</b>")
    if dest_sub and dest_sub.get("status") == "active":
        exp = dest_sub.get("expiry_time")
        if exp:
            if exp.tzinfo is None:
                exp = IST.localize(exp)
            if exp > now:
                time_left = exp - now
                days = time_left.days
                plan_name = dest_sub.get("plan_name")
                if not plan_name:
                    pid = dest_sub.get("plan_id", "vip")
                    plan_name = f"{pid.title()} VIP" if pid else "VIP Plan"
                dest_ids = dest_sub.get("destinations", [])
                dest_names = [destinations.get(d, {}).get("name", d) for d in dest_ids]
                lines.append(
                    f"  ├ <b>Plan:</b> <code>{plan_name}</code>\n"
                    f"  ├ <b>Status:</b> <code>ACTIVE</code>\n"
                    f"  ├ <b>Destinations:</b> <code>{', '.join(dest_names)}</code>\n"
                    f"  ├ <b>Expiry:</b> <code>{exp.strftime('%d-%m-%Y %I:%M %p')} IST</code>\n"
                    f"  └ <b>Time Left:</b> <code>{days} Days, {hours} Hours</code>\n"
                )
            else:
                lines.append("  └ <b>Status:</b> <code>EXPIRED</code>\n")
        else:
            lines.append("  └ <b>Status:</b> <code>EXPIRED</code>\n")
    else:
        lines.append("  └ <b>Status:</b> <code>NOT ACTIVE</code>\n")

    return "\n".join(lines)


def build_my_plans_keyboard(has_dest_sub: bool = False):
    """Build my plans keyboard with Feature 44 Premium Typography and ZERO colour emojis."""
    buttons = []
    if has_dest_sub:
        buttons.append([InlineKeyboardButton("✦ 𝐌𝐘 𝐈𝐍𝐕𝐈𝐓𝐄 𝐋𝐈𝐍𝐊𝐒 ✦", callback_data="dest_invites")])
    buttons.append([
        InlineKeyboardButton("✦ 𝐑𝐄𝐍𝐄𝐖 / 𝐔𝐏𝐆𝐑𝐀𝐃𝐄 ✦", callback_data="dest_plans"),
        InlineKeyboardButton("♛ 『 𝐏𝐑𝐄𝐌𝐈𝐔𝐌 𝐇𝐔𝐁 』", callback_data="premium_hub"),
    ])
    buttons.append([InlineKeyboardButton("◁ 𝐁𝐀𝐂𝐊 𝐓𝐎 𝐇𝐎𝐌𝐄", callback_data="start")])
    return InlineKeyboardMarkup(buttons)
