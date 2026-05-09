# -*- coding: utf-8 -*-
"""IraqNow Bot — بوت تليجرام للأخبار والذكاء الاصطناعي.

الهيكل (9 وحدات):
    main.py            — نقطة الدخول
    config.py          — الإعدادات والمفاتيح
    bot_core.py        — كائن البوت + logger + safe_send
    db.py              — SQLite (مُستخرَج فعلياً)
    ai.py              — محرك الذكاء الاصطناعي (مُستخرَج فعلياً)
    features_news.py   — الأخبار والبث
    features_users.py  — المستخدمون والمكافآت
    features_sports.py — الرياضة v5+v6 (مُستخرَج فعلياً)
    handlers.py        — معالجات الأوامر
    bot_legacy.py      — باقي الكود غير المنقول بعد
"""
__version__ = "4.1.0-split"
