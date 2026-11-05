# Manual Payment Screenshot Approval System
# RKMOVIESZIP — Unified Payment Verification Layer for Bot & Destination Subscriptions
import time
import secrets
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

# Predefined rejection reasons
REJECTION_REASONS = [
    "Payment not received in our bank/UPI",
    "Invalid / Fake transaction screenshot",
    "Incorrect amount paid for this plan",
    "Duplicate or previously submitted transaction",
    "Transaction UTR / Reference ID unreadable",
]


class PaymentManager:
    """Manages persistent payment requests, admin approval, and independent entitlement dispatch."""

    def __init__(self, db_client=None, review_channel_id: Optional[int] = None, authorized_reviewers: Optional[List[int]] = None):
        self.db = db_client
        self.review_channel_id = review_channel_id
        self.authorized_reviewers: List[int] = authorized_reviewers or []
        # In-memory store for fast lookup and testing
        self._requests: Dict[str, dict] = {}
        # In-memory user payment selection state {user_id: {"product_type": ..., "plan_id": ..., ...}}
        self._user_plan_states: Dict[int, dict] = {}
        # In-memory admin pending prompt states {admin_id: {"action": "custom_msg"|"custom_reject", "req_id": ...}}
        self._admin_states: Dict[int, dict] = {}

    def set_db(self, db_client):
        self.db = db_client

    def set_review_channel(self, channel_id: int):
        self.review_channel_id = int(channel_id)

    def set_authorized_reviewers(self, reviewers: List[int]):
        self.authorized_reviewers = [int(r) for r in reviewers if r]

    def is_authorized_reviewer(self, user_id: int) -> bool:
        if not self.authorized_reviewers:
            return True
        return int(user_id) in self.authorized_reviewers

    # --- User Flow State Helpers ---

    def set_user_plan_selection(self, user_id: int, product_type: str, plan_id: str, plan_name: str, duration_days: int, amount: str):
        """Record what plan the user intends to pay for before they upload proof."""
        self._user_plan_states[int(user_id)] = {
            "product_type": product_type,  # 'bot_premium' or 'group_premium'
            "plan_id": plan_id,
            "plan_name": plan_name,
            "duration_days": int(duration_days),
            "amount": amount,
            "selected_at": datetime.now(IST),
        }

    def get_user_plan_selection(self, user_id: int) -> Optional[dict]:
        return self._user_plan_states.get(int(user_id))

    def clear_user_plan_selection(self, user_id: int):
        self._user_plan_states.pop(int(user_id), None)

    # --- Admin Input State Helpers ---

    def set_admin_state(self, admin_id: int, action: str, request_id: str):
        self._admin_states[int(admin_id)] = {
            "action": action,
            "request_id": request_id,
            "started_at": datetime.now(IST),
        }

    def get_admin_state(self, admin_id: int) -> Optional[dict]:
        return self._admin_states.get(int(admin_id))

    def clear_admin_state(self, admin_id: int):
        self._admin_states.pop(int(admin_id), None)

    # --- Core Request Lifecycle ---

    async def create_payment_request(
        self,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        product_type: str,
        plan_id: str,
        plan_name: str,
        duration_days: int,
        amount: str,
        screenshot_file_id: str,
    ) -> Tuple[bool, str, dict]:
        """User Payment Flow: Persist payment request with unique ID and pending status."""
        user_id = int(user_id)
        # Prevent spam: check if user already has an active pending payment
        existing_pending = await self.get_user_pending_request(user_id)
        if existing_pending:
            return False, f"You already have a pending payment request (<code>{existing_pending['request_id']}</code>) under review. Please wait for admin approval.", {}

        req_id = f"PAY_{int(time.time())}_{secrets.token_hex(3).upper()}"
        now = datetime.now(IST)

        request_doc = {
            "request_id": req_id,
            "user_id": user_id,
            "username": username or "",
            "first_name": first_name or "",
            "product_type": product_type,  # 'bot_premium' or 'group_premium'
            "plan_id": plan_id,
            "plan_name": plan_name,
            "duration_days": int(duration_days),
            "amount": amount,
            "screenshot_file_id": screenshot_file_id,
            "status": "pending",  # 'pending', 'approved', 'rejected'
            "submitted_at": now,
            "reviewed_by": None,
            "reviewed_at": None,
            "reject_reason": None,
            "review_message_id": None,
            "review_chat_id": None,
            "dm_delivery_failed": False,
        }

        self._requests[req_id] = request_doc

        if self.db is not None:
            try:
                await self.db["payment_requests"].update_one(
                    {"request_id": req_id},
                    {"$set": request_doc},
                    upsert=True,
                )
            except Exception as e:
                logger.error(f"Failed to persist payment request {req_id}: {e}")

        # Clear active plan selection state
        self.clear_user_plan_selection(user_id)
        return True, "Payment screenshot submitted successfully.", request_doc

    async def get_request(self, request_id: str) -> Optional[dict]:
        """Fetch request by unique ID."""
        if self.db is not None:
            try:
                doc = await self.db["payment_requests"].find_one({"request_id": request_id})
                if doc:
                    self._requests[request_id] = doc
                    return doc
            except Exception as e:
                logger.warning(f"Error fetching payment request {request_id}: {e}")
        return self._requests.get(request_id)

    async def get_user_pending_request(self, user_id: int) -> Optional[dict]:
        """Find if user has an existing pending request."""
        user_id = int(user_id)
        if self.db is not None:
            try:
                doc = await self.db["payment_requests"].find_one({"user_id": user_id, "status": "pending"})
                if doc:
                    self._requests[doc["request_id"]] = doc
                    return doc
            except Exception:
                pass
        for req in self._requests.values():
            if req.get("user_id") == user_id and req.get("status") == "pending":
                return req
        return None

    async def list_pending_requests(self, limit: int = 20) -> List[dict]:
        """List active pending payment requests."""
        if self.db is not None:
            try:
                results = []
                cursor = self.db["payment_requests"].find({"status": "pending"}).sort("submitted_at", -1).limit(limit)
                async for doc in cursor:
                    results.append(doc)
                return results
            except Exception:
                pass
        return [r for r in self._requests.values() if r.get("status") == "pending"][:limit]

    # --- Approval Workflow ---

    async def approve_payment_request(
        self,
        client: Any,
        request_id: str,
        admin_id: int,
        user_db: Any,
        sub_mgr: Any,
    ) -> Tuple[bool, str, dict]:
        """Approve payment atomically and activate ONLY the corresponding product."""
        req = await self.get_request(request_id)
        if not req:
            return False, f"Payment request '{request_id}' not found.", {}

        if req.get("status") != "pending":
            return False, f"Request {request_id} is already {req.get('status').upper()} (processed by {req.get('reviewed_by')}).", req

        now = datetime.now(IST)
        user_id = req["user_id"]
        product_type = req["product_type"]
        plan_id = req["plan_id"]
        plan_name = req["plan_name"]
        duration_days = req["duration_days"]

        # Atomic transition in DB: verify status is still pending
        if self.db is not None:
            try:
                res = await self.db["payment_requests"].update_one(
                    {"request_id": request_id, "status": "pending"},
                    {
                        "$set": {
                            "status": "approved",
                            "reviewed_by": int(admin_id),
                            "reviewed_at": now,
                        }
                    },
                )
                if res.modified_count == 0:
                    return False, f"Payment request {request_id} was already updated by another admin.", req
            except Exception as e:
                logger.error(f"Error updating payment status: {e}")

        req["status"] = "approved"
        req["reviewed_by"] = int(admin_id)
        req["reviewed_at"] = now
        self._requests[request_id] = req

        # 1. Activate corresponding product independently
        user_dm_delivered = False
        dm_error_msg = None

        if product_type == "bot_premium":
            # Bot Premium: activate via user_db
            try:
                current_user = await user_db.get_user(user_id) if hasattr(user_db, "get_user") else None
                existing_expiry = current_user.get("expiry_time") if current_user else None
                if existing_expiry:
                    if existing_expiry.tzinfo is None:
                        existing_expiry = IST.localize(existing_expiry)
                    if existing_expiry > now:
                        expiry_time = existing_expiry + timedelta(days=duration_days)
                    else:
                        expiry_time = now + timedelta(days=duration_days)
                else:
                    expiry_time = now + timedelta(days=duration_days)

                if hasattr(user_db, "update_user"):
                    await user_db.update_user({"id": user_id, "expiry_time": expiry_time})
                elif hasattr(user_db, "col"):
                    await user_db.col.update_one({"id": user_id}, {"$set": {"expiry_time": expiry_time}}, upsert=True)

                exp_str = expiry_time.strftime("%d-%m-%Y %I:%M %p")
                dm_text = get_desi_text(
                    "payment_approved_bot",
                    user_id=user_id,
                    plan_name=plan_name,
                    duration_days=duration_days,
                    expiry_str=exp_str,
                )
                if client:
                    await client.send_message(user_id, dm_text)
                    user_dm_delivered = True
            except Exception as e:
                dm_error_msg = str(e)
                logger.error(f"Failed to deliver approval DM to user {user_id}: {e}")

        elif product_type == "group_premium":
            # Group/Channel VIP: activate via subscription_manager
            try:
                ok, act_msg, sub_rec = await sub_mgr.activate_subscription(
                    user_id=user_id,
                    plan_id=plan_id,
                    duration_days=duration_days,
                    admin_id=admin_id,
                )
                if not ok:
                    logger.error(f"Failed to activate subscription for user {user_id}: {act_msg}")

                # Generate unique per-user, per-destination invite links
                invites = await sub_mgr.get_or_create_user_invites(client, user_id)
                exp_str = sub_rec["expiry_time"].strftime("%d-%m-%Y %I:%M %p") if "expiry_time" in sub_rec else ""

                buttons = []
                for item in invites:
                    dest_title = item.get("destination_name", "VIP Channel")
                    link = item.get("invite_link")
                    if link:
                        buttons.append([InlineKeyboardButton(f"JOIN {dest_title.upper()}", url=link)])
                buttons.append([
                    InlineKeyboardButton("MY ACTIVE PLANS", callback_data="my_plans_hub"),
                    InlineKeyboardButton("PREMIUM HUB", callback_data="premium_hub"),
                ])

                dm_text = get_desi_text(
                    "payment_approved_vip",
                    user_id=user_id,
                    plan_name=plan_name,
                    duration_days=duration_days,
                    expiry_str=exp_str,
                )
                if client:
                    await client.send_message(user_id, dm_text, reply_markup=InlineKeyboardMarkup(buttons))
                    user_dm_delivered = True
            except Exception as e:
                dm_error_msg = str(e)
                logger.error(f"Failed to deliver VIP approval DM to user {user_id}: {e}")

        if not user_dm_delivered and dm_error_msg:
            req["dm_delivery_failed"] = True
            if self.db is not None:
                try:
                    await self.db["payment_requests"].update_one(
                        {"request_id": request_id},
                        {"$set": {"dm_delivery_failed": True, "dm_error": dm_error_msg}},
                    )
                except Exception:
                    pass

        return True, f"Payment {request_id} approved successfully for user {user_id}.", req

    # --- Rejection Workflow ---

    async def reject_payment_request(
        self,
        client: Any,
        request_id: str,
        admin_id: int,
        reason: str,
    ) -> Tuple[bool, str, dict]:
        """Reject payment request without granting any entitlement."""
        req = await self.get_request(request_id)
        if not req:
            return False, f"Payment request '{request_id}' not found.", {}

        if req.get("status") != "pending":
            return False, f"Request {request_id} is already {req.get('status').upper()}.", req

        now = datetime.now(IST)
        user_id = req["user_id"]
        reason = reason.strip() if reason else "Verification details could not be matched."

        if self.db is not None:
            try:
                res = await self.db["payment_requests"].update_one(
                    {"request_id": request_id, "status": "pending"},
                    {
                        "$set": {
                            "status": "rejected",
                            "reviewed_by": int(admin_id),
                            "reviewed_at": now,
                            "reject_reason": reason,
                        }
                    },
                )
                if res.modified_count == 0:
                    return False, f"Payment request {request_id} was already updated by another admin.", req
            except Exception as e:
                logger.error(f"Error rejecting payment {request_id}: {e}")

        req["status"] = "rejected"
        req["reviewed_by"] = int(admin_id)
        req["reviewed_at"] = now
        req["reject_reason"] = reason
        self._requests[request_id] = req

        # Notify user of rejection with reason
        if client:
            try:
                buttons = [[InlineKeyboardButton("PREMIUM HUB", callback_data="premium_hub")]]
                rej_text = get_desi_text(
                    "payment_rejected",
                    user_id=user_id,
                    request_id=request_id,
                    reason=reason,
                )
                await client.send_message(
                    user_id,
                    rej_text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            except Exception as e:
                logger.warning(f"Could not send rejection DM to {user_id}: {e}")

        return True, f"Payment {request_id} rejected. Reason: {reason}", req

    # --- Custom Messaging Workflow ---

    async def send_custom_message(
        self,
        client: Any,
        request_id: str,
        admin_id: int,
        message_text: str,
    ) -> Tuple[bool, str]:
        """Send admin custom inquiry message to user without changing pending payment state."""
        req = await self.get_request(request_id)
        if not req:
            return False, f"Payment request '{request_id}' not found."

        user_id = req["user_id"]
        if not client:
            return True, f"Mock DM sent to user {user_id}."

        try:
            await client.send_message(
                user_id,
                f"<b>Message from Billing / Admin Support:</b>\n"
                f"<i>Regarding Payment Request: <code>{request_id}</code></i>\n\n"
                f"{message_text}\n\n"
                f"<i>Aap seedha is chat me reply ya clear screenshot send kar sakte hain.</i>"
            )
            return True, f"Custom message delivered to user {user_id}."
        except Exception as e:
            logger.error(f"Failed to send custom message to user {user_id}: {e}")
            return False, f"Could not send DM to user {user_id}: {e}"

    # --- Permission Test for Review Channel ---

    async def test_review_channel_permissions(self, client: Any, channel_id: int) -> dict:
        """Verify bot can post screenshots and text messages to the configured review channel."""
        if not client:
            return {"success": True, "can_post_messages": True, "title": "Mock Channel"}
        try:
            bot_member = await client.get_chat_member(channel_id, "me")
            priv = getattr(bot_member, "privileges", None)
            can_post = getattr(priv, "can_post_messages", True) if priv else True
            chat = await client.get_chat(channel_id)
            return {
                "success": True,
                "chat_id": channel_id,
                "title": getattr(chat, "title", "Review Channel"),
                "can_post_messages": can_post,
                "status": getattr(bot_member, "status", "unknown"),
            }
        except Exception as e:
            return {"success": False, "chat_id": channel_id, "error": str(e)}


# Global singleton instance
payment_manager = PaymentManager()


# --- UI Formatting and Inline Keyboards (ZERO COLOUR EMOJIS) ---

def format_review_message_caption(req: dict) -> str:
    """Format payment proof review caption for admin channel."""
    req_id = req.get("request_id")
    user_id = req.get("user_id")
    username = req.get("username")
    first_name = req.get("first_name", "User")
    product_type = req.get("product_type")
    prod_label = "BOT PREMIUM" if product_type == "bot_premium" else "COMMUNITY VIP"
    plan_name = req.get("plan_name", "Standard")
    days = req.get("duration_days", 30)
    amount = req.get("amount", "N/A")
    sub_at = req.get("submitted_at")
    sub_str = sub_at.strftime("%d-%m-%Y %I:%M %p") if hasattr(sub_at, "strftime") else str(sub_at)
    status = req.get("status", "pending").upper()

    user_mention = f"@{username}" if username else f"<code>{first_name}</code>"

    lines = [
        "<b>PAYMENT PROOF SUBMISSION</b>\n",
        f"• <b>Request ID:</b> <code>{req_id}</code>",
        f"• <b>User:</b> {user_mention} (<code>{user_id}</code>)",
        f"• <b>Product:</b> <code>{prod_label}</code>",
        f"• <b>Plan:</b> {plan_name} ({days} Days)",
        f"• <b>Amount:</b> <code>{amount}</code>",
        f"• <b>Submitted:</b> {sub_str} IST",
        f"• <b>Status:</b> <code>{status}</code>",
    ]
    if req.get("reviewed_by"):
        lines.append(f"• <b>Reviewed By:</b> <code>{req.get('reviewed_by')}</code>")
    if req.get("reject_reason"):
        lines.append(f"• <b>Reject Reason:</b> <i>{req.get('reject_reason')}</i>")
    if req.get("dm_delivery_failed"):
        lines.append("• <b>Warning:</b> User blocked bot / DM failed.")

    return "\n".join(lines)


def build_admin_review_keyboard(request_id: str):
    """Build approval action buttons with ZERO colour emojis."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("APPROVE", callback_data=f"pay_app#{request_id}"),
            InlineKeyboardButton("REJECT", callback_data=f"pay_rej#{request_id}"),
        ],
        [
            InlineKeyboardButton("CUSTOM MESSAGE", callback_data=f"pay_msg#{request_id}"),
        ],
    ])


def build_rejection_reasons_keyboard(request_id: str):
    """Build predefined rejection reasons keyboard with ZERO colour emojis."""
    buttons = []
    for idx, reason in enumerate(REJECTION_REASONS):
        buttons.append([InlineKeyboardButton(reason, callback_data=f"pay_rejr#{request_id}#{idx}")])
    buttons.append([
        InlineKeyboardButton("ENTER CUSTOM REASON", callback_data=f"pay_rejcustom#{request_id}"),
        InlineKeyboardButton("CANCEL", callback_data=f"pay_cancel#{request_id}"),
    ])
    return InlineKeyboardMarkup(buttons)


def format_user_payment_instructions(product_type: str, plan_name: str, duration_days: int, amount: str, user_id: Optional[int] = None) -> str:
    """Format instructions sent to user when starting payment flow."""
    prod_title = "BOT PREMIUM" if product_type == "bot_premium" else "COMMUNITY VIP"
    return get_desi_text(
        "payment_instructions",
        user_id=user_id,
        prod_title=prod_title,
        plan_name=plan_name,
        duration_days=duration_days,
        amount=amount,
    )
