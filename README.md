# IraqNow Bot v4.1 — هيكل مُقسَّم للرفع على Heroku

## الملفات (9 وحدات + ملفات النشر)

| الملف | الأسطر | المحتوى |
|------|--------|---------|
| `main.py` | 72 | نقطة الدخول + حلقة polling مع retry |
| `config.py` | 112 | جميع المفاتيح من env + Feature Flags + الثوابت |
| `bot_core.py` | 46 | كائن البوت + الـ logger + دوال الإرسال الآمن |
| `db.py` | **475** | ✅ **كود فعلي:** SQLite (users, channels, dead_users, button_cache) |
| `ai.py` | **1406** | ✅ **كود فعلي:** محرك AI متعدد المزودين + Fact Check + InsightX |
| `features_news.py` | 80 | re-exports لكل دوال الأخبار والـ RSS والبث |
| `features_users.py` | 29 | re-exports لإدارة المستخدمين والمكافآت |
| `features_sports.py` | **2026** | ✅ **كود فعلي:** PATCH v5 + v6 (40+ ميزة رياضية + 365score) |
| `handlers.py` | 20 | re-exports للأوامر المباشرة |
| `bot_legacy.py` | 33,792 | باقي الكود الذي لم يُنقَل بعد (متشابك) |

**إجمالي ما نُقل فعلياً:** 3,805 سطر (DB + AI + Sports v5/v6).

## الرفع على Heroku

```bash
heroku create iraqnow-bot
heroku config:set BOT_TOKEN=YOUR_BOT_TOKEN WEATHER_KEY=YOUR_WEATHER_KEY NEWS_KEY=YOUR_NEWS_KEY ADMIN_ID=YOUR_TELEGRAM_ID
git push heroku main
heroku ps:scale worker=1
```

## التشغيل المحلي

```bash
export BOT_TOKEN="..."
python -m IraqNowBot.main
```

## ملاحظات مهمة

1. **التوكن لم يُغيَّر** — يُقرأ من متغير البيئة `BOT_TOKEN` مع fallback للقيمة الأصلية.
2. **bot_legacy.py** يحتوي على باقي الكود (المعالجات + الأخبار + المستخدمين). عند تحميل أي وحدة، يستورد bot_legacy تلقائياً، فلا تحذفه.
3. ترتيب التحميل في `main.py` مهم: `config → bot_legacy (مع imports داخلية لـ ai/db/sports) → باقي الوحدات`.
