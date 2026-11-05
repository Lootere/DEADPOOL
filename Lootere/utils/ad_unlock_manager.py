# Feature 45 – RKMOVIESZIP Watch Ad to Unlock File
#
# Additive access-control and monetization module:
# - Core Rule: 1 verified ad = 1 file delivery, one-time only
# - Preserves Daily Free Limit (does not reset quota)
# - Enforces Feature 43 Admin Personal File Lock & Resolution Lock precedence
# - Safe retry on Telegram delivery error within expiry window
# - Atomic state transitions & replay protection

import asyncio
import importlib.util
import logging
from pathlib import Path
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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

try:
    from Lootere.utils.button_typography import get_button_label
except Exception:
    _bt_path = Path(__file__).resolve().parent / "button_typography.py"
    _bt_spec = importlib.util.spec_from_file_location("button_typography", _bt_path)
    _bt_mod = importlib.util.module_from_spec(_bt_spec)
    assert _bt_spec and _bt_spec.loader
    _bt_spec.loader.exec_module(_bt_mod)
    get_button_label = _bt_mod.get_button_label

logger = logging.getLogger(__name__)

# Authorization lifecycle states (Section 9 of PRD)
STATE_PENDING_VERIFICATION = "PENDING_VERIFICATION"
STATE_VERIFIED = "VERIFIED"
STATE_DELIVERY_IN_PROGRESS = "DELIVERY_IN_PROGRESS"
STATE_CONSUMED = "CONSUMED"
STATE_EXPIRED = "EXPIRED"
STATE_FAILED = "FAILED"

DEFAULT_AD_UNLOCK_EXPIRY_SECONDS = 600  # 10 minutes default (Section 4)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_daily_limit_exhausted_text() -> str:
    """Return the exact Section 2.1 Daily Limit Exhausted prompt."""
    return (
        "<b>⚠️ 𝐃𝐀𝐈𝐋𝐘 𝐋𝐈𝐌𝐈𝐓 𝐑𝐄𝐀𝐂𝐇𝐄𝐃</b>\n\n"
        "Aaj ki free file limit khatam ho gayi hai!\n\n"
        "File chahiye? Premium le lo, ya ek ad verify karke apni selected file unlock kar lo."
    )


def build_daily_limit_exhausted_keyboard(
    grp_id: int,
    canonical_file_id: str,
    pre: str = "files",
    ad_unlock_enabled: bool = True,
    use_plain_fallback: bool = False,
) -> InlineKeyboardMarkup:
    """Build the Section 2.1 Daily Limit Reached keyboard with Feature 44 Unicode buttons."""
    buy_label = get_button_label("ad_buy_premium", use_plain_fallback=use_plain_fallback)
    watch_label = get_button_label("ad_watch_unlock", use_plain_fallback=use_plain_fallback)
    back_label = get_button_label("nav_back", use_plain_fallback=use_plain_fallback)

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(buy_label, callback_data="premium_info")],
    ]
    if ad_unlock_enabled and canonical_file_id:
        rows.append(
            [
                InlineKeyboardButton(
                    watch_label,
                    callback_data=f"ad_unlock_start#{int(grp_id)}#{pre}#{canonical_file_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(back_label, callback_data="start")])
    return InlineKeyboardMarkup(rows)


def build_ad_verification_prompt_text(file_name: str, expiry_seconds: int = DEFAULT_AD_UNLOCK_EXPIRY_SECONDS) -> str:
    """Build the Watch Ad verification instructions message."""
    mins = max(1, int(expiry_seconds) // 60)
    return (
        "<b>✦ 𝐖𝐀𝐓𝐂𝐇 𝐀𝐃 & 𝐔𝐍𝐋𝐎𝐂𝐊 𝐅𝐈𝐋𝐄 ✦</b>\n\n"
        f"🎬 <b>Selected File:</b> <code>{file_name}</code>\n"
        f"⏳ <b>Validity:</b> One-time delivery ({mins} mins after verification)\n"
        "📌 <b>Rule:</b> 1 Verified Ad = 1 Selected File\n\n"
        "Neeche <b>𝐕𝐄𝐑𝐈𝐅𝐘 𝐀𝐃</b> button par click karke verification poora karein, "
        "phir aapko seedha isi file ka unlock link mil jayega!"
    )


def build_ad_verification_keyboard(
    verify_url: str,
    tutorial_url: Optional[str] = None,
    use_plain_fallback: bool = False,
) -> InlineKeyboardMarkup:
    """Build the Watch Ad verification inline keyboard (Section 8)."""
    verify_label = get_button_label("ad_verify_ad", use_plain_fallback=use_plain_fallback)
    how_to_label = get_button_label("file_how_to_verify", use_plain_fallback=use_plain_fallback)
    buy_label = get_button_label("ad_buy_premium", use_plain_fallback=use_plain_fallback)
    back_label = get_button_label("nav_back", use_plain_fallback=use_plain_fallback)

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(verify_label, url=verify_url)],
    ]
    if tutorial_url:
        rows.append([InlineKeyboardButton(how_to_label, url=tutorial_url)])
    rows.append([InlineKeyboardButton(buy_label, callback_data="premium_info")])
    rows.append([InlineKeyboardButton(back_label, callback_data="start")])
    return InlineKeyboardMarkup(rows)


def build_ad_verified_ready_text(file_name: str, expiry_seconds: int = DEFAULT_AD_UNLOCK_EXPIRY_SECONDS) -> str:
    """Build the message shown once the user completes ad verification."""
    mins = max(1, int(expiry_seconds) // 60)
    return (
        "<b>✅ 𝐀𝐃 𝐕𝐄𝐑𝐈𝐅𝐈𝐂𝐀𝐓𝐈𝐎𝐍 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃</b>\n\n"
        f"🎬 <b>Unlocked File:</b> <code>{file_name}</code>\n"
        f"⏳ <b>One-Time Access Window:</b> {mins} minutes\n\n"
        "Aapka one-time file unlock tayyar hai! Neeche <b>𝐆𝐄𝐓 𝐅𝐈𝐋𝐄</b> par click karke apni file le lo."
    )


def build_ad_verified_delivery_keyboard(
    unlock_request_id: str,
    use_plain_fallback: bool = False,
) -> InlineKeyboardMarkup:
    """Build the keyboard with `⇩ 𝐆𝐄𝐓 𝐅𝐈𝐋𝐄` to claim the single unlocked file."""
    get_file_label = get_button_label("ad_get_file", use_plain_fallback=use_plain_fallback)
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(get_file_label, callback_data=f"ad_deliver#{unlock_request_id}")]]
    )


class AdUnlockManager:
    """Manages one-time Watch Ad to Unlock requests, verification, and atomic delivery."""

    def __init__(self) -> None:
        self._requests: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._enabled: bool = True
        self._expiry_seconds: int = DEFAULT_AD_UNLOCK_EXPIRY_SECONDS
        self._personal_locked_files: Set[str] = set()
        self._simulate_db_unavailable: bool = False
        self._metrics: Dict[str, int] = {
            "requests_created": 0,
            "verifications_succeeded": 0,
            "verifications_failed": 0,
            "verifications_expired": 0,
            "deliveries_succeeded": 0,
            "deliveries_failed": 0,
            "replay_attempts_blocked": 0,
            "premium_lock_blocks": 0,
        }

    def _get_lock(self, unlock_request_id: str) -> asyncio.Lock:
        if unlock_request_id not in self._locks:
            self._locks[unlock_request_id] = asyncio.Lock()
        return self._locks[unlock_request_id]

    # ------------------------------------------------------------------
    # Admin Configuration & Feature 43 Personal File Lock Management
    # ------------------------------------------------------------------

    async def is_enabled(self, user_db: Any = None) -> bool:
        if user_db is not None and hasattr(user_db, "get_setting"):
            try:
                val = await user_db.get_setting("AD_UNLOCK_ENABLED", default=self._enabled)
                return bool(val)
            except Exception:
                pass
        return self._enabled

    async def set_enabled(self, enabled: bool, user_db: Any = None) -> bool:
        self._enabled = bool(enabled)
        if user_db is not None and hasattr(user_db, "set_setting"):
            try:
                await user_db.set_setting("AD_UNLOCK_ENABLED", self._enabled)
            except Exception:
                pass
        return self._enabled

    async def get_expiry_seconds(self, user_db: Any = None) -> int:
        if user_db is not None and hasattr(user_db, "get_setting"):
            try:
                val = await user_db.get_setting("AD_UNLOCK_EXPIRY_SECONDS", default=self._expiry_seconds)
                return max(60, int(val))
            except Exception:
                pass
        return self._expiry_seconds

    async def set_expiry_seconds(self, seconds: int, user_db: Any = None) -> int:
        self._expiry_seconds = max(60, int(seconds))
        if user_db is not None and hasattr(user_db, "set_setting"):
            try:
                await user_db.set_setting("AD_UNLOCK_EXPIRY_SECONDS", self._expiry_seconds)
            except Exception:
                pass
        return self._expiry_seconds

    async def lock_personal_file(self, canonical_file_id: str, user_db: Any = None) -> None:
        """Feature 43: Mark a specific file_id as Admin Personal / Premium-exclusive locked."""
        clean_id = str(canonical_file_id or "").strip()
        if not clean_id:
            return
        self._personal_locked_files.add(clean_id)
        if user_db is not None and hasattr(user_db, "get_setting") and hasattr(user_db, "set_setting"):
            try:
                existing = await user_db.get_setting("PERSONAL_LOCKED_FILES", default=[])
                updated = sorted(set(existing or []) | {clean_id})
                await user_db.set_setting("PERSONAL_LOCKED_FILES", updated)
            except Exception:
                pass

    async def unlock_personal_file(self, canonical_file_id: str, user_db: Any = None) -> None:
        """Feature 43: Remove Admin Personal lock from a specific file_id."""
        clean_id = str(canonical_file_id or "").strip()
        self._personal_locked_files.discard(clean_id)
        if user_db is not None and hasattr(user_db, "get_setting") and hasattr(user_db, "set_setting"):
            try:
                existing = await user_db.get_setting("PERSONAL_LOCKED_FILES", default=[])
                updated = [fid for fid in (existing or []) if fid != clean_id]
                await user_db.set_setting("PERSONAL_LOCKED_FILES", updated)
            except Exception:
                pass

    async def get_personal_locked_files(self, user_db: Any = None) -> Set[str]:
        locked = set(self._personal_locked_files)
        if user_db is not None and hasattr(user_db, "get_setting"):
            try:
                db_locked = await user_db.get_setting("PERSONAL_LOCKED_FILES", default=[])
                if db_locked:
                    locked.update(str(x) for x in db_locked)
            except Exception:
                pass
        return locked

    async def is_file_premium_locked(
        self,
        canonical_file_id: str,
        file_name: Optional[str] = None,
        user_db: Any = None,
        resolution_lock_checker: Optional[Callable[[str], Any]] = None,
    ) -> bool:
        """Check whether a file is Premium-exclusive under Feature 43 or Resolution Lock."""
        clean_id = str(canonical_file_id or "").strip()
        locked_ids = await self.get_personal_locked_files(user_db=user_db)
        if clean_id in locked_ids:
            return True
        if file_name and resolution_lock_checker is not None:
            res = resolution_lock_checker(file_name)
            if asyncio.iscoroutine(res):
                res = await res
            if res:
                return True
        return False

    # ------------------------------------------------------------------
    # Persistence Helpers (Fail-Closed on DB Error)
    # ------------------------------------------------------------------

    def _get_collection(self, user_db: Any) -> Any:
        if user_db is None:
            return None
        raw_db = getattr(user_db, "db", None)
        if raw_db is None:
            return None
        return getattr(raw_db, "ad_unlock_requests", None)

    async def _save_request_record(self, record: Dict[str, Any], user_db: Any = None) -> bool:
        if self._simulate_db_unavailable:
            raise RuntimeError("Database persistence unavailable (fail-closed)")
        req_id = record["unlock_request_id"]
        self._requests[req_id] = dict(record)
        col = self._get_collection(user_db)
        if col is not None:
            await col.update_one(
                {"unlock_request_id": req_id},
                {"$set": dict(record)},
                upsert=True,
            )
        return True

    async def get_request(self, unlock_request_id: str, user_db: Any = None) -> Optional[Dict[str, Any]]:
        if self._simulate_db_unavailable:
            raise RuntimeError("Database persistence unavailable (fail-closed)")
        req_id = str(unlock_request_id or "").strip()
        if not req_id:
            return None
        col = self._get_collection(user_db)
        if col is not None:
            try:
                doc = await col.find_one({"unlock_request_id": req_id})
                if doc:
                    doc.pop("_id", None)
                    self._requests[req_id] = dict(doc)
                    return dict(doc)
            except Exception as exc:
                logger.error("Failed to fetch ad_unlock_request %s from DB: %s", req_id, exc)
                raise
        cached = self._requests.get(req_id)
        return dict(cached) if cached else None

    # ------------------------------------------------------------------
    # Lifecycle Step 1: Create Short-Lived User-Bound Unlock Request
    # ------------------------------------------------------------------

    async def create_unlock_request(
        self,
        telegram_user_id: int,
        canonical_file_id: str,
        grp_id: int = 0,
        pre: str = "files",
        file_name: Optional[str] = None,
        user_db: Any = None,
        resolution_lock_checker: Optional[Callable[[str], Any]] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Create a short-lived, user-bound, single-file ad-unlock request."""
        try:
            if not await self.is_enabled(user_db=user_db):
                return False, "Watch Ad to Unlock is currently disabled by Admin.", None

            clean_file_id = str(canonical_file_id or "").strip()
            if not clean_file_id:
                return False, "Invalid file selection.", None

            # Feature 43 / Premium-exclusive precedence check (Section 5 & Section 6)
            if await self.is_file_premium_locked(
                clean_file_id,
                file_name=file_name,
                user_db=user_db,
                resolution_lock_checker=resolution_lock_checker,
            ):
                self._metrics["premium_lock_blocks"] += 1
                logger.info(
                    "ad_unlock blocked by Premium file lock (user_id=%s, file_id=%s)",
                    telegram_user_id,
                    clean_file_id,
                )
                return (
                    False,
                    "Ye file sirf Premium members ke liye locked hai. Iske liye Premium plan lein.",
                    None,
                )

            expiry_secs = await self.get_expiry_seconds(user_db=user_db)
            now = _utcnow()
            unlock_request_id = f"ADU{secrets.token_hex(5).upper()}"
            verification_attempt_id = secrets.token_urlsafe(9).replace("_", "A").replace("-", "B")[:12]

            record: Dict[str, Any] = {
                "unlock_request_id": unlock_request_id,
                "telegram_user_id": int(telegram_user_id),
                "canonical_file_id": clean_file_id,
                "file_name": file_name or clean_file_id,
                "grp_id": int(grp_id),
                "pre": str(pre or "files"),
                "verification_attempt_id": verification_attempt_id,
                "verification_status": "PENDING",
                "authorization_status": STATE_PENDING_VERIFICATION,
                "created_at": now,
                "verified_at": None,
                "expires_at": now + timedelta(seconds=expiry_secs),
                "consumed_at": None,
                "delivery_reference": None,
                "last_error": None,
            }

            await self._save_request_record(record, user_db=user_db)
            self._metrics["requests_created"] += 1
            logger.info(
                "Created ad_unlock_request id=%s user_id=%s file_id=%s",
                unlock_request_id,
                telegram_user_id,
                clean_file_id,
            )
            return True, "Unlock request created.", record

        except Exception as exc:
            logger.error(
                "Failed to create ad_unlock_request (user_id=%s, file_id=%s): %s",
                telegram_user_id,
                canonical_file_id,
                exc,
            )
            return False, "Service temporarily unavailable. Please try again later.", None

    # ------------------------------------------------------------------
    # Lifecycle Step 2: Verify Trusted Completion Callback / Deep-Link
    # ------------------------------------------------------------------

    async def verify_unlock_request(
        self,
        unlock_request_id: str,
        actor_user_id: int,
        verification_attempt_id: str,
        user_db: Any = None,
        file_name: Optional[str] = None,
        resolution_lock_checker: Optional[Callable[[str], Any]] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validate trusted shortener completion and issue a one-time VERIFIED authorization."""
        req_id = str(unlock_request_id or "").strip()
        async with self._get_lock(req_id):
            try:
                record = await self.get_request(req_id, user_db=user_db)
            except Exception as exc:
                logger.error("DB error during verify_unlock_request id=%s: %s", req_id, exc)
                self._metrics["verifications_failed"] += 1
                return False, "Verification service unavailable. Please try again.", None

            if not record:
                self._metrics["verifications_failed"] += 1
                return False, "Invalid or unknown ad-unlock verification link.", None

            # 1. Strict User Binding (Section 4 & Section 10)
            if int(record["telegram_user_id"]) != int(actor_user_id):
                self._metrics["verifications_failed"] += 1
                self._metrics["replay_attempts_blocked"] += 1
                logger.warning(
                    "Cross-user ad_unlock verification rejected (req_id=%s, owner=%s, actor=%s)",
                    req_id,
                    record["telegram_user_id"],
                    actor_user_id,
                )
                return False, "Ye verification link kisi aur user ka hai. Apna khud ka link generate karein.", None

            # 2. Check replay / already consumed or verified
            auth_status = record.get("authorization_status")
            if auth_status == STATE_CONSUMED:
                self._metrics["replay_attempts_blocked"] += 1
                return False, "Ye ad-unlock link pehle hi use ho chuka hai. Nayi file ke liye dobara verify karein.", None

            if auth_status in (STATE_VERIFIED, STATE_DELIVERY_IN_PROGRESS):
                self._metrics["replay_attempts_blocked"] += 1
                return False, "Ye verification link pehle hi verify ho chuka hai.", record

            # 3. Validate cryptographic attempt token
            expected_token = str(record.get("verification_attempt_id") or "")
            if not expected_token or not secrets.compare_digest(expected_token, str(verification_attempt_id or "")):
                self._metrics["verifications_failed"] += 1
                record["verification_status"] = "FAILED"
                record["authorization_status"] = STATE_FAILED
                record["last_error"] = "Token mismatch"
                await self._save_request_record(record, user_db=user_db)
                return False, "Invalid verification token. Kripya naya Watch Ad link banayein.", None

            # 4. Check expiration
            now = _utcnow()
            expires_at = _ensure_utc(record.get("expires_at"))
            if expires_at and now > expires_at:
                record["verification_status"] = "EXPIRED"
                record["authorization_status"] = STATE_EXPIRED
                await self._save_request_record(record, user_db=user_db)
                self._metrics["verifications_expired"] += 1
                return False, "Verification link expire ho gaya hai. Kripya dobara Watch Ad & Unlock karein.", None

            # 5. Re-check Feature 43 / Premium-exclusive lock
            effective_name = file_name or record.get("file_name")
            if await self.is_file_premium_locked(
                record["canonical_file_id"],
                file_name=effective_name,
                user_db=user_db,
                resolution_lock_checker=resolution_lock_checker,
            ):
                record["verification_status"] = "FAILED"
                record["authorization_status"] = STATE_FAILED
                record["last_error"] = "File locked for Premium"
                await self._save_request_record(record, user_db=user_db)
                self._metrics["premium_lock_blocks"] += 1
                return (
                    False,
                    "Ye file ab Premium-only lock mein hai. Isko access karne ke liye Premium lein.",
                    None,
                )

            # 6. Transition to VERIFIED with fresh pending delivery expiry window
            expiry_secs = await self.get_expiry_seconds(user_db=user_db)
            record["verification_status"] = "VERIFIED"
            record["authorization_status"] = STATE_VERIFIED
            record["verified_at"] = now
            record["expires_at"] = now + timedelta(seconds=expiry_secs)
            if file_name:
                record["file_name"] = file_name
            await self._save_request_record(record, user_db=user_db)
            self._metrics["verifications_succeeded"] += 1
            logger.info(
                "Verified ad_unlock_request id=%s user_id=%s file_id=%s",
                req_id,
                actor_user_id,
                record["canonical_file_id"],
            )
            return True, "Ad verification successful!", record

    # ------------------------------------------------------------------
    # Lifecycle Step 3: Atomic Claim & Single-File Delivery Boundary
    # ------------------------------------------------------------------

    async def begin_file_delivery(
        self,
        unlock_request_id: str,
        actor_user_id: int,
        user_db: Any = None,
        file_name: Optional[str] = None,
        resolution_lock_checker: Optional[Callable[[str], Any]] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Atomically validate and transition VERIFIED -> DELIVERY_IN_PROGRESS before sending media."""
        req_id = str(unlock_request_id or "").strip()
        async with self._get_lock(req_id):
            try:
                record = await self.get_request(req_id, user_db=user_db)
            except Exception as exc:
                logger.error("DB error during begin_file_delivery id=%s: %s", req_id, exc)
                return False, "Service temporarily unavailable. Please try again.", None

            if not record:
                return False, "Unlock request not found.", None

            # 1. Verify User Ownership
            if int(record["telegram_user_id"]) != int(actor_user_id):
                self._metrics["replay_attempts_blocked"] += 1
                return False, "Ye unlock request aapke account ke liye nahi hai.", None

            # 2. Check current authorization status
            auth_status = record.get("authorization_status")
            if auth_status == STATE_CONSUMED:
                self._metrics["replay_attempts_blocked"] += 1
                return (
                    False,
                    "Ye one-time unlock pehle hi use ho chuka hai! Agli file ke liye naya ad verify karein.",
                    None,
                )

            if auth_status == STATE_DELIVERY_IN_PROGRESS:
                self._metrics["replay_attempts_blocked"] += 1
                return False, "File abhi bheji ja rahi hai, kripya thoda wait karein.", None

            if auth_status == STATE_PENDING_VERIFICATION or record.get("verification_status") != "VERIFIED":
                return False, "Ad verification abhi poora nahi hua hai. Pehle ad verify karein.", None

            if auth_status in (STATE_EXPIRED, STATE_FAILED):
                return False, "Ye unlock authorization expire ya invalid ho chuka hai.", None

            # 3. Check expiry window
            now = _utcnow()
            expires_at = _ensure_utc(record.get("expires_at"))
            if expires_at and now > expires_at:
                record["authorization_status"] = STATE_EXPIRED
                record["verification_status"] = "EXPIRED"
                await self._save_request_record(record, user_db=user_db)
                self._metrics["verifications_expired"] += 1
                return False, "Unlock authorization ka time (10 mins) khatam ho gaya hai. Dobara verify karein.", None

            # 4. Re-check Feature 43 / Premium-exclusive lock immediately before delivery (Section 10)
            effective_name = file_name or record.get("file_name")
            if await self.is_file_premium_locked(
                record["canonical_file_id"],
                file_name=effective_name,
                user_db=user_db,
                resolution_lock_checker=resolution_lock_checker,
            ):
                record["authorization_status"] = STATE_FAILED
                record["last_error"] = "Blocked by Feature 43 lock at delivery boundary"
                await self._save_request_record(record, user_db=user_db)
                self._metrics["premium_lock_blocks"] += 1
                return (
                    False,
                    "Ye file Premium-only lock mein hai. Watch Ad se unlock nahi ho sakti.",
                    None,
                )

            # 5. Transition atomically to DELIVERY_IN_PROGRESS
            record["authorization_status"] = STATE_DELIVERY_IN_PROGRESS
            await self._save_request_record(record, user_db=user_db)
            return True, "Ready for delivery", record

    async def mark_delivery_consumed(
        self,
        unlock_request_id: str,
        delivery_reference: Optional[str] = None,
        user_db: Any = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Mark the authorization CONSUMED after Telegram successfully delivers the file."""
        req_id = str(unlock_request_id or "").strip()
        async with self._get_lock(req_id):
            record = await self.get_request(req_id, user_db=user_db)
            if not record:
                return False, None
            record["authorization_status"] = STATE_CONSUMED
            record["consumed_at"] = _utcnow()
            record["delivery_reference"] = str(delivery_reference or "delivered")
            record["last_error"] = None
            await self._save_request_record(record, user_db=user_db)
            self._metrics["deliveries_succeeded"] += 1
            logger.info(
                "Consumed ad_unlock_request id=%s user_id=%s file_id=%s ref=%s",
                req_id,
                record["telegram_user_id"],
                record["canonical_file_id"],
                record["delivery_reference"],
            )
            return True, record

    async def abort_delivery_for_retry(
        self,
        unlock_request_id: str,
        error_reason: str,
        user_db: Any = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Section 4 Delivery Failure Policy: Revert to VERIFIED if Telegram send fails before file delivery."""
        req_id = str(unlock_request_id or "").strip()
        async with self._get_lock(req_id):
            record = await self.get_request(req_id, user_db=user_db)
            if not record:
                return False, None
            now = _utcnow()
            expires_at = _ensure_utc(record.get("expires_at"))
            if expires_at and now > expires_at:
                record["authorization_status"] = STATE_EXPIRED
            else:
                record["authorization_status"] = STATE_VERIFIED
            record["last_error"] = str(error_reason or "Telegram delivery error")
            await self._save_request_record(record, user_db=user_db)
            self._metrics["deliveries_failed"] += 1
            logger.warning(
                "Reverted ad_unlock_request id=%s to VERIFIED for safe retry after delivery failure: %s",
                req_id,
                error_reason,
            )
            return True, record

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Return operational counters and status for Admin visibility (Section 11)."""
        return {
            "enabled": self._enabled,
            "expiry_seconds": self._expiry_seconds,
            "personal_locked_files_count": len(self._personal_locked_files),
            **self._metrics,
        }


ad_unlock_manager = AdUnlockManager()
