import telebot
from telebot import types
import requests
import feedparser
import atexit
import os
import json
import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# ======== مفاتيح البوت ========
BOT_TOKEN = "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
WEATHER_KEY = "18a7801721693e772bbada4687d03e43"
NEWS_KEY = "98b2295d1a034076913e0c0e2aa64fa4"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "5149213983"))

bot = telebot.TeleBot(BOT_TOKEN)

# ======== ملفات الحفظ ========
USERS_FILE = "users.json"
STATS_FILE = "stats.json"
BANNED_FILE = "banned.json"
RSS_FILE = "rss.json"
ADMINS_FILE = "admins.json"
KEYWORDS_FILE = "keywords.json"
TRACK_FILE = "tracking.json"

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

users = load_json(USERS_FILE, {})
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
        "🌤 روی *آب‌وهوا* بزنید برای وضعیت هوا\n"
        "📰 روی *اخبار* بزنید برای آخرین خبرها\n"
        "💱 روی *نرخ ارز* بزنید برای قیمت‌ها\n"
        "🔍 روی *جستجو* بزنید برای جستجوی خبر\n"
        "🔔 روی *اعلان‌ها* بزنید برای مدیریت اطلاع‌رسانی\n"
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
        "العراق": ["بغداد", "البصرة", "أربيل", "الأنبار", "كركوك", "ذي قار", "بابل", "ميسان", "نينوى", "واسط", "كربلاء", "صلاح الدين", "ديالى", "القادسية", "المثنى", "حلبجة"]
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
        "https://www.alarabiya.net/.mrss/ar/0/0/0.xml",
        "https://www.bbc.com/arabic/index.xml",
        "https://www.aljazeera.net/aljazeera/feeds/rss.xml",
        "https://www.alsumaria.tv/rss/latest-news",
        "https://www.skynewsarabia.com/rss.xml",
        "https://arabic.rt.com/rss/",
        "https://feeds.feedburner.com/alkhaleejonline",
        "https://www.independentarabia.com/rss.xml",
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
        "weather": "🌤 آب‌وهوا",
        "forecast": "📅 پیش‌بینی ۳ روزه",
        "news": "📰 آخرین اخبار",
        "all_news": "📰 ارسال همه اخبار",
        "mena_politics": "📰 اخبار خاورمیانه",
        "trending": "🔥 پرتداول‌ترین",
        "sports": "⚽ اخبار ورزشی",
        "daily_summary": "📋 خلاصه اخبار امروز",
        "weekly_summary": "📆 خلاصه هفتگی",
        "news_cats": "🗂 دسته‌بندی اخبار",
        "currency": "💱 نرخ ارز",
        "dollar_parallel": "💵 دلار موازی",
        "convert": "🔄 تبدیل ارز",
        "crypto": "💎 ارز دیجیتال",
        "track_asset": "📌 پیگیری دارایی",
        "prayer": "🕌 اوقات نماز",
        "search": "🔍 جستجوی اخبار",
        "my_stats": "📈 آمار من",
        "referral": "🎁 دعوت‌هایم",
        "top_referrers": "🏆 برترین‌ها",
        "share_bot": "📢 اشتراک‌گذاری ربات",
        "public_stats": "📊 آمار ربات",
        "notif_on": "🔔 غیرفعال‌کردن اعلان‌ها",
        "notif_off": "🔕 فعال‌کردن اعلان‌ها",
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
        "🌤 پیش‌بینی آب‌وهوا برای ۷ روز\n"
        "🏙 افزودن چند شهر\n"
        "📌 اخبار بر اساس علایق\n"
        "⚡ اخبار فوری هر ۱۵ دقیقه\n"
        "🌅 خلاصه صبحگاهی\n"
        "💱 هشدار نرخ ارز\n"
        "🌧 هشدار تغییرات آب‌وهوا\n"
        "🕐 انتخاب زمان اطلاع‌رسانی\n\n"
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
    "العربية 🇮🇶": ["⚽ رياضة", "💰 اقتصاد", "💻 تقنية", "🏛 سياسة", "🏥 صحة"],
    "English 🇬🇧": ["⚽ Sports", "💰 Economy", "💻 Technology", "🏛 Politics", "🏥 Health"],
    "Русский 🇷🇺": ["⚽ Спорт", "💰 Экономика", "💻 Технологии", "🏛 Политика", "🏥 Здоровье"],
    "فارسی 🇮🇷": ["⚽ ورزش", "💰 اقتصاد", "💻 فناوری", "🏛 سیاست", "🏥 سلامت"],
    "हिन्दी 🇮🇳": ["⚽ खेल", "💰 अर्थव्यवस्था", "💻 प्रौद्योगिकी", "🏛 राजनीति", "🏥 स्वास्थ्य"],
    "Português 🇧🇷": ["⚽ Esporte", "💰 Economia", "💻 Tecnologia", "🏛 Política", "🏥 Saúde"],
    "Türkçe 🇹🇷": ["⚽ Spor", "💰 Ekonomi", "💻 Teknoloji", "🏛 Siyaset", "🏥 Sağlık"],
    "اردو 🇵🇰": ["⚽ کھیل", "💰 معیشت", "💻 ٹیکنالوجی", "🏛 سیاست", "🏥 صحت"],
    "Deutsch 🇩🇪": ["⚽ Sport", "💰 Wirtschaft", "💻 Technologie", "🏛 Politik", "🏥 Gesundheit"],
    "Українська 🇺🇦": ["⚽ Спорт", "💰 Економіка", "💻 Технології", "🏛 Політика", "🏥 Здоров'я"],
    "Italiano 🇮🇹": ["⚽ Sport", "💰 Economia", "💻 Tecnologia", "🏛 Politica", "🏥 Salute"],
    "Español 🇲🇽": ["⚽ Deporte", "💰 Economía", "💻 Tecnología", "🏛 Política", "🏥 Salud"],
}

INTEREST_KEYWORDS = {
    "رياضة": ["رياضة", "كرة", "مباراة", "بطولة", "لاعب", "فريق", "هدف", "ملعب"],
    "اقتصاد": ["اقتصاد", "نفط", "دولار", "تجارة", "بنك", "مال", "بورصة", "سوق"],
    "تقنية": ["تقنية", "ذكاء اصطناعي", "تكنولوجيا", "هاتف", "إنترنت", "تطبيق", "برنامج"],
    "سياسة": ["سياسة", "حكومة", "رئيس", "وزير", "برلمان", "انتخاب", "حزب"],
    "صحة": ["صحة", "مستشفى", "طبيب", "علاج", "مرض", "لقاح", "وباء"],
    "sports": ["sport", "football", "match", "tournament", "player", "team", "goal"],
    "economy": ["economy", "oil", "dollar", "trade", "bank", "finance", "market", "stock"],
    "technology": ["tech", "ai", "internet", "app", "software", "phone", "digital"],
    "politics": ["politics", "government", "president", "minister", "parliament", "election"],
    "health": ["health", "hospital", "doctor", "treatment", "disease", "vaccine", "epidemic"],
    "спорт": ["спорт", "футбол", "матч", "турнир", "игрок", "команда", "гол"],
    "экономика": ["экономика", "нефть", "доллар", "торговля", "банк", "рынок"],
    "технологии": ["технологии", "ии", "интернет", "приложение", "программа"],
    "политика": ["политика", "правительство", "президент", "министр", "парламент"],
    "здоровье": ["здоровье", "больница", "врач", "лечение", "болезнь", "вакцина"],
    "ورزش": ["ورزش", "فوتبال", "مسابقه", "تیم", "بازیکن"],
    "اقتصاد_fa": ["اقتصاد", "نفت", "دلار", "تجارت", "بانک", "بازار"],
    "فناوری": ["فناوری", "هوش مصنوعی", "اینترنت", "نرم‌افزار"],
    "سیاست": ["سیاست", "دولت", "رئیس جمهور", "وزیر", "مجلس"],
    "سلامت": ["سلامت", "بیمارستان", "پزشک", "درمان", "بیماری"],
    "spor": ["spor", "futbol", "maç", "turnuva", "oyuncu", "takım", "gol"],
    "ekonomi": ["ekonomi", "petrol", "dolar", "ticaret", "banka", "piyasa"],
    "teknoloji": ["teknoloji", "yapay zeka", "internet", "uygulama", "yazılım"],
    "siyaset": ["siyaset", "hükümet", "cumhurbaşkanı", "bakan", "meclis", "seçim"],
    "sağlık": ["sağlık", "hastane", "doktor", "tedavi", "hastalık", "aşı"],
    "sport_de": ["sport", "fußball", "spiel", "turnier", "spieler", "mannschaft"],
    "wirtschaft": ["wirtschaft", "öl", "dollar", "handel", "bank", "markt"],
    "technologie": ["technologie", "ki", "internet", "app", "software"],
    "politik": ["politik", "regierung", "präsident", "minister", "parlament", "wahl"],
    "gesundheit": ["gesundheit", "krankenhaus", "arzt", "behandlung", "krankheit"],
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
        "https://www.aljazeera.net/aljazeera/feeds/rss.xml",
        "https://feeds.skynewsarabia.com/web/rss/2",
        "https://arabic.rt.com/rss/",
        "https://www.bbc.com/arabic/index.xml",
        "https://www.independentarabia.com/rss.xml",
        "https://rss.almasryalyoum.com/rss.xml",
        "https://arabi21.com/rss.xml",
        "https://www.elnashra.com/rss",
        "https://www.alsumaria.tv/rss/latest-news",
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
    return int(uid) in stats.get("premium_users", [])

# ======== لوحة تحكم الأدمن ========
def admin_panel(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 المستخدمون", callback_data="admin_users"),
        types.InlineKeyboardButton("📢 إرسال رسالة", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🔴 إيقاف/تشغيل البوت", callback_data="admin_pause"),
        types.InlineKeyboardButton("📡 إدارة RSS", callback_data="admin_rss"),
        types.InlineKeyboardButton("💰 المالية", callback_data="admin_finance"),
        types.InlineKeyboardButton("✏️ تغيير رسالة الترحيب", callback_data="admin_welcome"),
        types.InlineKeyboardButton("👑 إدارة الأدمن", callback_data="admin_manage_admins"),
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
        save_json(USERS_FILE, users)
    bot.send_message(uid, "🔕 تم إيقاف الإشعارات. أرسل /start للرجوع.")

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

    if not is_premium(uid):
        bot.send_message(uid, "⭐ هذه الميزة للمشتركين المميزين فقط.")
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
        save_json(USERS_FILE, users)
        send_interest_menu(uid)

    elif data == "interest_save":
        interests = users.get(str(uid), {}).get("interests", [])
        if interests:
            bot.send_message(uid, f"✅ تم حفظ اهتماماتك:\n" + "\n".join(interests))
        else:
            bot.send_message(uid, "✅ لا توجد اهتمامات محددة — ستصلك جميع الأخبار.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_") or c.data.startswith("broadcast_") or c.data.startswith("rss_"))
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
            types.InlineKeyboardButton("🔍 معلومات مستخدم", callback_data="admin_user_info"),
            types.InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban"),
            types.InlineKeyboardButton("✅ رفع حظر", callback_data="admin_unban"),
            types.InlineKeyboardButton("📋 قائمة المحظورين", callback_data="admin_banned_list"),
            types.InlineKeyboardButton("⭐ ترقية لمميز", callback_data="admin_premium"),
            types.InlineKeyboardButton("❌ إلغاء اشتراك مميز", callback_data="admin_unpremium"),
        )
        bot.send_message(uid, "👥 *إدارة المستخدمين:*", parse_mode="Markdown", reply_markup=markup)

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
        msg = (
            f"👤 *معلومات المستخدم*\n\n"
            f"🆔 ID: `{target_id}`\n"
            f"👤 الاسم: {user.get('name', 'غير معروف')}\n"
            f"🗣 اللغة: {user.get('lang', '-')}\n"
            f"🌍 الدولة: {user.get('country', '-')}\n"
            f"📍 المحافظة: {user.get('province', '-')}\n"
            f"🚫 محظور: {'نعم' if is_banned_user else 'لا'}\n"
            f"⭐ مميز: {'نعم' if is_premium_user else 'لا'}\n"
            f"👑 أدمن: {'نعم' if is_admin_user else 'لا'}\n"
        )
        bot.send_message(message.from_user.id, msg, parse_mode="Markdown")
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
        btn["weather"], btn.get("forecast", "📅 توقعات 3 أيام"),
        btn["news"], btn.get("trending", "🔥 الأكثر تداولاً"),
        btn.get("sports", "⚽ رياضة"), btn["mena_politics"],
        btn["daily_summary"], btn.get("weekly_summary", "📆 ملخص أسبوعي"),
        btn["news_cats"],
        btn["currency"], btn.get("dollar_parallel", "💵 دولار السوق"),
        btn.get("convert", "🔄 محوّل العملات"),
        btn.get("crypto", "💎 كريبتو"), btn.get("track_asset", "📌 تتبع عملة/سهم"),
        btn.get("prayer", "🕌 الصلاة"),
        btn["search"], btn.get("my_stats", "📈 إحصائياتي"),
        btn.get("referral", "🎁 دعواتي"), btn.get("top_referrers", "🏆 أفضل الداعين"),
        btn.get("share_bot", "📢 انشر البوت"), btn.get("public_stats", "📊 إحصائيات"),
        notif_label, btn.get("premium", "⭐ Premium"),
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
        local_rate = rates.get(local_code, "غير متوفر")
        eur = rates.get("EUR", "-")
        gbp = rates.get("GBP", "-")
        iqd = rates.get("IQD", "-")
        try_rate = rates.get("TRY", "-")
        sar = rates.get("SAR", "-")
        msg = (
            f"💱 *أسعار الصرف مقابل الدولار 🇺🇸*\n\n"
            f"🏠 {local_name}: `{local_rate}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"🇪🇺 اليورو: `{eur}`\n"
            f"🇬🇧 الجنيه الإسترليني: `{gbp}`\n"
            f"🇮🇶 الدينار العراقي: `{iqd}`\n"
            f"🇹🇷 الليرة التركية: `{try_rate}`\n"
            f"🇸🇦 الريال السعودي: `{sar}`\n"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ لا يمكن جلب أسعار العملات حالياً.")
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
            bot.send_message(uid, "⚠️ لا توجد نتائج لهذا البحث.")
            return
        bot.send_message(uid, f"🔍 *نتائج البحث عن: {query}*", parse_mode="Markdown")
        for article in articles[:5]:
            title = article.get("title", "")
            link = article.get("url", "")
            if title:
                if link:
                    markup = make_news_share_markup(link, title)
                    bot.send_message(uid, f"📰 {title}", parse_mode="Markdown", reply_markup=markup)
                else:
                    bot.send_message(uid, f"📰 {title}", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ حدث خطأ أثناء البحث.")
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
                    bot.send_message(uid, "🔥 *الأكثر تداولاً*\n━━━━━━━━━━━━━━━", parse_mode="Markdown")
                    for item in articles_rss:
                        title = getattr(item, 'title', '')
                        link = getattr(item, 'link', '')
                        if title and link:
                            markup = make_news_share_markup(link, title)
                            bot.send_message(uid, format_news_item("🔥", title), parse_mode="Markdown", reply_markup=markup)
                    return
                except:
                    pass
            bot.send_message(uid, "⚠️ لا توجد أخبار رائجة الآن، حاول لاحقاً.")
            return
        bot.send_message(uid, "🔥 *الأكثر تداولاً*\n━━━━━━━━━━━━━━━", parse_mode="Markdown")
        for article in articles[:8]:
            title = article.get("title", "")
            link = article.get("url", "")
            if title and link:
                markup = make_news_share_markup(link, title)
                bot.send_message(uid, format_news_item("🔥", title), parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        bot.send_message(uid, "⚠️ حدث خطأ أثناء جلب الأخبار الرائجة.")
        notify_admin_error(f"خطأ في الأخبار الرائجة: {e}")

def send_premium_upgrade(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    msg = PREMIUM_UPGRADE_MSG.get(lang, PREMIUM_UPGRADE_MSG["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⭐ طلب الاشتراك المميز", callback_data=f"req_premium_{uid}"))
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

def send_premium_menu(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🌤 توقعات 7 أيام", callback_data="prem_7day"),
        types.InlineKeyboardButton("🕐 طقس كل 3 ساعات", callback_data="prem_hourly"),
        types.InlineKeyboardButton("🏙 إضافة مدينة", callback_data="prem_addcity"),
        types.InlineKeyboardButton("📋 مدنيّ المحفوظة", callback_data="prem_mycities"),
        types.InlineKeyboardButton("📌 اهتماماتي", callback_data="prem_interests"),
        types.InlineKeyboardButton("💱 تنبيه العملات", callback_data="prem_currency_alert"),
        types.InlineKeyboardButton("📊 جدول العملات", callback_data="prem_currency_table"),
        types.InlineKeyboardButton("🕐 وقت الإشعارات", callback_data="prem_notif_time"),
        types.InlineKeyboardButton("📰 ملخص أسبوعي", callback_data="prem_weekly"),
        types.InlineKeyboardButton("🔑 كلمات مفتاحية", callback_data="prem_keywords"),
    )
    bot.send_message(uid, "⭐ *قائمة المميز — اختر ما تريد:*", parse_mode="Markdown", reply_markup=markup)

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
            msg = f"🌤 *توقعات الطقس لـ 7 أيام — {city}*\n\n"
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

def get_uv_level(uvi):
    if uvi is None:
        return "غير متوفر"
    uvi = float(uvi)
    if uvi < 3:
        return f"{uvi:.1f} 🟢 منخفض"
    elif uvi < 6:
        return f"{uvi:.1f} 🟡 متوسط"
    elif uvi < 8:
        return f"{uvi:.1f} 🟠 مرتفع"
    elif uvi < 11:
        return f"{uvi:.1f} 🔴 خطر"
    else:
        return f"{uvi:.1f} 🟣 شديد الخطورة"

def get_wind_direction(deg):
    dirs = ["⬆️ شمال", "↗️ شمال شرق", "➡️ شرق", "↘️ جنوب شرق",
            "⬇️ جنوب", "↙️ جنوب غرب", "⬅️ غرب", "↖️ شمال غرب"]
    return dirs[round(deg / 45) % 8] if deg is not None else "-"

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
            bot.send_message(uid, f"⚠️ لم يتم العثور على بيانات الطقس لمدينة: {province}")
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
        msg = (
            f"{weather_emoji} *الطقس في {province}*\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"🌡 *الحرارة:* {temp}°C\n"
            f"🤔 *يشعر كـ:* {feels}°C\n"
            f"🔼 أعلى: {temp_max}°C  |  🔽 أدنى: {temp_min}°C\n\n"
            f"☁️ *الحالة:* {desc}\n"
            f"🌫 *الغيوم:* {clouds}%\n"
            f"👁 *الرؤية:* {visibility_km} كم\n\n"
            f"💧 *الرطوبة:* {humidity}%\n"
            f"🌀 *الضغط الجوي:* {pressure} hPa\n"
            f"☀️ *مؤشر UV:* {get_uv_level(uvi)}\n\n"
            f"💨 *الرياح:* {wind_speed} م/ث | {get_wind_direction(wind_deg)}\n"
            f"💨 *أقصى هبوب:* {wind_gust} م/ث\n\n"
            f"🌅 *الشروق:* {sunrise}  |  🌇 *الغروب:* {sunset}\n"
            f"━━━━━━━━━━━━━━━\n"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ لا يمكن جلب بيانات الطقس حالياً.")
        notify_admin_error(f"خطأ في الطقس لـ {uid}: {e}")

def add_extra_city(uid, city):
    users[str(uid)].setdefault("extra_cities", [])
    if city not in users[str(uid)]["extra_cities"]:
        users[str(uid)]["extra_cities"].append(city)
    save_json(USERS_FILE, users)
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
            bot.send_message(uid, "⚠️ لا يمكن جلب توقعات الساعات.")
            return
        msg = f"🕐 *الطقس كل 3 ساعات — {province}*\n━━━━━━━━━━━━━━━\n\n"
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
            msg += f"   💧 {humidity}% | 💨 {wind} م/ث\n\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ حدث خطأ في جلب توقعات الساعات.")
        notify_admin_error(f"خطأ في الطقس الساعي لـ {uid}: {e}")

def send_full_currency_table(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        rates = r.get("rates", {})
        pairs = [
            ("🇪🇺", "EUR", "اليورو"),
            ("🇬🇧", "GBP", "الجنيه الإسترليني"),
            ("🇮🇶", "IQD", "الدينار العراقي"),
            ("🇸🇦", "SAR", "الريال السعودي"),
            ("🇦🇪", "AED", "الدرهم الإماراتي"),
            ("🇹🇷", "TRY", "الليرة التركية"),
            ("🇮🇷", "IRR", "الريال الإيراني"),
            ("🇷🇺", "RUB", "الروبل الروسي"),
            ("🇵🇰", "PKR", "الروبية الباكستانية"),
            ("🇮🇳", "INR", "الروبية الهندية"),
            ("🇧🇷", "BRL", "الريال البرازيلي"),
            ("🇲🇽", "MXN", "البيزو المكسيكي"),
            ("🇨🇳", "CNY", "اليوان الصيني"),
            ("🇯🇵", "JPY", "الين الياباني"),
            ("🇨🇦", "CAD", "الدولار الكندي"),
            ("🇦🇺", "AUD", "الدولار الأسترالي"),
            ("🇰🇼", "KWD", "الدينار الكويتي"),
            ("🇪🇬", "EGP", "الجنيه المصري"),
        ]
        msg = "📊 *جدول أسعار الصرف الكامل مقابل الدولار 🇺🇸*\n━━━━━━━━━━━━━━━\n\n"
        for flag, code, name in pairs:
            rate = rates.get(code, "-")
            msg += f"{flag} {name}: `{rate}`\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ لا يمكن جلب الأسعار حالياً.")
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
        bot.send_message(uid, "⚠️ لا توجد أخبار لإنشاء الملخص الأسبوعي.")
        return
    msg = f"📰 *الملخص الأسبوعي — أبرز {min(len(headlines), 20)} خبر*\n━━━━━━━━━━━━━━━\n\n"
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
        save_json(USERS_FILE, users)
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
        save_json(USERS_FILE, users)
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

def broadcast_premium_instant_news():
    for uid, info in list(users.items()):
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
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for item in feed.entries[:3]:
                    if not hasattr(item, 'link') or item.link in sent:
                        continue
                    if not news_matches_interests(item.title, interests):
                        continue
                    sent.add(item.link)
                    bot.send_message(uid, f"⚡ *خبر عاجل فوري*\n\n📰 {item.title}", parse_mode="Markdown")
            except Exception as e:
                notify_admin_error(f"خطأ في الأخبار الفورية للمميز: {e}")
    save_json(USERS_FILE, users)

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
            msg = f"🌅 *ملخص صباحي — أبرز الأخبار*\n\n" + "\n".join(headlines[:10])
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
                    save_json(USERS_FILE, users)
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
            try:
                bot.send_message(referrer_id, f"🎉 انضم شخص جديد عبر رابطك!\n👤 الاسم: {message.from_user.first_name}\n👥 إجمالي دعواتك: {len(users[str(referrer_id)]['referrals'])}")
            except:
                pass
        save_json(USERS_FILE, users)
        update_stats("new_user", uid=uid)
        all_admins = [ADMIN_ID] + extra_admins
        for admin_id in all_admins:
            try:
                bot.send_message(admin_id, f"مستخدم جديد 👤\n\nالاسم: {message.from_user.first_name}\nاليوزر: @{username}\nID: `{uid}`", parse_mode="Markdown")
            except:
                pass
        send_first_time_welcome(uid, message.from_user.first_name)
        welcome_user(uid)
    else:
        users[str(uid)]["name"] = message.from_user.first_name
        save_json(USERS_FILE, users)
        user = users[str(uid)]
        if "province" in user:
            send_main_menu(uid)
        else:
            welcome_user(uid)

# ======== التعامل مع الرسائل ========
@bot.message_handler(func=lambda m: True)
def handle_selection(m):
    uid = m.from_user.id
    text = m.text
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
                bot.send_message(uid, "⚠️ صيغة غير صحيحة. مثال: *100 USD*", parse_mode="Markdown")
        else:
            bot.send_message(uid, "⚠️ أرسل المبلغ والعملة معاً. مثال: *100 USD*", parse_mode="Markdown")
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
            bot.send_message(uid, f"✅ تم حفظ {len(new_kws)} كلمة مفتاحية.\n🔔 ستصلك تنبيه عند ظهورها في أي خبر!")
        return

    if "province" in user:
        update_stats("button", button=text)
        if text == btn["settings"]:
            users[str(uid)] = {"name": user["name"], "sent_news": set()}
            save_json(USERS_FILE, users)
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
            bot.send_message(uid, "🔍 اكتب كلمة البحث:")
        elif text == btn.get("referral"):
            send_referral_stats(uid)
        elif text == btn.get("top_referrers"):
            send_top_referrers(uid)
        elif text == btn.get("sports"):
            send_sports_news(uid)
        elif text == btn.get("convert"):
            user_states[uid] = "converting_currency"
            bot.send_message(uid, "🔄 أرسل المبلغ والعملة، مثال:\n*100 USD*\n*50 EUR*\n*200 IQD*", parse_mode="Markdown")
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
            save_json(USERS_FILE, users)
            if not current:
                bot.send_message(uid, "🔔 تم تفعيل الإشعارات التلقائية.")
            else:
                bot.send_message(uid, "🔕 تم إيقاف الإشعارات التلقائية.")
            send_main_menu(uid)
        elif text == btn.get("premium", "⭐ Premium"):
            if is_premium(uid):
                send_premium_menu(uid)
            else:
                send_premium_upgrade(uid)
        else:
            send_main_menu(uid)
        return

    if "lang" not in user:
        for key, val in languages.items():
            if text == val:
                if val not in countries:
                    bot.send_message(uid, "⚠️ هذه اللغة غير متوفرة بالكامل. اختر لغة أخرى.")
                    return
                users[str(uid)]["lang"] = val
                save_json(USERS_FILE, users)
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[val]:
                    markup.add(country)
                bot.send_message(uid, "اختر دولتك / Choose your country:", reply_markup=markup)
                send_usage_hint(uid, val)
                return
        bot.send_message(uid, "👇 الرجاء اختيار لغة من القائمة.")
        return

    if "country" not in user:
        if lang in countries and text in countries[lang]:
            users[str(uid)]["country"] = text
            save_json(USERS_FILE, users)
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            for prov in countries[lang][text]:
                markup.add(prov)
            bot.send_message(uid, "اختر محافظتك / Choose your province:", reply_markup=markup)
        else:
            bot.send_message(uid, "👇 الرجاء اختيار دولة من القائمة.")
        return

    if "province" not in user:
        country = user["country"]
        if lang in countries and country in countries[lang]:
            valid_provinces = countries[lang][country]
            if text in valid_provinces:
                users[str(uid)]["province"] = text
                save_json(USERS_FILE, users)
                update_stats("new_user", country=country, lang=lang)
                bot.send_message(uid, "تم حفظ اختياراتك ✅\nستصلك الأخبار والطقس تلقائيًا كل ساعة.")
                send_main_menu(uid)
            else:
                bot.send_message(uid, "👇 الرجاء اختيار محافظة من القائمة.")

BOT_SIGNATURE = "\n━━━━━━━━━━━━━━\nعبر بوت أخبار العالم\n@Iraqnowbot"

# ======== دوال الأخبار (عنوان فقط — بدون رابط أو مصدر) ========
def format_news_item(prefix, title):
    return f"{prefix}\n\n📰 {title}{BOT_SIGNATURE}"

def make_news_share_markup(link, title=""):
    markup = types.InlineKeyboardMarkup()
    share_text = f"📰 {title[:80]}\n\nعبر @{BOT_USERNAME}" if title else f"عبر @{BOT_USERNAME}"
    share_url = f"https://t.me/share/url?url={link}&text={share_text}"
    bot_share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}&text=اشترك+في+بوت+الأخبار+%40{BOT_USERNAME}+لأحدث+الأخبار+والطقس+والعملات"
    markup.add(
        types.InlineKeyboardButton("🔗 فتح الخبر", url=link),
        types.InlineKeyboardButton("📤 مشاركة الخبر", url=share_url)
    )
    markup.add(
        types.InlineKeyboardButton(f"🤖 انشر البوت @{BOT_USERNAME}", url=bot_share_url)
    )
    return markup

def send_hourly_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, "⚠️ لا توجد مصادر أخبار لهذه اللغة حالياً.")
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
                markup = make_news_share_markup(item.link, getattr(item, 'title', ''))
                bot.send_message(uid, format_news_item("🚨 خبر", item.title), parse_mode="Markdown", reply_markup=markup)
                count += 1
        except Exception as e:
            notify_admin_error(f"خطأ في RSS ({feed_url}): {e}")
    if count == 0:
        bot.send_message(uid, "⚠️ لا توجد أخبار جديدة الآن.")
    else:
        save_json(USERS_FILE, users)

def send_all_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, "⚠️ لا توجد مصادر أخبار لهذه اللغة حالياً.")
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
                markup = make_news_share_markup(item.link, getattr(item, 'title', ''))
                bot.send_message(uid, format_news_item("🚨 خبر عاجل", item.title), parse_mode="Markdown", reply_markup=markup)
                count += 1
        except Exception as e:
            notify_admin_error(f"خطأ في RSS ({feed_url}): {e}")
    if count == 0:
        bot.send_message(uid, "⚠️ لا توجد أخبار جديدة الآن.")
    else:
        save_json(USERS_FILE, users)

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
                markup = make_news_share_markup(link, title)
                bot.send_message(uid, format_news_item("📰 أخبار الشرق الأوسط السياسية", title), parse_mode="Markdown", reply_markup=markup)
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
                        markup = make_news_share_markup(link, title)
                        bot.send_message(uid, format_news_item("📰 أخبار الشرق الأوسط السياسية", title), parse_mode="Markdown", reply_markup=markup)
                        count += 1
                        if count >= 5:
                            break
            except Exception as e:
                notify_admin_error(f"خطأ في RSS fallback MENA: {e}")
            if count >= 5:
                break
    if count == 0:
        bot.send_message(uid, "⚠️ لا توجد أخبار سياسية جديدة الآن، حاول مرة أخرى لاحقاً.")
    else:
        save_json(USERS_FILE, users)

# ======== البث التلقائي ========
def broadcast_weather():
    for uid, info in list(users.items()):
        province = info.get("province")
        if not province or int(uid) in banned:
            continue
        if not info.get("notifications", True):
            continue
        lang = info.get("lang", "English 🇬🇧")
        lang_code = LANG_CODES.get(lang, "en")
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
        try:
            data = requests.get(url, timeout=10).json()
            if data.get("cod") == 200:
                temp = data['main']['temp']
                desc = data['weather'][0]['description']
                bot.send_message(uid, f"🌤 الطقس في {province}: {temp}°C\n☁️ {desc}")
        except Exception as e:
            notify_admin_error(f"خطأ في بث الطقس لـ {uid}: {e}")

def broadcast_news():
    for uid, info in list(users.items()):
        if int(uid) in banned:
            continue
        if not info.get("notifications", True):
            continue
        if "province" not in info:
            continue
        lang = info.get("lang", "English 🇬🇧")
        feeds = RSS.get(lang, [])
        sent = info.setdefault("sent_news", set())
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for item in feed.entries[:5]:
                    if not hasattr(item, 'link') or item.link in sent:
                        continue
                    sent.add(item.link)
                    bot.send_message(uid, format_news_item("🚨 خبر عاجل", item.title), parse_mode="Markdown")
            except Exception as e:
                notify_admin_error(f"خطأ في RSS ({feed_url}): {e}")
    save_json(USERS_FILE, users)

# ======== أخبار الرياضة ========
def send_sports_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = SPORTS_RSS.get(lang, SPORTS_RSS.get("English 🇬🇧", []))
    if not feeds:
        bot.send_message(uid, "⚠️ لا توجد مصادر رياضية لهذه اللغة.")
        return
    sent = user.setdefault("sent_news", set())
    count = 0
    bot.send_message(uid, "⚽ *أخبار الرياضة*\n━━━━━━━━━━━━━━━", parse_mode="Markdown")
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for item in feed.entries[:5]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                markup = make_news_share_markup(item.link, getattr(item, 'title', ''))
                bot.send_message(uid, format_news_item("⚽", item.title), parse_mode="Markdown", reply_markup=markup)
                count += 1
                if count >= 8:
                    break
        except Exception as e:
            notify_admin_error(f"خطأ في أخبار الرياضة: {e}")
        if count >= 8:
            break
    if count == 0:
        bot.send_message(uid, "⚠️ لا توجد أخبار رياضية جديدة الآن.")
    else:
        save_json(USERS_FILE, users)

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
    name = user.get("name", "مستخدم")
    lang = user.get("lang", "—")
    province = user.get("province", "—")
    sent_news = user.get("sent_news", set())
    referrals = user.get("referrals", [])
    is_prem = "⭐ نعم" if is_premium(uid) else "❌ لا"
    notif = "🔔 مفعّلة" if user.get("notifications", True) else "🔕 متوقفة"
    join_date = user.get("join_date", "—")
    kws = user_keywords.get(str(uid), [])

    msg = (
        f"📈 *إحصائياتك الشخصية*\n━━━━━━━━━━━━━━━\n\n"
        f"👤 الاسم: *{name}*\n"
        f"🌍 اللغة: *{lang}*\n"
        f"🏙 المدينة: *{province}*\n"
        f"📅 تاريخ الانضمام: *{join_date}*\n\n"
        f"📰 أخبار استلمتها: *{len(sent_news)}*\n"
        f"🎁 دعوات أرسلتها: *{len(referrals)}*\n"
        f"🔑 كلمات مفتاحية: *{len(kws)}*\n"
        f"⭐ اشتراك مميز: *{is_prem}*\n"
        f"🔔 الإشعارات: *{notif}*\n"
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
        bot.send_message(uid, "⚠️ لم يتم تحديد مدينتك بعد.")
        return
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}&cnt=24"
        data = requests.get(url, timeout=10).json()
        if str(data.get("cod")) != "200":
            bot.send_message(uid, f"⚠️ لم يتم العثور على بيانات الطقس لمدينة: {province}")
            return
        days = {}
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            if date not in days:
                days[date] = {"temps": [], "descs": [], "icons": []}
            days[date]["temps"].append(item["main"]["temp"])
            days[date]["descs"].append(item["weather"][0]["description"])
            days[date]["icons"].append(item["weather"][0]["id"])
        msg = f"📅 *توقعات الطقس لـ 3 أيام — {province}*\n━━━━━━━━━━━━━━━\n\n"
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
        bot.send_message(uid, "⚠️ لا يمكن جلب توقعات الطقس حالياً.")
        notify_admin_error(f"خطأ في توقعات 3 أيام لـ {uid}: {e}")

# ======== ترتيب أفضل الداعين ========
def send_top_referrers(uid):
    referral_counts = []
    for user_id, info in users.items():
        refs = info.get("referrals", [])
        if refs:
            name = info.get("name", "مستخدم")
            referral_counts.append((name, len(refs)))
    referral_counts.sort(key=lambda x: x[1], reverse=True)
    top = referral_counts[:10]
    if not top:
        bot.send_message(uid, "📊 لا توجد دعوات بعد، كن أول من يدعو أصدقاءه! 🎯")
        return
    medals = ["🥇", "🥈", "🥉"] + ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    msg = "🏆 *أفضل الداعين*\n━━━━━━━━━━━━━━━\n\n"
    for i, (name, count) in enumerate(top):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        msg += f"{medal} *{name}* — {count} دعوة\n"
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== تنظيف البيانات التلقائي (Auto-Clean) ========
def auto_clean_sent_news():
    cutoff = datetime.datetime.now() - datetime.timedelta(days=2)
    cleaned = 0
    for uid, info in users.items():
        sent = info.get("sent_news", set())
        if isinstance(sent, list):
            sent = set(sent)
        if len(sent) > 500:
            sent_list = list(sent)
            users[uid]["sent_news"] = set(sent_list[-300:])
            cleaned += 1
    if cleaned > 0:
        save_json(USERS_FILE, users)
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
    save_json(USERS_FILE, users)

# ======== الجدولة ========

# ======== ملخص أخبار اليوم ========
def send_daily_summary(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, "⚠️ لا توجد مصادر أخبار لهذه اللغة حالياً.")
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
        bot.send_message(uid, "⚠️ لا توجد أخبار متاحة الآن، حاول لاحقاً.")
        return
    today = datetime.date.today().strftime("%Y-%m-%d")
    msg = f"📋 *ملخص أخبار اليوم — {today}*\n━━━━━━━━━━━━━━━\n\n"
    for i, title in enumerate(headlines[:10], 1):
        msg += f"{i}. {title}\n\n"
    msg += f"━━━━━━━━━━━━━━━\n{BOT_SIGNATURE}"
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== أسعار العملات الرقمية ========
def send_crypto_prices(uid):
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether,binancecoin,solana,ripple,dogecoin,cardano,tron,litecoin&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=10).json()
        crypto_names = {
            "bitcoin": ("₿ بيتكوين", "BTC"),
            "ethereum": ("⟠ إيثيريوم", "ETH"),
            "tether": ("💵 تيثر", "USDT"),
            "binancecoin": ("🟡 بينانس", "BNB"),
            "solana": ("◎ سولانا", "SOL"),
            "ripple": ("〇 ريبل", "XRP"),
            "dogecoin": ("🐶 دوجكوين", "DOGE"),
            "cardano": ("🔵 كاردانو", "ADA"),
            "tron": ("🔴 ترون", "TRX"),
            "litecoin": ("🥈 لايتكوين", "LTC"),
        }
        msg = "💎 *أسعار العملات الرقمية*\n━━━━━━━━━━━━━━━\n\n"
        for coin_id, (name, symbol) in crypto_names.items():
            data = r.get(coin_id, {})
            price = data.get("usd", "—")
            change = data.get("usd_24h_change", None)
            if isinstance(price, (int, float)):
                price_str = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
            else:
                price_str = "—"
            if change is not None:
                arrow = "📈" if change >= 0 else "📉"
                change_str = f"{arrow} {change:+.2f}%"
            else:
                change_str = ""
            msg += f"{name} ({symbol})\n   💲 {price_str}  {change_str}\n\n"
        msg += "━━━━━━━━━━━━━━━\n🔄 البيانات من CoinGecko"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ لا يمكن جلب أسعار العملات الرقمية الآن، حاول لاحقاً.")
        notify_admin_error(f"خطأ في أسعار الكريبتو: {e}")

# ======== أوقات الصلاة ========
def send_prayer_times(uid):
    user = users.get(str(uid))
    if not user:
        return
    province = user.get("province", "")
    if not province:
        bot.send_message(uid, "⚠️ لم يتم تحديد مدينتك. اضغط على تغيير الإعدادات وأعد الإعداد.")
        return
    try:
        today = datetime.date.today()
        url = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=IQ&method=4&date={today}"
        r = requests.get(url, timeout=10).json()
        if r.get("code") != 200:
            url2 = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=&method=4&date={today}"
            r = requests.get(url2, timeout=10).json()
        if r.get("code") != 200:
            bot.send_message(uid, f"⚠️ لا يمكن جلب أوقات الصلاة لمدينة: {province}\nتأكد من اسم المدينة باللغة الإنجليزية في إعداداتك.")
            return
        timings = r["data"]["timings"]
        date_info = r["data"]["date"]["readable"]
        hijri = r["data"]["date"]["hijri"]
        hijri_str = f"{hijri['day']} {hijri['month']['ar']} {hijri['year']} هـ"
        msg = (
            f"🕌 *أوقات الصلاة في {province}*\n"
            f"📅 {date_info}\n"
            f"🗓 {hijri_str}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"🌅 الفجر:     `{timings['Fajr']}`\n"
            f"☀️ الشروق:   `{timings['Sunrise']}`\n"
            f"🌞 الظهر:    `{timings['Dhuhr']}`\n"
            f"🌇 العصر:    `{timings['Asr']}`\n"
            f"🌆 المغرب:   `{timings['Maghrib']}`\n"
            f"🌙 العشاء:   `{timings['Isha']}`\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔄 البيانات من Aladhan API"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ لا يمكن جلب أوقات الصلاة الآن، حاول لاحقاً.")
        notify_admin_error(f"خطأ في أوقات الصلاة لـ {uid}: {e}")

# ======== إحصائيات الدعوات (رابط الدعوة) ========
def send_referral_stats(uid):
    user = users.get(str(uid))
    if not user:
        return
    referrals = user.get("referrals", [])
    ref_count = len(referrals)
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    msg = (
        f"🎁 *نظام الدعوات*\n━━━━━━━━━━━━━━━\n\n"
        f"🔗 *رابط دعوتك الخاص:*\n"
        f"`{invite_link}`\n\n"
        f"👥 *إجمالي من دعوتهم:* `{ref_count}` شخص\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📤 شارك الرابط مع أصدقائك وعائلتك!\n"
        f"كل شخص ينضم عبر رابطك سيُحتسب لك. 🎯"
    )
    markup = types.InlineKeyboardMarkup()
    share_text = f"📰 اكتشف بوت الأخبار والطقس العراقي!\n\n{invite_link}"
    share_url = f"https://t.me/share/url?url={invite_link}&text=انضم+معي+في+بوت+الأخبار+العراقي+%40{BOT_USERNAME}"
    markup.add(types.InlineKeyboardButton("📤 مشاركة الرابط", url=share_url))
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

# ======== انشر البوت ========
def send_share_bot(uid):
    invite_link = f"https://t.me/{BOT_USERNAME}"
    msg = (
        f"📢 *انشر البوت وساعدنا بالوصول لأكثر مستخدمين!*\n\n"
        f"🔗 *رابط البوت:*\n"
        f"@{BOT_USERNAME}\n\n"
        f"📌 أو عبر الرابط:\n"
        f"`{invite_link}`\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💡 شارك البوت مع أصدقائك للحصول على:\n"
        f"📰 آخر الأخبار العراقية والعالمية\n"
        f"🌤 حالة الطقس الفورية\n"
        f"💱 أسعار العملات\n"
        f"🕌 أوقات الصلاة\n"
        f"💎 أسعار العملات الرقمية"
    )
    markup = types.InlineKeyboardMarkup()
    share_url = f"https://t.me/share/url?url={invite_link}&text=اشترك+في+بوت+الأخبار+العراقي+%40{BOT_USERNAME}+لأحدث+الأخبار+والطقس"
    markup.add(
        types.InlineKeyboardButton("📤 مشاركة البوت", url=share_url),
        types.InlineKeyboardButton("🔗 فتح البوت", url=invite_link)
    )
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

# ======== إحصائيات البوت العامة ========
def send_public_stats(uid):
    total = stats.get("total_users", len(users))
    today = str(datetime.date.today())
    today_count = stats.get("daily_users", {}).get(today, 0)
    active = sum(1 for u in users.values() if "province" in u)
    premium_count = len(stats.get("premium_users", []))
    top_langs = sorted(stats.get("languages_count", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    msg = (
        f"📊 *إحصائيات البوت*\n━━━━━━━━━━━━━━━\n\n"
        f"👥 إجمالي المستخدمين: *{total}*\n"
        f"✅ مستخدمون نشطون: *{active}*\n"
        f"🆕 انضموا اليوم: *{today_count}*\n"
        f"⭐ مشتركون مميزون: *{premium_count}*\n\n"
    )
    if top_langs:
        msg += "🌍 *أكثر اللغات استخداماً:*\n"
        for lang_name, count in top_langs:
            msg += f"  • {lang_name}: {count}\n"
    msg += f"\n━━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}"
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== دولار السوق الموازية ========
def send_dollar_parallel(uid):
    rate = None
    source_note = ""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://dolarsoft.com/api/v1/price", headers=headers, timeout=8)
        data = r.json()
        sell = data.get("sell") or data.get("price") or data.get("usd_sell")
        buy = data.get("buy") or data.get("usd_buy")
        if sell:
            rate = f"بيع: `{sell}` دينار\nشراء: `{buy or '-'}` دينار"
            source_note = "dolarsoft.com"
    except:
        pass
    if not rate:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
            iqd = r.json().get("rates", {}).get("IQD", None)
            if iqd:
                rate = f"السعر: `{int(iqd):,}` دينار\n_(السعر الرسمي — قد يختلف عن السوق)_"
                source_note = "exchangerate-api.com"
        except:
            pass
    if not rate:
        bot.send_message(uid, "⚠️ تعذّر جلب سعر الدولار حالياً. حاول لاحقاً.")
        return
    now = datetime.datetime.now().strftime("%H:%M - %d/%m/%Y")
    msg = (
        f"💵 *سعر الدولار مقابل الدينار العراقي*\n\n"
        f"🏪 السوق الموازية:\n"
        f"{rate}\n\n"
        f"⏰ آخر تحديث: `{now}`\n"
        f"📡 المصدر: {source_note}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"🤖 @{BOT_USERNAME}"
    )
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== ملخص أسبوعي نصي ========
def send_weekly_summary_text(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, "⚠️ لا توجد مصادر أخبار متاحة لهذه اللغة.")
        return
    bot.send_message(uid, "⏳ جاري جمع أبرز أخبار الأسبوع...")
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
        bot.send_message(uid, "⚠️ لا توجد أخبار كافية هذا الأسبوع.")
        return
    week_start = (datetime.datetime.now() - datetime.timedelta(days=6)).strftime("%d/%m")
    week_end = datetime.datetime.now().strftime("%d/%m/%Y")
    lines = [f"📆 *ملخص أخبار الأسبوع*\n📅 {week_start} — {week_end}\n━━━━━━━━━━━━━━\n"]
    for i, title in enumerate(headlines, 1):
        lines.append(f"{i}. {title}")
    lines.append(f"\n━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}")
    full_msg = "\n".join(lines)
    if len(full_msg) > 4000:
        full_msg = full_msg[:3990] + "\n..."
    bot.send_message(uid, full_msg, parse_mode="Markdown")

# ======== تتبع العملات والأسهم ========
CRYPTO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
    "USDT": "tether", "XRP": "ripple", "ADA": "cardano",
    "SOL": "solana", "DOGE": "dogecoin", "DOT": "polkadot",
    "MATIC": "matic-network", "LTC": "litecoin", "AVAX": "avalanche-2",
    "SHIB": "shiba-inu", "TRX": "tron", "LINK": "chainlink"
}
FIAT_CURRENCIES = {"USD", "EUR", "GBP", "IQD", "SAR", "AED", "TRY", "JPY", "CNY", "KWD", "EGP", "JOD"}

def fetch_asset_price(symbol):
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
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        ).json()
        closes = r["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        price = next((p for p in reversed(closes) if p is not None), None)
        return float(price) if price else None
    except:
        return None

def format_asset_price(symbol, price):
    if price is None:
        return f"{symbol}: غير متوفر"
    if price >= 1000:
        return f"{symbol}: `{price:,.2f}`"
    elif price >= 1:
        return f"{symbol}: `{price:.4f}`"
    else:
        return f"{symbol}: `{price:.8f}`"

def start_track_asset(uid):
    user_data = tracked_assets.get(str(uid), {})
    assets = user_data.get("assets", [])
    last_prices = user_data.get("last_prices", {})
    msg = "📌 *تتبع العملات والأسهم*\n\n"
    if assets:
        msg += "📋 *قائمتك الحالية:*\n"
        for sym in assets:
            p = last_prices.get(sym)
            msg += f"  • {format_asset_price(sym, p)}\n"
        msg += "\n"
    msg += (
        "➕ *لإضافة رمز جديد:* أرسل اسمه\n"
        "مثال: `AAPL` `TSLA` `BTC` `EUR` `GOLD`\n\n"
        "❌ *لحذف رمز:* أرسل `/removetrack AAPL`\n"
        "📋 *لعرض قائمتك:* أرسل `/mytrack`"
    )
    user_states[uid] = "tracking_asset"
    bot.send_message(uid, msg, parse_mode="Markdown")

def check_asset_tracking():
    for uid_str, data in list(tracked_assets.items()):
        assets = data.get("assets", [])
        last_prices = data.get("last_prices", {})
        changed = False
        for symbol in assets:
            try:
                new_price = fetch_asset_price(symbol)
                if new_price is None:
                    continue
                old_price = last_prices.get(symbol)
                if old_price and old_price > 0:
                    change_pct = ((new_price - old_price) / old_price) * 100
                    if abs(change_pct) >= 2.0:
                        direction = "📈 ارتفع" if change_pct > 0 else "📉 انخفض"
                        try:
                            bot.send_message(
                                int(uid_str),
                                f"🔔 *تنبيه تغير السعر*\n\n"
                                f"💱 *{symbol}*\n"
                                f"{direction} بنسبة `{change_pct:+.2f}%`\n\n"
                                f"السعر القديم: `{old_price:.4f}`\n"
                                f"السعر الجديد: `{new_price:.4f}`\n\n"
                                f"🤖 @{BOT_USERNAME}",
                                parse_mode="Markdown"
                            )
                        except:
                            pass
                tracked_assets[uid_str]["last_prices"][symbol] = new_price
                changed = True
            except:
                continue
        if changed:
            save_tracked_assets()

@bot.message_handler(commands=["mytrack"])
def cmd_mytrack(m):
    uid = m.from_user.id
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if not assets:
        bot.send_message(uid, "📌 قائمة التتبع فارغة.\nاضغط زر *تتبع عملة/سهم* لإضافة رموز.", parse_mode="Markdown")
        return
    last_prices = data.get("last_prices", {})
    msg = "📌 *قائمة أصولك المتتبعة:*\n━━━━━━━━━━━━━━\n"
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
    parts = m.text.strip().split()
    if len(parts) < 2:
        bot.send_message(uid, "⚠️ أرسل الرمز بعد الأمر. مثال: `/removetrack AAPL`", parse_mode="Markdown")
        return
    symbol = parts[1].upper()
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if symbol not in assets:
        bot.send_message(uid, f"⚠️ *{symbol}* غير موجودة في قائمتك.", parse_mode="Markdown")
        return
    assets.remove(symbol)
    tracked_assets[str(uid)]["assets"] = assets
    tracked_assets[str(uid)]["last_prices"].pop(symbol, None)
    save_tracked_assets()
    bot.send_message(uid, f"✅ تم حذف *{symbol}* من قائمة التتبع.", parse_mode="Markdown")

# ======== الجدولة ========
scheduler = BackgroundScheduler()
scheduler.add_job(broadcast_weather, 'interval', hours=1)
scheduler.add_job(broadcast_news, 'interval', minutes=5)
scheduler.add_job(broadcast_premium_instant_news, 'interval', minutes=5)
scheduler.add_job(send_morning_summary, 'interval', hours=1)
scheduler.add_job(check_weather_alerts, 'interval', hours=6)
scheduler.add_job(check_currency_alerts, 'interval', hours=3)
scheduler.add_job(check_keyword_alerts, 'interval', minutes=15)
scheduler.add_job(auto_clean_sent_news, 'interval', hours=24)
scheduler.add_job(check_asset_tracking, 'interval', minutes=30)
scheduler.add_job(lambda: save_json(USERS_FILE, users), 'interval', minutes=10)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))

# ======== تشغيل البوت ========
bot.infinity_polling()
