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
# تحويل banned إلى قائمة من int دائماً
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

# ======== مصادر RSS (مع دعم الحفظ) ========
DEFAULT_RSS = {
    "العربية 🇮🇶": [
        "https://www.alarabiya.net/.mrss/ar/0/0/0.xml",        # العربية
        "https://www.bbc.com/arabic/index.xml",                # BBC عربي
        "https://www.aljazeera.net/aljazeera/feeds/rss.xml",   # الجزيرة
        "https://www.alsumaria.tv/rss/latest-news",            # السومرية
        "https://www.skynewsarabia.com/rss.xml",               # سكاي نيوز عربية
        "https://arabic.rt.com/rss/",                          # RT عربي
        "https://feeds.feedburner.com/alkhaleejonline",        # الخليج
        "https://www.independentarabia.com/rss.xml",           # إندبندنت عربي
    ],
    "English 🇬🇧": [
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",         # NY Times
        "http://feeds.bbci.co.uk/news/world/rss.xml",                     # BBC
        "https://feeds.reuters.com/reuters/worldNews",                    # Reuters
        "https://rss.cnn.com/rss/edition_world.rss",                      # CNN
        "https://feeds.skynews.com/feeds/rss/world.xml",                  # Sky News
        "https://www.aljazeera.com/xml/rss/all.xml",                      # Al Jazeera
        "https://feeds.washingtonpost.com/rss/world",                     # Washington Post
        "https://rss.dw.com/rdf/rss-en-all",                              # DW English
    ],
    "Русский 🇷🇺": [
        "https://www.rbc.ru/rss/news",                                     # RBC
        "https://tass.ru/rss/v2.xml",                                      # ТАСС
        "https://rss.dw.com/rdf/rss-ru-all",                              # DW Русский
        "https://www.bbc.com/russian/index.xml",                          # BBC Русский
        "https://www.golos-ameriki.ru/api/zrqomtmopp",                    # Голос Америки
        "https://meduza.io/rss/all",                                       # Медуза
    ],
    "فارسی 🇮🇷": [
        "https://www.radiofarda.com/api/zrqomtmopp",                      # رادیو فردا
        "https://ir.voanews.com/api/zrqomtmopp",                          # VOA فارسی
        "https://www.bbc.com/persian/index.xml",                          # BBC فارسی
        "https://rss.dw.com/rdf/rss-per-all",                             # DW فارسی
        "https://www.dw.com/fa/rss",                                       # DW فارسی
    ],
    "हिन्दी 🇮🇳": [
        "https://feeds.bbci.co.uk/hindi/rss.xml",                         # BBC हिंदी
        "https://www.hindustantimes.com/rss/rssfeed.xml",                 # Hindustan Times
        "https://ndtv.com/rss/top-stories",                               # NDTV
        "https://www.aajtak.in/rss/top-stories.xml",                      # Aaj Tak
        "https://rss.dw.com/rdf/rss-hin-all",                             # DW हिंदी
        "https://www.indiatoday.in/rss/home",                             # India Today
    ],
    "Português 🇧🇷": [
        "https://feeds.bbci.co.uk/portuguese/rss.xml",                    # BBC Português
        "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",  # Agência Brasil
        "https://rss.dw.com/rdf/rss-por-all",                             # DW Português
        "https://g1.globo.com/rss/g1/index.xml",                          # G1 Globo
        "https://www.uol.com.br/rss.xml",                                 # UOL
        "https://feeds.folha.uol.com.br/poder/rss091.xml",               # Folha de S.Paulo
    ],
    "Türkçe 🇹🇷": [
        "https://feeds.bbci.co.uk/turkish/rss.xml",                       # BBC Türkçe
        "https://www.aa.com.tr/tr/rss/default",                           # Anadolu Ajansı
        "https://rss.dw.com/rdf/rss-tur-all",                             # DW Türkçe
        "https://www.hurriyet.com.tr/rss/anasayfa",                       # Hürriyet
        "https://www.sabah.com.tr/rss/anasayfa.xml",                      # Sabah
        "https://www.ntv.com.tr/son-dakika.rss",                          # NTV
    ],
    "اردو 🇵🇰": [
        "https://feeds.bbci.co.uk/urdu/rss.xml",                          # BBC اردو
        "https://www.geo.tv/rss",                                          # Geo TV
        "https://www.jang.com.pk/rss/1",                                  # Jang
        "https://rss.dw.com/rdf/rss-urd-all",                             # DW اردو
        "https://www.urduvoa.com/api/zrqomtmopp",                         # VOA اردو
        "https://www.express.pk/feed",                                    # Express News
    ],
    "Deutsch 🇩🇪": [
        "https://www.spiegel.de/international/index.rss",                 # Spiegel
        "https://rss.dw.com/rdf/rss-de-all",                              # DW Deutsch
        "https://www.tagesschau.de/xml/rss2",                             # Tagesschau
        "https://www.faz.net/rss/aktuell",                                # FAZ
        "https://www.zeit.de/news/rss-aktuell",                           # Die Zeit
        "https://www.bild.de/rssfeeds/rss3-20745882,dzbildplus=false,sort=1,teaserImage=true,mxheight=1000,outputType%3Drss2/rss2.bild.html", # Bild
    ],
    "Українська 🇺🇦": [
        "https://feeds.bbci.co.uk/ukrainian/rss.xml",                     # BBC Україна
        "https://www.ukrinform.ua/rss/block-lastnews",                    # Укрінформ
        "https://rss.dw.com/rdf/rss-ukr-all",                             # DW Українська
        "https://www.unian.ua/rss/all_news.rss",                          # УНІАН
        "https://www.pravda.com.ua/rss/view_news/",                       # Українська правда
        "https://espresso.com.ua/rss",                                    # Еспресо
    ],
    "Italiano 🇮🇹": [
        "https://www.repubblica.it/rss/homepage/rss2.0.xml",              # La Repubblica
        "https://www.corriere.it/rss/homepage.xml",                       # Corriere della Sera
        "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",       # ANSA
        "https://rss.dw.com/rdf/rss-it-all",                              # DW Italiano
        "https://www.lastampa.it/rss.xml",                                # La Stampa
        "https://feeds.bbci.co.uk/italian/rss.xml",                      # BBC Italiano
    ],
    "Español 🇲🇽": [
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada", # El País
        "https://feeds.bbci.co.uk/mundo/rss.xml",                          # BBC Mundo
        "https://rss.dw.com/rdf/rss-es-all",                               # DW Español
        "https://feeds.reuters.com/reuters/MXdomesticNews",               # Reuters México
        "https://www.infobae.com/feeds/rss/",                             # Infobae
        "https://cnnespanol.cnn.com/feed/",                               # CNN Español
        "https://eldiariony.com/feed/",                                   # El Diario NY
    ],
}

# تحميل RSS من الملف إن وجد، وإلا استخدام الافتراضي
RSS = load_json(RSS_FILE, DEFAULT_RSS)

def save_rss():
    save_json(RSS_FILE, RSS)

# ======== الأزرار (لجميع اللغات الـ 12) ========
BUTTONS = {
    "العربية 🇮🇶": {
        "weather": "🌤 الطقس الآن",
        "news": "📰 آخر الأخبار",
        "all_news": "📰 إرسال كل الأخبار",
        "mena_politics": "📰 أخبار الشرق الأوسط السياسية",
        "currency": "💱 أسعار العملات",
        "search": "🔍 بحث في الأخبار",
        "notif_on": "🔔 إيقاف الإشعارات",
        "notif_off": "🔕 تفعيل الإشعارات",
        "premium": "⭐ المميز",
        "settings": "🔄 تغيير الإعدادات",
        "choose": "✅ اختر ما تريد:"
    },
    "English 🇬🇧": {
        "weather": "🌤 Weather Now",
        "news": "📰 Latest News",
        "all_news": "📰 Send All News",
        "mena_politics": "📰 Middle East Politics News",
        "currency": "💱 Currency Rates",
        "search": "🔍 Search News",
        "notif_on": "🔔 Disable Notifications",
        "notif_off": "🔕 Enable Notifications",
        "premium": "⭐ Premium",
        "settings": "🔄 Change Settings",
        "choose": "✅ Choose what you want:"
    },
    "Русский 🇷🇺": {
        "weather": "🌤 Погода сейчас",
        "news": "📰 Последние новости",
        "all_news": "📰 Все новости",
        "mena_politics": "📰 Политика Ближнего Востока",
        "currency": "💱 Курсы валют",
        "search": "🔍 Поиск новостей",
        "notif_on": "🔔 Отключить уведомления",
        "notif_off": "🔕 Включить уведомления",
        "premium": "⭐ Премиум",
        "settings": "🔄 Изменить настройки",
        "choose": "✅ Выберите:"
    },
    "فارسی 🇮🇷": {
        "weather": "🌤 آب‌وهوا",
        "news": "📰 آخرین اخبار",
        "all_news": "📰 ارسال همه اخبار",
        "mena_politics": "📰 اخبار سیاسی خاورمیانه",
        "currency": "💱 نرخ ارز",
        "search": "🔍 جستجوی اخبار",
        "notif_on": "🔔 غیرفعال‌کردن اعلان‌ها",
        "notif_off": "🔕 فعال‌کردن اعلان‌ها",
        "premium": "⭐ ویژه",
        "settings": "🔄 تغییر تنظیمات",
        "choose": "✅ انتخاب کنید:"
    },
    "हिन्दी 🇮🇳": {
        "weather": "🌤 मौसम अभी",
        "news": "📰 ताज़ा खबरें",
        "all_news": "📰 सभी खबरें भेजें",
        "mena_politics": "📰 मध्य पूर्व राजनीति",
        "currency": "💱 मुद्रा दरें",
        "search": "🔍 खबर खोजें",
        "notif_on": "🔔 सूचनाएं बंद करें",
        "notif_off": "🔕 सूचनाएं चालू करें",
        "premium": "⭐ प्रीमियम",
        "settings": "🔄 सेटिंग बदलें",
        "choose": "✅ चुनें:"
    },
    "Português 🇧🇷": {
        "weather": "🌤 Clima agora",
        "news": "📰 Últimas notícias",
        "all_news": "📰 Enviar todas notícias",
        "mena_politics": "📰 Política do Oriente Médio",
        "currency": "💱 Taxas de câmbio",
        "search": "🔍 Buscar notícias",
        "notif_on": "🔔 Desativar notificações",
        "notif_off": "🔕 Ativar notificações",
        "premium": "⭐ Premium",
        "settings": "🔄 Mudar configurações",
        "choose": "✅ Escolha:"
    },
    "Türkçe 🇹🇷": {
        "weather": "🌤 Hava durumu",
        "news": "📰 Son haberler",
        "all_news": "📰 Tüm haberleri gönder",
        "mena_politics": "📰 Orta Doğu Siyaseti",
        "currency": "💱 Döviz kurları",
        "search": "🔍 Haber ara",
        "notif_on": "🔔 Bildirimleri kapat",
        "notif_off": "🔕 Bildirimleri aç",
        "premium": "⭐ Premium",
        "settings": "🔄 Ayarları değiştir",
        "choose": "✅ Seçin:"
    },
    "اردو 🇵🇰": {
        "weather": "🌤 موسم ابھی",
        "news": "📰 تازہ خبریں",
        "all_news": "📰 تمام خبریں بھیجیں",
        "mena_politics": "📰 مشرق وسطی سیاسی خبریں",
        "currency": "💱 کرنسی ریٹ",
        "search": "🔍 خبریں تلاش کریں",
        "notif_on": "🔔 اطلاعات بند کریں",
        "notif_off": "🔕 اطلاعات چالو کریں",
        "premium": "⭐ پریمیم",
        "settings": "🔄 ترتیبات بدلیں",
        "choose": "✅ انتخاب کریں:"
    },
    "Deutsch 🇩🇪": {
        "weather": "🌤 Wetter jetzt",
        "news": "📰 Neueste Nachrichten",
        "all_news": "📰 Alle Nachrichten",
        "mena_politics": "📰 Nahost-Politik",
        "currency": "💱 Wechselkurse",
        "search": "🔍 Nachrichten suchen",
        "notif_on": "🔔 Benachrichtigungen aus",
        "notif_off": "🔕 Benachrichtigungen ein",
        "premium": "⭐ Premium",
        "settings": "🔄 Einstellungen ändern",
        "choose": "✅ Wählen Sie:"
    },
    "Українська 🇺🇦": {
        "weather": "🌤 Погода зараз",
        "news": "📰 Останні новини",
        "all_news": "📰 Всі новини",
        "mena_politics": "📰 Близький Схід",
        "currency": "💱 Курси валют",
        "search": "🔍 Пошук новин",
        "notif_on": "🔔 Вимкнути сповіщення",
        "notif_off": "🔕 Увімкнути сповіщення",
        "premium": "⭐ Преміум",
        "settings": "🔄 Змінити налаштування",
        "choose": "✅ Оберіть:"
    },
    "Italiano 🇮🇹": {
        "weather": "🌤 Meteo ora",
        "news": "📰 Ultime notizie",
        "all_news": "📰 Tutte le notizie",
        "mena_politics": "📰 Politica Medio Oriente",
        "currency": "💱 Tassi di cambio",
        "search": "🔍 Cerca notizie",
        "notif_on": "🔔 Disattiva notifiche",
        "notif_off": "🔕 Attiva notifiche",
        "premium": "⭐ Premium",
        "settings": "🔄 Cambia impostazioni",
        "choose": "✅ Scegli:"
    },
    "Español 🇲🇽": {
        "weather": "🌤 Clima ahora",
        "news": "📰 Últimas noticias",
        "all_news": "📰 Todas las noticias",
        "mena_politics": "📰 Política de Oriente Medio",
        "currency": "💱 Tipos de cambio",
        "search": "🔍 Buscar noticias",
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

# ======== الاهتمامات والكلمات المفتاحية (لجميع اللغات) ========
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
    # عربي
    "رياضة": ["رياضة", "كرة", "مباراة", "بطولة", "لاعب", "فريق", "هدف", "ملعب"],
    "اقتصاد": ["اقتصاد", "نفط", "دولار", "تجارة", "بنك", "مال", "بورصة", "سوق"],
    "تقنية": ["تقنية", "ذكاء اصطناعي", "تكنولوجيا", "هاتف", "إنترنت", "تطبيق", "برنامج"],
    "سياسة": ["سياسة", "حكومة", "رئيس", "وزير", "برلمان", "انتخاب", "حزب"],
    "صحة": ["صحة", "مستشفى", "طبيب", "علاج", "مرض", "لقاح", "وباء"],
    # إنجليزي
    "sports": ["sport", "football", "match", "tournament", "player", "team", "goal"],
    "economy": ["economy", "oil", "dollar", "trade", "bank", "finance", "market", "stock"],
    "technology": ["tech", "ai", "internet", "app", "software", "phone", "digital"],
    "politics": ["politics", "government", "president", "minister", "parliament", "election"],
    "health": ["health", "hospital", "doctor", "treatment", "disease", "vaccine", "epidemic"],
    # روسي
    "спорт": ["спорт", "футбол", "матч", "турнир", "игрок", "команда", "гол"],
    "экономика": ["экономика", "нефть", "доллар", "торговля", "банк", "рынок"],
    "технологии": ["технологии", "ии", "интернет", "приложение", "программа"],
    "политика": ["политика", "правительство", "президент", "министр", "парламент"],
    "здоровье": ["здоровье", "больница", "врач", "лечение", "болезнь", "вакцина"],
    # فارسي
    "ورزش": ["ورزش", "فوتبال", "مسابقه", "تیم", "بازیکن"],
    "اقتصاد_fa": ["اقتصاد", "نفت", "دلار", "تجارت", "بانک", "بازار"],
    "فناوری": ["فناوری", "هوش مصنوعی", "اینترنت", "نرم‌افزار"],
    "سیاست": ["سیاست", "دولت", "رئیس جمهور", "وزیر", "مجلس"],
    "سلامت": ["سلامت", "بیمارستان", "پزشک", "درمان", "بیماری"],
    # تركي
    "spor": ["spor", "futbol", "maç", "turnuva", "oyuncu", "takım", "gol"],
    "ekonomi": ["ekonomi", "petrol", "dolar", "ticaret", "banka", "piyasa"],
    "teknoloji": ["teknoloji", "yapay zeka", "internet", "uygulama", "yazılım"],
    "siyaset": ["siyaset", "hükümet", "cumhurbaşkanı", "bakan", "meclis", "seçim"],
    "sağlık": ["sağlık", "hastane", "doktor", "tedavi", "hastalık", "aşı"],
    # ألماني
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

# ======== مصادر MENA حسب اللغة ========
MENA_RSS = {
    "العربية 🇮🇶": [
        "https://www.aljazeera.net/aljazeera/feeds/rss.xml",
        "https://www.alarabiya.net/.mrss/ar/0/0/0.xml",
        "https://www.alsumaria.tv/rss/latest-news",
    ],
    "English 🇬🇧": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.middleeasteye.net/rss",
    ],
    "Русский 🇷🇺": [
        "https://www.aljazeera.com/xml/rss/all.xml",
    ],
    "Türkçe 🇹🇷": [
        "https://www.aljazeera.com.tr/feed",
    ],
    "Deutsch 🇩🇪": [
        "https://www.aljazeera.com/xml/rss/all.xml",
    ],
    "Español 🇲🇽": [
        "https://www.aljazeera.com/xml/rss/all.xml",
    ],
    "Italiano 🇮🇹": [
        "https://www.aljazeera.com/xml/rss/all.xml",
    ],
}

# ======== حالة البحث ========
user_states = {}

# ======== إشعار الأدمن بالأخطاء ========
def notify_admin_error(msg):
    try:
        bot.send_message(ADMIN_ID, f"⚠️ *خطأ في البوت:*\n`{msg}`", parse_mode="Markdown")
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
            try:
                bot.send_message(ADMIN_ID, f"🎉 وصلت {total} مستخدم!")
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
    )
    bot.send_message(uid, "👑 *لوحة تحكم الأدمن:*", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.from_user.id != ADMIN_ID:
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
        bot.send_message(ADMIN_ID,
            f"⭐ *طلب اشتراك مميز*\n\n"
            f"👤 الاسم: {name}\n"
            f"🆔 ID: `{requester_id}`\n"
            f"🗣 اللغة: {lang}\n\n"
            f"لترقيته: /admin ← المستخدمون ← ترقية لمميز",
            parse_mode="Markdown"
        )
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
    if call.from_user.id != ADMIN_ID:
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

# ======== خطوات الأدمن ========
def get_user_info(message):
    try:
        target_id = str(message.text.strip())
        user = users.get(target_id)
        if not user:
            bot.send_message(ADMIN_ID, "❌ المستخدم غير موجود.")
            return
        is_banned_user = int(target_id) in banned
        is_premium_user = int(target_id) in stats.get("premium_users", [])
        msg = (
            f"👤 *معلومات المستخدم*\n\n"
            f"🆔 ID: `{target_id}`\n"
            f"👤 الاسم: {user.get('name', 'غير معروف')}\n"
            f"🗣 اللغة: {user.get('lang', '-')}\n"
            f"🌍 الدولة: {user.get('country', '-')}\n"
            f"📍 المحافظة: {user.get('province', '-')}\n"
            f"🚫 محظور: {'نعم' if is_banned_user else 'لا'}\n"
            f"⭐ مميز: {'نعم' if is_premium_user else 'لا'}\n"
        )
        bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def ban_user_step(message):
    try:
        target_id = int(message.text.strip())
        if target_id not in banned:
            banned.append(target_id)
            save_json(BANNED_FILE, banned)
        bot.send_message(ADMIN_ID, f"✅ تم حظر المستخدم `{target_id}`", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "🚫 تم حظرك من استخدام البوت.")
        except:
            pass
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def unban_user_step(message):
    try:
        target_id = int(message.text.strip())
        if target_id in banned:
            banned.remove(target_id)
            save_json(BANNED_FILE, banned)
            bot.send_message(ADMIN_ID, f"✅ تم رفع حظر المستخدم `{target_id}`", parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_ID, "⚠️ المستخدم غير محظور.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def promote_premium_step(message):
    try:
        target_id = int(message.text.strip())
        if "premium_users" not in stats:
            stats["premium_users"] = []
        if target_id not in stats["premium_users"]:
            stats["premium_users"].append(target_id)
            save_json(STATS_FILE, stats)
        bot.send_message(ADMIN_ID, f"⭐ تم ترقية المستخدم `{target_id}` للمميز.", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "⭐ تهانينا! تمت ترقيتك لحساب مميز.")
        except:
            pass
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def demote_premium_step(message):
    try:
        target_id = int(message.text.strip())
        if target_id in stats.get("premium_users", []):
            stats["premium_users"].remove(target_id)
            save_json(STATS_FILE, stats)
            bot.send_message(ADMIN_ID, f"✅ تم إلغاء الاشتراك المميز للمستخدم `{target_id}`", parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_ID, "⚠️ المستخدم ليس مميزاً.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def broadcast_all_step(message):
    text = message.text
    count, failed = 0, 0
    for uid in list(users.keys()):
        try:
            bot.send_message(uid, text)
            count += 1
        except:
            failed += 1
    bot.send_message(ADMIN_ID, f"📢 *تم الإرسال:*\n✅ نجح: `{count}`\n❌ فشل: `{failed}`", parse_mode="Markdown")

def broadcast_country_step(message):
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(ADMIN_ID, "❌ أرسل الدولة ثم الرسالة في سطرين.")
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
    bot.send_message(ADMIN_ID, f"✅ تم الإرسال لـ `{count}` مستخدم في {country}", parse_mode="Markdown")

def broadcast_lang_step(message):
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(ADMIN_ID, "❌ أرسل اللغة ثم الرسالة في سطرين.")
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
    bot.send_message(ADMIN_ID, f"✅ تم الإرسال لـ `{count}` مستخدم يتحدث {lang}", parse_mode="Markdown")

def broadcast_premium_step(message):
    text = message.text
    count = 0
    for uid in stats.get("premium_users", []):
        try:
            bot.send_message(uid, text)
            count += 1
        except:
            pass
    bot.send_message(ADMIN_ID, f"⭐ تم الإرسال لـ `{count}` مستخدم مميز", parse_mode="Markdown")

def pause_bot_step(message):
    global bot_paused, pause_message
    if message.text.strip() != "افتراضي":
        pause_message = message.text.strip()
    bot_paused = True
    bot.send_message(ADMIN_ID, "🔴 تم إيقاف البوت مؤقتاً.\nأرسل /admin ثم 'إيقاف/تشغيل البوت' لإعادة التشغيل.")

def rss_add_step(message):
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(ADMIN_ID, "❌ أرسل اللغة ثم الرابط في سطرين.")
        return
    lang, url = lines[0].strip(), lines[1].strip()
    if lang not in RSS:
        RSS[lang] = []
    RSS[lang].append(url)
    save_rss()  # حفظ التغييرات
    bot.send_message(ADMIN_ID, f"✅ تم إضافة المصدر لـ {lang}")

def rss_remove_step(message):
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(ADMIN_ID, "❌ أرسل اللغة ثم رقم المصدر في سطرين.")
        return
    lang = lines[0].strip()
    try:
        index = int(lines[1].strip()) - 1
        if lang in RSS and 0 <= index < len(RSS[lang]):
            removed = RSS[lang].pop(index)
            save_rss()  # حفظ التغييرات
            bot.send_message(ADMIN_ID, f"✅ تم حذف المصدر:\n{removed}")
        else:
            bot.send_message(ADMIN_ID, "❌ رقم أو لغة غير صحيحة.")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def change_welcome_step(message):
    global welcome_override
    if message.text.strip() == "افتراضي":
        welcome_override = None
        bot.send_message(ADMIN_ID, "✅ تم الرجوع لرسالة الترحيب الافتراضية.")
    else:
        welcome_override = message.text.strip()
        bot.send_message(ADMIN_ID, "✅ تم تغيير رسالة الترحيب.")

# ======== رسالة الترحيب الأولى (للمستخدمين الجدد فقط — مرة واحدة) ========
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
    # زر تواصل inline منفصل عن لوحة الأزرار
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
    # زر Inline للتواصل المباشر
    bot.send_message(uid, "💬 تواصل معنا مباشرة:", reply_markup=inline_markup)

# ======== تلميح الاستخدام (بعد اختيار اللغة أو الدولة) ========
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
        btn["weather"], btn["news"],
        btn["all_news"], btn["mena_politics"],
        btn["currency"], btn["search"],
        notif_label, btn.get("premium", "⭐ Premium"),
        btn["settings"]
    )
    # إضافة (4): رابط التواصل في نص القائمة الرئيسية
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

# ======== بحث في الأخبار ========
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
            url_link = article.get("url", "")
            source = article.get("source", {}).get("name", "")
            if title and url_link:
                bot.send_message(uid, f"📰 *{title}*\n🔗 {url_link}\n📡 {source}", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ حدث خطأ أثناء البحث.")
        notify_admin_error(f"خطأ في البحث: {e}")

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
        types.InlineKeyboardButton("🏙 إضافة مدينة", callback_data="prem_addcity"),
        types.InlineKeyboardButton("📌 اهتماماتي", callback_data="prem_interests"),
        types.InlineKeyboardButton("💱 تنبيه العملات", callback_data="prem_currency_alert"),
        types.InlineKeyboardButton("🕐 وقت الإشعارات", callback_data="prem_notif_time"),
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

def add_extra_city(uid, city):
    users[str(uid)].setdefault("extra_cities", [])
    if city not in users[str(uid)]["extra_cities"]:
        users[str(uid)]["extra_cities"].append(city)
    save_json(USERS_FILE, users)
    bot.send_message(uid, f"✅ تمت إضافة مدينة: *{city}*", parse_mode="Markdown")

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
                    source_name = get_source_name(feed_url)
                    bot.send_message(uid, format_news_item("⚡ خبر عاجل فوري", item.title, item.link, source_name), parse_mode="Markdown")
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

# ======== /start (مصلح — لا يمسح بيانات المستخدم القديم) ========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    if uid in banned:
        bot.send_message(uid, "🚫 أنت محظور من استخدام البوت.")
        return
    if bot_paused and uid != ADMIN_ID:
        bot.send_message(uid, pause_message)
        return
    username = message.from_user.username or "لا يوجد يوزر"
    is_new = str(uid) not in users
    if is_new:
        users[str(uid)] = {"name": message.from_user.first_name, "sent_news": set(), "first_visit": True}
        save_json(USERS_FILE, users)
        update_stats("new_user", uid=uid)
        bot.send_message(ADMIN_ID, f"مستخدم جديد 👤\n\nالاسم: {message.from_user.first_name}\nاليوزر: @{username}\nID: `{uid}`", parse_mode="Markdown")
        # إضافة (6): رسالة ترحيب خاصة لأول مرة فقط
        send_first_time_welcome(uid, message.from_user.first_name)
        welcome_user(uid)
    else:
        # FIX: تحديث الاسم فقط دون مسح البيانات
        users[str(uid)]["name"] = message.from_user.first_name
        save_json(USERS_FILE, users)
        user = users[str(uid)]
        if "province" in user:
            # المستخدم مكتمل التسجيل — اعرض القائمة مباشرة
            send_main_menu(uid)
        else:
            # المستخدم لم يكمل التسجيل — أعد عرض الترحيب
            welcome_user(uid)

# ======== التعامل مع الرسائل ========
@bot.message_handler(func=lambda m: True)
def handle_selection(m):
    uid = m.from_user.id
    text = m.text
    if uid in banned:
        return
    if bot_paused and uid != ADMIN_ID:
        bot.send_message(uid, pause_message)
        return
    user = users.get(str(uid))
    if not user:
        bot.send_message(uid, "👋 الرجاء إرسال /start أولاً.")
        return
    lang = user.get("lang", "English 🇬🇧")
    btn = BUTTONS.get(lang, BUTTONS["English 🇬🇧"])

    # حالة البحث — المستخدم أرسل كلمة البحث
    if user_states.get(uid) == "searching":
        user_states.pop(uid, None)
        search_news(uid, text)
        return

    if "province" in user:
        update_stats("button", button=text)
        if text == btn["settings"]:
            # FIX: تغيير الإعدادات يعيد للترحيب دون مسح كل البيانات
            users[str(uid)] = {"name": user["name"], "sent_news": set()}
            save_json(USERS_FILE, users)
            welcome_user(uid)
        elif text == btn["weather"]:
            province = user.get("province")
            lang_code = LANG_CODES.get(lang, "en")
            url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
            try:
                data = requests.get(url, timeout=10).json()
                if data.get("cod") != 200:
                    bot.send_message(uid, f"⚠️ لم يتم العثور على بيانات الطقس لمدينة: {province}")
                else:
                    temp = data['main']['temp']
                    feels = data['main']['feels_like']
                    humidity = data['main']['humidity']
                    desc = data['weather'][0]['description']
                    wind = data['wind']['speed']
                    bot.send_message(uid,
                        f"🌤 *الطقس في {province}*\n\n"
                        f"🌡 الحرارة: *{temp}°C* (يشعر كـ {feels}°C)\n"
                        f"☁️ الحالة: {desc}\n"
                        f"💧 الرطوبة: {humidity}%\n"
                        f"💨 الرياح: {wind} م/ث",
                        parse_mode="Markdown"
                    )
            except Exception as e:
                bot.send_message(uid, "⚠️ لا يمكن جلب بيانات الطقس حالياً.")
                notify_admin_error(f"خطأ في الطقس لـ {uid}: {e}")
        elif text == btn["news"]:
            send_hourly_news(uid)
        elif text == btn["all_news"]:
            send_all_news(uid)
        elif text == btn["mena_politics"]:
            send_mena_politics(uid)
        elif text == btn["currency"]:
            send_currency(uid)
        elif text == btn["search"]:
            user_states[uid] = "searching"
            bot.send_message(uid, "🔍 اكتب كلمة البحث:")
        elif text in (btn["notif_on"], btn["notif_off"]):
            # FIX: التعامل مع كلا زري الإشعارات بشكل صحيح
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
                # إضافة (3): تلميح الاستخدام بعد اختيار اللغة
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

# ======== مساعد استخراج اسم المصدر (إضافة 5) ========
def get_source_name(feed_url):
    try:
        from urllib.parse import urlparse
        domain = urlparse(feed_url).netloc
        domain = domain.replace("www.", "").replace("feeds.", "").replace("rss.", "")
        return domain.split(".")[0].capitalize()
    except:
        return "News"

def format_news_item(prefix, title, link, source_name):
    return f"{prefix}\n\n📰 {title}\n📡 *{source_name}*\n🔗 {link}"

# ======== دوال الأخبار ========
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
            source_name = get_source_name(feed_url)
            for item in feed.entries[:3]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                bot.send_message(uid, format_news_item("🚨 خبر", item.title, item.link, source_name), parse_mode="Markdown")
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
            source_name = get_source_name(feed_url)
            for item in feed.entries[:15]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                bot.send_message(uid, format_news_item("🚨 خبر عاجل", item.title, item.link, source_name), parse_mode="Markdown")
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
    for feed_url in mena_feeds:
        try:
            feed = feedparser.parse(feed_url)
            source_name = get_source_name(feed_url)
            for item in feed.entries[:5]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                bot.send_message(uid, format_news_item("📰 أخبار الشرق الأوسط السياسية", item.title, item.link, source_name), parse_mode="Markdown")
                count += 1
        except Exception as e:
            notify_admin_error(f"خطأ في RSS MENA: {e}")
    if count == 0:
        bot.send_message(uid, "⚠️ لا توجد أخبار سياسية جديدة الآن.")
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
            # FIX: تخطي المستخدمين الذين لم يكملوا التسجيل
            continue
        lang = info.get("lang", "English 🇬🇧")
        feeds = RSS.get(lang, [])
        sent = info.setdefault("sent_news", set())
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                source_name = get_source_name(feed_url)
                for item in feed.entries[:5]:
                    if not hasattr(item, 'link') or item.link in sent:
                        continue
                    sent.add(item.link)
                    bot.send_message(uid, format_news_item("🚨 خبر عاجل", item.title, item.link, source_name), parse_mode="Markdown")
            except Exception as e:
                notify_admin_error(f"خطأ في RSS ({feed_url}): {e}")
    save_json(USERS_FILE, users)

# ======== الجدولة ========
scheduler = BackgroundScheduler()
scheduler.add_job(broadcast_weather, 'interval', hours=1)
scheduler.add_job(broadcast_news, 'interval', minutes=5)
scheduler.add_job(broadcast_premium_instant_news, 'interval', minutes=5)
scheduler.add_job(send_morning_summary, 'interval', hours=1)
scheduler.add_job(check_weather_alerts, 'interval', hours=6)
scheduler.add_job(check_currency_alerts, 'interval', hours=3)
scheduler.add_job(lambda: save_json(USERS_FILE, users), 'interval', minutes=10)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))

# ======== تشغيل البوت ========
bot.infinity_polling()
