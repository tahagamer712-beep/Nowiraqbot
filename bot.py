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
AQI_KEY = "dd90e9d65caffb048e68b9d48d6b9aeab31c00d3"

bot = telebot.TeleBot(BOT_TOKEN)

# ======== اللغات ========
languages = {
    "Arabic": {"name": "العربية 🇮🇶", "code": "ar"},
    "English": {"name": "English 🇬🇧", "code": "en"},
    "Russian": {"name": "Русский 🇷🇺", "code": "ru"},
    # أضف باقي اللغات هنا
}

# ======== الدول + المحافظات (مثال) ========
countries = {
    "العربية 🇮🇶": {
        "العراق": ["بغداد", "البصرة", "أربيل", "البقية..."],
    },
    "English 🇬🇧": {
        "Iraq": ["Baghdad", "Basra", "Erbil", "Others..."],
    },
    "Русский 🇷🇺": {
        "Россия": ["Москва", "Санкт-Петербург", "Others..."],
    }
    # أضف باقي الدول واللغات هنا
}

# ======== قائمة المستخدمين وحفظ اختياراتهم ========
users = {}  # user_id : {"lang": "", "country": "", "province": ""}

# ======== أوامر البوت ========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    users[user_id] = {}
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages:
        markup.add(languages[lang]["name"])
    bot.send_message(user_id, "اختر لغتك / Choose your language:", reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_selection(message):
    user_id = message.from_user.id
    text = message.text

    # 1️⃣ اختيار اللغة
    if "lang" not in users[user_id]:
        for key, val in languages.items():
            if text == val["name"]:
                users[user_id]["lang"] = val["name"]
                # بعد اختيار اللغة، نعرض الدول حسب اللغة
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[val["name"]]:
                    markup.add(country)
                bot.send_message(user_id, "اختر دولتك / Choose your country:", reply_markup=markup)
                return

    # 2️⃣ اختيار الدولة
    elif "country" not in users[user_id]:
        lang = users[user_id]["lang"]
        if text in countries[lang]:
            users[user_id]["country"] = text
            # بعد اختيار الدولة، نعرض المحافظات حسب اللغة
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            for province in countries[lang][text]:
                markup.add(province)
            bot.send_message(user_id, "اختر محافظتك / Choose your province:", reply_markup=markup)
            return

    # 3️⃣ اختيار المحافظة
    elif "province" not in users[user_id]:
        users[user_id]["province"] = text
        bot.send_message(user_id, "تم حفظ اختياراتك ✅\nستصلك جميع الأخبار، الطقس، العملات، جودة الهواء تلقائيًا كل ساعة.")
        bot.send_message(user_id, "للتواصل: [@Ilovedaddyandmommybot](https://t.me/Ilovedaddyandmommybot)", parse_mode="Markdown")
        # بعد الاختيار، نبدأ البث التلقائي للمستخدم
        # send_initial_data(user_id)  # هنا يمكن استدعاء دالة البث الأولي
        return

# ======== مثال دالة البث التلقائي ========
def broadcast_weather():
    for user_id, info in users.items():
        province = info.get("province", "Baghdad")  # افتراضي
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric"
        data = requests.get(url).json()
        temp = data['main']['temp']
        bot.send_message(user_id, f"🌤 الطقس في {province}: {temp}°C")

# ======== مثال دالة بث الأخبار ========
RSS_SOURCES = {
    "Arabic 🇮🇶": ["https://www.alarabiya.net/.mrss/ar/0/0/0.xml"],
    "English 🇬🇧": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],
    # أضف باقي المصادر
}

def broadcast_news():
    for user_id, info in users.items():
        lang = info.get("lang")
        if lang in RSS_SOURCES:
            for feed in RSS_SOURCES[lang]:
                rss = feedparser.parse(feed)
                for entry in rss.entries[:10]:  # 10 أخبار كحد أقصى
                    bot.send_message(user_id, f"📰 {entry.title}\n{entry.link}")

# ======== ضبط كل ساعة ========
schedule.every().hour.do(broadcast_weather)
schedule.every().hour.do(broadcast_news)

# ======== تشغيل البوت ========
while True:
    try:
        schedule.run_pending()
        time.sleep(60)
    except Exception as e:
        print("Error:", e)
