import telebot
from telebot import types
import schedule
import time
import requests
import feedparser

# ======== مفاتيح البوت ========
BOT_TOKEN = "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
WEATHER_KEY = "18a7801721693e772bbada4687d03e43"
NEWS_KEY = "98b2295d1a034076913e0c0e2aa64fa4"

ADMIN_ID = 5149213983  # الاي دي مالك

bot = telebot.TeleBot(BOT_TOKEN)

# ======== اللغات ========
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

# ======== الدول + المحافظات ========
countries = {
    "العربية 🇮🇶": {"العراق": ["بغداد", "البصرة", "أربيل", "الموصل", "النجف", "كربلاء", "ديالى", "ذي قار", "ميسان", "القادسية", "صلاح الدين", "كركوك", "السليمانية", "دهوك", "واسط", "الأنبار", "بابل", "الحلة", "دهوك"]},
    "English 🇬🇧": {"USA": ["New York", "Washington", "Los Angeles", "Chicago"], "UK": ["London", "Manchester", "Birmingham"]},
    "Русский 🇷🇺": {"Россия": ["Москва", "Санкт-Петербург", "Новосибирск"]},
    "فارسی 🇮🇷": {"ایران": ["تهران", "مشهد", "اصفهان"]},
    "हिन्दी 🇮🇳": {"भारत": ["दिल्ली", "मुंबई", "बेंगलुरु"]},
    "Português 🇧🇷": {"Brasil": ["São Paulo", "Rio de Janeiro", "Brasília"]},
    "Türkçe 🇹🇷": {"Türkiye": ["İstanbul", "Ankara", "İzmir"]},
    "اردو 🇵🇰": {"پاکستان": ["کراچی", "لاہور", "اسلام آباد"]},
    "Deutsch 🇩🇪": {"Deutschland": ["Berlin", "Munich", "Hamburg"]},
    "Українська 🇺🇦": {"Україна": ["Київ", "Львів", "Одеса"]},
    "Italiano 🇮🇹": {"Italia": ["Roma", "Milano", "Napoli"]},
    "Español 🇲🇽": {"México": ["Ciudad de México", "Guadalajara", "Monterrey"]}
}

# ======== المستخدمين ========
users = {}  # user_id : {"name":"", "lang": "", "country": "", "province": ""}

# ======== الأخبار المرسلة لتجنب التكرار ========
sent_news = set()

# ======== RSS المصادر ========
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
def send_welcome(uid):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages:
        markup.add(languages[lang]["name"])

    username = users[uid]["name"] if "name" in users[uid] else "صديق"
    welcome_text = (
        f"🌍 *World News & Weather Bot*\n\n"
        f"👋 أهلاً وسهلاً بك {username}\n"
        f"👋 Welcome!\n\n"
        f"📰 آخر أخبار العالم من مصادر موثوقة\n"
        f"📰 Latest world news from trusted sources\n\n"
        f"🌤 حالة الطقس في مدينتك\n"
        f"🌤 Weather updates for your city\n\n"
        f"💱 أسعار العملات مقابل الدولار\n"
        f"💱 Currency exchange rates vs USD\n\n"
        f"📢 يمكنك أيضاً إضافة البوت إلى قناتك أو مجموعتك في تلغرام\n"
        f"📢 You can also add the bot to your Telegram channel or group\n"
        f"وسيتم نشر الأخبار تلقائياً.\n"
        f"And it will automatically publish news.\n\n"
        f"🌐 البوت يدعم 12 لغة حول العالم\n"
        f"🌐 The bot supports 12 languages worldwide\n\n"
        f"👇 اختر لغتك للمتابعة\n"
        f"👇 Choose your language to continue"
    )
    bot.send_message(uid, welcome_text, parse_mode="Markdown", reply_markup=markup)

# ======== أوامر البوت ========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    users[uid] = {"name": message.from_user.first_name}

    # إرسال بيانات المستخدم للـ Admin
    username = message.from_user.username if message.from_user.username else "لا يوجد يوزر"
    bot.send_message(
        ADMIN_ID,
        f"مستخدم جديد 👤\n\n"
        f"الاسم: {message.from_user.first_name}\n"
        f"اليوزر: @{username}\n"
        f"ID: {uid}"
    )

    send_welcome(uid)

# ======== اختيار اللغة والدولة والمحافظة ========
@bot.message_handler(func=lambda m: True)
def handle_selection(m):
    uid = m.from_user.id
    text = m.text

    if "lang" not in users[uid]:
        for lang in languages:
            if text == languages[lang]["name"]:
                users[uid]["lang"] = languages[lang]["name"]
                bot.send_message(ADMIN_ID, f"المستخدم {users[uid]['name']} ({uid}) اختار اللغة: {text}")
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[languages[lang]["name"]]:
                    markup.add(country)
                bot.send_message(uid, "اختر دولتك / Choose your country:", reply_markup=markup)
                return

    elif "country" not in users[uid]:
        lang = users[uid]["lang"]
        if text in countries[lang]:
            users[uid]["country"] = text
            bot.send_message(ADMIN_ID, f"المستخدم {users[uid]['name']} ({uid}) اختار الدولة: {text}")
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            for province in countries[lang][text]:
                markup.add(province)
            bot.send_message(uid, "اختر محافظتك / Choose your province:", reply_markup=markup)
            return

    elif "province" not in users[uid]:
        users[uid]["province"] = text
        bot.send_message(uid, "تم حفظ اختياراتك ✅\nستصلك جميع الأخبار، الطقس، العملات تلقائيًا كل ساعة.")
        bot.send_message(ADMIN_ID, f"المستخدم {users[uid]['name']} ({uid}) اختار المحافظة: {text}")
        return

# ======== دوال البث ========
def broadcast_weather():
    for uid, info in users.items():
        province = info.get("province", "Baghdad")
        user_name = info.get("name", "صديقي")
        try:
            data = requests.get(f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric").json()
            temp = data['main']['temp']
            bot.send_message(uid, f"{user_name}, 🌤 الطقس في {province}: {temp}°C")
        except:
            bot.send_message(uid, f"{user_name}, ⚠️ لا يمكن جلب بيانات الطقس حالياً.")

def broadcast_news():
    for uid, info in users.items():
        lang = info.get("lang")
        user_name = info.get("name", "صديقي")
        if lang not in RSS:
            continue
        for feed in RSS[lang]:
            rss = feedparser.parse(feed)
            for entry in rss.entries[:5]:
                if entry.link in sent_news:
                    continue
                sent_news.add(entry.link)
                bot.send_message(uid, f"🚨 خبر عاجل\n\n📰 {entry.title}\n{entry.link}")

# ======== جدولة كل ساعة ========
schedule.every().hour.do(broadcast_weather)
schedule.every().hour.do(broadcast_news)

# ======== تشغيل البوت ========
while True:
    try:
        schedule.run_pending()
        time.sleep(60)
    except Exception as e:
        print("Error:", e)
