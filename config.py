# -*- coding: utf-8 -*-
"""
config.py — كل الإعدادات من متغيرات البيئة فقط. لا قيم افتراضية للمفاتيح.
"""

import os
import sys
import logging

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════
# دوال الأمان
# ════════════════════════════════════════════════════════════════════

def _require(var: str) -> str:
    """يوقف البوت فوراً إذا لم يُضبط المتغير الإلزامي."""
    val = os.environ.get(var, "").strip()
    if not val:
        logger.critical(f"[SECURITY] المتغير الإلزامي '{var}' غير مضبوط. إيقاف البوت.")
        sys.exit(1)
    return val

def _optional(var: str) -> str:
    """متغير اختياري — يُعيد نصاً فارغاً إذا لم يُضبط."""
    return os.environ.get(var, "").strip()

def _require_int(var: str, default: int = 0) -> int:
    val = os.environ.get(var, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        logger.warning(f"[SECURITY] المتغير '{var}' ليس رقماً صحيحاً، سيُستخدم {default}")
        return default

# ════════════════════════════════════════════════════════════════════
# مفاتيح API — من متغيرات البيئة فقط، لا قيم مضمّنة أبداً
# ════════════════════════════════════════════════════════════════════

BOT_TOKEN   = _require("BOT_TOKEN")       # إلزامي — البوت لا يعمل بدونه
WEATHER_KEY = _optional("WEATHER_KEY")    # اختياري
NEWS_KEY    = _optional("NEWS_KEY")       # اختياري
ADMIN_ID    = _require_int("ADMIN_ID", 0)

# ════════════════════════════════════════════════════════════════════
# مفاتيح الذكاء الاصطناعي
# ════════════════════════════════════════════════════════════════════
GEMINI_API_KEY     = _optional("GEMINI_API_KEY")
_GEMINI_KEYS       = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]
_DS_GROQ_KEY       = _optional("GROQ_API_KEY")
_DS_OPENROUTER_KEY = _optional("OPENROUTER_KEY")
_DS_TOGETHER_KEY   = _optional("TOGETHER_API_KEY")
_DS_MISTRAL_KEY    = _optional("MISTRAL_API_KEY")
_DS_COHERE_KEY     = _optional("COHERE_API_KEY")

# مفاتيح Social Media
FB_PAGE_TOKEN = _optional("FB_PAGE_TOKEN")
FB_PAGE_ID    = _optional("FB_PAGE_ID")
IG_USER_ID    = _optional("IG_USER_ID")
IMGBB_API_KEY = _optional("IMGBB_API_KEY")

# ════════════════════════════════════════════════════════════════════
# Heroku Auto-Backup
# ════════════════════════════════════════════════════════════════════
BACKUP_CHANNEL_ID   = _require_int("BACKUP_CHANNEL_ID",   0)
BACKUP_STATE_MSG_ID = _require_int("BACKUP_STATE_MSG_ID", 0)

# ════════════════════════════════════════════════════════════════════
# فحص أمني عند الإقلاع — يطبع ما هو مضبوط وما هو غائب
# ════════════════════════════════════════════════════════════════════
def security_audit() -> None:
    """اطبع حالة كل متغير عند البدء — بدون كشف القيم."""
    keys = {
        "BOT_TOKEN":        bool(BOT_TOKEN),
        "ADMIN_ID":         bool(ADMIN_ID),
        "WEATHER_KEY":      bool(WEATHER_KEY),
        "NEWS_KEY":         bool(NEWS_KEY),
        "GEMINI_API_KEY":   bool(GEMINI_API_KEY),
        "GROQ_API_KEY":     bool(_DS_GROQ_KEY),
        "FB_PAGE_TOKEN":    bool(FB_PAGE_TOKEN),
        "IMGBB_API_KEY":    bool(IMGBB_API_KEY),
    }
    lines = ["[SECURITY AUDIT] حالة متغيرات البيئة عند الإقلاع:"]
    for k, ok in keys.items():
        lines.append(f"  {'✅' if ok else '⚠️ '} {k}")
    logger.info("\n".join(lines))

# ════════════════════════════════════════════════════════════════════
# Feature Flags
# ════════════════════════════════════════════════════════════════════
_FF: dict = {
    "broadcast":      os.getenv("FF_BROADCAST",     "1") == "1",
    "breaking_news":  os.getenv("FF_BREAKING",      "1") == "1",
    "sports":         os.getenv("FF_SPORTS",        "1") == "1",
    "voice":          os.getenv("FF_VOICE",         "1") == "1",
    "crisis":         os.getenv("FF_CRISIS",        "1") == "1",
    "ai_summary":     os.getenv("FF_AI_SUMMARY",    "1") == "1",
    "ai_factcheck":   os.getenv("FF_AI_FACTCHECK",  "1") == "1",
    "ai_why":         os.getenv("FF_AI_WHY",        "1") == "1",
    "ai_duel":        os.getenv("FF_AI_DUEL",       "1") == "1",
    "ask":            os.getenv("FF_ASK",           "1") == "1",
    "verify":         os.getenv("FF_VERIFY",        "1") == "1",
    "profile":        os.getenv("FF_PROFILE",       "1") == "1",
    "influence":      os.getenv("FF_INFLUENCE",     "1") == "1",
    "v5":             os.getenv("FF_V5",            "1") == "1",
    "weather":        os.getenv("FF_WEATHER",       "1") == "1",
    "economy":        os.getenv("FF_ECONOMY",       "1") == "1",
    "crypto":         os.getenv("FF_CRYPTO",        "1") == "1",
    "search":         os.getenv("FF_SEARCH",        "1") == "1",
    "timeline":       os.getenv("FF_TIMELINE",      "1") == "1",
    "quiet_hours":    os.getenv("FF_QUIET_HOURS",   "1") == "1",
    "rss_etag":       os.getenv("FF_RSS_ETAG",      "1") == "1",
    "title_dedup":    os.getenv("FF_TITLE_DEDUP",   "1") == "1",
    "feed_health":    os.getenv("FF_FEED_HEALTH",   "1") == "1",
    "bc_checkpoint":  os.getenv("FF_BC_CHECKPOINT", "1") == "1",
}

# ════════════════════════════════════════════════════════════════════
# أصوات Edge-TTS
# ════════════════════════════════════════════════════════════════════
TTS_VOICES = {
    "العربية 🇮🇶":    "ar-IQ-BasselNeural",
    "English 🇬🇧":    "en-GB-RyanNeural",
    "Русский 🇷🇺":    "ru-RU-DmitryNeural",
    "فارسی 🇮🇷":     "fa-IR-FaridNeural",
    "हिन्दी 🇮🇳":     "hi-IN-MadhurNeural",
    "Português 🇧🇷":  "pt-BR-AntonioNeural",
    "Türkçe 🇹🇷":    "tr-TR-AhmetNeural",
    "اردو 🇵🇰":      "ur-PK-AsadNeural",
    "Deutsch 🇩🇪":    "de-DE-ConradNeural",
    "Українська 🇺🇦": "uk-UA-OstapNeural",
    "Italiano 🇮🇹":   "it-IT-DiegoNeural",
    "Español 🇲🇽":    "es-MX-JorgeNeural",
    "Français 🇫🇷":   "fr-FR-HenriNeural",
}

# ════════════════════════════════════════════════════════════════════
# ثوابت البث والـ RSS
# ════════════════════════════════════════════════════════════════════
# FIX B4: كانت القيمة 3، لكن bot_legacy.py تُعيد تعريفها بـ 8 (السطر 22046).
# القيمة الفعلية التي يستخدمها البوت هي 8 لأنها تُعيَّن لاحقاً بعد `from config import *`.
# نُزامن هنا حتى لا يضلّل المطوّر مستقبلاً.
MAX_NEWS_PER_BROADCAST = 8   # 8 أخبار كحد أقصى لكل دورة بث (يُزامن مع bot_legacy L22046)
_MAX_NEWS_PER_CYCLE    = 500   # FIX: كان 9999 — خُفِّض لمنع تجميد الدورة

# ════════════════════════════════════════════════════════════════════
# مسارات الملفات
# ════════════════════════════════════════════════════════════════════
DB_FILE  = "bot_data.db"
LOG_FILE = "iraqnow_bot.log"
