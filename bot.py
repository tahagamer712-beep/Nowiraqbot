import telebot
from telebot import types
import requests
import feedparser
from apscheduler.schedulers.background import BackgroundScheduler

# ===== مفاتيح البوت =====
BOT_TOKEN = "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
WEATHER_KEY = "18a7801721693e772bbada4687d03e43"
NEWS_KEY = "98b2295d1a034076913e0c0e2aa64fa4"
ADMIN_ID = 5149213983

bot = telebot.TeleBot(BOT_TOKEN)

# ===== اللغات =====
languages = {
    "Arabic": {"name": "العربية 🇮🇶", "code": "ar"},
    "English": {"name": "English 🇬🇧", "code": "en"},
    "Russian": {"name": "Русский 🇷🇺", "code": "ru"},
    "Farsi": {"name": "فارسی 🇮🇷", "code": "fa"},
    "Hindi": {"name": "हिन्दी 🇮🇳", "code": "hi"},
    "Portuguese": {"name": "Português 🇧🇷", "code": "pt"},
    "Turkish": {"name": "Türkçe 🇹🇷", "code": "tr"},
    "Urdu": {"name": "اردو 🇵🇰", "code": "ur"},
    "German": {"name": "Deutsch 🇩🇪", "code": "de"},
    "Ukrainian": {"name": "Українська 🇺🇦", "code": "uk"},
    "Italian": {"name": "Italiano 🇮🇹", "code": "it"},
    "Spanish": {"name": "Español 🇲🇽", "code": "es"}
}

# ===== الدول + المحافظات (حقيقية) =====
countries = {
    "العربية 🇮🇶": {
        "العراق": ["بغداد", "البصرة", "أربيل", "الأنبار", "ديالى", "كربلاء", "كركوك", "ميسان", "النجف", "نينوى", "صلاح الدين", "واسط", "ذو القار", "ذي قار", "بابل", "الحلة"]
    },
    "English 🇬🇧": {
        "USA": ["New York", "Washington", "Los Angeles", "Chicago", "Houston"],
        "UK": ["London", "Manchester", "Liverpool", "Birmingham", "Leeds"]
    },
    "Русский 🇷🇺": {
        "Россия": ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань"]
    },
    "فارسی 🇮🇷": {
        "ایران": ["تهران", "مشهد", "اصفهان", "شیراز", "تبریز"]
    },
    "हिन्दी 🇮🇳": {
        "भारत": ["दिल्ली", "मुंबई", "बैंगलोर", "चेन्नई", "हैदराबाद"]
    },
    "Português 🇧🇷": {
        "Brasil": ["São Paulo", "Rio de Janeiro", "Brasília", "Salvador", "Fortaleza"]
    },
    "Türkçe 🇹🇷": {
        "Türkiye": ["İstanbul", "Ankara", "İzmir", "Bursa", "Adana"]
    },
    "اردو 🇵🇰": {
        "پاکستان": ["کراچی", "لاہور", "اسلام آباد", "فیصل آباد", "پشاور"]
    },
    "Deutsch 🇩🇪": {
        "Deutschland": ["Berlin", "Hamburg", "München", "Köln", "Frankfurt"]
    },
    "Українська 🇺🇦": {
        "Україна": ["Київ", "Львів", "Харків", "Одеса", "Дніпро"]
    },
    "Italiano 🇮🇹": {
        "Italia": ["Roma", "Milano", "Napoli", "Torino", "Firenze"]
    },
    "Español 🇲🇽": {
        "México": ["Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana"]
    }
}

# ===== قائمة المستخدمين =====
users = {}  # user_id : {"name":"", "lang":"", "country":"", "province":""}

# ===== RSS المصادر =====
RSS_SOURCES = {
    "العربية 🇮🇶": ["https://www.alarabiya.net/.mrss/ar/0/0/0.xml", "https://www.bbc.com/arabic/index.xml"],
    "English 🇬🇧": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "http://feeds.bbci.co.uk/news/world/rss.xml"],
    "Русский 🇷🇺": ["https://www.rbc.ru/rbcnews.rss"],
    "فارسی 🇮🇷": ["https://www.bbc.com/persian/index.xml"],
    "हिन्दी 🇮🇳": ["https://www.bbc.com/hindi/index.xml"],
    "Português 🇧🇷": ["https://g1.globo.com/rss/g1/"],
    "Türkçe 🇹🇷": ["https://www.bbc.com/turkce/index.xml"],
    "اردو 🇵🇰": ["https://www.bbc.com/urdu/index.xml"],
    "Deutsch 🇩🇪": ["https://www.bbc.com/german/index.xml"],
    "Українська 🇺🇦": ["https://www.bbc.com/ukrainian/index.xml"],
    "Italiano 🇮🇹": ["https://www.ansa.it/sito/ansait_rss.xml"],
    "Español 🇲🇽": ["https://www.bbc.com/mundo/index.xml"]
}

# ===== حفظ الأخبار المرسلة =====
sent_news = set()

# ======== دوال البث =====
def broadcast_weather():
    for uid, info in users.items():
        province = info.get("province", "Baghdad")
        user_name = info.get("name", "صديقي")
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric"
            data = requests.get(url).json()
            temp = data['main']['temp']
            bot.send_message(uid, f"{user_name}, 🌤 الطقس في {province}: {temp}°C\nWeather update for {province}: {temp}°C")
        except:
            bot.send_message(uid, f"{user_name}, ⚠️ لا يمكن جلب بيانات الطقس حالياً\n⚠️ Weather data not available.")

def broadcast_news():
    for uid, info in users.items():
        lang = info.get("lang", "English 🇬🇧")
        user_name = info.get("name", "صديقي")
        if lang in RSS_SOURCES:
            for feed in RSS_SOURCES[lang]:
                rss = feedparser.parse(feed)
                for entry in rss.entries[:5]:
                    if entry.link in sent_news:
                        continue
                    sent_news.add(entry.link)
                    bot.send_message(uid, f"🚨 خبر عاجل / Breaking News\n\n📰 {entry.title}\n{entry.link}")

# ======== الترحيب =====
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    username = message.from_user.username if message.from_user.username else "لا يوجد يوزر"
    users[uid] = {"name": message.from_user.first_name}

    # إرسال للـ Admin
    bot.send_message(ADMIN_ID, f"مستخدم جديد 👤\n\nالاسم: {message.from_user.first_name}\nاليوزر: @{username}\nID: {uid}")

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages:
        markup.add(languages[lang]["name"])

    welcome_text = (
        "🌍 *World News & Weather Bot*\n\n"
        "👋 أهلاً وسهلاً بك\n"
        "👋 Welcome!\n\n"
        "📰 آخر أخبار العالم من مصادر موثوقة / Latest world news from trusted sources\n"
        "🌤 حالة الطقس في مدينتك / Weather updates for your city\n"
        "💱 أسعار العملات مقابل الدولار / Currency exchange rates vs USD\n"
        "📢 يمكنك إضافة البوت لقناتك أو مجموعتك / Add the bot to your Telegram channel or group\n\n"
        "🌐 البوت يدعم 12 لغة حول العالم / Supports 12 languages worldwide\n\n"
        "👇 اختر لغتك للمتابعة / Choose your language to continue"
    )
    bot.send_message(uid, welcome_text, parse_mode="Markdown", reply_markup=markup)

# ======== اختيار اللغة والدولة والمحافظة =====
@bot.message_handler(func=lambda m: True)
def handle_selection(m):
    uid = m.from_user.id
    text = m.text
    user_name = users[uid]["name"]

    if "lang" not in users[uid]:
        for key, val in languages.items():
            if text == val["name"]:
                users[uid]["lang"] = val["name"]
                bot.send_message(ADMIN_ID, f"{user_name} ({uid}) اختار اللغة: {text}")
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[val["name"]]:
                    markup.add(country)
                bot.send_message(uid, "اختر دولتك / Choose your country:", reply_markup=markup)
                return

    elif "country" not in users[uid]:
        lang = users[uid]["lang"]
        if text in countries[lang]:
            users[uid]["country"] = text
            bot.send_message(ADMIN_ID, f"{user_name} ({uid}) اختار الدولة: {text}")
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            for province in countries[lang][text]:
                markup.add(province)
            bot.send_message(uid, "اختر محافظتك / Choose your province:", reply_markup=markup)
            return

    elif "province" not in users[uid]:
        users[uid]["province"] = text
        bot.send_message(uid, "تم حفظ اختياراتك ✅\nستصلك الأخبار والطقس تلقائيًا كل ساعة.\nSaved successfully! ✅")
        bot.send_message(ADMIN_ID, f"{user_name} ({uid}) اختار المحافظة: {text}")
        return

# ======== إحصائيات =====
@bot.message_handler(commands=['stats'])
def stats(message):
    if message.from_user.id != ADMIN_ID:
        return
    total_users = len(users)
    bot.send_message(ADMIN_ID, f"📊 إحصائيات البوت\nعدد المستخدمين: {total_users}")

# ======== Scheduler لتشغيل كل ساعة =====
scheduler = BackgroundScheduler()
scheduler.add_job(broadcast_weather, 'interval', hours=1)
scheduler.add_job(broadcast_news, 'interval', hours=1)
scheduler.start()

# ======== تشغيل البوت =====
bot.polling(none_stop=True)
