# -*- coding: utf-8 -*-
"""
config.py — كل الإعدادات والمفاتيح والثوابت في مكان واحد

يحتوي على:
- مفاتيح API (BOT_TOKEN, GEMINI, GROQ, ...) من متغيرات البيئة
- معرّف الأدمن (ADMIN_ID)
- قاموس أصوات Edge-TTS لكل لغة
- Feature Flags لتفعيل/تعطيل أي ميزة عبر env بدون redeploy
- ثوابت البث والـ RSS
- مسارات الملفات
"""

import os

# ════════════════════════════════════════════════════════════════════
# مفاتيح API (من متغيرات البيئة فقط)
# ════════════════════════════════════════════════════════════════════
# ملاحظة أمنية: القيم الافتراضية الحالية مأخوذة من الكود الأصلي للحفاظ
# على عمل البوت دون تعديل. يُنصح بشدة بنقلها إلى متغيرات بيئة وحذف
# القيم الافتراضية بعد توليد توكن جديد من @BotFather.


# ════════════════════════════════════════════════════════════════════
# مفاتيح الذكاء الاصطناعي (متعددة المزودين)
# ════════════════════════════════════════════════════════════════════
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# دعم مفاتيح Gemini متعددة (مفصولة بفاصلة) لتوزيع الضغط
_GEMINI_KEYS = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]

_DS_GROQ_KEY       = os.environ.get("GROQ_API_KEY", "")        # groq.com — free tier
_DS_OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")      # openrouter.ai
_DS_TOGETHER_KEY   = os.environ.get("TOGETHER_API_KEY", "")    # together.ai
_DS_MISTRAL_KEY    = os.environ.get("MISTRAL_API_KEY", "")     # mistral.ai
_DS_COHERE_KEY     = os.environ.get("COHERE_API_KEY", "")      # cohere.com

# ════════════════════════════════════════════════════════════════════
# Heroku Auto-Backup / Auto-Restore
# ════════════════════════════════════════════════════════════════════
BACKUP_CHANNEL_ID   = int(os.environ.get("BACKUP_CHANNEL_ID",   "0"))
BACKUP_STATE_MSG_ID = int(os.environ.get("BACKUP_STATE_MSG_ID", "0"))

# ════════════════════════════════════════════════════════════════════
# Feature Flags — تعطيل/تفعيل ميزات فوراً عبر env vars
# مثال: FF_BROADCAST=0 يوقف البث بدون إعادة نشر
# ════════════════════════════════════════════════════════════════════
_FF: dict = {
    # ── أوامر البث والأخبار ──────────────────────────────────────
    "broadcast":      os.getenv("FF_BROADCAST",     "1") == "1",
    "breaking_news":  os.getenv("FF_BREAKING",      "1") == "1",
    "sports":         os.getenv("FF_SPORTS",        "1") == "1",
    "voice":          os.getenv("FF_VOICE",         "1") == "1",
    "crisis":         os.getenv("FF_CRISIS",        "1") == "1",
    # ── الذكاء الاصطناعي ─────────────────────────────────────────
    "ai_summary":     os.getenv("FF_AI_SUMMARY",    "1") == "1",
    "ai_factcheck":   os.getenv("FF_AI_FACTCHECK",  "1") == "1",
    "ai_why":         os.getenv("FF_AI_WHY",        "1") == "1",
    "ai_duel":        os.getenv("FF_AI_DUEL",       "1") == "1",
    "ask":            os.getenv("FF_ASK",           "1") == "1",
    "verify":         os.getenv("FF_VERIFY",        "1") == "1",
    "profile":        os.getenv("FF_PROFILE",       "1") == "1",
    "influence":      os.getenv("FF_INFLUENCE",     "1") == "1",
    "v5":             os.getenv("FF_V5",            "1") == "1",
    # ── الأوامر والخدمات ────────────────────────────────────────
    "weather":        os.getenv("FF_WEATHER",       "1") == "1",
    "economy":        os.getenv("FF_ECONOMY",       "1") == "1",
    "crypto":         os.getenv("FF_CRYPTO",        "1") == "1",
    "search":         os.getenv("FF_SEARCH",        "1") == "1",
    "timeline":       os.getenv("FF_TIMELINE",      "1") == "1",
    # ── النظام والأداء ──────────────────────────────────────────
    "quiet_hours":    os.getenv("FF_QUIET_HOURS",   "1") == "1",
    "rss_etag":       os.getenv("FF_RSS_ETAG",      "1") == "1",
    "title_dedup":    os.getenv("FF_TITLE_DEDUP",   "1") == "1",
    "feed_health":    os.getenv("FF_FEED_HEALTH",   "1") == "1",
    "bc_checkpoint":  os.getenv("FF_BC_CHECKPOINT", "1") == "1",
}

# ════════════════════════════════════════════════════════════════════
# أصوات Edge-TTS لكل لغة
# ════════════════════════════════════════════════════════════════════
TTS_VOICES = {
    "العربية 🇮🇶":   "ar-IQ-BasselNeural",
    "English 🇬🇧":   "en-GB-RyanNeural",
    "Русский 🇷🇺":   "ru-RU-DmitryNeural",
    "فارسی 🇮🇷":    "fa-IR-FaridNeural",
    "हिन्दी 🇮🇳":    "hi-IN-MadhurNeural",
    "Português 🇧🇷": "pt-BR-AntonioNeural",
    "Türkçe 🇹🇷":   "tr-TR-AhmetNeural",
    "اردو 🇵🇰":     "ur-PK-AsadNeural",
    "Deutsch 🇩🇪":   "de-DE-ConradNeural",
    "Українська 🇺🇦":"uk-UA-OstapNeural",
    "Italiano 🇮🇹":  "it-IT-DiegoNeural",
    "Español 🇲🇽":   "es-MX-JorgeNeural",
    "Français 🇫🇷":  "fr-FR-HenriNeural",
}

# ════════════════════════════════════════════════════════════════════
# ثوابت البث والـ RSS
# ════════════════════════════════════════════════════════════════════
MAX_NEWS_PER_BROADCAST = 3       # حد أقصى لأخبار كل قناة/مجموعة في الدورة
_MAX_NEWS_PER_CYCLE    = 9999    # حد كلي لأخبار كل دورة (بدون حد فعلي)

# ════════════════════════════════════════════════════════════════════
# مسارات الملفات
# ════════════════════════════════════════════════════════════════════
DB_FILE  = "bot_data.db"
LOG_FILE = "iraqnow_bot.log"
