import telebot
import requests
import schedule
import time
import threading

# ===== توكن البوت =====
TOKEN = "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU"
bot = telebot.TeleBot(TOKEN)

# ===== ملفات المستخدمين =====
USERS_FILE = "users.txt"

# ===== API Keys =====
WEATHER_KEY = "18a7801721693e772bbada4687d03e43"
NEWS_KEY = "98b2295d1a034076913e0c0e2aa64fa4"
AQI_KEY = "dd90e9d65caffb048e68b9d48d6b9aeab31c00d3"

# ===== تخصيص المدن والعملات =====
cities = ["Baghdad", "Basra", "Erbil"]
currencies = {"USD": "دولار", "EUR": "يورو"}
metals = ["Gold", "Silver"]
crypto = ["Bitcoin", "Ethereum"]

# ===== دالة ترسل رسالة لكل مستخدم =====
def broadcast(text):
    try:
        with open(USERS_FILE, "r") as f:
            users = f.readlines()
        for user in users:
            chat_id = user.strip().split(",")[0]
            bot.send_message(chat_id, text)
    except Exception as e:
        print(f"Broadcast error: {e}")

# ===== /start handler =====
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "أهلاً! 👋 هذا البوت يرسل لك الطقس، العملات، المباريات، الأخبار، وجودة الهواء تلقائيًا كل ساعة.")
    # تسجيل المستخدم
    try:
        with open(USERS_FILE, "a") as f:
            f.write(f"{message.chat.id},{message.from_user.username}\n")
    except:
        pass

# ===== سكشن الطقس =====
def send_weather():
    for city in cities:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric"
        data = requests.get(url).json()
        temp = data['main']['temp']
        humidity = data['main']['humidity']
        wind = data['wind']['speed']
        broadcast(f"☀️ الطقس في {city}: {temp}°C, رطوبة {humidity}%, سرعة الرياح {wind} m/s")

# ===== سكشن الأسعار =====
def send_prices():
    # مثال عملات، مع امكانية ربط قناة رسمية لاحقًا
    for cur, name in currencies.items():
        url = f"https://api.exchangerate.host/latest?base=USD&symbols={cur}"
        data = requests.get(url).json()
        rate = data['rates'][cur]
        broadcast(f"💰 سعر {name} اليوم: {rate}")

# ===== سكشن جودة الهواء =====
def send_air_quality():
    for city in cities:
        url = f"https://api.waqi.info/feed/{city}/?token={AQI_KEY}"
        data = requests.get(url).json()
        aqi = data['data']['aqi']
        broadcast(f"🌫 جودة الهواء في {city}: AQI {aqi}")

# ===== سكشن الأخبار =====
def send_news():
    url = f"https://newsapi.org/v2/top-headlines?country=us&apiKey={NEWS_KEY}"
    data = requests.get(url).json()
    articles = data.get('articles', [])[:5]
    messages = [f"- {a['title']}" for a in articles]
    broadcast("📰 أهم الأخبار:\n" + "\n".join(messages))

# ===== ضبط كل ساعة =====
schedule.every().hour.do(send_weather)
schedule.every().hour.do(send_prices)
schedule.every().hour.do(send_news)
schedule.every().hour.do(send_air_quality)

# ===== تشغيل الجدولة في thread =====
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=run_schedule).start()

# ===== تشغيل البوت =====
bot.polling(none_stop=True)
