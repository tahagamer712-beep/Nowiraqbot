import telebot
from telebot import types
import requests
import feedparser
import atexit
from apscheduler.schedulers.background import BackgroundScheduler

# ======== مفاتيح البوت ========
BOT_TOKEN = "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
WEATHER_KEY = "18a7801721693e772bbada4687d03e43"
NEWS_KEY = "98b2295d1a034076913e0c0e2aa64fa4"
ADMIN_ID = 5149213983

bot = telebot.TeleBot(BOT_TOKEN)

# ======== المستخدمين ========
users = {}  # user_id : {"name":"", "lang":"", "country":"", "province":"", "sent_news": set()}

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

# ======== الدول + المحافظات ========
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
        "ایران": ["تهران", "مشهد", "اصفهان", "شیراز", "تبریز"]
    },
    "हिन्दी 🇮🇳": {
        "भारत": ["दिल्ली", "मुंबई", "बेंगलुरु", "चेन्नई", "कोलकाता"]
    },
    "Português 🇧🇷": {
        "Brasil": ["São Paulo", "Rio de Janeiro", "Brasília", "Salvador", "Fortaleza"]
    },
    "Türkçe 🇹🇷": {
        "Türkiye": ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya"]
    },
    "اردو 🇵🇰": {
        "پاکستان": ["کراچی", "لاہور", "اسلام آباد", "پشاور", "کوئٹہ"]
    },
    "Deutsch 🇩🇪": {
        "Deutschland": ["Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne"]
    },
    "Українська 🇺🇦": {
        "Україна": ["Київ", "Львів", "Харків", "Одеса", "Дніпро"]
    },
    "Italiano 🇮🇹": {
        "Italia": ["Roma", "Milano", "Napoli", "Torino", "Palermo"]
    },
    "Español 🇲🇽": {
        "México": ["Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana"]
    }
}

# ======== RSS الأخبار ========
RSS = {
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

# ======== رسالة الترحيب ========
def welcome_user(uid):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages.values():
        markup.add(lang)
    welcome_text = (
        "🌍 *World News & Weather Bot*\n\n"
        "👋 أهلاً وسهلاً بك\n"
        "👋 Welcome!\n\n"
        "📰 آخر أخبار العالم من مصادر موثوقة\n"
        "📰 Latest world news from trusted sources\n\n"
        "🌤 حالة الطقس في مدينتك\n"
        "🌤 Weather updates for your city\n\n"
        "💱 أسعار العملات مقابل الدولار\n"
        "💱 Currency exchange rates vs USD\n\n"
        "📢 يمكنك أيضاً إضافة البوت إلى قناتك أو مجموعتك\n"
        "📢 You can also add the bot to your Telegram channel or group\n\n"
        "🌐 البوت يدعم 12 لغة حول العالم\n"
        "🌐 The bot supports 12 languages worldwide\n\n"
        "👇 اختر لغتك للمتابعة\n"
        "👇 Choose your language to continue"
    )
    bot.send_message(uid, welcome_text, parse_mode="Markdown", reply_markup=markup)

# ======== القائمة الرئيسية بعد اكتمال الإعداد ========
def send_main_menu(uid):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("🌤 الطقس الآن", "📰 آخر الأخبار", "🔄 تغيير الإعدادات")
    bot.send_message(uid, "✅ اختر ما تريد:", reply_markup=markup)

# ======== بدء البوت ========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    username = message.from_user.username if message.from_user.username else "لا يوجد يوزر"
    users[uid] = {"name": message.from_user.first_name, "sent_news": set()}
    bot.send_message(ADMIN_ID, f"مستخدم جديد 👤\n\nالاسم: {message.from_user.first_name}\nاليوزر: @{username}\nID: {uid}")
    welcome_user(uid)

# ======== اختيار اللغة والدولة والمحافظة ========
@bot.message_handler(func=lambda m: True)
def handle_selection(m):
    uid = m.from_user.id
    text = m.text

    if uid not in users:
        bot.send_message(uid, "👋 الرجاء إرسال /start أولاً.")
        return

    user_name = users[uid]["name"]

    # ======== بعد اكتمال الإعداد ========
    if "province" in users[uid]:
        if text == "🔄 تغيير الإعدادات":
            users[uid] = {"name": user_name, "sent_news": set()}
            welcome_user(uid)
        elif text == "🌤 الطقس الآن":
            province = users[uid].get("province")
            url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang=ar"
            try:
                data = requests.get(url, timeout=10).json()
                if data.get("cod") != 200:
                    bot.send_message(uid, f"⚠️ لم يتم العثور على بيانات الطقس لمدينة: {province}")
                else:
                    temp = data['main']['temp']
                    desc = data['weather'][0]['description']
                    bot.send_message(uid, f"🌤 الطقس في {province}:\n🌡 {temp}°C\n☁️ {desc}")
            except Exception:
                bot.send_message(uid, "⚠️ لا يمكن جلب بيانات الطقس حالياً.")
        elif text == "📰 آخر الأخبار":
            lang = users[uid].get("lang", "English 🇬🇧")
            if lang not in RSS:
                bot.send_message(uid, "⚠️ لا توجد أخبار متاحة للغتك حالياً.")
                return
            sent = False
            for feed_url in RSS[lang]:
                try:
                    feed = feedparser.parse(feed_url)
                    for item in feed.entries[:3]:
                        bot.send_message(uid, f"🚨 خبر\n\n📰 {item.title}\n{item.link}")
                        sent = True
                except Exception:
                    continue
            if not sent:
                bot.send_message(uid, "⚠️ لا يمكن جلب الأخبار حالياً.")
        else:
            send_main_menu(uid)
        return

    # ======== اختيار اللغة ========
    if "lang" not in users[uid]:
        for key, val in languages.items():
            if text == val:
                users[uid]["lang"] = val
                bot.send_message(ADMIN_ID, f"{user_name} ({uid}) اختار اللغة: {text}")
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[val]:
                    markup.add(country)
                bot.send_message(uid, "اختر دولتك / Choose your country:", reply_markup=markup)
                return
        bot.send_message(uid, "👇 الرجاء اختيار لغة من القائمة.")

    # ======== اختيار الدولة ========
    elif "country" not in users[uid]:
        lang = users[uid]["lang"]
        if text in countries[lang]:
            users[uid]["country"] = text
            bot.send_message(ADMIN_ID, f"{user_name} ({uid}) اختار الدولة: {text}")
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            for prov in countries[lang][text]:
                markup.add(prov)
            bot.send_message(uid, "اختر محافظتك / Choose your province:", reply_markup=markup)
        else:
            bot.send_message(uid, "👇 الرجاء اختيار دولة من القائمة.")

    # ======== اختيار المحافظة ========
    elif "province" not in users[uid]:
        lang = users[uid]["lang"]
        country = users[uid]["country"]
        valid_provinces = countries[lang][country]
        if text in valid_provinces:
            users[uid]["province"] = text
            bot.send_message(uid, "تم حفظ اختياراتك ✅\nستصلك الأخبار والطقس تلقائيًا كل ساعة.")
            bot.send_message(ADMIN_ID, f"{user_name} ({uid}) اختار المحافظة: {text}")
            send_main_menu(uid)
        else:
            bot.send_message(uid, "👇 الرجاء اختيار محافظة من القائمة.")

# ======== البث التلقائي — الطقس ========
def broadcast_weather():
    for uid, info in list(users.items()):
        province = info.get("province")
        if not province:
            continue
        name = info.get("name", "صديقي")
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang=ar"
        try:
            data = requests.get(url, timeout=10).json()
            if data.get("cod") != 200:
                bot.send_message(uid, f"{name}, ⚠️ لم يتم العثور على بيانات الطقس لمدينة: {province}")
            else:
                temp = data['main']['temp']
                desc = data['weather'][0]['description']
                bot.send_message(uid, f"{name}, 🌤 الطقس في {province}: {temp}°C\n☁️ {desc}")
        except Exception:
            bot.send_message(uid, f"{name}, ⚠️ لا يمكن جلب بيانات الطقس حالياً.")

# ======== البث التلقائي — الأخبار ========
def broadcast_news():
    for uid, info in list(users.items()):
        if "province" not in info:
            continue
        lang = info.get("lang", "English 🇬🇧")
        if lang not in RSS:
            continue
        user_sent = info.setdefault("sent_news", set())
        for feed_url in RSS[lang]:
            try:
                feed = feedparser.parse(feed_url)
                for item in feed.entries[:5]:
                    if not hasattr(item, 'link') or not hasattr(item, 'title'):
                        continue
                    if item.link in user_sent:
                        continue
                    user_sent.add(item.link)
                    bot.send_message(uid, f"🚨 خبر عاجل\n\n📰 {item.title}\n{item.link}")
            except Exception:
                continue

# ======== الجدولة ========
scheduler = BackgroundScheduler()
scheduler.add_job(broadcast_weather, 'interval', hours=1)
scheduler.add_job(broadcast_news, 'interval', hours=1)
scheduler.start()

# ======== إيقاف الـ scheduler عند انتهاء البوت ========
atexit.register(lambda: scheduler.shutdown(wait=False))

# ======== تشغيل البوت ========
bot.infinity_polling()
