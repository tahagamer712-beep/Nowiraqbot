import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import schedule
import time
import threading
import feedparser

# ====== إعدادات البوت ======
TOKEN = "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
bot = telebot.TeleBot(TOKEN)

# ====== مفاتيح API ======
WEATHER_KEY = "18a7801721693e772bbada4687d03e43"
AQI_KEY = "dd90e9d65caffb048e68b9d48d6b9aeab31c00d3"

# ====== الدول والمحافظات حسب اللغات ======
COUNTRIES_PROVINCES = {
    "Iraq": ["Baghdad", "Basra", "Erbil", "Sulaymaniyah", "Mosul", "Najaf", "Kirkuk"],
    "USA": ["California", "New York", "Texas", "Florida"],
    "Spain": ["Madrid", "Barcelona", "Valencia", "Seville"],
    "France": ["Paris", "Lyon", "Marseille", "Nice"],
    "Germany": ["Berlin", "Munich", "Hamburg", "Frankfurt"]
}

# ====== اللغات ======
LANGUAGES = {
    "ar": "🇮🇶 العربية",
    "en": "🇺🇸 English",
    "es": "🇪🇸 Español",
    "fr": "🇫🇷 Français",
    "de": "🇩🇪 Deutsch"
}

# ====== بيانات المستخدم ======
user_data = {}  # chat_id: {lang, country, province}

# ====== قنوات ومجموعات البث ======
broadcast_targets = [
    "@MyChannel",  # ضع اسم القناة أو المجموعة
    "@MyGroup"
]

# ====== RSS لكل لغة ======
rss_urls = {
    "ar": [
        "https://www.bbc.com/arabic/index.xml",
        "https://www.aljazeera.net/aljazeerarss"
    ],
    "en": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "http://rss.cnn.com/rss/edition_world.rss",
        "http://feeds.reuters.com/reuters/worldNews",
        "https://www.aljazeera.com/xml/rss/all.xml"
    ],
    "es": [
        "https://feeds.bbcmundo.com/rss",
        "https://elpais.com/rss/elpais/internacional.xml",
        "https://www.aljazeera.com/xml/rss/spanish.xml"
    ],
    "fr": [
        "https://www.france24.com/fr/rss",
        "https://www.lemonde.fr/rss/une.xml",
        "https://www.aljazeera.com/xml/rss/french.xml"
    ],
    "de": [
        "https://rss.dw.com/rdf/rss-de-all",
        "https://www.aljazeera.com/xml/rss/german.xml"
    ]
}

# ====== رسالة الترحيب ======
def welcome_message(user_name):
    return f"""
👋 أهلاً بك {user_name} في البوت الرسمي!

هذا البوت يرسل لك:
- 🌤 الطقس
- 💰 أسعار العملات والذهب والفضة
- ⚽ المباريات وترتيب الفرق
- 📰 الأخبار العاجلة فور نزولها
- 🌫 جودة الهواء

🌐 أولاً: اختر لغتك ثم الدولة والمحافظة لتصلك المعلومات المخصصة.

🤝 يمكنك إضافة البوت إلى قناتك أو مجموعتك كأدمن ليقوم بالنشر تلقائيًا ومجانًا.

💬 للتواصل معنا: [اضغط هنا](https://t.me/Ilovedaddyandmommybot)
"""

# ====== أوامر البوت ======
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_data[chat_id] = {}
    bot.send_message(chat_id, welcome_message(message.from_user.first_name), parse_mode="Markdown")
    
    # اختيار اللغة
    keyboard = InlineKeyboardMarkup(row_width=3)
    buttons = [InlineKeyboardButton(name, callback_data=f"lang_{code}") for code, name in LANGUAGES.items()]
    keyboard.add(*buttons)
    bot.send_message(chat_id, "اختر لغتك / Choose your language:", reply_markup=keyboard)

# ====== التعامل مع الأزرار ======
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    data = call.data
    
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        user_data[chat_id]["lang"] = lang
        # عرض الدول
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = [InlineKeyboardButton(country, callback_data=f"country_{country}") for country in COUNTRIES_PROVINCES.keys()]
        keyboard.add(*buttons)
        bot.send_message(chat_id, "اختر الدولة / Choose your country:", reply_markup=keyboard)
    
    elif data.startswith("country_"):
        country = data.split("_")[1]
        user_data[chat_id]["country"] = country
        # عرض المحافظات
        keyboard = InlineKeyboardMarkup(row_width=2)
        provinces = COUNTRIES_PROVINCES[country]
        buttons = [InlineKeyboardButton(prov, callback_data=f"province_{prov}") for prov in provinces]
        keyboard.add(*buttons)
        bot.send_message(chat_id, "اختر المحافظة / Choose your province:", reply_markup=keyboard)
    
    elif data.startswith("province_"):
        province = data.split("_")[1]
        user_data[chat_id]["province"] = province
        bot.send_message(chat_id, f"تم اختيار: {province}\nجميع السكشنات ستصل لك تلقائياً! ✅")

# ====== وظائف البث التلقائي ======
def broadcast(message):
    # للمستخدمين
    for chat_id in user_data:
        bot.send_message(chat_id, message)
    # للقنوات والمجموعات
    for target in broadcast_targets:
        bot.send_message(target, message)

def send_weather():
    for chat_id, info in user_data.items():
        province = info.get("province")
        if province:
            weather_msg = f"🌤 الطقس في {province}: درجة الحرارة: 30°C، الرطوبة: 50%"
            bot.send_message(chat_id, weather_msg)
            for target in broadcast_targets:
                bot.send_message(target, weather_msg)

def send_news():
    for lang, urls in rss_urls.items():
        for url in urls:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:  # 10–20 خبر/ساعة
                for chat_id in user_data:
                    if user_data[chat_id].get("lang") == lang:
                        bot.send_message(chat_id, f"📰 {entry.title}")
                        for target in broadcast_targets:
                            bot.send_message(target, f"📰 {entry.title}")

# ====== جدولة البث ======
schedule.every().hour.do(send_weather)
schedule.every().hour.do(send_news)

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=run_schedule).start()
bot.polling(none_stop=True)
