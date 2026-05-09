# دليل الأمان — IraqNow Bot

## ✅ متغيرات البيئة المطلوبة (Heroku Config Vars)

### إلزامية — البوت لا يعمل بدونها
| المتغير | الوصف |
|---------|-------|
| `BOT_TOKEN` | توكن البوت من @BotFather |
| `ADMIN_ID` | Telegram user ID للمشرف |

### اختيارية
| المتغير | الوصف |
|---------|-------|
| `GEMINI_API_KEY` | مفتاح Google Gemini |
| `GROQ_API_KEY` | مفتاح Groq |
| `OPENROUTER_KEY` | مفتاح OpenRouter |
| `NEWS_KEY` | مفتاح NewsAPI |
| `WEATHER_KEY` | مفتاح OpenWeatherMap |
| `FB_PAGE_TOKEN` | توكن صفحة Facebook |
| `FB_PAGE_ID` | ID صفحة Facebook |
| `IG_USER_ID` | Instagram User ID |
| `IMGBB_API_KEY` | مفتاح ImgBB |
| `BACKUP_CHANNEL_ID` | ID قناة النسخ الاحتياطي |

## ⚠️ قواعد الأمان

1. **لا ترفع أي secret إلى GitHub أبداً** — استخدم Heroku Config Vars دائماً
2. **ملفات `.db` و `.log` و `.env` محظورة** في `.gitignore`
3. **ADMIN_ID يجب أن يكون رقم Telegram الحقيقي** — لا تتركه 0
4. **لا تشارك BOT_TOKEN** — من حصل عليه يتحكم بالبوت كاملاً
5. **عند اختراق التوكن** — أوقفه فوراً عبر @BotFather ثم أنشئ توكناً جديداً

## 🔒 Heroku — خطوات الأمان

```bash
heroku config:set BOT_TOKEN=your_token_here
heroku config:set ADMIN_ID=your_telegram_id
heroku config:set GEMINI_API_KEY=your_key
# ... إلخ
```

## 🚫 ما يجب ألا يكون في GitHub

- لا `*.db` files
- لا `*.env` files  
- لا tokens في الكود مباشرة
- لا `global_sent_news.json`
- لا `users_backup*.json`
