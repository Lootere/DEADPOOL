import unittest
import os
import sys
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_DP_PATH = _ROOT / "Lootere" / "utils" / "desi_personality.py"
_DP_SPEC = importlib.util.spec_from_file_location("Lootere.utils.desi_personality", _DP_PATH)
desi_personality_mod = importlib.util.module_from_spec(_DP_SPEC)
assert _DP_SPEC and _DP_SPEC.loader
sys.modules["Lootere.utils.desi_personality"] = desi_personality_mod
_DP_SPEC.loader.exec_module(desi_personality_mod)

DESI_FLIRTY_TEMPLATES = desi_personality_mod.DESI_FLIRTY_TEMPLATES
NEUTRAL_FALLBACK_TEMPLATES = desi_personality_mod.NEUTRAL_FALLBACK_TEMPLATES
DesiFlirtyPersonalityEngine = desi_personality_mod.DesiFlirtyPersonalityEngine
personality_engine = desi_personality_mod.personality_engine
get_desi_text = desi_personality_mod.get_desi_text

_PAY_PATH = _ROOT / "Lootere" / "utils" / "payment_manager.py"
_PAY_SPEC = importlib.util.spec_from_file_location("Lootere.utils.payment_manager", _PAY_PATH)
payment_manager_mod = importlib.util.module_from_spec(_PAY_SPEC)
assert _PAY_SPEC and _PAY_SPEC.loader
sys.modules["Lootere.utils.payment_manager"] = payment_manager_mod
_PAY_SPEC.loader.exec_module(payment_manager_mod)
format_user_payment_instructions = payment_manager_mod.format_user_payment_instructions

from Script import script


class TestDesiFlirtyPersonalitySystem(unittest.TestCase):
    """Unit & regression tests for the Global Desi-Flirty Personality System (FR1-FR8)."""

    def setUp(self):
        personality_engine.set_enabled(True)

    def tearDown(self):
        personality_engine.set_enabled(True)

    def test_fr1_lifecycle_context_coverage(self):
        """FR1: Verify centralized template service covers all required lifecycle contexts."""
        required_contexts = [
            "start_welcome",
            "search_loading",
            "search_results_header",
            "search_no_results",
            "search_suggestions",
            "not_your_request_alert",
            "file_delivery_caption",
            "auto_delete_notice",
            "series_season_prompt",
            "series_episode_prompt",
            "imdb_header",
            "premium_hub_intro",
            "free_trial_granted",
            "payment_instructions",
            "payment_submitted_pending",
            "payment_approved_bot",
            "payment_approved_vip",
            "payment_rejected",
            "force_sub_prompt",
            "verify_step_1",
            "verify_step_2",
            "verify_step_3",
            "verify_complete_1",
            "verify_complete_2",
            "verify_complete_3",
            "referral_info",
            "stream_links_ready",
            "limit_reached_files",
            "limit_reached_buttons",
            "bot_authored_alert",
            "admin_action_status",
            "error_generic",
            "maintenance_notice",
            "callback_greeting",
            "vip_reminder_day_before",
            "vip_reminder_expiry_day",
            "vip_expired_notice",
        ]
        for ctx in required_contexts:
            self.assertIn(ctx, DESI_FLIRTY_TEMPLATES, f"Missing Desi-Flirty context: {ctx}")
            self.assertIn(ctx, NEUTRAL_FALLBACK_TEMPLATES, f"Missing neutral fallback for: {ctx}")
            text = get_desi_text(
                ctx,
                user_id=101,
                user="TestUser",
                bot_name="RKBot",
                bot_username="RKMoviesBot",
                query="Pushpa 2",
                file_name="Pushpa.2.1080p.mkv",
                minutes=10,
                title="Mirzapur",
                season="Season 3",
                prod_title="BOT PREMIUM",
                plan_name="1 Month",
                duration_days=30,
                amount="₹99",
                request_id="PAY-1234",
                expiry_str="30-12-2026 10:00 PM",
                reason="Invalid UTR",
                message="New movies added!",
                details="Database indexed.",
                error="Timeout",
            )
            self.assertTrue(len(text.strip()) > 0, f"Empty output for context: {ctx}")

    def test_fr2_fr3_repetition_avoidance(self):
        """FR2 & FR3: Consecutive calls for the same user and multi-variant context must not repeat."""
        engine = DesiFlirtyPersonalityEngine(enabled=True)
        multi_variant_contexts = [
            k for k, v in DESI_FLIRTY_TEMPLATES.items() if len(v) >= 2
        ]
        self.assertGreaterEqual(len(multi_variant_contexts), 15)

        for ctx in multi_variant_contexts:
            previous = None
            for _ in range(10):
                current = engine.get_text(
                    ctx,
                    user_id=999888,
                    user="Aarav",
                    query="Jawan",
                    file_name="Jawan.mkv",
                    minutes=5,
                    title="Sacred Games",
                    season="S01",
                    prod_title="BOT PREMIUM",
                    plan_name="Gold",
                    duration_days=30,
                    amount="₹99",
                    request_id="PAY-999",
                    message="Hello",
                    details="Done",
                    error="NetError",
                )
                if previous is not None:
                    self.assertNotEqual(
                        current,
                        previous,
                        f"Consecutive duplicate detected for context '{ctx}'",
                    )
                previous = current

    def test_fr4_neutral_fallback_mode(self):
        """FR4: Neutral fallback returns plain, direct wording when requested or engine disabled."""
        neutral_welcome = get_desi_text(
            "start_welcome",
            user_id=501,
            use_neutral_fallback=True,
            user="Riya",
            bot_name="RKMoviesBot",
        )
        self.assertIn("Welcome to RKMoviesBot", neutral_welcome)
        self.assertNotIn("ᴍᴀɪɴ ᴋᴀʙ sᴇ ᴀᴀᴘᴋᴀ ʜɪ ᴡᴀɪᴛ", neutral_welcome)

        # Also test disabling engine globally
        personality_engine.set_enabled(False)
        disabled_welcome = get_desi_text(
            "start_welcome",
            user_id=501,
            user="Riya",
            bot_name="RKMoviesBot",
        )
        self.assertEqual(neutral_welcome, disabled_welcome)

    def test_fr5_fr7_payment_and_verification_accuracy(self):
        """FR5 & FR7: Payment instructions, pending state, approval, and rejection remain explicit and accurate."""
        instr = format_user_payment_instructions("bot_premium", "Gold Plan", 30, "₹99", user_id=777)
        self.assertIn("MANUAL PAYMENT VERIFICATION", instr)
        self.assertIn("BOT PREMIUM", instr)
        self.assertIn("Gold Plan (30 Days)", instr)
        self.assertIn("₹99", instr)
        self.assertIn("rkmovieszip@ybl", instr)
        # Must not claim already approved
        self.assertNotIn("Payment Verified & Approved!", instr)

        pending_msg = get_desi_text(
            "payment_submitted_pending",
            user_id=777,
            request_id="PAY-ABCD12",
            plan_name="Gold Plan",
            duration_days=30,
        )
        self.assertIn("PENDING ADMIN VERIFICATION", pending_msg)
        self.assertIn("PAY-ABCD12", pending_msg)
        self.assertNotIn("Payment Verified & Approved", pending_msg)

        rej_msg = get_desi_text(
            "payment_rejected",
            user_id=777,
            request_id="PAY-ABCD12",
            reason="Invalid / Fake transaction screenshot",
        )
        self.assertIn("PAY-ABCD12", rej_msg)
        self.assertIn("Invalid / Fake transaction screenshot", rej_msg)
        self.assertIn("Not Approved", rej_msg)

        app_bot = get_desi_text(
            "payment_approved_bot",
            user_id=777,
            plan_name="Gold Plan",
            duration_days=30,
            expiry_str="31-12-2026 11:59 PM",
        )
        self.assertIn("Payment Verified & Approved!", app_bot)
        self.assertIn("Gold Plan", app_bot)
        self.assertIn("31-12-2026 11:59 PM", app_bot)

    def test_fr6_admin_broadcast_preservation(self):
        """FR6: Admin-authored broadcast messages are never rewritten."""
        raw_admin_broadcast = "Urgent server maintenance tonight at 11 PM IST. Do not panic."
        self.assertEqual(
            personality_engine.preserve_admin_broadcast(raw_admin_broadcast),
            raw_admin_broadcast,
        )
        # Verify plugins/broadcast.py does not inject personality rewriting
        broadcast_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "plugins", "broadcast.py"))
        with open(broadcast_path, "r", encoding="utf-8") as f:
            broadcast_code = f.read()
        self.assertNotIn("get_desi_text", broadcast_code)

    def test_fr8_diagnostic_logs_remain_factual(self):
        """FR8: Diagnostic log templates in Script.py remain factual without flirt words."""
        log_templates = [
            script.LOG_TEXT_G,
            script.LOG_TEXT_P,
            script.VERIFIED_LOG_TEXT,
            script.NORSLTS,
        ]
        flirty_markers = ["😉", "😘", "🥰", "ᴄᴜᴛɪᴇ", "ʜᴀʏᴇ", "sʜᴀʀᴍᴀᴏ"]
        for log_tpl in log_templates:
            for marker in flirty_markers:
                self.assertNotIn(marker, log_tpl, f"Flirty marker '{marker}' found in diagnostic log template!")

    def test_script_placeholder_compatibility(self):
        """Verify all updated Script.py constants preserve exact positional {} placeholders."""
        self.assertIn("User", script.START_TXT.format("User", "BotUsername", "BotName"))
        self.assertIn("BotUsername", script.REFFER_TXT.format("BotUsername", 12345))
        self.assertIn("User", script.VERIFICATION_TEXT.format("User", "2026-01-01", "10:00:00"))
        self.assertIn("User", script.SECOND_VERIFICATION_TEXT.format("User", "2026-01-01", "10:00:00"))
        self.assertIn("User", script.THIRDT_VERIFICATION_TEXT.format("User", "2026-01-01", "10:00:00"))
        self.assertIn("User", script.VERIFY_COMPLETE_TEXT.format("User"))
        self.assertIn("User", script.SECOND_COMPLETE_TEXT.format("User"))
        self.assertIn("User", script.THIRDT_COMPLETE_TEXT.format("User"))
        self.assertIn("User", script.ALRT_TXT.format("User"))
        self.assertIn("Pushpa", script.CUDNT_FND.format("Pushpa"))
        self.assertIn("User", script.FREE_TXT.format("User"))
        self.assertIn("Avatar", script.NOT_AVAILABLE_TXT.format("Avatar"))
        self.assertIn("Dark", script.SERIES_FORMAT_TXT.format("Dark"))
        self.assertIn("Leo", script.UPLOADED_TXT.format("Leo"))
        self.assertIn("GTA6", script.NOT_RELEASE_TXT.format("GTA6"))
        self.assertIn("Incepton", script.SPELL_TXT.format("Incepton"))


if __name__ == "__main__":
    unittest.main()
