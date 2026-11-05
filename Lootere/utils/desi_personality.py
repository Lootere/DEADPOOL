# Global Desi-Flirty Personality System
# RKMOVIESZIP — Centralized Template & Wording Engine (Layer Only)
# Preserves all business logic, commands, callbacks, database operations, and Features 1-36.
import random
from collections import deque
from typing import Dict, List, Optional, Any


# Context-specific Desi Hinglish + Cute Flirty templates (2-4 natural variations per context)
DESI_FLIRTY_TEMPLATES: Dict[str, List[str]] = {
    "start_welcome": [
        (
            "<b><i>ʜᴇʏ {user} 😉✨</i></b>\n"
            "<b><blockquote>ᴀᴀ ɢᴀʏᴇ ᴀᴀᴘ? ᴍᴀɪɴ ᴋᴀʙ sᴇ ᴀᴀᴘᴋᴀ ʜɪ ᴡᴀɪᴛ ᴋᴀʀ ʀᴀʜɪ ᴛʜɪ! 🥰\n"
            "ʙᴀs ᴀᴘɴɪ ғᴀᴠᴏʀɪᴛᴇ ᴍᴏᴠɪᴇ ʏᴀ sᴇʀɪᴇs ᴋᴀ ɴᴀᴀᴍ ʙᴀᴛᴀᴏ, ᴘᴀʟᴀᴋ ᴊʜᴀᴘᴀᴋᴛᴇ ʜɪ ʜᴀज़ɪʀ ᴋᴀʀ ᴅᴜɴɢɪ! 🎬💫</blockquote></b>\n\n"
            "<b><spoiler>🔋 ᴍᴀɪɴᴛᴀɪɴᴇᴅ ʙʏ - <a href=https://t.me/Looterekrish>Lₒₒ𝚝ₑᵣₑ™</a></spoiler></b>"
        ),
        (
            "<b><i>ʜᴇʟʟᴏ ᴊɪ {user} 😍🌸</i></b>\n"
            "<b><blockquote>ᴀᴀᴘᴋᴇ ᴀᴀɴᴇ sᴇ ʏᴇʜ ᴄʜᴀᴛ ᴀᴜʀ ʙʜɪ ᴄᴜᴛᴇ ʜᴏ ɢᴀʏɪ! ✨\n"
            "ᴀᴀᴊ ᴋᴀᴜɴsɪ ᴍᴏᴠɪᴇ ʏᴀ sᴇʀɪᴇs ᴅᴇᴋʜɴᴇ ᴋᴀ ᴍᴏᴏᴅ ʜᴀɪ? ɴᴀᴀᴍ ʟɪᴋʜᴏ ᴀᴜʀ ᴍᴇʀᴀ ᴊᴀᴀᴅᴜ ᴅᴇᴋʜᴏ! 🍿💖</blockquote></b>\n\n"
            "<b><spoiler>🔋 ᴍᴀɪɴᴛᴀɪɴᴇᴅ ʙʏ - <a href=https://t.me/Looterekrish>Lₒₒ𝚝ₑᵣₑ™</a></spoiler></b>"
        ),
        (
            "<b><i>ʜᴀʏᴇ {user}, ᴡᴇʟᴄᴏᴍᴇ! 😘💫</i></b>\n"
            "<b><blockquote>ᴍᴏᴠɪᴇs ᴋɪ ᴅᴜɴɪʏᴀ ᴍᴇɪɴ ᴀᴀᴘᴋᴀ sᴡᴀɢᴀᴛ ʜᴀɪ! 🎬\n"
            "ᴋᴏɪ ʙʜɪ ᴍᴏᴠɪᴇ ʏᴀ ᴡᴇʙ sᴇʀɪᴇs ᴄʜᴀʜɪʏᴇ ᴛᴏʜ sʜᴀʀᴍᴀᴏ ᴍᴀᴛ, sᴇᴇᴅʜᴀ ɴᴀᴀᴍ ʙʜᴇᴊᴏ! 🥰🔥</blockquote></b>\n\n"
            "<b><spoiler>🔋 ᴍᴀɪɴᴛᴀɪɴᴇᴅ ʙʏ - <a href=https://t.me/Looterekrish>Lₒₒ𝚝ₑᵣₑ™</a></spoiler></b>"
        ),
    ],
    "search_loading": [
        "ʀᴜᴋᴏ ज़ʀᴀ, ᴀᴀᴘᴋᴇ ʟɪʏᴇ  बेस्ट ᴘʀɪɴᴛ ᴅʜᴜɴᴅ ʀᴀʜɪ ʜᴜɴ... 🔍✨",
        "ʙᴀs ᴅᴏ ᴘᴀʟ ɪɴᴛᴇज़ᴀʀ ᴋᴀʀᴏ, ᴀᴀᴘकी ᴍᴏᴠɪᴇ ʟᴀᴀ ʀᴀʜɪ ʜᴜɴ... 😉🎬",
        "sᴇᴀʀᴄʜɪɴɢ... ᴀᴀᴘकी ᴘᴀsᴀɴᴅ ᴋᴀ ᴋʜᴀज़ᴀɴᴀ ɴɪᴋᴀʟ ʀᴀʜɪ ʜᴜɴ! 🔍💫",
    ],
    "search_results_header": [
        "<b>ʟᴏ ᴊɪ {user}, ᴀᴀᴘɴᴇ ᴍᴀᴀɴɢᴀ ᴀᴜʀ ᴍᴀɪɴ ʟᴇ ᴀᴀʏɪ! 😉✨\nनीचे से अपनी पसंदीदा क्वालिटी चुन लो:</b>",
        "<b>ᴀᴀᴘकी ғᴀʀᴍᴀɪsʜ ᴘᴜʀɪ ʜᴜɪ {user}! 🥰🍿\nअपनी फाइल पर टैप करो और एन्जॉय करो:</b>",
        "<b>ᴅᴇᴋʜᴏ {user}, ᴋɪᴛɴɪ ᴊᴀʟᴅɪ ᴅʜᴜɴᴅ ʟɪʏᴀ ɴᴀ? 😘🎬\nचलो अब जल्दी से अपना प्रिंट सेलेक्ट कर लो:</b>",
    ],
    "search_no_results": [
        (
            "<i>ᴀʀᴇʏ ʏᴀᴀʀ, <code>{query}</code> ɴᴀᴀᴍ sᴇ ᴋᴜᴄʜ ᴍɪʟᴀ ɴᴀʜɪ 😕\n\n"
            "ᴛʜᴏᴅᴀ sᴘᴇʟʟɪɴɢ ᴄʜᴇᴄᴋ ᴋᴀʀᴋᴇ ᴅᴏʙᴀʀᴀ ᴛʀʏ ᴋᴀʀᴏ ɴᴀ? 😉\n"
            "Example: <code>Pushpa 2021</code> ʏᴀ <code>Money Heist S01E01</code></i>"
        ),
        (
            "<i>ᴏᴏᴘs! <code>{query}</code> ᴀʙʜɪ ᴍᴇʀɪ ʟɪsᴛ ᴍᴇɪɴ ɴᴀʜɪ ᴅɪᴋʜ ʀᴀʜᴀ 🥺\n\n"
            "ɢᴏᴏɢʟᴇ sᴇ sᴀʜɪ sᴘᴇʟʟɪɴɢ ᴅᴇᴋʜ ᴋᴀʀ sɪʀғ ɴᴀᴀᴍ ᴀᴜʀ sᴀᴀʟ (year) ʟɪᴋʜᴏ, ᴍᴀɪɴ ᴛᴜʀᴀɴᴛ ᴅʜᴜɴᴅ ᴅᴜɴɢɪ! ✨</i>"
        ),
        (
            "<i>ʜᴀʏᴇ, <code>{query}</code> ᴛᴏʜ ɴᴀʜɪ ᴍɪʟ ᴘᴀʏɪ 🙈\n\n"
            "ᴇᴋ ʙᴀᴀʀ sᴘᴇʟʟɪɴɢ ᴄʜᴇᴄᴋ ᴋᴀʀ ʟᴏ ʏᴀ ʙɪɴᴀ ᴇxᴛʀᴀ ᴡᴏʀᴅs ᴋᴇ sɪʀғ ᴛɪᴛʟᴇ ʟɪᴋʜ ᴋᴇ ʙʜᴇᴊᴏ! 💫</i>"
        ),
    ],
    "search_suggestions": [
        "<i><code>{query}</code> ᴛᴏʜ ᴇxᴀᴄᴛ ɴᴀʜɪ ᴍɪʟᴀ, ᴘᴀʀ ᴋʏᴀ ᴀᴀᴘ ɪɴᴍᴇ sᴇ ᴋᴜᴄʜ ᴅʜᴜɴᴅ ʀᴀʜᴇ ᴛʜᴇ? 😉👇</i>",
        "<i>ᴀʀᴇʏ, sʜᴀʏᴀᴅ sᴘᴇʟʟɪɴɢ ᴛʜᴏᴅɪ ɪᴅʜᴀʀ-ᴜᴅʜᴀʀ ʜᴏ ɢᴀʏɪ! 🤭\nᴅᴇᴋʜᴏ ᴋʏᴀ ʏᴇʜ ᴡᴀʟɪ ᴍᴏᴠɪᴇ ᴄʜᴀʜɪʏᴇ ᴛʜɪ? 👇</i>",
    ],
    "not_your_request_alert": [
        "ᴀʀᴇʏ {user}, ʏᴇʜ ᴋɪsɪ ᴀᴜʀ ᴋɪ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇsᴛ ʜᴀɪ! 😉 ᴀᴘɴɪ ᴍᴏᴠɪᴇ ᴋᴀ ɴᴀᴀᴍ ᴀʟᴀɢ sᴇ ʟɪᴋʜᴏ, ᴀᴀᴘᴋᴏ ʙʜɪ ᴅᴇ ᴅᴜɴɢɪ!",
        "ᴄʜोरी-ᴄʜोरी ᴅᴜsʀᴏ ᴋᴇ ʙᴜᴛᴛᴏɴ ᴍᴀᴛ ᴅᴀʙᴀᴏ {user}! 🤭 ᴀᴘɴᴀ ɴᴀᴀᴍ ᴛʏᴘᴇ ᴋᴀʀᴏ, ᴀᴀᴘके ʟɪʏᴇ ᴀʟᴀɢ sᴇ ʟᴀᴀ ᴅᴜɴɢɪ!",
    ],
    "file_delivery_caption": [
        "<b>📂 Fɪʟᴇ : <code>{file_name}</code>\n\n✨ ᴀᴀᴘकी ғɪʟᴇ ʀᴇᴀᴅʏ ʜᴀɪ! 🍿 Pᴏᴡᴇʀᴇᴅ Bʏ @Rkmovieszip</b>",
        "<b>📂 Fɪʟᴇ : <code>{file_name}</code>\n\n💖 ᴇɴᴊᴏʏ ʏᴏᴜʀ sʜᴏᴡ! Pᴏᴡᴇʀᴇᴅ Bʏ @Rkmovieszip</b>",
    ],
    "auto_delete_notice": [
        "<b>⚠️ ध्यान दें: कॉपीराइट की वजह से यह फाइल <u>{minutes} मिनट</u> में अपने आप डिलीट हो जाएगी! 😉\nजल्दी से अपने Saved Messages में फॉरवर्ड कर लो ताकि बाद में आराम से देख सको! 💖</b>",
        "<b>⏳ सुनो जी! यह मैसेज <u>{minutes} मिनट</u> के बाद गायब हो जाएगा!\nइसे अभी कहीं फॉरवर्ड करके सेव कर लो, वरना फिर मुझे याद करोगे! 🥰✨</b>",
    ],
    "series_season_prompt": [
        "<b>🎬 {title}</b>\n\n<i>कौना सा सीज़न (Season) देखना है आपको? नीचे से चुन लो 😉👇</i>",
        "<b>📺 {title}</b>\n\n<i>सीरीज़ का मूड है आज? अपना पसंदीदा सीज़न सेलेक्ट करो 🥰👇</i>",
    ],
    "series_episode_prompt": [
        "<b>🎬 {title} — {season}</b>\n\n<i>अब अपना एपिसोड भी चुन लो, पूरा इंतज़ाम कर रखा है आपके लिए! 😘👇</i>",
        "<b>📺 {title} ({season})</b>\n\n<i>लो जी, सारे एपिसोड्स हाज़िर हैं! जिसपर दिल आए टैप करो ✨👇</i>",
    ],
    "imdb_header": [
        "<b>🌟 ʟᴏ ᴊɪ, ɪᴍᴅʙ ᴋɪ ᴘᴜʀɪ ᴋᴜɴᴅʟɪ ɴɪᴋᴀʟ ʟᴀᴀʏɪ ʜᴜɴ! 😉✨</b>",
        "<b>🎬 ᴀᴀᴘकी ᴍᴏᴠɪᴇ ᴋɪ sᴀᴀʀɪ ᴅᴇᴛᴀɪʟs ʏᴀʜᴀɴ ʜᴀɪɴ: 🥰👇</b>",
    ],
    "premium_hub_intro": [
        (
            "<b>★ PREMIUM HUB ★</b>\n\n"
            "<i>ᴀᴀᴘके ʟɪʏᴇ sᴘᴇᴄɪᴀʟ ᴠɪᴘ ᴛʀᴇᴀᴛᴍᴇɴᴛ ᴋᴀ ɪɴᴛᴇज़ᴀᴍ ʜᴀɪ ʏᴀʜᴀɴ! 😉✨</i>\n\n"
            "• <b>BOT PREMIUM:</b> Unlimited instant searches, direct files (no verification links), and fast streaming.\n"
            "• <b>VIP DESTINATIONS:</b> Direct entry to our private Telegram VIP movie & series channels & groups.\n"
            "• <b>FREE TRIAL & REFERRALS:</b> Invite friends to earn free bot access.\n"
            "• <b>MY ACTIVE PLANS:</b> Check your active memberships, exact expiry dates & private invite links.\n\n"
            "<i>नीचे से अपना ऑप्शन चुनो और VIP बन जाओ: 👇</i>"
        ),
        (
            "<b>★ PREMIUM HUB ★</b>\n\n"
            "<i>बिना किसी रुकावट के मूवीज़ का मज़ा लेना चाहते हो? तो आप बिल्कुल सही जगह आए हो! 🥰💎</i>\n\n"
            "• <b>BOT PREMIUM:</b> Unlimited instant searches, direct files (no verification links), and fast streaming.\n"
            "• <b>VIP DESTINATIONS:</b> Direct entry to our private Telegram VIP movie & series channels & groups.\n"
            "• <b>FREE TRIAL & REFERRALS:</b> Invite friends to earn free bot access.\n"
            "• <b>MY ACTIVE PLANS:</b> Check your active memberships, exact expiry dates & private invite links.\n\n"
            "<i>अपना पसंदीदा प्लान देखने के लिए नीचे क्लिक करें: 👇</i>"
        ),
    ],
    "free_trial_granted": [
        (
            "<b>👋 ʜᴇʏ {user},  बधाई हो! 🥳✨\n\n"
            "आपको <u>5 मिनट</u> का <b>Free Bot Premium Trial</b> मिल गया है! 🥰\n"
            "बिना किसी वेरिफिकेशन के अभी अपनी मूवी सर्च करो और स्पीड देखो! (/myplan से स्टेटस चेक करें)</b>"
        ),
        (
            "<b>🎉 ᴡᴏᴏʜᴏᴏ {user}! आपका <u>5 मिनट</u> का <b>Free Trial</b> एक्टिव हो गया है! 😘💫\n\n"
            "चलो जल्दी से अपनी पसंदीदा मूवी मंगा लो, अभी कोई लिंक ओपन नहीं करना पड़ेगा! (/myplan)</b>"
        ),
    ],
    "payment_instructions": [
        (
            "<b>MANUAL PAYMENT VERIFICATION</b>\n\n"
            "• <b>Selected Product:</b> {prod_title}\n"
            "• <b>Plan:</b> {plan_name} ({duration_days} Days)\n"
            "• <b>Payable Amount:</b> <code>{amount}</code>\n"
            "• <b>UPI ID:</b> <code>rkmovieszip@ybl</code>\n\n"
            "<b>Instructions:</b>\n"
            "1. Pay the exact amount <code>{amount}</code> using any UPI app (GPay, PhonePe, Paytm, etc.).\n"
            "2. Take a clear screenshot showing the transaction UTR / Reference number.\n"
            "3. <b>Send or forward the screenshot right here in this chat! 😉📸</b>\n\n"
            "<i>Note: Your plan will be activated after admin verification. Send /cancel to abort.</i>"
        ),
        (
            "<b>MANUAL PAYMENT VERIFICATION</b>\n\n"
            "• <b>Selected Product:</b> {prod_title}\n"
            "• <b>Plan:</b> {plan_name} ({duration_days} Days)\n"
            "• <b>Payable Amount:</b> <code>{amount}</code>\n"
            "• <b>UPI ID:</b> <code>rkmovieszip@ybl</code>\n\n"
            "<b>Instructions:</b>\n"
            "1. Complete the payment of <code>{amount}</code> to the UPI ID above.\n"
            "2. Capture a clear screenshot with the UTR / Transaction ID visible.\n"
            "3. <b>Upload the payment screenshot directly in this chat! 🥰✨</b>\n\n"
            "<i>Note: Entitlements are activated only after admin approval. Send /cancel to abort.</i>"
        ),
    ],
    "payment_submitted_pending": [
        (
            "<b>Payment Proof Received! 📸✨</b>\n\n"
            "• <b>Request ID:</b> <code>{request_id}</code>\n"
            "• <b>Plan:</b> {plan_name} ({duration_days} Days)\n"
            "• <b>Status:</b> <code>PENDING ADMIN VERIFICATION</code>\n\n"
            "आपका स्क्रीनशॉट एडमिन के पास भेज दिया गया है! 😉 जैसे ही पेमेंट वेरीफाई और अप्रूव होता है, मैं तुरंत आपको बता दूंगी! 💖"
        ),
        (
            "<b>Screenshot मिल गया जी! 🥰✨</b>\n\n"
            "• <b>Request ID:</b> <code>{request_id}</code>\n"
            "• <b>Plan:</b> {plan_name} ({duration_days} Days)\n"
            "• <b>Status:</b> <code>PENDING ADMIN VERIFICATION</code>\n\n"
            "बस थोड़ा सा इंतज़ार करो, एडमिन के अप्रूव करते ही आपका प्लान एक्टिव हो जाएगा! 🌸"
        ),
    ],
    "payment_approved_bot": [
        (
            "<b>Payment Verified & Approved! 🎉💖</b>\n\n"
            "आपका <b>Bot Premium</b> सफलतापूर्वक एक्टिवेट कर दिया गया है! 🥰\n"
            "• <b>Plan:</b> {plan_name}\n"
            "• <b>Duration:</b> {duration_days} Days\n"
            "• <b>Expiry Date:</b> {expiry_str} (IST)\n\n"
            "अब बिना किसी रुकावट के अनलिमिटेड मूवीज़ डाउनलोड और स्ट्रीम करो! 😉🍿\n"
            "Check status anytime via /myplan"
        ),
    ],
    "payment_approved_vip": [
        (
            "<b>Payment Verified & Approved! 🎉💎</b>\n\n"
            "आपकी <b>Community VIP</b> मेंबरशिप एक्टिवेट हो गई है! 🥰✨\n"
            "• <b>Plan:</b> {plan_name}\n"
            "• <b>Duration:</b> {duration_days} Days\n"
            "• <b>Expiry:</b> {expiry_str} (IST)\n\n"
            "नीचे दिए गए आपके पर्सनल (single-use) बटन्स पर टैप करके प्राइवेट VIP चैनल्स और ग्रुप ज्वाइन कर लो: 👇"
        ),
    ],
    "payment_rejected": [
        (
            "<b>Payment Verification Update ⚠️</b>\n\n"
            "आपकी पेमेंट रिक्वेस्ट (<code>{request_id}</code>) अप्रूव नहीं हो सकी (Not Approved).\n"
            "• <b>Reason:</b> {reason}\n\n"
            "कोई भी प्लान एक्टिवेट नहीं किया गया है। अगर आपने सही पेमेंट की थी, तो कृपया साफ UTR नंबर वाले स्क्रीनशॉट के साथ दोबारा ट्राई करें या एडमिन से संपर्क करें।"
        ),
    ],
    "force_sub_prompt": [
        (
            "<i><b>अरे रुको जी! 😉 मूवी लेने से पहले हमारा अपडेट चैनल तो ज्वाइन कर लो! 🥰\n\n"
            "नीचे <b>Join Now</b> बटन पर क्लिक करके ज्वाइन करो और फिर <b>Try Again</b> दबाओ, फाइल तुरंत मिल जाएगी! 👇✨</b></i>"
        ),
        (
            "<i><b>इतनी भी क्या जल्दी है? 🤭 पहले हमारे चैनल से जुड़ जाओ ताकि हम हमेशा साथ रहें! 💖\n\n"
            "नीचे बटन से चैनल ज्वाइन करो और तुरंत अपनी मूवी ले लो 👇</b></i>"
        ),
    ],
    "verify_step_1": [
        (
            "<b>ʜᴇʏ {user} 😉✨\n\n"
            "<u>आज का पहला वेरिफिकेशन (Verification 1/3) बाकी है! नीचे Verify लिंक पर टैप करके इसे पूरा कर लो ताकि अनलिमिटेड मूवीज़ मिलती रहें 🥰</u>\n\n"
            "#ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ:- 1/3\n\n"
            "अगर बिना किसी लिंक और वेरिफिकेशन के डायरेक्ट फाइल्स चाहिए, तो हमारा प्रीमियम ले लो! 💎\n"
            "💶 sᴇɴᴅ /plans ᴛᴏ ʙᴜʏ sᴜʙsᴄʀɪᴘᴛɪᴏɴ</b>"
        ),
    ],
    "verify_step_2": [
        (
            "<b>ʜᴇʏ {user} 😊💫\n\n"
            "<u>आपका दूसरा वेरिफिकेशन (Verification 2/3) पेंडिंग है! बस एक छोटा सा क्लिक करो और फिर आराम से मूवीज़ एन्जॉय करो 🍿</u>\n\n"
            "#ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ:- 2/3\n\n"
            "डायरेक्ट फाइल्स के लिए कभी भी /plans चेक कर सकते हो! 💖</b>"
        ),
    ],
    "verify_step_3": [
        (
            "<b>ʜᴇʏ {user} 🥰🌸\n\n"
            "📌 <u>बस आज का आखिरी वेरिफिकेशन (Verification 3/3)! इसे पूरा करते ही पूरे दिन के लिए फ्री एक्सेस मिल जाएगा! ✨</u>\n\n"
            "#ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ:- 3/3\n\n"
            "बिना वेरिफिकेशन के डायरेक्ट फाइल्स के लिए /plans देखें।</b>"
        ),
    ],
    "verify_complete_1": [
        (
            "<b>क्या बात है {user}! 😉✅\n\n"
            "आपने <b>1st Verification</b> पूरा कर लिया है! अब अगले वेरिफिकेशन तक अनलिमिटेड मूवीज़ का मज़ा लो! 🍿✨\n\n"
            "डायरेक्ट फाइल्स के लिए /plans चेक करें।</b>"
        ),
    ],
    "verify_complete_2": [
        (
            "<b>सुपर {user}! 🥰✅\n\n"
            "आपका <b>2nd Verification</b> भी पूरा हो गया! चलो अब आराम से अपनी मूवी देखो! 🎬💖\n\n"
            "बिना लिंक ओपन किए डायरेक्ट फाइल्स के लिए /plans देखें।</b>"
        ),
    ],
    "verify_complete_3": [
        (
            "<b>बधाई हो {user}! 😘🎉\n\n"
            "आपने आज का <b>3rd Verification</b> पूरा कर लिया है ✅\n"
            "अब पूरे दिन बेफिक्र होकर जितनी चाहो मूवीज़ मंगाओ! 🍿🔥</b>"
        ),
    ],
    "referral_info": [
        (
            "<b>अपने दोस्तों को बुलाओ और मुफ्त में प्रीमियम पाओ! 😉🎁\n\n"
            "• हर सफल रेफरल पर: <code>10 Points</code>\n"
            "• <code>50 Points</code> होते ही: <b>1 Month Free Bot Premium!</b> 🥰\n\n"
            "🔗 <b>आपका रेफरल लिंक:</b>\nhttps://telegram.me/{bot_username}?start=reff_{user_id}\n"
            "============================\n"
            "<u>💫 ᴘʀᴇᴍɪᴜᴍ ғᴇᴀᴛᴜʀᴇs 💫</u> :\n"
            "○ Direct Files without Verification Links\n"
            "○ Unlimited Daily Downloads & Send All\n"
            "○ PM Search & Fast Streaming\n"
            "____________________________\n"
            "डायरेक्ट प्लान लेने के लिए - /plans</b>"
        ),
    ],
    "stream_links_ready": [
        "<b>🎬 आपकी फाइल स्ट्रीमिंग और फास्ट डाउनलोड के लिए तैयार है! 😉🍿\nनीचे बटन पर टैप करके ऑनलाइन देखो या डाउनलोड कर लो: 👇</b>",
        "<b>✨ लो जी, ऑनलाइन वॉच और डाउनलोड लिंक रेडी कर दिया है आपके लिए! 🥰👇</b>",
    ],
    "limit_reached_files": [
        (
            "📁 <b>आज की फ्री फाइल लिमिट पूरी हो गई है जी! 🥺</b>\n\n"
            "अगर बिना किसी डेली लिमिट के अनलिमिटेड मूवीज़ चाहिए, तो हमारा प्रीमियम प्लान ले लो! 😉💎\n\n"
            "💲 <b>See Plans:</b> /plans\n"
            "⌚ <b>Daily Reset Time:</b> 12:00 AM IST"
        ),
    ],
    "limit_reached_buttons": [
        (
            "📦 <b>आज की 'Send All' बटन लिमिट पूरी हो गई है! 🙈</b>\n\n"
            "अनलिमिटेड बार 'Send All' इस्तेमाल करने के लिए प्रीमियम मेंबर बन जाओ! 🥰✨\n\n"
            "💲 <b>See Plans:</b> /plans\n"
            "⌚ <b>Daily Reset Time:</b> 12:00 AM IST"
        ),
    ],
    "bot_authored_alert": [
        "<b>🔔 ᴀᴀᴘके ʟɪʏᴇ ᴇᴋ ɴᴀʏᴀ ᴜᴘᴅᴀᴛᴇ ʜᴀɪ जी! 😉✨</b>\n\n{message}",
        "<b>💌 sᴜɴᴏ ᴊɪ, ᴀᴀᴘके ᴋᴀᴀᴍ ᴋɪ ᴋʜᴀʙᴀʀ ʟᴀᴀʏɪ ʜᴜɴ! 🥰👇</b>\n\n{message}",
    ],
    "admin_action_status": [
        "<b>✅ ʜᴏ ɢᴀʏᴀ ʙᴏss! 😉</b>\n\n{details}",
        "<b>✨ ᴀᴀᴘका ʜᴜᴋᴜᴍ sᴀʀ ᴀᴀɴᴋʜᴏɴ ᴘᴀʀ! काम पूरा हो गया:</b>\n\n{details}",
    ],
    "error_generic": [
        "<b>अरे यार, कुछ टेक्निकल गड़बड़ हो गई है 🥺\nथोड़ी देर में दोबारा ट्राई करो ना? ({error})</b>",
        "<b>उफ़! अभी सर्वर थोड़ा नखरे कर रहा है 🙈\nकृपया कुछ सेकंड बाद फिर से कोशिश करें! ({error})</b>",
    ],
    "maintenance_notice": [
        "<b>🛠️ अभी मैं थोड़ा तैयार हो रही हूँ (Maintenance Mode)! 😉✨\nबस कुछ ही देर में और भी तेज़ होकर वापस आऊंगी, थोड़ा इंतज़ार करना! 💖</b>",
    ],
    "callback_greeting": [
        "आपका हुकुम सर आँखों पर! 😉✨",
        "हाज़िर हूँ जी! 🥰🌸",
        "बस आपके ही क्लिक का इंतज़ार था! 😘💫",
        "चलो कुछ बढ़िया देखते हैं! 🍿✨",
    ],
    "vip_reminder_day_before": [
        (
            "<b>VIP Membership Reminder 💌</b>\n\n"
            "सुनो जी! आपकी Telegram VIP मेंबरशिप <b>कल एक्सपायर (Expire)</b> होने वाली है 🥺\n"
            "हमारा साथ बना रहे, इसके लिए समय पर रिन्यू (Renew) करवा लेना! 😉💖"
        ),
    ],
    "vip_reminder_expiry_day": [
        (
            "<b>VIP Membership Expiry Alert ⏳</b>\n\n"
            "ध्यान दें! आपकी VIP मेंबरशिप <b>आज समाप्त (Expire)</b> हो रही है!\n"
            "अगर रिन्यू नहीं हुआ तो प्राइवेट चैनल्स से एक्सेस अपने आप हट जाएगा। अभी रिन्यू करने के लिए Premium Hub चेक करें! 🙏✨"
        ),
    ],
    "vip_expired_notice": [
        (
            "<b>VIP Membership Expired 💔</b>\n\n"
            "आपकी VIP मेंबरशिप की अवधि समाप्त हो गई है और प्राइवेट चैनल्स से एक्सेस हटा दिया गया है।\n"
            "वापस जुड़ने के लिए कभी भी नया प्लान ले सकते हैं—मैं आपका इंतज़ार करूँगी! 🥰✨"
        ),
    ],
}


# Neutral, clear fallbacks if personality is disabled or an unknown/critical fallback is requested
NEUTRAL_FALLBACK_TEMPLATES: Dict[str, str] = {
    "start_welcome": (
        "<b>Hello {user},</b>\n"
        "<b><blockquote>Welcome to {bot_name}. Send any movie or series title to search our catalog.</blockquote></b>\n\n"
        "<b>Maintained by <a href=https://t.me/Looterekrish>Lₒₒ𝚝ₑᵣₑ™</a></b>"
    ),
    "search_loading": "Searching for your request...",
    "search_results_header": "<b>Search results for {user}:</b>",
    "search_no_results": "<i>No files were found for <code>{query}</code>. Please check the spelling and try again.</i>",
    "search_suggestions": "<i>Could not find exact match for <code>{query}</code>. Did you mean one of these?</i>",
    "not_your_request_alert": "{user}, this is not your movie request. Please send your own search query.",
    "file_delivery_caption": "<b>File Name: <code>{file_name}</code>\nPowered By @Rkmovieszip</b>",
    "auto_delete_notice": "<b>Note: This message will be automatically deleted in {minutes} minutes due to copyright. Please forward it to Saved Messages.</b>",
    "series_season_prompt": "<b>{title}</b>\n\nSelect a season below:",
    "series_episode_prompt": "<b>{title} — {season}</b>\n\nSelect an episode below:",
    "imdb_header": "<b>IMDb Information:</b>",
    "premium_hub_intro": (
        "<b>★ PREMIUM HUB ★</b>\n\n"
        "• <b>BOT PREMIUM:</b> Unlimited searches, direct files, and fast streaming.\n"
        "• <b>VIP DESTINATIONS:</b> Access to private Telegram VIP movie & series channels.\n"
        "• <b>FREE TRIAL & REFERRALS:</b> Invite friends to earn free bot access.\n"
        "• <b>MY ACTIVE PLANS:</b> View active subscriptions, expiry dates & invite links."
    ),
    "free_trial_granted": "<b>Hello {user}, your 5-minute free Bot Premium trial is now active. Check /myplan for status.</b>",
    "payment_instructions": (
        "<b>MANUAL PAYMENT VERIFICATION</b>\n\n"
        "• <b>Selected Product:</b> {prod_title}\n"
        "• <b>Plan:</b> {plan_name} ({duration_days} Days)\n"
        "• <b>Payable Amount:</b> <code>{amount}</code>\n"
        "• <b>UPI ID:</b> <code>rkmovieszip@ybl</code>\n\n"
        "Pay the exact amount and upload the transaction screenshot showing the UTR number in this chat."
    ),
    "payment_submitted_pending": (
        "<b>Payment Proof Received</b>\n\n"
        "• <b>Request ID:</b> <code>{request_id}</code>\n"
        "• <b>Plan:</b> {plan_name} ({duration_days} Days)\n"
        "• <b>Status:</b> <code>PENDING ADMIN VERIFICATION</code>"
    ),
    "payment_approved_bot": (
        "<b>Payment Verified & Approved</b>\n\n"
        "Your Bot Premium plan ({plan_name}, {duration_days} Days) is now active until {expiry_str} (IST)."
    ),
    "payment_approved_vip": (
        "<b>Payment Verified & Approved</b>\n\n"
        "Your Community VIP plan ({plan_name}, {duration_days} Days) is now active until {expiry_str} (IST)."
    ),
    "payment_rejected": (
        "<b>Payment Verification Update</b>\n\n"
        "Your payment request (<code>{request_id}</code>) was not approved.\n"
        "• <b>Reason:</b> {reason}"
    ),
    "force_sub_prompt": "<i>Please join our updates channel first to access this file, then tap Try Again.</i>",
    "verify_step_1": "<b>Hello {user}, please complete Verification 1/3 to continue accessing files. Send /plans for direct access.</b>",
    "verify_step_2": "<b>Hello {user}, please complete Verification 2/3 to continue accessing files. Send /plans for direct access.</b>",
    "verify_step_3": "<b>Hello {user}, please complete Verification 3/3 for full-day access. Send /plans for direct access.</b>",
    "verify_complete_1": "<b>Hello {user}, Verification 1/3 is complete.</b>",
    "verify_complete_2": "<b>Hello {user}, Verification 2/3 is complete.</b>",
    "verify_complete_3": "<b>Hello {user}, Verification 3/3 is complete.</b>",
    "referral_info": (
        "<b>Refer friends to earn 10 points per referral. Collect 50 points for 1 Month Bot Premium.\n"
        "Referral Link: https://telegram.me/{bot_username}?start=reff_{user_id}</b>"
    ),
    "stream_links_ready": "<b>Your streaming and download links are ready below:</b>",
    "limit_reached_files": "📁 Your daily free file limit has been reached. Check /plans for unlimited access. Resets at 12:00 AM IST.",
    "limit_reached_buttons": "Send All button daily limit reached. Check /plans for unlimited access. Resets at 12:00 AM IST.",
    "bot_authored_alert": "<b>Notification:</b>\n\n{message}",
    "admin_action_status": "<b>Action Completed:</b>\n\n{details}",
    "error_generic": "<b>An error occurred: {error}. Please try again later.</b>",
    "maintenance_notice": "<b>The bot is currently under maintenance. Please try again shortly.</b>",
    "callback_greeting": "Welcome!",
    "vip_reminder_day_before": "<b>VIP Membership Reminder:</b> Your VIP membership expires tomorrow. Please contact admin to renew.",
    "vip_reminder_expiry_day": "<b>VIP Membership Expiry Alert:</b> Your VIP membership expires today. Access will be revoked if not renewed.",
    "vip_expired_notice": "<b>VIP Membership Expired:</b> Your VIP access has expired. Contact admin to renew.",
}


class SafeFormatDict(dict):
    """Prevents KeyError if a template placeholder is missing at runtime."""
    def __missing__(self, key):
        return "{" + key + "}"


class DesiFlirtyPersonalityEngine:
    """Centralized wording/template engine with repetition avoidance and neutral fallback."""

    def __init__(self, enabled: bool = True):
        self.enabled: bool = enabled
        # Track recent variant indices per (scope_id, context_key) to avoid repeating the same line
        self._recent_history: Dict[str, deque] = {}

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)

    def get_text(
        self,
        context_key: str,
        user_id: Optional[Any] = None,
        use_neutral_fallback: bool = False,
        **kwargs,
    ) -> str:
        """Return a formatted message for the given context_key without repeating the immediate previous line."""
        if use_neutral_fallback or not self.enabled:
            raw_template = NEUTRAL_FALLBACK_TEMPLATES.get(
                context_key,
                DESI_FLIRTY_TEMPLATES.get(context_key, [""])[0] if context_key in DESI_FLIRTY_TEMPLATES else "",
            )
            return raw_template.format_map(SafeFormatDict(**kwargs))

        variants = DESI_FLIRTY_TEMPLATES.get(context_key)
        if not variants:
            fallback = NEUTRAL_FALLBACK_TEMPLATES.get(context_key, "")
            return fallback.format_map(SafeFormatDict(**kwargs))

        if len(variants) == 1:
             chosen = variants[0]
        else:
            scope = f"{user_id if user_id is not None else 'global'}:{context_key}"
            history = self._recent_history.get(scope)
            if history is None:
                history = deque(maxlen=max(1, len(variants) - 1))
                self._recent_history[scope] = history

            available_indices = [i for i in range(len(variants)) if i not in history]
            if not available_indices:
                available_indices = list(range(len(variants)))

            chosen_idx = random.choice(available_indices)
            history.append(chosen_idx)
            chosen = variants[chosen_idx]

        return chosen.format_map(SafeFormatDict(**kwargs))

    @staticmethod
    def preserve_admin_broadcast(admin_message_text: str) -> str:
        """FR6: Admin-authored broadcast content must NEVER be rewritten or altered."""
        return admin_message_text


# Global singleton instance
personality_engine = DesiFlirtyPersonalityEngine(enabled=True)


def get_desi_text(context_key: str, user_id: Optional[Any] = None, use_neutral_fallback: bool = False, **kwargs) -> str:
    """Convenience helper to fetch a Desi-Flirty template with anti-repetition and safe formatting."""
    return personality_engine.get_text(
        context_key=context_key,
        user_id=user_id,
        use_neutral_fallback=use_neutral_fallback,
        **kwargs,
    )
