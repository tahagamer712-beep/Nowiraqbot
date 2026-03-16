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

# الاي دي مالك لتصلك معلومات المستخدم
ADMIN_ID = 5149213983

bot = telebot.TeleBot(BOT_TOKEN)

# ======== اللغات ========
languages = {
    "Arabic": {"name": "العربية 🇮🇶", "code": "ar"},
    "English": {"name": "English 🇬🇧", "code": "en"},
    "Russian": {"name": "Русский 🇷🇺", "code": "ru"},
    # أضف باقي اللغات هنا
}

# ======== الدول + المحافظات ========
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
users = {}  # user_id : {"name":"", "lang": "", "country": "", "province": ""}

# ======== RSS المصادر ========
RSS_SOURCES = {
    "العربية 🇮🇶": ["https://www.alarabiya.net/.mrss/ar/0/0/0.xml"],
    "English 🇬🇧": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],
    "Русский 🇷🇺": ["https://www.rbc.ru/rbcnews.rss"],
    # أضف باقي المصادر
}

# ======== أوامر البوت ========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    users[user_id] = {"name": message.from_user.first_name}
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages:
        markup.add(languages[lang]["name"])
    bot.send_message(user_id, 
                     "أهلاً! 👋\nاختر لغتك / Choose your language:\n\n"
                     "بعد اختيار اللغة ستتمكن من اختيار الدولة والمحافظة لتصلك الأخبار، الطقس، العملات، جودة الهواء تلقائيًا.", 
                     reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_selection(message):
    user_id = message.from_user.id
    text = message.text
    user_name = users[user_id]["name"]

    # 1️⃣ اختيار اللغة
    if "lang" not in users[user_id]:
        for key, val in languages.items():
            if text == val["name"]:
                users[user_id]["lang"] = val["name"]
                # إرسال رسالة لك عن اختيار المستخدم
                bot.send_message(ADMIN_ID, f"المستخدم {user_name} ({user_id}) اختار اللغة: {text}")
                # عرض الدول حسب اللغة
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
            bot.send_message(ADMIN_ID, f"المستخدم {user_name} ({user_id}) اختار الدولة: {text}")
            # عرض المحافظات حسب اللغة
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
        bot.send_message(ADMIN_ID, f"المستخدم {user_name} ({user_id}) اختار المحافظة: {text}")
        return

# ======== دوال البث التلقائي ========
def broadcast_weather():
    for user_id, info in users.items():
        province = info.get("province", "Baghdad")
        user_name = info.get("name", "صديقي")
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric"
        try:
            data = requests.get(url).json()
            temp = data['main']['temp']
            bot.send_message(user_id, f"{user_name}, 🌤 الطقس في {province}: {temp}°C")
        except:
            bot.send_message(user_id, f"{user_name}, ⚠️ لا يمكن جلب بيانات الطقس حالياً.")

def broadcast_news():
    for user_id, info in users.items():
        lang = info.get("lang", "English 🇬🇧")
        user_name = info.get("name", "صديقي")
        if lang in RSS_SOURCES:
            for feed in RSS_SOURCES[lang]:
                rss = feedparser.parse(feed)
                for entry in rss.entries[:10]:
                    bot.send_message(user_id, f"{user_name}, 📰 {entry.title}\n{entry.link}")

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
