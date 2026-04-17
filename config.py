# config.py
import os

# =============================================================================
# 1. مفاتيح البوت الأساسية (Bot Tokens)
# =============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "5149213983"))
BOT_USERNAME = "Iraqnowbot"

# =============================================================================
# 2. مفاتيح API للخدمات الخارجية (Weather, News, AI)
# =============================================================================
WEATHER_KEY = os.environ.get("WEATHER_KEY", "18a7801721693e772bbada4687d03e43")
NEWS_KEY = os.environ.get("NEWS_KEY", "98b2295d1a034076913e0c0e2aa64fa4")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# مفاتيح AI الإضافية (Groq, OpenRouter, إلخ)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
COHERE_API_KEY = os.environ.get("COHERE_API_KEY", "")

# =============================================================================
# 3. إعدادات السوشيال ميديا (Facebook, Instagram)
# =============================================================================
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "")

# =============================================================================
# 4. إعدادات النسخ الاحتياطي (Heroku Backup)
# =============================================================================
BACKUP_CHANNEL_ID = int(os.environ.get("BACKUP_CHANNEL_ID", "0"))
BACKUP_STATE_MSG_ID = int(os.environ.get("BACKUP_STATE_MSG_ID", "0"))

# =============================================================================
# 5. إعدادات قاعدة البيانات والملفات (Database & File Paths)
# =============================================================================
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# للتطوير المحلي، استخدم SQLite إذا لم يوجد DATABASE_URL
USE_SQLITE = DATABASE_URL is None
if USE_SQLITE:
    DATABASE_URL = "sqlite:///./data/bot_data.db"

DB_FILE = "data/bot_data.db"
USERS_FILE = "data/users.json"
STATS_FILE = "data/stats.json"
BANNED_FILE = "data/banned.json"
RSS_FILE = "data/rss.json"
CHANNELS_FILE = "data/channels.json"
ADMINS_FILE = "data/admins.json"
KEYWORDS_FILE = "data/keywords.json"
TRACK_FILE = "data/tracking.json"
BLACKLIST_FILE = "data/blacklist.json"
READ_STATS_FILE = "data/read_stats.json"
BROADCAST_SETTINGS_FILE = "data/broadcast_settings.json"
NEWS_SETTINGS_FILE = "data/news_settings.json"
INBOX_FILE = "data/inbox.json"
RATINGS_FILE = "data/ratings.json"
WELCOME_FILE = "data/welcome.json"
CUSTOM_TG_CHANNELS_FILE = "data/custom_tg_channels.json"
GLOBAL_SENT_FILE = "data/global_sent_news.json"
SPORTS_CACHE_FILE = "data/sports_match_cache.json"

# =============================================================================
# 6. ثوابت عامة (Timing, Limits, Thresholds)
# =============================================================================
RSS_FRESHNESS_MINUTES = 360  # 6 ساعات
RSS_FETCH_TIMEOUT = 8        # ثواني
MAX_NEWS_PER_USER_CYCLE = 10
MAX_NEWS_PER_BROADCAST = 3   # للقنوات
QUEUE_MAX_SIZE = 20000
QUEUE_WORKERS = 5
USER_SENT_TTL = 6 * 3600     # 6 ساعات
GLOBAL_SENT_TTL = 2 * 3600   # 2 ساعات
AI_CACHE_TTL = 3 * 3600      # 3 ساعات

# =============================================================================
# 7. تواقيت المنطقة الزمنية (Timezones)
# =============================================================================
import datetime as _dt
SA_TZ_OFFSET = _dt.timedelta(hours=3)

def _now_sa():
    """يُعيد الوقت الحالي بتوقيت السعودية / العراق (UTC+3)."""
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + SA_TZ_OFFSET

def _sa_str(fmt="%H:%M:%S — %d/%m/%Y"):
    """يُعيد الوقت الحالي كنص بتوقيت السعودية بالصيغة المطلوبة."""
    return _now_sa().strftime(fmt)
