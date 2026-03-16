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
    "العربية 🇮🇶": {"العراق": ["بغداد","البصرة","أربيل","الموصل","كربلاء","النجف","السليمانية","دهوك","ميسان","ذي قار","ديالى","الحلة","كركوك","واسط","المثنى","صلاح الدين","بابل","القادسية"]},
    "English 🇬🇧": {"USA": ["New York","Washington","Los Angeles","Chicago"], "UK": ["London","Manchester","Birmingham"]},
    "Русский 🇷🇺": {"Россия": ["Москва","Санкт-Петербург","Новосибирск","Екатеринбург"]},
    "فارسی 🇮🇷": {"ایران": ["تهران","مشهد","اصفهان","شیراز"]},
    "हिन्दी 🇮🇳": {"भारत": ["दिल्ली","मुंबई","बंगलोर","चेन्नई"]},
    "Português 🇧🇷": {"Brasil": ["São Paulo","Rio de Janeiro","Brasília","Salvador"]},
    "Türkçe 🇹🇷": {"Türkiye": ["İstanbul","Ankara","İzmir","Bursa"]},
    "اردو 🇵🇰": {"پاکستان": ["کراچی","لاہور","اسلام آباد","فیصل آباد"]},
    "Deutsch 🇩🇪": {"Deutschland": ["Berlin","Munich","Hamburg","Frankfurt"]},
    "Українська 🇺🇦": {"Україна": ["Київ","Львів","Одеса","Харків"]},
    "Italiano 🇮🇹": {"Italia": ["Roma","Milano","Napoli","Torino"]},
    "Español 🇲🇽": {"México": ["Ciudad de México","Guadalajara","Monterrey","Puebla"]}
}

# ======== قائمة المستخدمين ========
users = {}  # user_id : {"name":"", "lang": "", "country": "", "province": ""}
sent_news = set()  # حفظ الأخبار المرسلة

# ======== RSS المصادر ========
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

# ======== أوامر البوت ========
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    username = m.from_user.username if m.from_user.username else "لا يوجد يوزر"
    users[uid] = {"name": m.from_user.first_name}
    
    # إرسال بيانات المستخدم للادمن
    bot.send_message(
        ADMIN_ID,
        f"مستخدم جديد 👤\n\n"
        f"الاسم: {m.from_user.first_name}\n"
        f"اليوزر: @{username}\n"
        f"ID: {uid}"
    )
    
    # إنشاء أزرار اللغات
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages:
        markup.add(languages[lang]["name"])
    
    # رسالة الترحيب
    welcome_text = (
        "🌍 *World News & Weather Bot*\n\n"
        "👋 أهلاً وسهلاً بك\n"
        "👋 Welcome!\n\n"
        "هذا البوت يوفر لك معلومات مهمة بشكل تلقائي:\n"
        "This bot automatically provides useful information:\n\n"
        "📰 آخر أخبار العالم من مصادر موثوقة\n"
        "📰 Latest world news from trusted sources\n\n"
        "🌤 حالة الطقس في مدينتك\n"
        "🌤 Weather updates for your city\n\n"
        "💱 أسعار العملات مقابل الدولار\n"
        "💱 Currency exchange rates vs USD\n\n"
        "📢 يمكنك أيضاً إضافة البوت إلى قناتك أو مجموعتك في تلغرام\n"
        "📢 You can also add the bot to your Telegram channel or group\n"
        "وسيتم نشر الأخبار تلقائياً.\n"
        "And it will automatically publish news.\n\n"
        "🌐 البوت يدعم 12 لغة حول العالم\n"
        "🌐 The bot supports 12 languages worldwide\n\n"
        "👇 اختر لغتك للمتابعة\n"
        "👇 Choose your language to continue"
    )
    
    bot.send_message(uid, welcome_text, parse_mode="Markdown", reply_markup=markup)


@bot.message_handler(func=lambda m: True)
def handle_selection(m):
    uid = m.from_user.id
    text = m.text
    name = users[uid]["name"]
    
    # اختيار اللغة
    if "lang" not in users[uid]:
        for key,val in languages.items():
            if text == val["name"]:
                users[uid]["lang"] = val["name"]
                bot.send_message(ADMIN_ID, f"المستخدم {name} ({uid}) اختار اللغة: {text}")
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[val["name"]]:
                    markup.add(country)
                bot.send_message(uid, "اختر دولتك / Choose your country:", reply_markup=markup)
                return
    
    # اختيار الدولة
    elif "country" not in users[uid]:
        lang = users[uid]["lang"]
        if text in countries[lang]:
            users[uid]["country"] = text
            bot.send_message(ADMIN_ID, f"المستخدم {name} ({uid}) اختار الدولة: {text}")
            markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            for province in countries[lang][text]:
                markup.add(province)
            bot.send_message(uid, "اختر محافظتك / Choose your province:", reply_markup=markup)
            return
    
    # اختيار المحافظة
    elif "province" not in users[uid]:
        users[uid]["province"] = text
        bot.send_message(uid, "تم حفظ اختياراتك ✅\nستصلك جميع الأخبار والطقس تلقائيًا كل ساعة.")
        bot.send_message(ADMIN_ID, f"المستخدم {name} ({uid}) اختار المحافظة: {text}")
        return

# ======== دوال البث التلقائي ========
def broadcast_weather():
    for uid, info in users.items():
        province = info.get("province", "Baghdad")
        name = info.get("name", "صديقي")
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric"
        try:
            data = requests.get(url).json()
            temp = data['main']['temp']
            bot.send_message(uid, f"{name}, 🌤 الطقس في {province}: {temp}°C")
        except:
            bot.send_message(uid, f"{name}, ⚠️ لا يمكن جلب بيانات الطقس حالياً.")

def broadcast_news():
    for uid, info in users.items():
        lang = info.get("lang")
        name = info.get("name", "صديقي")
        if lang not in RSS_SOURCES:
            continue
        for feed in RSS_SOURCES[lang]:
            try:
                rss = feedparser.parse(feed)
                for entry in rss.entries[:10]:
                    if entry.link in sent_news:
                        continue
                    sent_news.add(entry.link)
                    bot.send_message(uid, f"{name}, 📰 {entry.title}\n{entry.link}")
            except:
                continue

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
