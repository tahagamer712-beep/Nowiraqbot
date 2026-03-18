import telebot
from telebot import types
import requests
import feedparser
import atexit
import os
import json
import datetime
import time
import sqlite3
import threading
import queue
from apscheduler.schedulers.background import BackgroundScheduler

# ======== مفاتيح البوت ========
BOT_TOKEN = "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
WEATHER_KEY = "18a7801721693e772bbada4687d03e43"
NEWS_KEY = "98b2295d1a034076913e0c0e2aa64fa4"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "5149213983"))

bot = telebot.TeleBot(BOT_TOKEN)

# ======== SQLite للمستخدمين ========
DB_FILE = "bot_data.db"
_db_lock = threading.Lock()

def _init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS users_store (
        uid TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )""")
    conn.commit()
    return conn

_db_conn = _init_db()

def _db_load_users():
    result = {}
    with _db_lock:
        rows = _db_conn.execute("SELECT uid, data FROM users_store").fetchall()
    for uid, raw in rows:
        try:
            d = json.loads(raw)
            if "sent_news" in d:
                d["sent_news"] = set(d["sent_news"])
            result[uid] = d
        except:
            pass
    return result

def _db_save_user(uid, user_data):
    d = dict(user_data)
    if "sent_news" in d:
        d["sent_news"] = list(d["sent_news"])[-500:]
    raw = json.dumps(d, ensure_ascii=False)
    with _db_lock:
        _db_conn.execute(
            "INSERT OR REPLACE INTO users_store (uid, data) VALUES (?, ?)",
            (str(uid), raw)
        )
        _db_conn.commit()

def _db_save_all_users(users_dict):
    rows = []
    for uid, user_data in users_dict.items():
        d = dict(user_data)
        if "sent_news" in d:
            d["sent_news"] = list(d["sent_news"])[-500:]
        rows.append((str(uid), json.dumps(d, ensure_ascii=False)))
    with _db_lock:
        _db_conn.executemany(
            "INSERT OR REPLACE INTO users_store (uid, data) VALUES (?, ?)",
            rows
        )
        _db_conn.commit()

def _migrate_users_from_json():
    if not os.path.exists(USERS_FILE):
        return
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if old_data:
            _db_save_all_users(old_data)
            os.rename(USERS_FILE, USERS_FILE + ".migrated")
            print("تم نقل بيانات المستخدمين من JSON إلى SQLite")
    except Exception as e:
        print(f"خطأ في هجرة البيانات: {e}")

# ======== كاش الطقس (10 دقائق لكل مدينة) ========
_weather_cache = {}
_WEATHER_CACHE_TTL = 600

def _get_cached_weather(city, lang_code):
    key = f"{city}_{lang_code}"
    if key in _weather_cache:
        data, ts = _weather_cache[key]
        if (datetime.datetime.now() - ts).total_seconds() < _WEATHER_CACHE_TTL:
            return data
    return None

def _set_cached_weather(city, lang_code, data):
    _weather_cache[f"{city}_{lang_code}"] = (data, datetime.datetime.now())

def _fetch_weather_cached(city, lang_code):
    d = _get_cached_weather(city, lang_code)
    if d:
        return d
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
    try:
        d = requests.get(url, timeout=10).json()
        if d.get("cod") == 200:
            _set_cached_weather(city, lang_code, d)
            return d
    except Exception:
        pass
    return None

# ======== طابور الإرسال (20 رسالة/ثانية) ========
_send_queue = queue.Queue()

def _queue_worker():
  while True:
      try:
          chat_id, text, kwargs = _send_queue.get(timeout=1)
          try:
              bot.send_message(chat_id, text, **kwargs)
          except Exception:
              pass
          finally:
              _send_queue.task_done()
          time.sleep(0.05)
      except queue.Empty:
          continue

_queue_thread = threading.Thread(target=_queue_worker, daemon=True)
_queue_thread.start()

def queue_send(chat_id, text, **kwargs):
    _send_queue.put((chat_id, text, kwargs))

# ======== ملفات الحفظ ========
USERS_FILE = "users.json"
STATS_FILE = "stats.json"
BANNED_FILE = "banned.json"
RSS_FILE = "rss.json"
ADMINS_FILE = "admins.json"
KEYWORDS_FILE = "keywords.json"
TRACK_FILE = "tracking.json"
CHANNELS_FILE = "channels.json"
BLACKLIST_FILE = "blacklist.json"
READ_STATS_FILE = "read_stats.json"
BROADCAST_SETTINGS_FILE = "broadcast_settings.json"
NEWS_SETTINGS_FILE = "news_settings.json"
INBOX_FILE = "inbox.json"
RATINGS_FILE = "ratings.json"

# ======== اسم البوت ========
BOT_USERNAME = "Iraqnowbot"

# ======== تحميل وحفظ البيانات ========
def load_json(file, default):
    try:
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if file == USERS_FILE:
                for uid in data:
                    if "sent_news" in data[uid]:
                        data[uid]["sent_news"] = set(data[uid]["sent_news"])
            return data
    except:
        return default

def save_json(file, data):
    try:
        save_data = data
        if file == USERS_FILE:
            save_data = {}
            for uid, val in data.items():
                save_data[uid] = dict(val)
                if "sent_news" in save_data[uid]:
                    save_data[uid]["sent_news"] = list(save_data[uid]["sent_news"])
        with open(file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        notify_admin_error(f"خطأ في حفظ البيانات: {e}")

_migrate_users_from_json()
users = _db_load_users()
banned = load_json(BANNED_FILE, [])
banned = [int(b) for b in banned]

stats = load_json(STATS_FILE, {
    "total_users": 0,
    "daily_users": {},
    "button_presses": {},
    "countries_count": {},
    "languages_count": {},
    "premium_users": [],
    "revenue": 0.0
})

# ======== قائمة الأدمن المتعددين ========
extra_admins = load_json(ADMINS_FILE, [])
extra_admins = [int(a) for a in extra_admins]

def is_admin(uid):
    return int(uid) == ADMIN_ID or int(uid) in extra_admins

def save_extra_admins():
    save_json(ADMINS_FILE, extra_admins)

# ======== القنوات والمجموعات ========
# كل عنصر: {"id": chat_id, "title": "اسم القناة", "type": "channel"/"group", "lang": "العربية 🇮🇶"}
channels_groups = load_json(CHANNELS_FILE, [])

def save_channels_groups():
    save_json(CHANNELS_FILE, channels_groups)

# ======== القائمة السوداء للكلمات ========
blacklist_words = load_json(BLACKLIST_FILE, [])

def save_blacklist():
    save_json(BLACKLIST_FILE, blacklist_words)

# ======== عداد القراءة ========
read_stats = load_json(READ_STATS_FILE, {"total_opens": 0, "daily": {}})

def save_read_stats():
    save_json(READ_STATS_FILE, read_stats)

# ======== إعدادات توقيت البث ========
broadcast_settings = load_json(BROADCAST_SETTINGS_FILE, {"interval_minutes": 5})

def save_broadcast_settings():
    save_json(BROADCAST_SETTINGS_FILE, broadcast_settings)

news_settings = load_json(NEWS_SETTINGS_FILE, {
    "label": "🚨 خبر عاجل",
    "separator": "━━━━━━━━━━━━━━",
    "signature": "عبر بوت أخبار العالم\n@Iraqnowbot"
})

def save_news_settings():
    save_json(NEWS_SETTINGS_FILE, news_settings)

inbox_messages = load_json(INBOX_FILE, [])

def save_inbox():
    save_json(INBOX_FILE, inbox_messages[-200:])

ratings_data = load_json(RATINGS_FILE, {"entries": [], "bot_sum": 0, "news_sum": 0, "count": 0})

def save_ratings():
    save_json(RATINGS_FILE, ratings_data)

# ======== إحصائيات القنوات ========
# يُحفظ داخل كل عنصر في channels_groups تحت مفتاح "news_sent_count"

# ======== حالة البوت ========
bot_paused = False
pause_message = "🔧 البوت متوقف مؤقتاً، سيعود قريباً."
welcome_override = None

# ======== رابط التواصل ========
CONTACT_LINK = "https://t.me/Ilovedaddyandmommybot"

# ======== تلميحات الاستخدام بعد اختيار اللغة/الدولة ========
USAGE_HINTS = {
    "العربية 🇮🇶": (
        "💡 *طريقة الاستخدام:*\n\n"
        "🌤 اضغط *الطقس الآن* لمعرفة حالة الطقس\n"
        "📰 اضغط *آخر الأخبار* لأحدث الأخبار\n"
        "💱 اضغط *أسعار العملات* لأسعار الصرف\n"
        "🔍 اضغط *بحث* للبحث في الأخبار\n"
        "🔔 اضغط *الإشعارات* لتفعيل/إيقاف التنبيهات\n"
        "⭐ اضغط *المميز* للحصول على ميزات حصرية"
    ),
    "English 🇬🇧": (
        "💡 *How to use:*\n\n"
        "🌤 Tap *Weather Now* for weather updates\n"
        "📰 Tap *Latest News* for top stories\n"
        "💱 Tap *Currency Rates* for exchange rates\n"
        "🔍 Tap *Search* to search news\n"
        "🔔 Tap *Notifications* to toggle alerts\n"
        "⭐ Tap *Premium* for exclusive features"
    ),
    "Русский 🇷🇺": (
        "💡 *Как использовать:*\n\n"
        "🌤 Нажмите *Погода* для обновления погоды\n"
        "📰 Нажмите *Новости* для свежих новостей\n"
        "💱 Нажмите *Курсы валют* для обменных курсов\n"
        "🔍 Нажмите *Поиск* для поиска новостей\n"
        "🔔 Нажмите *Уведомления* для управления оповещениями\n"
        "⭐ Нажмите *Премиум* для эксклюзивных функций"
    ),
    "فارسی 🇮🇷": (
        "💡 *نحوه استفاده:*\n\n"
        "🌤 روی *آبوهوا* بزنید برای وضعیت هوا\n"
        "📰 روی *اخبار* بزنید برای آخرین خبرها\n"
        "💱 روی *نرخ ارز* بزنید برای قیمتها\n"
        "🔍 روی *جستجو* بزنید برای جستجوی خبر\n"
        "🔔 روی *اعلانها* بزنید برای مدیریت اطلاعرسانی\n"
        "⭐ روی *ویژه* بزنید برای امکانات انحصاری"
    ),
    "हिन्दी 🇮🇳": (
        "💡 *उपयोग कैसे करें:*\n\n"
        "🌤 मौसम के लिए *मौसम अभी* दबाएं\n"
        "📰 खबरों के लिए *ताज़ा खबरें* दबाएं\n"
        "💱 विनिमय दर के लिए *मुद्रा दरें* दबाएं\n"
        "🔍 खोज के लिए *खबर खोजें* दबाएं\n"
        "🔔 अलर्ट के लिए *सूचनाएं* दबाएं\n"
        "⭐ विशेष सुविधाओं के लिए *प्रीमियम* दबाएं"
    ),
    "Português 🇧🇷": (
        "💡 *Como usar:*\n\n"
        "🌤 Toque em *Clima* para o tempo atual\n"
        "📰 Toque em *Notícias* para as últimas notícias\n"
        "💱 Toque em *Câmbio* para taxas de câmbio\n"
        "🔍 Toque em *Buscar* para pesquisar notícias\n"
        "🔔 Toque em *Notificações* para gerenciar alertas\n"
        "⭐ Toque em *Premium* para recursos exclusivos"
    ),
    "Türkçe 🇹🇷": (
        "💡 *Nasıl kullanılır:*\n\n"
        "🌤 Hava durumu için *Hava durumu* düğmesine basın\n"
        "📰 Haberler için *Son haberler* düğmesine basın\n"
        "💱 Döviz için *Döviz kurları* düğmesine basın\n"
        "🔍 Arama için *Haber ara* düğmesine basın\n"
        "🔔 Bildirimler için *Bildirimler* düğmesine basın\n"
        "⭐ Özel özellikler için *Premium* düğmesine basın"
    ),
    "اردو 🇵🇰": (
        "💡 *استعمال کا طریقہ:*\n\n"
        "🌤 موسم کے لیے *موسم ابھی* دبائیں\n"
        "📰 خبروں کے لیے *تازہ خبریں* دبائیں\n"
        "💱 کرنسی کے لیے *کرنسی ریٹ* دبائیں\n"
        "🔍 تلاش کے لیے *خبریں تلاش کریں* دبائیں\n"
        "🔔 الرٹ کے لیے *اطلاعات* دبائیں\n"
        "⭐ خصوصی خصوصیات کے لیے *پریمیم* دبائیں"
    ),
    "Deutsch 🇩🇪": (
        "💡 *Anleitung:*\n\n"
        "🌤 Tippen Sie auf *Wetter* für das aktuelle Wetter\n"
        "📰 Tippen Sie auf *Nachrichten* für aktuelle Nachrichten\n"
        "💱 Tippen Sie auf *Wechselkurse* für Wechselkurse\n"
        "🔍 Tippen Sie auf *Suchen* für die Nachrichtensuche\n"
        "🔔 Tippen Sie auf *Benachrichtigungen* für Alarme\n"
        "⭐ Tippen Sie auf *Premium* für exklusive Funktionen"
    ),
    "Українська 🇺🇦": (
        "💡 *Як користуватись:*\n\n"
        "🌤 Натисніть *Погода* для перегляду погоди\n"
        "📰 Натисніть *Новини* для останніх новин\n"
        "💱 Натисніть *Курси валют* для курсів обміну\n"
        "🔍 Натисніть *Пошук* для пошуку новин\n"
        "🔔 Натисніть *Сповіщення* для керування оповіщеннями\n"
        "⭐ Натисніть *Преміум* для ексклюзивних функцій"
    ),
    "Italiano 🇮🇹": (
        "💡 *Come usare:*\n\n"
        "🌤 Tocca *Meteo* per il meteo attuale\n"
        "📰 Tocca *Notizie* per le ultime notizie\n"
        "💱 Tocca *Tassi di cambio* per i cambi valuta\n"
        "🔍 Tocca *Cerca* per cercare notizie\n"
        "🔔 Tocca *Notifiche* per gestire gli avvisi\n"
        "⭐ Tocca *Premium* per funzionalità esclusive"
    ),
    "Español 🇲🇽": (
        "💡 *Cómo usar:*\n\n"
        "🌤 Toca *Clima* para el tiempo actual\n"
        "📰 Toca *Noticias* para las últimas noticias\n"
        "💱 Toca *Tipos de cambio* para tasas de cambio\n"
        "🔍 Toca *Buscar* para buscar noticias\n"
        "🔔 Toca *Notificaciones* para gestionar alertas\n"
        "⭐ Toca *Premium* para funciones exclusivas"
    ),
}

# ======== اللغات ========
languages = {
    "Arabic": "العربية 🇮🇶",
    "English": "English 🇬🇧",
    "Russian": "Русский 🇷🇺",
    "Farsi": "فارسی 🇮🇷",
    "Hindi": "हिन्दी 🇮🇳",
    "Portuguese": "Português 🇧🇷",
    "Turkish": "Türkçe 🇹🇷",
    "Urdu": "اردو 🇵🇰",
    "German": "Deutsch 🇩🇪",
    "Ukrainian": "Українська 🇺🇦",
    "Italian": "Italiano 🇮🇹",
    "Spanish": "Español 🇲🇽"
}

# ======== كودات اللغة للطقس ========
LANG_CODES = {
    "العربية 🇮🇶": "ar",
    "English 🇬🇧": "en",
    "Русский 🇷🇺": "ru",
    "فارسی 🇮🇷": "fa",
    "हिन्दी 🇮🇳": "hi",
    "Português 🇧🇷": "pt",
    "Türkçe 🇹🇷": "tr",
    "اردو 🇵🇰": "ur",
    "Deutsch 🇩🇪": "de",
    "Українська 🇺🇦": "uk",
    "Italiano 🇮🇹": "it",
    "Español 🇲🇽": "es"
}

# ======== الدول والمحافظات ========
countries = {
    "العربية 🇮🇶": {
        "العراق": ["بغداد", "البصرة", "أربيل", "الأنبار", "كركوك", "ذي قار", "بابل", "ميسان", "نينوى", "واسط", "كربلاء", "صلاح الدين", "ديالى", "القادسية", "المثنى", "حلبجة"],
        "السعودية 🇸🇦": [],
        "الكويت 🇰🇼": [],
        "قطر 🇶🇦": [],
        "الإمارات العربية المتحدة 🇦🇪": [],
        "البحرين 🇧🇭": [],
        "عُمان 🇴🇲": [],
        "اليمن 🇾🇪": [],
        "سوريا 🇸🇾": [],
        "لبنان 🇱🇧": [],
        "الأردن 🇯🇴": [],
        "فلسطين 🇵🇸": [],
        "مصر 🇪🇬": [],
        "ليبيا 🇱🇾": [],
        "تونس 🇹🇳": [],
        "الجزائر 🇩🇿": [],
        "المغرب 🇲🇦": [],
        "موريتانيا 🇲🇷": [],
        "السودان 🇸🇩": [],
        "الصومال 🇸🇴": [],
        "جيبوتي 🇩🇯": [],
        "جزر القمر 🇰🇲": []
    },
    "English 🇬🇧": {
        "USA": ["New York", "Washington", "Los Angeles", "Chicago", "Houston"],
        "UK": ["London", "Manchester", "Birmingham", "Glasgow", "Liverpool"]
    },
    "Русский 🇷🇺": {
        "Россия": ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань"]
    },
    "فارسی 🇮🇷": {
        "ایران": ["تهران", "اصفهان", "شیراز", "تبریز", "مشهد"]
    },
    "हिन्दी 🇮🇳": {
        "India": ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai"]
    },
    "Português 🇧🇷": {
        "Brasil": ["São Paulo", "Rio de Janeiro", "Brasília", "Salvador", "Fortaleza"]
    },
    "Türkçe 🇹🇷": {
        "Türkiye": ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya"]
    },
    "اردو 🇵🇰": {
        "Pakistan": ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad"]
    },
    "Deutsch 🇩🇪": {
        "Deutschland": ["Berlin", "Hamburg", "München", "Köln", "Frankfurt"]
    },
    "Українська 🇺🇦": {
        "Україна": ["Київ", "Харків", "Одеса", "Дніпро", "Львів"]
    },
    "Italiano 🇮🇹": {
        "Italia": ["Roma", "Milano", "Napoli", "Torino", "Palermo"]
    },
    "Español 🇲🇽": {
        "México": ["Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana"],
        "España": ["Madrid", "Barcelona", "Valencia", "Sevilla", "Bilbao"]
    }
}

# ======== مصادر RSS ========
DEFAULT_RSS = {
    "العربية 🇮🇶": [
        # عراق
        "https://www.alsumaria.tv/rss/latest-news",
        "https://shafaq.com/ar/rss.xml",
        "https://www.rudaw.net/arabic/rss",
        "https://www.almaalomah.com/feed/",
        "https://almada-paper.com/feed/",
        # قنوات عربية كبرى
        "https://www.alarabiya.net/.mrss/ar/0/0/0.xml",
        "https://www.bbc.com/arabic/index.xml",
        "https://www.aljazeera.net/aljazeera/feeds/rss.xml",
        "https://www.skynewsarabia.com/rss.xml",
        "https://feeds.skynewsarabia.com/web/rss/2",
        "https://arabic.rt.com/rss/",
        "https://www.independentarabia.com/rss.xml",
        "https://www.france24.com/ar/rss",
        "https://arabic.euronews.com/rss",
        "https://arabi21.com/rss.xml",
        "https://www.middleeasteye.net/ar/rss",
        "https://www.aawsat.com/rss.xml",
        # مصر
        "https://rss.almasryalyoum.com/rss.xml",
        # الخليج
        "https://feeds.feedburner.com/alkhaleejonline",
        "https://www.alriyadh.com/tools/rss/rss.xml",
        # لبنان / سوريا
        "https://www.elnashra.com/rss",
        # فلسطين / غزة
        "https://www.alquds.com/feed/",
    ],
    "English 🇬🇧": [
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.reuters.com/reuters/worldNews",
        "https://rss.cnn.com/rss/edition_world.rss",
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.washingtonpost.com/rss/world",
        "https://rss.dw.com/rdf/rss-en-all",
    ],
    "Русский 🇷🇺": [
        "https://www.rbc.ru/rss/news",
        "https://tass.ru/rss/v2.xml",
        "https://rss.dw.com/rdf/rss-ru-all",
        "https://www.bbc.com/russian/index.xml",
        "https://www.golos-ameriki.ru/api/zrqomtmopp",
        "https://meduza.io/rss/all",
    ],
    "فارسی 🇮🇷": [
        "https://www.radiofarda.com/api/zrqomtmopp",
        "https://ir.voanews.com/api/zrqomtmopp",
        "https://www.bbc.com/persian/index.xml",
        "https://rss.dw.com/rdf/rss-per-all",
        "https://www.dw.com/fa/rss",
    ],
    "हिन्दी 🇮🇳": [
        "https://feeds.bbci.co.uk/hindi/rss.xml",
        "https://www.hindustantimes.com/rss/rssfeed.xml",
        "https://ndtv.com/rss/top-stories",
        "https://www.aajtak.in/rss/top-stories.xml",
        "https://rss.dw.com/rdf/rss-hin-all",
        "https://www.indiatoday.in/rss/home",
    ],
    "Português 🇧🇷": [
        "https://feeds.bbci.co.uk/portuguese/rss.xml",
        "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",
        "https://rss.dw.com/rdf/rss-por-all",
        "https://g1.globo.com/rss/g1/index.xml",
        "https://www.uol.com.br/rss.xml",
        "https://feeds.folha.uol.com.br/poder/rss091.xml",
    ],
    "Türkçe 🇹🇷": [
        "https://feeds.bbci.co.uk/turkish/rss.xml",
        "https://www.aa.com.tr/tr/rss/default",
        "https://rss.dw.com/rdf/rss-tur-all",
        "https://www.hurriyet.com.tr/rss/anasayfa",
        "https://www.sabah.com.tr/rss/anasayfa.xml",
        "https://www.ntv.com.tr/son-dakika.rss",
    ],
    "اردو 🇵🇰": [
        "https://feeds.bbci.co.uk/urdu/rss.xml",
        "https://www.geo.tv/rss",
        "https://www.jang.com.pk/rss/1",
        "https://rss.dw.com/rdf/rss-urd-all",
        "https://www.urduvoa.com/api/zrqomtmopp",
        "https://www.express.pk/feed",
    ],
    "Deutsch 🇩🇪": [
        "https://www.spiegel.de/international/index.rss",
        "https://rss.dw.com/rdf/rss-de-all",
        "https://www.tagesschau.de/xml/rss2",
        "https://www.faz.net/rss/aktuell",
        "https://www.zeit.de/news/rss-aktuell",
    ],
    "Українська 🇺🇦": [
        "https://feeds.bbci.co.uk/ukrainian/rss.xml",
        "https://www.ukrinform.ua/rss/block-lastnews",
        "https://rss.dw.com/rdf/rss-ukr-all",
        "https://www.unian.ua/rss/all_news.rss",
        "https://www.pravda.com.ua/rss/view_news/",
        "https://espresso.com.ua/rss",
    ],
    "Italiano 🇮🇹": [
        "https://www.repubblica.it/rss/homepage/rss2.0.xml",
        "https://www.corriere.it/rss/homepage.xml",
        "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
        "https://rss.dw.com/rdf/rss-it-all",
        "https://www.lastampa.it/rss.xml",
        "https://feeds.bbci.co.uk/italian/rss.xml",
    ],
    "Español 🇲🇽": [
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
        "https://feeds.bbci.co.uk/mundo/rss.xml",
        "https://rss.dw.com/rdf/rss-es-all",
        "https://feeds.reuters.com/reuters/MXdomesticNews",
        "https://www.infobae.com/feeds/rss/",
        "https://cnnespanol.cnn.com/feed/",
        "https://eldiariony.com/feed/",
    ],
}

RSS = load_json(RSS_FILE, DEFAULT_RSS)

def save_rss():
    save_json(RSS_FILE, RSS)

# ======== مصادر أخبار الرياضة ========
SPORTS_RSS = {
    "العربية 🇮🇶": [
        "https://www.skynewsarabia.com/rss/sport.xml",
        "https://www.filgoal.com/rss",
        "https://www.yallakora.com/rss",
    ],
    "English 🇬🇧": [
        "https://feeds.bbci.co.uk/sport/rss.xml",
        "https://www.espn.com/espn/rss/news",
        "https://rss.skysports.com/rss/swf/latest.xml",
        "https://feeds.feedburner.com/SkySports-Football",
    ],
    "Русский 🇷🇺": [
        "https://rsport.ria.ru/export/rss2/index.xml",
        "https://www.sports.ru/rss/main.xml",
    ],
    "فارسی 🇮🇷": [
        "https://feeds.bbci.co.uk/persian/rss.xml",
        "https://www.varzesh3.com/rss/all",
    ],
    "Türkçe 🇹🇷": [
        "https://www.ntv.com.tr/spor.rss",
        "https://www.sabah.com.tr/rss/spor.xml",
    ],
    "Deutsch 🇩🇪": [
        "https://rss.dw.com/rdf/rss-de-sports",
        "https://www.sport1.de/rss/sport1-news.rss",
    ],
    "Español 🇲🇽": [
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/deportes/portada",
        "https://cnnespanol.cnn.com/deportes/feed/",
    ],
    "Português 🇧🇷": [
        "https://globoesporte.globo.com/dynamo/esportes/futebol/rss2.xml",
        "https://feeds.bbci.co.uk/portuguese/rss.xml",
    ],
    "Italiano 🇮🇹": [
        "https://www.gazzetta.it/rss/home.xml",
        "https://feeds.bbci.co.uk/sport/rss.xml",
    ],
    "हिन्दी 🇮🇳": [
        "https://feeds.bbci.co.uk/hindi/rss.xml",
    ],
    "اردو 🇵🇰": [
        "https://www.geo.tv/rss",
    ],
    "Українська 🇺🇦": [
        "https://www.ukrinform.ua/rss/block-sport",
    ],
}

# ======== الكلمات المفتاحية للمستخدمين المميزين ========
user_keywords = load_json(KEYWORDS_FILE, {})

def save_keywords():
    save_json(KEYWORDS_FILE, user_keywords)

# ======== تتبع العملات والأسهم ========
tracked_assets = load_json(TRACK_FILE, {})

def save_tracked_assets():
    save_json(TRACK_FILE, tracked_assets)

# ======== الأزرار ========
BUTTONS = {
    "العربية 🇮🇶": {
        "weather": "🌤 الطقس الآن",
        "forecast": "📅 توقعات 3 أيام",
        "news": "📰 آخر الأخبار",
        "all_news": "📰 إرسال كل الأخبار",
        "mena_politics": "📰 أخبار الشرق الأوسط",
        "trending": "🔥 الأكثر تداولاً",
        "sports": "⚽ أخبار الرياضة",
        "daily_summary": "📋 ملخص أخبار اليوم",
        "weekly_summary": "📆 ملخص أسبوعي",
        "news_cats": "🗂 اختيار أنواع الأخبار",
        "currency": "💱 أسعار العملات",
        "dollar_parallel": "💵 دولار السوق",
        "convert": "🔄 محوّل العملات",
        "crypto": "💎 العملات الرقمية",
        "track_asset": "📌 تتبع عملة/سهم",
        "prayer": "🕌 أوقات الصلاة",
        "search": "🔍 بحث في الأخبار",
        "my_stats": "📈 إحصائياتي",
        "referral": "🎁 دعواتي",
        "top_referrers": "🏆 أفضل الداعين",
        "share_bot": "📢 انشر البوت",
        "public_stats": "📊 إحصائيات البوت",
        "notif_on": "🔔 إيقاف الإشعارات",
        "notif_off": "🔕 تفعيل الإشعارات",
        "premium": "⭐ المميز",
        "settings": "🔄 تغيير الإعدادات",
        "choose": "✅ اختر ما تريد:"
    },
    "English 🇬🇧": {
        "weather": "🌤 Weather Now",
        "forecast": "📅 3-Day Forecast",
        "news": "📰 Latest News",
        "all_news": "📰 Send All News",
        "mena_politics": "📰 Middle East News",
        "trending": "🔥 Trending News",
        "sports": "⚽ Sports News",
        "daily_summary": "📋 Daily News Summary",
        "weekly_summary": "📆 Weekly Summary",
        "news_cats": "🗂 News Categories",
        "currency": "💱 Currency Rates",
        "dollar_parallel": "💵 Parallel Dollar",
        "convert": "🔄 Currency Converter",
        "crypto": "💎 Crypto Prices",
        "track_asset": "📌 Track Asset",
        "prayer": "🕌 Prayer Times",
        "search": "🔍 Search News",
        "my_stats": "📈 My Statistics",
        "referral": "🎁 My Referrals",
        "top_referrers": "🏆 Top Referrers",
        "share_bot": "📢 Share Bot",
        "public_stats": "📊 Bot Statistics",
        "notif_on": "🔔 Disable Notifications",
        "notif_off": "🔕 Enable Notifications",
        "premium": "⭐ Premium",
        "settings": "🔄 Change Settings",
        "choose": "✅ Choose what you want:"
    },
    "Русский 🇷🇺": {
        "weather": "🌤 Погода сейчас",
        "forecast": "📅 Прогноз на 3 дня",
        "news": "📰 Последние новости",
        "all_news": "📰 Все новости",
        "mena_politics": "📰 Ближний Восток",
        "trending": "🔥 В тренде",
        "sports": "⚽ Спортивные новости",
        "daily_summary": "📋 Сводка дня",
        "weekly_summary": "📆 Недельный итог",
        "news_cats": "🗂 Категории новостей",
        "currency": "💱 Курсы валют",
        "dollar_parallel": "💵 Параллельный доллар",
        "convert": "🔄 Конвертер валют",
        "crypto": "💎 Криптовалюты",
        "track_asset": "📌 Отслеживать актив",
        "prayer": "🕌 Время намаза",
        "search": "🔍 Поиск новостей",
        "my_stats": "📈 Моя статистика",
        "referral": "🎁 Мои приглашения",
        "top_referrers": "🏆 Лучшие",
        "share_bot": "📢 Поделиться ботом",
        "public_stats": "📊 Статистика бота",
        "notif_on": "🔔 Отключить уведомления",
        "notif_off": "🔕 Включить уведомления",
        "premium": "⭐ Премиум",
        "settings": "🔄 Изменить настройки",
        "choose": "✅ Выберите:"
    },
    "فارسی 🇮🇷": {
        "weather": "🌤 آبوهوا",
        "forecast": "📅 پیشبینی ۳ روزه",
        "news": "📰 آخرین اخبار",
        "all_news": "📰 ارسال همه اخبار",
        "mena_politics": "📰 اخبار خاورمیانه",
        "trending": "🔥 پرتداولترین",
        "sports": "⚽ اخبار ورزشی",
        "daily_summary": "📋 خلاصه اخبار امروز",
        "weekly_summary": "📆 خلاصه هفتگی",
        "news_cats": "🗂 دستهبندی اخبار",
        "currency": "💱 نرخ ارز",
        "dollar_parallel": "💵 دلار موازی",
        "convert": "🔄 تبدیل ارز",
        "crypto": "💎 ارز دیجیتال",
        "track_asset": "📌 پیگیری دارایی",
        "prayer": "🕌 اوقات نماز",
        "search": "🔍 جستجوی اخبار",
        "my_stats": "📈 آمار من",
        "referral": "🎁 دعوتهایم",
        "top_referrers": "🏆 برترینها",
        "share_bot": "📢 اشتراکگذاری ربات",
        "public_stats": "📊 آمار ربات",
        "notif_on": "🔔 غیرفعالکردن اعلانها",
        "notif_off": "🔕 فعالکردن اعلانها",
        "premium": "⭐ ویژه",
        "settings": "🔄 تغییر تنظیمات",
        "choose": "✅ انتخاب کنید:"
    },
    "हिन्दी 🇮🇳": {
        "weather": "🌤 मौसम अभी",
        "forecast": "📅 3-दिन का पूर्वानुमान",
        "news": "📰 ताज़ा खबरें",
        "all_news": "📰 सभी खबरें भेजें",
        "mena_politics": "📰 मध्य पूर्व समाचार",
        "trending": "🔥 ट्रेंडिंग",
        "sports": "⚽ खेल समाचार",
        "daily_summary": "📋 आज की खबर सारांश",
        "weekly_summary": "📆 साप्ताहिक सारांश",
        "news_cats": "🗂 समाचार श्रेणियाँ",
        "currency": "💱 मुद्रा दरें",
        "dollar_parallel": "💵 Parallel Dollar",
        "convert": "🔄 मुद्रा परिवर्तक",
        "crypto": "💎 क्रिप्टो कीमतें",
        "track_asset": "📌 Asset Track",
        "prayer": "🕌 नमाज़ के वक्त",
        "search": "🔍 खबर खोजें",
        "my_stats": "📈 मेरे आँकड़े",
        "referral": "🎁 मेरे रेफरल",
        "top_referrers": "🏆 शीर्ष",
        "share_bot": "📢 बॉट शेयर करें",
        "public_stats": "📊 बॉट आँकड़े",
        "notif_on": "🔔 सूचनाएं बंद करें",
        "notif_off": "🔕 सूचनाएं चालू करें",
        "premium": "⭐ प्रीमियम",
        "settings": "🔄 सेटिंग बदलें",
        "choose": "✅ चुनें:"
    },
    "Português 🇧🇷": {
        "weather": "🌤 Clima agora",
        "forecast": "📅 Previsão 3 dias",
        "news": "📰 Últimas notícias",
        "all_news": "📰 Enviar todas notícias",
        "mena_politics": "📰 Oriente Médio",
        "trending": "🔥 Em alta",
        "sports": "⚽ Esportes",
        "daily_summary": "📋 Resumo do dia",
        "weekly_summary": "📆 Resumo semanal",
        "news_cats": "🗂 Categorias de notícias",
        "currency": "💱 Taxas de câmbio",
        "dollar_parallel": "💵 Dólar paralelo",
        "convert": "🔄 Conversor de moeda",
        "crypto": "💎 Criptomoedas",
        "track_asset": "📌 Monitorar ativo",
        "prayer": "🕌 Horários de oração",
        "search": "🔍 Buscar notícias",
        "my_stats": "📈 Minhas estatísticas",
        "referral": "🎁 Minhas indicações",
        "top_referrers": "🏆 Melhores",
        "share_bot": "📢 Compartilhar bot",
        "public_stats": "📊 Estatísticas",
        "notif_on": "🔔 Desativar notificações",
        "notif_off": "🔕 Ativar notificações",
        "premium": "⭐ Premium",
        "settings": "🔄 Mudar configurações",
        "choose": "✅ Escolha:"
    },
    "Türkçe 🇹🇷": {
        "weather": "🌤 Hava durumu",
        "forecast": "📅 3 Günlük Tahmin",
        "news": "📰 Son haberler",
        "all_news": "📰 Tüm haberleri gönder",
        "mena_politics": "📰 Orta Doğu",
        "trending": "🔥 Trend haberler",
        "sports": "⚽ Spor haberleri",
        "daily_summary": "📋 Günlük özet",
        "weekly_summary": "📆 Haftalık özet",
        "news_cats": "🗂 Haber kategorileri",
        "currency": "💱 Döviz kurları",
        "dollar_parallel": "💵 Paralel dolar",
        "convert": "🔄 Döviz çevirici",
        "crypto": "💎 Kripto fiyatları",
        "track_asset": "📌 Varlık takibi",
        "prayer": "🕌 Namaz vakitleri",
        "search": "🔍 Haber ara",
        "my_stats": "📈 İstatistiklerim",
        "referral": "🎁 Davetlerim",
        "top_referrers": "🏆 En İyiler",
        "share_bot": "📢 Botu paylaş",
        "public_stats": "📊 Bot istatistikleri",
        "notif_on": "🔔 Bildirimleri kapat",
        "notif_off": "🔕 Bildirimleri aç",
        "premium": "⭐ Premium",
        "settings": "🔄 Ayarları değiştir",
        "choose": "✅ Seçin:"
    },
    "اردو 🇵🇰": {
        "weather": "🌤 موسم ابھی",
        "forecast": "📅 3 دن کی پیشگوئی",
        "news": "📰 تازہ خبریں",
        "all_news": "📰 تمام خبریں بھیجیں",
        "mena_politics": "📰 مشرق وسطی خبریں",
        "trending": "🔥 ٹرینڈنگ خبریں",
        "sports": "⚽ کھیل کی خبریں",
        "daily_summary": "📋 آج کا خلاصہ",
        "weekly_summary": "📆 ہفتہ وار خلاصہ",
        "news_cats": "🗂 خبروں کی اقسام",
        "currency": "💱 کرنسی ریٹ",
        "dollar_parallel": "💵 پیرالل ڈالر",
        "convert": "🔄 کرنسی کنورٹر",
        "crypto": "💎 کرپٹو قیمتیں",
        "track_asset": "📌 اثاثہ ٹریک",
        "prayer": "🕌 نماز کے اوقات",
        "search": "🔍 خبریں تلاش کریں",
        "my_stats": "📈 میرے اعداد",
        "referral": "🎁 میری دعوتیں",
        "top_referrers": "🏆 بہترین",
        "share_bot": "📢 بوٹ شیئر کریں",
        "public_stats": "📊 بوٹ اعداد",
        "notif_on": "🔔 اطلاعات بند کریں",
        "notif_off": "🔕 اطلاعات چالو کریں",
        "premium": "⭐ پریمیم",
        "settings": "🔄 ترتیبات بدلیں",
        "choose": "✅ انتخاب کریں:"
    },
    "Deutsch 🇩🇪": {
        "weather": "🌤 Wetter jetzt",
        "forecast": "📅 3-Tage-Prognose",
        "news": "📰 Neueste Nachrichten",
        "all_news": "📰 Alle Nachrichten",
        "mena_politics": "📰 Nahost-Nachrichten",
        "trending": "🔥 Trending",
        "sports": "⚽ Sportnachrichten",
        "daily_summary": "📋 Tageszusammenfassung",
        "weekly_summary": "📆 Wochenzusammenfassung",
        "news_cats": "🗂 Nachrichtenkategorien",
        "currency": "💱 Wechselkurse",
        "dollar_parallel": "💵 Parallelkurs Dollar",
        "convert": "🔄 Währungsrechner",
        "crypto": "💎 Kryptowährungen",
        "track_asset": "📌 Asset verfolgen",
        "prayer": "🕌 Gebetszeiten",
        "search": "🔍 Nachrichten suchen",
        "my_stats": "📈 Meine Statistiken",
        "referral": "🎁 Meine Einladungen",
        "top_referrers": "🏆 Beste",
        "share_bot": "📢 Bot teilen",
        "public_stats": "📊 Bot-Statistiken",
        "notif_on": "🔔 Benachrichtigungen aus",
        "notif_off": "🔕 Benachrichtigungen ein",
        "premium": "⭐ Premium",
        "settings": "🔄 Einstellungen ändern",
        "choose": "✅ Wählen Sie:"
    },
    "Українська 🇺🇦": {
        "weather": "🌤 Погода зараз",
        "forecast": "📅 Прогноз на 3 дні",
        "news": "📰 Останні новини",
        "all_news": "📰 Всі новини",
        "mena_politics": "📰 Близький Схід",
        "trending": "🔥 Тренди",
        "sports": "⚽ Спортивні новини",
        "daily_summary": "📋 Зведення дня",
        "weekly_summary": "📆 Тижневий підсумок",
        "news_cats": "🗂 Категорії новин",
        "currency": "💱 Курси валют",
        "dollar_parallel": "💵 Паралельний долар",
        "convert": "🔄 Конвертер валют",
        "crypto": "💎 Криптовалюти",
        "track_asset": "📌 Стежити за активом",
        "prayer": "🕌 Час молитви",
        "search": "🔍 Пошук новин",
        "my_stats": "📈 Моя статистика",
        "referral": "🎁 Мої запрошення",
        "top_referrers": "🏆 Найкращі",
        "share_bot": "📢 Поділитися ботом",
        "public_stats": "📊 Статистика",
        "notif_on": "🔔 Вимкнути сповіщення",
        "notif_off": "🔕 Увімкнути сповіщення",
        "premium": "⭐ Преміум",
        "settings": "🔄 Змінити налаштування",
        "choose": "✅ Оберіть:"
    },
    "Italiano 🇮🇹": {
        "weather": "🌤 Meteo ora",
        "forecast": "📅 Previsioni 3 giorni",
        "news": "📰 Ultime notizie",
        "all_news": "📰 Tutte le notizie",
        "mena_politics": "📰 Medio Oriente",
        "trending": "🔥 Notizie di tendenza",
        "sports": "⚽ Notizie sportive",
        "daily_summary": "📋 Riepilogo del giorno",
        "weekly_summary": "📆 Riepilogo settimanale",
        "news_cats": "🗂 Categorie notizie",
        "currency": "💱 Tassi di cambio",
        "dollar_parallel": "💵 Dollaro parallelo",
        "convert": "🔄 Convertitore valuta",
        "crypto": "💎 Criptovalute",
        "track_asset": "📌 Traccia attivo",
        "prayer": "🕌 Orari di preghiera",
        "search": "🔍 Cerca notizie",
        "my_stats": "📈 Le mie statistiche",
        "referral": "🎁 I miei inviti",
        "top_referrers": "🏆 I migliori",
        "share_bot": "📢 Condividi bot",
        "public_stats": "📊 Statistiche bot",
        "notif_on": "🔔 Disattiva notifiche",
        "notif_off": "🔕 Attiva notifiche",
        "premium": "⭐ Premium",
        "settings": "🔄 Cambia impostazioni",
        "choose": "✅ Scegli:"
    },
    "Español 🇲🇽": {
        "weather": "🌤 Clima ahora",
        "forecast": "📅 Pronóstico 3 días",
        "news": "📰 Últimas noticias",
        "all_news": "📰 Todas las noticias",
        "mena_politics": "📰 Oriente Medio",
        "trending": "🔥 Tendencias",
        "sports": "⚽ Noticias deportivas",
        "daily_summary": "📋 Resumen del día",
        "weekly_summary": "📆 Resumen semanal",
        "news_cats": "🗂 Categorías de noticias",
        "currency": "💱 Tipos de cambio",
        "dollar_parallel": "💵 Dólar paralelo",
        "convert": "🔄 Conversor de divisas",
        "crypto": "💎 Criptomonedas",
        "track_asset": "📌 Rastrear activo",
        "prayer": "🕌 Horarios de oración",
        "search": "🔍 Buscar noticias",
        "my_stats": "📈 Mis estadísticas",
        "referral": "🎁 Mis invitaciones",
        "top_referrers": "🏆 Mejores",
        "share_bot": "📢 Compartir bot",
        "public_stats": "📊 Estadísticas",
        "notif_on": "🔔 Desactivar notificaciones",
        "notif_off": "🔕 Activar notificaciones",
        "premium": "⭐ Premium",
        "settings": "🔄 Cambiar configuración",
        "choose": "✅ Elige lo que quieres:"
    },
}

# ======== رسائل الترقية للمميز ========
PREMIUM_UPGRADE_MSG = {
    "العربية 🇮🇶": (
        "⭐ *الاشتراك المميز*\n\n"
        "احصل على مميزات حصرية:\n\n"
        "🌤 توقعات الطقس لـ 7 أيام\n"
        "🏙 إضافة أكثر من مدينة\n"
        "📌 أخبار حسب اهتماماتك\n"
        "⚡ أخبار عاجلة فورية كل 15 دقيقة\n"
        "🌅 ملخص صباحي يومي\n"
        "💱 تنبيه عند تغير سعر العملة\n"
        "🌧 تنبيه تغيرات الطقس\n"
        "🕐 اختيار وقت الإشعارات\n\n"
        "للاشتراك اضغط الزر أدناه 👇"
    ),
    "English 🇬🇧": (
        "⭐ *Premium Subscription*\n\n"
        "Get exclusive features:\n\n"
        "🌤 7-day weather forecast\n"
        "🏙 Add multiple cities\n"
        "📌 News by your interests\n"
        "⚡ Instant breaking news every 15 min\n"
        "🌅 Daily morning summary\n"
        "💱 Currency rate alerts\n"
        "🌧 Weather change alerts\n"
        "🕐 Choose your notification time\n\n"
        "Press the button below to subscribe 👇"
    ),
    "Русский 🇷🇺": (
        "⭐ *Премиум подписка*\n\n"
        "Получите эксклюзивные функции:\n\n"
        "🌤 Прогноз погоды на 7 дней\n"
        "🏙 Добавить несколько городов\n"
        "📌 Новости по интересам\n"
        "⚡ Срочные новости каждые 15 минут\n"
        "🌅 Утренние сводки\n"
        "💱 Оповещения о курсе валют\n"
        "🌧 Оповещения о погоде\n"
        "🕐 Выбор времени уведомлений\n\n"
        "Нажмите кнопку ниже 👇"
    ),
    "فارسی 🇮🇷": (
        "⭐ *اشتراک ویژه*\n\n"
        "امکانات انحصاری:\n\n"
        "🌤 پیشبینی آبوهوا برای ۷ روز\n"
        "🏙 افزودن چند شهر\n"
        "📌 اخبار بر اساس علایق\n"
        "⚡ اخبار فوری هر ۱۵ دقیقه\n"
        "🌅 خلاصه صبحگاهی\n"
        "💱 هشدار نرخ ارز\n"
        "🌧 هشدار تغییرات آبوهوا\n"
        "🕐 انتخاب زمان اطلاعرسانی\n\n"
        "برای اشتراک دکمه زیر را بزنید 👇"
    ),
    "हिन्दी 🇮🇳": (
        "⭐ *प्रीमियम सदस्यता*\n\n"
        "विशेष सुविधाएं:\n\n"
        "🌤 7 दिनों का मौसम पूर्वानुमान\n"
        "🏙 कई शहर जोड़ें\n"
        "📌 आपकी रुचि की खबरें\n"
        "⚡ हर 15 मिनट में ताज़ा खबरें\n"
        "🌅 सुबह का सारांश\n"
        "💱 मुद्रा दर अलर्ट\n"
        "🌧 मौसम परिवर्तन अलर्ट\n"
        "🕐 अधिसूचना समय चुनें\n\n"
        "सदस्यता के लिए नीचे बटन दबाएं 👇"
    ),
    "Português 🇧🇷": (
        "⭐ *Assinatura Premium*\n\n"
        "Recursos exclusivos:\n\n"
        "🌤 Previsão do tempo por 7 dias\n"
        "🏙 Adicionar várias cidades\n"
        "📌 Notícias por seus interesses\n"
        "⚡ Últimas notícias a cada 15 min\n"
        "🌅 Resumo matinal diário\n"
        "💱 Alertas de câmbio\n"
        "🌧 Alertas de clima\n"
        "🕐 Escolha o horário de notificações\n\n"
        "Pressione o botão abaixo 👇"
    ),
    "Türkçe 🇹🇷": (
        "⭐ *Premium Üyelik*\n\n"
        "Özel özellikler:\n\n"
        "🌤 7 günlük hava durumu tahmini\n"
        "🏙 Birden fazla şehir ekle\n"
        "📌 İlgi alanına göre haberler\n"
        "⚡ Her 15 dakikada son dakika haberleri\n"
        "🌅 Günlük sabah özeti\n"
        "💱 Döviz kuru uyarıları\n"
        "🌧 Hava durumu uyarıları\n"
        "🕐 Bildirim saatini seç\n\n"
        "Abone olmak için aşağıdaki butona bas 👇"
    ),
    "اردو 🇵🇰": (
        "⭐ *پریمیم سبسکرپشن*\n\n"
        "خصوصی خصوصیات:\n\n"
        "🌤 7 دن کی موسم کی پیش گوئی\n"
        "🏙 متعدد شہر شامل کریں\n"
        "📌 آپ کی دلچسپی کی خبریں\n"
        "⚡ ہر 15 منٹ میں تازہ ترین خبریں\n"
        "🌅 روزانہ صبح کا خلاصہ\n"
        "💱 کرنسی ریٹ الرٹ\n"
        "🌧 موسم تبدیلی الرٹ\n"
        "🕐 اطلاع کا وقت منتخب کریں\n\n"
        "سبسکرائب کرنے کے لیے نیچے بٹن دبائیں 👇"
    ),
    "Deutsch 🇩🇪": (
        "⭐ *Premium-Abonnement*\n\n"
        "Exklusive Funktionen:\n\n"
        "🌤 7-Tage-Wettervorhersage\n"
        "🏙 Mehrere Städte hinzufügen\n"
        "📌 Nachrichten nach Interessen\n"
        "⚡ Breaking News alle 15 Minuten\n"
        "🌅 Tägliche Morgenzusammenfassung\n"
        "💱 Wechselkurs-Benachrichtigungen\n"
        "🌧 Wetterwarnungen\n"
        "🕐 Benachrichtigungszeit wählen\n\n"
        "Drücken Sie die Schaltfläche unten 👇"
    ),
    "Українська 🇺🇦": (
        "⭐ *Преміум підписка*\n\n"
        "Ексклюзивні функції:\n\n"
        "🌤 Прогноз погоди на 7 днів\n"
        "🏙 Додати кілька міст\n"
        "📌 Новини за інтересами\n"
        "⚡ Термінові новини кожні 15 хвилин\n"
        "🌅 Ранкова зведення\n"
        "💱 Сповіщення про курс валют\n"
        "🌧 Погодні попередження\n"
        "🕐 Вибір часу сповіщень\n\n"
        "Натисніть кнопку нижче 👇"
    ),
    "Italiano 🇮🇹": (
        "⭐ *Abbonamento Premium*\n\n"
        "Funzionalità esclusive:\n\n"
        "🌤 Previsioni meteo per 7 giorni\n"
        "🏙 Aggiungi più città\n"
        "📌 Notizie per i tuoi interessi\n"
        "⚡ Ultime notizie ogni 15 minuti\n"
        "🌅 Riassunto mattutino\n"
        "💱 Avvisi sul tasso di cambio\n"
        "🌧 Avvisi meteo\n"
        "🕐 Scegli l'orario delle notifiche\n\n"
        "Premi il pulsante qui sotto 👇"
    ),
    "Español 🇲🇽": (
        "⭐ *Suscripción Premium*\n\n"
        "Funciones exclusivas:\n\n"
        "🌤 Pronóstico del tiempo por 7 días\n"
        "🏙 Agregar varias ciudades\n"
        "📌 Noticias según tus intereses\n"
        "⚡ Últimas noticias cada 15 minutos\n"
        "🌅 Resumen matutino diario\n"
        "💱 Alertas de tipo de cambio\n"
        "🌧 Alertas meteorológicas\n"
        "🕐 Elige el horario de notificaciones\n\n"
        "Presiona el botón de abajo 👇"
    ),
}

# ======== الاهتمامات والكلمات المفتاحية ========
INTERESTS = {
    "العربية 🇮🇶": [
        "📰 سياسة", "💰 اقتصاد", "⚽ رياضة", "💻 تكنولوجيا",
        "🌍 أخبار العالم", "🚗 سيارات", "🏥 صحة",
        "🎬 فن وثقافة", "✈️ سفر وسياحة", "🔬 علوم", "🎲 منوعات"
    ],
    "English 🇬🇧": [
        "📰 Politics", "💰 Economy", "⚽ Sports", "💻 Technology",
        "🌍 World News", "🚗 Automotive", "🏥 Health",
        "🎬 Arts & Culture", "✈️ Travel", "🔬 Science", "🎲 Entertainment"
    ],
    "Русский 🇷🇺": [
        "📰 Политика", "💰 Экономика", "⚽ Спорт", "💻 Технологии",
        "🌍 Мировые новости", "🚗 Авто", "🏥 Здоровье",
        "🎬 Культура", "✈️ Путешествия", "🔬 Наука", "🎲 Развлечения"
    ],
    "فارسی 🇮🇷": [
        "📰 سیاست", "💰 اقتصاد", "⚽ ورزش", "💻 فناوری",
        "🌍 اخبار جهان", "🚗 خودرو", "🏥 سلامت",
        "🎬 هنر و فرهنگ", "✈️ سفر", "🔬 علوم", "🎲 سرگرمی"
    ],
    "हिन्दी 🇮🇳": [
        "📰 राजनीति", "💰 अर्थव्यवस्था", "⚽ खेल", "💻 प्रौद्योगिकी",
        "🌍 विश्व समाचार", "🚗 ऑटो", "🏥 स्वास्थ्य",
        "🎬 कला और संस्कृति", "✈️ यात्रा", "🔬 विज्ञान", "🎲 मनोरंजन"
    ],
    "Português 🇧🇷": [
        "📰 Política", "💰 Economia", "⚽ Esporte", "💻 Tecnologia",
        "🌍 Mundo", "🚗 Automóveis", "🏥 Saúde",
        "🎬 Arte e Cultura", "✈️ Viagem", "🔬 Ciência", "🎲 Entretenimento"
    ],
    "Türkçe 🇹🇷": [
        "📰 Siyaset", "💰 Ekonomi", "⚽ Spor", "💻 Teknoloji",
        "🌍 Dünya", "🚗 Otomotiv", "🏥 Sağlık",
        "🎬 Sanat ve Kültür", "✈️ Seyahat", "🔬 Bilim", "🎲 Eğlence"
    ],
    "اردو 🇵🇰": [
        "📰 سیاست", "💰 معیشت", "⚽ کھیل", "💻 ٹیکنالوجی",
        "🌍 عالمی خبریں", "🚗 آٹو", "🏥 صحت",
        "🎬 فن و ثقافت", "✈️ سفر", "🔬 سائنس", "🎲 تفریح"
    ],
    "Deutsch 🇩🇪": [
        "📰 Politik", "💰 Wirtschaft", "⚽ Sport", "💻 Technologie",
        "🌍 Welt", "🚗 Auto", "🏥 Gesundheit",
        "🎬 Kunst & Kultur", "✈️ Reisen", "🔬 Wissenschaft", "🎲 Unterhaltung"
    ],
    "Українська 🇺🇦": [
        "📰 Політика", "💰 Економіка", "⚽ Спорт", "💻 Технології",
        "🌍 Світ", "🚗 Авто", "🏥 Здоров'я",
        "🎬 Культура", "✈️ Подорожі", "🔬 Наука", "🎲 Розваги"
    ],
    "Italiano 🇮🇹": [
        "📰 Politica", "💰 Economia", "⚽ Sport", "💻 Tecnologia",
        "🌍 Mondo", "🚗 Auto", "🏥 Salute",
        "🎬 Arte e Cultura", "✈️ Viaggi", "🔬 Scienza", "🎲 Intrattenimento"
    ],
    "Español 🇲🇽": [
        "📰 Política", "💰 Economía", "⚽ Deporte", "💻 Tecnología",
        "🌍 Mundo", "🚗 Automóviles", "🏥 Salud",
        "🎬 Arte y Cultura", "✈️ Viajes", "🔬 Ciencia", "🎲 Entretenimiento"
    ],
}

INTEREST_KEYWORDS = {
    "سياسة": ["سياسة", "حكومة", "رئيس", "وزير", "برلمان", "انتخاب", "حزب", "قرار", "مجلس"],
    "اقتصاد": ["اقتصاد", "نفط", "دولار", "تجارة", "بنك", "مال", "بورصة", "سوق", "ميزانية", "استثمار"],
    "رياضة": ["رياضة", "كرة", "مباراة", "بطولة", "لاعب", "فريق", "هدف", "ملعب", "منتخب", "دوري"],
    "تكنولوجيا": ["تقنية", "تكنولوجيا", "ذكاء اصطناعي", "هاتف", "إنترنت", "تطبيق", "برنامج", "شركة تقنية"],
    "أخبار العالم": ["عالم", "دولي", "أمريكا", "أوروبا", "آسيا", "أفريقيا", "خارجية", "ناتو", "أمم متحدة"],
    "سيارات": ["سيارة", "سيارات", "مركبة", "سباق", "محرك", "كهربائية", "وقود", "أوتوماتيك"],
    "صحة": ["صحة", "مستشفى", "طبيب", "علاج", "مرض", "لقاح", "وباء", "دواء", "جراحة"],
    "فن وثقافة": ["فن", "ثقافة", "فيلم", "مسلسل", "موسيقى", "مهرجان", "معرض", "روائي", "شاعر", "فنان"],
    "سفر وسياحة": ["سفر", "سياحة", "رحلة", "فندق", "مطار", "وجهة", "سياحي", "جواز", "تأشيرة"],
    "علوم": ["علوم", "بحث", "اكتشاف", "فضاء", "ناسا", "كواكب", "تجربة", "دراسة", "باحثون"],
    "منوعات": ["منوعات", "طريف", "غريب", "عجيب", "حيوان", "طبيعة", "بيئة", "مناخ"],
    "politics": ["politics", "government", "president", "minister", "parliament", "election", "policy"],
    "economy": ["economy", "oil", "dollar", "trade", "bank", "finance", "market", "stock", "budget"],
    "sports": ["sport", "football", "match", "tournament", "player", "team", "goal", "league"],
    "technology": ["tech", "ai", "artificial intelligence", "internet", "app", "software", "phone", "digital"],
    "world news": ["world", "international", "global", "united nations", "nato", "foreign", "crisis"],
    "automotive": ["car", "vehicle", "automotive", "electric vehicle", "motor", "race", "fuel"],
    "health": ["health", "hospital", "doctor", "treatment", "disease", "vaccine", "medicine", "surgery"],
    "arts & culture": ["art", "culture", "film", "movie", "music", "festival", "exhibition", "artist"],
    "travel": ["travel", "tourism", "trip", "hotel", "airport", "destination", "visa", "flight"],
    "science": ["science", "research", "discovery", "space", "nasa", "planet", "experiment", "study"],
    "entertainment": ["entertainment", "celebrity", "viral", "funny", "trend", "social media"],
    "спорт": ["спорт", "футбол", "матч", "турнир", "игрок", "команда", "гол", "лига"],
    "экономика": ["экономика", "нефть", "доллар", "торговля", "банк", "рынок", "бюджет"],
    "технологии": ["технологии", "ии", "интернет", "приложение", "программа", "цифровой"],
    "политика": ["политика", "правительство", "президент", "министр", "парламент", "выборы"],
    "мировые новости": ["мир", "международный", "глобальный", "нато", "оон"],
    "авто": ["автомобиль", "машина", "гонки", "двигатель", "электромобиль"],
    "здоровье": ["здоровье", "больница", "врач", "лечение", "болезнь", "вакцина"],
    "культура": ["культура", "искусство", "фильм", "музыка", "фестиваль"],
    "путешествия": ["путешествие", "туризм", "отель", "аэропорт", "виза"],
    "наука": ["наука", "исследование", "открытие", "космос", "эксперимент"],
    "развлечения": ["развлечение", "знаменитость", "вирусный", "юмор"],
    "ورزش": ["ورزش", "فوتبال", "مسابقه", "تیم", "بازیکن", "لیگ"],
    "اقتصاد_fa": ["اقتصاد", "نفت", "دلار", "تجارت", "بانک", "بازار"],
    "فناوری": ["فناوری", "هوش مصنوعی", "اینترنت", "نرمافزار", "دیجیتال"],
    "سیاست": ["سیاست", "دولت", "رئیس جمهور", "وزیر", "مجلس", "انتخابات"],
    "اخبار جهان": ["جهان", "بینالملل", "ناتو", "سازمان ملل"],
    "خودرو": ["خودرو", "ماشین", "برقی", "موتور", "مسابقه"],
    "سلامت": ["سلامت", "بیمارستان", "پزشک", "درمان", "بیماری", "واکسن"],
    "هنر و فرهنگ": ["هنر", "فرهنگ", "فیلم", "موسیقی", "جشنواره"],
    "سفر": ["سفر", "گردشگری", "هتل", "فرودگاه", "ویزا"],
    "علوم_fa": ["علوم", "تحقیق", "کشف", "فضا", "آزمایش"],
    "سرگرمی": ["سرگرمی", "مشهور", "ویروسی", "طنز"],
    "spor": ["spor", "futbol", "maç", "turnuva", "oyuncu", "takım", "gol", "lig"],
    "ekonomi": ["ekonomi", "petrol", "dolar", "ticaret", "banka", "piyasa", "bütçe"],
    "teknoloji": ["teknoloji", "yapay zeka", "internet", "uygulama", "yazılım"],
    "siyaset": ["siyaset", "hükümet", "cumhurbaşkanı", "bakan", "meclis", "seçim"],
    "dünya": ["dünya", "uluslararası", "nato", "bm", "küresel"],
    "otomotiv": ["araba", "otomobil", "elektrikli", "motor", "yarış"],
    "sağlık": ["sağlık", "hastane", "doktor", "tedavi", "hastalık", "aşı"],
    "sanat ve kültür": ["sanat", "kültür", "film", "müzik", "festival"],
    "seyahat": ["seyahat", "turizm", "otel", "havalimanı", "vize"],
    "bilim": ["bilim", "araştırma", "keşif", "uzay", "deney"],
    "eğlence": ["eğlence", "ünlü", "viral", "komedi"],
    "sport_de": ["sport", "fußball", "spiel", "turnier", "spieler", "mannschaft", "liga"],
    "wirtschaft": ["wirtschaft", "öl", "dollar", "handel", "bank", "markt", "budget"],
    "technologie": ["technologie", "ki", "internet", "app", "software", "digital"],
    "politik": ["politik", "regierung", "präsident", "minister", "parlament", "wahl"],
    "welt": ["welt", "international", "global", "nato", "un"],
    "auto": ["auto", "fahrzeug", "elektroauto", "motor", "rennen"],
    "gesundheit": ["gesundheit", "krankenhaus", "arzt", "behandlung", "krankheit", "impfstoff"],
    "kunst & kultur": ["kunst", "kultur", "film", "musik", "festival"],
    "reisen": ["reisen", "tourismus", "hotel", "flughafen", "visum"],
    "wissenschaft": ["wissenschaft", "forschung", "entdeckung", "weltraum", "experiment"],
    "unterhaltung": ["unterhaltung", "promi", "viral", "humor"],
}

# ======== العملات حسب اللغة ========
CURRENCY_MAP = {
    "العربية 🇮🇶": ("IQD", "الدينار العراقي 🇮🇶"),
    "English 🇬🇧": ("GBP", "British Pound 🇬🇧"),
    "Русский 🇷🇺": ("RUB", "Российский рубль 🇷🇺"),
    "فارسی 🇮🇷": ("IRR", "ریال ایرانی 🇮🇷"),
    "हिन्दी 🇮🇳": ("INR", "Indian Rupee 🇮🇳"),
    "Português 🇧🇷": ("BRL", "Real Brasileiro 🇧🇷"),
    "Türkçe 🇹🇷": ("TRY", "Türk Lirası 🇹🇷"),
    "اردو 🇵🇰": ("PKR", "Pakistani Rupee 🇵🇰"),
    "Deutsch 🇩🇪": ("EUR", "Euro 🇩🇪"),
    "Українська 🇺🇦": ("UAH", "Українська гривня 🇺🇦"),
    "Italiano 🇮🇹": ("EUR", "Euro 🇮🇹"),
    "Español 🇲🇽": ("MXN", "Peso Mexicano 🇲🇽"),
}

# ======== مصادر MENA ========
MENA_RSS = {
    "العربية 🇮🇶": [
        "https://www.alsumaria.tv/rss/latest-news",
        "https://shafaq.com/ar/rss.xml",
        "https://www.rudaw.net/arabic/rss",
        "https://www.almaalomah.com/feed/",
        "https://almada-paper.com/feed/",
        "https://www.alarabiya.net/.mrss/ar/0/0/0.xml",
        "https://www.aljazeera.net/aljazeera/feeds/rss.xml",
        "https://feeds.skynewsarabia.com/web/rss/2",
        "https://arabic.rt.com/rss/",
        "https://www.bbc.com/arabic/index.xml",
        "https://www.independentarabia.com/rss.xml",
        "https://rss.almasryalyoum.com/rss.xml",
        "https://arabi21.com/rss.xml",
        "https://www.elnashra.com/rss",
        "https://www.france24.com/ar/rss",
        "https://arabic.euronews.com/rss",
        "https://www.middleeasteye.net/ar/rss",
        "https://www.aawsat.com/rss.xml",
        "https://www.alquds.com/feed/",
        "https://www.alriyadh.com/tools/rss/rss.xml",
    ],
    "English 🇬🇧": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.middleeasteye.net/rss",
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://rss.cnn.com/rss/edition_world.rss",
    ],
    "Русский 🇷🇺": [
        "https://arabic.rt.com/rss/",
        "https://www.aljazeera.com/xml/rss/all.xml",
    ],
    "Türkçe 🇹🇷": [
        "https://www.aljazeera.com.tr/feed",
        "https://www.aa.com.tr/tr/rss/default",
    ],
    "Deutsch 🇩🇪": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.dw.com/rdf/rss-de-all",
    ],
    "Español 🇲🇽": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
    ],
    "Italiano 🇮🇹": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
    ],
    "فارسی 🇮🇷": [
        "https://www.radiofarda.com/api/zrqomtmopp",
        "https://www.bbc.com/persian/index.xml",
    ],
    "हिन्दी 🇮🇳": [
        "https://feeds.bbci.co.uk/hindi/rss.xml",
    ],
    "Português 🇧🇷": [
        "https://feeds.bbci.co.uk/portuguese/rss.xml",
    ],
    "اردو 🇵🇰": [
        "https://feeds.bbci.co.uk/urdu/rss.xml",
        "https://www.geo.tv/rss",
    ],
    "Українська 🇺🇦": [
        "https://feeds.bbci.co.uk/ukrainian/rss.xml",
    ],
}

# ======== كلمات مفتاحية للشرق الأوسط (fallback) ========
MENA_KEYWORDS = [
    "عراق", "سوريا", "لبنان", "فلسطين", "غزة", "إيران", "السعودية", "تركيا", "اليمن", "ليبيا",
    "مصر", "الأردن", "الخليج", "حماس", "حزب الله", "إسرائيل", "بغداد", "دمشق", "طهران",
    "iraq", "syria", "lebanon", "palestine", "gaza", "iran", "saudi", "turkey", "yemen", "libya",
    "egypt", "jordan", "gulf", "hamas", "hezbollah", "israel", "baghdad", "damascus", "tehran",
    "middle east", "الشرق الأوسط", "الخليج العربي", "القدس", "jerusalem"
]

# ======== حالة البحث ========
user_states = {}

# ======== إشعار الأدمن بالأخطاء ========
def notify_admin_error(msg):
    all_admins = [ADMIN_ID] + extra_admins
    for admin_id in all_admins:
        try:
            bot.send_message(admin_id, f"⚠️ *خطأ في البوت:*\n`{msg}`", parse_mode="Markdown")
        except:
            pass

# ======== تحديث الإحصائيات ========
def update_stats(action, uid=None, country=None, lang=None, button=None):
    today = str(datetime.date.today())
    if action == "new_user":
        stats["total_users"] = stats.get("total_users", 0) + 1
        stats["daily_users"][today] = stats["daily_users"].get(today, 0) + 1
        if lang:
            stats["languages_count"][lang] = stats["languages_count"].get(lang, 0) + 1
        if country:
            stats["countries_count"][country] = stats["countries_count"].get(country, 0) + 1
        total = stats["total_users"]
        if total in [100, 500, 1000, 5000, 10000]:
            all_admins = [ADMIN_ID] + extra_admins
            for admin_id in all_admins:
                try:
                    bot.send_message(admin_id, f"🎉 وصلت {total} مستخدم!")
                except:
                    pass
    elif action == "button":
        if button:
            stats["button_presses"][button] = stats["button_presses"].get(button, 0) + 1
    save_json(STATS_FILE, stats)

# ======== دوال المميز ========
def is_premium(uid):
    uid_int = int(uid)
    if uid_int in stats.get("premium_users", []):
        return True
    user = users.get(str(uid), {})
    expiry = user.get("ref_premium_expiry")
    if expiry:
        try:
            expiry_dt = datetime.datetime.fromisoformat(expiry)
            if datetime.datetime.now() < expiry_dt:
                return True
            else:
                users[str(uid)].pop("ref_premium_expiry", None)
        except:
            pass
    return False

def has_feature(uid, feature):
    if is_premium(uid):
        return True
    user = users.get(str(uid), {})
    return feature in user.get("unlocked_features", [])

# ======== ميزات الإحالة ========
REFERRAL_FEATURES = {
    "prem_7day":           "📅 توقعات طقس 7 أيام",
    "prem_hourly":         "⚡ أخبار فورية كل ساعة",
    "prem_addcity":        "🏙 إضافة مدينة إضافية",
    "prem_mycities":       "🗂 عرض مدنك المحفوظة",
    "prem_interests":      "🎯 أخبار حسب اهتماماتك",
    "prem_currency_alert": "💱 تنبيه سعر العملة",
    "prem_currency_table": "📊 جدول العملات الكامل",
    "prem_notif_time":     "🕐 وقت إشعار مخصص",
    "prem_weekly":         "📋 ملخص أسبوعي",
    "prem_keywords":       "🔑 تنبيه كلمات مفتاحية",
}
REFERRAL_MILESTONES = [5, 10, 15, 20, 25]

def check_referral_rewards(referrer_id, new_member_name=""):
    uid_str = str(referrer_id)
    user = users.get(uid_str)
    if not user:
        return
    ref_count = len(user.get("referrals", []))
    rewarded = user.setdefault("rewarded_milestones", [])
    for milestone in REFERRAL_MILESTONES:
        if ref_count >= milestone and milestone not in rewarded:
            rewarded.append(milestone)
            users[uid_str]["rewarded_milestones"] = rewarded
            _db_save_all_users(users)
            if milestone == 25:
                expiry = datetime.datetime.now() + datetime.timedelta(days=30)
                users[uid_str]["ref_premium_expiry"] = expiry.isoformat()
                _db_save_all_users(users)
                try:
                    bot.send_message(
                        referrer_id,
                        "🎊 *تهانينا! وصلت إلى 25 دعوة!*\n\n"
                        "🌟 حصلت على *اشتراك مميز كامل لمدة شهر* مجاناً!\n"
                        "━━━━━━━━━━━━━━\n"
                        "📅 الاشتراك ساري لمدة 30 يوم\n"
                        "✨ استمتع بجميع الميزات المميزة!",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            else:
                try:
                    bot.send_message(
                        referrer_id,
                        f"🎉 *تهانينا! وصلت إلى {milestone} دعوة!*\n\n"
                        f"🎁 ربحت *ميزة مميزة مجانية* — اختر الميزة التي تريدها:",
                        parse_mode="Markdown"
                    )
                    send_feature_choice_menu(referrer_id)
                except:
                    pass
            break

def send_feature_choice_menu(uid):
    user = users.get(str(uid), {})
    unlocked = user.get("unlocked_features", [])
    markup = types.InlineKeyboardMarkup(row_width=1)
    for feat_key, feat_name in REFERRAL_FEATURES.items():
        if feat_key not in unlocked:
            markup.add(types.InlineKeyboardButton(feat_name, callback_data=f"ref_feature_{feat_key}"))
    if not markup.keyboard:
        bot.send_message(uid, "✅ لقد فتحت جميع الميزات المتاحة بالفعل!")
        return
    bot.send_message(uid,
        "🎁 *اختر ميزة مميزة واحدة تريد فتحها:*\n"
        "━━━━━━━━━━━━━━\n"
        "الميزة المختارة ستكون متاحة لك دائماً مجاناً.",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ======== لوحة تحكم الأدمن ========
def admin_panel(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 المستخدمون", callback_data="admin_users"),
        types.InlineKeyboardButton("📢 إرسال رسالة للكل", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🚨 خبر عاجل مخصص", callback_data="admin_breaking_news"),
        types.InlineKeyboardButton("🔴 إيقاف/تشغيل البوت", callback_data="admin_pause"),
        types.InlineKeyboardButton("⏱ توقيت البث", callback_data="admin_interval"),
        types.InlineKeyboardButton("📡 إدارة RSS", callback_data="admin_rss"),
        types.InlineKeyboardButton("🚫 القائمة السوداء", callback_data="admin_blacklist"),
        types.InlineKeyboardButton("💰 المالية", callback_data="admin_finance"),
        types.InlineKeyboardButton("📖 عداد القراءة", callback_data="admin_read_stats"),
        types.InlineKeyboardButton("✏️ تغيير رسالة الترحيب", callback_data="admin_welcome"),
        types.InlineKeyboardButton("👑 إدارة الأدمن", callback_data="admin_manage_admins"),
        types.InlineKeyboardButton("📺 إدارة القنوات/المجموعات", callback_data="admin_channels"),
        types.InlineKeyboardButton("📈 إحصائيات القنوات", callback_data="admin_channel_stats"),
        types.InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="admin_search_user"),
        types.InlineKeyboardButton("✉️ رسالة لمستخدم", callback_data="admin_msg_user"),
        types.InlineKeyboardButton("📋 قائمة الأوامر", callback_data="admin_commands"),
        types.InlineKeyboardButton("✏️ شكل رسالة الخبر", callback_data="admin_news_format"),
        types.InlineKeyboardButton("💬 صندوق الرسائل", callback_data="admin_inbox"),
        types.InlineKeyboardButton("⭐ تقييمات المستخدمين", callback_data="admin_ratings"),
    )
    bot.send_message(uid, "👑 *لوحة تحكم الأدمن:*", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message.from_user.id):
        return
    admin_panel(message.from_user.id)

@bot.message_handler(commands=['help'])
def help_command(message):
    uid = message.from_user.id
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    help_texts = {
        "العربية 🇮🇶": "📖 *المساعدة*\n\n/start — بدء البوت\n/help — عرض المساعدة\n/stop — إيقاف الإشعارات",
        "English 🇬🇧": "📖 *Help*\n\n/start — Start the bot\n/help — Show help\n/stop — Stop notifications",
    }
    bot.send_message(uid, help_texts.get(lang, help_texts["English 🇬🇧"]), parse_mode="Markdown")

@bot.message_handler(commands=['stop'])
def stop_command(message):
    uid = message.from_user.id
    if str(uid) in users:
        users[str(uid)]["notifications"] = False
        _db_save_all_users(users)
    bot.send_message(uid, "🔕 تم إيقاف الإشعارات. أرسل /start للرجوع.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ref_feature_"))
def ref_feature_callback(call):
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)
    feat_key = data.replace("ref_feature_", "")
    if feat_key not in REFERRAL_FEATURES:
        return
    user = users.get(str(uid), {})
    unlocked = user.setdefault("unlocked_features", [])
    if feat_key in unlocked:
        bot.send_message(uid, "⚠️ هذه الميزة مفتوحة لديك بالفعل.")
        return
    unlocked.append(feat_key)
    users[str(uid)]["unlocked_features"] = unlocked
    _db_save_all_users(users)
    feat_name = REFERRAL_FEATURES[feat_key]
    bot.send_message(uid,
        f"✅ *تم فتح الميزة بنجاح!*\n\n"
        f"🎁 *{feat_name}*\n\n"
        f"يمكنك استخدامها الآن من قائمة ⭐ المميز",
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("prem_") or c.data.startswith("req_premium_") or c.data.startswith("interest_"))
def premium_callbacks(call):
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)

    if data.startswith("req_premium_"):
        requester_id = data.split("_")[-1]
        user = users.get(str(uid), {})
        name = user.get("name", "مجهول")
        lang = user.get("lang", "-")
        all_admins = [ADMIN_ID] + extra_admins
        for admin_id in all_admins:
            try:
                bot.send_message(admin_id,
                    f"⭐ *طلب اشتراك مميز*\n\n"
                    f"👤 الاسم: {name}\n"
                    f"🆔 ID: `{requester_id}`\n"
                    f"🗣 اللغة: {lang}\n\n"
                    f"لترقيته: /admin ← المستخدمون ← ترقية لمميز",
                    parse_mode="Markdown"
                )
            except:
                pass
        bot.send_message(uid, "✅ تم إرسال طلبك للإدارة. سيتم التواصل معك قريباً.")
        return

    if not has_feature(uid, data):
        ref_count = len(users.get(str(uid), {}).get("referrals", []))
        next_milestone = next((m for m in REFERRAL_MILESTONES if m > ref_count), None)
        remaining = (next_milestone - ref_count) if next_milestone else 0
        bot.send_message(uid,
            "⭐ *هذه الميزة للمشتركين المميزين فقط.*\n\n"
            "💡 *يمكنك الحصول عليها مجاناً:*\n"
            "• دعوة 5 أصدقاء ← ميزة مجانية\n"
            "• دعوة 10 أصدقاء ← ميزتان مجانيتان\n"
            "• دعوة 25 صديق ← اشتراك مميز كامل شهر!\n\n"
            + (f"📊 دعواتك: `{ref_count}` — تحتاج `{remaining}` دعوة للمكافأة القادمة\n\n" if next_milestone else f"📊 دعواتك: `{ref_count}`\n\n")
            + "🔗 رابط دعوتك في قائمة *دعواتي*",
            parse_mode="Markdown"
        )
        return

    if data == "prem_7day":
        send_7day_forecast(uid)

    elif data == "prem_addcity":
        msg = bot.send_message(uid, "🏙 أرسل اسم المدينة التي تريد إضافتها (بالإنجليزي):")
        bot.register_next_step_handler(msg, lambda m: add_extra_city(m.from_user.id, m.text.strip()))

    elif data == "prem_interests":
        send_interest_menu(uid)

    elif data == "prem_currency_alert":
        user = users.get(str(uid), {})
        lang = user.get("lang", "English 🇬🇧")
        local_code, local_name = CURRENCY_MAP.get(lang, ("EUR", "Euro"))
        msg = bot.send_message(uid, f"💱 أرسل السعر المستهدف للدولار مقابل {local_name}:\n(مثال: 1600)")
        bot.register_next_step_handler(msg, set_currency_alert_step)

    elif data == "prem_notif_time":
        msg = bot.send_message(uid, "🕐 أرسل الساعة التي تريد استلام الملخص الصباحي فيها (0-23):\n(مثال: 8 للساعة 8 صباحاً)")
        bot.register_next_step_handler(msg, set_notif_time_step)

    elif data == "prem_hourly":
        send_hourly_weather_forecast(uid)

    elif data == "prem_mycities":
        user = users.get(str(uid), {})
        cities = [user.get("province", "")] + user.get("extra_cities", [])
        cities = [c for c in cities if c]
        if not cities:
            bot.send_message(uid, "⚠️ لا توجد مدن محفوظة.")
        else:
            msg = "🏙 *مدنك المحفوظة:*\n\n"
            for i, city in enumerate(cities):
                label = "(رئيسية)" if i == 0 else ""
                msg += f"  {i+1}. {city} {label}\n"
            bot.send_message(uid, msg, parse_mode="Markdown")

    elif data == "prem_currency_table":
        send_full_currency_table(uid)

    elif data == "prem_weekly":
        send_weekly_news_summary(uid)

    elif data == "prem_keywords":
        kws = user_keywords.get(str(uid), [])
        if kws:
            kw_list = "\n".join(f"• {k}" for k in kws)
            bot.send_message(uid,
                f"🔑 *كلماتك المفتاحية الحالية:*\n{kw_list}\n\n"
                "أرسل كلمة جديدة لإضافتها أو أرسل 'حذف كلمة' لحذفها:",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(uid,
                "🔑 *تنبيه الكلمات المفتاحية*\n\n"
                "أرسل كلمات تريد تتبعها مفصولة بفاصلة:\n"
                "مثال: رواتب, ميسي, عطلة رسمية\n\n"
                "عند ظهور أي كلمة في خبر ستصلك تنبيه فوري! 🔔",
                parse_mode="Markdown"
            )
        user_states[uid] = "adding_keyword"

    elif data.startswith("interest_") and data != "interest_save":
        opt = data[len("interest_"):]
        user = users.get(str(uid), {})
        interests = user.get("interests", [])
        if opt in interests:
            interests.remove(opt)
        else:
            interests.append(opt)
        users[str(uid)]["interests"] = interests
        _db_save_all_users(users)
        send_interest_menu(uid)

    elif data == "interest_save":
        interests = users.get(str(uid), {}).get("interests", [])
        if interests:
            bot.send_message(uid, "✅ تم حفظ اهتماماتك:\n" + "\n".join(interests))
        else:
            bot.send_message(uid, "✅ لا توجد اهتمامات محددة — ستصلك جميع الأخبار.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_") or c.data.startswith("broadcast_") or c.data.startswith("rss_") or c.data.startswith("quick_") or c.data.startswith("ch_") or c.data.startswith("interval_") or c.data.startswith("bl_") or c.data == "noop" or c.data == "read_open")
def admin_callbacks(call):
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)

    # ======== الإحصائيات ========
    if data == "admin_stats":
        today = str(datetime.date.today())
        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
        week_ago = datetime.date.today() - datetime.timedelta(days=7)
        weekly = sum(v for k, v in stats["daily_users"].items() if datetime.date.fromisoformat(k) >= week_ago)
        today_count = stats["daily_users"].get(today, 0)
        yesterday_count = stats["daily_users"].get(yesterday, 0)
        total = stats.get("total_users", len(users))
        active = sum(1 for u in users.values() if "province" in u)
        top_countries = sorted(stats["countries_count"].items(), key=lambda x: x[1], reverse=True)[:3]
        top_langs = sorted(stats["languages_count"].items(), key=lambda x: x[1], reverse=True)[:3]
        top_buttons = sorted(stats["button_presses"].items(), key=lambda x: x[1], reverse=True)[:3]
        msg = "📊 *الإحصائيات التفصيلية*\n\n"
        msg += f"👥 إجمالي المستخدمين: `{total}`\n"
        msg += f"✅ مستخدمون نشطون: `{active}`\n"
        msg += f"🆕 اليوم: `{today_count}`\n"
        msg += f"📅 أمس: `{yesterday_count}`\n"
        msg += f"📆 هذا الأسبوع: `{weekly}`\n"
        msg += f"⭐ مميزون: `{len(stats.get('premium_users', []))}`\n"
        msg += f"🚫 محظورون: `{len(banned)}`\n\n"
        if top_countries:
            msg += "🌍 *أكثر الدول:*\n"
            for c, n in top_countries:
                msg += f"  {c}: `{n}`\n"
        if top_langs:
            msg += "\n🗣 *أكثر اللغات:*\n"
            for l, n in top_langs:
                msg += f"  {l}: `{n}`\n"
        if top_buttons:
            msg += "\n🔘 *أكثر الأزرار استخداماً:*\n"
            for b, n in top_buttons:
                msg += f"  {b}: `{n}`\n"
        bot.send_message(uid, msg, parse_mode="Markdown")

    # ======== إدارة المستخدمين ========
    elif data == "admin_users":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📋 قائمة جميع المستخدمين", callback_data="admin_users_list_0"),
            types.InlineKeyboardButton("🔍 معلومات مستخدم", callback_data="admin_user_info"),
            types.InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban"),
            types.InlineKeyboardButton("✅ رفع حظر", callback_data="admin_unban"),
            types.InlineKeyboardButton("📋 قائمة المحظورين", callback_data="admin_banned_list"),
            types.InlineKeyboardButton("⭐ ترقية لمميز", callback_data="admin_premium"),
            types.InlineKeyboardButton("❌ إلغاء اشتراك مميز", callback_data="admin_unpremium"),
        )
        bot.send_message(uid, "👥 *إدارة المستخدمين:*\n\nإجمالي المستخدمين: `{}`".format(len(users)), parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("admin_users_list_"):
        page = int(data.split("_")[-1])
        per_page = 10
        all_uids = list(users.keys())
        total = len(all_uids)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = page * per_page
        end = start + per_page
        page_uids = all_uids[start:end]
        premium_list = stats.get("premium_users", [])
        lines = [f"👥 *قائمة المستخدمين* — صفحة {page+1}/{total_pages}\n━━━━━━━━━━━━━━"]
        for i, u_id in enumerate(page_uids, start + 1):
            u = users[u_id]
            name = u.get("name", "—")[:20]
            country = u.get("country", "—")[:15]
            lang = u.get("lang", "")[:4]
            is_prem = "⭐" if int(u_id) in premium_list else ""
            is_ban = "🚫" if int(u_id) in banned else ""
            lines.append(f"{i}. {is_prem}{is_ban} *{name}*\n    🆔 `{u_id}` | 🌍 {country} | 🗣 {lang}")
        msg = "\n".join(lines)
        nav_markup = types.InlineKeyboardMarkup(row_width=3)
        nav_btns = []
        if page > 0:
            nav_btns.append(types.InlineKeyboardButton("◀️ السابق", callback_data=f"admin_users_list_{page-1}"))
        nav_btns.append(types.InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
        if end < total:
            nav_btns.append(types.InlineKeyboardButton("التالي ▶️", callback_data=f"admin_users_list_{page+1}"))
        if nav_btns:
            nav_markup.add(*nav_btns)
        nav_markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_users"))
        try:
            bot.edit_message_text(msg, uid, call.message.message_id, parse_mode="Markdown", reply_markup=nav_markup)
        except:
            bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=nav_markup)

    elif data == "admin_user_info":
        msg = bot.send_message(uid, "أرسل ID المستخدم:")
        bot.register_next_step_handler(msg, get_user_info)

    elif data == "admin_ban":
        msg = bot.send_message(uid, "أرسل ID المستخدم لحظره:")
        bot.register_next_step_handler(msg, ban_user_step)

    elif data == "admin_unban":
        msg = bot.send_message(uid, "أرسل ID المستخدم لرفع حظره:")
        bot.register_next_step_handler(msg, unban_user_step)

    elif data == "admin_banned_list":
        if not banned:
            bot.send_message(uid, "✅ لا يوجد مستخدمون محظورون.")
        else:
            bot.send_message(uid, "🚫 *المحظورون:*\n" + "\n".join(f"`{b}`" for b in banned), parse_mode="Markdown")

    elif data == "admin_premium":
        msg = bot.send_message(uid, "أرسل ID المستخدم لترقيته للمميز:")
        bot.register_next_step_handler(msg, promote_premium_step)

    elif data == "admin_unpremium":
        msg = bot.send_message(uid, "أرسل ID المستخدم لإلغاء اشتراكه المميز:")
        bot.register_next_step_handler(msg, demote_premium_step)

    # ======== الإرسال الجماعي ========
    elif data == "admin_broadcast":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📢 للكل", callback_data="broadcast_all"),
            types.InlineKeyboardButton("🌍 حسب الدولة", callback_data="broadcast_country"),
            types.InlineKeyboardButton("🗣 حسب اللغة", callback_data="broadcast_lang"),
            types.InlineKeyboardButton("⭐ للمميزين فقط", callback_data="broadcast_premium"),
        )
        bot.send_message(uid, "📢 *اختر نوع الإرسال:*", parse_mode="Markdown", reply_markup=markup)

    elif data == "broadcast_all":
        msg = bot.send_message(uid, "أرسل الرسالة لإرسالها لجميع المستخدمين:")
        bot.register_next_step_handler(msg, broadcast_all_step)

    elif data == "broadcast_country":
        msg = bot.send_message(uid, "أرسل اسم الدولة في السطر الأول، والرسالة في السطر الثاني:")
        bot.register_next_step_handler(msg, broadcast_country_step)

    elif data == "broadcast_lang":
        msg = bot.send_message(uid, "أرسل اللغة في السطر الأول، والرسالة في السطر الثاني:")
        bot.register_next_step_handler(msg, broadcast_lang_step)

    elif data == "broadcast_premium":
        msg = bot.send_message(uid, "أرسل الرسالة لإرسالها للمستخدمين المميزين:")
        bot.register_next_step_handler(msg, broadcast_premium_step)

    # ======== إيقاف/تشغيل البوت ========
    elif data == "admin_pause":
        global bot_paused
        if bot_paused:
            bot_paused = False
            bot.send_message(uid, "✅ البوت يعمل الآن.")
        else:
            msg = bot.send_message(uid, "أرسل رسالة الإيقاف (أو أرسل 'افتراضي'):")
            bot.register_next_step_handler(msg, pause_bot_step)

    # ======== إدارة RSS ========
    elif data == "admin_rss":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة مصدر", callback_data="rss_add"),
            types.InlineKeyboardButton("➖ حذف مصدر", callback_data="rss_remove"),
            types.InlineKeyboardButton("📋 عرض المصادر", callback_data="rss_list"),
        )
        bot.send_message(uid, "📡 *إدارة مصادر RSS:*", parse_mode="Markdown", reply_markup=markup)

    elif data == "rss_add":
        msg = bot.send_message(uid, "أرسل اللغة في السطر الأول، والرابط في السطر الثاني:")
        bot.register_next_step_handler(msg, rss_add_step)

    elif data == "rss_remove":
        msg = bot.send_message(uid, "أرسل اللغة في السطر الأول، ورقم المصدر في السطر الثاني:")
        bot.register_next_step_handler(msg, rss_remove_step)

    elif data == "rss_list":
        msg = "📡 *مصادر RSS الحالية:*\n\n"
        for lang, feeds in RSS.items():
            msg += f"*{lang}*\n"
            for i, f in enumerate(feeds):
                msg += f"  `{i+1}`. {f}\n"
            msg += "\n"
        bot.send_message(uid, msg, parse_mode="Markdown")

    # ======== المالية ========
    elif data == "admin_finance":
        premium_count = len(stats.get("premium_users", []))
        revenue = stats.get("revenue", 0.0)
        msg = (
            f"💰 *المالية*\n\n"
            f"⭐ المميزون: `{premium_count}`\n"
            f"💵 الدخل الكلي: `${revenue:.2f}`\n"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")

    # ======== تغيير رسالة الترحيب ========
    elif data == "admin_welcome":
        msg = bot.send_message(uid, "أرسل رسالة الترحيب الجديدة (أو 'افتراضي' للرجوع للأصلية):")
        bot.register_next_step_handler(msg, change_welcome_step)

    # ======== إدارة الأدمن ========
    elif data == "admin_manage_admins":
        # فقط الأدمن الرئيسي يستطيع إدارة الأدمن الآخرين
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة أدمن", callback_data="admin_addadmin"),
            types.InlineKeyboardButton("➖ إزالة أدمن", callback_data="admin_removeadmin"),
            types.InlineKeyboardButton("📋 قائمة الأدمن", callback_data="admin_listadmins"),
        )
        bot.send_message(uid, "👑 *إدارة الأدمن:*", parse_mode="Markdown", reply_markup=markup)

    elif data == "admin_addadmin":
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        msg = bot.send_message(uid, "أرسل ID المستخدم الذي تريد تعيينه أدمن:")
        bot.register_next_step_handler(msg, add_admin_step)

    elif data == "admin_removeadmin":
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        msg = bot.send_message(uid, "أرسل ID الأدمن الذي تريد إزالته:")
        bot.register_next_step_handler(msg, remove_admin_step)

    elif data == "admin_listadmins":
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        if not extra_admins:
            bot.send_message(uid, f"👑 *قائمة الأدمن:*\n\n🔑 الأدمن الرئيسي: `{ADMIN_ID}`\n\nلا يوجد أدمن إضافيون.", parse_mode="Markdown")
        else:
            admins_list = "\n".join(f"  `{a}`" for a in extra_admins)
            bot.send_message(uid,
                f"👑 *قائمة الأدمن:*\n\n"
                f"🔑 الأدمن الرئيسي: `{ADMIN_ID}`\n\n"
                f"👥 الأدمن الإضافيون:\n{admins_list}",
                parse_mode="Markdown"
            )

    elif data == "noop":
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_view_"):
        target_id = data.split("admin_view_")[-1]
        user = users.get(target_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ المستخدم غير موجود")
            return
        is_banned_user = int(target_id) in banned
        is_premium_user = int(target_id) in stats.get("premium_users", [])
        referrals = user.get("referrals", [])
        referred_by = user.get("referred_by", None)
        join_date = user.get("join_date", "غير معروف")
        interests = user.get("interests", [])
        notif = "✅" if user.get("notifications", True) else "❌"
        track_data = tracked_assets.get(target_id, {})
        tracked = track_data.get("assets", [])
        msg = (
            f"👤 *ملف المستخدم*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{target_id}`\n"
            f"👤 الاسم: *{user.get('name', '—')}*\n"
            f"🗣 اللغة: {user.get('lang', '-')}\n"
            f"🌍 الدولة: {user.get('country', '-')}\n"
            f"📍 المحافظة: {user.get('province', '-')}\n"
            f"📅 الانضمام: `{join_date}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"🚫 محظور: {'نعم' if is_banned_user else 'لا'} | "
            f"⭐ مميز: {'نعم' if is_premium_user else 'لا'}\n"
            f"🔔 إشعارات: {notif} | 🎁 دعوات: `{len(referrals)}`\n"
            f"👈 جاء عبر: `{referred_by if referred_by else 'مباشر'}`\n"
            f"📌 يتتبع: `{', '.join(tracked) if tracked else '—'}`\n"
            f"📰 اهتمامات: `{', '.join(interests) if interests else '—'}`\n"
        )
        view_markup = types.InlineKeyboardMarkup(row_width=2)
        view_markup.add(
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{target_id}"),
            types.InlineKeyboardButton("⭐ ترقية مميز", callback_data=f"quick_premium_{target_id}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={target_id}"),
        )
        bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=view_markup)

    elif data.startswith("quick_ban_"):
        target_id_str = data.split("quick_ban_")[-1]
        try:
            target_id_int = int(target_id_str)
            if target_id_int not in banned:
                banned.append(target_id_int)
                save_json(BANNED_FILE, banned)
                bot.answer_callback_query(call.id, f"✅ تم حظر المستخدم {target_id_str}")
                bot.send_message(uid, f"🚫 تم حظر المستخدم `{target_id_str}` بنجاح.", parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "⚠️ هذا المستخدم محظور مسبقاً")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

    elif data.startswith("quick_premium_"):
        target_id_str = data.split("quick_premium_")[-1]
        try:
            target_id_int = int(target_id_str)
            premium_list = stats.get("premium_users", [])
            if target_id_int not in premium_list:
                premium_list.append(target_id_int)
                stats["premium_users"] = premium_list
                save_json(STATS_FILE, stats)
                bot.answer_callback_query(call.id, "✅ تمت الترقية لـ ⭐ مميز")
                bot.send_message(uid, f"⭐ تم ترقية المستخدم `{target_id_str}` للمميز.", parse_mode="Markdown")
                try:
                    bot.send_message(target_id_int, "🎉 تهانينا! تمت ترقيتك للاشتراك المميز ⭐\nاستمتع بجميع الميزات الحصرية!")
                except:
                    pass
            else:
                bot.answer_callback_query(call.id, "⚠️ هذا المستخدم مميز مسبقاً")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

    elif data == "admin_channels":
        handle_admin_channels(uid, call)

    elif data == "ch_add":
        bot.send_message(uid,
            "➕ *إضافة قناة أو مجموعة*\n\n"
            "أرسل المعلومات في رسالة واحدة بهذا الشكل:\n\n"
            "`-1001234567890`\n"
            "`العربية 🇮🇶`\n\n"
            "📌 السطر الأول: ID القناة/المجموعة\n"
            "📌 السطر الثاني: لغة الأخبار التي ستُرسل لها\n\n"
            "⚠️ تأكد أن البوت أدمن في القناة/المجموعة أولاً",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler_by_chat_id(uid, add_channel_step)

    elif data == "ch_remove":
        if not channels_groups:
            bot.send_message(uid, "📭 لا توجد قنوات/مجموعات مضافة حالياً.")
            return
        msg = "➖ *حذف قناة أو مجموعة*\n\nأرسل ID القناة/المجموعة للحذف:\n\n"
        for ch in channels_groups:
            msg += f"📺 *{ch['title']}* — `{ch['id']}`\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, remove_channel_step)

    elif data == "ch_list":
        if not channels_groups:
            bot.send_message(uid, "📭 لا توجد قنوات/مجموعات مضافة حالياً.")
            return
        msg = "📋 *قائمة القنوات والمجموعات:*\n\n"
        for i, ch in enumerate(channels_groups, 1):
            emoji = "📢" if ch.get("type") == "channel" else "👥"
            msg += (
                f"{i}. {emoji} *{ch['title']}*\n"
                f"   🆔 ID: `{ch['id']}`\n"
                f"   🗣 اللغة: {ch.get('lang', 'غير محددة')}\n\n"
            )
        bot.send_message(uid, msg, parse_mode="Markdown")

    elif data == "ch_broadcast_now":
        bot.send_message(uid, "📡 جاري إرسال الأخبار للقنوات والمجموعات...")
        try:
            broadcast_to_channels()
            bot.send_message(uid, f"✅ تم إرسال الأخبار لـ {len(channels_groups)} قناة/مجموعة.")
        except Exception as e:
            bot.send_message(uid, f"❌ خطأ أثناء البث: {e}")

    # ======== خبر عاجل مخصص ========
    elif data == "admin_breaking_news":
        bot.send_message(uid,
            "🚨 *إرسال خبر عاجل مخصص*\n\n"
            "أرسل نص الخبر العاجل، وسيُرسَل فوراً لجميع المستخدمين والقنوات مع الأزرار.\n\n"
            "💡 يمكنك إضافة رابط في السطر الثاني (اختياري):\n"
            "`نص الخبر العاجل`\n"
            "`https://رابط-الخبر (اختياري)`",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler_by_chat_id(uid, breaking_news_step)

    # ======== توقيت البث ========
    elif data == "admin_interval":
        current = broadcast_settings.get("interval_minutes", 5)
        markup_int = types.InlineKeyboardMarkup(row_width=3)
        markup_int.add(
            types.InlineKeyboardButton("3 دقائق", callback_data="interval_3"),
            types.InlineKeyboardButton("5 دقائق ✅" if current == 5 else "5 دقائق", callback_data="interval_5"),
            types.InlineKeyboardButton("10 دقائق", callback_data="interval_10"),
            types.InlineKeyboardButton("15 دقيقة", callback_data="interval_15"),
            types.InlineKeyboardButton("30 دقيقة", callback_data="interval_30"),
            types.InlineKeyboardButton("60 دقيقة", callback_data="interval_60"),
        )
        bot.send_message(uid,
            f"⏱ *توقيت البث الحالي:* كل `{current}` دقيقة\n\nاختر التوقيت الجديد:",
            parse_mode="Markdown", reply_markup=markup_int
        )

    elif data.startswith("interval_"):
        minutes = int(data.split("_")[1])
        broadcast_settings["interval_minutes"] = minutes
        save_broadcast_settings()
        bot.send_message(uid,
            f"✅ تم تغيير توقيت البث إلى كل *{minutes}* دقيقة.\n"
            f"⚠️ سيُطبَّق التغيير بعد إعادة تشغيل البوت.",
            parse_mode="Markdown"
        )

    # ======== القائمة السوداء ========
    elif data == "admin_blacklist":
        words = blacklist_words
        count = len(words)
        words_preview = "، ".join(words[:10]) if words else "لا توجد كلمات"
        markup_bl = types.InlineKeyboardMarkup(row_width=2)
        markup_bl.add(
            types.InlineKeyboardButton("➕ إضافة كلمة", callback_data="bl_add"),
            types.InlineKeyboardButton("➖ حذف كلمة", callback_data="bl_remove"),
            types.InlineKeyboardButton("📋 عرض الكل", callback_data="bl_list"),
            types.InlineKeyboardButton("🗑 مسح الكل", callback_data="bl_clear"),
        )
        bot.send_message(uid,
            f"🚫 *القائمة السوداء للكلمات*\n\n"
            f"📊 عدد الكلمات: `{count}`\n"
            f"📝 عينة: {words_preview}\n\n"
            f"أي خبر يحتوي كلمة من هذه القائمة لن يُرسَل.",
            parse_mode="Markdown", reply_markup=markup_bl
        )

    elif data == "bl_add":
        bot.send_message(uid, "➕ أرسل الكلمة أو الكلمات التي تريد حجبها (كلمة واحدة أو أكثر مفصولة بفاصلة):")
        bot.register_next_step_handler_by_chat_id(uid, bl_add_step)

    elif data == "bl_remove":
        if not blacklist_words:
            bot.send_message(uid, "📭 القائمة السوداء فارغة.")
            return
        bot.send_message(uid, f"➖ أرسل الكلمة التي تريد حذفها:\n\n{', '.join(blacklist_words)}")
        bot.register_next_step_handler_by_chat_id(uid, bl_remove_step)

    elif data == "bl_list":
        if not blacklist_words:
            bot.send_message(uid, "📭 القائمة السوداء فارغة.")
            return
        bot.send_message(uid, "📋 *الكلمات المحجوبة:*\n\n" + "\n".join(f"• `{w}`" for w in blacklist_words), parse_mode="Markdown")

    elif data == "bl_clear":
        blacklist_words.clear()
        save_blacklist()
        bot.send_message(uid, "✅ تم مسح القائمة السوداء بالكامل.")

    # ======== عداد القراءة ========
    elif data == "admin_read_stats":
        total = read_stats.get("total_opens", 0)
        today = str(datetime.date.today())
        today_count = read_stats.get("daily", {}).get(today, 0)
        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
        yesterday_count = read_stats.get("daily", {}).get(yesterday, 0)
        bot.send_message(uid,
            f"📖 *إحصائيات القراءة (فتح الأخبار):*\n\n"
            f"📊 الإجمالي: `{total}` ضغطة\n"
            f"📅 اليوم: `{today_count}` ضغطة\n"
            f"📅 أمس: `{yesterday_count}` ضغطة",
            parse_mode="Markdown"
        )

    # ======== إحصائيات القنوات ========
    elif data == "admin_channel_stats":
        if not channels_groups:
            bot.send_message(uid, "📭 لا توجد قنوات/مجموعات مضافة.")
            return
        msg = "📈 *إحصائيات القنوات والمجموعات:*\n\n"
        total_sent = 0
        for ch in channels_groups:
            count_ch = ch.get("news_sent_count", 0)
            total_sent += count_ch
            emoji = "📢" if ch.get("type") == "channel" else "👥"
            msg += (
                f"{emoji} *{ch['title']}*\n"
                f"   📰 أخبار مُرسَلة: `{count_ch}`\n"
                f"   🌐 اللغة: {ch.get('lang', '-')}\n\n"
            )
        msg += f"━━━━━━━━━━━━━━\n📊 *إجمالي الأخبار المُرسَلة:* `{total_sent}`"
        bot.send_message(uid, msg, parse_mode="Markdown")

    # ======== بحث عن مستخدم ========
    elif data == "admin_search_user":
        bot.send_message(uid, "🔍 *بحث عن مستخدم*\n\nأرسل ID المستخدم أو اسمه للبحث:", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, search_user_step)

    # ======== رسالة لمستخدم محدد ========
    elif data == "admin_msg_user":
        bot.send_message(uid,
            "✉️ *إرسال رسالة لمستخدم محدد*\n\n"
            "أرسل في سطرين:\n"
            "السطر 1: ID المستخدم\n"
            "السطر 2: نص الرسالة",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler_by_chat_id(uid, msg_user_step)

    # ======== قائمة الأوامر ========
    elif data == "admin_commands":
        commands_text = (
            "📋 *قائمة جميع أوامر البوت:*\n\n"
            "━━━━━━━━━ *للأدمن* ━━━━━━━━━\n"
            "👑 `/admin` — لوحة تحكم الأدمن\n"
            "📊 `/stats` — إحصائيات البوت (إن وُجد)\n\n"
            "━━━━━━━━━ *للمستخدم* ━━━━━━━━━\n"
            "🚀 `/start` — بدء البوت\n"
            "❓ `/help` — المساعدة\n"
            "🔔 `/notify` — تفعيل/إيقاف الإشعارات (إن وُجد)\n\n"
            "━━━━━━━━━ *لأدمن القناة/المجموعة* ━━━━━━━━━\n"
            "🌐 `/setlang اسم_اللغة` — تغيير لغة الأخبار\n"
            "🏙 `/setcity اسم_المدينة` — تعيين المدينة\n"
            "📡 `/setsource رابط_RSS` — إضافة مصدر أخبار\n"
            "🗑 `/removesource رابط_RSS` — حذف مصدر أخبار\n"
            "📋 `/listsources` — عرض مصادر الأخبار\n"
            "⏸ `/pause` — إيقاف البث مؤقتاً\n"
            "▶️ `/resume` — استئناف البث\n"
            "⚙️ `/settings` — عرض الإعدادات الحالية\n\n"
            "━━━━━━━━━ *الأزرار على كل خبر* ━━━━━━━━━\n"
            "🔗 فتح الخبر — يفتح رابط الخبر\n"
            "📤 شارك الخبر — يشارك الخبر\n"
            f"🤖 شارك البوت — يشارك @{BOT_USERNAME}"
        )
        bot.send_message(uid, commands_text, parse_mode="Markdown")

    elif data == "admin_news_format":
        sep = news_settings.get("separator", "━━━━━━━━━━━━━━")
        sig = news_settings.get("signature", "عبر بوت أخبار العالم\n@Iraqnowbot")
        label = news_settings.get("label", "🚨 خبر عاجل")
        preview = f"{label}\n\n📰 عنوان الخبر التجريبي\n{sep}\n{sig}"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✏️ تعديل العنوان", callback_data="admin_nf_label"),
            types.InlineKeyboardButton("➖ تعديل الفاصل", callback_data="admin_nf_sep"),
            types.InlineKeyboardButton("📝 تعديل التوقيع", callback_data="admin_nf_sig"),
        )
        bot.send_message(uid, f"✏️ *شكل رسالة الخبر الحالي:*\n\n{preview}", parse_mode="Markdown", reply_markup=markup)

    elif data == "admin_nf_label":
        msg = bot.send_message(uid, "📝 أرسل العنوان الجديد للخبر (مثال: 🚨 خبر عاجل):")
        bot.register_next_step_handler(msg, _nf_label_step)

    elif data == "admin_nf_sep":
        msg = bot.send_message(uid, "📝 أرسل الفاصل الجديد (مثال: ━━━━━━━━━━━━━━ أو --- أو اكتب 'بدون' لحذفه):")
        bot.register_next_step_handler(msg, _nf_sep_step)

    elif data == "admin_nf_sig":
        msg = bot.send_message(uid, "📝 أرسل التوقيع الجديد (مثال: عبر بوتي\\n@username):")
        bot.register_next_step_handler(msg, _nf_sig_step)

    elif data == "admin_inbox":
        if not inbox_messages:
            bot.send_message(uid, "📭 صندوق الرسائل فارغ حالياً.")
        else:
            last = inbox_messages[-10:]
            for entry in reversed(last):
                u_id = entry.get("uid")
                name = entry.get("name", "مجهول")
                text = entry.get("text", "")
                utype = "⭐ مميز" if entry.get("premium") else "👤 عادي"
                ts = entry.get("time", "")
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(f"↩️ رد على {name}", callback_data=f"admin_reply_{u_id}"))
                bot.send_message(uid,
                    f"💬 *رسالة من:* {name}\n"
                    f"🆔 `{u_id}` | {utype}\n"
                    f"🕐 {ts}\n\n"
                    f"📩 {text}",
                    parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("admin_reply_"):
        target_uid = data.split("admin_reply_")[-1]
        msg = bot.send_message(uid, f"✏️ اكتب ردك على المستخدم `{target_uid}`:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m, tid=target_uid: _admin_reply_step(m, tid))

    elif data == "admin_ratings":
        count = ratings_data.get("count", 0)
        if count == 0:
            bot.send_message(uid, "⭐ لا توجد تقييمات بعد.")
        else:
            bot_avg = round(ratings_data.get("bot_sum", 0) / count, 1)
            news_avg = round(ratings_data.get("news_sum", 0) / count, 1)
            bot.send_message(uid,
                f"⭐ *تقييمات المستخدمين*\n\n"
                f"📊 إجمالي التقييمات: `{count}`\n"
                f"🤖 متوسط تقييم البوت: `{bot_avg}/5`\n"
                f"📰 متوسط تقييم الأخبار: `{news_avg}/5`",
                parse_mode="Markdown")

# ======== دوال شكل الخبر ========
def _nf_label_step(message):
    if not is_admin(message.from_user.id):
        return
    news_settings["label"] = message.text.strip()
    save_news_settings()
    bot.send_message(message.from_user.id, f"✅ تم تغيير عنوان الخبر إلى:\n{news_settings['label']}")

def _nf_sep_step(message):
    if not is_admin(message.from_user.id):
        return
    val = message.text.strip()
    news_settings["separator"] = "" if val == "بدون" else val
    save_news_settings()
    bot.send_message(message.from_user.id, "✅ تم تحديث الفاصل.")

def _nf_sig_step(message):
    if not is_admin(message.from_user.id):
        return
    news_settings["signature"] = message.text.strip().replace("\\n", "\n")
    save_news_settings()
    bot.send_message(message.from_user.id, "✅ تم تحديث التوقيع.")

def _admin_reply_step(message, target_uid):
    if not is_admin(message.from_user.id):
        return
    try:
        bot.send_message(int(target_uid),
            f"💬 *رد من إدارة البوت:*\n\n{message.text}",
            parse_mode="Markdown")
        bot.send_message(message.from_user.id, "✅ تم إرسال الرد بنجاح.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"⚠️ فشل الإرسال: {e}")

# ======== إدارة القنوات والمجموعات ========
def handle_admin_channels(uid, call):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ إضافة قناة/مجموعة", callback_data="ch_add"),
        types.InlineKeyboardButton("➖ حذف قناة/مجموعة", callback_data="ch_remove"),
        types.InlineKeyboardButton("📋 قائمة القنوات", callback_data="ch_list"),
        types.InlineKeyboardButton("📢 بث أخبار للقنوات الآن", callback_data="ch_broadcast_now"),
    )
    count = len(channels_groups)
    bot.send_message(uid,
        f"📺 *إدارة القنوات والمجموعات*\n\n"
        f"📊 عدد القنوات/المجموعات المضافة: `{count}`\n\n"
        f"💡 *كيفية الإضافة:*\n"
        f"1. أضف البوت كأدمن في القناة/المجموعة\n"
        f"2. أرسل ID القناة أو المجموعة (مثال: -1001234567890)\n"
        f"3. حدد اللغة المناسبة لإرسال الأخبار",
        parse_mode="Markdown", reply_markup=markup
    )

def add_channel_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    lines = message.text.strip().split("\n")
    if len(lines) < 2:
        bot.send_message(uid,
            "❌ أرسل في سطرين:\n"
            "السطر 1: ID القناة/المجموعة (مثال: -1001234567890)\n"
            "السطر 2: اللغة (مثال: العربية 🇮🇶)"
        )
        return
    try:
        chat_id = int(lines[0].strip())
        lang = lines[1].strip()
        try:
            chat_info = bot.get_chat(chat_id)
            title = chat_info.title or str(chat_id)
            chat_type = chat_info.type
        except Exception as e:
            bot.send_message(uid, f"❌ تعذّر الوصول للقناة/المجموعة: {e}\nتأكد أن البوت أدمن فيها.")
            return
        for ch in channels_groups:
            if ch["id"] == chat_id:
                bot.send_message(uid, f"⚠️ هذه القناة/المجموعة مضافة مسبقاً: *{title}*", parse_mode="Markdown")
                return
        feeds = RSS.get(lang, RSS.get("العربية 🇮🇶", []))
        initial_sent = list(prefill_sent_news(feeds))
        channels_groups.append({"id": chat_id, "title": title, "type": chat_type, "lang": lang, "sent_news": initial_sent})
        save_channels_groups()
        bot.send_message(uid,
            f"✅ تمت الإضافة بنجاح!\n"
            f"📺 *{title}*\n"
            f"🆔 ID: `{chat_id}`\n"
            f"🗣 اللغة: {lang}\n"
            f"📡 النوع: {chat_type}\n"
            f"📰 تم حفظ {len(initial_sent)} خبر موجود — ستصل فقط الأخبار الجديدة من الآن.",
            parse_mode="Markdown"
        )
    except ValueError:
        bot.send_message(uid, "❌ ID غير صحيح. يجب أن يكون رقماً مثل: -1001234567890")
    except Exception as e:
        bot.send_message(uid, f"❌ خطأ: {e}")

def remove_channel_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    try:
        chat_id = int(message.text.strip())
        removed = None
        for i, ch in enumerate(channels_groups):
            if ch["id"] == chat_id:
                removed = channels_groups.pop(i)
                break
        if removed:
            save_channels_groups()
            bot.send_message(uid, f"✅ تم حذف القناة/المجموعة: *{removed['title']}*", parse_mode="Markdown")
        else:
            bot.send_message(uid, "⚠️ هذا ID غير موجود في القائمة.")
    except ValueError:
        bot.send_message(uid, "❌ أرسل ID رقمياً فقط.")
    except Exception as e:
        bot.send_message(uid, f"❌ خطأ: {e}")

def prefill_sent_news(feeds):
    """جلب روابط الأخبار الحالية من الـ RSS لملء sent_news أولياً (لتجنب بث الأخبار القديمة دفعة واحدة)."""
    links = set()
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:20]:
                link = getattr(item, 'link', '')
                if link:
                    links.add(link)
        except:
            pass
    return links

def broadcast_to_channels():
    try:
        if not channels_groups:
            return
        changed = False
        rss_cache = {}
        for ch in list(channels_groups):
            try:
                if ch.get('paused'):
                    continue
                chat_id = ch["id"]
                lang = ch.get('lang', 'العربية 🇮🇶')
                custom_sources = ch.get('custom_sources', [])
                feeds = custom_sources if custom_sources else RSS.get(lang, RSS.get('العربية 🇮🇶', []))
                sent = set(ch.setdefault('sent_news', []))
                for feed_url in feeds:
                    if feed_url not in rss_cache:
                        try:
                            rss_cache[feed_url] = feedparser.parse(feed_url)
                        except Exception:
                            rss_cache[feed_url] = None
                    feed = rss_cache.get(feed_url)
                    if not feed:
                        continue
                    for item in feed.entries[:50]:
                        if not hasattr(item, 'link') or not hasattr(item, 'title'):
                            continue
                        link = getattr(item, 'link', '')
                        title = getattr(item, 'title', '')
                        if not link or link in sent:
                            continue
                        if is_blacklisted(title):
                            continue
                        sent.add(link)
                        ch["sent_news"] = list(sent)[-1000:]
                        ch["news_sent_count"] = ch.get("news_sent_count", 0) + 1
                        changed = True
                        item_summary = getattr(item, 'summary', '') or getattr(item, 'description', '')
                        markup = make_news_share_markup(link, title, lang, item_summary)
                        queue_send(chat_id, format_news_item(t(lang, "label_breaking"), title),
                            parse_mode="Markdown", reply_markup=markup)
            except Exception:
                continue
        if changed:
            save_channels_groups()
    except Exception as e:
        try:
            bot.send_message(ADMIN_ID, f"⚠️ خطأ في broadcast_to_channels: {e}")
        except Exception:
            pass

def breaking_news_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    lines = message.text.strip().split("\n")
    news_text = lines[0].strip()
    link = lines[1].strip() if len(lines) > 1 and lines[1].startswith("http") else ""
    full_msg = f"🚨 *خبر عاجل*\n\n📰 {news_text}{BOT_SIGNATURE}"
    sent_users = 0
    failed_users = 0
    for target_uid in list(users.keys()):
        if int(target_uid) in banned:
            continue
        try:
            user_lang = users.get(target_uid, {}).get("lang", "English 🇬🇧")
            user_markup = make_news_share_markup(link, news_text, user_lang) if link else None
            bot.send_message(target_uid, full_msg, parse_mode="Markdown", reply_markup=user_markup)
            sent_users += 1
        except:
            failed_users += 1
    sent_ch = 0
    for ch in list(channels_groups):
        try:
            ch_lang = ch.get("lang", "العربية 🇮🇶")
            ch_markup = make_news_share_markup(link, news_text, ch_lang) if link else None
            bot.send_message(ch["id"], full_msg, parse_mode="Markdown", reply_markup=ch_markup)
            sent_ch += 1
        except:
            pass
    bot.send_message(uid,
        f"✅ *تم إرسال الخبر العاجل:*\n\n"
        f"👤 المستخدمون: `{sent_users}` وصل، `{failed_users}` فشل\n"
        f"📺 القنوات/المجموعات: `{sent_ch}` وصل",
        parse_mode="Markdown"
    )

def bl_add_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    words_input = message.text.strip()
    new_words = [w.strip() for w in words_input.replace("،", ",").split(",") if w.strip()]
    added = []
    for w in new_words:
        if w not in blacklist_words:
            blacklist_words.append(w)
            added.append(w)
    save_blacklist()
    bot.send_message(uid,
        f"✅ تم إضافة `{len(added)}` كلمة للقائمة السوداء:\n" +
        "\n".join(f"• `{w}`" for w in added),
        parse_mode="Markdown"
    )

def bl_remove_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    word = message.text.strip()
    if word in blacklist_words:
        blacklist_words.remove(word)
        save_blacklist()
        bot.send_message(uid, f"✅ تم حذف الكلمة `{word}` من القائمة السوداء.", parse_mode="Markdown")
    else:
        bot.send_message(uid, f"⚠️ الكلمة `{word}` غير موجودة في القائمة.", parse_mode="Markdown")

def search_user_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    query = message.text.strip().lower()
    results = []
    for u_id, u_info in users.items():
        name = u_info.get("name", "").lower()
        if query == u_id or query in name:
            results.append((u_id, u_info))
    if not results:
        bot.send_message(uid, "❌ لم يُعثَر على مستخدم بهذا ID أو الاسم.")
        return
    for u_id, u_info in results[:5]:
        notif = "✅" if u_info.get("notifications", True) else "❌"
        is_pr = int(u_id) in stats.get("premium_users", [])
        msg = (
            f"👤 *نتيجة البحث*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{u_id}`\n"
            f"👤 الاسم: *{u_info.get('name', '—')}*\n"
            f"🗣 اللغة: {u_info.get('lang', '-')}\n"
            f"🌍 الدولة: {u_info.get('country', '-')}\n"
            f"📅 الانضمام: `{u_info.get('join_date', '-')}`\n"
            f"🔔 إشعارات: {notif} | ⭐ مميز: {'نعم' if is_pr else 'لا'}"
        )
        view_markup = types.InlineKeyboardMarkup(row_width=2)
        view_markup.add(
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{u_id}"),
            types.InlineKeyboardButton("⭐ ترقية", callback_data=f"quick_premium_{u_id}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={u_id}"),
        )
        bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=view_markup)

def msg_user_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    lines = message.text.strip().split("\n")
    if len(lines) < 2:
        bot.send_message(uid, "❌ أرسل في سطرين: السطر 1 ID المستخدم، السطر 2 الرسالة.")
        return
    try:
        target_id = int(lines[0].strip())
        msg_text = "\n".join(lines[1:]).strip()
        bot.send_message(target_id, f"📩 *رسالة من الإدارة:*\n\n{msg_text}", parse_mode="Markdown")
        bot.send_message(uid, f"✅ تم إرسال الرسالة للمستخدم `{target_id}` بنجاح.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(uid, "❌ ID غير صحيح.")
    except Exception as e:
        bot.send_message(uid, f"❌ فشل الإرسال: {e}")

# ======== معالج عداد القراءة (لجميع المستخدمين) ========
@bot.callback_query_handler(func=lambda c: c.data == "read_open")
def handle_read_open(call):
    today = str(datetime.date.today())
    read_stats["total_opens"] = read_stats.get("total_opens", 0) + 1
    read_stats.setdefault("daily", {})[today] = read_stats["daily"].get(today, 0) + 1
    save_read_stats()
    bot.answer_callback_query(call.id)

# ======== معالج زر ملخص الخبر ========
@bot.callback_query_handler(func=lambda c: c.data.startswith("sum_"))
def handle_summary_button(call):
    uid = call.from_user.id
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    lbl = NEWS_SHARE_LABELS.get(lang, NEWS_SHARE_LABELS["English 🇬🇧"])
    sum_key = call.data[4:]
    summary_text = _news_summary_cache.get(sum_key)
    if not summary_text:
        bot.answer_callback_query(call.id, lbl["no_summary"], show_alert=True)
        return
    clean = _clean_html(summary_text)
    if not clean:
        bot.answer_callback_query(call.id, lbl["no_summary"], show_alert=True)
        return
    MAX_ALERT = 190
    if len(clean) <= MAX_ALERT:
        bot.answer_callback_query(call.id, clean, show_alert=True)
    else:
        bot.answer_callback_query(call.id)
        bot.send_message(uid, f"📄 {lbl['summary_btn']}\n\n{clean[:1500]}")
        user["used_summary"] = True
        _db_save_user(uid, user)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_bot_") or c.data.startswith("rate_news_"))
def handle_rating(call):
    uid = call.from_user.id
    data = call.data
    try:
        parts = data.split("_")
        rtype = parts[1]
        stars = int(parts[2])
        bot.answer_callback_query(call.id, f"✅ شكراً! قيّمت بـ {stars}⭐")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        if rtype == "bot":
            ratings_data["bot_sum"] = ratings_data.get("bot_sum", 0) + stars
            ratings_data["count"] = ratings_data.get("count", 0) + 1
        elif rtype == "news":
            ratings_data["news_sum"] = ratings_data.get("news_sum", 0) + stars
        ratings_data.setdefault("entries", []).append({
            "uid": uid, "type": rtype, "stars": stars,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        save_ratings()
    except Exception:
        pass

# ======== خطوات إدارة الأدمن ========
def add_admin_step(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id == ADMIN_ID:
            bot.send_message(ADMIN_ID, "⚠️ هذا هو الأدمن الرئيسي بالفعل.")
            return
        if new_admin_id in extra_admins:
            bot.send_message(ADMIN_ID, "⚠️ هذا المستخدم أدمن بالفعل.")
            return
        extra_admins.append(new_admin_id)
        save_extra_admins()
        bot.send_message(ADMIN_ID, f"✅ تم تعيين المستخدم `{new_admin_id}` كأدمن.", parse_mode="Markdown")
        try:
            bot.send_message(new_admin_id, "👑 تم تعيينك كأدمن في البوت.\nاستخدم /admin للوصول للوحة التحكم.")
        except:
            pass
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def remove_admin_step(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target_id = int(message.text.strip())
        if target_id not in extra_admins:
            bot.send_message(ADMIN_ID, "⚠️ هذا المستخدم ليس أدمن إضافياً.")
            return
        extra_admins.remove(target_id)
        save_extra_admins()
        bot.send_message(ADMIN_ID, f"✅ تم إزالة الأدمن `{target_id}`.", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "⚠️ تم إلغاء صلاحيات الأدمن الخاصة بك.")
        except:
            pass
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

# ======== خطوات الأدمن ========
def get_user_info(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = str(message.text.strip())
        user = users.get(target_id)
        if not user:
            bot.send_message(message.from_user.id, "❌ المستخدم غير موجود.")
            return
        is_banned_user = int(target_id) in banned
        is_premium_user = int(target_id) in stats.get("premium_users", [])
        is_admin_user = is_admin(int(target_id))
        referrals = user.get("referrals", [])
        referred_by = user.get("referred_by", None)
        join_date = user.get("join_date", "غير معروف")
        interests = user.get("interests", [])
        notif = "✅ مفعّل" if user.get("notifications", True) else "❌ موقوف"
        track_data = tracked_assets.get(target_id, {})
        tracked = track_data.get("assets", [])
        msg = (
            f"👤 *ملف المستخدم الكامل*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{target_id}`\n"
            f"👤 الاسم: *{user.get('name', 'غير معروف')}*\n"
            f"🗣 اللغة: {user.get('lang', '-')}\n"
            f"🌍 الدولة: {user.get('country', '-')}\n"
            f"📍 المحافظة: {user.get('province', '-')}\n"
            f"📅 تاريخ الانضمام: `{join_date}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"🚫 محظور: {'✅ نعم' if is_banned_user else '❌ لا'}\n"
            f"⭐ مميز: {'✅ نعم' if is_premium_user else '❌ لا'}\n"
            f"👑 أدمن: {'✅ نعم' if is_admin_user else '❌ لا'}\n"
            f"🔔 الإشعارات: {notif}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎁 دعواته: `{len(referrals)}` شخص\n"
            f"👈 جاء عبر: `{referred_by if referred_by else 'مباشر'}`\n"
            f"📌 أصوله المتتبعة: `{', '.join(tracked) if tracked else 'لا يوجد'}`\n"
            f"📰 اهتماماته: `{', '.join(interests) if interests else 'لم يختر'}`\n"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{target_id}"),
            types.InlineKeyboardButton("⭐ ترقية مميز", callback_data=f"quick_premium_{target_id}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={target_id}"),
        )
        bot.send_message(message.from_user.id, msg, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def ban_user_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if target_id not in banned:
            banned.append(target_id)
            save_json(BANNED_FILE, banned)
        bot.send_message(message.from_user.id, f"✅ تم حظر المستخدم `{target_id}`", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "🚫 تم حظرك من استخدام البوت.")
        except:
            pass
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def unban_user_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if target_id in banned:
            banned.remove(target_id)
            save_json(BANNED_FILE, banned)
            bot.send_message(message.from_user.id, f"✅ تم رفع حظر المستخدم `{target_id}`", parse_mode="Markdown")
        else:
            bot.send_message(message.from_user.id, "⚠️ المستخدم غير محظور.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def promote_premium_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if "premium_users" not in stats:
            stats["premium_users"] = []
        if target_id not in stats["premium_users"]:
            stats["premium_users"].append(target_id)
            save_json(STATS_FILE, stats)
        bot.send_message(message.from_user.id, f"⭐ تم ترقية المستخدم `{target_id}` للمميز.", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "⭐ تهانينا! تمت ترقيتك لحساب مميز.")
        except:
            pass
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def demote_premium_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if target_id in stats.get("premium_users", []):
            stats["premium_users"].remove(target_id)
            save_json(STATS_FILE, stats)
            bot.send_message(message.from_user.id, f"✅ تم إلغاء الاشتراك المميز للمستخدم `{target_id}`", parse_mode="Markdown")
        else:
            bot.send_message(message.from_user.id, "⚠️ المستخدم ليس مميزاً.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def broadcast_all_step(message):
    if not is_admin(message.from_user.id):
        return
    text = message.text
    count, failed = 0, 0
    for uid in list(users.keys()):
        try:
            bot.send_message(uid, text)
            count += 1
        except:
            failed += 1
    bot.send_message(message.from_user.id, f"📢 *تم الإرسال:*\n✅ نجح: `{count}`\n❌ فشل: `{failed}`", parse_mode="Markdown")

def broadcast_country_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل الدولة ثم الرسالة في سطرين.")
        return
    country, text = lines[0].strip(), lines[1].strip()
    count = 0
    for uid, info in list(users.items()):
        if info.get("country") == country:
            try:
                bot.send_message(uid, text)
                count += 1
            except:
                pass
    bot.send_message(message.from_user.id, f"✅ تم الإرسال لـ `{count}` مستخدم في {country}", parse_mode="Markdown")

def broadcast_lang_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل اللغة ثم الرسالة في سطرين.")
        return
    lang, text = lines[0].strip(), lines[1].strip()
    count = 0
    for uid, info in list(users.items()):
        if info.get("lang") == lang:
            try:
                bot.send_message(uid, text)
                count += 1
            except:
                pass
    bot.send_message(message.from_user.id, f"✅ تم الإرسال لـ `{count}` مستخدم يتحدث {lang}", parse_mode="Markdown")

def broadcast_premium_step(message):
    if not is_admin(message.from_user.id):
        return
    text = message.text
    count = 0
    for uid in stats.get("premium_users", []):
        try:
            bot.send_message(uid, text)
            count += 1
        except:
            pass
    bot.send_message(message.from_user.id, f"⭐ تم الإرسال لـ `{count}` مستخدم مميز", parse_mode="Markdown")

def pause_bot_step(message):
    global bot_paused, pause_message
    if message.text.strip() != "افتراضي":
        pause_message = message.text.strip()
    bot_paused = True
    bot.send_message(message.from_user.id, "🔴 تم إيقاف البوت مؤقتاً.\nأرسل /admin ثم 'إيقاف/تشغيل البوت' لإعادة التشغيل.")

def rss_add_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل اللغة ثم الرابط في سطرين.")
        return
    lang, url = lines[0].strip(), lines[1].strip()
    if lang not in RSS:
        RSS[lang] = []
    RSS[lang].append(url)
    save_rss()
    bot.send_message(message.from_user.id, f"✅ تم إضافة المصدر لـ {lang}")

def rss_remove_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل اللغة ثم رقم المصدر في سطرين.")
        return
    lang = lines[0].strip()
    try:
        index = int(lines[1].strip()) - 1
        if lang in RSS and 0 <= index < len(RSS[lang]):
            removed = RSS[lang].pop(index)
            save_rss()
            bot.send_message(message.from_user.id, f"✅ تم حذف المصدر:\n{removed}")
        else:
            bot.send_message(message.from_user.id, "❌ رقم أو لغة غير صحيحة.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def change_welcome_step(message):
    global welcome_override
    if message.text.strip() == "افتراضي":
        welcome_override = None
        bot.send_message(message.from_user.id, "✅ تم الرجوع لرسالة الترحيب الافتراضية.")
    else:
        welcome_override = message.text.strip()
        bot.send_message(message.from_user.id, "✅ تم تغيير رسالة الترحيب.")

# ======== رسالة الترحيب الأولى ========
def send_first_time_welcome(uid, name):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 تواصل مع الدعم", url=CONTACT_LINK))
    text = (
        f"🎉 *أهلاً {name}!*\n\n"
        "شكراً لانضمامك إلى *World News & Weather Bot* 🌍\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔰 *ماذا يقدم لك البوت؟*\n\n"
        "📰 أخبار عالمية لحظية من أكبر المصادر\n"
        "🌤 حالة الطقس الآنية لمدينتك\n"
        "💱 أسعار العملات مباشرة\n"
        "🔍 بحث ذكي في الأخبار\n"
        "🔔 إشعارات تلقائية كل ساعة\n"
        "⭐ اشتراك مميز بمزايا حصرية\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 *ابدأ بتحديد لغتك من القائمة أدناه*\n\n"
        f"💬 للتواصل أو الدعم: {CONTACT_LINK}"
    )
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=markup)

# ======== رسالة الترحيب (اختيار اللغة) ========
def welcome_user(uid):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages.values():
        markup.add(lang)
    inline_markup = types.InlineKeyboardMarkup()
    inline_markup.add(types.InlineKeyboardButton("💬 تواصل / Contact", url=CONTACT_LINK))
    text = welcome_override if welcome_override else (
        "🌍 *World News & Weather Bot*\n\n"
        "👋 أهلاً وسهلاً بك\n"
        "👋 Welcome!\n\n"
        "📰 آخر أخبار العالم من مصادر موثوقة\n"
        "📰 Latest world news from trusted sources\n\n"
        "🌤 حالة الطقس في مدينتك\n"
        "🌤 Weather updates for your city\n\n"
        "🌐 البوت يدعم 12 لغة حول العالم\n"
        "🌐 The bot supports 12 languages worldwide\n\n"
        "👇 اختر لغتك للمتابعة\n"
        "👇 Choose your language to continue\n\n"
        f"💬 للتواصل: {CONTACT_LINK}"
    )
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=markup)
    bot.send_message(uid, "💬 تواصل معنا مباشرة:", reply_markup=inline_markup)

# ======== تلميح الاستخدام ========
def send_usage_hint(uid, lang):
    hint = USAGE_HINTS.get(lang, USAGE_HINTS["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 تواصل / Contact", url=CONTACT_LINK))
    bot.send_message(uid, hint, parse_mode="Markdown", reply_markup=markup)

# ======== القائمة الرئيسية ========
def send_main_menu(uid):
    lang = users[str(uid)].get("lang", "English 🇬🇧")
    btn = BUTTONS.get(lang, BUTTONS["English 🇬🇧"])
    notif_on = users[str(uid)].get("notifications", True)
    notif_label = btn["notif_on"] if notif_on else btn["notif_off"]
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        btn["weather"], btn["forecast"],
        btn["news"], btn["sports"],
        btn["mena_politics"], btn["news_cats"],
        btn["daily_summary"], btn["weekly_summary"],
        btn["currency"], btn["dollar_parallel"],
        btn["convert"],
        btn["crypto"], btn["track_asset"],
        btn["prayer"],
        btn["search"], btn["my_stats"],
        btn["referral"], btn["top_referrers"],
        btn["share_bot"],
        notif_label, btn["premium"],
        btn["settings"]
    )
    inline_markup = types.InlineKeyboardMarkup()
    inline_markup.add(types.InlineKeyboardButton("💬 تواصل / Contact", url=CONTACT_LINK))
    bot.send_message(uid, btn["choose"], reply_markup=markup)
    bot.send_message(uid, f"💬 {CONTACT_LINK}", reply_markup=inline_markup)

# ======== أسعار العملات ========
def send_currency(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧")
    local_code, local_name = CURRENCY_MAP.get(lang, ("EUR", "Euro"))
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        rates = r.get("rates", {})
        local_rate = rates.get(local_code, t(lang, "track_unavailable"))
        eur = rates.get("EUR", "-")
        gbp = rates.get("GBP", "-")
        iqd = rates.get("IQD", "-")
        try_rate = rates.get("TRY", "-")
        sar = rates.get("SAR", "-")
        msg = (
            f"{t(lang, 'currency_rate_header')}"
            f"{t(lang, 'currency_local_label').format(name=local_name)}: `{local_rate}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"{t(lang, 'currency_eur')}: `{eur}`\n"
            f"{t(lang, 'currency_gbp')}: `{gbp}`\n"
            f"{t(lang, 'currency_iqd')}: `{iqd}`\n"
            f"{t(lang, 'currency_try')}: `{try_rate}`\n"
            f"{t(lang, 'currency_sar')}: `{sar}`\n"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "currency_error"))
        notify_admin_error(f"خطأ في أسعار العملات: {e}")

# ======== بحث في الأخبار (عنوان فقط — بدون رابط أو مصدر) ========
def search_news(uid, query):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    try:
        url = f"https://newsapi.org/v2/everything?q={query}&language={lang_code}&pageSize=5&apiKey={NEWS_KEY}"
        r = requests.get(url, timeout=10).json()
        articles = r.get("articles", [])
        if not articles:
            bot.send_message(uid, t(lang, "search_no_results") or t(lang, "no_results"))
            return
        bot.send_message(uid, t(lang, "search_results_header").format(query=query), parse_mode="Markdown")
        for article in articles[:5]:
            title = article.get("title", "")
            link = article.get("url", "")
            if title:
                if link:
                    art_summary = article.get("description", "") or article.get("content", "")
                    markup = make_news_share_markup(link, title, lang, art_summary)
                    bot.send_message(uid, f"📰 {title}", parse_mode="Markdown", reply_markup=markup)
                else:
                    bot.send_message(uid, f"📰 {title}", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "search_error"))
        notify_admin_error(f"خطأ في البحث: {e}")

def send_trending_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    try:
        url = f"https://newsapi.org/v2/top-headlines?language={lang_code}&pageSize=8&sortBy=popularity&apiKey={NEWS_KEY}"
        r = requests.get(url, timeout=10).json()
        articles = r.get("articles", [])
        if not articles:
            feeds = RSS.get(lang, [])
            if feeds:
                try:
                    feed = feedparser.parse(feeds[0])
                    articles_rss = feed.entries[:8]
                    bot.send_message(uid, t(lang, "trending_header"), parse_mode="Markdown")
                    for item in articles_rss:
                        title = getattr(item, 'title', '')
                        link = getattr(item, 'link', '')
                        if title and link:
                            item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                            markup = make_news_share_markup(link, title, lang, item_sum)
                            bot.send_message(uid, format_news_item(t(lang, "label_trending"), title), parse_mode="Markdown", reply_markup=markup)
                    return
                except:
                    pass
            bot.send_message(uid, t(lang, "no_trending"))
            return
        bot.send_message(uid, t(lang, "trending_header"), parse_mode="Markdown")
        for article in articles[:8]:
            title = article.get("title", "")
            link = article.get("url", "")
            if title and link:
                art_sum = article.get("description", "") or article.get("content", "")
                markup = make_news_share_markup(link, title, lang, art_sum)
                bot.send_message(uid, format_news_item(t(lang, "label_trending"), title), parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        bot.send_message(uid, t(lang, "no_trending"))
        notify_admin_error(f"خطأ في الأخبار الرائجة: {e}")

def send_premium_upgrade(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    msg = PREMIUM_UPGRADE_MSG.get(lang, PREMIUM_UPGRADE_MSG["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(t(lang, "premium_subscribe_btn"), callback_data=f"req_premium_{uid}"))
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

def send_premium_menu(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(t(lang, "premium_btn_7day"), callback_data="prem_7day"),
        types.InlineKeyboardButton(t(lang, "premium_btn_hourly"), callback_data="prem_hourly"),
        types.InlineKeyboardButton(t(lang, "premium_btn_addcity"), callback_data="prem_addcity"),
        types.InlineKeyboardButton(t(lang, "premium_btn_mycities"), callback_data="prem_mycities"),
        types.InlineKeyboardButton(t(lang, "premium_btn_interests"), callback_data="prem_interests"),
        types.InlineKeyboardButton(t(lang, "premium_btn_currency_alert"), callback_data="prem_currency_alert"),
        types.InlineKeyboardButton(t(lang, "premium_btn_currency_table"), callback_data="prem_currency_table"),
        types.InlineKeyboardButton(t(lang, "premium_btn_notif_time"), callback_data="prem_notif_time"),
        types.InlineKeyboardButton(t(lang, "premium_btn_weekly"), callback_data="prem_weekly"),
        types.InlineKeyboardButton(t(lang, "premium_btn_keywords"), callback_data="prem_keywords"),
    )
    bot.send_message(uid, t(lang, "premium_menu_header"), parse_mode="Markdown", reply_markup=markup)

def send_7day_forecast(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    cities = [user.get("province", "")] + user.get("extra_cities", [])
    cities = [c for c in cities if c]
    for city in cities[:3]:
        try:
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_KEY}&units=metric&lang={lang_code}&cnt=40"
            data = requests.get(url, timeout=10).json()
            if str(data.get("cod")) != "200":
                continue
            days = {}
            for item in data["list"]:
                date = item["dt_txt"].split(" ")[0]
                if date not in days:
                    days[date] = {"temps": [], "desc": item["weather"][0]["description"]}
                days[date]["temps"].append(item["main"]["temp"])
            msg = t(lang, "forecast_7day_header").format(city=city)
            for date, info in list(days.items())[:7]:
                min_t = round(min(info["temps"]))
                max_t = round(max(info["temps"]))
                msg += f"📅 {date}: {min_t}°C — {max_t}°C | {info['desc']}\n"
            bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception as e:
            notify_admin_error(f"خطأ في توقعات 7 أيام ({city}): {e}")

def get_weather_emoji(weather_id):
    if weather_id < 300:
        return "⚡"
    elif weather_id < 500:
        return "🌦"
    elif weather_id < 600:
        return "🌧"
    elif weather_id < 700:
        return "❄️"
    elif weather_id < 800:
        return "🌫"
    elif weather_id == 800:
        return "☀️"
    elif weather_id < 803:
        return "🌤"
    else:
        return "☁️"

def get_uv_level(uvi, lang="English 🇬🇧"):
    if uvi is None:
        return t(lang, "uv_na")
    uvi = float(uvi)
    if uvi < 3:
        return f"{uvi:.1f} 🟢 {t(lang, 'uv_low')}"
    elif uvi < 6:
        return f"{uvi:.1f} 🟡 {t(lang, 'uv_moderate')}"
    elif uvi < 8:
        return f"{uvi:.1f} 🟠 {t(lang, 'uv_high')}"
    elif uvi < 11:
        return f"{uvi:.1f} 🔴 {t(lang, 'uv_very_high')}"
    else:
        return f"{uvi:.1f} 🟣 {t(lang, 'uv_extreme')}"

def get_wind_direction(deg, lang="English 🇬🇧"):
    keys = ["wind_N", "wind_NE", "wind_E", "wind_SE",
            "wind_S", "wind_SW", "wind_W", "wind_NW"]
    if deg is None:
        return "-"
    return t(lang, keys[round(deg / 45) % 8])

def send_detailed_weather(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    province = user.get("province", "")
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
        data = requests.get(url, timeout=10).json()
        if data.get("cod") != 200:
            bot.send_message(uid, t(lang, "city_not_found").format(city=province))
            return
        temp = round(data['main']['temp'], 1)
        feels = round(data['main']['feels_like'], 1)
        temp_min = round(data['main']['temp_min'], 1)
        temp_max = round(data['main']['temp_max'], 1)
        humidity = data['main']['humidity']
        pressure = data['main']['pressure']
        desc = data['weather'][0]['description'].capitalize()
        weather_id = data['weather'][0]['id']
        weather_emoji = get_weather_emoji(weather_id)
        wind_speed = data['wind']['speed']
        wind_deg = data['wind'].get('deg')
        wind_gust = data['wind'].get('gust', '-')
        visibility = data.get('visibility', 0)
        visibility_km = round(visibility / 1000, 1) if visibility else '-'
        clouds = data['clouds']['all']
        sunrise_ts = data['sys'].get('sunrise', 0)
        sunset_ts = data['sys'].get('sunset', 0)
        sunrise = datetime.datetime.fromtimestamp(sunrise_ts).strftime("%H:%M") if sunrise_ts else "-"
        sunset = datetime.datetime.fromtimestamp(sunset_ts).strftime("%H:%M") if sunset_ts else "-"
        lat = data['coord']['lat']
        lon = data['coord']['lon']
        try:
            one_call_url = f"https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={lon}&exclude=minutely,hourly,daily,alerts&appid={WEATHER_KEY}&units=metric"
            one_call = requests.get(one_call_url, timeout=5).json()
            uvi = one_call.get('current', {}).get('uvi')
        except:
            uvi = None
        msg = t(lang, "weather_header").format(
            emoji=weather_emoji, city=province, temp=temp, feels=feels,
            temp_max=temp_max, temp_min=temp_min, desc=desc, clouds=clouds,
            visibility_km=visibility_km, humidity=humidity, pressure=pressure,
            uvi=get_uv_level(uvi, lang),
            wind_speed=wind_speed, wind_dir=get_wind_direction(wind_deg, lang),
            wind_gust=wind_gust, sunrise=sunrise, sunset=sunset
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "weather_error"))
        notify_admin_error(f"خطأ في الطقس لـ {uid}: {e}")

def add_extra_city(uid, city):
    users[str(uid)].setdefault("extra_cities", [])
    if city not in users[str(uid)]["extra_cities"]:
        users[str(uid)]["extra_cities"].append(city)
    _db_save_all_users(users)
    bot.send_message(uid, f"✅ تمت إضافة مدينة: *{city}*", parse_mode="Markdown")

def send_hourly_weather_forecast(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    province = user.get("province", "")
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}&cnt=8"
        data = requests.get(url, timeout=10).json()
        if str(data.get("cod")) != "200":
            bot.send_message(uid, t(lang, "forecast_error"))
            return
        msg = t(lang, "hourly_header").format(city=province)
        wind_unit = t(lang, "wind_unit")
        for item in data["list"][:8]:
            time_str = item["dt_txt"].split(" ")[1][:5]
            date_str = item["dt_txt"].split(" ")[0][5:]
            temp = round(item["main"]["temp"], 1)
            desc = item["weather"][0]["description"].capitalize()
            wid = item["weather"][0]["id"]
            emoji = get_weather_emoji(wid)
            humidity = item["main"]["humidity"]
            wind = item["wind"]["speed"]
            msg += f"{emoji} *{date_str} | {time_str}*\n"
            msg += f"   🌡 {temp}°C | {desc}\n"
            msg += f"   💧 {humidity}% | 💨 {wind} {wind_unit}\n\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "forecast_error"))
        notify_admin_error(f"خطأ في الطقس الساعي لـ {uid}: {e}")

def send_full_currency_table(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        rates = r.get("rates", {})
        pairs = [
            ("🇪🇺", "EUR"), ("🇬🇧", "GBP"), ("🇮🇶", "IQD"),
            ("🇸🇦", "SAR"), ("🇦🇪", "AED"), ("🇹🇷", "TRY"),
            ("🇮🇷", "IRR"), ("🇷🇺", "RUB"), ("🇵🇰", "PKR"),
            ("🇮🇳", "INR"), ("🇧🇷", "BRL"), ("🇲🇽", "MXN"),
            ("🇨🇳", "CNY"), ("🇯🇵", "JPY"), ("🇨🇦", "CAD"),
            ("🇦🇺", "AUD"), ("🇰🇼", "KWD"), ("🇪🇬", "EGP"),
            ("🇯🇴", "JOD"), ("🇵🇱", "PLN"), ("🇨🇭", "CHF"),
            ("🇸🇬", "SGD"), ("🇿🇦", "ZAR"), ("🇳🇬", "NGN"),
        ]
        msg = t(lang, "currency_table_header")
        for flag, code in pairs:
            rate = rates.get(code, "-")
            msg += f"{flag} {code}: `{rate}`\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "currency_error"))
        notify_admin_error(f"خطأ في جدول العملات: {e}")

def send_weekly_news_summary(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    headlines = []
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:5]:
                title = getattr(item, 'title', '')
                if title:
                    headlines.append(title)
            if len(headlines) >= 20:
                break
        except:
            pass
    if not headlines:
        bot.send_message(uid, t(lang, "no_weekly"))
        return
    count = min(len(headlines), 20)
    msg = t(lang, "weekly_summary_header").format(count=count)
    for i, title in enumerate(headlines[:20], 1):
        msg += f"{i}. {title}\n\n"
    bot.send_message(uid, msg, parse_mode="Markdown")

def send_interest_menu(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "العربية 🇮🇶")
    options = INTERESTS.get(lang, INTERESTS["English 🇬🇧"])
    current = user.get("interests", [])
    markup = types.InlineKeyboardMarkup(row_width=2)
    for opt in options:
        check = "✅ " if opt in current else ""
        markup.add(types.InlineKeyboardButton(f"{check}{opt}", callback_data=f"interest_{opt}"))
    markup.add(types.InlineKeyboardButton("💾 حفظ", callback_data="interest_save"))
    bot.send_message(uid, "📌 *اختر اهتماماتك (يمكن أكثر من واحد):*", parse_mode="Markdown", reply_markup=markup)

def set_currency_alert_step(message):
    uid = message.from_user.id
    try:
        rate = float(message.text.strip())
        users[str(uid)]["currency_alert"] = rate
        _db_save_all_users(users)
        bot.send_message(uid, f"✅ سيتم تنبيهك عند وصول الدولار إلى `{rate}` من عملتك المحلية.", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ أرسل رقماً صحيحاً مثل: 1600")

def set_notif_time_step(message):
    uid = message.from_user.id
    try:
        hour = int(message.text.strip())
        if not (0 <= hour <= 23):
            raise ValueError
        users[str(uid)]["notif_hour"] = hour
        _db_save_all_users(users)
        bot.send_message(uid, f"✅ سيتم إرسال الملخص الصباحي في الساعة *{hour}:00* يومياً.", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ أرسل رقماً بين 0 و 23 (مثال: 8 للساعة 8 صباحاً)")

def news_matches_interests(title, interests):
    if not interests:
        return True
    title_lower = title.lower()
    for interest in interests:
        key = interest.split(" ", 1)[-1].lower()
        keywords = INTEREST_KEYWORDS.get(key, [])
        for kw in keywords:
            if kw.lower() in title_lower:
                return True
    return False

def is_blacklisted(title):
    if not blacklist_words:
        return False
    title_lower = title.lower()
    for word in blacklist_words:
        if word.lower() in title_lower:
            return True
    return False

def broadcast_premium_instant_news():
    try:
        rss_cache = {}
        for uid, info in list(users.items()):
            try:
                if not is_premium(uid):
                    continue
                if int(uid) in banned:
                    continue
                if not info.get("notifications", True):
                    continue
                lang = info.get("lang", "English 🇬🇧")
                feeds = RSS.get(lang, [])
                sent = info.setdefault("sent_news", set())
                interests = info.get("interests", [])
                changed = False
                for feed_url in feeds:
                    if feed_url not in rss_cache:
                        try:
                            rss_cache[feed_url] = feedparser.parse(feed_url)
                        except Exception:
                            rss_cache[feed_url] = None
                    feed = rss_cache.get(feed_url)
                    if not feed:
                        continue
                    for item in feed.entries[:5]:
                        if not hasattr(item, 'link') or item.link in sent:
                            continue
                        if not news_matches_interests(item.title, interests):
                            continue
                        sent.add(item.link)
                        changed = True
                        link = getattr(item, 'link', '')
                        title = getattr(item, 'title', '')
                        item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                        markup = make_news_share_markup(link, title, lang, item_sum)
                        queue_send(uid, format_news_item(t(lang, "label_breaking"), title),
                            parse_mode="Markdown", reply_markup=markup)
                if changed:
                    _db_save_user(uid, info)
            except Exception:
                continue
    except Exception as e:
        try:
            bot.send_message(ADMIN_ID, f"⚠️ خطأ في broadcast_premium_instant_news: {e}")
        except Exception:
            pass

def send_morning_summary():
    now_hour = datetime.datetime.now().hour
    for uid, info in list(users.items()):
        if not is_premium(uid):
            continue
        if int(uid) in banned:
            continue
        notif_hour = info.get("notif_hour", 8)
        if now_hour != notif_hour:
            continue
        lang = info.get("lang", "English 🇬🇧")
        feeds = RSS.get(lang, [])
        headlines = []
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for item in feed.entries[:3]:
                    if hasattr(item, 'title'):
                        headlines.append(f"• {item.title}")
                if len(headlines) >= 10:
                    break
            except:
                pass
        if headlines:
            msg = "🌅 *ملخص صباحي — أبرز الأخبار*\n\n" + "\n".join(headlines[:10])
            try:
                bot.send_message(uid, msg, parse_mode="Markdown")
            except:
                pass

def check_weather_alerts():
    for uid, info in list(users.items()):
        if not is_premium(uid):
            continue
        if int(uid) in banned:
            continue
        province = info.get("province")
        if not province:
            continue
        lang = info.get("lang", "English 🇬🇧")
        lang_code = LANG_CODES.get(lang, "en")
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
            data = requests.get(url, timeout=10).json()
            if data.get("cod") != 200:
                continue
            temp = data['main']['temp']
            weather_id = data['weather'][0]['id']
            desc = data['weather'][0]['description']
            if temp >= 45:
                bot.send_message(uid, f"🔥 *تنبيه حرارة شديدة!*\nدرجة الحرارة في {province}: *{temp}°C*\nكن حذراً!", parse_mode="Markdown")
            elif weather_id < 700:
                bot.send_message(uid, f"🌧 *تنبيه طقس!*\n{province}: {desc}", parse_mode="Markdown")
        except Exception as e:
            notify_admin_error(f"خطأ في تنبيهات الطقس: {e}")

def check_currency_alerts():
    alerted_users = [uid for uid, info in users.items() if "currency_alert" in info and is_premium(uid)]
    if not alerted_users:
        return
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        rates = r.get("rates", {})
        for uid in alerted_users:
            info = users[uid]
            lang = info.get("lang", "English 🇬🇧")
            local_code, local_name = CURRENCY_MAP.get(lang, ("EUR", "Euro"))
            current_rate = rates.get(local_code)
            target = info.get("currency_alert")
            if current_rate and target:
                last = info.get("currency_alert_last", 0)
                if abs(current_rate - target) <= target * 0.01 and abs(current_rate - last) > target * 0.005:
                    users[uid]["currency_alert_last"] = current_rate
                    _db_save_all_users(users)
                    bot.send_message(int(uid), f"💱 *تنبيه العملة!*\nوصل الدولار إلى `{current_rate}` {local_name}", parse_mode="Markdown")
    except Exception as e:
        notify_admin_error(f"خطأ في تنبيهات العملة: {e}")

# ======== /start ========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    if uid in banned:
        bot.send_message(uid, "🚫 أنت محظور من استخدام البوت.")
        return
    if bot_paused and not is_admin(uid):
        bot.send_message(uid, pause_message)
        return
    username = message.from_user.username or "لا يوزر"
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
        except:
            pass
    is_new = str(uid) not in users
    if is_new:
        users[str(uid)] = {"name": message.from_user.first_name, "sent_news": set(), "first_visit": True, "referrals": [], "join_date": datetime.datetime.now().strftime("%Y-%m-%d")}
        if referrer_id and referrer_id != uid and str(referrer_id) in users:
            users[str(uid)]["referred_by"] = referrer_id
            users[str(referrer_id)].setdefault("referrals", [])
            if uid not in users[str(referrer_id)]["referrals"]:
                users[str(referrer_id)]["referrals"].append(uid)
                ref_total = len(users[str(referrer_id)]["referrals"])
                next_m = next((m for m in REFERRAL_MILESTONES if m > ref_total), None)
                progress_txt = f"\n🎯 تحتاج {next_m - ref_total} دعوة أخرى للمكافأة القادمة!" if next_m else "\n🏆 وصلت لأعلى مستوى!"
                try:
                    bot.send_message(referrer_id,
                        f"🎉 *انضم شخص جديد عبر رابطك!*\n"
                        f"👤 الاسم: {message.from_user.first_name}\n"
                        f"👥 إجمالي دعواتك: `{ref_total}`"
                        f"{progress_txt}",
                        parse_mode="Markdown"
                    )
                except:
                    pass
                check_referral_rewards(referrer_id, message.from_user.first_name)
        _db_save_all_users(users)
        update_stats("new_user", uid=uid)
        all_admins = [ADMIN_ID] + extra_admins
        referrer_name = None
        if referrer_id and str(referrer_id) in users:
            referrer_name = users[str(referrer_id)].get("name", str(referrer_id))
        join_time = datetime.datetime.now().strftime("%H:%M - %d/%m/%Y")
        new_user_msg = (
            f"🆕 *مستخدم جديد انضم!*\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 الاسم: *{message.from_user.first_name}*\n"
            f"🆔 ID: `{uid}`\n"
            f"📛 اليوزر: @{username}\n"
            f"⏰ وقت الانضمام: `{join_time}`\n"
            f"👈 جاء عبر: {('دعوة من *' + referrer_name + '*') if referrer_name else 'مباشر'}\n"
            f"━━━━━━━━━━━━━━\n"
            f"👥 إجمالي المستخدمين: `{len(users)}`"
        )
        quick_markup = types.InlineKeyboardMarkup(row_width=2)
        quick_markup.add(
            types.InlineKeyboardButton("👤 عرض ملفه", callback_data=f"admin_view_{uid}"),
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{uid}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={uid}"),
        )
        for admin_id in all_admins:
            try:
                bot.send_message(admin_id, new_user_msg, parse_mode="Markdown", reply_markup=quick_markup)
            except:
                pass
        send_first_time_welcome(uid, message.from_user.first_name)
        welcome_user(uid)
    else:
        users[str(uid)]["name"] = message.from_user.first_name
        _db_save_all_users(users)
        user = users[str(uid)]
        if "province" in user:
            send_main_menu(uid)
        else:
            welcome_user(uid)

# ======== دوال الرسائل والتقييم والنشاط ========
def _forward_to_admin(m):
    uid = m.from_user.id
    user = users.get(str(uid), {})
    name = getattr(m.from_user, "first_name", "مجهول")
    utype = is_premium(uid)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = {
        "uid": uid,
        "name": name,
        "text": m.text or "",
        "premium": utype,
        "time": ts,
        "lang": user.get("lang", "-"),
        "country": user.get("country", "-"),
    }
    inbox_messages.append(entry)
    save_inbox()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"↩️ رد على {name}", callback_data=f"admin_reply_{uid}"))
    utype_label = "⭐ مميز" if utype else "👤 عادي"
    try:
        bot.send_message(ADMIN_ID,
            f"💬 *رسالة جديدة من مستخدم*\n\n"
            f"👤 الاسم: {name}\n"
            f"🆔 `{uid}` | {utype_label}\n"
            f"🌍 {user.get('country', '-')} | 🗣 {user.get('lang', '-')}\n"
            f"🕐 {ts}\n\n"
            f"📩 {m.text}",
            parse_mode="Markdown", reply_markup=markup)
    except Exception:
        pass

def _update_last_seen(uid):
    u = users.get(str(uid))
    if u:
        u["last_seen"] = datetime.datetime.now().strftime("%Y-%m-%d")
        _db_save_user(uid, u)

def send_rating_request():
    for uid, info in list(users.items()):
        try:
            if int(uid) in banned:
                continue
            if not info.get("notifications", True):
                continue
            if info.get("rating_sent_today"):
                continue
            markup = types.InlineKeyboardMarkup(row_width=5)
            markup.add(
                types.InlineKeyboardButton("1⭐", callback_data=f"rate_bot_1_{uid}"),
                types.InlineKeyboardButton("2⭐", callback_data=f"rate_bot_2_{uid}"),
                types.InlineKeyboardButton("3⭐", callback_data=f"rate_bot_3_{uid}"),
                types.InlineKeyboardButton("4⭐", callback_data=f"rate_bot_4_{uid}"),
                types.InlineKeyboardButton("5⭐", callback_data=f"rate_bot_5_{uid}"),
            )
            markup2 = types.InlineKeyboardMarkup(row_width=5)
            markup2.add(
                types.InlineKeyboardButton("1⭐", callback_data=f"rate_news_1_{uid}"),
                types.InlineKeyboardButton("2⭐", callback_data=f"rate_news_2_{uid}"),
                types.InlineKeyboardButton("3⭐", callback_data=f"rate_news_3_{uid}"),
                types.InlineKeyboardButton("4⭐", callback_data=f"rate_news_4_{uid}"),
                types.InlineKeyboardButton("5⭐", callback_data=f"rate_news_5_{uid}"),
            )
            bot.send_message(int(uid),
                "⭐ *كيف تقيّم البوت اليوم؟*\n\nاختر عدد النجوم:",
                parse_mode="Markdown", reply_markup=markup)
            bot.send_message(int(uid),
                "📰 *كيف تقيّم أخبار اليوم؟*\n\nاختر عدد النجوم:",
                parse_mode="Markdown", reply_markup=markup2)
            info["rating_sent_today"] = True
            _db_save_user(uid, info)
        except Exception:
            continue

def check_inactive_users():
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    for uid, info in list(users.items()):
        try:
            if int(uid) in banned:
                continue
            last_seen = info.get("last_seen", info.get("join_date", ""))
            if last_seen and last_seen < cutoff:
                reminders = info.get("inactive_reminders", 0)
                if reminders >= 2:
                    continue
                bot.send_message(int(uid),
                    "👋 *مرحباً، اشتقنا إليك!*\n\n"
                    "📰 لا تفوت آخر أخبار الشرق الأوسط.\n"
                    "اضغط /start للعودة للبوت.",
                    parse_mode="Markdown")
                info["inactive_reminders"] = reminders + 1
                _db_save_user(uid, info)
        except Exception:
            continue

def check_summary_hint():
    for uid, info in list(users.items()):
        try:
            if int(uid) in banned:
                continue
            if info.get("summary_hint_sent"):
                continue
            if info.get("used_summary"):
                continue
            join = info.get("join_date", "")
            if join:
                joined = datetime.datetime.strptime(join, "%Y-%m-%d")
                if (datetime.datetime.now() - joined).days >= 3:
                    bot.send_message(int(uid),
                        "📖 *هل تعلم؟*\n\n"
                        "يمكنك الحصول على ملخص يومي للأخبار!\n"
                        "اضغط على زر *📋 ملخص اليوم* من القائمة الرئيسية.",
                        parse_mode="Markdown")
                    info["summary_hint_sent"] = True
                    _db_save_user(uid, info)
        except Exception:
            continue

def reset_daily_rating_flags():
    for uid, info in list(users.items()):
        if info.get("rating_sent_today"):
            info["rating_sent_today"] = False

# ======== التعامل مع الرسائل ========
@bot.message_handler(func=lambda m: True)
def handle_selection(m):
    uid = m.from_user.id
    text = m.text
    _update_last_seen(uid)
    if uid in banned:
        return
    if bot_paused and not is_admin(uid):
        bot.send_message(uid, pause_message)
        return
    user = users.get(str(uid))
    if not user:
        bot.send_message(uid, "👋 الرجاء إرسال /start أولاً.")
        return
    lang = user.get("lang", "English 🇬🇧")
    btn = BUTTONS.get(lang, BUTTONS["English 🇬🇧"])

    if user_states.get(uid) == "searching":
        user_states.pop(uid, None)
        search_news(uid, text)
        return

    if user_states.get(uid) == "converting_currency":
        user_states.pop(uid, None)
        parts = text.strip().split()
        if len(parts) >= 2:
            try:
                amount = float(parts[0].replace(",", ""))
                currency = parts[1].upper()
                convert_currency_msg(uid, amount, currency)
            except ValueError:
                bot.send_message(uid, st(lang, "convert_format_error"), parse_mode="Markdown")
        else:
            bot.send_message(uid, st(lang, "convert_send_both"), parse_mode="Markdown")
        return

    if user_states.get(uid) == "tracking_asset":
        user_states.pop(uid, None)
        symbol = text.strip().upper()
        if not symbol or len(symbol) > 15:
            bot.send_message(uid, "⚠️ رمز غير صحيح. أرسل مثال: AAPL أو BTC أو EUR")
            return
        existing = tracked_assets.get(str(uid), {}).get("assets", [])
        if symbol in existing:
            bot.send_message(uid, f"📌 *{symbol}* مضافة مسبقاً في قائمة التتبع.", parse_mode="Markdown")
        elif len(existing) >= 10:
            bot.send_message(uid, "⚠️ الحد الأقصى 10 أصول. أرسل /removetrack {رمز} لحذف واحدة.")
        else:
            price = fetch_asset_price(symbol)
            if price is None:
                bot.send_message(uid, f"⚠️ لم أتمكن من العثور على *{symbol}*. تأكد من الرمز وأعد المحاولة.", parse_mode="Markdown")
                return
            if str(uid) not in tracked_assets:
                tracked_assets[str(uid)] = {"assets": [], "last_prices": {}}
            tracked_assets[str(uid)]["assets"].append(symbol)
            tracked_assets[str(uid)]["last_prices"][symbol] = price
            save_tracked_assets()
            bot.send_message(uid,
                f"✅ تمت إضافة *{symbol}* للتتبع!\n"
                f"💰 السعر الحالي: `{price}`\n\n"
                f"🔔 ستصلك تنبيه عند تغير السعر بنسبة ±2%",
                parse_mode="Markdown"
            )
        return

    if user_states.get(uid) == "adding_keyword":
        user_states.pop(uid, None)
        if not is_premium(uid):
            bot.send_message(uid, "⭐ هذه الميزة للمشتركين المميزين فقط.")
            return
        if text.strip().startswith("حذف") or text.strip().startswith("delete"):
            user_keywords[str(uid)] = []
            save_keywords()
            bot.send_message(uid, "✅ تم حذف جميع كلماتك المفتاحية.")
        else:
            new_kws = [k.strip() for k in text.replace("،", ",").split(",") if k.strip()]
            existing = user_keywords.get(str(uid), [])
            for kw in new_kws:
                if kw not in existing:
                    existing.append(kw)
            user_keywords[str(uid)] = existing[:20]
            save_keywords()
            bot.send_message(uid, st(lang, "keywords_saved", n=len(new_kws)))
        return

    if "province" in user:
        update_stats("button", button=text)
        if text == btn["settings"]:
            users[str(uid)] = {"name": user["name"], "sent_news": set()}
            _db_save_all_users(users)
            welcome_user(uid)
        elif text == btn["weather"]:
            send_detailed_weather(uid)
        elif text == btn.get("forecast"):
            send_3day_forecast(uid)
        elif text == btn["news"]:
            send_hourly_news(uid)
        elif text == btn["all_news"]:
            send_all_news(uid)
        elif text == btn["mena_politics"]:
            send_mena_politics(uid)
        elif text == btn.get("trending"):
            send_trending_news(uid)
        elif text == btn.get("daily_summary"):
            send_daily_summary(uid)
        elif text == btn.get("news_cats"):
            send_interest_menu(uid)
        elif text == btn["currency"]:
            send_currency(uid)
        elif text == btn.get("crypto"):
            send_crypto_prices(uid)
        elif text == btn.get("prayer"):
            send_prayer_times(uid)
        elif text == btn["search"]:
            user_states[uid] = "searching"
            bot.send_message(uid, t(lang, "search_prompt"))
        elif text == btn.get("referral"):
            send_referral_stats(uid)
        elif text == btn.get("top_referrers"):
            send_top_referrers(uid)
        elif text == btn.get("sports"):
            send_sports_news(uid)
        elif text == btn.get("convert"):
            user_states[uid] = "converting_currency"
            bot.send_message(uid, st(lang, "convert_prompt"), parse_mode="Markdown")
        elif text == btn.get("my_stats"):
            send_my_stats(uid)
        elif text == btn.get("share_bot"):
            send_share_bot(uid)
        elif text == btn.get("public_stats"):
            send_public_stats(uid)
        elif text == btn.get("dollar_parallel"):
            send_dollar_parallel(uid)
        elif text == btn.get("weekly_summary"):
            send_weekly_summary_text(uid)
        elif text == btn.get("track_asset"):
            start_track_asset(uid)
        elif text in (btn["notif_on"], btn["notif_off"]):
            current = users[str(uid)].get("notifications", True)
            users[str(uid)]["notifications"] = not current
            _db_save_all_users(users)
            if not current:
                bot.send_message(uid, st(lang, "notif_enabled"))
            else:
                bot.send_message(uid, st(lang, "notif_disabled"))
            send_main_menu(uid)
        elif text == btn.get("premium", "⭐ Premium"):
            if is_premium(uid):
                send_premium_menu(uid)
            else:
                send_premium_upgrade(uid)
        else:
            _forward_to_admin(m)
            bot.send_message(uid, "✅ تم إرسال رسالتك للإدارة، سيتم الرد عليك قريباً.")
        return

    if "lang" not in user:
        for key, val in languages.items():
            if text == val:
                if val not in countries:
                    bot.send_message(uid, "⚠️ هذه اللغة غير متوفرة بالكامل. اختر لغة أخرى.")
                    return
                users[str(uid)]["lang"] = val
                user_feeds = RSS.get(val, [])
                users[str(uid)]["sent_news"] = prefill_sent_news(user_feeds)
                _db_save_all_users(users)
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[val]:
                    markup.add(country)
                bot.send_message(uid, st(val, "choose_country"), reply_markup=markup)
                send_usage_hint(uid, val)
                return
        bot.send_message(uid, "👇 Please choose a language from the list.")
        return

    if "country" not in user:
        lang = users[str(uid)].get("lang", lang)
        if lang in countries and text in countries[lang]:
            users[str(uid)]["country"] = text
            provinces = countries[lang][text]
            if provinces:
                _db_save_all_users(users)
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for prov in provinces:
                    markup.add(prov)
                bot.send_message(uid, st(lang, "choose_province"), reply_markup=markup)
            else:
                users[str(uid)]["province"] = text
                _db_save_all_users(users)
                update_stats("new_user", country=text, lang=lang)
                bot.send_message(uid, st(lang, "settings_saved"))
                send_main_menu(uid)
        else:
            bot.send_message(uid, st(lang, "choose_country_from_list"))
        return

    if "province" not in user:
        lang = users[str(uid)].get("lang", lang)
        country = user["country"]
        if lang in countries and country in countries[lang]:
            valid_provinces = countries[lang][country]
            if text in valid_provinces:
                users[str(uid)]["province"] = text
                _db_save_all_users(users)
                update_stats("new_user", country=country, lang=lang)
                bot.send_message(uid, st(lang, "settings_saved"))
                send_main_menu(uid)
            else:
                bot.send_message(uid, st(lang, "choose_province_from_list"))

BOT_SIGNATURE = "\n━━━━━━━━━━━━━━\nعبر بوت أخبار العالم\n@Iraqnowbot"

def get_news_signature():
    sep = news_settings.get("separator", "━━━━━━━━━━━━━━")
    sig = news_settings.get("signature", "عبر بوت أخبار العالم\n@Iraqnowbot")
    return f"\n{sep}\n{sig}"

# ======== نصوص أزرار مشاركة الأخبار حسب اللغة ========
NEWS_SHARE_LABELS = {
    "العربية 🇮🇶": {
        "open": "🔗 فتح الخبر",
        "share_news": "📤 شارك الخبر",
        "share_bot": "🤖 شارك البوت",
        "via": "عبر",
        "bot_promo": "بوت الأخبار والطقس\nآخر أخبار العالم والطقس والعملات على مدار الساعة!",
        "summary_btn": "📄 ملخص الخبر",
        "no_summary": "⚠️ لا يوجد ملخص متوفر لهذا الخبر."
    },
    "English 🇬🇧": {
        "open": "🔗 Open Article",
        "share_news": "📤 Share News",
        "share_bot": "🤖 Share Bot",
        "via": "via",
        "bot_promo": "News & Weather Bot\nLatest world news, weather & currency rates 24/7!",
        "summary_btn": "📄 Article Summary",
        "no_summary": "⚠️ No summary available for this article."
    },
    "Русский 🇷🇺": {
        "open": "🔗 Открыть статью",
        "share_news": "📤 Поделиться",
        "share_bot": "🤖 Поделиться ботом",
        "via": "через",
        "bot_promo": "Бот новостей и погоды\nПоследние мировые новости, погода и курсы валют!",
        "summary_btn": "📄 Краткое содержание",
        "no_summary": "⚠️ Краткое содержание недоступно."
    },
    "فارسی 🇮🇷": {
        "open": "🔗 باز کردن خبر",
        "share_news": "📤 اشتراکگذاری",
        "share_bot": "🤖 اشتراکگذاری ربات",
        "via": "از طریق",
        "bot_promo": "ربات اخبار و آبوهوا\nآخرین اخبار جهان، آبوهوا و نرخ ارز!",
        "summary_btn": "📄 خلاصه خبر",
        "no_summary": "⚠️ خلاصهای برای این خبر موجود نیست."
    },
    "हिन्दी 🇮🇳": {
        "open": "🔗 खबर खोलें",
        "share_news": "📤 शेयर करें",
        "share_bot": "🤖 बॉट शेयर करें",
        "via": "के द्वारा",
        "bot_promo": "न्यूज़ और मौसम बॉट\nताज़ा खबरें, मौसम और मुद्रा दरें!",
        "summary_btn": "📄 खबर सारांश",
        "no_summary": "⚠️ इस खबर का कोई सारांश उपलब्ध नहीं है।"
    },
    "Português 🇧🇷": {
        "open": "🔗 Abrir notícia",
        "share_news": "📤 Compartilhar",
        "share_bot": "🤖 Compartilhar bot",
        "via": "via",
        "bot_promo": "Bot de Notícias e Clima\nÚltimas notícias, clima e câmbio!",
        "summary_btn": "📄 Resumo da Notícia",
        "no_summary": "⚠️ Nenhum resumo disponível para esta notícia."
    },
    "Türkçe 🇹🇷": {
        "open": "🔗 Haberi Aç",
        "share_news": "📤 Paylaş",
        "share_bot": "🤖 Botu Paylaş",
        "via": "ile",
        "bot_promo": "Haber ve Hava Durumu Botu\nSon haberler, hava durumu ve döviz kurları!",
        "summary_btn": "📄 Haber Özeti",
        "no_summary": "⚠️ Bu haber için özet mevcut değil."
    },
    "اردو 🇵🇰": {
        "open": "🔗 خبر کھولیں",
        "share_news": "📤 شیئر کریں",
        "share_bot": "🤖 بوٹ شیئر کریں",
        "via": "کے ذریعے",
        "bot_promo": "خبر اور موسم بوٹ\nتازہ خبریں، موسم اور کرنسی ریٹ!",
        "summary_btn": "📄 خبر کا خلاصہ",
        "no_summary": "⚠️ اس خبر کا کوئی خلاصہ دستیاب نہیں۔"
    },
    "Deutsch 🇩🇪": {
        "open": "🔗 Artikel öffnen",
        "share_news": "📤 Teilen",
        "share_bot": "🤖 Bot teilen",
        "via": "über",
        "bot_promo": "Nachrichten- und Wetter-Bot\nAktuelle Nachrichten, Wetter und Wechselkurse!",
        "summary_btn": "📄 Artikel-Zusammenfassung",
        "no_summary": "⚠️ Keine Zusammenfassung für diesen Artikel verfügbar."
    },
    "Українська 🇺🇦": {
        "open": "🔗 Відкрити статтю",
        "share_news": "📤 Поділитися",
        "share_bot": "🤖 Поділитися ботом",
        "via": "через",
        "bot_promo": "Бот новин і погоди\nОстанні новини, погода та курси валют!",
        "summary_btn": "📄 Короткий зміст",
        "no_summary": "⚠️ Короткий зміст недоступний."
    },
    "Italiano 🇮🇹": {
        "open": "🔗 Apri articolo",
        "share_news": "📤 Condividi",
        "share_bot": "🤖 Condividi bot",
        "via": "tramite",
        "bot_promo": "Bot Notizie e Meteo\nUltime notizie, meteo e tassi di cambio!",
        "summary_btn": "📄 Riepilogo Articolo",
        "no_summary": "⚠️ Nessun riepilogo disponibile per questo articolo."
    },
    "Español 🇲🇽": {
        "open": "🔗 Abrir artículo",
        "share_news": "📤 Compartir",
        "share_bot": "🤖 Compartir bot",
        "via": "vía",
        "bot_promo": "Bot de Noticias y Clima\n¡Últimas noticias, clima y tipos de cambio!",
        "summary_btn": "📄 Resumen del Artículo",
        "no_summary": "⚠️ No hay resumen disponible para este artículo."
    },
}

# ======== رسائل النظام المترجمة ========
MSGS = {
    "العربية 🇮🇶": {
        "no_news": "⚠️ لا توجد أخبار جديدة الآن.",
        "no_results": "⚠️ لا توجد نتائج لهذا البحث.",
        "search_error": "⚠️ حدث خطأ أثناء البحث.",
        "no_trending": "⚠️ لا توجد أخبار رائجة الآن، حاول لاحقاً.",
        "trending_header": "🔥 *الأكثر تداولاً*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *أخبار الرياضة*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ لا توجد أخبار رياضية جديدة الآن.",
        "no_sports_source": "⚠️ لا توجد مصادر رياضية لهذه اللغة.",
        "no_mena": "⚠️ لا توجد أخبار سياسية جديدة الآن، حاول مرة أخرى لاحقاً.",
        "no_source": "⚠️ لا توجد مصادر أخبار لهذه اللغة حالياً.",
        "weather_error": "⚠️ لا يمكن جلب بيانات الطقس حالياً.",
        "forecast_error": "⚠️ لا يمكن جلب توقعات الساعات.",
        "no_weekly": "⚠️ لا توجد أخبار لإنشاء الملخص الأسبوعي.",
        "currency_error": "⚠️ لا يمكن جلب أسعار العملات حالياً.",
        "search_prompt": "🔍 اكتب كلمة البحث:",
        "label_breaking": "🚨 خبر عاجل",
        "label_news": "🚨 خبر",
        "label_mena": "📰 أخبار الشرق الأوسط السياسية",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ لم يتم تحديد مدينتك بعد.",
        "city_not_found": "⚠️ لم يتم العثور على بيانات الطقس لمدينة: {city}",
        "weather_header": "{emoji} *الطقس في {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *الحرارة:* {temp}°C\n🤔 *يشعر كـ:* {feels}°C\n🔼 أعلى: {temp_max}°C  |  🔽 أدنى: {temp_min}°C\n\n☁️ *الحالة:* {desc}\n🌫 *الغيوم:* {clouds}%\n👁 *الرؤية:* {visibility_km} كم\n\n💧 *الرطوبة:* {humidity}%\n🌀 *الضغط الجوي:* {pressure} hPa\n☀️ *مؤشر UV:* {uvi}\n\n💨 *الرياح:* {wind_speed} م/ث | {wind_dir}\n💨 *أقصى هبوب:* {wind_gust} م/ث\n\n🌅 *الشروق:* {sunrise}  |  🌇 *الغروب:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *توقعات الطقس لـ 3 أيام — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *توقعات الطقس لـ 7 أيام — {city}*\n\n",
        "hourly_header": "🕐 *الطقس كل 3 ساعات — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "م/ث",
        "uv_low": "منخفض",
        "uv_moderate": "متوسط",
        "uv_high": "مرتفع",
        "uv_very_high": "خطر",
        "uv_extreme": "شديد الخطورة",
        "uv_na": "غير متوفر",
        "wind_N": "⬆️ شمال",
        "wind_NE": "↗️ شمال شرق",
        "wind_E": "➡️ شرق",
        "wind_SE": "↘️ جنوب شرق",
        "wind_S": "⬇️ جنوب",
        "wind_SW": "↙️ جنوب غرب",
        "wind_W": "⬅️ غرب",
        "wind_NW": "↖️ شمال غرب",
        "crypto_header": "💎 *أسعار العملات الرقمية*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 البيانات من CoinGecko",
        "crypto_error": "⚠️ لا يمكن جلب أسعار العملات الرقمية الآن، حاول لاحقاً.",
        "prayer_header": "🕌 *أوقات الصلاة في {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 الفجر:     `{fajr}`\n☀️ الشروق:   `{sunrise}`\n🌞 الظهر:    `{dhuhr}`\n🌇 العصر:    `{asr}`\n🌆 المغرب:   `{maghrib}`\n🌙 العشاء:   `{isha}`\n━━━━━━━━━━━━━━━\n🔄 البيانات من Aladhan API",
        "prayer_no_city": "⚠️ لم يتم تحديد مدينتك. اضغط على تغيير الإعدادات وأعد الإعداد.",
        "prayer_city_error": "⚠️ لا يمكن جلب أوقات الصلاة لمدينة: {city}\nتأكد من اسم المدينة باللغة الإنجليزية في إعداداتك.",
        "prayer_error": "⚠️ لا يمكن جلب أوقات الصلاة الآن، حاول لاحقاً.",
        "referral_header": "🎁 *نظام الدعوات*\n━━━━━━━━━━━━━━━\n\n🔗 *رابط دعوتك الخاص:*\n`{link}`\n\n👥 *إجمالي من دعوتهم:* `{count}` شخص\n\n━━━━━━━━━━━━━━━\n📤 شارك الرابط مع أصدقائك وعائلتك!\nكل شخص ينضم عبر رابطك سيُحتسب لك. 🎯",
        "referral_share_btn": "📤 مشاركة الرابط",
        "share_bot_header": "📢 *انشر البوت وساعدنا بالوصول لأكثر مستخدمين!*\n\n🔗 *رابط البوت:*\n@{username}\n\n📌 أو عبر الرابط:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 شارك البوت مع أصدقائك للحصول على:\n📰 آخر الأخبار العراقية والعالمية\n🌤 حالة الطقس الفورية\n💱 أسعار العملات\n🕌 أوقات الصلاة\n💎 أسعار العملات الرقمية",
        "share_bot_btn": "📤 مشاركة البوت",
        "open_bot_btn": "🔗 فتح البوت",
        "public_stats_header": "📊 *إحصائيات البوت*\n━━━━━━━━━━━━━━━\n\n👥 إجمالي المستخدمين: *{total}*\n✅ مستخدمون نشطون: *{active}*\n🆕 انضموا اليوم: *{today}*\n⭐ مشتركون مميزون: *{premium}*\n\n",
        "public_stats_langs": "🌍 *أكثر اللغات استخداماً:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *إحصائياتك الشخصية*\n━━━━━━━━━━━━━━━\n\n👤 الاسم: *{name}*\n🌍 اللغة: *{lang}*\n🏙 المدينة: *{city}*\n📅 تاريخ الانضمام: *{join}*\n\n📰 أخبار استلمتها: *{news}*\n🎁 دعوات أرسلتها: *{refs}*\n🔑 كلمات مفتاحية: *{kws}*\n⭐ اشتراك مميز: *{prem}*\n🔔 الإشعارات: *{notif}*\n",
        "my_stats_prem_yes": "⭐ نعم",
        "my_stats_prem_no": "❌ لا",
        "my_stats_notif_on": "🔔 مفعّلة",
        "my_stats_notif_off": "🔕 متوقفة",
        "my_stats_user": "مستخدم",
        "daily_summary_header": "📋 *ملخص أخبار اليوم — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ لا توجد مصادر أخبار لهذه اللغة حالياً.",
        "daily_summary_no_news": "⚠️ لا توجد أخبار متاحة الآن، حاول لاحقاً.",
        "top_referrers_header": "🏆 *أفضل الداعين*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 لا توجد دعوات بعد، كن أول من يدعو أصدقاءه! 🎯",
        "top_referrers_invite": "دعوة",
        "dollar_header": "💵 *سعر الدولار مقابل الدينار العراقي*\n\n🏪 السوق الموازية:\n{rate}\n\n⏰ آخر تحديث: `{time}`\n📡 المصدر: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "بيع",
        "dollar_buy": "شراء",
        "dollar_official": "السعر: `{price}` دينار\n_(السعر الرسمي — قد يختلف عن السوق)_",
        "dollar_error": "⚠️ تعذّر جلب سعر الدولار حالياً. حاول لاحقاً.",
        "weekly_summary_header": "📰 *الملخص الأسبوعي — أبرز {count} خبر*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *ملخص أخبار الأسبوع*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ جاري جمع أبرز أخبار الأسبوع...",
        "weekly_summary_text_no_source": "⚠️ لا توجد مصادر أخبار متاحة لهذه اللغة.",
        "weekly_summary_text_no_news": "⚠️ لا توجد أخبار كافية هذا الأسبوع.",
        "currency_table_header": "📊 *جدول أسعار الصرف الكامل مقابل الدولار 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *قائمة المميز — اختر ما تريد:*",
        "premium_btn_7day": "🌤 توقعات 7 أيام",
        "premium_btn_hourly": "🕐 طقس كل 3 ساعات",
        "premium_btn_addcity": "🏙 إضافة مدينة",
        "premium_btn_mycities": "📋 مدنيّ المحفوظة",
        "premium_btn_interests": "📌 اهتماماتي",
        "premium_btn_currency_alert": "💱 تنبيه العملات",
        "premium_btn_currency_table": "📊 جدول العملات",
        "premium_btn_notif_time": "🕐 وقت الإشعارات",
        "premium_btn_weekly": "📰 ملخص أسبوعي",
        "premium_btn_keywords": "🔑 كلمات مفتاحية",
        "premium_subscribe_btn": "⭐ طلب الاشتراك المميز",
        "broadcast_weather_msg": "🌤 الطقس في {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *تتبع العملات والأسهم والسلع*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *قائمتك الحالية:*\n",
        "track_count": "\n({count}/20 رمز)\n\n",
        "track_add_hint": "➕ *لإضافة رمز:* أرسل اسمه مباشرة\n\n",
        "track_crypto_label": "💎 *عملات رقمية:*\n",
        "track_fiat_label": "💱 *عملات فيات:*\n",
        "track_stocks_label": "📈 *أسهم:*\n",
        "track_commodities_label": "🏅 *سلع ومؤشرات:*\n",
        "track_alert_hint": "🔔 *ستصلك تنبيهات فورية عند تغير ±1% وتقرير ساعي بأسعارك.*\n\n",
        "track_remove_hint": "❌ لحذف رمز: `/removetrack AAPL`\n",
        "track_list_hint": "📋 لعرض قائمتك: `/mytrack`",
        "track_empty": "📌 قائمة التتبع فارغة.\nاضغط *تتبع عملة/سهم* لإضافة رموز.",
        "track_list_header": "📌 *رموزك المتتبعة:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *تنبيهات أسعارك*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 ارتفع",
        "track_fell": "📉 انخفض",
        "track_report_title": "📊 *تقرير ساعي — أصولك المتتبعة*\n",
        "track_unavailable": "غير متوفر",
        "track_remove_usage": "⚠️ حدد الرمز. مثال: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* غير موجود في قائمتك.",
        "track_removed": "✅ تم حذف *{symbol}* من قائمة التتبع.",
        "interest_save_btn": "💾 حفظ",
        "interest_choose_msg": "📌 *اختر اهتماماتك (يمكن اختيار أكثر من واحد):*",
        "currency_rate_header": "💱 *أسعار الصرف مقابل الدولار 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *تحويل {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ عملة غير مدعومة: {currency}",
        "currency_fetch_error": "⚠️ لا يمكن جلب أسعار العملات.",
        "city_add_success": "✅ تمت إضافة المدينة: *{city}*",
        "currency_alert_set": "✅ ستصلك تنبيهات عندما يصل الدولار إلى `{rate}` من عملتك.",
        "currency_alert_invalid": "❌ أدخل رقماً، مثال: 1600",
        "notif_time_set": "✅ سيُرسل الملخص الصباحي في الساعة *{hour}:00* يومياً.",
        "notif_time_invalid": "❌ أدخل رقماً من 0 إلى 23 (مثال: 8 للساعة 8 صباحاً)",
        "currency_eur": "🇪🇺 اليورو",
        "currency_gbp": "🇬🇧 الجنيه الإسترليني",
        "currency_iqd": "🇮🇶 الدينار العراقي",
        "currency_try": "🇹🇷 الليرة التركية",
        "currency_sar": "🇸🇦 الريال السعودي",
        "search_results_header": "🔍 *نتائج البحث عن: {query}*",
        "search_no_results": "⚠️ لا توجد نتائج لهذا البحث.",
    },
    "English 🇬🇧": {
        "no_news": "⚠️ No new news available right now.",
        "no_results": "⚠️ No results found for your search.",
        "search_error": "⚠️ An error occurred while searching.",
        "no_trending": "⚠️ No trending news right now, try again later.",
        "trending_header": "🔥 *Trending News*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Sports News*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ No new sports news right now.",
        "no_sports_source": "⚠️ No sports sources available for this language.",
        "no_mena": "⚠️ No new political news right now, try again later.",
        "no_source": "⚠️ No news sources available for this language right now.",
        "weather_error": "⚠️ Cannot fetch weather data right now.",
        "forecast_error": "⚠️ Cannot fetch hourly forecast.",
        "no_weekly": "⚠️ No news available for weekly summary.",
        "currency_error": "⚠️ Cannot fetch currency rates right now.",
        "search_prompt": "🔍 Type your search keyword:",
        "label_breaking": "🚨 Breaking News",
        "label_news": "🚨 News",
        "label_mena": "📰 Middle East Political News",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Your city is not set yet.",
        "city_not_found": "⚠️ Weather data not found for: {city}",
        "weather_header": "{emoji} *Weather in {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Feels like:* {feels}°C\n🔼 Max: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Condition:* {desc}\n🌫 *Clouds:* {clouds}%\n👁 *Visibility:* {visibility_km} km\n\n💧 *Humidity:* {humidity}%\n🌀 *Pressure:* {pressure} hPa\n☀️ *UV Index:* {uvi}\n\n💨 *Wind:* {wind_speed} m/s | {wind_dir}\n💨 *Gusts:* {wind_gust} m/s\n\n🌅 *Sunrise:* {sunrise}  |  🌇 *Sunset:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3-Day Weather Forecast — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7-Day Weather Forecast — {city}*\n\n",
        "hourly_header": "🕐 *3-Hourly Weather — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Low",
        "uv_moderate": "Moderate",
        "uv_high": "High",
        "uv_very_high": "Very High",
        "uv_extreme": "Extreme",
        "uv_na": "N/A",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ E",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SW",
        "wind_W": "⬅️ W",
        "wind_NW": "↖️ NW",
        "crypto_header": "💎 *Crypto Prices*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Data from CoinGecko",
        "crypto_error": "⚠️ Cannot fetch crypto prices right now, try later.",
        "prayer_header": "🕌 *Prayer Times in {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Sunrise: `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Data from Aladhan API",
        "prayer_no_city": "⚠️ Your city is not set. Go to Settings and set it up.",
        "prayer_city_error": "⚠️ Cannot fetch prayer times for: {city}\nMake sure the city name is in English in your settings.",
        "prayer_error": "⚠️ Cannot fetch prayer times right now, try later.",
        "referral_header": "🎁 *Referral System*\n━━━━━━━━━━━━━━━\n\n🔗 *Your referral link:*\n`{link}`\n\n👥 *Total invited:* `{count}` people\n\n━━━━━━━━━━━━━━━\n📤 Share with friends & family!\nEveryone who joins via your link counts. 🎯",
        "referral_share_btn": "📤 Share Link",
        "share_bot_header": "📢 *Share the bot and help us grow!*\n\n🔗 *Bot link:*\n@{username}\n\n📌 Or via link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Share with friends to get:\n📰 Latest world news\n🌤 Live weather\n💱 Currency rates\n🕌 Prayer times\n💎 Crypto prices",
        "share_bot_btn": "📤 Share Bot",
        "open_bot_btn": "🔗 Open Bot",
        "public_stats_header": "📊 *Bot Statistics*\n━━━━━━━━━━━━━━━\n\n👥 Total users: *{total}*\n✅ Active users: *{active}*\n🆕 Joined today: *{today}*\n⭐ Premium subscribers: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Most used languages:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Your Personal Stats*\n━━━━━━━━━━━━━━━\n\n👤 Name: *{name}*\n🌍 Language: *{lang}*\n🏙 City: *{city}*\n📅 Join date: *{join}*\n\n📰 News received: *{news}*\n🎁 Referrals sent: *{refs}*\n🔑 Keywords: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notifications: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Yes",
        "my_stats_prem_no": "❌ No",
        "my_stats_notif_on": "🔔 Active",
        "my_stats_notif_off": "🔕 Paused",
        "my_stats_user": "User",
        "daily_summary_header": "📋 *Today's News Summary — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ No news sources available for this language.",
        "daily_summary_no_news": "⚠️ No news available right now, try later.",
        "top_referrers_header": "🏆 *Top Referrers*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 No referrals yet — be the first to invite friends! 🎯",
        "top_referrers_invite": "invite(s)",
        "dollar_header": "💵 *USD vs Iraqi Dinar*\n\n🏪 Parallel market:\n{rate}\n\n⏰ Last updated: `{time}`\n📡 Source: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Sell",
        "dollar_buy": "Buy",
        "dollar_official": "Rate: `{price}` IQD\n_(Official rate — may differ from market)_",
        "dollar_error": "⚠️ Cannot fetch dollar rate right now. Try later.",
        "weekly_summary_header": "📰 *Weekly Summary — Top {count} stories*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Weekly News Summary*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Collecting this week's top stories...",
        "weekly_summary_text_no_source": "⚠️ No news sources available for this language.",
        "weekly_summary_text_no_news": "⚠️ Not enough news this week.",
        "currency_table_header": "📊 *Full Exchange Rate Table vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Premium Menu — Choose:*",
        "premium_btn_7day": "🌤 7-Day Forecast",
        "premium_btn_hourly": "🕐 3-Hourly Weather",
        "premium_btn_addcity": "🏙 Add City",
        "premium_btn_mycities": "📋 My Saved Cities",
        "premium_btn_interests": "📌 My Interests",
        "premium_btn_currency_alert": "💱 Currency Alert",
        "premium_btn_currency_table": "📊 Currency Table",
        "premium_btn_notif_time": "🕐 Notification Time",
        "premium_btn_weekly": "📰 Weekly Summary",
        "premium_btn_keywords": "🔑 Keywords",
        "premium_subscribe_btn": "⭐ Request Premium Subscription",
        "broadcast_weather_msg": "🌤 Weather in {city}: {temp}°C\n☁️ {desc}",
        "currency_eur": "🇪🇺 Euro",
        "currency_gbp": "🇬🇧 British Pound",
        "currency_iqd": "🇮🇶 Iraqi Dinar",
        "currency_try": "🇹🇷 Turkish Lira",
        "currency_sar": "🇸🇦 Saudi Riyal",
        "search_results_header": "🔍 *Search results for: {query}*",
        "search_no_results": "⚠️ No results found for this search.",
        "track_header": "📌 *Track Assets — Crypto, Forex, Stocks & Commodities*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Your current list:*\n",
        "track_count": "\n({count}/20 symbols)\n\n",
        "track_add_hint": "➕ *Add a symbol:* send its name directly\n\n",
        "track_crypto_label": "💎 *Crypto:*\n",
        "track_fiat_label": "💱 *Fiat Currencies:*\n",
        "track_stocks_label": "📈 *Stocks:*\n",
        "track_commodities_label": "🏅 *Commodities & Indices:*\n",
        "track_alert_hint": "🔔 *You will receive instant alerts on ±1% change and an hourly price report.*\n\n",
        "track_remove_hint": "❌ To remove a symbol: `/removetrack AAPL`\n",
        "track_list_hint": "📋 To view your list: `/mytrack`",
        "track_empty": "📌 Tracking list is empty.\nTap *Track Asset* to add symbols.",
        "track_list_header": "📌 *Your tracked assets:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Price Alerts*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 rose",
        "track_fell": "📉 fell",
        "track_report_title": "📊 *Hourly Report — Your Tracked Assets*\n",
        "track_unavailable": "unavailable",
        "track_remove_usage": "⚠️ Specify the symbol. Example: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* not found in your list.",
        "track_removed": "✅ *{symbol}* removed from your tracking list.",
        "interest_save_btn": "💾 Save",
        "interest_choose_msg": "📌 *Choose your interests (multiple allowed):*",
        "currency_rate_header": "💱 *Exchange Rates vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Convert {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Unsupported currency: {currency}",
        "currency_fetch_error": "⚠️ Unable to fetch exchange rates.",
        "currency_alert_set": "✅ You will be notified when USD reaches `{rate}` of your currency.",
        "currency_alert_invalid": "❌ Enter a number, e.g.: 1600",
        "notif_time_set": "✅ Morning summary will be sent at *{hour}:00* daily.",
        "notif_time_invalid": "❌ Enter a number from 0 to 23 (e.g.: 8 for 8 AM)",
    },
    "Русский 🇷🇺": {
        "no_news": "⚠️ Новых новостей нет.",
        "no_results": "⚠️ По вашему запросу ничего не найдено.",
        "search_error": "⚠️ При поиске произошла ошибка.",
        "no_trending": "⚠️ Нет трендовых новостей, попробуйте позже.",
        "trending_header": "🔥 *В тренде*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Спортивные новости*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Новых спортивных новостей нет.",
        "no_sports_source": "⚠️ Нет спортивных источников для этого языка.",
        "no_mena": "⚠️ Новых политических новостей нет, попробуйте позже.",
        "no_source": "⚠️ Нет источников новостей для этого языка.",
        "weather_error": "⚠️ Не удаётся получить данные о погоде.",
        "forecast_error": "⚠️ Не удаётся получить почасовой прогноз.",
        "no_weekly": "⚠️ Нет новостей для еженедельной сводки.",
        "currency_error": "⚠️ Не удаётся получить курсы валют.",
        "search_prompt": "🔍 Введите слово для поиска:",
        "label_breaking": "🚨 Срочная новость",
        "label_news": "🚨 Новость",
        "label_mena": "📰 Ближний Восток",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Ваш город ещё не указан.",
        "city_not_found": "⚠️ Данные о погоде не найдены для: {city}",
        "weather_header": "{emoji} *Погода в {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Темп:* {temp}°C\n🤔 *Ощущается:* {feels}°C\n🔼 Макс: {temp_max}°C  |  🔽 Мин: {temp_min}°C\n\n☁️ *Состояние:* {desc}\n🌫 *Облачность:* {clouds}%\n👁 *Видимость:* {visibility_km} км\n\n💧 *Влажность:* {humidity}%\n🌀 *Давление:* {pressure} hPa\n☀️ *УФ-индекс:* {uvi}\n\n💨 *Ветер:* {wind_speed} м/с | {wind_dir}\n💨 *Порывы:* {wind_gust} м/с\n\n🌅 *Восход:* {sunrise}  |  🌇 *Закат:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Прогноз на 3 дня — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Прогноз на 7 дней — {city}*\n\n",
        "hourly_header": "🕐 *Погода каждые 3 часа — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "м/с",
        "uv_low": "Низкий",
        "uv_moderate": "Умеренный",
        "uv_high": "Высокий",
        "uv_very_high": "Очень высокий",
        "uv_extreme": "Экстремальный",
        "uv_na": "Н/Д",
        "wind_N": "⬆️ С",
        "wind_NE": "↗️ СВ",
        "wind_E": "➡️ В",
        "wind_SE": "↘️ ЮВ",
        "wind_S": "⬇️ Ю",
        "wind_SW": "↙️ ЮЗ",
        "wind_W": "⬅️ З",
        "wind_NW": "↖️ СЗ",
        "crypto_header": "💎 *Курсы криптовалют*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Данные от CoinGecko",
        "crypto_error": "⚠️ Не удаётся получить курсы криптовалют, попробуйте позже.",
        "prayer_header": "🕌 *Время молитв в {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Фаджр:   `{fajr}`\n☀️ Восход:  `{sunrise}`\n🌞 Зухр:    `{dhuhr}`\n🌇 Аср:     `{asr}`\n🌆 Магриб:  `{maghrib}`\n🌙 Иша:     `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Данные от Aladhan API",
        "prayer_no_city": "⚠️ Ваш город не указан. Перейдите в настройки.",
        "prayer_city_error": "⚠️ Не удаётся получить время молитв для: {city}",
        "prayer_error": "⚠️ Не удаётся получить время молитв, попробуйте позже.",
        "referral_header": "🎁 *Реферальная система*\n━━━━━━━━━━━━━━━\n\n🔗 *Ваша реферальная ссылка:*\n`{link}`\n\n👥 *Всего приглашено:* `{count}` чел.\n\n━━━━━━━━━━━━━━━\n📤 Поделитесь с друзьями и семьёй!\nКаждый, кто присоединится по вашей ссылке, будет засчитан. 🎯",
        "referral_share_btn": "📤 Поделиться ссылкой",
        "share_bot_header": "📢 *Поделитесь ботом и помогите нам расти!*\n\n🔗 *Ссылка на бот:*\n@{username}\n\n📌 Или по ссылке:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Поделитесь с друзьями, чтобы получать:\n📰 Последние мировые новости\n🌤 Погода в реальном времени\n💱 Курсы валют\n🕌 Время молитв\n💎 Курсы криптовалют",
        "share_bot_btn": "📤 Поделиться ботом",
        "open_bot_btn": "🔗 Открыть бот",
        "public_stats_header": "📊 *Статистика бота*\n━━━━━━━━━━━━━━━\n\n👥 Всего пользователей: *{total}*\n✅ Активных: *{active}*\n🆕 Присоединились сегодня: *{today}*\n⭐ Премиум-подписчиков: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Наиболее используемые языки:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Ваша личная статистика*\n━━━━━━━━━━━━━━━\n\n👤 Имя: *{name}*\n🌍 Язык: *{lang}*\n🏙 Город: *{city}*\n📅 Дата регистрации: *{join}*\n\n📰 Получено новостей: *{news}*\n🎁 Отправлено приглашений: *{refs}*\n🔑 Ключевых слов: *{kws}*\n⭐ Премиум: *{prem}*\n🔔 Уведомления: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Да",
        "my_stats_prem_no": "❌ Нет",
        "my_stats_notif_on": "🔔 Активны",
        "my_stats_notif_off": "🔕 Отключены",
        "my_stats_user": "Пользователь",
        "daily_summary_header": "📋 *Сводка новостей за {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Нет источников новостей для этого языка.",
        "daily_summary_no_news": "⚠️ Нет доступных новостей, попробуйте позже.",
        "top_referrers_header": "🏆 *Лучшие рефереры*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Пока нет рефералов — будьте первым! 🎯",
        "top_referrers_invite": "приглашение(й)",
        "dollar_header": "💵 *Доллар США к иракскому динару*\n\n🏪 Параллельный рынок:\n{rate}\n\n⏰ Последнее обновление: `{time}`\n📡 Источник: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Продажа",
        "dollar_buy": "Покупка",
        "dollar_official": "Курс: `{price}` IQD\n_(Официальный курс — может отличаться от рыночного)_",
        "dollar_error": "⚠️ Не удаётся получить курс доллара. Попробуйте позже.",
        "weekly_summary_header": "📰 *Еженедельный обзор — Топ {count} новостей*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Еженедельная сводка*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Собираем главные новости недели...",
        "weekly_summary_text_no_source": "⚠️ Нет доступных источников для этого языка.",
        "weekly_summary_text_no_news": "⚠️ Недостаточно новостей за эту неделю.",
        "currency_table_header": "📊 *Полная таблица курсов валют к USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Премиум-меню — Выберите:*",
        "premium_btn_7day": "🌤 Прогноз на 7 дней",
        "premium_btn_hourly": "🕐 Погода каждые 3 часа",
        "premium_btn_addcity": "🏙 Добавить город",
        "premium_btn_mycities": "📋 Мои сохранённые города",
        "premium_btn_interests": "📌 Мои интересы",
        "premium_btn_currency_alert": "💱 Оповещение о валюте",
        "premium_btn_currency_table": "📊 Таблица валют",
        "premium_btn_notif_time": "🕐 Время уведомлений",
        "premium_btn_weekly": "📰 Еженедельная сводка",
        "premium_btn_keywords": "🔑 Ключевые слова",
        "premium_subscribe_btn": "⭐ Запросить премиум-подписку",
        "broadcast_weather_msg": "🌤 Погода в {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Отслеживание активов*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Текущий список:*\n",
        "track_count": "\n({count}/20 символов)\n\n",
        "track_add_hint": "➕ *Добавить символ:* отправьте его название\n\n",
        "track_crypto_label": "💎 *Криптовалюты:*\n",
        "track_fiat_label": "💱 *Фиатные валюты:*\n",
        "track_stocks_label": "📈 *Акции:*\n",
        "track_commodities_label": "🏅 *Сырьё и индексы:*\n",
        "track_alert_hint": "🔔 *Вы получите мгновенные оповещения при изменении ±1% и ежечасный отчёт.*\n\n",
        "track_remove_hint": "❌ Удалить символ: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Просмотреть список: `/mytrack`",
        "track_empty": "📌 Список отслеживания пуст.\nНажмите *Отслеживать актив* для добавления символов.",
        "track_list_header": "📌 *Ваши отслеживаемые активы:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Оповещения о ценах*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 вырос",
        "track_fell": "📉 упал",
        "track_report_title": "📊 *Ежечасный отчёт — Ваши активы*\n",
        "track_unavailable": "недоступно",
        "track_remove_usage": "⚠️ Укажите символ. Пример: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* не найден в вашем списке.",
        "track_removed": "✅ *{symbol}* удалён из списка отслеживания.",
        "interest_save_btn": "💾 Сохранить",
        "interest_choose_msg": "📌 *Выберите интересы (можно несколько):*",
        "currency_rate_header": "💱 *Курсы валют к доллару 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Конвертация {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Неподдерживаемая валюта: {currency}",
        "currency_fetch_error": "⚠️ Не удаётся получить курсы валют.",
        "city_add_success": "✅ Город добавлен: *{city}*",
        "currency_alert_set": "✅ Вы будете оповещены, когда доллар достигнет `{rate}` вашей валюты.",
        "currency_alert_invalid": "❌ Введите число, например: 1600",
        "notif_time_set": "✅ Утренняя сводка будет отправляться в *{hour}:00* ежедневно.",
        "notif_time_invalid": "❌ Введите число от 0 до 23 (например: 8 для 8 утра)",
    },
    "فارسی 🇮🇷": {
        "no_news": "⚠️ اخبار جدیدی موجود نیست.",
        "no_results": "⚠️ نتیجهای برای جستجوی شما یافت نشد.",
        "search_error": "⚠️ خطایی در جستجو رخ داد.",
        "no_trending": "⚠️ اخبار پرطرفداری موجود نیست، بعداً دوباره امتحان کنید.",
        "trending_header": "🔥 *پرطرفدارترین*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *اخبار ورزشی*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ اخبار ورزشی جدیدی موجود نیست.",
        "no_sports_source": "⚠️ منبع ورزشی برای این زبان موجود نیست.",
        "no_mena": "⚠️ اخبار سیاسی جدیدی موجود نیست، بعداً دوباره امتحان کنید.",
        "no_source": "⚠️ منبع خبری برای این زبان موجود نیست.",
        "weather_error": "⚠️ دریافت اطلاعات آبوهوا ممکن نیست.",
        "forecast_error": "⚠️ دریافت پیشبینی ساعتی ممکن نیست.",
        "no_weekly": "⚠️ اخباری برای خلاصه هفتگی موجود نیست.",
        "currency_error": "⚠️ دریافت نرخ ارز ممکن نیست.",
        "search_prompt": "🔍 کلمه جستجو را بنویسید:",
        "label_breaking": "🚨 خبر فوری",
        "label_news": "🚨 خبر",
        "label_mena": "📰 اخبار سیاسی خاورمیانه",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ شهر شما هنوز تنظیم نشده.",
        "city_not_found": "⚠️ اطلاعات آبوهوا برای شهر {city} یافت نشد.",
        "weather_header": "{emoji} *آبوهوا در {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *دما:* {temp}°C\n🤔 *احساس میشود:* {feels}°C\n🔼 حداکثر: {temp_max}°C  |  🔽 حداقل: {temp_min}°C\n\n☁️ *وضعیت:* {desc}\n🌫 *ابرناکی:* {clouds}%\n👁 *دید:* {visibility_km} کم\n\n💧 *رطوبت:* {humidity}%\n🌀 *فشار:* {pressure} hPa\n☀️ *شاخص UV:* {uvi}\n\n💨 *باد:* {wind_speed} م/ث | {wind_dir}\n💨 *وزش:* {wind_gust} م/ث\n\n🌅 *طلوع:* {sunrise}  |  🌇 *غروب:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *پیشبینی ۳ روزه — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *پیشبینی ۷ روزه — {city}*\n\n",
        "hourly_header": "🕐 *آبوهوا هر ۳ ساعت — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "م/ث",
        "uv_low": "کم",
        "uv_moderate": "متوسط",
        "uv_high": "زیاد",
        "uv_very_high": "خیلی زیاد",
        "uv_extreme": "بسیار خطرناک",
        "uv_na": "ناموجود",
        "wind_N": "⬆️ شمال",
        "wind_NE": "↗️ شمالشرق",
        "wind_E": "➡️ شرق",
        "wind_SE": "↘️ جنوبشرق",
        "wind_S": "⬇️ جنوب",
        "wind_SW": "↙️ جنوبغرب",
        "wind_W": "⬅️ غرب",
        "wind_NW": "↖️ شمالغرب",
        "crypto_header": "💎 *قیمت ارزهای دیجیتال*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 دادهها از CoinGecko",
        "crypto_error": "⚠️ دریافت قیمت ارزهای دیجیتال ممکن نیست، بعداً امتحان کنید.",
        "prayer_header": "🕌 *اوقات نماز در {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 صبح:    `{fajr}`\n☀️ طلوع:   `{sunrise}`\n🌞 ظهر:    `{dhuhr}`\n🌇 عصر:    `{asr}`\n🌆 مغرب:   `{maghrib}`\n🌙 عشاء:   `{isha}`\n━━━━━━━━━━━━━━━\n🔄 دادهها از Aladhan API",
        "prayer_no_city": "⚠️ شهر شما تنظیم نشده. به تنظیمات بروید.",
        "prayer_city_error": "⚠️ دریافت اوقات نماز برای {city} ممکن نیست.",
        "prayer_error": "⚠️ دریافت اوقات نماز ممکن نیست، بعداً امتحان کنید.",
        "referral_header": "🎁 *سیستم دعوت*\n━━━━━━━━━━━━━━━\n\n🔗 *لینک دعوت شما:*\n`{link}`\n\n👥 *جمع دعوتشدگان:* `{count}` نفر\n\n━━━━━━━━━━━━━━━\n📤 با دوستان و خانواده به اشتراک بگذارید!\nهر کسی که از لینک شما بپیوندد حساب میشود. 🎯",
        "referral_share_btn": "📤 اشتراکگذاری لینک",
        "share_bot_header": "📢 *ربات را به اشتراک بگذارید و کمک کنید رشد کند!*\n\n🔗 *لینک ربات:*\n@{username}\n\n📌 یا از طریق لینک:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 با دوستان به اشتراک بگذارید:",
        "share_bot_btn": "📤 اشتراکگذاری ربات",
        "open_bot_btn": "🔗 باز کردن ربات",
        "public_stats_header": "📊 *آمار ربات*\n━━━━━━━━━━━━━━━\n\n👥 کل کاربران: *{total}*\n✅ کاربران فعال: *{active}*\n🆕 امروز پیوستند: *{today}*\n⭐ اشتراک ویژه: *{premium}*\n\n",
        "public_stats_langs": "🌍 *پرکاربردترین زبانها:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *آمار شخصی شما*\n━━━━━━━━━━━━━━━\n\n👤 نام: *{name}*\n🌍 زبان: *{lang}*\n🏙 شهر: *{city}*\n📅 تاریخ عضویت: *{join}*\n\n📰 اخبار دریافتی: *{news}*\n🎁 دعوتهای ارسالی: *{refs}*\n🔑 کلمات کلیدی: *{kws}*\n⭐ اشتراک ویژه: *{prem}*\n🔔 اعلانها: *{notif}*\n",
        "my_stats_prem_yes": "⭐ بله",
        "my_stats_prem_no": "❌ خیر",
        "my_stats_notif_on": "🔔 فعال",
        "my_stats_notif_off": "🔕 غیرفعال",
        "my_stats_user": "کاربر",
        "daily_summary_header": "📋 *خلاصه اخبار امروز — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ منبع خبری برای این زبان موجود نیست.",
        "daily_summary_no_news": "⚠️ اخبار موجود نیست، بعداً امتحان کنید.",
        "top_referrers_header": "🏆 *برترین دعوتکنندگان*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 هنوز دعوتی نیست — اولین باشید! 🎯",
        "top_referrers_invite": "دعوت",
        "dollar_header": "💵 *دلار آمریکا در برابر دینار عراق*\n\n🏪 بازار موازی:\n{rate}\n\n⏰ آخرین بهروزرسانی: `{time}`\n📡 منبع: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "فروش",
        "dollar_buy": "خرید",
        "dollar_official": "نرخ: `{price}` IQD\n_(نرخ رسمی — ممکن است با بازار متفاوت باشد)_",
        "dollar_error": "⚠️ دریافت نرخ دلار ممکن نیست. بعداً امتحان کنید.",
        "weekly_summary_header": "📰 *خلاصه هفتگی — برترین {count} خبر*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *خلاصه اخبار هفته*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ در حال جمعآوری اخبار برتر هفته...",
        "weekly_summary_text_no_source": "⚠️ منبع خبری برای این زبان موجود نیست.",
        "weekly_summary_text_no_news": "⚠️ اخبار کافی این هفته وجود ندارد.",
        "currency_table_header": "📊 *جدول کامل نرخ ارز در برابر دلار 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *منوی ویژه — انتخاب کنید:*",
        "premium_btn_7day": "🌤 پیشبینی ۷ روزه",
        "premium_btn_hourly": "🕐 آبوهوا هر ۳ ساعت",
        "premium_btn_addcity": "🏙 افزودن شهر",
        "premium_btn_mycities": "📋 شهرهای ذخیرهشده",
        "premium_btn_interests": "📌 علاقهمندیهای من",
        "premium_btn_currency_alert": "💱 هشدار ارز",
        "premium_btn_currency_table": "📊 جدول ارز",
        "premium_btn_notif_time": "🕐 زمان اعلان",
        "premium_btn_weekly": "📰 خلاصه هفتگی",
        "premium_btn_keywords": "🔑 کلمات کلیدی",
        "premium_subscribe_btn": "⭐ درخواست اشتراک ویژه",
        "broadcast_weather_msg": "🌤 آبوهوا در {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *ردیابی ارزها، سهام و کالاها*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *لیست فعلی شما:*\n",
        "track_count": "\n({count}/20 نماد)\n\n",
        "track_add_hint": "➕ *افزودن نماد:* نام آن را ارسال کنید\n\n",
        "track_crypto_label": "💎 *ارزهای دیجیتال:*\n",
        "track_fiat_label": "💱 *ارزهای فیات:*\n",
        "track_stocks_label": "📈 *سهام:*\n",
        "track_commodities_label": "🏅 *کالا و شاخصها:*\n",
        "track_alert_hint": "🔔 *هنگام تغییر ±۱٪ هشدار فوری دریافت میکنید و گزارش ساعتی نیز ارسال میشود.*\n\n",
        "track_remove_hint": "❌ حذف نماد: `/removetrack AAPL`\n",
        "track_list_hint": "📋 مشاهده لیست: `/mytrack`",
        "track_empty": "📌 لیست ردیابی خالی است.\nروی *ردیابی دارایی* بزنید تا نماد اضافه کنید.",
        "track_list_header": "📌 *داراییهای ردیابیشده شما:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *هشدارهای قیمت*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 افزایش یافت",
        "track_fell": "📉 کاهش یافت",
        "track_report_title": "📊 *گزارش ساعتی — داراییهای شما*\n",
        "track_unavailable": "ناموجود",
        "track_remove_usage": "⚠️ نماد را بعد از دستور بفرستید. مثال: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* در لیست شما یافت نشد.",
        "track_removed": "✅ *{symbol}* از لیست ردیابی حذف شد.",
        "interest_save_btn": "💾 ذخیره",
        "interest_choose_msg": "📌 *علاقهمندیهای خود را انتخاب کنید (چندتایی):*",
        "currency_rate_header": "💱 *نرخ ارز در برابر دلار 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *تبدیل {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ ارز پشتیبانینشده: {currency}",
        "currency_fetch_error": "⚠️ دریافت نرخ ارز ممکن نیست.",
        "city_add_success": "✅ شهر اضافه شد: *{city}*",
        "currency_alert_set": "✅ وقتی دلار به `{rate}` ارز محلی شما برسد هشدار میگیرید.",
        "currency_alert_invalid": "❌ یک عدد ارسال کنید، مثلاً: 1600",
        "notif_time_set": "✅ خلاصه صبحگاهی روزانه در ساعت *{hour}:00* ارسال میشود.",
        "notif_time_invalid": "❌ عددی بین ۰ تا ۲۳ وارد کنید (مثال: ۸ برای ساعت ۸ صبح)",
    },
    "हिन्दी 🇮🇳": {
        "no_news": "⚠️ अभी कोई नई खबर नहीं है।",
        "no_results": "⚠️ आपकी खोज का कोई परिणाम नहीं मिला।",
        "search_error": "⚠️ खोज के दौरान त्रुटि हुई।",
        "no_trending": "⚠️ अभी कोई ट्रेंडिंग खबर नहीं, बाद में प्रयास करें।",
        "trending_header": "🔥 *ट्रेंडिंग खबरें*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *खेल समाचार*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ अभी कोई नई खेल खबर नहीं।",
        "no_sports_source": "⚠️ इस भाषा के लिए कोई खेल स्रोत नहीं।",
        "no_mena": "⚠️ अभी कोई नई राजनीतिक खबर नहीं, बाद में प्रयास करें।",
        "no_source": "⚠️ इस भाषा के लिए कोई समाचार स्रोत नहीं।",
        "weather_error": "⚠️ मौसम डेटा प्राप्त नहीं हो सका।",
        "forecast_error": "⚠️ घंटे की भविष्यवाणी प्राप्त नहीं हो सकी।",
        "no_weekly": "⚠️ साप्ताहिक सारांश के लिए कोई समाचार नहीं।",
        "currency_error": "⚠️ मुद्रा दरें अभी प्राप्त नहीं हो सकीं।",
        "search_prompt": "🔍 खोज शब्द टाइप करें:",
        "label_breaking": "🚨 ब्रेकिंग न्यूज़",
        "label_news": "🚨 खबर",
        "label_mena": "📰 मध्य पूर्व राजनीतिक समाचार",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ आपका शहर अभी तक सेट नहीं है।",
        "city_not_found": "⚠️ {city} के लिए मौसम डेटा नहीं मिला।",
        "weather_header": "{emoji} *{city} में मौसम*\n━━━━━━━━━━━━━━━\n\n🌡 *तापमान:* {temp}°C\n🤔 *महसूस होता है:* {feels}°C\n🔼 अधिकतम: {temp_max}°C  |  🔽 न्यूनतम: {temp_min}°C\n\n☁️ *स्थिति:* {desc}\n🌫 *बादल:* {clouds}%\n👁 *दृश्यता:* {visibility_km} किमी\n\n💧 *नमी:* {humidity}%\n🌀 *दबाव:* {pressure} hPa\n☀️ *UV सूचकांक:* {uvi}\n\n💨 *हवा:* {wind_speed} मी/से | {wind_dir}\n💨 *झोंके:* {wind_gust} मी/से\n\n🌅 *सूर्योदय:* {sunrise}  |  🌇 *सूर्यास्त:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3-दिन का मौसम पूर्वानुमान — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7-दिन का मौसम पूर्वानुमान — {city}*\n\n",
        "hourly_header": "🕐 *हर 3 घंटे का मौसम — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "मी/से",
        "uv_low": "कम",
        "uv_moderate": "मध्यम",
        "uv_high": "उच्च",
        "uv_very_high": "बहुत उच्च",
        "uv_extreme": "अत्यधिक",
        "uv_na": "उपलब्ध नहीं",
        "wind_N": "⬆️ उत्तर",
        "wind_NE": "↗️ उत्तर-पूर्व",
        "wind_E": "➡️ पूर्व",
        "wind_SE": "↘️ दक्षिण-पूर्व",
        "wind_S": "⬇️ दक्षिण",
        "wind_SW": "↙️ दक्षिण-पश्चिम",
        "wind_W": "⬅️ पश्चिम",
        "wind_NW": "↖️ उत्तर-पश्चिम",
        "crypto_header": "💎 *क्रिप्टो मूल्य*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 CoinGecko से डेटा",
        "crypto_error": "⚠️ अभी क्रिप्टो मूल्य प्राप्त नहीं हो सका, बाद में प्रयास करें।",
        "prayer_header": "🕌 *{city} में नमाज़ के समय*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 फज्र:    `{fajr}`\n☀️ उदय:    `{sunrise}`\n🌞 जुहर:   `{dhuhr}`\n🌇 अस्र:    `{asr}`\n🌆 मगरिब:  `{maghrib}`\n🌙 ईशा:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Aladhan API से डेटा",
        "prayer_no_city": "⚠️ आपका शहर सेट नहीं है। सेटिंग्स में जाएं।",
        "prayer_city_error": "⚠️ {city} के लिए नमाज़ के समय प्राप्त नहीं हो सके।",
        "prayer_error": "⚠️ नमाज़ के समय अभी प्राप्त नहीं हो सके, बाद में प्रयास करें।",
        "referral_header": "🎁 *रेफरल सिस्टम*\n━━━━━━━━━━━━━━━\n\n🔗 *आपका रेफरल लिंक:*\n`{link}`\n\n👥 *कुल आमंत्रित:* `{count}` लोग\n\n━━━━━━━━━━━━━━━\n📤 दोस्तों और परिवार के साथ साझा करें!\nआपके लिंक से जुड़ने वाला हर व्यक्ति गिना जाएगा। 🎯",
        "referral_share_btn": "📤 लिंक साझा करें",
        "share_bot_header": "📢 *बॉट साझा करें और हमें बढ़ने में मदद करें!*\n\n🔗 *बॉट लिंक:*\n@{username}\n\n📌 या लिंक से:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 दोस्तों के साथ साझा करें:",
        "share_bot_btn": "📤 बॉट साझा करें",
        "open_bot_btn": "🔗 बॉट खोलें",
        "public_stats_header": "📊 *बॉट सांख्यिकी*\n━━━━━━━━━━━━━━━\n\n👥 कुल उपयोगकर्ता: *{total}*\n✅ सक्रिय उपयोगकर्ता: *{active}*\n🆕 आज जुड़े: *{today}*\n⭐ प्रीमियम सदस्य: *{premium}*\n\n",
        "public_stats_langs": "🌍 *सबसे अधिक उपयोग की जाने वाली भाषाएं:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *आपकी व्यक्तिगत सांख्यिकी*\n━━━━━━━━━━━━━━━\n\n👤 नाम: *{name}*\n🌍 भाषा: *{lang}*\n🏙 शहर: *{city}*\n📅 शामिल होने की तारीख: *{join}*\n\n📰 प्राप्त समाचार: *{news}*\n🎁 भेजे गए रेफरल: *{refs}*\n🔑 कीवर्ड: *{kws}*\n⭐ प्रीमियम: *{prem}*\n🔔 सूचनाएं: *{notif}*\n",
        "my_stats_prem_yes": "⭐ हाँ",
        "my_stats_prem_no": "❌ नहीं",
        "my_stats_notif_on": "🔔 सक्रिय",
        "my_stats_notif_off": "🔕 बंद",
        "my_stats_user": "उपयोगकर्ता",
        "daily_summary_header": "📋 *आज के समाचार का सारांश — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ इस भाषा के लिए कोई समाचार स्रोत नहीं।",
        "daily_summary_no_news": "⚠️ अभी कोई समाचार उपलब्ध नहीं, बाद में प्रयास करें।",
        "top_referrers_header": "🏆 *शीर्ष रेफरर्स*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 अभी कोई रेफरल नहीं — पहले बनें! 🎯",
        "top_referrers_invite": "आमंत्रण",
        "dollar_header": "💵 *USD बनाम इराकी दीनार*\n\n🏪 समानांतर बाज़ार:\n{rate}\n\n⏰ अंतिम अपडेट: `{time}`\n📡 स्रोत: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "बिक्री",
        "dollar_buy": "खरीद",
        "dollar_official": "दर: `{price}` IQD\n_(आधिकारिक दर — बाज़ार से भिन्न हो सकती है)_",
        "dollar_error": "⚠️ अभी डॉलर दर प्राप्त नहीं हो सकी। बाद में प्रयास करें।",
        "weekly_summary_header": "📰 *साप्ताहिक सारांश — शीर्ष {count} खबरें*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *साप्ताहिक समाचार सारांश*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ इस सप्ताह की शीर्ष खबरें एकत्र की जा रही हैं...",
        "weekly_summary_text_no_source": "⚠️ इस भाषा के लिए कोई समाचार स्रोत नहीं।",
        "weekly_summary_text_no_news": "⚠️ इस सप्ताह पर्याप्त खबरें नहीं।",
        "currency_table_header": "📊 *USD के मुकाबले पूर्ण विनिमय दर तालिका 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *प्रीमियम मेनू — चुनें:*",
        "premium_btn_7day": "🌤 7-दिन का पूर्वानुमान",
        "premium_btn_hourly": "🕐 हर 3 घंटे का मौसम",
        "premium_btn_addcity": "🏙 शहर जोड़ें",
        "premium_btn_mycities": "📋 मेरे सहेजे गए शहर",
        "premium_btn_interests": "📌 मेरी रुचियां",
        "premium_btn_currency_alert": "💱 मुद्रा अलर्ट",
        "premium_btn_currency_table": "📊 मुद्रा तालिका",
        "premium_btn_notif_time": "🕐 सूचना समय",
        "premium_btn_weekly": "📰 साप्ताहिक सारांश",
        "premium_btn_keywords": "🔑 कीवर्ड",
        "premium_subscribe_btn": "⭐ प्रीमियम सदस्यता का अनुरोध करें",
        "broadcast_weather_msg": "🌤 {city} में मौसम: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *मुद्राओं, शेयरों और वस्तुओं की निगरानी*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *आपकी वर्तमान सूची:*\n",
        "track_count": "\n({count}/20 प्रतीक)\n\n",
        "track_add_hint": "➕ *प्रतीक जोड़ें:* सीधे नाम भेजें\n\n",
        "track_crypto_label": "💎 *क्रिप्टोकरेंसी:*\n",
        "track_fiat_label": "💱 *फिएट मुद्राएं:*\n",
        "track_stocks_label": "📈 *शेयर:*\n",
        "track_commodities_label": "🏅 *वस्तु और सूचकांक:*\n",
        "track_alert_hint": "🔔 *±1% परिवर्तन पर तुरंत अलर्ट और प्रति घंटे रिपोर्ट मिलेगी।*\n\n",
        "track_remove_hint": "❌ प्रतीक हटाएं: `/removetrack AAPL`\n",
        "track_list_hint": "📋 सूची देखें: `/mytrack`",
        "track_empty": "📌 ट्रैकिंग सूची खाली है।\n*संपत्ति ट्रैक करें* बटन दबाएं।",
        "track_list_header": "📌 *आपकी ट्रैक की गई संपत्तियां:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *मूल्य अलर्ट*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 बढ़ा",
        "track_fell": "📉 गिरा",
        "track_report_title": "📊 *प्रति घंटे रिपोर्ट — आपकी संपत्तियां*\n",
        "track_unavailable": "अनुपलब्ध",
        "track_remove_usage": "⚠️ कमांड के बाद प्रतीक भेजें। उदाहरण: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* आपकी सूची में नहीं है।",
        "track_removed": "✅ *{symbol}* ट्रैकिंग सूची से हटा दिया।",
        "interest_save_btn": "💾 सहेजें",
        "interest_choose_msg": "📌 *अपनी रुचियां चुनें (एक से अधिक):*",
        "currency_rate_header": "💱 *USD के मुकाबले विनिमय दरें 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *{amount} {currency} का रूपांतरण*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ असमर्थित मुद्रा: {currency}",
        "currency_fetch_error": "⚠️ विनिमय दरें प्राप्त नहीं हो सकीं।",
        "city_add_success": "✅ शहर जोड़ा गया: *{city}*",
        "currency_alert_set": "✅ जब डॉलर आपकी स्थानीय मुद्रा के `{rate}` पर पहुंचेगा तो सूचित किया जाएगा।",
        "currency_alert_invalid": "❌ एक संख्या भेजें, जैसे: 1600",
        "notif_time_set": "✅ सुबह की सारांश रोज *{hour}:00* बजे भेजी जाएगी।",
        "notif_time_invalid": "❌ 0 से 23 के बीच संख्या दर्ज करें (उदाहरण: 8 सुबह 8 बजे के लिए)",
    },
    "Português 🇧🇷": {
        "no_news": "⚠️ Nenhuma notícia nova agora.",
        "no_results": "⚠️ Nenhum resultado encontrado para sua pesquisa.",
        "search_error": "⚠️ Ocorreu um erro durante a pesquisa.",
        "no_trending": "⚠️ Sem notícias em alta agora, tente mais tarde.",
        "trending_header": "🔥 *Em Alta*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Notícias Esportivas*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Sem novas notícias esportivas agora.",
        "no_sports_source": "⚠️ Nenhuma fonte esportiva para este idioma.",
        "no_mena": "⚠️ Sem notícias políticas novas, tente mais tarde.",
        "no_source": "⚠️ Nenhuma fonte de notícias para este idioma.",
        "weather_error": "⚠️ Não foi possível obter dados meteorológicos.",
        "forecast_error": "⚠️ Não foi possível obter previsão por hora.",
        "no_weekly": "⚠️ Sem notícias para resumo semanal.",
        "currency_error": "⚠️ Não foi possível obter taxas de câmbio.",
        "search_prompt": "🔍 Digite a palavra de pesquisa:",
        "label_breaking": "🚨 Urgente",
        "label_news": "🚨 Notícia",
        "label_mena": "📰 Notícias Políticas do Médio Oriente",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Sua cidade ainda não foi definida.",
        "city_not_found": "⚠️ Dados meteorológicos não encontrados para: {city}",
        "weather_header": "{emoji} *Tempo em {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Sensação:* {feels}°C\n🔼 Máx: {temp_max}°C  |  🔽 Mín: {temp_min}°C\n\n☁️ *Condição:* {desc}\n🌫 *Nuvens:* {clouds}%\n👁 *Visibilidade:* {visibility_km} km\n\n💧 *Umidade:* {humidity}%\n🌀 *Pressão:* {pressure} hPa\n☀️ *Índice UV:* {uvi}\n\n💨 *Vento:* {wind_speed} m/s | {wind_dir}\n💨 *Rajadas:* {wind_gust} m/s\n\n🌅 *Nascer:* {sunrise}  |  🌇 *Pôr do sol:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Previsão de 3 dias — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Previsão de 7 dias — {city}*\n\n",
        "hourly_header": "🕐 *Tempo a cada 3 horas — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Baixo",
        "uv_moderate": "Moderado",
        "uv_high": "Alto",
        "uv_very_high": "Muito alto",
        "uv_extreme": "Extremo",
        "uv_na": "N/D",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ L",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SO",
        "wind_W": "⬅️ O",
        "wind_NW": "↖️ NO",
        "crypto_header": "💎 *Preços de Criptomoedas*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Dados do CoinGecko",
        "crypto_error": "⚠️ Não foi possível obter preços de cripto agora, tente mais tarde.",
        "prayer_header": "🕌 *Horários de Oração em {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Nascer:  `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Dados da Aladhan API",
        "prayer_no_city": "⚠️ Sua cidade não está definida. Vá às Configurações.",
        "prayer_city_error": "⚠️ Não foi possível obter horários de oração para: {city}",
        "prayer_error": "⚠️ Não foi possível obter horários de oração, tente mais tarde.",
        "referral_header": "🎁 *Sistema de Indicação*\n━━━━━━━━━━━━━━━\n\n🔗 *Seu link de indicação:*\n`{link}`\n\n👥 *Total indicados:* `{count}` pessoas\n\n━━━━━━━━━━━━━━━\n📤 Compartilhe com amigos e família!\nCada pessoa que entrar pelo seu link conta. 🎯",
        "referral_share_btn": "📤 Compartilhar Link",
        "share_bot_header": "📢 *Compartilhe o bot e ajude-nos a crescer!*\n\n🔗 *Link do bot:*\n@{username}\n\n📌 Ou via link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Compartilhe com amigos para receber:\n📰 Últimas notícias\n🌤 Tempo ao vivo\n💱 Taxas de câmbio\n🕌 Horários de oração\n💎 Preços de cripto",
        "share_bot_btn": "📤 Compartilhar Bot",
        "open_bot_btn": "🔗 Abrir Bot",
        "public_stats_header": "📊 *Estatísticas do Bot*\n━━━━━━━━━━━━━━━\n\n👥 Total de usuários: *{total}*\n✅ Usuários ativos: *{active}*\n🆕 Entraram hoje: *{today}*\n⭐ Assinantes premium: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Idiomas mais usados:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Suas Estatísticas Pessoais*\n━━━━━━━━━━━━━━━\n\n👤 Nome: *{name}*\n🌍 Idioma: *{lang}*\n🏙 Cidade: *{city}*\n📅 Data de entrada: *{join}*\n\n📰 Notícias recebidas: *{news}*\n🎁 Indicações enviadas: *{refs}*\n🔑 Palavras-chave: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notificações: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Sim",
        "my_stats_prem_no": "❌ Não",
        "my_stats_notif_on": "🔔 Ativo",
        "my_stats_notif_off": "🔕 Pausado",
        "my_stats_user": "Usuário",
        "daily_summary_header": "📋 *Resumo de Notícias de Hoje — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Nenhuma fonte de notícias para este idioma.",
        "daily_summary_no_news": "⚠️ Nenhuma notícia disponível agora, tente mais tarde.",
        "top_referrers_header": "🏆 *Melhores Indicadores*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Sem indicações ainda — seja o primeiro! 🎯",
        "top_referrers_invite": "indicação(ões)",
        "dollar_header": "💵 *USD vs Dinar Iraquiano*\n\n🏪 Mercado paralelo:\n{rate}\n\n⏰ Última atualização: `{time}`\n📡 Fonte: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Venda",
        "dollar_buy": "Compra",
        "dollar_official": "Taxa: `{price}` IQD\n_(Taxa oficial — pode diferir do mercado)_",
        "dollar_error": "⚠️ Não foi possível obter a taxa do dólar. Tente mais tarde.",
        "weekly_summary_header": "📰 *Resumo Semanal — Top {count} notícias*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Resumo de Notícias da Semana*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Coletando as principais notícias da semana...",
        "weekly_summary_text_no_source": "⚠️ Nenhuma fonte de notícias para este idioma.",
        "weekly_summary_text_no_news": "⚠️ Notícias insuficientes esta semana.",
        "currency_table_header": "📊 *Tabela Completa de Câmbio vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Menu Premium — Escolha:*",
        "premium_btn_7day": "🌤 Previsão de 7 dias",
        "premium_btn_hourly": "🕐 Tempo a cada 3 horas",
        "premium_btn_addcity": "🏙 Adicionar Cidade",
        "premium_btn_mycities": "📋 Minhas Cidades Salvas",
        "premium_btn_interests": "📌 Meus Interesses",
        "premium_btn_currency_alert": "💱 Alerta de Câmbio",
        "premium_btn_currency_table": "📊 Tabela de Câmbio",
        "premium_btn_notif_time": "🕐 Horário de Notificação",
        "premium_btn_weekly": "📰 Resumo Semanal",
        "premium_btn_keywords": "🔑 Palavras-chave",
        "premium_subscribe_btn": "⭐ Solicitar Assinatura Premium",
        "broadcast_weather_msg": "🌤 Tempo em {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Rastreamento de Ativos*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Sua lista atual:*\n",
        "track_count": "\n({count}/20 símbolos)\n\n",
        "track_add_hint": "➕ *Adicionar símbolo:* envie o nome diretamente\n\n",
        "track_crypto_label": "💎 *Criptomoedas:*\n",
        "track_fiat_label": "💱 *Moedas fiduciárias:*\n",
        "track_stocks_label": "📈 *Ações:*\n",
        "track_commodities_label": "🏅 *Commodities e Índices:*\n",
        "track_alert_hint": "🔔 *Você receberá alertas imediatos em mudanças de ±1% e relatório por hora.*\n\n",
        "track_remove_hint": "❌ Remover símbolo: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Ver sua lista: `/mytrack`",
        "track_empty": "📌 Lista de rastreamento vazia.\nToque em *Rastrear ativo* para adicionar símbolos.",
        "track_list_header": "📌 *Seus ativos rastreados:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Alertas de preço*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 subiu",
        "track_fell": "📉 caiu",
        "track_report_title": "📊 *Relatório por hora — Seus ativos*\n",
        "track_unavailable": "indisponível",
        "track_remove_usage": "⚠️ Envie o símbolo após o comando. Exemplo: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* não está na sua lista.",
        "track_removed": "✅ *{symbol}* removido da lista de rastreamento.",
        "interest_save_btn": "💾 Salvar",
        "interest_choose_msg": "📌 *Escolha seus interesses (pode ser mais de um):*",
        "currency_rate_header": "💱 *Taxas de câmbio vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Conversão de {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Moeda não suportada: {currency}",
        "currency_fetch_error": "⚠️ Não foi possível obter taxas de câmbio.",
        "city_add_success": "✅ Cidade adicionada: *{city}*",
        "currency_alert_set": "✅ Você será alertado quando o dólar atingir `{rate}` da sua moeda local.",
        "currency_alert_invalid": "❌ Envie um número, por exemplo: 1600",
        "notif_time_set": "✅ O resumo matinal será enviado às *{hour}:00* todos os dias.",
        "notif_time_invalid": "❌ Insira um número entre 0 e 23 (exemplo: 8 para 8h)",
    },
    "Türkçe 🇹🇷": {
        "no_news": "⚠️ Şu an yeni haber yok.",
        "no_results": "⚠️ Aramanız için sonuç bulunamadı.",
        "search_error": "⚠️ Arama sırasında hata oluştu.",
        "no_trending": "⚠️ Şu an trend haber yok, daha sonra deneyin.",
        "trending_header": "🔥 *Trend Haberler*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Spor Haberleri*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Şu an yeni spor haberi yok.",
        "no_sports_source": "⚠️ Bu dil için spor kaynağı yok.",
        "no_mena": "⚠️ Şu an yeni siyasi haber yok, daha sonra deneyin.",
        "no_source": "⚠️ Bu dil için haber kaynağı yok.",
        "weather_error": "⚠️ Hava durumu verisi alınamıyor.",
        "forecast_error": "⚠️ Saatlik tahmin alınamıyor.",
        "no_weekly": "⚠️ Haftalık özet için haber yok.",
        "currency_error": "⚠️ Döviz kurları alınamıyor.",
        "search_prompt": "🔍 Arama kelimesini yazın:",
        "label_breaking": "🚨 Son Dakika",
        "label_news": "🚨 Haber",
        "label_mena": "📰 Orta Doğu Siyasi Haberleri",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Şehriniz henüz ayarlanmamış.",
        "city_not_found": "⚠️ {city} için hava durumu verisi bulunamadı.",
        "weather_header": "{emoji} *{city} Hava Durumu*\n━━━━━━━━━━━━━━━\n\n🌡 *Sıcaklık:* {temp}°C\n🤔 *Hissedilen:* {feels}°C\n🔼 Maks: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Durum:* {desc}\n🌫 *Bulut:* {clouds}%\n👁 *Görüş:* {visibility_km} km\n\n💧 *Nem:* {humidity}%\n🌀 *Basınç:* {pressure} hPa\n☀️ *UV İndeksi:* {uvi}\n\n💨 *Rüzgar:* {wind_speed} m/s | {wind_dir}\n💨 *Gusts:* {wind_gust} m/s\n\n🌅 *Gündoğumu:* {sunrise}  |  🌇 *Gün batımı:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3 Günlük Hava Tahmini — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7 Günlük Hava Tahmini — {city}*\n\n",
        "hourly_header": "🕐 *3 Saatlik Hava Durumu — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Düşük",
        "uv_moderate": "Orta",
        "uv_high": "Yüksek",
        "uv_very_high": "Çok Yüksek",
        "uv_extreme": "Aşırı",
        "uv_na": "Yok",
        "wind_N": "⬆️ K",
        "wind_NE": "↗️ KD",
        "wind_E": "➡️ D",
        "wind_SE": "↘️ GD",
        "wind_S": "⬇️ G",
        "wind_SW": "↙️ GB",
        "wind_W": "⬅️ B",
        "wind_NW": "↖️ KB",
        "crypto_header": "💎 *Kripto Para Fiyatları*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 CoinGecko'dan veri",
        "crypto_error": "⚠️ Şu an kripto fiyatları alınamıyor, daha sonra deneyin.",
        "prayer_header": "🕌 *{city} Namaz Vakitleri*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 İmsak:   `{fajr}`\n☀️ Güneş:   `{sunrise}`\n🌞 Öğle:    `{dhuhr}`\n🌇 İkindi:  `{asr}`\n🌆 Akşam:   `{maghrib}`\n🌙 Yatsı:   `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Aladhan API'den veri",
        "prayer_no_city": "⚠️ Şehriniz ayarlanmamış. Ayarlara gidin.",
        "prayer_city_error": "⚠️ {city} için namaz vakitleri alınamıyor.",
        "prayer_error": "⚠️ Namaz vakitleri şu an alınamıyor, daha sonra deneyin.",
        "referral_header": "🎁 *Davet Sistemi*\n━━━━━━━━━━━━━━━\n\n🔗 *Davet linkiniz:*\n`{link}`\n\n👥 *Toplam davet:* `{count}` kişi\n\n━━━━━━━━━━━━━━━\n📤 Arkadaş ve ailenizle paylaşın!\nLinkinizle katılan herkes sayılır. 🎯",
        "referral_share_btn": "📤 Linki Paylaş",
        "share_bot_header": "📢 *Botu paylaşın ve büyümemize yardımcı olun!*\n\n🔗 *Bot linki:*\n@{username}\n\n📌 Ya da link ile:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Arkadaşlarınızla paylaşarak şunlara ulaşın:\n📰 Son haberler\n🌤 Canlı hava\n💱 Döviz kurları\n🕌 Namaz vakitleri\n💎 Kripto fiyatları",
        "share_bot_btn": "📤 Botu Paylaş",
        "open_bot_btn": "🔗 Botu Aç",
        "public_stats_header": "📊 *Bot İstatistikleri*\n━━━━━━━━━━━━━━━\n\n👥 Toplam kullanıcı: *{total}*\n✅ Aktif kullanıcı: *{active}*\n🆕 Bugün katılan: *{today}*\n⭐ Premium üye: *{premium}*\n\n",
        "public_stats_langs": "🌍 *En çok kullanılan diller:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Kişisel İstatistikleriniz*\n━━━━━━━━━━━━━━━\n\n👤 Ad: *{name}*\n🌍 Dil: *{lang}*\n🏙 Şehir: *{city}*\n📅 Katılım tarihi: *{join}*\n\n📰 Alınan haber: *{news}*\n🎁 Davet gönderilen: *{refs}*\n🔑 Anahtar kelime: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Bildirimler: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Evet",
        "my_stats_prem_no": "❌ Hayır",
        "my_stats_notif_on": "🔔 Aktif",
        "my_stats_notif_off": "🔕 Durduruldu",
        "my_stats_user": "Kullanıcı",
        "daily_summary_header": "📋 *Bugünün Haber Özeti — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Bu dil için haber kaynağı yok.",
        "daily_summary_no_news": "⚠️ Şu an haber yok, daha sonra deneyin.",
        "top_referrers_header": "🏆 *En İyi Davetçiler*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Henüz davet yok — ilk siz olun! 🎯",
        "top_referrers_invite": "davet",
        "dollar_header": "💵 *USD - Irak Dinarı*\n\n🏪 Paralel piyasa:\n{rate}\n\n⏰ Son güncelleme: `{time}`\n📡 Kaynak: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Satış",
        "dollar_buy": "Alış",
        "dollar_official": "Kur: `{price}` IQD\n_(Resmi kur — piyasadan farklı olabilir)_",
        "dollar_error": "⚠️ Dolar kuru şu an alınamıyor. Daha sonra deneyin.",
        "weekly_summary_header": "📰 *Haftalık Özet — En iyi {count} haber*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Haftalık Haber Özeti*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Haftanın öne çıkan haberleri toplanıyor...",
        "weekly_summary_text_no_source": "⚠️ Bu dil için haber kaynağı yok.",
        "weekly_summary_text_no_news": "⚠️ Bu hafta yeterli haber yok.",
        "currency_table_header": "📊 *USD'ye Karşı Tam Döviz Tablosu 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Premium Menü — Seçin:*",
        "premium_btn_7day": "🌤 7 Günlük Tahmin",
        "premium_btn_hourly": "🕐 3 Saatlik Hava",
        "premium_btn_addcity": "🏙 Şehir Ekle",
        "premium_btn_mycities": "📋 Kayıtlı Şehirlerim",
        "premium_btn_interests": "📌 İlgi Alanlarım",
        "premium_btn_currency_alert": "💱 Döviz Uyarısı",
        "premium_btn_currency_table": "📊 Döviz Tablosu",
        "premium_btn_notif_time": "🕐 Bildirim Saati",
        "premium_btn_weekly": "📰 Haftalık Özet",
        "premium_btn_keywords": "🔑 Anahtar Kelimeler",
        "premium_subscribe_btn": "⭐ Premium Üyelik Talep Et",
        "broadcast_weather_msg": "🌤 {city} hava durumu: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Döviz, Hisse ve Emtia Takibi*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Mevcut listeniz:*\n",
        "track_count": "\n({count}/20 sembol)\n\n",
        "track_add_hint": "➕ *Sembol ekle:* adını doğrudan gönderin\n\n",
        "track_crypto_label": "💎 *Kripto Paralar:*\n",
        "track_fiat_label": "💱 *Fiat Para Birimleri:*\n",
        "track_stocks_label": "📈 *Hisse Senetleri:*\n",
        "track_commodities_label": "🏅 *Emtia ve Endeksler:*\n",
        "track_alert_hint": "🔔 *±%1 değişimde anlık uyarı ve saatlik rapor alırsınız.*\n\n",
        "track_remove_hint": "❌ Sembol sil: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Listenizi görün: `/mytrack`",
        "track_empty": "📌 Takip listesi boş.\n*Varlık takip et* butonuna basın.",
        "track_list_header": "📌 *Takip ettiğiniz varlıklar:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Fiyat Uyarıları*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 yükseldi",
        "track_fell": "📉 düştü",
        "track_report_title": "📊 *Saatlik Rapor — Varlıklarınız*\n",
        "track_unavailable": "mevcut değil",
        "track_remove_usage": "⚠️ Komuttan sonra sembolü gönderin. Örnek: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* listenizde yok.",
        "track_removed": "✅ *{symbol}* takip listesinden kaldırıldı.",
        "interest_save_btn": "💾 Kaydet",
        "interest_choose_msg": "📌 *İlgi alanlarınızı seçin (birden fazla olabilir):*",
        "currency_rate_header": "💱 *USD'ye Karşı Döviz Kurları 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *{amount} {currency} Dönüşümü*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Desteklenmeyen para birimi: {currency}",
        "currency_fetch_error": "⚠️ Döviz kurları alınamıyor.",
        "city_add_success": "✅ Şehir eklendi: *{city}*",
        "currency_alert_set": "✅ Dolar yerel paranızın `{rate}` değerine ulaştığında uyarılacaksınız.",
        "currency_alert_invalid": "❌ Bir sayı gönderin, örnek: 1600",
        "notif_time_set": "✅ Sabah özeti her gün *{hour}:00*'de gönderilecek.",
        "notif_time_invalid": "❌ 0 ile 23 arasında bir sayı girin (örnek: sabah 8 için 8)",
    },
    "اردو 🇵🇰": {
        "no_news": "⚠️ ابھی کوئی نئی خبر نہیں۔",
        "no_results": "⚠️ آپ کی تلاش کا کوئی نتیجہ نہیں ملا۔",
        "search_error": "⚠️ تلاش کے دوران خرابی ہوئی۔",
        "no_trending": "⚠️ ابھی کوئی ٹرینڈنگ خبر نہیں، بعد میں کوشش کریں۔",
        "trending_header": "🔥 *ٹرینڈنگ خبریں*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *کھیل کی خبریں*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ ابھی کوئی نئی کھیل کی خبر نہیں۔",
        "no_sports_source": "⚠️ اس زبان کے لیے کوئی کھیل ذریعہ نہیں۔",
        "no_mena": "⚠️ ابھی کوئی نئی سیاسی خبر نہیں، بعد میں کوشش کریں۔",
        "no_source": "⚠️ اس زبان کے لیے کوئی خبر ذریعہ نہیں۔",
        "weather_error": "⚠️ موسم کا ڈیٹا حاصل نہیں ہو سکا۔",
        "forecast_error": "⚠️ گھنٹہ وار پیشگوئی حاصل نہیں ہو سکی۔",
        "no_weekly": "⚠️ ہفتہ وار خلاصے کے لیے کوئی خبر نہیں۔",
        "currency_error": "⚠️ کرنسی ریٹ حاصل نہیں ہو سکے۔",
        "search_prompt": "🔍 تلاش کا لفظ لکھیں:",
        "label_breaking": "🚨 بریکنگ نیوز",
        "label_news": "🚨 خبر",
        "label_mena": "📰 مشرق وسطیٰ سیاسی خبریں",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ آپ کا شہر ابھی تک سیٹ نہیں ہوا۔",
        "city_not_found": "⚠️ {city} کے لیے موسم کا ڈیٹا نہیں ملا۔",
        "weather_header": "{emoji} *{city} میں موسم*\n━━━━━━━━━━━━━━━\n\n🌡 *درجہ حرارت:* {temp}°C\n🤔 *محسوس ہوتا ہے:* {feels}°C\n🔼 زیادہ: {temp_max}°C  |  🔽 کم: {temp_min}°C\n\n☁️ *حالت:* {desc}\n🌫 *بادل:* {clouds}%\n👁 *مرئیت:* {visibility_km} کمی\n\n💧 *نمی:* {humidity}%\n🌀 *دباؤ:* {pressure} hPa\n☀️ *UV انڈیکس:* {uvi}\n\n💨 *ہوا:* {wind_speed} م/س | {wind_dir}\n💨 *جھونکے:* {wind_gust} م/س\n\n🌅 *طلوع آفتاب:* {sunrise}  |  🌇 *غروب آفتاب:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3 روزہ موسم کی پیشگوئی — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7 روزہ موسم کی پیشگوئی — {city}*\n\n",
        "hourly_header": "🕐 *ہر 3 گھنٹے کا موسم — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "م/س",
        "uv_low": "کم",
        "uv_moderate": "معتدل",
        "uv_high": "زیادہ",
        "uv_very_high": "بہت زیادہ",
        "uv_extreme": "انتہائی خطرناک",
        "uv_na": "دستیاب نہیں",
        "wind_N": "⬆️ شمال",
        "wind_NE": "↗️ شمال مشرق",
        "wind_E": "➡️ مشرق",
        "wind_SE": "↘️ جنوب مشرق",
        "wind_S": "⬇️ جنوب",
        "wind_SW": "↙️ جنوب مغرب",
        "wind_W": "⬅️ مغرب",
        "wind_NW": "↖️ شمال مغرب",
        "crypto_header": "💎 *کرپٹو کرنسی کے نرخ*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 CoinGecko سے ڈیٹا",
        "crypto_error": "⚠️ ابھی کرپٹو کی قیمتیں حاصل نہیں ہو سکیں، بعد میں کوشش کریں۔",
        "prayer_header": "🕌 *{city} میں نماز کے اوقات*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 فجر:     `{fajr}`\n☀️ طلوع:    `{sunrise}`\n🌞 ظہر:     `{dhuhr}`\n🌇 عصر:     `{asr}`\n🌆 مغرب:    `{maghrib}`\n🌙 عشاء:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Aladhan API سے ڈیٹا",
        "prayer_no_city": "⚠️ آپ کا شہر سیٹ نہیں۔ ترتیبات میں جائیں۔",
        "prayer_city_error": "⚠️ {city} کے نماز اوقات حاصل نہیں ہو سکے۔",
        "prayer_error": "⚠️ نماز اوقات ابھی حاصل نہیں ہو سکے، بعد میں کوشش کریں۔",
        "referral_header": "🎁 *دعوت نظام*\n━━━━━━━━━━━━━━━\n\n🔗 *آپ کا دعوت لنک:*\n`{link}`\n\n👥 *کل مدعو:* `{count}` افراد\n\n━━━━━━━━━━━━━━━\n📤 دوستوں اور خاندان کے ساتھ شیئر کریں!\nآپ کے لنک سے شامل ہونے والا ہر شخص گنا جائے گا۔ 🎯",
        "referral_share_btn": "📤 لنک شیئر کریں",
        "share_bot_header": "📢 *بوٹ شیئر کریں اور ہماری ترقی میں مدد کریں!*\n\n🔗 *بوٹ لنک:*\n@{username}\n\n📌 یا لنک سے:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 دوستوں کے ساتھ شیئر کریں:",
        "share_bot_btn": "📤 بوٹ شیئر کریں",
        "open_bot_btn": "🔗 بوٹ کھولیں",
        "public_stats_header": "📊 *بوٹ کے اعداد و شمار*\n━━━━━━━━━━━━━━━\n\n👥 کل صارفین: *{total}*\n✅ فعال صارفین: *{active}*\n🆕 آج شامل ہوئے: *{today}*\n⭐ پریمیم ممبران: *{premium}*\n\n",
        "public_stats_langs": "🌍 *سب سے زیادہ استعمال ہونے والی زبانیں:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *آپ کے ذاتی اعداد و شمار*\n━━━━━━━━━━━━━━━\n\n👤 نام: *{name}*\n🌍 زبان: *{lang}*\n🏙 شہر: *{city}*\n📅 شمولیت کی تاریخ: *{join}*\n\n📰 موصولہ خبریں: *{news}*\n🎁 بھیجی گئی دعوتیں: *{refs}*\n🔑 کلیدی الفاظ: *{kws}*\n⭐ پریمیم: *{prem}*\n🔔 اطلاعات: *{notif}*\n",
        "my_stats_prem_yes": "⭐ ہاں",
        "my_stats_prem_no": "❌ نہیں",
        "my_stats_notif_on": "🔔 فعال",
        "my_stats_notif_off": "🔕 بند",
        "my_stats_user": "صارف",
        "daily_summary_header": "📋 *آج کی خبروں کا خلاصہ — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ اس زبان کے لیے کوئی خبر ذریعہ نہیں۔",
        "daily_summary_no_news": "⚠️ ابھی کوئی خبر دستیاب نہیں، بعد میں کوشش کریں۔",
        "top_referrers_header": "🏆 *بہترین دعوت دہندگان*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 ابھی کوئی دعوت نہیں — پہلے بنیں! 🎯",
        "top_referrers_invite": "دعوت",
        "dollar_header": "💵 *امریکی ڈالر بمقابلہ عراقی دینار*\n\n🏪 متوازی مارکیٹ:\n{rate}\n\n⏰ آخری اپ ڈیٹ: `{time}`\n📡 ذریعہ: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "فروخت",
        "dollar_buy": "خریداری",
        "dollar_official": "شرح: `{price}` IQD\n_(سرکاری شرح — بازار سے مختلف ہو سکتی ہے)_",
        "dollar_error": "⚠️ ابھی ڈالر کی شرح حاصل نہیں ہو سکی۔ بعد میں کوشش کریں۔",
        "weekly_summary_header": "📰 *ہفتہ وار خلاصہ — بہترین {count} خبریں*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *ہفتہ وار خبروں کا خلاصہ*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ اس ہفتے کی اہم خبریں جمع کی جا رہی ہیں...",
        "weekly_summary_text_no_source": "⚠️ اس زبان کے لیے کوئی خبر ذریعہ نہیں۔",
        "weekly_summary_text_no_news": "⚠️ اس ہفتے کافی خبریں نہیں۔",
        "currency_table_header": "📊 *USD کے مقابلے مکمل زر مبادلہ جدول 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *پریمیم مینو — انتخاب کریں:*",
        "premium_btn_7day": "🌤 7 روزہ پیشگوئی",
        "premium_btn_hourly": "🕐 ہر 3 گھنٹے کا موسم",
        "premium_btn_addcity": "🏙 شہر شامل کریں",
        "premium_btn_mycities": "📋 میرے محفوظ شہر",
        "premium_btn_interests": "📌 میری دلچسپیاں",
        "premium_btn_currency_alert": "💱 کرنسی الرٹ",
        "premium_btn_currency_table": "📊 کرنسی جدول",
        "premium_btn_notif_time": "🕐 اطلاع کا وقت",
        "premium_btn_weekly": "📰 ہفتہ وار خلاصہ",
        "premium_btn_keywords": "🔑 کلیدی الفاظ",
        "premium_subscribe_btn": "⭐ پریمیم سبسکرپشن کی درخواست کریں",
        "broadcast_weather_msg": "🌤 {city} میں موسم: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *کرنسیوں، حصص اور اجناس کی نگرانی*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *آپ کی موجودہ فہرست:*\n",
        "track_count": "\n({count}/20 علامات)\n\n",
        "track_add_hint": "➕ *علامت شامل کریں:* اس کا نام سیدھا بھیجیں\n\n",
        "track_crypto_label": "💎 *کرپٹو کرنسیاں:*\n",
        "track_fiat_label": "💱 *فیاٹ کرنسیاں:*\n",
        "track_stocks_label": "📈 *حصص:*\n",
        "track_commodities_label": "🏅 *اجناس اور اشاریہ جات:*\n",
        "track_alert_hint": "🔔 *±1٪ تبدیلی پر فوری الرٹ اور گھنٹہ وار رپورٹ ملے گی۔*\n\n",
        "track_remove_hint": "❌ علامت حذف کریں: `/removetrack AAPL`\n",
        "track_list_hint": "📋 اپنی فہرست دیکھیں: `/mytrack`",
        "track_empty": "📌 ٹریکنگ فہرست خالی ہے۔\n*اثاثہ ٹریک کریں* کا بٹن دبائیں۔",
        "track_list_header": "📌 *آپ کے ٹریک شدہ اثاثے:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *قیمتوں کے الرٹ*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 بڑھا",
        "track_fell": "📉 گرا",
        "track_report_title": "📊 *گھنٹہ وار رپورٹ — آپ کے اثاثے*\n",
        "track_unavailable": "دستیاب نہیں",
        "track_remove_usage": "⚠️ کمانڈ کے بعد علامت بھیجیں۔ مثال: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* آپ کی فہرست میں نہیں۔",
        "track_removed": "✅ *{symbol}* ٹریکنگ فہرست سے حذف ہو گیا۔",
        "interest_save_btn": "💾 محفوظ کریں",
        "interest_choose_msg": "📌 *اپنی دلچسپیاں چنیں (ایک سے زیادہ ہو سکتی ہیں):*",
        "currency_rate_header": "💱 *USD کے مقابلے زر مبادلہ 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *{amount} {currency} کی تبدیلی*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ غیر معاون کرنسی: {currency}",
        "currency_fetch_error": "⚠️ زر مبادلہ حاصل نہیں ہو سکے۔",
        "city_add_success": "✅ شہر شامل ہوا: *{city}*",
        "currency_alert_set": "✅ جب ڈالر آپ کی مقامی کرنسی کے `{rate}` تک پہنچے گا تو الرٹ ملے گا۔",
        "currency_alert_invalid": "❌ ایک نمبر بھیجیں، جیسے: 1600",
        "notif_time_set": "✅ صبح کا خلاصہ روزانہ *{hour}:00* بجے بھیجا جائے گا۔",
        "notif_time_invalid": "❌ 0 سے 23 کے درمیان نمبر درج کریں (مثال: 8 صبح 8 بجے کے لیے)",
    },
    "Deutsch 🇩🇪": {
        "no_news": "⚠️ Derzeit keine neuen Nachrichten.",
        "no_results": "⚠️ Keine Ergebnisse für Ihre Suche gefunden.",
        "search_error": "⚠️ Fehler bei der Suche.",
        "no_trending": "⚠️ Derzeit keine Trend-Nachrichten, versuchen Sie es später.",
        "trending_header": "🔥 *Trending*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Sportnachrichten*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Derzeit keine neuen Sportnachrichten.",
        "no_sports_source": "⚠️ Keine Sportquellen für diese Sprache.",
        "no_mena": "⚠️ Derzeit keine neuen politischen Nachrichten.",
        "no_source": "⚠️ Keine Nachrichtenquellen für diese Sprache.",
        "weather_error": "⚠️ Wetterdaten können nicht abgerufen werden.",
        "forecast_error": "⚠️ Stundenvorhersage kann nicht abgerufen werden.",
        "no_weekly": "⚠️ Keine Nachrichten für wöchentliche Zusammenfassung.",
        "currency_error": "⚠️ Wechselkurse können nicht abgerufen werden.",
        "search_prompt": "🔍 Suchbegriff eingeben:",
        "label_breaking": "🚨 Eilmeldung",
        "label_news": "🚨 Nachricht",
        "label_mena": "📰 Nahost-Politiknachrichten",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Ihre Stadt ist noch nicht festgelegt.",
        "city_not_found": "⚠️ Keine Wetterdaten für: {city}",
        "weather_header": "{emoji} *Wetter in {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Gefühlt:* {feels}°C\n🔼 Max: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Zustand:* {desc}\n🌫 *Wolken:* {clouds}%\n👁 *Sichtweite:* {visibility_km} km\n\n💧 *Luftfeuchte:* {humidity}%\n🌀 *Luftdruck:* {pressure} hPa\n☀️ *UV-Index:* {uvi}\n\n💨 *Wind:* {wind_speed} m/s | {wind_dir}\n💨 *Böen:* {wind_gust} m/s\n\n🌅 *Sonnenaufgang:* {sunrise}  |  🌇 *Sonnenuntergang:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3-Tage-Wettervorhersage — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7-Tage-Wettervorhersage — {city}*\n\n",
        "hourly_header": "🕐 *Wetter alle 3 Stunden — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Niedrig",
        "uv_moderate": "Mäßig",
        "uv_high": "Hoch",
        "uv_very_high": "Sehr hoch",
        "uv_extreme": "Extrem",
        "uv_na": "N/V",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NO",
        "wind_E": "➡️ O",
        "wind_SE": "↘️ SO",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SW",
        "wind_W": "⬅️ W",
        "wind_NW": "↖️ NW",
        "crypto_header": "💎 *Kryptopreise*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Daten von CoinGecko",
        "crypto_error": "⚠️ Kryptopreise können derzeit nicht abgerufen werden.",
        "prayer_header": "🕌 *Gebetszeiten in {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Aufgang: `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Daten von Aladhan API",
        "prayer_no_city": "⚠️ Ihre Stadt ist nicht festgelegt. Gehen Sie zu Einstellungen.",
        "prayer_city_error": "⚠️ Gebetszeiten für {city} können nicht abgerufen werden.",
        "prayer_error": "⚠️ Gebetszeiten derzeit nicht abrufbar, versuchen Sie es später.",
        "referral_header": "🎁 *Empfehlungssystem*\n━━━━━━━━━━━━━━━\n\n🔗 *Ihr Empfehlungslink:*\n`{link}`\n\n👥 *Insgesamt eingeladen:* `{count}` Personen\n\n━━━━━━━━━━━━━━━\n📤 Mit Freunden und Familie teilen!\nJeder, der über Ihren Link beitritt, wird gezählt. 🎯",
        "referral_share_btn": "📤 Link teilen",
        "share_bot_header": "📢 *Bot teilen und uns beim Wachsen helfen!*\n\n🔗 *Bot-Link:*\n@{username}\n\n📌 Oder per Link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Mit Freunden teilen für:\n📰 Aktuelle Nachrichten\n🌤 Live-Wetter\n💱 Wechselkurse\n🕌 Gebetszeiten\n💎 Kryptokurse",
        "share_bot_btn": "📤 Bot teilen",
        "open_bot_btn": "🔗 Bot öffnen",
        "public_stats_header": "📊 *Bot-Statistiken*\n━━━━━━━━━━━━━━━\n\n👥 Gesamte Nutzer: *{total}*\n✅ Aktive Nutzer: *{active}*\n🆕 Heute beigetreten: *{today}*\n⭐ Premium-Abonnenten: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Am häufigsten verwendete Sprachen:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Ihre persönlichen Statistiken*\n━━━━━━━━━━━━━━━\n\n👤 Name: *{name}*\n🌍 Sprache: *{lang}*\n🏙 Stadt: *{city}*\n📅 Beitrittsdatum: *{join}*\n\n📰 Erhaltene Nachrichten: *{news}*\n🎁 Gesendete Empfehlungen: *{refs}*\n🔑 Schlüsselwörter: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Benachrichtigungen: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Ja",
        "my_stats_prem_no": "❌ Nein",
        "my_stats_notif_on": "🔔 Aktiv",
        "my_stats_notif_off": "🔕 Pausiert",
        "my_stats_user": "Benutzer",
        "daily_summary_header": "📋 *Heutige Nachrichtenübersicht — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Keine Nachrichtenquellen für diese Sprache.",
        "daily_summary_no_news": "⚠️ Keine Nachrichten verfügbar, versuchen Sie es später.",
        "top_referrers_header": "🏆 *Top-Empfehlende*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Noch keine Empfehlungen — seien Sie der Erste! 🎯",
        "top_referrers_invite": "Einladung(en)",
        "dollar_header": "💵 *USD vs Irakischer Dinar*\n\n🏪 Parallelmarkt:\n{rate}\n\n⏰ Zuletzt aktualisiert: `{time}`\n📡 Quelle: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Verkauf",
        "dollar_buy": "Kauf",
        "dollar_official": "Kurs: `{price}` IQD\n_(Offizieller Kurs — kann vom Markt abweichen)_",
        "dollar_error": "⚠️ Dollarkurs derzeit nicht abrufbar. Versuchen Sie es später.",
        "weekly_summary_header": "📰 *Wochenrückblick — Top {count} Nachrichten*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Wöchentliche Nachrichtenübersicht*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Die wichtigsten Nachrichten der Woche werden gesammelt...",
        "weekly_summary_text_no_source": "⚠️ Keine Nachrichtenquellen für diese Sprache.",
        "weekly_summary_text_no_news": "⚠️ Nicht genug Nachrichten diese Woche.",
        "currency_table_header": "📊 *Vollständige Wechselkurstabelle vs. USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Premium-Menü — Wählen:*",
        "premium_btn_7day": "🌤 7-Tage-Vorhersage",
        "premium_btn_hourly": "🕐 Wetter alle 3 Std.",
        "premium_btn_addcity": "🏙 Stadt hinzufügen",
        "premium_btn_mycities": "📋 Meine gespeicherten Städte",
        "premium_btn_interests": "📌 Meine Interessen",
        "premium_btn_currency_alert": "💱 Währungsalarm",
        "premium_btn_currency_table": "📊 Währungstabelle",
        "premium_btn_notif_time": "🕐 Benachrichtigungszeit",
        "premium_btn_weekly": "📰 Wochenübersicht",
        "premium_btn_keywords": "🔑 Schlüsselwörter",
        "premium_subscribe_btn": "⭐ Premium-Abonnement anfragen",
        "broadcast_weather_msg": "🌤 Wetter in {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Währungen, Aktien und Rohstoffe verfolgen*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Ihre aktuelle Liste:*\n",
        "track_count": "\n({count}/20 Symbole)\n\n",
        "track_add_hint": "➕ *Symbol hinzufügen:* Namen direkt senden\n\n",
        "track_crypto_label": "💎 *Kryptowährungen:*\n",
        "track_fiat_label": "💱 *Fiat-Währungen:*\n",
        "track_stocks_label": "📈 *Aktien:*\n",
        "track_commodities_label": "🏅 *Rohstoffe und Indizes:*\n",
        "track_alert_hint": "🔔 *Bei ±1% Änderung erhalten Sie sofortige Benachrichtigungen und stündliche Berichte.*\n\n",
        "track_remove_hint": "❌ Symbol entfernen: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Liste anzeigen: `/mytrack`",
        "track_empty": "📌 Verfolgungsliste ist leer.\nDrücken Sie *Asset verfolgen*, um Symbole hinzuzufügen.",
        "track_list_header": "📌 *Ihre verfolgten Assets:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Preisalarme*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 gestiegen",
        "track_fell": "📉 gefallen",
        "track_report_title": "📊 *Stündlicher Bericht — Ihre Assets*\n",
        "track_unavailable": "nicht verfügbar",
        "track_remove_usage": "⚠️ Senden Sie das Symbol nach dem Befehl. Beispiel: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* ist nicht in Ihrer Liste.",
        "track_removed": "✅ *{symbol}* aus der Verfolgungsliste entfernt.",
        "interest_save_btn": "💾 Speichern",
        "interest_choose_msg": "📌 *Wählen Sie Ihre Interessen (mehrere möglich):*",
        "currency_rate_header": "💱 *Wechselkurse vs. USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Umrechnung von {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Nicht unterstützte Währung: {currency}",
        "currency_fetch_error": "⚠️ Wechselkurse können nicht abgerufen werden.",
        "city_add_success": "✅ Stadt hinzugefügt: *{city}*",
        "currency_alert_set": "✅ Sie werden benachrichtigt, wenn der Dollar `{rate}` Ihrer Lokalwährung erreicht.",
        "currency_alert_invalid": "❌ Senden Sie eine Zahl, z. B.: 1600",
        "notif_time_set": "✅ Die Morgenzusammenfassung wird täglich um *{hour}:00* Uhr gesendet.",
        "notif_time_invalid": "❌ Geben Sie eine Zahl zwischen 0 und 23 ein (Beispiel: 8 für 8 Uhr morgens)",
    },
    "Українська 🇺🇦": {
        "no_news": "⚠️ Зараз немає нових новин.",
        "no_results": "⚠️ За вашим запитом нічого не знайдено.",
        "search_error": "⚠️ Під час пошуку сталася помилка.",
        "no_trending": "⚠️ Немає трендових новин, спробуйте пізніше.",
        "trending_header": "🔥 *У тренді*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Спортивні новини*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Нових спортивних новин немає.",
        "no_sports_source": "⚠️ Немає спортивних джерел для цієї мови.",
        "no_mena": "⚠️ Нових політичних новин немає, спробуйте пізніше.",
        "no_source": "⚠️ Немає джерел новин для цієї мови.",
        "weather_error": "⚠️ Не вдається отримати дані про погоду.",
        "forecast_error": "⚠️ Не вдається отримати погодинний прогноз.",
        "no_weekly": "⚠️ Немає новин для тижневого підсумку.",
        "currency_error": "⚠️ Не вдається отримати курси валют.",
        "search_prompt": "🔍 Введіть слово для пошуку:",
        "label_breaking": "🚨 Термінова новина",
        "label_news": "🚨 Новина",
        "label_mena": "📰 Близький Схід",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Ваше місто ще не вказано.",
        "city_not_found": "⚠️ Дані про погоду не знайдено для: {city}",
        "weather_header": "{emoji} *Погода в {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Темп:* {temp}°C\n🤔 *Відчувається:* {feels}°C\n🔼 Макс: {temp_max}°C  |  🔽 Мін: {temp_min}°C\n\n☁️ *Стан:* {desc}\n🌫 *Хмарність:* {clouds}%\n👁 *Видимість:* {visibility_km} км\n\n💧 *Вологість:* {humidity}%\n🌀 *Тиск:* {pressure} hPa\n☀️ *УФ-індекс:* {uvi}\n\n💨 *Вітер:* {wind_speed} м/с | {wind_dir}\n💨 *Пориви:* {wind_gust} м/с\n\n🌅 *Схід:* {sunrise}  |  🌇 *Захід:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Прогноз на 3 дні — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Прогноз на 7 днів — {city}*\n\n",
        "hourly_header": "🕐 *Погода кожні 3 години — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "м/с",
        "uv_low": "Низький",
        "uv_moderate": "Помірний",
        "uv_high": "Високий",
        "uv_very_high": "Дуже високий",
        "uv_extreme": "Екстремальний",
        "uv_na": "Н/Д",
        "wind_N": "⬆️ П",
        "wind_NE": "↗️ ПС",
        "wind_E": "➡️ С",
        "wind_SE": "↘️ ПС",
        "wind_S": "⬇️ Пд",
        "wind_SW": "↙️ ПдЗ",
        "wind_W": "⬅️ З",
        "wind_NW": "↖️ ПнЗ",
        "crypto_header": "💎 *Курси криптовалют*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Дані від CoinGecko",
        "crypto_error": "⚠️ Не вдається отримати курси криптовалют, спробуйте пізніше.",
        "prayer_header": "🕌 *Час молитов у {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Фаджр:   `{fajr}`\n☀️ Схід:    `{sunrise}`\n🌞 Зухр:    `{dhuhr}`\n🌇 Аср:     `{asr}`\n🌆 Магріб:  `{maghrib}`\n🌙 Іша:     `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Дані від Aladhan API",
        "prayer_no_city": "⚠️ Ваше місто не вказано. Перейдіть до налаштувань.",
        "prayer_city_error": "⚠️ Не вдається отримати час молитов для: {city}",
        "prayer_error": "⚠️ Час молитов зараз недоступний, спробуйте пізніше.",
        "referral_header": "🎁 *Реферальна система*\n━━━━━━━━━━━━━━━\n\n🔗 *Ваше реферальне посилання:*\n`{link}`\n\n👥 *Усього запрошено:* `{count}` осіб\n\n━━━━━━━━━━━━━━━\n📤 Поділіться з друзями та родиною!\nКожен, хто приєднається за вашим посиланням, буде зарахований. 🎯",
        "referral_share_btn": "📤 Поділитися посиланням",
        "share_bot_header": "📢 *Поділіться ботом і допоможіть нам зростати!*\n\n🔗 *Посилання на бот:*\n@{username}\n\n📌 Або за посиланням:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Поділіться з друзями для отримання:\n📰 Останні новини\n🌤 Погода онлайн\n💱 Курси валют\n🕌 Час молитов\n💎 Курси криптовалют",
        "share_bot_btn": "📤 Поділитися ботом",
        "open_bot_btn": "🔗 Відкрити бот",
        "public_stats_header": "📊 *Статистика бота*\n━━━━━━━━━━━━━━━\n\n👥 Всього користувачів: *{total}*\n✅ Активних: *{active}*\n🆕 Приєдналися сьогодні: *{today}*\n⭐ Преміум-передплатників: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Найбільш використовувані мови:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Ваша особиста статистика*\n━━━━━━━━━━━━━━━\n\n👤 Ім'я: *{name}*\n🌍 Мова: *{lang}*\n🏙 Місто: *{city}*\n📅 Дата реєстрації: *{join}*\n\n📰 Отримано новин: *{news}*\n🎁 Надіслано запрошень: *{refs}*\n🔑 Ключових слів: *{kws}*\n⭐ Преміум: *{prem}*\n🔔 Сповіщення: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Так",
        "my_stats_prem_no": "❌ Ні",
        "my_stats_notif_on": "🔔 Активні",
        "my_stats_notif_off": "🔕 Вимкнені",
        "my_stats_user": "Користувач",
        "daily_summary_header": "📋 *Зведення новин за {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Немає джерел новин для цієї мови.",
        "daily_summary_no_news": "⚠️ Немає доступних новин, спробуйте пізніше.",
        "top_referrers_header": "🏆 *Кращі реферери*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Поки немає рефералів — будьте першим! 🎯",
        "top_referrers_invite": "запрошення",
        "dollar_header": "💵 *Долар США до іракського динара*\n\n🏪 Паралельний ринок:\n{rate}\n\n⏰ Останнє оновлення: `{time}`\n📡 Джерело: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Продаж",
        "dollar_buy": "Купівля",
        "dollar_official": "Курс: `{price}` IQD\n_(Офіційний курс — може відрізнятися від ринкового)_",
        "dollar_error": "⚠️ Не вдається отримати курс долара. Спробуйте пізніше.",
        "weekly_summary_header": "📰 *Тижневий огляд — Топ {count} новин*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Тижневе зведення новин*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Збираємо головні новини тижня...",
        "weekly_summary_text_no_source": "⚠️ Немає доступних джерел для цієї мови.",
        "weekly_summary_text_no_news": "⚠️ Недостатньо новин цього тижня.",
        "currency_table_header": "📊 *Повна таблиця курсів валют до USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Преміум-меню — Оберіть:*",
        "premium_btn_7day": "🌤 Прогноз на 7 днів",
        "premium_btn_hourly": "🕐 Погода кожні 3 год.",
        "premium_btn_addcity": "🏙 Додати місто",
        "premium_btn_mycities": "📋 Мої збережені міста",
        "premium_btn_interests": "📌 Мої інтереси",
        "premium_btn_currency_alert": "💱 Сповіщення про валюту",
        "premium_btn_currency_table": "📊 Таблиця валют",
        "premium_btn_notif_time": "🕐 Час сповіщень",
        "premium_btn_weekly": "📰 Тижневий огляд",
        "premium_btn_keywords": "🔑 Ключові слова",
        "premium_subscribe_btn": "⭐ Запросити преміум-передплату",
        "broadcast_weather_msg": "🌤 Погода в {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Відстеження валют, акцій та товарів*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Ваш поточний список:*\n",
        "track_count": "\n({count}/20 символів)\n\n",
        "track_add_hint": "➕ *Додати символ:* надішліть його назву\n\n",
        "track_crypto_label": "💎 *Криптовалюти:*\n",
        "track_fiat_label": "💱 *Фіатні валюти:*\n",
        "track_stocks_label": "📈 *Акції:*\n",
        "track_commodities_label": "🏅 *Сировина та індекси:*\n",
        "track_alert_hint": "🔔 *При зміні ±1% ви отримаєте миттєві сповіщення та щогодинний звіт.*\n\n",
        "track_remove_hint": "❌ Видалити символ: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Переглянути список: `/mytrack`",
        "track_empty": "📌 Список відстеження порожній.\nНатисніть *Відстежити актив*, щоб додати символи.",
        "track_list_header": "📌 *Ваші відстежувані активи:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Цінові сповіщення*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 зріс",
        "track_fell": "📉 впав",
        "track_report_title": "📊 *Щогодинний звіт — Ваші активи*\n",
        "track_unavailable": "недоступно",
        "track_remove_usage": "⚠️ Вкажіть символ після команди. Приклад: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* не знайдено у вашому списку.",
        "track_removed": "✅ *{symbol}* видалено зі списку відстеження.",
        "interest_save_btn": "💾 Зберегти",
        "interest_choose_msg": "📌 *Оберіть свої інтереси (можна кілька):*",
        "currency_rate_header": "💱 *Курси валют до USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Конвертація {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Непідтримувана валюта: {currency}",
        "currency_fetch_error": "⚠️ Не вдається отримати курси валют.",
        "city_add_success": "✅ Місто додано: *{city}*",
        "currency_alert_set": "✅ Ви отримаєте сповіщення, коли долар досягне `{rate}` вашої місцевої валюти.",
        "currency_alert_invalid": "❌ Введіть число, наприклад: 1600",
        "notif_time_set": "✅ Ранковий підсумок надсилатиметься щодня о *{hour}:00*.",
        "notif_time_invalid": "❌ Введіть число від 0 до 23 (наприклад: 8 для 8 ранку)",
    },
    "Italiano 🇮🇹": {
        "no_news": "⚠️ Nessuna notizia nuova al momento.",
        "no_results": "⚠️ Nessun risultato trovato per la tua ricerca.",
        "search_error": "⚠️ Si è verificato un errore durante la ricerca.",
        "no_trending": "⚠️ Nessuna notizia di tendenza ora, riprova più tardi.",
        "trending_header": "🔥 *In Tendenza*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Notizie Sportive*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Nessuna nuova notizia sportiva al momento.",
        "no_sports_source": "⚠️ Nessuna fonte sportiva per questa lingua.",
        "no_mena": "⚠️ Nessuna nuova notizia politica, riprova più tardi.",
        "no_source": "⚠️ Nessuna fonte di notizie per questa lingua.",
        "weather_error": "⚠️ Impossibile recuperare i dati meteo.",
        "forecast_error": "⚠️ Impossibile recuperare le previsioni orarie.",
        "no_weekly": "⚠️ Nessuna notizia per il riepilogo settimanale.",
        "currency_error": "⚠️ Impossibile recuperare i tassi di cambio.",
        "search_prompt": "🔍 Inserisci la parola di ricerca:",
        "label_breaking": "🚨 Notizia Flash",
        "label_news": "🚨 Notizia",
        "label_mena": "📰 Notizie Politiche del Medio Oriente",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ La tua città non è ancora impostata.",
        "city_not_found": "⚠️ Dati meteo non trovati per: {city}",
        "weather_header": "{emoji} *Meteo a {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Percepita:* {feels}°C\n🔼 Max: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Condizione:* {desc}\n🌫 *Nuvole:* {clouds}%\n👁 *Visibilità:* {visibility_km} km\n\n💧 *Umidità:* {humidity}%\n🌀 *Pressione:* {pressure} hPa\n☀️ *Indice UV:* {uvi}\n\n💨 *Vento:* {wind_speed} m/s | {wind_dir}\n💨 *Raffiche:* {wind_gust} m/s\n\n🌅 *Alba:* {sunrise}  |  🌇 *Tramonto:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Previsioni 3 giorni — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Previsioni 7 giorni — {city}*\n\n",
        "hourly_header": "🕐 *Meteo ogni 3 ore — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Basso",
        "uv_moderate": "Moderato",
        "uv_high": "Alto",
        "uv_very_high": "Molto alto",
        "uv_extreme": "Estremo",
        "uv_na": "N/D",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ E",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SO",
        "wind_W": "⬅️ O",
        "wind_NW": "↖️ NO",
        "crypto_header": "💎 *Prezzi Crypto*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Dati da CoinGecko",
        "crypto_error": "⚠️ Impossibile recuperare i prezzi crypto, riprova più tardi.",
        "prayer_header": "🕌 *Orari di Preghiera a {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Alba:    `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Dati da Aladhan API",
        "prayer_no_city": "⚠️ La tua città non è impostata. Vai alle impostazioni.",
        "prayer_city_error": "⚠️ Impossibile recuperare gli orari di preghiera per: {city}",
        "prayer_error": "⚠️ Impossibile recuperare gli orari di preghiera, riprova più tardi.",
        "referral_header": "🎁 *Sistema di Referral*\n━━━━━━━━━━━━━━━\n\n🔗 *Il tuo link di referral:*\n`{link}`\n\n👥 *Totale invitati:* `{count}` persone\n\n━━━━━━━━━━━━━━━\n📤 Condividi con amici e familiari!\nOgni persona che si unisce tramite il tuo link conta. 🎯",
        "referral_share_btn": "📤 Condividi Link",
        "share_bot_header": "📢 *Condividi il bot e aiutaci a crescere!*\n\n🔗 *Link del bot:*\n@{username}\n\n📌 O tramite link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Condividi con gli amici per ottenere:\n📰 Ultime notizie\n🌤 Meteo in diretta\n💱 Tassi di cambio\n🕌 Orari di preghiera\n💎 Prezzi crypto",
        "share_bot_btn": "📤 Condividi Bot",
        "open_bot_btn": "🔗 Apri Bot",
        "public_stats_header": "📊 *Statistiche del Bot*\n━━━━━━━━━━━━━━━\n\n👥 Utenti totali: *{total}*\n✅ Utenti attivi: *{active}*\n🆕 Iscritti oggi: *{today}*\n⭐ Abbonati premium: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Lingue più usate:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Le Tue Statistiche Personali*\n━━━━━━━━━━━━━━━\n\n👤 Nome: *{name}*\n🌍 Lingua: *{lang}*\n🏙 Città: *{city}*\n📅 Data iscrizione: *{join}*\n\n📰 Notizie ricevute: *{news}*\n🎁 Referral inviati: *{refs}*\n🔑 Parole chiave: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notifiche: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Sì",
        "my_stats_prem_no": "❌ No",
        "my_stats_notif_on": "🔔 Attive",
        "my_stats_notif_off": "🔕 In pausa",
        "my_stats_user": "Utente",
        "daily_summary_header": "📋 *Sommario Notizie di Oggi — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Nessuna fonte di notizie per questa lingua.",
        "daily_summary_no_news": "⚠️ Nessuna notizia disponibile, riprova più tardi.",
        "top_referrers_header": "🏆 *Migliori Referrer*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Nessun referral ancora — sii il primo! 🎯",
        "top_referrers_invite": "invito/i",
        "dollar_header": "💵 *USD vs Dinaro Iracheno*\n\n🏪 Mercato parallelo:\n{rate}\n\n⏰ Ultimo aggiornamento: `{time}`\n📡 Fonte: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Vendita",
        "dollar_buy": "Acquisto",
        "dollar_official": "Tasso: `{price}` IQD\n_(Tasso ufficiale — può differire dal mercato)_",
        "dollar_error": "⚠️ Impossibile recuperare il tasso del dollaro. Riprova più tardi.",
        "weekly_summary_header": "📰 *Riepilogo Settimanale — Top {count} notizie*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Riepilogo Notizie della Settimana*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Raccogliendo le principali notizie della settimana...",
        "weekly_summary_text_no_source": "⚠️ Nessuna fonte di notizie per questa lingua.",
        "weekly_summary_text_no_news": "⚠️ Notizie insufficienti questa settimana.",
        "currency_table_header": "📊 *Tabella Completa Tassi di Cambio vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Menu Premium — Scegli:*",
        "premium_btn_7day": "🌤 Previsioni 7 giorni",
        "premium_btn_hourly": "🕐 Meteo ogni 3 ore",
        "premium_btn_addcity": "🏙 Aggiungi Città",
        "premium_btn_mycities": "📋 Le mie città salvate",
        "premium_btn_interests": "📌 I miei interessi",
        "premium_btn_currency_alert": "💱 Avviso valuta",
        "premium_btn_currency_table": "📊 Tabella valute",
        "premium_btn_notif_time": "🕐 Orario notifiche",
        "premium_btn_weekly": "📰 Riepilogo settimanale",
        "premium_btn_keywords": "🔑 Parole chiave",
        "premium_subscribe_btn": "⭐ Richiedi Abbonamento Premium",
        "broadcast_weather_msg": "🌤 Meteo a {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Monitoraggio Valute, Azioni e Materie Prime*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *La tua lista attuale:*\n",
        "track_count": "\n({count}/20 simboli)\n\n",
        "track_add_hint": "➕ *Aggiungi simbolo:* invia il suo nome direttamente\n\n",
        "track_crypto_label": "💎 *Criptovalute:*\n",
        "track_fiat_label": "💱 *Valute Fiat:*\n",
        "track_stocks_label": "📈 *Azioni:*\n",
        "track_commodities_label": "🏅 *Materie Prime e Indici:*\n",
        "track_alert_hint": "🔔 *Riceverai avvisi immediati a variazioni di ±1% e report orari.*\n\n",
        "track_remove_hint": "❌ Rimuovi simbolo: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Visualizza la lista: `/mytrack`",
        "track_empty": "📌 Lista monitoraggio vuota.\nPremi *Monitora asset* per aggiungere simboli.",
        "track_list_header": "📌 *I tuoi asset monitorati:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Avvisi di prezzo*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 salito",
        "track_fell": "📉 sceso",
        "track_report_title": "📊 *Report orario — I tuoi asset*\n",
        "track_unavailable": "non disponibile",
        "track_remove_usage": "⚠️ Invia il simbolo dopo il comando. Esempio: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* non è nella tua lista.",
        "track_removed": "✅ *{symbol}* rimosso dalla lista di monitoraggio.",
        "interest_save_btn": "💾 Salva",
        "interest_choose_msg": "📌 *Scegli i tuoi interessi (puoi sceglierne più di uno):*",
        "currency_rate_header": "💱 *Tassi di cambio vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Conversione di {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Valuta non supportata: {currency}",
        "currency_fetch_error": "⚠️ Impossibile recuperare i tassi di cambio.",
        "city_add_success": "✅ Città aggiunta: *{city}*",
        "currency_alert_set": "✅ Sarai avvisato quando il dollaro raggiungerà `{rate}` della tua valuta locale.",
        "currency_alert_invalid": "❌ Invia un numero, ad esempio: 1600",
        "notif_time_set": "✅ Il riepilogo mattutino sarà inviato alle *{hour}:00* ogni giorno.",
        "notif_time_invalid": "❌ Inserisci un numero tra 0 e 23 (esempio: 8 per le 8 di mattina)",
    },
    "Español 🇲🇽": {
        "no_news": "⚠️ No hay noticias nuevas ahora.",
        "no_results": "⚠️ No se encontraron resultados para tu búsqueda.",
        "search_error": "⚠️ Se produjo un error durante la búsqueda.",
        "no_trending": "⚠️ No hay noticias en tendencia ahora, inténtalo más tarde.",
        "trending_header": "🔥 *En Tendencia*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Noticias Deportivas*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ No hay noticias deportivas nuevas ahora.",
        "no_sports_source": "⚠️ No hay fuentes deportivas para este idioma.",
        "no_mena": "⚠️ No hay noticias políticas nuevas, inténtalo más tarde.",
        "no_source": "⚠️ No hay fuentes de noticias para este idioma.",
        "weather_error": "⚠️ No se pueden obtener datos del tiempo.",
        "forecast_error": "⚠️ No se puede obtener el pronóstico por hora.",
        "no_weekly": "⚠️ No hay noticias para el resumen semanal.",
        "currency_error": "⚠️ No se pueden obtener las tasas de cambio.",
        "search_prompt": "🔍 Escribe la palabra de búsqueda:",
        "label_breaking": "🚨 Última Hora",
        "label_news": "🚨 Noticia",
        "label_mena": "📰 Noticias Políticas del Medio Oriente",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Tu ciudad aún no está configurada.",
        "city_not_found": "⚠️ No se encontraron datos del tiempo para: {city}",
        "weather_header": "{emoji} *Tiempo en {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Sensación:* {feels}°C\n🔼 Máx: {temp_max}°C  |  🔽 Mín: {temp_min}°C\n\n☁️ *Condición:* {desc}\n🌫 *Nubes:* {clouds}%\n👁 *Visibilidad:* {visibility_km} km\n\n💧 *Humedad:* {humidity}%\n🌀 *Presión:* {pressure} hPa\n☀️ *Índice UV:* {uvi}\n\n💨 *Viento:* {wind_speed} m/s | {wind_dir}\n💨 *Ráfagas:* {wind_gust} m/s\n\n🌅 *Amanecer:* {sunrise}  |  🌇 *Atardecer:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Pronóstico de 3 días — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Pronóstico de 7 días — {city}*\n\n",
        "hourly_header": "🕐 *Tiempo cada 3 horas — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Bajo",
        "uv_moderate": "Moderado",
        "uv_high": "Alto",
        "uv_very_high": "Muy alto",
        "uv_extreme": "Extremo",
        "uv_na": "N/D",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ E",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SO",
        "wind_W": "⬅️ O",
        "wind_NW": "↖️ NO",
        "crypto_header": "💎 *Precios de Criptomonedas*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Datos de CoinGecko",
        "crypto_error": "⚠️ No se pueden obtener precios crypto ahora, inténtalo más tarde.",
        "prayer_header": "🕌 *Horarios de Oración en {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Amanecer:`{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Datos de Aladhan API",
        "prayer_no_city": "⚠️ Tu ciudad no está configurada. Ve a Ajustes.",
        "prayer_city_error": "⚠️ No se pueden obtener horarios de oración para: {city}",
        "prayer_error": "⚠️ No se pueden obtener horarios de oración ahora, inténtalo más tarde.",
        "referral_header": "🎁 *Sistema de Referidos*\n━━━━━━━━━━━━━━━\n\n🔗 *Tu enlace de referido:*\n`{link}`\n\n👥 *Total invitados:* `{count}` personas\n\n━━━━━━━━━━━━━━━\n📤 ¡Comparte con amigos y familia!\nCada persona que se una a través de tu enlace cuenta. 🎯",
        "referral_share_btn": "📤 Compartir Enlace",
        "share_bot_header": "📢 *¡Comparte el bot y ayúdanos a crecer!*\n\n🔗 *Enlace del bot:*\n@{username}\n\n📌 O mediante enlace:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Comparte con amigos para obtener:\n📰 Últimas noticias\n🌤 Tiempo en directo\n💱 Tasas de cambio\n🕌 Horarios de oración\n💎 Precios crypto",
        "share_bot_btn": "📤 Compartir Bot",
        "open_bot_btn": "🔗 Abrir Bot",
        "public_stats_header": "📊 *Estadísticas del Bot*\n━━━━━━━━━━━━━━━\n\n👥 Usuarios totales: *{total}*\n✅ Usuarios activos: *{active}*\n🆕 Se unieron hoy: *{today}*\n⭐ Suscriptores premium: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Idiomas más usados:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Tus Estadísticas Personales*\n━━━━━━━━━━━━━━━\n\n👤 Nombre: *{name}*\n🌍 Idioma: *{lang}*\n🏙 Ciudad: *{city}*\n📅 Fecha de ingreso: *{join}*\n\n📰 Noticias recibidas: *{news}*\n🎁 Referidos enviados: *{refs}*\n🔑 Palabras clave: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notificaciones: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Sí",
        "my_stats_prem_no": "❌ No",
        "my_stats_notif_on": "🔔 Activas",
        "my_stats_notif_off": "🔕 Pausadas",
        "my_stats_user": "Usuario",
        "daily_summary_header": "📋 *Resumen de Noticias de Hoy — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ No hay fuentes de noticias para este idioma.",
        "daily_summary_no_news": "⚠️ No hay noticias disponibles ahora, inténtalo más tarde.",
        "top_referrers_header": "🏆 *Mejores Referidores*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Aún no hay referidos — ¡sé el primero! 🎯",
        "top_referrers_invite": "invitación(es)",
        "dollar_header": "💵 *USD vs Dinar Iraquí*\n\n🏪 Mercado paralelo:\n{rate}\n\n⏰ Última actualización: `{time}`\n📡 Fuente: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Venta",
        "dollar_buy": "Compra",
        "dollar_official": "Tasa: `{price}` IQD\n_(Tasa oficial — puede diferir del mercado)_",
        "dollar_error": "⚠️ No se puede obtener la tasa del dólar ahora. Inténtalo más tarde.",
        "weekly_summary_header": "📰 *Resumen Semanal — Top {count} noticias*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Resumen de Noticias de la Semana*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Recopilando las principales noticias de la semana...",
        "weekly_summary_text_no_source": "⚠️ No hay fuentes de noticias para este idioma.",
        "weekly_summary_text_no_news": "⚠️ No hay suficientes noticias esta semana.",
        "currency_table_header": "📊 *Tabla Completa de Tasas de Cambio vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Menú Premium — Elige:*",
        "premium_btn_7day": "🌤 Pronóstico de 7 días",
        "premium_btn_hourly": "🕐 Tiempo cada 3 horas",
        "premium_btn_addcity": "🏙 Agregar Ciudad",
        "premium_btn_mycities": "📋 Mis Ciudades Guardadas",
        "premium_btn_interests": "📌 Mis Intereses",
        "premium_btn_currency_alert": "💱 Alerta de Divisas",
        "premium_btn_currency_table": "📊 Tabla de Divisas",
        "premium_btn_notif_time": "🕐 Hora de Notificación",
        "premium_btn_weekly": "📰 Resumen Semanal",
        "premium_btn_keywords": "🔑 Palabras Clave",
        "premium_subscribe_btn": "⭐ Solicitar Suscripción Premium",
        "broadcast_weather_msg": "🌤 Tiempo en {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Seguimiento de Divisas, Acciones y Materias Primas*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Tu lista actual:*\n",
        "track_count": "\n({count}/20 símbolos)\n\n",
        "track_add_hint": "➕ *Agregar símbolo:* envía su nombre directamente\n\n",
        "track_crypto_label": "💎 *Criptomonedas:*\n",
        "track_fiat_label": "💱 *Divisas Fiat:*\n",
        "track_stocks_label": "📈 *Acciones:*\n",
        "track_commodities_label": "🏅 *Materias Primas e Índices:*\n",
        "track_alert_hint": "🔔 *Recibirás alertas inmediatas a cambios de ±1% y reporte por hora.*\n\n",
        "track_remove_hint": "❌ Eliminar símbolo: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Ver tu lista: `/mytrack`",
        "track_empty": "📌 Lista de seguimiento vacía.\nPresiona *Rastrear activo* para agregar símbolos.",
        "track_list_header": "📌 *Tus activos rastreados:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Alertas de precios*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 subió",
        "track_fell": "📉 bajó",
        "track_report_title": "📊 *Reporte por hora — Tus activos*\n",
        "track_unavailable": "no disponible",
        "track_remove_usage": "⚠️ Envía el símbolo después del comando. Ejemplo: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* no está en tu lista.",
        "track_removed": "✅ *{symbol}* eliminado de la lista de seguimiento.",
        "interest_save_btn": "💾 Guardar",
        "interest_choose_msg": "📌 *Elige tus intereses (puedes elegir más de uno):*",
        "currency_rate_header": "💱 *Tasas de cambio vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Conversión de {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Divisa no compatible: {currency}",
        "currency_fetch_error": "⚠️ No se pueden obtener las tasas de cambio.",
        "city_add_success": "✅ Ciudad agregada: *{city}*",
        "currency_alert_set": "✅ Se te avisará cuando el dólar alcance `{rate}` de tu moneda local.",
        "currency_alert_invalid": "❌ Envía un número, por ejemplo: 1600",
        "notif_time_set": "✅ El resumen matinal se enviará a las *{hour}:00* todos los días.",
        "notif_time_invalid": "❌ Ingresa un número entre 0 y 23 (ejemplo: 8 para las 8 de la mañana)",
    },
}

def t(lang, key):
    """ترجمة رسالة نظام حسب لغة المستخدم مع الرجوع للإنجليزية إذا لم توجد."""
    return MSGS.get(lang, MSGS["English 🇬🇧"]).get(key, MSGS["English 🇬🇧"].get(key, ""))

# ======== رسائل الإعداد والتفاعل المترجمة ========
SETUP_MSGS = {
    "العربية 🇮🇶": {
        "choose_country": "🌍 اختر دولتك:",
        "choose_province": "🏙 اختر محافظتك:",
        "settings_saved": "✅ تم حفظ اختياراتك\nستصلك الأخبار والطقس تلقائيًا كل ساعة.",
        "choose_country_from_list": "👇 الرجاء اختيار دولة من القائمة.",
        "choose_province_from_list": "👇 الرجاء اختيار محافظة من القائمة.",
        "notif_enabled": "🔔 تم تفعيل الإشعارات التلقائية.",
        "notif_disabled": "🔕 تم إيقاف الإشعارات التلقائية.",
        "convert_prompt": "🔄 أرسل المبلغ والعملة، مثال:\n*100 USD*\n*50 EUR*\n*200 IQD*",
        "convert_format_error": "⚠️ صيغة غير صحيحة. مثال: *100 USD*",
        "convert_send_both": "⚠️ أرسل المبلغ والعملة معاً. مثال: *100 USD*",
        "keywords_saved": "✅ تم حفظ {n} كلمة مفتاحية.\n🔔 ستصلك تنبيه عند ظهورها في أي خبر!",
    },
    "English 🇬🇧": {
        "choose_country": "🌍 Choose your country:",
        "choose_province": "🏙 Choose your city/province:",
        "settings_saved": "✅ Your settings have been saved!\nYou'll receive news and weather automatically every hour.",
        "choose_country_from_list": "👇 Please select a country from the list.",
        "choose_province_from_list": "👇 Please select a city from the list.",
        "notif_enabled": "🔔 Automatic notifications have been enabled.",
        "notif_disabled": "🔕 Automatic notifications have been disabled.",
        "convert_prompt": "🔄 Send the amount and currency, example:\n*100 USD*\n*50 EUR*\n*200 GBP*",
        "convert_format_error": "⚠️ Invalid format. Example: *100 USD*",
        "convert_send_both": "⚠️ Send the amount and currency together. Example: *100 USD*",
        "keywords_saved": "✅ {n} keyword(s) saved.\n🔔 You'll be alerted when they appear in any news!",
    },
    "Русский 🇷🇺": {
        "choose_country": "🌍 Выберите страну:",
        "choose_province": "🏙 Выберите город/регион:",
        "settings_saved": "✅ Ваши настройки сохранены!\nВы будете получать новости и погоду автоматически каждый час.",
        "choose_country_from_list": "👇 Пожалуйста, выберите страну из списка.",
        "choose_province_from_list": "👇 Пожалуйста, выберите город из списка.",
        "notif_enabled": "🔔 Автоматические уведомления включены.",
        "notif_disabled": "🔕 Автоматические уведомления отключены.",
        "convert_prompt": "🔄 Отправьте сумму и валюту, например:\n*100 USD*\n*50 EUR*\n*200 RUB*",
        "convert_format_error": "⚠️ Неверный формат. Пример: *100 USD*",
        "convert_send_both": "⚠️ Отправьте сумму и валюту вместе. Пример: *100 USD*",
        "keywords_saved": "✅ Сохранено {n} ключевых слов.\n🔔 Вы получите уведомление, когда они появятся в новостях!",
    },
    "فارسی 🇮🇷": {
        "choose_country": "🌍 کشور خود را انتخاب کنید:",
        "choose_province": "🏙 استان/شهر خود را انتخاب کنید:",
        "settings_saved": "✅ تنظیمات شما ذخیره شد!\nاخبار و آبوهوا هر ساعت برایتان ارسال میشود.",
        "choose_country_from_list": "👇 لطفاً یک کشور از لیست انتخاب کنید.",
        "choose_province_from_list": "👇 لطفاً یک شهر از لیست انتخاب کنید.",
        "notif_enabled": "🔔 اعلانهای خودکار فعال شد.",
        "notif_disabled": "🔕 اعلانهای خودکار غیرفعال شد.",
        "convert_prompt": "🔄 مبلغ و ارز را ارسال کنید، مثال:\n*100 USD*\n*50 EUR*\n*200 IRR*",
        "convert_format_error": "⚠️ فرمت نادرست. مثال: *100 USD*",
        "convert_send_both": "⚠️ مبلغ و ارز را با هم بفرستید. مثال: *100 USD*",
        "keywords_saved": "✅ {n} کلمه کلیدی ذخیره شد.\n🔔 هنگامی که در اخباری ظاهر شوند اطلاعرسانی میشوید!",
    },
    "हिन्दी 🇮🇳": {
        "choose_country": "🌍 अपना देश चुनें:",
        "choose_province": "🏙 अपना शहर/राज्य चुनें:",
        "settings_saved": "✅ आपकी सेटिंग सेव हो गई!\nआपको हर घंटे स्वचालित रूप से समाचार और मौसम मिलेगा।",
        "choose_country_from_list": "👇 कृपया सूची से एक देश चुनें।",
        "choose_province_from_list": "👇 कृपया सूची से एक शहर चुनें।",
        "notif_enabled": "🔔 स्वचालित सूचनाएं सक्रिय की गईं।",
        "notif_disabled": "🔕 स्वचालित सूचनाएं बंद की गईं।",
        "convert_prompt": "🔄 राशि और मुद्रा भेजें, उदाहरण:\n*100 USD*\n*50 EUR*\n*200 INR*",
        "convert_format_error": "⚠️ गलत प्रारूप। उदाहरण: *100 USD*",
        "convert_send_both": "⚠️ राशि और मुद्रा एक साथ भेजें। उदाहरण: *100 USD*",
        "keywords_saved": "✅ {n} कीवर्ड सेव किए गए।\n🔔 जब भी वे किसी खबर में आएंगे आपको अलर्ट मिलेगा!",
    },
    "Português 🇧🇷": {
        "choose_country": "🌍 Escolha seu país:",
        "choose_province": "🏙 Escolha sua cidade/estado:",
        "settings_saved": "✅ Suas configurações foram salvas!\nVocê receberá notícias e clima automaticamente a cada hora.",
        "choose_country_from_list": "👇 Por favor, selecione um país da lista.",
        "choose_province_from_list": "👇 Por favor, selecione uma cidade da lista.",
        "notif_enabled": "🔔 Notificações automáticas ativadas.",
        "notif_disabled": "🔕 Notificações automáticas desativadas.",
        "convert_prompt": "🔄 Envie o valor e a moeda, exemplo:\n*100 USD*\n*50 EUR*\n*200 BRL*",
        "convert_format_error": "⚠️ Formato inválido. Exemplo: *100 USD*",
        "convert_send_both": "⚠️ Envie o valor e a moeda juntos. Exemplo: *100 USD*",
        "keywords_saved": "✅ {n} palavra(s)-chave salva(s).\n🔔 Você será alertado quando aparecerem em qualquer notícia!",
    },
    "Türkçe 🇹🇷": {
        "choose_country": "🌍 Ülkenizi seçin:",
        "choose_province": "🏙 Şehrinizi seçin:",
        "settings_saved": "✅ Ayarlarınız kaydedildi!\nHer saat otomatik olarak haber ve hava durumu alacaksınız.",
        "choose_country_from_list": "👇 Lütfen listeden bir ülke seçin.",
        "choose_province_from_list": "👇 Lütfen listeden bir şehir seçin.",
        "notif_enabled": "🔔 Otomatik bildirimler etkinleştirildi.",
        "notif_disabled": "🔕 Otomatik bildirimler devre dışı bırakıldı.",
        "convert_prompt": "🔄 Tutarı ve para birimini gönderin, örnek:\n*100 USD*\n*50 EUR*\n*200 TRY*",
        "convert_format_error": "⚠️ Geçersiz format. Örnek: *100 USD*",
        "convert_send_both": "⚠️ Tutarı ve para birimini birlikte gönderin. Örnek: *100 USD*",
        "keywords_saved": "✅ {n} anahtar kelime kaydedildi.\n🔔 Herhangi bir haberde göründüklerinde uyarılacaksınız!",
    },
    "اردو 🇵🇰": {
        "choose_country": "🌍 اپنا ملک منتخب کریں:",
        "choose_province": "🏙 اپنا شہر منتخب کریں:",
        "settings_saved": "✅ آپ کی ترتیبات محفوظ ہو گئیں!\nآپ کو ہر گھنٹے خودکار طور پر خبریں اور موسم ملے گا۔",
        "choose_country_from_list": "👇 براہ کرم فہرست سے ایک ملک منتخب کریں۔",
        "choose_province_from_list": "👇 براہ کرم فہرست سے ایک شہر منتخب کریں۔",
        "notif_enabled": "🔔 خودکار اطلاعات فعال ہو گئیں۔",
        "notif_disabled": "🔕 خودکار اطلاعات بند ہو گئیں۔",
        "convert_prompt": "🔄 رقم اور کرنسی بھیجیں، مثال:\n*100 USD*\n*50 EUR*\n*200 PKR*",
        "convert_format_error": "⚠️ غلط فارمیٹ۔ مثال: *100 USD*",
        "convert_send_both": "⚠️ رقم اور کرنسی ایک ساتھ بھیجیں۔ مثال: *100 USD*",
        "keywords_saved": "✅ {n} مطلوبہ الفاظ محفوظ ہوئے۔\n🔔 جب کسی خبر میں آئیں گے آپ کو اطلاع ملے گی!",
    },
    "Deutsch 🇩🇪": {
        "choose_country": "🌍 Wählen Sie Ihr Land:",
        "choose_province": "🏙 Wählen Sie Ihre Stadt:",
        "settings_saved": "✅ Ihre Einstellungen wurden gespeichert!\nSie erhalten stündlich automatisch Nachrichten und Wetter.",
        "choose_country_from_list": "👇 Bitte wählen Sie ein Land aus der Liste.",
        "choose_province_from_list": "👇 Bitte wählen Sie eine Stadt aus der Liste.",
        "notif_enabled": "🔔 Automatische Benachrichtigungen wurden aktiviert.",
        "notif_disabled": "🔕 Automatische Benachrichtigungen wurden deaktiviert.",
        "convert_prompt": "🔄 Betrag und Währung senden, Beispiel:\n*100 USD*\n*50 EUR*\n*200 CHF*",
        "convert_format_error": "⚠️ Ungültiges Format. Beispiel: *100 USD*",
        "convert_send_both": "⚠️ Betrag und Währung zusammen senden. Beispiel: *100 USD*",
        "keywords_saved": "✅ {n} Schlüsselwörter gespeichert.\n🔔 Sie werden benachrichtigt, wenn sie in Nachrichten erscheinen!",
    },
    "Українська 🇺🇦": {
        "choose_country": "🌍 Виберіть свою країну:",
        "choose_province": "🏙 Виберіть своє місто:",
        "settings_saved": "✅ Ваші налаштування збережено!\nВи будете автоматично отримувати новини і погоду кожну годину.",
        "choose_country_from_list": "👇 Будь ласка, виберіть країну зі списку.",
        "choose_province_from_list": "👇 Будь ласка, виберіть місто зі списку.",
        "notif_enabled": "🔔 Автоматичні сповіщення увімкнено.",
        "notif_disabled": "🔕 Автоматичні сповіщення вимкнено.",
        "convert_prompt": "🔄 Надішліть суму та валюту, наприклад:\n*100 USD*\n*50 EUR*\n*200 UAH*",
        "convert_format_error": "⚠️ Невірний формат. Приклад: *100 USD*",
        "convert_send_both": "⚠️ Надішліть суму і валюту разом. Приклад: *100 USD*",
        "keywords_saved": "✅ Збережено {n} ключових слів.\n🔔 Ви будете повідомлені, коли вони з'являться в новинах!",
    },
    "Italiano 🇮🇹": {
        "choose_country": "🌍 Scegli il tuo paese:",
        "choose_province": "🏙 Scegli la tua città:",
        "settings_saved": "✅ Le tue impostazioni sono state salvate!\nRiceverai notizie e meteo automaticamente ogni ora.",
        "choose_country_from_list": "👇 Per favore seleziona un paese dall'elenco.",
        "choose_province_from_list": "👇 Per favore seleziona una città dall'elenco.",
        "notif_enabled": "🔔 Notifiche automatiche attivate.",
        "notif_disabled": "🔕 Notifiche automatiche disattivate.",
        "convert_prompt": "🔄 Invia l'importo e la valuta, esempio:\n*100 USD*\n*50 EUR*\n*200 CHF*",
        "convert_format_error": "⚠️ Formato non valido. Esempio: *100 USD*",
        "convert_send_both": "⚠️ Invia importo e valuta insieme. Esempio: *100 USD*",
        "keywords_saved": "✅ {n} parola/e chiave salvata/e.\n🔔 Sarai avvisato quando appariranno in qualsiasi notizia!",
    },
    "Español 🇲🇽": {
        "choose_country": "🌍 Elige tu país:",
        "choose_province": "🏙 Elige tu ciudad:",
        "settings_saved": "✅ ¡Tu configuración ha sido guardada!\nRecibirás noticias y clima automáticamente cada hora.",
        "choose_country_from_list": "👇 Por favor selecciona un país de la lista.",
        "choose_province_from_list": "👇 Por favor selecciona una ciudad de la lista.",
        "notif_enabled": "🔔 Las notificaciones automáticas han sido activadas.",
        "notif_disabled": "🔕 Las notificaciones automáticas han sido desactivadas.",
        "convert_prompt": "🔄 Envía el monto y la moneda, ejemplo:\n*100 USD*\n*50 EUR*\n*200 MXN*",
        "convert_format_error": "⚠️ Formato no válido. Ejemplo: *100 USD*",
        "convert_send_both": "⚠️ Envía el monto y la moneda juntos. Ejemplo: *100 USD*",
        "keywords_saved": "✅ Se guardaron {n} palabras clave.\n🔔 ¡Serás alertado cuando aparezcan en cualquier noticia!",
    },
}

def st(lang, key, **kwargs):
    """ترجمة رسائل الإعداد والتفاعل حسب لغة المستخدم."""
    text = SETUP_MSGS.get(lang, SETUP_MSGS["English 🇬🇧"]).get(
        key, SETUP_MSGS["English 🇬🇧"].get(key, "")
    )
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text

# ======== cache مؤقت لملخصات الأخبار ========
import hashlib
_news_summary_cache = {}

def _cache_summary(link, summary_text):
    """تخزين ملخص الخبر مع مفتاح MD5 مختصر."""
    key = hashlib.md5(link.encode("utf-8")).hexdigest()[:16]
    if len(_news_summary_cache) > 2000:
        oldest = list(_news_summary_cache.keys())[:500]
        for k in oldest:
            del _news_summary_cache[k]
    _news_summary_cache[key] = summary_text
    return key

def _clean_html(text):
    """إزالة وسوم HTML من الملخص."""
    import re
    text = re.sub(r'<[^>]+>', '', text or '')
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    return text.strip()

# ======== دوال الأخبار ========
def format_news_item(prefix, title):
    label = news_settings.get("label", prefix)
    return f"{label}\n\n📰 {title}{get_news_signature()}"

def make_news_share_markup(link, title="", lang="English 🇬🇧", summary=""):
    import urllib.parse
    lbl = NEWS_SHARE_LABELS.get(lang, NEWS_SHARE_LABELS["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup(row_width=2)
    via_text = lbl["via"]
    share_text = f"📰 {title[:100]}\n\n🔗 {link}\n\n{via_text} @{BOT_USERNAME}" if title else f"🔗 {link}\n\n{via_text} @{BOT_USERNAME}"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(link, safe='')}&text={urllib.parse.quote(share_text, safe='')}"
    bot_link = f"https://t.me/{BOT_USERNAME}"
    bot_share_text = f"@{BOT_USERNAME}\n{lbl['bot_promo']}"
    bot_share_url = f"https://t.me/share/url?url={urllib.parse.quote(bot_link, safe='')}&text={urllib.parse.quote(bot_share_text, safe='')}"
    if link:
        markup.add(
            types.InlineKeyboardButton(lbl["open"], url=link),
            types.InlineKeyboardButton(lbl["share_news"], url=share_url)
        )
    else:
        markup.add(
            types.InlineKeyboardButton(lbl["share_news"], url=share_url)
        )
    clean_summary = _clean_html(summary)
    if clean_summary and link:
        sum_key = _cache_summary(link, clean_summary)
        markup.add(
            types.InlineKeyboardButton(lbl["summary_btn"], callback_data=f"sum_{sum_key}")
        )
    markup.add(
        types.InlineKeyboardButton(f"{lbl['share_bot']} @{BOT_USERNAME}", url=bot_share_url)
    )
    return markup

def send_hourly_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    sent = user.setdefault("sent_news", set())
    count = 0
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:3]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(item.link, getattr(item, 'title', ''), lang, item_sum)
                bot.send_message(uid, format_news_item(t(lang, "label_news"), item.title), parse_mode="Markdown", reply_markup=markup)
                count += 1
        except Exception as e:
            notify_admin_error(f"خطأ في RSS ({feed_url}): {e}")
    if count == 0:
        bot.send_message(uid, t(lang, "no_news"))
    else:
        _db_save_all_users(users)

def send_all_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    sent = user.setdefault("sent_news", set())
    count = 0
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:15]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(item.link, getattr(item, 'title', ''), lang, item_sum)
                bot.send_message(uid, format_news_item(t(lang, "label_breaking"), item.title), parse_mode="Markdown", reply_markup=markup)
                count += 1
        except Exception as e:
            notify_admin_error(f"خطأ في RSS ({feed_url}): {e}")
    if count == 0:
        bot.send_message(uid, t(lang, "no_news"))
    else:
        _db_save_all_users(users)

def send_mena_politics(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "العربية 🇮🇶")
    mena_feeds = MENA_RSS.get(lang, MENA_RSS.get("العربية 🇮🇶", []))
    sent = user.setdefault("sent_news", set())
    count = 0
    headlines_sent = []
    for feed_url in mena_feeds:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:10]:
                title = getattr(item, 'title', '')
                link = getattr(item, 'link', '')
                if not link:
                    continue
                if link in sent:
                    continue
                sent.add(link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(link, title, lang, item_sum)
                bot.send_message(uid, format_news_item(t(lang, "label_mena"), title), parse_mode="Markdown", reply_markup=markup)
                headlines_sent.append(title)
                count += 1
                if count >= 10:
                    break
        except Exception as e:
            notify_admin_error(f"خطأ في RSS MENA ({feed_url}): {e}")
        if count >= 10:
            break
    if count == 0:
        general_feeds = RSS.get(lang, [])
        for feed_url in general_feeds:
            try:
                feed = feedparser.parse(feed_url)
                for item in feed.entries[:20]:
                    title = getattr(item, 'title', '')
                    link = getattr(item, 'link', '')
                    if not link or link in sent:
                        continue
                    title_lower = title.lower()
                    if any(kw.lower() in title_lower for kw in MENA_KEYWORDS):
                        sent.add(link)
                        item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                        markup = make_news_share_markup(link, title, lang, item_sum)
                        bot.send_message(uid, format_news_item(t(lang, "label_mena"), title), parse_mode="Markdown", reply_markup=markup)
                        count += 1
                        if count >= 5:
                            break
            except Exception as e:
                notify_admin_error(f"خطأ في RSS fallback MENA: {e}")
            if count >= 5:
                break
    if count == 0:
        bot.send_message(uid, t(lang, "no_news"))
    else:
        _db_save_all_users(users)

# ======== البث التلقائي ========
def broadcast_weather():
    # تم إزالة البث التلقائي للطقس — الطقس يُرسل فقط عند طلب المستخدم
    # هذه الدالة محجوزة للاستخدام اليدوي إذا أراد الأدمن ذلك
    pass

def broadcast_news():
    try:
        rss_cache = {}
        for uid, info in list(users.items()):
            try:
                if int(uid) in banned:
                    continue
                if not info.get("notifications", True):
                    continue
                lang = info.get("lang", "English 🇬🇧")
                feeds = RSS.get(lang, [])
                sent = info.setdefault("sent_news", set())
                changed = False
                for feed_url in feeds:
                    if feed_url not in rss_cache:
                        try:
                            rss_cache[feed_url] = feedparser.parse(feed_url)
                        except Exception:
                            rss_cache[feed_url] = None
                    feed = rss_cache.get(feed_url)
                    if not feed:
                        continue
                    for item in feed.entries[:50]:
                        if not hasattr(item, 'link') or item.link in sent:
                            continue
                        title = getattr(item, 'title', '')
                        if is_blacklisted(title):
                            continue
                        sent.add(item.link)
                        changed = True
                        item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                        markup = make_news_share_markup(item.link, title, lang, item_sum)
                        queue_send(uid, format_news_item(t(lang, "label_breaking"), title),
                            parse_mode="Markdown", reply_markup=markup)
                if changed:
                    _db_save_user(uid, info)
            except Exception:
                continue
    except Exception as e:
        try:
            bot.send_message(ADMIN_ID, f"⚠️ خطأ في broadcast_news: {e}")
        except Exception:
            pass

def send_sports_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = SPORTS_RSS.get(lang, SPORTS_RSS.get("English 🇬🇧", []))
    if not feeds:
        bot.send_message(uid, t(lang, "no_sports_source"))
        return
    sent = user.setdefault("sent_news", set())
    count = 0
    bot.send_message(uid, t(lang, "sports_header"), parse_mode="Markdown")
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:5]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(item.link, getattr(item, 'title', ''), lang, item_sum)
                bot.send_message(uid, format_news_item(t(lang, "label_sports"), item.title), parse_mode="Markdown", reply_markup=markup)
                count += 1
                if count >= 8:
                    break
        except Exception as e:
            notify_admin_error(f"خطأ في أخبار الرياضة: {e}")
        if count >= 8:
            break
    if count == 0:
        bot.send_message(uid, t(lang, "no_sports"))
    else:
        _db_save_all_users(users)

# ======== محوّل العملات ========
CURRENCY_SYMBOLS = {
    "USD": "🇺🇸 دولار أمريكي",
    "EUR": "🇪🇺 يورو",
    "GBP": "🇬🇧 جنيه إسترليني",
    "IQD": "🇮🇶 دينار عراقي",
    "SAR": "🇸🇦 ريال سعودي",
    "AED": "🇦🇪 درهم إماراتي",
    "TRY": "🇹🇷 ليرة تركية",
    "IRR": "🇮🇷 ريال إيراني",
    "KWD": "🇰🇼 دينار كويتي",
    "JOD": "🇯🇴 دينار أردني",
    "EGP": "🇪🇬 جنيه مصري",
    "RUB": "🇷🇺 روبل روسي",
    "CNY": "🇨🇳 يوان صيني",
    "INR": "🇮🇳 روبية هندية",
}

def convert_currency_msg(uid, amount, from_currency):
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
        r = requests.get(url, timeout=10).json()
        rates = r.get("rates", {})
        if not rates:
            bot.send_message(uid, f"⚠️ عملة غير مدعومة: {from_currency}")
            return
        targets = ["USD", "EUR", "IQD", "SAR", "AED", "GBP", "TRY", "KWD", "EGP", "RUB"]
        msg = f"🔄 *تحويل {amount:,.2f} {from_currency}*\n━━━━━━━━━━━━━━━\n\n"
        for t in targets:
            if t == from_currency:
                continue
            rate = rates.get(t)
            if rate:
                converted = amount * rate
                label = CURRENCY_SYMBOLS.get(t, t)
                msg += f"{label}: *{converted:,.2f}*\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ لا يمكن جلب أسعار الصرف الآن.")
        notify_admin_error(f"خطأ في محوّل العملات: {e}")

# ======== إحصائيات المستخدم الشخصية ========
def send_my_stats(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    name = user.get("name", t(lang, "my_stats_user"))
    province = user.get("province", "—")
    sent_news = user.get("sent_news", set())
    referrals = user.get("referrals", [])
    is_prem = t(lang, "my_stats_prem_yes") if is_premium(uid) else t(lang, "my_stats_prem_no")
    notif = t(lang, "my_stats_notif_on") if user.get("notifications", True) else t(lang, "my_stats_notif_off")
    join_date = user.get("join_date", "—")
    kws = user_keywords.get(str(uid), [])
    msg = t(lang, "my_stats_header").format(
        name=name, lang=lang, city=province, join=join_date,
        news=len(sent_news), refs=len(referrals), kws=len(kws),
        prem=is_prem, notif=notif
    )
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== توقعات 3 أيام (مجانية) ========
def send_3day_forecast(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    province = user.get("province", "")
    if not province:
        bot.send_message(uid, t(lang, "no_city"))
        return
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}&cnt=24"
        data = requests.get(url, timeout=10).json()
        if str(data.get("cod")) != "200":
            bot.send_message(uid, t(lang, "city_not_found").format(city=province))
            return
        days = {}
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            if date not in days:
                days[date] = {"temps": [], "descs": [], "icons": []}
            days[date]["temps"].append(item["main"]["temp"])
            days[date]["descs"].append(item["weather"][0]["description"])
            days[date]["icons"].append(item["weather"][0]["id"])
        msg = t(lang, "forecast_3day_header").format(city=province)
        day_names = list(days.items())[:3]
        for date, info in day_names:
            min_t = round(min(info["temps"]))
            max_t = round(max(info["temps"]))
            desc = info["descs"][len(info["descs"])//2]
            icon = get_weather_emoji(info["icons"][len(info["icons"])//2])
            msg += f"{icon} *{date}*\n"
            msg += f"   🌡 {min_t}°C — {max_t}°C\n"
            msg += f"   ☁️ {desc.capitalize()}\n\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "weather_error"))
        notify_admin_error(f"خطأ في توقعات 3 أيام لـ {uid}: {e}")

# ======== ترتيب أفضل الداعين ========
def send_top_referrers(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    referral_counts = []
    for user_id, info in users.items():
        refs = info.get("referrals", [])
        if refs:
            name = info.get("name", t(lang, "my_stats_user"))
            referral_counts.append((name, len(refs)))
    referral_counts.sort(key=lambda x: x[1], reverse=True)
    top = referral_counts[:10]
    if not top:
        bot.send_message(uid, t(lang, "top_referrers_empty"))
        return
    medals = ["🥇", "🥈", "🥉"] + ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    invite_word = t(lang, "top_referrers_invite")
    msg = t(lang, "top_referrers_header")
    for i, (name, count) in enumerate(top):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        msg += f"{medal} *{name}* — {count} {invite_word}\n"
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== تنظيف البيانات التلقائي (Auto-Clean) ========
def auto_clean_sent_news():
    cleaned = 0
    for uid, info in users.items():
        sent = info.get("sent_news", set())
        if isinstance(sent, list):
            sent = set(sent)
        if len(sent) > 1000:
            sent_list = list(sent)
            users[uid]["sent_news"] = set(sent_list[-500:])
            cleaned += 1
    if cleaned > 0:
        _db_save_all_users(users)
        notify_admin_error(f"✅ Auto-Clean: تم تنظيف بيانات {cleaned} مستخدم")

# ======== فحص الكلمات المفتاحية للمميزين ========
def check_keyword_alerts():
    for uid, keywords in list(user_keywords.items()):
        if not keywords:
            continue
        if not is_premium(uid):
            continue
        if int(uid) in banned:
            continue
        user = users.get(uid)
        if not user:
            continue
        lang = user.get("lang", "English 🇬🇧")
        feeds = RSS.get(lang, [])
        sent = user.setdefault("sent_news", set())
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for item in feed.entries[:5]:
                    if not hasattr(item, 'link') or item.link in sent:
                        continue
                    title = getattr(item, 'title', '')
                    title_lower = title.lower()
                    matched_kw = None
                    for kw in keywords:
                        if kw.lower() in title_lower:
                            matched_kw = kw
                            break
                    if matched_kw:
                        sent.add(item.link)
                        try:
                            bot.send_message(
                                int(uid),
                                f"🔑 *تنبيه كلمة مفتاحية: {matched_kw}*\n\n"
                                f"📰 {title}{BOT_SIGNATURE}",
                                parse_mode="Markdown"
                            )
                        except:
                            pass
            except Exception as e:
                notify_admin_error(f"خطأ في فحص الكلمات المفتاحية: {e}")
    _db_save_all_users(users)

# ======== الجدولة ========

# ======== ملخص أخبار اليوم ========
def send_daily_summary(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    headlines = []
    for feed_url in feeds[:3]:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:5]:
                if hasattr(item, 'title') and item.title:
                    headlines.append(item.title)
            if len(headlines) >= 15:
                break
        except Exception as e:
            notify_admin_error(f"خطأ في ملخص اليوم ({feed_url}): {e}")
    if not headlines:
        bot.send_message(uid, t(lang, "no_news"))
        return
    today = datetime.date.today().strftime("%Y-%m-%d")
    msg = t(lang, "daily_summary_header").format(date=today)
    for i, title in enumerate(headlines[:10], 1):
        msg += f"{i}. {title}\n\n"
    msg += f"━━━━━━━━━━━━━━━\n{BOT_SIGNATURE}"
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== أسعار العملات الرقمية ========
def send_crypto_prices(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether,binancecoin,solana,ripple,dogecoin,cardano,tron,litecoin,the-open-network,notcoin,pepe,dogwifcoin,bittensor&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=10).json()
        crypto_names = {
            "bitcoin":          ("₿ Bitcoin",  "BTC"),
            "ethereum":         ("⟠ Ethereum", "ETH"),
            "tether":           ("💵 Tether",   "USDT"),
            "binancecoin":      ("🟡 BNB",      "BNB"),
            "solana":           ("◎ Solana",    "SOL"),
            "ripple":           ("〇 XRP",       "XRP"),
            "dogecoin":         ("🐶 Dogecoin", "DOGE"),
            "cardano":          ("🔵 Cardano",  "ADA"),
            "tron":             ("🔴 TRON",     "TRX"),
            "litecoin":         ("🥈 Litecoin", "LTC"),
            "the-open-network": ("💎 TON",      "TON"),
            "notcoin":          ("🎮 NOT",      "NOT"),
            "pepe":             ("🐸 PEPE",     "PEPE"),
            "dogwifcoin":       ("🐕 WIF",      "WIF"),
            "bittensor":        ("🧠 TAO",      "TAO"),
        }
        msg = t(lang, "crypto_header")
        for coin_id, (name, symbol) in crypto_names.items():
            data = r.get(coin_id, {})
            price = data.get("usd", "—")
            change = data.get("usd_24h_change", None)
            if isinstance(price, (int, float)):
                price_str = f"${price:,.6f}" if price < 0.01 else (f"${price:,.4f}" if price < 1 else f"${price:,.2f}")
            else:
                price_str = "—"
            if change is not None:
                arrow = "📈" if change >= 0 else "📉"
                change_str = f"{arrow} {change:+.2f}%"
            else:
                change_str = ""
            msg += f"{name} ({symbol})\n   💲 {price_str}  {change_str}\n\n"
        msg += t(lang, "crypto_footer")
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "crypto_error"))
        notify_admin_error(f"خطأ في أسعار الكريبتو: {e}")

# ======== أوقات الصلاة ========
def send_prayer_times(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    province = user.get("province", "")
    if not province:
        bot.send_message(uid, t(lang, "prayer_no_city"))
        return
    try:
        today = datetime.date.today()
        url = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=IQ&method=4&date={today}"
        r = requests.get(url, timeout=10).json()
        if r.get("code") != 200:
            url2 = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=&method=4&date={today}"
            r = requests.get(url2, timeout=10).json()
        if r.get("code") != 200:
            bot.send_message(uid, t(lang, "prayer_city_error").format(city=province))
            return
        timings = r["data"]["timings"]
        date_info = r["data"]["date"]["readable"]
        hijri = r["data"]["date"]["hijri"]
        hijri_str = f"{hijri['day']} {hijri['month']['ar']} {hijri['year']} هـ"
        msg = t(lang, "prayer_header").format(
            city=province, date=date_info, hijri=hijri_str,
            fajr=timings['Fajr'], sunrise=timings['Sunrise'],
            dhuhr=timings['Dhuhr'], asr=timings['Asr'],
            maghrib=timings['Maghrib'], isha=timings['Isha']
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "prayer_error"))
        notify_admin_error(f"خطأ في أوقات الصلاة لـ {uid}: {e}")

# ======== إحصائيات الدعوات (رابط الدعوة) ========
def send_referral_stats(uid):
    user = users.get(str(uid))
    if not user:
        return
    referrals = user.get("referrals", [])
    ref_count = len(referrals)
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    unlocked = user.get("unlocked_features", [])
    rewarded = user.get("rewarded_milestones", [])
    ref_premium_expiry = user.get("ref_premium_expiry", "")

    progress_lines = ""
    for milestone in REFERRAL_MILESTONES:
        if milestone == 25:
            label = "🌟 اشتراك مميز كامل شهر"
        else:
            label = "🎁 ميزة مميزة مجانية"
        if milestone in rewarded:
            status = "✅"
        elif ref_count >= milestone:
            status = "🔓"
        else:
            remaining = milestone - ref_count
            status = f"🔒 ({remaining} متبقية)"
        progress_lines += f"{status} {milestone} دعوة ← {label}\n"

    unlocked_names = "\n".join(f"  ✨ {REFERRAL_FEATURES.get(f, f)}" for f in unlocked) if unlocked else "  لا توجد بعد"

    expiry_txt = ""
    if ref_premium_expiry:
        try:
            expiry_dt = datetime.datetime.fromisoformat(ref_premium_expiry)
            if datetime.datetime.now() < expiry_dt:
                days_left = (expiry_dt - datetime.datetime.now()).days
                expiry_txt = f"\n🌟 *اشتراك مميز كامل:* ينتهي بعد {days_left} يوم\n"
        except:
            pass

    msg = (
        f"🎁 *نظام الدعوات والمكافآت*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 دعواتك: `{ref_count}` شخص\n"
        f"🔗 رابطك:\n`{invite_link}`\n"
        f"{expiry_txt}"
        f"\n📊 *مستويات المكافآت:*\n{progress_lines}"
        f"\n🔓 *ميزاتك المفتوحة:*\n{unlocked_names}\n"
        f"━━━━━━━━━━━━━━\n"
        f"💡 شارك رابطك وكلما زادت دعواتك زادت مكافآتك!"
    )
    markup = types.InlineKeyboardMarkup()
    share_url = f"https://t.me/share/url?url={invite_link}&text=📱 جرب بوت الأخبار @{BOT_USERNAME}"
    markup.add(types.InlineKeyboardButton("📤 مشاركة رابط الدعوة", url=share_url))
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

# ======== انشر البوت ========
def send_share_bot(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    invite_link = f"https://t.me/{BOT_USERNAME}"
    msg = t(lang, "share_bot_header").format(username=BOT_USERNAME, link=invite_link)
    markup = types.InlineKeyboardMarkup()
    share_url = f"https://t.me/share/url?url={invite_link}&text=@{BOT_USERNAME}"
    markup.add(
        types.InlineKeyboardButton(t(lang, "share_bot_btn"), url=share_url),
        types.InlineKeyboardButton(t(lang, "open_bot_btn"), url=invite_link)
    )
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

# ======== إحصائيات البوت العامة ========
def send_public_stats(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    total = stats.get("total_users", len(users))
    today = str(datetime.date.today())
    today_count = stats.get("daily_users", {}).get(today, 0)
    active = sum(1 for u in users.values() if "province" in u)
    premium_count = len(stats.get("premium_users", []))
    top_langs = sorted(stats.get("languages_count", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    msg = t(lang, "public_stats_header").format(
        total=total, active=active, today=today_count, premium=premium_count
    )
    if top_langs:
        msg += t(lang, "public_stats_langs")
        for lang_name, count in top_langs:
            msg += f"  • {lang_name}: {count}\n"
    msg += t(lang, "public_stats_footer").format(username=BOT_USERNAME)
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== دولار السوق الموازية ========
def send_dollar_parallel(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    rate = None
    source_note = ""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://dolarsoft.com/api/v1/price", headers=headers, timeout=8)
        data = r.json()
        sell = data.get("sell") or data.get("price") or data.get("usd_sell")
        buy = data.get("buy") or data.get("usd_buy")
        if sell:
            rate = f"{t(lang, 'dollar_sell')}: `{sell}` IQD\n{t(lang, 'dollar_buy')}: `{buy or '-'}` IQD"
            source_note = "dolarsoft.com"
    except:
        pass
    if not rate:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
            iqd = r.json().get("rates", {}).get("IQD", None)
            if iqd:
                rate = t(lang, "dollar_official").format(price=f"{int(iqd):,}")
                source_note = "exchangerate-api.com"
        except:
            pass
    if not rate:
        bot.send_message(uid, t(lang, "dollar_error"))
        return
    now = datetime.datetime.now().strftime("%H:%M - %d/%m/%Y")
    msg = t(lang, "dollar_header").format(rate=rate, time=now, source=source_note, username=BOT_USERNAME)
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== ملخص أسبوعي نصي ========
def send_weekly_summary_text(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    bot.send_message(uid, t(lang, "weekly_summary_text_wait"))
    headlines = []
    seen_titles = set()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    for feed_url in feeds[:6]:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                title = getattr(entry, "title", "").strip()
                if not title or title in seen_titles:
                    continue
                pub = getattr(entry, "published_parsed", None)
                if pub:
                    try:
                        pub_dt = datetime.datetime(*pub[:6])
                        if pub_dt < cutoff:
                            continue
                    except:
                        pass
                seen_titles.add(title)
                headlines.append(title)
                if len(headlines) >= 25:
                    break
        except:
            continue
        if len(headlines) >= 25:
            break
    if not headlines:
        bot.send_message(uid, t(lang, "no_weekly"))
        return
    week_start = (datetime.datetime.now() - datetime.timedelta(days=6)).strftime("%d/%m")
    week_end = datetime.datetime.now().strftime("%d/%m/%Y")
    lines = [t(lang, "weekly_summary_text_header").format(start=week_start, end=week_end)]
    for i, title in enumerate(headlines, 1):
        lines.append(f"{i}. {title}")
    lines.append(t(lang, "public_stats_footer").format(username=BOT_USERNAME))
    full_msg = "\n".join(lines)
    if len(full_msg) > 4000:
        full_msg = full_msg[:3990] + "\n..."
    bot.send_message(uid, full_msg, parse_mode="Markdown")

# ======== تتبع العملات والأسهم والسلع والمؤشرات ========
CRYPTO_IDS = {
    # العملات الرئيسية
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "XRP": "ripple",
    "ADA": "cardano",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "AVAX": "avalanche-2",
    "SHIB": "shiba-inu",
    "TRX": "tron",
    "LINK": "chainlink",
    "TON": "the-open-network",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ALGO": "algorand",
    "VET": "vechain",
    "FIL": "filecoin",
    "HBAR": "hedera-hashgraph",
    "ICP": "internet-computer",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "MKR": "maker",
    "AAVE": "aave",
    "CRV": "curve-dao-token",
    "FTM": "fantom",
    "NEAR": "near",
    "SUI": "sui",
    "SEI": "sei-network",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "BONK": "bonk",
    "FLOKI": "floki",
    "NOT": "notcoin",
    "DOGS": "dogs-coin",
    "HMSTR": "hamster-kombat",
    "TAO": "bittensor",
    "RENDER": "render-token",
    "INJ": "injective-protocol",
    "PYTH": "pyth-network",
    "JUP": "jupiter-exchange-solana",
    "POPCAT": "popcat",
    "BRETT": "based-brett",
    "TRUMP": "maga",
    "PENGU": "pudgy-penguins",
}

FIAT_CURRENCIES = {
    "USD", "EUR", "GBP", "IQD", "SAR", "AED", "TRY",
    "JPY", "CNY", "KWD", "EGP", "JOD", "IRR", "PKR",
    "INR", "BRL", "RUB", "MXN", "CAD", "AUD", "CHF",
    "SEK", "NOK", "DKK", "SGD", "HKD", "QAR", "BHD",
    "OMR", "MAD", "TND", "DZD", "LYD", "SYP", "YER",
    "UAH", "PLN", "CZK", "HUF", "RON", "IDR", "MYR",
    "THB", "PHP", "VND", "ZAR", "NGN",
}

# أسهم شهيرة وسلع — تُجلب من Yahoo Finance
YAHOO_SYMBOLS = {
    # أسهم التكنولوجيا الكبرى
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Google",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "META": "Meta",
    "TSLA": "Tesla",
    "AMD": "AMD",
    "INTC": "Intel",
    "NFLX": "Netflix",
    "ORCL": "Oracle",
    "IBM": "IBM",
    "QCOM": "Qualcomm",
    "AVGO": "Broadcom",
    "CRM": "Salesforce",
    # أسهم أخرى
    "JPM": "JPMorgan",
    "BAC": "Bank of America",
    "WMT": "Walmart",
    "KO": "Coca-Cola",
    "PEP": "PepsiCo",
    "DIS": "Disney",
    "BABA": "Alibaba",
    "TSM": "TSMC",
    "NKE": "Nike",
    "PYPL": "PayPal",
    "UBER": "Uber",
    "SPOT": "Spotify",
    "SNAP": "Snap",
    "X": "X (Twitter)",
    "COIN": "Coinbase",
    "HOOD": "Robinhood",
    # سلع
    "GC=F": "Gold",
    "SI=F": "Silver",
    "CL=F": "Oil (WTI)",
    "BZ=F": "Oil (Brent)",
    "NG=F": "Natural Gas",
    "HG=F": "Copper",
    "PL=F": "Platinum",
    "PA=F": "Palladium",
    # مؤشرات
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^FTSE": "FTSE 100",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
}

def get_asset_label(symbol):
    """اسم وصفي للرمز إن وُجد."""
    if symbol in YAHOO_SYMBOLS:
        return f"{symbol} ({YAHOO_SYMBOLS[symbol]})"
    return symbol

def fetch_asset_price(symbol):
    """جلب سعر أي أصل: عملة رقمية / فيات / سهم / سلعة / مؤشر."""
    if symbol in CRYPTO_IDS:
        try:
            cg_id = CRYPTO_IDS[symbol]
            r = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd",
                timeout=10
            ).json()
            price = r.get(cg_id, {}).get("usd")
            return float(price) if price else None
        except:
            return None
    if symbol in FIAT_CURRENCIES:
        try:
            r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
            rate = r.get("rates", {}).get(symbol)
            return float(rate) if rate else None
        except:
            return None
    # أسهم وسلع ومؤشرات عبر Yahoo Finance
    try:
        encoded = requests.utils.quote(symbol, safe='')
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1d",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10
        ).json()
        result = r.get("chart", {}).get("result")
        if result:
            closes = result[0]["indicators"]["quote"][0].get("close", [])
            price = next((p for p in reversed(closes) if p is not None), None)
            return float(price) if price else None
    except:
        pass
    return None

def format_asset_price(symbol, price):
    """تنسيق عرض السعر حسب حجمه."""
    label = get_asset_label(symbol)
    if price is None:
        return f"❓ {label}: غير متوفر"
    if price >= 10000:
        return f"`{label}`: `${price:,.0f}`"
    elif price >= 1:
        return f"`{label}`: `${price:,.2f}`"
    elif price >= 0.0001:
        return f"`{label}`: `${price:.6f}`"
    else:
        return f"`{label}`: `${price:.8f}`"

def start_track_asset(uid):
    user_data = tracked_assets.get(str(uid), {})
    assets = user_data.get("assets", [])
    last_prices = user_data.get("last_prices", {})
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")

    msg = t(lang, "track_header")

    if assets:
        msg += t(lang, "track_current_list")
        for sym in assets:
            p = last_prices.get(sym)
            msg += f"  • {format_asset_price(sym, p)}\n"
        msg += t(lang, "track_count").format(count=len(assets))

    msg += t(lang, "track_add_hint")
    msg += t(lang, "track_crypto_label")
    msg += "`BTC` `ETH` `SOL` `BNB` `XRP` `DOGE`\n"
    msg += "`TON` `TRX` `ADA` `MATIC` `LINK` `UNI`\n"
    msg += "`SHIB` `PEPE` `WIF` `BONK` `NOT` ...\n\n"
    msg += t(lang, "track_fiat_label")
    msg += "`USD` `EUR` `GBP` `IQD` `SAR` `AED`\n"
    msg += "`TRY` `IRR` `KWD` `EGP` `INR` `RUB` ...\n\n"
    msg += t(lang, "track_stocks_label")
    msg += "`AAPL` `TSLA` `NVDA` `MSFT` `AMZN`\n"
    msg += "`META` `GOOGL` `AMD` `NFLX` `BABA` ...\n\n"
    msg += t(lang, "track_commodities_label")
    msg += "`GC=F` (Gold)  `SI=F` (Silver)\n"
    msg += "`CL=F` (WTI)  `BZ=F` (Brent)\n"
    msg += "`^GSPC` (S&P500)  `^IXIC` (NASDAQ)\n\n"
    msg += t(lang, "track_alert_hint")
    msg += t(lang, "track_remove_hint")
    msg += t(lang, "track_list_hint")

    user_states[uid] = "tracking_asset"
    bot.send_message(uid, msg, parse_mode="Markdown")

def check_asset_tracking():
    """يعمل كل ساعة: يرسل تقريراً شاملاً + تنبيهات التغيرات الكبيرة."""
    for uid_str, data in list(tracked_assets.items()):
        assets = data.get("assets", [])
        if not assets:
            continue
        last_prices = data.get("last_prices", {})
        changed = False
        report_lines = []
        alerts = []

        user = users.get(uid_str, {})
        lang = user.get("lang", "English 🇬🇧")

        for symbol in assets:
            try:
                new_price = fetch_asset_price(symbol)
                if new_price is None:
                    report_lines.append(f"❓ {get_asset_label(symbol)}: {t(lang, 'track_unavailable')}")
                    continue
                old_price = last_prices.get(symbol)
                if old_price and old_price > 0:
                    change_pct = ((new_price - old_price) / old_price) * 100
                    arrow = "📈" if change_pct >= 0 else "📉"
                    report_lines.append(
                        f"{arrow} {format_asset_price(symbol, new_price)}  `{change_pct:+.2f}%`"
                    )
                    if abs(change_pct) >= 1.0:
                        direction = t(lang, "track_rose") if change_pct > 0 else t(lang, "track_fell")
                        alerts.append(
                            f"{direction} *{get_asset_label(symbol)}* بنسبة `{change_pct:+.2f}%`\n"
                            f"   السعر: `${new_price:,.4f}` (كان `${old_price:,.4f}`)"
                        )
                else:
                    report_lines.append(f"🔹 {format_asset_price(symbol, new_price)}")
                tracked_assets[uid_str]["last_prices"][symbol] = new_price
                changed = True
            except:
                continue

        if changed:
            save_tracked_assets()

        # إرسال التنبيهات الفورية للتغيرات الكبيرة
        if alerts:
            alert_msg = (
                t(lang, "track_alert_title")
                + "\n\n".join(alerts)
                + f"\n\n🤖 @{BOT_USERNAME}"
            )
            try:
                bot.send_message(int(uid_str), alert_msg, parse_mode="Markdown")
            except:
                pass

        # إرسال التقرير الساعي الشامل
        if report_lines:
            import datetime as _dt
            now_str = _dt.datetime.now().strftime("%H:%M — %d/%m/%Y")
            report_msg = (
                t(lang, "track_report_title")
                + f"🕐 {now_str}\n"
                f"━━━━━━━━━━━━━━━\n\n"
                + "\n".join(report_lines)
                + f"\n\n━━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}"
            )
            try:
                bot.send_message(int(uid_str), report_msg, parse_mode="Markdown")
            except:
                pass

@bot.message_handler(commands=["mytrack"])
def cmd_mytrack(m):
    uid = m.from_user.id
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if not assets:
        bot.send_message(uid, t(lang, "track_empty"), parse_mode="Markdown")
        return
    last_prices = data.get("last_prices", {})
    msg = t(lang, "track_list_header")
    for sym in assets:
        price = fetch_asset_price(sym)
        if price:
            tracked_assets[str(uid)]["last_prices"][sym] = price
            save_tracked_assets()
        msg += f"• {format_asset_price(sym, price or last_prices.get(sym))}\n"
    msg += f"━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}"
    bot.send_message(uid, msg, parse_mode="Markdown")

@bot.message_handler(commands=["removetrack"])
def cmd_removetrack(m):
    uid = m.from_user.id
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    parts = m.text.strip().split()
    if len(parts) < 2:
        bot.send_message(uid, t(lang, "track_remove_usage"), parse_mode="Markdown")
        return
    symbol = parts[1].upper()
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if symbol not in assets:
        bot.send_message(uid, t(lang, "track_not_found").format(symbol=symbol), parse_mode="Markdown")
        return
    assets.remove(symbol)
    tracked_assets[str(uid)]["assets"] = assets
    tracked_assets[str(uid)]["last_prices"].pop(symbol, None)
    save_tracked_assets()
    bot.send_message(uid, t(lang, "track_removed").format(symbol=symbol), parse_mode="Markdown")

# ======== الجدولة ========
# ======== تغليف آمن للمهام المجدولة ========
def _safe_job(fn):
    def wrapper():
        try:
            fn()
        except Exception as e:
            try:
                bot.send_message(ADMIN_ID, f"\u26a0\ufe0f \u062e\u0637\u0623 \u0641\u064a \u0627\u0644\u0645\u0647\u0645\u0629 {fn.__name__}: {e}")
            except Exception:
                pass
    wrapper.__name__ = fn.__name__
    return wrapper

scheduler = BackgroundScheduler()
scheduler.add_job(_safe_job(broadcast_news), 'interval', minutes=2)
scheduler.add_job(_safe_job(broadcast_to_channels), 'interval', minutes=2)
scheduler.add_job(_safe_job(send_morning_summary), 'interval', hours=1)
scheduler.add_job(_safe_job(check_weather_alerts), 'interval', hours=6)
scheduler.add_job(_safe_job(check_currency_alerts), 'interval', hours=3)
scheduler.add_job(_safe_job(check_keyword_alerts), 'interval', minutes=15)
scheduler.add_job(_safe_job(auto_clean_sent_news), 'interval', hours=24)
scheduler.add_job(_safe_job(check_asset_tracking), 'interval', hours=1)
scheduler.add_job(_safe_job(lambda: _db_save_all_users(users)), 'interval', minutes=10)
# broadcast_weather أُزيلت من الجدولة — تُرسل عند طلب المستخدم فقط
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))

# ======== رسالة الترحيب عند إضافة البوت للقناة/المجموعة ========
CHANNEL_WELCOME_MSG = (
   "👋 *أهلاً! تم تفعيل بوت الأخبار بنجاح في هذه القناة/المجموعة.*\n\n"
   "━━━━━━━━━━━━━━\n"
   "📋 *الأوامر المتاحة لأدمن القناة/المجموعة:*\n\n"
   "🌐 *تغيير لغة الأخبار:*\n"
   "`/setlang العربية 🇮🇶`\n"
   "`/setlang English 🇬🇧`\n"
   "`/setlang فارسی 🇮🇷`\n"
   "`/setlang Türkçe 🇹🇷`\n\n"
   "🏙 *تغيير المدينة:*\n"
   "`/setcity بغداد`\n\n"
   "📡 *مصادر الأخبار (RSS):*\n"
   "`/setsource رابط_RSS` — إضافة مصدر\n"
   "`/removesource رابط_RSS` — حذف مصدر\n"
   "`/listsources` — عرض المصادر\n\n"
   "⏸ *التحكم في البث:*\n"
   "`/pause` — إيقاف البث مؤقتاً\n"
   "`/resume` — استئناف البث\n\n"
   "⚙️ *الإعدادات:*\n"
   "`/settings` — عرض الإعدادات الحالية\n\n"
   "━━━━━━━━━━━━━━\n"
   "📰 سيبدأ إرسال الأخبار تلقائياً كل بضع دقائق.\n"
   f"🤖 @{BOT_USERNAME}"
)

@bot.my_chat_member_handler()
def on_bot_chat_member_update(update):
    new_status = update.new_chat_member.status
    old_status = update.old_chat_member.status
    chat = update.chat
    chat_id = chat.id
    chat_type = chat.type

    if chat_type not in ("channel", "group", "supergroup"):
        return

    if new_status in ("administrator", "member") and old_status in ("left", "kicked", "restricted"):
        title = chat.title or str(chat_id)
        already = any(ch["id"] == chat_id for ch in channels_groups)
        if not already:
            default_lang = "العربية 🇮🇶"
            auto_feeds = RSS.get(default_lang, [])
            initial_sent = list(prefill_sent_news(auto_feeds))
            channels_groups.append({
                "id": chat_id,
                "title": title,
                "type": chat_type,
                "lang": default_lang,
                "city": "",
                "sent_news": initial_sent
            })
            save_channels_groups()
        try:
            bot.send_message(chat_id, CHANNEL_WELCOME_MSG, parse_mode="Markdown")
        except Exception as e:
            notify_admin_error(f"خطأ في إرسال رسالة الترحيب للقناة {title}: {e}")
        notify_admin_error(f"✅ تمت إضافة البوت لـ: *{title}* (`{chat_id}`) — النوع: {chat_type}")

    elif new_status in ("left", "kicked") and old_status in ("administrator", "member"):
        title = chat.title or str(chat_id)
        for i, ch in enumerate(channels_groups):
            if ch["id"] == chat_id:
                channels_groups.pop(i)
                save_channels_groups()
                break
        notify_admin_error(f"⚠️ تمت إزالة البوت من: *{title}* (`{chat_id}`)")


# ======== أوامر التحكم داخل القناة/المجموعة ========
VALID_LANGS = ["العربية 🇮🇶", "English 🇬🇧", "فارسی 🇮🇷", "Türkçe 🇹🇷"]

def is_chat_admin(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

@bot.message_handler(commands=["setlang"], chat_types=["channel", "group", "supergroup"])
def cmd_setlang(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    args = message.text.strip().replace("/setlang", "").strip()
    matched_lang = None
    for lang in VALID_LANGS:
        if lang.lower().startswith(args.lower()) or args.lower() in lang.lower():
            matched_lang = lang
            break
    if not matched_lang:
        bot.send_message(chat_id,
            "❌ *لغة غير صحيحة.*\n\n"
            "اللغات المتاحة:\n"
            "• `العربية 🇮🇶`\n"
            "• `English 🇬🇧`\n"
            "• `فارسی 🇮🇷`\n"
            "• `Türkçe 🇹🇷`\n\n"
            "مثال: `/setlang العربية 🇮🇶`",
            parse_mode="Markdown"
        )
        return
    found = False
    for ch in channels_groups:
        if ch["id"] == chat_id:
            ch["lang"] = matched_lang
            ch["sent_news"] = []
            found = True
            break
    if not found:
        channels_groups.append({
            "id": chat_id,
            "title": message.chat.title or str(chat_id),
            "type": message.chat.type,
            "lang": matched_lang,
            "city": "",
            "sent_news": []
        })
    save_channels_groups()
    bot.send_message(chat_id,
        f"✅ *تم تغيير لغة الأخبار إلى:* {matched_lang}\n"
        f"📰 سيبدأ إرسال الأخبار باللغة الجديدة في البث القادم.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["setcity"], chat_types=["channel", "group", "supergroup"])
def cmd_setcity(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    city = message.text.strip().replace("/setcity", "").strip()
    if not city:
        bot.send_message(chat_id,
            "❌ *أرسل اسم المدينة.*\n\nمثال: `/setcity بغداد`",
            parse_mode="Markdown"
        )
        return
    found = False
    for ch in channels_groups:
        if ch["id"] == chat_id:
            ch["city"] = city
            found = True
            break
    if not found:
        channels_groups.append({
            "id": chat_id,
            "title": message.chat.title or str(chat_id),
            "type": message.chat.type,
            "lang": "العربية 🇮🇶",
            "city": city,
            "sent_news": []
        })
    save_channels_groups()
    bot.send_message(chat_id,
        f"✅ *تم تعيين المدينة إلى:* {city}",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["settings"], chat_types=["channel", "group", "supergroup"])
def cmd_settings(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        bot.send_message(chat_id,
            "⚠️ هذه القناة/المجموعة غير مسجلة في البوت بعد.\n"
            "أضف البوت كأدمن وسيبدأ تلقائياً.",
            parse_mode="Markdown"
        )
        return
    lang = ch_data.get("lang", "العربية 🇮🇶")
    city = ch_data.get("city", "") or "غير محددة"
    chat_type = ch_data.get("type", "")
    type_label = "📢 قناة" if chat_type == "channel" else "👥 مجموعة"
    bot.send_message(chat_id,
        f"⚙️ *إعدادات هذه {type_label}:*\n\n"
        f"🌐 اللغة: *{lang}*\n"
        f"🏙 المدينة: *{city}*\n\n"
        f"🔧 لتغيير اللغة: `/setlang اسم اللغة`\n"
        f"🔧 لتغيير المدينة: `/setcity اسم المدينة`",
        parse_mode="Markdown"
    )

# ======== أوامر المصادر المخصصة لأدمن القناة/المجموعة ========
@bot.message_handler(commands=["setsource"], chat_types=["channel", "group", "supergroup"])
def cmd_setsource(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    url = message.text.strip().replace("/setsource", "").strip()
    if not url.startswith("http"):
        bot.send_message(chat_id, "❌ أرسل رابط RSS صحيح يبدأ بـ http\nمثال: `/setsource https://feeds.bbcarabic.com/world-arabic-rss.xml`", parse_mode="Markdown")
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        channels_groups.append({"id": chat_id, "title": message.chat.title or str(chat_id),
                                 "type": message.chat.type, "lang": "العربية 🇮🇶",
                                 "custom_sources": [url], "sent_news": []})
    else:
        sources = ch_data.setdefault("custom_sources", [])
        if url in sources:
            bot.send_message(chat_id, "⚠️ هذا المصدر مضاف مسبقاً.")
            return
        sources.append(url)
    save_channels_groups()
    bot.send_message(chat_id, f"✅ *تمت إضافة المصدر:*\n`{url}`", parse_mode="Markdown")

@bot.message_handler(commands=["removesource"], chat_types=["channel", "group", "supergroup"])
def cmd_removesource(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    url = message.text.strip().replace("/removesource", "").strip()
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data or url not in ch_data.get("custom_sources", []):
        bot.send_message(chat_id, "⚠️ المصدر غير موجود.")
        return
    ch_data["custom_sources"].remove(url)
    save_channels_groups()
    bot.send_message(chat_id, f"✅ تم حذف المصدر:\n`{url}`", parse_mode="Markdown")

@bot.message_handler(commands=["listsources"], chat_types=["channel", "group", "supergroup"])
def cmd_listsources(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    sources = ch_data.get("custom_sources", []) if ch_data else []
    if not sources:
        bot.send_message(chat_id,
            "📋 لا توجد مصادر مخصصة.\n"
            "يستخدم البوت المصادر الافتراضية حسب اللغة.\n"
            "أضف مصدراً: `/setsource رابط_RSS`",
            parse_mode="Markdown"
        )
        return
    msg = "📋 *مصادر الأخبار المخصصة:*\n\n"
    for i, src in enumerate(sources, 1):
        msg += f"{i}. `{src}`\n"
    bot.send_message(chat_id, msg, parse_mode="Markdown")

@bot.message_handler(commands=["pause"], chat_types=["channel", "group", "supergroup"])
def cmd_pause(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        bot.send_message(chat_id, "⚠️ هذه القناة/المجموعة غير مسجلة.")
        return
    ch_data["paused"] = True
    save_channels_groups()
    bot.send_message(chat_id, "⏸ *تم إيقاف البث مؤقتاً.*\nاستخدم `/resume` للاستئناف.", parse_mode="Markdown")

@bot.message_handler(commands=["resume"], chat_types=["channel", "group", "supergroup"])
def cmd_resume(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        bot.send_message(chat_id, "⚠️ هذه القناة/المجموعة غير مسجلة.")
        return
    ch_data["paused"] = False
    save_channels_groups()
    bot.send_message(chat_id, "▶️ *تم استئناف البث.*\nستصلك الأخبار تلقائياً قريباً.", parse_mode="Markdown")

# ======== تقرير يومي للأدمن ========
def send_daily_report():
    today = str(datetime.date.today())
    yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
    total_users_count = len(users)
    new_today = sum(1 for u in users.values() if u.get("join_date", "").startswith(today))
    premium_count = len(stats.get("premium_users", []))
    channels_count = len(channels_groups)
    total_ch_news = sum(ch.get("news_sent_count", 0) for ch in channels_groups)
    read_today = read_stats.get("daily", {}).get(today, 0)
    read_yest = read_stats.get("daily", {}).get(yesterday, 0)
    total_reads = read_stats.get("total_opens", 0)
    active_users = sum(1 for u in users.values() if u.get("notifications", True))
    report = (
        f"📊 *التقرير اليومي — {today}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 إجمالي المستخدمين: `{total_users_count}`\n"
        f"🆕 جدد اليوم: `{new_today}`\n"
        f"🔔 نشطون (إشعارات مفعّلة): `{active_users}`\n"
        f"⭐ مميزون: `{premium_count}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📺 القنوات/المجموعات: `{channels_count}`\n"
        f"📰 إجمالي أخبار القنوات: `{total_ch_news}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📖 قراءات اليوم: `{read_today}`\n"
        f"📖 قراءات أمس: `{read_yest}`\n"
        f"📖 إجمالي القراءات: `{total_reads}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"🤖 @{BOT_USERNAME}"
    )
    try:
        bot.send_message(ADMIN_ID, report, parse_mode="Markdown")
    except Exception:
        pass
    for admin_id in extra_admins:
        try:
            bot.send_message(admin_id, report, parse_mode="Markdown")
        except:
            pass

scheduler.add_job(send_daily_report, 'cron', hour=8, minute=0)
scheduler.add_job(_safe_job(send_rating_request), 'cron', hour=20, minute=0)
scheduler.add_job(_safe_job(reset_daily_rating_flags), 'cron', hour=0, minute=0)
scheduler.add_job(_safe_job(check_inactive_users), 'cron', hour=10, minute=0)
scheduler.add_job(_safe_job(check_summary_hint), 'interval', hours=12)

# ======== تشغيل البوت ========
bot.infinity_polling(allowed_updates=["message", "callback_query", "my_chat_member"])
