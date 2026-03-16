import telebot
from telebot import types
import requests
import feedparser
import json
import schedule
import time
import threading

BOT_TOKEN="8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
WEATHER_KEY="18a7801721693e772bbada4687d03e43"
ADMIN_ID=5149213983

bot=telebot.TeleBot(BOT_TOKEN)

try:
    with open("users.json","r") as f:
        users=json.load(f)
except:
    users={}

def save_users():
    with open("users.json","w") as f:
        json.dump(users,f)

languages=[
"العربية 🇮🇶",
"English 🇬🇧",
"Русский 🇷🇺",
"فارسی 🇮🇷",
"Türkçe 🇹🇷",
"Español 🇪🇸",
"Português 🇧🇷",
"Deutsch 🇩🇪",
"Italiano 🇮🇹",
"हिन्दी 🇮🇳",
"اردو 🇵🇰",
"Українська 🇺🇦"
]

countries={
"العربية 🇮🇶":{"العراق":["Baghdad","Basra","Erbil"]},
"English 🇬🇧":{"USA":["New York","Washington"]},
"Русский 🇷🇺":{"Россия":["Moscow","Saint Petersburg"]},
"فارسی 🇮🇷":{"ایران":["Tehran","Mashhad"]},
"Türkçe 🇹🇷":{"Türkiye":["Istanbul","Ankara"]},
"Español 🇪🇸":{"España":["Madrid","Barcelona"]},
"Português 🇧🇷":{"Brasil":["Sao Paulo","Rio de Janeiro"]},
"Deutsch 🇩🇪":{"Deutschland":["Berlin","Munich"]},
"Italiano 🇮🇹":{"Italia":["Rome","Milan"]},
"हिन्दी 🇮🇳":{"भारत":["Delhi","Mumbai"]},
"اردو 🇵🇰":{"پاکستان":["Karachi","Lahore"]},
"Українська 🇺🇦":{"Україна":["Kyiv","Lviv"]}
}

RSS={
"العربية 🇮🇶":[
"https://www.aljazeera.net/aljazeera/rss",
"https://www.alarabiya.net/.mrss/ar/0/0/0.xml"
],
"English 🇬🇧":[
"http://feeds.bbci.co.uk/news/world/rss.xml"
],
"Русский 🇷🇺":[
"https://www.rbc.ru/rbcnews.rss"
],
"فارسی 🇮🇷":[
"https://www.bbc.com/persian/index.xml"
],
"Türkçe 🇹🇷":[
"https://www.bbc.com/turkce/index.xml"
],
"Español 🇪🇸":[
"https://www.bbc.com/mundo/index.xml"
]
}

@bot.message_handler(commands=["start"])
def start(m):

    uid=str(m.from_user.id)

    users[uid]={"name":m.from_user.first_name}

    save_users()

    markup=types.ReplyKeyboardMarkup(resize_keyboard=True)

    for l in languages:
        markup.add(l)

    bot.send_message(uid,"اختر لغتك",reply_markup=markup)

@bot.message_handler(func=lambda m:True)
def handle(m):

    uid=str(m.from_user.id)

    if uid not in users:
        return

    text=m.text
    user=users[uid]

    if "lang" not in user:

        if text in languages:

            user["lang"]=text
            save_users()

            markup=types.ReplyKeyboardMarkup(resize_keyboard=True)

            for c in countries[text]:
                markup.add(c)

            bot.send_message(uid,"اختر دولتك",reply_markup=markup)

            bot.send_message(
            ADMIN_ID,
            f"مستخدم جديد\n{m.from_user.first_name}\nID:{uid}"
            )

    elif "country" not in user:

        lang=user["lang"]

        if text in countries[lang]:

            user["country"]=text
            save_users()

            markup=types.ReplyKeyboardMarkup(resize_keyboard=True)

            for p in countries[lang][text]:
                markup.add(p)

            bot.send_message(uid,"اختر محافظتك",reply_markup=markup)

    elif "province" not in user:

        user["province"]=text
        save_users()

        bot.send_message(uid,"تم الحفظ ✅ ستصلك الأخبار والطقس")

def weather():

    for uid,data in users.items():

        if "province" not in data:
            continue

        city=data["province"]

        try:

            url=f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric"

            r=requests.get(url).json()

            temp=r["main"]["temp"]

            bot.send_message(uid,f"🌤 الطقس في {city}\n{temp}°C")

        except:
            pass

def news():

    for uid,data in users.items():

        lang=data.get("lang")

        if lang not in RSS:
            continue

        for src in RSS[lang]:

            feed=feedparser.parse(src)

            for item in feed.entries[:3]:

                bot.send_message(uid,f"📰 {item.title}\n{item.link}")

schedule.every().hour.do(weather)
schedule.every().hour.do(news)

def run():

    while True:

        schedule.run_pending()

        time.sleep(60)

threading.Thread(target=run).start()

bot.infinity_polling()
