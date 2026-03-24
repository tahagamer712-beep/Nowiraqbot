# -*- coding: utf-8 -*-
# ===== IRAQNOW BOT - PRODUCTION READY v4.0 - Self-Healing + Monitoring =====
# ─── UTF-8 Fix (أولاً قبل أي شيء) ───────────────────────────────────────────
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import telebot
from telebot import types
import requests
import feedparser
import atexit
import os
import json
import datetime
import time
import sqlite3
import threading
import queue
import asyncio
import tempfile
import math
import logging
import traceback
import functools
from logging.handlers import RotatingFileHandler
from apscheduler.schedulers.background import BackgroundScheduler
from concurrent.futures import ThreadPoolExecutor, as_completed
import re as _re

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SYSTEM — احترافي مع تدوير الملف
# ═══════════════════════════════════════════════════════════════════════════════
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE   = "%Y-%m-%d %H:%M:%S"

# Logger رئيسي
_logger = logging.getLogger("IraqNow")
_logger.setLevel(logging.DEBUG)

# Handler للملف (5MB × 3 نسخ احتياطية)
try:
    _fh = RotatingFileHandler(
        "iraqnow_bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE))
    _logger.addHandler(_fh)
except Exception:
    pass

# Handler للكونسول
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE))
_logger.addHandler(_ch)

# منع تضاعف رسائل الـ logging من telebot
logging.getLogger("TeleBot").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

_logger.info("🚀 IraqNow Bot v4.0 — بدء التشغيل")

# ─── توقيت السعودية (UTC+3) ──────────────────────────────────────
_SA_TZ_OFFSET = datetime.timedelta(hours=3)

def _now_sa() -> datetime.datetime:
    """يُعيد الوقت الحالي بتوقيت السعودية / العراق (UTC+3)."""
    return datetime.datetime.utcnow() + _SA_TZ_OFFSET

def _sa_str(fmt="%H:%M:%S — %d/%m/%Y") -> str:
    """يُعيد الوقت الحالي كنص بتوقيت السعودية بالصيغة المطلوبة."""
    return _now_sa().strftime(fmt)

# ======== Edge TTS (رسائل صوتية مجانية) ========
_TTS_AVAILABLE = False
try:
    import edge_tts
    _TTS_AVAILABLE = True
except ImportError:
    pass

# ======== صوت لكل لغة في Edge TTS ========
TTS_VOICES = {
    "العربية 🇮🇶":   "ar-IQ-BasselNeural",
    "English 🇬🇧":   "en-GB-RyanNeural",
    "Русский 🇷🇺":   "ru-RU-DmitryNeural",
    "فارسی 🇮🇷":    "fa-IR-FaridNeural",
    "हिन्दी 🇮🇳":    "hi-IN-MadhurNeural",
    "Português 🇧🇷": "pt-BR-AntonioNeural",
    "Türkçe 🇹🇷":   "tr-TR-AhmetNeural",
    "اردو 🇵🇰":     "ur-PK-AsadNeural",
    "Deutsch 🇩🇪":   "de-DE-ConradNeural",
    "Українська 🇺🇦":"uk-UA-OstapNeural",
    "Italiano 🇮🇹":  "it-IT-DiegoNeural",
    "Español 🇲🇽":   "es-MX-JorgeNeural",
}

# ======== Gemini AI — تنظيف وتلخيص الأخبار ========
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_AI_AVAILABLE = False
_AI_MODEL = None

def _init_gemini():
    global _AI_AVAILABLE, _AI_MODEL
    if not GEMINI_API_KEY:
        return
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _AI_MODEL = genai.GenerativeModel("gemini-2.5-flash")
        _AI_AVAILABLE = True
        print("✅ Gemini AI جاهز للتلخيص والتنظيف")
    except ImportError:
        print("⚠️ مكتبة google-generativeai غير مثبتة. شغّل:  pip install google-generativeai")
    except Exception as e:
        print(f"⚠️ خطأ في تهيئة Gemini AI: {e}")

_init_gemini()

_AI_CACHE = {}           # link -> cleaned_text
_AI_CACHE_LOCK = threading.Lock()

def _ai_clean_news(title, body="", link=""):
    """
    يستخدم Gemini لتنظيف نص الخبر:
    - يحذف حقوق القنوات والتوقيعات والهاشتاقات
    - يُعيد العنوان نظيفاً أو ملخصاً قصيراً (جملة أو جملتان)
    - عند فشل AI يُعيد العنوان الأصلي بعد تنظيف بسيط بـ regex
    """
    # ─── كلمات تدل على محتوى ترويجي/غير إخباري ───────────────────
    _PROMO_WORDS = [
        "لا تنسى", "شاركونا", "اشترك معنا", "انضم إلينا", "انضم الينا",
        "تابعونا", "تابعنا على", "قناتنا", "صفحتنا",
        "أكبر نشر", "فوروارد", "forward this", "subscribe now",
        "follow us", "join us", "click here", "اضغط هنا", "لايك وكومنت",
        "رابط في البايو", "كانال تيليجرام", "انضم لقناتنا",
        "اشترك في قناتنا", "للاشتراك اضغط",
    ]
    # ─── كلمات مفردة تمثل اسم دولة/مدينة فقط (ليست خبراً) ─────────
    _GEO_ONLY = {
        "العراق","بغداد","البصرة","أربيل","الموصل","السليمانية","كركوك",
        "الأنبار","النجف","كربلاء","ذي قار","واسط","ميسان","ديالى",
        "بابل","المثنى","القادسية","صلاح الدين","دهوك","حلبجة",
        "السعودية","الإمارات","قطر","الكويت","إيران","تركيا","سوريا",
        "لبنان","الأردن","مصر","الولايات المتحدة الأمريكية","أمريكا",
        "روسيا","الصين","أوروبا","إسرائيل","فلسطين","اليمن","السودان",
        "ليبيا","تونس","الجزائر","المغرب","باكستان","أفغانستان",
    }

    # تنظيف regex أساسي دائماً
    def _basic_clean(text):
        # حذف الهاشتاقات
        text = _re.sub(r'#\S+', '', text)
        # حذف @mentions
        text = _re.sub(r'@\S+', '', text)
        # حذف URLs
        text = _re.sub(r'https?://\S+', '', text)
        # حذف أسطر "المصدر:" أو "via:" أو "حصري:" في نهاية النص
        text = _re.sub(r'[\n\r]*(المصدر|Source|via|حصري|خاص|©|حقوق|نقلاً عن)[^\n\r]*', '', text, flags=_re.IGNORECASE)
        # حذف أسطر فارغة متكررة
        text = _re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    clean_title = _basic_clean(title)

    # ─── فلتر محتوى ترويجي (بدون AI) ────────────────────────────────
    _ct_lower = clean_title.lower()
    if any(w in _ct_lower for w in _PROMO_WORDS):
        return None  # أسقط هذا المنشور — ليس خبراً

    # ─── فلتر اسم جغرافي مجرد ────────────────────────────────────────
    _stripped = clean_title.strip("📰📢🔴🟡⚡ ،.,!؟?-–—")
    if _stripped in _GEO_ONLY:
        return None  # مجرد اسم دولة/مدينة — ليس خبراً

    # ─── فلتر عناوين قصيرة جداً من قنوات تيليغرام ──────────────────
    if link and "t.me/" in link and len(clean_title) < 18:
        return None

    if not _AI_AVAILABLE or not _AI_MODEL:
        return clean_title

    # كاش لتجنب استدعاء AI مرتين لنفس الخبر
    cache_key = link or title[:80]
    with _AI_CACHE_LOCK:
        if cache_key in _AI_CACHE:
            return _AI_CACHE[cache_key]

    try:
        full_text = f"{title}\n\n{body}" if body else title
        prompt = (
            "أنت محرر أخبار محترف في وكالة أنباء دولية. مهمتك:\n"
            "1. استخرج الخبر الأساسي فقط بجملة واحدة واضحة أو جملتين كحد أقصى\n"
            "2. احذف تماماً: أسماء القنوات، التوقيعات، الهاشتاقات، الحقوق، @mentions، الروابط، إعلانات الاشتراك\n"
            "3. اكتب بالعربية الفصحى الدقيقة، محافظاً على الأرقام والأسماء الصحيحة\n"
            "4. إذا كان النص ترويجياً أو إعلانياً وليس خبراً، اكتب فقط: SKIP\n"
            "5. لا تضف أي مقدمة أو تعليق، فقط نص الخبر المنقى مباشرة\n\n"
            f"النص:\n{full_text[:1500]}"
        )
        # ⏱ تنفيذ AI بـ timeout 5 ثواني — منع تجميد البث
        _result_holder = [clean_title]
        def _call_ai():
            try:
                response = _AI_MODEL.generate_content(prompt)
                if response and response.text:
                    _result_holder[0] = response.text.strip()
            except Exception as _e:
                _logger.debug("_ai_clean_news: خطأ AI: %s", _e)
        _t = threading.Thread(target=_call_ai, daemon=True)
        _t.start()
        _t.join(timeout=5)      # أقصى انتظار 5 ثواني
        result = _result_holder[0]
        # رفض النتيجة إذا أشارت AI بأنه محتوى ترويجي
        if result and result.strip().upper() == "SKIP":
            return None
        # لا نقبل نتيجة فارغة أو طويلة جداً
        if not result or len(result) > 600:
            result = clean_title
        with _AI_CACHE_LOCK:
            _AI_CACHE[cache_key] = result
            if len(_AI_CACHE) > 1000:
                keys = list(_AI_CACHE.keys())
                for k in keys[:200]:
                    del _AI_CACHE[k]
        return result
    except Exception:
        return clean_title


_AI_SUMMARY_CACHE = {}
_AI_SUMMARY_LOCK = __import__('threading').Lock()

def _ai_generate_summary(text, title="", lang="العربية 🇮🇶"):
    """
    يُولّد ملخصاً صحفياً احترافياً من نص الخبر أو منشور القناة.
    يستخدم Gemini إذا متاح، وإلا يُعيد النص مباشرة.
    المخرج: 3-5 جمل بلغة المستخدم.
    """
    cache_key = (title or text[:60]) + lang
    with _AI_SUMMARY_LOCK:
        if cache_key in _AI_SUMMARY_CACHE:
            return _AI_SUMMARY_CACHE[cache_key]

    import re as _re2
    # تنظيف أولي
    clean = _re2.sub(r'#\S+', '', text)
    clean = _re2.sub(r'@\S+', '', clean)
    clean = _re2.sub(r'https?://\S+', '', clean)
    clean = _re2.sub(r'\n{3,}', '\n\n', clean).strip()

    if not _AI_AVAILABLE or not _AI_MODEL:
        return clean[:800]

    lang_instruction = {
        "العربية 🇮🇶": "اكتب الملخص باللغة العربية الفصحى",
        "English 🇬🇧": "Write the summary in fluent English",
        "Русский 🇷🇺": "Напиши резюме на русском языке",
        "فارسی 🇮🇷": "خلاصه را به فارسی بنویس",
        "हिन्दी 🇮🇳": "सारांश हिन्दी में लिखें",
        "Türkçe 🇹🇷": "Özeti Türkçe olarak yaz",
        "Deutsch 🇩🇪": "Schreibe die Zusammenfassung auf Deutsch",
        "Español 🇲🇽": "Escribe el resumen en español",
        "Português 🇧🇷": "Escreva o resumo em português",
        "Italiano 🇮🇹": "Scrivi il riassunto in italiano",
        "Українська 🇺🇦": "Напиши резюме українською",
        "اردو 🇵🇰": "خلاصہ اردو میں لکھیں",
    }.get(lang, "Write the summary in the same language as the text")

    try:
        full_input = f"{title}\n\n{clean[:1200]}" if title else clean[:1200]
        prompt = (
            f"أنت صحفي محترف. مهمتك كتابة ملخص إخباري للخبر التالي.\n"
            f"القواعد:\n"
            f"1. {lang_instruction}\n"
            f"2. اكتب 3 إلى 5 جمل تغطي أهم نقاط الخبر\n"
            f"3. احذف أسماء القنوات، التوقيعات، الهاشتاقات، الروابط\n"
            f"4. لا تضف مقدمة أو تعليقاً، فقط نص الملخص مباشرة\n\n"
            f"الخبر:\n{full_input}"
        )
        # ⏱ timeout 8 ثواني — منع التجميد
        _sum_holder = [clean[:800]]
        def _call_sum():
            try:
                response = _AI_MODEL.generate_content(prompt)
                if response and response.text:
                    _sum_holder[0] = response.text.strip()
            except Exception as _se:
                _logger.debug("_ai_generate_summary: خطأ AI: %s", _se)
        _st = threading.Thread(target=_call_sum, daemon=True)
        _st.start()
        _st.join(timeout=8)
        result = _sum_holder[0]
        if not result or len(result) < 20:
            result = clean[:800]
        with _AI_SUMMARY_LOCK:
            _AI_SUMMARY_CACHE[cache_key] = result
            if len(_AI_SUMMARY_CACHE) > 500:
                keys = list(_AI_SUMMARY_CACHE.keys())
                for k in keys[:100]:
                    del _AI_SUMMARY_CACHE[k]
        return result
    except Exception:
        return clean[:800]


# ─── التحقق من الأخبار (Fact Check) ────────────────────────────
_FACT_CHECK_AI_CACHE: dict = {}
_FACT_CHECK_AI_LOCK = threading.Lock()

def _ai_fact_check(title: str, body: str = "") -> dict:
    """
    يُصنّف الخبر: موثوق ✅ / يحتاج تحقق ⚠️ / شائعة ❌
    يُعيد: {"verdict": "✅"|"⚠️"|"❌", "label": str, "reason": str}
    """
    cache_key = title[:80]
    with _FACT_CHECK_AI_LOCK:
        cached = _FACT_CHECK_AI_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 3600:
            return cached["data"]

    fallback = {"verdict": "⚠️", "label": "يحتاج تحقق", "reason": "لم يتم التحقق"}

    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    full = f"{title}\n{body[:500]}" if body else title
    prompt = (
        "أنت محقق أخبار محترف. حلّل الخبر التالي وأجب بصيغة JSON فقط:\n"
        '{"verdict": "✅ موثوق" أو "⚠️ يحتاج تحقق" أو "❌ شائعة", "reason": "سبب واحد في جملة"}\n\n'
        "معايير التصنيف:\n"
        "✅ موثوق: خبر واضح ومحدد بأسماء وأرقام وجهات رسمية\n"
        "⚠️ يحتاج تحقق: خبر غامض أو ادعاء بدون مصدر أو رأي\n"
        "❌ شائعة: مبالغة واضحة أو تناقض داخلي أو لغة تحريضية بلا دليل\n\n"
        f"الخبر:\n{full[:600]}"
    )
    try:
        _holder = [None]
        def _call():
            try:
                resp = _AI_MODEL.generate_content(prompt)
                if resp and resp.text:
                    _holder[0] = resp.text.strip()
            except Exception:
                pass
        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=6)
        raw = _holder[0] or ""
        import json as _json2
        raw_clean = _re.sub(r'```json|```', '', raw).strip()
        data_raw = _json2.loads(raw_clean)
        verdict_raw = data_raw.get("verdict", "⚠️")
        if "✅" in verdict_raw:
            icon, label = "✅", "موثوق"
        elif "❌" in verdict_raw:
            icon, label = "❌", "شائعة"
        else:
            icon, label = "⚠️", "يحتاج تحقق"
        result = {"verdict": icon, "label": label, "reason": data_raw.get("reason", "")[:120]}
        with _FACT_CHECK_AI_LOCK:
            _FACT_CHECK_AI_CACHE[cache_key] = {"data": result, "ts": time.time()}
            if len(_FACT_CHECK_AI_CACHE) > 500:
                oldest = list(_FACT_CHECK_AI_CACHE.keys())[:100]
                for k in oldest:
                    del _FACT_CHECK_AI_CACHE[k]
        return result
    except Exception:
        return fallback


# ─── البحث في الأخبار المؤرشفة ──────────────────────────────────
def _ai_find_connections(news_titles: list) -> str:
    """يُحلل قائمة عناوين الأخبار ويكشف العلاقات والروابط الخفية"""
    if not _AI_AVAILABLE or not _AI_MODEL or not news_titles:
        return "لا تتوفر بيانات كافية للتحليل"
    joined = "\n".join(f"• {t}" for t in news_titles[:25])
    prompt = (
        "أنت محلل استخباراتي. لديك هذه الأخبار من الساعات الأخيرة:\n\n"
        f"{joined}\n\n"
        "اكشف الروابط والعلاقات بين هذه الأخبار:\n"
        "- ما الخيط الذي يربطها؟\n"
        "- هل هناك سبب وتأثير؟\n"
        "- ماذا تتوقع أن يحدث بعدها؟\n"
        "اكتب تحليلاً عميقاً في 5-7 جمل. ابدأ مباشرة."
    )
    try:
        _h = [None]
        def _c():
            try:
                r = _AI_MODEL.generate_content(prompt)
                if r and r.text:
                    _h[0] = r.text.strip()
            except Exception:
                pass
        t = threading.Thread(target=_c, daemon=True)
        t.start()
        t.join(timeout=12)
        return _h[0] or "تعذر التحليل"
    except Exception:
        return "تعذر التحليل"


# ─── كاشف التناقضات السياسية ────────────────────────────────────
def _ai_detect_contradiction(name: str, old_stmt: str, new_stmt: str, old_date: str = "") -> str:
    """يُحلل تناقض بين تصريحين لنفس الشخص"""
    if not _AI_AVAILABLE or not _AI_MODEL:
        return ""
    prompt = (
        f"السياسي: {name}\n"
        f"تصريح قديم ({old_date}): {old_stmt}\n"
        f"تصريح جديد (اليوم): {new_stmt}\n\n"
        "هل هناك تناقض؟ إذا نعم: اشرح الفرق بجملة واحدة حادة وموضوعية. "
        "إذا لا تناقض: أجب بـ 'لا تناقض'."
    )
    try:
        _h = [None]
        def _c():
            try:
                r = _AI_MODEL.generate_content(prompt)
                if r and r.text:
                    _h[0] = r.text.strip()
            except Exception:
                pass
        t = threading.Thread(target=_c, daemon=True)
        t.start()
        t.join(timeout=7)
        return _h[0] or ""
    except Exception:
        return ""


# ─── تقرير غرفة الأزمات ─────────────────────────────────────────
def _ai_crisis_intelligence_report(keyword: str, timeline: list) -> str:
    """يُولّد تقريراً استخباراتياً كاملاً عن أزمة"""
    if not _AI_AVAILABLE or not _AI_MODEL:
        return ""
    timeline_text = "\n".join(
        f"[{item.get('time','')}] {item.get('text','')}" for item in timeline[-30:]
    )
    prompt = (
        f"كلمة الأزمة: {keyword}\n\n"
        f"تسلسل الأحداث (من الأقدم للأحدث):\n{timeline_text}\n\n"
        "اكتب تقريراً استخباراتياً كاملاً يشمل:\n"
        "🔴 **ما حدث** — ملخص الحدث\n"
        "🕵️ **الأطراف المتورطة** — من؟ وماذا فعل؟\n"
        "📈 **التطور** — كيف تصاعدت الأحداث؟\n"
        "⚠️ **التهديد** — ما الخطر المحتمل؟\n"
        "🔮 **التوقعات** — ماذا قد يحدث خلال 24 ساعة؟\n\n"
        "اكتب بأسلوب استخباراتي محترف. حد أقصى 400 كلمة."
    )
    try:
        _h = [None]
        def _c():
            try:
                r = _AI_MODEL.generate_content(prompt)
                if r and r.text:
                    _h[0] = r.text.strip()
            except Exception:
                pass
        t = threading.Thread(target=_c, daemon=True)
        t.start()
        t.join(timeout=15)
        return _h[0] or ""
    except Exception:
        return ""


# ─── محقق الشائعات ───────────────────────────────────────────────
def _ai_verify_rumor(claim: str, sources_text: str) -> dict:
    """
    يتحقق من ادعاء مقارنةً بما نشرته المصادر
    يُعيد: {"verdict": str, "confidence": int, "explanation": str, "first_source": str}
    """
    if not _AI_AVAILABLE or not _AI_MODEL:
        return {"verdict": "⚠️", "confidence": 0, "explanation": "AI غير متاح", "first_source": ""}
    prompt = (
        f"الادعاء المراد التحقق منه:\n\"{claim}\"\n\n"
        f"ما نشرته المصادر الإخبارية الموثوقة (آخر 24 ساعة):\n{sources_text[:2000]}\n\n"
        "حلّل وأجب بـ JSON فقط:\n"
        '{"verdict": "✅ مؤكد" أو "⚠️ غير مؤكد" أو "❌ مضلل", '
        '"confidence": رقم 0-100, '
        '"explanation": "شرح في جملتين", '
        '"first_source": "أول مصدر ذكره إذا وجد أو فارغ"}'
    )
    try:
        _h = [None]
        def _c():
            try:
                r = _AI_MODEL.generate_content(prompt)
                if r and r.text:
                    _h[0] = r.text.strip()
            except Exception:
                pass
        t = threading.Thread(target=_c, daemon=True)
        t.start()
        t.join(timeout=10)
        raw = _h[0] or ""
        import json as _j3
        raw_c = _re.sub(r'```json|```', '', raw).strip()
        return _j3.loads(raw_c)
    except Exception:
        return {"verdict": "⚠️", "confidence": 0, "explanation": "تعذر التحليل", "first_source": ""}


# ─── ذاكرة الأمة (هذا اليوم في التاريخ) ────────────────────────
def _ai_nation_memory(lang: str = "العربية 🇮🇶") -> str:
    """يُولّد ملخصاً: ماذا جرى في مثل هذا اليوم في تاريخ العراق"""
    if not _AI_AVAILABLE or not _AI_MODEL:
        return "AI غير متاح"
    today_str = _now_sa().strftime("%d %B")
    lang_map = {
        "العربية 🇮🇶": "العربية الفصحى", "English 🇬🇧": "English",
        "Русский 🇷🇺": "Russian", "فارسی 🇮🇷": "Persian",
        "Türkçe 🇹🇷": "Turkish", "Deutsch 🇩🇪": "German",
        "Español 🇲🇽": "Spanish",
    }
    write_lang = lang_map.get(lang, "English")
    prompt = (
        f"اليوم هو {today_str}. اكتب ملخصاً مثيراً عن أبرز ما جرى في العراق "
        f"في مثل هذا اليوم عبر التاريخ (أحداث حقيقية موثقة من تواريخ مختلفة).\n\n"
        f"اكتب باللغة: {write_lang}\n"
        "يشمل: حدث سياسي، حدث عسكري أو أمني، حدث اقتصادي أو ثقافي إن أمكن.\n"
        "الأسلوب: درامي وجذاب، كأنك تروي قصة. لا تزيد عن 250 كلمة."
    )
    try:
        _h = [None]
        def _c():
            try:
                r = _AI_MODEL.generate_content(prompt)
                if r and r.text:
                    _h[0] = r.text.strip()
            except Exception:
                pass
        t = threading.Thread(target=_c, daemon=True)
        t.start()
        t.join(timeout=12)
        return _h[0] or "لا توجد بيانات لهذا اليوم"
    except Exception:
        return "تعذر الاسترداد"


# ======== قفل تداخل دورات البث ========
# نستخدم Event بدلاً من Lock حتى يتمكن الـ watchdog من إعادة التعيين
_broadcast_news_lock    = threading.Event()   # set = مشغول، clear = حر
_broadcast_channels_lock = threading.Event()  # نفس الأسلوب
_broadcast_lock_ts      = [0.0]               # وقت بدء دورة البث الحالية
_BROADCAST_MAX_SECS     = 150                 # أقصى مدة لدورة بث واحدة (ثانية)

_broadcast_ch_lock_ts   = [0.0]               # وقت بدء دورة بث القنوات

def _broadcast_watchdog():
    """خيط مراقبة: يُعيد تعيين أقفال البث إذا علقت أكثر من 90 ثانية."""
    while True:
        time.sleep(20)
        try:
            # مراقبة قفل بث المستخدمين
            if _broadcast_news_lock.is_set():
                elapsed = time.time() - _broadcast_lock_ts[0]
                if elapsed > _BROADCAST_MAX_SECS:
                    _broadcast_news_lock.clear()
                    try:
                        bot.send_message(ADMIN_ID,
                            f"⚠️ watchdog: بث الأخبار علق {elapsed:.0f}ث — تم إعادة التعيين")
                    except Exception:
                        pass
            # مراقبة قفل بث القنوات
            if _broadcast_channels_lock.is_set():
                elapsed2 = time.time() - _broadcast_ch_lock_ts[0]
                if elapsed2 > _BROADCAST_MAX_SECS:
                    _broadcast_channels_lock.clear()
        except Exception:
            pass

threading.Thread(target=_broadcast_watchdog, daemon=True, name="broadcast_watchdog").start()

# ======== نظام الإصلاح التلقائي الذكي ========
_auto_recovery_last = {
    "clearcache": 0.0,
    "forcenews":  0.0,
    "ai_retry":   0.0,
}
_QUEUE_OVERFLOW_THRESHOLD = 300    # إذا تجاوز عدد الرسائل المنتظرة هذا الرقم
_NO_NEWS_TIMEOUT_SEC      = 25*60  # إذا لم يُرسَل أي خبر خلال 25 دقيقة

def _auto_recovery_watchdog():
    """
    نظام الإصلاح التلقائي الذكي — يعمل في الخلفية كل 60 ثانية ويُنفّذ:
    1. تنظيف القائمة تلقائياً إذا تراكمت أكثر من 300 رسالة
    2. إعادة البث تلقائياً إذا لم يُرسَل خبر خلال 25 دقيقة
    3. محاولة إعادة تهيئة الذكاء الاصطناعي كل 30 دقيقة
    """
    global _AI_AVAILABLE, _AI_MODEL
    while True:
        time.sleep(60)
        try:
            now = time.time()

            # ─── 1. تنظيف القائمة إذا طفحت ────────────────────────
            q_size = _send_queue.qsize() if hasattr(_send_queue, 'qsize') else 0
            if q_size > _QUEUE_OVERFLOW_THRESHOLD:
                cooldown = 300  # مرة واحدة كل 5 دقائق كحد أقصى
                if now - _auto_recovery_last["clearcache"] > cooldown:
                    _auto_recovery_last["clearcache"] = now
                    # تفريغ العناصر الزائدة (نبقي آخر 50)
                    dropped = 0
                    while _send_queue.qsize() > 50:
                        try:
                            _send_queue.get_nowait()
                            _send_queue.task_done()
                            dropped += 1
                        except Exception:
                            break
                    msg = (
                        f"🤖 *إصلاح تلقائي — تنظيف القائمة*\n"
                        f"📬 كانت القائمة: `{q_size}` رسالة\n"
                        f"🗑 تم حذف: `{dropped}` رسالة قديمة\n"
                        f"✅ القائمة الآن: `{_send_queue.qsize()}` رسالة"
                    )
                    try:
                        bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
                    except Exception:
                        pass

            # ─── 2. إعادة البث إذا توقف الخبر ──────────────────────
            last_bc = _broadcast_stats.get("last_broadcast_time")
            if last_bc:
                try:
                    last_bc_ts = last_bc.timestamp() if hasattr(last_bc, 'timestamp') else float(last_bc)
                    elapsed_since = now - last_bc_ts
                except Exception:
                    elapsed_since = 0
                if elapsed_since > _NO_NEWS_TIMEOUT_SEC:
                    cooldown2 = 30 * 60  # مرة واحدة كل 30 دقيقة
                    if now - _auto_recovery_last["forcenews"] > cooldown2:
                        _auto_recovery_last["forcenews"] = now
                        # إعادة تعيين القفل أولاً
                        _broadcast_news_lock.clear()
                        _broadcast_channels_lock.clear()
                        msg2 = (
                            f"🤖 *إصلاح تلقائي — إعادة تشغيل البث*\n"
                            f"⏱ لم يُرسَل أي خبر منذ: `{elapsed_since/60:.0f}` دقيقة\n"
                            f"🔄 تم إعادة تعيين أقفال البث\n"
                            f"📡 سيُرسَل البث في الدورة القادمة..."
                        )
                        try:
                            bot.send_message(ADMIN_ID, msg2, parse_mode="Markdown")
                        except Exception:
                            pass

            # ─── 2.5 مراقبة عدد الخيوط (thread count) ──────────────
            active_threads = threading.active_count()
            if active_threads > 200:
                # تحذير فقط — لا يمكن قتل الخيوط مباشرة
                try:
                    bot.send_message(ADMIN_ID,
                        f"⚠️ *تحذير: خيوط مفتوحة كثيرة*\n"
                        f"   عدد الخيوط الحالية: `{active_threads}`\n"
                        f"   حد Heroku: ~256\n"
                        f"   البوت سيُعيد تشغيله تلقائياً قريباً إذا وصل للحد"
                    , parse_mode="Markdown")
                except Exception:
                    pass

            # ─── 3. إعادة محاولة تهيئة الذكاء الاصطناعي ───────────
            if not _AI_AVAILABLE and GEMINI_API_KEY:
                cooldown3 = 30 * 60  # كل 30 دقيقة
                if now - _auto_recovery_last["ai_retry"] > cooldown3:
                    _auto_recovery_last["ai_retry"] = now
                    try:
                        import google.generativeai as genai
                        genai.configure(api_key=GEMINI_API_KEY)
                        _AI_MODEL = genai.GenerativeModel("gemini-2.5-flash")
                        _AI_AVAILABLE = True
                        try:
                            bot.send_message(ADMIN_ID,
                                "✅ *تم تفعيل الذكاء الاصطناعي تلقائياً!*",
                                parse_mode="Markdown")
                        except Exception:
                            pass
                    except Exception:
                        pass

        except Exception:
            pass

threading.Thread(target=_auto_recovery_watchdog, daemon=True, name="auto_recovery_watchdog").start()

# ======== إحصائيات البث ========
_broadcast_stats = {
    "today_date": "",
    "today_news_sent": 0,
    "today_users_reached": 0,
    "total_news_all_time": 0,
    "last_broadcast_time": None,
    "hourly_activity": {},      # {"0": N, "1": N, ..., "23": N}  — إجمالي إرسالات كل ساعة
}
_broadcast_errors = []   # آخر 30 خطأ في البث
_broadcast_stats_lock = threading.Lock()

def _record_broadcast_stat(users_reached=0, news_count=0):
    with _broadcast_stats_lock:
        today = str(datetime.date.today())
        if _broadcast_stats["today_date"] != today:
            _broadcast_stats["today_date"] = today
            _broadcast_stats["today_news_sent"] = 0
            _broadcast_stats["today_users_reached"] = 0
        _broadcast_stats["today_news_sent"] += news_count
        _broadcast_stats["today_users_reached"] += users_reached
        _broadcast_stats["total_news_all_time"] += news_count
        _broadcast_stats["last_broadcast_time"] = _now_sa().strftime("%H:%M:%S")
        # تتبع ساعات الذروة
        hour_key = str(_now_sa().hour)
        hourly = _broadcast_stats.setdefault("hourly_activity", {})
        hourly[hour_key] = hourly.get(hour_key, 0) + users_reached

def _record_broadcast_error(err_msg):
    with _broadcast_stats_lock:
        ts = _now_sa().strftime("%Y-%m-%d %H:%M:%S")
        _broadcast_errors.append(f"[{ts}] {err_msg}")
        if len(_broadcast_errors) > 30:
            _broadcast_errors.pop(0)

# ═══════════════════════════════════════════════════════════════════════════════
# SELF-HEALING ENGINE v2.0 — مراقبة النظام، التعافي التلقائي، الصيانة الاستباقية
# ═══════════════════════════════════════════════════════════════════════════════

# ── محاولة تحميل psutil (اختياري) ──────────────────────────────────────────
try:
    import psutil as _psutil
    _PSUTIL_OK = True
except ImportError:
    _psutil = None
    _PSUTIL_OK = False

# ── تتبع الأخطاء التنبؤية (Predictive Error Tracking + Timeline) ────────────
_error_freq: dict = {}          # func_name → total count
_error_freq_lock = threading.Lock()

# Timeline: قائمة مرتّبة زمنياً لآخر 200 خطأ بالتفاصيل الكاملة
_error_timeline: list = []          # [{ts, func, type, msg}]
_error_timeline_lock = threading.Lock()
_ERROR_TIMELINE_MAX  = 200

def _track_error(func_name: str, exc: Exception = None, err_type: str = ""):
    """
    سجّل خطأ في وظيفة معيّنة:
    • يُحدّث عداد التكرار
    • يُضيف سجلاً في التيملاين بطابع زمني
    • يُرسل تحذيراً استباقياً عند أعداد محددة
    """
    err_msg  = str(exc)[:300] if exc else ""
    if not err_type:
        try:
            err_type = _classify_error(err_msg) if err_msg else "unknown"
        except Exception:
            err_type = "unknown"

    # ── تحديث العداد ──
    with _error_freq_lock:
        _error_freq[func_name] = _error_freq.get(func_name, 0) + 1
        total = _error_freq[func_name]

    # ── تحديث التيملاين ──
    entry = {
        "ts":   time.time(),
        "func": func_name,
        "type": err_type,
        "msg":  err_msg,
    }
    with _error_timeline_lock:
        _error_timeline.append(entry)
        if len(_error_timeline) > _ERROR_TIMELINE_MAX:
            del _error_timeline[0]

    # ── تحذير الأدمن الاستباقي ──
    if total in (5, 10, 25, 50, 100) or total % 100 == 0:
        try:
            bot.send_message(
                ADMIN_ID,
                f"⚠️ *تحذير استباقي* — `{func_name}` أخطأت *{total}* مرة\n"
                f"نوع الخطأ: `{err_type}`\n"
                + (f"`{err_msg[:200]}`" if err_msg else ""),
                parse_mode="Markdown"
            )
        except Exception:
            pass

# ── إحصاءات صحة النظام ──────────────────────────────────────────────────────
_sys_health: dict = {
    "ram_pct":   0.0,
    "cpu_pct":   0.0,
    "disk_pct":  0.0,
    "start_ts":  time.time(),
    "recoveries": 0,   # عدد مرات التعافي التلقائي
}

def _get_sys_metrics() -> dict:
    """يُعيد مقاييس النظام الحالية بدون تعليق."""
    ram = cpu = disk = 0.0
    if _PSUTIL_OK:
        try:
            ram  = _psutil.virtual_memory().percent
            cpu  = _psutil.cpu_percent(interval=0.5)
            disk = _psutil.disk_usage('/').percent
        except Exception:
            pass
    else:
        # fallback: /proc/meminfo للنظم التي لا تملك psutil
        try:
            with open("/proc/meminfo") as _mf:
                lines = {l.split(':')[0]: l.split(':')[1].strip() for l in _mf}
            _total = int(lines.get("MemTotal","0 kB").split()[0])
            _avail = int(lines.get("MemAvailable","0 kB").split()[0])
            if _total > 0:
                ram = (_total - _avail) / _total * 100
        except Exception:
            pass
    return {"ram_pct": ram, "cpu_pct": cpu, "disk_pct": disk}

def _auto_memory_cleanup():
    """يُطلق garbage collector ويُنظف الكاشات الكبيرة عند ارتفاع الذاكرة."""
    import gc
    gc.collect()
    with _AI_CACHE_LOCK:
        if len(_AI_CACHE) > 500:
            keys = list(_AI_CACHE.keys())
            for k in keys[:300]:
                del _AI_CACHE[k]
    with _AI_SUMMARY_LOCK:
        if len(_AI_SUMMARY_CACHE) > 200:
            keys = list(_AI_SUMMARY_CACHE.keys())
            for k in keys[:100]:
                del _AI_SUMMARY_CACHE[k]
    if len(_news_summary_cache) > 1000:
        oldest = list(_news_summary_cache.keys())[:300]
        for k in oldest:
            _news_summary_cache.pop(k, None)
    _logger.info("🧹 auto_memory_cleanup: تنظيف ذاكرة تام")
    _sys_health["recoveries"] += 1

def _system_health_monitor():
    """
    خيط مراقبة النظام — يعمل كل 60 ثانية.
    يفحص RAM/CPU ويتخذ إجراءات تعافي تلقائية عند تجاوز الحدود.
    """
    _WARN_RAM  = 85.0   # % — تحذير
    _CRIT_RAM  = 92.0   # % — تنظيف فوري
    _WARN_CPU  = 90.0   # % — تحذير فقط (لا يمكن التحكم فيه)
    _notified_ram = False
    while True:
        time.sleep(60)
        try:
            m = _get_sys_metrics()
            _sys_health.update(m)
            ram = m["ram_pct"]
            cpu = m["cpu_pct"]
            # ── RAM حرجة: تنظيف فوري ──────────────────────────────
            if ram > _CRIT_RAM:
                _logger.warning("🔴 RAM حرجة %.1f%% — بدء التنظيف التلقائي", ram)
                _auto_memory_cleanup()
                _notified_ram = False  # إعادة تعيين حتى يُرسل تنبيه بعد التعافي
                try:
                    bot.send_message(
                        ADMIN_ID,
                        f"🔴 *تحذير: RAM حرجة* `{ram:.1f}%`\n"
                        f"⚙️ تم تشغيل التنظيف التلقائي للذاكرة.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            # ── RAM مرتفعة: تحذير مبكر ────────────────────────────
            elif ram > _WARN_RAM and not _notified_ram:
                _notified_ram = True
                try:
                    bot.send_message(
                        ADMIN_ID,
                        f"⚠️ *تحذير: RAM مرتفعة* `{ram:.1f}%`\n"
                        f"🖥 CPU: `{cpu:.1f}%`",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            elif ram < 75:
                _notified_ram = False
        except Exception as _she:
            _logger.debug("_system_health_monitor: %s", _she)

threading.Thread(
    target=_system_health_monitor,
    daemon=True,
    name="SystemHealthMonitor"
).start()

# ── نسخ احتياطي تلقائي لقاعدة البيانات ────────────────────────────────────
def _auto_db_backup():
    """
    ينسخ `bot_data.db` إلى `bot_data.db.bak` دورياً.
    يُجري VACUUM لتحسين الأداء وتقليص الحجم.
    """
    try:
        import shutil
        bak = DB_FILE + ".bak"
        with _db_lock:
            try:
                _db_conn.execute("VACUUM")
                _db_conn.commit()
            except Exception:
                pass
        shutil.copy2(DB_FILE, bak)
        size_kb = os.path.getsize(bak) / 1024
        _logger.info("💾 DB backup: %s — %.1f KB", bak, size_kb)
    except Exception as _dbe:
        _logger.error("_auto_db_backup: %s", _dbe)
        _track_error("_auto_db_backup", _dbe)

# ── Replit Keep-Alive: HTTP server بسيط لمنع السقوط ────────────────────────
def _start_keepalive_server():
    """
    يُشغّل HTTP server بسيط على PORT بيئي (أو 8080 افتراضياً).
    يُجيب على /health بـ 200 OK حتى تبقى العملية حية على Replit/Railway/Heroku.
    """
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class _PingHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                uptime_s  = int(time.time() - _sys_health["start_ts"])
                uptime_h  = uptime_s // 3600
                uptime_m  = (uptime_s % 3600) // 60
                body = (
                    f"OK | uptime={uptime_h}h{uptime_m}m"
                    f" | users={len(users)}"
                    f" | ram={_sys_health['ram_pct']:.0f}%"
                    f" | recoveries={_sys_health['recoveries']}"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass  # تعطيل سجلات HTTP العادية

        port = int(os.environ.get("PORT", 8080))
        srv  = HTTPServer(("0.0.0.0", port), _PingHandler)
        _logger.info("🌐 Keep-Alive server يعمل على port %d", port)
        srv.serve_forever()
    except Exception as _kae:
        _logger.warning("_start_keepalive_server: %s", _kae)

threading.Thread(
    target=_start_keepalive_server,
    daemon=True,
    name="KeepAliveServer"
).start()

# ═══════════════════════════════════════════════════════════════════════════════
# نهاية SELF-HEALING ENGINE v2.0
# ═══════════════════════════════════════════════════════════════════════════════

# ── سجل الوحدات القابلة للإعادة (Module Registry) ─────────────────────────────
# كل وحدة تُسجّل هنا ← يمكن إعادة تشغيلها بالاسم عبر /restartmod
_module_registry: dict = {}
_module_registry_lock = threading.Lock()

def _register_module(name: str, target_fn):
    """يُسجّل خيطاً جديداً للوحدة في السجل المركزي ويُشغّله."""
    t = threading.Thread(target=target_fn, daemon=True, name=name)
    t.start()
    with _module_registry_lock:
        _module_registry[name] = {
            "target":     target_fn,
            "thread":     t,
            "started_at": time.time(),
            "restarts":   0,
        }
    return t

def _restart_module(name: str) -> str:
    """
    يُعيد تشغيل وحدة بالاسم مع الحفاظ على البيانات.
    يُعيد رسالة نصية توضح نتيجة العملية.
    """
    with _module_registry_lock:
        entry = dict(_module_registry.get(name, {}))
    if not entry:
        available = ", ".join(_module_registry.keys()) or "لا شيء"
        return f"❌ لا توجد وحدة باسم `{name}`.\nالمتاح: `{available}`"
    alive  = entry["thread"].is_alive() if entry.get("thread") else False
    t      = threading.Thread(target=entry["target"], daemon=True, name=name)
    t.start()
    with _module_registry_lock:
        _module_registry[name]["thread"]     = t
        _module_registry[name]["started_at"] = time.time()
        _module_registry[name]["restarts"]  += 1
        restarts = _module_registry[name]["restarts"]
    status = "كان حياً" if alive else "كان ميتاً"
    _logger.info("🔄 _restart_module: %s | %s | إعادة #%d", name, status, restarts)
    return (
        f"✅ أُعيد تشغيل `{name}`\n"
        f"الحالة السابقة: {status}\n"
        f"إجمالي إعادات التشغيل: `{restarts}`"
    )

def _get_module_status() -> str:
    """يُعيد جدولاً نصياً بحالة كل الوحدات المسجّلة."""
    with _module_registry_lock:
        items = list(_module_registry.items())
    if not items:
        return "لا توجد وحدات مسجّلة بعد."
    lines = []
    now = time.time()
    for name, info in items:
        alive   = info["thread"].is_alive() if info.get("thread") else False
        icon    = "🟢" if alive else "🔴"
        uptime  = int(now - info.get("started_at", now))
        h, m    = uptime // 3600, (uptime % 3600) // 60
        lines.append(f"{icon} `{name}` — {h}h{m}m | إعادات: {info.get('restarts', 0)}")
    return "\n".join(lines)

# ======== كشف التكرار الذكي (Jaccard Similarity) ========
def _title_words(title):
    """استخرج الكلمات المهمة من العنوان للمقارنة"""
    words = _re.sub(r'[^\w\s]', ' ', title.lower()).split()
    stop = {'the','a','an','of','in','on','at','to','for','is','are','was','were',
            'و','في','من','على','إلى','أن','هذا','هذه','ذلك','التي','الذي',
            'مع','عن','لا','ما','أو','لم','قد','كان','كانت','يكون','تكون'}
    return set(w for w in words if w not in stop and len(w) > 2)

def _bigram_set(text):
    """تحويل النص لمجموعة bigrams (زوجين من الحروف) لكشف أدق"""
    words = list(_title_words(text))
    return {f"{words[i]}_{words[i+1]}" for i in range(len(words)-1)}

def _cosine_similarity_titles(t1, t2):
    """تشابه Cosine مبسّط عبر تردد الكلمات"""
    w1 = list(_title_words(t1))
    w2 = list(_title_words(t2))
    if not w1 or not w2:
        return 0.0
    all_words = set(w1) | set(w2)
    v1 = {w: w1.count(w) for w in all_words}
    v2 = {w: w2.count(w) for w in all_words}
    dot   = sum(v1[w] * v2[w] for w in all_words)
    norm1 = sum(x**2 for x in v1.values()) ** 0.5
    norm2 = sum(x**2 for x in v2.values()) ** 0.5
    return dot / (norm1 * norm2) if norm1 and norm2 else 0.0

def _is_similar_title(t1, t2, threshold=0.52):
    """
    هل العنوانان يتحدثان عن نفس الخبر؟
    يستخدم Jaccard + Cosine + Bigram معاً لكشف أشمل.
    """
    w1, w2 = _title_words(t1), _title_words(t2)
    if not w1 or not w2:
        return False
    # Jaccard
    intersection = len(w1 & w2)
    union = len(w1 | w2)
    jaccard = (intersection / union) if union else 0.0
    if jaccard >= threshold:
        return True
    # Cosine
    cosine = _cosine_similarity_titles(t1, t2)
    if cosine >= threshold:
        return True
    # Bigram (للعناوين القصيرة — أكثر دقة)
    b1, b2 = _bigram_set(t1), _bigram_set(t2)
    if b1 and b2:
        b_inter = len(b1 & b2)
        b_union = len(b1 | b2)
        bigram_j = (b_inter / b_union) if b_union else 0.0
        if bigram_j >= threshold:
            return True
    return False

def _dedup_news_list(items):
    """
    إزالة الأخبار المكررة من قائمة (link, title, source, img).
    يحتفظ بأول نسخة ويحذف المشابهة.
    نستخدم مجموعة من bigrams لتحسين الأداء:
    - التحقق السريع بـ bigram overlap قبل الحساب الكامل
    - حد أقصى 200 خبر في القائمة لمنع البطء الشديد
    """
    seen_titles = []
    seen_bigrams = []
    result = []
    for item in items[:200]:  # حد أقصى 200 خبر
        title = item[1]
        bg_t = _bigram_set(title)
        duplicate = False
        for i, seen in enumerate(seen_titles):
            # فحص سريع بـ Jaccard قبل cosine كامل
            bg_s = seen_bigrams[i]
            if bg_t and bg_s:
                inter = len(bg_t & bg_s)
                union = len(bg_t | bg_s)
                if union > 0 and inter / union > 0.3:
                    if _is_similar_title(title, seen):
                        duplicate = True
                        break
            elif not bg_t and not bg_s and _is_similar_title(title, seen):
                duplicate = True
                break
        if not duplicate:
            seen_titles.append(title)
            seen_bigrams.append(bg_t)
            result.append(item)
    return result

# ======== كشف لغة العنوان (لمنع تسرب أخبار بلغة أخرى) ========
_LANG_SCRIPT = {
    "العربية 🇮🇶": _re.compile(r'[\u0600-\u06FF]'),
    "فارسی 🇮🇷":   _re.compile(r'[\u0600-\u06FF]'),
    "اردو 🇵🇰":    _re.compile(r'[\u0600-\u06FF\u0750-\u077F]'),
    "हिन्दी 🇮🇳":   _re.compile(r'[\u0900-\u097F]'),
    "Русский 🇷🇺":  _re.compile(r'[\u0400-\u04FF]'),
    "Українська 🇺🇦":_re.compile(r'[\u0400-\u04FF]'),
    "Deutsch 🇩🇪":  _re.compile(r'[a-zA-ZäöüÄÖÜß]'),
    "Türkçe 🇹🇷":  _re.compile(r'[a-zA-ZçğıöşüÇĞİÖŞÜ]'),
    "Português 🇧🇷":_re.compile(r'[a-zA-ZáàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ]'),
    "Italiano 🇮🇹": _re.compile(r'[a-zA-ZàèéìíîòóùúÀÈÉÌÍÎÒÓÙÚ]'),
    "Español 🇲🇽":  _re.compile(r'[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]'),
    "English 🇬🇧":  _re.compile(r'[a-zA-Z]'),
}
# لغات تستخدم حروف لاتينية متشابهة — لا نفلترها بالنص
_LATIN_LANGS = {"Deutsch 🇩🇪","Türkçe 🇹🇷","Português 🇧🇷","Italiano 🇮🇹","Español 🇲🇽","English 🇬🇧"}

def _title_in_lang(title, lang):
    """
    هل عنوان الخبر بالفعل بلغة المستخدم؟
    يُستخدم لمنع وصول أخبار إنجليزية لمستخدمي العربية/الفارسية/الهندية/الروسية.
    اللغات اللاتينية (إنجليزي/فرنسي/ألماني...) لا تُفلتر لأنها تتشارك الحروف.
    """
    if lang in _LATIN_LANGS:
        return True   # لا نستطيع التمييز بين اللاتينيات بدقة
    pat = _LANG_SCRIPT.get(lang)
    if not pat:
        return True   # لغة غير معروفة — نقبلها
    non_space = [c for c in title if not c.isspace()]
    if not non_space:
        return True
    matched = len(pat.findall(title))
    ratio = matched / len(non_space)
    return ratio >= 0.25   # 25% من الحروف يجب أن تكون بالنص الصحيح

# ======== تحليل مشاعر الخبر (Sentiment Analysis) ========
_SENTIMENT_POSITIVE = {
    'اتفاقية','توقيع','نجاح','إنجاز','تطور','انتعاش','ازدهار','سلام','تعاون',
    'مساعدة','دعم','تنمية','استثمار','بناء','إعادة إعمار','انفراج','حل','تقدم',
    'success','agreement','peace','growth','recovery','development','aid',
    'cooperation','progress','victory','positive','improvement','deal','boost',
    'انتصار','تحرير','عودة','أمل','فرصة','إنقاذ',
}
_SENTIMENT_NEGATIVE = {
    'انفجار','هجوم','قتل','اغتيال','حريق','كارثة','أزمة','انهيار','خسارة',
    'تدمير','دمار','ضحايا','قتلى','جرحى','احتجاج','غضب','مظاهرة','فشل',
    'سقوط','اعتقال','حظر','عقوبات','مجاعة','وفاة','مرض','وباء','تلوث',
    'explosion','attack','killed','crisis','collapse','disaster','violence',
    'war','conflict','death','disease','flood','earthquake','murder','protest',
    'تضخم','ارتفاع أسعار','ركود','بطالة',
}

def _sentiment_emoji(title):
    """يحلل العنوان ويعيد إيموجي يعبر عن طبيعة الخبر"""
    if not title:
        return ''
    words = set(_re.sub(r'[^\w\s]', ' ', title.lower()).split())
    pos = len(words & _SENTIMENT_POSITIVE)
    neg = len(words & _SENTIMENT_NEGATIVE)
    if neg > pos:
        return '📉'   # سلبي
    elif pos > neg:
        return '📈'   # إيجابي
    return ''          # محايد — لا إيموجي

# ======== فحص الوضع الصامت ذكياً ========
def _is_quiet_hours(uid):
    """الأخبار تُنشر 24/7 بلا توقف — دائماً False"""
    return False

# ======== مستوى التنبيه لكل مستخدم ========
# 'all' = كل الأخبار, 'important' = مهم+عاجل, 'breaking' = عاجل فقط
def _passes_alert_level(title, uid):
    """هل يُسمح بإرسال هذا الخبر لهذا المستخدم حسب مستوى تنبيهه؟"""
    user = users.get(str(uid), {})
    level = user.get("alert_level", "all")
    if level == "all":
        return True
    score = _news_importance_score(title)
    if level == "important":
        return score >= 1
    if level == "breaking":
        return score >= 2
    return True

# ======== تقييم أهمية الخبر ========
_IMPORTANCE_HIGH = {
    # عربية — عاجل وأمني وكوارث
    'عاجل','عاجلة','طارئ','طارئة','انفجار','انفجارات','اغتيال','اغتيالات',
    'زلزال','فيضان','كارثة','هجوم','هجمات','اشتباك','اشتباكات','سقوط',
    'اعتقال','اعتقالات','اعدام','مجزرة','ضحايا','قتلى','جرحى','شهداء',
    'اختطاف','حريق','انتحار','حادث','تفجير','تفجيرات','قصف','غارة',
    # إنجليزية
    'breaking','urgent','explosion','attack','killed','dead','shooting',
    'earthquake','flood','crash','fire','emergency','arrested','assassination',
    'war','conflict','crisis','disaster','missile','strike','hostage',
    # روسية وتركية وفارسية
    'срочно','взрыв','убийство','катастрофа',
    'acil','patlama','saldırı','deprem',
    'فوری','انفجار','ترور','زلزله',
}
_IMPORTANCE_MEDIUM = {
    # عربية
    'مهم','هام','تحذير','إنذار','قرار','اتفاقية','صفقة','احتجاج',
    'مظاهرة','إضراب','أزمة','ارتفاع','انخفاض','توقيف','مداهمة',
    'تصريح','بيان','وزير','رئيس','برلمان','انتخاب','إلغاء','تعيين',
    # إنجليزية
    'warning','alert','sanctions','protest','summit','election','resign',
    'agreement','deal','minister','parliament','condemned','arrested',
    # تركية وروسية
    'önemli','uyarı','kritik','важно','предупреждение',
}

def _news_importance_score(title):
    """
    يُقيّم أهمية الخبر بناءً على كلماته.
    يُعيد: 2 = عالي (صورة), 1 = متوسط (صورة), 0 = عادي (بدون صورة)
    """
    if not title:
        return 0
    words = set(_re.sub(r'[^\w\s]', ' ', title.lower()).split())
    if words & _IMPORTANCE_HIGH:
        return 2
    if words & _IMPORTANCE_MEDIUM:
        return 1
    return 0

def _should_send_with_image(title):
    """هل يستحق هذا الخبر إرسال صورة معه؟ (فقط الأخبار العاجلة لتجنب تكرار الصور)"""
    return _news_importance_score(title) >= 2

# ======== استخراج صورة المقال (og:image) ========
_OG_IMAGE_CACHE = {}
_OG_IMAGE_LOCK = threading.Lock()

def _get_og_image(url, timeout=6):
    """جلب صورة og:image من مقال إخباري (مع كاش)"""
    if not url:
        return None
    with _OG_IMAGE_LOCK:
        if url in _OG_IMAGE_CACHE:
            return _OG_IMAGE_CACHE[url]
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"},
                         allow_redirects=True)
        if r.status_code != 200:
            return None
        # بحث سريع عن og:image بدون BeautifulSoup
        match = _re.search(
            r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
            r.text, _re.IGNORECASE
        )
        if not match:
            match = _re.search(
                r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
                r.text, _re.IGNORECASE
            )
        img = match.group(1) if match else None
        with _OG_IMAGE_LOCK:
            _OG_IMAGE_CACHE[url] = img
            if len(_OG_IMAGE_CACHE) > 500:
                keys = list(_OG_IMAGE_CACHE.keys())
                for k in keys[:100]:
                    del _OG_IMAGE_CACHE[k]
        return img
    except Exception:
        return None

def _normalize_news_link(url: str) -> str:
    """
    تطبيع رابط الخبر لمنع التكرار بسبب طوابع زمنية/معاملات URL مختلفة.
    مثال: https://site.com/news?t=123&utm_source=tg → https://site.com/news
    """
    if not url:
        return url
    try:
        import urllib.parse as _up2
        p = _up2.urlparse(url.strip())
        # إبقاء fragment فقط إذا كان جزءاً حقيقياً من المسار (مقالات SPA)
        clean = _up2.urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))
        return clean.lower() if clean else url
    except Exception:
        return url

# ======== Edge TTS — تحويل الأخبار إلى صوت ========
def _tts_generate(text, voice, out_path):
    """توليد ملف صوتي باستخدام edge-tts (مزامن)"""
    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out_path)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.close()
        return True
    except Exception as e:
        return False

def send_voice_news(uid, count=3):
    """جلب آخر الأخبار وإرسالها كرسالة صوتية"""
    if not _TTS_AVAILABLE:
        bot.send_message(uid, "⚠️ خاصية الأخبار الصوتية غير متاحة حالياً.")
        return
    user = users.get(str(uid), {})
    lang = user.get("lang", "العربية 🇮🇶")
    voice = TTS_VOICES.get(lang, "ar-IQ-BasselNeural")

    bot.send_message(uid, "🎙️ جاري تحضير الأخبار الصوتية...")

    # جلب آخر الأخبار من RSS
    feeds = RSS.get(lang, [])
    news_titles = []
    for feed_url in feeds[:5]:
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:8]:
                title = getattr(entry, 'title', '').strip()
                if title and len(title) > 15:
                    news_titles.append(title)
                if len(news_titles) >= count * 3:
                    break
        except Exception:
            pass
        if len(news_titles) >= count * 3:
            break

    # إزالة المكررة وأخذ العدد المطلوب
    unique = []
    for t in news_titles:
        dup = any(_is_similar_title(t, u) for u in unique)
        if not dup:
            unique.append(t)
        if len(unique) >= count:
            break

    if not unique:
        bot.send_message(uid, "⚠️ لم أجد أخبار متاحة الآن. حاول لاحقاً.")
        return

    # تجميع النص الصوتي
    intro_map = {
        "العربية 🇮🇶": "مرحباً، إليك آخر الأخبار.",
        "English 🇬🇧": "Hello, here are the latest news.",
        "Русский 🇷🇺": "Привет, вот последние новости.",
        "فارسی 🇮🇷": "سلام، آخرین اخبار را بشنوید.",
        "Türkçe 🇹🇷": "Merhaba, işte son haberler.",
        "Deutsch 🇩🇪": "Hallo, hier sind die neuesten Nachrichten.",
        "Español 🇲🇽": "Hola, aquí están las últimas noticias.",
        "Italiano 🇮🇹": "Ciao, ecco le ultime notizie.",
    }
    separator_map = {
        "العربية 🇮🇶": ". الخبر التالي: ",
        "English 🇬🇧": ". Next: ",
        "Русский 🇷🇺": ". Следующее: ",
        "فارسی 🇮🇷": ". خبر بعدی: ",
        "Türkçe 🇹🇷": ". Sonraki: ",
        "Deutsch 🇩🇪": ". Als nächstes: ",
        "Español 🇲🇽": ". A continuación: ",
        "Italiano 🇮🇹": ". Prossimo: ",
    }
    intro = intro_map.get(lang, "Here are the latest news.")
    sep = separator_map.get(lang, ". Next: ")
    full_text = intro + " " + sep.join(unique)

    # توليد الصوت وإرساله
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        success = _tts_generate(full_text, voice, tmp_path)
        if not success or not os.path.exists(tmp_path):
            bot.send_message(uid, "⚠️ فشل توليد الصوت. حاول مرة أخرى.")
            return
        with open(tmp_path, 'rb') as audio:
            news_text = "\n".join([f"{i+1}. {t}" for i, t in enumerate(unique)])
            bot.send_voice(uid, audio, caption=f"🎙️ *أخبار صوتية* — {count} أخبار\n\n{news_text[:800]}", parse_mode="Markdown")
        os.unlink(tmp_path)
    except Exception as e:
        bot.send_message(uid, f"⚠️ خطأ في الأخبار الصوتية: {str(e)[:100]}")

# ======== تتبع عالمي للأخبار المُرسلة لكل لغة ========
# بدلاً من تخزين 500 رابط لكل مستخدم (20 ألف × 500 = 10 مليون رابط)
# نخزن مجموعة واحدة لكل لغة — إذا أُرسل الخبر للغة العربية مرة واحدة لا يُرسل أبداً لأي مستخدم عربي
_GLOBAL_SENT_FILE   = "global_sent_news.json"
_SPORTS_CACHE_FILE  = "sports_match_cache.json"
_global_sent_news = {}          # lang -> set of links
_global_sent_lock = threading.Lock()

def _load_global_sent_news():
    """
    يحمّل روابط الأخبار المُرسَلة من الملف المحفوظ.
    يُحتفظ بآخر 1000 رابط لكل لغة لمنع التكرار حتى بعد إعادة تشغيل Heroku.
    فقط إذا كان الملف أقدم من 6 ساعات نبدأ من صفر (تنشيط طبيعي بعد توقف طويل).
    """
    global _global_sent_news
    _global_sent_news = {}
    try:
        if not os.path.exists(_GLOBAL_SENT_FILE):
            _logger.info("global_sent_news.json غير موجود — ابتداء جديد")
            return
        file_age_secs = time.time() - os.path.getmtime(_GLOBAL_SENT_FILE)
        # 6 ساعات = 21600 ثانية — بعد هذا الوقت نبدأ من جديد لضمان إرسال الأخبار
        if file_age_secs > 21600:
            _logger.info(f"global_sent_news.json أقدم من 6 ساعات ({file_age_secs/3600:.1f}س) — ابتداء جديد")
            return
        with open(_GLOBAL_SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # آخر 1000 رابط لكل لغة — كافٍ لمنع التكرار دون حجب الأخبار الجديدة
        _global_sent_news = {lang: set(links[-1000:]) for lang, links in data.items()}
        total = sum(len(s) for s in _global_sent_news.values())
        _logger.info(f"✅ تم تحميل global_sent_news: {total} رابط لـ {len(_global_sent_news)} لغة (عمر الملف: {file_age_secs/60:.0f}د)")
    except Exception as e:
        _logger.warning(f"فشل تحميل global_sent_news: {e}")
        _global_sent_news = {}

def _save_global_sent_news():
    try:
        with _global_sent_lock:
            data = {lang: list(links)[-5000:] for lang, links in _global_sent_news.items()}
        with open(_GLOBAL_SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

# ======== feedparser بـ timeout (30 ثانية) لتجنب التعليق اللانهائي ========
def _parse_feed(url, timeout=30):
    result = [None]
    def _fetch():
        try:
            result[0] = feedparser.parse(url)
        except Exception:
            pass
    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]


# ======== جلب RSS متوازي مع وقت النشر الحقيقي ========
_RSS_FRESHNESS_MINUTES = 120   # نافذة الحداثة: 120 دقيقة (ساعتان)
_RSS_FETCH_TIMEOUT     = 12    # ثواني لكل feed


def _fetch_one_feed(feed_url):
    """
    يجلب feed واحد ويعيد قائمة entries مرتبة حسب وقت النشر.
    كل entry: dict بـ link, title, summary, published_dt, feed_url
    """
    try:
        parsed = _parse_feed(feed_url, timeout=_RSS_FETCH_TIMEOUT)
        if not parsed or not parsed.entries:
            return []
        entries_out = []
        for item in parsed.entries[:40]:
            link  = getattr(item, 'link',  None)
            title = getattr(item, 'title', '').strip()
            if not link or not title:
                continue
            summ  = getattr(item, 'summary', '') or getattr(item, 'description', '')
            # استخراج وقت النشر الفعلي
            pub_struct = (getattr(item, 'published_parsed', None)
                          or getattr(item, 'updated_parsed', None))
            if pub_struct:
                try:
                    import calendar
                    pub_dt = datetime.datetime.utcfromtimestamp(
                        calendar.timegm(pub_struct)
                    )
                except Exception:
                    pub_dt = None
            else:
                pub_dt = None
            entries_out.append({
                "link":         link,
                "title":        title,
                "summary":      summ,
                "published_dt": pub_dt,   # datetime UTC أو None
                "feed_url":     feed_url,
            })
        # رتّب من الأحدث للأقدم
        entries_out.sort(
            key=lambda x: x["published_dt"] or datetime.datetime(2000, 1, 1),
            reverse=True
        )
        return entries_out
    except Exception:
        return []


def _parallel_fetch_feeds(feed_urls, max_workers=8):
    """
    يجلب قائمة feeds بالتوازي ويدمج النتائج مرتبةً بوقت النشر.
    """
    all_entries = []
    workers = min(max_workers, len(feed_urls) or 1, 8)  # حد أقصى 8 خيوط
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_fetch_one_feed, url): url for url in feed_urls}
            for future in as_completed(futures, timeout=_RSS_FETCH_TIMEOUT + 5):
                try:
                    all_entries.extend(future.result())
                except Exception:
                    pass
    except RuntimeError:
        # خيوط النظام مستنزفة — نجلب بشكل متسلسل كبديل
        for url in feed_urls[:5]:
            try:
                all_entries.extend(_fetch_one_feed(url))
            except Exception:
                pass
    # رتّب الكل من الأحدث للأقدم
    all_entries.sort(
        key=lambda x: x["published_dt"] or datetime.datetime(2000, 1, 1),
        reverse=True
    )
    return all_entries


def _is_fresh(pub_dt, window_minutes=_RSS_FRESHNESS_MINUTES):
    """هل الخبر منشور خلال النافذة الزمنية المحددة؟"""
    if pub_dt is None:
        return True   # مجهول الوقت → نقبله (ربما مصدر لا يُدرج الوقت)
    now_utc = datetime.datetime.utcnow()
    age = (now_utc - pub_dt).total_seconds() / 60
    return age <= window_minutes


_PUB_TIME_I18N = {
    "العربية 🇮🇶": ("منذ لحظات", "منذ {} دقيقة", "منذ {} ساعة"),
    "English 🇬🇧":  ("just now",    "{} min ago",    "{} hr ago"),
    "Русский 🇷🇺":  ("только что",  "{} мин назад",  "{} ч назад"),
    "فارسی 🇮🇷":    ("لحظاتی پیش", "{} دقیقه پیش", "{} ساعت پیش"),
    "हिन्दी 🇮🇳":   ("अभी",        "{} मिनट पहले",  "{} घंटे पहले"),
    "Türkçe 🇹🇷":   ("az önce",    "{} dk önce",    "{} sa önce"),
    "Deutsch 🇩🇪":  ("gerade eben", "vor {} Min",    "vor {} Std"),
    "Español 🇲🇽":  ("hace un momento", "hace {} min", "hace {} h"),
    "Português 🇧🇷":("há pouco",   "há {} min",     "há {} h"),
    "Italiano 🇮🇹": ("or ora",     "{} min fa",     "{} ore fa"),
    "Українська 🇺🇦":("щойно",    "{} хв тому",    "{} год тому"),
    "اردو 🇵🇰":     ("ابھی",       "{} منٹ پہلے",   "{} گھنٹے پہلے"),
}

def _format_pub_time(pub_dt, lang=None):
    """
    يُحوّل وقت النشر UTC إلى نص بسيط بلغة المستخدم.
    يحسب الفرق من لحظة الاستدعاء.
    إذا كان pub_dt فارغاً يُعرض "منذ لحظات" لأن الخبر اجتاز فلتر الحداثة.
    """
    if pub_dt is None:
        patterns = _PUB_TIME_I18N.get(lang) or _PUB_TIME_I18N["العربية 🇮🇶"]
        return f"🕐 {patterns[0]}"
    try:
        now_utc  = datetime.datetime.utcnow()
        diff_min = int((now_utc - pub_dt).total_seconds() / 60)
        if diff_min < 0:
            diff_min = 0

        # اختر نمط اللغة أو العربية كاحتياطي
        patterns = _PUB_TIME_I18N.get(lang) or _PUB_TIME_I18N["العربية 🇮🇶"]
        just_now_txt, min_fmt, hr_fmt = patterns

        if diff_min < 2:
            label = just_now_txt
        elif diff_min < 60:
            label = min_fmt.format(diff_min)
        elif diff_min < 1440:
            label = hr_fmt.format(diff_min // 60)
        else:
            # تاريخ بالتوقيت المحلي للمستخدم (العراق UTC+3)
            local_dt = pub_dt + datetime.timedelta(hours=3)
            label = local_dt.strftime("%d/%m %H:%M")

        return f"🕐 {label}"
    except Exception:
        return ""

# ======== مفاتيح البوت ========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8606492099:AAGAh8TFt4FexlnqNcH2IB_GP8DERvOjhJU")
WEATHER_KEY = os.environ.get("WEATHER_KEY", "18a7801721693e772bbada4687d03e43")
NEWS_KEY = os.environ.get("NEWS_KEY", "98b2295d1a034076913e0c0e2aa64fa4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "5149213983"))

bot = telebot.TeleBot(BOT_TOKEN)

# ======== ذاكرة تخزين مؤقت عالمية لـ RSS (TTL = 55 ثانية) ========
# تمنع إعادة جلب نفس الـ feed في كل دورة 30-ثانية
_GLOBAL_RSS_CACHE_TTL = 120   # ثانية — الـ prefetcher يُجدّد كل 90 ثانية فكفاية
_global_rss_cache     = {}    # url -> (entries_list, fetched_at_timestamp)
_global_rss_cache_lock = threading.Lock()


def _get_cached_feed(feed_url):
    """يعيد entries من الذاكرة المؤقتة إذا لم تنته صلاحيتها، وإلا يجلب ويخزّن."""
    now = time.time()
    with _global_rss_cache_lock:
        cached = _global_rss_cache.get(feed_url)
        if cached:
            entries, fetched_at = cached
            if (now - fetched_at) < _GLOBAL_RSS_CACHE_TTL:
                return entries   # استخدام الذاكرة المؤقتة
    # منتهية أو غير موجودة — اجلب جديدة
    entries = _fetch_one_feed(feed_url)
    with _global_rss_cache_lock:
        _global_rss_cache[feed_url] = (entries, now)
        # تنظيف الذاكرة من الـ feeds القديمة (> 10 دقائق)
        stale = [u for u, (_, t) in _global_rss_cache.items() if now - t > 600]
        for u in stale:
            _global_rss_cache.pop(u, None)
    return entries


def _rss_prefetcher():
    """
    🔑 المحمّل المسبق للـ RSS (الحل الجذري لمشكلة البطء):
    يجلب كل feeds جميع اللغات دفعةً واحدة في الخلفية كل 90 ثانية.
    broadcast_news يقرأ من الكاش مباشرة — لا يستغرق إلا ثوانٍ.
    """
    all_urls = set()
    try:
        for lang_feeds in DEFAULT_RSS.values():
            all_urls.update(lang_feeds)
    except Exception:
        pass
    if not all_urls:
        return
    now = time.time()
    with _global_rss_cache_lock:
        stale_urls = [u for u in all_urls
                      if u not in _global_rss_cache
                      or (now - _global_rss_cache[u][1]) >= _GLOBAL_RSS_CACHE_TTL]
    if not stale_urls:
        _logger.debug("✅ _rss_prefetcher: كل الـ feeds محدّثة (%d)", len(all_urls))
        return

    _logger.info("🔄 _rss_prefetcher: يجلب %d feed من أصل %d", len(stale_urls), len(all_urls))
    t0 = time.time()

    def _store(url):
        entries = _fetch_one_feed(url)
        with _global_rss_cache_lock:
            _global_rss_cache[url] = (entries, time.time())

    # max_workers=8 لمنع استنزاف خيوط Heroku (حد النظام ~256 خيط)
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_store, url): url for url in stale_urls}
            for fut in as_completed(futs, timeout=_RSS_FETCH_TIMEOUT + 5):
                try:
                    fut.result()
                except Exception:
                    pass
    except RuntimeError:
        # خيوط النظام مستنزفة — نجلب بشكل متسلسل كبديل
        for url in stale_urls[:10]:
            try:
                _store(url)
            except Exception:
                pass

    with _global_rss_cache_lock:
        total_entries = sum(len(v[0]) for v in _global_rss_cache.values())
    _logger.info(
        "✅ _rss_prefetcher: انتهى خلال %.1f ثانية — %d خبر في الكاش من %d feed",
        time.time() - t0, total_entries, len(_global_rss_cache)
    )


# ======== حدّ أقصى لأخبار كل دورة بث (لمنع فيضان القائمة) ========
_MAX_NEWS_PER_CYCLE = 9999  # بدون حد كلي

# ======== SQLite للمستخدمين ========
DB_FILE = "bot_data.db"
_db_lock = threading.Lock()

def _init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS users_store (
        uid TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS channels_store (
        chat_id INTEGER PRIMARY KEY,
        data TEXT NOT NULL
    )""")
    conn.commit()
    return conn

_db_conn = _init_db()

def _db_load_users():
    result = {}
    with _db_lock:
        rows = _db_conn.execute("SELECT uid, data FROM users_store").fetchall()
    for uid, raw in rows:
        try:
            d = json.loads(raw)
            if "sent_news" in d:
                d["sent_news"] = set(d["sent_news"])
            result[uid] = d
        except:
            pass
    return result

def _db_save_user(uid, user_data):
    d = dict(user_data)
    if "sent_news" in d:
        d["sent_news"] = list(d["sent_news"])[-5000:]
    raw = json.dumps(d, ensure_ascii=False)
    with _db_lock:
        _db_conn.execute(
            "INSERT OR REPLACE INTO users_store (uid, data) VALUES (?, ?)",
            (str(uid), raw)
        )
        _db_conn.commit()

def _db_save_all_users(users_dict):
    rows = []
    for uid, user_data in users_dict.items():
        d = dict(user_data)
        if "sent_news" in d:
            d["sent_news"] = list(d["sent_news"])[-5000:]
        rows.append((str(uid), json.dumps(d, ensure_ascii=False)))
    with _db_lock:
        _db_conn.executemany(
            "INSERT OR REPLACE INTO users_store (uid, data) VALUES (?, ?)",
            rows
        )
        _db_conn.commit()

def _migrate_users_from_json():
    if not os.path.exists(USERS_FILE):
        return
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if old_data:
            _db_save_all_users(old_data)
            os.rename(USERS_FILE, USERS_FILE + ".migrated")
            print("تم نقل بيانات المستخدمين من JSON إلى SQLite")
    except Exception as e:
        print(f"خطأ في هجرة البيانات: {e}")

# ======== SQLite للقنوات والمجموعات ========
def _db_load_channels():
    """تحميل القنوات والمجموعات من SQLite."""
    result = []
    try:
        with _db_lock:
            rows = _db_conn.execute("SELECT chat_id, data FROM channels_store").fetchall()
        for chat_id, raw in rows:
            try:
                d = json.loads(raw)
                if "sent_news" in d:
                    d["sent_news"] = list(d["sent_news"])
                result.append(d)
            except Exception:
                pass
    except Exception as e:
        _logger.error("خطأ في تحميل القنوات من SQLite: %s", e)
    return result

def _db_save_channel(ch_data):
    """حفظ قناة/مجموعة واحدة في SQLite."""
    try:
        d = dict(ch_data)
        if "sent_news" in d:
            d["sent_news"] = list(d["sent_news"])[-2000:]
        raw = json.dumps(d, ensure_ascii=False)
        with _db_lock:
            _db_conn.execute(
                "INSERT OR REPLACE INTO channels_store (chat_id, data) VALUES (?, ?)",
                (int(d["id"]), raw)
            )
            _db_conn.commit()
    except Exception as e:
        _logger.error("خطأ في حفظ القناة %s: %s", ch_data.get("id"), e)

def _db_save_all_channels(ch_list):
    """حفظ كل القنوات في SQLite."""
    try:
        rows = []
        for ch_data in ch_list:
            d = dict(ch_data)
            if "sent_news" in d:
                d["sent_news"] = list(d["sent_news"])[-2000:]
            rows.append((int(d["id"]), json.dumps(d, ensure_ascii=False)))
        with _db_lock:
            _db_conn.executemany(
                "INSERT OR REPLACE INTO channels_store (chat_id, data) VALUES (?, ?)",
                rows
            )
            _db_conn.commit()
    except Exception as e:
        _logger.error("خطأ في حفظ القنوات: %s", e)

def _db_delete_channel(chat_id):
    """حذف قناة/مجموعة من SQLite."""
    try:
        with _db_lock:
            _db_conn.execute("DELETE FROM channels_store WHERE chat_id = ?", (int(chat_id),))
            _db_conn.commit()
    except Exception as e:
        _logger.error("خطأ في حذف القناة %s: %s", chat_id, e)

def _migrate_channels_from_json():
    """نقل القنوات من JSON إلى SQLite عند أول تشغيل."""
    channels_file = "channels.json"
    if not os.path.exists(channels_file):
        return
    try:
        with open(channels_file, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if old_data:
            _db_save_all_channels(old_data)
            os.rename(channels_file, channels_file + ".migrated")
            _logger.info("✅ تم نقل %d قناة من JSON إلى SQLite", len(old_data))
    except Exception as e:
        _logger.error("خطأ في هجرة القنوات: %s", e)

# ======== كاش الطقس (10 دقائق لكل مدينة) ========
_weather_cache = {}
_WEATHER_CACHE_TTL = 600

def _get_cached_weather(city, lang_code):
    key = f"{city}_{lang_code}"
    if key in _weather_cache:
        data, ts = _weather_cache[key]
        if (datetime.datetime.now() - ts).total_seconds() < _WEATHER_CACHE_TTL:
            return data
    return None

def _set_cached_weather(city, lang_code, data):
    _weather_cache[f"{city}_{lang_code}"] = (data, datetime.datetime.now())

def _fetch_weather_cached(city, lang_code):
    d = _get_cached_weather(city, lang_code)
    if d:
        return d
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
    try:
        d = requests.get(url, timeout=10).json()
        if d.get("cod") == 200:
            _set_cached_weather(city, lang_code, d)
            return d
    except Exception:
        pass
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# IMMORTAL DELIVERY ENGINE — تصنيف الأخطاء + ضمان التسليم + ضبط الحمل التلقائي
# ═══════════════════════════════════════════════════════════════════════════════

# ── ثوابت تصنيف الأخطاء ─────────────────────────────────────────────────────
_ERR_TELEGRAM_API  = "telegram_api"   # خطأ من API تيليغرام
_ERR_DELIVERY      = "delivery"       # فشل التسليم (مستخدم حجب / حذف)
_ERR_PARSE         = "parse"          # خطأ Markdown/HTML
_ERR_RATE_LIMIT    = "rate_limit"     # 429 Too Many Requests
_ERR_NETWORK       = "network"        # انقطاع الشبكة
_ERR_RESOURCE      = "resource"       # CPU/RAM مرتفع
_ERR_UNKNOWN       = "unknown"        # غير معروف

# ── قائمة الـ chats المعطّلة مؤقتاً (blacklist) ─────────────────────────────
_dead_chats: dict = {}        # chat_id → timestamp_blacklisted
_dead_chats_lock  = threading.Lock()
_DEAD_CHAT_TTL    = 86400     # يُعاد المحاولة بعد 24 ساعة

# ── إحصاءات التسليم المتقدمة ──────────────────────────────────────────────────
_delivery_stats: dict = {
    "sent_ok":        0,
    "sent_fail":      0,
    "retried":        0,
    "rate_limited":   0,
    "auto_resolved":  0,    # مشاكل حُلّت تلقائياً
    "admin_alerted":  0,    # مشاكل أُبلغ عنها للأدمن
}
_delivery_stats_lock = threading.Lock()

def _classify_error(err_str: str) -> str:
    """
    يصنّف الخطأ إلى أحد الأنواع المعروفة.
    يُعيد أحد ثوابت _ERR_* لاتخاذ إجراء مخصص.
    """
    e = err_str.lower()
    if "429" in e or "too many requests" in e or "flood" in e:
        return _ERR_RATE_LIMIT
    if any(x in e for x in ("bot was blocked", "user is deactivated",
                             "chat not found", "peer_id_invalid",
                             "kicked", "not a member", "forbidden")):
        return _ERR_DELIVERY
    if "can't parse" in e or "parse entities" in e or ("400" in e and "parse" in e):
        return _ERR_PARSE
    if any(x in e for x in ("network", "timeout", "connection", "timed out",
                             "connection reset", "connection aborted", "eof")):
        return _ERR_NETWORK
    if any(x in e for x in ("400", "401", "403", "500", "502", "503")):
        return _ERR_TELEGRAM_API
    return _ERR_UNKNOWN

def _is_dead_chat(chat_id) -> bool:
    """هل هذا الـ chat محظور مؤقتاً بسبب فشل متكرر؟"""
    with _dead_chats_lock:
        ts = _dead_chats.get(str(chat_id))
        if ts is None:
            return False
        if time.time() - ts > _DEAD_CHAT_TTL:
            del _dead_chats[str(chat_id)]
            return False
        return True

def _blacklist_chat(chat_id):
    """يُدرج الـ chat في القائمة السوداء مؤقتاً."""
    with _dead_chats_lock:
        _dead_chats[str(chat_id)] = time.time()

def _smart_admin_alert(func_name: str, error: str, chat_id=None, resolution: str = ""):
    """
    يُرسل تنبيهاً للأدمن فقط عندما يفشل الحل التلقائي.
    يتضمن: نوع الخطأ + الإجراء المتخذ + اقتراح الحل.
    """
    with _delivery_stats_lock:
        _delivery_stats["admin_alerted"] += 1
    err_type = _classify_error(error)
    suggestions = {
        _ERR_RATE_LIMIT:   "⏳ تلغرام يحد الإرسال — انخفض معدل البث مؤقتاً.",
        _ERR_DELIVERY:     "🚫 مستخدم حذف/حجب البوت — تم تعطيل إشعاراته.",
        _ERR_PARSE:        "✏️ خطأ تنسيق — أُرسل بدون Markdown.",
        _ERR_NETWORK:      "🌐 انقطاع شبكة — البوت يُعيد المحاولة تلقائياً.",
        _ERR_TELEGRAM_API: "⚙️ خطأ API — تحقق من الـ token وحالة خوادم تيليغرام.",
        _ERR_UNKNOWN:      "❓ خطأ غير معروف — راجع السجل.",
    }
    msg = (
        f"🤖 *تنبيه ذكي — فشل التعافي التلقائي*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📍 الوظيفة: `{func_name}`\n"
        f"🏷 نوع الخطأ: `{err_type}`\n"
        f"💬 التفاصيل: `{error[:200]}`\n"
        + (f"👤 Chat: `{chat_id}`\n" if chat_id else "")
        + (f"⚙️ الإجراء التلقائي: {resolution}\n" if resolution else "")
        + f"💡 اقتراح: {suggestions.get(err_type, '—')}"
    )
    try:
        bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
    except Exception:
        pass

# ── ضبط سرعة البث تلقائياً بحسب حمل النظام ─────────────────────────────────
_dynamic_delay: float = 0.05   # التأخير بين رسائل الـ queue (ثانية)
_dynamic_delay_lock   = threading.Lock()

def _update_dynamic_delay():
    """
    يُعدّل التأخير بين الرسائل بحسب حمل النظام والـ queue:
    - حمل طبيعي  → 0.05s (20 رسالة/ثانية)
    - حمل متوسط  → 0.10s (10 رسالة/ثانية)
    - حمل عالٍ   → 0.25s (4 رسائل/ثانية)
    - حمل حرج    → 0.50s (2 رسالة/ثانية)
    """
    global _dynamic_delay
    ram = _sys_health.get("ram_pct", 0)
    q   = _send_queue.qsize() if hasattr(_send_queue, "qsize") else 0
    q_pct = q / _QUEUE_MAX_SIZE * 100 if _QUEUE_MAX_SIZE > 0 else 0
    if ram > 88 or q_pct > 80:
        delay = 0.50
    elif ram > 75 or q_pct > 60:
        delay = 0.25
    elif ram > 65 or q_pct > 40:
        delay = 0.10
    else:
        delay = 0.05
    with _dynamic_delay_lock:
        _dynamic_delay = delay

def _dynamic_delay_adjuster():
    """خيط يُحدّث التأخير الديناميكي كل 30 ثانية."""
    while True:
        time.sleep(30)
        try:
            _update_dynamic_delay()
        except Exception:
            pass

threading.Thread(
    target=_dynamic_delay_adjuster,
    daemon=True,
    name="DynamicDelayAdjuster"
).start()

# ═══════════════════════════════════════════════════════════════════════════════
# نهاية IMMORTAL DELIVERY ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

# ======== قائمة الإرسال — محدودة الحجم لمنع امتلاء الذاكرة ========
_QUEUE_MAX_SIZE  = 4000   # حدّ أقصى للرسائل في الانتظار
_send_queue      = queue.Queue(maxsize=_QUEUE_MAX_SIZE)
_queue_dropped   = 0      # عدد الرسائل التي سقطت بسبب الامتلاء (للإحصاء)
_queue_thread    = None   # الخيط الحالي (يُراقَب ويُعاد إذا مات)


def _queue_worker():
    """
    ═══ IMMORTAL QUEUE WORKER ═══
    مُشغّل الإرسال المحسّن — يستخدم:
    • تصنيف الأخطاء (classify) لاتخاذ قرار مخصص لكل نوع
    • Exponential backoff حقيقي (1s → 2s → 4s → 8s → 16s)
    • تنبيه الأدمن فقط عند فشل الحل التلقائي
    • ضبط سرعة الإرسال ديناميكياً بحسب حمل النظام
    • قائمة سوداء مؤقتة للـ chats التي تفشل باستمرار
    """
    while True:
        try:
            chat_id, text, kwargs = _send_queue.get(timeout=1)

            # ── تخطّ الـ chats الميتة مؤقتاً ──────────────────────────
            if _is_dead_chat(chat_id):
                _send_queue.task_done()
                continue

            sent          = False
            auto_resolved = False
            last_err      = ""

            for attempt in range(5):
                try:
                    bot.send_message(chat_id, text, **kwargs)
                    sent = True
                    with _delivery_stats_lock:
                        _delivery_stats["sent_ok"] += 1
                        if attempt > 0:
                            _delivery_stats["retried"] += 1
                    break

                except Exception as e:
                    err_str   = str(e)
                    last_err  = err_str
                    err_type  = _classify_error(err_str)

                    # ── Rate Limit: انتظر حسب تعليمات تيليغرام ────────
                    if err_type == _ERR_RATE_LIMIT:
                        with _delivery_stats_lock:
                            _delivery_stats["rate_limited"] += 1
                        try:
                            retry_after = int(
                                getattr(e, 'result_json', {}).get(
                                    'parameters', {}).get('retry_after', None)
                                or _re.search(r'retry after (\d+)', err_str, _re.I).group(1)
                            )
                        except Exception:
                            retry_after = 30
                        _logger.debug("⏳ rate_limit: انتظار %ds", retry_after + 1)
                        time.sleep(retry_after + 1)
                        auto_resolved = True
                        # لا نكسر الحلقة — نُعيد المحاولة

                    # ── فشل التسليم: عطّل المستخدم تلقائياً ──────────
                    elif err_type == _ERR_DELIVERY:
                        try:
                            uid_str = str(chat_id)
                            if uid_str in users:
                                users[uid_str]["notifications"] = False
                                _db_save_user(uid_str, users[uid_str])
                            _blacklist_chat(chat_id)
                        except Exception:
                            pass
                        auto_resolved = True
                        with _delivery_stats_lock:
                            _delivery_stats["auto_resolved"] += 1
                        break   # لا نُعيد المحاولة — مستخدم غير متاح

                    # ── خطأ Parse: أرسل بدون تنسيق ───────────────────
                    elif err_type == _ERR_PARSE:
                        try:
                            plain_kw = {k: v for k, v in kwargs.items()
                                        if k != 'parse_mode'}
                            bot.send_message(chat_id, text, **plain_kw)
                            sent = True
                            auto_resolved = True
                            with _delivery_stats_lock:
                                _delivery_stats["sent_ok"]       += 1
                                _delivery_stats["auto_resolved"] += 1
                        except Exception:
                            pass
                        break

                    # ── خطأ شبكة: exponential backoff ─────────────────
                    elif err_type == _ERR_NETWORK:
                        wait = min(1 * (2 ** attempt), 32)   # 1→2→4→8→16→32
                        _logger.debug("🌐 network error attempt=%d wait=%.1fs", attempt, wait)
                        time.sleep(wait)
                        auto_resolved = True

                    # ── خطأ API عام: exponential backoff ──────────────
                    elif err_type == _ERR_TELEGRAM_API:
                        wait = min(2 * (2 ** attempt), 60)   # 2→4→8→16→32→60
                        _logger.debug("⚙️ telegram_api error attempt=%d wait=%.1fs", attempt, wait)
                        time.sleep(wait)

                    # ── غير معروف: exponential backoff متحفظ ──────────
                    else:
                        wait = min(1 * (2 ** attempt), 16)   # 1→2→4→8→16
                        time.sleep(wait)

            # ── إحصاءات الفشل + تنبيه الأدمن إذا فشل الحل التلقائي ──
            if not sent:
                with _delivery_stats_lock:
                    _delivery_stats["sent_fail"] += 1
                _track_error("_queue_worker", None)
                if not auto_resolved:
                    _smart_admin_alert(
                        func_name  = "_queue_worker",
                        error      = last_err,
                        chat_id    = chat_id,
                        resolution = "فشل بعد 5 محاولات — لم يُحل تلقائياً"
                    )

            _send_queue.task_done()

            # ── تأخير ديناميكي بحسب حمل النظام ───────────────────────
            with _dynamic_delay_lock:
                _sleep_t = _dynamic_delay
            time.sleep(_sleep_t)

        except queue.Empty:
            continue
        except Exception as _qe:
            _logger.debug("_queue_worker loop error: %s", _qe)
            time.sleep(1)
            continue


def _start_queue_worker():
    """يبدأ خيط إرسال جديد."""
    global _queue_thread
    t = threading.Thread(target=_queue_worker, daemon=True, name="SendQueueWorker")
    t.start()
    _queue_thread = t


_start_queue_worker()


def _queue_watchdog():
    """
    مراقب يعمل في خلفية: يتحقق كل 10 ثواني أن خيط الإرسال حي.
    إذا مات لأي سبب → يعيد تشغيله فوراً.
    """
    while True:
        time.sleep(10)
        try:
            if _queue_thread is None or not _queue_thread.is_alive():
                print("⚠️ خيط الإرسال مات — يُعاد تشغيله...")
                _start_queue_worker()
        except Exception:
            pass


threading.Thread(target=_queue_watchdog, daemon=True, name="QueueWatchdog").start()


def queue_send(chat_id, text, **kwargs):
    """
    يضع رسالة في القائمة.
    إذا كانت القائمة ممتلئة، يُسقط الرسالة القديمة لإفساح مجال للجديدة.
    لا يُعلّق البوت أبداً بسبب القائمة.
    """
    global _queue_dropped
    try:
        _send_queue.put_nowait((chat_id, text, kwargs))
    except queue.Full:
        # القائمة ممتلئة — احذف أقدم رسالة وأضف الجديدة
        try:
            _send_queue.get_nowait()
            _send_queue.task_done()
            _queue_dropped += 1
        except Exception:
            pass
        try:
            _send_queue.put_nowait((chat_id, text, kwargs))
        except Exception:
            pass

# ======== ملفات الحفظ ========
USERS_FILE = "users.json"
STATS_FILE = "stats.json"
BANNED_FILE = "banned.json"
RSS_FILE = "rss.json"
CUSTOM_TG_CHANNELS_FILE = "custom_tg_channels.json"  # قنوات تيليغرام أضافها الأدمن ديناميكياً
ADMINS_FILE = "admins.json"
KEYWORDS_FILE = "keywords.json"
TRACK_FILE = "tracking.json"
CHANNELS_FILE = "channels.json"
BLACKLIST_FILE = "blacklist.json"
READ_STATS_FILE = "read_stats.json"
BROADCAST_SETTINGS_FILE = "broadcast_settings.json"
NEWS_SETTINGS_FILE = "news_settings.json"
INBOX_FILE = "inbox.json"
RATINGS_FILE = "ratings.json"
WELCOME_FILE = "welcome.json"

# ======== اسم البوت ========
BOT_USERNAME = "Iraqnowbot"

# ======== تحميل وحفظ البيانات ========
def load_json(file, default):
    try:
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if file == USERS_FILE:
                for uid in data:
                    if "sent_news" in data[uid]:
                        data[uid]["sent_news"] = set(data[uid]["sent_news"])
            return data
    except:
        return default

def save_json(file, data):
    try:
        save_data = data
        if file == USERS_FILE:
            save_data = {}
            for uid, val in data.items():
                save_data[uid] = dict(val)
                if "sent_news" in save_data[uid]:
                    save_data[uid]["sent_news"] = list(save_data[uid]["sent_news"])
        with open(file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        notify_admin_error(f"خطأ في حفظ البيانات: {e}")

_migrate_users_from_json()
_load_global_sent_news()
users = _db_load_users()
banned = load_json(BANNED_FILE, [])
banned = [int(b) for b in banned]

stats = load_json(STATS_FILE, {
    "total_users": 0,
    "daily_users": {},
    "button_presses": {},
    "countries_count": {},
    "languages_count": {},
    "premium_users": [],
    "revenue": 0.0
})

# ======== قائمة الأدمن المتعددين ========
extra_admins = load_json(ADMINS_FILE, [])
extra_admins = [int(a) for a in extra_admins]
ADMINS = [ADMIN_ID] + extra_admins

def is_admin(uid):
    return int(uid) == ADMIN_ID or int(uid) in extra_admins

def save_extra_admins():
    save_json(ADMINS_FILE, extra_admins)

# ======== القنوات والمجموعات ========
# كل عنصر: {"id": chat_id, "title": "اسم القناة", "type": "channel"/"group", "lang": "العربية 🇮🇶"}
# مخزنة في SQLite لضمان البقاء بعد إعادة تشغيل Heroku
_migrate_channels_from_json()   # نقل من JSON إلى SQLite عند أول تشغيل
channels_groups = _db_load_channels()
if not channels_groups:         # fallback: إذا SQLite فارغ، حاول JSON
    channels_groups = load_json(CHANNELS_FILE, [])

# =====================================================================
# ==================== نظام الرياضة ==================================
# =====================================================================
SPORTS_LEAGUES = {
    # ══════════════ كرة القدم ══════════════
    "pl":           {"name": "الدوري الإنجليزي الممتاز",  "espn": "soccer/eng.1",                  "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "sport": "football"},
    "laliga":       {"name": "الدوري الإسباني",            "espn": "soccer/esp.1",                  "flag": "🇪🇸", "sport": "football"},
    "bundesliga":   {"name": "الدوري الألماني",            "espn": "soccer/ger.1",                  "flag": "🇩🇪", "sport": "football"},
    "seriea":       {"name": "الدوري الإيطالي",            "espn": "soccer/ita.1",                  "flag": "🇮🇹", "sport": "football"},
    "ligue1":       {"name": "الدوري الفرنسي",             "espn": "soccer/fra.1",                  "flag": "🇫🇷", "sport": "football"},
    "ucl":          {"name": "دوري أبطال أوروبا",          "espn": "soccer/uefa.champions",         "flag": "🏆", "sport": "football"},
    "uel":          {"name": "الدوري الأوروبي",            "espn": "soccer/uefa.europa",            "flag": "🟠", "sport": "football"},
    "uecl":         {"name": "دوري المؤتمر الأوروبي",      "espn": "soccer/uefa.europa.conf",       "flag": "🟢", "sport": "football"},
    "eredivisie":   {"name": "الدوري الهولندي",            "espn": "soccer/ned.1",                  "flag": "🇳🇱", "sport": "football"},
    "primera":      {"name": "الدوري البرتغالي",           "espn": "soccer/por.1",                  "flag": "🇵🇹", "sport": "football"},
    "superlig":     {"name": "الدوري التركي",              "espn": "soccer/tur.1",                  "flag": "🇹🇷", "sport": "football"},
    "saudi":        {"name": "الدوري السعودي",             "espn": "soccer/ksa.1",                  "flag": "🇸🇦", "sport": "football"},
    "egypt":        {"name": "الدوري المصري",              "espn": "soccer/egy.1",                  "flag": "🇪🇬", "sport": "football"},
    "iraqleague":   {"name": "الدوري العراقي",             "espn": None,                             "flag": "🇮🇶", "sport": "football"},
    "mls":          {"name": "الدوري الأمريكي (MLS)",      "espn": "soccer/usa.1",                  "flag": "🇺🇸", "sport": "football"},
    "libertadores": {"name": "كوبا ليبرتادوريس",          "espn": "soccer/conmebol.libertadores",  "flag": "🌎", "sport": "football"},
    "copaamerica":  {"name": "كوبا أمريكا",                "espn": "soccer/conmebol.copa_america",  "flag": "🌎", "sport": "football"},
    "argentinal":   {"name": "الدوري الأرجنتيني",          "espn": "soccer/arg.1",                  "flag": "🇦🇷", "sport": "football"},
    "brasileirao":  {"name": "الدوري البرازيلي",           "espn": "soccer/bra.1",                  "flag": "🇧🇷", "sport": "football"},
    "wc":           {"name": "كأس العالم FIFA",            "espn": "soccer/fifa.world",             "flag": "🌍", "sport": "football"},
    "acl":          {"name": "دوري أبطال آسيا",            "espn": "soccer/afc.champions",          "flag": "🌏", "sport": "football"},
    "concacaf":     {"name": "CONCACAF أبطال",             "espn": "soccer/concacaf.champions",     "flag": "🌍", "sport": "football"},
    "scottish":     {"name": "الدوري الاسكتلندي",          "espn": "soccer/sco.1",                  "flag": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "sport": "football"},
    "mxleague":     {"name": "الدوري المكسيكي",            "espn": "soccer/mex.1",                  "flag": "🇲🇽", "sport": "football"},
    # ══════════════ كرة السلة ══════════════
    "nba":          {"name": "دوري NBA",                   "espn": "basketball/nba",                "flag": "🏀", "sport": "basketball"},
    "wnba":         {"name": "دوري WNBA (نسائي)",          "espn": "basketball/wnba",               "flag": "🏀", "sport": "basketball"},
    "euroleague":   {"name": "يوروليغ للسلة",              "espn": "basketball/euroleague",         "flag": "🇪🇺", "sport": "basketball"},
    "ncaab":        {"name": "سلة الجامعات الأمريكية",    "espn": "basketball/mens-college-basketball","flag":"🏀","sport":"basketball"},
    # ══════════════ التنس ══════════════
    "atp":          {"name": "ATP - رجال",                 "espn": "tennis/atp.singles",            "flag": "🎾", "sport": "tennis"},
    "wta":          {"name": "WTA - نساء",                 "espn": "tennis/wta.singles",            "flag": "🎾", "sport": "tennis"},
    "wimbledon":    {"name": "ويمبلدون",                   "espn": "tennis/wimbledon",              "flag": "🌿", "sport": "tennis"},
    "usopen_t":     {"name": "يو إس أوبن (تنس)",           "espn": "tennis/us-open",               "flag": "🎾", "sport": "tennis"},
    "frenchopen":   {"name": "رولان غاروس",               "espn": "tennis/french-open",           "flag": "🎾", "sport": "tennis"},
    "ausopen":      {"name": "أستراليان أوبن",             "espn": "tennis/australian-open",       "flag": "🎾", "sport": "tennis"},
    # ══════════════ السيارات ══════════════
    "f1":           {"name": "الفورمولا 1",                "espn": "racing/f1",                     "flag": "🏎️", "sport": "racing"},
    "nascar":       {"name": "ناسكار كاب سيريز",           "espn": "racing/nascar-winston-cup",     "flag": "🏁", "sport": "racing"},
    "nascar_xfin":  {"name": "ناسكار Xfinity",            "espn": "racing/nascar-xfinity",         "flag": "🏁", "sport": "racing"},
    "motogp":       {"name": "موتو جي بي MotoGP",          "espn": "racing/motogp",                 "flag": "🏍️", "sport": "racing"},
    "indycar":      {"name": "إندي كار IndyCar",           "espn": "racing/indycar",                "flag": "🏎️", "sport": "racing"},
    "wrc":          {"name": "WRC - رالي العالم",          "espn": None,                             "flag": "🚗", "sport": "racing"},
    "dakar":        {"name": "رالي داكار",                 "espn": None,                             "flag": "🏜️", "sport": "racing"},
    # ══════════════ الهوكي ══════════════
    "nhl":          {"name": "دوري NHL (هوكي الجليد)",     "espn": "hockey/nhl",                    "flag": "🏒", "sport": "hockey"},
    # ══════════════ البيسبول ══════════════
    "mlb":          {"name": "دوري MLB (بيسبول)",          "espn": "baseball/mlb",                  "flag": "⚾", "sport": "baseball"},
    # ══════════════ كرة القدم الأمريكية ══════════════
    "nfl":          {"name": "دوري NFL (أمريكي)",          "espn": "football/nfl",                  "flag": "🏈", "sport": "american_football"},
    "ncaaf":        {"name": "كرة الجامعات الأمريكية",    "espn": "football/college-football",     "flag": "🏈", "sport": "american_football"},
    # ══════════════ الغولف ══════════════
    "pga":          {"name": "PGA Tour (غولف)",            "espn": "golf/pga",                      "flag": "⛳", "sport": "golf"},
    "lpga":         {"name": "LPGA Tour (غولف نسائي)",    "espn": "golf/lpga",                     "flag": "⛳", "sport": "golf"},
    "masters":      {"name": "بطولة الماسترز",            "espn": "golf/masters",                  "flag": "🏆", "sport": "golf"},
    # ══════════════ كريكيت ══════════════
    "ipl":          {"name": "دوري IPL (كريكيت هندي)",    "espn": "cricket/ipl",                   "flag": "🏏", "sport": "cricket"},
    "icc_wc":       {"name": "كأس العالم كريكيت",          "espn": "cricket/icc.wc",                "flag": "🏏", "sport": "cricket"},
    # ══════════════ كرة اليد ══════════════
    "handball_wc":  {"name": "كأس العالم كرة اليد",       "espn": None,                             "flag": "🤾", "sport": "handball"},
    # ══════════════ الرياضات الإلكترونية ══════════════
    "esports":      {"name": "Esports / رياضات إلكترونية","espn": None,                             "flag": "🎮", "sport": "esports"},
}

SPORTS_NEWS_RSS = {
    "العربية 🇮🇶": [
        "https://feeds.bbci.co.uk/arabic/sport/rss.xml",
        "https://www.france24.com/ar/sport/rss",
        "https://arabic.rt.com/rss/sport/",
        "https://arabic.sport360.com/feed/",
    ],
    "English 🇬🇧": [
        "https://www.skysports.com/rss/12040",
        "https://feeds.bbci.co.uk/sport/football/rss.xml",
    ],
}


def save_channels_groups():
    _db_save_all_channels(channels_groups)
    save_json(CHANNELS_FILE, channels_groups)   # نسخة احتياطية فقط

# ======== القائمة السوداء للكلمات ========
blacklist_words = load_json(BLACKLIST_FILE, [])

def save_blacklist():
    save_json(BLACKLIST_FILE, blacklist_words)

# ======== عداد القراءة ========
read_stats = load_json(READ_STATS_FILE, {"total_opens": 0, "daily": {}})

def save_read_stats():
    save_json(READ_STATS_FILE, read_stats)

# ======== إعدادات توقيت البث ========
broadcast_settings = load_json(BROADCAST_SETTINGS_FILE, {"interval_minutes": 1})

def save_broadcast_settings():
    save_json(BROADCAST_SETTINGS_FILE, broadcast_settings)

news_settings = load_json(NEWS_SETTINGS_FILE, {
    "label": "🚨 خبر عاجل",
    "separator": "━━━━━━━━━━━━━━",
    "signature": "عبر بوت أخبار العالم\n@Iraqnowbot"
})

def save_news_settings():
    save_json(NEWS_SETTINGS_FILE, news_settings)

inbox_messages = load_json(INBOX_FILE, [])

def save_inbox():
    save_json(INBOX_FILE, inbox_messages[-200:])

ratings_data = load_json(RATINGS_FILE, {"entries": [], "bot_sum": 0, "news_sum": 0, "count": 0})

def save_ratings():
    save_json(RATINGS_FILE, ratings_data)

# ======== إحصائيات القنوات ========
# يُحفظ داخل كل عنصر في channels_groups تحت مفتاح "news_sent_count"

# ======== حالة البوت ========
bot_paused = False
_pause_since = None   # وقت آخر إيقاف — لإرسال تذكير للأدمن
pause_message = "🔧 البوت متوقف مؤقتاً، سيعود قريباً."
broadcast_paused = False   # إيقاف/تشغيل البث الإخباري تحديداً (مستقل عن إيقاف البوت كله)
_welcome_data = load_json(WELCOME_FILE, {"override": None})
welcome_override = _welcome_data.get("override", None)

def save_welcome_override():
    save_json(WELCOME_FILE, {"override": welcome_override})

# ======== رابط التواصل ========
CONTACT_LINK = "https://t.me/Ilovedaddyandmommybot"

# ======== تلميحات الاستخدام بعد اختيار اللغة/الدولة ========
USAGE_HINTS = {
    "العربية 🇮🇶": (
        "💡 *طريقة الاستخدام:*\n\n"
        "📰 اضغط *آخر الأخبار* لأحدث الأخبار\n"
        "⚽ اضغط *أخبار الرياضة* لأخبار الملاعب\n"
        "🌤 اضغط *الطقس الآن* لحالة الطقس\n"
        "🕌 اضغط *أوقات الصلاة* لمواقيت الصلاة\n"
        "💱 اضغط *أسعار العملات* لأسعار الصرف\n"
        "💎 اضغط *العملات الرقمية* لأسعار الكريبتو\n"
        "🔍 اضغط *بحث* للبحث السريع في الأخبار\n"
        "🧠 اضغط *بحث عميق* لتحليل أي موضوع بالذكاء الاصطناعي\n"
        "📋 اضغط *ملخص أخبار اليوم* لأبرز أخبار اليوم\n"
        "🔔 اضغط *الإشعارات* لتفعيل/إيقاف التنبيهات\n"
        "🔄 اضغط *الإعدادات* لتغيير اللغة أو البلد"
    ),
    "English 🇬🇧": (
        "💡 *How to use:*\n\n"
        "📰 Tap *Latest News* for top stories\n"
        "⚽ Tap *Sports News* for sports updates\n"
        "🌤 Tap *Weather Now* for weather\n"
        "🕌 Tap *Prayer Times* for daily prayer schedule\n"
        "💱 Tap *Currency Rates* for exchange rates\n"
        "💎 Tap *Crypto* for cryptocurrency prices\n"
        "🔍 Tap *Search* for quick news search\n"
        "🧠 Tap *AI Deep Search* for in-depth AI analysis\n"
        "📋 Tap *Daily Summary* for today's top stories\n"
        "🔔 Tap *Notifications* to toggle alerts\n"
        "🔄 Tap *Settings* to change language or country"
    ),
    "Русский 🇷🇺": (
        "💡 *Как использовать:*\n\n"
        "📰 Нажмите *Новости* для свежих новостей\n"
        "⚽ Нажмите *Спорт* для спортивных новостей\n"
        "🌤 Нажмите *Погода* для погоды\n"
        "🕌 Нажмите *Время молитвы* для расписания\n"
        "💱 Нажмите *Курсы валют* для курсов обмена\n"
        "💎 Нажмите *Крипто* для цен криптовалют\n"
        "🔍 Нажмите *Поиск* для поиска новостей\n"
        "🧠 Нажмите *Глубокий поиск* для анализа ИИ\n"
        "📋 Нажмите *Сводка дня* для главных новостей\n"
        "🔔 Нажмите *Уведомления* для управления оповещениями\n"
        "🔄 Нажмите *Настройки* для смены языка или страны"
    ),
    "فارسی 🇮🇷": (
        "💡 *نحوه استفاده:*\n\n"
        "📰 روی *اخبار* بزنید برای آخرین خبرها\n"
        "⚽ روی *اخبار ورزشی* بزنید\n"
        "🌤 روی *آبوهوا* بزنید برای وضعیت هوا\n"
        "🕌 روی *اوقات نماز* بزنید\n"
        "💱 روی *نرخ ارز* بزنید\n"
        "💎 روی *ارزهای دیجیتال* بزنید\n"
        "🔍 روی *جستجو* بزنید برای جستجوی سریع\n"
        "🧠 روی *جستجوی عمیق* بزنید برای تحلیل هوش مصنوعی\n"
        "📋 روی *خلاصه روز* بزنید\n"
        "🔔 روی *اعلانها* بزنید برای مدیریت اطلاعرسانی\n"
        "🔄 روی *تنظیمات* بزنید برای تغییر زبان یا کشور"
    ),
    "हिन्दी 🇮🇳": (
        "💡 *उपयोग कैसे करें:*\n\n"
        "📰 खबरों के लिए *ताज़ा खबरें* दबाएं\n"
        "⚽ खेल खबरों के लिए *खेल समाचार* दबाएं\n"
        "🌤 मौसम के लिए *मौसम अभी* दबाएं\n"
        "🕌 नमाज़ के समय के लिए *नमाज़ का समय* दबाएं\n"
        "💱 विनिमय दर के लिए *मुद्रा दरें* दबाएं\n"
        "💎 क्रिप्टो के लिए *क्रिप्टो* दबाएं\n"
        "🔍 त्वरित खोज के लिए *खोज* दबाएं\n"
        "🧠 AI विश्लेषण के लिए *डीप सर्च* दबाएं\n"
        "📋 दिन की खबरों के लिए *दैनिक सारांश* दबाएं\n"
        "🔔 अलर्ट के लिए *सूचनाएं* दबाएं\n"
        "🔄 भाषा बदलने के लिए *सेटिंग्स* दबाएं"
    ),
    "Português 🇧🇷": (
        "💡 *Como usar:*\n\n"
        "📰 Toque em *Notícias* para as últimas notícias\n"
        "⚽ Toque em *Esportes* para notícias esportivas\n"
        "🌤 Toque em *Clima* para o tempo atual\n"
        "🕌 Toque em *Horários de Oração* para os horários\n"
        "💱 Toque em *Câmbio* para taxas de câmbio\n"
        "💎 Toque em *Cripto* para preços de criptomoedas\n"
        "🔍 Toque em *Buscar* para pesquisa rápida\n"
        "🧠 Toque em *Busca Profunda* para análise de IA\n"
        "📋 Toque em *Resumo do Dia* para as principais notícias\n"
        "🔔 Toque em *Notificações* para gerenciar alertas\n"
        "🔄 Toque em *Configurações* para mudar idioma ou país"
    ),
    "Türkçe 🇹🇷": (
        "💡 *Nasıl kullanılır:*\n\n"
        "📰 Haberler için *Son haberler* düğmesine basın\n"
        "⚽ Spor için *Spor haberleri* düğmesine basın\n"
        "🌤 Hava durumu için *Hava durumu* düğmesine basın\n"
        "🕌 Namaz vakitleri için *Namaz vakitleri* düğmesine basın\n"
        "💱 Döviz için *Döviz kurları* düğmesine basın\n"
        "💎 Kripto için *Kripto* düğmesine basın\n"
        "🔍 Hızlı arama için *Ara* düğmesine basın\n"
        "🧠 Yapay zeka analizi için *Derin Arama* düğmesine basın\n"
        "📋 Günlük özet için *Günlük özet* düğmesine basın\n"
        "🔔 Bildirimler için *Bildirimler* düğmesine basın\n"
        "🔄 Dili değiştirmek için *Ayarlar* düğmesine basın"
    ),
    "اردو 🇵🇰": (
        "💡 *استعمال کا طریقہ:*\n\n"
        "📰 خبروں کے لیے *تازہ خبریں* دبائیں\n"
        "⚽ کھیلوں کے لیے *کھیل کی خبریں* دبائیں\n"
        "🌤 موسم کے لیے *موسم ابھی* دبائیں\n"
        "🕌 نماز کے اوقات کے لیے *نماز کے اوقات* دبائیں\n"
        "💱 کرنسی کے لیے *کرنسی ریٹ* دبائیں\n"
        "💎 کریپٹو کے لیے *کریپٹو* دبائیں\n"
        "🔍 فوری تلاش کے لیے *تلاش* دبائیں\n"
        "🧠 AI تجزیہ کے لیے *گہری تلاش* دبائیں\n"
        "📋 روزانہ خلاصے کے لیے *روزانہ خلاصہ* دبائیں\n"
        "🔔 الرٹ کے لیے *اطلاعات* دبائیں\n"
        "🔄 زبان تبدیل کرنے کے لیے *ترتیبات* دبائیں"
    ),
    "Deutsch 🇩🇪": (
        "💡 *Anleitung:*\n\n"
        "📰 Tippen Sie auf *Nachrichten* für aktuelle Nachrichten\n"
        "⚽ Tippen Sie auf *Sport* für Sportnachrichten\n"
        "🌤 Tippen Sie auf *Wetter* für das aktuelle Wetter\n"
        "🕌 Tippen Sie auf *Gebetszeiten* für den Zeitplan\n"
        "💱 Tippen Sie auf *Wechselkurse* für Wechselkurse\n"
        "💎 Tippen Sie auf *Krypto* für Kryptowährungspreise\n"
        "🔍 Tippen Sie auf *Suchen* für die schnelle Suche\n"
        "🧠 Tippen Sie auf *Deep Search* für KI-Analyse\n"
        "📋 Tippen Sie auf *Tagesübersicht* für die besten Nachrichten\n"
        "🔔 Tippen Sie auf *Benachrichtigungen* für Alarme\n"
        "🔄 Tippen Sie auf *Einstellungen* für Sprache oder Land"
    ),
    "Українська 🇺🇦": (
        "💡 *Як користуватись:*\n\n"
        "📰 Натисніть *Новини* для останніх новин\n"
        "⚽ Натисніть *Спорт* для спортивних новин\n"
        "🌤 Натисніть *Погода* для перегляду погоди\n"
        "🕌 Натисніть *Час молитви* для розкладу\n"
        "💱 Натисніть *Курси валют* для курсів обміну\n"
        "💎 Натисніть *Крипто* для цін криптовалют\n"
        "🔍 Натисніть *Пошук* для швидкого пошуку\n"
        "🧠 Натисніть *Глибокий пошук* для аналізу ШІ\n"
        "📋 Натисніть *Зведення дня* для головних новин\n"
        "🔔 Натисніть *Сповіщення* для керування оповіщеннями\n"
        "🔄 Натисніть *Налаштування* для зміни мови або країни"
    ),
    "Italiano 🇮🇹": (
        "💡 *Come usare:*\n\n"
        "📰 Tocca *Notizie* per le ultime notizie\n"
        "⚽ Tocca *Sport* per le notizie sportive\n"
        "🌤 Tocca *Meteo* per il meteo attuale\n"
        "🕌 Tocca *Orari di preghiera* per gli orari\n"
        "💱 Tocca *Tassi di cambio* per i cambi valuta\n"
        "💎 Tocca *Cripto* per i prezzi delle criptovalute\n"
        "🔍 Tocca *Cerca* per la ricerca rapida\n"
        "🧠 Tocca *Ricerca profonda* per l'analisi AI\n"
        "📋 Tocca *Riepilogo del giorno* per le principali notizie\n"
        "🔔 Tocca *Notifiche* per gestire gli avvisi\n"
        "🔄 Tocca *Impostazioni* per cambiare lingua o paese"
    ),
    "Español 🇲🇽": (
        "💡 *Cómo usar:*\n\n"
        "📰 Toca *Noticias* para las últimas noticias\n"
        "⚽ Toca *Deportes* para noticias deportivas\n"
        "🌤 Toca *Clima* para el tiempo actual\n"
        "🕌 Toca *Horarios de oración* para el horario\n"
        "💱 Toca *Tipos de cambio* para tasas de cambio\n"
        "💎 Toca *Cripto* para precios de criptomonedas\n"
        "🔍 Toca *Buscar* para búsqueda rápida\n"
        "🧠 Toca *Búsqueda profunda* para análisis de IA\n"
        "📋 Toca *Resumen del día* para las principales noticias\n"
        "🔔 Toca *Notificaciones* para gestionar alertas\n"
        "🔄 Toca *Configuración* para cambiar idioma o país"
    ),
}

# ======== اللغات ========
languages = {
    "Arabic": "العربية 🇮🇶",
    "English": "English 🇬🇧",
    "Russian": "Русский 🇷🇺",
    "Farsi": "فارسی 🇮🇷",
    "Hindi": "हिन्दी 🇮🇳",
    "Portuguese": "Português 🇧🇷",
    "Turkish": "Türkçe 🇹🇷",
    "Urdu": "اردو 🇵🇰",
    "German": "Deutsch 🇩🇪",
    "Ukrainian": "Українська 🇺🇦",
    "Italian": "Italiano 🇮🇹",
    "Spanish": "Español 🇲🇽"
}

# ======== كودات اللغة للطقس ========
LANG_CODES = {
    "العربية 🇮🇶": "ar",
    "English 🇬🇧": "en",
    "Русский 🇷🇺": "ru",
    "فارسی 🇮🇷": "fa",
    "हिन्दी 🇮🇳": "hi",
    "Português 🇧🇷": "pt",
    "Türkçe 🇹🇷": "tr",
    "اردو 🇵🇰": "ur",
    "Deutsch 🇩🇪": "de",
    "Українська 🇺🇦": "uk",
    "Italiano 🇮🇹": "it",
    "Español 🇲🇽": "es"
}

# ======== الدول والمحافظات ========
countries = {
    # ═══ العربية: جميع الدول العربية ═══
    "العربية 🇮🇶": {
        "العراق 🇮🇶": [],
        "السعودية 🇸🇦": [],
        "الكويت 🇰🇼": [],
        "قطر 🇶🇦": [],
        "الإمارات العربية المتحدة 🇦🇪": [],
        "البحرين 🇧🇭": [],
        "عُمان 🇴🇲": [],
        "اليمن 🇾🇪": [],
        "سوريا 🇸🇾": [],
        "لبنان 🇱🇧": [],
        "الأردن 🇯🇴": [],
        "فلسطين 🇵🇸": [],
        "مصر 🇪🇬": [],
        "ليبيا 🇱🇾": [],
        "تونس 🇹🇳": [],
        "الجزائر 🇩🇿": [],
        "المغرب 🇲🇦": [],
        "موريتانيا 🇲🇷": [],
        "السودان 🇸🇩": [],
        "الصومال 🇸🇴": [],
        "جيبوتي 🇩🇯": [],
        "جزر القمر 🇰🇲": [],
    },
    # ═══ English: all major English-speaking countries ═══
    "English 🇬🇧": {
        "United States 🇺🇸": [],
        "United Kingdom 🇬🇧": [],
        "Australia 🇦🇺": [],
        "Canada 🇨🇦": [],
        "Ireland 🇮🇪": [],
        "New Zealand 🇳🇿": [],
        "South Africa 🇿🇦": [],
        "Nigeria 🇳🇬": [],
        "Ghana 🇬🇭": [],
        "Kenya 🇰🇪": [],
        "Tanzania 🇹🇿": [],
        "Uganda 🇺🇬": [],
        "Zimbabwe 🇿🇼": [],
        "Zambia 🇿🇲": [],
        "Botswana 🇧🇼": [],
        "Singapore 🇸🇬": [],
        "Philippines 🇵🇭": [],
        "Jamaica 🇯🇲": [],
        "Trinidad & Tobago 🇹🇹": [],
        "Barbados 🇧🇧": [],
        "Malta 🇲🇹": [],
        "Cyprus 🇨🇾": [],
        "Guyana 🇬🇾": [],
        "Belize 🇧🇿": [],
        "Bahamas 🇧🇸": [],
    },
    # ═══ Русский: все страны со значительным русскоязычным населением ═══
    "Русский 🇷🇺": {
        "Россия 🇷🇺": [],
        "Беларусь 🇧🇾": [],
        "Казахстан 🇰🇿": [],
        "Узбекистан 🇺🇿": [],
        "Кыргызстан 🇰🇬": [],
        "Таджикистан 🇹🇯": [],
        "Армения 🇦🇲": [],
        "Азербайджан 🇦🇿": [],
        "Грузия 🇬🇪": [],
        "Молдова 🇲🇩": [],
        "Латвия 🇱🇻": [],
        "Литва 🇱🇹": [],
        "Эстония 🇪🇪": [],
        "Израиль 🇮🇱": [],
        "Германия 🇩🇪": [],
    },
    # ═══ فارسی: کشورهایی که فارسی در آنها رسمی یا رایج است ═══
    "فارسی 🇮🇷": {
        "ایران 🇮🇷": [],
        "افغانستان 🇦🇫": [],
        "تاجیکستان 🇹🇯": [],
        "ازبکستان 🇺🇿": [],
        "پاکستان 🇵🇰": [],
        "عراق 🇮🇶": [],
        "بحرین 🇧🇭": [],
        "کویت 🇰🇼": [],
        "امارات متحده عربی 🇦🇪": [],
    },
    # ═══ हिन्दी: हिन्दी भाषी देश और प्रवासी ═══
    "हिन्दी 🇮🇳": {
        "भारत 🇮🇳": [],
        "नेपाल 🇳🇵": [],
        "फ़िजी 🇫🇯": [],
        "मॉरीशस 🇲🇺": [],
        "गुयाना 🇬🇾": [],
        "त्रिनिदाद और टोबैगो 🇹🇹": [],
        "सूरीनाम 🇸🇷": [],
        "दक्षिण अफ्रीका 🇿🇦": [],
        "संयुक्त अरब अमीरात 🇦🇪": [],
        "कनाडा 🇨🇦": [],
        "संयुक्त राज्य अमेरिका 🇺🇸": [],
        "यूनाइटेड किंगडम 🇬🇧": [],
    },
    # ═══ Português: todos os países lusófonos ═══
    "Português 🇧🇷": {
        "Brasil 🇧🇷": [],
        "Portugal 🇵🇹": [],
        "Angola 🇦🇴": [],
        "Moçambique 🇲🇿": [],
        "Cabo Verde 🇨🇻": [],
        "Guiné-Bissau 🇬🇼": [],
        "São Tomé e Príncipe 🇸🇹": [],
        "Guiné Equatorial 🇬🇶": [],
        "Timor-Leste 🇹🇱": [],
        "Macau 🇲🇴": [],
    },
    # ═══ Türkçe: Türkçe konuşulan ülkeler ═══
    "Türkçe 🇹🇷": {
        "Türkiye 🇹🇷": [],
        "Azerbaycan 🇦🇿": [],
        "Kıbrıs 🇨🇾": [],
        "Kazakistan 🇰🇿": [],
        "Özbekistan 🇺🇿": [],
        "Türkmenistan 🇹🇲": [],
        "Kırgızistan 🇰🇬": [],
        "Almanya 🇩🇪": [],
        "Avusturya 🇦🇹": [],
    },
    # ═══ اردو: اردو بولنے والے ممالک ═══
    "اردو 🇵🇰": {
        "پاکستان 🇵🇰": [],
        "بھارت 🇮🇳": [],
        "بنگلہ دیش 🇧🇩": [],
        "افغانستان 🇦🇫": [],
        "متحدہ عرب امارات 🇦🇪": [],
        "سعودی عرب 🇸🇦": [],
        "کویت 🇰🇼": [],
        "قطر 🇶🇦": [],
        "بحرین 🇧🇭": [],
        "عُمان 🇴🇲": [],
        "مملکت متحدہ 🇬🇧": [],
        "کینیڈا 🇨🇦": [],
        "امریکہ 🇺🇸": [],
    },
    # ═══ Deutsch: alle deutschsprachigen Länder ═══
    "Deutsch 🇩🇪": {
        "Deutschland 🇩🇪": [],
        "Österreich 🇦🇹": [],
        "Schweiz 🇨🇭": [],
        "Liechtenstein 🇱🇮": [],
        "Luxemburg 🇱🇺": [],
        "Belgien 🇧🇪": [],
        "Südtirol (Italien) 🇮🇹": [],
        "Namibia 🇳🇦": [],
    },
    # ═══ Українська: країни з українськомовним населенням ═══
    "Українська 🇺🇦": {
        "Україна 🇺🇦": [],
        "Канада 🇨🇦": [],
        "США 🇺🇸": [],
        "Польща 🇵🇱": [],
        "Молдова 🇲🇩": [],
        "Словаччина 🇸🇰": [],
        "Румунія 🇷🇴": [],
        "Угорщина 🇭🇺": [],
        "Австралія 🇦🇺": [],
    },
    # ═══ Italiano: tutti i paesi italofoni ═══
    "Italiano 🇮🇹": {
        "Italia 🇮🇹": [],
        "Svizzera 🇨🇭": [],
        "San Marino 🇸🇲": [],
        "Città del Vaticano 🇻🇦": [],
        "Malta 🇲🇹": [],
        "Croazia 🇭🇷": [],
        "Slovenia 🇸🇮": [],
        "Argentina 🇦🇷": [],
        "Brasile 🇧🇷": [],
        "Uruguay 🇺🇾": [],
    },
    # ═══ Español: todos los países hispanohablantes ═══
    "Español 🇲🇽": {
        "México 🇲🇽": [],
        "España 🇪🇸": [],
        "Argentina 🇦🇷": [],
        "Colombia 🇨🇴": [],
        "Chile 🇨🇱": [],
        "Perú 🇵🇪": [],
        "Venezuela 🇻🇪": [],
        "Ecuador 🇪🇨": [],
        "Bolivia 🇧🇴": [],
        "Paraguay 🇵🇾": [],
        "Uruguay 🇺🇾": [],
        "Cuba 🇨🇺": [],
        "República Dominicana 🇩🇴": [],
        "Guatemala 🇬🇹": [],
        "Honduras 🇭🇳": [],
        "El Salvador 🇸🇻": [],
        "Nicaragua 🇳🇮": [],
        "Costa Rica 🇨🇷": [],
        "Panamá 🇵🇦": [],
        "Guinea Ecuatorial 🇬🇶": [],
        "Puerto Rico 🇵🇷": [],
    },
}

# ======== مصادر RSS ========
DEFAULT_RSS = {
    "العربية 🇮🇶": [
        # قنوات دولية كبرى
        "https://feeds.bbci.co.uk/arabic/rss.xml",
        "https://www.aljazeera.net/xml/rss/all.xml",
        "https://arabic.rt.com/rss/",
        "https://rss.dw.com/rdf/rss-ara-all",
        "https://www.france24.com/ar/rss",
        "https://arabic.euronews.com/rss",
        "https://www.aa.com.tr/ar/rss/default",
        "https://www.skynewsarabia.com/rss.xml",
        "https://www.alhurra.com/api/zrqomtmopp",
        "https://feeds.bbci.co.uk/arabic/middleeast/rss.xml",
        "https://www.independentarabia.com/rss.xml",
        "https://alarab.co.uk/rss.xml",
        "https://www.elaph.com/rss/",
        "https://www.arabnews.com/rss.xml",
        "https://www.asharqalawsat.com/rss.xml",
        # عراقية
        "https://baghdadtoday.news/rss.xml",
        "https://www.alsumaria.tv/rss",
        "https://shafaq.com/ar/rss.xml",
        "https://www.mawazin.net/rss.xml",
        "https://www.ankawa.org/feed.php",
        "https://ikhnaton2.com/rss.xml",
        "https://www.nasnews.com/rss.xml",
        "https://www.ina.iq/feed",
        "https://www.ultrairaq.ultrasawt.com/rss.xml",
        "https://www.rudaw.net/arabic/rss",
        "https://www.basnews.com/ar/rss",
        "https://www.nrttv.com/ar/rss",
        "https://www.almaalomah.com/feed/",
        "https://almada-paper.com/feed/",
        "https://www.buratha.news/feed/",
        "https://www.alforatnews.iq/feed/",
        "https://alkafeel.net/rss.xml",
        "https://www.alsabah.iq/feed",
        # وكالات عالمية إضافية
        "https://www.middleeasteye.net/ar/rss",
        "https://feeds.skynewsarabia.com/web/rss/2",
        "https://arabi21.com/rss.xml",
        "https://www.alquds.com/feed/",
        "https://www.alaraby.co.uk/rss.xml",
        "https://www.huffpostarabi.com/feed/",
        "https://www.masrawy.com/rssFeed/news",
        "https://www.youm7.com/rss/rss.xml",
        "https://www.alwatan.com.sa/rss.xml",
        # مصادر عراقية إضافية
        "https://www.almothaqaf.com/feed/",
        "https://www.al-monitor.com/rss.xml",
        "https://www.iraq-businessnews.com/feed/",
        "https://www.nin.iq/feed/",
        "https://thenational.ae/rss.xml",
        "https://www.dinarstandard.com/feed",
        "https://www.almasalah.com/feed/",
        "https://www.haberni.com/feed/",
        "https://www.sotaliraq.com/feed/",
        "https://www.awsat.com/feed/",
        # مصادر عربية إضافية
        "https://www.aawsat.com/rss.xml",
        "https://feed.informer.com/digests/HDCJPVKJKZ/feeder",
        "https://www.alkhaleej.ae/rss.xml",
        "https://rss.hespress.com/",
        "https://www.noonpost.com/feed",
        "https://arabic.alibaba.com/rss/rss.xml",
        "https://www.zawya.com/rss/mena-news.rss",
    ],
    "English 🇬🇧": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.dw.com/rdf/rss-en-all",
        "https://www.france24.com/en/rss",
        "https://www.theguardian.com/world/rss",
        "https://www.rt.com/rss/news/",
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://www.aa.com.tr/en/rss/default",
        "https://rss.euronews.com/en/news.rss",
        "https://abcnews.go.com/abcnews/internationalheadlines",
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.npr.org/1001/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://feeds.washingtonpost.com/rss/world",
        "https://feeds.bbci.co.uk/news/politics/rss.xml",
        "https://www.independent.co.uk/news/world/rss",
        "https://apnews.com/feed",
        # مصادر إنجليزية إضافية
        "https://rss.cnn.com/rss/edition_world.rss",
        "https://feeds.nbcnews.com/nbcnews/public/news",
        "https://feeds.foxnews.com/foxnews/world",
        "https://www.cbsnews.com/latest/rss/world",
        "https://feeds.skynews.com/feeds/rss/home.xml",
        "https://www.politico.com/rss/politics08.xml",
        "https://www.ft.com/rss/home/uk",
        "https://www.economist.com/international/rss.xml",
        "https://feeds.bloomberg.com/news/sitemap.xml",
        "https://www.businessinsider.com/rss",
        "https://rss.dw.com/rdf/rss-en-world",
        "https://www.aa.com.tr/en/rss/default",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/Reuters/worldNews",
    ],
    "Русский 🇷🇺": [
        "https://feeds.bbci.co.uk/russian/rss.xml",
        "https://russian.rt.com/rss",
        "https://tass.ru/rss/v2.xml",
        "https://rss.dw.com/rdf/rss-ru-all",
        "https://www.rbc.ru/rss/news",
        "https://ria.ru/export/rss2/archive/index.xml",
        "https://www.interfax.ru/rss.asp",
        "https://www.aa.com.tr/ru/rss/default",
        "https://lenta.ru/rss/news",
        "https://www.kommersant.ru/RSS/news.xml",
        "https://www.mk.ru/rss/news/index.xml",
        "https://iz.ru/xml/rss/all.xml",
        "https://www.vesti.ru/vesti.rss",
    ],
    "فارسی 🇮🇷": [
        "https://feeds.bbci.co.uk/persian/rss.xml",
        "https://rss.dw.com/rdf/rss-per-all",
        "https://www.radiofarda.com/api/zrqomtmopp",
        "https://ir.voanews.com/api/zrqomtmopp",
        "https://www.iranintl.com/rss",
        "https://www.aa.com.tr/fa/rss/default",
        "https://www.france24.com/fa/rss",
        "https://www.isna.ir/rss",
        "https://www.irna.ir/rss",
        "https://farsnews.ir/rss.aspx",
        "https://www.mehrnews.com/rss",
        "https://www.tabnak.ir/rss/fa/index.xml",
    ],
    "हिन्दी 🇮🇳": [
        "https://feeds.bbci.co.uk/hindi/rss.xml",
        "https://rss.dw.com/rdf/rss-hin-all",
        "https://www.aa.com.tr/hi/rss/default",
        "https://feeds.feedburner.com/ndtvnews-top-stories",
        "https://www.indiatoday.in/rss/home",
        "https://navbharattimes.indiatimes.com/rssfeedstopstories.cms",
        "https://www.aajtak.in/rss/india.xml",
        "https://www.jagran.com/rss/news-national.xml",
        "https://www.bhaskar.com/rss-feed/1061/",
        "https://www.amarujala.com/rss/breaking-news.xml",
        "https://www.zeenews.india.com/hindi/rss/top-stories.xml",
    ],
    "Português 🇧🇷": [
        "https://feeds.bbci.co.uk/portuguese/rss.xml",
        "https://rss.dw.com/rdf/rss-por-all",
        "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml",
        "https://g1.globo.com/rss/g1/index.xml",
        "https://www.france24.com/pt/rss",
        "https://www.aa.com.tr/pt/rss/default",
        "https://rss.euronews.com/pt/news.rss",
        "https://www.uol.com.br/rss.xml",
        "https://oglobo.globo.com/rss.xml",
        "https://www.correiobraziliense.com.br/rss/index.xml",
        "https://feeds.folha.uol.com.br/poder/rss091.xml",
        "https://www.publico.pt/api/rss",
    ],
    "Türkçe 🇹🇷": [
        "https://feeds.bbci.co.uk/turkish/rss.xml",
        "https://www.aa.com.tr/tr/rss/default",
        "https://rss.dw.com/rdf/rss-tur-all",
        "https://www.trthaber.com/sondakika.rss",
        "https://www.ntv.com.tr/son-dakika.rss",
        "https://www.sabah.com.tr/rss/anasayfa.xml",
        "https://www.hurriyet.com.tr/rss/anasayfa",
        "https://rss.euronews.com/tr/news.rss",
        "https://www.haberturk.com/rss",
        "https://www.milliyet.com.tr/rss/rssNew/gundem.rss",
        "https://www.cumhuriyet.com.tr/rss/son_dakika.xml",
        "https://www.sozcu.com.tr/feed/",
        "https://www.cnnturk.com/feed/rss/news",
    ],
    "اردو 🇵🇰": [
        "https://feeds.bbci.co.uk/urdu/rss.xml",
        "https://rss.dw.com/rdf/rss-urd-all",
        "https://www.geo.tv/rss",
        "https://www.urduvoa.com/api/zrqomtmopp",
        "https://urdu.arynews.tv/feed/",
        "https://www.dawnnews.tv/feed/",
        "https://dunyanews.tv/rss/urdu",
        "https://jang.com.pk/rss/1",
        "https://www.express.pk/feed/",
        "https://www.samaa.tv/feed/",
        "https://92newshd.tv/feed/",
        "https://www.boltpak.com/feed/",
    ],
    "Deutsch 🇩🇪": [
        "https://rss.dw.com/rdf/rss-de-all",
        "https://www.tagesschau.de/xml/rss2",
        "https://www.spiegel.de/schlagzeilen/index.rss",
        "https://www.aa.com.tr/de/rss/default",
        "https://rss.euronews.com/de/news.rss",
        "https://www.zeit.de/news/rss-aktuell",
        "https://www.sueddeutsche.de/news/rss",
        "https://www.faz.net/rss/aktuell/",
        "https://www.welt.de/feeds/latest.rss",
        "https://www.stern.de/feed/standard/alle-nachrichten/",
        "https://www.focus.de/rss/news_rss.xml",
    ],
    "Українська 🇺🇦": [
        "https://feeds.bbci.co.uk/ukrainian/rss.xml",
        "https://rss.dw.com/rdf/rss-ukr-all",
        "https://www.ukrinform.ua/rss/block-lastnews",
        "https://www.radiosvoboda.org/api/zrqomtmopp",
        "https://www.pravda.com.ua/rss/view_news/",
        "https://www.unian.ua/rss/all_news.rss",
        "https://suspilne.media/rss",
        "https://www.rbc.ua/rss/all.xml",
        "https://tsn.ua/rss/full.rss",
        "https://www.segodnya.ua/rss/all.rss",
    ],
    "Italiano 🇮🇹": [
        "https://rss.dw.com/rdf/rss-it-all",
        "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
        "https://www.repubblica.it/rss/homepage/rss2.0.xml",
        "https://rss.euronews.com/it/news.rss",
        "https://www.aa.com.tr/it/rss/default",
        "https://www.corriere.it/rss/homepage.xml",
        "https://www.lastampa.it/rss.xml",
        "https://www.ilsole24ore.com/rss/mondo.xml",
        "https://www.rainews.it/dl/img/mediaplayer/rss/video.xml",
        "https://www.sky.it/sky-tg24/rss.xml",
        "https://www.tgcom24.mediaset.it/rss/home.xml",
    ],
    "Español 🇲🇽": [
        "https://feeds.bbci.co.uk/mundo/rss.xml",
        "https://rss.dw.com/rdf/rss-es-all",
        "https://www.france24.com/es/rss",
        "https://rss.euronews.com/es/news.rss",
        "https://www.aa.com.tr/es/rss/default",
        "https://www.infobae.com/feeds/rss/",
        "https://cnnespanol.cnn.com/feed/",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
        "https://www.elmundo.es/rss/portada.xml",
        "https://www.elconfidencial.com/rss/",
        "https://www.lavanguardia.com/rss/home.xml",
        "https://www.clarin.com/rss/",
        "https://www.milenio.com/rss",
        "https://www.excelsior.com.mx/rss.xml",
    ],
}

# تحميل الـ feeds مع الدمج الذكي: الأفضلية للـ DEFAULT_RSS لكن مع الحفاظ على أي إضافات يدوية
_loaded_rss = load_json(RSS_FILE, {})
RSS = {}
for lang, feeds in DEFAULT_RSS.items():
    RSS[lang] = DEFAULT_RSS[lang]  # دائماً خذ المصادر الجديدة
for lang, feeds in _loaded_rss.items():
    if lang not in RSS:
        RSS[lang] = feeds  # أضف أي لغة أضافها الأدمن يدوياً

def save_rss():
    save_json(RSS_FILE, RSS)

# ======== تحميل ودمج القنوات المخصصة (تيليغرام) ========
_custom_tg_channels = load_json(CUSTOM_TG_CHANNELS_FILE, {})
# ادمج القنوات المخصصة مع TELEGRAM_NEWS_CHANNELS
for _lang, _chs in _custom_tg_channels.items():
    if _lang not in TELEGRAM_NEWS_CHANNELS:
        TELEGRAM_NEWS_CHANNELS[_lang] = []
    _existing_handles = {c["handle"] for c in TELEGRAM_NEWS_CHANNELS[_lang]}
    for _ch in _chs:
        if _ch["handle"] not in _existing_handles:
            TELEGRAM_NEWS_CHANNELS[_lang].append(_ch)
            _existing_handles.add(_ch["handle"])

def save_custom_tg_channels():
    save_json(CUSTOM_TG_CHANNELS_FILE, _custom_tg_channels)

def add_custom_tg_channel(lang, handle, name):
    """يضيف قناة تيليغرام جديدة لمصادر الأخبار ديناميكياً"""
    handle = handle.lstrip("@").strip()
    if not name:
        name = f"@{handle}"
    entry = {"handle": handle, "name": name}
    if lang not in TELEGRAM_NEWS_CHANNELS:
        TELEGRAM_NEWS_CHANNELS[lang] = []
    if lang not in _custom_tg_channels:
        _custom_tg_channels[lang] = []
    existing_handles = {c["handle"] for c in TELEGRAM_NEWS_CHANNELS[lang]}
    if handle in existing_handles:
        return False, "موجودة مسبقاً"
    TELEGRAM_NEWS_CHANNELS[lang].append(entry)
    _custom_tg_channels[lang].append(entry)
    save_custom_tg_channels()
    return True, entry

def remove_custom_tg_channel(handle):
    """يحذف قناة تيليغرام مخصصة من قائمة المصادر"""
    handle = handle.lstrip("@").strip()
    removed_from = []
    for lang in list(_custom_tg_channels.keys()):
        before = len(_custom_tg_channels[lang])
        _custom_tg_channels[lang] = [c for c in _custom_tg_channels[lang] if c["handle"] != handle]
        if len(_custom_tg_channels[lang]) < before:
            removed_from.append(lang)
    for lang in list(TELEGRAM_NEWS_CHANNELS.keys()):
        TELEGRAM_NEWS_CHANNELS[lang] = [c for c in TELEGRAM_NEWS_CHANNELS[lang] if c["handle"] != handle]
    if removed_from:
        save_custom_tg_channels()
        return True, removed_from
    return False, []

# ======== مصادر أخبار الرياضة ========
SPORTS_RSS = {
    "العربية 🇮🇶": [
        "https://www.skynewsarabia.com/rss/sport.xml",
        "https://www.filgoal.com/rss",
        "https://www.yallakora.com/rss",
        "https://arabic.euronews.com/rss/sport",
        "https://sport.al-ain.com/rss",
        "https://arabic.goal.com/ar/news/rss",
        "https://www.beinsports.com/ar/rss",
        "https://www.kooora.com/?rss",
        # F1 / موتور سبورت
        "https://ar.motorsport.com/rss/f1/news/",
        "https://ar.motorsport.com/rss/motogp/news/",
        # رالي داكار
        "https://ar.motorsport.com/rss/dakar/news/",
        # تنس
        "https://ar.wtatennis.com/news/rss",
    ],
    "English 🇬🇧": [
        "https://feeds.bbci.co.uk/sport/rss.xml",
        "https://www.espn.com/espn/rss/news",
        "https://www.theguardian.com/sport/rss",
        "https://sports.yahoo.com/rss/",
        "https://www.goal.com/feeds/en/news",
        # F1
        "https://www.motorsport.com/rss/f1/news/",
        "https://www.formula1.com/content/fom-website/en/latest/all.xml",
        # NASCAR
        "https://www.motorsport.com/rss/nascar/news/",
        "https://www.nascar.com/rss/news.xml",
        # MotoGP
        "https://www.motorsport.com/rss/motogp/news/",
        # Rally Dakar
        "https://www.dakar.com/en/rss",
        "https://www.motorsport.com/rss/dakar/news/",
        # WRC
        "https://www.motorsport.com/rss/wrc/news/",
        # Tennis
        "https://www.atptour.com/en/media/rss-feed/xml-feed",
        "https://www.wtatennis.com/news/rss",
        # NBA / Basketball
        "https://www.nba.com/feeds/nba/league/stories.rss",
        # NFL
        "https://www.nfl.com/rss/rsslanding?searchString=news",
        # NHL Hockey
        "https://www.nhl.com/rss/news.xml",
        # MLB Baseball
        "https://www.mlb.com/feeds/news/rss.xml",
        # Golf
        "https://www.pgatour.com/news/rss.xml",
        # Boxing / MMA
        "https://www.espn.com/espn/rss/boxing/news",
        "https://mmajunkie.usatoday.com/feed",
    ],
    "Русский 🇷🇺": [
        "https://rsport.ria.ru/export/rss2/index.xml",
        "https://www.sports.ru/rss/main.xml",
        "https://ru.motorsport.com/rss/f1/news/",
    ],
    "فارسی 🇮🇷": [
        "https://feeds.bbci.co.uk/persian/rss.xml",
        "https://www.varzesh3.com/rss/all",
        "https://fa.motorsport.com/rss/f1/news/",
    ],
    "Türkçe 🇹🇷": [
        "https://www.ntv.com.tr/spor.rss",
        "https://www.sabah.com.tr/rss/spor.xml",
        "https://tr.motorsport.com/rss/f1/news/",
    ],
    "Deutsch 🇩🇪": [
        "https://rss.dw.com/rdf/rss-de-sports",
        "https://www.sport1.de/rss/sport1-news.rss",
        "https://de.motorsport.com/rss/f1/news/",
    ],
    "Español 🇲🇽": [
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/deportes/portada",
        "https://cnnespanol.cnn.com/deportes/feed/",
        "https://es.motorsport.com/rss/f1/news/",
        "https://es.motorsport.com/rss/motogp/news/",
    ],
    "Português 🇧🇷": [
        "https://globoesporte.globo.com/dynamo/esportes/futebol/rss2.xml",
        "https://feeds.bbci.co.uk/portuguese/rss.xml",
        "https://pt.motorsport.com/rss/f1/news/",
    ],
    "Italiano 🇮🇹": [
        "https://www.gazzetta.it/rss/home.xml",
        "https://it.motorsport.com/rss/f1/news/",
        "https://it.motorsport.com/rss/motogp/news/",
    ],
    "हिन्दी 🇮🇳": [
        "https://feeds.bbci.co.uk/hindi/rss.xml",
        "https://hi.motorsport.com/rss/f1/news/",
    ],
    "اردو 🇵🇰": [
        "https://www.geo.tv/rss",
        "https://www.dawn.com/feeds/sport",
    ],
    "Українська 🇺🇦": [
        "https://www.ukrinform.ua/rss/block-sport",
        "https://uk.motorsport.com/rss/f1/news/",
    ],
}

# ======== نظام Scraping — سحب الأخبار مباشرة من المواقع ========
try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False
    print("⚠️ مكتبة beautifulsoup4 غير مثبتة. ثبّتها بـ:  pip install beautifulsoup4")

_SCRAPE_TIMEOUT = 20                # ثانية قبل تجاهل الموقع
_SCRAPE_CACHE = {}                  # url -> (items_list, timestamp)
_SCRAPE_CACHE_TTL = 300             # 5 دقائق — لا نطلب نفس الصفحة أكثر من مرة كل 5 دقائق
_SCRAPE_LOCK = threading.Lock()

# User-Agent واقعي يحاكي متصفح Chrome لتجنب الحجب
_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# ======== مصادر الـ Scraping (مواقع بدون RSS أو RSS ضعيف) ========
# كل مصدر يحتوي: url, name, base_url
# base_url يُستخدم لتحويل الروابط النسبية (/news/123) إلى روابط مطلقة
SCRAPE_SOURCES = {
    # ======== وكالات وصحف عراقية ========
    "العربية 🇮🇶": [
        {"url": "https://www.rudaw.net/arabic/latest-news",   "name": "رووداو",               "base_url": "https://www.rudaw.net"},
        {"url": "https://mawazin.net/",                        "name": "موازين نيوز",          "base_url": "https://mawazin.net"},
        {"url": "https://www.alsabah.iq/",                    "name": "الصباح",               "base_url": "https://www.alsabah.iq"},
        {"url": "https://www.ina.iq/arabic/latest.php",       "name": "وكالة الأنباء العراقية","base_url": "https://www.ina.iq"},
        {"url": "https://www.iraqia.news/news",               "name": "العراقية نيوز",        "base_url": "https://www.iraqia.news"},
        {"url": "https://alkafeel.net/news/",                 "name": "الكفيل",               "base_url": "https://alkafeel.net"},
        {"url": "https://www.nrttv.com/ar/news",              "name": "NRT عربي",             "base_url": "https://www.nrttv.com"},
        {"url": "https://shafaq.com/ar/",                     "name": "شفق نيوز",             "base_url": "https://shafaq.com"},
        {"url": "https://www.almaalomah.com/",                "name": "المعلومة",             "base_url": "https://www.almaalomah.com"},
        {"url": "https://almada-paper.com/",                  "name": "المدى",                "base_url": "https://almada-paper.com"},
        {"url": "https://www.alsumaria.tv/",                  "name": "السومرية",             "base_url": "https://www.alsumaria.tv"},
        {"url": "https://www.baghdadtoday.news/",             "name": "بغداد اليوم",          "base_url": "https://www.baghdadtoday.news"},
        {"url": "https://www.basnews.com/ar/",                "name": "باس نيوز",             "base_url": "https://www.basnews.com"},
        {"url": "https://www.ankawa.com/",                    "name": "عنكاوا",               "base_url": "https://www.ankawa.com"},
        {"url": "https://www.buratha.news/",                  "name": "بروثا نيوز",           "base_url": "https://www.buratha.news"},
        {"url": "https://www.alforatnews.iq/",               "name": "الفرات نيوز",          "base_url": "https://www.alforatnews.iq"},
        {"url": "https://www.nasnews.com/",                   "name": "ناس نيوز",             "base_url": "https://www.nasnews.com"},
        {"url": "https://www.krsc.org/ar/",                   "name": "KirkukNow",            "base_url": "https://www.krsc.org"},
        # ======== وكالات عالمية باللغة العربية ========
        {"url": "https://arabic.rt.com/news/",                "name": "RT عربي",              "base_url": "https://arabic.rt.com"},
        {"url": "https://www.dw.com/ar/",                     "name": "DW عربي",              "base_url": "https://www.dw.com"},
        {"url": "https://www.france24.com/ar/",               "name": "فرانس 24",             "base_url": "https://www.france24.com"},
        {"url": "https://arabic.euronews.com/news",           "name": "يورونيوز عربي",        "base_url": "https://arabic.euronews.com"},
        {"url": "https://www.alarabiya.net/",                 "name": "العربية",              "base_url": "https://www.alarabiya.net"},
        {"url": "https://www.middleeasteye.net/ar/",          "name": "Middle East Eye",      "base_url": "https://www.middleeasteye.net"},
        {"url": "https://www.independentarabia.com/",         "name": "إندبندنت عربية",       "base_url": "https://www.independentarabia.com"},
        {"url": "https://arabi21.com/",                       "name": "عربي 21",              "base_url": "https://arabi21.com"},
    ],
    "English 🇬🇧": [
        {"url": "https://www.rudaw.net/english/latest-news",  "name": "Rudaw English",        "base_url": "https://www.rudaw.net"},
        {"url": "https://www.iraqinews.com/latest/",          "name": "Iraq News",            "base_url": "https://www.iraqinews.com"},
        {"url": "https://www.nrttv.com/en/news",              "name": "NRT English",          "base_url": "https://www.nrttv.com"},
        {"url": "https://www.basnews.com/en/",                "name": "Bas News English",     "base_url": "https://www.basnews.com"},
        {"url": "https://www.reuters.com/world/",             "name": "Reuters",              "base_url": "https://www.reuters.com"},
        {"url": "https://apnews.com/",                        "name": "AP News",              "base_url": "https://apnews.com"},
        {"url": "https://www.bbc.com/news/world/",            "name": "BBC World",            "base_url": "https://www.bbc.com"},
        {"url": "https://www.dw.com/en/news/",                "name": "DW English",           "base_url": "https://www.dw.com"},
        {"url": "https://www.aljazeera.com/news/",            "name": "Al Jazeera",           "base_url": "https://www.aljazeera.com"},
        {"url": "https://www.middleeasteye.net/",             "name": "Middle East Eye",      "base_url": "https://www.middleeasteye.net"},
        {"url": "https://english.alarabiya.net/",             "name": "Al Arabiya English",   "base_url": "https://english.alarabiya.net"},
    ],
    "Русский 🇷🇺": [
        {"url": "https://lenta.ru/",                          "name": "Лента.ру",             "base_url": "https://lenta.ru"},
        {"url": "https://www.gazeta.ru/news/",                "name": "Газета.ру",            "base_url": "https://www.gazeta.ru"},
        {"url": "https://tass.ru/",                           "name": "ТАСС",                 "base_url": "https://tass.ru"},
        {"url": "https://ria.ru/",                            "name": "РИА Новости",          "base_url": "https://ria.ru"},
        {"url": "https://www.kommersant.ru/",                 "name": "Коммерсантъ",          "base_url": "https://www.kommersant.ru"},
        {"url": "https://russian.rt.com/",                    "name": "RT Русский",           "base_url": "https://russian.rt.com"},
    ],
    "Türkçe 🇹🇷": [
        {"url": "https://www.haberturk.com/son-dakika",       "name": "Haber Türk",           "base_url": "https://www.haberturk.com"},
        {"url": "https://www.milliyet.com.tr/son-dakika/",    "name": "Milliyet",             "base_url": "https://www.milliyet.com.tr"},
        {"url": "https://www.hurriyet.com.tr/gundem/",        "name": "Hürriyet",             "base_url": "https://www.hurriyet.com.tr"},
        {"url": "https://www.sabah.com.tr/son-dakika/",       "name": "Sabah",                "base_url": "https://www.sabah.com.tr"},
        {"url": "https://www.ntv.com.tr/son-dakika",          "name": "NTV",                  "base_url": "https://www.ntv.com.tr"},
        {"url": "https://tr.sputniknews.com/",                "name": "Sputnik Türkçe",       "base_url": "https://tr.sputniknews.com"},
    ],
    "فارسی 🇮🇷": [
        {"url": "https://www.farsnews.ir/",                   "name": "فارس نیوز",            "base_url": "https://www.farsnews.ir"},
        {"url": "https://www.tasnimnews.com/fa/news",         "name": "تسنیم",                "base_url": "https://www.tasnimnews.com"},
        {"url": "https://www.isna.ir/",                       "name": "ایسنا",                "base_url": "https://www.isna.ir"},
        {"url": "https://www.irna.ir/",                       "name": "ایرنا",                "base_url": "https://www.irna.ir"},
        {"url": "https://ir.sputniknews.com/",                "name": "اسپوتنیک فارسی",       "base_url": "https://ir.sputniknews.com"},
    ],
    "Deutsch 🇩🇪": [
        {"url": "https://www.focus.de/",                      "name": "Focus",                "base_url": "https://www.focus.de"},
        {"url": "https://www.spiegel.de/",                    "name": "Der Spiegel",          "base_url": "https://www.spiegel.de"},
        {"url": "https://www.zeit.de/",                       "name": "Die Zeit",             "base_url": "https://www.zeit.de"},
        {"url": "https://www.n-tv.de/",                       "name": "n-tv",                 "base_url": "https://www.n-tv.de"},
        {"url": "https://www.sueddeutsche.de/",               "name": "Süddeutsche Zeitung",  "base_url": "https://www.sueddeutsche.de"},
    ],
    "Español 🇲🇽": [
        {"url": "https://www.clarin.com/ultimo-momento/",     "name": "Clarín",               "base_url": "https://www.clarin.com"},
        {"url": "https://www.infobae.com/",                   "name": "Infobae",              "base_url": "https://www.infobae.com"},
        {"url": "https://www.elmundo.es/",                    "name": "El Mundo",             "base_url": "https://www.elmundo.es"},
        {"url": "https://elpais.com/",                        "name": "El País",              "base_url": "https://elpais.com"},
        {"url": "https://es.sputniknews.com/",                "name": "Sputnik Español",      "base_url": "https://es.sputniknews.com"},
    ],
    "Português 🇧🇷": [
        {"url": "https://noticias.uol.com.br/",               "name": "UOL Notícias",         "base_url": "https://noticias.uol.com.br"},
        {"url": "https://www.terra.com.br/noticias/",         "name": "Terra Brasil",         "base_url": "https://www.terra.com.br"},
        {"url": "https://www.correiobraziliense.com.br/",     "name": "Correio Braziliense",  "base_url": "https://www.correiobraziliense.com.br"},
        {"url": "https://pt.sputniknews.com/",                "name": "Sputnik Português",    "base_url": "https://pt.sputniknews.com"},
    ],
    "हिन्दी 🇮🇳": [
        {"url": "https://www.ndtv.com/india/",                "name": "NDTV Hindi",           "base_url": "https://www.ndtv.com"},
        {"url": "https://www.bhaskar.com/",                   "name": "Dainik Bhaskar",       "base_url": "https://www.bhaskar.com"},
        {"url": "https://hindi.news18.com/",                  "name": "News18 Hindi",         "base_url": "https://hindi.news18.com"},
    ],
    "اردو 🇵🇰": [
        {"url": "https://www.geo.tv/",                        "name": "Geo TV",               "base_url": "https://www.geo.tv"},
        {"url": "https://www.dunyanews.tv/",                  "name": "Dunya News",           "base_url": "https://www.dunyanews.tv"},
        {"url": "https://jang.com.pk/",                       "name": "جنگ",                  "base_url": "https://jang.com.pk"},
    ],
    "Українська 🇺🇦": [
        {"url": "https://www.pravda.com.ua/",                 "name": "Українська правда",    "base_url": "https://www.pravda.com.ua"},
        {"url": "https://www.unian.ua/",                      "name": "УНІАН",                "base_url": "https://www.unian.ua"},
        {"url": "https://ukrinform.ua/",                      "name": "Укрінформ",            "base_url": "https://ukrinform.ua"},
    ],
    "Italiano 🇮🇹": [
        {"url": "https://www.ansa.it/sito/notizie/topnews/",  "name": "ANSA",                 "base_url": "https://www.ansa.it"},
        {"url": "https://www.corriere.it/",                   "name": "Corriere della Sera",  "base_url": "https://www.corriere.it"},
        {"url": "https://www.repubblica.it/",                 "name": "La Repubblica",        "base_url": "https://www.repubblica.it"},
    ],
}

# ======== قنوات تلغرام كمصادر أخبار (عراقية وعالمية) ========
TELEGRAM_NEWS_CHANNELS = {
    "العربية 🇮🇶": [
        # ===== وكالات أخبار عراقية (مُختبَرة وتعمل) =====
        {"handle": "inainaiq",          "name": "وكالة الأنباء العراقية"},
        {"handle": "shafaq",            "name": "شفق نيوز"},
        {"handle": "alsbaahiq",         "name": "الصباح العراقية"},
        {"handle": "almaalomah",        "name": "المعلومة"},
        {"handle": "baghdadtoday",      "name": "بغداد اليوم"},
        {"handle": "RN24_IQ",           "name": "راديو نوا 24"},
        {"handle": "StevenNabilIraq",   "name": "ستيفن نبيل"},
        {"handle": "baghdad7city",      "name": "بغداد سيتي"},
        {"handle": "RudawArabic",       "name": "رووداو عربي"},
        {"handle": "NRT_Arabic",        "name": "NRT عربي"},
        {"handle": "burathanews",       "name": "بروثا نيوز"},
        {"handle": "iraq_news_now",     "name": "أخبار العراق"},
        {"handle": "kirkuk_now",        "name": "كركوك ناو"},
        {"handle": "iraq11e",           "name": "عين العراق"},
        {"handle": "iraqi1_news",       "name": "شبكة أخبار العراق"},
        {"handle": "Iraq_now3",         "name": "عراق ناو"},
        # ===== وكالات عالمية بالعربية =====
        {"handle": "RT_ar",             "name": "RT عربي"},
        {"handle": "aljazeera",         "name": "الجزيرة"},
        {"handle": "alarabiya",         "name": "العربية"},
        {"handle": "bbcarabic",         "name": "بي بي سي عربي"},
        {"handle": "france24_ar",       "name": "فرانس 24 عربي"},
        {"handle": "DWArabic",          "name": "DW عربي"},
        {"handle": "independentarabia", "name": "إندبندنت عربية"},
        {"handle": "arabi21news",       "name": "عربي 21"},
        {"handle": "almayadeen_ar",     "name": "الميادين"},
    ],
    "English 🇬🇧": [
        {"handle": "ap_news",           "name": "Associated Press"},
        {"handle": "BBCWorld",          "name": "BBC World"},
        {"handle": "AlJazeera",         "name": "Al Jazeera English"},
        {"handle": "cnnbrk",            "name": "CNN Breaking News"},
        {"handle": "guardian",          "name": "The Guardian"},
        {"handle": "Independent",       "name": "The Independent"},
        {"handle": "TheEconomist",      "name": "The Economist"},
        {"handle": "politico",          "name": "Politico"},
    ],
    "Русский 🇷🇺": [
        {"handle": "tass_agency",       "name": "ТАСС"},
        {"handle": "rianewsru",         "name": "РИА Новости"},
        {"handle": "lenta_ru",          "name": "Лента.ру"},
        {"handle": "kommersant",        "name": "Коммерсантъ"},
        {"handle": "izvestia",          "name": "Известия"},
        {"handle": "rbc_news",          "name": "РБК Новости"},
    ],
    "Türkçe 🇹🇷": [
        {"handle": "anadoluajansi",     "name": "Anadolu Ajansı"},
    ],
    "فارسی 🇮🇷": [
        {"handle": "bbcpersian",        "name": "بیبیسی فارسی"},
    ],
    "Deutsch 🇩🇪": [
        {"handle": "dwnachrichten",     "name": "DW Nachrichten"},
    ],
    "Español 🇲🇽": [
        {"handle": "RTenEspanol",       "name": "RT en Español"},
        {"handle": "elpais",            "name": "El País"},
    ],
    "Français 🇫🇷": [
        {"handle": "lemondefr",         "name": "Le Monde"},
        {"handle": "rfi_francais",      "name": "RFI Français"},
    ],
    "中文 🇨🇳": [
        {"handle": "xinhua_cn",         "name": "新华社"},
        {"handle": "cgtn_cn",           "name": "CGTN中文"},
    ],
    "हिन्दी 🇮🇳": [
        {"handle": "ndtvindia",         "name": "NDTV India"},
        {"handle": "bbc_hindi",         "name": "BBC Hindi"},
    ],
    "Italiano 🇮🇹": [
        {"handle": "larepubblica",      "name": "la Repubblica"},
    ],
}

_TG_SCRAPE_CACHE = {}       # handle -> (items, timestamp)
_TG_SCRAPE_CACHE_TTL = 180  # 3 دقائق

def _scrape_telegram_channel(handle, max_items=8):
    """
    يسحب أحدث المنشورات من قناة تلغرام عامة عبر t.me/s/{handle}
    يُعيد قائمة من (text, link) — النص قبل تنظيف AI
    """
    if not _BS4_AVAILABLE:
        return []

    now = datetime.datetime.now()
    cached = _TG_SCRAPE_CACHE.get(handle)
    if cached:
        items, ts = cached
        if (now - ts).total_seconds() < _TG_SCRAPE_CACHE_TTL:
            return items

    url = f"https://t.me/s/{handle}"
    try:
        resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        return []

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        posts = soup.select(".tgme_widget_message_wrap")[-max_items:]
        items = []
        for post in reversed(posts):
            # رابط المنشور
            link_tag = post.select_one(".tgme_widget_message_date")
            link = link_tag["href"] if link_tag and link_tag.has_attr("href") else ""
            # نص المنشور
            text_tag = post.select_one(".tgme_widget_message_text")
            if not text_tag:
                continue
            raw_text = text_tag.get_text(separator="\n", strip=True)
            # ─── حذف أسطر الروابط والتوقيعات من نهاية المنشور ────────
            import re as _re
            cleaned_lines = []
            for line in raw_text.splitlines():
                stripped = line.strip()
                # تخطى الأسطر التي هي مجرد رابط t.me أو @قناة
                if _re.match(r'^https?://t\.me/\S+$', stripped):
                    continue
                if _re.match(r'^@[A-Za-z0-9_]{3,}$', stripped):
                    continue
                if _re.match(r'^t\.me/\S+$', stripped):
                    continue
                cleaned_lines.append(line)
            raw_text = "\n".join(cleaned_lines).strip()
            if len(raw_text) < 20:
                continue
            items.append((raw_text, link))
        _TG_SCRAPE_CACHE[handle] = (items, now)
        return items
    except Exception:
        return []


# ─── سعر دولار السوق من قناة @dollariraqi ─────────────────────────
_DOLLAR_IRAQI_CACHE: dict = {"text": None, "ts": 0.0}
_DOLLAR_IRAQI_TTL = 600  # 10 دقائق

# الأنماط المسموح باستخراجها فقط (الأسعار)
_DOLLAR_IRAQI_ALLOWED_PATTERNS = [
    r'▣[^\n]+',            # عناوين المناطق  ▣بغداد-صيرفات:
    r'🔹[^\n]+',           # أسعار البيع والشراء
    r'💎[^\n]+',           # سعر الذهب
    r'[\U0001F1E0-\U0001F1FF]{2}[^\n]+',  # أعلام + سعر (اليورو، الدولار، إلخ)
    r'[٠-٩0-9,،.]+\s*(?:دينار|iqd|بيع|شراء|\$|IQD)',  # أرقام الأسعار
]

def _fetch_dollariraqi_market() -> str | None:
    """
    يسحب آخر رسالة من قناة @dollariraqi ويستخرج الأسعار فقط.
    يُعيد نص منظف يحتوي فقط على أسعار الصرف — بدون حقوق القناة.
    النتيجة مخزنة 10 دقائق.
    """
    now = time.time()
    # تحقق من الكاش
    if _DOLLAR_IRAQI_CACHE["text"] and now - _DOLLAR_IRAQI_CACHE["ts"] < _DOLLAR_IRAQI_TTL:
        return _DOLLAR_IRAQI_CACHE["text"]

    # سحب آخر رسالة من القناة
    posts = _scrape_telegram_channel("dollariraqi", max_items=5)
    if not posts:
        return None

    # آخر رسالة (الأحدث — القائمة مرتبة من الأقدم للأحدث، نأخذ الأخير)
    raw_text = posts[-1][0] if posts else ""
    if not raw_text or len(raw_text) < 20:
        return None

    # تنظيف AI: استخراج الأسعار فقط
    cleaned = _ai_extract_dollar_rates(raw_text)
    if cleaned:
        _DOLLAR_IRAQI_CACHE["text"] = cleaned
        _DOLLAR_IRAQI_CACHE["ts"]   = now
    return cleaned


def _ai_extract_dollar_rates(raw_text: str) -> str:
    """
    AI يستخرج فقط أسعار العملات والذهب من نص القناة —
    يحذف تلقائياً: اسم القناة، حقوق النشر، @mentions، الإعلانات،
    أي نص لا علاقة له بالأسعار.
    """
    # تنظيف regex أولي — حذف @mentions وروابط
    import re as _re_d
    text_clean = _re_d.sub(r'@\S+', '', raw_text)
    text_clean = _re_d.sub(r'https?://\S+', '', text_clean)
    text_clean = _re_d.sub(r'#\S+', '', text_clean).strip()

    # استخراج regex مباشر بدون AI (سريع وموثوق)
    lines = text_clean.split('\n')
    keep = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # الأسطر المسموحة: تبدأ بـ ▣ أو 🔹 أو 💎 أو علم أو تحتوي على أرقام أسعار
        has_price = bool(_re_d.search(r'[0-9٠-٩][0-9٠-٩,،. ]{3,}', line))
        has_marker = any(line.startswith(m) for m in ['▣', '🔹', '💎', '🇦', '🇺', '🇪', '🇬', '🇸'])
        # تجاهل الأسطر الدعائية: تحتوي على "قناة" أو "اشتر" أو تبدأ بـ " — " أو قصيرة جداً
        is_promo = any(w in line for w in ['قناة', 'اشترك', 'تواصل', 'واتس', 'telegram', 'Telegram', 'bot', 'Bot', '©', 'حقوق'])
        if is_promo:
            continue
        if (has_price or has_marker) and len(line) < 120:
            keep.append(line)

    if keep:
        return '\n'.join(keep)

    # fallback: AI إذا فشل الاستخراج بـ regex
    if not _AI_AVAILABLE or not _AI_MODEL:
        return text_clean[:400]

    prompt = (
        "من النص التالي، استخرج فقط أسعار الدولار والعملات والذهب.\n"
        "القواعد الصارمة:\n"
        "✅ اقتصر على: ▣بغداد-صيرفات، 🔹البيع والشراء، 💎الذهب، 🇪🇺اليورو، أي عملة وسعرها\n"
        "❌ احذف تماماً: اسم القناة، @mentions، الروابط، عبارات الاشتراك، الإعلانات\n"
        "❌ احذف: أي جملة لا تحتوي على رقم سعر\n"
        "لا تضف أي تعليق — فقط الأسعار بنفس التنسيق الأصلي.\n\n"
        f"النص:\n{text_clean[:800]}"
    )
    _h = [text_clean[:300]]
    def _c():
        try:
            r = _AI_MODEL.generate_content(prompt)
            if r and r.text:
                _h[0] = r.text.strip()
        except Exception:
            pass
    _t = threading.Thread(target=_c, daemon=True)
    _t.start()
    _t.join(timeout=6)
    return _h[0]


def _is_iraqi_user(uid) -> bool:
    """يتحقق إذا كان المستخدم من العراق (لغة عربية عراقية أو مدينة عراقية)"""
    user = users.get(str(uid), {})
    lang = user.get("lang", "")
    province = user.get("province", "")
    if lang == "العربية 🇮🇶":
        return True
    iraqi_cities = {
        "بغداد", "بصرة", "موصل", "اربيل", "كربلاء", "نجف", "كركوك",
        "سليمانية", "ديالى", "بابل", "الانبار", "الديوانية", "ميسان",
        "واسط", "ذي قار", "صلاح الدين", "نينوى", "دهوك", "المثنى",
        "Baghdad", "Basra", "Mosul", "Erbil", "Karbala", "Najaf",
    }
    if province and any(c.lower() in province.lower() for c in iraqi_cities):
        return True
    return False


def _scrape_news_site(url, base_url, max_items=10):
    """
    يسحب الأخبار من صفحة موقع بدون RSS.
    يجرب أنماط CSS متعددة للعثور على العناوين والروابط تلقائياً.
    يُعيد قائمة من (title, full_link).
    """
    if not _BS4_AVAILABLE:
        return []

    # فحص الكاش أولاً
    with _SCRAPE_LOCK:
        cached = _SCRAPE_CACHE.get(url)
        if cached:
            items, ts = cached
            if (datetime.datetime.now() - ts).total_seconds() < _SCRAPE_CACHE_TTL:
                return items

    items = []
    seen_links = set()

    def _fetch():
        try:
            resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=_SCRAPE_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return None

    # جلب الصفحة في thread منفصل حتى لا يُجمّد البوت
    result_html = [None]
    t = threading.Thread(target=lambda: result_html.__setitem__(0, _fetch()), daemon=True)
    t.start()
    t.join(_SCRAPE_TIMEOUT + 2)

    html = result_html[0]
    if not html:
        return []

    try:
        soup = BeautifulSoup(html, 'html.parser')

        # إزالة عناصر غير مفيدة (قوائم التنقل، تذييل الصفحة، الإعلانات)
        for tag in soup.select('nav, footer, header, script, style, .ad, .advertisement, .sidebar'):
            tag.decompose()

        candidates = []

        # ---- الأنماط المرتبة من الأدق إلى الأعم ----

        # النمط 1: روابط داخل وسم article
        for a in soup.select('article a[href]'):
            title = a.get_text(strip=True)
            href = a.get('href', '').strip()
            if len(title) > 25 and href:
                candidates.append((title, href))

        # النمط 2: h2/h3 داخل وسم article
        if len(candidates) < 5:
            for h in soup.select('article h2, article h3'):
                a = h.find('a', href=True)
                if a:
                    title = a.get_text(strip=True)
                    href = a['href'].strip()
                    if len(title) > 25:
                        candidates.append((title, href))

        # النمط 3: كلاسات شائعة لعناوين الأخبار
        if len(candidates) < 5:
            for sel in [
                'h2 a[href]', 'h3 a[href]',
                '.title a[href]', '.news-title a[href]',
                '.story-title a[href]', '.article-title a[href]',
                '.entry-title a[href]', '.headline a[href]',
                '.post-title a[href]', '.card-title a[href]',
                'a.title[href]', 'a.headline[href]',
            ]:
                for a in soup.select(sel):
                    title = a.get_text(strip=True)
                    href = a.get('href', '').strip()
                    if len(title) > 25 and href:
                        candidates.append((title, href))
                if len(candidates) >= 10:
                    break

        # ---- تنظيف الروابط وتحويلها إلى مطلقة ----
        for title, href in candidates:
            if len(items) >= max_items:
                break
            if not href:
                continue
            # تحويل النسبي إلى مطلق
            if href.startswith('//'):
                href = 'https:' + href
            elif href.startswith('/'):
                href = base_url.rstrip('/') + href
            elif not href.startswith('http'):
                continue
            # تجاهل روابط التصنيف والمؤلف والأنكور
            if any(x in href for x in ['#', 'javascript:', 'mailto:', '/tag/', '/category/', '/author/', '/page/']):
                continue
            if href in seen_links:
                continue
            seen_links.add(href)
            # تنظيف العنوان من رموز زائدة
            title = ' '.join(title.split())
            if len(title) > 200:
                title = title[:200] + '…'
            items.append((title, href))

    except Exception:
        pass

    # تخزين في الكاش حتى لو فارغة (لتجنب الطلبات المتكررة على موقع فاشل)
    with _SCRAPE_LOCK:
        _SCRAPE_CACHE[url] = (items, datetime.datetime.now())

    return items


def get_scraped_news(lang, max_per_source=5):
    """
    جلب الأخبار بالـ scraping من جميع مصادر لغة معينة.
    يُعيد قائمة من dicts: {title, link, source}
    """
    if not _BS4_AVAILABLE:
        return []
    sources = SCRAPE_SOURCES.get(lang, [])
    results = []
    for src in sources:
        try:
            items = _scrape_news_site(src['url'], src['base_url'], max_items=max_per_source)
            for title, link in items:
                results.append({
                    'title': title,
                    'link': link,
                    'source': src['name'],
                })
        except Exception:
            pass
    return results


# ======== الكلمات المفتاحية للمستخدمين المميزين ========
user_keywords = load_json(KEYWORDS_FILE, {})

def save_keywords():
    save_json(KEYWORDS_FILE, user_keywords)

# ======== تتبع العملات والأسهم ========
tracked_assets = load_json(TRACK_FILE, {})

def save_tracked_assets():
    save_json(TRACK_FILE, tracked_assets)

# ======== الأزرار ========
BUTTONS = {
    "العربية 🇮🇶": {
        "weather": "🌤 الطقس الآن",
        "forecast": "📅 توقعات 3 أيام",
        "news": "📰 آخر الأخبار",
        "all_news": "📰 إرسال كل الأخبار",
        "mena_politics": "📰 أخبار الشرق الأوسط",
        "trending": "🔥 الأكثر تداولاً",
        "sports": "⚽ أخبار الرياضة",
        "daily_summary": "📋 ملخص أخبار اليوم",
        "weekly_summary": "📆 ملخص أسبوعي",
        "news_cats": "🗂 اختيار أنواع الأخبار",
        "currency": "💱 أسعار العملات",
        "dollar_parallel": "💵 دولار السوق",
        "convert": "🔄 محوّل العملات",
        "crypto": "💎 العملات الرقمية",
        "track_asset": "📌 تتبع عملة/سهم",
        "prayer": "🕌 أوقات الصلاة",
        "search": "🔍 بحث في الأخبار",
        "deepsearch": "🧠 بحث عميق بالذكاء الاصطناعي",
        "my_stats": "📈 إحصائياتي",
        "referral": "🎁 دعواتي",
        "top_referrers": "🏆 أفضل الداعين",
        "share_bot": "📢 انشر البوت",
        "public_stats": "📊 إحصائيات البوت",
        "voice_news": "🎙️ أخبار صوتية",
        "notif_on": "🔔 إيقاف الإشعارات",
        "notif_off": "🔕 تفعيل الإشعارات",
        "premium": "⭐ المميز",
        "settings": "🔄 تغيير الإعدادات",
        "choose": "✅ اختر ما تريد:"
    },
    "English 🇬🇧": {
        "weather": "🌤 Weather Now",
        "forecast": "📅 3-Day Forecast",
        "news": "📰 Latest News",
        "all_news": "📰 Send All News",
        "mena_politics": "📰 Middle East News",
        "trending": "🔥 Trending News",
        "sports": "⚽ Sports News",
        "daily_summary": "📋 Daily News Summary",
        "weekly_summary": "📆 Weekly Summary",
        "news_cats": "🗂 News Categories",
        "currency": "💱 Currency Rates",
        "dollar_parallel": "💵 Parallel Dollar",
        "convert": "🔄 Currency Converter",
        "crypto": "💎 Crypto Prices",
        "track_asset": "📌 Track Asset",
        "prayer": "🕌 Prayer Times",
        "search": "🔍 Search News",
        "deepsearch": "🧠 AI Deep Search",
        "my_stats": "📈 My Statistics",
        "referral": "🎁 My Referrals",
        "top_referrers": "🏆 Top Referrers",
        "share_bot": "📢 Share Bot",
        "public_stats": "📊 Bot Statistics",
        "voice_news": "🎙️ Voice News",
        "notif_on": "🔔 Disable Notifications",
        "notif_off": "🔕 Enable Notifications",
        "premium": "⭐ Premium",
        "settings": "🔄 Change Settings",
        "choose": "✅ Choose what you want:"
    },
    "Русский 🇷🇺": {
        "weather": "🌤 Погода сейчас",
        "forecast": "📅 Прогноз на 3 дня",
        "news": "📰 Последние новости",
        "all_news": "📰 Все новости",
        "mena_politics": "📰 Ближний Восток",
        "trending": "🔥 В тренде",
        "sports": "⚽ Спортивные новости",
        "daily_summary": "📋 Сводка дня",
        "weekly_summary": "📆 Недельный итог",
        "news_cats": "🗂 Категории новостей",
        "currency": "💱 Курсы валют",
        "dollar_parallel": "💵 Параллельный доллар",
        "convert": "🔄 Конвертер валют",
        "crypto": "💎 Криптовалюты",
        "track_asset": "📌 Отслеживать актив",
        "prayer": "🕌 Время намаза",
        "search": "🔍 Поиск новостей",
        "deepsearch": "🧠 Глубокий поиск ИИ",
        "my_stats": "📈 Моя статистика",
        "referral": "🎁 Мои приглашения",
        "top_referrers": "🏆 Лучшие",
        "share_bot": "📢 Поделиться ботом",
        "public_stats": "📊 Статистика бота",
        "voice_news": "🎙️ Голосовые новости",
        "notif_on": "🔔 Отключить уведомления",
        "notif_off": "🔕 Включить уведомления",
        "premium": "⭐ Премиум",
        "settings": "🔄 Изменить настройки",
        "choose": "✅ Выберите:"
    },
    "فارسی 🇮🇷": {
        "weather": "🌤 آبوهوا",
        "forecast": "📅 پیشبینی ۳ روزه",
        "news": "📰 آخرین اخبار",
        "all_news": "📰 ارسال همه اخبار",
        "mena_politics": "📰 اخبار خاورمیانه",
        "trending": "🔥 پرتداولترین",
        "sports": "⚽ اخبار ورزشی",
        "daily_summary": "📋 خلاصه اخبار امروز",
        "weekly_summary": "📆 خلاصه هفتگی",
        "news_cats": "🗂 دستهبندی اخبار",
        "currency": "💱 نرخ ارز",
        "dollar_parallel": "💵 دلار موازی",
        "convert": "🔄 تبدیل ارز",
        "crypto": "💎 ارز دیجیتال",
        "track_asset": "📌 پیگیری دارایی",
        "prayer": "🕌 اوقات نماز",
        "search": "🔍 جستجوی اخبار",
        "deepsearch": "🧠 جستجوی عمیق هوش مصنوعی",
        "my_stats": "📈 آمار من",
        "referral": "🎁 دعوتهایم",
        "top_referrers": "🏆 برترینها",
        "share_bot": "📢 اشتراکگذاری ربات",
        "public_stats": "📊 آمار ربات",
        "voice_news": "🎙️ اخبار صوتی",
        "notif_on": "🔔 غیرفعالکردن اعلانها",
        "notif_off": "🔕 فعالکردن اعلانها",
        "premium": "⭐ ویژه",
        "settings": "🔄 تغییر تنظیمات",
        "choose": "✅ انتخاب کنید:"
    },
    "हिन्दी 🇮🇳": {
        "weather": "🌤 मौसम अभी",
        "forecast": "📅 3-दिन का पूर्वानुमान",
        "news": "📰 ताज़ा खबरें",
        "all_news": "📰 सभी खबरें भेजें",
        "mena_politics": "📰 मध्य पूर्व समाचार",
        "trending": "🔥 ट्रेंडिंग",
        "sports": "⚽ खेल समाचार",
        "daily_summary": "📋 आज की खबर सारांश",
        "weekly_summary": "📆 साप्ताहिक सारांश",
        "news_cats": "🗂 समाचार श्रेणियाँ",
        "currency": "💱 मुद्रा दरें",
        "dollar_parallel": "💵 Parallel Dollar",
        "convert": "🔄 मुद्रा परिवर्तक",
        "crypto": "💎 क्रिप्टो कीमतें",
        "track_asset": "📌 Asset Track",
        "prayer": "🕌 नमाज़ के वक्त",
        "search": "🔍 खबर खोजें",
        "deepsearch": "🧠 AI गहन खोज",
        "my_stats": "📈 मेरे आँकड़े",
        "referral": "🎁 मेरे रेफरल",
        "top_referrers": "🏆 शीर्ष",
        "share_bot": "📢 बॉट शेयर करें",
        "public_stats": "📊 बॉट आँकड़े",
        "voice_news": "🎙️ आवाज़ समाचार",
        "voice_news": "🎙️ आवाज़ समाचार",
        "notif_on": "🔔 सूचनाएं बंद करें",
        "notif_off": "🔕 सूचनाएं चालू करें",
        "premium": "⭐ प्रीमियम",
        "settings": "🔄 सेटिंग बदलें",
        "choose": "✅ चुनें:"
    },
    "Português 🇧🇷": {
        "weather": "🌤 Clima agora",
        "forecast": "📅 Previsão 3 dias",
        "news": "📰 Últimas notícias",
        "all_news": "📰 Enviar todas notícias",
        "mena_politics": "📰 Oriente Médio",
        "trending": "🔥 Em alta",
        "sports": "⚽ Esportes",
        "daily_summary": "📋 Resumo do dia",
        "weekly_summary": "📆 Resumo semanal",
        "news_cats": "🗂 Categorias de notícias",
        "currency": "💱 Taxas de câmbio",
        "dollar_parallel": "💵 Dólar paralelo",
        "convert": "🔄 Conversor de moeda",
        "crypto": "💎 Criptomoedas",
        "track_asset": "📌 Monitorar ativo",
        "prayer": "🕌 Horários de oração",
        "search": "🔍 Buscar notícias",
        "deepsearch": "🧠 Pesquisa profunda IA",
        "my_stats": "📈 Minhas estatísticas",
        "referral": "🎁 Minhas indicações",
        "top_referrers": "🏆 Melhores",
        "share_bot": "📢 Compartilhar bot",
        "public_stats": "📊 Estatísticas",
        "voice_news": "🎙️ Notícias por voz",
        "notif_on": "🔔 Desativar notificações",
        "notif_off": "🔕 Ativar notificações",
        "premium": "⭐ Premium",
        "settings": "🔄 Mudar configurações",
        "choose": "✅ Escolha:"
    },
    "Türkçe 🇹🇷": {
        "weather": "🌤 Hava durumu",
        "forecast": "📅 3 Günlük Tahmin",
        "news": "📰 Son haberler",
        "all_news": "📰 Tüm haberleri gönder",
        "mena_politics": "📰 Orta Doğu",
        "trending": "🔥 Trend haberler",
        "sports": "⚽ Spor haberleri",
        "daily_summary": "📋 Günlük özet",
        "weekly_summary": "📆 Haftalık özet",
        "news_cats": "🗂 Haber kategorileri",
        "currency": "💱 Döviz kurları",
        "dollar_parallel": "💵 Paralel dolar",
        "convert": "🔄 Döviz çevirici",
        "crypto": "💎 Kripto fiyatları",
        "track_asset": "📌 Varlık takibi",
        "prayer": "🕌 Namaz vakitleri",
        "search": "🔍 Haber ara",
        "deepsearch": "🧠 Yapay Zeka Derin Arama",
        "my_stats": "📈 İstatistiklerim",
        "referral": "🎁 Davetlerim",
        "top_referrers": "🏆 En İyiler",
        "share_bot": "📢 Botu paylaş",
        "public_stats": "📊 Bot istatistikleri",
        "voice_news": "🎙️ Sesli Haberler",
        "notif_on": "🔔 Bildirimleri kapat",
        "notif_off": "🔕 Bildirimleri aç",
        "premium": "⭐ Premium",
        "settings": "🔄 Ayarları değiştir",
        "choose": "✅ Seçin:"
    },
    "اردو 🇵🇰": {
        "weather": "🌤 موسم ابھی",
        "forecast": "📅 3 دن کی پیشگوئی",
        "news": "📰 تازہ خبریں",
        "all_news": "📰 تمام خبریں بھیجیں",
        "mena_politics": "📰 مشرق وسطی خبریں",
        "trending": "🔥 ٹرینڈنگ خبریں",
        "sports": "⚽ کھیل کی خبریں",
        "daily_summary": "📋 آج کا خلاصہ",
        "weekly_summary": "📆 ہفتہ وار خلاصہ",
        "news_cats": "🗂 خبروں کی اقسام",
        "currency": "💱 کرنسی ریٹ",
        "dollar_parallel": "💵 پیرالل ڈالر",
        "convert": "🔄 کرنسی کنورٹر",
        "crypto": "💎 کرپٹو قیمتیں",
        "track_asset": "📌 اثاثہ ٹریک",
        "prayer": "🕌 نماز کے اوقات",
        "search": "🔍 خبریں تلاش کریں",
        "deepsearch": "🧠 AI گہری تلاش",
        "my_stats": "📈 میرے اعداد",
        "referral": "🎁 میری دعوتیں",
        "top_referrers": "🏆 بہترین",
        "share_bot": "📢 بوٹ شیئر کریں",
        "public_stats": "📊 بوٹ اعداد",
        "voice_news": "🎙️ آواز خبریں",
        "voice_news": "🎙️ آواز خبریں",
        "notif_on": "🔔 اطلاعات بند کریں",
        "notif_off": "🔕 اطلاعات چالو کریں",
        "premium": "⭐ پریمیم",
        "settings": "🔄 ترتیبات بدلیں",
        "choose": "✅ انتخاب کریں:"
    },
    "Deutsch 🇩🇪": {
        "weather": "🌤 Wetter jetzt",
        "forecast": "📅 3-Tage-Prognose",
        "news": "📰 Neueste Nachrichten",
        "all_news": "📰 Alle Nachrichten",
        "mena_politics": "📰 Nahost-Nachrichten",
        "trending": "🔥 Trending",
        "sports": "⚽ Sportnachrichten",
        "daily_summary": "📋 Tageszusammenfassung",
        "weekly_summary": "📆 Wochenzusammenfassung",
        "news_cats": "🗂 Nachrichtenkategorien",
        "currency": "💱 Wechselkurse",
        "dollar_parallel": "💵 Parallelkurs Dollar",
        "convert": "🔄 Währungsrechner",
        "crypto": "💎 Kryptowährungen",
        "track_asset": "📌 Asset verfolgen",
        "prayer": "🕌 Gebetszeiten",
        "search": "🔍 Nachrichten suchen",
        "deepsearch": "🧠 KI-Tiefensuche",
        "my_stats": "📈 Meine Statistiken",
        "referral": "🎁 Meine Einladungen",
        "top_referrers": "🏆 Beste",
        "share_bot": "📢 Bot teilen",
        "public_stats": "📊 Bot-Statistiken",
        "voice_news": "🎙️ Sprachnachrichten",
        "notif_on": "🔔 Benachrichtigungen aus",
        "notif_off": "🔕 Benachrichtigungen ein",
        "premium": "⭐ Premium",
        "settings": "🔄 Einstellungen ändern",
        "choose": "✅ Wählen Sie:"
    },
    "Українська 🇺🇦": {
        "weather": "🌤 Погода зараз",
        "forecast": "📅 Прогноз на 3 дні",
        "news": "📰 Останні новини",
        "all_news": "📰 Всі новини",
        "mena_politics": "📰 Близький Схід",
        "trending": "🔥 Тренди",
        "sports": "⚽ Спортивні новини",
        "daily_summary": "📋 Зведення дня",
        "weekly_summary": "📆 Тижневий підсумок",
        "news_cats": "🗂 Категорії новин",
        "currency": "💱 Курси валют",
        "dollar_parallel": "💵 Паралельний долар",
        "convert": "🔄 Конвертер валют",
        "crypto": "💎 Криптовалюти",
        "track_asset": "📌 Стежити за активом",
        "prayer": "🕌 Час молитви",
        "search": "🔍 Пошук новин",
        "deepsearch": "🧠 Глибокий пошук ШІ",
        "my_stats": "📈 Моя статистика",
        "referral": "🎁 Мої запрошення",
        "top_referrers": "🏆 Найкращі",
        "share_bot": "📢 Поділитися ботом",
        "public_stats": "📊 Статистика",
        "voice_news": "🎙️ Голосові новини",
        "notif_on": "🔔 Вимкнути сповіщення",
        "notif_off": "🔕 Увімкнути сповіщення",
        "premium": "⭐ Преміум",
        "settings": "🔄 Змінити налаштування",
        "choose": "✅ Оберіть:"
    },
    "Italiano 🇮🇹": {
        "weather": "🌤 Meteo ora",
        "forecast": "📅 Previsioni 3 giorni",
        "news": "📰 Ultime notizie",
        "all_news": "📰 Tutte le notizie",
        "mena_politics": "📰 Medio Oriente",
        "trending": "🔥 Notizie di tendenza",
        "sports": "⚽ Notizie sportive",
        "daily_summary": "📋 Riepilogo del giorno",
        "weekly_summary": "📆 Riepilogo settimanale",
        "news_cats": "🗂 Categorie notizie",
        "currency": "💱 Tassi di cambio",
        "dollar_parallel": "💵 Dollaro parallelo",
        "convert": "🔄 Convertitore valuta",
        "crypto": "💎 Criptovalute",
        "track_asset": "📌 Traccia attivo",
        "prayer": "🕌 Orari di preghiera",
        "search": "🔍 Cerca notizie",
        "deepsearch": "🧠 Ricerca profonda IA",
        "my_stats": "📈 Le mie statistiche",
        "referral": "🎁 I miei inviti",
        "top_referrers": "🏆 I migliori",
        "share_bot": "📢 Condividi bot",
        "public_stats": "📊 Statistiche bot",
        "voice_news": "🎙️ Notizie vocali",
        "notif_on": "🔔 Disattiva notifiche",
        "notif_off": "🔕 Attiva notifiche",
        "premium": "⭐ Premium",
        "settings": "🔄 Cambia impostazioni",
        "choose": "✅ Scegli:"
    },
    "Español 🇲🇽": {
        "weather": "🌤 Clima ahora",
        "forecast": "📅 Pronóstico 3 días",
        "news": "📰 Últimas noticias",
        "all_news": "📰 Todas las noticias",
        "mena_politics": "📰 Oriente Medio",
        "trending": "🔥 Tendencias",
        "sports": "⚽ Noticias deportivas",
        "daily_summary": "📋 Resumen del día",
        "weekly_summary": "📆 Resumen semanal",
        "news_cats": "🗂 Categorías de noticias",
        "currency": "💱 Tipos de cambio",
        "dollar_parallel": "💵 Dólar paralelo",
        "convert": "🔄 Conversor de divisas",
        "crypto": "💎 Criptomonedas",
        "track_asset": "📌 Rastrear activo",
        "prayer": "🕌 Horarios de oración",
        "search": "🔍 Buscar noticias",
        "deepsearch": "🧠 Búsqueda profunda IA",
        "my_stats": "📈 Mis estadísticas",
        "referral": "🎁 Mis invitaciones",
        "top_referrers": "🏆 Mejores",
        "share_bot": "📢 Compartir bot",
        "public_stats": "📊 Estadísticas",
        "voice_news": "🎙️ Noticias de voz",
        "notif_on": "🔔 Desactivar notificaciones",
        "notif_off": "🔕 Activar notificaciones",
        "premium": "⭐ Premium",
        "settings": "🔄 Cambiar configuración",
        "choose": "✅ Elige lo que quieres:"
    },
}

# ======== رسائل الترقية للمميز ========
PREMIUM_UPGRADE_MSG = {
    "العربية 🇮🇶": (
        "⭐ *الاشتراك المميز*\n\n"
        "احصل على مميزات حصرية:\n\n"
        "🌤 توقعات الطقس لـ 7 أيام\n"
        "🏙 إضافة أكثر من مدينة\n"
        "📌 أخبار حسب اهتماماتك\n"
        "⚡ أخبار عاجلة فورية كل 15 دقيقة\n"
        "🌅 ملخص صباحي يومي\n"
        "💱 تنبيه عند تغير سعر العملة\n"
        "🌧 تنبيه تغيرات الطقس\n"
        "🕐 اختيار وقت الإشعارات\n\n"
        "للاشتراك اضغط الزر أدناه 👇"
    ),
    "English 🇬🇧": (
        "⭐ *Premium Subscription*\n\n"
        "Get exclusive features:\n\n"
        "🌤 7-day weather forecast\n"
        "🏙 Add multiple cities\n"
        "📌 News by your interests\n"
        "⚡ Instant breaking news every 15 min\n"
        "🌅 Daily morning summary\n"
        "💱 Currency rate alerts\n"
        "🌧 Weather change alerts\n"
        "🕐 Choose your notification time\n\n"
        "Press the button below to subscribe 👇"
    ),
    "Русский 🇷🇺": (
        "⭐ *Премиум подписка*\n\n"
        "Получите эксклюзивные функции:\n\n"
        "🌤 Прогноз погоды на 7 дней\n"
        "🏙 Добавить несколько городов\n"
        "📌 Новости по интересам\n"
        "⚡ Срочные новости каждые 15 минут\n"
        "🌅 Утренние сводки\n"
        "💱 Оповещения о курсе валют\n"
        "🌧 Оповещения о погоде\n"
        "🕐 Выбор времени уведомлений\n\n"
        "Нажмите кнопку ниже 👇"
    ),
    "فارسی 🇮🇷": (
        "⭐ *اشتراک ویژه*\n\n"
        "امکانات انحصاری:\n\n"
        "🌤 پیشبینی آبوهوا برای ۷ روز\n"
        "🏙 افزودن چند شهر\n"
        "📌 اخبار بر اساس علایق\n"
        "⚡ اخبار فوری هر ۱۵ دقیقه\n"
        "🌅 خلاصه صبحگاهی\n"
        "💱 هشدار نرخ ارز\n"
        "🌧 هشدار تغییرات آبوهوا\n"
        "🕐 انتخاب زمان اطلاعرسانی\n\n"
        "برای اشتراک دکمه زیر را بزنید 👇"
    ),
    "हिन्दी 🇮🇳": (
        "⭐ *प्रीमियम सदस्यता*\n\n"
        "विशेष सुविधाएं:\n\n"
        "🌤 7 दिनों का मौसम पूर्वानुमान\n"
        "🏙 कई शहर जोड़ें\n"
        "📌 आपकी रुचि की खबरें\n"
        "⚡ हर 15 मिनट में ताज़ा खबरें\n"
        "🌅 सुबह का सारांश\n"
        "💱 मुद्रा दर अलर्ट\n"
        "🌧 मौसम परिवर्तन अलर्ट\n"
        "🕐 अधिसूचना समय चुनें\n\n"
        "सदस्यता के लिए नीचे बटन दबाएं 👇"
    ),
    "Português 🇧🇷": (
        "⭐ *Assinatura Premium*\n\n"
        "Recursos exclusivos:\n\n"
        "🌤 Previsão do tempo por 7 dias\n"
        "🏙 Adicionar várias cidades\n"
        "📌 Notícias por seus interesses\n"
        "⚡ Últimas notícias a cada 15 min\n"
        "🌅 Resumo matinal diário\n"
        "💱 Alertas de câmbio\n"
        "🌧 Alertas de clima\n"
        "🕐 Escolha o horário de notificações\n\n"
        "Pressione o botão abaixo 👇"
    ),
    "Türkçe 🇹🇷": (
        "⭐ *Premium Üyelik*\n\n"
        "Özel özellikler:\n\n"
        "🌤 7 günlük hava durumu tahmini\n"
        "🏙 Birden fazla şehir ekle\n"
        "📌 İlgi alanına göre haberler\n"
        "⚡ Her 15 dakikada son dakika haberleri\n"
        "🌅 Günlük sabah özeti\n"
        "💱 Döviz kuru uyarıları\n"
        "🌧 Hava durumu uyarıları\n"
        "🕐 Bildirim saatini seç\n\n"
        "Abone olmak için aşağıdaki butona bas 👇"
    ),
    "اردو 🇵🇰": (
        "⭐ *پریمیم سبسکرپشن*\n\n"
        "خصوصی خصوصیات:\n\n"
        "🌤 7 دن کی موسم کی پیش گوئی\n"
        "🏙 متعدد شہر شامل کریں\n"
        "📌 آپ کی دلچسپی کی خبریں\n"
        "⚡ ہر 15 منٹ میں تازہ ترین خبریں\n"
        "🌅 روزانہ صبح کا خلاصہ\n"
        "💱 کرنسی ریٹ الرٹ\n"
        "🌧 موسم تبدیلی الرٹ\n"
        "🕐 اطلاع کا وقت منتخب کریں\n\n"
        "سبسکرائب کرنے کے لیے نیچے بٹن دبائیں 👇"
    ),
    "Deutsch 🇩🇪": (
        "⭐ *Premium-Abonnement*\n\n"
        "Exklusive Funktionen:\n\n"
        "🌤 7-Tage-Wettervorhersage\n"
        "🏙 Mehrere Städte hinzufügen\n"
        "📌 Nachrichten nach Interessen\n"
        "⚡ Breaking News alle 15 Minuten\n"
        "🌅 Tägliche Morgenzusammenfassung\n"
        "💱 Wechselkurs-Benachrichtigungen\n"
        "🌧 Wetterwarnungen\n"
        "🕐 Benachrichtigungszeit wählen\n\n"
        "Drücken Sie die Schaltfläche unten 👇"
    ),
    "Українська 🇺🇦": (
        "⭐ *Преміум підписка*\n\n"
        "Ексклюзивні функції:\n\n"
        "🌤 Прогноз погоди на 7 днів\n"
        "🏙 Додати кілька міст\n"
        "📌 Новини за інтересами\n"
        "⚡ Термінові новини кожні 15 хвилин\n"
        "🌅 Ранкова зведення\n"
        "💱 Сповіщення про курс валют\n"
        "🌧 Погодні попередження\n"
        "🕐 Вибір часу сповіщень\n\n"
        "Натисніть кнопку нижче 👇"
    ),
    "Italiano 🇮🇹": (
        "⭐ *Abbonamento Premium*\n\n"
        "Funzionalità esclusive:\n\n"
        "🌤 Previsioni meteo per 7 giorni\n"
        "🏙 Aggiungi più città\n"
        "📌 Notizie per i tuoi interessi\n"
        "⚡ Ultime notizie ogni 15 minuti\n"
        "🌅 Riassunto mattutino\n"
        "💱 Avvisi sul tasso di cambio\n"
        "🌧 Avvisi meteo\n"
        "🕐 Scegli l'orario delle notifiche\n\n"
        "Premi il pulsante qui sotto 👇"
    ),
    "Español 🇲🇽": (
        "⭐ *Suscripción Premium*\n\n"
        "Funciones exclusivas:\n\n"
        "🌤 Pronóstico del tiempo por 7 días\n"
        "🏙 Agregar varias ciudades\n"
        "📌 Noticias según tus intereses\n"
        "⚡ Últimas noticias cada 15 minutos\n"
        "🌅 Resumen matutino diario\n"
        "💱 Alertas de tipo de cambio\n"
        "🌧 Alertas meteorológicas\n"
        "🕐 Elige el horario de notificaciones\n\n"
        "Presiona el botón de abajo 👇"
    ),
}

# ======== الاهتمامات والكلمات المفتاحية ========
INTERESTS = {
    "العربية 🇮🇶": [
        "📰 سياسة", "💰 اقتصاد", "⚽ رياضة", "💻 تكنولوجيا",
        "🌍 أخبار العالم", "🚗 سيارات", "🏥 صحة",
        "🎬 فن وثقافة", "✈️ سفر وسياحة", "🔬 علوم", "🎲 منوعات"
    ],
    "English 🇬🇧": [
        "📰 Politics", "💰 Economy", "⚽ Sports", "💻 Technology",
        "🌍 World News", "🚗 Automotive", "🏥 Health",
        "🎬 Arts & Culture", "✈️ Travel", "🔬 Science", "🎲 Entertainment"
    ],
    "Русский 🇷🇺": [
        "📰 Политика", "💰 Экономика", "⚽ Спорт", "💻 Технологии",
        "🌍 Мировые новости", "🚗 Авто", "🏥 Здоровье",
        "🎬 Культура", "✈️ Путешествия", "🔬 Наука", "🎲 Развлечения"
    ],
    "فارسی 🇮🇷": [
        "📰 سیاست", "💰 اقتصاد", "⚽ ورزش", "💻 فناوری",
        "🌍 اخبار جهان", "🚗 خودرو", "🏥 سلامت",
        "🎬 هنر و فرهنگ", "✈️ سفر", "🔬 علوم", "🎲 سرگرمی"
    ],
    "हिन्दी 🇮🇳": [
        "📰 राजनीति", "💰 अर्थव्यवस्था", "⚽ खेल", "💻 प्रौद्योगिकी",
        "🌍 विश्व समाचार", "🚗 ऑटो", "🏥 स्वास्थ्य",
        "🎬 कला और संस्कृति", "✈️ यात्रा", "🔬 विज्ञान", "🎲 मनोरंजन"
    ],
    "Português 🇧🇷": [
        "📰 Política", "💰 Economia", "⚽ Esporte", "💻 Tecnologia",
        "🌍 Mundo", "🚗 Automóveis", "🏥 Saúde",
        "🎬 Arte e Cultura", "✈️ Viagem", "🔬 Ciência", "🎲 Entretenimento"
    ],
    "Türkçe 🇹🇷": [
        "📰 Siyaset", "💰 Ekonomi", "⚽ Spor", "💻 Teknoloji",
        "🌍 Dünya", "🚗 Otomotiv", "🏥 Sağlık",
        "🎬 Sanat ve Kültür", "✈️ Seyahat", "🔬 Bilim", "🎲 Eğlence"
    ],
    "اردو 🇵🇰": [
        "📰 سیاست", "💰 معیشت", "⚽ کھیل", "💻 ٹیکنالوجی",
        "🌍 عالمی خبریں", "🚗 آٹو", "🏥 صحت",
        "🎬 فن و ثقافت", "✈️ سفر", "🔬 سائنس", "🎲 تفریح"
    ],
    "Deutsch 🇩🇪": [
        "📰 Politik", "💰 Wirtschaft", "⚽ Sport", "💻 Technologie",
        "🌍 Welt", "🚗 Auto", "🏥 Gesundheit",
        "🎬 Kunst & Kultur", "✈️ Reisen", "🔬 Wissenschaft", "🎲 Unterhaltung"
    ],
    "Українська 🇺🇦": [
        "📰 Політика", "💰 Економіка", "⚽ Спорт", "💻 Технології",
        "🌍 Світ", "🚗 Авто", "🏥 Здоров'я",
        "🎬 Культура", "✈️ Подорожі", "🔬 Наука", "🎲 Розваги"
    ],
    "Italiano 🇮🇹": [
        "📰 Politica", "💰 Economia", "⚽ Sport", "💻 Tecnologia",
        "🌍 Mondo", "🚗 Auto", "🏥 Salute",
        "🎬 Arte e Cultura", "✈️ Viaggi", "🔬 Scienza", "🎲 Intrattenimento"
    ],
    "Español 🇲🇽": [
        "📰 Política", "💰 Economía", "⚽ Deporte", "💻 Tecnología",
        "🌍 Mundo", "🚗 Automóviles", "🏥 Salud",
        "🎬 Arte y Cultura", "✈️ Viajes", "🔬 Ciencia", "🎲 Entretenimiento"
    ],
}

INTEREST_KEYWORDS = {
    "سياسة": ["سياسة", "حكومة", "رئيس", "وزير", "برلمان", "انتخاب", "حزب", "قرار", "مجلس"],
    "اقتصاد": ["اقتصاد", "نفط", "دولار", "تجارة", "بنك", "مال", "بورصة", "سوق", "ميزانية", "استثمار"],
    "رياضة": ["رياضة", "كرة", "مباراة", "بطولة", "لاعب", "فريق", "هدف", "ملعب", "منتخب", "دوري"],
    "تكنولوجيا": ["تقنية", "تكنولوجيا", "ذكاء اصطناعي", "هاتف", "إنترنت", "تطبيق", "برنامج", "شركة تقنية"],
    "أخبار العالم": ["عالم", "دولي", "أمريكا", "أوروبا", "آسيا", "أفريقيا", "خارجية", "ناتو", "أمم متحدة"],
    "سيارات": ["سيارة", "سيارات", "مركبة", "سباق", "محرك", "كهربائية", "وقود", "أوتوماتيك"],
    "صحة": ["صحة", "مستشفى", "طبيب", "علاج", "مرض", "لقاح", "وباء", "دواء", "جراحة"],
    "فن وثقافة": ["فن", "ثقافة", "فيلم", "مسلسل", "موسيقى", "مهرجان", "معرض", "روائي", "شاعر", "فنان"],
    "سفر وسياحة": ["سفر", "سياحة", "رحلة", "فندق", "مطار", "وجهة", "سياحي", "جواز", "تأشيرة"],
    "علوم": ["علوم", "بحث", "اكتشاف", "فضاء", "ناسا", "كواكب", "تجربة", "دراسة", "باحثون"],
    "منوعات": ["منوعات", "طريف", "غريب", "عجيب", "حيوان", "طبيعة", "بيئة", "مناخ"],
    "politics": ["politics", "government", "president", "minister", "parliament", "election", "policy"],
    "economy": ["economy", "oil", "dollar", "trade", "bank", "finance", "market", "stock", "budget"],
    "sports": ["sport", "football", "match", "tournament", "player", "team", "goal", "league"],
    "technology": ["tech", "ai", "artificial intelligence", "internet", "app", "software", "phone", "digital"],
    "world news": ["world", "international", "global", "united nations", "nato", "foreign", "crisis"],
    "automotive": ["car", "vehicle", "automotive", "electric vehicle", "motor", "race", "fuel"],
    "health": ["health", "hospital", "doctor", "treatment", "disease", "vaccine", "medicine", "surgery"],
    "arts & culture": ["art", "culture", "film", "movie", "music", "festival", "exhibition", "artist"],
    "travel": ["travel", "tourism", "trip", "hotel", "airport", "destination", "visa", "flight"],
    "science": ["science", "research", "discovery", "space", "nasa", "planet", "experiment", "study"],
    "entertainment": ["entertainment", "celebrity", "viral", "funny", "trend", "social media"],
    "спорт": ["спорт", "футбол", "матч", "турнир", "игрок", "команда", "гол", "лига"],
    "экономика": ["экономика", "нефть", "доллар", "торговля", "банк", "рынок", "бюджет"],
    "технологии": ["технологии", "ии", "интернет", "приложение", "программа", "цифровой"],
    "политика": ["политика", "правительство", "президент", "министр", "парламент", "выборы"],
    "мировые новости": ["мир", "международный", "глобальный", "нато", "оон"],
    "авто": ["автомобиль", "машина", "гонки", "двигатель", "электромобиль"],
    "здоровье": ["здоровье", "больница", "врач", "лечение", "болезнь", "вакцина"],
    "культура": ["культура", "искусство", "фильм", "музыка", "фестиваль"],
    "путешествия": ["путешествие", "туризм", "отель", "аэропорт", "виза"],
    "наука": ["наука", "исследование", "открытие", "космос", "эксперимент"],
    "развлечения": ["развлечение", "знаменитость", "вирусный", "юмор"],
    "ورزش": ["ورزش", "فوتبال", "مسابقه", "تیم", "بازیکن", "لیگ"],
    "اقتصاد_fa": ["اقتصاد", "نفت", "دلار", "تجارت", "بانک", "بازار"],
    "فناوری": ["فناوری", "هوش مصنوعی", "اینترنت", "نرمافزار", "دیجیتال"],
    "سیاست": ["سیاست", "دولت", "رئیس جمهور", "وزیر", "مجلس", "انتخابات"],
    "اخبار جهان": ["جهان", "بینالملل", "ناتو", "سازمان ملل"],
    "خودرو": ["خودرو", "ماشین", "برقی", "موتور", "مسابقه"],
    "سلامت": ["سلامت", "بیمارستان", "پزشک", "درمان", "بیماری", "واکسن"],
    "هنر و فرهنگ": ["هنر", "فرهنگ", "فیلم", "موسیقی", "جشنواره"],
    "سفر": ["سفر", "گردشگری", "هتل", "فرودگاه", "ویزا"],
    "علوم_fa": ["علوم", "تحقیق", "کشف", "فضا", "آزمایش"],
    "سرگرمی": ["سرگرمی", "مشهور", "ویروسی", "طنز"],
    "spor": ["spor", "futbol", "maç", "turnuva", "oyuncu", "takım", "gol", "lig"],
    "ekonomi": ["ekonomi", "petrol", "dolar", "ticaret", "banka", "piyasa", "bütçe"],
    "teknoloji": ["teknoloji", "yapay zeka", "internet", "uygulama", "yazılım"],
    "siyaset": ["siyaset", "hükümet", "cumhurbaşkanı", "bakan", "meclis", "seçim"],
    "dünya": ["dünya", "uluslararası", "nato", "bm", "küresel"],
    "otomotiv": ["araba", "otomobil", "elektrikli", "motor", "yarış"],
    "sağlık": ["sağlık", "hastane", "doktor", "tedavi", "hastalık", "aşı"],
    "sanat ve kültür": ["sanat", "kültür", "film", "müzik", "festival"],
    "seyahat": ["seyahat", "turizm", "otel", "havalimanı", "vize"],
    "bilim": ["bilim", "araştırma", "keşif", "uzay", "deney"],
    "eğlence": ["eğlence", "ünlü", "viral", "komedi"],
    "sport_de": ["sport", "fußball", "spiel", "turnier", "spieler", "mannschaft", "liga"],
    "wirtschaft": ["wirtschaft", "öl", "dollar", "handel", "bank", "markt", "budget"],
    "technologie": ["technologie", "ki", "internet", "app", "software", "digital"],
    "politik": ["politik", "regierung", "präsident", "minister", "parlament", "wahl"],
    "welt": ["welt", "international", "global", "nato", "un"],
    "auto": ["auto", "fahrzeug", "elektroauto", "motor", "rennen"],
    "gesundheit": ["gesundheit", "krankenhaus", "arzt", "behandlung", "krankheit", "impfstoff"],
    "kunst & kultur": ["kunst", "kultur", "film", "musik", "festival"],
    "reisen": ["reisen", "tourismus", "hotel", "flughafen", "visum"],
    "wissenschaft": ["wissenschaft", "forschung", "entdeckung", "weltraum", "experiment"],
    "unterhaltung": ["unterhaltung", "promi", "viral", "humor"],
}

# ======== العملات حسب اللغة ========
CURRENCY_MAP = {
    "العربية 🇮🇶": ("IQD", "الدينار العراقي 🇮🇶"),
    "English 🇬🇧": ("GBP", "British Pound 🇬🇧"),
    "Русский 🇷🇺": ("RUB", "Российский рубль 🇷🇺"),
    "فارسی 🇮🇷": ("IRR", "ریال ایرانی 🇮🇷"),
    "हिन्दी 🇮🇳": ("INR", "Indian Rupee 🇮🇳"),
    "Português 🇧🇷": ("BRL", "Real Brasileiro 🇧🇷"),
    "Türkçe 🇹🇷": ("TRY", "Türk Lirası 🇹🇷"),
    "اردو 🇵🇰": ("PKR", "Pakistani Rupee 🇵🇰"),
    "Deutsch 🇩🇪": ("EUR", "Euro 🇩🇪"),
    "Українська 🇺🇦": ("UAH", "Українська гривня 🇺🇦"),
    "Italiano 🇮🇹": ("EUR", "Euro 🇮🇹"),
    "Español 🇲🇽": ("MXN", "Peso Mexicano 🇲🇽"),
}

# ======== مصادر MENA ========
MENA_RSS = {
    "العربية 🇮🇶": [
        "https://www.alsumaria.tv/rss/latest-news",
        "https://shafaq.com/ar/rss.xml",
        "https://www.rudaw.net/arabic/rss",
        "https://www.almaalomah.com/feed/",
        "https://almada-paper.com/feed/",
        "https://www.alarabiya.net/.mrss/ar/0/0/0.xml",
        "https://www.aljazeera.net/aljazeera/feeds/rss.xml",
        "https://feeds.skynewsarabia.com/web/rss/2",
        "https://arabic.rt.com/rss/",
        "https://www.bbc.com/arabic/index.xml",
        "https://www.independentarabia.com/rss.xml",
        "https://rss.almasryalyoum.com/rss.xml",
        "https://arabi21.com/rss.xml",
        "https://www.elnashra.com/rss",
        "https://www.france24.com/ar/rss",
        "https://arabic.euronews.com/rss",
        "https://www.middleeasteye.net/ar/rss",
        "https://www.aawsat.com/rss.xml",
        "https://www.alquds.com/feed/",
        "https://www.alriyadh.com/tools/rss/rss.xml",
    ],
    "English 🇬🇧": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.middleeasteye.net/rss",
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://rss.cnn.com/rss/edition_world.rss",
    ],
    "Русский 🇷🇺": [
        "https://arabic.rt.com/rss/",
        "https://www.aljazeera.com/xml/rss/all.xml",
    ],
    "Türkçe 🇹🇷": [
        "https://www.aljazeera.com.tr/feed",
        "https://www.aa.com.tr/tr/rss/default",
    ],
    "Deutsch 🇩🇪": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://rss.dw.com/rdf/rss-de-all",
    ],
    "Español 🇲🇽": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
    ],
    "Italiano 🇮🇹": [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
    ],
    "فارسی 🇮🇷": [
        "https://www.radiofarda.com/api/zrqomtmopp",
        "https://www.bbc.com/persian/index.xml",
    ],
    "हिन्दी 🇮🇳": [
        "https://feeds.bbci.co.uk/hindi/rss.xml",
    ],
    "Português 🇧🇷": [
        "https://feeds.bbci.co.uk/portuguese/rss.xml",
    ],
    "اردو 🇵🇰": [
        "https://feeds.bbci.co.uk/urdu/rss.xml",
        "https://www.geo.tv/rss",
    ],
    "Українська 🇺🇦": [
        "https://feeds.bbci.co.uk/ukrainian/rss.xml",
    ],
}

# ======== كلمات مفتاحية للشرق الأوسط (fallback) ========
MENA_KEYWORDS = [
    "عراق", "سوريا", "لبنان", "فلسطين", "غزة", "إيران", "السعودية", "تركيا", "اليمن", "ليبيا",
    "مصر", "الأردن", "الخليج", "حماس", "حزب الله", "إسرائيل", "بغداد", "دمشق", "طهران",
    "iraq", "syria", "lebanon", "palestine", "gaza", "iran", "saudi", "turkey", "yemen", "libya",
    "egypt", "jordan", "gulf", "hamas", "hezbollah", "israel", "baghdad", "damascus", "tehran",
    "middle east", "الشرق الأوسط", "الخليج العربي", "القدس", "jerusalem"
]

# ======== حالة البحث ========
user_states = {}

# ======== إشعار الأدمن بالأخطاء ========
# ═══════════════════════════════════════════════════════════════════════════════
# MONITORING + ALERT SYSTEM — نظام المراقبة والتنبيه
# ═══════════════════════════════════════════════════════════════════════════════
_alert_lock   = threading.Lock()
_alert_count  = {}        # {minute_key: count} — منع التشبع
_MAX_ALERTS_PER_MIN = 5   # حد أقصى 5 تنبيهات في الدقيقة

def send_alert(message: str, exc: Exception = None, func_name: str = "",
               show_traceback: bool = True):
    """
    إرسال تنبيه فوري للأدمن عند أي خطأ.
    مع traceback كامل + مكان الخطأ + محاولة إعادة ثلاث مرات.
    """
    global _alert_count
    # ─── منع التشبع ──────────────────────────────────────────────────────────
    min_key = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with _alert_lock:
        cnt = _alert_count.get(min_key, 0)
        if cnt >= _MAX_ALERTS_PER_MIN:
            return
        _alert_count[min_key] = cnt + 1
        # تنظيف القديم
        old_keys = [k for k in _alert_count if k != min_key]
        for k in old_keys:
            _alert_count.pop(k, None)

    # ─── بناء نص التنبيه ──────────────────────────────────────────────────────
    now_str = _now_sa().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"🚨 *تنبيه فوري — IraqNow Bot*", f"🕐 `{now_str}` (توقيت السعودية)"]
    if func_name:
        lines.append(f"📌 *المكان:* `{func_name}`")
    if message:
        lines.append(f"📋 *الرسالة:* `{str(message)[:300]}`")
    if exc is not None:
        lines.append(f"❌ *نوع الخطأ:* `{type(exc).__name__}`")
        lines.append(f"💬 *التفاصيل:* `{str(exc)[:200]}`")
        if show_traceback:
            tb = traceback.format_exc()
            if tb and "NoneType" not in tb:
                tb_short = tb[-800:].replace("`", "'")
                lines.append(f"🔍 *Traceback:*\n```\n{tb_short}\n```")

    alert_text = "\n".join(lines)
    all_admins = [ADMIN_ID] + extra_admins

    # ─── إرسال مع إعادة المحاولة ──────────────────────────────────────────────
    for admin_id in all_admins:
        for attempt in range(3):
            try:
                bot.send_message(admin_id, alert_text, parse_mode="Markdown")
                _logger.info(f"✅ تنبيه أُرسل للأدمن {admin_id}")
                break
            except Exception as send_err:
                if attempt == 2:
                    _logger.error(f"فشل إرسال التنبيه للأدمن {admin_id}: {send_err}")
                else:
                    time.sleep(2 ** attempt)


def notify_admin_error(msg: str, exc: Exception = None):
    """دالة مشتركة — ترسل التنبيه عبر send_alert الجديدة."""
    frame = sys._getframe(1)
    func_name = frame.f_code.co_name
    lineno    = frame.f_lineno
    send_alert(
        message      = f"{msg}  (line {lineno})",
        exc          = exc,
        func_name    = func_name,
        show_traceback = exc is not None
    )
    _logger.error(f"[{func_name}:{lineno}] {msg}" + (f" | {exc}" if exc else ""))


# ─── Global Exception Hook — يصطاد أي خطأ غير محاط بـ try ───────────────────
def _global_exception_hook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _logger.critical(f"UNCAUGHT EXCEPTION:\n{tb_str}")
    try:
        send_alert(
            message    = "خطأ غير محاط بـ try/except",
            exc        = exc_value,
            func_name  = "GLOBAL",
            show_traceback = True
        )
    except Exception:
        pass

sys.excepthook = _global_exception_hook


# ═══════════════════════════════════════════════════════════════════════════════
# SAFE EXECUTION LAYER — طبقة الإرسال الآمن مع Exponential Backoff
# ═══════════════════════════════════════════════════════════════════════════════
def _exponential_backoff(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """حساب وقت الانتظار: 1s, 2s, 4s, 8s ... حد أقصى 60s"""
    return min(cap, base * (2 ** attempt))


def safe_send_message(chat_id, text, max_retries: int = 4, **kwargs):
    """إرسال رسالة آمن مع retry + exponential backoff + fallback بدون parse_mode."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            last_err = e
            err_str = str(e)
            # Flood wait
            if "429" in err_str or "Too Many Requests" in err_str or "Flood" in err_str:
                try:
                    wait = int(
                        _re.search(r'retry after (\d+)', err_str, _re.I).group(1)
                    )
                except Exception:
                    wait = 30
                _logger.warning(f"flood wait {wait}s — chat {chat_id}")
                time.sleep(wait + 1)
                continue
            # Blocked / deactivated — لا تعيد المحاولة
            if any(x in err_str for x in ("bot was blocked", "user is deactivated",
                                           "chat not found", "PEER_ID_INVALID")):
                _logger.info(f"chat {chat_id} غير متاح — تجاوز")
                return None
            # Markdown error — fallback بدون parse_mode
            if "can't parse" in err_str or "parse entities" in err_str:
                plain = {k: v for k, v in kwargs.items() if k != "parse_mode"}
                try:
                    return bot.send_message(chat_id, text, **plain)
                except Exception:
                    return None
            # أي خطأ آخر — exponential backoff
            wait = _exponential_backoff(attempt)
            _logger.warning(f"safe_send_message محاولة {attempt+1}/{max_retries} — {e} — انتظار {wait:.0f}s")
            time.sleep(wait)
    _logger.error(f"safe_send_message فشل نهائي — chat {chat_id}: {last_err}")
    return None


def safe_send_audio(chat_id, audio, max_retries: int = 3, **kwargs):
    """إرسال ملف صوتي آمن مع retry + fallback إلى رسالة نصية."""
    caption = kwargs.pop("caption", "")
    last_err = None
    for attempt in range(max_retries):
        try:
            return bot.send_audio(chat_id, audio, caption=caption, **kwargs)
        except Exception as e:
            last_err = e
            err_str = str(e)
            if any(x in err_str for x in ("bot was blocked", "user is deactivated",
                                           "chat not found")):
                return None
            if "429" in err_str or "Flood" in err_str:
                time.sleep(30)
                continue
            wait = _exponential_backoff(attempt)
            _logger.warning(f"safe_send_audio محاولة {attempt+1}/{max_retries} — انتظار {wait:.0f}s")
            time.sleep(wait)
    # Fallback: نص بدلاً من صوت
    _logger.error(f"safe_send_audio فشل — fallback نصي — {last_err}")
    if caption:
        try:
            return safe_send_message(chat_id, f"🔊 {caption}")
        except Exception:
            pass
    return None


def safe_send_photo(chat_id, photo, max_retries: int = 3, **kwargs):
    """إرسال صورة آمن مع retry + fallback إلى رسالة نصية."""
    caption = kwargs.pop("caption", "")
    last_err = None
    for attempt in range(max_retries):
        try:
            return bot.send_photo(chat_id, photo, caption=caption, **kwargs)
        except Exception as e:
            last_err = e
            err_str = str(e)
            if any(x in err_str for x in ("bot was blocked", "user is deactivated",
                                           "chat not found")):
                return None
            if "429" in err_str or "Flood" in err_str:
                time.sleep(30)
                continue
            wait = _exponential_backoff(attempt)
            _logger.warning(f"safe_send_photo محاولة {attempt+1}/{max_retries} — انتظار {wait:.0f}s")
            time.sleep(wait)
    _logger.error(f"safe_send_photo فشل — fallback نصي — {last_err}")
    if caption:
        try:
            return safe_send_message(chat_id, f"🖼 {caption}")
        except Exception:
            pass
    return None

# ======== تحديث الإحصائيات ========
def update_stats(action, uid=None, country=None, lang=None, button=None):
    today = str(datetime.date.today())
    if action == "new_user":
        stats["total_users"] = stats.get("total_users", 0) + 1
        stats["daily_users"][today] = stats["daily_users"].get(today, 0) + 1
        if lang:
            stats["languages_count"][lang] = stats["languages_count"].get(lang, 0) + 1
        if country:
            stats["countries_count"][country] = stats["countries_count"].get(country, 0) + 1
        total = stats["total_users"]
        if total in [100, 500, 1000, 5000, 10000]:
            all_admins = [ADMIN_ID] + extra_admins
            for admin_id in all_admins:
                try:
                    bot.send_message(admin_id, f"🎉 وصلت {total} مستخدم!")
                except:
                    pass
    elif action == "button":
        if button:
            stats["button_presses"][button] = stats["button_presses"].get(button, 0) + 1
    save_json(STATS_FILE, stats)

# ======== دوال المميز ========
def is_premium(uid):
    # جميع الميزات مجانية للجميع — لا يوجد اشتراك مميز
    return True

def has_feature(uid, feature):
    # جميع الميزات متاحة للجميع
    return True

# ======== ميزات الإحالة ========
REFERRAL_FEATURES = {
    "prem_7day":           "📅 توقعات طقس 7 أيام",
    "prem_hourly":         "⚡ أخبار فورية كل ساعة",
    "prem_addcity":        "🏙 إضافة مدينة إضافية",
    "prem_mycities":       "🗂 عرض مدنك المحفوظة",
    "prem_interests":      "🎯 أخبار حسب اهتماماتك",
    "prem_currency_alert": "💱 تنبيه سعر العملة",
    "prem_currency_table": "📊 جدول العملات الكامل",
    "prem_notif_time":     "🕐 وقت إشعار مخصص",
    "prem_weekly":         "📋 ملخص أسبوعي",
    "prem_keywords":       "🔑 تنبيه كلمات مفتاحية",
}
REFERRAL_MILESTONES = [5, 10, 15, 20, 25]

def check_referral_rewards(referrer_id, new_member_name=""):
    uid_str = str(referrer_id)
    user = users.get(uid_str)
    if not user:
        return
    ref_count = len(user.get("referrals", []))
    rewarded = user.setdefault("rewarded_milestones", [])
    for milestone in REFERRAL_MILESTONES:
        if ref_count >= milestone and milestone not in rewarded:
            rewarded.append(milestone)
            users[uid_str]["rewarded_milestones"] = rewarded
            _db_save_all_users(users)
            if milestone == 25:
                expiry = datetime.datetime.now() + datetime.timedelta(days=30)
                users[uid_str]["ref_premium_expiry"] = expiry.isoformat()
                _db_save_all_users(users)
                try:
                    bot.send_message(
                        referrer_id,
                        "🎊 *تهانينا! وصلت إلى 25 دعوة!*\n\n"
                        "🌟 حصلت على *اشتراك مميز كامل لمدة شهر* مجاناً!\n"
                        "━━━━━━━━━━━━━━\n"
                        "📅 الاشتراك ساري لمدة 30 يوم\n"
                        "✨ استمتع بجميع الميزات المميزة!",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            else:
                try:
                    bot.send_message(
                        referrer_id,
                        f"🎉 *تهانينا! وصلت إلى {milestone} دعوة!*\n\n"
                        f"🎁 ربحت *ميزة مميزة مجانية* — اختر الميزة التي تريدها:",
                        parse_mode="Markdown"
                    )
                    send_feature_choice_menu(referrer_id)
                except:
                    pass
            break

def send_feature_choice_menu(uid):
    user = users.get(str(uid), {})
    unlocked = user.get("unlocked_features", [])
    markup = types.InlineKeyboardMarkup(row_width=1)
    for feat_key, feat_name in REFERRAL_FEATURES.items():
        if feat_key not in unlocked:
            markup.add(types.InlineKeyboardButton(feat_name, callback_data=f"ref_feature_{feat_key}"))
    if not markup.keyboard:
        bot.send_message(uid, "✅ لقد فتحت جميع الميزات المتاحة بالفعل!")
        return
    bot.send_message(uid,
        "🎁 *اختر ميزة مميزة واحدة تريد فتحها:*\n"
        "━━━━━━━━━━━━━━\n"
        "الميزة المختارة ستكون متاحة لك دائماً مجاناً.",
        parse_mode="Markdown",
        reply_markup=markup
    )

# ======== لوحة تحكم الأدمن ========
def admin_panel(uid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 المستخدمون", callback_data="admin_users"),
        types.InlineKeyboardButton("📢 إرسال رسالة للكل", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🚨 خبر عاجل مخصص", callback_data="admin_breaking_news"),
        types.InlineKeyboardButton("🔴 إيقاف/تشغيل البوت", callback_data="admin_pause"),
        types.InlineKeyboardButton("⏱ توقيت البث", callback_data="admin_interval"),
        types.InlineKeyboardButton("📡 إدارة RSS", callback_data="admin_rss"),
        types.InlineKeyboardButton("🚫 القائمة السوداء", callback_data="admin_blacklist"),
        types.InlineKeyboardButton("💰 المالية", callback_data="admin_finance"),
        types.InlineKeyboardButton("📖 عداد القراءة", callback_data="admin_read_stats"),
        types.InlineKeyboardButton("✏️ تغيير رسالة الترحيب", callback_data="admin_welcome"),
        types.InlineKeyboardButton("👑 إدارة الأدمن", callback_data="admin_manage_admins"),
        types.InlineKeyboardButton("📺 إدارة القنوات/المجموعات", callback_data="admin_channels"),
        types.InlineKeyboardButton("📈 إحصائيات القنوات", callback_data="admin_channel_stats"),
        types.InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="admin_search_user"),
        types.InlineKeyboardButton("✉️ رسالة لمستخدم", callback_data="admin_msg_user"),
        types.InlineKeyboardButton("📋 قائمة الأوامر", callback_data="admin_commands"),
        types.InlineKeyboardButton("✏️ شكل رسالة الخبر", callback_data="admin_news_format"),
        types.InlineKeyboardButton("💬 صندوق الرسائل", callback_data="admin_inbox"),
        types.InlineKeyboardButton("⭐ تقييمات المستخدمين", callback_data="admin_ratings"),
        types.InlineKeyboardButton("💾 نسخة احتياطية", callback_data="admin_backup"),
        types.InlineKeyboardButton("🔄 إعادة تعيين الأخبار", callback_data="admin_reset_sent_news"),
        types.InlineKeyboardButton("📴 إيقاف البث" if not broadcast_paused else "📡 تشغيل البث", callback_data="admin_toggle_broadcast"),
        types.InlineKeyboardButton("🗑 إعادة تعيين البوت كاملاً", callback_data="admin_full_reset"),
        types.InlineKeyboardButton("🔍 تشخيص الإرسال", callback_data="admin_debugnews"),
        types.InlineKeyboardButton("🧹 مسح كاش الأخبار", callback_data="admin_clearcache"),
        types.InlineKeyboardButton("⚡ بث فوري الآن", callback_data="admin_forcenews"),
    )
    bot.send_message(uid, "👑 *لوحة تحكم الأدمن:*", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message.from_user.id):
        return
    admin_panel(message.from_user.id)

HELP_TEXTS = {
    "العربية 🇮🇶": (
        "📖 *دليل بوت @Iraqnowbot الشامل*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *ما هو هذا البوت؟*\n"
        "بوت أخبار ذكي مجاني بالكامل يُرسل إليك الأخبار لحظة نزولها من أكثر من 50 مصدراً عالمياً، بلغتك التي تختارها. كل المميزات متاحة للجميع بدون رسوم.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *أزرار القائمة الرئيسية*\n\n"
        "📰 *آخر الأخبار* — يُرسل لك آخر الأخبار الحديثة (خلال ساعتين) من مصادرك المختارة فوراً.\n\n"
        "⚽ *أخبار الرياضة* — متابعة مباشرة للمباريات مع أهداف وبطاقات ونتائج، وإمكانية تفعيل التنبيهات الفورية لدوريات بعينها.\n\n"
        "🌤 *الطقس الآن* — حالة الطقس التفصيلية لمدينتك (درجة الحرارة، الرياح، الرطوبة، شروق وغروب الشمس).\n\n"
        "🕌 *أوقات الصلاة* — مواقيت الصلاة الخمس حسب موقعك.\n\n"
        "💱 *أسعار العملات* — أسعار صرف الدولار والعملات الرئيسية والذهب والنفط مباشرة.\n\n"
        "💎 *العملات الرقمية* — أسعار البيتكوين وأبرز العملات الرقمية لحظياً.\n\n"
        "🔍 *بحث في الأخبار* — ابحث عن أي خبر بكلمة مفتاحية من آخر 24 ساعة.\n\n"
        "🧠 *بحث عميق بالذكاء الاصطناعي* — تحليل شامل لأي موضوع بـ 8 محاور: الخلفية، التطورات، المواقف، التحليل، التوقعات، الأثر الإقليمي، المعلومات الموثوقة، والمصادر.\n\n"
        "📋 *ملخص أخبار اليوم* — أبرز 5 أخبار ليومك في رسالة واحدة.\n\n"
        "🔔 *الإشعارات* — تفعيل أو إيقاف وصول الأخبار التلقائية.\n\n"
        "⚙️ *تغيير الإعدادات* — تغيير لغتك أو مدينتك أو بلدك.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *الأوامر النصية*\n\n"
        "/start — القائمة الرئيسية\n"
        "/help — هذا الدليل\n"
        "/settings — الإعدادات (لغة، مدينة، إشعارات)\n"
        "/news — آخر الأخبار الآن\n"
        "/trending — الأخبار الأكثر تداولاً\n"
        "/summary — ملخص اليوم\n"
        "/weather — الطقس التفصيلي\n"
        "/currency — أسعار العملات\n"
        "/markets — الأسواق المالية الكاملة\n"
        "/sports — الرياضة والمباريات\n"
        "/chart [رمز] — رسم بياني للسعر (مثال: /chart BTC)\n"
        "/deepsearch [موضوع] — بحث AI عميق\n"
        "/ask [سؤال] — اسأل الذكاء الاصطناعي\n"
        "/profile — ملفك وإحصائياتك\n"
        "/restart — إعادة ضبط الإعدادات\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💡 *نصائح*\n"
        "• الأخبار تصلك تلقائياً كل دقائق بدون أي إجراء\n"
        "• استخدم 🗂 اختيار أنواع الأخبار لتخصيص ما تستقبله\n"
        "• DeepSearch يعمل بـ Gemini AI ويغطي أي موضوع بالعمق\n"
        "• جميع الميزات مجانية 100% ولا يوجد اشتراك مدفوع\n\n"
        "🤖 @Iraqnowbot"
    ),
    "English 🇬🇧": (
        "📖 *@Iraqnowbot — Full Guide*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *What is this bot?*\n"
        "A 100% free smart news bot that delivers breaking news the moment it happens, from 50+ global sources, in your chosen language. All features are free — no subscriptions.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Main Menu Buttons*\n\n"
        "📰 *Latest News* — Sends you fresh news (within 2 hours) from your selected sources instantly.\n\n"
        "⚽ *Sports* — Live match tracking with goals, cards & scores. Enable alerts for specific leagues.\n\n"
        "🌤 *Weather* — Detailed weather for your city (temp, wind, humidity, sunrise/sunset).\n\n"
        "🕌 *Prayer Times* — Daily prayer schedule based on your location.\n\n"
        "💱 *Currency Rates* — Live exchange rates for USD and major currencies, gold & oil.\n\n"
        "💎 *Crypto* — Live Bitcoin and top cryptocurrency prices.\n\n"
        "🔍 *Search News* — Search any keyword in news from the last 24 hours.\n\n"
        "🧠 *AI Deep Search* — 8-section AI analysis of any topic: background, developments, positions, analysis, forecast, regional impact, verified facts, sources.\n\n"
        "📋 *Daily Summary* — Top 5 news stories of the day in one message.\n\n"
        "🔔 *Notifications* — Toggle automatic news delivery on/off.\n\n"
        "⭐ *Extra Features* — All free: 7-day forecast, currency alerts, custom schedule.\n\n"
        "⚙️ *Settings* — Change your language, city, or country.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Commands*\n\n"
        "/start — Main menu\n"
        "/help — This guide\n"
        "/settings — Language, city, notifications\n"
        "/news — Latest news now\n"
        "/trending — Most trending news\n"
        "/summary — Daily digest\n"
        "/weather — Detailed weather\n"
        "/currency — Currency rates\n"
        "/markets — Full financial markets\n"
        "/sports — Sports & matches\n"
        "/chart [symbol] — Price chart (e.g. /chart BTC)\n"
        "/deepsearch [topic] — AI deep research\n"
        "/ask [question] — Ask the AI\n"
        "/profile — Your profile & stats\n"
        "/restart — Reset your settings\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💡 *Tips*\n"
        "• News arrives automatically every few minutes\n"
        "• Use 🗂 News Categories to filter what you receive\n"
        "• DeepSearch uses Gemini AI for in-depth analysis\n"
        "• Everything is 100% free — no paid tier\n\n"
        "🤖 @Iraqnowbot"
    ),
    "Русский 🇷🇺": (
        "📖 *@Iraqnowbot — Полное руководство*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *Что это за бот?*\n"
        "Умный новостной бот, полностью бесплатный. Доставляет свежие новости от 50+ мировых источников на вашем языке. Все функции бесплатны.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Кнопки главного меню*\n\n"
        "📰 *Последние новости* — Свежие новости (за 2 часа) от ваших источников.\n"
        "⚽ *Спорт* — Прямые трансляции матчей: голы, карточки, счёт. Уведомления по лигам.\n"
        "🌤 *Погода* — Подробный прогноз для вашего города.\n"
        "🕌 *Время намаза* — Расписание молитв по вашему местоположению.\n"
        "💱 *Курсы валют* — Курс доллара и основных валют, золото, нефть.\n"
        "💎 *Криптовалюты* — Цены Bitcoin и топ-монет в реальном времени.\n"
        "🔍 *Поиск новостей* — Поиск по ключевому слову за последние 24 часа.\n"
        "🧠 *ИИ-поиск* — Глубокий анализ темы по 8 разделам с Gemini AI.\n"
        "📋 *Сводка дня* — Топ-5 новостей за день одним сообщением.\n"
        "🔔 *Уведомления* — Включить/выключить автодоставку.\n"
        "⭐ *Доп. функции* — Прогноз 7 дней, валютные уведомления — всё бесплатно.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Команды*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [символ] /deepsearch [тема] /ask [вопрос]\n\n"
        "💡 Все функции бесплатны. Новости доставляются автоматически.\n"
        "🤖 @Iraqnowbot"
    ),
    "فارسی 🇮🇷": (
        "📖 *راهنمای کامل @Iraqnowbot*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *این بات چیست؟*\n"
        "یک بات خبری هوشمند و کاملاً رایگان که اخبار لحظه‌ای از بیش از ۵۰ منبع جهانی را به زبان شما ارسال می‌کند.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *دکمه‌های منوی اصلی*\n\n"
        "📰 *آخرین اخبار* — اخبار تازه (در ۲ ساعت اخیر) از منابع شما.\n"
        "⚽ *ورزش* — پیگیری زنده مسابقات با گل، کارت و نتیجه. هشدار لیگ‌های مختلف.\n"
        "🌤 *آب‌وهوا* — پیش‌بینی تفصیلی برای شهر شما.\n"
        "🕌 *اوقات نماز* — جدول نماز بر اساس موقعیت شما.\n"
        "💱 *نرخ ارز* — دلار، ارزهای اصلی، طلا و نفت به‌صورت زنده.\n"
        "💎 *رمزارزها* — قیمت بیت‌کوین و ارزهای دیجیتال برتر.\n"
        "🔍 *جستجوی خبر* — جستجو با کلیدواژه در اخبار ۲۴ ساعت اخیر.\n"
        "🧠 *جستجوی عمیق AI* — تحلیل ۸ بخشی موضوع با Gemini AI.\n"
        "📋 *خلاصه روز* — ۵ خبر برتر روز در یک پیام.\n"
        "🔔 *اعلان‌ها* — روشن/خاموش کردن ارسال خودکار خبر.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *دستورات*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [نماد] /deepsearch [موضوع] /ask [سؤال]\n\n"
        "💡 همه امکانات رایگان است. اخبار به‌صورت خودکار می‌رسد.\n"
        "🤖 @Iraqnowbot"
    ),
    "हिन्दी 🇮🇳": (
        "📖 *@Iraqnowbot — पूर्ण मार्गदर्शिका*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *यह बॉट क्या है?*\n"
        "एक 100% मुफ़्त स्मार्ट न्यूज़ बॉट जो 50+ वैश्विक स्रोतों से ताज़ा खबरें आपकी भाषा में भेजता है।\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *मुख्य मेनू बटन*\n\n"
        "📰 *ताज़ा समाचार* — 2 घंटे के अंदर की खबरें तुरंत।\n"
        "⚽ *खेल* — लाइव मैच, गोल, कार्ड, स्कोर। लीग अलर्ट।\n"
        "🌤 *मौसम* — आपके शहर का विस्तृत मौसम पूर्वानुमान।\n"
        "🕌 *नमाज़ का समय* — आपके स्थान के अनुसार।\n"
        "💱 *मुद्रा दर* — डॉलर, प्रमुख मुद्राएँ, सोना, तेल।\n"
        "💎 *क्रिप्टो* — Bitcoin और टॉप क्रिप्टो की लाइव कीमतें।\n"
        "🔍 *समाचार खोज* — पिछले 24 घंटे में कीवर्ड से खोजें।\n"
        "🧠 *AI डीप सर्च* — Gemini AI से 8-खंड विश्लेषण।\n"
        "📋 *दैनिक सारांश* — एक संदेश में दिन की टॉप 5 खबरें।\n"
        "🔔 *सूचनाएँ* — स्वचालित समाचार चालू/बंद करें।\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *कमांड*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [symbol] /deepsearch [topic] /ask [question]\n\n"
        "💡 सभी सुविधाएँ मुफ़्त हैं। खबरें स्वचालित रूप से आती हैं।\n"
        "🤖 @Iraqnowbot"
    ),
    "Português 🇧🇷": (
        "📖 *@Iraqnowbot — Guia Completo*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *O que é este bot?*\n"
        "Um bot de notícias inteligente e 100% gratuito que entrega notícias em tempo real de 50+ fontes globais no seu idioma.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Botões do Menu Principal*\n\n"
        "📰 *Últimas Notícias* — Notícias frescas (últimas 2h) das suas fontes.\n"
        "⚽ *Esportes* — Acompanhamento ao vivo: gols, cartões, placar. Alertas por liga.\n"
        "🌤 *Clima* — Previsão detalhada para sua cidade.\n"
        "🕌 *Horários de Oração* — Programação diária por localização.\n"
        "💱 *Câmbio* — Dólar, principais moedas, ouro e petróleo ao vivo.\n"
        "💎 *Cripto* — Preços do Bitcoin e top criptomoedas em tempo real.\n"
        "🔍 *Buscar Notícias* — Pesquise por palavra-chave nas últimas 24h.\n"
        "🧠 *Pesquisa Profunda IA* — Análise de 8 seções com Gemini AI.\n"
        "📋 *Resumo do Dia* — Top 5 notícias do dia em uma mensagem.\n"
        "🔔 *Notificações* — Ativar/desativar entrega automática.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Comandos*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [símbolo] /deepsearch [tema] /ask [pergunta]\n\n"
        "💡 Tudo é 100% gratuito. Notícias chegam automaticamente.\n"
        "🤖 @Iraqnowbot"
    ),
    "Türkçe 🇹🇷": (
        "📖 *@Iraqnowbot — Tam Rehber*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *Bu bot nedir?*\n"
        "50+ küresel kaynaktan anlık haberleri seçtiğiniz dilde ileten %100 ücretsiz akıllı haber botu.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Ana Menü Düğmeleri*\n\n"
        "📰 *Son Haberler* — 2 saat içindeki taze haberler anında.\n"
        "⚽ *Spor* — Canlı maç takibi: goller, kartlar, skor. Lig uyarıları.\n"
        "🌤 *Hava Durumu* — Şehriniz için ayrıntılı hava tahmini.\n"
        "🕌 *Namaz Vakitleri* — Konumunuza göre günlük program.\n"
        "💱 *Döviz* — Dolar, başlıca para birimleri, altın ve petrol.\n"
        "💎 *Kripto* — Bitcoin ve en iyi kripto fiyatları anlık.\n"
        "🔍 *Haber Ara* — Son 24 saatteki haberlerde anahtar kelime araması.\n"
        "🧠 *Derin AI Arama* — Gemini AI ile 8 bölümlü konu analizi.\n"
        "📋 *Günün Özeti* — Günün en iyi 5 haberi tek mesajda.\n"
        "🔔 *Bildirimler* — Otomatik haber teslimatını açın/kapatın.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Komutlar*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [sembol] /deepsearch [konu] /ask [soru]\n\n"
        "💡 Her şey ücretsiz. Haberler otomatik gelir.\n"
        "🤖 @Iraqnowbot"
    ),
    "اردو 🇵🇰": (
        "📖 *@Iraqnowbot — مکمل رہنما*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *یہ بوٹ کیا ہے؟*\n"
        "ایک 100% مفت ذہین خبر بوٹ جو 50+ عالمی ذرائع سے فوری خبریں آپ کی زبان میں بھیجتا ہے۔\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *مین مینو کے بٹن*\n\n"
        "📰 *تازہ خبریں* — 2 گھنٹے کے اندر کی خبریں فوری طور پر۔\n"
        "⚽ *کھیل* — لائیو میچ: گول، کارڈ، اسکور۔ لیگ الرٹس۔\n"
        "🌤 *موسم* — آپ کے شہر کی تفصیلی موسمی پیشگوئی۔\n"
        "🕌 *نماز کے اوقات* — آپ کے مقام کے مطابق روزانہ کا شیڈول۔\n"
        "💱 *کرنسی ریٹ* — ڈالر، بڑی کرنسیاں، سونا اور تیل لائیو۔\n"
        "💎 *کرپٹو* — بٹ کوائن اور ٹاپ کرپٹو کی لائیو قیمتیں۔\n"
        "🔍 *خبر تلاش* — پچھلے 24 گھنٹوں میں کلیدی الفاظ سے تلاش۔\n"
        "🧠 *AI گہری تلاش* — Gemini AI سے 8 حصوں میں تجزیہ۔\n"
        "📋 *دن کا خلاصہ* — ایک پیغام میں دن کی ٹاپ 5 خبریں۔\n"
        "🔔 *نوٹیفکیشن* — خودکار خبر فراہمی آن/آف کریں۔\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *احکامات*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [علامت] /deepsearch [موضوع] /ask [سوال]\n\n"
        "💡 سب کچھ مفت ہے۔ خبریں خودکار آتی ہیں۔\n"
        "🤖 @Iraqnowbot"
    ),
    "Deutsch 🇩🇪": (
        "📖 *@Iraqnowbot — Vollständige Anleitung*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *Was ist dieser Bot?*\n"
        "Ein 100% kostenloser intelligenter Nachrichtenbot, der Eilmeldungen von 50+ globalen Quellen in Ihrer Sprache liefert.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Hauptmenü-Schaltflächen*\n\n"
        "📰 *Aktuelle Nachrichten* — Frische Nachrichten (letzte 2 Std.) sofort.\n"
        "⚽ *Sport* — Live-Spiele: Tore, Karten, Ergebnis. Liga-Benachrichtigungen.\n"
        "🌤 *Wetter* — Detaillierte Wettervorhersage für Ihre Stadt.\n"
        "🕌 *Gebetszeiten* — Täglicher Gebetsplan nach Standort.\n"
        "💱 *Wechselkurse* — Dollar, Hauptwährungen, Gold und Öl live.\n"
        "💎 *Krypto* — Bitcoin und Top-Krypto-Preise in Echtzeit.\n"
        "🔍 *Nachrichten suchen* — Suche nach Stichwort der letzten 24 Std.\n"
        "🧠 *KI-Tiefensuche* — 8-Abschnitt-Analyse mit Gemini AI.\n"
        "📋 *Tageszusammenfassung* — Top 5 Nachrichten des Tages.\n"
        "🔔 *Benachrichtigungen* — Automatische Lieferung ein/ausschalten.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Befehle*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [Symbol] /deepsearch [Thema] /ask [Frage]\n\n"
        "💡 Alles kostenlos. Nachrichten kommen automatisch.\n"
        "🤖 @Iraqnowbot"
    ),
    "Українська 🇺🇦": (
        "📖 *@Iraqnowbot — Повний посібник*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *Що це за бот?*\n"
        "Розумний новинний бот, повністю безкоштовний. Доставляє свіжі новини від 50+ світових джерел вашою мовою.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Кнопки головного меню*\n\n"
        "📰 *Останні новини* — Свіжі новини (за 2 год.) від ваших джерел.\n"
        "⚽ *Спорт* — Пряма трансляція матчів: голи, картки, рахунок. Ліга-сповіщення.\n"
        "🌤 *Погода* — Детальний прогноз для вашого міста.\n"
        "🕌 *Час молитви* — Щоденний розклад за місцезнаходженням.\n"
        "💱 *Курс валют* — Долар, основні валюти, золото і нафта.\n"
        "💎 *Крипто* — Ціни Bitcoin і топ-монет у реальному часі.\n"
        "🔍 *Пошук новин* — За ключовим словом за 24 години.\n"
        "🧠 *ШІ-пошук* — Глибокий аналіз теми за 8 розділами з Gemini AI.\n"
        "📋 *Зведення дня* — Топ-5 новин дня в одному повідомленні.\n"
        "🔔 *Сповіщення* — Увімкнути/вимкнути автодоставку.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Команди*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [символ] /deepsearch [тема] /ask [питання]\n\n"
        "💡 Усе безкоштовно. Новини надходять автоматично.\n"
        "🤖 @Iraqnowbot"
    ),
    "Italiano 🇮🇹": (
        "📖 *@Iraqnowbot — Guida Completa*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *Cos'è questo bot?*\n"
        "Un bot di notizie intelligente e 100% gratuito che consegna notizie in tempo reale da 50+ fonti globali nella tua lingua.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Pulsanti del Menu Principale*\n\n"
        "📰 *Ultime Notizie* — Notizie fresche (ultime 2 ore) dalle tue fonti.\n"
        "⚽ *Sport* — Partite in diretta: gol, cartellini, punteggio. Avvisi per lega.\n"
        "🌤 *Meteo* — Previsioni dettagliate per la tua città.\n"
        "🕌 *Orari di Preghiera* — Programma giornaliero per posizione.\n"
        "💱 *Cambio* — Dollaro, valute principali, oro e petrolio live.\n"
        "💎 *Crypto* — Prezzi Bitcoin e top crypto in tempo reale.\n"
        "🔍 *Cerca Notizie* — Ricerca per parola chiave nelle ultime 24 ore.\n"
        "🧠 *Ricerca Profonda AI* — Analisi 8 sezioni con Gemini AI.\n"
        "📋 *Riepilogo del Giorno* — Top 5 notizie del giorno in un messaggio.\n"
        "🔔 *Notifiche* — Attiva/disattiva consegna automatica.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Comandi*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [simbolo] /deepsearch [argomento] /ask [domanda]\n\n"
        "💡 Tutto è gratuito. Le notizie arrivano automaticamente.\n"
        "🤖 @Iraqnowbot"
    ),
    "Español 🇲🇽": (
        "📖 *@Iraqnowbot — Guía Completa*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤖 *¿Qué es este bot?*\n"
        "Un bot de noticias inteligente y 100% gratuito que entrega noticias en tiempo real de 50+ fuentes globales en tu idioma.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *Botones del Menú Principal*\n\n"
        "📰 *Últimas Noticias* — Noticias frescas (últimas 2 h) de tus fuentes.\n"
        "⚽ *Deportes* — Seguimiento en vivo: goles, tarjetas, marcador. Alertas por liga.\n"
        "🌤 *Clima* — Pronóstico detallado para tu ciudad.\n"
        "🕌 *Horarios de Oración* — Programa diario según ubicación.\n"
        "💱 *Cambio de Divisas* — Dólar, monedas principales, oro y petróleo en vivo.\n"
        "💎 *Cripto* — Precios de Bitcoin y top criptos en tiempo real.\n"
        "🔍 *Buscar Noticias* — Búsqueda por palabra clave en las últimas 24 h.\n"
        "🧠 *Búsqueda Profunda IA* — Análisis de 8 secciones con Gemini AI.\n"
        "📋 *Resumen del Día* — Top 5 noticias del día en un mensaje.\n"
        "🔔 *Notificaciones* — Activar/desactivar entrega automática.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📟 *Comandos*\n"
        "/start /help /settings /news /trending /summary\n"
        "/weather /currency /markets /sports\n"
        "/chart [símbolo] /deepsearch [tema] /ask [pregunta]\n\n"
        "💡 Todo es gratuito. Las noticias llegan automáticamente.\n"
        "🤖 @Iraqnowbot"
    ),
}

HELP_CMD_LABELS = {
    "العربية 🇮🇶": {
        "sec_start":   "⚡ البدء والإعدادات",
        "sec_trade":   "💹 التداول والمتابعة",
        "sec_news":    "📢 الأخبار والطقس",
        "start":  "▶️ /start", "help":  "❓ /help", "settings": "⚙️ /settings",
        "mytrack":"📋 /mytrack","addtrack":"➕ /addtrack","removetrack":"➖ /removetrack",
        "markets":"💹 /markets","alerts":"🔔 /alerts","chart":"📊 /chart",
        "news":"📰 /news","trending":"🔥 /trending","summary":"📝 /summary","weather":"🌤 /weather",
    },
    "English 🇬🇧": {
        "sec_start":   "⚡ Start & Settings",
        "sec_trade":   "💹 Trading & Tracking",
        "sec_news":    "📢 News & Weather",
        "start":  "▶️ /start", "help":  "❓ /help", "settings": "⚙️ /settings",
        "mytrack":"📋 /mytrack","addtrack":"➕ /addtrack","removetrack":"➖ /removetrack",
        "markets":"💹 /markets","alerts":"🔔 /alerts","chart":"📊 /chart",
        "news":"📰 /news","trending":"🔥 /trending","summary":"📝 /summary","weather":"🌤 /weather",
    },
    "Русский 🇷🇺": {
        "sec_start":   "⚡ Начало и настройки",
        "sec_trade":   "💹 Торговля и отслеживание",
        "sec_news":    "📢 Новости и погода",
        "start":"▶️ /start","help":"❓ /help","settings":"⚙️ /settings",
        "mytrack":"📋 /mytrack","addtrack":"➕ /addtrack","removetrack":"➖ /removetrack",
        "markets":"💹 /markets","alerts":"🔔 /alerts","chart":"📊 /chart",
        "news":"📰 /news","trending":"🔥 /trending","summary":"📝 /summary","weather":"🌤 /weather",
    },
    "فارسی 🇮🇷": {
        "sec_start":"⚡ شروع و تنظیمات","sec_trade":"💹 معاملات و پیگیری","sec_news":"📢 اخبار و آبوهوا",
        "start":"▶️ /start","help":"❓ /help","settings":"⚙️ /settings",
        "mytrack":"📋 /mytrack","addtrack":"➕ /addtrack","removetrack":"➖ /removetrack",
        "markets":"💹 /markets","alerts":"🔔 /alerts","chart":"📊 /chart",
        "news":"📰 /news","trending":"🔥 /trending","summary":"📝 /summary","weather":"🌤 /weather",
    },
}

def _make_help_keyboard(lang):
    lbl = HELP_CMD_LABELS.get(lang, HELP_CMD_LABELS["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton(lbl["start"],    callback_data="hcmd_start"),
        types.InlineKeyboardButton(lbl["settings"], callback_data="hcmd_settings"),
        types.InlineKeyboardButton(lbl["help"],     callback_data="hcmd_help"),
    )
    markup.add(
        types.InlineKeyboardButton(lbl["mytrack"],     callback_data="hcmd_mytrack"),
        types.InlineKeyboardButton(lbl["markets"],     callback_data="hcmd_markets"),
        types.InlineKeyboardButton(lbl["alerts"],      callback_data="hcmd_alerts"),
    )
    markup.add(
        types.InlineKeyboardButton(lbl["chart"],       callback_data="hcmd_chart"),
        types.InlineKeyboardButton(lbl["addtrack"],    callback_data="hcmd_addtrack"),
        types.InlineKeyboardButton(lbl["removetrack"], callback_data="hcmd_removetrack"),
    )
    markup.add(
        types.InlineKeyboardButton(lbl["news"],     callback_data="hcmd_news"),
        types.InlineKeyboardButton(lbl["trending"], callback_data="hcmd_trending"),
        types.InlineKeyboardButton(lbl["summary"],  callback_data="hcmd_summary"),
    )
    markup.add(
        types.InlineKeyboardButton(lbl["weather"],  callback_data="hcmd_weather"),
    )
    return markup

@bot.message_handler(commands=['help'])
def help_command(message):
    uid = message.from_user.id
    if uid in banned: return
    _update_user_last_command(uid, "/help")
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    text = HELP_TEXTS.get(lang, HELP_TEXTS["English 🇬🇧"])
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=_make_help_keyboard(lang))

@bot.callback_query_handler(func=lambda c: c.data.startswith("hcmd_"))
def help_cmd_callback(call):
    uid = call.from_user.id
    cmd = call.data.replace("hcmd_", "")
    bot.answer_callback_query(call.id)
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    if cmd == "start":
        class _FakeMsg:
            from_user = type("U", (), {"id": uid, "first_name": user.get("name",""), "username": None})()
            chat = type("C", (), {"id": uid, "type": "private"})()
            text = "/start"
        start(_FakeMsg())
    elif cmd == "help":
        text = HELP_TEXTS.get(lang, HELP_TEXTS["English 🇬🇧"])
        bot.send_message(uid, text, parse_mode="Markdown", reply_markup=_make_help_keyboard(lang))
    elif cmd == "settings":
        if str(uid) in users:
            class _FakeSettingsMsg:
                from_user = type("U", (), {"id": uid})()
                chat = type("C", (), {"id": uid, "type": "private"})()
            cmd_settings_private(_FakeSettingsMsg())
    elif cmd == "mytrack":
        start_track_asset(uid)
    elif cmd == "markets":
        class _M:
            from_user = type("U",(),{"id":uid})()
        cmd_markets(_M())
    elif cmd == "alerts":
        class _M:
            from_user = type("U",(),{"id":uid})()
        cmd_alerts(_M())
    elif cmd == "chart":
        _send_chart_categories(uid, lang)
    elif cmd == "news":
        if str(uid) in users:
            send_hourly_news(uid)
        else:
            bot.send_message(uid, "⚠️ أرسل /start أولاً.")
    elif cmd == "trending":
        if str(uid) in users:
            send_trending_news(uid)
        else:
            bot.send_message(uid, "⚠️ أرسل /start أولاً.")
    elif cmd == "summary":
        if str(uid) in users:
            send_daily_top3(uid)
        else:
            bot.send_message(uid, "⚠️ أرسل /start أولاً.")
    elif cmd == "weather":
        if str(uid) in users:
            u = users[str(uid)]
            if u.get("province"):
                send_detailed_weather(uid)
            else:
                bot.send_message(uid, "⚠️ لم تحدد مدينتك. أرسل /start لإعداد حسابك.")
        else:
            bot.send_message(uid, "⚠️ أرسل /start أولاً.")
    elif cmd in ("addtrack", "removetrack"):
        hint = {
            "addtrack": {"العربية 🇮🇶": "أرسل رمز الأصل لإضافته، مثال: `BTC` أو `AAPL`",
                         "English 🇬🇧": "Send the asset symbol to add, e.g.: `BTC` or `AAPL`"},
            "removetrack": {"العربية 🇮🇶": "أرسل رمز الأصل لحذفه من قائمة التتبع",
                            "English 🇬🇧": "Send the asset symbol to remove from tracking"},
        }
        msg = hint[cmd].get(lang, hint[cmd]["English 🇬🇧"])
        if cmd == "addtrack":
            bot.send_message(uid, f"➕ {msg}", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: _addtrack_step(m))
        else:
            bot.send_message(uid, f"➖ {msg}", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: _removetrack_step(m))

def _addtrack_step(message):
    uid = message.from_user.id
    if not message.text or message.text.startswith('/'):
        bot.send_message(uid, "⚠️ تم إلغاء إضافة الرمز. أرسل /addtrack للمحاولة مجدداً.")
        return
    symbol = message.text.strip().upper()
    _do_addtrack(uid, symbol)

def _removetrack_step(message):
    uid = message.from_user.id
    symbol = message.text.strip().upper()
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if symbol in assets:
        assets.remove(symbol)
        save_tracked_assets()
        bot.send_message(uid, f"✅ تم حذف *{symbol}* من التتبع.", parse_mode="Markdown")
    else:
        bot.send_message(uid, f"⚠️ *{symbol}* غير موجود في قائمتك.", parse_mode="Markdown")

@bot.message_handler(commands=['stop'])
def stop_command(message):
    uid = message.from_user.id
    if uid in banned: return
    if str(uid) in users:
        users[str(uid)]["notifications"] = False
        _db_save_all_users(users)
    bot.send_message(uid, "🔕 تم إيقاف الإشعارات. أرسل /start للرجوع.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ref_feature_"))
def ref_feature_callback(call):
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)
    feat_key = data.replace("ref_feature_", "")
    if feat_key not in REFERRAL_FEATURES:
        return
    user = users.get(str(uid), {})
    unlocked = user.setdefault("unlocked_features", [])
    if feat_key in unlocked:
        bot.send_message(uid, "⚠️ هذه الميزة مفتوحة لديك بالفعل.")
        return
    unlocked.append(feat_key)
    users[str(uid)]["unlocked_features"] = unlocked
    _db_save_all_users(users)
    feat_name = REFERRAL_FEATURES[feat_key]
    bot.send_message(uid,
        f"✅ *تم فتح الميزة بنجاح!*\n\n"
        f"🎁 *{feat_name}*\n\n"
        f"يمكنك استخدامها الآن من /help لرؤية جميع الميزات.",
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("prem_") or c.data.startswith("req_premium_") or c.data.startswith("interest_") or c.data == "premium_menu")
def premium_callbacks(call):
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)

    if data == "premium_menu":
        send_premium_menu(uid)
        return

    elif data.startswith("req_premium_"):
        requester_id = data.split("_")[-1]
        user = users.get(str(uid), {})
        name = user.get("name", "مجهول")
        lang = user.get("lang", "-")
        all_admins = [ADMIN_ID] + extra_admins
        for admin_id in all_admins:
            try:
                bot.send_message(admin_id,
                    f"⭐ *طلب اشتراك مميز*\n\n"
                    f"👤 الاسم: {name}\n"
                    f"🆔 ID: `{requester_id}`\n"
                    f"🗣 اللغة: {lang}\n\n"
                    f"لترقيته: /admin ← المستخدمون ← ترقية لمميز",
                    parse_mode="Markdown"
                )
            except:
                pass
        bot.send_message(uid, "✅ تم إرسال طلبك للإدارة. سيتم التواصل معك قريباً.")
        return

    # الاهتمامات مجانية للجميع — لا تحتاج اشتراكاً مميزاً
    if data == "prem_interests":
        send_interest_menu(uid)
        return

    if not has_feature(uid, data):
        ref_count = len(users.get(str(uid), {}).get("referrals", []))
        next_milestone = next((m for m in REFERRAL_MILESTONES if m > ref_count), None)
        remaining = (next_milestone - ref_count) if next_milestone else 0
        bot.send_message(uid,
            "⭐ *هذه الميزة للمشتركين المميزين فقط.*\n\n"
            "💡 *يمكنك الحصول عليها مجاناً:*\n"
            "• دعوة 5 أصدقاء ← ميزة مجانية\n"
            "• دعوة 10 أصدقاء ← ميزتان مجانيتان\n"
            "• دعوة 25 صديق ← اشتراك مميز كامل شهر!\n\n"
            + (f"📊 دعواتك: `{ref_count}` — تحتاج `{remaining}` دعوة للمكافأة القادمة\n\n" if next_milestone else f"📊 دعواتك: `{ref_count}`\n\n")
            + "🔗 رابط دعوتك في قائمة *دعواتي*",
            parse_mode="Markdown"
        )
        return

    if data == "prem_7day":
        send_7day_forecast(uid)

    elif data == "prem_addcity":
        msg = bot.send_message(uid, "🏙 أرسل اسم المدينة التي تريد إضافتها (بالإنجليزي):")
        bot.register_next_step_handler(msg, lambda m: add_extra_city(m.from_user.id, m.text.strip()))

    elif data == "prem_interests":
        send_interest_menu(uid)

    elif data == "prem_currency_alert":
        user = users.get(str(uid), {})
        lang = user.get("lang", "English 🇬🇧")
        local_code, local_name = CURRENCY_MAP.get(lang, ("EUR", "Euro"))
        msg = bot.send_message(uid, f"💱 أرسل السعر المستهدف للدولار مقابل {local_name}:\n(مثال: 1600)")
        bot.register_next_step_handler(msg, set_currency_alert_step)

    elif data == "prem_notif_time":
        msg = bot.send_message(uid, "🕐 أرسل الساعة التي تريد استلام الملخص الصباحي فيها (0-23):\n(مثال: 8 للساعة 8 صباحاً)")
        bot.register_next_step_handler(msg, set_notif_time_step)

    elif data == "prem_hourly":
        send_hourly_weather_forecast(uid)

    elif data == "prem_mycities":
        user = users.get(str(uid), {})
        cities = [user.get("province", "")] + user.get("extra_cities", [])
        cities = [c for c in cities if c]
        if not cities:
            bot.send_message(uid, "⚠️ لا توجد مدن محفوظة.")
        else:
            msg = "🏙 *مدنك المحفوظة:*\n\n"
            for i, city in enumerate(cities):
                label = "(رئيسية)" if i == 0 else ""
                msg += f"  {i+1}. {city} {label}\n"
            bot.send_message(uid, msg, parse_mode="Markdown")

    elif data == "prem_currency_table":
        send_full_currency_table(uid)

    elif data == "prem_weekly":
        send_weekly_news_summary(uid)

    elif data == "prem_keywords":
        kws = user_keywords.get(str(uid), [])
        if kws:
            kw_list = "\n".join(f"• {k}" for k in kws)
            bot.send_message(uid,
                f"🔑 *كلماتك المفتاحية الحالية:*\n{kw_list}\n\n"
                "أرسل كلمة جديدة لإضافتها أو أرسل 'حذف كلمة' لحذفها:",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(uid,
                "🔑 *تنبيه الكلمات المفتاحية*\n\n"
                "أرسل كلمات تريد تتبعها مفصولة بفاصلة:\n"
                "مثال: رواتب, ميسي, عطلة رسمية\n\n"
                "عند ظهور أي كلمة في خبر ستصلك تنبيه فوري! 🔔",
                parse_mode="Markdown"
            )
        user_states[uid] = "adding_keyword"

    elif data.startswith("interest_") and data != "interest_save":
        opt = data[len("interest_"):]
        user = users.get(str(uid), {})
        interests = user.get("interests", [])
        if opt in interests:
            interests.remove(opt)
        else:
            interests.append(opt)
        users[str(uid)]["interests"] = interests
        _db_save_all_users(users)
        send_interest_menu(uid)

    elif data == "interest_save":
        interests = users.get(str(uid), {}).get("interests", [])
        if interests:
            bot.send_message(uid, "✅ تم حفظ اهتماماتك:\n" + "\n".join(interests))
        else:
            bot.send_message(uid, "✅ لا توجد اهتمامات محددة — ستصلك جميع الأخبار.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_") or c.data.startswith("broadcast_") or c.data.startswith("rss_") or c.data.startswith("quick_") or c.data.startswith("ch_") or c.data.startswith("interval_") or c.data.startswith("bl_") or c.data.startswith("backup_") or c.data == "noop")
def admin_callbacks(call):
    global users, stats, banned, inbox_messages, RSS, bot_paused, _pause_since, broadcast_paused
    if not is_admin(call.from_user.id):
        return
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)

    # ======== الإحصائيات ========
    if data == "admin_stats":
        today = str(datetime.date.today())
        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
        week_ago = datetime.date.today() - datetime.timedelta(days=7)
        weekly = sum(v for k, v in stats["daily_users"].items() if datetime.date.fromisoformat(k) >= week_ago)
        today_count = stats["daily_users"].get(today, 0)
        yesterday_count = stats["daily_users"].get(yesterday, 0)
        total = stats.get("total_users", len(users))
        active = sum(1 for u in users.values() if "province" in u)
        top_countries = sorted(stats["countries_count"].items(), key=lambda x: x[1], reverse=True)[:3]
        top_langs = sorted(stats["languages_count"].items(), key=lambda x: x[1], reverse=True)[:3]
        top_buttons = sorted(stats["button_presses"].items(), key=lambda x: x[1], reverse=True)[:3]
        msg = "📊 *الإحصائيات التفصيلية*\n\n"
        msg += f"👥 إجمالي المستخدمين: `{total}`\n"
        msg += f"✅ مستخدمون نشطون: `{active}`\n"
        msg += f"🆕 اليوم: `{today_count}`\n"
        msg += f"📅 أمس: `{yesterday_count}`\n"
        msg += f"📆 هذا الأسبوع: `{weekly}`\n"
        msg += f"⭐ مميزون: `{len(stats.get('premium_users', []))}`\n"
        msg += f"🚫 محظورون: `{len(banned)}`\n\n"
        if top_countries:
            msg += "🌍 *أكثر الدول:*\n"
            for c, n in top_countries:
                msg += f"  {c}: `{n}`\n"
        if top_langs:
            msg += "\n🗣 *أكثر اللغات:*\n"
            for l, n in top_langs:
                msg += f"  {l}: `{n}`\n"
        if top_buttons:
            msg += "\n🔘 *أكثر الأزرار استخداماً:*\n"
            for b, n in top_buttons:
                msg += f"  {b}: `{n}`\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
        # --- إحصائيات البث ---
        with _broadcast_stats_lock:
            bs = dict(_broadcast_stats)
            err_count = len(_broadcast_errors)
        interval_now = broadcast_settings.get("interval_minutes", 1)
        last_time = bs.get("last_broadcast_time") or "لم يحدث بعد"
        bcast_msg = (
            "📡 *إحصائيات البث:*\n\n"
            f"⏱ التوقيت: كل `{interval_now}` دقيقة\n"
            f"🕒 آخر بث: `{last_time}`\n"
            f"📰 أخبار اليوم: `{bs.get('today_news_sent', 0)}`\n"
            f"👥 مستخدمون وصلتهم اليوم: `{bs.get('today_users_reached', 0)}`\n"
            f"📊 إجمالي الأخبار المُرسلة: `{bs.get('total_news_all_time', 0)}`\n"
            f"⚠️ أخطاء مسجّلة: `{err_count}`"
        )
        markup_bs = types.InlineKeyboardMarkup()
        if err_count > 0:
            markup_bs.add(types.InlineKeyboardButton("📋 عرض سجل الأخطاء", callback_data="admin_broadcast_errors"))
        bot.send_message(uid, bcast_msg, parse_mode="Markdown", reply_markup=markup_bs if err_count > 0 else None)

    # ======== إدارة المستخدمين ========
    elif data == "admin_users":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📋 قائمة جميع المستخدمين", callback_data="admin_users_list_0"),
            types.InlineKeyboardButton("🔍 معلومات مستخدم", callback_data="admin_user_info"),
            types.InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban"),
            types.InlineKeyboardButton("✅ رفع حظر", callback_data="admin_unban"),
            types.InlineKeyboardButton("📋 قائمة المحظورين", callback_data="admin_banned_list"),
            types.InlineKeyboardButton("⭐ ترقية لمميز", callback_data="admin_premium"),
            types.InlineKeyboardButton("❌ إلغاء اشتراك مميز", callback_data="admin_unpremium"),
        )
        bot.send_message(uid, "👥 *إدارة المستخدمين:*\n\nإجمالي المستخدمين: `{}`".format(len(users)), parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("admin_users_list_"):
        page = int(data.split("_")[-1])
        per_page = 10
        all_uids = list(users.keys())
        total = len(all_uids)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = page * per_page
        end = start + per_page
        page_uids = all_uids[start:end]
        premium_list = stats.get("premium_users", [])
        lines = [f"👥 *قائمة المستخدمين* — صفحة {page+1}/{total_pages}\n━━━━━━━━━━━━━━"]
        for i, u_id in enumerate(page_uids, start + 1):
            u = users[u_id]
            name = u.get("name", "—")[:20]
            country = u.get("country", "—")[:15]
            lang = u.get("lang", "")[:4]
            is_prem = "⭐" if int(u_id) in premium_list else ""
            is_ban = "🚫" if int(u_id) in banned else ""
            lines.append(f"{i}. {is_prem}{is_ban} *{name}*\n    🆔 `{u_id}` | 🌍 {country} | 🗣 {lang}")
        msg = "\n".join(lines)
        nav_markup = types.InlineKeyboardMarkup(row_width=3)
        nav_btns = []
        if page > 0:
            nav_btns.append(types.InlineKeyboardButton("◀️ السابق", callback_data=f"admin_users_list_{page-1}"))
        nav_btns.append(types.InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
        if end < total:
            nav_btns.append(types.InlineKeyboardButton("التالي ▶️", callback_data=f"admin_users_list_{page+1}"))
        if nav_btns:
            nav_markup.add(*nav_btns)
        nav_markup.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="admin_users"))
        try:
            bot.edit_message_text(msg, uid, call.message.message_id, parse_mode="Markdown", reply_markup=nav_markup)
        except:
            bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=nav_markup)

    elif data == "admin_user_info":
        msg = bot.send_message(uid, "أرسل ID المستخدم:")
        bot.register_next_step_handler(msg, get_user_info)

    elif data == "admin_ban":
        msg = bot.send_message(uid, "أرسل ID المستخدم لحظره:")
        bot.register_next_step_handler(msg, ban_user_step)

    elif data == "admin_unban":
        msg = bot.send_message(uid, "أرسل ID المستخدم لرفع حظره:")
        bot.register_next_step_handler(msg, unban_user_step)

    elif data == "admin_banned_list":
        if not banned:
            bot.send_message(uid, "✅ لا يوجد مستخدمون محظورون.")
        else:
            bot.send_message(uid, "🚫 *المحظورون:*\n" + "\n".join(f"`{b}`" for b in banned), parse_mode="Markdown")

    elif data == "admin_premium":
        msg = bot.send_message(uid, "أرسل ID المستخدم لترقيته للمميز:")
        bot.register_next_step_handler(msg, promote_premium_step)

    elif data == "admin_unpremium":
        msg = bot.send_message(uid, "أرسل ID المستخدم لإلغاء اشتراكه المميز:")
        bot.register_next_step_handler(msg, demote_premium_step)

    # ======== الإرسال الجماعي ========
    elif data == "admin_broadcast":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📢 للكل", callback_data="broadcast_all"),
            types.InlineKeyboardButton("🌍 حسب الدولة", callback_data="broadcast_country"),
            types.InlineKeyboardButton("🗣 حسب اللغة", callback_data="broadcast_lang"),
            types.InlineKeyboardButton("⭐ للمميزين فقط", callback_data="broadcast_premium"),
        )
        bot.send_message(uid, "📢 *اختر نوع الإرسال:*", parse_mode="Markdown", reply_markup=markup)

    elif data == "broadcast_all":
        msg = bot.send_message(uid, "أرسل الرسالة لإرسالها لجميع المستخدمين:")
        bot.register_next_step_handler(msg, broadcast_all_step)

    elif data == "broadcast_country":
        msg = bot.send_message(uid, "أرسل اسم الدولة في السطر الأول، والرسالة في السطر الثاني:")
        bot.register_next_step_handler(msg, broadcast_country_step)

    elif data == "broadcast_lang":
        msg = bot.send_message(uid, "أرسل اللغة في السطر الأول، والرسالة في السطر الثاني:")
        bot.register_next_step_handler(msg, broadcast_lang_step)

    elif data == "broadcast_premium":
        msg = bot.send_message(uid, "أرسل الرسالة لإرسالها للمستخدمين المميزين:")
        bot.register_next_step_handler(msg, broadcast_premium_step)

    # ======== إيقاف/تشغيل البوت ========
    elif data == "admin_pause":
        if bot_paused:
            bot_paused = False
            _pause_since = None
            bot.send_message(uid, "✅ البوت يعمل الآن.")
        else:
            msg = bot.send_message(uid, "أرسل رسالة الإيقاف (أو أرسل 'افتراضي'):")
            bot.register_next_step_handler(msg, pause_bot_step)

    # ======== إدارة RSS ========
    elif data == "admin_rss":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة مصدر RSS", callback_data="rss_add"),
            types.InlineKeyboardButton("📥 إضافة متعددة", callback_data="rss_bulk_add"),
            types.InlineKeyboardButton("➖ حذف مصدر", callback_data="rss_remove"),
            types.InlineKeyboardButton("📋 عرض المصادر", callback_data="rss_list"),
            types.InlineKeyboardButton("🔍 اكتشاف RSS تلقائي", callback_data="rss_discover_help"),
            types.InlineKeyboardButton("📺 إضافة قناة تيليغرام", callback_data="rss_addchannel_help"),
            types.InlineKeyboardButton("🗑 حذف قناة مخصصة", callback_data="rss_removechannel_help"),
            types.InlineKeyboardButton("📋 قنوات مُضافة يدوياً", callback_data="rss_custom_channels_list"),
            types.InlineKeyboardButton("🔄 استعادة المصادر الافتراضية", callback_data="rss_reset_defaults"),
        )
        total_rss = sum(len(v) for v in RSS.values())
        total_tg = sum(len(v) for v in TELEGRAM_NEWS_CHANNELS.values())
        custom_tg = sum(len(v) for v in _custom_tg_channels.values())
        bot.send_message(uid,
            f"📡 *إدارة مصادر الأخبار*\n\n"
            f"📰 مصادر RSS: *{total_rss}*\n"
            f"📺 قنوات تيليغرام: *{total_tg}* (منها *{custom_tg}* مخصصة)\n\n"
            f"💡 استخدم الأوامر السريعة:\n"
            f"• `/discover <url>` — اكتشاف RSS من موقع\n"
            f"• `/addchannel <handle>` — إضافة قناة تيليغرام\n"
            f"• `/listsources` — القنوات المضافة يدوياً",
            parse_mode="Markdown", reply_markup=markup
        )

    elif data == "rss_bulk_add":
        msg = bot.send_message(uid,
            "📥 *إضافة مصادر متعددة دفعة واحدة*\n\n"
            "أرسل رسالة بالشكل التالي:\n\n"
            "`اللغة`\n"
            "`https://مصدر1.com/rss`\n"
            "`https://مصدر2.com/feed`\n"
            "`https://مصدر3.com/rss.xml`\n"
            "...\n\n"
            "مثال:\n"
            "`العربية 🇮🇶`\n"
            "`https://site1.com/rss`\n"
            "`https://site2.com/feed`",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, rss_bulk_add_step)

    elif data == "rss_discover_help":
        bot.send_message(uid,
            "🔍 *اكتشاف RSS تلقائي من موقع ويب*\n\n"
            "*كيفية الاستخدام:*\n"
            "`/discover <رابط الموقع> [اللغة]`\n\n"
            "*أمثلة:*\n"
            "`/discover https://www.almayadeen.net العربية 🇮🇶`\n"
            "`/discover https://www.bbc.com/arabic`\n"
            "`/discover https://www.reuters.com English 🇬🇧`\n\n"
            "⚙️ يجرب البوت تلقائياً أكثر من 9 أنماط شائعة للـ RSS،\n"
            "ويبحث أيضاً في كود الصفحة عن روابط RSS مخفية.",
            parse_mode="Markdown"
        )

    elif data == "rss_addchannel_help":
        langs_list = "\n".join(f"• `{l}`" for l in list(TELEGRAM_NEWS_CHANNELS.keys())[:8])
        bot.send_message(uid,
            "📺 *إضافة قناة تيليغرام كمصدر أخبار*\n\n"
            "*كيفية الاستخدام:*\n"
            "`/addchannel <handle> [اللغة] [الاسم]`\n\n"
            "*أمثلة:*\n"
            "`/addchannel AlJazeeraArabic العربية 🇮🇶 الجزيرة`\n"
            "`/addchannel BBCBreaking English 🇬🇧 BBC Breaking`\n\n"
            f"*اللغات المتاحة:*\n{langs_list}\n...\n\n"
            "💡 القناة ستساهم بالأخبار في دورة البث القادمة.",
            parse_mode="Markdown"
        )

    elif data == "rss_removechannel_help":
        bot.send_message(uid,
            "🗑 *حذف قناة تيليغرام من مصادر الأخبار*\n\n"
            "*كيفية الاستخدام:*\n"
            "`/removechannel <handle>`\n\n"
            "*مثال:*\n"
            "`/removechannel OldChannelHandle`\n\n"
            "⚠️ يعمل فقط على القنوات المُضافة يدوياً.\n"
            "القنوات الافتراضية تحتاج تعديل الكود لحذفها.",
            parse_mode="Markdown"
        )

    elif data == "rss_custom_channels_list":
        if not _custom_tg_channels or all(len(v) == 0 for v in _custom_tg_channels.values()):
            bot.send_message(uid,
                "📭 لم تُضف أي قنوات مخصصة بعد.\n"
                "استخدم `/addchannel` لإضافة قنوات جديدة.",
                parse_mode="Markdown"
            )
        else:
            msg = "📺 *قنوات التيليغرام المضافة يدوياً:*\n\n"
            for lang, channels in _custom_tg_channels.items():
                if channels:
                    msg += f"*{lang}:*\n"
                    for ch in channels:
                        msg += f"  • `@{ch['handle']}` — {ch['name']}\n"
                    msg += "\n"
            msg += "لحذف قناة: `/removechannel <handle>`"
            bot.send_message(uid, msg, parse_mode="Markdown")

    elif data == "rss_reset_defaults":
        RSS = {lang: list(feeds) for lang, feeds in DEFAULT_RSS.items()}
        save_rss()
        total = sum(len(v) for v in RSS.values())
        arabic_count = len(RSS.get("العربية 🇮🇶", []))
        bot.answer_callback_query(call.id, "✅ تم استعادة المصادر")
        bot.send_message(uid,
            f"✅ *تم استعادة المصادر الافتراضية*\n\n"
            f"• إجمالي المصادر: *{total}*\n"
            f"• مصادر العربية: *{arabic_count}* مصدر عامل مؤكد\n\n"
            f"⚠️ ملاحظة: المصادر القديمة المحذوفة كانت معطلة (404/403).",
            parse_mode="Markdown"
        )

    elif data == "rss_add":
        msg = bot.send_message(uid, "أرسل اللغة في السطر الأول، والرابط في السطر الثاني:")
        bot.register_next_step_handler(msg, rss_add_step)

    elif data == "rss_remove":
        msg = bot.send_message(uid, "أرسل اللغة في السطر الأول، ورقم المصدر في السطر الثاني:")
        bot.register_next_step_handler(msg, rss_remove_step)

    elif data == "rss_list":
        msg = "📡 *مصادر RSS الحالية:*\n\n"
        for lang, feeds in RSS.items():
            msg += f"*{lang}*\n"
            for i, f in enumerate(feeds):
                msg += f"  `{i+1}`. {f}\n"
            msg += "\n"
        bot.send_message(uid, msg, parse_mode="Markdown")

    # ======== المالية ========
    elif data == "admin_finance":
        premium_count = len(stats.get("premium_users", []))
        revenue = stats.get("revenue", 0.0)
        msg = (
            f"💰 *المالية*\n\n"
            f"⭐ المميزون: `{premium_count}`\n"
            f"💵 الدخل الكلي: `${revenue:.2f}`\n"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")

    # ======== تغيير رسالة الترحيب ========
    elif data == "admin_welcome":
        msg = bot.send_message(uid, "أرسل رسالة الترحيب الجديدة (أو 'افتراضي' للرجوع للأصلية):")
        bot.register_next_step_handler(msg, change_welcome_step)

    # ======== إدارة الأدمن ========
    elif data == "admin_manage_admins":
        # فقط الأدمن الرئيسي يستطيع إدارة الأدمن الآخرين
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة أدمن", callback_data="admin_addadmin"),
            types.InlineKeyboardButton("➖ إزالة أدمن", callback_data="admin_removeadmin"),
            types.InlineKeyboardButton("📋 قائمة الأدمن", callback_data="admin_listadmins"),
        )
        bot.send_message(uid, "👑 *إدارة الأدمن:*", parse_mode="Markdown", reply_markup=markup)

    elif data == "admin_addadmin":
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        msg = bot.send_message(uid, "أرسل ID المستخدم الذي تريد تعيينه أدمن:")
        bot.register_next_step_handler(msg, add_admin_step)

    elif data == "admin_removeadmin":
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        msg = bot.send_message(uid, "أرسل ID الأدمن الذي تريد إزالته:")
        bot.register_next_step_handler(msg, remove_admin_step)

    elif data == "admin_listadmins":
        if int(uid) != ADMIN_ID:
            bot.send_message(uid, "⛔ هذه الصلاحية للأدمن الرئيسي فقط.")
            return
        if not extra_admins:
            bot.send_message(uid, f"👑 *قائمة الأدمن:*\n\n🔑 الأدمن الرئيسي: `{ADMIN_ID}`\n\nلا يوجد أدمن إضافيون.", parse_mode="Markdown")
        else:
            admins_list = "\n".join(f"  `{a}`" for a in extra_admins)
            bot.send_message(uid,
                f"👑 *قائمة الأدمن:*\n\n"
                f"🔑 الأدمن الرئيسي: `{ADMIN_ID}`\n\n"
                f"👥 الأدمن الإضافيون:\n{admins_list}",
                parse_mode="Markdown"
            )

    elif data == "noop":
        bot.answer_callback_query(call.id)

    elif data.startswith("admin_view_"):
        target_id = data.split("admin_view_")[-1]
        user = users.get(target_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ المستخدم غير موجود")
            return
        is_banned_user = int(target_id) in banned
        is_premium_user = int(target_id) in stats.get("premium_users", [])
        referrals = user.get("referrals", [])
        referred_by = user.get("referred_by", None)
        join_date = user.get("join_date", "غير معروف")
        interests = user.get("interests", [])
        notif = "✅" if user.get("notifications", True) else "❌"
        track_data = tracked_assets.get(target_id, {})
        tracked = track_data.get("assets", [])
        msg = (
            f"👤 *ملف المستخدم*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{target_id}`\n"
            f"👤 الاسم: *{user.get('name', '—')}*\n"
            f"🗣 اللغة: {user.get('lang', '-')}\n"
            f"🌍 الدولة: {user.get('country', '-')}\n"
            f"📍 المحافظة: {user.get('province', '-')}\n"
            f"📅 الانضمام: `{join_date}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"🚫 محظور: {'نعم' if is_banned_user else 'لا'} | "
            f"⭐ مميز: {'نعم' if is_premium_user else 'لا'}\n"
            f"🔔 إشعارات: {notif} | 🎁 دعوات: `{len(referrals)}`\n"
            f"👈 جاء عبر: `{referred_by if referred_by else 'مباشر'}`\n"
            f"📌 يتتبع: `{', '.join(tracked) if tracked else '—'}`\n"
            f"📰 اهتمامات: `{', '.join(interests) if interests else '—'}`\n"
        )
        view_markup = types.InlineKeyboardMarkup(row_width=2)
        view_markup.add(
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{target_id}"),
            types.InlineKeyboardButton("⭐ ترقية مميز", callback_data=f"quick_premium_{target_id}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={target_id}"),
        )
        bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=view_markup)

    elif data.startswith("quick_ban_"):
        target_id_str = data.split("quick_ban_")[-1]
        try:
            target_id_int = int(target_id_str)
            if target_id_int not in banned:
                banned.append(target_id_int)
                save_json(BANNED_FILE, banned)
                bot.answer_callback_query(call.id, f"✅ تم حظر المستخدم {target_id_str}")
                bot.send_message(uid, f"🚫 تم حظر المستخدم `{target_id_str}` بنجاح.", parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "⚠️ هذا المستخدم محظور مسبقاً")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

    elif data.startswith("quick_premium_"):
        target_id_str = data.split("quick_premium_")[-1]
        try:
            target_id_int = int(target_id_str)
            premium_list = stats.get("premium_users", [])
            if target_id_int not in premium_list:
                premium_list.append(target_id_int)
                stats["premium_users"] = premium_list
                save_json(STATS_FILE, stats)
                bot.answer_callback_query(call.id, "✅ تمت الترقية لـ ⭐ مميز")
                bot.send_message(uid, f"⭐ تم ترقية المستخدم `{target_id_str}` للمميز.", parse_mode="Markdown")
                try:
                    bot.send_message(target_id_int, "🎉 تهانينا! تمت ترقيتك للاشتراك المميز ⭐\nاستمتع بجميع الميزات الحصرية!")
                except:
                    pass
            else:
                bot.answer_callback_query(call.id, "⚠️ هذا المستخدم مميز مسبقاً")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

    elif data == "admin_channels":
        handle_admin_channels(uid, call)

    elif data == "ch_add":
        bot.send_message(uid,
            "➕ *إضافة قناة أو مجموعة*\n\n"
            "أرسل المعلومات في رسالة واحدة بهذا الشكل:\n\n"
            "`-1001234567890`\n"
            "`العربية 🇮🇶`\n\n"
            "📌 السطر الأول: ID القناة/المجموعة\n"
            "📌 السطر الثاني: لغة الأخبار التي ستُرسل لها\n\n"
            "⚠️ تأكد أن البوت أدمن في القناة/المجموعة أولاً",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler_by_chat_id(uid, add_channel_step)

    elif data == "ch_remove":
        if not channels_groups:
            bot.send_message(uid, "📭 لا توجد قنوات/مجموعات مضافة حالياً.")
            return
        msg = "➖ *حذف قناة أو مجموعة*\n\nأرسل ID القناة/المجموعة للحذف:\n\n"
        for ch in channels_groups:
            msg += f"📺 *{ch['title']}* — `{ch['id']}`\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, remove_channel_step)

    elif data == "ch_list":
        if not channels_groups:
            bot.send_message(uid, "📭 لا توجد قنوات/مجموعات مضافة حالياً.")
            return
        msg = "📋 *قائمة القنوات والمجموعات:*\n\n"
        for i, ch in enumerate(channels_groups, 1):
            emoji = "📢" if ch.get("type") == "channel" else "👥"
            msg += (
                f"{i}. {emoji} *{ch['title']}*\n"
                f"   🆔 ID: `{ch['id']}`\n"
                f"   🗣 اللغة: {ch.get('lang', 'غير محددة')}\n\n"
            )
        bot.send_message(uid, msg, parse_mode="Markdown")

    elif data == "ch_broadcast_now":
        bot.send_message(uid, "📡 جاري إرسال الأخبار للقنوات والمجموعات...")
        try:
            broadcast_to_channels()
            bot.send_message(uid, f"✅ تم إرسال الأخبار لـ {len(channels_groups)} قناة/مجموعة.")
        except Exception as e:
            bot.send_message(uid, f"❌ خطأ أثناء البث: {e}")

    # ======== خبر عاجل مخصص ========
    elif data == "admin_breaking_news":
        bot.send_message(uid,
            "🚨 *إرسال خبر عاجل مخصص*\n\n"
            "أرسل نص الخبر العاجل، وسيُرسَل فوراً لجميع المستخدمين والقنوات مع الأزرار.\n\n"
            "💡 يمكنك إضافة رابط في السطر الثاني (اختياري):\n"
            "`نص الخبر العاجل`\n"
            "`https://رابط-الخبر (اختياري)`",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler_by_chat_id(uid, breaking_news_step)

    # ======== توقيت البث ========
    elif data == "admin_interval":
        current = broadcast_settings.get("interval_minutes", 1)
        markup_int = types.InlineKeyboardMarkup(row_width=3)
        markup_int.add(
            types.InlineKeyboardButton("1 دقيقة ✅" if current == 1 else "1 دقيقة", callback_data="interval_1"),
            types.InlineKeyboardButton("3 دقائق ✅" if current == 3 else "3 دقائق", callback_data="interval_3"),
            types.InlineKeyboardButton("5 دقائق ✅" if current == 5 else "5 دقائق", callback_data="interval_5"),
            types.InlineKeyboardButton("10 دقائق ✅" if current == 10 else "10 دقائق", callback_data="interval_10"),
            types.InlineKeyboardButton("15 دقيقة ✅" if current == 15 else "15 دقيقة", callback_data="interval_15"),
            types.InlineKeyboardButton("30 دقيقة ✅" if current == 30 else "30 دقيقة", callback_data="interval_30"),
            types.InlineKeyboardButton("60 دقيقة ✅" if current == 60 else "60 دقيقة", callback_data="interval_60"),
        )
        bot.send_message(uid,
            f"⏱ *توقيت البث الحالي:* كل `{current}` دقيقة\n\nاختر التوقيت الجديد:",
            parse_mode="Markdown", reply_markup=markup_int
        )

    elif data.startswith("interval_"):
        minutes = int(data.split("_")[1])
        broadcast_settings["interval_minutes"] = minutes
        save_broadcast_settings()
        interval_sec = max(30, minutes * 60)
        try:
            scheduler.reschedule_job("broadcast_news_job", trigger='interval', seconds=interval_sec)
            scheduler.reschedule_job("broadcast_channels_job", trigger='interval', seconds=interval_sec)
            applied = "✅ طُبِّق فوراً بدون إعادة تشغيل."
        except Exception as e:
            applied = f"⚠️ سيُطبَّق بعد إعادة التشغيل. ({e})"
        bot.send_message(uid,
            f"✅ تم تغيير توقيت البث إلى كل *{minutes}* دقيقة.\n{applied}",
            parse_mode="Markdown"
        )

    # ======== القائمة السوداء ========
    elif data == "admin_blacklist":
        words = blacklist_words
        count = len(words)
        words_preview = "، ".join(words[:10]) if words else "لا توجد كلمات"
        markup_bl = types.InlineKeyboardMarkup(row_width=2)
        markup_bl.add(
            types.InlineKeyboardButton("➕ إضافة كلمة", callback_data="bl_add"),
            types.InlineKeyboardButton("➖ حذف كلمة", callback_data="bl_remove"),
            types.InlineKeyboardButton("📋 عرض الكل", callback_data="bl_list"),
            types.InlineKeyboardButton("🗑 مسح الكل", callback_data="bl_clear"),
        )
        bot.send_message(uid,
            f"🚫 *القائمة السوداء للكلمات*\n\n"
            f"📊 عدد الكلمات: `{count}`\n"
            f"📝 عينة: {words_preview}\n\n"
            f"أي خبر يحتوي كلمة من هذه القائمة لن يُرسَل.",
            parse_mode="Markdown", reply_markup=markup_bl
        )

    elif data == "bl_add":
        bot.send_message(uid, "➕ أرسل الكلمة أو الكلمات التي تريد حجبها (كلمة واحدة أو أكثر مفصولة بفاصلة):")
        bot.register_next_step_handler_by_chat_id(uid, bl_add_step)

    elif data == "bl_remove":
        if not blacklist_words:
            bot.send_message(uid, "📭 القائمة السوداء فارغة.")
            return
        bot.send_message(uid, f"➖ أرسل الكلمة التي تريد حذفها:\n\n{', '.join(blacklist_words)}")
        bot.register_next_step_handler_by_chat_id(uid, bl_remove_step)

    elif data == "bl_list":
        if not blacklist_words:
            bot.send_message(uid, "📭 القائمة السوداء فارغة.")
            return
        bot.send_message(uid, "📋 *الكلمات المحجوبة:*\n\n" + "\n".join(f"• `{w}`" for w in blacklist_words), parse_mode="Markdown")

    elif data == "bl_clear":
        blacklist_words.clear()
        save_blacklist()
        bot.send_message(uid, "✅ تم مسح القائمة السوداء بالكامل.")

    # ======== عداد القراءة ========
    elif data == "admin_read_stats":
        total = read_stats.get("total_opens", 0)
        today = str(datetime.date.today())
        today_count = read_stats.get("daily", {}).get(today, 0)
        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
        yesterday_count = read_stats.get("daily", {}).get(yesterday, 0)
        bot.send_message(uid,
            f"📖 *إحصائيات القراءة (فتح الأخبار):*\n\n"
            f"📊 الإجمالي: `{total}` ضغطة\n"
            f"📅 اليوم: `{today_count}` ضغطة\n"
            f"📅 أمس: `{yesterday_count}` ضغطة",
            parse_mode="Markdown"
        )

    # ======== إحصائيات القنوات ========
    elif data == "admin_channel_stats":
        if not channels_groups:
            bot.send_message(uid, "📭 لا توجد قنوات/مجموعات مضافة.")
            return
        msg = "📈 *إحصائيات القنوات والمجموعات:*\n\n"
        total_sent = 0
        for ch in channels_groups:
            count_ch = ch.get("news_sent_count", 0)
            total_sent += count_ch
            emoji = "📢" if ch.get("type") == "channel" else "👥"
            msg += (
                f"{emoji} *{ch['title']}*\n"
                f"   📰 أخبار مُرسَلة: `{count_ch}`\n"
                f"   🌐 اللغة: {ch.get('lang', '-')}\n\n"
            )
        msg += f"━━━━━━━━━━━━━━\n📊 *إجمالي الأخبار المُرسَلة:* `{total_sent}`"
        bot.send_message(uid, msg, parse_mode="Markdown")

    # ======== بحث عن مستخدم ========
    elif data == "admin_search_user":
        bot.send_message(uid, "🔍 *بحث عن مستخدم*\n\nأرسل ID المستخدم أو اسمه للبحث:", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, search_user_step)

    # ======== رسالة لمستخدم محدد ========
    elif data == "admin_msg_user":
        bot.send_message(uid,
            "✉️ *إرسال رسالة لمستخدم محدد*\n\n"
            "أرسل في سطرين:\n"
            "السطر 1: ID المستخدم\n"
            "السطر 2: نص الرسالة",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler_by_chat_id(uid, msg_user_step)

    # ======== قائمة الأوامر ========
    elif data == "admin_commands":
        commands_text = (
            "📋 *قائمة جميع أوامر البوت:*\n\n"
            "━━━━━━━━━ *للأدمن* ━━━━━━━━━\n"
            "👑 `/admin` — لوحة تحكم الأدمن\n"
            "📊 `/stats` — إحصائيات البوت (إن وُجد)\n\n"
            "━━━━━━━━━ *للمستخدم* ━━━━━━━━━\n"
            "🚀 `/start` — بدء البوت\n"
            "❓ `/help` — المساعدة\n"
            "🔔 `/notify` — تفعيل/إيقاف الإشعارات (إن وُجد)\n\n"
            "━━━━━━━━━ *لأدمن القناة/المجموعة* ━━━━━━━━━\n"
            "🌐 `/setlang اسم_اللغة` — تغيير لغة الأخبار\n"
            "🏙 `/setcity اسم_المدينة` — تعيين المدينة\n"
            "📡 `/setsource رابط_RSS` — إضافة مصدر أخبار\n"
            "🗑 `/removesource رابط_RSS` — حذف مصدر أخبار\n"
            "📋 `/listsources` — عرض مصادر الأخبار\n"
            "⏸ `/pause` — إيقاف البث مؤقتاً\n"
            "▶️ `/resume` — استئناف البث\n"
            "⚙️ `/settings` — عرض الإعدادات الحالية\n\n"
            "━━━━━━━━━ *الأزرار على كل خبر* ━━━━━━━━━\n"
            "🔗 فتح الخبر — يفتح رابط الخبر\n"
            "📤 شارك الخبر — يشارك الخبر\n"
            f"🤖 شارك البوت — يشارك @{BOT_USERNAME}"
        )
        bot.send_message(uid, commands_text, parse_mode="Markdown")

    elif data == "admin_news_format":
        sep = news_settings.get("separator", "━━━━━━━━━━━━━━")
        sig = news_settings.get("signature", "عبر بوت أخبار العالم\n@Iraqnowbot")
        label = news_settings.get("label", "🚨 خبر عاجل")
        preview = f"{label}\n\n📰 عنوان الخبر التجريبي\n{sep}\n{sig}"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✏️ تعديل العنوان", callback_data="admin_nf_label"),
            types.InlineKeyboardButton("➖ تعديل الفاصل", callback_data="admin_nf_sep"),
            types.InlineKeyboardButton("📝 تعديل التوقيع", callback_data="admin_nf_sig"),
            types.InlineKeyboardButton("🔬 بث تجريبي للأدمن", callback_data="admin_nf_test"),
            types.InlineKeyboardButton("🔄 إعادة تعيين الإعدادات", callback_data="admin_nf_reset"),
        )
        try:
            bot.send_message(uid, f"✏️ *شكل رسالة الخبر الحالي:*\n\n{preview}", parse_mode="Markdown", reply_markup=markup)
        except Exception:
            # إذا فشل Markdown (بسبب رموز خاصة في الإعدادات)، أرسل بدون تنسيق
            bot.send_message(uid,
                f"✏️ شكل رسالة الخبر الحالي:\n\n{preview}\n\n"
                "⚠️ تنبيه: الإعدادات الحالية تحتوي على رموز غير صحيحة.\n"
                "استخدم 'إعادة تعيين' لإرجاع الإعدادات الافتراضية.",
                reply_markup=markup)

    elif data == "admin_broadcast_errors":
        with _broadcast_stats_lock:
            errors = list(_broadcast_errors)
        if not errors:
            bot.send_message(uid, "✅ لا توجد أخطاء مسجّلة.")
        else:
            text = "📋 *سجل آخر أخطاء البث:*\n\n" + "\n".join(f"`{e}`" for e in errors[-15:])
            try:
                bot.send_message(uid, text, parse_mode="Markdown")
            except Exception:
                bot.send_message(uid, "📋 سجل الأخطاء:\n\n" + "\n".join(errors[-10:]))

    elif data == "admin_nf_test":
        lang_test = "العربية 🇮🇶"
        feeds_test = RSS.get(lang_test, [])
        sent_test = False
        for feed_url in feeds_test:
            try:
                feed = _parse_feed(feed_url, timeout=15)
                if feed and feed.entries:
                    item = feed.entries[0]
                    title = getattr(item, 'title', 'عنوان تجريبي')
                    link = getattr(item, 'link', '')
                    summary = getattr(item, 'summary', '')
                    src_name = get_source_name_from_url(feed_url)
                    markup = make_news_share_markup(link, title, lang_test, summary)
                    pub_time_str = _format_pub_time(_pub_dt_from_item(item) if hasattr(item, 'published_parsed') else None, lang=lang_test)
                    text = format_news_item(t(lang_test, "label_breaking"), title, lang_test, src_name, pub_time_str, summary=summary)
                    bot.send_message(uid, "🔬 *بث تجريبي — هكذا سيصل الخبر للمستخدمين:*", parse_mode="Markdown")
                    try:
                        bot.send_message(uid, text, parse_mode="Markdown", reply_markup=markup)
                    except Exception:
                        bot.send_message(uid, text, reply_markup=markup)
                    sent_test = True
                    break
            except Exception:
                continue
        if not sent_test:
            bot.send_message(uid, "⚠️ لم يتم العثور على أخبار حالياً للاختبار.")

    elif data == "admin_nf_label":
        msg = bot.send_message(uid, "📝 أرسل العنوان الجديد للخبر (مثال: 🚨 خبر عاجل):")
        bot.register_next_step_handler(msg, _nf_label_step)

    elif data == "admin_nf_sep":
        msg = bot.send_message(uid, "📝 أرسل الفاصل الجديد (مثال: ━━━━━━━━━━━━━━ أو --- أو اكتب 'بدون' لحذفه):")
        bot.register_next_step_handler(msg, _nf_sep_step)

    elif data == "admin_nf_sig":
        msg = bot.send_message(uid, "📝 أرسل التوقيع الجديد (مثال: عبر بوتي\\n@username):")
        bot.register_next_step_handler(msg, _nf_sig_step)

    elif data == "admin_nf_reset":
        news_settings["label"] = "🚨 خبر عاجل"
        news_settings["separator"] = "━━━━━━━━━━━━━━"
        news_settings["signature"] = "عبر بوت أخبار العالم\n@Iraqnowbot"
        save_news_settings()
        bot.send_message(uid, "✅ تم إعادة تعيين شكل الخبر إلى الإعدادات الافتراضية.")

    elif data == "admin_inbox":
        if not inbox_messages:
            bot.send_message(uid, "📭 صندوق الرسائل فارغ حالياً.")
        else:
            last = inbox_messages[-10:]
            for entry in reversed(last):
                u_id = entry.get("uid")
                name = entry.get("name", "مجهول")
                text = entry.get("text", "")
                utype = "⭐ مميز" if entry.get("premium") else "👤 عادي"
                ts = entry.get("time", "")
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(f"↩️ رد على {name}", callback_data=f"admin_reply_{u_id}"))
                bot.send_message(uid,
                    f"💬 *رسالة من:* {name}\n"
                    f"🆔 `{u_id}` | {utype}\n"
                    f"🕐 {ts}\n\n"
                    f"📩 {text}",
                    parse_mode="Markdown", reply_markup=markup)

    elif data.startswith("admin_reply_"):
        target_uid = data.split("admin_reply_")[-1]
        msg = bot.send_message(uid, f"✏️ اكتب ردك على المستخدم `{target_uid}`:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, lambda m, tid=target_uid: _admin_reply_step(m, tid))

    elif data == "admin_ratings":
        count = ratings_data.get("count", 0)
        if count == 0:
            bot.send_message(uid, "⭐ لا توجد تقييمات بعد.")
        else:
            bot_avg = round(ratings_data.get("bot_sum", 0) / count, 1)
            news_avg = round(ratings_data.get("news_sum", 0) / count, 1)
            bot.send_message(uid,
                f"⭐ *تقييمات المستخدمين*\n\n"
                f"📊 إجمالي التقييمات: `{count}`\n"
                f"🤖 متوسط تقييم البوت: `{bot_avg}/5`\n"
                f"📰 متوسط تقييم الأخبار: `{news_avg}/5`",
                parse_mode="Markdown")

    elif data == "admin_backup":
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📦 نسخة كاملة",      callback_data="backup_full"),
            types.InlineKeyboardButton("👥 قاعدة المستخدمين", callback_data="backup_users"),
            types.InlineKeyboardButton("📡 مصادر RSS",        callback_data="backup_rss"),
            types.InlineKeyboardButton("📺 القنوات والمجموعات", callback_data="backup_channels"),
            types.InlineKeyboardButton("⚙️ إعدادات البوت",    callback_data="backup_settings"),
        )
        bot.send_message(uid, "💾 *اختر نوع النسخة الاحتياطية:*", parse_mode="Markdown", reply_markup=markup)

    elif data == "backup_full":
        bot.answer_callback_query(call.id, "📤 جاري إرسال النسخة الكاملة...")
        send_backup(uid)

    elif data == "backup_users":
        bot.answer_callback_query(call.id, "👥 جاري إرسال بيانات المستخدمين...")
        _send_sectioned_backup(uid, "users")

    elif data == "backup_rss":
        bot.answer_callback_query(call.id, "📡 جاري إرسال مصادر RSS...")
        _send_sectioned_backup(uid, "rss")

    elif data == "backup_channels":
        bot.answer_callback_query(call.id, "📺 جاري إرسال القنوات...")
        _send_sectioned_backup(uid, "channels")

    elif data == "backup_settings":
        bot.answer_callback_query(call.id, "⚙️ جاري إرسال الإعدادات...")
        _send_sectioned_backup(uid, "settings")

    elif data == "admin_toggle_broadcast":
        broadcast_paused = not broadcast_paused
        if broadcast_paused:
            bot.answer_callback_query(call.id, "📴 تم إيقاف البث")
            bot.send_message(uid,
                "📴 *تم إيقاف البث الإخباري*\n\n"
                "البوت لا يزال يعمل ويستقبل الأوامر، لكن لن تُرسل أخبار تلقائية للمستخدمين.\n"
                "اضغط */admin* ← *📡 تشغيل البث* لإعادة التشغيل.",
                parse_mode="Markdown"
            )
        else:
            bot.answer_callback_query(call.id, "📡 تم تشغيل البث")
            bot.send_message(uid,
                "📡 *تم تشغيل البث الإخباري*\n\n"
                "سيبدأ إرسال الأخبار للمستخدمين في الدورة القادمة (خلال دقيقتين).",
                parse_mode="Markdown"
            )

    elif data == "admin_reset_sent_news":
        bot.answer_callback_query(call.id, "🔄 جاري إعادة التعيين...")
        count = 0
        for user_uid, user_data in users.items():
            if "sent_news" in user_data:
                user_data["sent_news"] = set()
                count += 1
        for ch in channels_groups:
            if "sent_news" in ch:
                ch["sent_news"] = []
        # مسح التتبع العالمي أيضاً
        with _global_sent_lock:
            _global_sent_news.clear()
        _db_save_all_users(users)
        save_channels_groups()
        _save_global_sent_news()
        bot.send_message(uid,
            f"✅ *تم إعادة تعيين سجل الأخبار*\n\n"
            f"• تم مسح sent\\_news لـ *{count}* مستخدم\n"
            f"• تم مسح سجل القنوات أيضاً\n"
            f"• تم مسح التتبع العالمي للأخبار\n\n"
            f"🚀 سيبدأ البث فوراً في الدورة القادمة (خلال دقيقتين)",
            parse_mode="Markdown"
        )

    elif data == "admin_full_reset":
        # خطوة التأكيد الأولى
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("⚠️ نعم، امسح كل شيء", callback_data="admin_full_reset_confirm"),
            types.InlineKeyboardButton("❌ إلغاء", callback_data="admin_cancel"),
        )
        bot.send_message(uid,
            "🗑 *إعادة تعيين البوت كاملاً*\n\n"
            "⚠️ *تحذير: هذا الإجراء لا يمكن التراجع عنه!*\n\n"
            "سيتم مسح:\n"
            "• ✂️ كل بيانات المستخدمين (اللغة، المدينة، الإعدادات)\n"
            "• 📰 سجل الأخبار المُرسلة\n"
            "• 📊 الإحصائيات\n"
            "• 🚫 قائمة المحظورين\n"
            "• 💬 صندوق الرسائل والتقييمات\n"
            "• ✏️ شكل رسالة الخبر (يُعاد للافتراضي)\n\n"
            "سيتم *الاحتفاظ* بـ:\n"
            "• 👑 قائمة الأدمن\n"
            "• 📡 مصادر RSS المخصصة\n"
            "• 📺 القنوات والمجموعات\n\n"
            "هل أنت متأكد؟",
            parse_mode="Markdown",
            reply_markup=markup
        )

    elif data == "admin_full_reset_confirm":
        bot.answer_callback_query(call.id, "⏳ جاري إعادة التعيين الكاملة...")
        # --- مسح بيانات المستخدمين ---
        users.clear()
        save_json(USERS_FILE, {})
        _db_save_all_users({})
        # --- مسح الإحصائيات ---
        stats.clear()
        stats.update({"total_users": 0, "daily_users": {}, "lang_dist": {}, "country_dist": {}})
        save_json(STATS_FILE, stats)
        # --- مسح قائمة المحظورين ---
        banned.clear()
        save_json(BANNED_FILE, [])
        # --- مسح صندوق الرسائل ---
        inbox_messages.clear()
        save_json(INBOX_FILE, [])
        # --- مسح التقييمات ---
        save_json(RATINGS_FILE, {})
        # --- مسح سجل القراءة ---
        save_json(READ_STATS_FILE, {"total_opens": 0, "daily": {}})
        # --- إعادة شكل الخبر للافتراضي ---
        news_settings["label"] = "🚨 خبر عاجل"
        news_settings["separator"] = "━━━━━━━━━━━━━━"
        news_settings["signature"] = "عبر بوت أخبار العالم\n@Iraqnowbot"
        save_news_settings()
        # --- مسح سجل الأخبار المُرسلة (global + per-channel) ---
        with _global_sent_lock:
            _global_sent_news.clear()
        _save_global_sent_news()
        for ch in channels_groups:
            ch["sent_news"] = []
        save_channels_groups()
        bot.send_message(uid,
            "✅ *تمت إعادة التعيين الكاملة بنجاح*\n\n"
            "• بيانات المستخدمين: ✅ ممسوحة\n"
            "• الإحصائيات: ✅ ممسوحة\n"
            "• قائمة المحظورين: ✅ ممسوحة\n"
            "• صندوق الرسائل: ✅ ممسوح\n"
            "• شكل الخبر: ✅ أُعيد للافتراضي\n"
            "• سجل الأخبار: ✅ ممسوح\n\n"
            "📡 قائمة الأدمن ومصادر RSS والقنوات محتفظ بها.\n\n"
            "🚀 البوت جاهز لاستقبال مستخدمين جدد!",
            parse_mode="Markdown"
        )

    elif data == "admin_cancel":
        bot.answer_callback_query(call.id, "❌ تم الإلغاء")
        bot.send_message(uid, "❌ تم إلغاء العملية.")

    elif data == "admin_debugnews":
        bot.answer_callback_query(call.id, "🔍 جاري التشخيص...")
        # استدعاء نفس منطق /debugnews
        now_utc = _now_sa()
        news_lock_status  = "🔴 مشغول" if _broadcast_news_lock.is_set() else "🟢 حر"
        ch_lock_status    = "🔴 مشغول" if _broadcast_channels_lock.is_set() else "🟢 حر"
        with _global_sent_lock:
            gsn_counts = {lang: len(s) for lang, s in _global_sent_news.items()}
        gsn_text = "\n".join([f"  `{l[:15]}`: {cnt}" for l, cnt in gsn_counts.items()]) or "  فارغ ✅"
        active_users = sum(1 for info in users.values()
                           if info.get("notifications", True) and info.get("lang"))
        gsn_age = "—"
        try:
            if os.path.exists(_GLOBAL_SENT_FILE):
                age_secs = time.time() - os.path.getmtime(_GLOBAL_SENT_FILE)
                gsn_age = f"{age_secs/60:.0f} دقيقة"
        except Exception:
            pass
        msg = (
            f"🔍 تشخيص نظام الإرسال\n"
            f"🕐 {now_utc.strftime('%H:%M:%S')} (توقيت السعودية)\n\n"
            f"الأقفال: بث={news_lock_status} | قنوات={ch_lock_status}\n"
            f"الإيقاف: bot={bot_paused}, bcast={broadcast_paused}\n"
            f"المستخدمون: إجمالي={len(users)} | فعّالون={active_users}\n\n"
            f"global_sent_news (عمر الملف: {gsn_age}):\n{gsn_text}\n\n"
            f"الأوامر: /clearcache | /forcenews"
        )
        bot.send_message(uid, msg)

    elif data == "admin_clearcache":
        bot.answer_callback_query(call.id, "🧹 جاري المسح...")
        with _global_sent_lock:
            old_count = sum(len(s) for s in _global_sent_news.values())
            _global_sent_news.clear()
        _save_global_sent_news()
        bot.send_message(uid,
            f"✅ *تم مسح كاش الأخبار*\n"
            f"حُذف `{old_count:,}` رابط — سيبدأ البث الفوري خلال 30 ثانية",
            parse_mode="Markdown")

    elif data == "admin_forcenews":
        bot.answer_callback_query(call.id, "⚡ جاري إطلاق البث...")
        if _broadcast_news_lock.is_set():
            bot.send_message(uid, "⚠️ دورة بث جارية الآن — انتظر 30 ثانية.")
        else:
            threading.Thread(target=_safe_job(broadcast_news), daemon=True,
                             name="ForceBroadcast").start()
            bot.send_message(uid, "✅ تم إطلاق دورة البث الفورية!")

# ======== دوال شكل الخبر ========
def _validate_news_format(uid, label, separator, signature):
    """
    يُجرّب إرسال خبر تجريبي بالتنسيق الجديد بنفس الشكل الحقيقي.
    يُعيد True إذا كان التنسيق صحيحاً، أو يُرسل رسالة خطأ تفصيلية ويُعيد False.
    """
    # نفس الصيغة التي تستخدمها format_news_item تماماً
    sep_line = f"\n{separator}" if separator else ""
    test_text = f"{label}\n\n📰 عنوان الخبر التجريبي\n🗞 مصدر تجريبي{sep_line}\n{signature}"
    try:
        bot.send_message(uid, test_text, parse_mode="Markdown")
        return True
    except Exception as e:
        err = str(e)
        if "can't parse" in err or "parse entities" in err or "400" in err:
            bot.send_message(
                uid,
                "❌ خطأ في التنسيق!\n\n"
                "النص الذي أدخلته يحتوي على رموز Markdown غير صحيحة أو غير مغلقة.\n\n"
                "الرموز التي قد تسبب مشكلة اذا ما كانت مغلقة:\n"
                "  * للعريض: يجب يكون *نص* (مفتوح ومغلق)\n"
                "  _ للمائل: يجب يكون _نص_ (مفتوح ومغلق)\n"
                "  ` للكود: يجب يكون `نص` (مفتوح ومغلق)\n\n"
                "للنص العادي: اكتب النص بدون أي رموز خاصة.\n\n"
                "لم يتم حفظ التغيير — حاول مجدداً."
            )
        return False

def _nf_label_step(message):
    if not is_admin(message.from_user.id):
        return
    new_label = message.text.strip()
    sep = news_settings.get("separator", "━━━━━━━━━━━━━━")
    sig = news_settings.get("signature", "عبر بوت أخبار العالم\n@Iraqnowbot")
    if not _validate_news_format(message.from_user.id, new_label, sep, sig):
        return
    news_settings["label"] = new_label
    save_news_settings()
    bot.send_message(message.from_user.id, "✅ تم حفظ العنوان الجديد بنجاح.")

def _nf_sep_step(message):
    if not is_admin(message.from_user.id):
        return
    val = message.text.strip()
    new_sep = "" if val == "بدون" else val
    label = news_settings.get("label", "🚨 خبر عاجل")
    sig = news_settings.get("signature", "عبر بوت أخبار العالم\n@Iraqnowbot")
    if not _validate_news_format(message.from_user.id, label, new_sep, sig):
        return
    news_settings["separator"] = new_sep
    save_news_settings()
    bot.send_message(message.from_user.id, "✅ تم حفظ الفاصل الجديد بنجاح.")

def _nf_sig_step(message):
    if not is_admin(message.from_user.id):
        return
    new_sig = message.text.strip().replace("\\n", "\n")
    label = news_settings.get("label", "🚨 خبر عاجل")
    sep = news_settings.get("separator", "━━━━━━━━━━━━━━")
    if not _validate_news_format(message.from_user.id, label, sep, new_sig):
        return
    news_settings["signature"] = new_sig
    save_news_settings()
    bot.send_message(message.from_user.id, "✅ تم حفظ التوقيع الجديد بنجاح.")

def _admin_reply_step(message, target_uid):
    if not is_admin(message.from_user.id):
        return
    try:
        bot.send_message(int(target_uid),
            f"💬 *رد من إدارة البوت:*\n\n{message.text}",
            parse_mode="Markdown")
        bot.send_message(message.from_user.id, "✅ تم إرسال الرد بنجاح.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"⚠️ فشل الإرسال: {e}")

# ======== إدارة القنوات والمجموعات ========
def handle_admin_channels(uid, call):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ إضافة قناة/مجموعة", callback_data="ch_add"),
        types.InlineKeyboardButton("➖ حذف قناة/مجموعة", callback_data="ch_remove"),
        types.InlineKeyboardButton("📋 قائمة القنوات", callback_data="ch_list"),
        types.InlineKeyboardButton("📢 بث أخبار للقنوات الآن", callback_data="ch_broadcast_now"),
    )
    count = len(channels_groups)
    bot.send_message(uid,
        f"📺 *إدارة القنوات والمجموعات*\n\n"
        f"📊 عدد القنوات/المجموعات المضافة: `{count}`\n\n"
        f"💡 *كيفية الإضافة:*\n"
        f"1. أضف البوت كأدمن في القناة/المجموعة\n"
        f"2. أرسل ID القناة أو المجموعة (مثال: -1001234567890)\n"
        f"3. حدد اللغة المناسبة لإرسال الأخبار",
        parse_mode="Markdown", reply_markup=markup
    )

def add_channel_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    lines = message.text.strip().split("\n")
    if len(lines) < 2:
        bot.send_message(uid,
            "❌ أرسل في سطرين:\n"
            "السطر 1: ID القناة/المجموعة (مثال: -1001234567890)\n"
            "السطر 2: اللغة (مثال: العربية 🇮🇶)"
        )
        return
    try:
        chat_id = int(lines[0].strip())
        lang = lines[1].strip()
        try:
            chat_info = bot.get_chat(chat_id)
            title = chat_info.title or str(chat_id)
            chat_type = chat_info.type
        except Exception as e:
            bot.send_message(uid, f"❌ تعذّر الوصول للقناة/المجموعة: {e}\nتأكد أن البوت أدمن فيها.")
            return
        for ch in channels_groups:
            if ch["id"] == chat_id:
                bot.send_message(uid, f"⚠️ هذه القناة/المجموعة مضافة مسبقاً: *{title}*", parse_mode="Markdown")
                return
        feeds = RSS.get(lang, RSS.get("العربية 🇮🇶", []))
        initial_sent = list(prefill_sent_news(feeds))
        channels_groups.append({"id": chat_id, "title": title, "type": chat_type, "lang": lang, "sent_news": initial_sent})
        save_channels_groups()
        bot.send_message(uid,
            f"✅ تمت الإضافة بنجاح!\n"
            f"📺 *{title}*\n"
            f"🆔 ID: `{chat_id}`\n"
            f"🗣 اللغة: {lang}\n"
            f"📡 النوع: {chat_type}\n"
            f"📰 تم حفظ {len(initial_sent)} خبر موجود — ستصل فقط الأخبار الجديدة من الآن.",
            parse_mode="Markdown"
        )
    except ValueError:
        bot.send_message(uid, "❌ ID غير صحيح. يجب أن يكون رقماً مثل: -1001234567890")
    except Exception as e:
        bot.send_message(uid, f"❌ خطأ: {e}")

def remove_channel_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    try:
        chat_id = int(message.text.strip())
        removed = None
        for i, ch in enumerate(channels_groups):
            if ch["id"] == chat_id:
                removed = channels_groups.pop(i)
                break
        if removed:
            save_channels_groups()
            bot.send_message(uid, f"✅ تم حذف القناة/المجموعة: *{removed['title']}*", parse_mode="Markdown")
        else:
            bot.send_message(uid, "⚠️ هذا ID غير موجود في القائمة.")
    except ValueError:
        bot.send_message(uid, "❌ أرسل ID رقمياً فقط.")
    except Exception as e:
        bot.send_message(uid, f"❌ خطأ: {e}")

def prefill_sent_news(feeds):
    """جلب روابط آخر 3 أخبار فقط من كل مصدر (لتجنب حظر الأخبار الحالية كلها)."""
    links = set()
    for feed_url in feeds[:10]:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for item in feed.entries[:3]:
                link = getattr(item, 'link', '')
                if link:
                    links.add(link)
        except:
            pass
    return links


# =====================================================================
# ==================== دوال نظام الرياضة ============================
# =====================================================================

def _get_live_scores(espn_slug: str) -> list:
    """جلب النتائج المباشرة من ESPN مع أحداث كاملة (أهداف، بطاقات، جزاء)"""
    try:
        sport, league = espn_slug.split('/', 1)
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        data = r.json()
        matches = []
        for event in data.get('events', []):
            comp = event.get('competitions', [{}])[0]
            status = comp.get('status', {})
            state = status.get('type', {}).get('state', '')
            desc = status.get('type', {}).get('description', '')
            clock = status.get('displayClock', '')
            period = status.get('period', 0)
            competitors = comp.get('competitors', [])
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
            away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
            home_team_id = home.get('team', {}).get('id', '')

            # ── جلب أحداث المباراة من حقل details ──────────────────────
            match_events = []
            for detail in comp.get('details', []):
                try:
                    ev_type = detail.get('type', {}).get('text', '')
                    ev_type_lower = ev_type.lower()
                    ev_clock = detail.get('clock', {}).get('displayValue', '') or detail.get('clock', '')
                    if isinstance(ev_clock, dict):
                        ev_clock = ev_clock.get('displayValue', '')
                    team_id = str(detail.get('team', {}).get('id', ''))
                    athletes = detail.get('athletesInvolved', [])
                    player = athletes[0].get('displayName', '') if athletes else ''
                    h_score = str(detail.get('homeScore', ''))
                    a_score = str(detail.get('awayScore', ''))
                    team_abbr = (
                        home.get('team', {}).get('abbreviation', '?')
                        if team_id == home_team_id
                        else away.get('team', {}).get('abbreviation', '?')
                    )
                    # إيموجي الحدث
                    if any(k in ev_type_lower for k in ('goal', 'score', 'touchdown', 'basket')):
                        ev_emoji = '⚽'
                    elif 'red' in ev_type_lower:
                        ev_emoji = '🟥'
                    elif 'yellow' in ev_type_lower or 'card' in ev_type_lower:
                        ev_emoji = '🟨'
                    elif 'penalty' in ev_type_lower or 'pen' in ev_type_lower:
                        ev_emoji = '🎯'
                    elif 'substitut' in ev_type_lower or 'sub' in ev_type_lower:
                        ev_emoji = '🔄'
                    elif 'offside' in ev_type_lower:
                        ev_emoji = '🚩'
                    else:
                        ev_emoji = '•'
                    score_part = f" [{h_score}-{a_score}]" if h_score and a_score else ''
                    player_part = f" {player}" if player else ''
                    team_part = f" ({team_abbr})" if team_abbr and team_abbr != '?' else ''
                    clock_part = f"{ev_clock}'" if ev_clock else ''
                    display = f"{ev_emoji} {clock_part}{player_part}{team_part}{score_part}".strip()
                    match_events.append({
                        'type': ev_type,
                        'emoji': ev_emoji,
                        'clock': ev_clock,
                        'player': player,
                        'team_id': team_id,
                        'display': display,
                        'score': f"{h_score}-{a_score}" if h_score else '',
                    })
                except Exception:
                    pass

            matches.append({
                'home':       home.get('team', {}).get('displayName', '?'),
                'away':       away.get('team', {}).get('displayName', '?'),
                'home_abbr':  home.get('team', {}).get('abbreviation', '?'),
                'away_abbr':  away.get('team', {}).get('abbreviation', '?'),
                'home_id':    str(home.get('team', {}).get('id', '')),
                'away_id':    str(away.get('team', {}).get('id', '')),
                'home_score': home.get('score', '-'),
                'away_score': away.get('score', '-'),
                'state':      state,
                'desc':       desc,
                'clock':      clock,
                'period':     period,
                'date':       event.get('date', ''),
                'id':         event.get('id', ''),
                'name':       event.get('name', ''),
                'events':     match_events,
            })
        return matches
    except Exception:
        return []

def _format_match_line(m: dict, sport: str = 'football', tz_offset: int = 3) -> str:
    """
    تنسيق سطر حدث رياضي واحد حسب نوع الرياضة.
    إصلاح #12: tz_offset يمرَّر من الخارج حسب لغة المستخدم (افتراضي +3 بغداد).
    """
    state = m.get('state', '')
    home  = m.get('home', '?')
    away  = m.get('away', '?')
    hs    = m.get('home_score', '-')
    as_   = m.get('away_score', '-')
    _live_icon = {
        'football':'🔴','basketball':'🔴','tennis':'🎾','racing':'🏎️',
        'hockey':'🏒','baseball':'⚾','american_football':'🏈','golf':'⛳','cricket':'🏏',
    }.get(sport, '🔴')
    _end_icon = '✅'
    if state == 'in':
        clock_part = f" ⏱{m['clock']}" if m.get('clock') else ''
        score_part = f" `{hs} - {as_}`" if hs != '-' else ''
        return f"{_live_icon} *{home}*{score_part} *{away}*{clock_part}"
    elif state == 'post':
        score_part = f" `{hs} - {as_}`" if hs != '-' else ''
        return f"{_end_icon} *{home}*{score_part} *{away}* (انتهت)"
    else:
        if m.get('date'):
            try:
                dt = datetime.datetime.strptime(m['date'][:16], '%Y-%m-%dT%H:%M')
                dt_local = dt + datetime.timedelta(hours=tz_offset)
                time_str = dt_local.strftime('%d/%m %H:%M')
            except Exception:
                time_str = ''
        else:
            time_str = ''
        return f"🕐 *{home}* vs *{away}*" + (f" — `{time_str}`" if time_str else "")

def _get_user_sports(uid) -> dict:
    prefs = users.get(str(uid), {}).get('sports', {})
    if not prefs:
        prefs = {'leagues': [], 'teams': {}, 'live_alerts': False}
    # ترقية: إذا teams كانت list قديمة → حوّلها لـ dict
    if isinstance(prefs.get('teams'), list):
        prefs['teams'] = {}
    if 'teams' not in prefs:
        prefs['teams'] = {}
    if 'leagues' not in prefs:
        prefs['leagues'] = []
    return prefs

def _set_user_sports(uid, prefs: dict):
    uid_s = str(uid)
    if uid_s not in users:
        users[uid_s] = {}
    users[uid_s]['sports'] = prefs
    save_users()

# تصنيفات الرياضة
SPORT_CATEGORIES = {
    "football":          {"name": "⚽ كرة القدم",               "flag": "⚽"},
    "basketball":        {"name": "🏀 كرة السلة",               "flag": "🏀"},
    "tennis":            {"name": "🎾 التنس",                   "flag": "🎾"},
    "racing":            {"name": "🏎️ فورمولا 1 / سيارات",      "flag": "🏎️"},
    "hockey":            {"name": "🏒 هوكي الجليد (NHL)",        "flag": "🏒"},
    "baseball":          {"name": "⚾ البيسبول (MLB)",           "flag": "⚾"},
    "american_football": {"name": "🏈 كرة القدم الأمريكية (NFL)","flag": "🏈"},
    "golf":              {"name": "⛳ الغولف",                   "flag": "⛳"},
    "cricket":           {"name": "🏏 الكريكيت",               "flag": "🏏"},
    "handball":          {"name": "🤾 كرة اليد",               "flag": "🤾"},
    "esports":           {"name": "🎮 رياضات إلكترونية",        "flag": "🎮"},
}

# كاش الفرق (league_key → list of teams)
_teams_cache = {}

def _get_league_teams(espn_slug: str) -> list:
    """جلب فرق الدوري من ESPN"""
    if espn_slug in _teams_cache:
        return _teams_cache[espn_slug]
    try:
        sport, league = espn_slug.split('/', 1)
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams?limit=50"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        sports_data = r.json().get('sports', [])
        if not sports_data:
            return []
        leagues_data = sports_data[0].get('leagues', [])
        if not leagues_data:
            return []
        teams = []
        for t in leagues_data[0].get('teams', []):
            team = t.get('team', {})
            teams.append({
                'id': str(team.get('id', '')),
                'name': team.get('displayName', team.get('name', '?')),
                'short': team.get('abbreviation', ''),
            })
        _teams_cache[espn_slug] = teams
        return teams
    except Exception:
        return []

# ─────────────────────────────────────────────────────────────────────
# نظام متابعة المباريات الكاملة — مثل 365Score
# ─────────────────────────────────────────────────────────────────────

def _get_upcoming_fixtures(espn_slug: str, days: int = 2) -> list:
    """يجلب المباريات القادمة من ESPN للأيام القادمة"""
    try:
        sport, league = espn_slug.split('/', 1)
        fixtures = []
        today = datetime.date.today()
        for i in range(days + 1):
            date_str = (today + datetime.timedelta(days=i)).strftime('%Y%m%d')
            url = (f"https://site.api.espn.com/apis/site/v2/sports"
                   f"/{sport}/{league}/scoreboard?dates={date_str}")
            try:
                r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    continue
                for event in r.json().get('events', []):
                    comp = event.get('competitions', [{}])[0]
                    state = comp.get('status', {}).get('type', {}).get('state', '')
                    competitors = comp.get('competitors', [])
                    if len(competitors) < 2:
                        continue
                    home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                    away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
                    fixtures.append({
                        'id':        event.get('id', ''),
                        'name':      event.get('name', ''),
                        'date':      event.get('date', ''),
                        'state':     state,
                        'home':      home.get('team', {}).get('displayName', '?'),
                        'away':      away.get('team', {}).get('displayName', '?'),
                        'home_id':   str(home.get('team', {}).get('id', '')),
                        'away_id':   str(away.get('team', {}).get('id', '')),
                        'home_abbr': home.get('team', {}).get('abbreviation', '?'),
                        'away_abbr': away.get('team', {}).get('abbreviation', '?'),
                        'venue':     comp.get('venue', {}).get('fullName', ''),
                    })
            except Exception:
                pass
        return fixtures
    except Exception:
        return []


def _get_match_play_by_play(espn_slug: str, event_id: str) -> list:
    """
    يجلب أحداث المباراة التفصيلية (play-by-play) من ESPN summary API.
    يُعيد قائمة أحداث: [{id, type, clock, period, player, home_score, away_score, text, team_id}]
    """
    try:
        sport, league = espn_slug.split('/', 1)
        url = (f"https://site.api.espn.com/apis/site/v2/sports"
               f"/{sport}/{league}/summary?event={event_id}")
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        data = r.json()
        plays = []

        # ── ملعب كرة القدم والأمريكية وباقي الرياضات ──
        for play in data.get('plays', []):
            play_type_obj = play.get('type', {})
            play_type = play_type_obj.get('text', '') or play_type_obj.get('name', '')
            clock_obj = play.get('clock', {})
            clock = clock_obj.get('displayValue', '') if isinstance(clock_obj, dict) else str(clock_obj)
            period = play.get('period', {})
            period_num = period.get('number', 0) if isinstance(period, dict) else period
            participants = play.get('participants', [])
            player = ''
            team_id = ''
            if participants:
                p0 = participants[0]
                athlete = p0.get('athlete', {})
                player = athlete.get('displayName', '')
                team_id = str(p0.get('team', {}).get('id', ''))
            plays.append({
                'id':         str(play.get('id', '')),
                'type':       play_type,
                'clock':      clock,
                'period':     period_num,
                'player':     player,
                'team_id':    team_id,
                'home_score': str(play.get('homeScore', '')),
                'away_score': str(play.get('awayScore', '')),
                'text':       play.get('text', ''),
            })

        # ── تنس وغولف: drives/holes/sets ──
        for hole in data.get('holes', []):
            plays.append({
                'id':      str(hole.get('id', hole.get('number', ''))),
                'type':    'Hole',
                'clock':   str(hole.get('number', '')),
                'period':  hole.get('number', 0),
                'player':  '',
                'team_id': '',
                'home_score': '',
                'away_score': '',
                'text':    hole.get('description', ''),
            })

        return plays
    except Exception:
        return []


def _event_to_emoji(ev_type: str, sport: str) -> str:
    """إيموجي مناسب لكل نوع حدث حسب الرياضة"""
    et = ev_type.lower()
    if sport == 'football':
        if any(k in et for k in ('goal', 'score')): return '⚽'
        if 'red card' in et or 'red' in et:         return '🟥'
        if 'yellow' in et or 'card' in et:          return '🟨'
        if 'penalty' in et or 'pen' in et:          return '🎯'
        if 'substitut' in et or 'sub' in et:        return '🔄'
        if 'offside' in et:                          return '🚩'
        if 'var' in et:                              return '📺'
        if 'half' in et or 'break' in et:           return '⏸'
        if 'corner' in et:                           return '🔵'
        if 'foul' in et:                             return '⚠️'
        if 'miss' in et or 'attempt' in et:         return '💨'
        if 'save' in et:                             return '🧤'
        if 'injury' in et:                           return '🏥'
    elif sport == 'basketball':
        if any(k in et for k in ('made', 'basket', '3pt', 'free throw')): return '🏀'
        if 'foul' in et:                             return '⚠️'
        if 'timeout' in et:                          return '⏸'
        if 'steal' in et:                            return '🤚'
        if 'block' in et:                            return '🛡'
    elif sport == 'tennis':
        if 'ace' in et:                              return '🎯'
        if 'set' in et:                              return '🎾'
        if 'double fault' in et:                    return '❌'
        if 'break' in et:                            return '💥'
    elif sport == 'racing':
        if 'pit' in et:                              return '🔧'
        if 'lead' in et or 'overtake' in et:        return '🏎️'
        if 'crash' in et or 'retire' in et:         return '💥'
        if 'safety car' in et:                      return '🚗'
        if 'podium' in et or 'finish' in et:        return '🏆'
    elif sport == 'hockey':
        if any(k in et for k in ('goal', 'score')): return '🏒'
        if 'penalty' in et:                          return '⏸'
    elif sport == 'baseball':
        if 'home run' in et:                         return '💣'
        if 'hit' in et:                              return '⚾'
        if 'strikeout' in et:                        return '❌'
    elif sport == 'american_football':
        if 'touchdown' in et:                        return '🏈'
        if 'field goal' in et:                       return '🎯'
        if 'interception' in et:                     return '🤚'
        if 'sack' in et:                             return '💥'
    return '•'


# ─── قفل + تتبع إشعارات ما قبل المباراة ───────────────────────────
_prematch_lock = threading.Event()
_prematch_lock_ts = [0.0]

def _prematch_watchdog():
    while True:
        time.sleep(60)
        try:
            if _prematch_lock.is_set() and time.time() - _prematch_lock_ts[0] > 120:
                _prematch_lock.clear()
        except Exception:
            pass
threading.Thread(target=_prematch_watchdog, daemon=True, name="prematch_watchdog").start()


def _parse_espn_date(date_str: str):
    """يحول تاريخ ESPN إلى datetime UTC"""
    for fmt in ('%Y-%m-%dT%H:%MZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.datetime.strptime(date_str[:len(fmt)].replace('Z',''), fmt.replace('Z',''))
        except Exception:
            pass
    try:
        return datetime.datetime.fromisoformat(date_str.replace('Z', ''))
    except Exception:
        return None


def _prematch_notifier():
    """
    يرسل إشعارات مسبقة للمستخدمين:
    • قبل يوم كامل (20-28 ساعة)
    • قبل 45 دقيقة (30-65 دقيقة)
    يعمل كل 15 دقيقة بواسطة المجدول.
    """
    if _prematch_lock.is_set():
        return
    _prematch_lock.set()
    _prematch_lock_ts[0] = time.time()
    try:
        now_utc = datetime.datetime.utcnow()

        # ── جمع اشتراكات المستخدمين ─────────────────────────────────
        # league_key → {team_id → [(uid_s, lang)]}
        league_team_users = {}
        for uid_s, info in list(users.items()):
            prefs = info.get('sports', {})
            if not prefs.get('live_alerts'):
                continue
            lang = info.get('lang', 'العربية 🇮🇶')
            for lk in prefs.get('leagues', []):
                team_ids = list(prefs.get('teams', {}).get(lk, []))
                entry = league_team_users.setdefault(lk, {})
                if team_ids:
                    for tid in team_ids:
                        entry.setdefault(tid, []).append((uid_s, lang))
                else:
                    entry.setdefault('__all__', []).append((uid_s, lang))

        if not league_team_users:
            return

        # ── جلب المباريات وإرسال الإشعارات ──────────────────────────
        for league_key, team_users in league_team_users.items():
            league = SPORTS_LEAGUES.get(league_key)
            if not league or not league.get('espn'):
                continue
            espn      = league['espn']
            flag      = league.get('flag', '🏅')
            lname     = league.get('name', league_key)
            sport     = league.get('sport', 'football')

            try:
                fixtures = _get_upcoming_fixtures(espn, days=2)
            except Exception:
                continue

            for fix in fixtures:
                if fix['state'] not in ('pre',):
                    continue
                match_id  = fix['id']
                if not match_id:
                    continue
                match_dt  = _parse_espn_date(fix['date'])
                if not match_dt:
                    continue
                delta_sec = (match_dt - now_utc).total_seconds()

                is_day_before = 20 * 3600 <= delta_sec <= 28 * 3600
                is_pre45      = 25 * 60   <= delta_sec <= 65 * 60

                if not (is_day_before or is_pre45):
                    continue

                # وقت المباراة بالتوقيت المحلي (+3 بغداد)
                local_dt     = match_dt + datetime.timedelta(hours=3)
                time_str_utc = match_dt.strftime('%H:%M')
                time_str_loc = local_dt.strftime('%H:%M')
                date_str     = local_dt.strftime('%d/%m/%Y')

                home_id = fix['home_id']
                away_id = fix['away_id']

                # تحديد المستخدمين المعنيين
                interested: list[tuple[str, str]] = []
                for tid, ulist in team_users.items():
                    if tid == '__all__' or tid in (home_id, away_id):
                        interested.extend(ulist)
                seen_uids = set()
                unique_interested = []
                for uid_s, lang in interested:
                    if uid_s not in seen_uids:
                        seen_uids.add(uid_s)
                        unique_interested.append((uid_s, lang))

                for uid_s, lang in unique_interested:
                    info      = users.get(uid_s, {})
                    notified  = info.setdefault('notified_matches', {})
                    nm        = notified.setdefault(match_id, {})

                    if is_day_before and not nm.get('day'):
                        sport_emoji = {'football':'⚽','basketball':'🏀','tennis':'🎾',
                            'racing':'🏎️','hockey':'🏒','baseball':'⚾',
                            'american_football':'🏈','golf':'⛳','cricket':'🏏'}.get(sport,'🏅')
                        msg = (
                            f"📅 *مباراة غداً!*\n"
                            f"{flag} *{lname}*\n\n"
                            f"{sport_emoji} *{fix['home']}*\n"
                            f"🆚\n"
                            f"{sport_emoji} *{fix['away']}*\n\n"
                            f"⏰ الموعد: `{time_str_loc}` (بغداد) — {date_str}\n"
                            f"🔔 ستصلك تنبيهات تلقائية لكل أحداث المباراة"
                        )
                        try:
                            bot.send_message(int(uid_s), msg, parse_mode="Markdown")
                            # إصلاح #9: حفظ timestamp مع الإشعار لتنظيف صحيح لاحقاً
                            nm['day'] = True
                            nm['ts']  = datetime.datetime.utcnow().timestamp()
                        except Exception:
                            pass

                    elif is_pre45 and not nm.get('pre45'):
                        venue = f"\n🏟 {fix['venue']}" if fix.get('venue') else ''
                        # إصلاح #11: توقيت المنطقة حسب لغة المستخدم
                        tz_offsets = {
                            'العربية 🇮🇶': 3, 'العربية السعودية 🇸🇦': 3,
                            'العربية المصرية 🇪🇬': 2, 'العربية السورية 🇸🇾': 3,
                            'العربية الكويتية 🇰🇼': 3, 'العربية الإماراتية 🇦🇪': 4,
                            'English 🇬🇧': 0, 'Français 🇫🇷': 1,
                        }
                        tz_off    = tz_offsets.get(lang, 3)
                        local_dt_ = match_dt + datetime.timedelta(hours=tz_off)
                        time_str_user = local_dt_.strftime('%H:%M')
                        msg = (
                            f"⏳ *بعد أقل من ساعة!*\n"
                            f"{flag} *{lname}*\n\n"
                            f"🏠 *{fix['home']}*\n"
                            f"🆚\n"
                            f"✈️ *{fix['away']}*\n\n"
                            f"⏰ `{time_str_user}` (توقيتك){venue}\n"
                            f"🔴 يبدأ التتبع المباشر فور الانطلاق"
                        )
                        try:
                            bot.send_message(int(uid_s), msg, parse_mode="Markdown")
                            nm['pre45'] = True
                            nm['ts']    = datetime.datetime.utcnow().timestamp()
                        except Exception:
                            pass

        # إصلاح #7: تنظيف الإشعارات القديمة (+48h) بحذف الإدخالات الفردية لا الكل
        now_utc_ts = datetime.datetime.utcnow().timestamp()
        for uid_s, info in list(users.items()):
            nm_dict = info.get('notified_matches', {})
            if len(nm_dict) > 100:
                # احذف المباريات التي مضى عليها أكثر من 48 ساعة
                old_keys = [
                    mid for mid, v in nm_dict.items()
                    if isinstance(v, dict) and v.get('ts', now_utc_ts) < now_utc_ts - 172800
                ]
                if old_keys:
                    for k in old_keys:
                        nm_dict.pop(k, None)
                elif len(nm_dict) > 300:
                    # fallback: إذا لم تحمل timestamps احذف الأقدم نصف
                    old_keys = list(nm_dict.keys())[:len(nm_dict)//2]
                    for k in old_keys:
                        nm_dict.pop(k, None)

    except Exception:
        pass
    finally:
        _prematch_lock.clear()


def _sports_main_keyboard(uid):
    prefs = _get_user_sports(uid)
    alerts_icon = "🔔" if prefs.get('live_alerts') else "🔕"
    sel_leagues = len(prefs.get('leagues', []))
    sel_teams   = sum(len(v) for v in prefs.get('teams', {}).values())
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔴 نتائج مباشرة", callback_data="sp_live"),
        types.InlineKeyboardButton("📅 جدول المباريات", callback_data="sp_schedule"),
    )
    kb.add(
        types.InlineKeyboardButton(f"🏅 اختر رياضتك ({sel_leagues} دوري، {sel_teams} فريق)", callback_data="sp_sports"),
    )
    kb.add(
        types.InlineKeyboardButton("📰 أخبار رياضية", callback_data="sp_news"),
        types.InlineKeyboardButton(f"{alerts_icon} تنبيهات", callback_data="sp_toggle_alerts"),
    )
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
    return kb

def _sport_categories_keyboard():
    """قائمة تصنيفات الرياضة"""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for cat_key, cat in SPORT_CATEGORIES.items():
        kb.add(types.InlineKeyboardButton(f"{cat['flag']} {cat['name']}", callback_data=f"sp_sport_{cat_key}"))
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_main"))
    return kb

def _leagues_by_sport_keyboard(uid, sport_key: str, page=0):
    """دوريات مفلترة حسب الرياضة"""
    prefs = _get_user_sports(uid)
    sel_leagues = set(prefs.get('leagues', []))
    keys = [k for k, v in SPORTS_LEAGUES.items() if v.get('sport') == sport_key]
    per_page = 6
    start = page * per_page
    chunk = keys[start:start + per_page]
    kb = types.InlineKeyboardMarkup(row_width=1)
    for key in chunk:
        league = SPORTS_LEAGUES[key]
        icon = "✅ " if key in sel_leagues else ""
        league_display = league['name'].replace('⚽ ','').replace('🏀 ','').replace('🏎️ ','')
        kb.add(types.InlineKeyboardButton(
            f"{icon}{league['flag']} {league_display}",
            # إصلاح #6: نُضيف رقم الصفحة الحالية لحفظها عند toggle
            callback_data=f"sp_tog_{key}_s{sport_key}_p{page}"
        ))
        if league.get('espn'):
            kb.add(types.InlineKeyboardButton(
                f"   👕 اختر فريق من {league_display}",
                callback_data=f"sp_tms_{key}_p0"
            ))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"sp_sport_{sport_key}_p{page-1}"))
    if start + per_page < len(keys):
        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"sp_sport_{sport_key}_p{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_sports"))
    return kb

def _teams_keyboard(uid, league_key: str, page=0):
    """قائمة فرق الدوري مع اختيار المستخدم"""
    prefs = _get_user_sports(uid)
    user_teams = prefs.get('teams', {})
    sel_teams = set(user_teams.get(league_key, []))
    league = SPORTS_LEAGUES.get(league_key, {})
    espn = league.get('espn')
    if not espn:
        return None
    teams = _get_league_teams(espn)
    if not teams:
        return None
    per_page = 8
    start = page * per_page
    chunk = teams[start:start + per_page]
    league_display = league.get('name','').replace('⚽ ','').replace('🏀 ','').replace('🏎️ ','')
    kb = types.InlineKeyboardMarkup(row_width=2)
    row = []
    for team in chunk:
        icon = "✅" if team['id'] in sel_teams else "○"
        btn = types.InlineKeyboardButton(f"{icon} {team['name']}", callback_data=f"sp_tm_{league_key}_{team['id']}")
        row.append(btn)
        if len(row) == 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"sp_tms_{league_key}_p{page-1}"))
    if start + per_page < len(teams):
        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"sp_tms_{league_key}_p{page+1}"))
    if nav:
        kb.row(*nav)
    sport_key = league.get('sport', 'football')
    kb.add(types.InlineKeyboardButton(f"🔙 رجوع للدوريات", callback_data=f"sp_sport_{sport_key}"))
    return kb

def _sports_leagues_keyboard(uid, page=0):
    """قائمة كل الدوريات (للتوافق القديم)"""
    prefs = _get_user_sports(uid)
    selected = set(prefs.get('leagues', []))
    keys = list(SPORTS_LEAGUES.keys())
    per_page = 8
    start = page * per_page
    chunk = keys[start:start + per_page]
    kb = types.InlineKeyboardMarkup(row_width=1)
    for key in chunk:
        league = SPORTS_LEAGUES[key]
        icon = "✅ " if key in selected else ""
        kb.add(types.InlineKeyboardButton(f"{icon}{league['flag']} {league['name'].replace('⚽ ','').replace('🏀 ','').replace('🏎️ ','')}", callback_data=f"sp_tog_{key}_s{league.get('sport','')}"))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️ السابق", callback_data=f"sp_leagues_p{page-1}"))
    if start + per_page < len(keys):
        nav.append(types.InlineKeyboardButton("التالي ▶️", callback_data=f"sp_leagues_p{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_sports"))
    return kb

def _get_user_tz_offset(uid) -> int:
    """إصلاح #11: يُعيد offset المنطقة الزمنية بالساعات حسب لغة المستخدم"""
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶') or 'العربية 🇮🇶'
    return {
        'العربية 🇮🇶': 3, 'العربية السعودية 🇸🇦': 3, 'العربية الكويتية 🇰🇼': 3,
        'العربية السورية 🇸🇾': 3, 'العربية اليمنية 🇾🇪': 3, 'العربية الأردنية 🇯🇴': 3,
        'العربية المصرية 🇪🇬': 2, 'العربية الليبية 🇱🇾': 2, 'العربية التونسية 🇹🇳': 1,
        'العربية الجزائرية 🇩🇿': 1, 'العربية المغربية 🇲🇦': 1,
        'العربية الإماراتية 🇦🇪': 4, 'العربية البحرينية 🇧🇭': 3, 'العربية القطرية 🇶🇦': 3,
        'English 🇬🇧': 0, 'Français 🇫🇷': 1, 'Deutsch 🇩🇪': 1,
        'Español 🇪🇸': 1, 'Türkçe 🇹🇷': 3, 'فارسی 🇮🇷': 3,
    }.get(lang, 3)

def _send_live_scores(uid, chat_id, msg_id=None):
    """
    إصلاح #2: يُظهر رسالة واضحة للدوريات بلا ESPN (كالدوري العراقي)
    بدلاً من تجاهلها.
    إصلاح #11: يُمرر tz_offset حسب لغة المستخدم.
    """
    prefs       = _get_user_sports(uid)
    selected    = prefs.get('leagues', [])
    tz_offset   = _get_user_tz_offset(uid)
    lang        = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')

    if not selected:
        text = "⚽ *النتائج المباشرة*\n\nاختر دورياتك أولاً من قائمة ⚽ اختر دورياتك"
    else:
        text = "🔴 *النتائج المباشرة*\n\n"
        found_any = False
        for key in selected:
            league = SPORTS_LEAGUES.get(key)
            if not league:
                continue
            sport = league.get('sport', 'football')
            # إصلاح #2: دوريات بلا ESPN → رسالة توضيحية
            if not league.get('espn'):
                text += f"{league['flag']} *{league['name']}*\n"
                text += "  ⚠️ النتائج المباشرة غير متاحة لهذا الدوري\n\n"
                found_any = True
                continue
            matches   = _get_live_scores(league['espn'])
            live      = [m for m in matches if m['state'] == 'in']
            recent    = [m for m in matches if m['state'] == 'post'][:3]
            if not live and not recent:
                continue
            found_any = True
            text += f"{league['flag']} *{league['name']}*\n"
            for m in live:
                text += f"  {_format_match_line(m, sport, tz_offset)}\n"
            if not live:
                for m in recent:
                    text += f"  {_format_match_line(m, sport, tz_offset)}\n"
            text += "\n"
        if not found_any:
            text += "لا توجد مباريات مباشرة الآن في دورياتك المختارة 📭\n\nاضغط 📅 جدول المباريات لرؤية القادمة"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔄 تحديث", callback_data="sp_live"),
        types.InlineKeyboardButton("📅 الجدول", callback_data="sp_schedule"),
    )
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_main"))
    try:
        if msg_id:
            bot.edit_message_text(text[:4096], chat_id, msg_id, parse_mode="Markdown", reply_markup=kb)
        else:
            bot.send_message(chat_id, text[:4096], parse_mode="Markdown", reply_markup=kb)
    except Exception:
        bot.send_message(chat_id, text[:4096], parse_mode="Markdown", reply_markup=kb)

def _send_schedule(uid, chat_id, msg_id=None):
    """
    إصلاح #2: يُظهر رسالة للدوريات بلا ESPN بدل تجاهلها.
    إصلاح #8: يستخدم _get_upcoming_fixtures بدل _get_live_scores لجلب المباريات القادمة.
    إصلاح #11: يُمرر tz_offset حسب لغة المستخدم.
    """
    prefs     = _get_user_sports(uid)
    selected  = prefs.get('leagues', [])
    tz_offset = _get_user_tz_offset(uid)

    if not selected:
        text = "📅 *جدول المباريات*\n\nاختر دورياتك أولاً من قائمة ⚽ اختر دورياتك"
    else:
        text = "📅 *جدول المباريات القادمة*\n\n"
        found_any = False
        for key in selected:
            league = SPORTS_LEAGUES.get(key)
            if not league:
                continue
            sport = league.get('sport', 'football')
            # إصلاح #2: الدوري العراقي وما شابهه ← رسالة توضيحية
            if not league.get('espn'):
                text += f"{league['flag']} *{league['name']}*\n"
                text += "  ⚠️ الجدول غير متاح لهذا الدوري حالياً\n\n"
                found_any = True
                continue
            # إصلاح #8: اجلب الجدول القادم مباشرة من ESPN
            all_matches = _get_live_scores(league['espn'])
            upcoming    = [m for m in all_matches if m['state'] == 'pre'][:5]
            if not upcoming:
                continue
            found_any = True
            text += f"{league['flag']} *{league['name']}*\n"
            for m in upcoming:
                text += f"  {_format_match_line(m, sport, tz_offset)}\n"
            text += "\n"
        if not found_any:
            text += "لا توجد مباريات قادمة في دورياتك المختارة 📭"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔄 تحديث", callback_data="sp_schedule"),
        types.InlineKeyboardButton("🔴 مباشر", callback_data="sp_live"),
    )
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_main"))
    try:
        if msg_id:
            bot.edit_message_text(text[:4096], chat_id, msg_id, parse_mode="Markdown", reply_markup=kb)
        else:
            bot.send_message(chat_id, text[:4096], parse_mode="Markdown", reply_markup=kb)
    except Exception:
        bot.send_message(chat_id, text[:4096], parse_mode="Markdown", reply_markup=kb)

def _send_sports_news(uid, chat_id, msg_id=None):
    """
    إصلاح #6: يستخدم SPORTS_RSS (dict بلغات، 14+ مصدر)
    بدلاً من SPORTS_NEWS_RSS (4 مصادر فقط).
    """
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
    # إصلاح #6: ابحث عن المصادر المناسبة للغة في SPORTS_RSS (dict)
    filtered_feeds = SPORTS_RSS.get(lang) or SPORTS_RSS.get('العربية 🇮🇶', [])

    items = []
    seen_titles = set()
    for feed_url in filtered_feeds:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:5]:
                title = getattr(entry, 'title', '').strip()
                link  = getattr(entry, 'link', '').strip()
                key   = title[:40].lower()
                if title and link and key not in seen_titles:
                    seen_titles.add(key)
                    items.append((title, link))
            if len(items) >= 15:
                break
        except Exception:
            pass

    if not items:
        text = "📰 *أخبار رياضية*\n\nلا توجد أخبار الآن، حاول لاحقاً."
    else:
        text = "📰 *آخر الأخبار الرياضية*\n\n"
        for i, (title, link) in enumerate(items[:12], 1):
            text += f"{i}. [{title}]({link})\n\n"

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🔄 تحديث", callback_data="sp_news"),
        types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_main"),
    )
    try:
        if msg_id:
            bot.edit_message_text(text[:4096], chat_id, msg_id, parse_mode="Markdown",
                                  reply_markup=kb, disable_web_page_preview=True)
        else:
            bot.send_message(chat_id, text[:4096], parse_mode="Markdown",
                             reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        bot.send_message(chat_id, text[:4096], parse_mode="Markdown",
                         reply_markup=kb, disable_web_page_preview=True)

# كاش الأحداث الرياضية: match_id → {state, home_score, away_score, known_events: set}
_sports_match_cache = {}

def _load_sports_cache():
    """
    تحميل كاش المباريات من الملف عند بدء التشغيل.
    إصلاح: يدعم كلاً من الصيغة القديمة (known_events)
    والصيغة الجديدة (known_ev_ids + known_pbp_ids).
    """
    global _sports_match_cache
    try:
        with open(_SPORTS_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for mid, data in raw.items():
            # دعم الصيغة القديمة: known_events → known_ev_ids
            if 'known_events' in data and 'known_ev_ids' not in data:
                data['known_ev_ids']  = set(data.pop('known_events', []))
                data['known_pbp_ids'] = set()
            else:
                data['known_ev_ids']  = set(data.get('known_ev_ids',  []))
                data['known_pbp_ids'] = set(data.get('known_pbp_ids', []))
        _sports_match_cache = raw
    except Exception:
        _sports_match_cache = {}

def _save_sports_cache():
    """
    حفظ كاش المباريات في ملف.
    إصلاح: يحفظ known_ev_ids + known_pbp_ids بدلاً من known_events.
    """
    try:
        save_data = {}
        for mid, data in _sports_match_cache.items():
            # لا نحفظ المباريات المنتهية منذ أكثر من 30 دقيقة لتوفير المساحة
            if data.get('state') == 'post':
                ts = data.get('ended_at', 0)
                if ts and (time.time() - ts) > 1800:
                    continue
            save_data[mid] = {
                'state':         data.get('state', ''),
                'home_score':    data.get('home_score', '-'),
                'away_score':    data.get('away_score', '-'),
                'home_id':       data.get('home_id', ''),
                'away_id':       data.get('away_id', ''),
                'ended_at':      data.get('ended_at', 0),
                'known_ev_ids':  list(data.get('known_ev_ids',  set())),
                'known_pbp_ids': list(data.get('known_pbp_ids', set())),
            }
        with open(_SPORTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False)
    except Exception:
        pass

_load_sports_cache()      # تحميل عند بدء التشغيل
_sports_broadcaster_lock = threading.Event()  # Event بدلاً من Lock لدعم الـ watchdog
_sports_lock_ts = [0.0]

def _sports_watchdog():
    """
    إصلاح #3: رفع timeout من 60s → 180s لأن البث قد يستغرق أكثر من دقيقة
    عند وجود عدة دوريات ومباريات حية تتطلب play-by-play.
    """
    while True:
        time.sleep(30)
        try:
            if _sports_broadcaster_lock.is_set() and time.time() - _sports_lock_ts[0] > 180:
                _sports_broadcaster_lock.clear()
        except Exception:
            pass
threading.Thread(target=_sports_watchdog, daemon=True, name="sports_watchdog").start()

def _sports_live_broadcaster():
    """
    بث رياضي مباشر مثل 365Score:
    ─ يكشف كل أحداث المباراة فور حدوثها (أهداف، بطاقات، جزاء، استبدال، نهاية...)
    ─ يفلتر حسب فريق المستخدم (إذا اختار فريقاً) أو الدوري كله
    ─ يستخدم ESPN play-by-play للأحداث التفصيلية
    ─ يعمل كل 10 ثواني لضمان أدنى تأخير ممكن
    """
    global _sports_match_cache
    if _sports_broadcaster_lock.is_set():
        return
    _sports_broadcaster_lock.set()
    _sports_lock_ts[0] = time.time()
    try:
        # ── 1. تجميع اشتراكات المستخدمين ─────────────────────────────
        # league_key → set of team_ids (أو '__all__' إذا اشترك بالدوري كله)
        league_team_map = {}   # league_key → {team_id → [(uid_s, lang)]}
        for uid_s, info in list(users.items()):
            prefs = info.get('sports', {})
            if not prefs.get('live_alerts'):
                continue
            lang = info.get('lang', 'العربية 🇮🇶')
            for lk in prefs.get('leagues', []):
                team_ids = list(prefs.get('teams', {}).get(lk, []))
                entry = league_team_map.setdefault(lk, {})
                if team_ids:
                    for tid in team_ids:
                        entry.setdefault(tid, []).append((uid_s, lang))
                else:
                    entry.setdefault('__all__', []).append((uid_s, lang))

        if not league_team_map:
            return

        # ── 2. جلب نتائج ESPN لكل دوري مطلوب ──────────────────────────
        fresh_matches = {}   # league_key → list of matches
        for key in league_team_map:
            league = SPORTS_LEAGUES.get(key)
            if not league or not league.get('espn'):
                continue
            try:
                matches = _get_live_scores(league['espn'])
                if matches:
                    fresh_matches[key] = matches
            except Exception:
                pass

        if not fresh_matches:
            return

        # ── 3. جلب play-by-play للمباريات الحية ───────────────────────
        # نحصل على أحداث تفصيلية من ESPN summary API
        pbp_events = {}  # match_id → [play_events]
        for key, matches in fresh_matches.items():
            league = SPORTS_LEAGUES.get(key, {})
            espn   = league.get('espn', '')
            if not espn:
                continue
            for m in matches:
                if m.get('state') != 'in':
                    continue
                mid = m.get('id', '')
                if mid and mid not in pbp_events:
                    try:
                        plays = _get_match_play_by_play(espn, mid)
                        if plays:
                            pbp_events[mid] = plays
                    except Exception:
                        pass

        # ── 4. كشف الأحداث الجديدة لكل مباراة ─────────────────────────
        # match_id → (league_key, list of alert strings, home_id, away_id)
        match_alerts = {}

        _SPORT_START = {'football':'🟢','basketball':'🟢','tennis':'🎾','racing':'🏁',
                        'hockey':'🏒','baseball':'⚾','american_football':'🏈','golf':'⛳','cricket':'🏏'}
        _SPORT_SCORE = {'football':'⚽','basketball':'🏀','tennis':'🎾','racing':'🏎️',
                        'hockey':'🏒','baseball':'⚾','american_football':'🏈','golf':'⛳','cricket':'🏏'}
        _SPORT_END   = {'football':'انتهت المباراة','basketball':'انتهت المباراة',
                        'tennis':'انتهت المباراة','racing':'انتهى السباق ✅',
                        'hockey':'انتهت المباراة','baseball':'انتهت المباراة',
                        'american_football':'انتهت المباراة','golf':'انتهت البطولة','cricket':'انتهت المباراة'}
        _SPORT_LABEL = {'football':'هدف جديد!','basketball':'سلة!','tennis':'نقطة!',
                        'racing':'تغيّر الترتيب!','hockey':'هدف!','baseball':'ران جديد!',
                        'american_football':'Touchdown!','golf':'تغيّر الترتيب!','cricket':'ران!'}

        for key, matches in fresh_matches.items():
            league     = SPORTS_LEAGUES.get(key, {})
            lname      = league.get('name', key)
            flag       = league.get('flag', '🏅')
            sport_type = league.get('sport', 'football')
            espn       = league.get('espn', '')

            s_start = _SPORT_START.get(sport_type, '🟢')
            s_score = _SPORT_SCORE.get(sport_type, '🏅')
            s_end   = _SPORT_END.get(sport_type, 'انتهى')
            s_label = _SPORT_LABEL.get(sport_type, 'حدث جديد!')

            for m in matches:
                match_id = m.get('id') or m.get('name', '')
                if not match_id:
                    continue

                prev          = _sports_match_cache.get(match_id, {})
                prev_state    = prev.get('state', '')
                prev_home     = prev.get('home_score', '-')
                prev_away     = prev.get('away_score', '-')
                prev_ev_ids   = prev.get('known_ev_ids', set())
                prev_pbp_ids  = prev.get('known_pbp_ids', set())

                curr_state    = m.get('state', '')
                curr_home     = m.get('home_score', '-')
                curr_away     = m.get('away_score', '-')
                home_id       = str(m.get('home_id', '')) if 'home_id' in m else ''
                away_id       = str(m.get('away_id', '')) if 'away_id' in m else ''

                # جمع home/away team ids من بيانات scoreboard
                comp_teams = {}  # team_name → team_id (نملأها من الأحداث)

                clock_str = f" ⏱{m['clock']}" if m.get('clock') else ''
                alerts    = []

                # ① انطلاق المباراة
                if curr_state == 'in' and prev_state not in ('in',):
                    alerts.append(
                        f"{s_start} *انطلقت المباراة الآن!*\n"
                        f"{flag} *{lname}*\n\n"
                        f"🏠 *{m['home']}*  🆚  ✈️ *{m['away']}*\n"
                        f"🔴 التتبع المباشر بدأ — سيصلك كل حدث فور وقوعه"
                    )
                    # إرسال إشعار "بدأت" لمن لم يُخطر بـ pre45
                    notif_alert = (match_id, 'start')

                # ② نهاية المباراة
                if curr_state == 'post' and prev_state == 'in':
                    sc = f"`{curr_home} - {curr_away}`" if curr_home != '-' else ''
                    alerts.append(
                        f"🏆 *{s_end}*\n"
                        f"{flag} *{lname}*\n\n"
                        f"🏠 *{m['home']}*  {sc}  *{m['away']}* ✈️\n"
                        f"⚡ النتيجة النهائية"
                    )

                # ③ أحداث scoreboard (details) الجديدة
                sc_events_raw = m.get('events', [])
                sc_event_ids  = {ev.get('display', '') for ev in sc_events_raw if ev.get('display')}
                new_sc_ids    = sc_event_ids - prev_ev_ids
                if new_sc_ids and curr_state == 'in':
                    new_sc_evs = [ev for ev in sc_events_raw if ev.get('display','') in new_sc_ids]
                    sc_str = f"`{curr_home}-{curr_away}`" if curr_home != '-' else ''
                    evs_text = "\n".join(f"  {ev['display']}" for ev in new_sc_evs)
                    alerts.append(
                        f"{s_score} *{s_label}*\n"
                        f"{flag} *{lname}*\n"
                        f"🏠 *{m['home']}* {sc_str} *{m['away']}* ✈️{clock_str}\n"
                        f"{evs_text}"
                    )

                # ④ أحداث play-by-play التفصيلية (أهداف، بطاقات، استبدال...)
                pbp_plays     = pbp_events.get(match_id, [])
                new_pbp_plays = [p for p in pbp_plays if p['id'] and p['id'] not in prev_pbp_ids]
                new_pbp_ids   = {p['id'] for p in new_pbp_plays}
                for play in new_pbp_plays:
                    ptype  = play.get('type', '')
                    if not ptype:
                        continue
                    # فلترة الأحداث التافهة
                    pt_low = ptype.lower()
                    trivial = ('kick off', 'throw in', 'goal kick', 'gk', 'clearance',
                               'pass', 'dribble', 'cross', 'reception', 'rush', 'tackle')
                    if any(t in pt_low for t in trivial):
                        continue
                    emoji  = _event_to_emoji(ptype, sport_type)
                    if emoji == '•':   # حدث عادي بدون إيموجي خاص — تجاهله
                        continue
                    clock  = play.get('clock', '')
                    player = play.get('player', '')
                    hs     = play.get('home_score', '')
                    as_    = play.get('away_score', '')
                    sc_part   = f" `{hs}-{as_}`" if hs and as_ else ''
                    clk_part  = f" {clock}'" if clock else ''
                    plyr_part = f" *{player}*" if player else ''
                    period_p  = play.get('period', '')
                    per_part  = f" (ش{period_p})" if period_p and sport_type in ('football','hockey','basketball','american_football') else ''
                    alerts.append(
                        f"{emoji} *{ptype}*{plyr_part}{clk_part}{per_part}\n"
                        f"{flag} *{lname}*\n"
                        f"🏠 *{m['home']}*{sc_part} *{m['away']}* ✈️"
                    )

                # ⑤ تغير النتيجة بدون حدث مسجل (fallback)
                if (curr_state == 'in' and prev_state == 'in'
                        and (curr_home != prev_home or curr_away != prev_away)
                        and not new_sc_ids and not new_pbp_ids):
                    sc_str = f"`{curr_home}-{curr_away}`" if curr_home != '-' else ''
                    alerts.append(
                        f"{s_score} *{s_label}*\n"
                        f"{flag} *{lname}*\n"
                        f"🏠 *{m['home']}* {sc_str} *{m['away']}* ✈️{clock_str}"
                    )

                if alerts:
                    # تخزين home_id وaway_id للفلترة
                    match_alerts[match_id] = {
                        'league_key': key,
                        'alerts':     alerts,
                        'home':       m.get('home', '?'),
                        'away':       m.get('away', '?'),
                        'home_id':    m.get('home_id', home_id),
                        'away_id':    m.get('away_id', away_id),
                    }

                # ── إصلاح #5: تسجيل وقت انتهاء المباراة لتنظيف صحيح ──
                ended_at_ts = _sports_match_cache.get(match_id, {}).get('ended_at', 0)
                if curr_state == 'post' and prev_state == 'in':
                    ended_at_ts = time.time()

                # تحديث الكاش — إصلاح #1: الأسماء الصحيحة known_ev_ids + known_pbp_ids
                _sports_match_cache[match_id] = {
                    'state':         curr_state,
                    'home_score':    curr_home,
                    'away_score':    curr_away,
                    'home_id':       home_id,
                    'away_id':       away_id,
                    'ended_at':      ended_at_ts,
                    'known_ev_ids':  prev_ev_ids  | sc_event_ids,
                    'known_pbp_ids': prev_pbp_ids | new_pbp_ids,
                }

        # ── إصلاح #5: تنظيف المباريات المنتهية منذ >30 دقيقة فقط ──
        now_ts   = time.time()
        seen_ids = {m.get('id') or m.get('name','') for ms in fresh_matches.values() for m in ms}
        to_delete = []
        for mid, cdata in _sports_match_cache.items():
            if cdata.get('state') == 'post':
                et = cdata.get('ended_at', 0)
                # إذا انتهت ومرت 30 دقيقة أو غير موجودة في ESPN → احذف
                if (et and now_ts - et > 1800) or mid not in seen_ids:
                    to_delete.append(mid)
        for mid in to_delete:
            _sports_match_cache.pop(mid, None)

        _save_sports_cache()

        if not match_alerts:
            return

        # ── 5. إرسال التنبيهات للمستخدمين المعنيين ────────────────────
        _msgs_sent_this_cycle = 0   # عداد للـ rate limit

        for uid_s, info in list(users.items()):
            prefs = info.get('sports', {})
            if not prefs.get('live_alerts'):
                continue
            lang        = info.get('lang', 'العربية 🇮🇶')
            sel_leagues = set(prefs.get('leagues', []))
            user_teams  = prefs.get('teams', {})

            user_msgs = []
            seen_alerts = set()   # dedup: لا نُرسل نفس التنبيه مرتين لنفس المستخدم
            for match_id, mdata in match_alerts.items():
                lk = mdata['league_key']
                if lk not in sel_leagues:
                    continue
                sel_teams = set(user_teams.get(lk, []))
                if sel_teams:
                    match_home = str(mdata.get('home_id', ''))
                    match_away = str(mdata.get('away_id', ''))
                    if match_home not in sel_teams and match_away not in sel_teams:
                        continue
                for alert_txt in mdata['alerts']:
                    key = alert_txt[:80]
                    if key not in seen_alerts:
                        seen_alerts.add(key)
                        user_msgs.append(alert_txt)

            if user_msgs:
                for msg in user_msgs:
                    try:
                        bot.send_message(int(uid_s), msg[:4096], parse_mode="Markdown",
                                         disable_web_page_preview=True)
                        _msgs_sent_this_cycle += 1
                        # إصلاح #4: تأخير 60ms بين كل رسالة (≈16 رسالة/ثانية، أمان من flood)
                        time.sleep(0.06)
                        # إضافي: استراحة أطول كل 20 رسالة
                        if _msgs_sent_this_cycle % 20 == 0:
                            time.sleep(1.0)
                    except Exception as e:
                        err_str = str(e).lower()
                        if 'retry' in err_str or '429' in err_str:
                            # Flood control — انتظر
                            try:
                                retry_sec = int(''.join(c for c in err_str if c.isdigit()) or '5')
                            except Exception:
                                retry_sec = 5
                            time.sleep(min(retry_sec + 1, 30))
                        elif 'blocked' in err_str or 'deactivated' in err_str or 'not found' in err_str:
                            pass  # مستخدم حجب البوت
                        # تجاهل بقية الأخطاء بصمت

    except Exception:
        pass
    finally:
        _sports_broadcaster_lock.clear()



# ═══════════════════════════════════════════════════════════════════
# ███████╗ ███████╗  █████╗  ████████╗██╗   ██╗██████╗ ███████╗███████╗
# ██╔════╝ ██╔════╝ ██╔══██╗ ╚══██╔══╝██║   ██║██╔══██╗██╔════╝██╔════╝
# █████╗   █████╗   ███████║    ██║   ██║   ██║██████╔╝█████╗  ███████╗
# ██╔══╝   ██╔══╝   ██╔══██║    ██║   ██║   ██║██╔══██╗██╔══╝  ╚════██║
# ██║      ███████╗ ██║  ██║    ██║   ╚██████╔╝██║  ██║███████╗███████║
# ╚═╝      ╚══════╝ ╚═╝  ╚═╝    ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚══════╝╚══════╝
# الميزات الأسطورية — AI Analysis + Crisis + Community + Dark Sources
# ═══════════════════════════════════════════════════════════════════

import collections

# ─── مصادر مظلمة: مواقع حكومية ورسمية عراقية ───────────────────────
DARK_SOURCES = [
    # البرلمان والحكومة
    {"url": "https://www.parliament.iq/", "base": "https://www.parliament.iq", "name": "البرلمان العراقي"},
    {"url": "https://pmo.iq/press/", "base": "https://pmo.iq", "name": "مجلس الوزراء"},
    {"url": "https://mof.gov.iq/", "base": "https://mof.gov.iq", "name": "وزارة المالية"},
    {"url": "https://www.cbi.iq/news", "base": "https://www.cbi.iq", "name": "البنك المركزي"},
    {"url": "https://oil.gov.iq/", "base": "https://oil.gov.iq", "name": "وزارة النفط"},
    {"url": "https://www.ihec.iq/", "base": "https://www.ihec.iq", "name": "المفوضية العليا للانتخابات"},
    # وكالات أنباء رسمية
    {"url": "https://www.ina.iq/", "base": "https://www.ina.iq", "name": "وكالة الأنباء العراقية"},
]

# ─── متابعة سرعة المصادر ─────────────────────────────────────────
_source_speed_log = collections.defaultdict(list)   # source → [timestamps]
_source_accuracy_log = collections.defaultdict(int) # source → verified_count

# ─── مراقبة الأزمات ───────────────────────────────────────────────
_crisis_keyword_freq = collections.defaultdict(list) # keyword → [timestamps]
_CRISIS_KEYWORDS = [
    "انفجار", "هجوم", "اغتيال", "اعتقال", "احتجاج", "تظاهر", "عاجل",
    "كارثة", "زلزال", "فيضان", "حريق", "اعلان الطوارئ", "حظر التجول",
    "explosion", "attack", "assassination", "protest", "emergency",
]
_CRISIS_THRESHOLD = 5  # عدد المرات خلال 30 دقيقة = أزمة محتملة
_last_crisis_alert = {}  # keyword → timestamp

# ─── الأحداث الحية ───────────────────────────────────────────────
_live_events = {}  # uid → {"event": str, "started": float, "last_update": float, "updates": []}

# ─── أخبار المستخدمين المُبلَّغ عنها ─────────────────────────────
_user_submitted_queue = []  # [{"uid": uid, "text": str, "time": float}]
_verified_user_news_log = []  # قائمة الأخبار الموثقة

# ─── أرشيف الأخبار (آخر 7 أيام، 1500 عنصر) ──────────────────────
_news_archive: list = []          # [{title, url, source, lang, ts, summary, fact}]
_news_archive_lock = threading.Lock()
_NEWS_ARCHIVE_MAX  = 1500
_NEWS_ARCHIVE_DAYS = 7

# ─── غرفة الأزمات المتقدمة ──────────────────────────────────────
_crisis_room_active   = False
_crisis_room_keyword  = ""
_crisis_room_timeline: list = []  # [{time_str, text, source}]
_crisis_room_start    = 0.0
_crisis_room_lock     = threading.Lock()
_crisis_report_sent_at = 0.0       # آخر مرة أُرسل فيها تقرير

# ─── قاعدة تصريحات السياسيين ────────────────────────────────────
_politician_statements: dict = {}   # name → [{text, date, source}]
_politician_lock = threading.Lock()
POLITICIAN_NAMES_WATCH = [
    "السوداني", "بارزاني", "الحلبوسي", "المالكي", "الصدر",
    "هادي العامري", "برهم صالح", "الفياض", "السامرائي",
    "الخزعلي", "السيستاني", "الكاظمي",
]

# ─── مخزن الذكاء الجماعي (crowd tips) ──────────────────────────
_crowd_tips: list = []              # [{uid, text, time, status: pending|approved|rejected}]
_crowd_tips_lock = threading.Lock()
_CROWD_TIP_MAX = 300

# ─── إحصاءات اليوم (للتقرير اليومي) ────────────────────────────
_daily_new_users: list = []         # [uid] من انضم اليوم
_daily_new_users_lock = threading.Lock()

# ─── وسائل الإعلام الأجنبية (الخبر قبل الخبر) ──────────────────
_FOREIGN_INTEL_FEEDS = [
    # إيران
    "https://www.tasnimnews.com/ar/rss",
    "https://www.presstv.ir/Arabic/rss",
    "https://www.mehrnews.com/rss/",
    # السعودية والخليج
    "https://feeds.alarabiya.net/alarabiya",
    "https://www.skynewsarabia.com/rss.xml",
    # دولي عن العراق
    "https://feeds.bbci.co.uk/arabic/rss.xml",
    "https://feeds.feedburner.com/aljazeera/live",
    "https://www.reuters.com/rss",
]
_IRAQ_FILTER_WORDS = [
    "العراق", "Iraq", "بغداد", "Baghdad", "بصرة", "كربلاء",
    "الموصل", "اربيل", "الحشد", "الديناري", "النفط العراقي",
    "PMF", "Kurdistan", "Basra", "Mosul",
]
_foreign_intel_sent: set = set()    # عناوين مُرسلة مسبقاً
_foreign_intel_last_run = 0.0

# ═══════════════════════════════════════════════════════════════════
# 1. كشف الأخبار الكاذبة
# ═══════════════════════════════════════════════════════════════════
def _ai_verify_news(title: str, body: str = "") -> dict:
    """يقارن الخبر بمصادر متعددة ويعطي نسبة موثوقية"""
    if not _AI_MODEL:
        return {"score": None, "verdict": "AI غير متاح", "reason": ""}
    try:
        prompt = f"""أنت محقق إعلامي متخصص في كشف الأخبار الكاذبة.

الخبر: {title}
{('التفاصيل: ' + body[:400]) if body else ''}

قيّم موثوقية هذا الخبر من 0 إلى 100 بناءً على:
1. هل يحتوي على ادعاءات قابلة للتحقق؟
2. هل الصياغة إثارية أم موضوعية؟
3. هل يتوافق مع الأحداث المعروفة؟
4. هل يحتوي على مبالغة أو أرقام غير منطقية؟

أجب بهذا الشكل الحرفي:
SCORE: [رقم 0-100]
VERDICT: [موثوق/مشكوك فيه/كاذب على الأرجح]
REASON: [سبب واحد مختصر]"""
        response = _AI_MODEL.generate_content(prompt)
        text = response.text.strip()
        score, verdict, reason = None, "غير محدد", ""
        for line in text.splitlines():
            if line.startswith("SCORE:"):
                try:
                    score = int(line.split(":", 1)[1].strip())
                except Exception:
                    pass
            elif line.startswith("VERDICT:"):
                verdict = line.split(":", 1)[1].strip()
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
        return {"score": score, "verdict": verdict, "reason": reason}
    except Exception:
        return {"score": None, "verdict": "تعذر التحقق", "reason": ""}

def _format_verify_result(result: dict, title: str) -> str:
    score = result.get("score")
    verdict = result.get("verdict", "غير محدد")
    reason = result.get("reason", "")
    if score is None:
        meter = "⬜⬜⬜⬜⬜"
        score_str = "؟"
    else:
        filled = round(score / 20)
        colors = ["🔴","🟠","🟡","🟢","🟢"]
        meter = "".join(colors[min(i, len(colors)-1)] for i in range(filled)) + "⬜" * (5 - filled)
        score_str = f"{score}%"
    icon = "✅" if (score or 0) >= 70 else "⚠️" if (score or 0) >= 40 else "🚨"
    return (
        f"🔍 *تحقق من الخبر*\n\n"
        f"📰 {title[:80]}\n\n"
        f"{meter} `{score_str}`\n"
        f"{icon} *{verdict}*\n"
        f"📝 {reason}"
    )

# ═══════════════════════════════════════════════════════════════════
# 2. تحليل المزاج السياسي والتوقعات
# ═══════════════════════════════════════════════════════════════════
def _ai_political_analysis(title: str, body: str = "", lang: str = "العربية 🇮🇶") -> str:
    """يحلل الخبر السياسي ويتوقع ما سيحدث"""
    if not _AI_MODEL:
        return "AI غير متاح"
    try:
        prompt = f"""أنت محلل سياسي متخصص بالشأن العراقي والمنطقة العربية.

الخبر: {title}
{('التفاصيل: ' + body[:500]) if body else ''}

قدم تحليلاً سريعاً ومباشراً بهذه النقاط:
1. 🎯 الأثر الفوري (جملة واحدة)
2. 🔮 التوقعات (ماذا سيحدث خلال أسبوع؟)
3. 🏛️ الأطراف المؤثرة (من المستفيد؟)
4. ⚡ مستوى الخطورة: [منخفض/متوسط/عالي/حرج]

كن مختصراً وجريئاً في تقييمك."""
        response = _AI_MODEL.generate_content(prompt)
        return response.text.strip()[:800]
    except Exception as e:
        return f"تعذر التحليل: {e}"

# ═══════════════════════════════════════════════════════════════════
# 3. مقارنة وجهات النظر
# ═══════════════════════════════════════════════════════════════════
def _ai_compare_perspectives(topic: str) -> str:
    """يقارن كيف غطّت مصادر مختلفة نفس الموضوع"""
    if not _AI_MODEL:
        return "AI غير متاح"
    try:
        # جمع أخبار من مصادر متنوعة
        sources_coverage = {}
        search_feeds = {
            "🇶🇦 الجزيرة": "https://www.aljazeera.net/xml/rss",
            "🇷🇺 RT عربي": "https://arabic.rt.com/rss/",
            "🇬🇧 BBC عربي": "https://feeds.bbci.co.uk/arabic/rss.xml",
            "🇺🇸 CNN عربي": "https://arabic.cnn.com/rss/latest",
        }
        for src_name, feed_url in search_feeds.items():
            try:
                feed = _parse_feed(feed_url)
                if not feed:
                    continue
                for entry in feed.entries[:20]:
                    entry_title = getattr(entry, 'title', '')
                    if topic.lower() in entry_title.lower():
                        sources_coverage[src_name] = entry_title
                        break
            except Exception:
                pass

        if len(sources_coverage) < 2:
            prompt = f"""قدّم مقارنة تحليلية لكيفية تغطية هذا الموضوع من منظور مصادر إعلامية مختلفة:
موضوع: {topic}
وضّح الفروق المتوقعة بين: الجزيرة، RT، BBC، CNN العربي، والإعلام العراقي.
اجعل الإجابة مختصرة (3-4 جمل لكل مصدر)."""
        else:
            coverage_text = "\n".join(f"{src}: {title}" for src, title in sources_coverage.items())
            prompt = f"""قارن هذه التغطيات الإعلامية لنفس الموضوع:

{coverage_text}

حلل:
1. نقاط الاتفاق بين المصادر
2. نقاط الاختلاف
3. من يُقدّم أكثر تحيزاً؟
4. ما الذي أغفله الجميع؟

كن موضوعياً وجريئاً."""
        response = _AI_MODEL.generate_content(prompt)
        return response.text.strip()[:1000]
    except Exception as e:
        return f"تعذر المقارنة: {e}"

# ═══════════════════════════════════════════════════════════════════
# 4. خريطة الأخبار الزمنية
# ═══════════════════════════════════════════════════════════════════
def _ai_build_timeline(topic: str) -> str:
    """يبني تسلسل زمني للأحداث المتعلقة بموضوع"""
    if not _AI_MODEL:
        return "AI غير متاح"
    try:
        # جمع أخبار متعلقة بالموضوع
        related_news = []
        for lang_feeds in RSS.values():
            for feed_url in lang_feeds[:5]:
                try:
                    feed = _parse_feed(feed_url)
                    if not feed:
                        continue
                    for entry in feed.entries[:15]:
                        title = getattr(entry, 'title', '')
                        if topic.lower() in title.lower():
                            pub = _pub_dt_from_item(entry)
                            pub_str = pub.strftime('%Y-%m-%d') if pub else 'تاريخ غير معروف'
                            related_news.append(f"[{pub_str}] {title}")
                except Exception:
                    pass

        if related_news:
            news_text = "\n".join(related_news[:15])
            prompt = f"""بناءً على هذه الأخبار المتعلقة بـ "{topic}"، ابنِ تسلسلاً زمنياً واضحاً للأحداث:

{news_text}

رتّبها من الأقدم للأحدث وأضف سياقاً لكل حدث."""
        else:
            prompt = f"""ابنِ تسلسلاً زمنياً تحليلياً لأبرز أحداث موضوع: "{topic}"
        
        من البداية حتى اليوم. استخدم معلوماتك العامة.
        الشكل: 📅 [تاريخ] — [الحدث] — [الأهمية]"""

        response = _AI_MODEL.generate_content(prompt)
        return response.text.strip()[:1500]
    except Exception as e:
        return f"تعذر بناء الخريطة: {e}"


# ═══════════════════════════════════════════════════════════════════
# الجيل الثاني — 8 ميزات أسطورية
# ═══════════════════════════════════════════════════════════════════

# ─── كاش البيانات ────────────────────────────────────────────────
_profile_cache    = {}   # name → {profile_text, timestamp}
_econ_last_alert  = {}   # indicator → timestamp
_user_interests   = {}   # uid → {topics: Counter, sources: Counter}
_parliament_cache = {"text": "", "timestamp": 0}

# ─── 1. محقق الشخصيات ──────────────────────────────────────────
def _ai_build_profile(name: str) -> str:
    if not _AI_MODEL:
        return "AI غير متاح"
    cached = _profile_cache.get(name)
    if cached and time.time() - cached["timestamp"] < 3600:
        return cached["text"]
    # جمع أخبار عن الشخص
    related = []
    for feed_url in list(RSS.get("العربية 🇮🇶", []))[:10]:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:20]:
                title = getattr(entry, 'title', '')
                if name.split()[0].lower() in title.lower():
                    pub = _pub_dt_from_item(entry)
                    pub_str = pub.strftime('%Y-%m-%d') if pub else ''
                    related.append(f"[{pub_str}] {title}")
        except Exception:
            pass
    news_ctx = "\n".join(related[:20]) if related else "لا توجد أخبار حديثة"
    prompt = f"""أنت محقق صحفي متخصص. ابنِ ملفاً شاملاً عن: {name}

أخبار حديثة متعلقة به:
{news_ctx}

الملف يشمل:
👤 **الهوية والمنصب**
📊 **أبرز مواقفه/قراراته الأخيرة**
🤝 **علاقاته وتحالفاته**
⚠️ **الجدل والانتقادات**
🔮 **توقعات دوره المستقبلي**

كن موضوعياً ومستنداً للأخبار."""
    try:
        response = _AI_MODEL.generate_content(prompt)
        result = response.text.strip()[:1500]
        _profile_cache[name] = {"text": result, "timestamp": time.time()}
        return result
    except Exception as e:
        return f"تعذر بناء الملف: {e}"

# ─── 2. محادثة مع الأخبار (RAG) ────────────────────────────────
def _ai_chat_with_news(question: str, lang: str = "العربية 🇮🇶") -> str:
    if not _AI_MODEL:
        return "AI غير متاح"
    # جمع أخبار ذات صلة بالسؤال
    keywords = [w for w in question.split() if len(w) > 3]
    related = []
    for feed_url in list(RSS.get(lang, RSS.get("العربية 🇮🇶", []))[:12]):
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:15]:
                title = getattr(entry, 'title', '')
                summary = getattr(entry, 'summary', '') or ''
                if any(kw.lower() in title.lower() for kw in keywords):
                    related.append(f"• {title}")
        except Exception:
            pass
    context = "\n".join(related[:15]) if related else "لا توجد أخبار مرتبطة مباشرة"
    prompt = f"""أنت مساعد إخباري ذكي. أجب على السؤال بناءً على الأخبار الحالية.

السؤال: {question}

أخبار ذات صلة:
{context}

قدم إجابة مباشرة ومختصرة (3-5 جمل) مستنداً للأخبار. إذا لم تجد إجابة واضحة، قل ذلك صراحةً."""
    try:
        response = _AI_MODEL.generate_content(prompt)
        return response.text.strip()[:800]
    except Exception as e:
        return f"تعذر الإجابة: {e}"

# ─── 3. تحليل الصور بـ AI ──────────────────────────────────────
def _ai_analyze_image_url(img_url: str, user_question: str = "") -> str:
    if not _AI_MODEL:
        return "AI غير متاح"
    try:
        import google.generativeai as genai
        vision_model = genai.GenerativeModel("gemini-2.5-flash")
        import urllib.request
        req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            img_bytes = resp.read()
        img_part = {"mime_type": "image/jpeg", "data": img_bytes}
        question = user_question or "حلل هذه الصورة إخبارياً: ما الحدث؟ من الأشخاص؟ ما السياق؟"
        response = vision_model.generate_content([question, img_part])
        return response.text.strip()[:1000]
    except Exception as e:
        return f"تعذر تحليل الصورة: {e}"

def _ai_analyze_photo_file(file_bytes: bytes, user_question: str = "") -> str:
    if not _AI_MODEL:
        return "AI غير متاح"
    try:
        import google.generativeai as genai
        vision_model = genai.GenerativeModel("gemini-2.5-flash")
        img_part = {"mime_type": "image/jpeg", "data": file_bytes}
        question = user_question or "حلل هذه الصورة إخبارياً: ما الحدث؟ من الأشخاص؟ ما السياق؟ هل تبدو حقيقية أم مفبركة؟"
        response = vision_model.generate_content([question, img_part])
        return response.text.strip()[:1000]
    except Exception as e:
        return f"تعذر تحليل الصورة: {e}"

# ─── 4. التنبؤ بالأحداث ────────────────────────────────────────
def _ai_predict_events(topic: str) -> str:
    if not _AI_MODEL:
        return "AI غير متاح"
    related = []
    for feed_url in list(RSS.get("العربية 🇮🇶", []))[:8]:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:10]:
                title = getattr(entry, 'title', '')
                if any(w.lower() in title.lower() for w in topic.split() if len(w) > 3):
                    related.append(title)
        except Exception:
            pass
    context = "\n".join(related[:10]) if related else ""
    _ctx_predict = ('أخبار حديثة ذات صلة:\n' + '\n'.join(related[:10])) if related else ''
    prompt = f"""أنت خبير تحليلي استراتيجي. بناءً على الأنماط الحالية، توقع ما سيحدث بخصوص: {topic}

{_ctx_predict}

قدم تنبؤات واضحة ومحددة:
🔮 **خلال 48 ساعة:**
📅 **خلال أسبوع:**
🗓️ **خلال شهر:**
⚡ **أعلى سيناريو خطورة:**
✅ **أفضل سيناريو:**

نسبة الثقة لكل تنبؤ (%)."""
    try:
        response = _AI_MODEL.generate_content(prompt)
        return response.text.strip()[:1200]
    except Exception as e:
        return f"تعذر التنبؤ: {e}"

# ─── 5. إنذار اقتصادي ذكي ──────────────────────────────────────
def _check_economic_alerts():
    """يراقب مؤشرات اقتصادية ويرسل إنذارات ذكية"""
    try:
        now = time.time()
        alerts = []
        # أسعار النفط
        try:
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1d&range=2d",
                timeout=8, headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code == 200:
                data = r.json()
                closes = data["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
                closes = [c for c in closes if c]
                if len(closes) >= 2:
                    change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100
                    if abs(change_pct) >= 3:
                        direction = "📉 هبط" if change_pct < 0 else "📈 ارتفع"
                        last_alert = _econ_last_alert.get("oil", 0)
                        if now - last_alert > 3600:
                            _econ_last_alert["oil"] = now
                            alerts.append(
                                f"🛢️ *تحذير نفطي*\n"
                                f"سعر خام النفط {direction} `{change_pct:+.1f}%`\n"
                                f"السعر الحالي: `${closes[-1]:.1f}`\n\n"
                                f"⚠️ قد يؤثر على الموازنة العراقية"
                            )
        except Exception:
            pass
        # الدولار مقابل الدينار (من البنك المركزي أو مصدر بديل)
        try:
            r = requests.get(
                "https://api.exchangerate-api.com/v4/latest/USD",
                timeout=8
            )
            if r.status_code == 200:
                rates = r.json().get("rates", {})
                iqd = rates.get("IQD", 0)
                if iqd and (iqd < 1290 or iqd > 1330):
                    last_alert = _econ_last_alert.get("usd_iqd", 0)
                    if now - last_alert > 7200:
                        _econ_last_alert["usd_iqd"] = now
                        status = "منخفض ⬇️" if iqd < 1290 else "مرتفع ⬆️"
                        alerts.append(
                            f"💵 *تحذير صرف*\n"
                            f"الدولار مقابل الدينار: `{iqd:,.0f}` — {status}\n"
                            f"⚠️ خارج النطاق الرسمي (1290-1330)"
                        )
        except Exception:
            pass
        # إرسال التحذيرات للمشتركين
        if alerts:
            for uid_s, info in list(users.items()):
                try:
                    if info.get("notifications", True) and info.get("alert_level", "medium") in ("high", "critical"):
                        for alert in alerts:
                            bot.send_message(int(uid_s), alert, parse_mode="Markdown")
                except Exception:
                    pass
            try:
                for alert in alerts:
                    bot.send_message(ADMIN_ID, alert, parse_mode="Markdown")
            except Exception:
                pass
    except Exception:
        pass

# ─── 6. تلخيص جلسات البرلمان ───────────────────────────────────
def _get_parliament_summary() -> str:
    if not _AI_MODEL:
        return "AI غير متاح"
    cached = _parliament_cache
    if time.time() - cached.get("timestamp", 0) < 1800:
        return cached.get("text", "")
    news_items = []
    parliament_feeds = [
        "https://www.parliament.iq/feed/",
        "https://www.ina.iq/rss.php",
    ]
    for url in parliament_feeds:
        try:
            feed = _parse_feed(url)
            if feed:
                for entry in feed.entries[:10]:
                    title = getattr(entry, 'title', '')
                    summary = getattr(entry, 'summary', '') or ''
                    if title:
                        news_items.append(f"• {title}: {summary[:100]}")
        except Exception:
            pass
    # جرّب السكرابنق
    if not news_items and _BS4_AVAILABLE:
        try:
            items = _scrape_news_site("https://www.parliament.iq/", "https://www.parliament.iq", max_items=8)
            news_items = [f"• {t}" for t, _ in items]
        except Exception:
            pass
    if not news_items:
        news_items = ["لا تتوفر بيانات مباشرة من موقع البرلمان"]
    prompt = f"""لخّص آخر أخبار البرلمان العراقي في 5 نقاط مختصرة وواضحة:

المعلومات المتاحة:
{chr(10).join(news_items[:15])}

الشكل المطلوب:
🏛️ **ملخص جلسة البرلمان**
1. ...
2. ...
3. ...
4. ...
5. ..."""
    try:
        response = _AI_MODEL.generate_content(prompt)
        result = response.text.strip()[:1000]
        _parliament_cache["text"] = result
        _parliament_cache["timestamp"] = time.time()
        return result
    except Exception as e:
        return f"تعذر التلخيص: {e}"

# ─── 7. خريطة النفوذ السياسي ───────────────────────────────────
def _ai_influence_map(name: str) -> str:
    if not _AI_MODEL:
        return "AI غير متاح"
    related = []
    for feed_url in list(RSS.get("العربية 🇮🇶", []))[:10]:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:15]:
                title = getattr(entry, 'title', '')
                if name.split()[0] in title:
                    related.append(title)
        except Exception:
            pass
    context = "\n".join(related[:15]) if related else ""
    _ctx_influence = ('أخبار حديثة:\n' + context) if context else ''
    prompt = f"""أنت محلل سياسي. ارسم خريطة نفوذ لـ: {name}

{_ctx_influence}

الخريطة تشمل:
🤝 **الحلفاء الرئيسيون** (مع طبيعة العلاقة)
⚔️ **المنافسون والخصوم**
🏛️ **المؤسسات التي يؤثر عليها**
💰 **مصادر قوته** (سياسية/اقتصادية/قبلية/دينية)
🌍 **ارتباطاته الخارجية**
📊 **مستوى نفوذه: [محلي/وطني/إقليمي/دولي]**"""
    try:
        response = _AI_MODEL.generate_content(prompt)
        return response.text.strip()[:1500]
    except Exception as e:
        return f"تعذر بناء الخريطة: {e}"

# ─── 8. بث مخصص بـ AI ─────────────────────────────────────────
def _update_user_interests(uid: str, title: str, source: str):
    """يتتبع اهتمامات المستخدم من سلوكه"""
    prefs = _user_interests.setdefault(uid, {"topics": collections.Counter(), "sources": collections.Counter(), "count": 0})
    words = [w for w in title.split() if len(w) > 4]
    for w in words[:5]:
        prefs["topics"][w] += 1
    if source:
        prefs["sources"][source] += 1
    prefs["count"] = prefs.get("count", 0) + 1

def _ai_curate_news_for_user(uid: str, candidates: list) -> list:
    """يرتب الأخبار حسب اهتمامات المستخدم"""
    prefs = _user_interests.get(str(uid))
    if not prefs or prefs.get("count", 0) < 5:
        return candidates  # لا يكفي تاريخ
    top_topics = [w for w, _ in prefs["topics"].most_common(10)]
    top_sources = [s for s, _ in prefs["sources"].most_common(5)]
    def score(cand):
        title = cand[1].lower()
        src = cand[2]
        s = 0
        for topic in top_topics:
            if topic.lower() in title:
                s += 10
        if src in top_sources:
            s += 5
        return s
    return sorted(candidates, key=score, reverse=True)


# ═══════════════════════════════════════════════════════════════════
# 5. إنذار مبكر للأزمات
# ═══════════════════════════════════════════════════════════════════
def _crisis_monitor_check():
    """يراقب تكرار الكلمات الحرجة ويُنذر عند الارتفاع المفاجئ"""
    try:
        now = time.time()
        window = 30 * 60  # 30 دقيقة
        for feed_url in list(RSS.get("العربية 🇮🇶", []))[:10]:
            try:
                feed = _parse_feed(feed_url)
                if not feed:
                    continue
                for entry in feed.entries[:5]:
                    title = getattr(entry, 'title', '').lower()
                    for kw in _CRISIS_KEYWORDS:
                        if kw.lower() in title:
                            _crisis_keyword_freq[kw].append(now)
            except Exception:
                pass

        # تنظيف الأحداث القديمة
        for kw in list(_crisis_keyword_freq.keys()):
            _crisis_keyword_freq[kw] = [t for t in _crisis_keyword_freq[kw] if now - t < window]

        # كشف الأزمة
        for kw, times in _crisis_keyword_freq.items():
            if len(times) >= _CRISIS_THRESHOLD:
                last_alert = _last_crisis_alert.get(kw, 0)
                if now - last_alert > 3600:  # لا تُنبّه أكثر من مرة كل ساعة
                    _last_crisis_alert[kw] = now
                    for uid_s, info in list(users.items()):
                        try:
                            level = info.get("alert_level", "medium")
                            if level in ("high", "critical") and info.get("notifications", True):
                                u_lang = info.get("lang", "English 🇬🇧")
                                alert_text = _ul(u_lang, "crisis_alert", kw=kw, n=len(times))
                                bot.send_message(int(uid_s), alert_text, parse_mode="Markdown")
                        except Exception:
                            pass
                    # إشعار الأدمن دائماً
                    try:
                        bot.send_message(ADMIN_ID, alert_text, parse_mode="Markdown")
                    except Exception:
                        pass
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════
# 6. بث مباشر للأحداث
# ═══════════════════════════════════════════════════════════════════
def _live_events_broadcaster():
    """يتابع الأحداث الحية ويرسل تحديثات"""
    if not _live_events:
        return
    now = time.time()
    to_remove = []
    for uid_s, event_info in list(_live_events.items()):
        try:
            event = event_info["event"]
            started = event_info["started"]
            last_upd = event_info.get("last_update", 0)
            # انتهاء التتبع بعد 6 ساعات
            if now - started > 6 * 3600:
                to_remove.append(uid_s)
                try:
                    bot.send_message(int(uid_s),
                        f"⏹ انتهى التتبع المباشر لـ: *{event}*\n_(6 ساعات)_",
                        parse_mode="Markdown")
                except Exception:
                    pass
                continue
            # تحديث كل دقيقتين فقط
            if now - last_upd < 120:
                continue
            # جمع أخبار جديدة عن الحدث
            new_items = []
            for feed_url in list(RSS.get("العربية 🇮🇶", []))[:8]:
                try:
                    feed = _parse_feed(feed_url)
                    if not feed:
                        continue
                    for entry in feed.entries[:5]:
                        title = getattr(entry, 'title', '')
                        link = getattr(entry, 'link', '')
                        pub = _pub_dt_from_item(entry)
                        if not pub or now - pub.timestamp() > 3600:
                            continue
                        if any(w.lower() in title.lower() for w in event.split()):
                            new_items.append((title, link, pub))
                except Exception:
                    pass

            _live_events[uid_s]["last_update"] = now
            if new_items:
                prev_titles = set(event_info.get("updates", []))
                fresh = [(t, l, p) for t, l, p in new_items if t not in prev_titles]
                if fresh:
                    text = f"🔴 *تحديث مباشر — {event}*\n\n"
                    for title, link, pub in fresh[:3]:
                        time_str = pub.strftime('%H:%M') if pub else ''
                        text += f"⏱ `{time_str}` — [{title}]({link})\n\n"
                    try:
                        bot.send_message(int(uid_s), text[:4096],
                            parse_mode="Markdown", disable_web_page_preview=True)
                    except Exception:
                        pass
                    for t, _, _ in fresh:
                        event_info.setdefault("updates", []).append(t)
                        if len(event_info["updates"]) > 50:
                            event_info["updates"] = event_info["updates"][-50:]
        except Exception:
            continue
    for uid_s in to_remove:
        _live_events.pop(uid_s, None)

# ═══════════════════════════════════════════════════════════════════
# 7. مجتمع مشاركة الأخبار
# ═══════════════════════════════════════════════════════════════════
def _ai_verify_user_news(text: str) -> dict:
    """يتحقق AI من خبر أرسله مستخدم"""
    if not _AI_MODEL:
        return {"valid": False, "reason": "AI غير متاح", "score": 0}
    try:
        prompt = f"""مستخدم أرسل هذا الخبر من أرض الواقع:

"{text[:500]}"

حكم عليه:
1. هل يبدو خبراً حقيقياً أم إشاعة أم محتوى عشوائي؟
2. هل يستحق النشر للمشتركين؟
3. ما نسبة موثوقيته 0-100؟

أجب بالشكل:
VALID: [yes/no]
SCORE: [0-100]
REASON: [سبب مختصر]
CLEANED: [الخبر بعد تنقيحه للنشر، أو "لا يصلح"]"""
        response = _AI_MODEL.generate_content(prompt)
        text_out = response.text.strip()
        result = {"valid": False, "score": 0, "reason": "", "cleaned": ""}
        for line in text_out.splitlines():
            if line.startswith("VALID:"):
                result["valid"] = "yes" in line.lower()
            elif line.startswith("SCORE:"):
                try:
                    result["score"] = int(line.split(":", 1)[1].strip())
                except Exception:
                    pass
            elif line.startswith("REASON:"):
                result["reason"] = line.split(":", 1)[1].strip()
            elif line.startswith("CLEANED:"):
                result["cleaned"] = line.split(":", 1)[1].strip()
        return result
    except Exception:
        return {"valid": False, "reason": "خطأ في التحقق", "score": 0, "cleaned": ""}

# ═══════════════════════════════════════════════════════════════════
# 8. تصنيف المصادر
# ═══════════════════════════════════════════════════════════════════
def _track_source_speed(source_name: str, pub_dt):
    """يسجّل توقيت نشر المصدر لقياس سرعته"""
    if pub_dt:
        _source_speed_log[source_name].append(pub_dt.timestamp())
        if len(_source_speed_log[source_name]) > 100:
            _source_speed_log[source_name] = _source_speed_log[source_name][-100:]

def _get_source_rankings() -> list:
    """يحسب ترتيب المصادر حسب السرعة والكمية"""
    now = time.time()
    rankings = []
    for source, timestamps in _source_speed_log.items():
        recent = [t for t in timestamps if now - t < 24 * 3600]
        if not recent:
            continue
        avg_gap = (max(recent) - min(recent)) / max(len(recent) - 1, 1) if len(recent) > 1 else 9999
        rankings.append({
            "source": source,
            "count_24h": len(recent),
            "avg_gap_min": round(avg_gap / 60, 1),
            "score": len(recent) * 100 / max(avg_gap / 60, 1),
        })
    return sorted(rankings, key=lambda x: x["score"], reverse=True)

# ═══════════════════════════════════════════════════════════════════
# 9. سكرابنق المصادر المظلمة (الرسمية)
# ═══════════════════════════════════════════════════════════════════
def _scrape_dark_sources() -> list:
    """يسكرب المواقع الحكومية الرسمية"""
    results = []
    if not _BS4_AVAILABLE:
        return results
    for src in DARK_SOURCES:
        try:
            items = _scrape_news_site(src["url"], src["base"], max_items=5)
            for title, link in items:
                if len(title) > 20 and not is_blacklisted(title):
                    results.append((link, title, src["name"], "", None))
        except Exception:
            pass
    return results



# ═══════════════════════════════════════════════════════════════════
# 🔍 DEEPSEARCH — بحث عميق مثل ChatGPT Deep Research
# ═══════════════════════════════════════════════════════════════════
import threading

_deepsearch_active = {}  # uid → True/False (لمنع تشغيل بحثين معاً)

def _deepsearch_worker(uid: int, topic: str, progress_msg_id: int, chat_id: int):
    """
    ═══════════════════════════════════════════════════════════════
    DeepSearch v2.0 — بحث عميق بـ 6 خطوات مثل ChatGPT Deep Research
    ───────────────────────────────────────────────────────────────
    1️⃣  تحليل المدخلات: كلمات مفتاحية + نية البحث + المجال
    2️⃣  جمع المعلومات: RSS + NewsAPI (داخلي وخارجي)
    3️⃣  تقييم موثوقية المصادر وفلترتها
    4️⃣  تحليل AI عميق بـ 8 محاور
    5️⃣  تجميع التقرير النهائي مع المصادر
    6️⃣  عرض النتيجة للمستخدم
    ═══════════════════════════════════════════════════════════════
    """
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')

    def upd(text):
        try:
            bot.edit_message_text(text, chat_id, progress_msg_id, parse_mode="Markdown")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════
    # ═ وظائف مساعدة داخلية للـ DeepSearch ══════════════════
    # ══════════════════════════════════════════════════════════

    def _topic_match(text, kw_list):
        """تطابق ذكي: يشترط وجود ≥50% من الكلمات المفتاحية في النص"""
        if not kw_list:
            return False
        text_l = text.lower()
        matched = sum(1 for kw in kw_list if kw.lower() in text_l)
        return matched >= max(1, len(kw_list) * 0.5)

    def _detect_intent(text: str) -> str:
        """
        يُحدد نية البحث:
        definition / steps / news / statistics / advice / analysis
        """
        t = text.lower()
        if any(w in t for w in ("ما هو","ما هي","تعريف","معنى","يعني","what is","define")):
            return "definition"
        if any(w in t for w in ("كيف","خطوات","طريقة","how to","steps","كيفية")):
            return "steps"
        if any(w in t for w in ("أخبار","حدث","اليوم","الآن","آخر","news","latest","breaking")):
            return "news"
        if any(w in t for w in ("إحصاء","إحصائية","كم","عدد","نسبة","statistics","number","how many")):
            return "statistics"
        if any(w in t for w in ("نصيحة","أنصح","أفضل","tips","advice","recommend")):
            return "advice"
        return "analysis"

    def _detect_domain(text: str) -> str:
        """
        يُحدد المجال: politics / economy / sports / science / tech / health / general
        """
        t = text.lower()
        if any(w in t for w in ("سياس","حكوم","انتخاب","رئيس","وزير","برلمان","politics","government","president")):
            return "politics"
        if any(w in t for w in ("اقتصاد","نفط","دولار","نمو","ميزانية","economy","oil","dollar","budget")):
            return "economy"
        if any(w in t for w in ("رياض","كرة","مباراة","فريق","sports","football","match","team")):
            return "sports"
        if any(w in t for w in ("علم","بحث","دراس","اكتشاف","science","research","study","discovery")):
            return "science"
        if any(w in t for w in ("تقنية","ذكاء اصطناعي","تكنولوج","هاتف","برنامج","tech","ai","software","app")):
            return "tech"
        if any(w in t for w in ("صحة","مرض","علاج","دواء","طب","health","disease","treatment","medicine")):
            return "health"
        return "general"

    def _source_reliability(url: str) -> int:
        """
        يُقيّم موثوقية المصدر (0-10):
        10 = رسمي/حكومي، 8 = وكالة أنباء كبرى، 6 = صحيفة معروفة، 4 = موقع متخصص، 2 = غير معروف
        """
        u = url.lower()
        if any(d in u for d in ("un.org","who.int","gov.","parliament.","whitehouse.","mofa.","pmo.","mof.")):
            return 10
        if any(d in u for d in ("reuters.","ap.org","afp.","bbc.","aljazeera.","france24.","dw.","bloomberg.")):
            return 9
        if any(d in u for d in ("nytimes.","theguardian.","washingtonpost.","economist.","ft.com","zeit.de","lemonde.")):
            return 8
        if any(d in u for d in ("alarabiya.","skynewsarabia.","rt.com","sputnik.","anadolu.")):
            return 6
        if any(d in u for d in ("wikipedia.","britannica.","scholarpedia.")):
            return 7
        if any(d in u for d in (".edu",".ac.","scholar.","researchgate.","pubmed.")):
            return 8
        return 4

    try:
        # ══════════════════════════════════════════════════════════
        # 1️⃣ الخطوة 1: تحليل المدخلات (كلمات مفتاحية + نية + مجال)
        # ══════════════════════════════════════════════════════════
        upd(
            f"🔍 *DeepSearch: {topic}*\n\n"
            f"`[1/6]` 🧩 أُحلّل موضوعك وأُحدّد الكلمات المفتاحية..."
        )

        # استخراج الكلمات المفتاحية
        stop_words = {"في","من","على","إلى","أن","هذا","هذه","ذلك","التي","الذي","مع","عن",
                      "لا","ما","أو","لم","قد","كان","the","a","an","of","in","on","is","are"}
        keywords = [w for w in topic.split() if len(w) > 2 and w.lower() not in stop_words]

        # تحديد النية والمجال
        intent = _detect_intent(topic)
        domain = _detect_domain(topic)

        intent_labels = {
            "definition":"تعريف وشرح","steps":"خطوات وطريقة","news":"أخبار وتطورات",
            "statistics":"إحصاءات وأرقام","advice":"نصائح وتوصيات","analysis":"تحليل عميق"
        }
        domain_labels = {
            "politics":"السياسة","economy":"الاقتصاد","sports":"الرياضة",
            "science":"العلوم","tech":"التقنية","health":"الصحة","general":"عام"
        }

        time.sleep(0.8)  # تأخير بسيط ليرى المستخدم الخطوة

        # ══════════════════════════════════════════════════════════
        # 2️⃣ الخطوة 2: جمع المعلومات (RSS + NewsAPI)
        # ══════════════════════════════════════════════════════════
        upd(
            f"🔍 *DeepSearch: {topic}*\n\n"
            f"✅ `[1/6]` تحليل المدخلات\n"
            f"  ↳ النية: {intent_labels.get(intent, intent)} | المجال: {domain_labels.get(domain, domain)}\n"
            f"  ↳ كلمات مفتاحية: {' · '.join(keywords[:5])}\n\n"
            f"`[2/6]` 📡 أجمع المعلومات من المصادر..."
        )

        rss_hits = []
        for feed_url in list(RSS.get(lang, RSS.get("العربية 🇮🇶", [])))[:30]:
            try:
                feed = _parse_feed(feed_url)
                if not feed:
                    continue
                reliability = _source_reliability(feed_url)
                for entry in feed.entries[:25]:
                    t_ = getattr(entry, 'title',   '') or ''
                    s_ = getattr(entry, 'summary',  '') or ''
                    l_ = getattr(entry, 'link',     '') or ''
                    if _topic_match(t_ + " " + s_, keywords):
                        pub = _pub_dt_from_item(entry)
                        rss_hits.append({
                            "title":       t_,
                            "summary":     s_[:500],
                            "link":        l_,
                            "pub":         pub,
                            "reliability": reliability,
                            "source":      feed_url,
                        })
            except Exception:
                pass

        newsapi_hits = []
        if NEWS_KEY:
            try:
                r = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": topic, "language": "ar", "pageSize": 20, "sortBy": "publishedAt"},
                    headers={"X-Api-Key": NEWS_KEY}, timeout=10
                )
                if r.status_code == 200:
                    for art in r.json().get("articles", []):
                        url_ = art.get("url", "")
                        newsapi_hits.append({
                            "title":       art.get("title", ""),
                            "summary":     art.get("description", "")[:500],
                            "link":        url_,
                            "reliability": _source_reliability(url_),
                            "source":      art.get("source", {}).get("name", ""),
                        })
            except Exception:
                pass

        # ══════════════════════════════════════════════════════════
        # 3️⃣ الخطوة 3: فلترة المصادر حسب الموثوقية
        # ══════════════════════════════════════════════════════════
        all_raw = rss_hits + newsapi_hits
        upd(
            f"🔍 *DeepSearch: {topic}*\n\n"
            f"✅ `[1/6]` تحليل المدخلات\n"
            f"✅ `[2/6]` جمع المعلومات — {len(all_raw)} نتيجة خام\n"
            f"`[3/6]` 🔎 أُقيّم موثوقية المصادر وأُفلترها..."
        )
        time.sleep(0.5)

        # إزالة التكرار + ترتيب حسب الموثوقية
        unique: dict = {}
        for item in all_raw:
            t_ = item.get("title", "")
            if t_ and len(t_) > 10:
                key = t_[:50].lower()
                if key not in unique or item.get("reliability", 0) > unique[key].get("reliability", 0):
                    unique[key] = item

        # فرز تنازلياً: الأعلى موثوقية أولاً
        verified_news = sorted(unique.values(), key=lambda x: x.get("reliability", 0), reverse=True)

        # فصل: موثوق (≥6) / مقبول (3-5) / مستبعد (<3)
        trusted   = [i for i in verified_news if i.get("reliability", 0) >= 6][:12]
        acceptable= [i for i in verified_news if 3 <= i.get("reliability", 0) < 6][:8]
        recent_news = trusted + acceptable   # المجموع المستخدم في التقرير

        # ══════════════════════════════════════════════════════════
        # 4️⃣ الخطوة 4: الذكاء الاصطناعي يُحلّل بعمق (8 محاور)
        # ══════════════════════════════════════════════════════════
        upd(
            f"🔍 *DeepSearch: {topic}*\n\n"
            f"✅ `[1/6]` تحليل المدخلات\n"
            f"✅ `[2/6]` جمع المعلومات — {len(all_raw)} نتيجة\n"
            f"✅ `[3/6]` فلترة المصادر — {len(trusted)} موثوق، {len(acceptable)} مقبول\n"
            f"`[4/6]` 🧠 الذكاء الاصطناعي يُحلّل بعمق (8 محاور)..."
        )

        recent_context = ""
        if recent_news:
            recent_context = "\n\n📰 أحدث المعلومات من المصادر الموثوقة:\n" + "\n".join([
                f"• [{item['title']}]({item.get('link','')})"
                + (f": {item['summary'][:120]}" if item.get('summary') else "")
                for item in recent_news[:10]
            ])

        # تخصيص الـ prompt بحسب النية والمجال
        intent_instruction = {
            "definition":  "ابدأ بتعريف دقيق وشامل ثم وسّع.",
            "steps":       "قدّم خطوات عملية واضحة ومرقّمة.",
            "news":        "ركّز على أحدث التطورات والأحداث.",
            "statistics":  "أبرز الأرقام والإحصاءات والبيانات.",
            "advice":      "قدّم توصيات عملية قابلة للتطبيق.",
            "analysis":    "قدّم تحليلاً استراتيجياً معمقاً.",
        }.get(intent, "")

        ai_report = None
        if _AI_MODEL:
            prompt = f"""أنت خبير تحليلي ومحقق صحفي متعمق في مجال {domain_labels.get(domain,'عام')}.

الموضوع: {topic}
النية: {intent_labels.get(intent, intent)} — {intent_instruction}
{recent_context}

اكتب تقريراً بحثياً شاملاً يشمل بالتفصيل:

🧵 **تقرير DeepSearch: {topic}**

**1/ الخلفية والسياق**
(من أين بدأ هذا الموضوع؟ التاريخ والأسباب الجذرية)

**2/ الوضع الراهن والمعطيات**
(ما الذي يحدث الآن؟ حقائق وأرقام محددة)

**3/ الأطراف والمحاور الرئيسية**
(من هم اللاعبون؟ مواقفهم ومصالحهم)

**4/ التحليل العميق**
(لماذا حدث هذا؟ الأسباب الحقيقية والخفية)

**5/ ما لا تقوله وسائل الإعلام**
(ما يُهمَل أو يُتجنّب في التغطية الإعلامية المعتادة)

**6/ التداعيات والانعكاسات**
(كيف يؤثر هذا إقليمياً ودولياً؟)

**7/ سيناريوهات المستقبل**
(توقعات واقعية لما قد يحدث لاحقاً)

**8/ خلاصة الخبير**
(رأيك التحليلي الصريح في سطرين)

قواعد صارمة:
- استخدم معرفتك الشاملة أساساً والأخبار المذكورة سياقاً
- كن محدداً: أسماء، تواريخ، أرقام — لا كلام فضفاض
- لا مقدمات عامة — ابدأ مباشرة من المحتوى
- اكتب بلغة المستخدم: {'العربية' if 'عربية' in lang or 'English' not in lang else 'English'}
- تحليل جريء ومباشر"""
            try:
                response = _AI_MODEL.generate_content(prompt)
                ai_report = response.text.strip()
            except Exception:
                ai_report = None

        # ══════════════════════════════════════════════════════════
        # 5️⃣ الخطوة 5: تجميع التقرير النهائي مع المصادر
        # ══════════════════════════════════════════════════════════
        upd(
            f"🔍 *DeepSearch: {topic}*\n\n"
            f"✅ `[1/6]` تحليل المدخلات\n"
            f"✅ `[2/6]` جمع المعلومات — {len(all_raw)} نتيجة\n"
            f"✅ `[3/6]` فلترة المصادر — {len(trusted)} موثوق\n"
            f"✅ `[4/6]` تحليل الذكاء الاصطناعي {'✓' if ai_report else '(غير متاح)'}\n"
            f"`[5/6]` 📝 أجمّع التقرير النهائي مع المصادر..."
        )
        time.sleep(0.5)

        if ai_report:
            header = (
                f"🔍 *DeepSearch — {intent_labels.get(intent,'تحليل')} | {domain_labels.get(domain,'عام')}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 *{topic}*\n"
                f"🔎 فُحص: {len(all_raw)} مصدر | موثوق: {len(trusted)} | مقبول: {len(acceptable)}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            full_report = header + ai_report
        else:
            header = (
                f"🔍 *DeepSearch — نتائج المصادر*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 *{topic}*\n"
                f"⚠️ الذكاء الاصطناعي غير متاح — عرض نتائج المصادر الموثوقة:\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            full_report = header + (
                "\n\n".join([
                    f"📰 *{item['title']}*"
                    + (f"\n_{item['summary'][:150]}_" if item.get('summary') else "")
                    + (f"\n🔗 [المصدر]({item['link']})" if item.get('link') else "")
                    for item in recent_news[:12]
                ]) if recent_news else "⚠️ لم يُعثر على نتائج ذات صلة."
            )

        # ── قسم المصادر الموثوقة ──
        if recent_news and ai_report:
            sources_sec = "\n\n━━━━━━━━━━━━━━━━━━━━\n📚 *المصادر الموثوقة المستخدمة:*\n"
            for item in recent_news[:8]:
                t_  = item.get('title', '')[:55]
                lnk = item.get('link', '')
                rel = item.get('reliability', 0)
                stars = "⭐" * min(rel // 2, 5)
                if lnk:
                    sources_sec += f"{stars} [{t_}]({lnk})\n"
                else:
                    sources_sec += f"{stars} {t_}\n"
            full_report += sources_sec

        # ── توقيع البوت ──
        full_report += f"\n\n━━━━━━━━━━━━━━━━━━━━\n🤖 *@{BOT_USERNAME}* | DeepSearch v2.0"

        # ══════════════════════════════════════════════════════════
        # 6️⃣ الخطوة 6: عرض النتيجة للمستخدم
        # ══════════════════════════════════════════════════════════
        upd(
            f"🔍 *DeepSearch: {topic}*\n\n"
            f"✅ `[1/6]` تحليل المدخلات\n"
            f"✅ `[2/6]` جمع المعلومات — {len(all_raw)} نتيجة\n"
            f"✅ `[3/6]` فلترة المصادر — {len(trusted)} موثوق\n"
            f"✅ `[4/6]` تحليل الذكاء الاصطناعي\n"
            f"✅ `[5/6]` تجميع التقرير\n"
            f"`[6/6]` 📤 يُرسل التقرير إليك..."
        )
        time.sleep(0.5)

        # تقسيم التقرير الطويل إلى رسائل (حد 3800 حرف)
        chunks = []
        current = ""
        for line in full_report.split('\n'):
            if len(current) + len(line) + 1 > 3800:
                chunks.append(current)
                current = line + '\n'
            else:
                current += line + '\n'
        if current:
            chunks.append(current)

        for i, chunk in enumerate(chunks):
            try:
                if i == 0:
                    bot.edit_message_text(chunk.strip(), chat_id, progress_msg_id,
                                          parse_mode="Markdown",
                                          disable_web_page_preview=True)
                else:
                    bot.send_message(chat_id, chunk.strip(),
                                     parse_mode="Markdown",
                                     disable_web_page_preview=True)
            except Exception:
                try:
                    bot.send_message(chat_id, chunk.strip(),
                                     parse_mode="Markdown",
                                     disable_web_page_preview=True)
                except Exception:
                    pass

    except Exception as e:
        try:
            bot.edit_message_text(f"❌ خطأ في DeepSearch: {e}", chat_id, progress_msg_id)
        except Exception:
            pass
    finally:
        _deepsearch_active.pop(str(uid), None)


def broadcast_to_channels():
    """
    يُعالج فقط القنوات/المجموعات ذات المصادر المخصصة.
    القنوات العادية تحصل على أخبارها من broadcast_news مباشرة.
    """
    if bot_paused or broadcast_paused:
        return
    if _broadcast_channels_lock.is_set():
        return
    _broadcast_channels_lock.set()
    _broadcast_ch_lock_ts[0] = time.time()
    try:
        custom_chs = [ch for ch in channels_groups if ch.get('custom_sources') and not ch.get('paused')]
        if not custom_chs:
            return
        changed = False
        for ch in custom_chs:
            try:
                chat_id = ch["id"]
                lang = ch.get('lang', 'العربية 🇮🇶')
                custom_sources = ch.get('custom_sources', [])
                feeds = custom_sources if custom_sources else RSS.get(lang, RSS.get('العربية 🇮🇶', []))
                sent = set(ch.setdefault('sent_news', []))
                candidates = []

                # --- 1: RSS — يقرأ من _global_rss_cache فقط (لا جلب متزامن) ---
                # إذا لم يكن feed_url في الكاش بعد، نجلبه بشكل متوازٍ مرة واحدة
                missing = []
                with _global_rss_cache_lock:
                    for feed_url in feeds:
                        if feed_url not in _global_rss_cache:
                            missing.append(feed_url)
                if missing:
                    def _fetch_m(url):
                        entries = _fetch_one_feed(url)
                        with _global_rss_cache_lock:
                            _global_rss_cache[url] = (entries, time.time())
                    with ThreadPoolExecutor(max_workers=min(8, len(missing))) as _ex:
                        _futs = {_ex.submit(_fetch_m, u): u for u in missing}
                        for _f in as_completed(_futs, timeout=20):
                            try: _f.result()
                            except Exception: pass

                with _global_rss_cache_lock:
                    all_ch_entries = []
                    for feed_url in feeds:
                        cached = _global_rss_cache.get(feed_url)
                        if cached:
                            all_ch_entries.extend(cached[0])

                for entry in all_ch_entries:
                    link  = entry.get("link", "")
                    title = entry.get("title", "")
                    if not link or link in sent:
                        continue
                    if is_blacklisted(title):
                        continue
                    pub_dt = entry.get("published_dt")
                    if pub_dt is not None and not _is_fresh(pub_dt):
                        continue
                    candidates.append((link, title, entry.get("feed_url", ""), entry.get("summary", ""), pub_dt))

                # --- 2: Scraping مواقع إخبارية ---
                if _BS4_AVAILABLE and not custom_sources:
                    for src in SCRAPE_SOURCES.get(lang, []):
                        try:
                            scraped = _scrape_news_site(src['url'], src['base_url'], max_items=10)
                            for s_title, s_link in scraped:
                                if s_link in sent or is_blacklisted(s_title):
                                    continue
                                if not _title_in_lang(s_title, lang):
                                    continue
                                candidates.append((s_link, s_title, src['url'], '', None))
                        except Exception:
                            pass

                # --- 3: قنوات تلغرام (حصة مضمونة 30 خبر) ---
                if _BS4_AVAILABLE and not custom_sources:
                    tg_collected = 0
                    for tg_ch in TELEGRAM_NEWS_CHANNELS.get(lang, []):
                        if tg_collected >= 9999:
                            break
                        try:
                            tg_posts = _scrape_telegram_channel(tg_ch['handle'], max_items=8)
                            for raw_text, tg_link in tg_posts:
                                if tg_collected >= 9999:
                                    break
                                # تطبيع الرابط: تجاهل معاملات URL لمنع تكرار نفس الخبر برابط مختلف
                                uid_key = _normalize_news_link(tg_link) if tg_link else raw_text[:80]
                                if uid_key in sent or is_blacklisted(raw_text):
                                    continue
                                if _is_tg_spam(raw_text, tg_link):
                                    continue
                                clean_title = _ai_clean_news(raw_text, link=tg_link)
                                if not clean_title or len(clean_title) < 15:
                                    continue
                                src_label = f"t.me/{tg_ch['handle']}"
                                candidates.append((tg_link or uid_key, clean_title, src_label, raw_text, None))
                                tg_collected += 1
                        except Exception:
                            pass

                # --- 4: NewsAPI ---
                if NEWS_KEY and not custom_sources:
                    try:
                        lang_code = LANG_CODES.get(lang, "ar")
                        na_url = (
                            f"https://newsapi.org/v2/top-headlines"
                            f"?language={lang_code}&pageSize=10&apiKey={NEWS_KEY}"
                        )
                        na_r = requests.get(na_url, timeout=8)
                        if na_r.status_code == 200:
                            for art in na_r.json().get("articles", []):
                                na_link  = art.get("url", "")
                                na_title = art.get("title", "")
                                na_desc  = art.get("description", "") or ""
                                if na_link and na_title and na_link not in sent:
                                    if not is_blacklisted(na_title):
                                        src_name = art.get("source", {}).get("name", "NewsAPI")
                                        na_pub_str = art.get("publishedAt", "")
                                        try:
                                            na_pub_dt = datetime.datetime.strptime(
                                                na_pub_str, "%Y-%m-%dT%H:%M:%SZ"
                                            ) if na_pub_str else None
                                        except Exception:
                                            na_pub_dt = None
                                        candidates.append((na_link, na_title, src_name, na_desc, na_pub_dt))
                    except Exception:
                        pass

                # --- فلتر اللغة + كشف التكرار الذكي ---
                candidates = [c for c in candidates if _title_in_lang(c[1], lang)]
                candidates = _dedup_news_list(candidates)

                # --- إرسال حتى MAX_NEWS_PER_BROADCAST خبر ---
                sent_this_channel = 0
                for cand in candidates:
                    if sent_this_channel >= MAX_NEWS_PER_BROADCAST:
                        break
                    link  = cand[0]
                    title = cand[1]
                    feed_url     = cand[2]
                    item_summary = cand[3]
                    pub_dt       = cand[4] if len(cand) > 4 else None
                    # تطبيع الرابط: إزالة معاملات URL (timestamps, utm_source) لمنع تكرار نفس الخبر
                    link_key = _normalize_news_link(link) if link else title[:80]
                    title_key = title.strip()[:70]  # تتبع العنوان لمنع التكرار بروابط مختلفة
                    if link_key in sent or title_key in sent:
                        continue
                    sent.add(link_key)
                    sent.add(title_key)
                    ch["sent_news"] = list(sent)[-5000:]
                    ch["news_sent_count"] = ch.get("news_sent_count", 0) + 1
                    changed = True
                    sent_this_channel += 1
                    src_name = get_source_name_from_url(feed_url)
                    pub_time_str = _format_pub_time(pub_dt, lang=lang)
                    # AI تنظيف العنوان لأخبار RSS/Scraping (قنوات TG نُنظَّف مسبقاً)
                    if _AI_AVAILABLE and not str(feed_url).startswith("t.me/"):
                        try:
                            _clean = _ai_clean_news(title, body=item_summary[:600] if item_summary else '', link=link)
                            if _clean and len(_clean) > 10:
                                title = _clean
                        except Exception:
                            pass
                    markup = make_news_share_markup(link, title, lang, item_summary)
                    news_text = format_news_item(t(lang, "label_breaking"), title, lang, src_name, pub_time_str, summary=item_summary)
                    img_sent = False
                    if _should_send_with_image(title):
                        try:
                            img_url = _get_og_image(link, timeout=4)
                            if img_url:
                                bot.send_photo(chat_id, img_url, caption=news_text[:1024],
                                               parse_mode="Markdown", reply_markup=markup)
                                img_sent = True
                        except Exception:
                            pass
                    if not img_sent:
                        queue_send(chat_id, news_text, parse_mode="Markdown", reply_markup=markup)
            except Exception:
                continue
        if changed:
            save_channels_groups()
    except Exception as e:
        try:
            bot.send_message(ADMIN_ID, f"⚠️ خطأ في broadcast_to_channels: {e}")
        except Exception:
            pass
    finally:
        _broadcast_channels_lock.clear()

def breaking_news_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    lines = message.text.strip().split("\n")
    news_text = lines[0].strip()
    link = lines[1].strip() if len(lines) > 1 and lines[1].startswith("http") else ""
    full_msg = f"🚨 *خبر عاجل*\n\n📰 {news_text}{BOT_SIGNATURE}"
    sent_users = 0
    failed_users = 0
    for target_uid in list(users.keys()):
        if int(target_uid) in banned:
            continue
        try:
            user_lang = users.get(target_uid, {}).get("lang", "English 🇬🇧")
            user_markup = make_news_share_markup(link, news_text, user_lang) if link else None
            bot.send_message(target_uid, full_msg, parse_mode="Markdown", reply_markup=user_markup)
            sent_users += 1
        except:
            failed_users += 1
    sent_ch = 0
    for ch in list(channels_groups):
        try:
            ch_lang = ch.get("lang", "العربية 🇮🇶")
            ch_markup = make_news_share_markup(link, news_text, ch_lang) if link else None
            bot.send_message(ch["id"], full_msg, parse_mode="Markdown", reply_markup=ch_markup)
            sent_ch += 1
        except:
            pass
    bot.send_message(uid,
        f"✅ *تم إرسال الخبر العاجل:*\n\n"
        f"👤 المستخدمون: `{sent_users}` وصل، `{failed_users}` فشل\n"
        f"📺 القنوات/المجموعات: `{sent_ch}` وصل",
        parse_mode="Markdown"
    )

def bl_add_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    words_input = message.text.strip()
    new_words = [w.strip() for w in words_input.replace("،", ",").split(",") if w.strip()]
    added = []
    for w in new_words:
        if w not in blacklist_words:
            blacklist_words.append(w)
            added.append(w)
    save_blacklist()
    bot.send_message(uid,
        f"✅ تم إضافة `{len(added)}` كلمة للقائمة السوداء:\n" +
        "\n".join(f"• `{w}`" for w in added),
        parse_mode="Markdown"
    )

def bl_remove_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    word = message.text.strip()
    if word in blacklist_words:
        blacklist_words.remove(word)
        save_blacklist()
        bot.send_message(uid, f"✅ تم حذف الكلمة `{word}` من القائمة السوداء.", parse_mode="Markdown")
    else:
        bot.send_message(uid, f"⚠️ الكلمة `{word}` غير موجودة في القائمة.", parse_mode="Markdown")

def search_user_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    query = message.text.strip().lower()
    results = []
    for u_id, u_info in users.items():
        name = u_info.get("name", "").lower()
        if query == u_id or query in name:
            results.append((u_id, u_info))
    if not results:
        bot.send_message(uid, "❌ لم يُعثَر على مستخدم بهذا ID أو الاسم.")
        return
    for u_id, u_info in results[:5]:
        notif = "✅" if u_info.get("notifications", True) else "❌"
        is_pr = int(u_id) in stats.get("premium_users", [])
        msg = (
            f"👤 *نتيجة البحث*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{u_id}`\n"
            f"👤 الاسم: *{u_info.get('name', '—')}*\n"
            f"🗣 اللغة: {u_info.get('lang', '-')}\n"
            f"🌍 الدولة: {u_info.get('country', '-')}\n"
            f"📅 الانضمام: `{u_info.get('join_date', '-')}`\n"
            f"🔔 إشعارات: {notif} | ⭐ مميز: {'نعم' if is_pr else 'لا'}"
        )
        view_markup = types.InlineKeyboardMarkup(row_width=2)
        view_markup.add(
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{u_id}"),
            types.InlineKeyboardButton("⭐ ترقية", callback_data=f"quick_premium_{u_id}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={u_id}"),
        )
        bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=view_markup)

def msg_user_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    lines = message.text.strip().split("\n")
    if len(lines) < 2:
        bot.send_message(uid, "❌ أرسل في سطرين: السطر 1 ID المستخدم، السطر 2 الرسالة.")
        return
    try:
        target_id = int(lines[0].strip())
        msg_text = "\n".join(lines[1:]).strip()
        bot.send_message(target_id, f"📩 *رسالة من الإدارة:*\n\n{msg_text}", parse_mode="Markdown")
        bot.send_message(uid, f"✅ تم إرسال الرسالة للمستخدم `{target_id}` بنجاح.", parse_mode="Markdown")
    except ValueError:
        bot.send_message(uid, "❌ ID غير صحيح.")
    except Exception as e:
        bot.send_message(uid, f"❌ فشل الإرسال: {e}")

# ======== معالج عداد القراءة (لجميع المستخدمين) ========
@bot.callback_query_handler(func=lambda c: c.data == "read_open")
def handle_read_open(call):
    today = str(datetime.date.today())
    read_stats["total_opens"] = read_stats.get("total_opens", 0) + 1
    read_stats.setdefault("daily", {})[today] = read_stats["daily"].get(today, 0) + 1
    save_read_stats()
    bot.answer_callback_query(call.id)

# ======== معالج زر ملخص الخبر ========
@bot.callback_query_handler(func=lambda c: c.data.startswith("sum_"))
def handle_summary_button(call):
    uid = call.from_user.id
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    lbl = NEWS_SHARE_LABELS.get(lang, NEWS_SHARE_LABELS["English 🇬🇧"])
    sum_key = call.data[4:]
    cached = _news_summary_cache.get(sum_key)
    if not cached:
        bot.answer_callback_query(call.id, lbl["no_summary"], show_alert=True)
        return
    # دعم الكاش القديم (نص مباشر) والجديد (dict)
    if isinstance(cached, dict):
        summary_text = cached.get("text", "")
        news_title   = cached.get("title", "")
    else:
        summary_text = cached
        news_title   = ""
    clean = _clean_html(summary_text)
    if not clean:
        bot.answer_callback_query(call.id, lbl["no_summary"], show_alert=True)
        return
    bot.answer_callback_query(call.id)
    # إذا كان النص طويلاً (منشور قناة تلغرام أو مقال كامل) → توليد ملخص AI احترافي
    # إذا كان قصيراً (ملخص RSS جاهز) → تنظيف بسيط فقط
    if _AI_AVAILABLE and len(clean) > 120:
        try:
            clean = _ai_generate_summary(clean, title=news_title, lang=lang)
        except Exception:
            pass
    elif _AI_AVAILABLE and news_title:
        try:
            clean = _ai_clean_news(news_title, body=clean[:800])
        except Exception:
            pass
    # بناء رسالة الملخص الجميلة
    separator = "━━━━━━━━━━━━━━"
    title_line = f"📰 *{escape_md(news_title)}*\n{separator}\n" if news_title else ""
    full_msg = (
        f"{title_line}"
        f"📄 *{lbl['summary_btn']}*\n\n"
        f"{escape_md(clean[:1800])}\n"
        f"{separator}"
    )
    bot.send_message(uid, full_msg, parse_mode="Markdown", disable_web_page_preview=True)
    user["used_summary"] = True
    _db_save_user(uid, user)

# ======== معالج زر متابعة القصة ========
@bot.callback_query_handler(func=lambda c: c.data.startswith("follow_story_"))
def handle_follow_story_button(call):
    uid = call.from_user.id
    if uid in banned:
        bot.answer_callback_query(call.id)
        return
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    lbl = NEWS_SHARE_LABELS.get(lang, NEWS_SHARE_LABELS["English 🇬🇧"])
    story_key = call.data[len("follow_story_"):]
    keyword = _story_key_cache.get(story_key, "")
    if not keyword:
        bot.answer_callback_query(call.id, "⚠️", show_alert=False)
        return
    # تحقق إذا يتابع بالفعل
    followed = user.get("followed_stories", [])
    if keyword in followed:
        # عرض خيار إلغاء المتابعة
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            lbl.get("unfollow_story", "🔕 Unfollow"),
            callback_data=f"unfollow_story_{story_key}"
        ))
        bot.answer_callback_query(call.id, lbl.get("already_following", "Already following."), show_alert=True)
        return
    # أضف للمتابعة
    if keyword not in _story_followers:
        _story_followers[keyword] = {}
    _story_followers[keyword][str(uid)] = lang
    followed.append(keyword)
    user["followed_stories"] = followed
    _db_save_user(uid, user)
    bot.answer_callback_query(call.id, lbl.get("follow_done", "✅ You'll get updates!"), show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("unfollow_story_"))
def handle_unfollow_story_button(call):
    uid = call.from_user.id
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    lbl = NEWS_SHARE_LABELS.get(lang, NEWS_SHARE_LABELS["English 🇬🇧"])
    story_key = call.data[len("unfollow_story_"):]
    keyword = _story_key_cache.get(story_key, "")
    if keyword:
        _story_followers.pop(keyword, None)
        followed = user.get("followed_stories", [])
        if keyword in followed:
            followed.remove(keyword)
        user["followed_stories"] = followed
        _db_save_user(uid, user)
    bot.answer_callback_query(call.id, lbl.get("unfollow_done", "✅ Unfollowed."), show_alert=True)

# ======== قائمة الأخبار الصوتية ========
def _send_voice_news_menu(uid):
    """إرسال قائمة اختيار عدد الأخبار الصوتية"""
    user = users.get(str(uid), {})
    lang = user.get("lang", "العربية 🇮🇶")
    if not _TTS_AVAILABLE:
        bot.send_message(uid, "⚠️ خاصية الأخبار الصوتية غير متاحة حالياً.")
        return
    labels = {
        "العربية 🇮🇶": ("🎙️ كم خبر تريد أن تسمع؟", "خبر واحد", "3 أخبار", "5 أخبار", "10 أخبار"),
        "English 🇬🇧": ("🎙️ How many news do you want to hear?", "1 news", "3 news", "5 news", "10 news"),
        "Русский 🇷🇺": ("🎙️ Сколько новостей?", "1 новость", "3 новости", "5 новостей", "10 новостей"),
        "Türkçe 🇹🇷": ("🎙️ Kaç haber duymak istersiniz?", "1 haber", "3 haber", "5 haber", "10 haber"),
        "Deutsch 🇩🇪": ("🎙️ Wie viele Nachrichten?", "1 Nachricht", "3 Nachrichten", "5 Nachrichten", "10 Nachrichten"),
        "Español 🇲🇽": ("🎙️ ¿Cuántas noticias?", "1 noticia", "3 noticias", "5 noticias", "10 noticias"),
    }
    lbl = labels.get(lang, labels["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"1️⃣ {lbl[1]}", callback_data="tts_1"),
        types.InlineKeyboardButton(f"3️⃣ {lbl[2]}", callback_data="tts_3"),
        types.InlineKeyboardButton(f"5️⃣ {lbl[3]}", callback_data="tts_5"),
        types.InlineKeyboardButton(f"🔟 {lbl[4]}", callback_data="tts_10"),
    )
    bot.send_message(uid, lbl[0], reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tts_"))
def handle_voice_news_count(call):
    uid = call.from_user.id
    count = int(call.data.split("_")[1])
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    threading.Thread(target=send_voice_news, args=(uid, count), daemon=True).start()

# ======== Inline Mode — البحث في الأخبار من أي محادثة ========
@bot.inline_handler(func=lambda q: True)
def handle_inline_query(query):
    uid = query.from_user.id
    q_text = query.query.strip()
    user = users.get(str(uid), {})
    lang = user.get("lang", "العربية 🇮🇶")
    results = []
    try:
        # جلب أخبار من RSS للغة المستخدم
        feeds = RSS.get(lang, RSS.get("العربية 🇮🇶", []))
        candidates = []
        for feed_url in feeds[:4]:
            try:
                parsed = feedparser.parse(feed_url)
                for entry in parsed.entries[:10]:
                    title = getattr(entry, 'title', '').strip()
                    link = getattr(entry, 'link', '')
                    if not title or not link:
                        continue
                    if q_text and q_text.lower() not in title.lower():
                        continue
                    candidates.append((title, link))
                    if len(candidates) >= 20:
                        break
            except Exception:
                pass
            if len(candidates) >= 20:
                break

        # إذا ما في بحث، خذ أحدث الأخبار
        if not q_text and not candidates:
            for feed_url in feeds[:2]:
                try:
                    parsed = feedparser.parse(feed_url)
                    for entry in parsed.entries[:8]:
                        title = getattr(entry, 'title', '').strip()
                        link = getattr(entry, 'link', '')
                        if title and link:
                            candidates.append((title, link))
                except Exception:
                    pass

        for i, (title, link) in enumerate(candidates[:15]):
            results.append(
                types.InlineQueryResultArticle(
                    id=str(i),
                    title=title[:100],
                    input_message_content=types.InputTextMessageContent(
                        f"📰 {title}\n\n🔗 {link}"
                    ),
                    description=link[:80],
                    url=link,
                    hide_url=True,
                )
            )
    except Exception:
        pass

    if not results:
        results.append(
            types.InlineQueryResultArticle(
                id="0",
                title="🔍 لا توجد نتائج" if lang == "العربية 🇮🇶" else "🔍 No results found",
                input_message_content=types.InputTextMessageContent("لا توجد أخبار متاحة الآن."),
                description="حاول لاحقاً" if lang == "العربية 🇮🇶" else "Try again later",
            )
        )
    try:
        bot.answer_inline_query(query.id, results, cache_time=60)
    except Exception:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_bot_") or c.data.startswith("rate_news_"))
def handle_rating(call):
    uid = call.from_user.id
    data = call.data
    try:
        parts = data.split("_")
        # إصلاح #12: استخدام parts[-1] لأمان أكثر (rate_bot_5 أو rate_news_5)
        rtype = parts[1]
        stars = int(parts[-1])
        bot.answer_callback_query(call.id, f"✅ شكراً! قيّمت بـ {stars}⭐")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        if rtype == "bot":
            ratings_data["bot_sum"] = ratings_data.get("bot_sum", 0) + stars
            ratings_data["count"] = ratings_data.get("count", 0) + 1
        elif rtype == "news":
            ratings_data["news_sum"] = ratings_data.get("news_sum", 0) + stars
        ratings_data.setdefault("entries", []).append({
            "uid": uid, "type": rtype, "stars": stars,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        save_ratings()
        # تحديث إحصائيات المستخدم الشخصية
        if str(uid) in users:
            if stars >= 4:
                users[str(uid)]["rated_positive"] = users[str(uid)].get("rated_positive", 0) + 1
            elif stars <= 2:
                users[str(uid)]["rated_negative"] = users[str(uid)].get("rated_negative", 0) + 1
            _db_save_user(uid, users[str(uid)])
    except Exception:
        pass

# ======== إيقاف الأخبار مؤقتاً للمستخدم ========
@bot.callback_query_handler(func=lambda c: c.data.startswith("pause_news_"))
def handle_pause_news(call):
    uid = call.from_user.id
    data = call.data
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    user = users.get(str(uid), {})
    lang = user.get("lang", "العربية 🇮🇶")
    if data == "pause_news_cancel":
        bot.send_message(uid, "↩️ تم الإلغاء، الأخبار لا تزال مفعّلة.")
    elif data == "pause_news_off":
        users[str(uid)]["notifications"] = False
        users[str(uid)].pop("news_paused_until", None)
        _db_save_user(str(uid), users[str(uid)])
        bot.send_message(uid, "❌ تم إيقاف الأخبار نهائياً.\nاضغط زر الإشعارات لإعادة التفعيل.")
        send_main_menu(uid)
    else:
        hours_map = {"pause_news_1h": 1, "pause_news_6h": 6, "pause_news_24h": 24}
        hours = hours_map.get(data, 1)
        # نستخدم _now_sa() لضمان التطابق مع المقارنة في broadcast_news
        paused_until = (_now_sa() + datetime.timedelta(hours=hours)).isoformat()
        users[str(uid)]["news_paused_until"] = paused_until
        _db_save_user(str(uid), users[str(uid)])
        label = f"{hours} ساعة" if hours == 1 else f"{hours} ساعات" if hours < 24 else "يوم كامل"
        bot.send_message(uid, f"⏸ تم إيقاف الأخبار لمدة *{label}*.\nستعود تلقائياً بعد انتهاء المدة.", parse_mode="Markdown")

# ======== خطوات إدارة الأدمن ========
def add_admin_step(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id == ADMIN_ID:
            bot.send_message(ADMIN_ID, "⚠️ هذا هو الأدمن الرئيسي بالفعل.")
            return
        if new_admin_id in extra_admins:
            bot.send_message(ADMIN_ID, "⚠️ هذا المستخدم أدمن بالفعل.")
            return
        extra_admins.append(new_admin_id)
        save_extra_admins()
        bot.send_message(ADMIN_ID, f"✅ تم تعيين المستخدم `{new_admin_id}` كأدمن.", parse_mode="Markdown")
        try:
            bot.send_message(new_admin_id, "👑 تم تعيينك كأدمن في البوت.\nاستخدم /admin للوصول للوحة التحكم.")
        except:
            pass
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

def remove_admin_step(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target_id = int(message.text.strip())
        if target_id not in extra_admins:
            bot.send_message(ADMIN_ID, "⚠️ هذا المستخدم ليس أدمن إضافياً.")
            return
        extra_admins.remove(target_id)
        save_extra_admins()
        bot.send_message(ADMIN_ID, f"✅ تم إزالة الأدمن `{target_id}`.", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "⚠️ تم إلغاء صلاحيات الأدمن الخاصة بك.")
        except:
            pass
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ خطأ: {e}")

# ======== خطوات الأدمن ========
def get_user_info(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = str(message.text.strip())
        user = users.get(target_id)
        if not user:
            bot.send_message(message.from_user.id, "❌ المستخدم غير موجود.")
            return
        is_banned_user = int(target_id) in banned
        is_premium_user = int(target_id) in stats.get("premium_users", [])
        is_admin_user = is_admin(int(target_id))
        referrals = user.get("referrals", [])
        referred_by = user.get("referred_by", None)
        join_date = user.get("join_date", "غير معروف")
        interests = user.get("interests", [])
        notif = "✅ مفعّل" if user.get("notifications", True) else "❌ موقوف"
        track_data = tracked_assets.get(target_id, {})
        tracked = track_data.get("assets", [])
        msg = (
            f"👤 *ملف المستخدم الكامل*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 ID: `{target_id}`\n"
            f"👤 الاسم: *{user.get('name', 'غير معروف')}*\n"
            f"🗣 اللغة: {user.get('lang', '-')}\n"
            f"🌍 الدولة: {user.get('country', '-')}\n"
            f"📍 المحافظة: {user.get('province', '-')}\n"
            f"📅 تاريخ الانضمام: `{join_date}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"🚫 محظور: {'✅ نعم' if is_banned_user else '❌ لا'}\n"
            f"⭐ مميز: {'✅ نعم' if is_premium_user else '❌ لا'}\n"
            f"👑 أدمن: {'✅ نعم' if is_admin_user else '❌ لا'}\n"
            f"🔔 الإشعارات: {notif}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎁 دعواته: `{len(referrals)}` شخص\n"
            f"👈 جاء عبر: `{referred_by if referred_by else 'مباشر'}`\n"
            f"📌 أصوله المتتبعة: `{', '.join(tracked) if tracked else 'لا يوجد'}`\n"
            f"📰 اهتماماته: `{', '.join(interests) if interests else 'لم يختر'}`\n"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{target_id}"),
            types.InlineKeyboardButton("⭐ ترقية مميز", callback_data=f"quick_premium_{target_id}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={target_id}"),
        )
        bot.send_message(message.from_user.id, msg, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def ban_user_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if target_id not in banned:
            banned.append(target_id)
            save_json(BANNED_FILE, banned)
        bot.send_message(message.from_user.id, f"✅ تم حظر المستخدم `{target_id}`", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "🚫 تم حظرك من استخدام البوت.")
        except:
            pass
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def unban_user_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if target_id in banned:
            banned.remove(target_id)
            save_json(BANNED_FILE, banned)
            bot.send_message(message.from_user.id, f"✅ تم رفع حظر المستخدم `{target_id}`", parse_mode="Markdown")
        else:
            bot.send_message(message.from_user.id, "⚠️ المستخدم غير محظور.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def promote_premium_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if "premium_users" not in stats:
            stats["premium_users"] = []
        if target_id not in stats["premium_users"]:
            stats["premium_users"].append(target_id)
            save_json(STATS_FILE, stats)
        bot.send_message(message.from_user.id, f"⭐ تم ترقية المستخدم `{target_id}` للمميز.", parse_mode="Markdown")
        try:
            bot.send_message(target_id, "⭐ تهانينا! تمت ترقيتك لحساب مميز.")
        except:
            pass
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def demote_premium_step(message):
    if not is_admin(message.from_user.id):
        return
    try:
        target_id = int(message.text.strip())
        if target_id in stats.get("premium_users", []):
            stats["premium_users"].remove(target_id)
            save_json(STATS_FILE, stats)
            bot.send_message(message.from_user.id, f"✅ تم إلغاء الاشتراك المميز للمستخدم `{target_id}`", parse_mode="Markdown")
        else:
            bot.send_message(message.from_user.id, "⚠️ المستخدم ليس مميزاً.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def broadcast_all_step(message):
    if not is_admin(message.from_user.id):
        return
    text = message.text
    count, failed = 0, 0
    for uid in list(users.keys()):
        try:
            bot.send_message(uid, text)
            count += 1
        except:
            failed += 1
    bot.send_message(message.from_user.id, f"📢 *تم الإرسال:*\n✅ نجح: `{count}`\n❌ فشل: `{failed}`", parse_mode="Markdown")

def broadcast_country_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل الدولة ثم الرسالة في سطرين.")
        return
    country, text = lines[0].strip(), lines[1].strip()
    count = 0
    for uid, info in list(users.items()):
        if info.get("country") == country:
            try:
                bot.send_message(uid, text)
                count += 1
            except:
                pass
    bot.send_message(message.from_user.id, f"✅ تم الإرسال لـ `{count}` مستخدم في {country}", parse_mode="Markdown")

def broadcast_lang_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل اللغة ثم الرسالة في سطرين.")
        return
    lang, text = lines[0].strip(), lines[1].strip()
    count = 0
    for uid, info in list(users.items()):
        if info.get("lang") == lang:
            try:
                bot.send_message(uid, text)
                count += 1
            except:
                pass
    bot.send_message(message.from_user.id, f"✅ تم الإرسال لـ `{count}` مستخدم يتحدث {lang}", parse_mode="Markdown")

def broadcast_premium_step(message):
    if not is_admin(message.from_user.id):
        return
    text = message.text
    count = 0
    for uid in stats.get("premium_users", []):
        try:
            bot.send_message(uid, text)
            count += 1
        except:
            pass
    bot.send_message(message.from_user.id, f"⭐ تم الإرسال لـ `{count}` مستخدم مميز", parse_mode="Markdown")

def pause_bot_step(message):
    global bot_paused, pause_message, _pause_since
    if message.text.strip() != "افتراضي":
        pause_message = message.text.strip()
    bot_paused = True
    _pause_since = datetime.datetime.now()
    bot.send_message(message.from_user.id, "🔴 تم إيقاف البوت مؤقتاً.\nأرسل /admin ثم 'إيقاف/تشغيل البوت' لإعادة التشغيل.")

def _auto_discover_rss(url):
    """
    يكتشف رابط RSS من موقع ويب تلقائياً.
    يجرب أنماطاً شائعة مثل /feed, /rss, /rss.xml, /?feed=rss2 ...
    يعيد رابط RSS الصالح أو None إذا فشل.
    """
    if not url.startswith("http"):
        url = "https://" + url
    # إذا الرابط نفسه يبدو وكأنه RSS — تحقق منه مباشرة
    rss_patterns_suffix = ('.rss', '.xml', '/feed', '/rss', 'feed=rss', 'rss2', '/atom')
    is_direct = any(p in url.lower() for p in rss_patterns_suffix)
    candidates = [url] if is_direct else []
    # أضف أنماطاً قياسية
    base = url.rstrip('/')
    candidates += [
        f"{base}/feed",
        f"{base}/rss",
        f"{base}/rss.xml",
        f"{base}/feed.xml",
        f"{base}/index.xml",
        f"{base}/?feed=rss2",
        f"{base}/feeds/posts/default",
        f"{base}/atom.xml",
        f"{base}/news.rss",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0; +https://t.me/IraqnowBot)"}
    for cand in candidates:
        try:
            r = requests.head(cand, timeout=5, headers=headers, allow_redirects=True)
            if r.status_code == 200:
                ct = r.headers.get("Content-Type", "")
                if any(x in ct for x in ("xml", "rss", "atom", "feed")):
                    return cand
            # إذا HEAD لم يُخبرنا، جرّب feedparser مباشرة
            parsed = feedparser.parse(cand)
            if parsed.entries and len(parsed.entries) > 0:
                return cand
        except Exception:
            pass
    # محاولة أخيرة: ابحث عن رابط RSS في صفحة الموقع الرئيسية
    if not is_direct:
        try:
            r = requests.get(base, timeout=8, headers=headers)
            if r.status_code == 200 and _BS4_AVAILABLE:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, 'html.parser')
                for link_tag in soup.find_all('link', type=lambda t: t and ('rss' in t or 'atom' in t)):
                    href = link_tag.get('href', '')
                    if href:
                        if href.startswith('/'):
                            from urllib.parse import urlparse
                            parsed_url = urlparse(base)
                            href = f"{parsed_url.scheme}://{parsed_url.netloc}{href}"
                        return href
        except Exception:
            pass
    return None


def rss_add_step(message):
    if not is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    lines = message.text.strip().split("\n", 1)
    if len(lines) < 2:
        bot.send_message(uid, "❌ أرسل اللغة ثم الرابط في سطرين.")
        return
    lang, url = lines[0].strip(), lines[1].strip()
    # محاولة اكتشاف تلقائي إذا لم يبدُ الرابط وكأنه RSS مباشر
    bot.send_message(uid, f"🔍 يجرب الرابط ويكتشف إذا كان RSS...")
    discovered = _auto_discover_rss(url)
    if not discovered:
        bot.send_message(uid, f"❌ لم أستطع التحقق من الرابط كمصدر RSS صالح:\n`{url}`\n\nتأكد أنه يُرجع محتوى XML/RSS.", parse_mode="Markdown")
        return
    if lang not in RSS:
        RSS[lang] = []
    if discovered in RSS.get(lang, []):
        bot.send_message(uid, f"⚠️ المصدر موجود مسبقاً:\n`{discovered}`", parse_mode="Markdown")
        return
    RSS[lang].append(discovered)
    save_rss()
    diff = f"\n_(تم اكتشافه تلقائياً من: `{url}`)_" if discovered != url else ""
    bot.send_message(uid,
        f"✅ *تم إضافة المصدر بنجاح!*\n`{discovered}`{diff}\n\n📡 مصادر {lang}: *{len(RSS[lang])}*",
        parse_mode="Markdown"
    )

def rss_bulk_add_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = [l.strip() for l in message.text.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل اللغة في السطر الأول ثم الروابط في الأسطر التالية.")
        return
    lang = lines[0]
    urls = [l for l in lines[1:] if l.startswith("http")]
    skipped = [l for l in lines[1:] if not l.startswith("http")]
    if not urls:
        bot.send_message(message.from_user.id, "❌ لم أجد روابط صحيحة (يجب أن تبدأ بـ http).")
        return
    if lang not in RSS:
        RSS[lang] = []
    added = []
    duplicates = []
    for url in urls:
        if url in RSS[lang]:
            duplicates.append(url)
        else:
            RSS[lang].append(url)
            added.append(url)
    save_rss()
    report = f"✅ *تمت إضافة {len(added)} مصدر لـ {lang}*\n\n"
    if added:
        report += "➕ *المضافة:*\n" + "\n".join(f"`{u}`" for u in added) + "\n\n"
    if duplicates:
        report += f"⚠️ *مكررة (تجاهلتها):* {len(duplicates)}\n"
    if skipped:
        report += f"❌ *أسطر غير صالحة:* {len(skipped)}\n"
    report += f"\n📡 إجمالي مصادر {lang}: *{len(RSS[lang])}*"
    bot.send_message(message.from_user.id, report, parse_mode="Markdown")

def rss_remove_step(message):
    if not is_admin(message.from_user.id):
        return
    lines = message.text.split("\n", 1)
    if len(lines) < 2:
        bot.send_message(message.from_user.id, "❌ أرسل اللغة ثم رقم المصدر في سطرين.")
        return
    lang = lines[0].strip()
    try:
        index = int(lines[1].strip()) - 1
        if lang in RSS and 0 <= index < len(RSS[lang]):
            removed = RSS[lang].pop(index)
            save_rss()
            bot.send_message(message.from_user.id, f"✅ تم حذف المصدر:\n{removed}")
        else:
            bot.send_message(message.from_user.id, "❌ رقم أو لغة غير صحيحة.")
    except Exception as e:
        bot.send_message(message.from_user.id, f"❌ خطأ: {e}")

def change_welcome_step(message):
    global welcome_override
    if message.text.strip() == "افتراضي":
        welcome_override = None
        save_welcome_override()
        bot.send_message(message.from_user.id, "✅ تم الرجوع لرسالة الترحيب الافتراضية.")
    else:
        welcome_override = message.text.strip()
        save_welcome_override()
        bot.send_message(message.from_user.id, "✅ تم تغيير رسالة الترحيب.")

# ======== رسالة الترحيب الأولى ========
LANG_SELECT_MSG = (
    "🌍 *World News & Weather Bot*\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "🇸🇦 *العربية:*\nمرحباً! 👋 الرجاء اختيار لغتك المفضلة للاستمرار في استخدام البوت.\n\n"
    "🇺🇸 *English:*\nHello! 👋 Please select your preferred language to continue using the bot.\n\n"
    "🇪🇸 *Español:*\n¡Hola! 👋 Por favor, selecciona tu idioma preferido para continuar usando el bot.\n\n"
    "🇮🇹 *Italiano:*\nCiao! 👋 Seleziona la tua lingua preferita per continuare a usare il bot.\n\n"
    "🇷🇺 *Русский:*\nПривет! 👋 Пожалуйста, выберите предпочитаемый язык для продолжения использования бота.\n\n"
    "🇵🇹 *Português:*\nOlá! 👋 Por favor, selecione seu idioma preferido para continuar usando o bot.\n\n"
    "🇺🇦 *Українська:*\nПривіт! 👋 Будь ласка, оберіть бажану мову для продовження користування ботом.\n\n"
    "🇮🇷 *فارسی:*\nسلام! 👋 لطفاً زبان مورد نظر خود را برای ادامه استفاده از ربات انتخاب کنید.\n\n"
    "🇮🇳 *हिंदी:*\nनमस्ते! 👋 कृपया बॉट का उपयोग जारी रखने के लिए अपनी पसंदीदा भाषा चुनें।\n\n"
    "🇹🇷 *Türkçe:*\nMerhaba! 👋 Lütfen botu kullanmaya devam etmek için tercih ettiğiniz dili seçin.\n\n"
    "🇩🇪 *Deutsch:*\nHallo! 👋 Bitte wähle deine bevorzugte Sprache, um den Bot weiter zu verwenden.\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "👇 اختر لغتك  |  Choose your language"
)

COUNTRY_SELECT_MSG = {
    "العربية 🇮🇶":   "مرحباً عزيزي! 👋\nيرجى أن تقوم باختيار بلدك من الأزرار أدناه لتنفتح لك جميع مميزات البوت المفيدة لك.",
    "English 🇬🇧":  "Hello dear! 👋\nPlease select your country from the buttons below to unlock all the useful features of the bot for you.",
    "Español 🇲🇽":  "¡Hola querido! 👋\nPor favor, selecciona tu país de los botones de abajo para desbloquear todas las funciones útiles del bot para ti.",
    "Italiano 🇮🇹": "Ciao caro! 👋\nSeleziona il tuo paese dai pulsanti qui sotto per sbloccare tutte le funzionalità utili del bot per te.",
    "Русский 🇷🇺":  "Привет, дорогой! 👋\nПожалуйста, выберите свою страну из кнопок ниже, чтобы открыть все полезные функции бота для вас.",
    "Português 🇧🇷":"Olá querido! 👋\nPor favor, selecione seu país nos botões abaixo para desbloquear todos os recursos úteis do bot para você.",
    "Українська 🇺🇦":"Привіт, дорогий! 👋\nБудь ласка, оберіть свою країну з кнопок нижче, щоб відкрити всі корисні функції бота для вас.",
    "فارسی 🇮🇷":    "سلام عزیز! 👋\nلطفاً کشور خود را از دکمههای زیر انتخاب کنید تا تمام ویژگیهای مفید ربات برای شما فعال شود.",
    "हिन्दी 🇮🇳":   "नमस्ते प्रिय! 👋\nकृपया नीचे दिए गए बटन से अपना देश चुनें ताकि आपके लिए बॉट की सभी उपयोगी सुविधाएँ खुल सकें।",
    "Türkçe 🇹🇷":   "Merhaba sevgili! 👋\nSenin için botun tüm faydalı özelliklerini açmak için lütfen aşağıdaki düğmelerden ülkeni seç.",
    "Deutsch 🇩🇪":  "Hallo lieber! 👋\nBitte wähle dein Land aus den untenstehenden Buttons, um alle nützlichen Funktionen des Bots für dich freizuschalten.",
    "اردو 🇵🇰":     "ہیلو عزیز! 👋\nبوٹ کی تمام مفید خصوصیات کو کھولنے کے لیے براہ کرم نیچے دیے گئے بٹنوں سے اپنا ملک منتخب کریں۔",
}

def send_first_time_welcome(uid, name):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages.values():
        markup.add(lang)
    sent = bot.send_message(uid, LANG_SELECT_MSG, parse_mode="Markdown", reply_markup=markup)
    try:
        bot.pin_chat_message(uid, sent.message_id, disable_notification=True)
    except Exception:
        pass

# ======== رسالة الترحيب (اختيار اللغة) ========
def welcome_user(uid):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for lang in languages.values():
        markup.add(lang)
    sent = bot.send_message(uid, LANG_SELECT_MSG, parse_mode="Markdown", reply_markup=markup)
    try:
        bot.pin_chat_message(uid, sent.message_id, disable_notification=True)
    except Exception:
        pass

# ======== تلميح الاستخدام ========
def send_usage_hint(uid, lang):
    hint = USAGE_HINTS.get(lang, USAGE_HINTS["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 تواصل / Contact", url=CONTACT_LINK))
    bot.send_message(uid, hint, parse_mode="Markdown", reply_markup=markup)

# ======== القائمة الرئيسية ========
def send_main_menu(uid):
    lang = users[str(uid)].get("lang", "English 🇬🇧")
    btn = BUTTONS.get(lang, BUTTONS["English 🇬🇧"])
    notif_on = users[str(uid)].get("notifications", True)
    notif_label = btn["notif_on"] if notif_on else btn["notif_off"]
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        btn["news"],        btn["sports"],
        btn["weather"],     btn["prayer"],
        btn["currency"],    btn["crypto"],
        btn["search"],      btn.get("deepsearch", "🧠 بحث عميق بالذكاء الاصطناعي"),
        btn["daily_summary"], notif_label,
        btn["settings"]
    )
    inline_markup = types.InlineKeyboardMarkup()
    inline_markup.add(types.InlineKeyboardButton("💬 تواصل / Contact", url=CONTACT_LINK))
    bot.send_message(uid, btn["choose"], reply_markup=markup)
    bot.send_message(uid, f"💬 {CONTACT_LINK}", reply_markup=inline_markup)

# ======== أسعار العملات ========
def _fetch_oil_price(symbol):
    try:
        encoded = requests.utils.quote(symbol, safe='')
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1d",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10
        ).json()
        result = r.get("chart", {}).get("result")
        if result:
            closes = result[0]["indicators"]["quote"][0].get("close", [])
            price = next((p for p in reversed(closes) if p is not None), None)
            return round(float(price), 2) if price else None
    except Exception:
        pass
    return None

def send_currency(uid):
    user = users.get(str(uid)) or {}
    lang = user.get("lang", "English 🇬🇧")
    local_code, local_name = CURRENCY_MAP.get(lang, ("EUR", "Euro"))
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        rates = r.get("rates", {})
        local_rate = rates.get(local_code, t(lang, "track_unavailable"))
        eur = rates.get("EUR", "-")
        gbp = rates.get("GBP", "-")
        iqd = rates.get("IQD", "-")
        try_rate = rates.get("TRY", "-")
        sar = rates.get("SAR", "-")
        oil_wti = _fetch_oil_price("CL=F")
        oil_brent = _fetch_oil_price("BZ=F")
        oil_wti_str = f"${oil_wti}" if oil_wti else "—"
        oil_brent_str = f"${oil_brent}" if oil_brent else "—"
        msg = (
            f"{t(lang, 'currency_rate_header')}"
            f"{t(lang, 'currency_local_label').format(name=local_name)}: `{local_rate}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"{t(lang, 'currency_eur')}: `{eur}`\n"
            f"{t(lang, 'currency_gbp')}: `{gbp}`\n"
            f"{t(lang, 'currency_iqd')}: `{iqd}`\n"
            f"{t(lang, 'currency_try')}: `{try_rate}`\n"
            f"{t(lang, 'currency_sar')}: `{sar}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"🛢 النفط WTI: `{oil_wti_str}`\n"
            f"🛢 النفط Brent: `{oil_brent_str}`\n"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "currency_error"))
        notify_admin_error(f"خطأ في أسعار العملات: {e}")

# ======== بحث في الأخبار (عنوان فقط — بدون رابط أو مصدر) ========
def search_news(uid, query, sort_by="publishedAt", sources=None, from_date=None):
    """بحث متقدم بفلاتر الترتيب والمصدر والتاريخ"""
    user = users.get(str(uid)) or {}
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    # ─ احفظ آخر استعلام للفلترة لاحقاً ─
    users[str(uid)]["_last_search"] = query
    users[str(uid)]["total_searches"] = users[str(uid)].get("total_searches", 0) + 1
    try:
        params = {
            "q": query, "language": lang_code,
            "pageSize": 6, "sortBy": sort_by, "apiKey": NEWS_KEY,
        }
        if from_date:
            params["from"] = from_date
        if sources:
            params["sources"] = sources
            params.pop("language", None)
        url = "https://newsapi.org/v2/everything?" + "&".join(f"{k}={v}" for k, v in params.items())
        r = requests.get(url, timeout=10).json()
        articles = r.get("articles", [])
        if not articles:
            # جرب من RSS المحلي
            _search_from_rss(uid, query, lang)
            return
        header_map = {
            "publishedAt": "🕐 الأحدث أولاً",
            "relevancy":   "🎯 الأكثر صلة",
            "popularity":  "🔥 الأكثر انتشاراً",
        }
        bot.send_message(uid,
            f"🔍 *نتائج البحث عن:* `{query}`\n_{header_map.get(sort_by, '')}_ — {len(articles)} نتيجة",
            parse_mode="Markdown"
        )
        for article in articles[:5]:
            title = article.get("title", "")
            link  = article.get("url",   "")
            src   = article.get("source", {}).get("name", "")
            pub   = article.get("publishedAt", "")[:10]
            if title:
                s_e = _sentiment_emoji(title)
                display = f"{s_e} " if s_e else ""
                display += f"*{title}*"
                if src or pub:
                    display += f"\n└ 📡 {src}  |  📅 {pub}"
                if link:
                    art_summary = article.get("description", "") or ""
                    markup = make_news_share_markup(link, title, lang, art_summary)
                    bot.send_message(uid, display, parse_mode="Markdown", reply_markup=markup)
                else:
                    bot.send_message(uid, display, parse_mode="Markdown")
        # ── فلاتر البحث المتقدم ──
        filter_markup = types.InlineKeyboardMarkup(row_width=3)
        filter_markup.add(
            types.InlineKeyboardButton("🕐 الأحدث",   callback_data=f"srch_sort_publishedAt"),
            types.InlineKeyboardButton("🎯 الأصلح",    callback_data=f"srch_sort_relevancy"),
            types.InlineKeyboardButton("🔥 الرائج",    callback_data=f"srch_sort_popularity"),
        )
        filter_markup.add(
            types.InlineKeyboardButton("📅 اليوم فقط",       callback_data="srch_today"),
            types.InlineKeyboardButton("📅 آخر 3 أيام",      callback_data="srch_3days"),
            types.InlineKeyboardButton("📅 آخر أسبوع",       callback_data="srch_week"),
        )
        bot.send_message(uid, "⚙️ *فلاتر البحث:*", parse_mode="Markdown", reply_markup=filter_markup)
    except Exception as e:
        bot.send_message(uid, t(lang, "search_error"))
        notify_admin_error(f"خطأ في البحث: {e}")


def _search_from_rss(uid, query, lang):
    """بحث محلي في مصادر RSS عند فشل NewsAPI"""
    feeds  = RSS.get(lang, [])
    results = []
    q_low = query.lower()
    for feed_url in feeds[:5]:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for item in feed.entries[:20]:
                title = getattr(item, 'title', '')
                if q_low in title.lower():
                    results.append((getattr(item, 'link', ''), title, feed_url,
                                    getattr(item, 'summary', '')))
        except:
            pass
    if results:
        bot.send_message(uid, f"🔍 *نتائج RSS لـ:* `{query}`", parse_mode="Markdown")
        for link, title, feed_url, summ in results[:5]:
            src_name = get_source_name_from_url(feed_url)
            s_e = _sentiment_emoji(title)
            markup = make_news_share_markup(link, title, lang, summ)
            bot.send_message(uid, f"{s_e + ' ' if s_e else ''}*{title}*\n└ 📡 {src_name}",
                             parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(uid, t(lang, "search_no_results") or "❌ لا توجد نتائج")


@bot.callback_query_handler(func=lambda c: c.data.startswith("srch_"))
def cb_advanced_search(call):
    bot.answer_callback_query(call.id)
    uid   = call.from_user.id
    query = users.get(str(uid), {}).get("_last_search", "")
    if not query:
        bot.send_message(uid, "❌ أعد البحث من جديد.")
        return
    d = call.data
    if d.startswith("srch_sort_"):
        sort = d.replace("srch_sort_", "")
        search_news(uid, query, sort_by=sort)
    elif d == "srch_today":
        from_date = datetime.date.today().isoformat()
        search_news(uid, query, from_date=from_date)
    elif d == "srch_3days":
        from_date = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        search_news(uid, query, from_date=from_date)
    elif d == "srch_week":
        from_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        search_news(uid, query, from_date=from_date)

def send_trending_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    try:
        url = f"https://newsapi.org/v2/top-headlines?language={lang_code}&pageSize=8&sortBy=popularity&apiKey={NEWS_KEY}"
        r = requests.get(url, timeout=10).json()
        articles = r.get("articles", [])
        if not articles:
            feeds = RSS.get(lang, [])
            if feeds:
                try:
                    feed = _parse_feed(feeds[0])
                    if feed is None:
                        feed = feedparser.parse(feeds[0])
                    if not feed:
                        raise Exception("feed is None")
                    articles_rss = feed.entries[:8]
                    bot.send_message(uid, t(lang, "trending_header"), parse_mode="Markdown")
                    for item in articles_rss:
                        title = getattr(item, 'title', '').strip()
                        link = getattr(item, 'link', '')
                        if title and link and _title_in_lang(title, lang):
                            item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                            markup = make_news_share_markup(link, title, lang, item_sum)
                            trending_src = get_source_name_from_url(link)
                            pub_time_str = _format_pub_time(_pub_dt_from_item(item), lang=lang)
                            bot.send_message(uid, format_news_item(t(lang, "label_trending"), title, lang, trending_src, pub_time_str, summary=item_sum), parse_mode="Markdown", reply_markup=markup)
                    return
                except:
                    pass
            bot.send_message(uid, t(lang, "no_trending"))
            return
        bot.send_message(uid, t(lang, "trending_header"), parse_mode="Markdown")
        for article in articles[:8]:
            title = article.get("title", "").strip()
            link = article.get("url", "")
            if title and link and _title_in_lang(title, lang):
                art_sum = article.get("description", "") or article.get("content", "")
                markup = make_news_share_markup(link, title, lang, art_sum)
                api_src = (article.get("source") or {}).get("name", "") or get_source_name_from_url(link)
                na_pub_str = article.get("publishedAt", "")
                try:
                    import datetime as _dt
                    na_pub_dt = _dt.datetime.strptime(na_pub_str, "%Y-%m-%dT%H:%M:%SZ") if na_pub_str else None
                except Exception:
                    na_pub_dt = None
                pub_time_str = _format_pub_time(na_pub_dt, lang=lang)
                bot.send_message(uid, format_news_item(t(lang, "label_trending"), title, lang, api_src, pub_time_str, summary=art_sum), parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        bot.send_message(uid, t(lang, "no_trending"))
        notify_admin_error(f"خطأ في الأخبار الرائجة: {e}")

def send_premium_upgrade(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    msg = PREMIUM_UPGRADE_MSG.get(lang, PREMIUM_UPGRADE_MSG["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(t(lang, "premium_subscribe_btn"), callback_data=f"req_premium_{uid}"))
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

def send_premium_menu(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(t(lang, "premium_btn_7day"), callback_data="prem_7day"),
        types.InlineKeyboardButton(t(lang, "premium_btn_hourly"), callback_data="prem_hourly"),
        types.InlineKeyboardButton(t(lang, "premium_btn_addcity"), callback_data="prem_addcity"),
        types.InlineKeyboardButton(t(lang, "premium_btn_mycities"), callback_data="prem_mycities"),
        types.InlineKeyboardButton(t(lang, "premium_btn_interests"), callback_data="prem_interests"),
        types.InlineKeyboardButton(t(lang, "premium_btn_currency_alert"), callback_data="prem_currency_alert"),
        types.InlineKeyboardButton(t(lang, "premium_btn_currency_table"), callback_data="prem_currency_table"),
        types.InlineKeyboardButton(t(lang, "premium_btn_notif_time"), callback_data="prem_notif_time"),
        types.InlineKeyboardButton(t(lang, "premium_btn_weekly"), callback_data="prem_weekly"),
        types.InlineKeyboardButton(t(lang, "premium_btn_keywords"), callback_data="prem_keywords"),
    )
    bot.send_message(uid, t(lang, "premium_menu_header"), parse_mode="Markdown", reply_markup=markup)

def send_7day_forecast(uid):
    user = users.get(str(uid)) or {}
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    cities = [user.get("province", "")] + user.get("extra_cities", [])
    cities = [c for c in cities if c]
    for city in cities[:3]:
        try:
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_KEY}&units=metric&lang={lang_code}&cnt=40"
            data = requests.get(url, timeout=10).json()
            if str(data.get("cod")) != "200":
                continue
            days = {}
            for item in data["list"]:
                date = item["dt_txt"].split(" ")[0]
                if date not in days:
                    days[date] = {"temps": [], "desc": item["weather"][0]["description"]}
                days[date]["temps"].append(item["main"]["temp"])
            msg = t(lang, "forecast_7day_header").format(city=city)
            for date, info in list(days.items())[:7]:
                min_t = round(min(info["temps"]))
                max_t = round(max(info["temps"]))
                msg += f"📅 {date}: {min_t}°C — {max_t}°C | {info['desc']}\n"
            bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception as e:
            notify_admin_error(f"خطأ في توقعات 7 أيام ({city}): {e}")

def get_weather_emoji(weather_id):
    if weather_id < 300:
        return "⚡"
    elif weather_id < 500:
        return "🌦"
    elif weather_id < 600:
        return "🌧"
    elif weather_id < 700:
        return "❄️"
    elif weather_id < 800:
        return "🌫"
    elif weather_id == 800:
        return "☀️"
    elif weather_id < 803:
        return "🌤"
    else:
        return "☁️"

def get_uv_level(uvi, lang="English 🇬🇧"):
    if uvi is None:
        return t(lang, "uv_na")
    uvi = float(uvi)
    if uvi < 3:
        return f"{uvi:.1f} 🟢 {t(lang, 'uv_low')}"
    elif uvi < 6:
        return f"{uvi:.1f} 🟡 {t(lang, 'uv_moderate')}"
    elif uvi < 8:
        return f"{uvi:.1f} 🟠 {t(lang, 'uv_high')}"
    elif uvi < 11:
        return f"{uvi:.1f} 🔴 {t(lang, 'uv_very_high')}"
    else:
        return f"{uvi:.1f} 🟣 {t(lang, 'uv_extreme')}"

def get_wind_direction(deg, lang="English 🇬🇧"):
    keys = ["wind_N", "wind_NE", "wind_E", "wind_SE",
            "wind_S", "wind_SW", "wind_W", "wind_NW"]
    if deg is None:
        return "-"
    return t(lang, keys[round(deg / 45) % 8])

def send_detailed_weather(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    province = user.get("province", "")
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
        data = requests.get(url, timeout=10).json()
        if data.get("cod") != 200:
            bot.send_message(uid, t(lang, "city_not_found").format(city=province))
            return
        temp = round(data['main']['temp'], 1)
        feels = round(data['main']['feels_like'], 1)
        temp_min = round(data['main']['temp_min'], 1)
        temp_max = round(data['main']['temp_max'], 1)
        humidity = data['main']['humidity']
        pressure = data['main']['pressure']
        desc = data['weather'][0]['description'].capitalize()
        weather_id = data['weather'][0]['id']
        weather_emoji = get_weather_emoji(weather_id)
        wind_speed = data['wind']['speed']
        wind_deg = data['wind'].get('deg')
        wind_gust = data['wind'].get('gust', '-')
        visibility = data.get('visibility', 0)
        visibility_km = round(visibility / 1000, 1) if visibility else '-'
        clouds = data['clouds']['all']
        sunrise_ts = data['sys'].get('sunrise', 0)
        sunset_ts = data['sys'].get('sunset', 0)
        sunrise = datetime.datetime.fromtimestamp(sunrise_ts).strftime("%H:%M") if sunrise_ts else "-"
        sunset = datetime.datetime.fromtimestamp(sunset_ts).strftime("%H:%M") if sunset_ts else "-"
        lat = data['coord']['lat']
        lon = data['coord']['lon']
        try:
            one_call_url = f"https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={lon}&exclude=minutely,hourly,daily,alerts&appid={WEATHER_KEY}&units=metric"
            one_call = requests.get(one_call_url, timeout=5).json()
            uvi = one_call.get('current', {}).get('uvi')
        except:
            uvi = None
        msg = t(lang, "weather_header").format(
            emoji=weather_emoji, city=province, temp=temp, feels=feels,
            temp_max=temp_max, temp_min=temp_min, desc=desc, clouds=clouds,
            visibility_km=visibility_km, humidity=humidity, pressure=pressure,
            uvi=get_uv_level(uvi, lang),
            wind_speed=wind_speed, wind_dir=get_wind_direction(wind_deg, lang),
            wind_gust=wind_gust, sunrise=sunrise, sunset=sunset
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "weather_error"))
        notify_admin_error(f"خطأ في الطقس لـ {uid}: {e}")

def add_extra_city(uid, city):
    users[str(uid)].setdefault("extra_cities", [])
    if city not in users[str(uid)]["extra_cities"]:
        users[str(uid)]["extra_cities"].append(city)
    _db_save_all_users(users)
    bot.send_message(uid, f"✅ تمت إضافة مدينة: *{city}*", parse_mode="Markdown")

def send_hourly_weather_forecast(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    province = user.get("province", "")
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}&cnt=8"
        data = requests.get(url, timeout=10).json()
        if str(data.get("cod")) != "200":
            bot.send_message(uid, t(lang, "forecast_error"))
            return
        msg = t(lang, "hourly_header").format(city=province)
        wind_unit = t(lang, "wind_unit")
        for item in data["list"][:8]:
            time_str = item["dt_txt"].split(" ")[1][:5]
            date_str = item["dt_txt"].split(" ")[0][5:]
            temp = round(item["main"]["temp"], 1)
            desc = item["weather"][0]["description"].capitalize()
            wid = item["weather"][0]["id"]
            emoji = get_weather_emoji(wid)
            humidity = item["main"]["humidity"]
            wind = item["wind"]["speed"]
            msg += f"{emoji} *{date_str} | {time_str}*\n"
            msg += f"   🌡 {temp}°C | {desc}\n"
            msg += f"   💧 {humidity}% | 💨 {wind} {wind_unit}\n\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "forecast_error"))
        notify_admin_error(f"خطأ في الطقس الساعي لـ {uid}: {e}")

def send_full_currency_table(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        rates = r.get("rates", {})
        pairs = [
            ("🇪🇺", "EUR"), ("🇬🇧", "GBP"), ("🇮🇶", "IQD"),
            ("🇸🇦", "SAR"), ("🇦🇪", "AED"), ("🇹🇷", "TRY"),
            ("🇮🇷", "IRR"), ("🇷🇺", "RUB"), ("🇵🇰", "PKR"),
            ("🇮🇳", "INR"), ("🇧🇷", "BRL"), ("🇲🇽", "MXN"),
            ("🇨🇳", "CNY"), ("🇯🇵", "JPY"), ("🇨🇦", "CAD"),
            ("🇦🇺", "AUD"), ("🇰🇼", "KWD"), ("🇪🇬", "EGP"),
            ("🇯🇴", "JOD"), ("🇵🇱", "PLN"), ("🇨🇭", "CHF"),
            ("🇸🇬", "SGD"), ("🇿🇦", "ZAR"), ("🇳🇬", "NGN"),
        ]
        msg = t(lang, "currency_table_header")
        for flag, code in pairs:
            rate = rates.get(code, "-")
            msg += f"{flag} {code}: `{rate}`\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "currency_error"))
        notify_admin_error(f"خطأ في جدول العملات: {e}")

def send_weekly_news_summary(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    headlines = []
    for feed_url in feeds:
        try:
            feed = _parse_feed(feed_url)
            if feed is None:
                feed = feedparser.parse(feed_url)
            if not feed:
                continue
            for item in feed.entries[:5]:
                title = getattr(item, 'title', '')
                if title:
                    headlines.append(title)
            if len(headlines) >= 20:
                break
        except:
            pass
    if not headlines:
        bot.send_message(uid, t(lang, "no_weekly"))
        return
    count = min(len(headlines), 20)
    msg = t(lang, "weekly_summary_header").format(count=count)
    for i, title in enumerate(headlines[:20], 1):
        msg += f"{i}. {title}\n\n"
    bot.send_message(uid, msg, parse_mode="Markdown")

def send_interest_menu(uid):
    user = users.get(str(uid)) or {}
    lang = user.get("lang", "العربية 🇮🇶")
    options = INTERESTS.get(lang, INTERESTS["English 🇬🇧"])
    current = user.get("interests", [])
    markup = types.InlineKeyboardMarkup(row_width=2)
    for opt in options:
        check = "✅ " if opt in current else ""
        markup.add(types.InlineKeyboardButton(f"{check}{opt}", callback_data=f"interest_{opt}"))
    markup.add(types.InlineKeyboardButton("💾 حفظ", callback_data="interest_save"))
    bot.send_message(uid, "📌 *اختر اهتماماتك (يمكن أكثر من واحد):*", parse_mode="Markdown", reply_markup=markup)

def set_currency_alert_step(message):
    uid = message.from_user.id
    try:
        rate = float(message.text.strip())
        users[str(uid)]["currency_alert"] = rate
        _db_save_all_users(users)
        bot.send_message(uid, f"✅ سيتم تنبيهك عند وصول الدولار إلى `{rate}` من عملتك المحلية.", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ أرسل رقماً صحيحاً مثل: 1600")

def set_notif_time_step(message):
    uid = message.from_user.id
    try:
        hour = int(message.text.strip())
        if not (0 <= hour <= 23):
            raise ValueError
        users[str(uid)]["notif_hour"] = hour
        _db_save_all_users(users)
        bot.send_message(uid, f"✅ سيتم إرسال الملخص الصباحي في الساعة *{hour}:00* يومياً.", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ أرسل رقماً بين 0 و 23 (مثال: 8 للساعة 8 صباحاً)")

def news_matches_interests(title, interests):
    if not interests:
        return True
    title_lower = title.lower()
    for interest in interests:
        key = interest.split(" ", 1)[-1].lower()
        keywords = INTEREST_KEYWORDS.get(key, [])
        for kw in keywords:
            if kw.lower() in title_lower:
                return True
    return False

def is_blacklisted(title):
    if not blacklist_words:
        return False
    title_lower = title.lower()
    for word in blacklist_words:
        if word.lower() in title_lower:
            return True
    return False

# =============================================================
# فلتر محتوى قنوات تيليجرام — يمنع البروموشن والإعلانات والألعاب
# =============================================================
_TG_SPAM_PATTERNS = [
    # وصف القنوات
    "قناة متخصصة", "قناة تختص", "قناة رسمية", "قناة تهتم", "قناة تقدم",
    "منصة متخصصة", "نحن نقدم", "نقدم لكم", "تابعونا", "تابعوا قناتنا",
    "انضم إلينا", "انضم الينا", "اشترك في قناتنا", "اشترك معنا",
    "للاشتراك", "للإعلان في قناتنا", "للتعاون والإعلان",
    "للتواصل واتس", "للتواصل اتصل", "للتواصل على واتساب",
    "للتعاون الإعلاني", "تواصل معنا على", "للإعلانات تواصل",
    # ألعاب وترفيه
    "العاب تيليجرام", "telegram games", "تيليجرام قيم", "العاب بوت",
    "ربح من الالعاب", "العب واكسب", "game bot", "gamebot",
    # إعلانات وبروموشن
    "حساب موثق", "قناة موثقة", "اعلانات", "إعلانات", "عروض حصرية",
    "خدماتنا", "خدمات متميزة", "فرصة استثمارية", "استثمر معنا",
    "ربح سريع", "دخل يومي", "ربح من المنزل",
    # محتوى غير إخباري
    "وصفة طبخ", "طبخات", "اكلات", "كورسات مجانية", "كورس مجاني",
    "تحميل مجاني", "تطبيق مجاني", "برنامج مجاني",
    # روابط ترويجية
    "t.me/+", "telegram.me/+", "جروب", "قروب واتساب",
    # تحيات وكلام تافه
    "صباح الخير", "صباح النور", "مساء الخير", "مساء النور",
    "صباح الورد", "صباح الفل", "صباحكم ورد", "مساؤكم نور",
    "تصبح على خير", "تصبحون على خير", "يومكم سعيد", "يوم مبارك",
    "جمعة مباركة", "جمعة طيبة", "أسبوع سعيد", "عيد مبارك",
    "رمضان كريم", "رمضان مبارك", "ليلة مباركة",
    # آراء شخصية وكلام عادي
    "رأيي الشخصي", "شخصياً أعتقد", "على رأيي", "من وجهة نظري",
    "اللي يحبنا", "متابعينا الكرام", "أهلاً وسهلاً",
    "ههههه", "هههههه", "😂😂😂", "😂😂😂😂",
    # دعوات منفردة (ليست خبراً — لكن نتحقق من السياق أدناه)
    "دعاء اليوم", "دعاء الصباح", "دعاء المساء", "اللهم صل على النبي",
    # طلبات تفاعل
    "أعد النشر", "فوروارد", "أرسل لأصحابك",
    "تفاعلوا معنا", "لا تنسى أن تشارك", "أكبر نشر",
    "شاركوا المنشور", "نشروا الخبر",
    # خدمات ومبيعات
    "للبيع", "للإيجار", "بسعر مغري", "عرض لفترة محدودة",
    "اشترِ الآن", "احجز الآن", "سعر خاص",
    # محتوى تعليمي/دراسي (ليس أخباراً)
    "اول متوسط", "ثاني متوسط", "ثالث متوسط",
    "اول ابتدائي", "ثاني ابتدائي", "ثالث ابتدائي",
    "رابع ابتدائي", "خامس ابتدائي", "سادس ابتدائي",
    "اول اعدادي", "ثاني اعدادي", "ثالث اعدادي",
    "رياضيات شهر", "علوم شهر", "لغة عربية شهر",
    "منهج الدراسي", "كتاب مدرسي", "امتحانات وزارية",
    "اسئلة الامتحان", "حل الاسئلة", "شرح الدرس",
    "ملخص المادة", "مادة الرياضيات", "مادة العلوم",
    "مادة التاريخ", "مادة الجغرافية", "التربية الاسلامية",
    "فيزياء شهر", "كيمياء شهر", "احياء شهر",
    "الفصل الدراسي", "نتائج الطلاب", "جدول الامتحانات",
    # دعوات مشاركة/تفاعل (نهايات رسائل القنوات)
    "لا تنسى المشاركة", "لا تنسوا المشاركة",
    "لا تنسى الاشتراك", "لا تنسوا الاشتراك",
    "شارك الخبر مع", "شارك مع اصدقائك",
    "اضغط متابعة", "فعّل الاشعارات",
    # محتوى ديني غير إخباري
    "تفسير الآية", "حديث شريف", "قال رسول الله",
    "دعاء مستجاب", "ثواب عظيم",
    # ترفيه ونكت
    "نكتة اليوم", "لطيفة اليوم", "تحدي اليوم",
    "معلومة طريفة", "هل تعلم ان",
]

# أنماط تشير إلى محادثة عادية (regex)
import re as _re_spam
_TG_SPAM_REGEX = [
    _re_spam.compile(r"^[\u2600-\u26FF\u2700-\u27BF\U0001F300-\U0001FFFF\s]{1,20}$"),  # إيموجي فقط
    _re_spam.compile(r"^[.،!؟?]{1,10}$"),   # ترقيم فقط
    _re_spam.compile(r"^(نعم|لا|أيوه|آه|ايوه|طيب|اوك|ok|yes|no|هم){1,3}[\s.،!؟]*$", _re_spam.IGNORECASE),
    # "لا تنسى المشاركة @قناة" أو "لا تنسوا المشاركة @قناة" — دعوة اشتراك
    _re_spam.compile(r"لا\s+تنس[ىيوو]+\s+المشاركة\s*@", _re_spam.IGNORECASE),
    # رياضيات/مواد دراسية + مستوى دراسي = محتوى تعليمي وليس خبراً
    _re_spam.compile(r"(رياضيات|علوم|فيزياء|كيمياء|احياء|جغرافية|تاريخ)\s+(شهر|اول|ثاني|ثالث|الفصل)", _re_spam.IGNORECASE),
]

def _is_tg_spam(raw_text: str, tg_link: str = "") -> bool:
    """يكتشف إذا كان المنشور إعلان/بروموشن/محتوى غير إخباري أو كلام تافه"""
    if not raw_text:
        return True
    stripped = raw_text.strip()
    text_lower = stripped.lower()

    # النص قصير جداً ولا يشبه خبراً (< 15 حرف)
    # ملاحظة: أخبار عاجلة كثيرة قصيرة مثل "عاجل: انفجار في بغداد" = ~30 حرف
    if len(stripped) < 15:
        return True

    # فحص الأنماط بالـ regex (إيموجي فقط، ترقيم فقط، إجابات أحادية)
    for pat in _TG_SPAM_REGEX:
        if pat.match(stripped):
            return True

    # فحص كلمات السبام
    for pat in _TG_SPAM_PATTERNS:
        if pat.lower() in text_lower:
            return True

    # رابط t.me/ لقناة مباشرة (بدون رقم رسالة) = إعادة توجيه وليس خبراً
    if tg_link:
        import re as _re
        if _re.match(r"https://t\.me/[A-Za-z0-9_]+$", tg_link):
            return True

    # نص مكوّن من إيموجي ومسافات بنسبة > 60%
    try:
        import unicodedata as _ud
        emoji_chars = sum(
            1 for ch in stripped
            if _ud.category(ch) in ('So', 'Sm') or ord(ch) > 0x1F300
        )
        if len(stripped) > 0 and emoji_chars / len(stripped) > 0.6:
            return True
    except Exception:
        pass

    # نص لا يحتوي على أي كلمة عربية أو إنجليزية حقيقية (> 3 أحرف)
    import re as _re2
    words = _re2.findall(r'[a-zA-Z\u0600-\u06FF]{4,}', stripped)
    if not words:
        return True

    # محتوى لا يشبه الخبر: أسئلة فقط بدون تفاصيل
    question_only = _re2.match(r'^[^؟?]*[؟?]\s*$', stripped)
    if question_only and len(stripped) < 80:
        return True

    # نص مكرر بشكل واضح (نفس الكلمة > 4 مرات)
    word_counts = {}
    for w in words:
        word_counts[w] = word_counts.get(w, 0) + 1
    if word_counts and max(word_counts.values()) > 4:
        return True

    return False



def broadcast_premium_instant_news():
    if bot_paused or broadcast_paused: return
    try:
        rss_cache = {}
        for uid, info in list(users.items()):
            try:
                if not is_premium(uid):
                    continue
                if int(uid) in banned:
                    continue
                if not info.get("notifications", True):
                    continue
                lang = info.get("lang", "English 🇬🇧")
                feeds = RSS.get(lang, [])
                sent = info.setdefault("sent_news", set())
                interests = info.get("interests", [])
                changed = False
                for feed_url in feeds:
                    if feed_url not in rss_cache:
                        try:
                            rss_cache[feed_url] = _parse_feed(feed_url)
                        except Exception:
                            rss_cache[feed_url] = None
                    feed = rss_cache.get(feed_url)
                    if not feed:
                        continue
                    for item in feed.entries[:5]:
                        if not hasattr(item, 'link') or item.link in sent:
                            continue
                        pub_dt = _pub_dt_from_item(item) if hasattr(item, 'published_parsed') else None
                        if not _is_fresh(pub_dt):
                            continue
                        if not news_matches_interests(item.title, interests):
                            continue
                        sent.add(item.link)
                        changed = True
                        link = getattr(item, 'link', '')
                        title = getattr(item, 'title', '')
                        item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                        markup = make_news_share_markup(link, title, lang, item_sum)
                        src_name = get_source_name_from_url(feed_url)
                        pub_time_str = _format_pub_time(_pub_dt_from_item(item) if hasattr(item, 'published_parsed') else None, lang=lang)
                        queue_send(uid, format_news_item(t(lang, "label_breaking"), title, lang, src_name, pub_time_str, summary=item_sum),
                            parse_mode="Markdown", reply_markup=markup)
                if changed:
                    _db_save_user(uid, info)
            except Exception:
                continue
    except Exception as e:
        try:
            bot.send_message(ADMIN_ID, f"⚠️ خطأ في broadcast_premium_instant_news: {e}")
        except Exception:
            pass

def _fetch_quick_weather(province, lang):
    """يجلب بيانات الطقس السريعة لعرضها في الملخص الصباحي"""
    try:
        lang_codes = {
            "العربية 🇮🇶": "ar", "English 🇬🇧": "en", "Русский 🇷🇺": "ru",
            "فارسی 🇮🇷": "fa", "हिन्दी 🇮🇳": "hi", "Português 🇧🇷": "pt",
            "Türkçe 🇹🇷": "tr", "اردو 🇵🇰": "ur", "Deutsch 🇩🇪": "de",
            "Українська 🇺🇦": "uk", "Italiano 🇮🇹": "it", "Español 🇲🇽": "es",
        }
        lang_code = lang_codes.get(lang, "en")
        url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            d = r.json()
            temp  = round(d["main"]["temp"])
            feels = round(d["main"]["feels_like"])
            desc  = d["weather"][0].get("description", "")
            emoji = get_weather_emoji(d["weather"][0].get("id", 800))
            return f"{emoji} *{province}*: {temp}°C ({desc}), يُشعر بـ {feels}°C"
    except Exception:
        pass
    return None

def _fetch_quick_prayer(province):
    """يجلب أوقات الصلاة القادمة لعرضها في الملخص الصباحي"""
    try:
        today = datetime.date.today().strftime("%d-%m-%Y")
        url = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=IQ&method=4&date={today}"
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            url2 = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=&method=4&date={today}"
            r = requests.get(url2, timeout=5)
        if r.status_code == 200:
            timings = r.json()["data"]["timings"]
            now = _now_sa()
            now_str = now.strftime("%H:%M")
            prayer_names = {
                "Fajr": "🌅 الفجر", "Dhuhr": "🌞 الظهر",
                "Asr": "🌇 العصر", "Maghrib": "🌆 المغرب", "Isha": "🌙 العشاء"
            }
            next_p = None
            for p_key, p_name in prayer_names.items():
                p_time = timings.get(p_key, "")
                if p_time > now_str:
                    next_p = f"{p_name}: `{p_time}`"
                    break
            return next_p
    except Exception:
        pass
    return None

def send_morning_summary():
    if bot_paused: return
    now_hour = _now_sa().hour
    for uid, info in list(users.items()):
        if int(uid) in banned:
            continue
        if not info.get("notifications", True):
            continue
        notif_hour = info.get("notif_hour", 8)
        if now_hour != notif_hour:
            continue
        lang     = info.get("lang", "English 🇬🇧")
        province = info.get("province", "")
        feeds    = RSS.get(lang, [])
        # ── جمع أبرز الأخبار ──
        headlines = []
        for feed_url in feeds:
            try:
                feed = _parse_feed(feed_url)
                if feed is None:
                    feed = feedparser.parse(feed_url)
                if not feed:
                    continue
                for item in feed.entries[:3]:
                    if hasattr(item, 'title'):
                        s_e = _sentiment_emoji(item.title)
                        headlines.append(f"{'• ' + s_e + ' ' if s_e else '• '}{item.title}")
                if len(headlines) >= 8:
                    break
            except:
                pass
        parts = [_ul(lang, "morning_title")]
        # ── الطقس ──
        if province and WEATHER_KEY:
            w = _fetch_quick_weather(province, lang)
            if w:
                parts.append(_ul(lang, "morning_weather") + w)
        # ── وقت الصلاة القادم ──
        if province:
            prayer = _fetch_quick_prayer(province)
            if prayer:
                parts.append(_ul(lang, "morning_prayer") + prayer)
        # ── الأخبار ──
        if headlines:
            parts.append(_ul(lang, "morning_news") + "\n".join(headlines[:8]))
        if len(parts) > 1:
            msg = "\n".join(parts)
            try:
                bot.send_message(uid, msg, parse_mode="Markdown")
            except:
                pass

def check_weather_alerts():
    if bot_paused: return
    for uid, info in list(users.items()):
        if int(uid) in banned:
            continue
        province = info.get("province")
        if not province:
            continue
        lang = info.get("lang", "English 🇬🇧")
        lang_code = LANG_CODES.get(lang, "en")
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}"
            data = requests.get(url, timeout=10).json()
            if data.get("cod") != 200:
                continue
            temp = data['main']['temp']
            weather_id = data['weather'][0]['id']
            desc = data['weather'][0]['description']
            if temp >= 45:
                bot.send_message(uid, _ul(lang, "weather_heat", city=province, temp=temp), parse_mode="Markdown")
            elif weather_id < 700:
                bot.send_message(uid, _ul(lang, "weather_alert", city=province, desc=desc), parse_mode="Markdown")
        except Exception as e:
            notify_admin_error(f"خطأ في تنبيهات الطقس: {e}")

def check_currency_alerts():
    if bot_paused: return
    alerted_users = [uid for uid, info in users.items() if "currency_alert" in info]
    if not alerted_users:
        return
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        rates = r.get("rates", {})
        for uid in alerted_users:
            info = users[uid]
            lang = info.get("lang", "English 🇬🇧")
            local_code, local_name = CURRENCY_MAP.get(lang, ("EUR", "Euro"))
            current_rate = rates.get(local_code)
            target = info.get("currency_alert")
            if current_rate and target:
                last = info.get("currency_alert_last", 0)
                if abs(current_rate - target) <= target * 0.01 and abs(current_rate - last) > target * 0.005:
                    users[uid]["currency_alert_last"] = current_rate
                    _db_save_all_users(users)
                    bot.send_message(int(uid), _ul(lang, "currency_alert", rate=current_rate, currency=local_name), parse_mode="Markdown")
    except Exception as e:
        notify_admin_error(f"خطأ في تنبيهات العملة: {e}")

# ======== /start ========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    if uid in banned:
        bot.send_message(uid, "🚫 أنت محظور من استخدام البوت.")
        return
    if bot_paused and not is_admin(uid):
        bot.send_message(uid, pause_message)
        return
    username = message.from_user.username or "لا يوزر"
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
        except:
            pass
    is_new = str(uid) not in users
    if is_new:
        users[str(uid)] = {
            "name": message.from_user.first_name,
            "first_name": message.from_user.first_name or "",
            "last_name": message.from_user.last_name or "",
            "username": message.from_user.username or "",
            "telegram_lang": message.from_user.language_code or "",
            "sent_news": set(),
            "first_visit": True,
            "referrals": [],
            "join_date": _now_sa().strftime("%Y-%m-%d"),
            "last_command": "/start"
        }
        # ─── تتبع المستخدمين الجدد للتقرير اليومي ────────────────────
        with _daily_new_users_lock:
            _daily_new_users.append(uid)
        if referrer_id and referrer_id != uid and str(referrer_id) in users:
            users[str(uid)]["referred_by"] = referrer_id
            users[str(referrer_id)].setdefault("referrals", [])
            if uid not in users[str(referrer_id)]["referrals"]:
                users[str(referrer_id)]["referrals"].append(uid)
                ref_total = len(users[str(referrer_id)]["referrals"])
                next_m = next((m for m in REFERRAL_MILESTONES if m > ref_total), None)
                progress_txt = f"\n🎯 تحتاج {next_m - ref_total} دعوة أخرى للمكافأة القادمة!" if next_m else "\n🏆 وصلت لأعلى مستوى!"
                try:
                    bot.send_message(referrer_id,
                        f"🎉 *انضم شخص جديد عبر رابطك!*\n"
                        f"👤 الاسم: {message.from_user.first_name}\n"
                        f"👥 إجمالي دعواتك: `{ref_total}`"
                        f"{progress_txt}",
                        parse_mode="Markdown"
                    )
                except:
                    pass
                check_referral_rewards(referrer_id, message.from_user.first_name)
        _db_save_all_users(users)
        update_stats("new_user", uid=uid)
        all_admins = [ADMIN_ID] + extra_admins
        referrer_name = None
        if referrer_id and str(referrer_id) in users:
            referrer_name = users[str(referrer_id)].get("name", str(referrer_id))
        join_time = _now_sa().strftime("%H:%M - %d/%m/%Y")
        new_user_msg = (
            f"🆕 *مستخدم جديد انضم!*\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 الاسم: *{message.from_user.first_name}*\n"
            f"🆔 ID: `{uid}`\n"
            f"📛 اليوزر: @{username}\n"
            f"⏰ وقت الانضمام: `{join_time}`\n"
            f"👈 جاء عبر: {('دعوة من *' + referrer_name + '*') if referrer_name else 'مباشر'}\n"
            f"━━━━━━━━━━━━━━\n"
            f"👥 إجمالي المستخدمين: `{len(users)}`"
        )
        quick_markup = types.InlineKeyboardMarkup(row_width=2)
        quick_markup.add(
            types.InlineKeyboardButton("👤 عرض ملفه", callback_data=f"admin_view_{uid}"),
            types.InlineKeyboardButton("🚫 حظر", callback_data=f"quick_ban_{uid}"),
            types.InlineKeyboardButton("📢 راسله", url=f"tg://user?id={uid}"),
        )
        for admin_id in all_admins:
            try:
                bot.send_message(admin_id, new_user_msg, parse_mode="Markdown", reply_markup=quick_markup)
            except:
                pass
        send_first_time_welcome(uid, message.from_user.first_name)
    else:
        users[str(uid)]["name"] = message.from_user.first_name
        users[str(uid)]["first_name"] = message.from_user.first_name or ""
        users[str(uid)]["last_name"] = message.from_user.last_name or ""
        users[str(uid)]["username"] = message.from_user.username or ""
        users[str(uid)]["telegram_lang"] = message.from_user.language_code or ""
        users[str(uid)]["last_command"] = "/start"
        user = users[str(uid)]
        lang = user.get("lang", "English 🇬🇧")
        user_feeds = RSS.get(lang, [])
        if user_feeds:
            current_sent = user.get("sent_news", set())
            fresh_links = prefill_sent_news(user_feeds)
            users[str(uid)]["sent_news"] = current_sent | fresh_links
        _db_save_all_users(users)
        _send_welcome_greeting(uid, message.from_user.first_name, lang)

def _send_welcome_greeting(uid, name, lang="English 🇬🇧"):
    """رسالة الترحيب والتواصل فقط — بدون إعادة إعداد."""
    contact_markup = types.InlineKeyboardMarkup()
    contact_markup.add(types.InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="menu_main"))
    contact_markup.add(types.InlineKeyboardButton("💬 تواصل / Contact", url=CONTACT_LINK))
    greetings = {
        "العربية 🇮🇶":   f"👋 *أهلاً {name}!*\n\nسعيد بعودتك إلى *World News & Weather Bot* 🌍\n\n",
        "English 🇬🇧":  f"👋 *Welcome back, {name}!*\n\nGlad to see you at *World News & Weather Bot* 🌍\n\n",
        "Русский 🇷🇺":  f"👋 *С возвращением, {name}!*\n\nРады видеть вас снова! 🌍\n\n",
        "فارسی 🇮🇷":    f"👋 *خوش آمدید، {name}!*\n\nخوشحالیم که برگشتید! 🌍\n\n",
        "हिन्दी 🇮🇳":   f"👋 *वापस स्वागत है, {name}!*\n\nआपको देखकर खुशी हुई! 🌍\n\n",
        "Português 🇧🇷": f"👋 *Bem-vindo de volta, {name}!*\n\nFeliz em vê-lo novamente! 🌍\n\n",
        "Türkçe 🇹🇷":   f"👋 *Tekrar hoş geldiniz, {name}!*\n\nSizi yeniden görmekten mutluyuz! 🌍\n\n",
        "اردو 🇵🇰":     f"👋 *خوش آمدید، {name}!*\n\nآپ کو دوبارہ دیکھ کر خوشی ہوئی! 🌍\n\n",
        "Deutsch 🇩🇪":  f"👋 *Willkommen zurück, {name}!*\n\nSchön, Sie wiederzusehen! 🌍\n\n",
        "Українська 🇺🇦": f"👋 *З поверненням, {name}!*\n\nРаді бачити вас знову! 🌍\n\n",
        "Italiano 🇮🇹": f"👋 *Bentornato, {name}!*\n\nFelici di rivederti! 🌍\n\n",
        "Español 🇲🇽":  f"👋 *¡Bienvenido de nuevo, {name}!*\n\n¡Feliz de verte de nuevo! 🌍\n\n",
    }
    body_lines = {
        "العربية 🇮🇶": (
            "📰 أخبار عالمية لحظية\n"
            "🌤 حالة الطقس لمدينتك\n"
            "💱 أسعار العملات والأسهم\n"
            "📊 /chart — رسم بياني تفاعلي\n"
            "❓ /help — دليل الأوامر الكامل\n"
            "🔄 /restart — إعادة ضبط إعداداتك"
        ),
        "English 🇬🇧": (
            "📰 Live world news\n"
            "🌤 Weather for your city\n"
            "💱 Currency & stock rates\n"
            "📊 /chart — Interactive chart\n"
            "❓ /help — Full commands guide\n"
            "🔄 /restart — Reset your settings"
        ),
        "Русский 🇷🇺": (
            "📰 Мировые новости в реальном времени\n"
            "🌤 Погода в вашем городе\n"
            "💱 Курсы валют и акций\n"
            "📊 /chart — Интерактивный график\n"
            "❓ /help — Полное руководство\n"
            "🔄 /restart — Перезапустить настройки"
        ),
        "فارسی 🇮🇷": (
            "📰 اخبار جهانی لحظهای\n"
            "🌤 آبوهوای شهر شما\n"
            "💱 نرخ ارز و سهام\n"
            "📊 /chart — نمودار تعاملی\n"
            "❓ /help — راهنمای کامل دستورات\n"
            "🔄 /restart — بازنشانی تنظیمات"
        ),
        "हिन्दी 🇮🇳": (
            "📰 लाइव विश्व समाचार\n"
            "🌤 आपके शहर का मौसम\n"
            "💱 मुद्रा और शेयर दरें\n"
            "📊 /chart — इंटरैक्टिव चार्ट\n"
            "❓ /help — पूरी कमांड गाइड\n"
            "🔄 /restart — सेटिंग्स रीसेट करें"
        ),
        "Português 🇧🇷": (
            "📰 Notícias mundiais ao vivo\n"
            "🌤 Clima para sua cidade\n"
            "💱 Taxas de câmbio e ações\n"
            "📊 /chart — Gráfico interativo\n"
            "❓ /help — Guia completo de comandos\n"
            "🔄 /restart — Redefinir configurações"
        ),
        "Türkçe 🇹🇷": (
            "📰 Canlı dünya haberleri\n"
            "🌤 Şehrinizin hava durumu\n"
            "💱 Döviz ve hisse senedi kurları\n"
            "📊 /chart — Etkileşimli grafik\n"
            "❓ /help — Tam komut rehberi\n"
            "🔄 /restart — Ayarları sıfırla"
        ),
        "اردو 🇵🇰": (
            "📰 لائیو عالمی خبریں\n"
            "🌤 آپ کے شہر کا موسم\n"
            "💱 کرنسی اور اسٹاک ریٹس\n"
            "📊 /chart — انٹرایکٹو چارٹ\n"
            "❓ /help — مکمل کمانڈ گائیڈ\n"
            "🔄 /restart — ترتیبات ری سیٹ کریں"
        ),
        "Deutsch 🇩🇪": (
            "📰 Live-Weltnachrichten\n"
            "🌤 Wetter für Ihre Stadt\n"
            "💱 Währungs- und Aktienkurse\n"
            "📊 /chart — Interaktives Diagramm\n"
            "❓ /help — Vollständige Befehlsanleitung\n"
            "🔄 /restart — Einstellungen zurücksetzen"
        ),
        "Українська 🇺🇦": (
            "📰 Світові новини в реальному часі\n"
            "🌤 Погода у вашому місті\n"
            "💱 Курси валют та акцій\n"
            "📊 /chart — Інтерактивний графік\n"
            "❓ /help — Повний посібник команд\n"
            "🔄 /restart — Скинути налаштування"
        ),
        "Italiano 🇮🇹": (
            "📰 Notizie mondiali in tempo reale\n"
            "🌤 Meteo per la tua città\n"
            "💱 Tassi di cambio e azioni\n"
            "📊 /chart — Grafico interattivo\n"
            "❓ /help — Guida completa ai comandi\n"
            "🔄 /restart — Reimposta le impostazioni"
        ),
        "Español 🇲🇽": (
            "📰 Noticias mundiales en vivo\n"
            "🌤 Clima para tu ciudad\n"
            "💱 Tasas de cambio y acciones\n"
            "📊 /chart — Gráfico interactivo\n"
            "❓ /help — Guía completa de comandos\n"
            "🔄 /restart — Restablecer configuración"
        ),
    }
    contact_labels = {
        "العربية 🇮🇶": "للتواصل",
        "English 🇬🇧": "Contact us",
        "Русский 🇷🇺": "Связаться",
        "فارسی 🇮🇷": "تماس با ما",
        "हिन्दी 🇮🇳": "संपर्क करें",
        "Português 🇧🇷": "Contato",
        "Türkçe 🇹🇷": "İletişim",
        "اردو 🇵🇰": "رابطہ کریں",
        "Deutsch 🇩🇪": "Kontakt",
        "Українська 🇺🇦": "Зв'язатися",
        "Italiano 🇮🇹": "Contattaci",
        "Español 🇲🇽": "Contacto",
    }
    greeting = greetings.get(lang, greetings["English 🇬🇧"])
    body = body_lines.get(lang, body_lines["English 🇬🇧"])
    contact_label = contact_labels.get(lang, contact_labels["English 🇬🇧"])
    text = (
        greeting
        + "━━━━━━━━━━━━━━━\n"
        + body + "\n"
        + "━━━━━━━━━━━━━━━\n"
        + f"💬 {contact_label}: {CONTACT_LINK}"
    )
    bot.send_message(uid, text, parse_mode="Markdown", reply_markup=contact_markup)

# ======== /reset — إعادة الإعداد من الصفر ========
@bot.message_handler(commands=["reset"])
def cmd_reset(m):
    uid = m.from_user.id
    if uid in banned:
        bot.send_message(uid, "🚫 أنت محظور من استخدام البوت.")
        return
    if str(uid) not in users:
        welcome_user(uid)
        return
    user = users[str(uid)]
    kept = {
        "name": user.get("name", ""),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
        "sent_news": set(),
        "referrals": user.get("referrals", []),
        "referred_by": user.get("referred_by"),
        "join_date": user.get("join_date", ""),
        "unlocked_features": user.get("unlocked_features", []),
        "premium": user.get("premium", False),
    }
    kept = {k: v for k, v in kept.items() if v is not None}
    users[str(uid)] = kept
    _db_save_all_users(users)
    lang_map = {
        "العربية 🇮🇶":   "♻️ *تم إعادة ضبط البوت!*\n\nاختر لغتك من جديد 👇",
        "English 🇬🇧":  "♻️ *Bot has been reset!*\n\nPlease choose your language again 👇",
        "Русский 🇷🇺":  "♻️ *Бот сброшен!*\n\nПожалуйста, выберите язык снова 👇",
        "فارسی 🇮🇷":    "♻️ *ربات ریست شد!*\n\nلطفاً دوباره زبان خود را انتخاب کنید 👇",
        "हिन्दी 🇮🇳":   "♻️ *बॉट रीसेट हो गया!*\n\nकृपया फिर से अपनी भाषा चुनें 👇",
        "Português 🇧🇷":"♻️ *Bot foi redefinido!*\n\nPor favor, escolha seu idioma novamente 👇",
        "Türkçe 🇹🇷":   "♻️ *Bot sıfırlandı!*\n\nLütfen tekrar dilinizi seçin 👇",
        "اردو 🇵🇰":     "♻️ *بوٹ ری سیٹ ہو گیا!*\n\nبراہ کرم دوبارہ اپنی زبان منتخب کریں 👇",
        "Deutsch 🇩🇪":  "♻️ *Bot wurde zurückgesetzt!*\n\nBitte wählen Sie erneut Ihre Sprache 👇",
        "Українська 🇺🇦":"♻️ *Бота скинуто!*\n\nБудь ласка, виберіть мову знову 👇",
        "Italiano 🇮🇹": "♻️ *Bot reimpostato!*\n\nSi prega di scegliere di nuovo la lingua 👇",
        "Español 🇲🇽":  "♻️ *Bot restablecido!*\n\nPor favor, elige tu idioma nuevamente 👇",
    }
    reset_msg = lang_map.get(user.get("lang", "English 🇬🇧"), lang_map["English 🇬🇧"])
    bot.send_message(uid, reset_msg, parse_mode="Markdown")
    welcome_user(uid)


# ======== /restart — إعادة ضبط إعدادات المستخدم دون حذف بياناته ========
@bot.message_handler(commands=["restart"])
def cmd_restart(m):
    uid = m.from_user.id
    if uid in banned:
        bot.send_message(uid, "🚫 أنت محظور من استخدام البوت.")
        return
    if str(uid) not in users:
        send_first_time_welcome(uid, getattr(m.from_user, "first_name", ""))
        return
    user = users[str(uid)]
    old_lang = user.get("lang", "English 🇬🇧")
    kept = {
        "name": user.get("name", ""),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
        "telegram_lang": user.get("telegram_lang", ""),
        "sent_news": user.get("sent_news", set()),
        "referrals": user.get("referrals", []),
        "referred_by": user.get("referred_by"),
        "join_date": user.get("join_date", ""),
        "unlocked_features": user.get("unlocked_features", []),
        "premium": user.get("premium", False),
        "last_command": "/restart",
    }
    kept = {k: v for k, v in kept.items() if v is not None}
    users[str(uid)] = kept
    _db_save_all_users(users)
    restart_msg_map = {
        "العربية 🇮🇶":   "🔄 *تم إعادة ضبط إعداداتك!*\n\nسيتم الآن طلب اختيار لغتك ومنطقتك مجدداً.\nبياناتك ومعلوماتك محفوظة كما هي. 👇",
        "English 🇬🇧":  "🔄 *Your settings have been reset!*\n\nYou will now be asked to choose your language and region again.\nYour data and information are preserved. 👇",
        "Русский 🇷🇺":  "🔄 *Ваши настройки сброшены!*\n\nВас попросят снова выбрать язык и регион.\nВаши данные сохранены. 👇",
        "فارسی 🇮🇷":    "🔄 *تنظیمات شما ریست شد!*\n\nاکنون از شما خواسته میشود دوباره زبان و منطقه خود را انتخاب کنید.\nاطلاعات شما حفظ شده است. 👇",
        "हिन्दी 🇮🇳":   "🔄 *आपकी सेटिंग्स रीसेट हो गई हैं!*\n\nआपसे फिर से भाषा और क्षेत्र चुनने के लिए कहा जाएगा।\nआपका डेटा सुरक्षित है। 👇",
        "Português 🇧🇷":"🔄 *Suas configurações foram redefinidas!*\n\nAgora você será solicitado a escolher seu idioma e região novamente.\nSeus dados estão preservados. 👇",
        "Türkçe 🇹🇷":   "🔄 *Ayarlarınız sıfırlandı!*\n\nDil ve bölgenizi tekrar seçmeniz istenecek.\nVerileriniz korunmaktadır. 👇",
        "اردو 🇵🇰":     "🔄 *آپ کی ترتیبات ری سیٹ ہو گئی ہیں!*\n\nآپ سے دوبارہ زبان اور علاقہ منتخب کرنے کو کہا جائے گا۔\nآپ کا ڈیٹا محفوظ ہے۔ 👇",
        "Deutsch 🇩🇪":  "🔄 *Ihre Einstellungen wurden zurückgesetzt!*\n\nSie werden nun aufgefordert, erneut Ihre Sprache und Region zu wählen.\nIhre Daten sind erhalten. 👇",
        "Українська 🇺🇦":"🔄 *Ваші налаштування скинуті!*\n\nВас попросять знову вибрати мову та регіон.\nВаші дані збережені. 👇",
        "Italiano 🇮🇹": "🔄 *Le tue impostazioni sono state reimpostate!*\n\nTi verrà chiesto di scegliere di nuovo la lingua e la regione.\nI tuoi dati sono conservati. 👇",
        "Español 🇲🇽":  "🔄 *¡Tu configuración ha sido restablecida!*\n\nSe te pedirá que elijas tu idioma y región nuevamente.\nTus datos están preservados. 👇",
    }
    restart_msg = restart_msg_map.get(old_lang, restart_msg_map["English 🇬🇧"])
    bot.send_message(uid, restart_msg, parse_mode="Markdown")
    welcome_user(uid)
# ======== دوال الرسائل والتقييم والنشاط ========
def _forward_to_admin(m):
    uid = m.from_user.id
    user = users.get(str(uid), {})
    name = getattr(m.from_user, "first_name", "مجهول")
    utype = is_premium(uid)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = {
        "uid": uid,
        "name": name,
        "text": m.text or "",
        "premium": utype,
        "time": ts,
        "lang": user.get("lang", "-"),
        "country": user.get("country", "-"),
    }
    inbox_messages.append(entry)
    save_inbox()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"↩️ رد على {name}", callback_data=f"admin_reply_{uid}"))
    utype_label = "⭐ مميز" if utype else "👤 عادي"
    try:
        bot.send_message(ADMIN_ID,
            f"💬 *رسالة جديدة من مستخدم*\n\n"
            f"👤 الاسم: {name}\n"
            f"🆔 `{uid}` | {utype_label}\n"
            f"🌍 {user.get('country', '-')} | 🗣 {user.get('lang', '-')}\n"
            f"🕐 {ts}\n\n"
            f"📩 {m.text}",
            parse_mode="Markdown", reply_markup=markup)
    except Exception:
        pass

def _update_last_seen(uid):
    u = users.get(str(uid))
    if u:
        u["last_seen"] = datetime.datetime.now().strftime("%Y-%m-%d")
        _db_save_user(uid, u)

def send_rating_request():
    if bot_paused: return
    for uid, info in list(users.items()):
        try:
            if int(uid) in banned:
                continue
            if not info.get("notifications", True):
                continue
            if info.get("rating_sent_today"):
                continue
            markup = types.InlineKeyboardMarkup(row_width=5)
            markup.add(
                types.InlineKeyboardButton("1⭐", callback_data=f"rate_bot_1_{uid}"),
                types.InlineKeyboardButton("2⭐", callback_data=f"rate_bot_2_{uid}"),
                types.InlineKeyboardButton("3⭐", callback_data=f"rate_bot_3_{uid}"),
                types.InlineKeyboardButton("4⭐", callback_data=f"rate_bot_4_{uid}"),
                types.InlineKeyboardButton("5⭐", callback_data=f"rate_bot_5_{uid}"),
            )
            markup2 = types.InlineKeyboardMarkup(row_width=5)
            markup2.add(
                types.InlineKeyboardButton("1⭐", callback_data=f"rate_news_1_{uid}"),
                types.InlineKeyboardButton("2⭐", callback_data=f"rate_news_2_{uid}"),
                types.InlineKeyboardButton("3⭐", callback_data=f"rate_news_3_{uid}"),
                types.InlineKeyboardButton("4⭐", callback_data=f"rate_news_4_{uid}"),
                types.InlineKeyboardButton("5⭐", callback_data=f"rate_news_5_{uid}"),
            )
            bot.send_message(int(uid),
                "⭐ *كيف تقيّم البوت اليوم؟*\n\nاختر عدد النجوم:",
                parse_mode="Markdown", reply_markup=markup)
            bot.send_message(int(uid),
                "📰 *كيف تقيّم أخبار اليوم؟*\n\nاختر عدد النجوم:",
                parse_mode="Markdown", reply_markup=markup2)
            info["rating_sent_today"] = True
            _db_save_user(uid, info)
        except Exception:
            continue

def check_inactive_users():
    if bot_paused: return
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    for uid, info in list(users.items()):
        try:
            if int(uid) in banned:
                continue
            last_seen = info.get("last_seen", info.get("join_date", ""))
            if last_seen and last_seen < cutoff:
                reminders = info.get("inactive_reminders", 0)
                if reminders >= 2:
                    continue
                bot.send_message(int(uid),
                    "👋 *مرحباً، اشتقنا إليك!*\n\n"
                    "📰 لا تفوت آخر أخبار الشرق الأوسط.\n"
                    "اضغط /start للعودة للبوت.",
                    parse_mode="Markdown")
                info["inactive_reminders"] = reminders + 1
                _db_save_user(uid, info)
        except Exception:
            continue

def check_summary_hint():
    if bot_paused: return
    for uid, info in list(users.items()):
        try:
            if int(uid) in banned:
                continue
            if info.get("summary_hint_sent"):
                continue
            if info.get("used_summary"):
                continue
            join = info.get("join_date", "")
            if join:
                joined = datetime.datetime.strptime(join, "%Y-%m-%d")
                if (datetime.datetime.now() - joined).days >= 3:
                    bot.send_message(int(uid),
                        "📖 *هل تعلم؟*\n\n"
                        "يمكنك الحصول على ملخص يومي للأخبار!\n"
                        "اضغط على زر *📋 ملخص اليوم* من القائمة الرئيسية.",
                        parse_mode="Markdown")
                    info["summary_hint_sent"] = True
                    _db_save_user(uid, info)
        except Exception:
            continue

def reset_daily_rating_flags():
    for uid, info in list(users.items()):
        if info.get("rating_sent_today"):
            info["rating_sent_today"] = False

# ======== التعامل مع الرسائل ========
@bot.message_handler(func=lambda m: m.text is not None and not m.text.startswith('/'))
def handle_selection(m):
    uid = m.from_user.id
    text = m.text
    _update_last_seen(uid)
    if uid in banned:
        return
    if bot_paused and not is_admin(uid):
        bot.send_message(uid, pause_message)
        return
    user = users.get(str(uid))
    if not user:
        bot.send_message(uid, "👋 الرجاء إرسال /start أولاً.")
        return
    lang = user.get("lang", "English 🇬🇧")
    btn = BUTTONS.get(lang, BUTTONS["English 🇬🇧"])

    if user_states.get(uid) == "searching":
        user_states.pop(uid, None)
        search_news(uid, text)
        return

    if user_states.get(uid) == "converting_currency":
        user_states.pop(uid, None)
        parts = text.strip().split()
        if len(parts) >= 2:
            try:
                amount = float(parts[0].replace(",", ""))
                currency = parts[1].upper()
                convert_currency_msg(uid, amount, currency)
            except ValueError:
                bot.send_message(uid, st(lang, "convert_format_error"), parse_mode="Markdown")
        else:
            bot.send_message(uid, st(lang, "convert_send_both"), parse_mode="Markdown")
        return

    if user_states.get(uid) == "tracking_asset":
        user_states.pop(uid, None)
        symbol = text.strip().upper()
        if not symbol or len(symbol) > 15:
            bot.send_message(uid, "⚠️ رمز غير صحيح. أرسل مثال: AAPL أو BTC أو EUR")
            return
        existing = tracked_assets.get(str(uid), {}).get("assets", [])
        if symbol in existing:
            bot.send_message(uid, f"📌 *{symbol}* مضافة مسبقاً في قائمة التتبع.", parse_mode="Markdown")
        elif len(existing) >= 10:
            bot.send_message(uid, "⚠️ الحد الأقصى 10 أصول. أرسل /removetrack {رمز} لحذف واحدة.")
        else:
            price = fetch_asset_price(symbol)
            if price is None:
                bot.send_message(uid, f"⚠️ لم أتمكن من العثور على *{symbol}*. تأكد من الرمز وأعد المحاولة.", parse_mode="Markdown")
                return
            if str(uid) not in tracked_assets:
                tracked_assets[str(uid)] = {"assets": [], "last_prices": {}}
            tracked_assets[str(uid)]["assets"].append(symbol)
            tracked_assets[str(uid)]["last_prices"][symbol] = price
            save_tracked_assets()
            bot.send_message(uid,
                f"✅ تمت إضافة *{symbol}* للتتبع!\n"
                f"💰 السعر الحالي: `{price}`\n\n"
                f"🔔 ستصلك تنبيه عند تغير السعر بنسبة ±2%",
                parse_mode="Markdown"
            )
        return

    if user_states.get(uid) == "adding_keyword":
        user_states.pop(uid, None)
        if text.strip().startswith("حذف") or text.strip().startswith("delete"):
            user_keywords[str(uid)] = []
            save_keywords()
            bot.send_message(uid, "✅ تم حذف جميع كلماتك المفتاحية.")
        else:
            new_kws = [k.strip() for k in text.replace("،", ",").split(",") if k.strip()]
            existing = user_keywords.get(str(uid), [])
            for kw in new_kws:
                if kw not in existing:
                    existing.append(kw)
            user_keywords[str(uid)] = existing[:20]
            save_keywords()
            bot.send_message(uid, st(lang, "keywords_saved", n=len(new_kws)))
        return

    if "province" in user:
        update_stats("button", button=text)
        if text == btn["settings"]:
            users[str(uid)] = {"name": user["name"], "sent_news": set()}
            _db_save_all_users(users)
            welcome_user(uid)
        elif text == btn["weather"]:
            send_detailed_weather(uid)
        elif text == btn.get("forecast"):
            send_3day_forecast(uid)
        elif text == btn["news"]:
            send_hourly_news(uid)
        elif text == btn["all_news"]:
            send_all_news(uid)
        elif text == btn["mena_politics"]:
            send_mena_politics(uid)
        elif text == btn.get("trending"):
            send_trending_news(uid)
        elif text == btn.get("daily_summary"):
            send_daily_summary(uid)
        elif text == btn.get("voice_news"):
            _send_voice_news_menu(uid)
        elif text == btn.get("news_cats"):
            send_interest_menu(uid)
        elif text == btn["currency"]:
            send_currency(uid)
        elif text == btn.get("crypto"):
            send_crypto_prices(uid)
        elif text == btn.get("prayer"):
            send_prayer_times(uid)
        elif text == btn["search"]:
            user_states[uid] = "searching"
            bot.send_message(uid, t(lang, "search_prompt"))
        elif text == btn.get("deepsearch", "🧠 بحث عميق بالذكاء الاصطناعي"):
            _labels = {
                "العربية 🇮🇶": "✏️ أرسل الموضوع الذي تريد البحث عنه الآن:",
                "English 🇬🇧": "✏️ Send the topic you want to deep search now:",
                "Русский 🇷🇺": "✏️ Отправьте тему для глубокого поиска:",
                "فارسی 🇮🇷": "✏️ موضوع مورد نظر را ارسال کنید:",
                "हिन्दी 🇮🇳": "✏️ अभी खोज का विषय भेजें:",
                "Português 🇧🇷": "✏️ Envie o tópico que deseja pesquisar:",
                "Türkçe 🇹🇷": "✏️ Aramak istediğiniz konuyu şimdi gönderin:",
                "اردو 🇵🇰": "✏️ ابھی موضوع بھیجیں جو آپ تلاش کرنا چاہتے ہیں:",
                "Deutsch 🇩🇪": "✏️ Senden Sie jetzt das Thema, das Sie suchen möchten:",
                "Українська 🇺🇦": "✏️ Надішліть тему для глибокого пошуку зараз:",
                "Italiano 🇮🇹": "✏️ Invia ora l'argomento che vuoi cercare:",
                "Español 🇲🇽": "✏️ Envía el tema que deseas buscar ahora:",
            }
            prompt_txt = _labels.get(lang, "✏️ Send the topic you want to deep search now:")
            sent = bot.send_message(uid, prompt_txt)
            def _wait_for_topic_kbd(msg, _uid=uid, _lang=lang):
                topic = (msg.text or "").strip()
                if not topic:
                    return
                if _deepsearch_active.get(str(_uid)):
                    _busy_msgs = {
                        "العربية 🇮🇶": "⏳ بحث سابق لا يزال جارياً، انتظر حتى يكتمل",
                        "English 🇬🇧": "⏳ A previous search is still running, please wait",
                        "Русский 🇷🇺": "⏳ Предыдущий поиск ещё выполняется, подождите",
                        "فارسی 🇮🇷": "⏳ جستجوی قبلی هنوز در حال اجراست، لطفاً صبر کنید",
                        "हिन्दी 🇮🇳": "⏳ पिछली खोज अभी भी चल रही है, कृपया प्रतीक्षा करें",
                        "Português 🇧🇷": "⏳ Uma pesquisa anterior ainda está em execução, aguarde",
                        "Türkçe 🇹🇷": "⏳ Önceki arama hâlâ devam ediyor, lütfen bekleyin",
                        "اردو 🇵🇰": "⏳ پچھلی تلاش ابھی جاری ہے، براہ کرم انتظار کریں",
                        "Deutsch 🇩🇪": "⏳ Eine vorherige Suche läuft noch, bitte warten",
                        "Українська 🇺🇦": "⏳ Попередній пошук ще виконується, зачекайте",
                        "Italiano 🇮🇹": "⏳ Una ricerca precedente è ancora in corso, attendere",
                        "Español 🇲🇽": "⏳ Una búsqueda anterior sigue en curso, espere",
                    }
                    bot.send_message(_uid, _busy_msgs.get(_lang, _busy_msgs["English 🇬🇧"]))
                    return
                _deepsearch_active[str(_uid)] = True
                _start_msgs = {
                    "العربية 🇮🇶": (
                        f"🔍 *DeepSearch بدأ*\n\n📌 الموضوع: *{topic}*\n\n"
                        f"⏳ جاري فحص:\n• مصادر RSS العربية والدولية\n"
                        f"• مواقع إخبارية بالسكرابنق\n• المصادر الرسمية والحكومية\n"
                        f"• قاعدة بيانات NewsAPI العالمية\n• تحليل عميق بالذكاء الاصطناعي\n\n"
                        f"_قد يستغرق 5-15 دقيقة..._"
                    ),
                    "English 🇬🇧": (
                        f"🔍 *DeepSearch Started*\n\n📌 Topic: *{topic}*\n\n"
                        f"⏳ Scanning:\n• Arabic & international RSS feeds\n"
                        f"• News sites via scraping\n• Official & government sources\n"
                        f"• NewsAPI global database\n• Deep AI analysis\n\n"
                        f"_May take 5-15 minutes..._"
                    ),
                }
                progress_msg = bot.send_message(
                    _uid,
                    _start_msgs.get(_lang, _start_msgs["English 🇬🇧"]),
                    parse_mode="Markdown"
                )
                import threading as _th
                _th.Thread(
                    target=_deepsearch_worker,
                    args=(_uid, topic, progress_msg.message_id, _uid),
                    daemon=True
                ).start()
            bot.register_next_step_handler(sent, _wait_for_topic_kbd)
        elif text == btn.get("referral"):
            send_referral_stats(uid)
        elif text == btn.get("top_referrers"):
            send_top_referrers(uid)
        elif text == btn.get("sports"):
            send_sports_news(uid)
        elif text == btn.get("convert"):
            user_states[uid] = "converting_currency"
            bot.send_message(uid, st(lang, "convert_prompt"), parse_mode="Markdown")
        elif text == btn.get("my_stats"):
            send_my_stats(uid)
        elif text == btn.get("share_bot"):
            send_share_bot(uid)
        elif text == btn.get("public_stats"):
            send_public_stats(uid)
        elif text == btn.get("dollar_parallel"):
            send_dollar_parallel(uid)
        elif text == btn.get("weekly_summary"):
            send_weekly_summary_text(uid)
        elif text == btn.get("track_asset"):
            start_track_asset(uid)
        elif text in (btn["notif_on"], btn["notif_off"]):
            current = users[str(uid)].get("notifications", True)
            if not current:
                # كانت مغلقة — أعد التفعيل فوراً
                users[str(uid)]["notifications"] = True
                users[str(uid)].pop("news_paused_until", None)
                _db_save_all_users(users)
                bot.send_message(uid, st(lang, "notif_enabled"))
                send_main_menu(uid)
            else:
                # مفعّلة — اعرض خيارات الإيقاف
                pause_markup = types.InlineKeyboardMarkup(row_width=2)
                pause_markup.add(
                    types.InlineKeyboardButton("⏸ ساعة واحدة", callback_data="pause_news_1h"),
                    types.InlineKeyboardButton("⏸ 6 ساعات", callback_data="pause_news_6h"),
                    types.InlineKeyboardButton("⏸ يوم كامل", callback_data="pause_news_24h"),
                    types.InlineKeyboardButton("❌ إيقاف نهائي", callback_data="pause_news_off"),
                    types.InlineKeyboardButton("↩️ إلغاء", callback_data="pause_news_cancel"),
                )
                bot.send_message(uid, "🔕 *كم تريد إيقاف الأخبار؟*", parse_mode="Markdown", reply_markup=pause_markup)
        elif text == btn.get("premium", "⭐ Premium"):
            lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
            free_msg = {
                "العربية 🇮🇶":   "✅ *جميع المميزات مفتوحة للجميع مجاناً!*\n\nاستخدم /help لرؤية كل الميزات المتاحة.",
                "English 🇬🇧":   "✅ *All features are free for everyone!*\n\nUse /help to see all available features.",
                "Русский 🇷🇺":   "✅ *Все функции бесплатны для всех!*\n\nИспользуйте /help для просмотра доступных функций.",
                "فارسی 🇮🇷":    "✅ *همه امکانات برای همه رایگان است!*\n\nاز /help برای مشاهده امکانات استفاده کنید.",
                "हिन्दी 🇮🇳":   "✅ *सभी सुविधाएं सभी के लिए मुफ़्त हैं!*\n\n/help का उपयोग करें।",
                "Português 🇧🇷": "✅ *Todos os recursos são gratuitos para todos!*\n\nUse /help para ver todos os recursos.",
                "Türkçe 🇹🇷":   "✅ *Tüm özellikler herkese ücretsiz!*\n\nTüm özellikleri görmek için /help kullanın.",
                "اردو 🇵🇰":     "✅ *تمام خصوصیات سب کے لیے مفت ہیں!*\n\nتمام خصوصیات دیکھنے کے لیے /help استعمال کریں۔",
                "Deutsch 🇩🇪":  "✅ *Alle Funktionen sind für alle kostenlos!*\n\nVerwenden Sie /help, um alle Funktionen zu sehen.",
                "Українська 🇺🇦": "✅ *Усі функції безкоштовні для всіх!*\n\nВикористовуйте /help для перегляду функцій.",
                "Italiano 🇮🇹": "✅ *Tutte le funzionalità sono gratuite per tutti!*\n\nUsa /help per vedere tutte le funzionalità.",
                "Español 🇲🇽":  "✅ *¡Todas las funciones son gratuitas para todos!*\n\nUsa /help para ver todas las funciones disponibles.",
            }
            bot.send_message(uid, free_msg.get(lang, free_msg["English 🇬🇧"]), parse_mode="Markdown")
        else:
            _forward_to_admin(m)
            bot.send_message(uid, "✅ تم إرسال رسالتك للإدارة، سيتم الرد عليك قريباً.")
        return

    if "lang" not in user:
        for key, val in languages.items():
            if text == val:
                if val not in countries:
                    bot.send_message(uid, "⚠️ هذه اللغة غير متوفرة بالكامل. اختر لغة أخرى.")
                    return
                users[str(uid)]["lang"] = val
                user_feeds = RSS.get(val, [])
                try:
                    news_count = 0
                    for feed_url in user_feeds[:3]:
                        try:
                            feed_data = _parse_feed(feed_url)
                            if feed_data is None:
                                feed_data = feedparser.parse(feed_url)
                            if not feed_data:
                                continue
                            for item in feed_data.entries[:2]:
                                title = getattr(item, 'title', '')
                                link = getattr(item, 'link', '')
                                if title and link:
                                    item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                                    markup_news = make_news_share_markup(link, title, val, item_sum)
                                    src_name = get_source_name_from_url(feed_url)
                                    pub_time_str = _format_pub_time(_pub_dt_from_item(item), lang=val)
                                    bot.send_message(uid,
                                        format_news_item(t(val, "label_news"), title, val, src_name, pub_time_str, summary=item_sum),
                                        parse_mode="Markdown",
                                        reply_markup=markup_news
                                    )
                                    news_count += 1
                                    if news_count >= 3:
                                        break
                        except Exception:
                            pass
                        if news_count >= 3:
                            break
                except Exception:
                    pass
                users[str(uid)]["sent_news"] = prefill_sent_news(user_feeds)
                _db_save_all_users(users)
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for country in countries[val]:
                    markup.add(country)
                country_msg_text = COUNTRY_SELECT_MSG.get(val, COUNTRY_SELECT_MSG.get("English 🇬🇧", "Please select your country."))
                sent_country = bot.send_message(uid, country_msg_text, reply_markup=markup)
                try:
                    bot.pin_chat_message(uid, sent_country.message_id, disable_notification=True)
                except Exception:
                    pass
                send_usage_hint(uid, val)
                return
        bot.send_message(uid, "👇 Please choose a language from the list.")
        return

    if "country" not in user:
        lang = users[str(uid)].get("lang", lang)
        if lang in countries and text in countries[lang]:
            users[str(uid)]["country"] = text
            provinces = countries[lang][text]
            if provinces:
                _db_save_all_users(users)
                markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
                for prov in provinces:
                    markup.add(prov)
                bot.send_message(uid, st(lang, "choose_province"), reply_markup=markup)
            else:
                users[str(uid)]["province"] = text
                _db_save_all_users(users)
                update_stats("new_user", country=text, lang=lang)
                bot.send_message(uid, st(lang, "settings_saved"))
                send_main_menu(uid)
        else:
            bot.send_message(uid, st(lang, "choose_country_from_list"))
        return

    if "province" not in user:
        lang = users[str(uid)].get("lang", lang)
        country = user["country"]
        if lang in countries and country in countries[lang]:
            valid_provinces = countries[lang][country]
            if text in valid_provinces:
                users[str(uid)]["province"] = text
                _db_save_all_users(users)
                update_stats("new_user", country=country, lang=lang)
                bot.send_message(uid, st(lang, "settings_saved"))
                send_main_menu(uid)
            else:
                bot.send_message(uid, st(lang, "choose_province_from_list"))

BOT_SIGNATURE = "\n━━━━━━━━━━━━━━\nعبر بوت أخبار العالم\n@Iraqnowbot"

_NEWS_SIGNATURE_LOCALIZED = {
    "العربية 🇮🇶":   "عبر بوت أخبار العالم\n@Iraqnowbot",
    "English 🇬🇧":  "via World News Bot\n@Iraqnowbot",
    "Русский 🇷🇺":  "через World News Bot\n@Iraqnowbot",
    "فارسی 🇮🇷":    "از طریق World News Bot\n@Iraqnowbot",
    "हिन्दी 🇮🇳":   "World News Bot के माध्यम से\n@Iraqnowbot",
    "Português 🇧🇷": "via World News Bot\n@Iraqnowbot",
    "Türkçe 🇹🇷":   "World News Bot aracılığıyla\n@Iraqnowbot",
    "اردو 🇵🇰":     "World News Bot کے ذریعے\n@Iraqnowbot",
    "Deutsch 🇩🇪":  "über World News Bot\n@Iraqnowbot",
    "Українська 🇺🇦": "через World News Bot\n@Iraqnowbot",
    "Italiano 🇮🇹": "tramite World News Bot\n@Iraqnowbot",
    "Español 🇲🇽":  "vía World News Bot\n@Iraqnowbot",
}

_DEFAULT_NEWS_SIGNATURE = "عبر بوت أخبار العالم\n@Iraqnowbot"

def get_news_signature(lang=None):
    sep = news_settings.get("separator", "━━━━━━━━━━━━━━")
    custom_sig = news_settings.get("signature", _DEFAULT_NEWS_SIGNATURE)
    if custom_sig != _DEFAULT_NEWS_SIGNATURE:
        sig = custom_sig
    elif lang and lang in _NEWS_SIGNATURE_LOCALIZED:
        sig = _NEWS_SIGNATURE_LOCALIZED[lang]
    else:
        sig = custom_sig
    return f"\n{sep}\n{sig}"

# ======== نصوص أزرار مشاركة الأخبار حسب اللغة ========
NEWS_SHARE_LABELS = {
    "العربية 🇮🇶": {
        "open": "🔗 فتح الخبر",
        "share_news": "📤 شارك الخبر",
        "share_bot": "🤖 شارك البوت",
        "via": "عبر",
        "bot_promo": "بوت الأخبار والطقس\nآخر أخبار العالم والطقس والعملات على مدار الساعة!",
        "summary_btn": "📄 ملخص الخبر",
        "no_summary": "⚠️ لا يوجد ملخص متوفر لهذا الخبر.",
        "follow_story": "🔔 تابع هذه القصة",
        "following_story": "✅ تتابع هذه القصة",
        "follow_done": "✅ ستصلك تحديثات عن هذه القصة!",
        "already_following": "أنت تتابع هذه القصة بالفعل.",
        "unfollow_story": "🔕 إلغاء المتابعة",
        "unfollow_done": "✅ تم إلغاء متابعة هذه القصة.",
        "story_update": "🔔 تحديث على قصة تتابعها",
    },
    "English 🇬🇧": {
        "open": "🔗 Open Article",
        "share_news": "📤 Share News",
        "share_bot": "🤖 Share Bot",
        "via": "via",
        "bot_promo": "News & Weather Bot\nLatest world news, weather & currency rates 24/7!",
        "summary_btn": "📄 Article Summary",
        "no_summary": "⚠️ No summary available for this article.",
        "follow_story": "🔔 Follow Story",
        "following_story": "✅ Following Story",
        "follow_done": "✅ You'll get updates on this story!",
        "already_following": "You're already following this story.",
        "unfollow_story": "🔕 Unfollow",
        "unfollow_done": "✅ Story unfollowed.",
        "story_update": "🔔 Story Update",
    },
    "Русский 🇷🇺": {
        "open": "🔗 Открыть статью",
        "share_news": "📤 Поделиться",
        "share_bot": "🤖 Поделиться ботом",
        "via": "через",
        "bot_promo": "Бот новостей и погоды\nПоследние мировые новости, погода и курсы валют!",
        "summary_btn": "📄 Краткое содержание",
        "no_summary": "⚠️ Краткое содержание недоступно.",
        "follow_story": "🔔 Следить за темой",
        "following_story": "✅ Вы следите",
        "follow_done": "✅ Вы будете получать обновления!",
        "already_following": "Вы уже следите за этой темой.",
        "unfollow_story": "🔕 Отписаться",
        "unfollow_done": "✅ Вы отписались от темы.",
        "story_update": "🔔 Обновление темы",
    },
    "فارسی 🇮🇷": {
        "open": "🔗 باز کردن خبر",
        "share_news": "📤 اشتراکگذاری",
        "share_bot": "🤖 اشتراکگذاری ربات",
        "via": "از طریق",
        "bot_promo": "ربات اخبار و آبوهوا\nآخرین اخبار جهان، آبوهوا و نرخ ارز!",
        "summary_btn": "📄 خلاصه خبر",
        "no_summary": "⚠️ خلاصهای برای این خبر موجود نیست.",
        "follow_story": "🔔 دنبال کردن خبر",
        "following_story": "✅ در حال دنبال کردن",
        "follow_done": "✅ بهروزرسانیها دریافت خواهید کرد!",
        "already_following": "شما در حال دنبال کردن این خبر هستید.",
        "unfollow_story": "🔕 لغو دنبال کردن",
        "unfollow_done": "✅ دنبال کردن لغو شد.",
        "story_update": "🔔 بهروزرسانی خبر",
    },
    "हिन्दी 🇮🇳": {
        "open": "🔗 खबर खोलें",
        "share_news": "📤 शेयर करें",
        "share_bot": "🤖 बॉट शेयर करें",
        "via": "के द्वारा",
        "bot_promo": "न्यूज़ और मौसम बॉट\nताज़ा खबरें, मौसम और मुद्रा दरें!",
        "summary_btn": "📄 खबर सारांश",
        "no_summary": "⚠️ इस खबर का कोई सारांश उपलब्ध नहीं है।",
        "follow_story": "🔔 स्टोरी फॉलो करें",
        "following_story": "✅ फॉलो कर रहे हैं",
        "follow_done": "✅ आपको अपडेट मिलेंगे!",
        "already_following": "आप पहले से इस स्टोरी को फॉलो कर रहे हैं।",
        "unfollow_story": "🔕 अनफॉलो करें",
        "unfollow_done": "✅ स्टोरी अनफॉलो हो गई।",
        "story_update": "🔔 स्टोरी अपडेट",
    },
    "Português 🇧🇷": {
        "open": "🔗 Abrir notícia",
        "share_news": "📤 Compartilhar",
        "share_bot": "🤖 Compartilhar bot",
        "via": "via",
        "bot_promo": "Bot de Notícias e Clima\nÚltimas notícias, clima e câmbio!",
        "summary_btn": "📄 Resumo da Notícia",
        "no_summary": "⚠️ Nenhum resumo disponível para esta notícia.",
        "follow_story": "🔔 Seguir história",
        "following_story": "✅ Seguindo",
        "follow_done": "✅ Você receberá atualizações!",
        "already_following": "Você já está seguindo esta história.",
        "unfollow_story": "🔕 Deixar de seguir",
        "unfollow_done": "✅ Você deixou de seguir.",
        "story_update": "🔔 Atualização da história",
    },
    "Türkçe 🇹🇷": {
        "open": "🔗 Haberi Aç",
        "share_news": "📤 Paylaş",
        "share_bot": "🤖 Botu Paylaş",
        "via": "ile",
        "bot_promo": "Haber ve Hava Durumu Botu\nSon haberler, hava durumu ve döviz kurları!",
        "summary_btn": "📄 Haber Özeti",
        "no_summary": "⚠️ Bu haber için özet mevcut değil.",
        "follow_story": "🔔 Konuyu Takip Et",
        "following_story": "✅ Takip Ediliyor",
        "follow_done": "✅ Güncellemeler alacaksınız!",
        "already_following": "Bu konuyu zaten takip ediyorsunuz.",
        "unfollow_story": "🔕 Takibi Bırak",
        "unfollow_done": "✅ Konu takipten çıkarıldı.",
        "story_update": "🔔 Konu Güncellemesi",
    },
    "اردو 🇵🇰": {
        "open": "🔗 خبر کھولیں",
        "share_news": "📤 شیئر کریں",
        "share_bot": "🤖 بوٹ شیئر کریں",
        "via": "کے ذریعے",
        "bot_promo": "خبر اور موسم بوٹ\nتازہ خبریں، موسم اور کرنسی ریٹ!",
        "summary_btn": "📄 خبر کا خلاصہ",
        "no_summary": "⚠️ اس خبر کا کوئی خلاصہ دستیاب نہیں۔",
        "follow_story": "🔔 اسٹوری فالو کریں",
        "following_story": "✅ فالو ہو رہی ہے",
        "follow_done": "✅ آپ کو اپڈیٹس ملیں گی!",
        "already_following": "آپ پہلے سے اسٹوری فالو کر رہے ہیں۔",
        "unfollow_story": "🔕 ان فالو کریں",
        "unfollow_done": "✅ اسٹوری ان فالو ہو گئی۔",
        "story_update": "🔔 اسٹوری اپڈیٹ",
    },
    "Deutsch 🇩🇪": {
        "open": "🔗 Artikel öffnen",
        "share_news": "📤 Teilen",
        "share_bot": "🤖 Bot teilen",
        "via": "über",
        "bot_promo": "Nachrichten- und Wetter-Bot\nAktuelle Nachrichten, Wetter und Wechselkurse!",
        "summary_btn": "📄 Artikel-Zusammenfassung",
        "no_summary": "⚠️ Keine Zusammenfassung für diesen Artikel verfügbar.",
        "follow_story": "🔔 Thema verfolgen",
        "following_story": "✅ Wird verfolgt",
        "follow_done": "✅ Sie erhalten Updates!",
        "already_following": "Sie verfolgen dieses Thema bereits.",
        "unfollow_story": "🔕 Abonnement beenden",
        "unfollow_done": "✅ Thema abonniert.",
        "story_update": "🔔 Themen-Update",
    },
    "Українська 🇺🇦": {
        "open": "🔗 Відкрити статтю",
        "share_news": "📤 Поділитися",
        "share_bot": "🤖 Поділитися ботом",
        "via": "через",
        "bot_promo": "Бот новин і погоди\nОстанні новини, погода та курси валют!",
        "summary_btn": "📄 Короткий зміст",
        "no_summary": "⚠️ Короткий зміст недоступний.",
        "follow_story": "🔔 Стежити за темою",
        "following_story": "✅ Стежите",
        "follow_done": "✅ Ви отримуватимете оновлення!",
        "already_following": "Ви вже стежите за цією темою.",
        "unfollow_story": "🔕 Відписатися",
        "unfollow_done": "✅ Ви відписалися від теми.",
        "story_update": "🔔 Оновлення теми",
    },
    "Italiano 🇮🇹": {
        "open": "🔗 Apri articolo",
        "share_news": "📤 Condividi",
        "share_bot": "🤖 Condividi bot",
        "via": "tramite",
        "bot_promo": "Bot Notizie e Meteo\nUltime notizie, meteo e tassi di cambio!",
        "summary_btn": "📄 Riepilogo Articolo",
        "no_summary": "⚠️ Nessun riepilogo disponibile per questo articolo.",
        "follow_story": "🔔 Segui la storia",
        "following_story": "✅ Stai seguendo",
        "follow_done": "✅ Riceverai aggiornamenti!",
        "already_following": "Stai già seguendo questa storia.",
        "unfollow_story": "🔕 Smetti di seguire",
        "unfollow_done": "✅ Non segui più questa storia.",
        "story_update": "🔔 Aggiornamento storia",
    },
    "Español 🇲🇽": {
        "open": "🔗 Abrir artículo",
        "share_news": "📤 Compartir",
        "share_bot": "🤖 Compartir bot",
        "via": "vía",
        "bot_promo": "Bot de Noticias y Clima\n¡Últimas noticias, clima y tipos de cambio!",
        "summary_btn": "📄 Resumen del Artículo",
        "no_summary": "⚠️ No hay resumen disponible para este artículo.",
        "follow_story": "🔔 Seguir historia",
        "following_story": "✅ Siguiendo",
        "follow_done": "✅ ¡Recibirás actualizaciones!",
        "already_following": "Ya estás siguiendo esta historia.",
        "unfollow_story": "🔕 Dejar de seguir",
        "unfollow_done": "✅ Historia sin seguir.",
        "story_update": "🔔 Actualización de historia",
    },
}

# ======== رسائل النظام المترجمة ========
MSGS = {
    "العربية 🇮🇶": {
        "no_news": "⚠️ لا توجد أخبار جديدة الآن.",
        "no_results": "⚠️ لا توجد نتائج لهذا البحث.",
        "search_error": "⚠️ حدث خطأ أثناء البحث.",
        "no_trending": "⚠️ لا توجد أخبار رائجة الآن، حاول لاحقاً.",
        "trending_header": "🔥 *الأكثر تداولاً*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *أخبار الرياضة*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ لا توجد أخبار رياضية جديدة الآن.",
        "no_sports_source": "⚠️ لا توجد مصادر رياضية لهذه اللغة.",
        "no_mena": "⚠️ لا توجد أخبار سياسية جديدة الآن، حاول مرة أخرى لاحقاً.",
        "no_source": "⚠️ لا توجد مصادر أخبار لهذه اللغة حالياً.",
        "weather_error": "⚠️ لا يمكن جلب بيانات الطقس حالياً.",
        "forecast_error": "⚠️ لا يمكن جلب توقعات الساعات.",
        "no_weekly": "⚠️ لا توجد أخبار لإنشاء الملخص الأسبوعي.",
        "currency_error": "⚠️ لا يمكن جلب أسعار العملات حالياً.",
        "search_prompt": "🔍 اكتب كلمة البحث:",
        "label_breaking": "🚨 خبر عاجل",
        "label_news": "🚨 خبر",
        "label_mena": "📰 أخبار الشرق الأوسط السياسية",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ لم يتم تحديد مدينتك بعد.",
        "city_not_found": "⚠️ لم يتم العثور على بيانات الطقس لمدينة: {city}",
        "weather_header": "{emoji} *الطقس في {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *الحرارة:* {temp}°C\n🤔 *يشعر كـ:* {feels}°C\n🔼 أعلى: {temp_max}°C  |  🔽 أدنى: {temp_min}°C\n\n☁️ *الحالة:* {desc}\n🌫 *الغيوم:* {clouds}%\n👁 *الرؤية:* {visibility_km} كم\n\n💧 *الرطوبة:* {humidity}%\n🌀 *الضغط الجوي:* {pressure} hPa\n☀️ *مؤشر UV:* {uvi}\n\n💨 *الرياح:* {wind_speed} م/ث | {wind_dir}\n💨 *أقصى هبوب:* {wind_gust} م/ث\n\n🌅 *الشروق:* {sunrise}  |  🌇 *الغروب:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *توقعات الطقس لـ 3 أيام — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *توقعات الطقس لـ 7 أيام — {city}*\n\n",
        "hourly_header": "🕐 *الطقس كل 3 ساعات — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "م/ث",
        "uv_low": "منخفض",
        "uv_moderate": "متوسط",
        "uv_high": "مرتفع",
        "uv_very_high": "خطر",
        "uv_extreme": "شديد الخطورة",
        "uv_na": "غير متوفر",
        "wind_N": "⬆️ شمال",
        "wind_NE": "↗️ شمال شرق",
        "wind_E": "➡️ شرق",
        "wind_SE": "↘️ جنوب شرق",
        "wind_S": "⬇️ جنوب",
        "wind_SW": "↙️ جنوب غرب",
        "wind_W": "⬅️ غرب",
        "wind_NW": "↖️ شمال غرب",
        "crypto_header": "💎 *أسعار العملات الرقمية*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 البيانات من CoinGecko",
        "crypto_error": "⚠️ لا يمكن جلب أسعار العملات الرقمية الآن، حاول لاحقاً.",
        "prayer_header": "🕌 *أوقات الصلاة في {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 الفجر:     `{fajr}`\n☀️ الشروق:   `{sunrise}`\n🌞 الظهر:    `{dhuhr}`\n🌇 العصر:    `{asr}`\n🌆 المغرب:   `{maghrib}`\n🌙 العشاء:   `{isha}`\n━━━━━━━━━━━━━━━\n🔄 البيانات من Aladhan API",
        "prayer_no_city": "⚠️ لم يتم تحديد مدينتك. اضغط على تغيير الإعدادات وأعد الإعداد.",
        "prayer_city_error": "⚠️ لا يمكن جلب أوقات الصلاة لمدينة: {city}\nتأكد من اسم المدينة باللغة الإنجليزية في إعداداتك.",
        "prayer_error": "⚠️ لا يمكن جلب أوقات الصلاة الآن، حاول لاحقاً.",
        "referral_header": "🎁 *نظام الدعوات*\n━━━━━━━━━━━━━━━\n\n🔗 *رابط دعوتك الخاص:*\n`{link}`\n\n👥 *إجمالي من دعوتهم:* `{count}` شخص\n\n━━━━━━━━━━━━━━━\n📤 شارك الرابط مع أصدقائك وعائلتك!\nكل شخص ينضم عبر رابطك سيُحتسب لك. 🎯",
        "referral_share_btn": "📤 مشاركة الرابط",
        "share_bot_header": "📢 *انشر البوت وساعدنا بالوصول لأكثر مستخدمين!*\n\n🔗 *رابط البوت:*\n@{username}\n\n📌 أو عبر الرابط:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 شارك البوت مع أصدقائك للحصول على:\n📰 آخر الأخبار العراقية والعالمية\n🌤 حالة الطقس الفورية\n💱 أسعار العملات\n🕌 أوقات الصلاة\n💎 أسعار العملات الرقمية",
        "share_bot_btn": "📤 مشاركة البوت",
        "open_bot_btn": "🔗 فتح البوت",
        "public_stats_header": "📊 *إحصائيات البوت*\n━━━━━━━━━━━━━━━\n\n👥 إجمالي المستخدمين: *{total}*\n✅ مستخدمون نشطون: *{active}*\n🆕 انضموا اليوم: *{today}*\n⭐ مشتركون مميزون: *{premium}*\n\n",
        "public_stats_langs": "🌍 *أكثر اللغات استخداماً:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *إحصائياتك الشخصية*\n━━━━━━━━━━━━━━━\n\n👤 الاسم: *{name}*\n🌍 اللغة: *{lang}*\n🏙 المدينة: *{city}*\n📅 تاريخ الانضمام: *{join}*\n\n📰 أخبار استلمتها: *{news}*\n🎁 دعوات أرسلتها: *{refs}*\n🔑 كلمات مفتاحية: *{kws}*\n⭐ اشتراك مميز: *{prem}*\n🔔 الإشعارات: *{notif}*\n",
        "my_stats_prem_yes": "⭐ نعم",
        "my_stats_prem_no": "❌ لا",
        "my_stats_notif_on": "🔔 مفعّلة",
        "my_stats_notif_off": "🔕 متوقفة",
        "my_stats_user": "مستخدم",
        "daily_summary_header": "📋 *ملخص أخبار اليوم — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ لا توجد مصادر أخبار لهذه اللغة حالياً.",
        "daily_summary_no_news": "⚠️ لا توجد أخبار متاحة الآن، حاول لاحقاً.",
        "top_referrers_header": "🏆 *أفضل الداعين*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 لا توجد دعوات بعد، كن أول من يدعو أصدقاءه! 🎯",
        "top_referrers_invite": "دعوة",
        "dollar_header": "💵 *سعر الدولار مقابل الدينار العراقي*\n\n🏪 السوق الموازية:\n{rate}\n\n⏰ آخر تحديث: `{time}`\n📡 المصدر: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "بيع",
        "dollar_buy": "شراء",
        "dollar_official": "السعر: `{price}` دينار\n_(السعر الرسمي — قد يختلف عن السوق)_",
        "dollar_error": "⚠️ تعذّر جلب سعر الدولار حالياً. حاول لاحقاً.",
        "weekly_summary_header": "📰 *الملخص الأسبوعي — أبرز {count} خبر*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *ملخص أخبار الأسبوع*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ جاري جمع أبرز أخبار الأسبوع...",
        "weekly_summary_text_no_source": "⚠️ لا توجد مصادر أخبار متاحة لهذه اللغة.",
        "weekly_summary_text_no_news": "⚠️ لا توجد أخبار كافية هذا الأسبوع.",
        "currency_table_header": "📊 *جدول أسعار الصرف الكامل مقابل الدولار 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *قائمة المميز — اختر ما تريد:*",
        "premium_btn_7day": "🌤 توقعات 7 أيام",
        "premium_btn_hourly": "🕐 طقس كل 3 ساعات",
        "premium_btn_addcity": "🏙 إضافة مدينة",
        "premium_btn_mycities": "📋 مدنيّ المحفوظة",
        "premium_btn_interests": "📌 اهتماماتي",
        "premium_btn_currency_alert": "💱 تنبيه العملات",
        "premium_btn_currency_table": "📊 جدول العملات",
        "premium_btn_notif_time": "🕐 وقت الإشعارات",
        "premium_btn_weekly": "📰 ملخص أسبوعي",
        "premium_btn_keywords": "🔑 كلمات مفتاحية",
        "premium_subscribe_btn": "⭐ طلب الاشتراك المميز",
        "broadcast_weather_msg": "🌤 الطقس في {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *تتبع العملات والأسهم والسلع*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *قائمتك الحالية:*\n",
        "track_count": "\n({count}/20 رمز)\n\n",
        "track_add_hint": "➕ *لإضافة رمز:* أرسل اسمه مباشرة\n\n",
        "track_crypto_label": "💎 *عملات رقمية:*\n",
        "track_fiat_label": "💱 *عملات فيات:*\n",
        "track_stocks_label": "📈 *أسهم:*\n",
        "track_commodities_label": "🏅 *سلع ومؤشرات:*\n",
        "track_alert_hint": "🔔 *ستصلك تنبيهات فورية عند تغير ±1% وتقرير ساعي بأسعارك.*\n\n",
        "track_remove_hint": "❌ لحذف رمز: `/removetrack AAPL`\n",
        "track_list_hint": "📋 لعرض قائمتك: `/mytrack`",
        "track_empty": "📌 قائمة التتبع فارغة.\nاضغط *تتبع عملة/سهم* لإضافة رموز.",
        "track_list_header": "📌 *رموزك المتتبعة:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *تنبيهات أسعارك*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 ارتفع",
        "track_fell": "📉 انخفض",
        "track_report_title": "📊 *تقرير ساعي — أصولك المتتبعة*\n",
        "track_unavailable": "غير متوفر",
        "track_remove_usage": "⚠️ حدد الرمز. مثال: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* غير موجود في قائمتك.",
        "track_removed": "✅ تم حذف *{symbol}* من قائمة التتبع.",
        "interest_save_btn": "💾 حفظ",
        "interest_choose_msg": "📌 *اختر اهتماماتك (يمكن اختيار أكثر من واحد):*",
        "currency_rate_header": "💱 *أسعار الصرف مقابل الدولار 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *تحويل {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ عملة غير مدعومة: {currency}",
        "currency_fetch_error": "⚠️ لا يمكن جلب أسعار العملات.",
        "city_add_success": "✅ تمت إضافة المدينة: *{city}*",
        "currency_alert_set": "✅ ستصلك تنبيهات عندما يصل الدولار إلى `{rate}` من عملتك.",
        "currency_alert_invalid": "❌ أدخل رقماً، مثال: 1600",
        "notif_time_set": "✅ سيُرسل الملخص الصباحي في الساعة *{hour}:00* يومياً.",
        "notif_time_invalid": "❌ أدخل رقماً من 0 إلى 23 (مثال: 8 للساعة 8 صباحاً)",
        "currency_eur": "🇪🇺 اليورو",
        "currency_gbp": "🇬🇧 الجنيه الإسترليني",
        "currency_iqd": "🇮🇶 الدينار العراقي",
        "currency_try": "🇹🇷 الليرة التركية",
        "currency_sar": "🇸🇦 الريال السعودي",
        "search_results_header": "🔍 *نتائج البحث عن: {query}*",
        "search_no_results": "⚠️ لا توجد نتائج لهذا البحث.",
    },
    "English 🇬🇧": {
        "no_news": "⚠️ No new news available right now.",
        "no_results": "⚠️ No results found for your search.",
        "search_error": "⚠️ An error occurred while searching.",
        "no_trending": "⚠️ No trending news right now, try again later.",
        "trending_header": "🔥 *Trending News*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Sports News*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ No new sports news right now.",
        "no_sports_source": "⚠️ No sports sources available for this language.",
        "no_mena": "⚠️ No new political news right now, try again later.",
        "no_source": "⚠️ No news sources available for this language right now.",
        "weather_error": "⚠️ Cannot fetch weather data right now.",
        "forecast_error": "⚠️ Cannot fetch hourly forecast.",
        "no_weekly": "⚠️ No news available for weekly summary.",
        "currency_error": "⚠️ Cannot fetch currency rates right now.",
        "search_prompt": "🔍 Type your search keyword:",
        "label_breaking": "🚨 Breaking News",
        "label_news": "🚨 News",
        "label_mena": "📰 Middle East Political News",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Your city is not set yet.",
        "city_not_found": "⚠️ Weather data not found for: {city}",
        "weather_header": "{emoji} *Weather in {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Feels like:* {feels}°C\n🔼 Max: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Condition:* {desc}\n🌫 *Clouds:* {clouds}%\n👁 *Visibility:* {visibility_km} km\n\n💧 *Humidity:* {humidity}%\n🌀 *Pressure:* {pressure} hPa\n☀️ *UV Index:* {uvi}\n\n💨 *Wind:* {wind_speed} m/s | {wind_dir}\n💨 *Gusts:* {wind_gust} m/s\n\n🌅 *Sunrise:* {sunrise}  |  🌇 *Sunset:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3-Day Weather Forecast — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7-Day Weather Forecast — {city}*\n\n",
        "hourly_header": "🕐 *3-Hourly Weather — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Low",
        "uv_moderate": "Moderate",
        "uv_high": "High",
        "uv_very_high": "Very High",
        "uv_extreme": "Extreme",
        "uv_na": "N/A",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ E",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SW",
        "wind_W": "⬅️ W",
        "wind_NW": "↖️ NW",
        "crypto_header": "💎 *Crypto Prices*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Data from CoinGecko",
        "crypto_error": "⚠️ Cannot fetch crypto prices right now, try later.",
        "prayer_header": "🕌 *Prayer Times in {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Sunrise: `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Data from Aladhan API",
        "prayer_no_city": "⚠️ Your city is not set. Go to Settings and set it up.",
        "prayer_city_error": "⚠️ Cannot fetch prayer times for: {city}\nMake sure the city name is in English in your settings.",
        "prayer_error": "⚠️ Cannot fetch prayer times right now, try later.",
        "referral_header": "🎁 *Referral System*\n━━━━━━━━━━━━━━━\n\n🔗 *Your referral link:*\n`{link}`\n\n👥 *Total invited:* `{count}` people\n\n━━━━━━━━━━━━━━━\n📤 Share with friends & family!\nEveryone who joins via your link counts. 🎯",
        "referral_share_btn": "📤 Share Link",
        "share_bot_header": "📢 *Share the bot and help us grow!*\n\n🔗 *Bot link:*\n@{username}\n\n📌 Or via link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Share with friends to get:\n📰 Latest world news\n🌤 Live weather\n💱 Currency rates\n🕌 Prayer times\n💎 Crypto prices",
        "share_bot_btn": "📤 Share Bot",
        "open_bot_btn": "🔗 Open Bot",
        "public_stats_header": "📊 *Bot Statistics*\n━━━━━━━━━━━━━━━\n\n👥 Total users: *{total}*\n✅ Active users: *{active}*\n🆕 Joined today: *{today}*\n⭐ Premium subscribers: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Most used languages:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Your Personal Stats*\n━━━━━━━━━━━━━━━\n\n👤 Name: *{name}*\n🌍 Language: *{lang}*\n🏙 City: *{city}*\n📅 Join date: *{join}*\n\n📰 News received: *{news}*\n🎁 Referrals sent: *{refs}*\n🔑 Keywords: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notifications: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Yes",
        "my_stats_prem_no": "❌ No",
        "my_stats_notif_on": "🔔 Active",
        "my_stats_notif_off": "🔕 Paused",
        "my_stats_user": "User",
        "daily_summary_header": "📋 *Today's News Summary — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ No news sources available for this language.",
        "daily_summary_no_news": "⚠️ No news available right now, try later.",
        "top_referrers_header": "🏆 *Top Referrers*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 No referrals yet — be the first to invite friends! 🎯",
        "top_referrers_invite": "invite(s)",
        "dollar_header": "💵 *USD vs Iraqi Dinar*\n\n🏪 Parallel market:\n{rate}\n\n⏰ Last updated: `{time}`\n📡 Source: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Sell",
        "dollar_buy": "Buy",
        "dollar_official": "Rate: `{price}` IQD\n_(Official rate — may differ from market)_",
        "dollar_error": "⚠️ Cannot fetch dollar rate right now. Try later.",
        "weekly_summary_header": "📰 *Weekly Summary — Top {count} stories*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Weekly News Summary*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Collecting this week's top stories...",
        "weekly_summary_text_no_source": "⚠️ No news sources available for this language.",
        "weekly_summary_text_no_news": "⚠️ Not enough news this week.",
        "currency_table_header": "📊 *Full Exchange Rate Table vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Premium Menu — Choose:*",
        "premium_btn_7day": "🌤 7-Day Forecast",
        "premium_btn_hourly": "🕐 3-Hourly Weather",
        "premium_btn_addcity": "🏙 Add City",
        "premium_btn_mycities": "📋 My Saved Cities",
        "premium_btn_interests": "📌 My Interests",
        "premium_btn_currency_alert": "💱 Currency Alert",
        "premium_btn_currency_table": "📊 Currency Table",
        "premium_btn_notif_time": "🕐 Notification Time",
        "premium_btn_weekly": "📰 Weekly Summary",
        "premium_btn_keywords": "🔑 Keywords",
        "premium_subscribe_btn": "⭐ Request Premium Subscription",
        "broadcast_weather_msg": "🌤 Weather in {city}: {temp}°C\n☁️ {desc}",
        "city_add_success": "✅ City added: *{city}*",
        "currency_eur": "🇪🇺 Euro",
        "currency_gbp": "🇬🇧 British Pound",
        "currency_iqd": "🇮🇶 Iraqi Dinar",
        "currency_try": "🇹🇷 Turkish Lira",
        "currency_sar": "🇸🇦 Saudi Riyal",
        "search_results_header": "🔍 *Search results for: {query}*",
        "search_no_results": "⚠️ No results found for this search.",
        "track_header": "📌 *Track Assets — Crypto, Forex, Stocks & Commodities*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Your current list:*\n",
        "track_count": "\n({count}/20 symbols)\n\n",
        "track_add_hint": "➕ *Add a symbol:* send its name directly\n\n",
        "track_crypto_label": "💎 *Crypto:*\n",
        "track_fiat_label": "💱 *Fiat Currencies:*\n",
        "track_stocks_label": "📈 *Stocks:*\n",
        "track_commodities_label": "🏅 *Commodities & Indices:*\n",
        "track_alert_hint": "🔔 *You will receive instant alerts on ±1% change and an hourly price report.*\n\n",
        "track_remove_hint": "❌ To remove a symbol: `/removetrack AAPL`\n",
        "track_list_hint": "📋 To view your list: `/mytrack`",
        "track_empty": "📌 Tracking list is empty.\nTap *Track Asset* to add symbols.",
        "track_list_header": "📌 *Your tracked assets:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Price Alerts*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 rose",
        "track_fell": "📉 fell",
        "track_report_title": "📊 *Hourly Report — Your Tracked Assets*\n",
        "track_unavailable": "unavailable",
        "track_remove_usage": "⚠️ Specify the symbol. Example: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* not found in your list.",
        "track_removed": "✅ *{symbol}* removed from your tracking list.",
        "interest_save_btn": "💾 Save",
        "interest_choose_msg": "📌 *Choose your interests (multiple allowed):*",
        "currency_rate_header": "💱 *Exchange Rates vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Convert {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Unsupported currency: {currency}",
        "currency_fetch_error": "⚠️ Unable to fetch exchange rates.",
        "currency_alert_set": "✅ You will be notified when USD reaches `{rate}` of your currency.",
        "currency_alert_invalid": "❌ Enter a number, e.g.: 1600",
        "notif_time_set": "✅ Morning summary will be sent at *{hour}:00* daily.",
        "notif_time_invalid": "❌ Enter a number from 0 to 23 (e.g.: 8 for 8 AM)",
    },
    "Русский 🇷🇺": {
        "no_news": "⚠️ Новых новостей нет.",
        "no_results": "⚠️ По вашему запросу ничего не найдено.",
        "search_error": "⚠️ При поиске произошла ошибка.",
        "no_trending": "⚠️ Нет трендовых новостей, попробуйте позже.",
        "trending_header": "🔥 *В тренде*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Спортивные новости*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Новых спортивных новостей нет.",
        "no_sports_source": "⚠️ Нет спортивных источников для этого языка.",
        "no_mena": "⚠️ Новых политических новостей нет, попробуйте позже.",
        "no_source": "⚠️ Нет источников новостей для этого языка.",
        "weather_error": "⚠️ Не удаётся получить данные о погоде.",
        "forecast_error": "⚠️ Не удаётся получить почасовой прогноз.",
        "no_weekly": "⚠️ Нет новостей для еженедельной сводки.",
        "currency_error": "⚠️ Не удаётся получить курсы валют.",
        "search_prompt": "🔍 Введите слово для поиска:",
        "label_breaking": "🚨 Срочная новость",
        "label_news": "🚨 Новость",
        "label_mena": "📰 Ближний Восток",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Ваш город ещё не указан.",
        "city_not_found": "⚠️ Данные о погоде не найдены для: {city}",
        "weather_header": "{emoji} *Погода в {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Темп:* {temp}°C\n🤔 *Ощущается:* {feels}°C\n🔼 Макс: {temp_max}°C  |  🔽 Мин: {temp_min}°C\n\n☁️ *Состояние:* {desc}\n🌫 *Облачность:* {clouds}%\n👁 *Видимость:* {visibility_km} км\n\n💧 *Влажность:* {humidity}%\n🌀 *Давление:* {pressure} hPa\n☀️ *УФ-индекс:* {uvi}\n\n💨 *Ветер:* {wind_speed} м/с | {wind_dir}\n💨 *Порывы:* {wind_gust} м/с\n\n🌅 *Восход:* {sunrise}  |  🌇 *Закат:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Прогноз на 3 дня — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Прогноз на 7 дней — {city}*\n\n",
        "hourly_header": "🕐 *Погода каждые 3 часа — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "м/с",
        "uv_low": "Низкий",
        "uv_moderate": "Умеренный",
        "uv_high": "Высокий",
        "uv_very_high": "Очень высокий",
        "uv_extreme": "Экстремальный",
        "uv_na": "Н/Д",
        "wind_N": "⬆️ С",
        "wind_NE": "↗️ СВ",
        "wind_E": "➡️ В",
        "wind_SE": "↘️ ЮВ",
        "wind_S": "⬇️ Ю",
        "wind_SW": "↙️ ЮЗ",
        "wind_W": "⬅️ З",
        "wind_NW": "↖️ СЗ",
        "crypto_header": "💎 *Курсы криптовалют*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Данные от CoinGecko",
        "crypto_error": "⚠️ Не удаётся получить курсы криптовалют, попробуйте позже.",
        "prayer_header": "🕌 *Время молитв в {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Фаджр:   `{fajr}`\n☀️ Восход:  `{sunrise}`\n🌞 Зухр:    `{dhuhr}`\n🌇 Аср:     `{asr}`\n🌆 Магриб:  `{maghrib}`\n🌙 Иша:     `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Данные от Aladhan API",
        "prayer_no_city": "⚠️ Ваш город не указан. Перейдите в настройки.",
        "prayer_city_error": "⚠️ Не удаётся получить время молитв для: {city}",
        "prayer_error": "⚠️ Не удаётся получить время молитв, попробуйте позже.",
        "referral_header": "🎁 *Реферальная система*\n━━━━━━━━━━━━━━━\n\n🔗 *Ваша реферальная ссылка:*\n`{link}`\n\n👥 *Всего приглашено:* `{count}` чел.\n\n━━━━━━━━━━━━━━━\n📤 Поделитесь с друзьями и семьёй!\nКаждый, кто присоединится по вашей ссылке, будет засчитан. 🎯",
        "referral_share_btn": "📤 Поделиться ссылкой",
        "share_bot_header": "📢 *Поделитесь ботом и помогите нам расти!*\n\n🔗 *Ссылка на бот:*\n@{username}\n\n📌 Или по ссылке:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Поделитесь с друзьями, чтобы получать:\n📰 Последние мировые новости\n🌤 Погода в реальном времени\n💱 Курсы валют\n🕌 Время молитв\n💎 Курсы криптовалют",
        "share_bot_btn": "📤 Поделиться ботом",
        "open_bot_btn": "🔗 Открыть бот",
        "public_stats_header": "📊 *Статистика бота*\n━━━━━━━━━━━━━━━\n\n👥 Всего пользователей: *{total}*\n✅ Активных: *{active}*\n🆕 Присоединились сегодня: *{today}*\n⭐ Премиум-подписчиков: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Наиболее используемые языки:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Ваша личная статистика*\n━━━━━━━━━━━━━━━\n\n👤 Имя: *{name}*\n🌍 Язык: *{lang}*\n🏙 Город: *{city}*\n📅 Дата регистрации: *{join}*\n\n📰 Получено новостей: *{news}*\n🎁 Отправлено приглашений: *{refs}*\n🔑 Ключевых слов: *{kws}*\n⭐ Премиум: *{prem}*\n🔔 Уведомления: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Да",
        "my_stats_prem_no": "❌ Нет",
        "my_stats_notif_on": "🔔 Активны",
        "my_stats_notif_off": "🔕 Отключены",
        "my_stats_user": "Пользователь",
        "daily_summary_header": "📋 *Сводка новостей за {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Нет источников новостей для этого языка.",
        "daily_summary_no_news": "⚠️ Нет доступных новостей, попробуйте позже.",
        "top_referrers_header": "🏆 *Лучшие рефереры*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Пока нет рефералов — будьте первым! 🎯",
        "top_referrers_invite": "приглашение(й)",
        "dollar_header": "💵 *Доллар США к иракскому динару*\n\n🏪 Параллельный рынок:\n{rate}\n\n⏰ Последнее обновление: `{time}`\n📡 Источник: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Продажа",
        "dollar_buy": "Покупка",
        "dollar_official": "Курс: `{price}` IQD\n_(Официальный курс — может отличаться от рыночного)_",
        "dollar_error": "⚠️ Не удаётся получить курс доллара. Попробуйте позже.",
        "weekly_summary_header": "📰 *Еженедельный обзор — Топ {count} новостей*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Еженедельная сводка*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Собираем главные новости недели...",
        "weekly_summary_text_no_source": "⚠️ Нет доступных источников для этого языка.",
        "weekly_summary_text_no_news": "⚠️ Недостаточно новостей за эту неделю.",
        "currency_table_header": "📊 *Полная таблица курсов валют к USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Премиум-меню — Выберите:*",
        "premium_btn_7day": "🌤 Прогноз на 7 дней",
        "premium_btn_hourly": "🕐 Погода каждые 3 часа",
        "premium_btn_addcity": "🏙 Добавить город",
        "premium_btn_mycities": "📋 Мои сохранённые города",
        "premium_btn_interests": "📌 Мои интересы",
        "premium_btn_currency_alert": "💱 Оповещение о валюте",
        "premium_btn_currency_table": "📊 Таблица валют",
        "premium_btn_notif_time": "🕐 Время уведомлений",
        "premium_btn_weekly": "📰 Еженедельная сводка",
        "premium_btn_keywords": "🔑 Ключевые слова",
        "premium_subscribe_btn": "⭐ Запросить премиум-подписку",
        "broadcast_weather_msg": "🌤 Погода в {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Отслеживание активов*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Текущий список:*\n",
        "track_count": "\n({count}/20 символов)\n\n",
        "track_add_hint": "➕ *Добавить символ:* отправьте его название\n\n",
        "track_crypto_label": "💎 *Криптовалюты:*\n",
        "track_fiat_label": "💱 *Фиатные валюты:*\n",
        "track_stocks_label": "📈 *Акции:*\n",
        "track_commodities_label": "🏅 *Сырьё и индексы:*\n",
        "track_alert_hint": "🔔 *Вы получите мгновенные оповещения при изменении ±1% и ежечасный отчёт.*\n\n",
        "track_remove_hint": "❌ Удалить символ: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Просмотреть список: `/mytrack`",
        "track_empty": "📌 Список отслеживания пуст.\nНажмите *Отслеживать актив* для добавления символов.",
        "track_list_header": "📌 *Ваши отслеживаемые активы:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Оповещения о ценах*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 вырос",
        "track_fell": "📉 упал",
        "track_report_title": "📊 *Ежечасный отчёт — Ваши активы*\n",
        "track_unavailable": "недоступно",
        "track_remove_usage": "⚠️ Укажите символ. Пример: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* не найден в вашем списке.",
        "track_removed": "✅ *{symbol}* удалён из списка отслеживания.",
        "interest_save_btn": "💾 Сохранить",
        "interest_choose_msg": "📌 *Выберите интересы (можно несколько):*",
        "currency_rate_header": "💱 *Курсы валют к доллару 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Конвертация {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Неподдерживаемая валюта: {currency}",
        "currency_fetch_error": "⚠️ Не удаётся получить курсы валют.",
        "city_add_success": "✅ Город добавлен: *{city}*",
        "currency_alert_set": "✅ Вы будете оповещены, когда доллар достигнет `{rate}` вашей валюты.",
        "currency_alert_invalid": "❌ Введите число, например: 1600",
        "notif_time_set": "✅ Утренняя сводка будет отправляться в *{hour}:00* ежедневно.",
        "notif_time_invalid": "❌ Введите число от 0 до 23 (например: 8 для 8 утра)",
    },
    "فارسی 🇮🇷": {
        "no_news": "⚠️ اخبار جدیدی موجود نیست.",
        "no_results": "⚠️ نتیجهای برای جستجوی شما یافت نشد.",
        "search_error": "⚠️ خطایی در جستجو رخ داد.",
        "no_trending": "⚠️ اخبار پرطرفداری موجود نیست، بعداً دوباره امتحان کنید.",
        "trending_header": "🔥 *پرطرفدارترین*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *اخبار ورزشی*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ اخبار ورزشی جدیدی موجود نیست.",
        "no_sports_source": "⚠️ منبع ورزشی برای این زبان موجود نیست.",
        "no_mena": "⚠️ اخبار سیاسی جدیدی موجود نیست، بعداً دوباره امتحان کنید.",
        "no_source": "⚠️ منبع خبری برای این زبان موجود نیست.",
        "weather_error": "⚠️ دریافت اطلاعات آبوهوا ممکن نیست.",
        "forecast_error": "⚠️ دریافت پیشبینی ساعتی ممکن نیست.",
        "no_weekly": "⚠️ اخباری برای خلاصه هفتگی موجود نیست.",
        "currency_error": "⚠️ دریافت نرخ ارز ممکن نیست.",
        "search_prompt": "🔍 کلمه جستجو را بنویسید:",
        "label_breaking": "🚨 خبر فوری",
        "label_news": "🚨 خبر",
        "label_mena": "📰 اخبار سیاسی خاورمیانه",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ شهر شما هنوز تنظیم نشده.",
        "city_not_found": "⚠️ اطلاعات آبوهوا برای شهر {city} یافت نشد.",
        "weather_header": "{emoji} *آبوهوا در {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *دما:* {temp}°C\n🤔 *احساس میشود:* {feels}°C\n🔼 حداکثر: {temp_max}°C  |  🔽 حداقل: {temp_min}°C\n\n☁️ *وضعیت:* {desc}\n🌫 *ابرناکی:* {clouds}%\n👁 *دید:* {visibility_km} کم\n\n💧 *رطوبت:* {humidity}%\n🌀 *فشار:* {pressure} hPa\n☀️ *شاخص UV:* {uvi}\n\n💨 *باد:* {wind_speed} م/ث | {wind_dir}\n💨 *وزش:* {wind_gust} م/ث\n\n🌅 *طلوع:* {sunrise}  |  🌇 *غروب:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *پیشبینی ۳ روزه — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *پیشبینی ۷ روزه — {city}*\n\n",
        "hourly_header": "🕐 *آبوهوا هر ۳ ساعت — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "م/ث",
        "uv_low": "کم",
        "uv_moderate": "متوسط",
        "uv_high": "زیاد",
        "uv_very_high": "خیلی زیاد",
        "uv_extreme": "بسیار خطرناک",
        "uv_na": "ناموجود",
        "wind_N": "⬆️ شمال",
        "wind_NE": "↗️ شمالشرق",
        "wind_E": "➡️ شرق",
        "wind_SE": "↘️ جنوبشرق",
        "wind_S": "⬇️ جنوب",
        "wind_SW": "↙️ جنوبغرب",
        "wind_W": "⬅️ غرب",
        "wind_NW": "↖️ شمالغرب",
        "crypto_header": "💎 *قیمت ارزهای دیجیتال*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 دادهها از CoinGecko",
        "crypto_error": "⚠️ دریافت قیمت ارزهای دیجیتال ممکن نیست، بعداً امتحان کنید.",
        "prayer_header": "🕌 *اوقات نماز در {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 صبح:    `{fajr}`\n☀️ طلوع:   `{sunrise}`\n🌞 ظهر:    `{dhuhr}`\n🌇 عصر:    `{asr}`\n🌆 مغرب:   `{maghrib}`\n🌙 عشاء:   `{isha}`\n━━━━━━━━━━━━━━━\n🔄 دادهها از Aladhan API",
        "prayer_no_city": "⚠️ شهر شما تنظیم نشده. به تنظیمات بروید.",
        "prayer_city_error": "⚠️ دریافت اوقات نماز برای {city} ممکن نیست.",
        "prayer_error": "⚠️ دریافت اوقات نماز ممکن نیست، بعداً امتحان کنید.",
        "referral_header": "🎁 *سیستم دعوت*\n━━━━━━━━━━━━━━━\n\n🔗 *لینک دعوت شما:*\n`{link}`\n\n👥 *جمع دعوتشدگان:* `{count}` نفر\n\n━━━━━━━━━━━━━━━\n📤 با دوستان و خانواده به اشتراک بگذارید!\nهر کسی که از لینک شما بپیوندد حساب میشود. 🎯",
        "referral_share_btn": "📤 اشتراکگذاری لینک",
        "share_bot_header": "📢 *ربات را به اشتراک بگذارید و کمک کنید رشد کند!*\n\n🔗 *لینک ربات:*\n@{username}\n\n📌 یا از طریق لینک:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 با دوستان به اشتراک بگذارید:",
        "share_bot_btn": "📤 اشتراکگذاری ربات",
        "open_bot_btn": "🔗 باز کردن ربات",
        "public_stats_header": "📊 *آمار ربات*\n━━━━━━━━━━━━━━━\n\n👥 کل کاربران: *{total}*\n✅ کاربران فعال: *{active}*\n🆕 امروز پیوستند: *{today}*\n⭐ اشتراک ویژه: *{premium}*\n\n",
        "public_stats_langs": "🌍 *پرکاربردترین زبانها:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *آمار شخصی شما*\n━━━━━━━━━━━━━━━\n\n👤 نام: *{name}*\n🌍 زبان: *{lang}*\n🏙 شهر: *{city}*\n📅 تاریخ عضویت: *{join}*\n\n📰 اخبار دریافتی: *{news}*\n🎁 دعوتهای ارسالی: *{refs}*\n🔑 کلمات کلیدی: *{kws}*\n⭐ اشتراک ویژه: *{prem}*\n🔔 اعلانها: *{notif}*\n",
        "my_stats_prem_yes": "⭐ بله",
        "my_stats_prem_no": "❌ خیر",
        "my_stats_notif_on": "🔔 فعال",
        "my_stats_notif_off": "🔕 غیرفعال",
        "my_stats_user": "کاربر",
        "daily_summary_header": "📋 *خلاصه اخبار امروز — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ منبع خبری برای این زبان موجود نیست.",
        "daily_summary_no_news": "⚠️ اخبار موجود نیست، بعداً امتحان کنید.",
        "top_referrers_header": "🏆 *برترین دعوتکنندگان*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 هنوز دعوتی نیست — اولین باشید! 🎯",
        "top_referrers_invite": "دعوت",
        "dollar_header": "💵 *دلار آمریکا در برابر دینار عراق*\n\n🏪 بازار موازی:\n{rate}\n\n⏰ آخرین بهروزرسانی: `{time}`\n📡 منبع: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "فروش",
        "dollar_buy": "خرید",
        "dollar_official": "نرخ: `{price}` IQD\n_(نرخ رسمی — ممکن است با بازار متفاوت باشد)_",
        "dollar_error": "⚠️ دریافت نرخ دلار ممکن نیست. بعداً امتحان کنید.",
        "weekly_summary_header": "📰 *خلاصه هفتگی — برترین {count} خبر*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *خلاصه اخبار هفته*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ در حال جمعآوری اخبار برتر هفته...",
        "weekly_summary_text_no_source": "⚠️ منبع خبری برای این زبان موجود نیست.",
        "weekly_summary_text_no_news": "⚠️ اخبار کافی این هفته وجود ندارد.",
        "currency_table_header": "📊 *جدول کامل نرخ ارز در برابر دلار 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *منوی ویژه — انتخاب کنید:*",
        "premium_btn_7day": "🌤 پیشبینی ۷ روزه",
        "premium_btn_hourly": "🕐 آبوهوا هر ۳ ساعت",
        "premium_btn_addcity": "🏙 افزودن شهر",
        "premium_btn_mycities": "📋 شهرهای ذخیرهشده",
        "premium_btn_interests": "📌 علاقهمندیهای من",
        "premium_btn_currency_alert": "💱 هشدار ارز",
        "premium_btn_currency_table": "📊 جدول ارز",
        "premium_btn_notif_time": "🕐 زمان اعلان",
        "premium_btn_weekly": "📰 خلاصه هفتگی",
        "premium_btn_keywords": "🔑 کلمات کلیدی",
        "premium_subscribe_btn": "⭐ درخواست اشتراک ویژه",
        "broadcast_weather_msg": "🌤 آبوهوا در {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *ردیابی ارزها، سهام و کالاها*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *لیست فعلی شما:*\n",
        "track_count": "\n({count}/20 نماد)\n\n",
        "track_add_hint": "➕ *افزودن نماد:* نام آن را ارسال کنید\n\n",
        "track_crypto_label": "💎 *ارزهای دیجیتال:*\n",
        "track_fiat_label": "💱 *ارزهای فیات:*\n",
        "track_stocks_label": "📈 *سهام:*\n",
        "track_commodities_label": "🏅 *کالا و شاخصها:*\n",
        "track_alert_hint": "🔔 *هنگام تغییر ±۱٪ هشدار فوری دریافت میکنید و گزارش ساعتی نیز ارسال میشود.*\n\n",
        "track_remove_hint": "❌ حذف نماد: `/removetrack AAPL`\n",
        "track_list_hint": "📋 مشاهده لیست: `/mytrack`",
        "track_empty": "📌 لیست ردیابی خالی است.\nروی *ردیابی دارایی* بزنید تا نماد اضافه کنید.",
        "track_list_header": "📌 *داراییهای ردیابیشده شما:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *هشدارهای قیمت*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 افزایش یافت",
        "track_fell": "📉 کاهش یافت",
        "track_report_title": "📊 *گزارش ساعتی — داراییهای شما*\n",
        "track_unavailable": "ناموجود",
        "track_remove_usage": "⚠️ نماد را بعد از دستور بفرستید. مثال: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* در لیست شما یافت نشد.",
        "track_removed": "✅ *{symbol}* از لیست ردیابی حذف شد.",
        "interest_save_btn": "💾 ذخیره",
        "interest_choose_msg": "📌 *علاقهمندیهای خود را انتخاب کنید (چندتایی):*",
        "currency_rate_header": "💱 *نرخ ارز در برابر دلار 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *تبدیل {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ ارز پشتیبانینشده: {currency}",
        "currency_fetch_error": "⚠️ دریافت نرخ ارز ممکن نیست.",
        "city_add_success": "✅ شهر اضافه شد: *{city}*",
        "currency_alert_set": "✅ وقتی دلار به `{rate}` ارز محلی شما برسد هشدار میگیرید.",
        "currency_alert_invalid": "❌ یک عدد ارسال کنید، مثلاً: 1600",
        "notif_time_set": "✅ خلاصه صبحگاهی روزانه در ساعت *{hour}:00* ارسال میشود.",
        "notif_time_invalid": "❌ عددی بین ۰ تا ۲۳ وارد کنید (مثال: ۸ برای ساعت ۸ صبح)",
    },
    "हिन्दी 🇮🇳": {
        "no_news": "⚠️ अभी कोई नई खबर नहीं है।",
        "no_results": "⚠️ आपकी खोज का कोई परिणाम नहीं मिला।",
        "search_error": "⚠️ खोज के दौरान त्रुटि हुई।",
        "no_trending": "⚠️ अभी कोई ट्रेंडिंग खबर नहीं, बाद में प्रयास करें।",
        "trending_header": "🔥 *ट्रेंडिंग खबरें*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *खेल समाचार*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ अभी कोई नई खेल खबर नहीं।",
        "no_sports_source": "⚠️ इस भाषा के लिए कोई खेल स्रोत नहीं।",
        "no_mena": "⚠️ अभी कोई नई राजनीतिक खबर नहीं, बाद में प्रयास करें।",
        "no_source": "⚠️ इस भाषा के लिए कोई समाचार स्रोत नहीं।",
        "weather_error": "⚠️ मौसम डेटा प्राप्त नहीं हो सका।",
        "forecast_error": "⚠️ घंटे की भविष्यवाणी प्राप्त नहीं हो सकी।",
        "no_weekly": "⚠️ साप्ताहिक सारांश के लिए कोई समाचार नहीं।",
        "currency_error": "⚠️ मुद्रा दरें अभी प्राप्त नहीं हो सकीं।",
        "search_prompt": "🔍 खोज शब्द टाइप करें:",
        "label_breaking": "🚨 ब्रेकिंग न्यूज़",
        "label_news": "🚨 खबर",
        "label_mena": "📰 मध्य पूर्व राजनीतिक समाचार",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ आपका शहर अभी तक सेट नहीं है।",
        "city_not_found": "⚠️ {city} के लिए मौसम डेटा नहीं मिला।",
        "weather_header": "{emoji} *{city} में मौसम*\n━━━━━━━━━━━━━━━\n\n🌡 *तापमान:* {temp}°C\n🤔 *महसूस होता है:* {feels}°C\n🔼 अधिकतम: {temp_max}°C  |  🔽 न्यूनतम: {temp_min}°C\n\n☁️ *स्थिति:* {desc}\n🌫 *बादल:* {clouds}%\n👁 *दृश्यता:* {visibility_km} किमी\n\n💧 *नमी:* {humidity}%\n🌀 *दबाव:* {pressure} hPa\n☀️ *UV सूचकांक:* {uvi}\n\n💨 *हवा:* {wind_speed} मी/से | {wind_dir}\n💨 *झोंके:* {wind_gust} मी/से\n\n🌅 *सूर्योदय:* {sunrise}  |  🌇 *सूर्यास्त:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3-दिन का मौसम पूर्वानुमान — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7-दिन का मौसम पूर्वानुमान — {city}*\n\n",
        "hourly_header": "🕐 *हर 3 घंटे का मौसम — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "मी/से",
        "uv_low": "कम",
        "uv_moderate": "मध्यम",
        "uv_high": "उच्च",
        "uv_very_high": "बहुत उच्च",
        "uv_extreme": "अत्यधिक",
        "uv_na": "उपलब्ध नहीं",
        "wind_N": "⬆️ उत्तर",
        "wind_NE": "↗️ उत्तर-पूर्व",
        "wind_E": "➡️ पूर्व",
        "wind_SE": "↘️ दक्षिण-पूर्व",
        "wind_S": "⬇️ दक्षिण",
        "wind_SW": "↙️ दक्षिण-पश्चिम",
        "wind_W": "⬅️ पश्चिम",
        "wind_NW": "↖️ उत्तर-पश्चिम",
        "crypto_header": "💎 *क्रिप्टो मूल्य*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 CoinGecko से डेटा",
        "crypto_error": "⚠️ अभी क्रिप्टो मूल्य प्राप्त नहीं हो सका, बाद में प्रयास करें।",
        "prayer_header": "🕌 *{city} में नमाज़ के समय*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 फज्र:    `{fajr}`\n☀️ उदय:    `{sunrise}`\n🌞 जुहर:   `{dhuhr}`\n🌇 अस्र:    `{asr}`\n🌆 मगरिब:  `{maghrib}`\n🌙 ईशा:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Aladhan API से डेटा",
        "prayer_no_city": "⚠️ आपका शहर सेट नहीं है। सेटिंग्स में जाएं।",
        "prayer_city_error": "⚠️ {city} के लिए नमाज़ के समय प्राप्त नहीं हो सके।",
        "prayer_error": "⚠️ नमाज़ के समय अभी प्राप्त नहीं हो सके, बाद में प्रयास करें।",
        "referral_header": "🎁 *रेफरल सिस्टम*\n━━━━━━━━━━━━━━━\n\n🔗 *आपका रेफरल लिंक:*\n`{link}`\n\n👥 *कुल आमंत्रित:* `{count}` लोग\n\n━━━━━━━━━━━━━━━\n📤 दोस्तों और परिवार के साथ साझा करें!\nआपके लिंक से जुड़ने वाला हर व्यक्ति गिना जाएगा। 🎯",
        "referral_share_btn": "📤 लिंक साझा करें",
        "share_bot_header": "📢 *बॉट साझा करें और हमें बढ़ने में मदद करें!*\n\n🔗 *बॉट लिंक:*\n@{username}\n\n📌 या लिंक से:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 दोस्तों के साथ साझा करें:",
        "share_bot_btn": "📤 बॉट साझा करें",
        "open_bot_btn": "🔗 बॉट खोलें",
        "public_stats_header": "📊 *बॉट सांख्यिकी*\n━━━━━━━━━━━━━━━\n\n👥 कुल उपयोगकर्ता: *{total}*\n✅ सक्रिय उपयोगकर्ता: *{active}*\n🆕 आज जुड़े: *{today}*\n⭐ प्रीमियम सदस्य: *{premium}*\n\n",
        "public_stats_langs": "🌍 *सबसे अधिक उपयोग की जाने वाली भाषाएं:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *आपकी व्यक्तिगत सांख्यिकी*\n━━━━━━━━━━━━━━━\n\n👤 नाम: *{name}*\n🌍 भाषा: *{lang}*\n🏙 शहर: *{city}*\n📅 शामिल होने की तारीख: *{join}*\n\n📰 प्राप्त समाचार: *{news}*\n🎁 भेजे गए रेफरल: *{refs}*\n🔑 कीवर्ड: *{kws}*\n⭐ प्रीमियम: *{prem}*\n🔔 सूचनाएं: *{notif}*\n",
        "my_stats_prem_yes": "⭐ हाँ",
        "my_stats_prem_no": "❌ नहीं",
        "my_stats_notif_on": "🔔 सक्रिय",
        "my_stats_notif_off": "🔕 बंद",
        "my_stats_user": "उपयोगकर्ता",
        "daily_summary_header": "📋 *आज के समाचार का सारांश — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ इस भाषा के लिए कोई समाचार स्रोत नहीं।",
        "daily_summary_no_news": "⚠️ अभी कोई समाचार उपलब्ध नहीं, बाद में प्रयास करें।",
        "top_referrers_header": "🏆 *शीर्ष रेफरर्स*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 अभी कोई रेफरल नहीं — पहले बनें! 🎯",
        "top_referrers_invite": "आमंत्रण",
        "dollar_header": "💵 *USD बनाम इराकी दीनार*\n\n🏪 समानांतर बाज़ार:\n{rate}\n\n⏰ अंतिम अपडेट: `{time}`\n📡 स्रोत: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "बिक्री",
        "dollar_buy": "खरीद",
        "dollar_official": "दर: `{price}` IQD\n_(आधिकारिक दर — बाज़ार से भिन्न हो सकती है)_",
        "dollar_error": "⚠️ अभी डॉलर दर प्राप्त नहीं हो सकी। बाद में प्रयास करें।",
        "weekly_summary_header": "📰 *साप्ताहिक सारांश — शीर्ष {count} खबरें*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *साप्ताहिक समाचार सारांश*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ इस सप्ताह की शीर्ष खबरें एकत्र की जा रही हैं...",
        "weekly_summary_text_no_source": "⚠️ इस भाषा के लिए कोई समाचार स्रोत नहीं।",
        "weekly_summary_text_no_news": "⚠️ इस सप्ताह पर्याप्त खबरें नहीं।",
        "currency_table_header": "📊 *USD के मुकाबले पूर्ण विनिमय दर तालिका 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *प्रीमियम मेनू — चुनें:*",
        "premium_btn_7day": "🌤 7-दिन का पूर्वानुमान",
        "premium_btn_hourly": "🕐 हर 3 घंटे का मौसम",
        "premium_btn_addcity": "🏙 शहर जोड़ें",
        "premium_btn_mycities": "📋 मेरे सहेजे गए शहर",
        "premium_btn_interests": "📌 मेरी रुचियां",
        "premium_btn_currency_alert": "💱 मुद्रा अलर्ट",
        "premium_btn_currency_table": "📊 मुद्रा तालिका",
        "premium_btn_notif_time": "🕐 सूचना समय",
        "premium_btn_weekly": "📰 साप्ताहिक सारांश",
        "premium_btn_keywords": "🔑 कीवर्ड",
        "premium_subscribe_btn": "⭐ प्रीमियम सदस्यता का अनुरोध करें",
        "broadcast_weather_msg": "🌤 {city} में मौसम: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *मुद्राओं, शेयरों और वस्तुओं की निगरानी*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *आपकी वर्तमान सूची:*\n",
        "track_count": "\n({count}/20 प्रतीक)\n\n",
        "track_add_hint": "➕ *प्रतीक जोड़ें:* सीधे नाम भेजें\n\n",
        "track_crypto_label": "💎 *क्रिप्टोकरेंसी:*\n",
        "track_fiat_label": "💱 *फिएट मुद्राएं:*\n",
        "track_stocks_label": "📈 *शेयर:*\n",
        "track_commodities_label": "🏅 *वस्तु और सूचकांक:*\n",
        "track_alert_hint": "🔔 *±1% परिवर्तन पर तुरंत अलर्ट और प्रति घंटे रिपोर्ट मिलेगी।*\n\n",
        "track_remove_hint": "❌ प्रतीक हटाएं: `/removetrack AAPL`\n",
        "track_list_hint": "📋 सूची देखें: `/mytrack`",
        "track_empty": "📌 ट्रैकिंग सूची खाली है।\n*संपत्ति ट्रैक करें* बटन दबाएं।",
        "track_list_header": "📌 *आपकी ट्रैक की गई संपत्तियां:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *मूल्य अलर्ट*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 बढ़ा",
        "track_fell": "📉 गिरा",
        "track_report_title": "📊 *प्रति घंटे रिपोर्ट — आपकी संपत्तियां*\n",
        "track_unavailable": "अनुपलब्ध",
        "track_remove_usage": "⚠️ कमांड के बाद प्रतीक भेजें। उदाहरण: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* आपकी सूची में नहीं है।",
        "track_removed": "✅ *{symbol}* ट्रैकिंग सूची से हटा दिया।",
        "interest_save_btn": "💾 सहेजें",
        "interest_choose_msg": "📌 *अपनी रुचियां चुनें (एक से अधिक):*",
        "currency_rate_header": "💱 *USD के मुकाबले विनिमय दरें 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *{amount} {currency} का रूपांतरण*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ असमर्थित मुद्रा: {currency}",
        "currency_fetch_error": "⚠️ विनिमय दरें प्राप्त नहीं हो सकीं।",
        "city_add_success": "✅ शहर जोड़ा गया: *{city}*",
        "currency_alert_set": "✅ जब डॉलर आपकी स्थानीय मुद्रा के `{rate}` पर पहुंचेगा तो सूचित किया जाएगा।",
        "currency_alert_invalid": "❌ एक संख्या भेजें, जैसे: 1600",
        "notif_time_set": "✅ सुबह की सारांश रोज *{hour}:00* बजे भेजी जाएगी।",
        "notif_time_invalid": "❌ 0 से 23 के बीच संख्या दर्ज करें (उदाहरण: 8 सुबह 8 बजे के लिए)",
    },
    "Português 🇧🇷": {
        "no_news": "⚠️ Nenhuma notícia nova agora.",
        "no_results": "⚠️ Nenhum resultado encontrado para sua pesquisa.",
        "search_error": "⚠️ Ocorreu um erro durante a pesquisa.",
        "no_trending": "⚠️ Sem notícias em alta agora, tente mais tarde.",
        "trending_header": "🔥 *Em Alta*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Notícias Esportivas*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Sem novas notícias esportivas agora.",
        "no_sports_source": "⚠️ Nenhuma fonte esportiva para este idioma.",
        "no_mena": "⚠️ Sem notícias políticas novas, tente mais tarde.",
        "no_source": "⚠️ Nenhuma fonte de notícias para este idioma.",
        "weather_error": "⚠️ Não foi possível obter dados meteorológicos.",
        "forecast_error": "⚠️ Não foi possível obter previsão por hora.",
        "no_weekly": "⚠️ Sem notícias para resumo semanal.",
        "currency_error": "⚠️ Não foi possível obter taxas de câmbio.",
        "search_prompt": "🔍 Digite a palavra de pesquisa:",
        "label_breaking": "🚨 Urgente",
        "label_news": "🚨 Notícia",
        "label_mena": "📰 Notícias Políticas do Médio Oriente",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Sua cidade ainda não foi definida.",
        "city_not_found": "⚠️ Dados meteorológicos não encontrados para: {city}",
        "weather_header": "{emoji} *Tempo em {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Sensação:* {feels}°C\n🔼 Máx: {temp_max}°C  |  🔽 Mín: {temp_min}°C\n\n☁️ *Condição:* {desc}\n🌫 *Nuvens:* {clouds}%\n👁 *Visibilidade:* {visibility_km} km\n\n💧 *Umidade:* {humidity}%\n🌀 *Pressão:* {pressure} hPa\n☀️ *Índice UV:* {uvi}\n\n💨 *Vento:* {wind_speed} m/s | {wind_dir}\n💨 *Rajadas:* {wind_gust} m/s\n\n🌅 *Nascer:* {sunrise}  |  🌇 *Pôr do sol:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Previsão de 3 dias — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Previsão de 7 dias — {city}*\n\n",
        "hourly_header": "🕐 *Tempo a cada 3 horas — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Baixo",
        "uv_moderate": "Moderado",
        "uv_high": "Alto",
        "uv_very_high": "Muito alto",
        "uv_extreme": "Extremo",
        "uv_na": "N/D",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ L",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SO",
        "wind_W": "⬅️ O",
        "wind_NW": "↖️ NO",
        "crypto_header": "💎 *Preços de Criptomoedas*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Dados do CoinGecko",
        "crypto_error": "⚠️ Não foi possível obter preços de cripto agora, tente mais tarde.",
        "prayer_header": "🕌 *Horários de Oração em {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Nascer:  `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Dados da Aladhan API",
        "prayer_no_city": "⚠️ Sua cidade não está definida. Vá às Configurações.",
        "prayer_city_error": "⚠️ Não foi possível obter horários de oração para: {city}",
        "prayer_error": "⚠️ Não foi possível obter horários de oração, tente mais tarde.",
        "referral_header": "🎁 *Sistema de Indicação*\n━━━━━━━━━━━━━━━\n\n🔗 *Seu link de indicação:*\n`{link}`\n\n👥 *Total indicados:* `{count}` pessoas\n\n━━━━━━━━━━━━━━━\n📤 Compartilhe com amigos e família!\nCada pessoa que entrar pelo seu link conta. 🎯",
        "referral_share_btn": "📤 Compartilhar Link",
        "share_bot_header": "📢 *Compartilhe o bot e ajude-nos a crescer!*\n\n🔗 *Link do bot:*\n@{username}\n\n📌 Ou via link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Compartilhe com amigos para receber:\n📰 Últimas notícias\n🌤 Tempo ao vivo\n💱 Taxas de câmbio\n🕌 Horários de oração\n💎 Preços de cripto",
        "share_bot_btn": "📤 Compartilhar Bot",
        "open_bot_btn": "🔗 Abrir Bot",
        "public_stats_header": "📊 *Estatísticas do Bot*\n━━━━━━━━━━━━━━━\n\n👥 Total de usuários: *{total}*\n✅ Usuários ativos: *{active}*\n🆕 Entraram hoje: *{today}*\n⭐ Assinantes premium: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Idiomas mais usados:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Suas Estatísticas Pessoais*\n━━━━━━━━━━━━━━━\n\n👤 Nome: *{name}*\n🌍 Idioma: *{lang}*\n🏙 Cidade: *{city}*\n📅 Data de entrada: *{join}*\n\n📰 Notícias recebidas: *{news}*\n🎁 Indicações enviadas: *{refs}*\n🔑 Palavras-chave: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notificações: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Sim",
        "my_stats_prem_no": "❌ Não",
        "my_stats_notif_on": "🔔 Ativo",
        "my_stats_notif_off": "🔕 Pausado",
        "my_stats_user": "Usuário",
        "daily_summary_header": "📋 *Resumo de Notícias de Hoje — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Nenhuma fonte de notícias para este idioma.",
        "daily_summary_no_news": "⚠️ Nenhuma notícia disponível agora, tente mais tarde.",
        "top_referrers_header": "🏆 *Melhores Indicadores*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Sem indicações ainda — seja o primeiro! 🎯",
        "top_referrers_invite": "indicação(ões)",
        "dollar_header": "💵 *USD vs Dinar Iraquiano*\n\n🏪 Mercado paralelo:\n{rate}\n\n⏰ Última atualização: `{time}`\n📡 Fonte: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Venda",
        "dollar_buy": "Compra",
        "dollar_official": "Taxa: `{price}` IQD\n_(Taxa oficial — pode diferir do mercado)_",
        "dollar_error": "⚠️ Não foi possível obter a taxa do dólar. Tente mais tarde.",
        "weekly_summary_header": "📰 *Resumo Semanal — Top {count} notícias*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Resumo de Notícias da Semana*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Coletando as principais notícias da semana...",
        "weekly_summary_text_no_source": "⚠️ Nenhuma fonte de notícias para este idioma.",
        "weekly_summary_text_no_news": "⚠️ Notícias insuficientes esta semana.",
        "currency_table_header": "📊 *Tabela Completa de Câmbio vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Menu Premium — Escolha:*",
        "premium_btn_7day": "🌤 Previsão de 7 dias",
        "premium_btn_hourly": "🕐 Tempo a cada 3 horas",
        "premium_btn_addcity": "🏙 Adicionar Cidade",
        "premium_btn_mycities": "📋 Minhas Cidades Salvas",
        "premium_btn_interests": "📌 Meus Interesses",
        "premium_btn_currency_alert": "💱 Alerta de Câmbio",
        "premium_btn_currency_table": "📊 Tabela de Câmbio",
        "premium_btn_notif_time": "🕐 Horário de Notificação",
        "premium_btn_weekly": "📰 Resumo Semanal",
        "premium_btn_keywords": "🔑 Palavras-chave",
        "premium_subscribe_btn": "⭐ Solicitar Assinatura Premium",
        "broadcast_weather_msg": "🌤 Tempo em {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Rastreamento de Ativos*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Sua lista atual:*\n",
        "track_count": "\n({count}/20 símbolos)\n\n",
        "track_add_hint": "➕ *Adicionar símbolo:* envie o nome diretamente\n\n",
        "track_crypto_label": "💎 *Criptomoedas:*\n",
        "track_fiat_label": "💱 *Moedas fiduciárias:*\n",
        "track_stocks_label": "📈 *Ações:*\n",
        "track_commodities_label": "🏅 *Commodities e Índices:*\n",
        "track_alert_hint": "🔔 *Você receberá alertas imediatos em mudanças de ±1% e relatório por hora.*\n\n",
        "track_remove_hint": "❌ Remover símbolo: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Ver sua lista: `/mytrack`",
        "track_empty": "📌 Lista de rastreamento vazia.\nToque em *Rastrear ativo* para adicionar símbolos.",
        "track_list_header": "📌 *Seus ativos rastreados:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Alertas de preço*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 subiu",
        "track_fell": "📉 caiu",
        "track_report_title": "📊 *Relatório por hora — Seus ativos*\n",
        "track_unavailable": "indisponível",
        "track_remove_usage": "⚠️ Envie o símbolo após o comando. Exemplo: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* não está na sua lista.",
        "track_removed": "✅ *{symbol}* removido da lista de rastreamento.",
        "interest_save_btn": "💾 Salvar",
        "interest_choose_msg": "📌 *Escolha seus interesses (pode ser mais de um):*",
        "currency_rate_header": "💱 *Taxas de câmbio vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Conversão de {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Moeda não suportada: {currency}",
        "currency_fetch_error": "⚠️ Não foi possível obter taxas de câmbio.",
        "city_add_success": "✅ Cidade adicionada: *{city}*",
        "currency_alert_set": "✅ Você será alertado quando o dólar atingir `{rate}` da sua moeda local.",
        "currency_alert_invalid": "❌ Envie um número, por exemplo: 1600",
        "notif_time_set": "✅ O resumo matinal será enviado às *{hour}:00* todos os dias.",
        "notif_time_invalid": "❌ Insira um número entre 0 e 23 (exemplo: 8 para 8h)",
    },
    "Türkçe 🇹🇷": {
        "no_news": "⚠️ Şu an yeni haber yok.",
        "no_results": "⚠️ Aramanız için sonuç bulunamadı.",
        "search_error": "⚠️ Arama sırasında hata oluştu.",
        "no_trending": "⚠️ Şu an trend haber yok, daha sonra deneyin.",
        "trending_header": "🔥 *Trend Haberler*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Spor Haberleri*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Şu an yeni spor haberi yok.",
        "no_sports_source": "⚠️ Bu dil için spor kaynağı yok.",
        "no_mena": "⚠️ Şu an yeni siyasi haber yok, daha sonra deneyin.",
        "no_source": "⚠️ Bu dil için haber kaynağı yok.",
        "weather_error": "⚠️ Hava durumu verisi alınamıyor.",
        "forecast_error": "⚠️ Saatlik tahmin alınamıyor.",
        "no_weekly": "⚠️ Haftalık özet için haber yok.",
        "currency_error": "⚠️ Döviz kurları alınamıyor.",
        "search_prompt": "🔍 Arama kelimesini yazın:",
        "label_breaking": "🚨 Son Dakika",
        "label_news": "🚨 Haber",
        "label_mena": "📰 Orta Doğu Siyasi Haberleri",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Şehriniz henüz ayarlanmamış.",
        "city_not_found": "⚠️ {city} için hava durumu verisi bulunamadı.",
        "weather_header": "{emoji} *{city} Hava Durumu*\n━━━━━━━━━━━━━━━\n\n🌡 *Sıcaklık:* {temp}°C\n🤔 *Hissedilen:* {feels}°C\n🔼 Maks: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Durum:* {desc}\n🌫 *Bulut:* {clouds}%\n👁 *Görüş:* {visibility_km} km\n\n💧 *Nem:* {humidity}%\n🌀 *Basınç:* {pressure} hPa\n☀️ *UV İndeksi:* {uvi}\n\n💨 *Rüzgar:* {wind_speed} m/s | {wind_dir}\n💨 *Gusts:* {wind_gust} m/s\n\n🌅 *Gündoğumu:* {sunrise}  |  🌇 *Gün batımı:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3 Günlük Hava Tahmini — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7 Günlük Hava Tahmini — {city}*\n\n",
        "hourly_header": "🕐 *3 Saatlik Hava Durumu — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Düşük",
        "uv_moderate": "Orta",
        "uv_high": "Yüksek",
        "uv_very_high": "Çok Yüksek",
        "uv_extreme": "Aşırı",
        "uv_na": "Yok",
        "wind_N": "⬆️ K",
        "wind_NE": "↗️ KD",
        "wind_E": "➡️ D",
        "wind_SE": "↘️ GD",
        "wind_S": "⬇️ G",
        "wind_SW": "↙️ GB",
        "wind_W": "⬅️ B",
        "wind_NW": "↖️ KB",
        "crypto_header": "💎 *Kripto Para Fiyatları*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 CoinGecko'dan veri",
        "crypto_error": "⚠️ Şu an kripto fiyatları alınamıyor, daha sonra deneyin.",
        "prayer_header": "🕌 *{city} Namaz Vakitleri*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 İmsak:   `{fajr}`\n☀️ Güneş:   `{sunrise}`\n🌞 Öğle:    `{dhuhr}`\n🌇 İkindi:  `{asr}`\n🌆 Akşam:   `{maghrib}`\n🌙 Yatsı:   `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Aladhan API'den veri",
        "prayer_no_city": "⚠️ Şehriniz ayarlanmamış. Ayarlara gidin.",
        "prayer_city_error": "⚠️ {city} için namaz vakitleri alınamıyor.",
        "prayer_error": "⚠️ Namaz vakitleri şu an alınamıyor, daha sonra deneyin.",
        "referral_header": "🎁 *Davet Sistemi*\n━━━━━━━━━━━━━━━\n\n🔗 *Davet linkiniz:*\n`{link}`\n\n👥 *Toplam davet:* `{count}` kişi\n\n━━━━━━━━━━━━━━━\n📤 Arkadaş ve ailenizle paylaşın!\nLinkinizle katılan herkes sayılır. 🎯",
        "referral_share_btn": "📤 Linki Paylaş",
        "share_bot_header": "📢 *Botu paylaşın ve büyümemize yardımcı olun!*\n\n🔗 *Bot linki:*\n@{username}\n\n📌 Ya da link ile:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Arkadaşlarınızla paylaşarak şunlara ulaşın:\n📰 Son haberler\n🌤 Canlı hava\n💱 Döviz kurları\n🕌 Namaz vakitleri\n💎 Kripto fiyatları",
        "share_bot_btn": "📤 Botu Paylaş",
        "open_bot_btn": "🔗 Botu Aç",
        "public_stats_header": "📊 *Bot İstatistikleri*\n━━━━━━━━━━━━━━━\n\n👥 Toplam kullanıcı: *{total}*\n✅ Aktif kullanıcı: *{active}*\n🆕 Bugün katılan: *{today}*\n⭐ Premium üye: *{premium}*\n\n",
        "public_stats_langs": "🌍 *En çok kullanılan diller:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Kişisel İstatistikleriniz*\n━━━━━━━━━━━━━━━\n\n👤 Ad: *{name}*\n🌍 Dil: *{lang}*\n🏙 Şehir: *{city}*\n📅 Katılım tarihi: *{join}*\n\n📰 Alınan haber: *{news}*\n🎁 Davet gönderilen: *{refs}*\n🔑 Anahtar kelime: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Bildirimler: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Evet",
        "my_stats_prem_no": "❌ Hayır",
        "my_stats_notif_on": "🔔 Aktif",
        "my_stats_notif_off": "🔕 Durduruldu",
        "my_stats_user": "Kullanıcı",
        "daily_summary_header": "📋 *Bugünün Haber Özeti — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Bu dil için haber kaynağı yok.",
        "daily_summary_no_news": "⚠️ Şu an haber yok, daha sonra deneyin.",
        "top_referrers_header": "🏆 *En İyi Davetçiler*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Henüz davet yok — ilk siz olun! 🎯",
        "top_referrers_invite": "davet",
        "dollar_header": "💵 *USD - Irak Dinarı*\n\n🏪 Paralel piyasa:\n{rate}\n\n⏰ Son güncelleme: `{time}`\n📡 Kaynak: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Satış",
        "dollar_buy": "Alış",
        "dollar_official": "Kur: `{price}` IQD\n_(Resmi kur — piyasadan farklı olabilir)_",
        "dollar_error": "⚠️ Dolar kuru şu an alınamıyor. Daha sonra deneyin.",
        "weekly_summary_header": "📰 *Haftalık Özet — En iyi {count} haber*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Haftalık Haber Özeti*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Haftanın öne çıkan haberleri toplanıyor...",
        "weekly_summary_text_no_source": "⚠️ Bu dil için haber kaynağı yok.",
        "weekly_summary_text_no_news": "⚠️ Bu hafta yeterli haber yok.",
        "currency_table_header": "📊 *USD'ye Karşı Tam Döviz Tablosu 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Premium Menü — Seçin:*",
        "premium_btn_7day": "🌤 7 Günlük Tahmin",
        "premium_btn_hourly": "🕐 3 Saatlik Hava",
        "premium_btn_addcity": "🏙 Şehir Ekle",
        "premium_btn_mycities": "📋 Kayıtlı Şehirlerim",
        "premium_btn_interests": "📌 İlgi Alanlarım",
        "premium_btn_currency_alert": "💱 Döviz Uyarısı",
        "premium_btn_currency_table": "📊 Döviz Tablosu",
        "premium_btn_notif_time": "🕐 Bildirim Saati",
        "premium_btn_weekly": "📰 Haftalık Özet",
        "premium_btn_keywords": "🔑 Anahtar Kelimeler",
        "premium_subscribe_btn": "⭐ Premium Üyelik Talep Et",
        "broadcast_weather_msg": "🌤 {city} hava durumu: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Döviz, Hisse ve Emtia Takibi*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Mevcut listeniz:*\n",
        "track_count": "\n({count}/20 sembol)\n\n",
        "track_add_hint": "➕ *Sembol ekle:* adını doğrudan gönderin\n\n",
        "track_crypto_label": "💎 *Kripto Paralar:*\n",
        "track_fiat_label": "💱 *Fiat Para Birimleri:*\n",
        "track_stocks_label": "📈 *Hisse Senetleri:*\n",
        "track_commodities_label": "🏅 *Emtia ve Endeksler:*\n",
        "track_alert_hint": "🔔 *±%1 değişimde anlık uyarı ve saatlik rapor alırsınız.*\n\n",
        "track_remove_hint": "❌ Sembol sil: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Listenizi görün: `/mytrack`",
        "track_empty": "📌 Takip listesi boş.\n*Varlık takip et* butonuna basın.",
        "track_list_header": "📌 *Takip ettiğiniz varlıklar:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Fiyat Uyarıları*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 yükseldi",
        "track_fell": "📉 düştü",
        "track_report_title": "📊 *Saatlik Rapor — Varlıklarınız*\n",
        "track_unavailable": "mevcut değil",
        "track_remove_usage": "⚠️ Komuttan sonra sembolü gönderin. Örnek: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* listenizde yok.",
        "track_removed": "✅ *{symbol}* takip listesinden kaldırıldı.",
        "interest_save_btn": "💾 Kaydet",
        "interest_choose_msg": "📌 *İlgi alanlarınızı seçin (birden fazla olabilir):*",
        "currency_rate_header": "💱 *USD'ye Karşı Döviz Kurları 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *{amount} {currency} Dönüşümü*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Desteklenmeyen para birimi: {currency}",
        "currency_fetch_error": "⚠️ Döviz kurları alınamıyor.",
        "city_add_success": "✅ Şehir eklendi: *{city}*",
        "currency_alert_set": "✅ Dolar yerel paranızın `{rate}` değerine ulaştığında uyarılacaksınız.",
        "currency_alert_invalid": "❌ Bir sayı gönderin, örnek: 1600",
        "notif_time_set": "✅ Sabah özeti her gün *{hour}:00*'de gönderilecek.",
        "notif_time_invalid": "❌ 0 ile 23 arasında bir sayı girin (örnek: sabah 8 için 8)",
    },
    "اردو 🇵🇰": {
        "no_news": "⚠️ ابھی کوئی نئی خبر نہیں۔",
        "no_results": "⚠️ آپ کی تلاش کا کوئی نتیجہ نہیں ملا۔",
        "search_error": "⚠️ تلاش کے دوران خرابی ہوئی۔",
        "no_trending": "⚠️ ابھی کوئی ٹرینڈنگ خبر نہیں، بعد میں کوشش کریں۔",
        "trending_header": "🔥 *ٹرینڈنگ خبریں*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *کھیل کی خبریں*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ ابھی کوئی نئی کھیل کی خبر نہیں۔",
        "no_sports_source": "⚠️ اس زبان کے لیے کوئی کھیل ذریعہ نہیں۔",
        "no_mena": "⚠️ ابھی کوئی نئی سیاسی خبر نہیں، بعد میں کوشش کریں۔",
        "no_source": "⚠️ اس زبان کے لیے کوئی خبر ذریعہ نہیں۔",
        "weather_error": "⚠️ موسم کا ڈیٹا حاصل نہیں ہو سکا۔",
        "forecast_error": "⚠️ گھنٹہ وار پیشگوئی حاصل نہیں ہو سکی۔",
        "no_weekly": "⚠️ ہفتہ وار خلاصے کے لیے کوئی خبر نہیں۔",
        "currency_error": "⚠️ کرنسی ریٹ حاصل نہیں ہو سکے۔",
        "search_prompt": "🔍 تلاش کا لفظ لکھیں:",
        "label_breaking": "🚨 بریکنگ نیوز",
        "label_news": "🚨 خبر",
        "label_mena": "📰 مشرق وسطیٰ سیاسی خبریں",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ آپ کا شہر ابھی تک سیٹ نہیں ہوا۔",
        "city_not_found": "⚠️ {city} کے لیے موسم کا ڈیٹا نہیں ملا۔",
        "weather_header": "{emoji} *{city} میں موسم*\n━━━━━━━━━━━━━━━\n\n🌡 *درجہ حرارت:* {temp}°C\n🤔 *محسوس ہوتا ہے:* {feels}°C\n🔼 زیادہ: {temp_max}°C  |  🔽 کم: {temp_min}°C\n\n☁️ *حالت:* {desc}\n🌫 *بادل:* {clouds}%\n👁 *مرئیت:* {visibility_km} کمی\n\n💧 *نمی:* {humidity}%\n🌀 *دباؤ:* {pressure} hPa\n☀️ *UV انڈیکس:* {uvi}\n\n💨 *ہوا:* {wind_speed} م/س | {wind_dir}\n💨 *جھونکے:* {wind_gust} م/س\n\n🌅 *طلوع آفتاب:* {sunrise}  |  🌇 *غروب آفتاب:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3 روزہ موسم کی پیشگوئی — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7 روزہ موسم کی پیشگوئی — {city}*\n\n",
        "hourly_header": "🕐 *ہر 3 گھنٹے کا موسم — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "م/س",
        "uv_low": "کم",
        "uv_moderate": "معتدل",
        "uv_high": "زیادہ",
        "uv_very_high": "بہت زیادہ",
        "uv_extreme": "انتہائی خطرناک",
        "uv_na": "دستیاب نہیں",
        "wind_N": "⬆️ شمال",
        "wind_NE": "↗️ شمال مشرق",
        "wind_E": "➡️ مشرق",
        "wind_SE": "↘️ جنوب مشرق",
        "wind_S": "⬇️ جنوب",
        "wind_SW": "↙️ جنوب مغرب",
        "wind_W": "⬅️ مغرب",
        "wind_NW": "↖️ شمال مغرب",
        "crypto_header": "💎 *کرپٹو کرنسی کے نرخ*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 CoinGecko سے ڈیٹا",
        "crypto_error": "⚠️ ابھی کرپٹو کی قیمتیں حاصل نہیں ہو سکیں، بعد میں کوشش کریں۔",
        "prayer_header": "🕌 *{city} میں نماز کے اوقات*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 فجر:     `{fajr}`\n☀️ طلوع:    `{sunrise}`\n🌞 ظہر:     `{dhuhr}`\n🌇 عصر:     `{asr}`\n🌆 مغرب:    `{maghrib}`\n🌙 عشاء:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Aladhan API سے ڈیٹا",
        "prayer_no_city": "⚠️ آپ کا شہر سیٹ نہیں۔ ترتیبات میں جائیں۔",
        "prayer_city_error": "⚠️ {city} کے نماز اوقات حاصل نہیں ہو سکے۔",
        "prayer_error": "⚠️ نماز اوقات ابھی حاصل نہیں ہو سکے، بعد میں کوشش کریں۔",
        "referral_header": "🎁 *دعوت نظام*\n━━━━━━━━━━━━━━━\n\n🔗 *آپ کا دعوت لنک:*\n`{link}`\n\n👥 *کل مدعو:* `{count}` افراد\n\n━━━━━━━━━━━━━━━\n📤 دوستوں اور خاندان کے ساتھ شیئر کریں!\nآپ کے لنک سے شامل ہونے والا ہر شخص گنا جائے گا۔ 🎯",
        "referral_share_btn": "📤 لنک شیئر کریں",
        "share_bot_header": "📢 *بوٹ شیئر کریں اور ہماری ترقی میں مدد کریں!*\n\n🔗 *بوٹ لنک:*\n@{username}\n\n📌 یا لنک سے:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 دوستوں کے ساتھ شیئر کریں:",
        "share_bot_btn": "📤 بوٹ شیئر کریں",
        "open_bot_btn": "🔗 بوٹ کھولیں",
        "public_stats_header": "📊 *بوٹ کے اعداد و شمار*\n━━━━━━━━━━━━━━━\n\n👥 کل صارفین: *{total}*\n✅ فعال صارفین: *{active}*\n🆕 آج شامل ہوئے: *{today}*\n⭐ پریمیم ممبران: *{premium}*\n\n",
        "public_stats_langs": "🌍 *سب سے زیادہ استعمال ہونے والی زبانیں:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *آپ کے ذاتی اعداد و شمار*\n━━━━━━━━━━━━━━━\n\n👤 نام: *{name}*\n🌍 زبان: *{lang}*\n🏙 شہر: *{city}*\n📅 شمولیت کی تاریخ: *{join}*\n\n📰 موصولہ خبریں: *{news}*\n🎁 بھیجی گئی دعوتیں: *{refs}*\n🔑 کلیدی الفاظ: *{kws}*\n⭐ پریمیم: *{prem}*\n🔔 اطلاعات: *{notif}*\n",
        "my_stats_prem_yes": "⭐ ہاں",
        "my_stats_prem_no": "❌ نہیں",
        "my_stats_notif_on": "🔔 فعال",
        "my_stats_notif_off": "🔕 بند",
        "my_stats_user": "صارف",
        "daily_summary_header": "📋 *آج کی خبروں کا خلاصہ — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ اس زبان کے لیے کوئی خبر ذریعہ نہیں۔",
        "daily_summary_no_news": "⚠️ ابھی کوئی خبر دستیاب نہیں، بعد میں کوشش کریں۔",
        "top_referrers_header": "🏆 *بہترین دعوت دہندگان*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 ابھی کوئی دعوت نہیں — پہلے بنیں! 🎯",
        "top_referrers_invite": "دعوت",
        "dollar_header": "💵 *امریکی ڈالر بمقابلہ عراقی دینار*\n\n🏪 متوازی مارکیٹ:\n{rate}\n\n⏰ آخری اپ ڈیٹ: `{time}`\n📡 ذریعہ: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "فروخت",
        "dollar_buy": "خریداری",
        "dollar_official": "شرح: `{price}` IQD\n_(سرکاری شرح — بازار سے مختلف ہو سکتی ہے)_",
        "dollar_error": "⚠️ ابھی ڈالر کی شرح حاصل نہیں ہو سکی۔ بعد میں کوشش کریں۔",
        "weekly_summary_header": "📰 *ہفتہ وار خلاصہ — بہترین {count} خبریں*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *ہفتہ وار خبروں کا خلاصہ*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ اس ہفتے کی اہم خبریں جمع کی جا رہی ہیں...",
        "weekly_summary_text_no_source": "⚠️ اس زبان کے لیے کوئی خبر ذریعہ نہیں۔",
        "weekly_summary_text_no_news": "⚠️ اس ہفتے کافی خبریں نہیں۔",
        "currency_table_header": "📊 *USD کے مقابلے مکمل زر مبادلہ جدول 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *پریمیم مینو — انتخاب کریں:*",
        "premium_btn_7day": "🌤 7 روزہ پیشگوئی",
        "premium_btn_hourly": "🕐 ہر 3 گھنٹے کا موسم",
        "premium_btn_addcity": "🏙 شہر شامل کریں",
        "premium_btn_mycities": "📋 میرے محفوظ شہر",
        "premium_btn_interests": "📌 میری دلچسپیاں",
        "premium_btn_currency_alert": "💱 کرنسی الرٹ",
        "premium_btn_currency_table": "📊 کرنسی جدول",
        "premium_btn_notif_time": "🕐 اطلاع کا وقت",
        "premium_btn_weekly": "📰 ہفتہ وار خلاصہ",
        "premium_btn_keywords": "🔑 کلیدی الفاظ",
        "premium_subscribe_btn": "⭐ پریمیم سبسکرپشن کی درخواست کریں",
        "broadcast_weather_msg": "🌤 {city} میں موسم: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *کرنسیوں، حصص اور اجناس کی نگرانی*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *آپ کی موجودہ فہرست:*\n",
        "track_count": "\n({count}/20 علامات)\n\n",
        "track_add_hint": "➕ *علامت شامل کریں:* اس کا نام سیدھا بھیجیں\n\n",
        "track_crypto_label": "💎 *کرپٹو کرنسیاں:*\n",
        "track_fiat_label": "💱 *فیاٹ کرنسیاں:*\n",
        "track_stocks_label": "📈 *حصص:*\n",
        "track_commodities_label": "🏅 *اجناس اور اشاریہ جات:*\n",
        "track_alert_hint": "🔔 *±1٪ تبدیلی پر فوری الرٹ اور گھنٹہ وار رپورٹ ملے گی۔*\n\n",
        "track_remove_hint": "❌ علامت حذف کریں: `/removetrack AAPL`\n",
        "track_list_hint": "📋 اپنی فہرست دیکھیں: `/mytrack`",
        "track_empty": "📌 ٹریکنگ فہرست خالی ہے۔\n*اثاثہ ٹریک کریں* کا بٹن دبائیں۔",
        "track_list_header": "📌 *آپ کے ٹریک شدہ اثاثے:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *قیمتوں کے الرٹ*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 بڑھا",
        "track_fell": "📉 گرا",
        "track_report_title": "📊 *گھنٹہ وار رپورٹ — آپ کے اثاثے*\n",
        "track_unavailable": "دستیاب نہیں",
        "track_remove_usage": "⚠️ کمانڈ کے بعد علامت بھیجیں۔ مثال: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* آپ کی فہرست میں نہیں۔",
        "track_removed": "✅ *{symbol}* ٹریکنگ فہرست سے حذف ہو گیا۔",
        "interest_save_btn": "💾 محفوظ کریں",
        "interest_choose_msg": "📌 *اپنی دلچسپیاں چنیں (ایک سے زیادہ ہو سکتی ہیں):*",
        "currency_rate_header": "💱 *USD کے مقابلے زر مبادلہ 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *{amount} {currency} کی تبدیلی*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ غیر معاون کرنسی: {currency}",
        "currency_fetch_error": "⚠️ زر مبادلہ حاصل نہیں ہو سکے۔",
        "city_add_success": "✅ شہر شامل ہوا: *{city}*",
        "currency_alert_set": "✅ جب ڈالر آپ کی مقامی کرنسی کے `{rate}` تک پہنچے گا تو الرٹ ملے گا۔",
        "currency_alert_invalid": "❌ ایک نمبر بھیجیں، جیسے: 1600",
        "notif_time_set": "✅ صبح کا خلاصہ روزانہ *{hour}:00* بجے بھیجا جائے گا۔",
        "notif_time_invalid": "❌ 0 سے 23 کے درمیان نمبر درج کریں (مثال: 8 صبح 8 بجے کے لیے)",
    },
    "Deutsch 🇩🇪": {
        "no_news": "⚠️ Derzeit keine neuen Nachrichten.",
        "no_results": "⚠️ Keine Ergebnisse für Ihre Suche gefunden.",
        "search_error": "⚠️ Fehler bei der Suche.",
        "no_trending": "⚠️ Derzeit keine Trend-Nachrichten, versuchen Sie es später.",
        "trending_header": "🔥 *Trending*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Sportnachrichten*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Derzeit keine neuen Sportnachrichten.",
        "no_sports_source": "⚠️ Keine Sportquellen für diese Sprache.",
        "no_mena": "⚠️ Derzeit keine neuen politischen Nachrichten.",
        "no_source": "⚠️ Keine Nachrichtenquellen für diese Sprache.",
        "weather_error": "⚠️ Wetterdaten können nicht abgerufen werden.",
        "forecast_error": "⚠️ Stundenvorhersage kann nicht abgerufen werden.",
        "no_weekly": "⚠️ Keine Nachrichten für wöchentliche Zusammenfassung.",
        "currency_error": "⚠️ Wechselkurse können nicht abgerufen werden.",
        "search_prompt": "🔍 Suchbegriff eingeben:",
        "label_breaking": "🚨 Eilmeldung",
        "label_news": "🚨 Nachricht",
        "label_mena": "📰 Nahost-Politiknachrichten",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Ihre Stadt ist noch nicht festgelegt.",
        "city_not_found": "⚠️ Keine Wetterdaten für: {city}",
        "weather_header": "{emoji} *Wetter in {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Gefühlt:* {feels}°C\n🔼 Max: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Zustand:* {desc}\n🌫 *Wolken:* {clouds}%\n👁 *Sichtweite:* {visibility_km} km\n\n💧 *Luftfeuchte:* {humidity}%\n🌀 *Luftdruck:* {pressure} hPa\n☀️ *UV-Index:* {uvi}\n\n💨 *Wind:* {wind_speed} m/s | {wind_dir}\n💨 *Böen:* {wind_gust} m/s\n\n🌅 *Sonnenaufgang:* {sunrise}  |  🌇 *Sonnenuntergang:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *3-Tage-Wettervorhersage — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *7-Tage-Wettervorhersage — {city}*\n\n",
        "hourly_header": "🕐 *Wetter alle 3 Stunden — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Niedrig",
        "uv_moderate": "Mäßig",
        "uv_high": "Hoch",
        "uv_very_high": "Sehr hoch",
        "uv_extreme": "Extrem",
        "uv_na": "N/V",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NO",
        "wind_E": "➡️ O",
        "wind_SE": "↘️ SO",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SW",
        "wind_W": "⬅️ W",
        "wind_NW": "↖️ NW",
        "crypto_header": "💎 *Kryptopreise*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Daten von CoinGecko",
        "crypto_error": "⚠️ Kryptopreise können derzeit nicht abgerufen werden.",
        "prayer_header": "🕌 *Gebetszeiten in {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Aufgang: `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Daten von Aladhan API",
        "prayer_no_city": "⚠️ Ihre Stadt ist nicht festgelegt. Gehen Sie zu Einstellungen.",
        "prayer_city_error": "⚠️ Gebetszeiten für {city} können nicht abgerufen werden.",
        "prayer_error": "⚠️ Gebetszeiten derzeit nicht abrufbar, versuchen Sie es später.",
        "referral_header": "🎁 *Empfehlungssystem*\n━━━━━━━━━━━━━━━\n\n🔗 *Ihr Empfehlungslink:*\n`{link}`\n\n👥 *Insgesamt eingeladen:* `{count}` Personen\n\n━━━━━━━━━━━━━━━\n📤 Mit Freunden und Familie teilen!\nJeder, der über Ihren Link beitritt, wird gezählt. 🎯",
        "referral_share_btn": "📤 Link teilen",
        "share_bot_header": "📢 *Bot teilen und uns beim Wachsen helfen!*\n\n🔗 *Bot-Link:*\n@{username}\n\n📌 Oder per Link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Mit Freunden teilen für:\n📰 Aktuelle Nachrichten\n🌤 Live-Wetter\n💱 Wechselkurse\n🕌 Gebetszeiten\n💎 Kryptokurse",
        "share_bot_btn": "📤 Bot teilen",
        "open_bot_btn": "🔗 Bot öffnen",
        "public_stats_header": "📊 *Bot-Statistiken*\n━━━━━━━━━━━━━━━\n\n👥 Gesamte Nutzer: *{total}*\n✅ Aktive Nutzer: *{active}*\n🆕 Heute beigetreten: *{today}*\n⭐ Premium-Abonnenten: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Am häufigsten verwendete Sprachen:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Ihre persönlichen Statistiken*\n━━━━━━━━━━━━━━━\n\n👤 Name: *{name}*\n🌍 Sprache: *{lang}*\n🏙 Stadt: *{city}*\n📅 Beitrittsdatum: *{join}*\n\n📰 Erhaltene Nachrichten: *{news}*\n🎁 Gesendete Empfehlungen: *{refs}*\n🔑 Schlüsselwörter: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Benachrichtigungen: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Ja",
        "my_stats_prem_no": "❌ Nein",
        "my_stats_notif_on": "🔔 Aktiv",
        "my_stats_notif_off": "🔕 Pausiert",
        "my_stats_user": "Benutzer",
        "daily_summary_header": "📋 *Heutige Nachrichtenübersicht — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Keine Nachrichtenquellen für diese Sprache.",
        "daily_summary_no_news": "⚠️ Keine Nachrichten verfügbar, versuchen Sie es später.",
        "top_referrers_header": "🏆 *Top-Empfehlende*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Noch keine Empfehlungen — seien Sie der Erste! 🎯",
        "top_referrers_invite": "Einladung(en)",
        "dollar_header": "💵 *USD vs Irakischer Dinar*\n\n🏪 Parallelmarkt:\n{rate}\n\n⏰ Zuletzt aktualisiert: `{time}`\n📡 Quelle: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Verkauf",
        "dollar_buy": "Kauf",
        "dollar_official": "Kurs: `{price}` IQD\n_(Offizieller Kurs — kann vom Markt abweichen)_",
        "dollar_error": "⚠️ Dollarkurs derzeit nicht abrufbar. Versuchen Sie es später.",
        "weekly_summary_header": "📰 *Wochenrückblick — Top {count} Nachrichten*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Wöchentliche Nachrichtenübersicht*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Die wichtigsten Nachrichten der Woche werden gesammelt...",
        "weekly_summary_text_no_source": "⚠️ Keine Nachrichtenquellen für diese Sprache.",
        "weekly_summary_text_no_news": "⚠️ Nicht genug Nachrichten diese Woche.",
        "currency_table_header": "📊 *Vollständige Wechselkurstabelle vs. USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Premium-Menü — Wählen:*",
        "premium_btn_7day": "🌤 7-Tage-Vorhersage",
        "premium_btn_hourly": "🕐 Wetter alle 3 Std.",
        "premium_btn_addcity": "🏙 Stadt hinzufügen",
        "premium_btn_mycities": "📋 Meine gespeicherten Städte",
        "premium_btn_interests": "📌 Meine Interessen",
        "premium_btn_currency_alert": "💱 Währungsalarm",
        "premium_btn_currency_table": "📊 Währungstabelle",
        "premium_btn_notif_time": "🕐 Benachrichtigungszeit",
        "premium_btn_weekly": "📰 Wochenübersicht",
        "premium_btn_keywords": "🔑 Schlüsselwörter",
        "premium_subscribe_btn": "⭐ Premium-Abonnement anfragen",
        "broadcast_weather_msg": "🌤 Wetter in {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Währungen, Aktien und Rohstoffe verfolgen*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Ihre aktuelle Liste:*\n",
        "track_count": "\n({count}/20 Symbole)\n\n",
        "track_add_hint": "➕ *Symbol hinzufügen:* Namen direkt senden\n\n",
        "track_crypto_label": "💎 *Kryptowährungen:*\n",
        "track_fiat_label": "💱 *Fiat-Währungen:*\n",
        "track_stocks_label": "📈 *Aktien:*\n",
        "track_commodities_label": "🏅 *Rohstoffe und Indizes:*\n",
        "track_alert_hint": "🔔 *Bei ±1% Änderung erhalten Sie sofortige Benachrichtigungen und stündliche Berichte.*\n\n",
        "track_remove_hint": "❌ Symbol entfernen: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Liste anzeigen: `/mytrack`",
        "track_empty": "📌 Verfolgungsliste ist leer.\nDrücken Sie *Asset verfolgen*, um Symbole hinzuzufügen.",
        "track_list_header": "📌 *Ihre verfolgten Assets:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Preisalarme*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 gestiegen",
        "track_fell": "📉 gefallen",
        "track_report_title": "📊 *Stündlicher Bericht — Ihre Assets*\n",
        "track_unavailable": "nicht verfügbar",
        "track_remove_usage": "⚠️ Senden Sie das Symbol nach dem Befehl. Beispiel: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* ist nicht in Ihrer Liste.",
        "track_removed": "✅ *{symbol}* aus der Verfolgungsliste entfernt.",
        "interest_save_btn": "💾 Speichern",
        "interest_choose_msg": "📌 *Wählen Sie Ihre Interessen (mehrere möglich):*",
        "currency_rate_header": "💱 *Wechselkurse vs. USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Umrechnung von {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Nicht unterstützte Währung: {currency}",
        "currency_fetch_error": "⚠️ Wechselkurse können nicht abgerufen werden.",
        "city_add_success": "✅ Stadt hinzugefügt: *{city}*",
        "currency_alert_set": "✅ Sie werden benachrichtigt, wenn der Dollar `{rate}` Ihrer Lokalwährung erreicht.",
        "currency_alert_invalid": "❌ Senden Sie eine Zahl, z. B.: 1600",
        "notif_time_set": "✅ Die Morgenzusammenfassung wird täglich um *{hour}:00* Uhr gesendet.",
        "notif_time_invalid": "❌ Geben Sie eine Zahl zwischen 0 und 23 ein (Beispiel: 8 für 8 Uhr morgens)",
    },
    "Українська 🇺🇦": {
        "no_news": "⚠️ Зараз немає нових новин.",
        "no_results": "⚠️ За вашим запитом нічого не знайдено.",
        "search_error": "⚠️ Під час пошуку сталася помилка.",
        "no_trending": "⚠️ Немає трендових новин, спробуйте пізніше.",
        "trending_header": "🔥 *У тренді*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Спортивні новини*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Нових спортивних новин немає.",
        "no_sports_source": "⚠️ Немає спортивних джерел для цієї мови.",
        "no_mena": "⚠️ Нових політичних новин немає, спробуйте пізніше.",
        "no_source": "⚠️ Немає джерел новин для цієї мови.",
        "weather_error": "⚠️ Не вдається отримати дані про погоду.",
        "forecast_error": "⚠️ Не вдається отримати погодинний прогноз.",
        "no_weekly": "⚠️ Немає новин для тижневого підсумку.",
        "currency_error": "⚠️ Не вдається отримати курси валют.",
        "search_prompt": "🔍 Введіть слово для пошуку:",
        "label_breaking": "🚨 Термінова новина",
        "label_news": "🚨 Новина",
        "label_mena": "📰 Близький Схід",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Ваше місто ще не вказано.",
        "city_not_found": "⚠️ Дані про погоду не знайдено для: {city}",
        "weather_header": "{emoji} *Погода в {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Темп:* {temp}°C\n🤔 *Відчувається:* {feels}°C\n🔼 Макс: {temp_max}°C  |  🔽 Мін: {temp_min}°C\n\n☁️ *Стан:* {desc}\n🌫 *Хмарність:* {clouds}%\n👁 *Видимість:* {visibility_km} км\n\n💧 *Вологість:* {humidity}%\n🌀 *Тиск:* {pressure} hPa\n☀️ *УФ-індекс:* {uvi}\n\n💨 *Вітер:* {wind_speed} м/с | {wind_dir}\n💨 *Пориви:* {wind_gust} м/с\n\n🌅 *Схід:* {sunrise}  |  🌇 *Захід:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Прогноз на 3 дні — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Прогноз на 7 днів — {city}*\n\n",
        "hourly_header": "🕐 *Погода кожні 3 години — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "м/с",
        "uv_low": "Низький",
        "uv_moderate": "Помірний",
        "uv_high": "Високий",
        "uv_very_high": "Дуже високий",
        "uv_extreme": "Екстремальний",
        "uv_na": "Н/Д",
        "wind_N": "⬆️ П",
        "wind_NE": "↗️ ПС",
        "wind_E": "➡️ С",
        "wind_SE": "↘️ ПС",
        "wind_S": "⬇️ Пд",
        "wind_SW": "↙️ ПдЗ",
        "wind_W": "⬅️ З",
        "wind_NW": "↖️ ПнЗ",
        "crypto_header": "💎 *Курси криптовалют*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Дані від CoinGecko",
        "crypto_error": "⚠️ Не вдається отримати курси криптовалют, спробуйте пізніше.",
        "prayer_header": "🕌 *Час молитов у {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Фаджр:   `{fajr}`\n☀️ Схід:    `{sunrise}`\n🌞 Зухр:    `{dhuhr}`\n🌇 Аср:     `{asr}`\n🌆 Магріб:  `{maghrib}`\n🌙 Іша:     `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Дані від Aladhan API",
        "prayer_no_city": "⚠️ Ваше місто не вказано. Перейдіть до налаштувань.",
        "prayer_city_error": "⚠️ Не вдається отримати час молитов для: {city}",
        "prayer_error": "⚠️ Час молитов зараз недоступний, спробуйте пізніше.",
        "referral_header": "🎁 *Реферальна система*\n━━━━━━━━━━━━━━━\n\n🔗 *Ваше реферальне посилання:*\n`{link}`\n\n👥 *Усього запрошено:* `{count}` осіб\n\n━━━━━━━━━━━━━━━\n📤 Поділіться з друзями та родиною!\nКожен, хто приєднається за вашим посиланням, буде зарахований. 🎯",
        "referral_share_btn": "📤 Поділитися посиланням",
        "share_bot_header": "📢 *Поділіться ботом і допоможіть нам зростати!*\n\n🔗 *Посилання на бот:*\n@{username}\n\n📌 Або за посиланням:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Поділіться з друзями для отримання:\n📰 Останні новини\n🌤 Погода онлайн\n💱 Курси валют\n🕌 Час молитов\n💎 Курси криптовалют",
        "share_bot_btn": "📤 Поділитися ботом",
        "open_bot_btn": "🔗 Відкрити бот",
        "public_stats_header": "📊 *Статистика бота*\n━━━━━━━━━━━━━━━\n\n👥 Всього користувачів: *{total}*\n✅ Активних: *{active}*\n🆕 Приєдналися сьогодні: *{today}*\n⭐ Преміум-передплатників: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Найбільш використовувані мови:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Ваша особиста статистика*\n━━━━━━━━━━━━━━━\n\n👤 Ім'я: *{name}*\n🌍 Мова: *{lang}*\n🏙 Місто: *{city}*\n📅 Дата реєстрації: *{join}*\n\n📰 Отримано новин: *{news}*\n🎁 Надіслано запрошень: *{refs}*\n🔑 Ключових слів: *{kws}*\n⭐ Преміум: *{prem}*\n🔔 Сповіщення: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Так",
        "my_stats_prem_no": "❌ Ні",
        "my_stats_notif_on": "🔔 Активні",
        "my_stats_notif_off": "🔕 Вимкнені",
        "my_stats_user": "Користувач",
        "daily_summary_header": "📋 *Зведення новин за {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Немає джерел новин для цієї мови.",
        "daily_summary_no_news": "⚠️ Немає доступних новин, спробуйте пізніше.",
        "top_referrers_header": "🏆 *Кращі реферери*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Поки немає рефералів — будьте першим! 🎯",
        "top_referrers_invite": "запрошення",
        "dollar_header": "💵 *Долар США до іракського динара*\n\n🏪 Паралельний ринок:\n{rate}\n\n⏰ Останнє оновлення: `{time}`\n📡 Джерело: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Продаж",
        "dollar_buy": "Купівля",
        "dollar_official": "Курс: `{price}` IQD\n_(Офіційний курс — може відрізнятися від ринкового)_",
        "dollar_error": "⚠️ Не вдається отримати курс долара. Спробуйте пізніше.",
        "weekly_summary_header": "📰 *Тижневий огляд — Топ {count} новин*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Тижневе зведення новин*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Збираємо головні новини тижня...",
        "weekly_summary_text_no_source": "⚠️ Немає доступних джерел для цієї мови.",
        "weekly_summary_text_no_news": "⚠️ Недостатньо новин цього тижня.",
        "currency_table_header": "📊 *Повна таблиця курсів валют до USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Преміум-меню — Оберіть:*",
        "premium_btn_7day": "🌤 Прогноз на 7 днів",
        "premium_btn_hourly": "🕐 Погода кожні 3 год.",
        "premium_btn_addcity": "🏙 Додати місто",
        "premium_btn_mycities": "📋 Мої збережені міста",
        "premium_btn_interests": "📌 Мої інтереси",
        "premium_btn_currency_alert": "💱 Сповіщення про валюту",
        "premium_btn_currency_table": "📊 Таблиця валют",
        "premium_btn_notif_time": "🕐 Час сповіщень",
        "premium_btn_weekly": "📰 Тижневий огляд",
        "premium_btn_keywords": "🔑 Ключові слова",
        "premium_subscribe_btn": "⭐ Запросити преміум-передплату",
        "broadcast_weather_msg": "🌤 Погода в {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Відстеження валют, акцій та товарів*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Ваш поточний список:*\n",
        "track_count": "\n({count}/20 символів)\n\n",
        "track_add_hint": "➕ *Додати символ:* надішліть його назву\n\n",
        "track_crypto_label": "💎 *Криптовалюти:*\n",
        "track_fiat_label": "💱 *Фіатні валюти:*\n",
        "track_stocks_label": "📈 *Акції:*\n",
        "track_commodities_label": "🏅 *Сировина та індекси:*\n",
        "track_alert_hint": "🔔 *При зміні ±1% ви отримаєте миттєві сповіщення та щогодинний звіт.*\n\n",
        "track_remove_hint": "❌ Видалити символ: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Переглянути список: `/mytrack`",
        "track_empty": "📌 Список відстеження порожній.\nНатисніть *Відстежити актив*, щоб додати символи.",
        "track_list_header": "📌 *Ваші відстежувані активи:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Цінові сповіщення*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 зріс",
        "track_fell": "📉 впав",
        "track_report_title": "📊 *Щогодинний звіт — Ваші активи*\n",
        "track_unavailable": "недоступно",
        "track_remove_usage": "⚠️ Вкажіть символ після команди. Приклад: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* не знайдено у вашому списку.",
        "track_removed": "✅ *{symbol}* видалено зі списку відстеження.",
        "interest_save_btn": "💾 Зберегти",
        "interest_choose_msg": "📌 *Оберіть свої інтереси (можна кілька):*",
        "currency_rate_header": "💱 *Курси валют до USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Конвертація {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Непідтримувана валюта: {currency}",
        "currency_fetch_error": "⚠️ Не вдається отримати курси валют.",
        "city_add_success": "✅ Місто додано: *{city}*",
        "currency_alert_set": "✅ Ви отримаєте сповіщення, коли долар досягне `{rate}` вашої місцевої валюти.",
        "currency_alert_invalid": "❌ Введіть число, наприклад: 1600",
        "notif_time_set": "✅ Ранковий підсумок надсилатиметься щодня о *{hour}:00*.",
        "notif_time_invalid": "❌ Введіть число від 0 до 23 (наприклад: 8 для 8 ранку)",
    },
    "Italiano 🇮🇹": {
        "no_news": "⚠️ Nessuna notizia nuova al momento.",
        "no_results": "⚠️ Nessun risultato trovato per la tua ricerca.",
        "search_error": "⚠️ Si è verificato un errore durante la ricerca.",
        "no_trending": "⚠️ Nessuna notizia di tendenza ora, riprova più tardi.",
        "trending_header": "🔥 *In Tendenza*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Notizie Sportive*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ Nessuna nuova notizia sportiva al momento.",
        "no_sports_source": "⚠️ Nessuna fonte sportiva per questa lingua.",
        "no_mena": "⚠️ Nessuna nuova notizia politica, riprova più tardi.",
        "no_source": "⚠️ Nessuna fonte di notizie per questa lingua.",
        "weather_error": "⚠️ Impossibile recuperare i dati meteo.",
        "forecast_error": "⚠️ Impossibile recuperare le previsioni orarie.",
        "no_weekly": "⚠️ Nessuna notizia per il riepilogo settimanale.",
        "currency_error": "⚠️ Impossibile recuperare i tassi di cambio.",
        "search_prompt": "🔍 Inserisci la parola di ricerca:",
        "label_breaking": "🚨 Notizia Flash",
        "label_news": "🚨 Notizia",
        "label_mena": "📰 Notizie Politiche del Medio Oriente",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ La tua città non è ancora impostata.",
        "city_not_found": "⚠️ Dati meteo non trovati per: {city}",
        "weather_header": "{emoji} *Meteo a {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Percepita:* {feels}°C\n🔼 Max: {temp_max}°C  |  🔽 Min: {temp_min}°C\n\n☁️ *Condizione:* {desc}\n🌫 *Nuvole:* {clouds}%\n👁 *Visibilità:* {visibility_km} km\n\n💧 *Umidità:* {humidity}%\n🌀 *Pressione:* {pressure} hPa\n☀️ *Indice UV:* {uvi}\n\n💨 *Vento:* {wind_speed} m/s | {wind_dir}\n💨 *Raffiche:* {wind_gust} m/s\n\n🌅 *Alba:* {sunrise}  |  🌇 *Tramonto:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Previsioni 3 giorni — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Previsioni 7 giorni — {city}*\n\n",
        "hourly_header": "🕐 *Meteo ogni 3 ore — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Basso",
        "uv_moderate": "Moderato",
        "uv_high": "Alto",
        "uv_very_high": "Molto alto",
        "uv_extreme": "Estremo",
        "uv_na": "N/D",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ E",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SO",
        "wind_W": "⬅️ O",
        "wind_NW": "↖️ NO",
        "crypto_header": "💎 *Prezzi Crypto*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Dati da CoinGecko",
        "crypto_error": "⚠️ Impossibile recuperare i prezzi crypto, riprova più tardi.",
        "prayer_header": "🕌 *Orari di Preghiera a {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Alba:    `{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Dati da Aladhan API",
        "prayer_no_city": "⚠️ La tua città non è impostata. Vai alle impostazioni.",
        "prayer_city_error": "⚠️ Impossibile recuperare gli orari di preghiera per: {city}",
        "prayer_error": "⚠️ Impossibile recuperare gli orari di preghiera, riprova più tardi.",
        "referral_header": "🎁 *Sistema di Referral*\n━━━━━━━━━━━━━━━\n\n🔗 *Il tuo link di referral:*\n`{link}`\n\n👥 *Totale invitati:* `{count}` persone\n\n━━━━━━━━━━━━━━━\n📤 Condividi con amici e familiari!\nOgni persona che si unisce tramite il tuo link conta. 🎯",
        "referral_share_btn": "📤 Condividi Link",
        "share_bot_header": "📢 *Condividi il bot e aiutaci a crescere!*\n\n🔗 *Link del bot:*\n@{username}\n\n📌 O tramite link:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Condividi con gli amici per ottenere:\n📰 Ultime notizie\n🌤 Meteo in diretta\n💱 Tassi di cambio\n🕌 Orari di preghiera\n💎 Prezzi crypto",
        "share_bot_btn": "📤 Condividi Bot",
        "open_bot_btn": "🔗 Apri Bot",
        "public_stats_header": "📊 *Statistiche del Bot*\n━━━━━━━━━━━━━━━\n\n👥 Utenti totali: *{total}*\n✅ Utenti attivi: *{active}*\n🆕 Iscritti oggi: *{today}*\n⭐ Abbonati premium: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Lingue più usate:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Le Tue Statistiche Personali*\n━━━━━━━━━━━━━━━\n\n👤 Nome: *{name}*\n🌍 Lingua: *{lang}*\n🏙 Città: *{city}*\n📅 Data iscrizione: *{join}*\n\n📰 Notizie ricevute: *{news}*\n🎁 Referral inviati: *{refs}*\n🔑 Parole chiave: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notifiche: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Sì",
        "my_stats_prem_no": "❌ No",
        "my_stats_notif_on": "🔔 Attive",
        "my_stats_notif_off": "🔕 In pausa",
        "my_stats_user": "Utente",
        "daily_summary_header": "📋 *Sommario Notizie di Oggi — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ Nessuna fonte di notizie per questa lingua.",
        "daily_summary_no_news": "⚠️ Nessuna notizia disponibile, riprova più tardi.",
        "top_referrers_header": "🏆 *Migliori Referrer*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Nessun referral ancora — sii il primo! 🎯",
        "top_referrers_invite": "invito/i",
        "dollar_header": "💵 *USD vs Dinaro Iracheno*\n\n🏪 Mercato parallelo:\n{rate}\n\n⏰ Ultimo aggiornamento: `{time}`\n📡 Fonte: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Vendita",
        "dollar_buy": "Acquisto",
        "dollar_official": "Tasso: `{price}` IQD\n_(Tasso ufficiale — può differire dal mercato)_",
        "dollar_error": "⚠️ Impossibile recuperare il tasso del dollaro. Riprova più tardi.",
        "weekly_summary_header": "📰 *Riepilogo Settimanale — Top {count} notizie*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Riepilogo Notizie della Settimana*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Raccogliendo le principali notizie della settimana...",
        "weekly_summary_text_no_source": "⚠️ Nessuna fonte di notizie per questa lingua.",
        "weekly_summary_text_no_news": "⚠️ Notizie insufficienti questa settimana.",
        "currency_table_header": "📊 *Tabella Completa Tassi di Cambio vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Menu Premium — Scegli:*",
        "premium_btn_7day": "🌤 Previsioni 7 giorni",
        "premium_btn_hourly": "🕐 Meteo ogni 3 ore",
        "premium_btn_addcity": "🏙 Aggiungi Città",
        "premium_btn_mycities": "📋 Le mie città salvate",
        "premium_btn_interests": "📌 I miei interessi",
        "premium_btn_currency_alert": "💱 Avviso valuta",
        "premium_btn_currency_table": "📊 Tabella valute",
        "premium_btn_notif_time": "🕐 Orario notifiche",
        "premium_btn_weekly": "📰 Riepilogo settimanale",
        "premium_btn_keywords": "🔑 Parole chiave",
        "premium_subscribe_btn": "⭐ Richiedi Abbonamento Premium",
        "broadcast_weather_msg": "🌤 Meteo a {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Monitoraggio Valute, Azioni e Materie Prime*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *La tua lista attuale:*\n",
        "track_count": "\n({count}/20 simboli)\n\n",
        "track_add_hint": "➕ *Aggiungi simbolo:* invia il suo nome direttamente\n\n",
        "track_crypto_label": "💎 *Criptovalute:*\n",
        "track_fiat_label": "💱 *Valute Fiat:*\n",
        "track_stocks_label": "📈 *Azioni:*\n",
        "track_commodities_label": "🏅 *Materie Prime e Indici:*\n",
        "track_alert_hint": "🔔 *Riceverai avvisi immediati a variazioni di ±1% e report orari.*\n\n",
        "track_remove_hint": "❌ Rimuovi simbolo: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Visualizza la lista: `/mytrack`",
        "track_empty": "📌 Lista monitoraggio vuota.\nPremi *Monitora asset* per aggiungere simboli.",
        "track_list_header": "📌 *I tuoi asset monitorati:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Avvisi di prezzo*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 salito",
        "track_fell": "📉 sceso",
        "track_report_title": "📊 *Report orario — I tuoi asset*\n",
        "track_unavailable": "non disponibile",
        "track_remove_usage": "⚠️ Invia il simbolo dopo il comando. Esempio: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* non è nella tua lista.",
        "track_removed": "✅ *{symbol}* rimosso dalla lista di monitoraggio.",
        "interest_save_btn": "💾 Salva",
        "interest_choose_msg": "📌 *Scegli i tuoi interessi (puoi sceglierne più di uno):*",
        "currency_rate_header": "💱 *Tassi di cambio vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Conversione di {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Valuta non supportata: {currency}",
        "currency_fetch_error": "⚠️ Impossibile recuperare i tassi di cambio.",
        "city_add_success": "✅ Città aggiunta: *{city}*",
        "currency_alert_set": "✅ Sarai avvisato quando il dollaro raggiungerà `{rate}` della tua valuta locale.",
        "currency_alert_invalid": "❌ Invia un numero, ad esempio: 1600",
        "notif_time_set": "✅ Il riepilogo mattutino sarà inviato alle *{hour}:00* ogni giorno.",
        "notif_time_invalid": "❌ Inserisci un numero tra 0 e 23 (esempio: 8 per le 8 di mattina)",
    },
    "Español 🇲🇽": {
        "no_news": "⚠️ No hay noticias nuevas ahora.",
        "no_results": "⚠️ No se encontraron resultados para tu búsqueda.",
        "search_error": "⚠️ Se produjo un error durante la búsqueda.",
        "no_trending": "⚠️ No hay noticias en tendencia ahora, inténtalo más tarde.",
        "trending_header": "🔥 *En Tendencia*\n━━━━━━━━━━━━━━━",
        "sports_header": "⚽ *Noticias Deportivas*\n━━━━━━━━━━━━━━━",
        "no_sports": "⚠️ No hay noticias deportivas nuevas ahora.",
        "no_sports_source": "⚠️ No hay fuentes deportivas para este idioma.",
        "no_mena": "⚠️ No hay noticias políticas nuevas, inténtalo más tarde.",
        "no_source": "⚠️ No hay fuentes de noticias para este idioma.",
        "weather_error": "⚠️ No se pueden obtener datos del tiempo.",
        "forecast_error": "⚠️ No se puede obtener el pronóstico por hora.",
        "no_weekly": "⚠️ No hay noticias para el resumen semanal.",
        "currency_error": "⚠️ No se pueden obtener las tasas de cambio.",
        "search_prompt": "🔍 Escribe la palabra de búsqueda:",
        "label_breaking": "🚨 Última Hora",
        "label_news": "🚨 Noticia",
        "label_mena": "📰 Noticias Políticas del Medio Oriente",
        "label_trending": "🔥",
        "label_sports": "⚽",
        "no_city": "⚠️ Tu ciudad aún no está configurada.",
        "city_not_found": "⚠️ No se encontraron datos del tiempo para: {city}",
        "weather_header": "{emoji} *Tiempo en {city}*\n━━━━━━━━━━━━━━━\n\n🌡 *Temp:* {temp}°C\n🤔 *Sensación:* {feels}°C\n🔼 Máx: {temp_max}°C  |  🔽 Mín: {temp_min}°C\n\n☁️ *Condición:* {desc}\n🌫 *Nubes:* {clouds}%\n👁 *Visibilidad:* {visibility_km} km\n\n💧 *Humedad:* {humidity}%\n🌀 *Presión:* {pressure} hPa\n☀️ *Índice UV:* {uvi}\n\n💨 *Viento:* {wind_speed} m/s | {wind_dir}\n💨 *Ráfagas:* {wind_gust} m/s\n\n🌅 *Amanecer:* {sunrise}  |  🌇 *Atardecer:* {sunset}\n━━━━━━━━━━━━━━━",
        "forecast_3day_header": "📅 *Pronóstico de 3 días — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "forecast_7day_header": "🌤 *Pronóstico de 7 días — {city}*\n\n",
        "hourly_header": "🕐 *Tiempo cada 3 horas — {city}*\n━━━━━━━━━━━━━━━\n\n",
        "wind_unit": "m/s",
        "uv_low": "Bajo",
        "uv_moderate": "Moderado",
        "uv_high": "Alto",
        "uv_very_high": "Muy alto",
        "uv_extreme": "Extremo",
        "uv_na": "N/D",
        "wind_N": "⬆️ N",
        "wind_NE": "↗️ NE",
        "wind_E": "➡️ E",
        "wind_SE": "↘️ SE",
        "wind_S": "⬇️ S",
        "wind_SW": "↙️ SO",
        "wind_W": "⬅️ O",
        "wind_NW": "↖️ NO",
        "crypto_header": "💎 *Precios de Criptomonedas*\n━━━━━━━━━━━━━━━\n\n",
        "crypto_footer": "━━━━━━━━━━━━━━━\n🔄 Datos de CoinGecko",
        "crypto_error": "⚠️ No se pueden obtener precios crypto ahora, inténtalo más tarde.",
        "prayer_header": "🕌 *Horarios de Oración en {city}*\n📅 {date}\n🗓 {hijri}\n━━━━━━━━━━━━━━━\n\n🌅 Fajr:    `{fajr}`\n☀️ Amanecer:`{sunrise}`\n🌞 Dhuhr:   `{dhuhr}`\n🌇 Asr:     `{asr}`\n🌆 Maghrib: `{maghrib}`\n🌙 Isha:    `{isha}`\n━━━━━━━━━━━━━━━\n🔄 Datos de Aladhan API",
        "prayer_no_city": "⚠️ Tu ciudad no está configurada. Ve a Ajustes.",
        "prayer_city_error": "⚠️ No se pueden obtener horarios de oración para: {city}",
        "prayer_error": "⚠️ No se pueden obtener horarios de oración ahora, inténtalo más tarde.",
        "referral_header": "🎁 *Sistema de Referidos*\n━━━━━━━━━━━━━━━\n\n🔗 *Tu enlace de referido:*\n`{link}`\n\n👥 *Total invitados:* `{count}` personas\n\n━━━━━━━━━━━━━━━\n📤 ¡Comparte con amigos y familia!\nCada persona que se una a través de tu enlace cuenta. 🎯",
        "referral_share_btn": "📤 Compartir Enlace",
        "share_bot_header": "📢 *¡Comparte el bot y ayúdanos a crecer!*\n\n🔗 *Enlace del bot:*\n@{username}\n\n📌 O mediante enlace:\n`{link}`\n\n━━━━━━━━━━━━━━━\n💡 Comparte con amigos para obtener:\n📰 Últimas noticias\n🌤 Tiempo en directo\n💱 Tasas de cambio\n🕌 Horarios de oración\n💎 Precios crypto",
        "share_bot_btn": "📤 Compartir Bot",
        "open_bot_btn": "🔗 Abrir Bot",
        "public_stats_header": "📊 *Estadísticas del Bot*\n━━━━━━━━━━━━━━━\n\n👥 Usuarios totales: *{total}*\n✅ Usuarios activos: *{active}*\n🆕 Se unieron hoy: *{today}*\n⭐ Suscriptores premium: *{premium}*\n\n",
        "public_stats_langs": "🌍 *Idiomas más usados:*\n",
        "public_stats_footer": "\n━━━━━━━━━━━━━━━\n🤖 @{username}",
        "my_stats_header": "📈 *Tus Estadísticas Personales*\n━━━━━━━━━━━━━━━\n\n👤 Nombre: *{name}*\n🌍 Idioma: *{lang}*\n🏙 Ciudad: *{city}*\n📅 Fecha de ingreso: *{join}*\n\n📰 Noticias recibidas: *{news}*\n🎁 Referidos enviados: *{refs}*\n🔑 Palabras clave: *{kws}*\n⭐ Premium: *{prem}*\n🔔 Notificaciones: *{notif}*\n",
        "my_stats_prem_yes": "⭐ Sí",
        "my_stats_prem_no": "❌ No",
        "my_stats_notif_on": "🔔 Activas",
        "my_stats_notif_off": "🔕 Pausadas",
        "my_stats_user": "Usuario",
        "daily_summary_header": "📋 *Resumen de Noticias de Hoy — {date}*\n━━━━━━━━━━━━━━━\n\n",
        "daily_summary_no_source": "⚠️ No hay fuentes de noticias para este idioma.",
        "daily_summary_no_news": "⚠️ No hay noticias disponibles ahora, inténtalo más tarde.",
        "top_referrers_header": "🏆 *Mejores Referidores*\n━━━━━━━━━━━━━━━\n\n",
        "top_referrers_empty": "📊 Aún no hay referidos — ¡sé el primero! 🎯",
        "top_referrers_invite": "invitación(es)",
        "dollar_header": "💵 *USD vs Dinar Iraquí*\n\n🏪 Mercado paralelo:\n{rate}\n\n⏰ Última actualización: `{time}`\n📡 Fuente: {source}\n\n━━━━━━━━━━━━━━\n🤖 @{username}",
        "dollar_sell": "Venta",
        "dollar_buy": "Compra",
        "dollar_official": "Tasa: `{price}` IQD\n_(Tasa oficial — puede diferir del mercado)_",
        "dollar_error": "⚠️ No se puede obtener la tasa del dólar ahora. Inténtalo más tarde.",
        "weekly_summary_header": "📰 *Resumen Semanal — Top {count} noticias*\n━━━━━━━━━━━━━━━\n\n",
        "weekly_summary_text_header": "📆 *Resumen de Noticias de la Semana*\n📅 {start} — {end}\n━━━━━━━━━━━━━━\n",
        "weekly_summary_text_wait": "⏳ Recopilando las principales noticias de la semana...",
        "weekly_summary_text_no_source": "⚠️ No hay fuentes de noticias para este idioma.",
        "weekly_summary_text_no_news": "⚠️ No hay suficientes noticias esta semana.",
        "currency_table_header": "📊 *Tabla Completa de Tasas de Cambio vs USD 🇺🇸*\n━━━━━━━━━━━━━━━\n\n",
        "premium_menu_header": "⭐ *Menú Premium — Elige:*",
        "premium_btn_7day": "🌤 Pronóstico de 7 días",
        "premium_btn_hourly": "🕐 Tiempo cada 3 horas",
        "premium_btn_addcity": "🏙 Agregar Ciudad",
        "premium_btn_mycities": "📋 Mis Ciudades Guardadas",
        "premium_btn_interests": "📌 Mis Intereses",
        "premium_btn_currency_alert": "💱 Alerta de Divisas",
        "premium_btn_currency_table": "📊 Tabla de Divisas",
        "premium_btn_notif_time": "🕐 Hora de Notificación",
        "premium_btn_weekly": "📰 Resumen Semanal",
        "premium_btn_keywords": "🔑 Palabras Clave",
        "premium_subscribe_btn": "⭐ Solicitar Suscripción Premium",
        "broadcast_weather_msg": "🌤 Tiempo en {city}: {temp}°C\n☁️ {desc}",
        "track_header": "📌 *Seguimiento de Divisas, Acciones y Materias Primas*\n━━━━━━━━━━━━━━━\n\n",
        "track_current_list": "📋 *Tu lista actual:*\n",
        "track_count": "\n({count}/20 símbolos)\n\n",
        "track_add_hint": "➕ *Agregar símbolo:* envía su nombre directamente\n\n",
        "track_crypto_label": "💎 *Criptomonedas:*\n",
        "track_fiat_label": "💱 *Divisas Fiat:*\n",
        "track_stocks_label": "📈 *Acciones:*\n",
        "track_commodities_label": "🏅 *Materias Primas e Índices:*\n",
        "track_alert_hint": "🔔 *Recibirás alertas inmediatas a cambios de ±1% y reporte por hora.*\n\n",
        "track_remove_hint": "❌ Eliminar símbolo: `/removetrack AAPL`\n",
        "track_list_hint": "📋 Ver tu lista: `/mytrack`",
        "track_empty": "📌 Lista de seguimiento vacía.\nPresiona *Rastrear activo* para agregar símbolos.",
        "track_list_header": "📌 *Tus activos rastreados:*\n━━━━━━━━━━━━━━\n",
        "track_alert_title": "🚨 *Alertas de precios*\n━━━━━━━━━━━━━━━\n\n",
        "track_rose": "📈 subió",
        "track_fell": "📉 bajó",
        "track_report_title": "📊 *Reporte por hora — Tus activos*\n",
        "track_unavailable": "no disponible",
        "track_remove_usage": "⚠️ Envía el símbolo después del comando. Ejemplo: `/removetrack AAPL`",
        "track_not_found": "⚠️ *{symbol}* no está en tu lista.",
        "track_removed": "✅ *{symbol}* eliminado de la lista de seguimiento.",
        "interest_save_btn": "💾 Guardar",
        "interest_choose_msg": "📌 *Elige tus intereses (puedes elegir más de uno):*",
        "currency_rate_header": "💱 *Tasas de cambio vs USD 🇺🇸*\n\n",
        "currency_local_label": "🏠 {name}",
        "currency_convert_header": "🔄 *Conversión de {amount} {currency}*\n━━━━━━━━━━━━━━━\n\n",
        "currency_unsupported": "⚠️ Divisa no compatible: {currency}",
        "currency_fetch_error": "⚠️ No se pueden obtener las tasas de cambio.",
        "city_add_success": "✅ Ciudad agregada: *{city}*",
        "currency_alert_set": "✅ Se te avisará cuando el dólar alcance `{rate}` de tu moneda local.",
        "currency_alert_invalid": "❌ Envía un número, por ejemplo: 1600",
        "notif_time_set": "✅ El resumen matinal se enviará a las *{hour}:00* todos los días.",
        "notif_time_invalid": "❌ Ingresa un número entre 0 y 23 (ejemplo: 8 para las 8 de la mañana)",
    },
}

def t(lang, key):
    """ترجمة رسالة نظام حسب لغة المستخدم مع الرجوع للإنجليزية إذا لم توجد."""
    return MSGS.get(lang, MSGS["English 🇬🇧"]).get(key, MSGS["English 🇬🇧"].get(key, ""))

# ======== رسائل الإعداد والتفاعل المترجمة ========

# ═══════════════════════════════════════════════════════════════════
# قاموس الرسائل متعددة اللغات — كل رسالة تصل للمستخدم
# ═══════════════════════════════════════════════════════════════════
_UL = {
    # ─── الملخص الصباحي ──────────────────────────────────────────
    "morning_title": {
        "العربية 🇮🇶": "🌅 *ملخص صباحي ذكي*\n━━━━━━━━━━━━━━━",
        "English 🇬🇧":  "🌅 *Smart Morning Briefing*\n━━━━━━━━━━━━━━━",
        "Русский 🇷🇺":  "🌅 *Умная утренняя сводка*\n━━━━━━━━━━━━━━━",
        "فارسی 🇮🇷":    "🌅 *خلاصه صبحگاهی*\n━━━━━━━━━━━━━━━",
        "हिन्दी 🇮🇳":   "🌅 *स्मार्ट मॉर्निंग ब्रीफिंग*\n━━━━━━━━━━━━━━━",
        "Português 🇧🇷": "🌅 *Resumo Matinal Inteligente*\n━━━━━━━━━━━━━━━",
        "Türkçe 🇹🇷":   "🌅 *Sabah Özeti*\n━━━━━━━━━━━━━━━",
        "اردو 🇵🇰":     "🌅 *صبح کا خلاصہ*\n━━━━━━━━━━━━━━━",
        "Deutsch 🇩🇪":  "🌅 *Morgenzusammenfassung*\n━━━━━━━━━━━━━━━",
        "Українська 🇺🇦": "🌅 *Ранковий огляд*\n━━━━━━━━━━━━━━━",
        "Italiano 🇮🇹": "🌅 *Briefing Mattutino*\n━━━━━━━━━━━━━━━",
        "Español 🇲🇽":  "🌅 *Resumen Matutino*\n━━━━━━━━━━━━━━━",
    },
    "morning_weather": {
        "العربية 🇮🇶": "\n🌡 *الطقس الآن*\n",
        "English 🇬🇧":  "\n🌡 *Current Weather*\n",
        "Русский 🇷🇺":  "\n🌡 *Текущая погода*\n",
        "فارسی 🇮🇷":    "\n🌡 *آبوهوا*\n",
        "हिन्दी 🇮🇳":   "\n🌡 *मौसम*\n",
        "Português 🇧🇷": "\n🌡 *Clima Atual*\n",
        "Türkçe 🇹🇷":   "\n🌡 *Hava Durumu*\n",
        "اردو 🇵🇰":     "\n🌡 *موجودہ موسم*\n",
        "Deutsch 🇩🇪":  "\n🌡 *Aktuelles Wetter*\n",
        "Українська 🇺🇦": "\n🌡 *Поточна погода*\n",
        "Italiano 🇮🇹": "\n🌡 *Meteo Attuale*\n",
        "Español 🇲🇽":  "\n🌡 *Clima Actual*\n",
    },
    "morning_prayer": {
        "العربية 🇮🇶": "\n🕌 *الصلاة القادمة*\n",
        "English 🇬🇧":  "\n🕌 *Next Prayer*\n",
        "Русский 🇷🇺":  "\n🕌 *Следующий намаз*\n",
        "فارسی 🇮🇷":    "\n🕌 *نماز بعدی*\n",
        "हिन्दी 🇮🇳":   "\n🕌 *अगली नमाज़*\n",
        "Português 🇧🇷": "\n🕌 *Próxima Oração*\n",
        "Türkçe 🇹🇷":   "\n🕌 *Sonraki Namaz*\n",
        "اردو 🇵🇰":     "\n🕌 *اگلی نماز*\n",
        "Deutsch 🇩🇪":  "\n🕌 *Nächstes Gebet*\n",
        "Українська 🇺🇦": "\n🕌 *Наступна молитва*\n",
        "Italiano 🇮🇹": "\n🕌 *Prossima Preghiera*\n",
        "Español 🇲🇽":  "\n🕌 *Próxima Oración*\n",
    },
    "morning_news": {
        "العربية 🇮🇶": "\n📰 *أبرز الأخبار*\n",
        "English 🇬🇧":  "\n📰 *Top Headlines*\n",
        "Русский 🇷🇺":  "\n📰 *Главные новости*\n",
        "فارسی 🇮🇷":    "\n📰 *اخبار برتر*\n",
        "हिन्दी 🇮🇳":   "\n📰 *मुख्य समाचार*\n",
        "Português 🇧🇷": "\n📰 *Principais Notícias*\n",
        "Türkçe 🇹🇷":   "\n📰 *Günün Haberleri*\n",
        "اردو 🇵🇰":     "\n📰 *اہم خبریں*\n",
        "Deutsch 🇩🇪":  "\n📰 *Hauptnachrichten*\n",
        "Українська 🇺🇦": "\n📰 *Головні новини*\n",
        "Italiano 🇮🇹": "\n📰 *Notizie Principali*\n",
        "Español 🇲🇽":  "\n📰 *Titulares Principales*\n",
    },
    # ─── النشرة المسائية ─────────────────────────────────────────
    "evening_title": {
        "العربية 🇮🇶": "🌆 *نشرة مسائية — أبرز أخبار اليوم*\n━━━━━━━━━━━━━━\n",
        "English 🇬🇧":  "🌆 *Evening Briefing — Top News Today*\n━━━━━━━━━━━━━━\n",
        "Русский 🇷🇺":  "🌆 *Вечерняя сводка — Главные новости дня*\n━━━━━━━━━━━━━━\n",
        "فارسی 🇮🇷":    "🌆 *خلاصه عصرگاهی — اخبار امروز*\n━━━━━━━━━━━━━━\n",
        "हिन्दी 🇮🇳":   "🌆 *शाम का बुलेटिन — आज की सुर्खियाँ*\n━━━━━━━━━━━━━━\n",
        "Português 🇧🇷": "🌆 *Boletim Noturno — Notícias do Dia*\n━━━━━━━━━━━━━━\n",
        "Türkçe 🇹🇷":   "🌆 *Akşam Bülteni — Günün Haberleri*\n━━━━━━━━━━━━━━\n",
        "اردو 🇵🇰":     "🌆 *شام کا خلاصہ — آج کی خبریں*\n━━━━━━━━━━━━━━\n",
        "Deutsch 🇩🇪":  "🌆 *Abendbericht — Schlagzeilen des Tages*\n━━━━━━━━━━━━━━\n",
        "Українська 🇺🇦": "🌆 *Вечірній огляд — Новини дня*\n━━━━━━━━━━━━━━\n",
        "Italiano 🇮🇹": "🌆 *Notiziario Serale — Principali di Oggi*\n━━━━━━━━━━━━━━\n",
        "Español 🇲🇽":  "🌆 *Boletín Vespertino — Noticias del Día*\n━━━━━━━━━━━━━━\n",
    },
    # ─── تنبيه الطقس ─────────────────────────────────────────────
    "weather_heat": {
        "العربية 🇮🇶": "🔥 *تنبيه حرارة شديدة!*\nدرجة الحرارة في {city}: *{temp}°C*\nكن حذراً!",
        "English 🇬🇧":  "🔥 *Extreme Heat Warning!*\nTemperature in {city}: *{temp}°C*\nStay safe!",
        "Русский 🇷🇺":  "🔥 *Сильная жара!*\nТемпература в {city}: *{temp}°C*\nБудьте осторожны!",
        "فارسی 🇮🇷":    "🔥 *هشدار گرمای شدید!*\nدما در {city}: *{temp}°C*\nمراقب باشید!",
        "हिन्दी 🇮🇳":   "🔥 *भीषण गर्मी की चेतावनी!*\n{city} में तापमान: *{temp}°C*\nसावधान रहें!",
        "Português 🇧🇷": "🔥 *Alerta de Calor Extremo!*\nTemperatura em {city}: *{temp}°C*\nFique seguro!",
        "Türkçe 🇹🇷":   "🔥 *Aşırı Sıcak Uyarısı!*\n{city}'de sıcaklık: *{temp}°C*\nDikkatli olun!",
        "اردو 🇵🇰":     "🔥 *شدید گرمی کی وارننگ!*\n{city} میں درجہ حرارت: *{temp}°C*\nمحتاط رہیں!",
        "Deutsch 🇩🇪":  "🔥 *Hitzewarnung!*\nTemperatur in {city}: *{temp}°C*\nBleiben Sie sicher!",
        "Українська 🇺🇦": "🔥 *Попередження про спеку!*\nТемпература в {city}: *{temp}°C*\nБудьте обережні!",
        "Italiano 🇮🇹": "🔥 *Allerta Caldo Estremo!*\nTemperatura a {city}: *{temp}°C*\nState al sicuro!",
        "Español 🇲🇽":  "🔥 *¡Alerta de Calor Extremo!*\nTemperatura en {city}: *{temp}°C*\n¡Tenga cuidado!",
    },
    "weather_alert": {
        "العربية 🇮🇶": "🌧 *تنبيه طقس!*\n{city}: {desc}",
        "English 🇬🇧":  "🌧 *Weather Alert!*\n{city}: {desc}",
        "Русский 🇷🇺":  "🌧 *Погодное предупреждение!*\n{city}: {desc}",
        "فارسی 🇮🇷":    "🌧 *هشدار آبوهوا!*\n{city}: {desc}",
        "हिन्दी 🇮🇳":   "🌧 *मौसम चेतावनी!*\n{city}: {desc}",
        "Português 🇧🇷": "🌧 *Alerta Meteorológico!*\n{city}: {desc}",
        "Türkçe 🇹🇷":   "🌧 *Hava Durumu Uyarısı!*\n{city}: {desc}",
        "اردو 🇵🇰":     "🌧 *موسمی انتباہ!*\n{city}: {desc}",
        "Deutsch 🇩🇪":  "🌧 *Wetterwarnung!*\n{city}: {desc}",
        "Українська 🇺🇦": "🌧 *Метеопопередження!*\n{city}: {desc}",
        "Italiano 🇮🇹": "🌧 *Allerta Meteo!*\n{city}: {desc}",
        "Español 🇲🇽":  "🌧 *¡Alerta Meteorológica!*\n{city}: {desc}",
    },
    # ─── تنبيه العملة ────────────────────────────────────────────
    "currency_alert": {
        "العربية 🇮🇶": "💱 *تنبيه العملة!*\nوصل الدولار إلى `{rate}` {currency}",
        "English 🇬🇧":  "💱 *Currency Alert!*\nUSD reached `{rate}` {currency}",
        "Русский 🇷🇺":  "💱 *Валютный сигнал!*\nДоллар достиг `{rate}` {currency}",
        "فارسی 🇮🇷":    "💱 *هشدار ارز!*\nدلار به `{rate}` {currency} رسید",
        "हिन्दी 🇮🇳":   "💱 *मुद्रा अलर्ट!*\nUSD `{rate}` {currency} हो गया",
        "Português 🇧🇷": "💱 *Alerta de Câmbio!*\nUSD chegou a `{rate}` {currency}",
        "Türkçe 🇹🇷":   "💱 *Döviz Uyarısı!*\nUSD `{rate}` {currency} oldu",
        "اردو 🇵🇰":     "💱 *کرنسی الرٹ!*\nڈالر `{rate}` {currency} ہو گیا",
        "Deutsch 🇩🇪":  "💱 *Währungsalarm!*\nUSD erreichte `{rate}` {currency}",
        "Українська 🇺🇦": "💱 *Валютне сповіщення!*\nUSD досяг `{rate}` {currency}",
        "Italiano 🇮🇹": "💱 *Avviso Valuta!*\nUSD ha raggiunto `{rate}` {currency}",
        "Español 🇲🇽":  "💱 *¡Alerta de Divisas!*\nUSD llegó a `{rate}` {currency}",
    },
    # ─── تنبيه الكلمة المفتاحية ───────────────────────────────────
    "keyword_alert": {
        "العربية 🇮🇶": "🔑 *تنبيه:* `{kw}`\n\n📰 {title}",
        "English 🇬🇧":  "🔑 *Keyword Alert:* `{kw}`\n\n📰 {title}",
        "Русский 🇷🇺":  "🔑 *Ключевое слово:* `{kw}`\n\n📰 {title}",
        "فارسی 🇮🇷":    "🔑 *هشدار کلیدواژه:* `{kw}`\n\n📰 {title}",
        "हिन्दी 🇮🇳":   "🔑 *कीवर्ड अलर्ट:* `{kw}`\n\n📰 {title}",
        "Português 🇧🇷": "🔑 *Alerta de Palavra-chave:* `{kw}`\n\n📰 {title}",
        "Türkçe 🇹🇷":   "🔑 *Anahtar Kelime Uyarısı:* `{kw}`\n\n📰 {title}",
        "اردو 🇵🇰":     "🔑 *کلیدی لفظ الرٹ:* `{kw}`\n\n📰 {title}",
        "Deutsch 🇩🇪":  "🔑 *Stichwort-Alarm:* `{kw}`\n\n📰 {title}",
        "Українська 🇺🇦": "🔑 *Сповіщення:* `{kw}`\n\n📰 {title}",
        "Italiano 🇮🇹": "🔑 *Avviso Parola Chiave:* `{kw}`\n\n📰 {title}",
        "Español 🇲🇽":  "🔑 *Alerta de Palabra Clave:* `{kw}`\n\n📰 {title}",
    },
    # ─── تنبيه الأزمة ────────────────────────────────────────────
    "crisis_alert": {
        "العربية 🇮🇶": "🚨 *إنذار مبكر*\nالكلمة: `{kw}` — تكررت `{n}` مرة خلال 30 دقيقة\n⚠️ محتمل وجود حدث طارئ",
        "English 🇬🇧":  "🚨 *Early Warning*\nKeyword: `{kw}` — {n} times in 30 min\n⚠️ Possible breaking event",
        "Русский 🇷🇺":  "🚨 *Раннее предупреждение*\nСлово: `{kw}` — {n} раз за 30 мин\n⚠️ Возможное экстренное событие",
        "فارسی 🇮🇷":    "🚨 *هشدار اولیه*\nکلمه: `{kw}` — {n} بار در 30 دقیقه\n⚠️ احتمال رویداد اضطراری",
        "हिन्दी 🇮🇳":   "🚨 *प्रारंभिक चेतावनी*\nशब्द: `{kw}` — 30 मिनट में {n} बार\n⚠️ आपातकालीन घटना संभव",
        "Português 🇧🇷": "🚨 *Aviso Prévio*\nPalavra: `{kw}` — {n} vezes em 30 min\n⚠️ Possível evento urgente",
        "Türkçe 🇹🇷":   "🚨 *Erken Uyarı*\nKelime: `{kw}` — 30 dakikada {n} kez\n⚠️ Acil olay olası",
        "اردو 🇵🇰":     "🚨 *ابتدائی انتباہ*\nلفظ: `{kw}` — 30 منٹ میں {n} بار\n⚠️ ہنگامی واقعہ ممکن",
        "Deutsch 🇩🇪":  "🚨 *Frühwarnung*\nWort: `{kw}` — {n} Mal in 30 Min\n⚠️ Mögliches Notfallereignis",
        "Українська 🇺🇦": "🚨 *Раннє попередження*\nСлово: `{kw}` — {n} разів за 30 хв\n⚠️ Можлива надзвичайна подія",
        "Italiano 🇮🇹": "🚨 *Allerta Precoce*\nParola: `{kw}` — {n} volte in 30 min\n⚠️ Possibile evento urgente",
        "Español 🇲🇽":  "🚨 *Alerta Temprana*\nPalabra: `{kw}` — {n} veces en 30 min\n⚠️ Posible evento de emergencia",
    },
    # ─── قسم الرياضة ─────────────────────────────────────────────
    "sports_title": {
        "العربية 🇮🇶": "⚽ *قسم الرياضة*\n\n",
        "English 🇬🇧":  "⚽ *Sports Section*\n\n",
        "Русский 🇷🇺":  "⚽ *Спортивный раздел*\n\n",
        "فارسی 🇮🇷":    "⚽ *بخش ورزش*\n\n",
        "हिन्दी 🇮🇳":   "⚽ *खेल विभाग*\n\n",
        "Português 🇧🇷": "⚽ *Seção de Esportes*\n\n",
        "Türkçe 🇹🇷":   "⚽ *Spor Bölümü*\n\n",
        "اردو 🇵🇰":     "⚽ *کھیل کا حصہ*\n\n",
        "Deutsch 🇩🇪":  "⚽ *Sport-Bereich*\n\n",
        "Українська 🇺🇦": "⚽ *Спортивний розділ*\n\n",
        "Italiano 🇮🇹": "⚽ *Sezione Sport*\n\n",
        "Español 🇲🇽":  "⚽ *Sección Deportiva*\n\n",
    },
    "sports_leagues": {
        "العربية 🇮🇶": "📊 دورياتك: {n}",
        "English 🇬🇧":  "📊 Your leagues: {n}",
        "Русский 🇷🇺":  "📊 Ваши лиги: {n}",
        "فارسی 🇮🇷":    "📊 لیگهای شما: {n}",
        "हिन्दी 🇮🇳":   "📊 आपकी लीग: {n}",
        "Português 🇧🇷": "📊 Suas ligas: {n}",
        "Türkçe 🇹🇷":   "📊 Ligleriniz: {n}",
        "اردو 🇵🇰":     "📊 آپ کی لیگ: {n}",
        "Deutsch 🇩🇪":  "📊 Ihre Ligen: {n}",
        "Українська 🇺🇦": "📊 Ваші ліги: {n}",
        "Italiano 🇮🇹": "📊 Le tue leghe: {n}",
        "Español 🇲🇽":  "📊 Tus ligas: {n}",
    },
    "sports_no_leagues": {
        "العربية 🇮🇶": "لم تختر دوريات بعد",
        "English 🇬🇧":  "No leagues selected yet",
        "Русский 🇷🇺":  "Лиги не выбраны",
        "فارسی 🇮🇷":    "هیچ لیگی انتخاب نشده",
        "हिन्दी 🇮🇳":   "कोई लीग नहीं चुनी",
        "Português 🇧🇷": "Nenhuma liga selecionada",
        "Türkçe 🇹🇷":   "Henüz lig seçilmedi",
        "اردو 🇵🇰":     "ابھی تک کوئی لیگ نہیں چنی",
        "Deutsch 🇩🇪":  "Noch keine Ligen ausgewählt",
        "Українська 🇺🇦": "Ліги не вибрані",
        "Italiano 🇮🇹": "Nessuna lega selezionata",
        "Español 🇲🇽":  "No hay ligas seleccionadas",
    },
    "sports_alerts_on": {
        "العربية 🇮🇶": "تنبيهات مباشرة: مفعّلة 🔔",
        "English 🇬🇧":  "Live alerts: On 🔔",
        "Русский 🇷🇺":  "Прямые уведомления: Вкл 🔔",
        "فارسی 🇮🇷":    "هشدار زنده: فعال 🔔",
        "हिन्दी 🇮🇳":   "लाइव अलर्ट: चालू 🔔",
        "Português 🇧🇷": "Alertas ao vivo: Ativo 🔔",
        "Türkçe 🇹🇷":   "Canlı uyarılar: Açık 🔔",
        "اردو 🇵🇰":     "براہ راست الرٹ: فعال 🔔",
        "Deutsch 🇩🇪":  "Live-Alarme: Ein 🔔",
        "Українська 🇺🇦": "Прямі сповіщення: Увімк 🔔",
        "Italiano 🇮🇹": "Avvisi in diretta: Attivo 🔔",
        "Español 🇲🇽":  "Alertas en vivo: Activado 🔔",
    },
    "sports_alerts_off": {
        "العربية 🇮🇶": "تنبيهات مباشرة: مغلقة 🔕",
        "English 🇬🇧":  "Live alerts: Off 🔕",
        "Русский 🇷🇺":  "Прямые уведомления: Выкл 🔕",
        "فارسی 🇮🇷":    "هشدار زنده: غیرفعال 🔕",
        "हिन्दी 🇮🇳":   "लाइव अलर्ट: बंद 🔕",
        "Português 🇧🇷": "Alertas ao vivo: Desativo 🔕",
        "Türkçe 🇹🇷":   "Canlı uyarılar: Kapalı 🔕",
        "اردو 🇵🇰":     "براہ راست الرٹ: بند 🔕",
        "Deutsch 🇩🇪":  "Live-Alarme: Aus 🔕",
        "Українська 🇺🇦": "Прямі сповіщення: Вимк 🔕",
        "Italiano 🇮🇹": "Avvisi in diretta: Disattivo 🔕",
        "Español 🇲🇽":  "Alertas en vivo: Desactivado 🔕",
    },
    "sports_choose": {
        "العربية 🇮🇶": "اختر من القائمة:",
        "English 🇬🇧":  "Choose from the menu:",
        "Русский 🇷🇺":  "Выберите из меню:",
        "فارسی 🇮🇷":    "از منو انتخاب کنید:",
        "हिन्दी 🇮🇳":   "मेनू से चुनें:",
        "Português 🇧🇷": "Escolha do menu:",
        "Türkçe 🇹🇷":   "Menüden seçin:",
        "اردو 🇵🇰":     "مینو سے انتخاب کریں:",
        "Deutsch 🇩🇪":  "Aus dem Menü wählen:",
        "Українська 🇺🇦": "Виберіть з меню:",
        "Italiano 🇮🇹": "Scegli dal menu:",
        "Español 🇲🇽":  "Elige del menú:",
    },
}

def _ul(lang: str, key: str, **kwargs) -> str:
    """ترجمة رسالة حسب اللغة مع دعم المتغيرات"""
    d = _UL.get(key, {})
    text = d.get(lang) or d.get("English 🇬🇧") or d.get("العربية 🇮🇶") or ""
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text


SETUP_MSGS = {
    "العربية 🇮🇶": {
        "choose_country": "🌍 اختر دولتك:",
        "choose_province": "🏙 اختر محافظتك:",
        "settings_saved": "✅ تم حفظ اختياراتك\nستصلك الأخبار والطقس تلقائيًا كل ساعة.",
        "choose_country_from_list": "👇 الرجاء اختيار دولة من القائمة.",
        "choose_province_from_list": "👇 الرجاء اختيار محافظة من القائمة.",
        "notif_enabled": "🔔 تم تفعيل الإشعارات التلقائية.",
        "notif_disabled": "🔕 تم إيقاف الإشعارات التلقائية.",
        "convert_prompt": "🔄 أرسل المبلغ والعملة، مثال:\n*100 USD*\n*50 EUR*\n*200 IQD*",
        "convert_format_error": "⚠️ صيغة غير صحيحة. مثال: *100 USD*",
        "convert_send_both": "⚠️ أرسل المبلغ والعملة معاً. مثال: *100 USD*",
        "keywords_saved": "✅ تم حفظ {n} كلمة مفتاحية.\n🔔 ستصلك تنبيه عند ظهورها في أي خبر!",
    },
    "English 🇬🇧": {
        "choose_country": "🌍 Choose your country:",
        "choose_province": "🏙 Choose your city/province:",
        "settings_saved": "✅ Your settings have been saved!\nYou'll receive news and weather automatically every hour.",
        "choose_country_from_list": "👇 Please select a country from the list.",
        "choose_province_from_list": "👇 Please select a city from the list.",
        "notif_enabled": "🔔 Automatic notifications have been enabled.",
        "notif_disabled": "🔕 Automatic notifications have been disabled.",
        "convert_prompt": "🔄 Send the amount and currency, example:\n*100 USD*\n*50 EUR*\n*200 GBP*",
        "convert_format_error": "⚠️ Invalid format. Example: *100 USD*",
        "convert_send_both": "⚠️ Send the amount and currency together. Example: *100 USD*",
        "keywords_saved": "✅ {n} keyword(s) saved.\n🔔 You'll be alerted when they appear in any news!",
    },
    "Русский 🇷🇺": {
        "choose_country": "🌍 Выберите страну:",
        "choose_province": "🏙 Выберите город/регион:",
        "settings_saved": "✅ Ваши настройки сохранены!\nВы будете получать новости и погоду автоматически каждый час.",
        "choose_country_from_list": "👇 Пожалуйста, выберите страну из списка.",
        "choose_province_from_list": "👇 Пожалуйста, выберите город из списка.",
        "notif_enabled": "🔔 Автоматические уведомления включены.",
        "notif_disabled": "🔕 Автоматические уведомления отключены.",
        "convert_prompt": "🔄 Отправьте сумму и валюту, например:\n*100 USD*\n*50 EUR*\n*200 RUB*",
        "convert_format_error": "⚠️ Неверный формат. Пример: *100 USD*",
        "convert_send_both": "⚠️ Отправьте сумму и валюту вместе. Пример: *100 USD*",
        "keywords_saved": "✅ Сохранено {n} ключевых слов.\n🔔 Вы получите уведомление, когда они появятся в новостях!",
    },
    "فارسی 🇮🇷": {
        "choose_country": "🌍 کشور خود را انتخاب کنید:",
        "choose_province": "🏙 استان/شهر خود را انتخاب کنید:",
        "settings_saved": "✅ تنظیمات شما ذخیره شد!\nاخبار و آبوهوا هر ساعت برایتان ارسال میشود.",
        "choose_country_from_list": "👇 لطفاً یک کشور از لیست انتخاب کنید.",
        "choose_province_from_list": "👇 لطفاً یک شهر از لیست انتخاب کنید.",
        "notif_enabled": "🔔 اعلانهای خودکار فعال شد.",
        "notif_disabled": "🔕 اعلانهای خودکار غیرفعال شد.",
        "convert_prompt": "🔄 مبلغ و ارز را ارسال کنید، مثال:\n*100 USD*\n*50 EUR*\n*200 IRR*",
        "convert_format_error": "⚠️ فرمت نادرست. مثال: *100 USD*",
        "convert_send_both": "⚠️ مبلغ و ارز را با هم بفرستید. مثال: *100 USD*",
        "keywords_saved": "✅ {n} کلمه کلیدی ذخیره شد.\n🔔 هنگامی که در اخباری ظاهر شوند اطلاعرسانی میشوید!",
    },
    "हिन्दी 🇮🇳": {
        "choose_country": "🌍 अपना देश चुनें:",
        "choose_province": "🏙 अपना शहर/राज्य चुनें:",
        "settings_saved": "✅ आपकी सेटिंग सेव हो गई!\nआपको हर घंटे स्वचालित रूप से समाचार और मौसम मिलेगा।",
        "choose_country_from_list": "👇 कृपया सूची से एक देश चुनें।",
        "choose_province_from_list": "👇 कृपया सूची से एक शहर चुनें।",
        "notif_enabled": "🔔 स्वचालित सूचनाएं सक्रिय की गईं।",
        "notif_disabled": "🔕 स्वचालित सूचनाएं बंद की गईं।",
        "convert_prompt": "🔄 राशि और मुद्रा भेजें, उदाहरण:\n*100 USD*\n*50 EUR*\n*200 INR*",
        "convert_format_error": "⚠️ गलत प्रारूप। उदाहरण: *100 USD*",
        "convert_send_both": "⚠️ राशि और मुद्रा एक साथ भेजें। उदाहरण: *100 USD*",
        "keywords_saved": "✅ {n} कीवर्ड सेव किए गए।\n🔔 जब भी वे किसी खबर में आएंगे आपको अलर्ट मिलेगा!",
    },
    "Português 🇧🇷": {
        "choose_country": "🌍 Escolha seu país:",
        "choose_province": "🏙 Escolha sua cidade/estado:",
        "settings_saved": "✅ Suas configurações foram salvas!\nVocê receberá notícias e clima automaticamente a cada hora.",
        "choose_country_from_list": "👇 Por favor, selecione um país da lista.",
        "choose_province_from_list": "👇 Por favor, selecione uma cidade da lista.",
        "notif_enabled": "🔔 Notificações automáticas ativadas.",
        "notif_disabled": "🔕 Notificações automáticas desativadas.",
        "convert_prompt": "🔄 Envie o valor e a moeda, exemplo:\n*100 USD*\n*50 EUR*\n*200 BRL*",
        "convert_format_error": "⚠️ Formato inválido. Exemplo: *100 USD*",
        "convert_send_both": "⚠️ Envie o valor e a moeda juntos. Exemplo: *100 USD*",
        "keywords_saved": "✅ {n} palavra(s)-chave salva(s).\n🔔 Você será alertado quando aparecerem em qualquer notícia!",
    },
    "Türkçe 🇹🇷": {
        "choose_country": "🌍 Ülkenizi seçin:",
        "choose_province": "🏙 Şehrinizi seçin:",
        "settings_saved": "✅ Ayarlarınız kaydedildi!\nHer saat otomatik olarak haber ve hava durumu alacaksınız.",
        "choose_country_from_list": "👇 Lütfen listeden bir ülke seçin.",
        "choose_province_from_list": "👇 Lütfen listeden bir şehir seçin.",
        "notif_enabled": "🔔 Otomatik bildirimler etkinleştirildi.",
        "notif_disabled": "🔕 Otomatik bildirimler devre dışı bırakıldı.",
        "convert_prompt": "🔄 Tutarı ve para birimini gönderin, örnek:\n*100 USD*\n*50 EUR*\n*200 TRY*",
        "convert_format_error": "⚠️ Geçersiz format. Örnek: *100 USD*",
        "convert_send_both": "⚠️ Tutarı ve para birimini birlikte gönderin. Örnek: *100 USD*",
        "keywords_saved": "✅ {n} anahtar kelime kaydedildi.\n🔔 Herhangi bir haberde göründüklerinde uyarılacaksınız!",
    },
    "اردو 🇵🇰": {
        "choose_country": "🌍 اپنا ملک منتخب کریں:",
        "choose_province": "🏙 اپنا شہر منتخب کریں:",
        "settings_saved": "✅ آپ کی ترتیبات محفوظ ہو گئیں!\nآپ کو ہر گھنٹے خودکار طور پر خبریں اور موسم ملے گا۔",
        "choose_country_from_list": "👇 براہ کرم فہرست سے ایک ملک منتخب کریں۔",
        "choose_province_from_list": "👇 براہ کرم فہرست سے ایک شہر منتخب کریں۔",
        "notif_enabled": "🔔 خودکار اطلاعات فعال ہو گئیں۔",
        "notif_disabled": "🔕 خودکار اطلاعات بند ہو گئیں۔",
        "convert_prompt": "🔄 رقم اور کرنسی بھیجیں، مثال:\n*100 USD*\n*50 EUR*\n*200 PKR*",
        "convert_format_error": "⚠️ غلط فارمیٹ۔ مثال: *100 USD*",
        "convert_send_both": "⚠️ رقم اور کرنسی ایک ساتھ بھیجیں۔ مثال: *100 USD*",
        "keywords_saved": "✅ {n} مطلوبہ الفاظ محفوظ ہوئے۔\n🔔 جب کسی خبر میں آئیں گے آپ کو اطلاع ملے گی!",
    },
    "Deutsch 🇩🇪": {
        "choose_country": "🌍 Wählen Sie Ihr Land:",
        "choose_province": "🏙 Wählen Sie Ihre Stadt:",
        "settings_saved": "✅ Ihre Einstellungen wurden gespeichert!\nSie erhalten stündlich automatisch Nachrichten und Wetter.",
        "choose_country_from_list": "👇 Bitte wählen Sie ein Land aus der Liste.",
        "choose_province_from_list": "👇 Bitte wählen Sie eine Stadt aus der Liste.",
        "notif_enabled": "🔔 Automatische Benachrichtigungen wurden aktiviert.",
        "notif_disabled": "🔕 Automatische Benachrichtigungen wurden deaktiviert.",
        "convert_prompt": "🔄 Betrag und Währung senden, Beispiel:\n*100 USD*\n*50 EUR*\n*200 CHF*",
        "convert_format_error": "⚠️ Ungültiges Format. Beispiel: *100 USD*",
        "convert_send_both": "⚠️ Betrag und Währung zusammen senden. Beispiel: *100 USD*",
        "keywords_saved": "✅ {n} Schlüsselwörter gespeichert.\n🔔 Sie werden benachrichtigt, wenn sie in Nachrichten erscheinen!",
    },
    "Українська 🇺🇦": {
        "choose_country": "🌍 Виберіть свою країну:",
        "choose_province": "🏙 Виберіть своє місто:",
        "settings_saved": "✅ Ваші налаштування збережено!\nВи будете автоматично отримувати новини і погоду кожну годину.",
        "choose_country_from_list": "👇 Будь ласка, виберіть країну зі списку.",
        "choose_province_from_list": "👇 Будь ласка, виберіть місто зі списку.",
        "notif_enabled": "🔔 Автоматичні сповіщення увімкнено.",
        "notif_disabled": "🔕 Автоматичні сповіщення вимкнено.",
        "convert_prompt": "🔄 Надішліть суму та валюту, наприклад:\n*100 USD*\n*50 EUR*\n*200 UAH*",
        "convert_format_error": "⚠️ Невірний формат. Приклад: *100 USD*",
        "convert_send_both": "⚠️ Надішліть суму і валюту разом. Приклад: *100 USD*",
        "keywords_saved": "✅ Збережено {n} ключових слів.\n🔔 Ви будете повідомлені, коли вони з'являться в новинах!",
    },
    "Italiano 🇮🇹": {
        "choose_country": "🌍 Scegli il tuo paese:",
        "choose_province": "🏙 Scegli la tua città:",
        "settings_saved": "✅ Le tue impostazioni sono state salvate!\nRiceverai notizie e meteo automaticamente ogni ora.",
        "choose_country_from_list": "👇 Per favore seleziona un paese dall'elenco.",
        "choose_province_from_list": "👇 Per favore seleziona una città dall'elenco.",
        "notif_enabled": "🔔 Notifiche automatiche attivate.",
        "notif_disabled": "🔕 Notifiche automatiche disattivate.",
        "convert_prompt": "🔄 Invia l'importo e la valuta, esempio:\n*100 USD*\n*50 EUR*\n*200 CHF*",
        "convert_format_error": "⚠️ Formato non valido. Esempio: *100 USD*",
        "convert_send_both": "⚠️ Invia importo e valuta insieme. Esempio: *100 USD*",
        "keywords_saved": "✅ {n} parola/e chiave salvata/e.\n🔔 Sarai avvisato quando appariranno in qualsiasi notizia!",
    },
    "Español 🇲🇽": {
        "choose_country": "🌍 Elige tu país:",
        "choose_province": "🏙 Elige tu ciudad:",
        "settings_saved": "✅ ¡Tu configuración ha sido guardada!\nRecibirás noticias y clima automáticamente cada hora.",
        "choose_country_from_list": "👇 Por favor selecciona un país de la lista.",
        "choose_province_from_list": "👇 Por favor selecciona una ciudad de la lista.",
        "notif_enabled": "🔔 Las notificaciones automáticas han sido activadas.",
        "notif_disabled": "🔕 Las notificaciones automáticas han sido desactivadas.",
        "convert_prompt": "🔄 Envía el monto y la moneda, ejemplo:\n*100 USD*\n*50 EUR*\n*200 MXN*",
        "convert_format_error": "⚠️ Formato no válido. Ejemplo: *100 USD*",
        "convert_send_both": "⚠️ Envía el monto y la moneda juntos. Ejemplo: *100 USD*",
        "keywords_saved": "✅ Se guardaron {n} palabras clave.\n🔔 ¡Serás alertado cuando aparezcan en cualquier noticia!",
    },
}

def st(lang, key, **kwargs):
    """ترجمة رسائل الإعداد والتفاعل حسب لغة المستخدم."""
    text = SETUP_MSGS.get(lang, SETUP_MSGS["English 🇬🇧"]).get(
        key, SETUP_MSGS["English 🇬🇧"].get(key, "")
    )
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text

# ======== cache مؤقت لملخصات الأخبار ========
import hashlib
_news_summary_cache = {}

def _cache_summary(link, summary_text, title=""):
    """تخزين ملخص الخبر مع مفتاح MD5 مختصر."""
    key = hashlib.md5(link.encode("utf-8")).hexdigest()[:16]
    if len(_news_summary_cache) > 5000:
        oldest = list(_news_summary_cache.keys())[:500]
        for k in oldest:
            del _news_summary_cache[k]
    _news_summary_cache[key] = {"text": summary_text, "title": title}
    return key

def _clean_html(text):
    """إزالة وسوم HTML والروابط من الملخص."""
    import re
    text = re.sub(r'<[^>]+>', '', text or '')
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    # حذف روابط t.me وURLs عامة من الملخص
    text = re.sub(r'https?://t\.me/\S*', '', text)
    text = re.sub(r'https?://\S+', '', text)
    # حذف @mention للقنوات
    text = re.sub(r'@[A-Za-z0-9_]{3,}', '', text)
    # حذف سطر "المصدر:" أو نحوه
    text = re.sub(r'(المصدر|Source|via|©|حصري)[^\n]*', '', text, flags=re.IGNORECASE)
    # تنظيف مسافات زائدة
    text = re.sub(r'\s{3,}', ' ', text)
    return text.strip()

def _pub_dt_from_item(item):
    """استخراج pub_dt من feedparser item."""
    pub_struct = (getattr(item, 'published_parsed', None)
                  or getattr(item, 'updated_parsed', None))
    if pub_struct:
        try:
            import calendar as _cal
            return datetime.datetime.utcfromtimestamp(_cal.timegm(pub_struct))
        except Exception:
            pass
    return None

# ======== قاموس أسماء المصادر ========
SOURCE_NAMES = {
    "alsumaria.tv": "السومرية",
    "shafaq.com": "شفق نيوز",
    "rudaw.net": "رووداو",
    "almaalomah.com": "المعلومة",
    "almada-paper.com": "المدى",
    "almadapaper.net": "المدى",
    "baghdadtoday.news": "بغداد اليوم",
    "ina.iq": "وكالة الأنباء العراقية",
    "buratha.com": "بوابة برثا",
    "mawazin.net": "موازين",
    "non14.net": "نون14",
    "aliraqnews.com": "الأخبار العراقية",
    "kitabat.com": "كتابات",
    "lvinpress.com": "لفين برس",
    "xebat.net": "خه بات",
    "nasiriyah.org": "ناصرية",
    "azzaman.com": "الزمان",
    "almasalah.com": "المصالح",
    "basnews.com": "باس نيوز",
    "alsharqiya.com": "قناة الشرقية",
    "sotaliraq.com": "صوت العراق",
    "imn.iq": "قناة العراقية",
    "mangish.net": "منكيش نت",
    "alarabiya.net": "العربية",
    "bbc.com": "بي بي سي",
    "bbc.co.uk": "بي بي سي",
    "aljazeera.net": "الجزيرة",
    "aljazeera.com": "الجزيرة",
    "skynewsarabia.com": "سكاي نيوز عربية",
    "rt.com": "روسيا اليوم",
    "independentarabia.com": "إندبندنت عربية",
    "france24.com": "فرانس 24",
    "euronews.com": "يورونيوز",
    "arabi21.com": "عربي 21",
    "middleeasteye.net": "ميدل إيست آي",
    "aawsat.com": "الشرق الأوسط",
    "almayadeen.net": "الميادين",
    "alhurra.com": "الحرة",
    "aa.com.tr": "الأناضول",
    "asharq.com": "الشرق",
    "raialyoum.com": "رأي اليوم",
    "noonpost.com": "نون بوست",
    "arabicpost.net": "ذا عربي بوست",
    "almasryalyoum.com": "المصري اليوم",
    "youm7.com": "اليوم السابع",
    "alquds.com": "القدس",
    "reuters.com": "رويترز",
    "nytimes.com": "نيويورك تايمز",
    "washingtonpost.com": "واشنطن بوست",
    "theguardian.com": "الغارديان",
    "cnn.com": "CNN",
    "apnews.com": "أسوشيتد برس",
    "dw.com": "DW",
    "hurriyet.com.tr": "حرييت",
    "sabah.com.tr": "صباح",
    "trtworld.com": "TRT World",
    "geo.tv": "جيو نيوز",
    "jang.com.pk": "جانج",
    # قنوات تلغرام
    "t.me/StevenNabilIraq": "ستيفن نبيل العراق",
    "t.me/baghdad7city": "بغداد سيتي",
    "t.me/iraq11e": "عراق نيوز",
    "t.me/iraqi1_news": "أخبار العراق 1",
    "t.me/iraqi1news": "شبكة أخبار العراق",
    "t.me/Iraqi1news": "شبكة أخبار العراق",
    "t.me/Iraq_now3": "عراق ناو",
    "t.me/iraqnow3": "عراق ناو",
    "t.me/RN24_IQ": "راديو نوا 24 عراق",
    "t.me/alsbaahiq": "الصباح العراقية",
    "t.me/inainaiq": "وكالة الأنباء العراقية",
    "t.me/IraqiMediaNet": "شبكة الإعلام العراقية",
    "t.me/alhadath_TV": "الحدث العراق",
    "t.me/AlHadathNews": "الحدث العراق",
    "t.me/AlRaedNews": "الرائد نيوز",
    "t.me/IraqNewsCh": "قناة أخبار العراق",
    "t.me/baghdad_breaking": "بغداد عاجل",
    "t.me/iraqbreaking": "عراق عاجل",
    "t.me/IraqBreakingNews": "عراق عاجل",
    "t.me/alsumariaTVNews": "السومرية نيوز",
    "t.me/AlSumaria": "السومرية",
    "t.me/alforatnews": "الفرات نيوز",
    "t.me/AlFurqan_1": "الفرقان",
    "t.me/AlAhad_TV": "الأحد نيوز",
    "t.me/mosulnews": "موصل نيوز",
    "t.me/basranews": "البصرة نيوز",
    "t.me/kurdistan_news": "كردستان نيوز",
}

# أسماء قنوات تلغرام للعرض السريع
_TG_CHANNEL_NAMES = {ch["handle"]: ch["name"]
                     for channels in TELEGRAM_NEWS_CHANNELS.values()
                     for ch in channels}

def get_source_name_from_url(feed_url):
    """استخراج اسم المصدر من رابط الـ RSS أو رابط تلغرام"""
    try:
        # روابط تلغرام: t.me/channelname أو t.me/channelname/123
        if "t.me/" in feed_url:
            # استخراج الهاندل بشكل موثوق
            clean_url = feed_url.replace("https://", "").replace("http://", "")
            parts = clean_url.split("/")
            # parts[0]="t.me", parts[1]=handle, parts[2]=message_id (اختياري)
            handle = parts[1] if len(parts) > 1 else parts[0].split("t.me/")[-1]
            handle = handle.split("?")[0].strip()  # حذف query params إن وجدت
            # بحث في قاموس القنوات المعروفة (TELEGRAM_NEWS_CHANNELS)
            if handle in _TG_CHANNEL_NAMES:
                return _TG_CHANNEL_NAMES[handle]
            # بحث في SOURCE_NAMES بشكل غير حساس لحالة الأحرف
            handle_lower = handle.lower()
            for key, name in SOURCE_NAMES.items():
                if key.startswith("t.me/") and key.split("t.me/")[-1].lower() == handle_lower:
                    return name
            # إعادة الهاندل كاسم نظيف (بدون رابط)
            return f"@{handle}"
        import urllib.parse as _up
        host = _up.urlparse(feed_url).netloc.lower()
        for prefix in ("www.", "feeds.", "rss.", "feed."):
            if host.startswith(prefix):
                host = host[len(prefix):]
        for key, name in SOURCE_NAMES.items():
            if key in host:
                return name
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[-2].replace("-", " ").capitalize()
        return host
    except Exception:
        return ""

def get_source_name_from_feed(feed_obj, feed_url=""):
    """استخراج اسم المصدر من بيانات الـ feed أو من الـ URL"""
    try:
        feed_meta = getattr(feed_obj, 'feed', None)
        if feed_meta:
            feed_title = getattr(feed_meta, 'title', '')
            if feed_title and len(feed_title.strip()) > 1:
                clean = feed_title.strip().split('|')[0].split(' - ')[0].strip()
                if clean and len(clean) < 60:
                    return clean
    except Exception:
        pass
    return get_source_name_from_url(feed_url)

# ======== دوال الأخبار ========
def escape_md(text):
    if not text:
        return ""
    # MarkdownV1 لا يدعم backslash escape — نحذف الرموز الخطرة مباشرة
    for ch in ['_', '*', '`', '[', ']', '\\']:
        text = text.replace(ch, '')
    return text

# ── لاصقة "آخر الأخبار" لكل لغة (تُستخدم في البث التلقائي) ──────────────
_LABEL_LATEST = {
    "العربية 🇮🇶": "آخر الأخبار",
    "English 🇬🇧":  "Latest News",
    "Русский 🇷🇺":  "Последние новости",
    "فارسی 🇮🇷":   "آخرین اخبار",
    "हिंदी 🇮🇳":    "ताज़ा खबर",
    "Español 🇪🇸":  "Últimas noticias",
    "Türkçe 🇹🇷":  "Son Haberler",
    "اردو 🇵🇰":    "تازہ خبریں",
    "Français 🇫🇷": "Dernières nouvelles",
    "Deutsch 🇩🇪":  "Aktuelle Nachrichten",
    "中文 🇨🇳":     "最新新闻",
    "日本語 🇯🇵":   "最新ニュース",
}

_DEFAULT_NEWS_LABEL = "🚨 خبر عاجل"

def format_news_item(prefix, title, lang=None, source_name=None, pub_time_str=None, summary=None):
    """
    شكل الخبر المطابق للتصميم المطلوب:
    📰 🗞️ عنوان الخبر
    ━━━━━━━━━━━━━━━━━━
    آخر الأخبار 🗞️ · اسم المصدر 🗞️ · منذ لحظات 🕐
    ━━━━━━━━━━━━━━━━━━
    نص/ملخص الخبر
    لا تنسى المشاركة @Iraqnowbot
    """
    separator = "━━━━━━━━━━━━━━━━━━"
    safe_title = escape_md(title)

    # ── السطر الأول: عنوان الخبر مع أيقونة ──────────────────
    result = f"📰 🗞️ *{safe_title}*\n{separator}"

    # ── سطر المعلومات: التسمية + المصدر + الوقت ─────────────
    meta_parts = []
    custom_label = news_settings.get("label", _DEFAULT_NEWS_LABEL)
    label = prefix if custom_label == _DEFAULT_NEWS_LABEL else custom_label
    meta_parts.append(f"{label} 🗞️")
    if source_name:
        meta_parts.append(f"{escape_md(source_name)} 🗞️")
    if pub_time_str:
        meta_parts.append(f"{pub_time_str} 🕐")
    if meta_parts:
        result += "\n" + "  ·  ".join(meta_parts)

    result += f"\n{separator}"

    # ── ملخص/نص الخبر ────────────────────────────────────────
    if summary:
        clean_snip = _clean_html(summary)
        if clean_snip and len(clean_snip) > 20:
            snip = clean_snip[:300].rsplit(' ', 1)[0] + '…' if len(clean_snip) > 300 else clean_snip
            result += f"\n\n{escape_md(snip)}"
    else:
        # إذا لا ملخص، كرر العنوان كنص الخبر (مثل الصورة)
        result += f"\n\n{safe_title}"

    # ── التوقيع ───────────────────────────────────────────────
    result += f"\n\n*لا تنسى المشاركة* @{BOT_USERNAME}"
    return result

def make_news_share_markup(link, title="", lang="العربية 🇮🇶", summary=""):
    """
    أزرار الخبر — كل زر في سطر منفصل:
    🔗 فتح الخبر        ← يفتح المقال مباشرةً (url)
    📩 شارك الخبر       ← يشارك الرابط عبر تيليغرام
    📄 ملخص الخبر
    🔔 تابع هذه القصة
    🔍 تحقق من الخبر
    🤖 شارك البوت @Iraqnowbot
    """
    import urllib.parse, hashlib as _hs

    markup = types.InlineKeyboardMarkup(row_width=1)

    # ── إعداد روابط المشاركة ────────────────────────────────────────
    _lnk_lower = (link or "").lower()
    is_valid_url = _lnk_lower.startswith("http://") or _lnk_lower.startswith("https://")
    is_tg_link   = "t.me/" in _lnk_lower or "telegram.me/" in _lnk_lower

    share_text   = f"📰 {title[:100]}\n\n🔗 {link}\n\nعبر @{BOT_USERNAME}" if title else f"🔗 {link}\n\nعبر @{BOT_USERNAME}"
    share_url    = f"https://t.me/share/url?url={urllib.parse.quote(link or '', safe='')}&text={urllib.parse.quote(share_text, safe='')}"
    bot_link     = f"https://t.me/{BOT_USERNAME}"
    bot_share_u  = f"https://t.me/share/url?url={urllib.parse.quote(bot_link, safe='')}&text={urllib.parse.quote(f'اشترك في @{BOT_USERNAME} لمتابعة آخر الأخبار العراقية 🇮🇶', safe='')}"

    # ── زر 0: فتح الخبر مباشرةً 🔗 ─────────────────────────────────
    # هذا الزر مفقود في الإصدارات السابقة — يفتح المقال الأصلي مباشرةً
    if is_valid_url and link and not is_tg_link:
        markup.add(types.InlineKeyboardButton("🔗 فتح الخبر", url=link))
    elif is_tg_link and is_valid_url and link:
        markup.add(types.InlineKeyboardButton("🔗 فتح في تيليغرام", url=link))

    # ── زر 1: شارك الخبر 📩 ────────────────────────────────────────
    if is_valid_url and link:
        markup.add(types.InlineKeyboardButton("📩 شارك الخبر", url=share_url))
    else:
        markup.add(types.InlineKeyboardButton("📩 شارك الخبر", url=bot_link))

    # ── زر 2: ملخص الخبر 📄 ────────────────────────────────────────
    clean_summary = _clean_html(summary) if summary else ""
    if clean_summary and len(clean_summary) > 20 and link:
        sum_key = _cache_summary(link, clean_summary, title=title)
        markup.add(types.InlineKeyboardButton("📄 ملخص الخبر", callback_data=f"sum_{sum_key}"))
    elif title:
        # حتى بدون ملخص، نوفر زر الملخص بناءً على العنوان وحده
        sum_key = _cache_summary(link or title, title, title=title)
        markup.add(types.InlineKeyboardButton("📄 ملخص الخبر", callback_data=f"sum_{sum_key}"))

    # ── زر 3: تابع هذه القصة 🔔 ────────────────────────────────────
    if title:
        story_key = _hs.md5((link or title).encode("utf-8")).hexdigest()[:16]
        kw = title[:40].rsplit(' ', 1)[0] if len(title) > 40 else title
        if len(_story_key_cache) > 3000:
            for _sk in list(_story_key_cache.keys())[:300]:
                del _story_key_cache[_sk]
        _story_key_cache[story_key] = kw
        markup.add(types.InlineKeyboardButton("🔔 تابع هذه القصة", callback_data=f"follow_story_{story_key}"))

    # ── زر 4: تحقق من الخبر 🔍 ────────────────────────────────────
    if title:
        fc_key = _hs.md5(title.encode("utf-8")).hexdigest()[:16]
        if len(_factcheck_key_cache) > 3000:
            for _ok in list(_factcheck_key_cache.keys())[:300]:
                del _factcheck_key_cache[_ok]
        is_new_key = fc_key not in _factcheck_key_cache
        _factcheck_key_cache[fc_key] = title[:400]
        # حفظ الكاش على القرص في خلفية (غير متزامن — لا يبطئ الإرسال)
        if is_new_key:
            threading.Thread(target=_save_factcheck_cache,
                             args=(_factcheck_key_cache.copy(),),
                             daemon=True, name="SaveFcCache").start()
        markup.add(types.InlineKeyboardButton("🔍 تحقق من الخبر", callback_data=f"fc_{fc_key}"))

    # ── زر 5: شارك البوت 🤖 ────────────────────────────────────────
    markup.add(types.InlineKeyboardButton(f"🤖 شارك البوت @{BOT_USERNAME}", url=bot_share_u))

    return markup

def send_hourly_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    sent = user.setdefault("sent_news", set())
    count = 0
    for feed_url in feeds:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            src_name = get_source_name_from_feed(feed, feed_url)
            for item in feed.entries[:3]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                title = getattr(item, 'title', '').strip()
                if not title:
                    continue
                if not _title_in_lang(title, lang):
                    continue
                pub_struct = getattr(item, 'published_parsed', None) or getattr(item, 'updated_parsed', None)
                pub_dt = None
                if pub_struct:
                    try:
                        import calendar as _cal
                        pub_dt = datetime.datetime.utcfromtimestamp(_cal.timegm(pub_struct))
                    except Exception:
                        pub_dt = None
                pub_time_str = _format_pub_time(pub_dt, lang=lang)
                sent.add(item.link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(item.link, title, lang, item_sum)
                bot.send_message(uid, format_news_item(t(lang, "label_news"), title, lang, src_name, pub_time_str, summary=item_sum), parse_mode="Markdown", reply_markup=markup)
                count += 1
        except Exception:
            pass  # فشل مصدر واحد لا يوقف باقي المصادر
    if count == 0:
        bot.send_message(uid, t(lang, "no_news"))
    else:
        _db_save_all_users(users)

def send_all_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    sent = user.setdefault("sent_news", set())
    count = 0
    for feed_url in feeds:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            src_name = get_source_name_from_feed(feed, feed_url)
            for item in feed.entries[:15]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                title = getattr(item, 'title', '').strip()
                if not title or not _title_in_lang(title, lang):
                    continue
                pub_struct = getattr(item, 'published_parsed', None) or getattr(item, 'updated_parsed', None)
                pub_dt = None
                if pub_struct:
                    try:
                        import calendar as _cal
                        pub_dt = datetime.datetime.utcfromtimestamp(_cal.timegm(pub_struct))
                    except Exception:
                        pub_dt = None
                pub_time_str = _format_pub_time(pub_dt, lang=lang)
                sent.add(item.link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(item.link, title, lang, item_sum)
                bot.send_message(uid, format_news_item(t(lang, "label_breaking"), title, lang, src_name, pub_time_str, summary=item_sum), parse_mode="Markdown", reply_markup=markup)
                count += 1
        except Exception:
            pass  # فشل مصدر واحد لا يوقف باقي المصادر
    if count == 0:
        bot.send_message(uid, t(lang, "no_news"))
    else:
        _db_save_all_users(users)

def send_mena_politics(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "العربية 🇮🇶")
    mena_feeds = MENA_RSS.get(lang, MENA_RSS.get("العربية 🇮🇶", []))
    sent = user.setdefault("sent_news", set())
    count = 0
    headlines_sent = []
    for feed_url in mena_feeds:
        try:
            feed = _parse_feed(feed_url)
            if feed is None:
                feed = feedparser.parse(feed_url)
            if not feed:
                continue
            for item in feed.entries[:10]:
                title = getattr(item, 'title', '').strip()
                link = getattr(item, 'link', '')
                if not link or not title:
                    continue
                if link in sent:
                    continue
                if not _title_in_lang(title, lang):
                    continue
                sent.add(link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(link, title, lang, item_sum)
                src_name = get_source_name_from_url(feed_url)
                pub_time_str = _format_pub_time(_pub_dt_from_item(item), lang=lang)
                bot.send_message(uid, format_news_item(t(lang, "label_mena"), title, lang, src_name, pub_time_str, summary=item_sum), parse_mode="Markdown", reply_markup=markup)
                headlines_sent.append(title)
                count += 1
                if count >= 10:
                    break
        except Exception:
            pass  # فشل مصدر MENA لا يوقف باقي المصادر
        if count >= 10:
            break
    if count == 0:
        general_feeds = RSS.get(lang, [])
        for feed_url in general_feeds:
            try:
                feed = _parse_feed(feed_url)
                if feed is None:
                    feed = feedparser.parse(feed_url)
                if not feed:
                    continue
                for item in feed.entries[:30]:
                    title = getattr(item, 'title', '')
                    link = getattr(item, 'link', '')
                    if not link or link in sent:
                        continue
                    title_lower = title.lower()
                    if any(kw.lower() in title_lower for kw in MENA_KEYWORDS):
                        if not _title_in_lang(title, lang):
                            continue
                        sent.add(link)
                        item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                        markup = make_news_share_markup(link, title, lang, item_sum)
                        src_name2 = get_source_name_from_url(feed_url)
                        pub_time_str = _format_pub_time(_pub_dt_from_item(item), lang=lang)
                        bot.send_message(uid, format_news_item(t(lang, "label_mena"), title, lang, src_name2, pub_time_str, summary=item_sum), parse_mode="Markdown", reply_markup=markup)
                        count += 1
                        if count >= 5:
                            break
            except Exception:
                pass  # فشل fallback MENA لا يوقف باقي المصادر
            if count >= 5:
                break
    if count == 0:
        bot.send_message(uid, t(lang, "no_news"))
    else:
        _db_save_all_users(users)

# ======== البث التلقائي ========
def broadcast_weather():
    # تم إزالة البث التلقائي للطقس — الطقس يُرسل فقط عند طلب المستخدم
    # هذه الدالة محجوزة للاستخدام اليدوي إذا أراد الأدمن ذلك
    pass

MAX_NEWS_PER_BROADCAST  = 3   # قنوات/مجموعات: 3 أخبار كحد أقصى لكل دورة بث
MAX_NEWS_PER_USER_CYCLE = 5   # مستخدمون: 5 أخبار كحد أقصى لكل مستخدم لكل دورة

def broadcast_news():
    """
    البث التلقائي للأخبار — يستخدم تتبعاً عالمياً لكل لغة بدلاً من تتبع منفصل لكل مستخدم.
    هذا يضمن:
    1. عدم تكرار الخبر مع أي عدد من المستخدمين (حتى لو كانوا 100 ألف).
    2. استهلاك ذاكرة ثابت بغض النظر عن عدد المستخدمين (مجموعة واحدة لكل لغة).
    """
    _logger.info("🔄 broadcast_news بدأت دورة جديدة")
    # إعادة تعيين مجموعة الأرشفة في كل دورة حتى لا تكبر إلى ما لا نهاية
    broadcast_news._archived_this_cycle = set()
    if bot_paused or broadcast_paused:
        _logger.info("⏸ broadcast_news: موقوف (bot_paused=%s, broadcast_paused=%s)", bot_paused, broadcast_paused)
        return
    # Event-based lock: set = مشغول، clear = حر
    if _broadcast_news_lock.is_set():
        _logger.info("🔒 broadcast_news: لا تزال الدورة السابقة شغّالة — تخطي")
        return
    _broadcast_news_lock.set()
    _broadcast_lock_ts[0] = time.time()
    try:
        # الخطوة 1: جمع الأخبار الجديدة لكل لغة (مرة واحدة فقط بدلاً من لكل مستخدم)
        new_items_by_lang  = {}  # lang -> أخبار جديدة (مفلترة بـ global_sent) — للقنوات
        all_fresh_by_lang  = {}  # lang -> كل الأخبار الطازجة (بدون global_sent) — للمستخدمين
        total_collected = 0      # عداد إجمالي لمنع الفيضان
        all_langs = set()
        for uid, info in users.items():
            if info.get("lang"):
                all_langs.add(info["lang"])
        # أضف لغات القنوات والمجموعات حتى تحصل على أخبارها في نفس الدورة
        for ch in channels_groups:
            if not ch.get('paused') and not ch.get('custom_sources'):
                cl = ch.get('lang', 'العربية 🇮🇶')
                if cl:
                    all_langs.add(cl)
        for lang in all_langs:
            if total_collected >= _MAX_NEWS_PER_CYCLE:
                break
            feeds = RSS.get(lang, [])

            # ══════════════════════════════════════════════════════════════
            # المرحلة A: جمع المرشحين (بدون أي قفل — لا يتجمد البث!)
            # ══════════════════════════════════════════════════════════════
            raw_candidates = []  # (link, title, feed_url, summary, pub_dt)

            # ─── RSS ─────────────────────────────────────────────────────
            # يقرأ من الكاش فقط — _rss_prefetcher يُحدّثه كل 90 ثانية.
            # لا جلب متزامن هنا → broadcast_news لا يتأخر أبداً.
            # استثناء: إذا لم يكن الـ feed في الكاش إطلاقاً (أول تشغيل)
            # نجلب أول 3 feeds فقط بشكل متوازٍ لتسريع الإقلاع الأول.
            now_ts = time.time()
            missing_feeds = []
            with _global_rss_cache_lock:
                for f in feeds:
                    if f not in _global_rss_cache:
                        missing_feeds.append(f)
            if missing_feeds:
                # جلب أول 5 feeds فقط (الإقلاع الأول) لتجنب التأخر
                first_batch = missing_feeds[:5]
                def _fetch_missing(url):
                    entries = _fetch_one_feed(url)
                    with _global_rss_cache_lock:
                        _global_rss_cache[url] = (entries, time.time())
                with ThreadPoolExecutor(max_workers=min(5, len(first_batch))) as ex:
                    futs = {ex.submit(_fetch_missing, url): url for url in first_batch}
                    for fut in as_completed(futs, timeout=15):
                        try: fut.result()
                        except Exception: pass
            all_entries = []
            with _global_rss_cache_lock:
                for feed_url in feeds:
                    cached = _global_rss_cache.get(feed_url)
                    if cached:
                        all_entries.extend(cached[0])
            all_entries.sort(
                key=lambda x: x.get("published_dt") or datetime.datetime(2000, 1, 1),
                reverse=True
            )
            for entry in all_entries:
                link  = entry["link"]
                title = entry["title"]
                if is_blacklisted(title):
                    continue
                pub_dt = entry.get("published_dt")
                # pub_dt=None → نقبل الخبر (مصدر لا يُرفق وقت النشر)
                # pub_dt موجود → نتحقق من الحداثة
                if pub_dt is not None and not _is_fresh(pub_dt):
                    continue
                raw_candidates.append((link, title, entry["feed_url"], entry.get("summary",""), pub_dt))

            # ─── Web Scraping ────────────────────────────────────────────
            if _BS4_AVAILABLE:
                for src in SCRAPE_SOURCES.get(lang, []):
                    try:
                        scraped = _scrape_news_site(src['url'], src['base_url'], max_items=10)
                        for s_title, s_link in scraped:
                            if not is_blacklisted(s_title):
                                raw_candidates.append((s_link, s_title, src['url'], '', None))
                    except Exception:
                        pass

            # ─── قنوات تيليغرام العراقية ──────────────────────────────
            if _BS4_AVAILABLE:
                for ch in TELEGRAM_NEWS_CHANNELS.get(lang, []):
                    try:
                        tg_posts = _scrape_telegram_channel(ch['handle'], max_items=10)
                        for raw_text, tg_link in tg_posts:
                            if not is_blacklisted(raw_text) and not _is_tg_spam(raw_text, tg_link):
                                uid_key = tg_link or raw_text[:80]
                                raw_candidates.append((uid_key, raw_text, f"t.me/{ch['handle']}", raw_text, None))
                    except Exception:
                        pass

            # ─── NewsAPI ─────────────────────────────────────────────────
            if NEWS_KEY:
                try:
                    lang_code = LANG_CODES.get(lang, "en")
                    na_r = requests.get(
                        f"https://newsapi.org/v2/top-headlines?language={lang_code}&pageSize=10&apiKey={NEWS_KEY}",
                        timeout=8
                    )
                    if na_r.status_code == 200:
                        for art in na_r.json().get("articles", []):
                            na_link  = art.get("url", "")
                            na_title = art.get("title", "")
                            if na_link and na_title and not is_blacklisted(na_title):
                                na_pub_str = art.get("publishedAt", "")
                                try:
                                    na_pub_dt = datetime.datetime.strptime(na_pub_str, "%Y-%m-%dT%H:%M:%SZ") if na_pub_str else None
                                except Exception:
                                    na_pub_dt = None
                                if na_pub_dt and _is_fresh(na_pub_dt):
                                    src_name = art.get("source", {}).get("name", "NewsAPI")
                                    raw_candidates.append((na_link, na_title, src_name, art.get("description","") or "", na_pub_dt))
                except Exception:
                    pass

            # ══════════════════════════════════════════════════════════════
            # المرحلة B: بناء قائمتين منفصلتين
            # all_fresh: كل الأخبار الطازجة (للمستخدمين — مفلترة بـ user_sent شخصياً)
            # new_items: أخبار جديدة فعلاً (للقنوات — مفلترة بـ global_sent لمنع التكرار)
            # ══════════════════════════════════════════════════════════════
            # تنقية أساسية لـ all_fresh (إزالة usernames/hashtags من منشورات تيليغرام)
            import re as _re_b
            all_fresh_cleaned = []
            for (lnk, ttl, src, summ, pdt) in raw_candidates:
                try:
                    if src.startswith('t.me/'):
                        _t = _re_b.sub(r'@\S+|#\S+|https?://\S+', '', ttl).strip()
                        if _t and len(_t) >= 15:
                            all_fresh_cleaned.append((lnk, _t, src, summ, pdt))
                    else:
                        all_fresh_cleaned.append((lnk, ttl, src, summ, pdt))
                except Exception:
                    all_fresh_cleaned.append((lnk, ttl, src, summ, pdt))
            # تطبيق فلتر اللغة وإزالة التكرار على all_fresh
            _af = [item for item in all_fresh_cleaned if _title_in_lang(item[1], lang)]
            all_fresh_by_lang[lang] = _dedup_news_list(_af)

            # global_sent للقنوات فقط (يمنع إعادة إرسال نفس الخبر كل دورة)
            with _global_sent_lock:
                global_sent = _global_sent_news.setdefault(lang, set())
                if len(global_sent) > 5000:
                    global_sent = set(list(global_sent)[-3000:])
                    _global_sent_news[lang] = global_sent
            # فلتر global_sent مع تطبيع الروابط لمنع التكرار بروابط متشابهة
            new_items = [
                cand for cand in raw_candidates
                if _normalize_news_link(cand[0]) not in global_sent and cand[0] not in global_sent
            ]
            total_collected += len(new_items)

            # ══════════════════════════════════════════════════════════════
            # المرحلة C: تنقية + AI (بدون أي قفل)
            # ══════════════════════════════════════════════════════════════
            # AI تنظيف قنوات تيليغرام — مع ميزانية زمنية (60 ث)
            _ai_budget_ok = (time.time() - _broadcast_lock_ts[0]) < 60
            cleaned = []
            for (lnk, ttl, src, summ, pdt) in new_items:
                try:
                    if src.startswith('t.me/') and _ai_budget_ok:
                        clean_ttl = _ai_clean_news(ttl, link=lnk)
                        if not clean_ttl or len(clean_ttl) < 15:
                            continue
                        cleaned.append((lnk, clean_ttl, src, summ, pdt))
                    elif src.startswith('t.me/'):
                        import re as _r2
                        _t = _r2.sub(r'@\S+|#\S+|https?://\S+', '', ttl).strip()
                        if _t and len(_t) >= 15:
                            cleaned.append((lnk, _t, src, summ, pdt))
                    else:
                        cleaned.append((lnk, ttl, src, summ, pdt))
                except Exception:
                    cleaned.append((lnk, ttl, src, summ, pdt))
            new_items = cleaned

            # فلتر اللغة
            new_items = [item for item in new_items if _title_in_lang(item[1], lang)]
            # إزالة التكرار الذكي
            new_items = _dedup_news_list(new_items)
            # AI تلخيص أخبار RSS (أول 5 فقط لمنع التجميد)
            if _AI_AVAILABLE and new_items:
                ai_items = []
                _ai_used = 0
                for (lnk, ttl, src, summ, pdt) in new_items:
                    try:
                        if not src.startswith('t.me/' ) and _ai_used < 2 and summ and len(summ) > 50:
                            clean = _ai_clean_news(ttl, body=summ[:600], link=lnk)
                            _ai_used += 1
                            # إذا أعاد AI قيمة None أو فارغة → استخدم العنوان الأصلي
                            if not clean:
                                clean = ttl
                        else:
                            clean = ttl
                        # تأكيد أخير: العنوان لا يكون None أبداً
                        if not clean:
                            continue
                        ai_items.append((lnk, clean, src, summ, pdt))
                    except Exception:
                        ai_items.append((lnk, ttl, src, summ, pdt))
                new_items = ai_items

            # ══════════════════════════════════════════════════════════════
            # المرحلة D: تسجيل الأخبار الجديدة فعلاً في global_sent (للإحصاء فقط)
            # ══════════════════════════════════════════════════════════════
            if new_items:
                with _global_sent_lock:
                    global_sent = _global_sent_news.setdefault(lang, set())
                    # نُضيف الرابط المُطبَّع (بدون معاملات URL) لمنع التكرار بروابط مختلفة
                    for (lnk, *_rest) in new_items:
                        global_sent.add(_normalize_news_link(lnk) or lnk)

            new_items_by_lang[lang] = new_items
            if new_items:
                _logger.info("📥 [%s] %d خبر طازج جاهز للإرسال", lang[:15], len(new_items))
            else:
                _logger.debug("📭 [%s] لا أخبار طازجة", lang[:15])

        total_new = sum(len(v) for v in new_items_by_lang.values())
        _logger.info("📊 broadcast_news: إجمالي الأخبار الجديدة = %d عبر %d لغة", total_new, len(new_items_by_lang))

        # حفظ التتبع العالمي بعد جمع الأخبار
        _save_global_sent_news()
        # تسجيل الأخبار للملخص الأسبوعي
        for _lang, _items in new_items_by_lang.items():
            for _link, _title, _feed, _sum, _pdt in _items:
                try:
                    _record_weekly_news(_title, _link, _lang)
                except Exception:
                    pass
        # فحص القصص المتابَعة وإرسال تنبيهات
        try:
            _check_followed_stories(new_items_by_lang)
        except Exception:
            pass
        # الخطوة 2: إرسال الأخبار الجديدة لكل مستخدم حسب لغته
        users_reached_this_cycle = 0
        news_sent_this_cycle = 0
        now = _now_sa()
        for uid, info in list(users.items()):
            try:
                if int(uid) in banned:
                    continue
                if not info.get("notifications", True):
                    continue
                # فحص الإيقاف المؤقت للمستخدم
                paused_until = info.get("news_paused_until")
                if paused_until:
                    try:
                        if datetime.datetime.fromisoformat(paused_until) > now:
                            continue
                        else:
                            users[str(uid)].pop("news_paused_until", None)
                    except Exception:
                        pass
                lang = info.get("lang")
                if not lang:
                    continue
                # المستخدمون يحصلون على كل الأخبار الطازجة (all_fresh)
                # ويُفلترون فقط بـ user_sent الشخصي — بهذا لا يُحرمون من أخبار القنوات
                items = all_fresh_by_lang.get(lang, [])
                if not items:
                    continue
                user_interests = info.get("interests", [])
                digest_mode   = info.get("digest_mode", False)
                # جدول مخصص: لا نرسل خارج الساعات المطلوبة (الأخبار العاجلة تُرسل دائماً)
                custom_sched  = info.get("custom_schedule", [])
                current_hour  = _now_sa().hour
                in_sched_window = (not custom_sched) or (current_hour in custom_sched)
                sent_to_user  = 0
                digest_lines  = []
                for link, title, feed_url, item_sum, pub_dt in items:
                    if sent_to_user >= MAX_NEWS_PER_USER_CYCLE:
                        break
                    # الجدول المخصص: تجاوز غير العاجلة خارج ساعات المستخدم
                    if not in_sched_window and _news_importance_score(title) < 2:
                        continue
                    # فلترة الاهتمامات (لكل المستخدمين)
                    if user_interests and not news_matches_interests(title, user_interests):
                        continue
                    # مستوى التنبيه
                    if not _passes_alert_level(title, uid):
                        continue
                    # فحص عدم إرسال هذا الخبر سابقاً لهذا المستخدم
                    # نتأكد دائماً أن user_sent هو set وليس list (من تحميل DB)
                    _raw_sent = info.get("sent_news", set())
                    if not isinstance(_raw_sent, set):
                        _raw_sent = set(_raw_sent)
                        info["sent_news"] = _raw_sent
                    user_sent = _raw_sent
                    # تطبيع الرابط لمنع التكرار حتى لو تغيرت معاملات URL
                    link_key  = _normalize_news_link(link) if link else title[:80]
                    title_key = title.strip()[:70]  # لمنع إرسال نفس الخبر من مصدرين مختلفين
                    if link_key in user_sent or title_key in user_sent:
                        continue
                    # إضافة إيموجي المشاعر للعنوان
                    s_emoji = _sentiment_emoji(title)
                    display_title = f"{s_emoji} {title}" if s_emoji else title
                    src_name = get_source_name_from_url(feed_url)
                    # وقت النشر الفعلي من المصدر — بلغة المستخدم
                    pub_time_str = _format_pub_time(pub_dt, lang=lang)
                    if digest_mode:
                        # جمع الأخبار لإرسالها كرسالة واحدة
                        imp = _news_importance_score(title)
                        bullet = "🚨" if imp >= 2 else ("⚡" if imp == 1 else "•")
                        time_suffix = f" _{pub_time_str}_" if pub_time_str else ""
                        digest_lines.append(f"{bullet} [{display_title}]({link}){time_suffix}")
                    else:
                        markup = make_news_share_markup(link, title, lang, item_sum)
                        # استخدام تسمية "عاجل" للأخبار المهمة — نفس جودة القنوات
                        imp_score = _news_importance_score(title)
                        if imp_score >= 2:
                            news_label = t(lang, "label_breaking") or "🚨 عاجل"
                        elif imp_score == 1:
                            news_label = "⚡ " + _LABEL_LATEST.get(lang, "مهم")
                        else:
                            news_label = _LABEL_LATEST.get(lang, "آخر الأخبار")
                        queue_send(uid, format_news_item(news_label, display_title, lang, src_name, pub_time_str, summary=item_sum),
                            parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)
                    sent_to_user += 1
                    news_sent_this_cycle += 1
                    # ─── أرشفة الخبر (مرة واحدة فقط لكل رابط) ─────────────
                    _arc_key = link_key
                    if _arc_key not in broadcast_news._archived_this_cycle:
                        broadcast_news._archived_this_cycle.add(_arc_key)
                        threading.Thread(
                            target=_archive_news_item,
                            args=(title, link, feed_url[:60], lang, item_sum or ""),
                            daemon=True
                        ).start()
                    # تسجيل الخبر كمُرسَل لهذا المستخدم (رابط + عنوان)
                    user_sent.add(link_key)
                    user_sent.add(title_key)
                    if len(user_sent) > 6000:
                        info["sent_news"] = set(list(user_sent)[-6000:])
                    # تحديث إحصائيات المستخدم الشخصية
                    users[str(uid)]["total_news_received"] = users[str(uid)].get("total_news_received", 0) + 1
                # تحديث streak ويوم النشاط
                if sent_to_user > 0:
                    today_str = str(datetime.date.today())
                    last_day = users[str(uid)].get("last_active_day", "")
                    if last_day != today_str:
                        yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
                        if last_day == yesterday:
                            users[str(uid)]["reading_streak"] = users[str(uid)].get("reading_streak", 0) + 1
                        else:
                            users[str(uid)]["reading_streak"] = 1
                        users[str(uid)]["last_active_day"] = today_str
                        users[str(uid)]["last_active"] = today_str
                # إرسال رسالة الدايجست الواحدة
                if digest_mode and digest_lines:
                    now_str = _now_sa().strftime("%H:%M")
                    digest_msg = f"📰 *نشرة أخبار — {now_str}*\n━━━━━━━━━━━━━━\n" + "\n".join(digest_lines)
                    if len(digest_msg) > 4096:
                        digest_msg = digest_msg[:4080] + "\n…"
                    queue_send(uid, digest_msg, parse_mode="Markdown", disable_web_page_preview=True)
                if sent_to_user > 0:
                    users_reached_this_cycle += 1
            except Exception:
                continue
        _record_broadcast_stat(users_reached=users_reached_this_cycle, news_count=news_sent_this_cycle)
        _logger.info(
            "✅ broadcast_news انتهت: أرسلت %d خبر لـ %d مستخدم",
            news_sent_this_cycle, users_reached_this_cycle
        )
        # ─── وضع علامة لحفظ user_sent في أقرب فرصة ─────────────────
        # (الحفظ الفعلي يتم كل 3 دقائق بالجدولة — لا نفتح thread جديد هنا)
        if news_sent_this_cycle > 0:
            broadcast_news._needs_save = True

        # ─── تشخيص ذكي: إذا لم يُرسَل أي خبر منذ 5 دورات — أخبر الأدمن ─────
        if not hasattr(broadcast_news, '_empty_cycles'):
            broadcast_news._empty_cycles = 0
        if news_sent_this_cycle == 0:
            broadcast_news._empty_cycles += 1
            # أرسل تحذيراً كل 20 دورة فارغة متتالية (≈10 دقائق)
            if broadcast_news._empty_cycles == 20:
                total_items_found = sum(len(v) for v in new_items_by_lang.values())
                active_u = sum(1 for i in users.values() if i.get("notifications", True) and i.get("lang"))
                reasons = []
                if not users:
                    reasons.append("❌ لا مستخدمين مسجّلين — أرسل /start لتفعيل الاشتراك")
                elif active_u == 0:
                    reasons.append("❌ كل المستخدمين لا يملكون لغة محددة")
                if total_items_found == 0:
                    reasons.append("❌ لم تجد دورة البث أي أخبار جديدة (كلها في global_sent)")
                if bot_paused:
                    reasons.append("❌ البوت متوقف كلياً (bot_paused=True)")
                if broadcast_paused:
                    reasons.append("❌ البث متوقف (broadcast_paused=True) — اضغط 📡 تشغيل البث في /admin")
                diag = "\n".join(reasons) if reasons else "⚠️ سبب غير معروف — جرّب /debugnews"
                try:
                    bot.send_message(ADMIN_ID,
                        f"⚠️ *تحذير: لم يُرسَل أي خبر منذ ~10 دقائق*\n\n"
                        f"{diag}\n\n"
                        f"👥 مستخدمون: {len(users)} (فعّال: {active_u})\n"
                        f"📰 أخبار في الدورة: {total_items_found}\n\n"
                        f"🔧 أوامر التشخيص: /debugnews | /clearcache | /forcenews",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        else:
            broadcast_news._empty_cycles = 0

        # ══════════════════════════════════════════════════════════════════
        # الخطوة 3: بث القنوات والمجموعات — نفس الأخبار، نفس الوقت تماماً!
        # (القنوات ذات المصادر المخصصة تُعالَج بواسطة broadcast_to_channels)
        # ══════════════════════════════════════════════════════════════════
        ch_changed = False
        for ch in list(channels_groups):
            try:
                if ch.get('paused'):
                    continue
                # القنوات بمصادر مخصصة → broadcast_to_channels تتكفل بها
                if ch.get('custom_sources'):
                    continue
                chat_id = ch["id"]
                lang    = ch.get('lang', 'العربية 🇮🇶')
                items   = new_items_by_lang.get(lang, [])
                if not items:
                    continue
                ch_sent = set(ch.get('sent_news', []))
                sent_this_ch = 0
                for (lnk, ttl, src, summ, pdt) in items:
                    if sent_this_ch >= MAX_NEWS_PER_BROADCAST:
                        break
                    # تطبيع الرابط لمنع التكرار بسبب معاملات URL المتغيرة
                    norm_lnk  = _normalize_news_link(lnk)
                    title_key = ttl.strip()[:70]
                    if norm_lnk in ch_sent or title_key in ch_sent:
                        continue
                    try:
                        src_name     = get_source_name_from_url(src)
                        pub_time_str = _format_pub_time(pdt, lang=lang)
                        s_emoji      = _sentiment_emoji(ttl)
                        display_ttl  = f"{s_emoji} {ttl}" if s_emoji else ttl
                        markup       = make_news_share_markup(lnk, ttl, lang, summ)
                        latest_label = _LABEL_LATEST.get(lang, "آخر الأخبار")
                        news_text    = format_news_item(
                            latest_label, display_ttl, lang,
                            src_name, pub_time_str, summary=summ
                        )
                        # إرسال مع صورة إن وُجدت (للقنوات فقط)
                        img_sent = False
                        if ch.get('type') == 'channel' and _should_send_with_image(ttl):
                            try:
                                img_url = _get_og_image(lnk, timeout=4)
                                if img_url:
                                    bot.send_photo(chat_id, img_url,
                                                   caption=news_text[:1024],
                                                   parse_mode="Markdown",
                                                   reply_markup=markup)
                                    img_sent = True
                            except Exception:
                                pass
                        if not img_sent:
                            queue_send(chat_id, news_text, parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)
                        # تسجيل الرابط المُطبَّع والعنوان لمنع إعادة الإرسال
                        ch_sent.add(norm_lnk)
                        ch_sent.add(title_key)
                        if lnk != norm_lnk:
                            ch_sent.add(lnk)  # الرابط الأصلي أيضاً للتوافق
                        sent_this_ch += 1
                        ch["news_sent_count"] = ch.get("news_sent_count", 0) + 1
                        time.sleep(0.05)
                    except Exception as send_e:
                        err_s = str(send_e).lower()
                        if any(x in err_s for x in ("kicked", "chat not found", "not a member", "forbidden")):
                            break
                        time.sleep(0.3)
                if sent_this_ch > 0:
                    ch['sent_news'] = list(ch_sent)[-3000:]
                    ch_changed = True
            except Exception:
                continue
        if ch_changed:
            save_channels_groups()

    except Exception as e:
        _record_broadcast_error(f"broadcast_news: {e}")
        _track_error("broadcast_news", e)
        try:
            bot.send_message(ADMIN_ID, f"⚠️ خطأ في broadcast_news: {e}")
        except Exception:
            pass
    finally:
        _broadcast_news_lock.clear()   # تحرير القفل دائماً حتى عند الاستثناء

def send_sports_news(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = SPORTS_RSS.get(lang, SPORTS_RSS.get("English 🇬🇧", []))
    if not feeds:
        bot.send_message(uid, t(lang, "no_sports_source"))
        return
    sent = user.setdefault("sent_news", set())
    count = 0
    bot.send_message(uid, t(lang, "sports_header"), parse_mode="Markdown")
    for feed_url in feeds:
        try:
            feed = _parse_feed(feed_url)
            if feed is None:
                feed = feedparser.parse(feed_url)
            if not feed:
                continue
            for item in feed.entries[:5]:
                if not hasattr(item, 'link') or item.link in sent:
                    continue
                sent.add(item.link)
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                markup = make_news_share_markup(item.link, getattr(item, 'title', ''), lang, item_sum)
                src_name = get_source_name_from_feed(feed, feed_url)
                title_s = getattr(item, 'title', '').strip()
                pub_time_str = _format_pub_time(_pub_dt_from_item(item), lang=lang)
                bot.send_message(uid, format_news_item(t(lang, "label_sports"), title_s, lang, src_name, pub_time_str, summary=item_sum), parse_mode="Markdown", reply_markup=markup)
                count += 1
                if count >= 8:
                    break
        except Exception:
            pass  # فشل مصدر رياضي لا يوقف باقي المصادر
        if count >= 8:
            break
    if count == 0:
        bot.send_message(uid, t(lang, "no_sports"))
    else:
        _db_save_all_users(users)

# ======== محوّل العملات ========
CURRENCY_SYMBOLS = {
    "USD": "🇺🇸 دولار أمريكي",
    "EUR": "🇪🇺 يورو",
    "GBP": "🇬🇧 جنيه إسترليني",
    "IQD": "🇮🇶 دينار عراقي",
    "SAR": "🇸🇦 ريال سعودي",
    "AED": "🇦🇪 درهم إماراتي",
    "TRY": "🇹🇷 ليرة تركية",
    "IRR": "🇮🇷 ريال إيراني",
    "KWD": "🇰🇼 دينار كويتي",
    "JOD": "🇯🇴 دينار أردني",
    "EGP": "🇪🇬 جنيه مصري",
    "RUB": "🇷🇺 روبل روسي",
    "CNY": "🇨🇳 يوان صيني",
    "INR": "🇮🇳 روبية هندية",
}

def convert_currency_msg(uid, amount, from_currency):
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
        r = requests.get(url, timeout=10).json()
        rates = r.get("rates", {})
        if not rates:
            bot.send_message(uid, f"⚠️ عملة غير مدعومة: {from_currency}")
            return
        targets = ["USD", "EUR", "IQD", "SAR", "AED", "GBP", "TRY", "KWD", "EGP", "RUB"]
        msg = f"🔄 *تحويل {amount:,.2f} {from_currency}*\n━━━━━━━━━━━━━━━\n\n"
        for t in targets:
            if t == from_currency:
                continue
            rate = rates.get(t)
            if rate:
                converted = amount * rate
                label = CURRENCY_SYMBOLS.get(t, t)
                msg += f"{label}: *{converted:,.2f}*\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, "⚠️ لا يمكن جلب أسعار الصرف الآن.")
        notify_admin_error(f"خطأ في محوّل العملات: {e}")

# ======== إحصائيات المستخدم الشخصية ========
def send_my_stats(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    name = user.get("name", t(lang, "my_stats_user"))
    province = user.get("province", "—")
    sent_news = user.get("sent_news", set())
    referrals = user.get("referrals", [])
    is_prem = t(lang, "my_stats_prem_yes") if is_premium(uid) else t(lang, "my_stats_prem_no")
    notif = t(lang, "my_stats_notif_on") if user.get("notifications", True) else t(lang, "my_stats_notif_off")
    join_date = user.get("join_date", "—")
    kws = user_keywords.get(str(uid), [])
    msg = t(lang, "my_stats_header").format(
        name=name, lang=lang, city=province, join=join_date,
        news=len(sent_news), refs=len(referrals), kws=len(kws),
        prem=is_prem, notif=notif
    )
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== توقعات 3 أيام (مجانية) ========
def send_3day_forecast(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    lang_code = LANG_CODES.get(lang, "en")
    province = user.get("province", "")
    if not province:
        bot.send_message(uid, t(lang, "no_city"))
        return
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={province}&appid={WEATHER_KEY}&units=metric&lang={lang_code}&cnt=24"
        data = requests.get(url, timeout=10).json()
        if str(data.get("cod")) != "200":
            bot.send_message(uid, t(lang, "city_not_found").format(city=province))
            return
        days = {}
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            if date not in days:
                days[date] = {"temps": [], "descs": [], "icons": []}
            days[date]["temps"].append(item["main"]["temp"])
            days[date]["descs"].append(item["weather"][0]["description"])
            days[date]["icons"].append(item["weather"][0]["id"])
        msg = t(lang, "forecast_3day_header").format(city=province)
        day_names = list(days.items())[:3]
        for date, info in day_names:
            min_t = round(min(info["temps"]))
            max_t = round(max(info["temps"]))
            desc = info["descs"][len(info["descs"])//2]
            icon = get_weather_emoji(info["icons"][len(info["icons"])//2])
            msg += f"{icon} *{date}*\n"
            msg += f"   🌡 {min_t}°C — {max_t}°C\n"
            msg += f"   ☁️ {desc.capitalize()}\n\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "weather_error"))
        notify_admin_error(f"خطأ في توقعات 3 أيام لـ {uid}: {e}")

# ======== ترتيب أفضل الداعين ========
def send_top_referrers(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    referral_counts = []
    for user_id, info in users.items():
        refs = info.get("referrals", [])
        if refs:
            name = info.get("name", t(lang, "my_stats_user"))
            referral_counts.append((name, len(refs)))
    referral_counts.sort(key=lambda x: x[1], reverse=True)
    top = referral_counts[:10]
    if not top:
        bot.send_message(uid, t(lang, "top_referrers_empty"))
        return
    medals = ["🥇", "🥈", "🥉"] + ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    invite_word = t(lang, "top_referrers_invite")
    msg = t(lang, "top_referrers_header")
    for i, (name, count) in enumerate(top):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        msg += f"{medal} *{name}* — {count} {invite_word}\n"
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== تنظيف البيانات التلقائي (Auto-Clean) ========
def auto_clean_sent_news():
    """
    تنظيف دوري لسجل الأخبار المُرسَلة لكل مستخدم.
    الحد = 8000 مدخل (4000 خبر × 2 مدخل: رابط + عنوان).
    هذا يغطي 24+ ساعة من الأخبار دون حذف القديمة قبل الأوان.
    """
    cleaned = 0
    for uid, info in users.items():
        sent = info.get("sent_news", set())
        if isinstance(sent, list):
            sent = set(sent)
        # حد آمن: 8000 مدخل = 4000 خبر (رابط + عنوان لكل خبر)
        if len(sent) > 8000:
            sent_list = list(sent)
            users[uid]["sent_news"] = set(sent_list[-8000:])
            cleaned += 1
    if cleaned > 0:
        _db_save_all_users(users)
        _logger.info(f"✅ Auto-Clean: تم تنظيف sent_news لـ {cleaned} مستخدم")

# ======== فحص الكلمات المفتاحية للمميزين ========
def check_keyword_alerts():
    if bot_paused: return
    for uid, keywords in list(user_keywords.items()):
        if not keywords:
            continue
        if int(uid) in banned:
            continue
        user = users.get(uid)
        if not user:
            continue
        lang = user.get("lang", "English 🇬🇧")
        feeds = RSS.get(lang, [])
        sent = user.setdefault("sent_news", set())
        for feed_url in feeds:
            try:
                feed = _parse_feed(feed_url)
                if feed is None:
                    feed = feedparser.parse(feed_url)
                if not feed:
                    continue
                for item in feed.entries[:5]:
                    if not hasattr(item, 'link') or item.link in sent:
                        continue
                    title = getattr(item, 'title', '')
                    title_lower = title.lower()
                    matched_kw = None
                    for kw in keywords:
                        if kw.lower() in title_lower:
                            matched_kw = kw
                            break
                    if matched_kw:
                        sent.add(item.link)
                        queue_send(
                            uid,
                            _ul(lang, "keyword_alert", kw=escape_md(matched_kw), title=escape_md(title)) + BOT_SIGNATURE,
                            parse_mode="Markdown"
                        )
            except Exception as e:
                notify_admin_error(f"خطأ في فحص الكلمات المفتاحية: {e}")
    _db_save_all_users(users)

# ======== الجدولة ========

# ======== ملخص أخبار اليوم ========
def send_daily_summary(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    headlines = []
    for feed_url in feeds[:3]:
        try:
            feed = _parse_feed(feed_url)
            if feed is None:
                feed = feedparser.parse(feed_url)
            if not feed:
                continue
            for item in feed.entries[:5]:
                if hasattr(item, 'title') and item.title:
                    headlines.append(item.title)
            if len(headlines) >= 15:
                break
        except Exception:
            pass  # فشل مصدر واحد لا يوقف باقي المصادر
    if not headlines:
        bot.send_message(uid, t(lang, "no_news"))
        return
    today = datetime.date.today().strftime("%Y-%m-%d")
    msg = t(lang, "daily_summary_header").format(date=today)
    for i, title in enumerate(headlines[:10], 1):
        msg += f"{i}. {title}\n\n"
    msg += f"━━━━━━━━━━━━━━━\n{BOT_SIGNATURE}"
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== أسعار العملات الرقمية ========
def send_crypto_prices(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether,binancecoin,solana,ripple,dogecoin,cardano,tron,litecoin,the-open-network,notcoin,pepe,dogwifcoin,bittensor&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=10).json()
        crypto_names = {
            "bitcoin":          ("₿ Bitcoin",  "BTC"),
            "ethereum":         ("⟠ Ethereum", "ETH"),
            "tether":           ("💵 Tether",   "USDT"),
            "binancecoin":      ("🟡 BNB",      "BNB"),
            "solana":           ("◎ Solana",    "SOL"),
            "ripple":           ("〇 XRP",       "XRP"),
            "dogecoin":         ("🐶 Dogecoin", "DOGE"),
            "cardano":          ("🔵 Cardano",  "ADA"),
            "tron":             ("🔴 TRON",     "TRX"),
            "litecoin":         ("🥈 Litecoin", "LTC"),
            "the-open-network": ("💎 TON",      "TON"),
            "notcoin":          ("🎮 NOT",      "NOT"),
            "pepe":             ("🐸 PEPE",     "PEPE"),
            "dogwifcoin":       ("🐕 WIF",      "WIF"),
            "bittensor":        ("🧠 TAO",      "TAO"),
        }
        msg = t(lang, "crypto_header")
        for coin_id, (name, symbol) in crypto_names.items():
            data = r.get(coin_id, {})
            price = data.get("usd", "—")
            change = data.get("usd_24h_change", None)
            if isinstance(price, (int, float)):
                price_str = f"${price:,.6f}" if price < 0.01 else (f"${price:,.4f}" if price < 1 else f"${price:,.2f}")
            else:
                price_str = "—"
            if change is not None:
                arrow = "📈" if change >= 0 else "📉"
                change_str = f"{arrow} {change:+.2f}%"
            else:
                change_str = ""
            msg += f"{name} ({symbol})\n   💲 {price_str}  {change_str}\n\n"
        msg += t(lang, "crypto_footer")
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "crypto_error"))
        notify_admin_error(f"خطأ في أسعار الكريبتو: {e}")

# ======== أوقات الصلاة ========
def send_prayer_times(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    province = user.get("province", "")
    if not province:
        bot.send_message(uid, t(lang, "prayer_no_city"))
        return
    try:
        today = datetime.date.today()
        url = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=IQ&method=4&date={today}"
        r = requests.get(url, timeout=10).json()
        if r.get("code") != 200:
            url2 = f"https://api.aladhan.com/v1/timingsByCity?city={province}&country=&method=4&date={today}"
            r = requests.get(url2, timeout=10).json()
        if r.get("code") != 200:
            bot.send_message(uid, t(lang, "prayer_city_error").format(city=province))
            return
        timings = r["data"]["timings"]
        date_info = r["data"]["date"]["readable"]
        hijri = r["data"]["date"]["hijri"]
        hijri_str = f"{hijri['day']} {hijri['month']['ar']} {hijri['year']} هـ"
        msg = t(lang, "prayer_header").format(
            city=province, date=date_info, hijri=hijri_str,
            fajr=timings['Fajr'], sunrise=timings['Sunrise'],
            dhuhr=timings['Dhuhr'], asr=timings['Asr'],
            maghrib=timings['Maghrib'], isha=timings['Isha']
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(uid, t(lang, "prayer_error"))
        notify_admin_error(f"خطأ في أوقات الصلاة لـ {uid}: {e}")

# ======== إحصائيات الدعوات (رابط الدعوة) ========
def send_referral_stats(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "العربية 🇮🇶")
    ref_count = len(user.get("referrals", []))
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    msg = st(lang, "referral_header").format(link=invite_link, count=ref_count)
    markup = types.InlineKeyboardMarkup()
    share_url = f"https://t.me/share/url?url={invite_link}&text=📱 @{BOT_USERNAME}"
    markup.add(types.InlineKeyboardButton(st(lang, "referral_share_btn"), url=share_url))
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

# ======== انشر البوت ========
def send_share_bot(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    invite_link = f"https://t.me/{BOT_USERNAME}"
    msg = t(lang, "share_bot_header").format(username=BOT_USERNAME, link=invite_link)
    markup = types.InlineKeyboardMarkup()
    share_url = f"https://t.me/share/url?url={invite_link}&text=@{BOT_USERNAME}"
    markup.add(
        types.InlineKeyboardButton(t(lang, "share_bot_btn"), url=share_url),
        types.InlineKeyboardButton(t(lang, "open_bot_btn"), url=invite_link)
    )
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)

# ======== إحصائيات البوت العامة ========
def send_public_stats(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    total = stats.get("total_users", len(users))
    today = str(datetime.date.today())
    today_count = stats.get("daily_users", {}).get(today, 0)
    active = sum(1 for u in users.values() if "province" in u)
    premium_count = len(stats.get("premium_users", []))
    top_langs = sorted(stats.get("languages_count", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    msg = t(lang, "public_stats_header").format(
        total=total, active=active, today=today_count, premium=premium_count
    )
    if top_langs:
        msg += t(lang, "public_stats_langs")
        for lang_name, count in top_langs:
            msg += f"  • {lang_name}: {count}\n"
    msg += t(lang, "public_stats_footer").format(username=BOT_USERNAME)
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== دولار السوق الموازية ========
def send_dollar_parallel(uid):
    user = users.get(str(uid))
    lang = user.get("lang", "English 🇬🇧") if user else "English 🇬🇧"
    now_str = _now_sa().strftime("%H:%M - %d/%m/%Y")

    # ─── المستخدمون العراقيون: مصدر @dollariraqi الحصري ─────────────
    if _is_iraqi_user(uid):
        wait_msg = bot.send_message(uid,
            "⏳ جاري جلب أسعار السوق الآن...", parse_mode="Markdown")
        market_text = _fetch_dollariraqi_market()
        try:
            bot.delete_message(uid, wait_msg.message_id)
        except Exception:
            pass
        if market_text:
            msg = (
                f"💵 *أسعار دولار السوق*\n"
                f"🕐 `{now_str}`\n"
                f"━━━━━━━━━━━━━━\n"
                f"{market_text}\n"
                f"━━━━━━━━━━━━━━\n"
                f"📡 _المصدر: @dollariraqi_\n"
                f"🤖 @{BOT_USERNAME}"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "🔄 تحديث الآن", callback_data="refresh_dollar_iraqi"
            ))
            markup.add(types.InlineKeyboardButton(
                "📢 قناة @dollariraqi", url="https://t.me/dollariraqi"
            ))
            bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)
            return
        else:
            # فشل الجلب — fallback للـ API العادي
            bot.send_message(uid,
                "⚠️ تعذر جلب أسعار @dollariraqi، جاري استخدام المصدر البديل...")

    # ─── المستخدمون غير العراقيين: API عالمي ────────────────────────
    rate = None
    source_note = ""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://dolarsoft.com/api/v1/price", headers=headers, timeout=8)
        data = r.json()
        sell = data.get("sell") or data.get("price") or data.get("usd_sell")
        buy  = data.get("buy") or data.get("usd_buy")
        if sell:
            rate = f"{t(lang, 'dollar_sell')}: `{sell}` IQD\n{t(lang, 'dollar_buy')}: `{buy or '-'}` IQD"
            source_note = "dolarsoft.com"
    except Exception:
        pass
    if not rate:
        try:
            r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
            iqd = r.json().get("rates", {}).get("IQD", None)
            if iqd:
                rate = t(lang, "dollar_official").format(price=f"{int(iqd):,}")
                source_note = "exchangerate-api.com"
        except Exception:
            pass
    if not rate:
        bot.send_message(uid, t(lang, "dollar_error"))
        return
    msg = t(lang, "dollar_header").format(
        rate=rate, time=now_str, source=source_note, username=BOT_USERNAME)
    bot.send_message(uid, msg, parse_mode="Markdown")

# ======== ملخص أسبوعي نصي ========
def send_weekly_summary_text(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    if not feeds:
        bot.send_message(uid, t(lang, "no_source"))
        return
    bot.send_message(uid, t(lang, "weekly_summary_text_wait"))
    headlines = []
    seen_titles = set()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    for feed_url in feeds[:6]:
        try:
            feed = _parse_feed(feed_url)
            if feed is None:
                feed = feedparser.parse(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:8]:
                title = getattr(entry, "title", "").strip()
                if not title or title in seen_titles:
                    continue
                pub = getattr(entry, "published_parsed", None)
                if pub:
                    try:
                        pub_dt = datetime.datetime(*pub[:6])
                        if pub_dt < cutoff:
                            continue
                    except:
                        pass
                seen_titles.add(title)
                headlines.append(title)
                if len(headlines) >= 25:
                    break
        except:
            continue
        if len(headlines) >= 25:
            break
    if not headlines:
        bot.send_message(uid, t(lang, "no_weekly"))
        return
    week_start = (_now_sa() - datetime.timedelta(days=6)).strftime("%d/%m")
    week_end = _now_sa().strftime("%d/%m/%Y")
    lines = [t(lang, "weekly_summary_text_header").format(start=week_start, end=week_end)]
    for i, title in enumerate(headlines, 1):
        lines.append(f"{i}. {title}")
    lines.append(t(lang, "public_stats_footer").format(username=BOT_USERNAME))
    full_msg = "\n".join(lines)
    if len(full_msg) > 4000:
        full_msg = full_msg[:3990] + "\n..."
    bot.send_message(uid, full_msg, parse_mode="Markdown")

# ======== تتبع العملات والأسهم والسلع والمؤشرات ========
CRYPTO_IDS = {
    # العملات الرئيسية
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "XRP": "ripple",
    "ADA": "cardano",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "AVAX": "avalanche-2",
    "SHIB": "shiba-inu",
    "TRX": "tron",
    "LINK": "chainlink",
    "TON": "the-open-network",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ALGO": "algorand",
    "VET": "vechain",
    "FIL": "filecoin",
    "HBAR": "hedera-hashgraph",
    "ICP": "internet-computer",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "MKR": "maker",
    "AAVE": "aave",
    "CRV": "curve-dao-token",
    "FTM": "fantom",
    "NEAR": "near",
    "SUI": "sui",
    "SEI": "sei-network",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "BONK": "bonk",
    "FLOKI": "floki",
    "NOT": "notcoin",
    "DOGS": "dogs-coin",
    "HMSTR": "hamster-kombat",
    "TAO": "bittensor",
    "RENDER": "render-token",
    "INJ": "injective-protocol",
    "PYTH": "pyth-network",
    "JUP": "jupiter-exchange-solana",
    "POPCAT": "popcat",
    "BRETT": "based-brett",
    "TRUMP": "maga",
    "PENGU": "pudgy-penguins",
    "LUNA": "terra-luna-2",
    "SAND": "the-sandbox",
    "APE": "apecoin",
    "MANA": "decentraland",
    "CRO": "crypto-com-chain",
}

FIAT_CURRENCIES = {
    "USD", "EUR", "GBP", "IQD", "SAR", "AED", "TRY",
    "JPY", "CNY", "KWD", "EGP", "JOD", "IRR", "PKR",
    "INR", "BRL", "RUB", "MXN", "CAD", "AUD", "CHF",
    "SEK", "NOK", "DKK", "SGD", "HKD", "QAR", "BHD",
    "OMR", "MAD", "TND", "DZD", "LYD", "SYP", "YER",
    "UAH", "PLN", "CZK", "HUF", "RON", "IDR", "MYR",
    "THB", "PHP", "VND", "ZAR", "NGN",
}

# أسهم شهيرة وسلع — تُجلب من Yahoo Finance
YAHOO_SYMBOLS = {
    # أسهم التكنولوجيا الكبرى
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Google",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "META": "Meta",
    "TSLA": "Tesla",
    "AMD": "AMD",
    "INTC": "Intel",
    "NFLX": "Netflix",
    "ORCL": "Oracle",
    "IBM": "IBM",
    "QCOM": "Qualcomm",
    "AVGO": "Broadcom",
    "CRM": "Salesforce",
    # أسهم أخرى
    "JPM": "JPMorgan",
    "BAC": "Bank of America",
    "WMT": "Walmart",
    "KO": "Coca-Cola",
    "PEP": "PepsiCo",
    "DIS": "Disney",
    "BABA": "Alibaba",
    "TSM": "TSMC",
    "NKE": "Nike",
    "PYPL": "PayPal",
    "UBER": "Uber",
    "SPOT": "Spotify",
    "SNAP": "Snap",
    "X": "X (Twitter)",
    "COIN": "Coinbase",
    "HOOD": "Robinhood",
    "ADBE": "Adobe",
    "CSCO": "Cisco",
    # بنوك ومالية
    "GS": "Goldman Sachs",
    "MS": "Morgan Stanley",
    "WFC": "Wells Fargo",
    "C": "Citigroup",
    "CFG": "Citizens Financial",
    "HSBC": "HSBC",
    "BNP.PA": "BNP Paribas",
    "DBK.DE": "Deutsche Bank",
    "BARC.L": "Barclays",
    # صناعة وطاقة
    "XOM": "ExxonMobil",
    "CVX": "Chevron",
    "BP": "BP",
    "TTE": "TotalEnergies",
    "GE": "GE",
    "BA": "Boeing",
    "CAT": "Caterpillar",
    "SIE.DE": "Siemens",
    "HON": "Honeywell",
    "LMT": "Lockheed Martin",
    # مستهلك وخدمات
    "MCD": "McDonald's",
    "SBUX": "Starbucks",
    "MC.PA": "LVMH",
    "ULVR.L": "Unilever",
    "NESN.SW": "Nestlé",
    "ADS.DE": "Adidas",
    # رعاية صحية
    "PFE": "Pfizer",
    "JNJ": "Johnson & Johnson",
    "MRNA": "Moderna",
    "MRK": "Merck",
    "AZN": "AstraZeneca",
    "LLY": "Eli Lilly",
    "SNY": "Sanofi",
    "NVS": "Novartis",
    "ROG.SW": "Roche",
    # سلع
    "GC=F": "Gold",
    "SI=F": "Silver",
    "CL=F": "Oil (WTI)",
    "BZ=F": "Oil (Brent)",
    "NG=F": "Natural Gas",
    "HG=F": "Copper",
    "PL=F": "Platinum",
    "PA=F": "Palladium",
    # مؤشرات
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^FTSE": "FTSE 100",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
}

def get_asset_label(symbol):
    """اسم وصفي للرمز إن وُجد."""
    if symbol in YAHOO_SYMBOLS:
        return f"{symbol} ({YAHOO_SYMBOLS[symbol]})"
    return symbol

def fetch_asset_price(symbol):
    """جلب سعر أي أصل: عملة رقمية / فيات / سهم / سلعة / مؤشر."""
    if symbol in CRYPTO_IDS:
        try:
            cg_id = CRYPTO_IDS[symbol]
            r = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd",
                timeout=10
            ).json()
            price = r.get(cg_id, {}).get("usd")
            return float(price) if price else None
        except:
            return None
    if symbol in FIAT_CURRENCIES:
        try:
            r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
            rate = r.get("rates", {}).get(symbol)
            return float(rate) if rate else None
        except:
            return None
    # أسهم وسلع ومؤشرات عبر Yahoo Finance
    try:
        encoded = requests.utils.quote(symbol, safe='')
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=1d",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=10
        ).json()
        result = r.get("chart", {}).get("result")
        if result:
            closes = result[0]["indicators"]["quote"][0].get("close", [])
            price = next((p for p in reversed(closes) if p is not None), None)
            return float(price) if price else None
    except:
        pass
    return None

def format_asset_price(symbol, price):
    """تنسيق عرض السعر حسب حجمه."""
    label = get_asset_label(symbol)
    if price is None:
        return f"❓ {label}: غير متوفر"
    if price >= 10000:
        return f"`{label}`: `${price:,.0f}`"
    elif price >= 1:
        return f"`{label}`: `${price:,.2f}`"
    elif price >= 0.0001:
        return f"`{label}`: `${price:.6f}`"
    else:
        return f"`{label}`: `${price:.8f}`"

def start_track_asset(uid):
    user_data = tracked_assets.get(str(uid), {})
    assets = user_data.get("assets", [])
    last_prices = user_data.get("last_prices", {})
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")

    msg = t(lang, "track_header")

    if assets:
        msg += t(lang, "track_current_list")
        for sym in assets:
            p = last_prices.get(sym)
            msg += f"  • {format_asset_price(sym, p)}\n"
        msg += t(lang, "track_count").format(count=len(assets))

    msg += (
        "➕ *لإضافة رمز:* أرسل اسمه مباشرة\n\n"
        "💎 *عملات رقمية (Cryptos):*\n"
        "`BTC` `ETH` `SOL` `BNB` `XRP` `DOGE` `ADA` `MATIC` `LINK` `UNI`\n"
        "`SHIB` `PEPE` `TRX` `TON` `WIF` `BONK` `LUNA` `AVAX` `DOT` `XLM`\n"
        "`FIL` `FTM` `SAND` `APE` `MANA` `CRO` `NEAR` `ALGO` `VET`\n\n"
        "💱 *عملات فيات (Fiat):*\n"
        "`USD` `EUR` `GBP` `IQD` `SAR` `AED` `TRY` `IRR` `KWD` `EGP` `INR` `RUB`\n\n"
        "📈 *أسهم (Stocks):*\n\n"
        "تقنية / تكنولوجيا:\n"
        "`AAPL` `MSFT` `GOOGL` `AMZN` `META` `TSLA` `NVDA` `INTEL` `AMD` `IBM` `CISCO` `ORACLE` `ADOBE` `SALESFORCE`\n\n"
        "بنوك ومالية:\n"
        "`JPM` `BAC` `C` `CFG` `GS` `MS` `WFC` `HSBC` `BARCLAYS` `DEUTSCHE` `CREDITBNP`\n\n"
        "صناعة / طاقة:\n"
        "`XOM` `CVX` `BP` `TOT` `GE` `BOEING` `CAT` `SIEMENS` `HONEYWELL` `LOCKHEED`\n\n"
        "مستهلك / خدمات:\n"
        "`KO` `PEP` `MCD` `SBUX` `WMT` `NKE` `ADS` `LVMH` `UNILEVER` `NESTLE`\n\n"
        "رعاية صحية / أدوية:\n"
        "`PFE` `JNJ` `MRNA` `ROCHE` `NOV` `NVS` `MRK` `AZN` `LLY` `SNY`\n\n"
        "🏅 *سلع ومؤشرات (Commodities & Indices):*\n"
        "`GC=F` (Gold)  `SI=F` (Silver)\n"
        "`CL=F` (WTI)  `BZ=F` (Brent)\n"
        "`^GSPC` (S&P500)  `^IXIC` (NASDAQ)\n\n"
        "🔔 ستصلك تنبيهات فورية عند تغير ±1% وقائمة بأسعارك كل ساعة.\n\n"
        "❌ لحذف رمز: `/removetrack [رمز]`\n"
        "📋 لعرض قائمتك: `/mytrack`"
    )

    user_states[uid] = "tracking_asset"
    bot.send_message(uid, msg, parse_mode="Markdown")

def check_asset_tracking():
    if bot_paused: return
    """يعمل كل ساعة: يرسل تقريراً شاملاً + تنبيهات التغيرات الكبيرة."""
    for uid_str, data in list(tracked_assets.items()):
        assets = data.get("assets", [])
        if not assets:
            continue
        last_prices = data.get("last_prices", {})
        changed = False
        report_lines = []
        alerts = []

        user = users.get(uid_str, {})
        lang = user.get("lang", "English 🇬🇧")

        for symbol in assets:
            try:
                new_price = fetch_asset_price(symbol)
                if new_price is None:
                    report_lines.append(f"❓ {get_asset_label(symbol)}: {t(lang, 'track_unavailable')}")
                    continue
                old_price = last_prices.get(symbol)
                if old_price and old_price > 0:
                    change_pct = ((new_price - old_price) / old_price) * 100
                    arrow = "📈" if change_pct >= 0 else "📉"
                    report_lines.append(
                        f"{arrow} {format_asset_price(symbol, new_price)}  `{change_pct:+.2f}%`"
                    )
                    if abs(change_pct) >= 1.0:
                        direction = t(lang, "track_rose") if change_pct > 0 else t(lang, "track_fell")
                        alerts.append(
                            f"{direction} *{get_asset_label(symbol)}* بنسبة `{change_pct:+.2f}%`\n"
                            f"   السعر: `${new_price:,.4f}` (كان `${old_price:,.4f}`)"
                        )
                else:
                    report_lines.append(f"🔹 {format_asset_price(symbol, new_price)}")
                tracked_assets[uid_str]["last_prices"][symbol] = new_price
                changed = True
            except:
                continue

        if changed:
            save_tracked_assets()

        # إرسال التنبيهات الفورية للتغيرات الكبيرة
        if alerts:
            alert_msg = (
                t(lang, "track_alert_title")
                + "\n\n".join(alerts)
                + f"\n\n🤖 @{BOT_USERNAME}"
            )
            try:
                bot.send_message(int(uid_str), alert_msg, parse_mode="Markdown")
            except:
                pass

        # إرسال التقرير الساعي الشامل
        if report_lines:
            now_str = _now_sa().strftime("%H:%M — %d/%m/%Y")
            report_msg = (
                t(lang, "track_report_title")
                + f"🕐 {now_str}\n"
                f"━━━━━━━━━━━━━━━\n\n"
                + "\n".join(report_lines)
                + f"\n\n━━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}"
            )
            try:
                bot.send_message(int(uid_str), report_msg, parse_mode="Markdown")
            except:
                pass

def _update_user_last_command(uid, command):
    """يحدّث آخر أمر استخدمه المستخدم."""
    uid_str = str(uid)
    if uid_str in users:
        users[uid_str]["last_command"] = command
        users[uid_str]["last_seen"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

@bot.message_handler(commands=["mytrack"])
def cmd_mytrack(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/mytrack")
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if not assets:
        bot.send_message(uid, t(lang, "track_empty"), parse_mode="Markdown")
        return
    last_prices = data.get("last_prices", {})
    msg = t(lang, "track_list_header")
    for sym in assets:
        price = fetch_asset_price(sym)
        if price:
            tracked_assets[str(uid)]["last_prices"][sym] = price
            save_tracked_assets()
        msg += f"• {format_asset_price(sym, price or last_prices.get(sym))}\n"
    msg += f"━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}"
    bot.send_message(uid, msg, parse_mode="Markdown")

@bot.message_handler(commands=["removetrack"])
def cmd_removetrack(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    parts = m.text.strip().split()
    if len(parts) < 2:
        bot.send_message(uid, t(lang, "track_remove_usage"), parse_mode="Markdown")
        return
    symbol = parts[1].upper()
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if symbol not in assets:
        bot.send_message(uid, t(lang, "track_not_found").format(symbol=symbol), parse_mode="Markdown")
        return
    assets.remove(symbol)
    tracked_assets[str(uid)]["assets"] = assets
    tracked_assets[str(uid)]["last_prices"].pop(symbol, None)
    save_tracked_assets()
    bot.send_message(uid, t(lang, "track_removed").format(symbol=symbol), parse_mode="Markdown")

# ======== النسخ الاحتياطي ========
def _build_backup_report():
    """يبني تقرير نصي مفصّل بكل بيانات البوت والمستخدمين."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💾 تقرير النسخة الاحتياطية الشاملة")
    lines.append(f"🕐 التاريخ والوقت: {now}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ── إحصائيات عامة ──
    total_users = len(users)
    premium_list = stats.get("premium_users", [])
    premium_count = len(premium_list)
    banned_count = len(banned)
    lines.append(f"\n📊 إحصائيات عامة:")
    lines.append(f"  👥 إجمالي المستخدمين: {total_users}")
    lines.append(f"  ⭐ المستخدمون المميزون: {premium_count}")
    lines.append(f"  🚫 المحظورون: {banned_count}")
    lines.append(f"  💰 الإيرادات: {stats.get('revenue', 0.0)}")

    # ── أعلى اللغات ──
    top_langs = sorted(stats.get("languages_count", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    if top_langs:
        lines.append(f"\n🌐 أكثر اللغات استخداماً:")
        for lang_name, count in top_langs:
            lines.append(f"  • {lang_name}: {count} مستخدم")

    # ── أكثر الأزرار ضغطاً ──
    top_buttons = sorted(stats.get("button_presses", {}).items(), key=lambda x: x[1], reverse=True)[:5]
    if top_buttons:
        lines.append(f"\n🔘 أكثر الأوامر/الأزرار استخداماً:")
        for btn, count in top_buttons:
            lines.append(f"  • {btn}: {count} مرة")

    # ── تحليل داخلي شامل (القسم 5) ──
    lines.append(f"\n{'━'*30}")
    lines.append(f"📊 تحليل داخلي شامل:")
    lines.append(f"{'━'*30}")

    # أكثر الرموز/الأسهم/العملات متابعةً عبر كل المستخدمين
    all_symbols_counter = {}
    for uid_str, td in tracked_assets.items():
        for sym in td.get("assets", []):
            all_symbols_counter[sym] = all_symbols_counter.get(sym, 0) + 1
    top_symbols = sorted(all_symbols_counter.items(), key=lambda x: x[1], reverse=True)[:10]
    if top_symbols:
        lines.append(f"\n📌 أكثر الرموز/الأسهم/العملات متابعةً:")
        for sym, cnt in top_symbols:
            lines.append(f"  • {sym}: {cnt} مستخدم")
    else:
        lines.append(f"\n📌 أكثر الرموز متابعةً: لا يوجد بيانات بعد")

    # أكثر المدن طلباً للطقس
    all_cities_counter = {}
    for uid_str, u in users.items():
        prov = u.get("province", "")
        if prov and prov not in ("—", ""):
            all_cities_counter[prov] = all_cities_counter.get(prov, 0) + 1
        for c in u.get("extra_cities", []):
            if c:
                all_cities_counter[c] = all_cities_counter.get(c, 0) + 1
    top_cities = sorted(all_cities_counter.items(), key=lambda x: x[1], reverse=True)[:10]
    if top_cities:
        lines.append(f"\n🌆 أكثر المدن طلباً للطقس:")
        for city, cnt in top_cities:
            lines.append(f"  • {city}: {cnt} مستخدم")

    # توزيع أوقات الملخص اليومي
    notif_hours_counter = {}
    users_with_notif_hour = 0
    for uid_str, u in users.items():
        nh = u.get("notif_hour")
        if nh and nh != "—":
            users_with_notif_hour += 1
            notif_hours_counter[str(nh)] = notif_hours_counter.get(str(nh), 0) + 1
    lines.append(f"\n⏰ المستخدمون الذين ضبطوا وقت ملخص يومي: {users_with_notif_hour}")
    if notif_hours_counter:
        top_hours = sorted(notif_hours_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        lines.append(f"  أكثر الأوقات شيوعاً:")
        for hr, cnt in top_hours:
            lines.append(f"    • الساعة {hr}: {cnt} مستخدم")

    # توزيع تنبيهات العملات
    users_with_alert = sum(1 for u in users.values() if u.get("currency_alert") and u.get("currency_alert") != "—")
    lines.append(f"\n🔔 المستخدمون الذين فعّلوا تنبيه سعر العملة: {users_with_alert}")

    # المستخدمون الأكثر إحالةً (أعلى 5)
    top_referrers = sorted(
        [(uid_str, len(u.get("referrals", []))) for uid_str, u in users.items() if u.get("referrals")],
        key=lambda x: x[1], reverse=True
    )[:5]
    if top_referrers:
        lines.append(f"\n🏆 أكثر المستخدمين إحالةً:")
        for uid_str, ref_cnt in top_referrers:
            u = users.get(uid_str, {})
            uname = u.get("username") or u.get("name") or uid_str
            lines.append(f"  • {uname} ({uid_str}): {ref_cnt} إحالة")

    # المستخدمون الذين استخدموا الملخص اليومي/الأسبوعي
    used_summary_count = sum(1 for u in users.values() if u.get("used_summary"))
    lines.append(f"\n📋 المستخدمون الذين استخدموا الملخص: {used_summary_count}")

    # توزيع الاهتمامات
    interests_counter = {}
    for u in users.values():
        for interest in u.get("interests", []):
            interests_counter[interest] = interests_counter.get(interest, 0) + 1
    if interests_counter:
        top_interests = sorted(interests_counter.items(), key=lambda x: x[1], reverse=True)[:8]
        lines.append(f"\n🎯 أكثر الاهتمامات شيوعاً:")
        for interest, cnt in top_interests:
            lines.append(f"  • {interest}: {cnt} مستخدم")

    # المستخدمون النشطون (آخر ظهور خلال 7 أيام)
    try:
        week_ago = datetime.datetime.now() - datetime.timedelta(days=7)
        active_7d = 0
        active_30d = 0
        month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        for u in users.values():
            ls = u.get("last_seen", "")
            if ls and ls != "—":
                try:
                    ls_dt = datetime.datetime.strptime(ls, "%Y-%m-%d %H:%M")
                    if ls_dt >= week_ago:
                        active_7d += 1
                    if ls_dt >= month_ago:
                        active_30d += 1
                except Exception:
                    pass
        lines.append(f"\n📅 المستخدمون النشطون خلال آخر 7 أيام: {active_7d}")
        lines.append(f"📅 المستخدمون النشطون خلال آخر 30 يوماً: {active_30d}")
    except Exception:
        pass

    # الكلمات المفتاحية (لكل مستخدم مميز)
    users_with_keywords = sum(1 for uid_str in users if user_keywords.get(uid_str))
    lines.append(f"\n🔑 المستخدمون الذين لديهم كلمات مفتاحية: {users_with_keywords}")

    # ── بيانات تقنية (القسم 6) ──
    lines.append(f"\n{'━'*30}")
    lines.append(f"🔧 بيانات تقنية:")
    lines.append(f"{'━'*30}")
    lines.append(f"  🤖 اسم البوت: @{BOT_USERNAME}")
    lines.append(f"  📦 ملف قاعدة البيانات: {DB_FILE}")
    lines.append(f"  📝 ملاحظة: عناوين IP غير محفوظة (تلغرام لا يوفرها للبوتات)")
    lines.append(f"  📝 ملاحظة: سجل أخطاء المستخدمين غير مخزّن بشكل مستقل")
    lines.append(f"  📝 ملاحظة: إصدار البوت عند المستخدم غير متاح عبر API تلغرام")

    # ── تفاصيل المستخدمين ──
    lines.append(f"\n{'━'*30}")
    lines.append(f"👤 تفاصيل المستخدمين ({total_users} مستخدم):")
    lines.append(f"{'━'*30}")

    for idx, (uid_str, user) in enumerate(users.items(), 1):
        # ── المعلومات الأساسية ──
        name = user.get("name", "غير معروف")
        username = user.get("username", "—")
        first_name = user.get("first_name", name)
        last_name = user.get("last_name", "")
        lang = user.get("lang", "—")
        country = user.get("country", "—")
        province = user.get("province", "—")
        join_date = user.get("join_date", "—")
        notifications = "✅ مفعّل" if user.get("notifications", True) else "❌ مغلق"
        is_prem = "⭐ نعم" if int(uid_str) in premium_list else "لا"
        is_ban = "🚫 نعم" if int(uid_str) in banned else "لا"
        premium_direct = "⭐ نعم" if user.get("premium") else "لا"

        # ── التفضيلات والتتبع ──
        track_data = tracked_assets.get(uid_str, {})
        tracked_symbols = track_data.get("assets", [])
        tracked_symbols_str = ", ".join(tracked_symbols) if tracked_symbols else "لا يوجد"

        extra_cities = user.get("extra_cities", [])
        all_cities = ([province] if province and province != "—" else []) + extra_cities
        cities_str = ", ".join(all_cities) if all_cities else "لا يوجد"

        currency_alert = user.get("currency_alert", "—")
        notif_hour = user.get("notif_hour", "—")
        notif_type = "رسالة نصية" if user.get("notifications", True) else "مغلق"
        interests = user.get("interests", [])
        interests_str = ", ".join(interests) if interests else "—"
        unlocked = user.get("unlocked_features", [])
        unlocked_str = ", ".join(unlocked) if unlocked else "—"
        ref_premium_expiry = user.get("ref_premium_expiry", "—")
        referrals_count = len(user.get("referrals", []))
        referred_by = user.get("referred_by", "—")
        last_alert_sent = user.get("currency_alert_last", "—")
        sent_news_count = len(user.get("sent_news", set()))
        telegram_lang = user.get("telegram_lang", "—")
        last_command = user.get("last_command", "—")
        last_seen = user.get("last_seen", "—")
        used_summary = "✅ نعم" if user.get("used_summary") else "لا"
        rewarded_milestones = user.get("rewarded_milestones", [])
        rewarded_str = ", ".join(str(m) for m in rewarded_milestones) if rewarded_milestones else "—"
        keywords = user_keywords.get(uid_str, [])
        keywords_str = ", ".join(keywords) if keywords else "—"

        lines.append(f"\n{'─'*30}")
        lines.append(f"#{idx} — {first_name} {last_name}".strip())

        lines.append(f"\n  1️⃣ معلومات الحساب:")
        lines.append(f"  🆔 user_id: {uid_str}")
        lines.append(f"  👤 username: @{username}" if username and username != "—" else f"  👤 username: —")
        lines.append(f"  📛 الاسم الأول: {first_name}")
        lines.append(f"  📛 الاسم الأخير: {last_name if last_name else '—'}")
        lines.append(f"  🌐 اللغة المختارة في البوت: {lang}")
        lines.append(f"  💬 لغة تلغرام (Language Code): {telegram_lang}")
        lines.append(f"  🌍 الدولة: {country}")
        lines.append(f"  📍 المدينة/المحافظة الرئيسية: {province}")
        lines.append(f"  📅 تاريخ الانضمام: {join_date}")
        lines.append(f"  🕐 آخر ظهور: {last_seen}")
        lines.append(f"  🚫 محظور: {is_ban}")

        lines.append(f"\n  2️⃣ الاشتراك والمميزات:")
        lines.append(f"  ⭐ مميز (قائمة الأدمن): {is_prem}")
        lines.append(f"  ⭐ مميز (حقل مباشر): {premium_direct}")
        lines.append(f"  ⏰ انتهاء المميز المجاني: {ref_premium_expiry}")
        lines.append(f"  🎖 مراحل الإحالة المكافأة: {rewarded_str}")
        lines.append(f"  🔓 الميزات المفتوحة: {unlocked_str}")

        lines.append(f"\n  3️⃣ وظائف البوت — الطقس والتنبيهات:")
        lines.append(f"  🌆 المدن المتابعة للطقس: {cities_str}")
        lines.append(f"  📌 الأسهم/العملات المتابعة (/mytrack): {tracked_symbols_str}")
        lines.append(f"  🔔 تنبيه سعر العملة (/alerts): {currency_alert}")
        lines.append(f"  💹 آخر سعر تنبيه أُرسل: {last_alert_sent}")
        lines.append(f"  ⏰ وقت الملخص اليومي: {notif_hour}")
        lines.append(f"  📢 حالة الإشعارات: {notifications}")
        lines.append(f"  📨 نوع الإشعار: {notif_type}")
        lines.append(f"  🔑 الكلمات المفتاحية (للمميزين): {keywords_str}")

        lines.append(f"\n  4️⃣ التفاعل والاهتمامات:")
        lines.append(f"  🎯 الاهتمامات: {interests_str}")
        lines.append(f"  🗞 عدد الأخبار المُرسلة له: {sent_news_count}")
        lines.append(f"  📋 استخدم الملخص اليومي/الأسبوعي: {used_summary}")
        lines.append(f"  🖱 آخر أمر استخدمه: {last_command}")
        lines.append(f"  👥 عدد الإحالات: {referrals_count}")
        lines.append(f"  🔗 مُحال من: {referred_by}")

    lines.append(f"\n{'━'*30}")
    lines.append(f"📦 ملفات JSON المحفوظة:")
    for fname in [STATS_FILE, BANNED_FILE, RSS_FILE, ADMINS_FILE,
                  KEYWORDS_FILE, TRACK_FILE, CHANNELS_FILE, BLACKLIST_FILE,
                  READ_STATS_FILE, BROADCAST_SETTINGS_FILE, NEWS_SETTINGS_FILE,
                  INBOX_FILE, RATINGS_FILE]:
        exists = "✅" if os.path.exists(fname) else "❌"
        lines.append(f"  {exists} {fname}")

    lines.append(f"\n💾 ملف قاعدة البيانات: {DB_FILE}")
    lines.append(f"🕐 وقت إنشاء التقرير: {now}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def _send_sectioned_backup(chat_id, section):
    """إرسال نسخة احتياطية لقسم محدد"""
    import io, json as _json, zipfile
    now_str  = _now_sa().strftime("%Y-%m-%d %H:%M")
    file_str = _now_sa().strftime("%Y%m%d-%H%M")
    try:
        if section == "users":
            # نسخة قاعدة المستخدمين من SQLite
            with _db_lock:
                _db_conn.commit()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(DB_FILE):
                    zf.write(DB_FILE, os.path.basename(DB_FILE))
                # ملف JSON احتياطي للمستخدمين
                users_json = {uid: {k: list(v) if isinstance(v, set) else v
                                    for k, v in info.items()}
                              for uid, info in users.items()}
                zf.writestr("users_backup.json", _json.dumps(users_json, ensure_ascii=False, indent=2))
            buf.seek(0)
            buf.name = f"users_backup_{file_str}.zip"
            caption = (f"👥 *نسخة المستخدمين*\n🕐 {now_str}\n"
                       f"📊 إجمالي: `{len(users)}` مستخدم")
            bot.send_document(chat_id, buf, caption=caption,
                              visible_file_name=f"users_backup_{file_str}.zip",
                              parse_mode="Markdown")

        elif section == "rss":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(RSS_FILE):
                    zf.write(RSS_FILE, os.path.basename(RSS_FILE))
                if os.path.exists(CUSTOM_TG_CHANNELS_FILE):
                    zf.write(CUSTOM_TG_CHANNELS_FILE, os.path.basename(CUSTOM_TG_CHANNELS_FILE))
                # إضافة بيانات RSS من الذاكرة
                zf.writestr("rss_in_memory.json", _json.dumps(RSS, ensure_ascii=False, indent=2))
                zf.writestr("custom_tg_channels_in_memory.json", _json.dumps(_custom_tg_channels, ensure_ascii=False, indent=2))
            buf.seek(0)
            buf.name = f"rss_backup_{file_str}.zip"
            total_feeds = sum(len(v) for v in RSS.values())
            caption = (f"📡 *نسخة مصادر RSS*\n🕐 {now_str}\n"
                       f"📊 إجمالي المصادر: `{total_feeds}`")
            bot.send_document(chat_id, buf, caption=caption,
                              visible_file_name=f"rss_backup_{file_str}.zip",
                              parse_mode="Markdown")

        elif section == "channels":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(CHANNELS_FILE):
                    zf.write(CHANNELS_FILE, os.path.basename(CHANNELS_FILE))
                zf.writestr("channels_in_memory.json",
                            _json.dumps(channels_groups, ensure_ascii=False, indent=2))
            buf.seek(0)
            buf.name = f"channels_backup_{file_str}.zip"
            caption = (f"📺 *نسخة القنوات والمجموعات*\n🕐 {now_str}\n"
                       f"📊 إجمالي: `{len(channels_groups)}`")
            bot.send_document(chat_id, buf, caption=caption,
                              visible_file_name=f"channels_backup_{file_str}.zip",
                              parse_mode="Markdown")

        elif section == "settings":
            settings_files = [
                ADMINS_FILE, KEYWORDS_FILE, TRACK_FILE, BLACKLIST_FILE,
                BROADCAST_SETTINGS_FILE, NEWS_SETTINGS_FILE, INBOX_FILE,
                RATINGS_FILE, WELCOME_FILE, STATS_FILE, READ_STATS_FILE,
            ]
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in settings_files:
                    if os.path.exists(fp):
                        zf.write(fp, os.path.basename(fp))
            buf.seek(0)
            buf.name = f"settings_backup_{file_str}.zip"
            caption = (f"⚙️ *نسخة الإعدادات*\n🕐 {now_str}")
            bot.send_document(chat_id, buf, caption=caption,
                              visible_file_name=f"settings_backup_{file_str}.zip",
                              parse_mode="Markdown")
    except Exception as e:
        try:
            bot.send_message(chat_id, f"❌ خطأ في النسخة الاحتياطية ({section}): {e}")
        except:
            pass


def send_backup(chat_id=None):
    import io, zipfile
    target = chat_id if chat_id else ADMIN_ID
    with _db_lock:
        _db_conn.commit()
    now = _now_sa().strftime("%Y-%m-%d %H:%M")
    file_now = _now_sa().strftime("%Y%m%d-%H%M")

    # ── 1) إرسال ملف الإعدادات ZIP (آمن 100% للاستعادة بدون كراش) ──
    try:
        settings_zip = io.BytesIO()
        settings_files = [
            ADMINS_FILE, KEYWORDS_FILE, TRACK_FILE, CHANNELS_FILE,
            BLACKLIST_FILE, BROADCAST_SETTINGS_FILE, NEWS_SETTINGS_FILE,
            INBOX_FILE, RATINGS_FILE, WELCOME_FILE, STATS_FILE, READ_STATS_FILE,
        ]
        with zipfile.ZipFile(settings_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f_path in settings_files:
                if os.path.exists(f_path):
                    zf.write(f_path, os.path.basename(f_path))
        settings_zip.seek(0)
        settings_zip.name = f"bot_settings_{file_now}.zip"
        bot.send_document(
            target,
            settings_zip,
            caption=(
                f"⚙️ *نسخة احتياطية — الإعدادات*\n"
                f"🕐 {now}\n\n"
                f"📦 يحتوي على:\n"
                f"• القنوات والمجموعات\n"
                f"• الأدمن المضافين\n"
                f"• الكلمات المفتاحية والتنبيهات\n"
                f"• تتبع الأسهم والعملات\n"
                f"• الكلمات المحظورة ({len(blacklist_words)})\n"
                f"• رسائل الصندوق ({len(inbox_messages)})\n"
                f"• إعدادات الأخبار والبث\n"
                f"• رسالة الترحيب المخصصة\n"
                f"• التقييمات والإحصائيات\n\n"
                f"↩️ *لاستعادة الإعدادات:* أرسل هذا الملف للبوت مباشرة\n"
                f"✅ آمن تماماً — لا يوقف البوت"
            ),
            visible_file_name=f"bot_settings_{file_now}.zip",
            parse_mode="Markdown"
        )
    except Exception as e:
        try:
            bot.send_message(target, f"❌ فشل إرسال ملف الإعدادات: {e}")
        except Exception:
            pass

    # ── 2) إرسال قاعدة البيانات .db (المستخدمون) ──
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "rb") as f:
                bot.send_document(
                    target,
                    f,
                    caption=(
                        f"💾 *نسخة احتياطية — قاعدة البيانات*\n"
                        f"🕐 {now}\n"
                        f"👥 المستخدمون: {len(users)}\n"
                        f"⭐ المميزون: {len(stats.get('premium_users', []))}\n"
                        f"🚫 المحظورون: {len(banned)}\n\n"
                        f"↩️ *لاستعادة البيانات:* أرسل هذا الملف للبوت مباشرة\n"
                        f"✅ آمن تماماً — لا يوقف البوت"
                    ),
                    visible_file_name=f"bot_data_{file_now}.db",
                    parse_mode="Markdown"
                )
    except Exception as e:
        try:
            bot.send_message(target, f"❌ فشل إرسال قاعدة البيانات: {e}")
        except Exception:
            pass

    # ── 3) إرسال تقرير المستخدمين .txt (مفصّل قابل للقراءة) ──
    try:
        report_text = _build_backup_report()
        report_bytes = io.BytesIO(report_text.encode("utf-8"))
        report_bytes.name = f"users_report_{file_now}.txt"
        bot.send_document(
            target,
            report_bytes,
            caption=(
                f"📋 *تقرير المستخدمين التفصيلي*\n"
                f"🕐 {now}\n"
                f"👥 إجمالي المستخدمين: {len(users)}\n\n"
                f"📄 يحتوي على:\n"
                f"• معلومات الحساب الكاملة (ID، اسم المستخدم، الأسماء)\n"
                f"• اللغة المختارة ولغة تلغرام\n"
                f"• الدولة والمدينة\n"
                f"• تاريخ الانضمام وآخر ظهور\n"
                f"• حالة الإشعارات والاشتراك المميز\n"
                f"• الرموز المتابعة وتنبيهات العملات\n"
                f"• آخر أمر واهتمامات المستخدم\n"
                f"• الإحالات والميزات المفعّلة"
            ),
            visible_file_name=f"users_report_{file_now}.txt",
            parse_mode="Markdown"
        )
    except Exception as e:
        try:
            bot.send_message(target, f"❌ فشل إرسال تقرير المستخدمين: {e}")
        except Exception:
            pass

def auto_backup():
    send_backup(ADMIN_ID)

# ======== تذكير الأدمن إذا البوت متوقف أكثر من 6 ساعات ========
def check_pause_reminder():
    global bot_paused, _pause_since
    if not bot_paused or _pause_since is None:
        return
    hours_paused = (datetime.datetime.now() - _pause_since).total_seconds() / 3600
    if hours_paused >= 6:
        try:
            bot.send_message(
                ADMIN_ID,
                f"⚠️ *تنبيه:* البوت متوقف منذ {int(hours_paused)} ساعة!\n"
                f"🕐 وقت الإيقاف: {_pause_since.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"افتح /admin واضغط *إيقاف/تشغيل البوت* لإعادة تشغيله.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

# ======== استعادة البيانات من ملف .db أو .zip ========
@bot.message_handler(content_types=['document'])
def handle_document(message):
    global blacklist_words, news_settings, inbox_messages, welcome_override, broadcast_settings
    global extra_admins, channels_groups, user_keywords, tracked_assets, read_stats
    global ratings_data, stats, _db_conn, users
    import io, zipfile, shutil
    if not is_admin(message.from_user.id):
        return
    doc = message.document
    if not doc.file_name:
        return

    file_info = bot.get_file(doc.file_id)
    downloaded = bot.download_file(file_info.file_path)

    # ── استعادة الإعدادات من ملف ZIP (آمن — JSON فقط، بدون لمس البوت أو DB) ──
    if doc.file_name.endswith(".zip"):
        try:
            restored = []
            zip_buffer = io.BytesIO(downloaded)
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                for name in zf.namelist():
                    # تجاهل bot.py وملفات .db وملفات التقرير — JSON فقط
                    if not name.endswith(".json") or name.startswith("backup_report"):
                        continue
                    data = zf.read(name)
                    with open(name, "wb") as f:
                        f.write(data)
                    # إعادة تحميل كل إعداد في الذاكرة فوراً
                    bn = name
                    if bn == os.path.basename(BLACKLIST_FILE):
                        blacklist_words = load_json(BLACKLIST_FILE, [])
                    elif bn == os.path.basename(NEWS_SETTINGS_FILE):
                        news_settings = load_json(NEWS_SETTINGS_FILE, {})
                    elif bn == os.path.basename(INBOX_FILE):
                        inbox_messages = load_json(INBOX_FILE, [])
                    elif bn == os.path.basename(WELCOME_FILE):
                        _wd = load_json(WELCOME_FILE, {"override": None})
                        welcome_override = _wd.get("override", None)
                    elif bn == os.path.basename(BROADCAST_SETTINGS_FILE):
                        broadcast_settings = load_json(BROADCAST_SETTINGS_FILE, {})
                    elif bn == os.path.basename(ADMINS_FILE):
                        extra_admins = [int(a) for a in load_json(ADMINS_FILE, [])]
                    elif bn == os.path.basename(CHANNELS_FILE):
                        channels_groups = load_json(CHANNELS_FILE, [])
                        _db_save_all_channels(channels_groups)  # sync to SQLite after restore
                    elif bn == os.path.basename(KEYWORDS_FILE):
                        user_keywords = load_json(KEYWORDS_FILE, {})
                    elif bn == os.path.basename(TRACK_FILE):
                        tracked_assets = load_json(TRACK_FILE, {})
                    elif bn == os.path.basename(READ_STATS_FILE):
                        read_stats = load_json(READ_STATS_FILE, {"total_opens": 0, "daily": {}})
                    elif bn == os.path.basename(RATINGS_FILE):
                        ratings_data = load_json(RATINGS_FILE, {"entries": [], "bot_sum": 0, "news_sum": 0, "count": 0})
                    elif bn == os.path.basename(STATS_FILE):
                        stats = load_json(STATS_FILE, {})
                    restored.append(f"✅ {name}")
            count = len(restored)
            bot.send_message(
                message.chat.id,
                f"✅ تم استعادة الإعدادات بنجاح!\n"
                f"📂 عدد الملفات المستعادة: {count}"
            )
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ فشل استعادة الملف: {str(e)[:200]}")
        return

    # ── استعادة من ملف .db فقط (للتوافق مع النسخ القديمة) ──
    if doc.file_name.endswith(".db"):
        try:
            backup_path = DB_FILE + ".bak"
            if os.path.exists(DB_FILE):
                import shutil
                shutil.copy2(DB_FILE, backup_path)
            with open(DB_FILE, "wb") as f:
                f.write(downloaded)
            with _db_lock:
                _db_conn.close()
                _db_conn = sqlite3.connect(DB_FILE, check_same_thread=False)
            users = _db_load_users()
            bot.send_message(
                message.chat.id,
                f"✅ *تم استعادة قاعدة البيانات بنجاح!*\n"
                f"👥 عدد المستخدمين المحملين: `{len(users)}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ فشل استعادة البيانات: {e}")

# ======== الجدولة ========
# ======== تغليف آمن للمهام المجدولة ========
def _safe_job(fn):
    """
    Wrapper لكل مهام الـ Scheduler:
    - يصطاد أي Exception
    - يُسجّل الخطأ في الـ log
    - يُرسل تنبيه فوري للأدمن مع traceback
    - لا يوقف الـ Scheduler أبداً
    """
    @functools.wraps(fn)
    def wrapper():
        try:
            fn()
        except Exception as e:
            _logger.error(f"❌ خطأ في المهمة المجدولة [{fn.__name__}]: {e}", exc_info=True)
            try:
                send_alert(
                    message    = f"خطأ في المهمة المجدولة: {fn.__name__}",
                    exc        = e,
                    func_name  = fn.__name__,
                    show_traceback = True
                )
            except Exception:
                pass
    return wrapper


# ─── Heartbeat: كل 10 دقائق يُرسل للأدمن تأكيد أن البوت يعمل ────────────────
_heartbeat_fail_count = 0

def _send_heartbeat():
    """لوحة مراقبة شاملة للأدمن — ترسل كل 10 دقائق بتوقيت السعودية."""
    global _heartbeat_fail_count
    try:
        # ─── 1. الوقت (توقيت السعودية UTC+3) ────────────────────────
        now_sa  = _now_sa()
        now_str = now_sa.strftime("%H:%M:%S — %d/%m/%Y")

        # ─── 2. معلومات وقت التشغيل (من نظام الملفات) ────────────────
        uptime_str = "—"
        try:
            with open("/proc/uptime") as f:
                secs = float(f.read().split()[0])
            h_up, rem  = divmod(int(secs), 3600)
            m_up, _    = divmod(rem, 60)
            uptime_str = f"{h_up}س {m_up}د"
        except Exception:
            pass

        # ─── 3. المستخدمون ───────────────────────────────────────────
        total_users   = len(users)
        active_users  = sum(1 for u in users.values()
                            if u.get("notifications", True) and u.get("lang"))
        banned_count  = len(banned) if hasattr(banned, '__len__') else 0

        # ─── 4. القنوات والمجموعات ────────────────────────────────────
        ch_count  = sum(1 for c in channels_groups if c.get("type") == "channel")
        grp_count = sum(1 for c in channels_groups
                        if c.get("type") in ("group", "supergroup"))
        paused_ch = sum(1 for c in channels_groups if c.get("paused"))

        # ─── 5. حالة البث ─────────────────────────────────────────────
        bcast_status = "🔴 متوقف" if (bot_paused or broadcast_paused) else "🟢 يعمل"
        news_lock_s  = "🔴 مشغول" if _broadcast_news_lock.is_set() else "🟢 حر"
        ch_lock_s    = "🔴 مشغول" if _broadcast_channels_lock.is_set() else "🟢 حر"
        with _broadcast_stats_lock:
            last_bcast   = _broadcast_stats.get("last_broadcast_time") or "لم يبث بعد"
            today_sent   = _broadcast_stats.get("today_news_sent", 0)
            today_users  = _broadcast_stats.get("today_users_reached", 0)
            total_sent   = _broadcast_stats.get("total_news_all_time", 0)

        # ─── 6. قائمة الإرسال ─────────────────────────────────────────
        q_size = _send_queue.qsize()
        q_icon = "🔴" if q_size > 500 else ("🟡" if q_size > 100 else "🟢")

        # ─── 7. global_sent_news ──────────────────────────────────────
        with _global_sent_lock:
            gsn_total = sum(len(s) for s in _global_sent_news.values())
            gsn_langs  = len(_global_sent_news)

        # ─── 8. الذكاء الاصطناعي ──────────────────────────────────────
        if _AI_AVAILABLE:
            ai_str = "✅ Gemini نشط — كل المزايا تعمل"
        elif GEMINI_API_KEY:
            ai_str = "⚠️ AI عنده مشكلة — يُحاول إعادة الاتصال تلقائياً"
        else:
            ai_str = (
                "⚠️ AI غير مفعّل\n"
                "   ← لتفعيله مجاناً:\n"
                "   1. افتح: https://aistudio.google.com/apikey\n"
                "   2. أنشئ مفتاح مجاني\n"
                "   3. أضفه في Heroku:\n"
                "      GEMINI_API_KEY = [المفتاح]\n"
                "   سيُفعَّل AI تلقائياً بعد إعادة التشغيل"
            )

        # ─── 9. آخر خطأ في البث ──────────────────────────────────────
        last_err = ""
        with _broadcast_stats_lock:
            if _broadcast_errors:
                last_err = f"\n🚨 آخر خطأ: `{_broadcast_errors[-1][-60:]}`"

        # ─── تجميع الرسالة ─────────────────────────────────────────────
        msg = (
            "💚 IraqNow Bot — لوحة المراقبة\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {now_str}  (توقيت السعودية)\n"
            f"⏱ وقت التشغيل: {uptime_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "👥 المستخدمون\n"
            f"   الكل: {total_users:,}  |  فعّال: {active_users:,}  |  محظور: {banned_count}\n"
            "📺 القنوات والمجموعات\n"
            f"   قنوات: {ch_count}  |  مجموعات: {grp_count}  |  موقوف: {paused_ch}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📡 حالة البث\n"
            f"   الحالة: {bcast_status}\n"
            f"   قفل المستخدمين: {news_lock_s}  |  قفل القنوات: {ch_lock_s}\n"
            f"   آخر بث: {last_bcast}\n"
            f"   🧵 خيوط نشطة: {threading.active_count()} / 256\n"
            f"   اليوم: {today_sent:,} خبر  →  {today_users:,} مستخدم\n"
            f"   الكل: {total_sent:,} خبر منذ البداية\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📬 قائمة الإرسال\n"
            f"   {q_icon} {q_size:,} رسالة بالانتظار\n"
            "📰 الأخبار المُسجَّلة (global_sent)\n"
            f"   {gsn_total:,} رابط  |  {gsn_langs} لغة\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 {ai_str}"
            f"{last_err}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 الإصلاح التلقائي: يعمل دائماً في الخلفية\n"
            "   • تنظيف القائمة تلقائياً إذا تجاوزت 300 رسالة\n"
            "   • إعادة البث تلقائياً إذا توقف >25 دقيقة\n"
            "   • إعادة تشغيل AI تلقائياً إذا أُضيف المفتاح"
        )
        bot.send_message(ADMIN_ID, msg)   # بدون parse_mode لتجنب أي مشكلة Markdown
        _heartbeat_fail_count = 0
        _logger.info(f"💚 Heartbeat — users={total_users}, q={q_size}, bcast={bcast_status}")
    except Exception as e:
        _heartbeat_fail_count += 1
        _logger.warning(f"⚠️ فشل إرسال Heartbeat ({_heartbeat_fail_count}): {e}")

# ======================================================
# ميزة: تجميع القصص المتكررة (Story Clustering)
# قصة واحدة من عدة مصادر → رسالة موحدة مع عداد المصادر
# ======================================================
def _cluster_stories(items, threshold=0.55):
    """
    يجمع الأخبار المتشابهة في مجموعات.
    يعيد قائمة من: (link, title, feed_urls_list, summary)
    حيث feed_urls_list = قائمة كل المصادر التي غطّت القصة.
    """
    if not items:
        return []
    clusters = []
    used = set()
    for i, (link_i, title_i, feed_i, sum_i) in enumerate(items):
        if i in used:
            continue
        group = [(link_i, title_i, feed_i, sum_i)]
        used.add(i)
        for j, (link_j, title_j, feed_j, sum_j) in enumerate(items):
            if j in used:
                continue
            sim = _cosine_similarity_titles(title_i, title_j)
            if sim >= threshold:
                group.append((link_j, title_j, feed_j, sum_j))
                used.add(j)
        # ممثّل المجموعة = أول خبر (الأقدم / الأكثر تفصيلاً)
        rep_link, rep_title, rep_feed, rep_sum = group[0]
        all_feeds = list({g[2] for g in group})
        clusters.append((rep_link, rep_title, all_feeds, rep_sum, len(group)))
    return clusters


def _format_clustered_news(lang, title, link, feeds, source_count, summary="", pub_time_str=""):
    """يُنسّق خبراً مجمّعاً مع إشارة للمصادر المتعددة"""
    sources_txt = ""
    if source_count > 1:
        sources_txt = f"\n📡 _غطّته {source_count} مصادر_"
    label = t(lang, "label_breaking")
    src_name = get_source_name_from_url(feeds[0]) if feeds else ""
    base = format_news_item(label, title, lang, src_name, pub_time_str, summary=summary)
    return base + sources_txt


# ======================================================
# ميزة: متابعة قصة بعينها (/follow)
# ======================================================
_story_followers = {}  # keyword → {uid: lang}
_story_key_cache = {}  # story_key (md5[:16]) → keyword string

# ── كاش التحقق من الأخبار — مع استمرارية على القرص لتجاوز إعادة التشغيل ──
_FACTCHECK_CACHE_FILE = "factcheck_key_cache.json"
def _load_factcheck_cache() -> dict:
    try:
        if os.path.exists(_FACTCHECK_CACHE_FILE):
            with open(_FACTCHECK_CACHE_FILE, "r", encoding="utf-8") as _f:
                data = json.load(_f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}

def _save_factcheck_cache(cache: dict):
    try:
        # نحتفظ بآخر 1000 مفتاح فقط لتحديد حجم الملف
        if len(cache) > 1000:
            keys = list(cache.keys())[-800:]
            cache = {k: cache[k] for k in keys}
        with open(_FACTCHECK_CACHE_FILE, "w", encoding="utf-8") as _f:
            json.dump(cache, _f, ensure_ascii=False)
    except Exception:
        pass

_factcheck_key_cache = _load_factcheck_cache()  # يُحمَّل من القرص عند الإقلاع


def _check_followed_stories(items_by_lang):
    """
    يفحص الأخبار الجديدة ويُرسل للمستخدمين الذين يتابعون كلمة مفتاحية معينة
    """
    if not _story_followers:
        return
    for keyword, followers in list(_story_followers.items()):
        kw_lower = keyword.lower()
        for uid_str, lang in list(followers.items()):
            uid = int(uid_str)
            items = items_by_lang.get(lang, [])
            for entry in items:
                link = entry[0] if len(entry) > 0 else ''
                title = entry[1] if len(entry) > 1 else ''
                feed_url = entry[2] if len(entry) > 2 else ''
                item_sum = entry[3] if len(entry) > 3 else ''
                pub_dt = entry[4] if len(entry) > 4 else None
                if kw_lower in title.lower():
                    src_name = get_source_name_from_url(feed_url)
                    pub_time_str = _format_pub_time(pub_dt, lang=lang)
                    story_label = t(lang, "label_breaking") + " 🔔"
                    msg_body = format_news_item(story_label, title, lang, src_name, pub_time_str, summary=item_sum)
                    # سطر متابعة يُضاف في الأعلى
                    follow_note = NEWS_SHARE_LABELS.get(lang, NEWS_SHARE_LABELS["English 🇬🇧"]).get("story_update", "🔔 Story Update")
                    msg = f"{follow_note}: `{keyword}`\n\n{msg_body}"
                    markup = make_news_share_markup(link, title, lang, item_sum)
                    try:
                        bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)
                    except Exception:
                        pass
                    break  # خبر واحد لكل قصة لكل دورة


@bot.message_handler(commands=["follow"])
def cmd_follow(m):
    """متابعة كلمة مفتاحية — سيُرسل البوت فور ظهورها في الأخبار"""
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    parts = m.text.strip().split(None, 1)
    if len(parts) < 2:
        user = users.get(str(uid), {})
        followed = user.get("followed_stories", [])
        if not followed:
            bot.send_message(uid,
                "🔔 *متابعة قصة إخبارية*\n\n"
                "أرسل الكلمة أو الموضوع الذي تريد متابعته:\n"
                "`/follow العراق`\n"
                "`/follow Gaza`\n"
                "`/follow أسعار النفط`\n\n"
                "سيُرسل لك البوت فوراً عند ظهور أخبار جديدة عن هذا الموضوع.",
                parse_mode="Markdown"
            )
        else:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for kw in followed:
                markup.add(types.InlineKeyboardButton(
                    f"❌ إلغاء متابعة: {kw}", callback_data=f"unfollow_{kw[:30]}"
                ))
            bot.send_message(uid,
                f"🔔 *القصص التي تتابعها:*\n" +
                "\n".join(f"• `{kw}`" for kw in followed) +
                "\n\nاضغط لإلغاء متابعة أي منها.",
                parse_mode="Markdown", reply_markup=markup
            )
        return
    keyword = parts[1].strip()[:50]
    lang = users.get(str(uid), {}).get("lang", "العربية 🇮🇶")
    # أضف للقائمة العامة
    if keyword not in _story_followers:
        _story_followers[keyword] = {}
    _story_followers[keyword][str(uid)] = lang
    # أضف لإعدادات المستخدم
    if str(uid) in users:
        followed = users[str(uid)].get("followed_stories", [])
        if keyword not in followed:
            followed.append(keyword)
            users[str(uid)]["followed_stories"] = followed
            _db_save_user(uid, users[str(uid)])
    bot.send_message(uid,
        f"✅ *ستصلك أخبار عن:* `{keyword}`\n\n"
        "سيُرسل لك البوت فور ظهور هذا الموضوع في الأخبار.\n"
        "لإلغاء المتابعة: `/unfollow {keyword}`".replace("{keyword}", keyword),
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["unfollow"])
def cmd_unfollow(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    parts = m.text.strip().split(None, 1)
    if len(parts) < 2:
        bot.send_message(uid, "❌ مثال: `/unfollow العراق`", parse_mode="Markdown")
        return
    keyword = parts[1].strip()
    _story_followers.pop(keyword, None)
    if str(uid) in users:
        followed = users[str(uid)].get("followed_stories", [])
        followed = [f for f in followed if f != keyword]
        users[str(uid)]["followed_stories"] = followed
        _db_save_user(uid, users[str(uid)])
    bot.send_message(uid, f"✅ تم إلغاء متابعة: `{keyword}`", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data.startswith("unfollow_") and not c.data.startswith("unfollow_story_"))
def cb_unfollow(call):
    # إصلاح #2: نستثني unfollow_story_ لتجنب التعارض مع handle_unfollow_story_button
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    keyword = call.data[len("unfollow_"):]
    _story_followers.pop(keyword, None)
    if str(uid) in users:
        followed = users[str(uid)].get("followed_stories", [])
        followed = [f for f in followed if f != keyword]
        users[str(uid)]["followed_stories"] = followed
        _db_save_user(uid, users[str(uid)])
    bot.send_message(uid, f"✅ تم إلغاء متابعة: `{keyword}`", parse_mode="Markdown")


# ======================================================
# ميزة: الملخص الأسبوعي (كل جمعة الساعة 10:00)
# ======================================================
_weekly_top_news = {}  # lang → list of (title, link, count)
_weekly_news_lock = False


def _record_weekly_news(title, link, lang):
    """يسجّل خبراً لقائمة الأسبوع"""
    if lang not in _weekly_top_news:
        _weekly_top_news[lang] = {}
    key = link
    if key not in _weekly_top_news[lang]:
        _weekly_top_news[lang][key] = {"title": title, "link": link, "count": 0}
    _weekly_top_news[lang][key]["count"] += 1


def send_weekly_summary():
    if bot_paused: return
    """ترسل ملخص أبرز أخبار الأسبوع لكل المستخدمين كل جمعة"""
    if not _weekly_top_news:
        return
    log("📆 إرسال الملخص الأسبوعي...")
    week_end = datetime.date.today().strftime("%Y/%m/%d")
    week_start = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y/%m/%d")
    for uid_str, info in list(users.items()):
        try:
            if not info.get("notifications", True):
                continue
            uid = int(uid_str)
            lang = info.get("lang", "العربية 🇮🇶")
            top = sorted(
                _weekly_top_news.get(lang, {}).values(),
                key=lambda x: x["count"], reverse=True
            )[:7]
            if not top:
                continue
            lines = []
            for i, item in enumerate(top, 1):
                lines.append(f"{i}. [{item['title']}]({item['link']})")
            msg = (
                f"📆 *الملخص الأسبوعي*\n"
                f"🗓 {week_start} — {week_end}\n"
                f"━━━━━━━━━━━━━━\n\n"
                + "\n\n".join(lines) +
                "\n\n━━━━━━━━━━━━━━\n"
                "_أبرز الأخبار التي غطّتها مصادر متعددة هذا الأسبوع_"
            )
            try:
                bot.send_message(uid, msg, parse_mode="Markdown",
                                 disable_web_page_preview=True)
            except Exception:
                pass
        except Exception:
            continue
    # إعادة تعيين قائمة الأسبوع
    _weekly_top_news.clear()
    log("✅ انتهى الملخص الأسبوعي")


# ======================================================
# ميزة: وضع المجموعات مع التصويت على الأخبار
# ======================================================
_group_votes = {}  # message_id → {"title": .., "yes": set(), "no": set(), "link": ..}


def _send_group_news(chat_id, title, link, lang, summary=""):
    """يرسل خبراً للمجموعة مع أزرار تصويت"""
    markup = types.InlineKeyboardMarkup(row_width=3)
    msg_placeholder = bot.send_message(chat_id,
        f"📰 *{title}*\n🔗 [اقرأ الخبر]({link})",
        parse_mode="Markdown"
    )
    mid = msg_placeholder.message_id
    _group_votes[mid] = {"title": title, "link": link, "yes": set(), "no": set(), "chat_id": chat_id}
    markup.add(
        types.InlineKeyboardButton("👍 مهم", callback_data=f"gvote_yes_{mid}"),
        types.InlineKeyboardButton("👎 غير مهم", callback_data=f"gvote_no_{mid}"),
        types.InlineKeyboardButton("🔗 فتح", url=link),
    )
    try:
        bot.edit_message_reply_markup(chat_id, mid, reply_markup=markup)
    except Exception:
        pass
    return mid


@bot.callback_query_handler(func=lambda c: c.data.startswith("gvote_"))
def cb_group_vote(call):
    uid = call.from_user.id
    parts = call.data.split("_")
    if len(parts) < 3:
        return
    vote_type = parts[1]  # yes / no
    mid = int(parts[2])
    vote_data = _group_votes.get(mid)
    if not vote_data:
        bot.answer_callback_query(call.id, "⏰ انتهت صلاحية التصويت")
        return
    # إزالة أي تصويت سابق للمستخدم
    vote_data["yes"].discard(uid)
    vote_data["no"].discard(uid)
    if vote_type == "yes":
        vote_data["yes"].add(uid)
        bot.answer_callback_query(call.id, "👍 صوّتت: مهم")
    else:
        vote_data["no"].add(uid)
        bot.answer_callback_query(call.id, "👎 صوّتت: غير مهم")
    # تحديث الأزرار بعداد التصويت
    yes_count = len(vote_data["yes"])
    no_count  = len(vote_data["no"])
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton(f"👍 {yes_count}", callback_data=f"gvote_yes_{mid}"),
        types.InlineKeyboardButton(f"👎 {no_count}",  callback_data=f"gvote_no_{mid}"),
        types.InlineKeyboardButton("🔗 فتح", url=vote_data["link"]),
    )
    try:
        bot.edit_message_reply_markup(vote_data["chat_id"], mid, reply_markup=markup)
    except Exception:
        pass
    # تعلّم من التصويت الإيجابي لتحسين التوصيات
    if vote_type == "yes":
        u = users.get(str(uid), {})
        u["rated_positive"] = u.get("rated_positive", 0) + 1
        _db_save_user(uid, u)
    else:
        u = users.get(str(uid), {})
        u["rated_negative"] = u.get("rated_negative", 0) + 1
        _db_save_user(uid, u)


def _validate_rss_sources():
    """يفحص كل مصادر RSS ليلاً ويُبلّغ الأدمن بالمصادر المعطوبة"""
    broken = {}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
    for lang, feeds in RSS.items():
        for url in feeds:
            try:
                parsed = feedparser.parse(url)
                if not parsed.entries:
                    broken.setdefault(lang, []).append(url)
            except Exception:
                broken.setdefault(lang, []).append(url)
    if broken:
        msg = "⚠️ *تقرير المصادر المعطوبة (فحص ليلي):*\n\n"
        for lang, urls in broken.items():
            msg += f"*{lang}:*\n" + "\n".join(f"• `{u}`" for u in urls) + "\n\n"
        msg += "يمكنك حذفها من لوحة الإدارة ← RSS."
        for admin_id in ADMINS:
            try:
                bot.send_message(admin_id, msg, parse_mode="Markdown")
            except Exception:
                pass
    else:
        log("✅ فحص ليلي: جميع مصادر RSS تعمل بشكل صحيح")


# ======== نشرة مسائية للأخبار العاجلة ========
# تُذكّر المستخدمين بأبرز الأخبار العاجلة عند المساء (18:00)
_evening_recap_sent = {}   # uid -> date_str (لمنع الإرسال المزدوج)

def send_evening_recap():
    if bot_paused: return
    """ترسل ملخصاً لأبرز أخبار اليوم العاجلة إلى كل المستخدمين المشتركين"""
    today = str(datetime.date.today())
    sent_links = set()
    breaking_items = []

    # اجمع الأخبار العاجلة من كل اللغات
    for lang in set(info.get("lang", "") for info in users.values() if info.get("lang")):
        feeds = RSS.get(lang, [])
        for feed_url in feeds[:5]:
            try:
                feed = _parse_feed(feed_url, timeout=10)
                if not feed:
                    continue
                for item in feed.entries[:15]:
                    title = getattr(item, 'title', '')
                    link  = getattr(item, 'link', '')
                    if not title or not link or link in sent_links:
                        continue
                    if _news_importance_score(title) >= 2:
                        sent_links.add(link)
                        breaking_items.append((lang, title, link))
                if len(breaking_items) >= 20:
                    break
            except:
                pass

    if not breaking_items:
        return

    # أرسل لكل مستخدم بلغته
    for uid, info in list(users.items()):
        try:
            if int(uid) in banned:
                continue
            if not info.get("notifications", True):
                continue
            # لا ترسل للوضع الصامت (إلا إذا عطّل)
            if not info.get("quiet_mode_enabled", True) is False and _is_quiet_hours(uid):
                continue
            # تحقق أنها لم تُرسل اليوم
            if _evening_recap_sent.get(str(uid)) == today:
                continue
            lang = info.get("lang", "")
            if not lang:
                continue
            user_items = [(t, l) for (lg, t, l) in breaking_items if lg == lang]
            if not user_items:
                continue
            lines = []
            for title, link in user_items[:8]:
                s_e = _sentiment_emoji(title)
                lines.append(f"🚨 [{s_e + ' ' if s_e else ''}{title}]({link})")
            if not lines:
                continue
            msg = _ul(lang, "evening_title") + "\n".join(lines)
            queue_send(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)
            _evening_recap_sent[str(uid)] = today
        except Exception:
            continue



# =====================================================================
# ==================== أوامر وكولباكات الرياضة ========================
# =====================================================================

@bot.message_handler(commands=['sports'])
def handle_sports_cmd(message):
    uid = message.from_user.id
    prefs = _get_user_sports(uid)
    # إصلاح #5: العربية هي اللغة الافتراضية لكل القسم الرياضي
    lang = users.get(str(uid), {}).get("lang", "العربية 🇮🇶")
    selected = prefs.get('leagues', [])
    leagues_text = _ul(lang, "sports_leagues", n=len(selected)) if selected else _ul(lang, "sports_no_leagues")
    alerts_text = _ul(lang, "sports_alerts_on") if prefs.get('live_alerts') else _ul(lang, "sports_alerts_off")
    text = (
        _ul(lang, "sports_title")
        + f"📊 {leagues_text}\n"
        + f"🔔 {alerts_text}\n\n"
        + _ul(lang, "sports_choose")
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown",
                     reply_markup=_sports_main_keyboard(uid))

@bot.callback_query_handler(func=lambda c: c.data == "sp_main")
def cb_sports_main(call):
    uid = call.from_user.id
    lang = users.get(str(uid), {}).get("lang", "العربية 🇮🇶")
    prefs = _get_user_sports(uid)
    selected = prefs.get('leagues', [])
    leagues_text = _ul(lang, "sports_leagues", n=len(selected)) if selected else _ul(lang, "sports_no_leagues")
    alerts_text = _ul(lang, "sports_alerts_on") if prefs.get('live_alerts') else _ul(lang, "sports_alerts_off")
    text = (
        _ul(lang, "sports_title")
        + f"📊 {leagues_text}\n"
        + f"🔔 {alerts_text}\n\n"
        + _ul(lang, "sports_choose")
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=_sports_main_keyboard(uid))
    except Exception:
        pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "sp_live")
def cb_sports_live(call):
    bot.answer_callback_query(call.id, "⏳ جاري جلب النتائج...")
    _send_live_scores(call.from_user.id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "sp_schedule")
def cb_sports_schedule(call):
    bot.answer_callback_query(call.id, "⏳ جاري جلب الجدول...")
    _send_schedule(call.from_user.id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "sp_news")
def cb_sports_news(call):
    bot.answer_callback_query(call.id, "⏳ جاري جلب الأخبار...")
    _send_sports_news(call.from_user.id, call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sp_leagues_p"))
def cb_sports_leagues(call):
    page = int(call.data.replace("sp_leagues_p", ""))
    uid = call.from_user.id
    prefs = _get_user_sports(uid)
    selected = prefs.get('leagues', [])
    text = f"⚽ *اختر دورياتك*\n\nالمختار: {len(selected)} دوري — اضغط لإضافة أو إزالة دوري\n\n✅ = مختار"
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown",
                              reply_markup=_sports_leagues_keyboard(uid, page))
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown",
                         reply_markup=_sports_leagues_keyboard(uid, page))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sp_tog_"))
def cb_sports_toggle_league(call):
    raw = call.data.replace("sp_tog_", "")
    # إصلاح #6: نستخرج رقم الصفحة (_p{N}) ثم نُحلّل sport_key
    page = 0
    if "_p" in raw:
        raw, pg_str = raw.rsplit("_p", 1)
        try:
            page = int(pg_str)
        except ValueError:
            page = 0
    # دعم الصيغتين: sp_tog_{key}_s{sport} أو sp_tog_{key}
    if "_s" in raw:
        key, sport_key = raw.rsplit("_s", 1)
    else:
        key = raw
        sport_key = SPORTS_LEAGUES.get(raw, {}).get('sport', 'football')
    uid = call.from_user.id
    prefs = _get_user_sports(uid)
    selected = prefs.get('leagues', [])
    if key in selected:
        selected.remove(key)
        action = "أُزيل"
    else:
        selected.append(key)
        action = "أُضيف"
    prefs['leagues'] = selected
    _set_user_sports(uid, prefs)
    league_name = SPORTS_LEAGUES.get(key, {}).get('name', key).replace('⚽ ','').replace('🏀 ','').replace('🏎️ ','')
    bot.answer_callback_query(call.id, f"✅ {league_name} {action}")
    prefs2 = _get_user_sports(uid)
    sel2 = prefs2.get('leagues', [])
    text = f"🏅 *اختر دورياتك — {SPORT_CATEGORIES.get(sport_key,{}).get('name','')}*\n\nالمختار: {len(sel2)} دوري\n✅ = مختار، اضغط ✅ مرة ثانية للإزالة"
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown",
                              # إصلاح #6: نُمرّر page لإبقاء المستخدم في نفس الصفحة
                              reply_markup=_leagues_by_sport_keyboard(uid, sport_key, page))
    except Exception:
        pass

@bot.callback_query_handler(func=lambda c: c.data == "sp_toggle_alerts")
def cb_sports_toggle_alerts(call):
    uid = call.from_user.id
    prefs = _get_user_sports(uid)
    prefs['live_alerts'] = not prefs.get('live_alerts', False)
    _set_user_sports(uid, prefs)
    status = "مفعّلة 🔔" if prefs['live_alerts'] else "مغلقة 🔕"
    bot.answer_callback_query(call.id, f"تنبيهات المباريات: {status}")
    # تحديث القائمة
    lang = users.get(str(uid), {}).get("lang", "العربية 🇮🇶")
    selected = prefs.get('leagues', [])
    leagues_text = _ul(lang, "sports_leagues", n=len(selected)) if selected else _ul(lang, "sports_no_leagues")
    alerts_text = _ul(lang, "sports_alerts_on") if prefs['live_alerts'] else _ul(lang, "sports_alerts_off")
    text = (
        _ul(lang, "sports_title")
        + f"📊 {leagues_text}\n"
        + f"🔔 {alerts_text}\n\n"
        + _ul(lang, "sports_choose")
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=_sports_main_keyboard(uid))
    except Exception:
        pass



@bot.callback_query_handler(func=lambda c: c.data == "sp_sports")
def cb_sports_categories(call):
    text = "🏅 *اختر الرياضة التي تتابعها*\n\nاختر أولاً نوع الرياضة ثم الدوري ثم الفريق:"
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=_sport_categories_keyboard())
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown",
                         reply_markup=_sport_categories_keyboard())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sp_sport_"))
def cb_sports_sport_filter(call):
    raw = call.data.replace("sp_sport_", "")
    page = 0
    if "_p" in raw:
        sport_key, pg = raw.rsplit("_p", 1)
        page = int(pg)
    else:
        sport_key = raw
    uid = call.from_user.id
    cat = SPORT_CATEGORIES.get(sport_key, {})
    prefs = _get_user_sports(uid)
    sel = prefs.get('leagues', [])
    sport_sel = [k for k in sel if SPORTS_LEAGUES.get(k, {}).get('sport') == sport_key]
    text = (
        f"{cat.get('flag','⚽')} *{cat.get('name','الدوريات')}*\n\n"
        f"المختار: {len(sport_sel)} دوري\n"
        "اضغط الدوري لإضافته ✅ أو إزالته\n"
        "اضغط 👕 لاختيار فريق من الدوري"
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown",
                              reply_markup=_leagues_by_sport_keyboard(uid, sport_key, page))
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown",
                         reply_markup=_leagues_by_sport_keyboard(uid, sport_key, page))
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sp_tms_"))
def cb_sports_teams_list(call):
    raw = call.data.replace("sp_tms_", "")
    # sp_tms_{league_key}_p{page}
    parts = raw.rsplit("_p", 1)
    league_key = parts[0]
    page = int(parts[1]) if len(parts) > 1 else 0
    uid = call.from_user.id
    league = SPORTS_LEAGUES.get(league_key, {})
    league_display = league.get('name','').replace('⚽ ','').replace('🏀 ','').replace('🏎️ ','')
    bot.answer_callback_query(call.id, "⏳ جاري جلب الفرق...")
    # إذا الفرق غير محمّلة في الكاش — نُحمّلها الآن مع إشعار "جاري التحميل"
    league = SPORTS_LEAGUES.get(league_key, {})
    espn = league.get('espn')
    if espn and espn not in _teams_cache:
        bot.answer_callback_query(call.id, "⏳ جاري تحميل قائمة الفرق...")
        # جلب الفرق (سيُخزَّن في الكاش تلقائياً داخل _get_league_teams)
        _get_league_teams(espn)
    kb = _teams_keyboard(uid, league_key, page)
    if not kb:
        bot.answer_callback_query(call.id, "❌ لا تتوفر بيانات فرق لهذا الدوري")
        return
    prefs = _get_user_sports(uid)
    user_teams = prefs.get('teams', {})
    league_teams_sel = user_teams.get(league_key, [])
    sel_count = len(league_teams_sel)
    # أسماء الفرق المختارة من الكاش
    sel_names = []
    if espn and espn in _teams_cache:
        id_to_name = {t['id']: t['name'] for t in _teams_cache[espn]}
        sel_names = [id_to_name.get(tid, tid) for tid in league_teams_sel]
    sel_text = "\n".join(f"  • {n}" for n in sel_names[:10]) if sel_names else "  لم تختر أي فريق بعد"
    text = (
        f"👕 *فرق {league_display}*\n\n"
        f"✅ فرقك المختارة ({sel_count}):\n{sel_text}\n\n"
        "💡 يمكنك اختيار *أكثر من فريق* — اضغط على الفريق للإضافة أو الإزالة"
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sp_tm_"))
def cb_sports_toggle_team(call):
    # sp_tm_{league_key}_{team_id}
    raw = call.data.replace("sp_tm_", "")
    # team_id قد يكون رقم — نقسم من اليمين مرة واحدة
    parts = raw.split("_", 1)
    if len(parts) < 2:
        bot.answer_callback_query(call.id)
        return
    league_key = parts[0]
    team_id = parts[1]
    # إذا league_key يحتوي _ نعيد المحاولة بأخذ كل شيء قبل آخر _
    # المنطق: league_key هي مفتاح موجود في SPORTS_LEAGUES
    # نبحث عن أطول prefix مطابق
    for possible_key in sorted(SPORTS_LEAGUES.keys(), key=len, reverse=True):
        if raw.startswith(possible_key + "_"):
            league_key = possible_key
            team_id = raw[len(possible_key)+1:]
            break
    uid = call.from_user.id
    prefs = _get_user_sports(uid)
    user_teams = prefs.setdefault('teams', {})
    sel = set(user_teams.get(league_key, []))
    league = SPORTS_LEAGUES.get(league_key, {})
    espn = league.get('espn')
    # جلب اسم الفريق من الكاش فقط — لا نستدعي ESPN هنا لتجنب التأخير
    team_name = team_id
    if espn and espn in _teams_cache:
        for t in _teams_cache[espn]:
            if t['id'] == team_id:
                team_name = t['name']
                break
    if team_id in sel:
        sel.discard(team_id)
        action = "أُزيل"
    else:
        sel.add(team_id)
        action = "أُضيف"
    user_teams[league_key] = list(sel)
    prefs['teams'] = user_teams
    _set_user_sports(uid, prefs)
    icon_a = "✅" if action == "أُضيف" else "❌"
    bot.answer_callback_query(call.id, f"{icon_a} {team_name} {action}")
    # تحديث قائمة الفرق (من الكاش — لا استدعاء HTTP جديد)
    league_display = league.get('name','').replace('⚽ ','').replace('🏀 ','').replace('🏎️ ','')
    kb = _teams_keyboard(uid, league_key, 0)
    prefs2 = _get_user_sports(uid)
    sel_count = len(prefs2.get('teams', {}).get(league_key, []))
    sel_names = []
    if espn and espn in _teams_cache:
        id_to_name = {t['id']: t['name'] for t in _teams_cache[espn]}
        sel_names = [id_to_name.get(tid, tid) for tid in prefs2.get('teams', {}).get(league_key, [])]
    sel_text = "\n".join(f"  • {n}" for n in sel_names[:10]) if sel_names else "  لم تختر أي فريق"
    text = (
        f"👕 *فرق {league_display}*\n\n"
        f"✅ فرقك المختارة ({sel_count}):\n{sel_text}\n\n"
        "💡 يمكنك اختيار *أكثر من فريق* — اضغط للإضافة أو الإزالة"
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# أوامر وكولباكات الميزات الأسطورية
# ═══════════════════════════════════════════════════════════════════

# [إصلاح #1] النسخة الأولى من /verify حُذفت — النسخة المحسّنة موجودة في قسم الميزات الاستخباراتية

@bot.message_handler(commands=['analyze'])
def handle_analyze_cmd(message):
    uid = message.from_user.id
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
    text = message.text.replace('/analyze', '').strip()
    if not text:
        bot.send_message(message.chat.id,
            "🧠 *تحليل المزاج السياسي*\n\nأرسل الخبر بعد الأمر:\n`/analyze عنوان الخبر`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, "🧠 جاري التحليل السياسي...")
    result = _ai_political_analysis(text, lang=lang)
    reply = f"🧠 *تحليل سياسي*\n\n📰 _{text[:60]}_\n\n{result}"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")

@bot.message_handler(commands=['compare'])
def handle_compare_cmd(message):
    text = message.text.replace('/compare', '').strip()
    if not text:
        bot.send_message(message.chat.id,
            "🌐 *مقارنة وجهات النظر*\n\nأرسل الموضوع بعد الأمر:\n`/compare الانتخابات العراقية`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, "🌐 جاري مقارنة المصادر الإعلامية...")
    result = _ai_compare_perspectives(text)
    reply = f"🌐 *مقارنة وجهات النظر*\n\n🔎 الموضوع: _{text}_\n\n{result}"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")

@bot.message_handler(commands=['timeline'])
def handle_timeline_cmd(message):
    text = message.text.replace('/timeline', '').strip()
    if not text:
        bot.send_message(message.chat.id,
            "📅 *خريطة الأخبار الزمنية*\n\nأرسل الموضوع بعد الأمر:\n`/timeline الأزمة السياسية في العراق`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, "📅 جاري بناء الخريطة الزمنية...")
    result = _ai_build_timeline(text)
    reply = f"📅 *الخريطة الزمنية*\n\n🔎 الموضوع: _{text}_\n\n{result}"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")

@bot.message_handler(commands=['live'])
def handle_live_event_cmd(message):
    uid = message.from_user.id
    text = message.text.replace('/live', '').strip()
    if not text:
        active = _live_events.get(str(uid))
        if active:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("⏹ إيقاف التتبع", callback_data="live_stop"))
            bot.send_message(message.chat.id,
                f"🔴 أنت الآن تتابع: *{active['event']}*\n\nسيرسل لك تحديث كل دقيقتين.",
                parse_mode="Markdown", reply_markup=kb)
        else:
            bot.send_message(message.chat.id,
                "🔴 *بث مباشر للأحداث*\n\nأرسل الحدث الذي تريد متابعته:\n`/live اجتماع البرلمان`\n\n⏱ ستستلم تحديثاً كل دقيقتين لمدة 6 ساعات",
                parse_mode="Markdown")
        return
    _live_events[str(uid)] = {
        "event": text,
        "started": time.time(),
        "last_update": 0,
        "updates": []
    }
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⏹ إيقاف التتبع", callback_data="live_stop"))
    bot.send_message(message.chat.id,
        f"🔴 *بدأ التتبع المباشر*\n\n📌 الحدث: *{text}*\n⏱ تحديث كل دقيقتين لمدة 6 ساعات\n\nسأرسل لك كل خبر جديد يذكر هذا الحدث فور نشره.",
        parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "live_stop")
def cb_live_stop(call):
    uid_s = str(call.from_user.id)
    if uid_s in _live_events:
        event = _live_events.pop(uid_s)["event"]
        bot.answer_callback_query(call.id, f"⏹ توقف تتبع: {event}")
        try:
            bot.edit_message_text(f"⏹ *تم إيقاف التتبع*\n\nالحدث: *{event}*", 
                call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        except Exception:
            pass
    else:
        bot.answer_callback_query(call.id, "لا يوجد تتبع نشط")

@bot.message_handler(commands=['submit'])
def handle_submit_news_cmd(message):
    uid = message.from_user.id
    text = message.text.replace('/submit', '').strip()
    if not text:
        bot.send_message(message.chat.id,
            "📢 *شارك خبراً من أرض الواقع*\n\nأرسل الخبر بعد الأمر:\n`/submit شهدت منطقة المنصور اليوم...`\n\n🤖 سيتحقق الذكاء الاصطناعي منه وإذا كان موثوقاً سيُوزَّع على المشتركين.",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, "🤖 جاري التحقق من خبرك...")
    result = _ai_verify_user_news(text)
    score = result.get("score", 0)
    valid = result.get("valid", False)
    reason = result.get("reason", "")
    cleaned = result.get("cleaned", text)
    if valid and score >= 60:
        # نشر للمشتركين
        user_name = message.from_user.first_name or "مستخدم"
        broadcast_text = (
            f"📢 *خبر من الميدان*\n\n"
            f"{cleaned}\n\n"
            f"📍 بلّغ: مستخدم من المجتمع\n"
            f"✅ تحقق الذكاء الاصطناعي: {score}%"
        )
        sent_count = 0
        for uid_s, info in list(users.items()):
            try:
                if info.get("notifications", True):
                    bot.send_message(int(uid_s), broadcast_text, parse_mode="Markdown")
                    sent_count += 1
            except Exception:
                pass
        reply = (
            f"✅ *تم قبول خبرك ونشره!*\n\n"
            f"📊 نسبة الموثوقية: `{score}%`\n"
            f"👥 أُرسل لـ `{sent_count}` مشترك\n\n"
            f"شكراً على مساهمتك في نشر الأخبار الموثوقة! 🙏"
        )
        _verified_user_news_log.append({"uid": uid, "text": cleaned, "score": score, "time": time.time()})
    else:
        reply = (
            f"❌ *لم يُقبل الخبر*\n\n"
            f"📊 نسبة الموثوقية: `{score}%` (يحتاج 60%+)\n"
            f"📝 السبب: {reason}\n\n"
            f"حاول إرسال معلومات أكثر تفصيلاً وموضوعية."
        )
    try:
        bot.edit_message_text(reply, message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply, parse_mode="Markdown")

@bot.message_handler(commands=['sources'])
def handle_sources_ranking_cmd(message):
    rankings = _get_source_rankings()
    if not rankings:
        bot.send_message(message.chat.id,
            "📊 *تصنيف المصادر*\n\nلم يتم جمع بيانات كافية بعد.\nسيظهر التصنيف بعد دورات بث عدة.",
            parse_mode="Markdown")
        return
    text = "📊 *تصنيف المصادر الإخبارية*\n_(حسب السرعة والكمية — آخر 24 ساعة)_\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 20
    for i, src in enumerate(rankings[:15]):
        medal = medals[i]
        text += (
            f"{medal} *{src['source']}*\n"
            f"   📰 {src['count_24h']} خبر · ⚡ كل {src['avg_gap_min']} دقيقة\n\n"
        )
    bot.send_message(message.chat.id, text[:4096], parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("verify_news_"))
def cb_verify_news(call):
    # إصلاح #3: لا نستبدل _ بمسافة — نأخذ الـkey كما هو ونجلب العنوان الأصلي من الكاش
    key = call.data[len("verify_news_"):]
    title = _factcheck_key_cache.get(key) or _news_summary_cache.get(key, {}).get("title", "") or key.replace("_", " ")
    title = title[:100]
    bot.answer_callback_query(call.id, "🔍 جاري التحقق...")
    msg = bot.send_message(call.message.chat.id, "🔍 جاري التحقق من الخبر...")
    result = _ai_verify_news(title)
    reply = _format_verify_result(result, title)
    try:
        bot.edit_message_text(reply, call.message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        pass


# ─── /deepsearch command handler ────────────────────────────────
@bot.message_handler(commands=['deepsearch'])
def handle_deepsearch_cmd(message):
    uid = message.from_user.id
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
    topic = message.text.replace('/deepsearch', '').strip()
    if not topic:
        prompts = {
            "العربية 🇮🇶": "🔍 *DeepSearch — بحث عميق*\n\nأرسل الموضوع بعد الأمر:\n`/deepsearch الأزمة السياسية في العراق`\n\n⏱ البحث يستغرق 5-15 دقيقة ويفحص عشرات المصادر",
            "English 🇬🇧": "🔍 *DeepSearch*\n\nSend topic after command:\n`/deepsearch Iraq political crisis`\n\n⏱ Search takes 5-15 minutes scanning dozens of sources",
        }
        bot.send_message(message.chat.id,
            prompts.get(lang, prompts["English 🇬🇧"]), parse_mode="Markdown")
        return
    if _deepsearch_active.get(str(uid)):
        bot.send_message(message.chat.id, "⏳ بحث سابق لا يزال جارياً، انتظر حتى يكتمل")
        return
    _deepsearch_active[str(uid)] = True
    start_msgs = {
        "العربية 🇮🇶": (
            f"🔍 *DeepSearch بدأ*\n\n"
            f"📌 الموضوع: *{topic}*\n\n"
            f"⏳ جاري فحص:\n"
            f"• مصادر RSS العربية والدولية\n"
            f"• مواقع إخبارية بالسكرابنق\n"
            f"• المصادر الرسمية والحكومية\n"
            f"• قاعدة بيانات NewsAPI العالمية\n"
            f"• تحليل عميق بالذكاء الاصطناعي\n\n"
            f"_قد يستغرق 5-15 دقيقة..._"
        ),
        "English 🇬🇧": (
            f"🔍 *DeepSearch Started*\n\n"
            f"📌 Topic: *{topic}*\n\n"
            f"⏳ Scanning:\n"
            f"• Arabic & international RSS feeds\n"
            f"• News sites via scraping\n"
            f"• Official & government sources\n"
            f"• NewsAPI global database\n"
            f"• Deep AI analysis\n\n"
            f"_May take 5-15 minutes..._"
        ),
    }
    progress_msg = bot.send_message(
        message.chat.id,
        start_msgs.get(lang, start_msgs["English 🇬🇧"]),
        parse_mode="Markdown"
    )
    t = threading.Thread(
        target=_deepsearch_worker,
        args=(uid, topic, progress_msg.message_id, message.chat.id),
        daemon=True
    )
    t.start()


@bot.callback_query_handler(func=lambda c: c.data.startswith("analyze_news_"))
def cb_analyze_news(call):
    # إصلاح #4: جلب العنوان الأصلي من الكاش بدلاً من استبدال _ بمسافة
    key   = call.data[len("analyze_news_"):]
    title = (_news_summary_cache.get(key, {}).get("title", "")
             or _factcheck_key_cache.get(key, "")
             or key.replace("_", " "))[:100]
    bot.answer_callback_query(call.id, "🧠 جاري التحليل...")
    msg = bot.send_message(call.message.chat.id, "🧠 جاري التحليل السياسي...")
    lang = users.get(str(call.from_user.id), {}).get('lang', 'العربية 🇮🇶')
    result = _ai_political_analysis(title, lang=lang)
    reply = f"🧠 *تحليل سياسي*\n\n📰 _{title[:60]}_\n\n{result}"
    try:
        bot.edit_message_text(reply[:4096], call.message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        pass



# ═══════════════════════════════════════════════════════════════════
# القائمة الرئيسية الجديدة — أبسط وأجمل
# ═══════════════════════════════════════════════════════════════════

_MENU_LABELS = {
    "العربية 🇮🇶": {
        "news":"📰 الأخبار","deep":"🔍 DeepSearch","ai":"🧠 تحليل AI",
        "sports":"🏅 الرياضة","weather":"🌤 الطقس","markets":"💰 الأسواق",
        "settings":"⚙️ الإعدادات","help":"❓ المساعدة",
        "ai_verify":"✅ تحقق من خبر","ai_analyze":"🧠 تحليل سياسي",
        "ai_compare":"🌐 مقارنة مصادر","ai_timeline":"📅 خط زمني",
        "ai_predict":"🔮 توقعات","ai_influence":"🗺 خريطة نفوذ",
        "ai_profile":"🕵️ محقق شخصية","ai_parliament":"🏛 البرلمان",
        "ai_econ":"📉 مؤشرات اقتصادية","ai_ask":"💬 اسألني",
        "back":"🔙 رجوع","title":"🏠 القائمة الرئيسية",
        "live":"🔴 بث مباشر","submit":"📢 شارك خبراً",
    },
    "English 🇬🇧": {
        "news":"📰 News","deep":"🔍 DeepSearch","ai":"🧠 AI Analysis",
        "sports":"🏅 Sports","weather":"🌤 Weather","markets":"💰 Markets",
        "settings":"⚙️ Settings","help":"❓ Help",
        "ai_verify":"✅ Verify News","ai_analyze":"🧠 Political Analysis",
        "ai_compare":"🌐 Compare Sources","ai_timeline":"📅 Timeline",
        "ai_predict":"🔮 Predictions","ai_influence":"🗺 Influence Map",
        "ai_profile":"🕵️ Investigate","ai_parliament":"🏛 Parliament",
        "ai_econ":"📉 Economy","ai_ask":"💬 Ask Me",
        "back":"🔙 Back","title":"🏠 Main Menu",
        "live":"🔴 Live Event","submit":"📢 Submit News",
    },
    "Русский 🇷🇺": {
        "news":"📰 Новости","deep":"🔍 DeepSearch","ai":"🧠 ИИ Анализ",
        "sports":"🏅 Спорт","weather":"🌤 Погода","markets":"💰 Рынки",
        "settings":"⚙️ Настройки","help":"❓ Помощь",
        "ai_verify":"✅ Проверка новости","ai_analyze":"🧠 Политический анализ",
        "ai_compare":"🌐 Сравнение источников","ai_timeline":"📅 Хронология",
        "ai_predict":"🔮 Прогноз","ai_influence":"🗺 Карта влияния",
        "ai_profile":"🕵️ Профиль личности","ai_parliament":"🏛 Парламент",
        "ai_econ":"📉 Экономика","ai_ask":"💬 Задать вопрос",
        "back":"🔙 Назад","title":"🏠 Главное меню",
        "live":"🔴 Прямой эфир","submit":"📢 Поделиться новостью",
    },
    "فارسی 🇮🇷": {
        "news":"📰 اخبار","deep":"🔍 جستجوی عمیق","ai":"🧠 تحلیل هوش مصنوعی",
        "sports":"🏅 ورزش","weather":"🌤 آبوهوا","markets":"💰 بازارها",
        "settings":"⚙️ تنظیمات","help":"❓ راهنما",
        "ai_verify":"✅ تأیید خبر","ai_analyze":"🧠 تحلیل سیاسی",
        "ai_compare":"🌐 مقایسه منابع","ai_timeline":"📅 خط زمانی",
        "ai_predict":"🔮 پیشبینی","ai_influence":"🗺 نقشه نفوذ",
        "ai_profile":"🕵️ پروفایل شخص","ai_parliament":"🏛 پارلمان",
        "ai_econ":"📉 اقتصاد","ai_ask":"💬 بپرس",
        "back":"🔙 بازگشت","title":"🏠 منوی اصلی",
        "live":"🔴 رویداد زنده","submit":"📢 ارسال خبر",
    },
    "हिन्दी 🇮🇳": {
        "news":"📰 समाचार","deep":"🔍 DeepSearch","ai":"🧠 AI विश्लेषण",
        "sports":"🏅 खेल","weather":"🌤 मौसम","markets":"💰 बाज़ार",
        "settings":"⚙️ सेटिंग्स","help":"❓ सहायता",
        "ai_verify":"✅ समाचार जांच","ai_analyze":"🧠 राजनीतिक विश्लेषण",
        "ai_compare":"🌐 स्रोत तुलना","ai_timeline":"📅 समयरेखा",
        "ai_predict":"🔮 भविष्यवाणी","ai_influence":"🗺 प्रभाव मानचित्र",
        "ai_profile":"🕵️ व्यक्ति प्रोफ़ाइल","ai_parliament":"🏛 संसद",
        "ai_econ":"📉 अर्थव्यवस्था","ai_ask":"💬 मुझसे पूछें",
        "back":"🔙 वापस","title":"🏠 मुख्य मेनू",
        "live":"🔴 लाइव इवेंट","submit":"📢 समाचार भेजें",
    },
    "Português 🇧🇷": {
        "news":"📰 Notícias","deep":"🔍 DeepSearch","ai":"🧠 Análise IA",
        "sports":"🏅 Esportes","weather":"🌤 Clima","markets":"💰 Mercados",
        "settings":"⚙️ Configurações","help":"❓ Ajuda",
        "ai_verify":"✅ Verificar Notícia","ai_analyze":"🧠 Análise Política",
        "ai_compare":"🌐 Comparar Fontes","ai_timeline":"📅 Linha do Tempo",
        "ai_predict":"🔮 Previsões","ai_influence":"🗺 Mapa de Influência",
        "ai_profile":"🕵️ Perfil de Pessoa","ai_parliament":"🏛 Parlamento",
        "ai_econ":"📉 Economia","ai_ask":"💬 Pergunte-me",
        "back":"🔙 Voltar","title":"🏠 Menu Principal",
        "live":"🔴 Evento ao Vivo","submit":"📢 Enviar Notícia",
    },
    "Türkçe 🇹🇷": {
        "news":"📰 Haberler","deep":"🔍 DeepSearch","ai":"🧠 AI Analiz",
        "sports":"🏅 Spor","weather":"🌤 Hava Durumu","markets":"💰 Piyasalar",
        "settings":"⚙️ Ayarlar","help":"❓ Yardım",
        "ai_verify":"✅ Haber Doğrula","ai_analyze":"🧠 Siyasi Analiz",
        "ai_compare":"🌐 Kaynak Karşılaştır","ai_timeline":"📅 Zaman Çizelgesi",
        "ai_predict":"🔮 Tahminler","ai_influence":"🗺 Nüfuz Haritası",
        "ai_profile":"🕵️ Kişi Profili","ai_parliament":"🏛 Parlamento",
        "ai_econ":"📉 Ekonomi","ai_ask":"💬 Bana Sor",
        "back":"🔙 Geri","title":"🏠 Ana Menü",
        "live":"🔴 Canlı Etkinlik","submit":"📢 Haber Gönder",
    },
    "اردو 🇵🇰": {
        "news":"📰 خبریں","deep":"🔍 DeepSearch","ai":"🧠 AI تجزیہ",
        "sports":"🏅 کھیل","weather":"🌤 موسم","markets":"💰 منڈیاں",
        "settings":"⚙️ ترتیبات","help":"❓ مدد",
        "ai_verify":"✅ خبر کی تصدیق","ai_analyze":"🧠 سیاسی تجزیہ",
        "ai_compare":"🌐 ذرائع کا موازنہ","ai_timeline":"📅 وقت کی لکیر",
        "ai_predict":"🔮 پیشن گوئیاں","ai_influence":"🗺 اثر کا نقشہ",
        "ai_profile":"🕵️ شخصیت پروفائل","ai_parliament":"🏛 پارلیمنٹ",
        "ai_econ":"📉 معیشت","ai_ask":"💬 مجھ سے پوچھیں",
        "back":"🔙 واپس","title":"🏠 مرکزی مینو",
        "live":"🔴 براہ راست","submit":"📢 خبر بھیجیں",
    },
    "Deutsch 🇩🇪": {
        "news":"📰 Nachrichten","deep":"🔍 DeepSearch","ai":"🧠 KI-Analyse",
        "sports":"🏅 Sport","weather":"🌤 Wetter","markets":"💰 Märkte",
        "settings":"⚙️ Einstellungen","help":"❓ Hilfe",
        "ai_verify":"✅ Nachricht prüfen","ai_analyze":"🧠 Politische Analyse",
        "ai_compare":"🌐 Quellen vergleichen","ai_timeline":"📅 Zeitlinie",
        "ai_predict":"🔮 Vorhersagen","ai_influence":"🗺 Einfluss-Karte",
        "ai_profile":"🕵️ Personen-Profil","ai_parliament":"🏛 Parlament",
        "ai_econ":"📉 Wirtschaft","ai_ask":"💬 Frag mich",
        "back":"🔙 Zurück","title":"🏠 Hauptmenü",
        "live":"🔴 Live-Event","submit":"📢 Nachricht einreichen",
    },
    "Українська 🇺🇦": {
        "news":"📰 Новини","deep":"🔍 DeepSearch","ai":"🧠 ШІ Аналіз",
        "sports":"🏅 Спорт","weather":"🌤 Погода","markets":"💰 Ринки",
        "settings":"⚙️ Налаштування","help":"❓ Допомога",
        "ai_verify":"✅ Перевірка новини","ai_analyze":"🧠 Політичний аналіз",
        "ai_compare":"🌐 Порівняння джерел","ai_timeline":"📅 Хронологія",
        "ai_predict":"🔮 Прогнози","ai_influence":"🗺 Карта впливу",
        "ai_profile":"🕵️ Профіль особи","ai_parliament":"🏛 Парламент",
        "ai_econ":"📉 Економіка","ai_ask":"💬 Запитай мене",
        "back":"🔙 Назад","title":"🏠 Головне меню",
        "live":"🔴 Пряма трансляція","submit":"📢 Надіслати новину",
    },
    "Italiano 🇮🇹": {
        "news":"📰 Notizie","deep":"🔍 DeepSearch","ai":"🧠 Analisi AI",
        "sports":"🏅 Sport","weather":"🌤 Meteo","markets":"💰 Mercati",
        "settings":"⚙️ Impostazioni","help":"❓ Aiuto",
        "ai_verify":"✅ Verifica Notizia","ai_analyze":"🧠 Analisi Politica",
        "ai_compare":"🌐 Confronta Fonti","ai_timeline":"📅 Linea del Tempo",
        "ai_predict":"🔮 Previsioni","ai_influence":"🗺 Mappa Influenza",
        "ai_profile":"🕵️ Profilo Persona","ai_parliament":"🏛 Parlamento",
        "ai_econ":"📉 Economia","ai_ask":"💬 Chiedimi",
        "back":"🔙 Indietro","title":"🏠 Menu Principale",
        "live":"🔴 Evento Live","submit":"📢 Invia Notizia",
    },
    "Español 🇲🇽": {
        "news":"📰 Noticias","deep":"🔍 DeepSearch","ai":"🧠 Análisis IA",
        "sports":"🏅 Deportes","weather":"🌤 Clima","markets":"💰 Mercados",
        "settings":"⚙️ Configuración","help":"❓ Ayuda",
        "ai_verify":"✅ Verificar Noticia","ai_analyze":"🧠 Análisis Político",
        "ai_compare":"🌐 Comparar Fuentes","ai_timeline":"📅 Línea de Tiempo",
        "ai_predict":"🔮 Predicciones","ai_influence":"🗺 Mapa de Influencia",
        "ai_profile":"🕵️ Perfil de Persona","ai_parliament":"🏛 Parlamento",
        "ai_econ":"📉 Economía","ai_ask":"💬 Pregúntame",
        "back":"🔙 Volver","title":"🏠 Menú Principal",
        "live":"🔴 Evento en Vivo","submit":"📢 Enviar Noticia",
    },
}
# سائر اللغات تستخدم الإنجليزية افتراضياً
def _ml(lang, key):
    return _MENU_LABELS.get(lang, _MENU_LABELS["English 🇬🇧"]).get(key, key)

def _build_main_menu(lang):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"news"),    callback_data="menu_news"),
        types.InlineKeyboardButton(_ml(lang,"deep"),    callback_data="menu_deep"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"ai"),      callback_data="menu_ai"),
        types.InlineKeyboardButton(_ml(lang,"sports"),  callback_data="menu_sports"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"weather"), callback_data="menu_weather"),
        types.InlineKeyboardButton(_ml(lang,"markets"), callback_data="menu_markets"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"settings"),callback_data="menu_settings"),
        types.InlineKeyboardButton(_ml(lang,"help"),    callback_data="menu_help"),
    )
    return kb

def _build_ai_menu(lang):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"ai_verify"),   callback_data="aimenu_verify"),
        types.InlineKeyboardButton(_ml(lang,"ai_analyze"),  callback_data="aimenu_analyze"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"ai_compare"),  callback_data="aimenu_compare"),
        types.InlineKeyboardButton(_ml(lang,"ai_timeline"), callback_data="aimenu_timeline"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"ai_predict"),  callback_data="aimenu_predict"),
        types.InlineKeyboardButton(_ml(lang,"ai_influence"),callback_data="aimenu_influence"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"ai_profile"),  callback_data="aimenu_profile"),
        types.InlineKeyboardButton(_ml(lang,"ai_ask"),      callback_data="aimenu_ask"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"ai_parliament"),callback_data="aimenu_parliament"),
        types.InlineKeyboardButton(_ml(lang,"ai_econ"),     callback_data="aimenu_econ"),
    )
    kb.add(
        types.InlineKeyboardButton(_ml(lang,"live"),        callback_data="aimenu_live"),
        types.InlineKeyboardButton(_ml(lang,"submit"),      callback_data="aimenu_submit"),
    )
    kb.add(types.InlineKeyboardButton(_ml(lang,"back"), callback_data="menu_main"))
    return kb

def _send_main_menu_msg(chat_id, lang, text=None):
    lbl = _MENU_LABELS.get(lang, _MENU_LABELS["English 🇬🇧"])
    if not text:
        text = lbl.get("title", "🏠 القائمة الرئيسية")
    kb = _build_main_menu(lang)
    bot.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

# ─── معالجات القائمة ────────────────────────────────────────────
@bot.message_handler(commands=['menu'])
def handle_menu_cmd(message):
    uid = str(message.from_user.id)
    lang = users.get(uid, {}).get('lang', 'العربية 🇮🇶')
    _send_main_menu_msg(message.chat.id, lang)

@bot.callback_query_handler(func=lambda c: c.data == "menu_main")
def cb_menu_main(call):
    lang = users.get(str(call.from_user.id), {}).get('lang', 'العربية 🇮🇶')
    kb = _build_main_menu(lang)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        _send_main_menu_msg(call.message.chat.id, lang)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def cb_back_main(call):
    """رجوع للقائمة الرئيسية من أي مكان"""
    lang = users.get(str(call.from_user.id), {}).get('lang', 'العربية 🇮🇶')
    kb = _build_main_menu(lang)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        _send_main_menu_msg(call.message.chat.id, lang)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "menu_news")
def cb_menu_news(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "📰 جاري تحضير آخر الأخبار...")
    try:
        handle_news_command_inline(uid, call.message.chat.id)
    except Exception:
        bot.send_message(call.message.chat.id, "أرسل /news لعرض الأخبار")

def handle_news_command_inline(uid, chat_id):
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
    count = 0
    seen = set()
    for feed_url in list(RSS.get(lang, RSS.get("العربية 🇮🇶", [])))[:8]:
        try:
            feed = _parse_feed(feed_url)
            if not feed: continue
            for entry in feed.entries[:5]:
                title = getattr(entry, 'title', '').strip()
                link = getattr(entry, 'link', '')
                if not title or title in seen: continue
                seen.add(title)
                pub = _pub_dt_from_item(entry)
                if pub and (datetime.datetime.now() - pub).total_seconds() > 86400: continue
                time_str = pub.strftime('%H:%M') if pub else ''
                bot.send_message(chat_id,
                    f"📰 *{title}*\n\n{('⏱ ' + time_str) if time_str else ''}\n🔗 [اقرأ الخبر]({link})",
                    parse_mode="Markdown", disable_web_page_preview=True)
                count += 1
                if count >= 5: return
        except Exception: pass
    if count == 0:
        bot.send_message(chat_id, "لا توجد أخبار حديثة متاحة الآن")

@bot.callback_query_handler(func=lambda c: c.data == "menu_deep")
def cb_menu_deep(call):
    uid = call.from_user.id
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
    bot.answer_callback_query(call.id)
    _deep_ask = {
        "العربية 🇮🇶": "🔍 *DeepSearch — بحث عميق*\n\n✏️ *أرسل الموضوع الذي تريد البحث عنه الآن:*\n\n_مثال: الأزمة السياسية في العراق — نتائج الانتخابات — سعر النفط_\n\n⏱ يستغرق البحث 5-15 دقيقة ويفحص عشرات المصادر",
        "English 🇬🇧": "🔍 *DeepSearch*\n\n✏️ *Type your topic now:*\n\n_Example: Iraq political crisis — Oil prices — Elections_\n\n⏱ Takes 5-15 minutes scanning dozens of sources",
        "Русский 🇷🇺": "🔍 *DeepSearch*\n\n✏️ *Напишите тему сейчас:*\n\n_Пример: политический кризис в Ираке_\n\n⏱ Занимает 5-15 минут",
        "فارسی 🇮🇷": "🔍 *DeepSearch*\n\n✏️ *موضوع را اکنون ارسال کنید:*\n\n⏱ ۵ تا ۱۵ دقیقه",
        "हिन्दी 🇮🇳": "🔍 *DeepSearch*\n\n✏️ *अभी विषय टाइप करें:*\n\n⏱ 5-15 मिनट लगते हैं",
        "Português 🇧🇷": "🔍 *DeepSearch*\n\n✏️ *Digite o tópico agora:*\n\n⏱ Demora 5-15 minutos",
        "Türkçe 🇹🇷": "🔍 *DeepSearch*\n\n✏️ *Şimdi konuyu yazın:*\n\n⏱ 5-15 dakika sürer",
        "اردو 🇵🇰": "🔍 *DeepSearch*\n\n✏️ *ابھی موضوع ٹائپ کریں:*\n\n⏱ 5-15 منٹ لگتے ہیں",
        "Deutsch 🇩🇪": "🔍 *DeepSearch*\n\n✏️ *Geben Sie das Thema jetzt ein:*\n\n⏱ Dauert 5-15 Minuten",
        "Українська 🇺🇦": "🔍 *DeepSearch*\n\n✏️ *Введіть тему зараз:*\n\n⏱ Займає 5-15 хвилин",
        "Italiano 🇮🇹": "🔍 *DeepSearch*\n\n✏️ *Scrivi l'argomento ora:*\n\n⏱ Richiede 5-15 minuti",
        "Español 🇲🇽": "🔍 *DeepSearch*\n\n✏️ *Escribe el tema ahora:*\n\n⏱ Tarda 5-15 minutos",
    }
    prompt_text = _deep_ask.get(lang, _deep_ask["English 🇬🇧"])
    sent = bot.send_message(call.message.chat.id, prompt_text, parse_mode="Markdown")

    def _wait_for_deep_topic(msg):
        topic = msg.text.strip() if msg.text else ''
        if not topic or topic.startswith('/'):
            bot.send_message(msg.chat.id, "⚠️ الموضوع فارغ. جرّب مرة أخرى عبر /deepsearch" if lang == "العربية 🇮🇶" else "⚠️ Empty topic. Try /deepsearch again")
            return
        if _deepsearch_active.get(str(uid)):
            bot.send_message(msg.chat.id, "⏳ بحث سابق لا يزال جارياً" if lang == "العربية 🇮🇶" else "⏳ Previous search still running")
            return
        _deepsearch_active[str(uid)] = True
        start_msgs = {
            "العربية 🇮🇶": (
                f"🔍 *DeepSearch بدأ*\n\n📌 الموضوع: *{topic}*\n\n"
                f"⏳ جاري فحص:\n• مصادر RSS العربية والدولية\n"
                f"• مواقع إخبارية بالسكرابنق\n• المصادر الرسمية والحكومية\n"
                f"• قاعدة بيانات NewsAPI العالمية\n• تحليل عميق بالذكاء الاصطناعي\n\n_قد يستغرق 5-15 دقيقة..._"
            ),
            "English 🇬🇧": (
                f"🔍 *DeepSearch Started*\n\n📌 Topic: *{topic}*\n\n"
                f"⏳ Scanning:\n• Arabic & international RSS feeds\n"
                f"• News sites via scraping\n• Official & government sources\n"
                f"• NewsAPI global database\n• Deep AI analysis\n\n_May take 5-15 minutes..._"
            ),
        }
        progress_msg = bot.send_message(
            msg.chat.id,
            start_msgs.get(lang, start_msgs["English 🇬🇧"]),
            parse_mode="Markdown"
        )
        import threading as _thr
        _thr.Thread(
            target=_deepsearch_worker,
            args=(uid, topic, progress_msg.message_id, msg.chat.id),
            daemon=True
        ).start()

    bot.register_next_step_handler(sent, _wait_for_deep_topic)

@bot.callback_query_handler(func=lambda c: c.data == "menu_ai")
def cb_menu_ai(call):
    lang = users.get(str(call.from_user.id), {}).get('lang', 'العربية 🇮🇶')
    bot.answer_callback_query(call.id)
    titles = {"العربية 🇮🇶": "🧠 *تحليل الذكاء الاصطناعي*\nاختر ما تريد:", "English 🇬🇧": "🧠 *AI Analysis*\nChoose:"}
    kb = _build_ai_menu(lang)
    try:
        bot.edit_message_text(titles.get(lang, titles["English 🇬🇧"]),
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, titles.get(lang, titles["English 🇬🇧"]),
            parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "menu_sports")
def cb_menu_sports(call):
    bot.answer_callback_query(call.id)
    try:
        uid2 = call.from_user.id
        lang2 = users.get(str(uid2), {}).get("lang", "English 🇬🇧")
        prefs = _get_user_sports(uid2)
        selected = prefs.get('leagues', [])
        leagues_text = _ul(lang2, "sports_leagues", n=len(selected)) if selected else _ul(lang2, "sports_no_leagues")
        alerts_text = _ul(lang2, "sports_alerts_on") if prefs.get("live_alerts") else _ul(lang2, "sports_alerts_off")
        text = (
            _ul(lang2, "sports_title")
            + f"📊 {leagues_text}\n"
            + f"🔔 {alerts_text}\n\n"
            + _ul(lang2, "sports_choose")
        )
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown",
                         reply_markup=_sports_main_keyboard(uid2))
    except Exception:
        bot.send_message(call.message.chat.id, "أرسل /sports للرياضة")

@bot.callback_query_handler(func=lambda c: c.data == "menu_weather")
def cb_menu_weather(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    user = users.get(str(uid))
    if not user or not user.get("province"):
        bot.send_message(call.message.chat.id, "⚠️ لم تحدد مدينتك بعد. أرسل /start لإعداد حسابك.")
        return
    send_detailed_weather(uid)

@bot.callback_query_handler(func=lambda c: c.data == "menu_markets")
def cb_menu_markets(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    user = users.get(str(uid))
    if not user:
        bot.send_message(call.message.chat.id, "⚠️ أرسل /start أولاً.")
        return
    send_currency(uid)

@bot.callback_query_handler(func=lambda c: c.data == "menu_settings")
def cb_menu_settings(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    user = users.get(str(uid))
    if not user:
        bot.send_message(call.message.chat.id, "⚠️ أرسل /start أولاً.")
        return
    class _FakeMsg:
        from_user = type("U", (), {"id": uid})()
        chat = type("C", (), {"id": uid, "type": "private"})()
    cmd_settings_private(_FakeMsg())

@bot.callback_query_handler(func=lambda c: c.data == "menu_help")
def cb_menu_help(call):
    uid = call.from_user.id
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
    bot.answer_callback_query(call.id)
    # دالة مساعدة لبناء النص حسب اللغة
    _help_texts = {
        "العربية 🇮🇶":
            "📖 *دليل الأوامر*\n\n"
            "📰 `/news` — آخر الأخبار\n"
            "🔍 `/deepsearch موضوع` — بحث عميق\n"
            "✅ `/verify خبر` — كشف الأخبار الكاذبة\n"
            "🧠 `/analyze خبر` — تحليل سياسي\n"
            "🌐 `/compare موضوع` — مقارنة مصادر\n"
            "📅 `/timeline موضوع` — خط زمني\n"
            "🔮 `/predict موضوع` — توقعات\n"
            "🗺 `/influence اسم` — خريطة نفوذ\n"
            "🕵️ `/profile اسم` — ملف شخصية\n"
            "🏛 `/parliament` — ملخص البرلمان\n"
            "💬 `/ask سؤال` — اسألني\n"
            "📉 `/econ` — مؤشرات اقتصادية\n"
            "🔴 `/live حدث` — بث مباشر\n"
            "📢 `/submit خبر` — شارك خبراً\n"
            "📊 `/sources` — تصنيف المصادر\n"
            "🏅 `/sports` — الرياضة\n"
            "🌤 `/weather مدينة` — الطقس\n"
            "💱 `/currency` — العملات\n"
            "⚙️ `/settings` — الإعدادات",
        "Русский 🇷🇺":
            "📖 *Руководство по командам*\n\n"
            "📰 `/news` — Последние новости\n"
            "🔍 `/deepsearch тема` — Глубокий поиск\n"
            "✅ `/verify заголовок` — Проверка новости\n"
            "🧠 `/analyze заголовок` — Политический анализ\n"
            "🌐 `/compare тема` — Сравнение источников\n"
            "📅 `/timeline тема` — Хронология событий\n"
            "🔮 `/predict тема` — Прогнозы\n"
            "🗺 `/influence имя` — Карта влияния\n"
            "🕵️ `/profile имя` — Профиль личности\n"
            "🏛 `/parliament` — Краткое изложение\n"
            "💬 `/ask вопрос` — Задать вопрос\n"
            "📉 `/econ` — Экономические показатели\n"
            "🔴 `/live событие` — Прямой эфир\n"
            "📢 `/submit новость` — Поделиться\n"
            "🏅 `/sports` — Спорт\n"
            "🌤 `/weather город` — Погода\n"
            "💱 `/currency` — Курсы валют\n"
            "⚙️ `/settings` — Настройки",
        "فارسی 🇮🇷":
            "📖 *راهنمای دستورات*\n\n"
            "📰 `/news` — آخرین اخبار\n"
            "🔍 `/deepsearch موضوع` — جستجوی عمیق\n"
            "✅ `/verify خبر` — تأیید خبر\n"
            "🧠 `/analyze خبر` — تحلیل سیاسی\n"
            "🌐 `/compare موضوع` — مقایسه منابع\n"
            "📅 `/timeline موضوع` — خط زمانی\n"
            "🔮 `/predict موضوع` — پیشبینی\n"
            "🗺 `/influence نام` — نقشه نفوذ\n"
            "🕵️ `/profile نام` — پروفایل\n"
            "🏛 `/parliament` — خلاصه پارلمان\n"
            "💬 `/ask سوال` — بپرس\n"
            "📉 `/econ` — شاخصهای اقتصادی\n"
            "🔴 `/live رویداد` — زنده\n"
            "📢 `/submit خبر` — ارسال خبر\n"
            "🏅 `/sports` — ورزش\n"
            "🌤 `/weather شهر` — آبوهوا\n"
            "💱 `/currency` — نرخ ارز\n"
            "⚙️ `/settings` — تنظیمات",
        "हिन्दी 🇮🇳":
            "📖 *कमांड गाइड*\n\n"
            "📰 `/news` — ताज़ा समाचार\n"
            "🔍 `/deepsearch विषय` — गहन खोज\n"
            "✅ `/verify शीर्षक` — समाचार जांच\n"
            "🧠 `/analyze शीर्षक` — राजनीतिक विश्लेषण\n"
            "🌐 `/compare विषय` — स्रोत तुलना\n"
            "📅 `/timeline विषय` — समयरेखा\n"
            "🔮 `/predict विषय` — भविष्यवाणी\n"
            "🗺 `/influence नाम` — प्रभाव मानचित्र\n"
            "🕵️ `/profile नाम` — व्यक्ति प्रोफ़ाइल\n"
            "🏛 `/parliament` — संसद सारांश\n"
            "💬 `/ask प्रश्न` — मुझसे पूछें\n"
            "📉 `/econ` — आर्थिक संकेतक\n"
            "🔴 `/live इवेंट` — लाइव ट्रैकिंग\n"
            "📢 `/submit समाचार` — समाचार भेजें\n"
            "🏅 `/sports` — खेल\n"
            "🌤 `/weather शहर` — मौसम\n"
            "💱 `/currency` — मुद्रा दरें\n"
            "⚙️ `/settings` — सेटिंग्स",
        "Português 🇧🇷":
            "📖 *Guia de Comandos*\n\n"
            "📰 `/news` — Últimas notícias\n"
            "🔍 `/deepsearch tópico` — Pesquisa profunda\n"
            "✅ `/verify manchete` — Verificar notícia\n"
            "🧠 `/analyze manchete` — Análise política\n"
            "🌐 `/compare tópico` — Comparar fontes\n"
            "📅 `/timeline tópico` — Linha do tempo\n"
            "🔮 `/predict tópico` — Previsões\n"
            "🗺 `/influence nome` — Mapa de influência\n"
            "🕵️ `/profile nome` — Perfil de pessoa\n"
            "🏛 `/parliament` — Resumo do parlamento\n"
            "💬 `/ask pergunta` — Pergunte-me\n"
            "📉 `/econ` — Indicadores econômicos\n"
            "🔴 `/live evento` — Ao vivo\n"
            "📢 `/submit notícia` — Enviar notícia\n"
            "🏅 `/sports` — Esportes\n"
            "🌤 `/weather cidade` — Clima\n"
            "💱 `/currency` — Taxas de câmbio\n"
            "⚙️ `/settings` — Configurações",
        "Türkçe 🇹🇷":
            "📖 *Komut Rehberi*\n\n"
            "📰 `/news` — Son haberler\n"
            "🔍 `/deepsearch konu` — Derin araştırma\n"
            "✅ `/verify başlık` — Haber doğrula\n"
            "🧠 `/analyze başlık` — Siyasi analiz\n"
            "🌐 `/compare konu` — Kaynak karşılaştır\n"
            "📅 `/timeline konu` — Zaman çizelgesi\n"
            "🔮 `/predict konu` — Tahminler\n"
            "🗺 `/influence isim` — Nüfuz haritası\n"
            "🕵️ `/profile isim` — Kişi profili\n"
            "🏛 `/parliament` — Parlamento özeti\n"
            "💬 `/ask soru` — Bana sor\n"
            "📉 `/econ` — Ekonomik göstergeler\n"
            "🔴 `/live etkinlik` — Canlı takip\n"
            "📢 `/submit haber` — Haber gönder\n"
            "🏅 `/sports` — Spor\n"
            "🌤 `/weather şehir` — Hava durumu\n"
            "💱 `/currency` — Döviz kurları\n"
            "⚙️ `/settings` — Ayarlar",
        "اردو 🇵🇰":
            "📖 *کمانڈ گائیڈ*\n\n"
            "📰 `/news` — تازہ خبریں\n"
            "🔍 `/deepsearch موضوع` — گہری تحقیق\n"
            "✅ `/verify خبر` — خبر کی تصدیق\n"
            "🧠 `/analyze خبر` — سیاسی تجزیہ\n"
            "🌐 `/compare موضوع` — ذرائع کا موازنہ\n"
            "📅 `/timeline موضوع` — وقت کی لکیر\n"
            "🔮 `/predict موضوع` — پیشن گوئیاں\n"
            "🗺 `/influence نام` — اثر کا نقشہ\n"
            "🕵️ `/profile نام` — شخصیت پروفائل\n"
            "🏛 `/parliament` — پارلیمنٹ خلاصہ\n"
            "💬 `/ask سوال` — مجھ سے پوچھیں\n"
            "📉 `/econ` — معاشی اشارے\n"
            "🔴 `/live تقریب` — براہ راست\n"
            "📢 `/submit خبر` — خبر بھیجیں\n"
            "🏅 `/sports` — کھیل\n"
            "🌤 `/weather شہر` — موسم\n"
            "💱 `/currency` — کرنسی ریٹس\n"
            "⚙️ `/settings` — ترتیبات",
        "Deutsch 🇩🇪":
            "📖 *Befehlsanleitung*\n\n"
            "📰 `/news` — Aktuelle Nachrichten\n"
            "🔍 `/deepsearch Thema` — Tiefenrecherche\n"
            "✅ `/verify Überschrift` — Nachricht prüfen\n"
            "🧠 `/analyze Überschrift` — Politische Analyse\n"
            "🌐 `/compare Thema` — Quellen vergleichen\n"
            "📅 `/timeline Thema` — Zeitlinie\n"
            "🔮 `/predict Thema` — Vorhersagen\n"
            "🗺 `/influence Name` — Einfluss-Karte\n"
            "🕵️ `/profile Name` — Personen-Profil\n"
            "🏛 `/parliament` — Parlamentszusammenfassung\n"
            "💬 `/ask Frage` — Frag mich\n"
            "📉 `/econ` — Wirtschaftsindikatoren\n"
            "🔴 `/live Ereignis` — Live-Verfolgung\n"
            "📢 `/submit Nachricht` — Nachricht einreichen\n"
            "🏅 `/sports` — Sport\n"
            "🌤 `/weather Stadt` — Wetter\n"
            "💱 `/currency` — Währungskurse\n"
            "⚙️ `/settings` — Einstellungen",
        "Українська 🇺🇦":
            "📖 *Посібник команд*\n\n"
            "📰 `/news` — Останні новини\n"
            "🔍 `/deepsearch тема` — Глибокий пошук\n"
            "✅ `/verify заголовок` — Перевірка новини\n"
            "🧠 `/analyze заголовок` — Політичний аналіз\n"
            "🌐 `/compare тема` — Порівняння джерел\n"
            "📅 `/timeline тема` — Хронологія\n"
            "🔮 `/predict тема` — Прогнози\n"
            "🗺 `/influence ім\'я` — Карта впливу\n"
            "🕵️ `/profile ім\'я` — Профіль особи\n"
            "🏛 `/parliament` — Зведення парламенту\n"
            "💬 `/ask питання` — Запитай мене\n"
            "📉 `/econ` — Економічні показники\n"
            "🔴 `/live подія` — Пряма трансляція\n"
            "📢 `/submit новина` — Надіслати новину\n"
            "🏅 `/sports` — Спорт\n"
            "🌤 `/weather місто` — Погода\n"
            "💱 `/currency` — Курси валют\n"
            "⚙️ `/settings` — Налаштування",
        "Italiano 🇮🇹":
            "📖 *Guida ai Comandi*\n\n"
            "📰 `/news` — Ultime notizie\n"
            "🔍 `/deepsearch argomento` — Ricerca approfondita\n"
            "✅ `/verify titolo` — Verifica notizia\n"
            "🧠 `/analyze titolo` — Analisi politica\n"
            "🌐 `/compare argomento` — Confronta fonti\n"
            "📅 `/timeline argomento` — Linea del tempo\n"
            "🔮 `/predict argomento` — Previsioni\n"
            "🗺 `/influence nome` — Mappa influenza\n"
            "🕵️ `/profile nome` — Profilo persona\n"
            "🏛 `/parliament` — Riepilogo parlamento\n"
            "💬 `/ask domanda` — Chiedimi\n"
            "📉 `/econ` — Indicatori economici\n"
            "🔴 `/live evento` — Evento live\n"
            "📢 `/submit notizia` — Invia notizia\n"
            "🏅 `/sports` — Sport\n"
            "🌤 `/weather città` — Meteo\n"
            "💱 `/currency` — Tassi di cambio\n"
            "⚙️ `/settings` — Impostazioni",
        "Español 🇲🇽":
            "📖 *Guía de Comandos*\n\n"
            "📰 `/news` — Últimas noticias\n"
            "🔍 `/deepsearch tema` — Búsqueda profunda\n"
            "✅ `/verify titular` — Verificar noticia\n"
            "🧠 `/analyze titular` — Análisis político\n"
            "🌐 `/compare tema` — Comparar fuentes\n"
            "📅 `/timeline tema` — Línea de tiempo\n"
            "🔮 `/predict tema` — Predicciones\n"
            "🗺 `/influence nombre` — Mapa de influencia\n"
            "🕵️ `/profile nombre` — Perfil de persona\n"
            "🏛 `/parliament` — Resumen del parlamento\n"
            "💬 `/ask pregunta` — Pregúntame\n"
            "📉 `/econ` — Indicadores económicos\n"
            "🔴 `/live evento` — Seguimiento en vivo\n"
            "📢 `/submit noticia` — Enviar noticia\n"
            "🏅 `/sports` — Deportes\n"
            "🌤 `/weather ciudad` — Clima\n"
            "💱 `/currency` — Tipos de cambio\n"
            "⚙️ `/settings` — Configuración",
    }
    bot.send_message(call.message.chat.id,
        _help_texts.get(lang, _help_texts["English 🇬🇧"]), parse_mode="Markdown")

# ─── AI Menu callbacks ───────────────────────────────────────────
_aimenu_prompts = {
    "aimenu_verify": {
        "العربية 🇮🇶":   "أرسل:\n`/verify عنوان الخبر`",
        "English 🇬🇧":   "Send:\n`/verify headline`",
        "Русский 🇷🇺":   "Отправьте:\n`/verify заголовок`",
        "فارسی 🇮🇷":    "ارسال:\n`/verify تیتر خبر`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/verify शीर्षक`",
        "Português 🇧🇷": "Envie:\n`/verify manchete`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/verify başlık`",
        "اردو 🇵🇰":     "بھیجیں:\n`/verify خبر کا عنوان`",
        "Deutsch 🇩🇪":  "Senden:\n`/verify Schlagzeile`",
        "Українська 🇺🇦": "Надішліть:\n`/verify заголовок`",
        "Italiano 🇮🇹": "Invia:\n`/verify titolo`",
        "Español 🇲🇽":  "Envía:\n`/verify titular`",
    },
    "aimenu_analyze": {
        "العربية 🇮🇶":   "أرسل:\n`/analyze عنوان الخبر`",
        "English 🇬🇧":   "Send:\n`/analyze headline`",
        "Русский 🇷🇺":   "Отправьте:\n`/analyze заголовок`",
        "فارسی 🇮🇷":    "ارسال:\n`/analyze تیتر خبر`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/analyze शीर्षक`",
        "Português 🇧🇷": "Envie:\n`/analyze manchete`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/analyze başlık`",
        "اردو 🇵🇰":     "بھیجیں:\n`/analyze خبر کا عنوان`",
        "Deutsch 🇩🇪":  "Senden:\n`/analyze Schlagzeile`",
        "Українська 🇺🇦": "Надішліть:\n`/analyze заголовок`",
        "Italiano 🇮🇹": "Invia:\n`/analyze titolo`",
        "Español 🇲🇽":  "Envía:\n`/analyze titular`",
    },
    "aimenu_compare": {
        "العربية 🇮🇶":   "أرسل:\n`/compare الموضوع`",
        "English 🇬🇧":   "Send:\n`/compare topic`",
        "Русский 🇷🇺":   "Отправьте:\n`/compare тема`",
        "فارسی 🇮🇷":    "ارسال:\n`/compare موضوع`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/compare विषय`",
        "Português 🇧🇷": "Envie:\n`/compare tópico`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/compare konu`",
        "اردو 🇵🇰":     "بھیجیں:\n`/compare موضوع`",
        "Deutsch 🇩🇪":  "Senden:\n`/compare Thema`",
        "Українська 🇺🇦": "Надішліть:\n`/compare тема`",
        "Italiano 🇮🇹": "Invia:\n`/compare argomento`",
        "Español 🇲🇽":  "Envía:\n`/compare tema`",
    },
    "aimenu_timeline": {
        "العربية 🇮🇶":   "أرسل:\n`/timeline الموضوع`",
        "English 🇬🇧":   "Send:\n`/timeline topic`",
        "Русский 🇷🇺":   "Отправьте:\n`/timeline тема`",
        "فارسی 🇮🇷":    "ارسال:\n`/timeline موضوع`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/timeline विषय`",
        "Português 🇧🇷": "Envie:\n`/timeline tópico`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/timeline konu`",
        "اردو 🇵🇰":     "بھیجیں:\n`/timeline موضوع`",
        "Deutsch 🇩🇪":  "Senden:\n`/timeline Thema`",
        "Українська 🇺🇦": "Надішліть:\n`/timeline тема`",
        "Italiano 🇮🇹": "Invia:\n`/timeline argomento`",
        "Español 🇲🇽":  "Envía:\n`/timeline tema`",
    },
    "aimenu_predict": {
        "العربية 🇮🇶":   "أرسل:\n`/predict الموضوع`",
        "English 🇬🇧":   "Send:\n`/predict topic`",
        "Русский 🇷🇺":   "Отправьте:\n`/predict тема`",
        "فارسی 🇮🇷":    "ارسال:\n`/predict موضوع`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/predict विषय`",
        "Português 🇧🇷": "Envie:\n`/predict tópico`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/predict konu`",
        "اردو 🇵🇰":     "بھیجیں:\n`/predict موضوع`",
        "Deutsch 🇩🇪":  "Senden:\n`/predict Thema`",
        "Українська 🇺🇦": "Надішліть:\n`/predict тема`",
        "Italiano 🇮🇹": "Invia:\n`/predict argomento`",
        "Español 🇲🇽":  "Envía:\n`/predict tema`",
    },
    "aimenu_influence": {
        "العربية 🇮🇶":   "أرسل:\n`/influence الاسم`",
        "English 🇬🇧":   "Send:\n`/influence name`",
        "Русский 🇷🇺":   "Отправьте:\n`/influence имя`",
        "فارسی 🇮🇷":    "ارسال:\n`/influence نام`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/influence नाम`",
        "Português 🇧🇷": "Envie:\n`/influence nome`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/influence ad`",
        "اردو 🇵🇰":     "بھیجیں:\n`/influence نام`",
        "Deutsch 🇩🇪":  "Senden:\n`/influence Name`",
        "Українська 🇺🇦": "Надішліть:\n`/influence ім'я`",
        "Italiano 🇮🇹": "Invia:\n`/influence nome`",
        "Español 🇲🇽":  "Envía:\n`/influence nombre`",
    },
    "aimenu_profile": {
        "العربية 🇮🇶":   "أرسل:\n`/profile الاسم`",
        "English 🇬🇧":   "Send:\n`/profile name`",
        "Русский 🇷🇺":   "Отправьте:\n`/profile имя`",
        "فارسی 🇮🇷":    "ارسال:\n`/profile نام`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/profile नाम`",
        "Português 🇧🇷": "Envie:\n`/profile nome`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/profile ad`",
        "اردو 🇵🇰":     "بھیجیں:\n`/profile نام`",
        "Deutsch 🇩🇪":  "Senden:\n`/profile Name`",
        "Українська 🇺🇦": "Надішліть:\n`/profile ім'я`",
        "Italiano 🇮🇹": "Invia:\n`/profile nome`",
        "Español 🇲🇽":  "Envía:\n`/profile nombre`",
    },
    "aimenu_ask": {
        "العربية 🇮🇶":   "أرسل:\n`/ask سؤالك`",
        "English 🇬🇧":   "Send:\n`/ask your question`",
        "Русский 🇷🇺":   "Отправьте:\n`/ask ваш вопрос`",
        "فارسی 🇮🇷":    "ارسال:\n`/ask سوال شما`",
        "हिन्दी 🇮🇳":   "भेजें:\n`/ask आपका प्रश्न`",
        "Português 🇧🇷": "Envie:\n`/ask sua pergunta`",
        "Türkçe 🇹🇷":   "Gönderin:\n`/ask sorunuz`",
        "اردو 🇵🇰":     "بھیجیں:\n`/ask آپ کا سوال`",
        "Deutsch 🇩🇪":  "Senden:\n`/ask Ihre Frage`",
        "Українська 🇺🇦": "Надішліть:\n`/ask ваше питання`",
        "Italiano 🇮🇹": "Invia:\n`/ask la tua domanda`",
        "Español 🇲🇽":  "Envía:\n`/ask tu pregunta`",
    },
    "aimenu_parliament": {
        "العربية 🇮🇶":   "أرسل:\n`/parliament`\nللحصول على ملخص جلسات البرلمان",
        "English 🇬🇧":   "Send:\n`/parliament`\nTo get parliament session summaries",
        "Русский 🇷🇺":   "Отправьте:\n`/parliament`\nДля сводки заседаний парламента",
        "فارسی 🇮🇷":    "ارسال:\n`/parliament`\nبرای خلاصه جلسات پارلمان",
        "हिन्दी 🇮🇳":   "भेजें:\n`/parliament`\nसंसद सत्र सारांश के लिए",
        "Português 🇧🇷": "Envie:\n`/parliament`\nPara resumos das sessões do parlamento",
        "Türkçe 🇹🇷":   "Gönderin:\n`/parliament`\nMeclis oturumu özetleri için",
        "اردو 🇵🇰":     "بھیجیں:\n`/parliament`\nپارلیمنٹ کے اجلاس کے خلاصوں کے لیے",
        "Deutsch 🇩🇪":  "Senden:\n`/parliament`\nFür Parlamentssitzungs-Zusammenfassungen",
        "Українська 🇺🇦": "Надішліть:\n`/parliament`\nДля зведень засідань парламенту",
        "Italiano 🇮🇹": "Invia:\n`/parliament`\nPer i riepiloghi delle sessioni parlamentari",
        "Español 🇲🇽":  "Envía:\n`/parliament`\nPara resúmenes de sesiones parlamentarias",
    },
    "aimenu_econ": {
        "العربية 🇮🇶":   "أرسل:\n`/econ`\nللحصول على التقرير الاقتصادي",
        "English 🇬🇧":   "Send:\n`/econ`\nTo get the economic report",
        "Русский 🇷🇺":   "Отправьте:\n`/econ`\nДля получения экономического отчёта",
        "فارسی 🇮🇷":    "ارسال:\n`/econ`\nبرای دریافت گزارش اقتصادی",
        "हिन्दी 🇮🇳":   "भेजें:\n`/econ`\nआर्थिक रिपोर्ट के लिए",
        "Português 🇧🇷": "Envie:\n`/econ`\nPara obter o relatório econômico",
        "Türkçe 🇹🇷":   "Gönderin:\n`/econ`\nEkonomik rapor için",
        "اردو 🇵🇰":     "بھیجیں:\n`/econ`\nاقتصادی رپورٹ کے لیے",
        "Deutsch 🇩🇪":  "Senden:\n`/econ`\nFür den Wirtschaftsbericht",
        "Українська 🇺🇦": "Надішліть:\n`/econ`\nДля отримання економічного звіту",
        "Italiano 🇮🇹": "Invia:\n`/econ`\nPer ottenere il rapporto economico",
        "Español 🇲🇽":  "Envía:\n`/econ`\nPara obtener el informe económico",
    },
    "aimenu_live": {
        "العربية 🇮🇶":   "أرسل:\n`/live اسم الحدث`\nللمتابعة اللحظية",
        "English 🇬🇧":   "Send:\n`/live event name`\nFor live coverage",
        "Русский 🇷🇺":   "Отправьте:\n`/live название события`\nДля прямого освещения",
        "فارسی 🇮🇷":    "ارسال:\n`/live نام رویداد`\nبرای پوشش زنده",
        "हिन्दी 🇮🇳":   "भेजें:\n`/live घटना का नाम`\nलाइव कवरेज के लिए",
        "Português 🇧🇷": "Envie:\n`/live nome do evento`\nPara cobertura ao vivo",
        "Türkçe 🇹🇷":   "Gönderin:\n`/live etkinlik adı`\nCanlı yayın için",
        "اردو 🇵🇰":     "بھیجیں:\n`/live واقعہ کا نام`\nلائیو کوریج کے لیے",
        "Deutsch 🇩🇪":  "Senden:\n`/live Ereignisname`\nFür Live-Berichterstattung",
        "Українська 🇺🇦": "Надішліть:\n`/live назва події`\nДля прямого висвітлення",
        "Italiano 🇮🇹": "Invia:\n`/live nome evento`\nPer la copertura in diretta",
        "Español 🇲🇽":  "Envía:\n`/live nombre del evento`\nPara cobertura en vivo",
    },
    "aimenu_submit": {
        "العربية 🇮🇶":   "أرسل:\n`/submit نص الخبر`\nلتقديم خبر للنشر",
        "English 🇬🇧":   "Send:\n`/submit news text`\nTo submit news for publication",
        "Русский 🇷🇺":   "Отправьте:\n`/submit текст новости`\nДля подачи новости на публикацию",
        "فارسی 🇮🇷":    "ارسال:\n`/submit متن خبر`\nبرای ارسال خبر برای انتشار",
        "हिन्दी 🇮🇳":   "भेजें:\n`/submit समाचार पाठ`\nप्रकाशन के लिए समाचार सबमिट करें",
        "Português 🇧🇷": "Envie:\n`/submit texto da notícia`\nPara enviar notícia para publicação",
        "Türkçe 🇹🇷":   "Gönderin:\n`/submit haber metni`\nYayın için haber göndermek için",
        "اردو 🇵🇰":     "بھیجیں:\n`/submit خبر کا متن`\nاشاعت کے لیے خبر جمع کرانے کے لیے",
        "Deutsch 🇩🇪":  "Senden:\n`/submit Nachrichtentext`\nUm eine Nachricht zur Veröffentlichung einzureichen",
        "Українська 🇺🇦": "Надішліть:\n`/submit текст новини`\nДля подачі новини на публікацію",
        "Italiano 🇮🇹": "Invia:\n`/submit testo della notizia`\nPer inviare notizie per la pubblicazione",
        "Español 🇲🇽":  "Envía:\n`/submit texto de la noticia`\nPara enviar noticias para su publicación",
    },
}

@bot.callback_query_handler(func=lambda c: c.data.startswith("aimenu_"))
def cb_aimenu_item(call):
    lang = users.get(str(call.from_user.id), {}).get('lang', 'العربية 🇮🇶')
    prompts = _aimenu_prompts.get(call.data, {})
    text = prompts.get(lang) or prompts.get("English 🇬🇧", "")
    bot.answer_callback_query(call.id)
    if text:
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════
# ميزات الجيل المتقدم
# ═══════════════════════════════════════════════════════════════════

# ─── 1. أرشيف الأخبار ────────────────────────────────────────────
def _archive_news_item(title: str, url: str, source: str, lang: str,
                       summary: str = "", fact: dict = None):
    """يُضيف خبراً للأرشيف مع تنظيف القديم تلقائياً"""
    now = time.time()
    cutoff = now - _NEWS_ARCHIVE_DAYS * 86400
    item = {
        "title": title, "url": url, "source": source, "lang": lang,
        "ts": now, "summary": summary, "fact": fact or {}
    }
    with _news_archive_lock:
        _news_archive.append(item)
        # حذف القديم
        while _news_archive and _news_archive[0]["ts"] < cutoff:
            _news_archive.pop(0)
        # حد أقصى
        if len(_news_archive) > _NEWS_ARCHIVE_MAX:
            del _news_archive[:len(_news_archive) - _NEWS_ARCHIVE_MAX]


def search_news_archive(query: str, lang_filter: str = "", max_results: int = 10) -> list:
    """يبحث في الأرشيف بكلمة مفتاحية"""
    q = query.lower().strip()
    if not q:
        return []
    words = [w for w in q.split() if len(w) > 2]
    results = []
    with _news_archive_lock:
        items = list(reversed(_news_archive))  # الأحدث أولاً
    for item in items:
        if lang_filter and item.get("lang") != lang_filter:
            continue
        title_l = item["title"].lower()
        if any(w in title_l for w in words):
            results.append(item)
        if len(results) >= max_results:
            break
    return results


# ─── 2. تقرير صحة البوت اليومي للأدمن ──────────────────────────
def _send_admin_health_report():
    """يُرسل للأدمن تقريراً شاملاً في الساعة 8 صباحاً يشمل مقاييس النظام."""
    if bot_paused:
        return
    now_h = _now_sa().hour
    if now_h != 8:
        return
    try:
        total_users = len(users)
        active_24h  = sum(
            1 for u in users.values()
            if time.time() - u.get("last_active", 0) < 86400
        )
        with _daily_new_users_lock:
            new_today = len(_daily_new_users)
            _daily_new_users.clear()

        with _broadcast_stats_lock:
            news_sent   = _broadcast_stats.get("today_news_sent", 0)
            users_reach = _broadcast_stats.get("today_users_reached", 0)
            hourly      = _broadcast_stats.get("hourly_activity", {})
            errors      = list(_broadcast_errors[-5:])

        # ساعة الذروة
        peak_h, peak_v = max(hourly.items(), key=lambda x: x[1]) if hourly else ("—", 0)

        # أكثر لغة
        lang_count: dict = {}
        for u in users.values():
            l = u.get("lang", "Unknown")
            lang_count[l] = lang_count.get(l, 0) + 1
        top_lang = max(lang_count, key=lang_count.get) if lang_count else "—"

        # أرشيف
        with _news_archive_lock:
            arc_count = len(_news_archive)

        # غرفة الأزمات
        crisis_status = "🔴 نشطة" if _crisis_room_active else "🟢 هادئة"

        # ── مقاييس النظام (SELF-HEALING ENGINE) ──
        sys_m  = _get_sys_metrics()
        ram    = sys_m.get("ram_pct", _sys_health.get("ram_pct", 0))
        cpu    = sys_m.get("cpu_pct", _sys_health.get("cpu_pct", 0))
        disk   = sys_m.get("disk_pct", _sys_health.get("disk_pct", 0))
        uptime_s  = int(time.time() - _sys_health["start_ts"])
        uptime_h  = uptime_s // 3600
        uptime_m  = (uptime_s % 3600) // 60
        recoveries = _sys_health.get("recoveries", 0)

        # ── أكثر الوظائف خطأً ──
        with _error_freq_lock:
            top_errs = sorted(_error_freq.items(), key=lambda x: x[1], reverse=True)[:3]
        top_err_str = "\n".join(f"  `{fn}`: {cnt}x" for fn, cnt in top_errs) or "  لا أخطاء 🎉"

        # ── القنوات ──
        total_chs = len(channels_groups)

        ram_icon  = "🔴" if ram > 85 else ("🟡" if ram > 65 else "🟢")
        cpu_icon  = "🔴" if cpu > 85 else ("🟡" if cpu > 65 else "🟢")
        disk_icon = "🔴" if disk > 85 else ("🟡" if disk > 65 else "🟢")

        report = (
            f"📊 *تقرير البوت اليومي — {datetime.date.today()}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👥 *المستخدمون*\n"
            f"  إجمالي: `{total_users:,}` | قنوات/مجموعات: `{total_chs}`\n"
            f"  نشط (24h): `{active_24h:,}` | جديد اليوم: `{new_today:,}`\n\n"
            f"📰 *الأخبار*\n"
            f"  بُثّت: `{news_sent:,}` خبر | وصلت لـ `{users_reach:,}` مستخدم\n"
            f"  في الأرشيف: `{arc_count:,}` | أكثر لغة: `{top_lang}`\n"
            f"  ساعة الذروة: `{peak_h}:00` — `{peak_v:,}` إرسال\n\n"
            f"🖥 *صحة النظام*\n"
            f"  {ram_icon} RAM: `{ram:.1f}%` | {cpu_icon} CPU: `{cpu:.1f}%` | {disk_icon} Disk: `{disk:.1f}%`\n"
            f"  ⏱ Uptime: `{uptime_h}h {uptime_m}m` | 🔄 تعافيات تلقائية: `{recoveries}`\n\n"
            f"🛡 *الاستقرار*\n"
            f"  غرفة الأزمات: {crisis_status}\n"
            f"  أخطاء البث: `{len(errors)}`\n"
            f"  أكثر الوظائف خطأً:\n{top_err_str}\n"
        )
        if errors:
            report += "\n*آخر أخطاء البث:*\n" + "\n".join(f"`{e[-100:]}`" for e in errors)

        bot.send_message(ADMIN_ID, report, parse_mode="Markdown")
    except Exception as _e:
        _logger.error("[HealthReport] %s", _e)


# ─── 3. غرفة الأزمات المتقدمة ────────────────────────────────────
def _crisis_room_broadcaster():
    """
    عند تفعيل وضع الأزمة: يُرسل تحديثات كل 30 ثانية ويبني خط زمني
    ثم يُرسل تقريراً استخباراتياً AI كاملاً
    """
    global _crisis_room_active, _crisis_room_keyword, _crisis_room_timeline
    global _crisis_room_start, _crisis_report_sent_at

    if bot_paused:
        return

    # كشف الأزمة الجديدة من _crisis_keyword_freq
    with _crisis_room_lock:
        if not _crisis_room_active:
            now = time.time()
            for kw, times in list(_crisis_keyword_freq.items()):
                recent = [t for t in times if now - t < 600]  # آخر 10 دقائق
                if len(recent) >= _CRISIS_THRESHOLD + 2:       # حد أعلى من المراقبة العادية
                    _crisis_room_active  = True
                    _crisis_room_keyword = kw
                    _crisis_room_start   = now
                    _crisis_room_timeline = []
                    _crisis_report_sent_at = 0.0
                    # إشعار الأدمن
                    try:
                        bot.send_message(
                            ADMIN_ID,
                            f"🚨 *غرفة الأزمات تفعّلت!*\n"
                            f"الكلمة المفتاحية: `{kw}`\n"
                            f"عدد الإشارات: `{len(recent)}` في 10 دقائق\n"
                            f"سيبدأ البث الفوري الآن...",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                    break
            if not _crisis_room_active:
                return

    # جمع تحديثات جديدة خلال وضع الأزمة
    now = time.time()
    # إيقاف تلقائي بعد 3 ساعات
    if now - _crisis_room_start > 3 * 3600:
        with _crisis_room_lock:
            _crisis_room_active = False
            _crisis_room_keyword = ""
        try:
            bot.send_message(ADMIN_ID, "✅ غرفة الأزمات: انتهى وضع الأزمة تلقائياً (3 ساعات)")
        except Exception:
            pass
        return

    kw = _crisis_room_keyword
    new_items = []
    for feed_url in list(RSS.get("العربية 🇮🇶", []))[:12]:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:5]:
                title = getattr(entry, 'title', '')
                if kw.lower() in title.lower():
                    link = getattr(entry, 'link', '')
                    time_str = _now_sa().strftime("%H:%M:%S")
                    item = {"time_str": time_str, "text": title, "source": feed_url[:40]}
                    # تجنب التكرار
                    existing_texts = {x["text"] for x in _crisis_room_timeline}
                    if title not in existing_texts:
                        new_items.append(item)
        except Exception:
            pass

    if new_items:
        with _crisis_room_lock:
            _crisis_room_timeline.extend(new_items)

        # إرسال التحديثات للمستخدمين ذوي تنبيهات الأزمة
        for uid_s, uinfo in list(users.items()):
            try:
                if not uinfo.get("notifications", True):
                    continue
                if int(uid_s) in banned:
                    continue
                level = uinfo.get("alert_level", "medium")
                if level not in ("high", "critical"):
                    continue
                for it in new_items[:3]:
                    bot.send_message(
                        int(uid_s),
                        f"🚨 *[غرفة الأزمات]* `{kw}`\n"
                        f"🕐 `{it['time_str']}`\n\n"
                        f"📌 {it['text']}",
                        parse_mode="Markdown"
                    )
                    time.sleep(0.05)
            except Exception:
                pass

    # إرسال التقرير الاستخباراتي كل 30 دقيقة
    if now - _crisis_report_sent_at > 1800 and len(_crisis_room_timeline) >= 5:
        with _crisis_room_lock:
            timeline_copy = list(_crisis_room_timeline)
        report_text = _ai_crisis_intelligence_report(kw, timeline_copy)
        if report_text:
            msg = (
                f"🕵️ *تقرير استخباراتي — أزمة: {kw}*\n"
                f"📅 {_now_sa().strftime('%H:%M')} (توقيت السعودية) | "
                f"{len(timeline_copy)} حدث مرصود\n"
                f"━━━━━━━━━━━━━━\n"
                f"{report_text[:3500]}"
            )
            # إرسال للأدمن
            try:
                bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
            except Exception:
                pass
            # إرسال للمستخدمين critical
            for uid_s, uinfo in list(users.items()):
                try:
                    if uinfo.get("alert_level") == "critical" and uinfo.get("notifications", True):
                        bot.send_message(int(uid_s), msg[:4096], parse_mode="Markdown")
                        time.sleep(0.05)
                except Exception:
                    pass
            _crisis_report_sent_at = now


# ─── 4. كاشف تناقضات السياسيين ───────────────────────────────────
def _politician_statement_tracker():
    """
    يفحص الأخبار الجديدة، يستخرج تصريحات السياسيين،
    ويبحث عن تناقضات مع تصريحاتهم السابقة
    """
    if bot_paused:
        return
    try:
        for feed_url in list(RSS.get("العربية 🇮🇶", []))[:10]:
            try:
                feed = _parse_feed(feed_url)
                if not feed:
                    continue
                for entry in feed.entries[:8]:
                    title = getattr(entry, 'title', '') or ''
                    summary = getattr(entry, 'summary', '') or ''
                    combined = f"{title} {summary}"
                    for name in POLITICIAN_NAMES_WATCH:
                        if name not in combined:
                            continue
                        # استخرج الجملة التي تحتوي على الاسم
                        sentences = combined.split('.')
                        stmt_sentence = next(
                            (s.strip() for s in sentences if name in s and len(s.strip()) > 15),
                            None
                        )
                        if not stmt_sentence:
                            continue
                        with _politician_lock:
                            history = _politician_statements.get(name, [])
                            # تجنب تكرار نفس التصريح
                            if any(stmt_sentence[:50] in h["text"] for h in history[-20:]):
                                continue
                            # إضافة للتاريخ
                            history.append({
                                "text": stmt_sentence,
                                "date": datetime.date.today().isoformat(),
                                "source": feed_url[:50]
                            })
                            _politician_statements[name] = history[-100:]  # الاحتفاظ بآخر 100

                            # فحص التناقض مع آخر تصريح مختلف
                            if len(history) >= 3:
                                old = history[-3]
                                if old["date"] != datetime.date.today().isoformat():
                                    contradiction = _ai_detect_contradiction(
                                        name, old["text"], stmt_sentence, old["date"]
                                    )
                                    if contradiction and "لا تناقض" not in contradiction and len(contradiction) > 20:
                                        alert_msg = (
                                            f"🔍 *كاشف التناقضات السياسية*\n\n"
                                            f"👤 *{name}*\n\n"
                                            f"📅 قبل ({old['date']}):\n_{old['text'][:200]}_\n\n"
                                            f"📅 اليوم:\n_{stmt_sentence[:200]}_\n\n"
                                            f"⚠️ *التحليل:*\n{contradiction[:300]}"
                                        )
                                        # إرسال للأدمن
                                        try:
                                            bot.send_message(ADMIN_ID, alert_msg, parse_mode="Markdown")
                                        except Exception:
                                            pass
                                        # إرسال للمهتمين بالأخبار السياسية
                                        for uid_s, uinfo in list(users.items()):
                                            try:
                                                if int(uid_s) in banned:
                                                    continue
                                                cats = uinfo.get("categories", [])
                                                if "سياسة" in cats or "politics" in str(cats).lower():
                                                    bot.send_message(int(uid_s), alert_msg[:4096], parse_mode="Markdown")
                                                    time.sleep(0.05)
                                            except Exception:
                                                pass
            except Exception:
                pass
    except Exception as _e:
        print(f"[PoliticianTracker] {_e}")


# ─── 5. الخبر قبل الخبر (المراقبة الأجنبية) ─────────────────────
def _foreign_intel_monitor():
    """
    يُراقب وسائل الإعلام الأجنبية ويُرسل الأخبار التي تخص العراق
    قبل أن تغطيها وسائل الإعلام العراقية
    """
    global _foreign_intel_last_run
    if bot_paused:
        return
    now = time.time()
    if now - _foreign_intel_last_run < 1500:  # كل 25 دقيقة
        return
    _foreign_intel_last_run = now

    iraq_news = []
    for feed_url in _FOREIGN_INTEL_FEEDS:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            source_name = getattr(feed.feed, 'title', feed_url[:30])
            for entry in feed.entries[:10]:
                title = getattr(entry, 'title', '') or ''
                summary = getattr(entry, 'summary', '') or ''
                combined = f"{title} {summary}"
                # فلترة: فقط الأخبار ذات الصلة بالعراق
                if not any(w.lower() in combined.lower() for w in _IRAQ_FILTER_WORDS):
                    continue
                if title in _foreign_intel_sent:
                    continue
                _foreign_intel_sent.add(title)
                # تجنب تضخم المجموعة
                if len(_foreign_intel_sent) > 2000:
                    old = list(_foreign_intel_sent)[:500]
                    for o in old:
                        _foreign_intel_sent.discard(o)
                pub_dt = _pub_dt_from_item(entry)
                age_min = (now - pub_dt.timestamp()) / 60 if pub_dt else 999
                # أخبار الساعات الأربع الأخيرة فقط
                if age_min > 240:
                    continue
                link = getattr(entry, 'link', '')
                iraq_news.append({
                    "title": title, "link": link,
                    "source": source_name, "age_min": int(age_min)
                })
        except Exception:
            pass

    if not iraq_news:
        return

    # إرسال للمستخدمين الذين فعّلوا هذه الميزة أو للأدمن مباشرة
    for item in iraq_news[:5]:
        age_str = f"{item['age_min']}د" if item['age_min'] < 60 else f"{item['age_min']//60}س"
        link_line = f"\n🔗 {item['link']}" if item['link'] else ""
        msg = (
            f"🌐 *رصد دولي — خبر عن العراق*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📺 *{item['source']}*  ·  ⏱ منذ {age_str}\n\n"
            f"📌 {item['title']}"
            f"{link_line}"
        )
        try:
            bot.send_message(ADMIN_ID, msg, parse_mode="Markdown")
        except Exception:
            pass
        for uid_s, uinfo in list(users.items()):
            try:
                if int(uid_s) in banned:
                    continue
                if not uinfo.get("foreign_intel", False):
                    continue
                if not uinfo.get("notifications", True):
                    continue
                bot.send_message(int(uid_s), msg[:4096], parse_mode="Markdown")
                time.sleep(0.04)
            except Exception:
                pass


# ─── 6. الذكاء الجماعي — معالجة البلاغات الواردة ────────────────
def _process_crowd_tips():
    """
    يُراجع البلاغات الواردة من المستخدمين ويُوجّهها للأدمن للموافقة
    """
    if bot_paused:
        return
    with _crowd_tips_lock:
        pending = [t for t in _crowd_tips if t.get("status") == "pending"]

    for tip in pending[:5]:  # حد 5 بلاغات كل دورة
        try:
            uid  = tip.get("uid")
            text = tip.get("text", "")
            ts   = tip.get("time", 0)
            age  = int((time.time() - ts) / 60)
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("✅ نشر", callback_data=f"tip_approve_{uid}_{ts}"),
                types.InlineKeyboardButton("❌ رفض", callback_data=f"tip_reject_{uid}_{ts}")
            )
            bot.send_message(
                ADMIN_ID,
                f"📢 *بلاغ من مستخدم* (منذ {age}د)\n"
                f"المستخدم: `{uid}`\n\n"
                f"_{text[:500]}_",
                parse_mode="Markdown",
                reply_markup=markup
            )
            with _crowd_tips_lock:
                for t in _crowd_tips:
                    if t.get("uid") == uid and t.get("time") == ts:
                        t["status"] = "reviewing"
                        break
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# أوامر الجيل المتقدم (بحث، تحقق، روابط، تاريخ، بلاغ)
# ═══════════════════════════════════════════════════════════════════

@bot.message_handler(commands=['search'])
def handle_search_cmd(message):
    """بحث في أرشيف أخبار آخر 7 أيام"""
    uid  = str(message.from_user.id)
    lang = users.get(uid, {}).get("lang", "العربية 🇮🇶")
    query = message.text.replace('/search', '').strip()
    if not query:
        bot.send_message(message.chat.id,
            "🔍 *بحث في أرشيف الأخبار*\n\nاكتب كلمة مفتاحية:\n`/search الدولار`\n`/search بغداد`",
            parse_mode="Markdown")
        return
    results = search_news_archive(query, lang_filter=lang)
    if not results:
        results = search_news_archive(query)  # بحث بدون فلتر اللغة
    if not results:
        bot.send_message(message.chat.id,
            f"🔍 لا توجد نتائج لـ *{query}* في أرشيف الأخبار (7 أيام).",
            parse_mode="Markdown")
        return
    lines = [f"🔍 *نتائج البحث عن:* `{query}`\n"]
    for i, item in enumerate(results[:10], 1):
        ts_str = datetime.datetime.fromtimestamp(item["ts"]).strftime("%d/%m %H:%M")
        fact   = item.get("fact", {})
        v_icon = fact.get("verdict", "") if fact else ""
        link   = item.get("url", "")
        title  = item["title"][:100]
        lines.append(f"{i}. {v_icon} *{title}*\n   _{item.get('source','')[:30]}_ | `{ts_str}`" +
                     (f"\n   🔗 {link}" if link else ""))
    bot.send_message(message.chat.id, "\n\n".join(lines)[:4096], parse_mode="Markdown",
                     disable_web_page_preview=True)


@bot.message_handler(commands=['verify'])
def handle_verify_cmd(message):
    """محقق الشائعات — يتحقق من أي خبر أو ادعاء"""
    uid  = str(message.from_user.id)
    lang = users.get(uid, {}).get("lang", "العربية 🇮🇶")
    claim = message.text.replace('/verify', '').strip()
    if not claim:
        bot.send_message(message.chat.id,
            "🕵️ *محقق الشائعات*\n\n"
            "أرسل النص الذي تريد التحقق منه:\n"
            "`/verify انهيار الدينار العراقي خلال 24 ساعة`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id,
        f"🕵️ جاري التحقق من: _{claim[:80]}_...", parse_mode="Markdown")
    # جمع أخبار ذات صلة للمقارنة
    keywords = [w for w in claim.split() if len(w) > 3]
    sources_lines = []
    for feed_url in list(RSS.get(lang, RSS.get("العربية 🇮🇶", [])))[:8]:
        try:
            feed = _parse_feed(feed_url)
            if not feed:
                continue
            for entry in feed.entries[:8]:
                title = getattr(entry, 'title', '') or ''
                if any(kw.lower() in title.lower() for kw in keywords):
                    sources_lines.append(f"• {title}")
        except Exception:
            pass
    sources_text = "\n".join(sources_lines[:20]) if sources_lines else "لا توجد أخبار مرتبطة"
    result = _ai_verify_rumor(claim, sources_text)
    verdict   = result.get("verdict", "⚠️")
    conf      = result.get("confidence", 0)
    explain   = result.get("explanation", "")
    first_src = result.get("first_source", "")
    conf_bar  = "█" * (conf // 10) + "░" * (10 - conf // 10)
    reply = (
        f"🕵️ *نتيجة التحقق*\n\n"
        f"📌 _{claim[:120]}_\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"الحكم: *{verdict}*\n"
        f"الثقة: `{conf_bar}` {conf}%\n\n"
        f"📝 {explain}"
    )
    if first_src:
        reply += f"\n\n🔗 أول مصدر: _{first_src}_"
    if sources_lines:
        reply += f"\n\n📰 أخبار مرتبطة: {len(sources_lines)} خبر"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")


@bot.message_handler(commands=['connections'])
def handle_connections_cmd(message):
    """خريطة العلاقات — يكشف الروابط بين الأخبار الأخيرة"""
    uid  = str(message.from_user.id)
    lang = users.get(uid, {}).get("lang", "العربية 🇮🇶")
    msg = bot.send_message(message.chat.id,
        "🕸 *جاري تحليل الأخبار وإيجاد الروابط الخفية...*", parse_mode="Markdown")
    # جمع عناوين آخر الأخبار من الأرشيف
    with _news_archive_lock:
        recent = list(reversed(_news_archive))[:40]
    titles = [it["title"] for it in recent if it.get("lang") == lang or not it.get("lang")]
    if len(titles) < 5:
        # fallback: جمع من RSS
        for feed_url in list(RSS.get(lang, RSS.get("العربية 🇮🇶", [])))[:6]:
            try:
                feed = _parse_feed(feed_url)
                if feed:
                    for e in feed.entries[:5]:
                        t = getattr(e, 'title', '')
                        if t:
                            titles.append(t)
            except Exception:
                pass
    analysis = _ai_find_connections(titles[:30])
    reply = (
        f"🕸 *خريطة العلاقات — آخر {len(titles)} خبر*\n\n"
        f"{analysis[:3800]}"
    )
    try:
        bot.edit_message_text(reply, message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")


@bot.message_handler(commands=['history', 'today'])
def handle_history_cmd(message):
    """ذاكرة الأمة — ماذا جرى في العراق في مثل هذا اليوم"""
    uid  = str(message.from_user.id)
    lang = users.get(uid, {}).get("lang", "العربية 🇮🇶")
    today_fmt = _now_sa().strftime("%d %B")
    msg = bot.send_message(message.chat.id,
        f"📅 *جاري البحث فيما جرى في {today_fmt}...*", parse_mode="Markdown")
    memory = _ai_nation_memory(lang)
    reply = (
        f"📅 *ذاكرة الأمة — {today_fmt}*\n\n"
        f"{memory[:3800]}"
    )
    try:
        bot.edit_message_text(reply, message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")


@bot.message_handler(commands=['tip'])
def handle_tip_cmd(message):
    """الذكاء الجماعي — المستخدم يُرسل خبراً شاهده"""
    uid  = str(message.from_user.id)
    text = message.text.replace('/tip', '').strip()
    if not text or len(text) < 10:
        bot.send_message(message.chat.id,
            "📢 *أرسل لنا خبراً*\n\n"
            "إذا شاهدت حدثاً في شارعك أو مدينتك أرسله:\n"
            "`/tip في الكرادة انفجار صوت قوي الآن`\n\n"
            "سيتم مراجعته ونشره إذا تم التحقق منه.",
            parse_mode="Markdown")
        return
    tip = {
        "uid": uid,
        "text": text,
        "time": time.time(),
        "status": "pending",
        "username": message.from_user.username or f"user_{uid}",
    }
    with _crowd_tips_lock:
        _crowd_tips.append(tip)
        if len(_crowd_tips) > _CROWD_TIP_MAX:
            _crowd_tips.pop(0)
    bot.send_message(message.chat.id,
        "✅ *شكراً! تم استلام تقريرك*\n\nسيتم مراجعته من قِبَل فريقنا وإذا تحقق سيُنشر للجميع.",
        parse_mode="Markdown")
    # إشعار فوري للأدمن
    try:
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ نشر الآن", callback_data=f"tip_approve_{uid}_{int(tip['time'])}"),
            types.InlineKeyboardButton("❌ رفض", callback_data=f"tip_reject_{uid}_{int(tip['time'])}")
        )
        bot.send_message(ADMIN_ID,
            f"📢 *بلاغ جديد من مستخدم*\n"
            f"👤 `{uid}` (@{tip['username']})\n\n"
            f"_{text[:500]}_",
            parse_mode="Markdown", reply_markup=markup)
    except Exception:
        pass


@bot.message_handler(commands=['intel'])
def handle_intel_cmd(message):
    """تفعيل/إيقاف ميزة 'الخبر قبل الخبر' للمستخدم"""
    uid = str(message.from_user.id)
    current = users.get(uid, {}).get("foreign_intel", False)
    users.setdefault(uid, {})["foreign_intel"] = not current
    _save_users_soon()
    status = "✅ مُفعَّل" if not current else "❌ مُوقَف"
    bot.send_message(message.chat.id,
        f"🌐 *الخبر قبل الخبر*\n\n"
        f"الحالة: {status}\n\n"
        f"{'ستصلك الأخبار من المصادر الأجنبية قبل غيرك ✅' if not current else 'أُوقفت هذه الميزة ❌'}",
        parse_mode="Markdown")


# ─── Callbacks: الموافقة/رفض بلاغات الذكاء الجماعي ───────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("tip_approve_") or c.data.startswith("tip_reject_"))
def cb_tip_admin(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ غير مصرح")
        return
    parts = call.data.split("_")
    action = parts[1]   # approve / reject
    tip_uid = parts[2]
    tip_ts  = float(parts[3]) if len(parts) > 3 else 0

    with _crowd_tips_lock:
        tip = next((t for t in _crowd_tips if t.get("uid") == tip_uid and abs(t.get("time", 0) - tip_ts) < 2), None)

    if not tip:
        bot.answer_callback_query(call.id, "❌ البلاغ غير موجود أو انتهى")
        return

    if action == "approve":
        tip["status"] = "approved"
        news_text = (
            f"📢 *خبر من المستخدمين (ذكاء جماعي)*\n\n"
            f"_{tip['text'][:600]}_"
        )
        # بث للجميع
        count = 0
        for uid_s, uinfo in list(users.items()):
            try:
                if int(uid_s) in banned:
                    continue
                if not uinfo.get("notifications", True):
                    continue
                bot.send_message(int(uid_s), news_text, parse_mode="Markdown")
                count += 1
                time.sleep(0.03)
            except Exception:
                pass
        bot.answer_callback_query(call.id, f"✅ نُشر لـ {count} مستخدم")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        # إشعار صاحب البلاغ
        try:
            bot.send_message(int(tip_uid), "🎉 *تم نشر تقريرك!* شكراً على مساهمتك.", parse_mode="Markdown")
        except Exception:
            pass
    else:
        tip["status"] = "rejected"
        bot.answer_callback_query(call.id, "❌ رُفض البلاغ")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass


# ─── Callback: Fact Check من رسالة الخبر ──────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "refresh_dollar_iraqi")
def cb_refresh_dollar_iraqi(call):
    """زر تحديث أسعار الدولار من @dollariraqi"""
    uid = call.from_user.id
    bot.answer_callback_query(call.id, "⏳ جاري التحديث...")
    # مسح الكاش لإجبار إعادة الجلب
    _DOLLAR_IRAQI_CACHE["text"] = None
    _DOLLAR_IRAQI_CACHE["ts"]   = 0.0
    market_text = _fetch_dollariraqi_market()
    now_str = _now_sa().strftime("%H:%M - %d/%m/%Y")
    if market_text:
        msg = (
            f"💵 *أسعار دولار السوق*\n"
            f"🕐 `{now_str}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"{market_text}\n"
            f"━━━━━━━━━━━━━━\n"
            f"📡 _المصدر: @dollariraqi_\n"
            f"🤖 @{BOT_USERNAME}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🔄 تحديث الآن", callback_data="refresh_dollar_iraqi"
        ))
        markup.add(types.InlineKeyboardButton(
            "📢 قناة @dollariraqi", url="https://t.me/dollariraqi"
        ))
        try:
            bot.edit_message_text(msg, call.message.chat.id, call.message.message_id,
                                  parse_mode="Markdown", reply_markup=markup)
        except Exception:
            bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "⚠️ تعذر التحديث — حاول لاحقاً", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("fc_"))
def cb_factcheck(call):
    bot.answer_callback_query(call.id, "🔍 جاري التحقق...")
    fc_key = call.data[3:]
    title = _factcheck_key_cache.get(fc_key, "")
    if not title:
        try:
            bot.send_message(call.message.chat.id, "⚠️ انتهت صلاحية هذا الزر. أعد فتح الخبر مرة أخرى.")
        except Exception:
            pass
        return
    chat_id = call.message.chat.id
    # إرسال رسالة "جاري التحقق" فوراً ثم نحدثها بعد الانتهاء
    try:
        wait_msg = bot.send_message(chat_id, "🔍 *جاري التحقق من الخبر...*\n_قد يستغرق بضع ثوانٍ_",
                                    parse_mode="Markdown")
    except Exception:
        wait_msg = None

    def _do_factcheck():
        result  = _ai_fact_check(title)
        verdict = result.get("verdict", "⚠️")
        label   = result.get("label", "يحتاج تحقق")
        reason  = result.get("reason", "")
        # إذا لم يكن هناك AI — نقيّم بناءً على قواعد بسيطة
        if not _AI_AVAILABLE and not reason:
            _tl = title.lower()
            promo_words = ["شارك", "اشترك", "لا تنسى", "تابعنا", "قناتنا",
                           "انضم", "subscribe", "follow", "join", "forward"]
            if any(w in _tl for w in promo_words):
                verdict, label, reason = "❌", "محتوى ترويجي", "النص يحتوي على دعوة للمشاركة أو الاشتراك"
            elif len(title.strip()) < 20:
                verdict, label, reason = "⚠️", "خبر قصير", "العنوان قصير جداً للتحقق"
            elif any(c.isdigit() for c in title) and any(
                    w in _tl for w in ["مليون","مليار","ألف","ميليار","كيلومتر","%"]):
                verdict, label, reason = "✅", "يبدو موثوقاً", "يحتوي على أرقام وتفاصيل محددة"
            else:
                verdict, label, reason = "⚠️", "يحتاج مراجعة", "تحقق من المصدر الأصلي"

        reply = (
            f"🔍 *نتيجة التحقق:*\n\n"
            f"📰 _{title[:80]}_\n\n"
            f"{verdict} *{label}*"
            + (f"\n📝 {reason}" if reason else "")
        )
        try:
            if wait_msg:
                bot.edit_message_text(reply, chat_id, wait_msg.message_id,
                                      parse_mode="Markdown")
            else:
                bot.send_message(chat_id, reply, parse_mode="Markdown")
        except Exception:
            try:
                bot.send_message(chat_id, reply, parse_mode="Markdown")
            except Exception:
                pass

    threading.Thread(target=_do_factcheck, daemon=True, name="FactCheck").start()


@bot.message_handler(commands=["debugnews"])
def cmd_debugnews(m):
    """
    تشخيص شامل ومفصّل خطوة بخطوة لنظام الإرسال.
    - يُرسل التقرير مقسّماً (لتفادي حد تيليغرام 4096 حرف)
    - يستخدم لغة الأدمن المسجّلة (fallback للعربية)
    - يكشف القفل العالق، فلاتر الأخبار، وأسباب عدم الوصول
    """
    uid = m.from_user.id
    if not is_admin(uid):
        return

    wait_msg = bot.send_message(uid, "🔍 جاري التشخيص الشامل... (10-20 ثانية)")
    now_sa = _now_sa()

    def _send_chunks(text: str):
        """يُرسل نص طويل مُقسَّماً إلى رسائل بحد أقصى 3900 حرف"""
        lines = text.split('\n')
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 3900:
                try:
                    bot.send_message(uid, chunk)
                except Exception:
                    pass
                chunk = line + '\n'
            else:
                chunk += line + '\n'
        if chunk.strip():
            try:
                bot.send_message(uid, chunk)
            except Exception:
                pass

    # لغة الأدمن (fallback للعربية)
    admin_lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶') or 'العربية 🇮🇶'

    # ═══ قسم 1: حالة النظام ═══
    # ── القفل العالق ──
    lock_age_txt = ""
    if _broadcast_news_lock.is_set():
        lock_age = time.time() - _broadcast_lock_ts[0] if _broadcast_lock_ts[0] else 0
        lock_age_txt = f" (عمره {lock_age/60:.1f} دقيقة)"
        if lock_age > 300:
            lock_age_txt += " ⚠️ عالق!"
    news_lock_txt = (f"🔴 مشغول{lock_age_txt}" if _broadcast_news_lock.is_set() else "🟢 حر")
    ch_lock_txt   = ("🔴 مشغول" if _broadcast_channels_lock.is_set() else "🟢 حر")

    paused_lines = []
    if bot_paused:       paused_lines.append("  ❌ bot_paused=True")
    if broadcast_paused: paused_lines.append("  ❌ broadcast_paused=True → اضغط 📡 في /admin")
    paused_txt = ("\n" + "\n".join(paused_lines)) if paused_lines else ""
    paused_icon = "🔴 متوقف" if (bot_paused or broadcast_paused) else "🟢 يعمل"

    # ── المستخدمون ──
    active_u = sum(1 for i in users.values() if i.get("notifications", True) and i.get("lang"))
    users_sample = []
    for u_id, info in list(users.items())[:8]:
        l_ = info.get("lang", "❌ بدون لغة")
        n_ = "🔔" if info.get("notifications", True) else "🔕"
        users_sample.append(f"  {n_} {u_id} | {l_}")
    users_info = "\n".join(users_sample) or "  ❌ لا يوجد مستخدمون — أرسل /start أولاً!"

    # ── global_sent ──
    with _global_sent_lock:
        gsn_counts = {lg: len(s) for lg, s in _global_sent_news.items()}
    gsn_total = sum(gsn_counts.values())
    gsn_txt   = " | ".join([f"{lg[:12]}:{c}" for lg, c in list(gsn_counts.items())[:6]]) or "فارغ ✅"
    gsn_age   = "—"
    try:
        if os.path.exists(_GLOBAL_SENT_FILE):
            gsn_age = f"{(time.time()-os.path.getmtime(_GLOBAL_SENT_FILE))/60:.0f} دقيقة"
    except Exception:
        pass

    # ── إحصائيات البث ──
    try:
        with _broadcast_stats_lock:
            last_bcast  = _broadcast_stats.get("last_broadcast_time") or "لم يبث بعد"
            today_sent  = _broadcast_stats.get("today_news_sent", 0)
            today_usr   = _broadcast_stats.get("today_users_reached", 0)
    except Exception:
        last_bcast = today_sent = today_usr = "—"

    part1 = (
        f"🔍 تشخيص شامل — {now_sa.strftime('%H:%M:%S')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 الأقفال:\n"
        f"  بث المستخدمين: {news_lock_txt}\n"
        f"  بث القنوات:    {ch_lock_txt}\n"
        f"🚦 البث: {paused_icon}{paused_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 المستخدمون: {len(users)} إجمالي | {active_u} فعّال\n"
        f"{users_info}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 global_sent: {gsn_total} رابط | عمر الملف: {gsn_age}\n"
        f"  {gsn_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 البث اليوم: {today_sent} خبر → {today_usr} مستخدم\n"
        f"  آخر بث: {last_bcast}"
    )

    # ═══ قسم 2: اختبار RSS التفصيلي ═══
    test_feeds = RSS.get(admin_lang, RSS.get("العربية 🇮🇶", []))
    rss_lines  = [f"📡 اختبار RSS | اللغة: {admin_lang} | عدد المصادر: {len(test_feeds)}"]
    total_raw = total_fresh = total_new = total_pass_lang = 0
    with _global_sent_lock:
        lang_sent = set(_global_sent_news.get(admin_lang, set()))

    for test_url in test_feeds[:5]:   # أول 5 مصادر
        try:
            entries = _fetch_one_feed(test_url)
            n_raw   = len(entries)
            n_fresh = sum(1 for e in entries if _is_fresh(e.get("published_dt")))
            n_new   = sum(1 for e in entries if _is_fresh(e.get("published_dt")) and e["link"] not in lang_sent)
            n_lang  = sum(1 for e in entries if _is_fresh(e.get("published_dt")) and e["link"] not in lang_sent and _title_in_lang(e["title"], admin_lang))
            src     = test_url.split('/')[2][:28] if '/' in test_url else test_url[:28]
            icon    = "✅" if n_fresh > 0 else "⚠️"
            rss_lines.append(f"  {icon} {src}")
            rss_lines.append(f"    raw={n_raw} | fresh={n_fresh} | new={n_new} | pass_lang={n_lang}")
            total_raw += n_raw; total_fresh += n_fresh; total_new += n_new; total_pass_lang += n_lang
            # مثال على خبر طازج
            sample_fresh = next((e for e in entries if _is_fresh(e.get("published_dt"))), None)
            if sample_fresh:
                age_m = int((datetime.datetime.utcnow()-sample_fresh["published_dt"]).total_seconds()/60) if sample_fresh.get("published_dt") else "؟"
                rss_lines.append(f"    مثال ({age_m}د): {sample_fresh['title'][:50]}")
        except Exception as ex:
            rss_lines.append(f"  ❌ {test_url[:35]}: {ex}")

    rss_lines.append(f"  ─ الإجمالي: raw={total_raw} | fresh={total_fresh} | new={total_new} | pass_lang={total_pass_lang}")
    part2 = "\n".join(rss_lines)

    # ═══ قسم 3: التشخيص والحل ═══
    diagnosis, fix = [], []
    if bot_paused or broadcast_paused:
        diagnosis.append("❌ البث متوقف يدوياً")
        fix.append("→ /resetbroadcast")
    if not users:
        diagnosis.append("❌ لا مستخدمون مسجلون")
        fix.append("→ /start واختر لغة")
    elif active_u == 0:
        diagnosis.append("❌ جميع المستخدمين بدون لغة محددة")
        fix.append("→ /start واختر لغة")
    if _broadcast_news_lock.is_set():
        lock_age_sec = time.time() - _broadcast_lock_ts[0] if _broadcast_lock_ts[0] else 0
        if lock_age_sec > 300:
            diagnosis.append(f"❌ قفل البث عالق منذ {lock_age_sec/60:.0f} دقيقة")
            fix.append("→ /forcenews يُفرج عنه تلقائياً")
    if total_raw == 0:
        diagnosis.append("❌ لا مقالات RSS — مشكلة شبكة أو feeds فارغة")
        fix.append("→ أعد تشغيل البوت")
    elif total_fresh == 0:
        diagnosis.append("⚠️ كل المقالات قديمة (أكثر من 120 دقيقة)")
        fix.append("→ انتظر دورة البث القادمة")
    elif total_new == 0:
        diagnosis.append("⚠️ كل المقالات الجديدة موجودة في global_sent")
        fix.append("→ /clearcache ثم /forcenews")
    elif total_pass_lang == 0:
        diagnosis.append("⚠️ المقالات محجوبة بفلتر اللغة")
        fix.append("→ تحقق إعداد اللغة أو راجع _title_in_lang")
    if not diagnosis:
        diagnosis.append("✅ كل شيء يعمل — إذا لم تصلك أخبار: /forcenews")

    channels_count = len(channels_groups) if channels_groups else 0
    active_ch = sum(1 for ch in (channels_groups or []) if not ch.get('paused'))

    part3 = (
        f"🩺 التشخيص والحل:\n"
        f"{''.join(chr(10)+d for d in diagnosis)}\n"
        f"{''.join(chr(10)+f for f in fix) if fix else ''}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 القنوات/المجموعات: {channels_count} مسجّلة | {active_ch} فعّالة\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛠 الأوامر: /forcenews | /clearcache | /resetbroadcast | /testnews"
    )

    # أرسل رسالة الانتظار كأول رسالة، ثم الأجزاء
    try:
        bot.edit_message_text(part1, uid, wait_msg.message_id)
    except Exception:
        bot.send_message(uid, part1)
    _send_chunks(part2)
    _send_chunks(part3)


@bot.message_handler(commands=["restartmod"])
def cmd_restartmod(m):
    """
    /restartmod <اسم الوحدة> — يُعيد تشغيل وحدة بعينها بدون إيقاف البوت.
    /restartmod list — لعرض كل الوحدات وحالتها.
    للأدمن فقط.
    """
    uid = m.from_user.id
    if not is_admin(uid):
        return
    args = m.text.split(maxsplit=1)
    if len(args) < 2 or args[1].strip().lower() in ("list", "قائمة", ""):
        status = _get_module_status()
        bot.send_message(
            uid,
            f"📋 *حالة الوحدات القابلة للإعادة*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{status}\n\n"
            f"لإعادة تشغيل وحدة: `/restartmod <الاسم>`\n"
            f"مثال: `/restartmod rss_prefetcher`",
            parse_mode="Markdown"
        )
        return
    mod_name = args[1].strip()
    bot.send_message(uid, f"⏳ جاري إعادة تشغيل `{mod_name}`...", parse_mode="Markdown")
    result = _restart_module(mod_name)
    bot.send_message(uid, result, parse_mode="Markdown")
    _track_error("restartmod_admin", err_type="manual_restart")


@bot.message_handler(commands=["errlogs"])
def cmd_errlogs(m):
    """
    /errlogs — لوحة أخطاء النظام للأدمن (منفصلة عن أخبار المستخدمين).
    تعرض آخر الأخطاء مع فلاتر بالنوع + أزرار التنقل.
    للأدمن فقط.
    """
    uid = m.from_user.id
    if not is_admin(uid):
        return
    _send_alerts_panel(uid, filter_type="all", page=0)


def _send_alerts_panel(uid: int, filter_type: str = "all", page: int = 0):
    """
    يُرسل لوحة التنبيهات الذكية مع أزرار الفلترة.
    filter_type: all / rate_limit / delivery / network / telegram_api / unknown
    """
    PAGE_SIZE = 8
    with _error_timeline_lock:
        history = list(_error_timeline)

    # ── تطبيق الفلتر ──
    if filter_type != "all":
        history = [e for e in history if e.get("type") == filter_type]

    history = list(reversed(history))   # الأحدث أولاً
    total   = len(history)
    page    = max(0, min(page, (total - 1) // PAGE_SIZE))
    chunk   = history[page * PAGE_SIZE: page * PAGE_SIZE + PAGE_SIZE]

    # ── إحصاء سريع حسب النوع ──
    from collections import Counter
    all_hist = list(_error_timeline)
    type_counts = Counter(e.get("type", "unknown") for e in all_hist)

    # ── بناء الرسالة ──
    filter_labels = {
        "all":          f"كل الأخطاء ({total})",
        "rate_limit":   f"⏳ Rate Limit ({type_counts.get('rate_limit', 0)})",
        "delivery":     f"🚫 تسليم فاشل ({type_counts.get('delivery', 0)})",
        "network":      f"🌐 شبكة ({type_counts.get('network', 0)})",
        "telegram_api": f"⚙️ Telegram API ({type_counts.get('telegram_api', 0)})",
        "unknown":      f"❓ غير معروف ({type_counts.get('unknown', 0)})",
    }
    header = (
        f"🔔 *لوحة التنبيهات — فلتر: {filter_labels.get(filter_type, filter_type)}*\n"
        f"صفحة {page + 1} | إجمالي: {total}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
    )
    lines = []
    for e in chunk:
        ts    = datetime.datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
        fn    = e.get("func", "?")[:20]
        etype = e.get("type", "?")[:12]
        msg   = e.get("msg", "")[:60]
        lines.append(f"`{ts}` [{etype}] `{fn}`\n  ↳ {msg}")
    body = "\n".join(lines) if lines else "لا توجد أخطاء في هذا الفلتر 🎉"

    text = header + body

    # ── أزرار الفلترة ──
    type_filters = [
        ("📋 الكل",    "alerts_f:all:0"),
        ("⏳ Rate",    "alerts_f:rate_limit:0"),
        ("🚫 تسليم",  "alerts_f:delivery:0"),
        ("🌐 شبكة",   "alerts_f:network:0"),
        ("⚙️ API",    "alerts_f:telegram_api:0"),
        ("❓ غير معروف","alerts_f:unknown:0"),
    ]
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(*[types.InlineKeyboardButton(lbl, callback_data=cd)
                 for lbl, cd in type_filters])
    # ── أزرار الصفحات ──
    nav_btns = []
    if page > 0:
        nav_btns.append(types.InlineKeyboardButton(
            "◀️ السابق", callback_data=f"alerts_f:{filter_type}:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav_btns.append(types.InlineKeyboardButton(
            "التالي ▶️", callback_data=f"alerts_f:{filter_type}:{page + 1}"))
    if nav_btns:
        markup.add(*nav_btns)
    # ── زر تحديث + حالة الوحدات ──
    markup.add(
        types.InlineKeyboardButton("🔄 تحديث", callback_data=f"alerts_f:{filter_type}:{page}"),
        types.InlineKeyboardButton("⚙️ الوحدات", callback_data="alerts_modules"),
    )

    try:
        bot.send_message(uid, text, parse_mode="Markdown", reply_markup=markup)
    except Exception:
        bot.send_message(uid, text[:3900], reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("alerts_f:") or c.data == "alerts_modules")
def cb_alerts(c):
    """معالج أزرار لوحة تنبيهات الأدمن فقط — لا يتعارض مع alerts_show_track/alerts_track."""
    if not is_admin(c.from_user.id):
        bot.answer_callback_query(c.id, "غير مصرح!")
        return
    bot.answer_callback_query(c.id)
    uid  = c.from_user.id
    data = c.data

    if data == "alerts_modules":
        status = _get_module_status()
        bot.send_message(
            uid,
            f"⚙️ *حالة الوحدات*\n━━━━━━━━━━━━━━━━━━━\n{status}\n\n"
            f"لإعادة وحدة: `/restartmod <الاسم>`",
            parse_mode="Markdown"
        )
        return

    if data.startswith("alerts_f:"):
        parts = data.split(":")
        if len(parts) == 3:
            _, f_type, pg = parts
            try:
                pg = int(pg)
            except ValueError:
                pg = 0
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except Exception:
                pass
            _send_alerts_panel(uid, filter_type=f_type, page=pg)


@bot.message_handler(commands=["sysinfo"])
def cmd_sysinfo(m):
    """تقرير صحي فوري للنظام — للأدمن فقط"""
    uid = m.from_user.id
    if not is_admin(uid):
        return
    try:
        # مقاييس النظام
        sys_m = _get_sys_metrics()
        ram   = sys_m.get("ram_pct", 0)
        cpu   = sys_m.get("cpu_pct", 0)
        disk  = sys_m.get("disk_pct", 0)
        uptime_s = int(time.time() - _sys_health["start_ts"])
        uptime_h = uptime_s // 3600
        uptime_m = (uptime_s % 3600) // 60
        recoveries = _sys_health.get("recoveries", 0)

        # حجم الكاشات
        with _AI_CACHE_LOCK:
            ai_sz = len(_AI_CACHE)
        with _AI_SUMMARY_LOCK:
            sum_sz = len(_AI_SUMMARY_CACHE)
        ns_sz = len(_news_summary_cache)
        with _news_archive_lock:
            arc_sz = len(_news_archive)

        # أكثر الوظائف خطأً
        with _error_freq_lock:
            top_errs = sorted(_error_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        top_err_str = "\n".join(f"  `{fn}`: {cnt}x" for fn, cnt in top_errs) or "  لا أخطاء 🎉"

        # رسائل في الكيو
        q_size = _send_queue.qsize() if hasattr(_send_queue, "qsize") else "؟"

        ram_icon  = "🔴" if ram  > 85 else ("🟡" if ram  > 65 else "🟢")
        cpu_icon  = "🔴" if cpu  > 85 else ("🟡" if cpu  > 65 else "🟢")
        disk_icon = "🔴" if disk > 85 else ("🟡" if disk > 65 else "🟢")

        msg = (
            f"🏥 *تقرير صحة النظام — فوري*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🖥 *الموارد*\n"
            f"  {ram_icon} RAM: `{ram:.1f}%`\n"
            f"  {cpu_icon} CPU: `{cpu:.1f}%`\n"
            f"  {disk_icon} Disk: `{disk:.1f}%`\n"
            f"  ⏱ Uptime: `{uptime_h}h {uptime_m}m`\n"
            f"  🔄 تعافيات تلقائية: `{recoveries}`\n\n"
            f"📦 *الكاشات*\n"
            f"  AI: `{ai_sz}` | ملخصات: `{sum_sz}` | خبر: `{ns_sz}` | أرشيف: `{arc_sz}`\n"
            f"  رسائل في الطابور: `{q_size}`\n\n"
            f"📬 *إحصاءات التسليم*\n"
            f"  ✅ نجح: `{_delivery_stats.get('sent_ok', 0):,}`\n"
            f"  ❌ فشل: `{_delivery_stats.get('sent_fail', 0):,}`\n"
            f"  🔁 أُعيد إرساله: `{_delivery_stats.get('retried', 0):,}`\n"
            f"  ⏳ Rate Limited: `{_delivery_stats.get('rate_limited', 0):,}`\n"
            f"  🔧 حُل تلقائياً: `{_delivery_stats.get('auto_resolved', 0):,}`\n"
            f"  🔔 أُبلغ الأدمن: `{_delivery_stats.get('admin_alerted', 0):,}`\n"
            f"  🚫 Chats ميتة: `{len(_dead_chats)}`\n"
            f"  ⚡ تأخير الإرسال: `{_dynamic_delay*1000:.0f}ms`\n\n"
            f"⚠️ *أكثر الوظائف خطأً*\n{top_err_str}\n"
        )
        bot.send_message(uid, msg, parse_mode="Markdown")
    except Exception as _e:
        bot.send_message(uid, f"خطأ في /sysinfo: {_e}")


@bot.message_handler(commands=["clearcache"])
def cmd_clearcache(m):
    """يمسح global_sent_news وsent_news لكل المستخدمين — للأدمن فقط"""
    uid = m.from_user.id
    if not is_admin(uid):
        return
    # 1. مسح global_sent_news
    with _global_sent_lock:
        old_global = sum(len(s) for s in _global_sent_news.values())
        _global_sent_news.clear()
    _save_global_sent_news()
    # 2. مسح sent_news لكل المستخدمين (حتى لا تحجبهم ذاكرة الرسائل القديمة)
    old_user_total = 0
    for u_id, info in users.items():
        cnt = len(info.get("sent_news", set()))
        old_user_total += cnt
        info["sent_news"] = set()
    threading.Thread(
        target=lambda: _db_save_all_users(users),
        daemon=True, name="SaveUsersAfterClear"
    ).start()
    bot.send_message(uid,
        f"✅ *تم المسح الكامل*\n\n"
        f"📦 global_sent_news: حُذف `{old_global:,}` رابط\n"
        f"👤 sent_news (لكل مستخدم): حُذف `{old_user_total:,}` رابط\n\n"
        f"⏳ البث يبدأ في الدورة القادمة (30-60 ثانية)",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["resetbroadcast"])
def cmd_resetbroadcast(m):
    """إعادة تشغيل البث كاملاً: يرفع الإيقاف + يحرر الأقفال + يمسح global_sent — للأدمن فقط"""
    global bot_paused, broadcast_paused, pause_message
    uid = m.from_user.id
    if not is_admin(uid):
        return
    # 1. رفع جميع حالات الإيقاف
    was_paused = bot_paused or broadcast_paused
    bot_paused = False
    broadcast_paused = False
    pause_message = ""
    # 2. تحرير الأقفال إن كانت عالقة
    locks_cleared = 0
    if _broadcast_news_lock.is_set():
        _broadcast_news_lock.clear()
        locks_cleared += 1
    if _broadcast_channels_lock.is_set():
        _broadcast_channels_lock.clear()
        locks_cleared += 1
    # 3. مسح global_sent_news لإرسال الأخبار الجديدة فوراً
    with _global_sent_lock:
        old_count = sum(len(s) for s in _global_sent_news.values())
        _global_sent_news.clear()
    _save_global_sent_news()
    # 4. إرسال تقرير
    active_u = sum(1 for i in users.values() if i.get("notifications", True) and i.get("lang"))
    status = "✅ كان متوقفاً — تم إعادة التشغيل" if was_paused else "✅ لم يكن متوقفاً"
    bot.send_message(uid,
        f"🔄 *إعادة تشغيل البث الكاملة*\n\n"
        f"حالة الإيقاف: {status}\n"
        f"أقفال محررة: {locks_cleared}\n"
        f"روابط محذوفة من global_sent: {old_count:,}\n\n"
        f"👥 مستخدمون فعّالون: {active_u}\n"
        f"📡 البث سيبدأ في الدورة القادمة (30 ثانية)\n\n"
        f"{'⚠️ لا يوجد مستخدمون نشطون! أرسل /start واختر لغة' if active_u == 0 else ''}",
        parse_mode="Markdown"
    )
    # 5. إطلاق بث فوري
    if active_u > 0 or channels_groups:
        threading.Thread(target=_safe_job(broadcast_news), daemon=True, name="ResetBroadcast").start()


@bot.message_handler(commands=["forcenews"])
def cmd_forcenews(m):
    """
    يُشغّل دورة بث فورية — للأدمن فقط.
    - يُفرج عن أي قفل عالق تلقائياً (إذا >5 دقائق)
    - يُبلّغ بالنتيجة: كم خبر أُرسل لكم مستخدم/قناة
    - لا يتوقف بسبب broadcast_paused (يُجبر البث)
    """
    uid = m.from_user.id
    if not is_admin(uid):
        return

    # ── 1. تحقق من القفل ──
    if _broadcast_news_lock.is_set():
        lock_age = time.time() - _broadcast_lock_ts[0] if _broadcast_lock_ts[0] else 0
        if lock_age < 300:  # أقل من 5 دقائق — ربما شغّال فعلاً
            remaining = int(300 - lock_age)
            bot.send_message(
                uid,
                f"⚠️ دورة بث شغّالة الآن (عمرها {lock_age/60:.0f} دقيقة).\n"
                f"انتظر {remaining//60}:{remaining%60:02d} دقيقة أو أعد المحاولة."
            )
            return
        else:
            # القفل عالق — افرج عنه بالقوة
            _broadcast_news_lock.clear()
            _broadcast_lock_ts[0] = 0
            bot.send_message(uid, f"🔓 أُفرج عن قفل عالق (كان مشغولاً {lock_age/60:.0f} دقيقة)")

    # ── 2. تحقق من إيقاف البوت الكلي ──
    global bot_paused, broadcast_paused
    if bot_paused:
        bot.send_message(uid, "❌ البوت متوقف كلياً (bot_paused=True). أرسل /resetbroadcast أولاً.")
        return

    # ── 3. إذا broadcast_paused، أوقف مؤقتاً للبث القسري ──
    was_paused = broadcast_paused
    if was_paused:
        broadcast_paused = False
        bot.send_message(uid, "⚡ تم تعليق إيقاف البث مؤقتاً لإجراء البث الفوري...")

    # ── 4. سجّل إحصائيات ما قبل البث ──
    try:
        with _broadcast_stats_lock:
            before_sent = _broadcast_stats.get("today_news_sent", 0)
            before_usr  = _broadcast_stats.get("today_users_reached", 0)
    except Exception:
        before_sent = before_usr = 0

    status_msg = bot.send_message(uid, "⏳ يُطلق البث الفوري...")

    def _force_run():
        global broadcast_paused
        try:
            broadcast_news()
        finally:
            # أعد حالة البث إذا كانت موقوفة
            if was_paused:
                broadcast_paused = True
            # أرسل ملخص النتيجة
            try:
                with _broadcast_stats_lock:
                    after_sent = _broadcast_stats.get("today_news_sent", 0)
                    after_usr  = _broadcast_stats.get("today_users_reached", 0)
                delta_sent = after_sent - before_sent
                delta_usr  = after_usr  - before_usr
                ch_count   = len(channels_groups) if channels_groups else 0
                result_txt = (
                    f"✅ اكتملت دورة البث الفوري\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📨 أُرسل: {delta_sent} خبر جديد\n"
                    f"👥 وصل: {delta_usr} مستخدم\n"
                    f"📢 القنوات/المجموعات: {ch_count}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                )
                if delta_sent == 0:
                    result_txt += (
                        "⚠️ لم يُرسل شيء — الأسباب المحتملة:\n"
                        "  • global_sent ممتلئ → /clearcache\n"
                        "  • لا مستخدمون فعّالون → /start واختر لغة\n"
                        "  • الأخبار قديمة → انتظر 30 دقيقة\n"
                        "🔍 للتشخيص التفصيلي: /debugnews"
                    )
                bot.edit_message_text(result_txt, uid, status_msg.message_id)
            except Exception:
                pass

    threading.Thread(target=_force_run, daemon=True, name="ForceBroadcast").start()


@bot.message_handler(commands=["testnews"])
def cmd_testnews(m):
    """
    اختبار خط أنابيب الأخبار خطوة بخطوة — للأدمن فقط.
    يُجيب على: لماذا لا تصل الأخبار؟
    يتجاوز global_sent ويُرسل خبراً حقيقياً مباشرة.
    """
    uid = m.from_user.id
    if not is_admin(uid):
        return
    bot.send_message(uid, "🧪 بدء اختبار خط أنابيب الأخبار... انتظر 15 ثانية")

    report = []
    lang = "العربية 🇮🇶"

    # ══ المرحلة 1: جلب RSS ══
    feeds = RSS.get(lang, [])
    report.append(f"📡 المرحلة 1: RSS feeds متاحة = {len(feeds)}")
    if not feeds:
        bot.send_message(uid, "\n".join(report) + "\n❌ توقف: لا توجد feeds للعربية!")
        return

    test_url = feeds[0]
    try:
        entries = _fetch_one_feed(test_url)
        report.append(f"  ✅ {test_url.split('/')[2]}: {len(entries)} مقال")
    except Exception as e:
        report.append(f"  ❌ فشل الجلب: {e}")
        entries = []
    if not entries:
        bot.send_message(uid, "\n".join(report) + "\n❌ توقف: RSS يعيد فارغاً!")
        return

    # ══ المرحلة 2: فلتر الحداثة ══
    fresh = [e for e in entries if _is_fresh(e.get("published_dt"))]
    report.append(f"⏱ المرحلة 2: بعد فلتر الحداثة (120 دق) = {len(fresh)}/{len(entries)}")
    if fresh:
        ex = fresh[0]
        pd = ex.get("published_dt")
        age_str = f"{int((datetime.datetime.utcnow()-pd).total_seconds()/60)}د" if pd else "مجهول"
        report.append(f"  أحدث خبر: عمره={age_str} | {ex['title'][:40]}")
    else:
        report.append("  ⚠️ كل الأخبار عمرها > 120 دقيقة!")
    source = fresh if fresh else entries[:5]

    # ══ المرحلة 3: فلتر البلاك ليست ══
    after_bl = [e for e in source if not is_blacklisted(e["title"])]
    report.append(f"🚫 المرحلة 3: بعد البلاك ليست = {len(after_bl)}/{len(source)}")
    dropped_bl = len(source) - len(after_bl)
    if dropped_bl > 0:
        report.append(f"  ⚠️ {dropped_bl} خبر محذوف بالبلاك ليست")

    # ══ المرحلة 4a: فلتر global_sent ══
    with _global_sent_lock:
        ar_sent = set(_global_sent_news.get(lang, set()))
    after_sent = [e for e in after_bl if e["link"] not in ar_sent]
    report.append(f"📦 المرحلة 4a: بعد global_sent ({len(ar_sent)} رابط) = {len(after_sent)}/{len(after_bl)}")
    if not after_sent:
        report.append("  ⚠️ كل الأخبار موجودة في global_sent — جرّب /clearcache")

    # ══ المرحلة 4b: فلتر user_sent (per-user history) ══
    my_info = users.get(str(uid), {})
    my_sent = my_info.get("sent_news", set())
    report.append(f"📋 المرحلة 4b: user_sent لحسابك = {len(my_sent)} رابط")
    if not my_info:
        report.append("  ❌ أنت غير مسجّل — أرسل /start واختر لغة!")
    elif not my_info.get("lang"):
        report.append("  ❌ لم تختر لغة — أرسل /start واختر لغة!")
    after_user_sent = [e for e in after_sent if e["link"] not in my_sent]
    report.append(f"  بعد user_sent = {len(after_user_sent)}/{len(after_sent)}")
    if not after_user_sent and after_sent:
        report.append("  ⚠️ كل الأخبار في user_sent الخاص بك! جرّب إعادة تشغيل البوت")

    # نُجبر على المتابعة بمرشح واحد على الأقل حتى لو في global_sent/user_sent
    test_pool = after_user_sent if after_user_sent else (after_sent[:3] if after_sent else after_bl[:3])

    # ══ المرحلة 5: فلتر اللغة ══
    after_lang = [e for e in test_pool if _title_in_lang(e["title"], lang)]
    report.append(f"🔤 المرحلة 5: بعد فلتر اللغة = {len(after_lang)}/{len(test_pool)}")
    if not after_lang and test_pool:
        sample = test_pool[0]["title"]
        report.append(f"  ⚠️ نموذج محجوب: '{sample[:40]}'")
        # احسب نسبة العربية
        import re as _re2
        ar_chars = len(_re2.findall(r'[\u0600-\u06FF]', sample))
        ratio = ar_chars / max(len([c for c in sample if not c.isspace()]), 1)
        report.append(f"  نسبة الحروف العربية: {ratio:.0%} (يحتاج ≥25%)")
    pick = after_lang if after_lang else test_pool

    # ══ المرحلة 6: اختبار AI ══
    test_entry = pick[0] if pick else None
    if test_entry:
        ai_in  = test_entry["title"]
        ai_out = None
        try:
            ai_out = _ai_clean_news(ai_in, body=test_entry.get("summary","")[:300], link=test_entry["link"])
        except Exception as ae:
            report.append(f"❌ المرحلة 6 AI: استثناء: {ae}")
        if ai_out is None:
            report.append(f"🤖 المرحلة 6 AI: أعاد None → يستخدم العنوان الأصلي (fallback)")
            ai_out = ai_in
        elif ai_out == ai_in:
            report.append(f"🤖 المرحلة 6 AI: غير متاح / يعيد نفس العنوان")
        else:
            report.append(f"🤖 المرحلة 6 AI: ✅ نظّف العنوان")

        # ══ المرحلة 7: إرسال تجريبي مباشر ══
        report.append(f"\n📨 المرحلة 7: إرسال خبر حقيقي مباشرة إليك...")
        bot.send_message(uid, "\n".join(report))

        try:
            src_name = test_entry["feed_url"].split('/')[2] if test_entry.get("feed_url") else "RSS"
            pub_dt   = test_entry.get("published_dt")
            pub_str  = _format_pub_time(pub_dt, lang=lang)
            msg_text = (
                f"🧪 *اختبار مباشر*\n\n"
                f"📰 {ai_out}\n\n"
                f"🔗 {test_entry['link']}\n"
                f"{pub_str} | {src_name}"
            )
            bot.send_message(uid, msg_text, parse_mode="Markdown", disable_web_page_preview=False)
            bot.send_message(uid,
                "✅ وصل الخبر إليك!\n\n"
                "👉 إذن: البوت يستطيع إرسال الأخبار.\n"
                "المشكلة في المقارنة مع global_sent أو عدم وجود مستخدمين فعّالين.\n"
                "الحل: /clearcache ثم /resetbroadcast"
            )
        except Exception as send_e:
            bot.send_message(uid, f"❌ فشل الإرسال التجريبي: {send_e}")
    else:
        bot.send_message(uid, "\n".join(report) + "\n❌ لا يوجد أي خبر للاختبار!")


scheduler = BackgroundScheduler()
# الفاصل الزمني الافتراضي 60 ثانية
_default_interval_sec = int(broadcast_settings.get("interval_minutes", 1) * 60)
if _default_interval_sec < 60:
    _default_interval_sec = 60
# ─── أول دورة بث بعد 120 ثانية من الإقلاع ─────────────────────────────────
# هذا يعطي _rss_prefetcher وقتاً كافياً (يحتاج ~60-90 ثانية لجلب 210 feed)
# فنضمن أن الكاش ممتلئ عند أول broadcast_news
_first_broadcast_delay = datetime.datetime.now() + datetime.timedelta(seconds=120)
_broadcast_news_job = scheduler.add_job(
    _safe_job(broadcast_news), 'interval',
    seconds=_default_interval_sec, id="broadcast_news_job",
    next_run_time=_first_broadcast_delay
)
_broadcast_channels_job = scheduler.add_job(
    _safe_job(broadcast_to_channels), 'interval',
    seconds=_default_interval_sec, id="broadcast_channels_job",
    next_run_time=_first_broadcast_delay
)
scheduler.add_job(_safe_job(send_morning_summary), 'interval', hours=1)
scheduler.add_job(_safe_job(check_weather_alerts), 'interval', hours=6)
scheduler.add_job(_safe_job(check_currency_alerts), 'interval', hours=3)
scheduler.add_job(_safe_job(check_keyword_alerts), 'interval', minutes=15)
scheduler.add_job(_safe_job(auto_clean_sent_news), 'interval', hours=1)
scheduler.add_job(_safe_job(_sports_live_broadcaster), 'interval', seconds=10)
scheduler.add_job(_safe_job(_prematch_notifier), 'interval', minutes=15)
scheduler.add_job(_safe_job(_crisis_monitor_check), 'interval', minutes=10)
scheduler.add_job(_safe_job(_live_events_broadcaster), 'interval', minutes=2)
scheduler.add_job(_safe_job(_check_economic_alerts), 'interval', hours=2)
scheduler.add_job(_safe_job(_get_parliament_summary), 'cron', hour=9, minute=0)
scheduler.add_job(_safe_job(check_pause_reminder), 'interval', hours=2)
scheduler.add_job(_safe_job(check_asset_tracking), 'interval', hours=1)
scheduler.add_job(_safe_job(lambda: _db_save_all_users(users)), 'interval', minutes=3)
scheduler.add_job(_safe_job(lambda: _db_save_all_channels(channels_groups)), 'interval', minutes=5)
scheduler.add_job(_safe_job(_save_global_sent_news), 'interval', minutes=5)
# ─── وظائف الجيل المتقدم ─────────────────────────────────────────
scheduler.add_job(_safe_job(_send_admin_health_report), 'interval', hours=1)
scheduler.add_job(_safe_job(_auto_db_backup),           'interval', hours=6)
scheduler.add_job(_safe_job(_crisis_room_broadcaster),  'interval', seconds=30)
scheduler.add_job(_safe_job(_politician_statement_tracker), 'interval', hours=2)
scheduler.add_job(_safe_job(_foreign_intel_monitor),    'interval', minutes=25)
scheduler.add_job(_safe_job(_process_crowd_tips),       'interval', minutes=10)
# ─── Heartbeat: نبضة الحياة كل 10 دقائق ─────────────────────────
scheduler.add_job(_safe_job(_rss_prefetcher), 'interval', seconds=90, id="rss_prefetch_job")
scheduler.add_job(_safe_job(_send_heartbeat), 'interval', minutes=10, id="heartbeat_job")
# تشغيل فوري للمحمّل المسبق بعد 3 ثوانٍ من الإقلاع
threading.Timer(3.0, _safe_job(_rss_prefetcher)).start()
# ─── تنظيف ذاكرة الكاش كل ساعة ──────────────────────────────────
def _cleanup_caches():
    """تنظيف الكاشات القديمة لمنع memory leaks."""
    try:
        # AI cache
        with _AI_CACHE_LOCK:
            if len(_AI_CACHE) > 800:
                for k in list(_AI_CACHE.keys())[:300]:
                    _AI_CACHE.pop(k, None)
        # AI summary cache
        with _AI_SUMMARY_LOCK:
            if len(_AI_SUMMARY_CACHE) > 500:
                for k in list(_AI_SUMMARY_CACHE.keys())[:200]:
                    _AI_SUMMARY_CACHE.pop(k, None)
        # Alert count (تنظيف الدقائق القديمة)
        now_min = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with _alert_lock:
            old = [k for k in _alert_count if k != now_min]
            for k in old:
                _alert_count.pop(k, None)
        _logger.info("🧹 تنظيف الكاش تم بنجاح")
    except Exception as e:
        _logger.warning(f"cleanup_caches خطأ: {e}")

scheduler.add_job(_safe_job(_cleanup_caches), 'interval', hours=1, id="cache_cleanup_job")
# broadcast_weather أُزيلت من الجدولة — تُرسل عند طلب المستخدم فقط
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))
atexit.register(_save_global_sent_news)
_logger.info("✅ Scheduler بدأ بنجاح — كل المهام المجدولة نشطة")

# ── تسجيل الوحدات الحرجة في Module Registry لإتاحة /restartmod ─────────────
_register_module("rss_prefetcher",      _rss_prefetcher)
_register_module("broadcast_news",      broadcast_news)
_register_module("system_health",       _system_health_monitor)
_register_module("dynamic_delay",       _dynamic_delay_adjuster)
_logger.info("📋 Module Registry: %d وحدة مسجّلة", len(_module_registry))

# ─── تحميل مسبق لفرق الدوريات الشهيرة في الخلفية عند الإطلاق ────
def _preload_popular_teams():
    """يحمّل فرق أشهر 6 دوريات في الخلفية عند بدء البوت لتجنب التأخير"""
    _POPULAR = [
        "soccer/eng.1",       # البريميرليغ
        "soccer/esp.1",       # لاليغا
        "soccer/ger.1",       # البوندسليغا
        "soccer/ita.1",       # السيريا آ
        "soccer/fra.1",       # الدوري الفرنسي
        "soccer/ksa.1",       # الدوري السعودي
        "soccer/uefa.champions", # دوري الأبطال
    ]
    for slug in _POPULAR:
        try:
            if slug not in _teams_cache:
                _get_league_teams(slug)
                time.sleep(0.5)
        except Exception:
            pass
    _logger.info("✅ تم التحميل المسبق لفرق الدوريات الشهيرة")

threading.Thread(target=_preload_popular_teams, daemon=True, name="TeamPreload").start()

# ======== رسالة الترحيب عند إضافة البوت للقناة/المجموعة ========
CHANNEL_WELCOME_MSG = (
   "👋 *أهلاً! تم تفعيل بوت الأخبار بنجاح في هذه القناة/المجموعة.*\n\n"
   "━━━━━━━━━━━━━━\n"
   "📋 *الأوامر المتاحة لأدمن القناة/المجموعة:*\n\n"
   "🌐 *تغيير لغة الأخبار:*\n"
   "`/setlang العربية 🇮🇶`\n"
   "`/setlang English 🇬🇧`\n"
   "`/setlang فارسی 🇮🇷`\n"
   "`/setlang Türkçe 🇹🇷`\n\n"
   "🏙 *تغيير المدينة:*\n"
   "`/setcity بغداد`\n\n"
   "📡 *مصادر الأخبار (RSS):*\n"
   "`/setsource رابط_RSS` — إضافة مصدر\n"
   "`/removesource رابط_RSS` — حذف مصدر\n"
   "`/listsources` — عرض المصادر\n\n"
   "⏸ *التحكم في البث:*\n"
   "`/pause` — إيقاف البث مؤقتاً\n"
   "`/resume` — استئناف البث\n\n"
   "⚙️ *الإعدادات:*\n"
   "`/settings` — عرض الإعدادات الحالية\n\n"
   "━━━━━━━━━━━━━━\n"
   "📰 سيبدأ إرسال الأخبار تلقائياً كل بضع دقائق.\n"
   f"🤖 @{BOT_USERNAME}"
)


# ═══════════════════════════════════════════════════════════════════
# أوامر الجيل الثاني
# ═══════════════════════════════════════════════════════════════════

@bot.message_handler(commands=['profile'])
def handle_profile_cmd(message):
    name = message.text.replace('/profile', '').strip()
    if not name:
        bot.send_message(message.chat.id,
            "🕵️ *محقق الشخصيات*\n\nأرسل اسم السياسي أو المسؤول:\n`/profile محمد شياع السوداني`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, f"🕵️ جاري بناء ملف: *{name}*...", parse_mode="Markdown")
    result = _ai_build_profile(name)
    reply = f"🕵️ *ملف: {name}*\n\n{result}"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")

@bot.message_handler(commands=['ask'])
def handle_ask_cmd(message):
    uid = message.from_user.id
    lang = users.get(str(uid), {}).get('lang', 'العربية 🇮🇶')
    question = message.text.replace('/ask', '').strip()
    if not question:
        bot.send_message(message.chat.id,
            "💬 *محادثة مع الأخبار*\n\nاسألني عن أي حدث:\n`/ask شنو صار اليوم ببغداد؟`\n`/ask ما آخر أخبار النفط؟`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, "💬 أبحث في الأخبار...")
    result = _ai_chat_with_news(question, lang)
    reply = f"💬 *{question}*\n\n{result}\n\n_مبني على آخر الأخبار المتاحة_"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def handle_photo_analysis(message):
    uid = message.from_user.id
    caption = message.caption or ""
    # فحص إذا المستخدم يريد التحليل
    if not any(w in caption.lower() for w in ["حلل", "analyze", "شنو", "ما هذا", "اقرأ", "تحقق", "verify"]):
        # لا تحلل كل صورة تلقائياً، فقط عند الطلب
        return
    msg = bot.send_message(message.chat.id, "📸 جاري تحليل الصورة بـ AI...")
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        import urllib.request
        with urllib.request.urlopen(file_url, timeout=10) as resp:
            img_bytes = resp.read()
        result = _ai_analyze_photo_file(img_bytes, caption)
        reply = f"📸 *تحليل الصورة*\n\n{result}"
        try:
            bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
        except Exception:
            bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")
    except Exception as e:
        try:
            bot.edit_message_text(f"❌ تعذر تحليل الصورة: {e}", message.chat.id, msg.message_id)
        except Exception:
            pass

@bot.message_handler(commands=['predict'])
def handle_predict_cmd(message):
    topic = message.text.replace('/predict', '').strip()
    if not topic:
        bot.send_message(message.chat.id,
            "🔮 *التنبؤ بالأحداث*\n\nأرسل الموضوع:\n`/predict الأزمة السياسية العراقية`\n`/predict أسعار النفط`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, f"🔮 جاري تحليل الأنماط والتنبؤ بـ: *{topic}*...", parse_mode="Markdown")
    result = _ai_predict_events(topic)
    reply = f"🔮 *التنبؤات — {topic}*\n\n{result}"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")

@bot.message_handler(commands=['parliament'])
def handle_parliament_cmd(message):
    msg = bot.send_message(message.chat.id, "🏛️ جاري جمع آخر أخبار البرلمان...")
    result = _get_parliament_summary()
    try:
        bot.edit_message_text(result[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, result[:4096], parse_mode="Markdown")

@bot.message_handler(commands=['influence'])
def handle_influence_cmd(message):
    name = message.text.replace('/influence', '').strip()
    if not name:
        bot.send_message(message.chat.id,
            "🗺️ *خريطة النفوذ السياسي*\n\nأرسل الاسم:\n`/influence نوري المالكي`",
            parse_mode="Markdown")
        return
    msg = bot.send_message(message.chat.id, f"🗺️ جاري رسم خريطة نفوذ: *{name}*...", parse_mode="Markdown")
    result = _ai_influence_map(name)
    reply = f"🗺️ *خريطة النفوذ — {name}*\n\n{result}"
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")

@bot.message_handler(commands=['econ'])
def handle_econ_cmd(message):
    uid = message.from_user.id
    msg = bot.send_message(message.chat.id, "📉 جاري جمع المؤشرات الاقتصادية...")
    lines = ["📊 *لوحة المؤشرات الاقتصادية*\n"]
    # النفط
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1d&range=2d",
                         timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
            closes = [c for c in closes if c]
            if len(closes) >= 2:
                chg = (closes[-1] - closes[-2]) / closes[-2] * 100
                icon = "📈" if chg > 0 else "📉"
                lines.append(f"🛢️ *النفط الخام:* `${closes[-1]:.1f}` {icon} `{chg:+.1f}%`")
    except Exception:
        lines.append("🛢️ النفط: غير متاح")
    # الذهب
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=2d",
                         timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0].get("close", [])
            closes = [c for c in closes if c]
            if len(closes) >= 2:
                chg = (closes[-1] - closes[-2]) / closes[-2] * 100
                icon = "📈" if chg > 0 else "📉"
                lines.append(f"🥇 *الذهب:* `${closes[-1]:.0f}` {icon} `{chg:+.1f}%`")
    except Exception:
        pass
    # الدولار
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=8)
        if r.status_code == 200:
            rates = r.json().get("rates", {})
            iqd = rates.get("IQD", 0)
            if iqd:
                status = "✅ طبيعي" if 1290 <= iqd <= 1330 else "⚠️ خارج النطاق"
                lines.append(f"💵 *دولار/دينار:* `{iqd:,.0f}` {status}")
    except Exception:
        pass
    if _AI_MODEL and len(lines) > 1:
        try:
            econ_text = "\n".join(lines[1:])
            prompt = f"""بناءً على هذه المؤشرات الاقتصادية، قدم تحليلاً مختصراً لأثرها على العراق:
{econ_text}
جملتان فقط، مباشرة."""
            resp = _AI_MODEL.generate_content(prompt)
            lines.append(f"\n🧠 *تحليل AI:* {resp.text.strip()[:200]}")
        except Exception:
            pass
    reply = "\n".join(lines)
    try:
        bot.edit_message_text(reply[:4096], message.chat.id, msg.message_id, parse_mode="Markdown")
    except Exception:
        bot.send_message(message.chat.id, reply[:4096], parse_mode="Markdown")


@bot.my_chat_member_handler()
def on_bot_chat_member_update(update):
    new_status = update.new_chat_member.status
    old_status = update.old_chat_member.status
    chat = update.chat
    chat_id = chat.id
    chat_type = chat.type

    if chat_type not in ("channel", "group", "supergroup"):
        return

    if new_status in ("administrator", "member") and old_status in ("left", "kicked", "restricted"):
        title = chat.title or str(chat_id)
        already = any(ch["id"] == chat_id for ch in channels_groups)
        if not already:
            default_lang = "العربية 🇮🇶"
            auto_feeds = RSS.get(default_lang, [])
            initial_sent = list(prefill_sent_news(auto_feeds))
            channels_groups.append({
                "id": chat_id,
                "title": title,
                "type": chat_type,
                "lang": default_lang,
                "city": "",
                "sent_news": initial_sent
            })
            save_channels_groups()
        try:
            bot.send_message(chat_id, CHANNEL_WELCOME_MSG, parse_mode="Markdown")
        except Exception as e:
            notify_admin_error(f"خطأ في إرسال رسالة الترحيب للقناة {title}: {e}")
        notify_admin_error(f"✅ تمت إضافة البوت لـ: *{title}* (`{chat_id}`) — النوع: {chat_type}")

    elif new_status in ("left", "kicked") and old_status in ("administrator", "member"):
        title = chat.title or str(chat_id)
        for i, ch in enumerate(channels_groups):
            if ch["id"] == chat_id:
                channels_groups.pop(i)
                save_channels_groups()
                break
        notify_admin_error(f"⚠️ تمت إزالة البوت من: *{title}* (`{chat_id}`)")


# ======== أوامر التحكم داخل القناة/المجموعة ========
VALID_LANGS = ["العربية 🇮🇶", "English 🇬🇧", "فارسی 🇮🇷", "Türkçe 🇹🇷"]

def is_chat_admin(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

@bot.message_handler(commands=["setlang"], chat_types=["channel", "group", "supergroup"])
def cmd_setlang(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    args = message.text.strip().replace("/setlang", "").strip()
    matched_lang = None
    for lang in VALID_LANGS:
        if lang.lower().startswith(args.lower()) or args.lower() in lang.lower():
            matched_lang = lang
            break
    if not matched_lang:
        bot.send_message(chat_id,
            "❌ *لغة غير صحيحة.*\n\n"
            "اللغات المتاحة:\n"
            "• `العربية 🇮🇶`\n"
            "• `English 🇬🇧`\n"
            "• `فارسی 🇮🇷`\n"
            "• `Türkçe 🇹🇷`\n\n"
            "مثال: `/setlang العربية 🇮🇶`",
            parse_mode="Markdown"
        )
        return
    found = False
    for ch in channels_groups:
        if ch["id"] == chat_id:
            ch["lang"] = matched_lang
            ch["sent_news"] = []
            found = True
            break
    if not found:
        channels_groups.append({
            "id": chat_id,
            "title": message.chat.title or str(chat_id),
            "type": message.chat.type,
            "lang": matched_lang,
            "city": "",
            "sent_news": []
        })
    save_channels_groups()
    bot.send_message(chat_id,
        f"✅ *تم تغيير لغة الأخبار إلى:* {matched_lang}\n"
        f"📰 سيبدأ إرسال الأخبار باللغة الجديدة في البث القادم.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["setcity"], chat_types=["channel", "group", "supergroup"])
def cmd_setcity(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    city = message.text.strip().replace("/setcity", "").strip()
    if not city:
        bot.send_message(chat_id,
            "❌ *أرسل اسم المدينة.*\n\nمثال: `/setcity بغداد`",
            parse_mode="Markdown"
        )
        return
    found = False
    for ch in channels_groups:
        if ch["id"] == chat_id:
            ch["city"] = city
            found = True
            break
    if not found:
        channels_groups.append({
            "id": chat_id,
            "title": message.chat.title or str(chat_id),
            "type": message.chat.type,
            "lang": "العربية 🇮🇶",
            "city": city,
            "sent_news": []
        })
    save_channels_groups()
    bot.send_message(chat_id,
        f"✅ *تم تعيين المدينة إلى:* {city}",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["settings"], chat_types=["channel", "group", "supergroup"])
def cmd_settings(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        bot.send_message(chat_id,
            "⚠️ هذه القناة/المجموعة غير مسجلة في البوت بعد.\n"
            "أضف البوت كأدمن وسيبدأ تلقائياً.",
            parse_mode="Markdown"
        )
        return
    lang = ch_data.get("lang", "العربية 🇮🇶")
    city = ch_data.get("city", "") or "غير محددة"
    chat_type = ch_data.get("type", "")
    type_label = "📢 قناة" if chat_type == "channel" else "👥 مجموعة"
    bot.send_message(chat_id,
        f"⚙️ *إعدادات هذه {type_label}:*\n\n"
        f"🌐 اللغة: *{lang}*\n"
        f"🏙 المدينة: *{city}*\n\n"
        f"🔧 لتغيير اللغة: `/setlang اسم اللغة`\n"
        f"🔧 لتغيير المدينة: `/setcity اسم المدينة`",
        parse_mode="Markdown"
    )

# ======== أوامر المصادر المخصصة لأدمن القناة/المجموعة ========
@bot.message_handler(commands=["setsource"], chat_types=["channel", "group", "supergroup"])
def cmd_setsource(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    url = message.text.strip().replace("/setsource", "").strip()
    if not url.startswith("http"):
        bot.send_message(chat_id, "❌ أرسل رابط RSS صحيح يبدأ بـ http\nمثال: `/setsource https://feeds.bbcarabic.com/world-arabic-rss.xml`", parse_mode="Markdown")
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        channels_groups.append({"id": chat_id, "title": message.chat.title or str(chat_id),
                                 "type": message.chat.type, "lang": "العربية 🇮🇶",
                                 "custom_sources": [url], "sent_news": []})
    else:
        sources = ch_data.setdefault("custom_sources", [])
        if url in sources:
            bot.send_message(chat_id, "⚠️ هذا المصدر مضاف مسبقاً.")
            return
        sources.append(url)
    save_channels_groups()
    bot.send_message(chat_id, f"✅ *تمت إضافة المصدر:*\n`{url}`", parse_mode="Markdown")

@bot.message_handler(commands=["removesource"], chat_types=["channel", "group", "supergroup"])
def cmd_removesource(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    url = message.text.strip().replace("/removesource", "").strip()
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data or url not in ch_data.get("custom_sources", []):
        bot.send_message(chat_id, "⚠️ المصدر غير موجود.")
        return
    ch_data["custom_sources"].remove(url)
    save_channels_groups()
    bot.send_message(chat_id, f"✅ تم حذف المصدر:\n`{url}`", parse_mode="Markdown")

@bot.message_handler(commands=["listsources"], chat_types=["channel", "group", "supergroup"])
def cmd_listsources(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    sources = ch_data.get("custom_sources", []) if ch_data else []
    if not sources:
        bot.send_message(chat_id,
            "📋 لا توجد مصادر مخصصة.\n"
            "يستخدم البوت المصادر الافتراضية حسب اللغة.\n"
            "أضف مصدراً: `/setsource رابط_RSS`",
            parse_mode="Markdown"
        )
        return
    msg = "📋 *مصادر الأخبار المخصصة:*\n\n"
    for i, src in enumerate(sources, 1):
        msg += f"{i}. `{src}`\n"
    bot.send_message(chat_id, msg, parse_mode="Markdown")

@bot.message_handler(commands=["pause"], chat_types=["channel", "group", "supergroup"])
def cmd_pause(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        bot.send_message(chat_id, "⚠️ هذه القناة/المجموعة غير مسجلة.")
        return
    ch_data["paused"] = True
    save_channels_groups()
    bot.send_message(chat_id, "⏸ *تم إيقاف البث مؤقتاً.*\nاستخدم `/resume` للاستئناف.", parse_mode="Markdown")

@bot.message_handler(commands=["resume"], chat_types=["channel", "group", "supergroup"])
def cmd_resume(message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or not is_chat_admin(chat_id, user_id):
        return
    ch_data = next((ch for ch in channels_groups if ch["id"] == chat_id), None)
    if not ch_data:
        bot.send_message(chat_id, "⚠️ هذه القناة/المجموعة غير مسجلة.")
        return
    ch_data["paused"] = False
    save_channels_groups()
    bot.send_message(chat_id, "▶️ *تم استئناف البث.*\nستصلك الأخبار تلقائياً قريباً.", parse_mode="Markdown")

# ======== تقرير يومي للأدمن ========
def send_daily_report():
    if bot_paused: return
    today = str(datetime.date.today())
    yesterday = str(datetime.date.today() - datetime.timedelta(days=1))
    total_users_count = len(users)
    new_today = sum(1 for u in users.values() if u.get("join_date", "").startswith(today))
    premium_count = len(stats.get("premium_users", []))
    channels_count = len(channels_groups)
    total_ch_news = sum(ch.get("news_sent_count", 0) for ch in channels_groups)
    read_today = read_stats.get("daily", {}).get(today, 0)
    read_yest = read_stats.get("daily", {}).get(yesterday, 0)
    total_reads = read_stats.get("total_opens", 0)
    active_users = sum(1 for u in users.values() if u.get("notifications", True))
    quiet_users   = sum(1 for u in users.values() if u.get("quiet_mode_enabled", True))
    breaking_only = sum(1 for u in users.values() if u.get("alert_level") == "breaking")
    interests_set = sum(1 for u in users.values() if u.get("interests"))
    # ── ساعات الذروة ──
    hourly = _broadcast_stats.get("hourly_activity", {})
    if hourly:
        sorted_hours = sorted(hourly.items(), key=lambda x: int(x[0]))
        peak_hour, peak_val = max(hourly.items(), key=lambda x: x[1])
        bar_max = max(hourly.values()) or 1
        peak_chart = ""
        for h, v in sorted_hours:
            bar = "█" * max(1, round(v / bar_max * 8))
            peak_mark = " ⬅ ذروة" if h == peak_hour else ""
            peak_chart += f"`{int(h):02d}:00` {bar}{peak_mark}\n"
    else:
        peak_chart = "_لا بيانات بعد_"
    report = (
        f"📊 *التقرير اليومي — {today}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 إجمالي المستخدمين: `{total_users_count}`\n"
        f"🆕 جدد اليوم: `{new_today}`\n"
        f"🔔 نشطون (إشعارات مفعّلة): `{active_users}`\n"
        f"⭐ مميزون: `{premium_count}`\n"
        f"🌙 وضع صامت: `{quiet_users}`\n"
        f"🚨 عاجلة فقط: `{breaking_only}`\n"
        f"📌 لديهم اهتمامات: `{interests_set}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📺 القنوات/المجموعات: `{channels_count}`\n"
        f"📰 إجمالي أخبار القنوات: `{total_ch_news}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"📖 قراءات اليوم: `{read_today}`\n"
        f"📖 قراءات أمس: `{read_yest}`\n"
        f"📖 إجمالي القراءات: `{total_reads}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"⏰ *ساعات الذروة:*\n{peak_chart}"
        f"━━━━━━━━━━━━━━\n"
        f"🤖 @{BOT_USERNAME}"
    )
    try:
        bot.send_message(ADMIN_ID, report, parse_mode="Markdown")
    except Exception:
        pass
    for admin_id in extra_admins:
        try:
            bot.send_message(admin_id, report, parse_mode="Markdown")
        except:
            pass

scheduler.add_job(send_daily_report, 'cron', hour=8, minute=0)
scheduler.add_job(_safe_job(send_rating_request), 'cron', hour=20, minute=0)
scheduler.add_job(_safe_job(reset_daily_rating_flags), 'cron', hour=0, minute=0)
scheduler.add_job(_safe_job(check_inactive_users), 'cron', hour=10, minute=0)
scheduler.add_job(_safe_job(check_summary_hint), 'interval', hours=12)
scheduler.add_job(_safe_job(auto_backup), 'interval', hours=12)
scheduler.add_job(_safe_job(send_evening_recap), 'cron', hour=18, minute=0)
scheduler.add_job(_safe_job(_validate_rss_sources), 'cron', hour=3, minute=0)    # فحص ليلي للمصادر
scheduler.add_job(_safe_job(send_weekly_summary),  'cron', day_of_week='fri', hour=10, minute=0)  # ملخص أسبوعي كل جمعة

# ======== /addtrack ========
def _do_addtrack(uid, symbol):
    existing = tracked_assets.get(str(uid), {}).get("assets", [])
    if symbol in existing:
        bot.send_message(uid, f"📌 *{symbol}* مضافة مسبقاً في قائمة التتبع.", parse_mode="Markdown")
        return
    if len(existing) >= 20:
        bot.send_message(uid, "⚠️ الحد الأقصى 20 أصل. استخدم /removetrack لحذف واحد.")
        return
    bot.send_message(uid, f"🔍 جارٍ التحقق من الرمز *{symbol}*...", parse_mode="Markdown")
    price = fetch_asset_price(symbol)
    if price is None:
        bot.send_message(uid, f"⚠️ لم يتم التعرف على الرمز *{symbol}*.\nتأكد من الرمز وأعد المحاولة، مثال: `BTC`، `AAPL`، `GC=F`", parse_mode="Markdown")
        return
    if str(uid) not in tracked_assets:
        tracked_assets[str(uid)] = {"assets": [], "last_prices": {}}
    tracked_assets[str(uid)]["assets"].append(symbol)
    tracked_assets[str(uid)]["last_prices"][symbol] = price
    save_tracked_assets()
    bot.send_message(uid,
        f"✅ تمت إضافة *{symbol}* للتتبع!\n"
        f"💰 السعر الحالي: `${price:,.4f}`\n\n"
        f"📋 /mytrack — لعرض قائمتك",
        parse_mode="Markdown"
    )

def _addtrack_step_cmd(message):
    uid = message.from_user.id
    if not message.text or message.text.startswith('/'):
        bot.send_message(uid, "⚠️ تم إلغاء إضافة الرمز. أرسل /addtrack للمحاولة مجدداً.")
        return
    symbol = message.text.strip().upper()
    _do_addtrack(uid, symbol)

@bot.message_handler(commands=["addtrack"])
def cmd_addtrack(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/addtrack")
    parts = m.text.strip().split()
    if len(parts) < 2:
        bot.send_message(uid,
            "➕ *إضافة رمز للتتبع*\n\n"
            "أرسل رمز الأصل الذي تريد تتبعه:\n\n"
            "🪙 عملات رقمية: `BTC`، `ETH`، `SOL`\n"
            "📈 أسهم: `AAPL`، `TSLA`، `NVDA`\n"
            "🥇 سلع: `GC=F` (ذهب)، `CL=F` (نفط)\n"
            "💱 عملات: `USD`، `EUR`، `GBP`",
            parse_mode="Markdown"
        )
        bot.register_next_step_handler_by_chat_id(uid, _addtrack_step_cmd)
        return
    symbol = parts[1].upper()
    _do_addtrack(uid, symbol)

# ======== /addchannel ========
@bot.message_handler(commands=["addchannel"])
def cmd_addchannel(m):
    """
    أمر للأدمن: إضافة قناة تيليغرام ديناميكياً لقائمة مصادر الأخبار.
    الاستخدام:  /addchannel <handle> [اللغة] [الاسم]
    مثال:       /addchannel AlJazeeraArabic العربية 🇮🇶 الجزيرة العربية
    """
    uid = m.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ هذا الأمر للمشرفين فقط.")
        return
    parts = m.text.strip().split(None, 3)
    if len(parts) < 2:
        langs_list = "\n".join(f"• `{l}`" for l in list(TELEGRAM_NEWS_CHANNELS.keys())[:8])
        bot.send_message(uid,
            "📺 *إضافة قناة تيليغرام كمصدر أخبار*\n\n"
            "*الاستخدام:*\n"
            "`/addchannel <handle> [اللغة] [الاسم]`\n\n"
            "*أمثلة:*\n"
            "`/addchannel NewChannelHandle العربية 🇮🇶 اسم القناة`\n"
            "`/addchannel BBCBreaking English 🇬🇧 BBC Breaking`\n\n"
            f"*اللغات المتاحة:*\n{langs_list}\n...",
            parse_mode="Markdown"
        )
        return
    handle = parts[1].lstrip("@")
    lang = parts[2] if len(parts) > 2 else "العربية 🇮🇶"
    # إذا اللغة تبدأ بـ "ال" وبعدها مسافة (معظمها عربية) دمجها مع الإيموجي
    # ابحث عن أقرب تطابق للغة
    matched_lang = None
    for l in TELEGRAM_NEWS_CHANNELS.keys():
        if lang in l or l.startswith(lang.split()[0]):
            matched_lang = l
            break
    if not matched_lang:
        matched_lang = lang  # أضفها كلغة جديدة
    name = parts[3] if len(parts) > 3 else f"@{handle}"
    ok, result = add_custom_tg_channel(matched_lang, handle, name)
    if ok:
        total = len(TELEGRAM_NEWS_CHANNELS.get(matched_lang, []))
        bot.send_message(uid,
            f"✅ *تمت الإضافة بنجاح!*\n\n"
            f"📺 القناة: `@{handle}`\n"
            f"📛 الاسم: {name}\n"
            f"🌐 اللغة: {matched_lang}\n"
            f"📊 إجمالي قنوات {matched_lang}: *{total}*\n\n"
            f"ستبدأ القناة في المساهمة بالأخبار في دورة البث القادمة.",
            parse_mode="Markdown"
        )
    else:
        bot.send_message(uid, f"⚠️ `@{handle}` {result} في {matched_lang}", parse_mode="Markdown")


@bot.message_handler(commands=["removechannel"])
def cmd_removechannel(m):
    """
    أمر للأدمن: حذف قناة تيليغرام من قائمة المصادر المخصصة.
    الاستخدام: /removechannel <handle>
    """
    uid = m.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ هذا الأمر للمشرفين فقط.")
        return
    parts = m.text.strip().split()
    if len(parts) < 2:
        bot.send_message(uid,
            "🗑 *حذف قناة من مصادر الأخبار*\n\n"
            "*الاستخدام:*\n`/removechannel <handle>`\n\n"
            "*مثال:*\n`/removechannel OldChannelHandle`\n\n"
            "⚠️ يعمل فقط على القنوات المُضافة يدوياً (المخصصة).",
            parse_mode="Markdown"
        )
        return
    handle = parts[1].lstrip("@")
    ok, langs = remove_custom_tg_channel(handle)
    if ok:
        bot.send_message(uid,
            f"✅ تم حذف `@{handle}` من مصادر الأخبار.\n"
            f"اللغات المتأثرة: {', '.join(langs)}",
            parse_mode="Markdown"
        )
    else:
        bot.send_message(uid,
            f"⚠️ `@{handle}` غير موجودة في قائمة المصادر المخصصة.\n"
            f"(القنوات الافتراضية لا يمكن حذفها بهذا الأمر)",
            parse_mode="Markdown"
        )


@bot.message_handler(commands=["discover"])
def cmd_discover(m):
    """
    أمر للأدمن: اكتشاف RSS تلقائياً من رابط موقع ويب وإضافته.
    الاستخدام: /discover <url> [اللغة]
    مثال:      /discover https://www.example-news.com العربية 🇮🇶
    """
    uid = m.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ هذا الأمر للمشرفين فقط.")
        return
    parts = m.text.strip().split(None, 2)
    if len(parts) < 2:
        bot.send_message(uid,
            "🔍 *اكتشاف RSS تلقائياً*\n\n"
            "*الاستخدام:*\n"
            "`/discover <url> [اللغة]`\n\n"
            "*أمثلة:*\n"
            "`/discover https://www.example-news.com العربية 🇮🇶`\n"
            "`/discover https://www.bbc.com/arabic`\n\n"
            "سيحاول البوت اكتشاف رابط RSS للموقع تلقائياً وإضافته.",
            parse_mode="Markdown"
        )
        return
    url = parts[1].strip()
    lang = parts[2].strip() if len(parts) > 2 else "العربية 🇮🇶"
    # أقرب لغة
    matched_lang = None
    for l in RSS.keys():
        if lang in l or l.startswith(lang.split()[0]):
            matched_lang = l
            break
    if not matched_lang:
        matched_lang = lang
    status_msg = bot.send_message(uid,
        f"🔍 *أبحث عن مصدر RSS للموقع:*\n`{url}`\n\nانتظر...",
        parse_mode="Markdown"
    )
    discovered = _auto_discover_rss(url)
    if not discovered:
        bot.edit_message_text(
            f"❌ *لم أجد مصدر RSS للموقع:*\n`{url}`\n\n"
            "جربت الأنماط الشائعة ولم أجد شيئاً صالحاً.\n"
            "يمكنك إضافة الرابط مباشرة من لوحة الإدارة إذا كنت تعرفه.",
            uid, status_msg.message_id, parse_mode="Markdown"
        )
        return
    # أضف إلى RSS
    if matched_lang not in RSS:
        RSS[matched_lang] = []
    if discovered in RSS[matched_lang]:
        bot.edit_message_text(
            f"⚠️ *المصدر موجود مسبقاً:*\n`{discovered}`",
            uid, status_msg.message_id, parse_mode="Markdown"
        )
        return
    RSS[matched_lang].append(discovered)
    save_rss()
    diff = f"\n_(تم اكتشافه من: `{url}`)_" if discovered != url else ""
    bot.edit_message_text(
        f"✅ *تم اكتشاف وإضافة المصدر بنجاح!*\n\n"
        f"🔗 الرابط: `{discovered}`{diff}\n"
        f"🌐 اللغة: {matched_lang}\n"
        f"📡 إجمالي مصادر {matched_lang}: *{len(RSS[matched_lang])}*",
        uid, status_msg.message_id, parse_mode="Markdown"
    )


@bot.message_handler(commands=["listchannels"])
def cmd_listchannels(m):
    """يعرض القنوات المضافة ديناميكياً فقط (المخصصة) مع إمكانية حذفها"""
    uid = m.from_user.id
    if not is_admin(uid):
        bot.send_message(uid, "❌ هذا الأمر للمشرفين فقط.")
        return
    if not _custom_tg_channels or all(len(v) == 0 for v in _custom_tg_channels.values()):
        bot.send_message(uid,
            "📭 لم تُضف أي قنوات مخصصة بعد.\n"
            "استخدم `/addchannel` لإضافة قنوات جديدة.",
            parse_mode="Markdown"
        )
        return
    msg = "📺 *قنوات التيليغرام المضافة يدوياً:*\n\n"
    for lang, channels in _custom_tg_channels.items():
        if channels:
            msg += f"*{lang}:*\n"
            for ch in channels:
                msg += f"  • `@{ch['handle']}` — {ch['name']}\n"
                msg += f"    🗑 `/removechannel {ch['handle']}`\n"
            msg += "\n"
    bot.send_message(uid, msg, parse_mode="Markdown")


# ======== /chart ========

CHART_CATEGORIES = {
    "crypto": (
        "🪙 Crypto",
        ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
         "LINK", "DOT", "MATIC", "LTC", "TRX", "ATOM", "TON",
         "SHIB", "NEAR", "ARB", "UNI", "ALGO"],
    ),
    "forex": (
        "💱 Forex",
        ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X",
         "USDCHF=X", "NZDUSD=X", "USDTRY=X", "USDEGP=X",
         "USDSAR=X", "USDKWD=X", "USDIQD=X"],
    ),
    "metals": (
        "🥇 Metals & Commodities",
        ["GC=F", "SI=F", "PL=F", "HG=F", "CL=F", "BZ=F", "NG=F",
         "ZW=F", "ZC=F", "CC=F"],
    ),
    "stocks": (
        "📈 Stocks",
        ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL",
         "META", "NFLX", "BABA", "2222.SR"],
    ),
    "indices": (
        "📊 Indices",
        ["^GSPC", "^IXIC", "^DJI", "^FTSE", "^DAX",
         "^N225", "^HSI", "^BSESN", "^STOXX50E"],
    ),
}

CHART_ASSET_LABELS = {
    "BTC": "Bitcoin",    "ETH": "Ethereum",  "SOL": "Solana",    "BNB": "BNB",
    "XRP": "XRP",        "DOGE": "Dogecoin", "ADA": "Cardano",   "AVAX": "Avalanche",
    "LINK": "Chainlink", "DOT": "Polkadot",  "MATIC": "Polygon", "LTC": "Litecoin",
    "TRX": "TRON",       "ATOM": "Cosmos",   "TON": "TON",       "SHIB": "SHIB",
    "NEAR": "NEAR",      "ARB": "Arbitrum",  "UNI": "Uniswap",   "ALGO": "Algorand",
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD", "USDCAD=X": "USD/CAD", "USDCHF=X": "USD/CHF",
    "NZDUSD=X": "NZD/USD", "USDTRY=X": "USD/TRY", "USDEGP=X": "USD/EGP",
    "USDSAR=X": "USD/SAR", "USDKWD=X": "USD/KWD", "USDIQD=X": "USD/IQD",
    "GC=F": "Gold",     "SI=F": "Silver",     "PL=F": "Platinum",
    "HG=F": "Copper",   "CL=F": "WTI Oil",    "BZ=F": "Brent Oil",
    "NG=F": "Nat. Gas", "ZW=F": "Wheat",      "ZC=F": "Corn",    "CC=F": "Cocoa",
    "AAPL": "Apple",    "TSLA": "Tesla",      "NVDA": "NVIDIA",  "MSFT": "Microsoft",
    "AMZN": "Amazon",   "GOOGL": "Google",    "META": "Meta",    "NFLX": "Netflix",
    "BABA": "Alibaba",  "2222.SR": "Aramco",
    "^GSPC": "S&P 500", "^IXIC": "NASDAQ",    "^DJI": "Dow Jones",
    "^FTSE": "FTSE 100","^DAX": "DAX",        "^N225": "Nikkei 225",
    "^HSI": "Hang Seng","^BSESN": "Sensex",   "^STOXX50E": "Euro Stoxx 50",
}

CHART_CAT_PROMPTS = {
    "العربية 🇮🇶":    "📊 *اختر فئة الأصل:*\n\n🪙 عملات رقمية │ 💱 فوركس │ 🥇 معادن وسلع │ 📈 أسهم │ 📊 مؤشرات",
    "English 🇬🇧":   "📊 *Choose asset category:*\n\n🪙 Crypto │ 💱 Forex │ 🥇 Metals & Commodities │ 📈 Stocks │ 📊 Indices",
    "Русский 🇷🇺":   "📊 *Выберите категорию:*\n\n🪙 Крипто │ 💱 Форекс │ 🥇 Металлы │ 📈 Акции │ 📊 Индексы",
    "فارسی 🇮🇷":     "📊 *دستهبندی را انتخاب کنید:*\n\n🪙 رمزارز │ 💱 فارکس │ 🥇 فلزات │ 📈 سهام │ 📊 شاخصها",
    "हिन्दी 🇮🇳":    "📊 *श्रेणी चुनें:*\n\n🪙 क्रिप्टो │ 💱 फ़ॉरेक्स │ 🥇 धातु │ 📈 स्टॉक │ 📊 सूचकांक",
    "Português 🇧🇷": "📊 *Escolha a categoria:*\n\n🪙 Cripto │ 💱 Forex │ 🥇 Metais │ 📈 Ações │ 📊 Índices",
    "Türkçe 🇹🇷":    "📊 *Kategori seçin:*\n\n🪙 Kripto │ 💱 Forex │ 🥇 Metaller │ 📈 Hisseler │ 📊 Endeksler",
    "اردو 🇵🇰":      "📊 *زمرہ منتخب کریں:*\n\n🪙 کرپٹو │ 💱 فاریکس │ 🥇 دھاتیں │ 📈 حصص │ 📊 اشاریے",
    "Deutsch 🇩🇪":   "📊 *Kategorie wählen:*\n\n🪙 Krypto │ 💱 Forex │ 🥇 Metalle │ 📈 Aktien │ 📊 Indizes",
    "Українська 🇺🇦":"📊 *Виберіть категорію:*\n\n🪙 Крипто │ 💱 Форекс │ 🥇 Метали │ 📈 Акції │ 📊 Індекси",
    "Italiano 🇮🇹":  "📊 *Scegli categoria:*\n\n🪙 Cripto │ 💱 Forex │ 🥇 Metalli │ 📈 Azioni │ 📊 Indici",
    "Español 🇲🇽":   "📊 *Elige categoría:*\n\n🪙 Cripto │ 💱 Forex │ 🥇 Metales │ 📈 Acciones │ 📊 Índices",
}

CHART_INTERVALS = {
    "Minutes": {"label": "آخر 10 دقائق",  "label_en": "Last 10 Minutes (Minute)", "range": "1d",  "yf_interval": "1m",  "ts_fmt": "%H:%M",   "ts_label": "Minute"},
    "Hours":   {"label": "آخر 10 ساعات",  "label_en": "Last 10 Hours (Hourly)",   "range": "7d",  "yf_interval": "1h",  "ts_fmt": "%H:%M",   "ts_label": "Hourly"},
    "Days":    {"label": "آخر 10 أيام",   "label_en": "Last 10 Days (Daily)",     "range": "90d", "yf_interval": "1d",  "ts_fmt": "%d %b",   "ts_label": "Daily"},
}

CHART_PROMPTS = {
    "العربية 🇮🇶":   "📊 اختر الأصل الذي تريد رسمه:",
    "English 🇬🇧":  "📊 Choose the asset you want to chart:",
    "Русский 🇷🇺":  "📊 Выберите актив для графика:",
    "فارسی 🇮🇷":    "📊 دارایی مورد نظر برای نمودار را انتخاب کنید:",
    "हिन्दी 🇮🇳":   "📊 चार्ट के लिए संपत्ति चुनें:",
    "Português 🇧🇷":"📊 Escolha o ativo para o gráfico:",
    "Türkçe 🇹🇷":   "📊 Grafik için varlık seçin:",
    "اردو 🇵🇰":     "📊 چارٹ کے لیے اثاثہ منتخب کریں:",
    "Deutsch 🇩🇪":  "📊 Wählen Sie das Asset für den Chart:",
    "Українська 🇺🇦":"📊 Оберіть актив для графіка:",
    "Italiano 🇮🇹": "📊 Scegli l'asset per il grafico:",
    "Español 🇲🇽":  "📊 Elige el activo para el gráfico:",
}

INTERVAL_PROMPTS = {
    "العربية 🇮🇶":   "⏱ اختر الفاصل الزمني:",
    "English 🇬🇧":  "⏱ Choose the time interval:",
    "Русский 🇷🇺":  "⏱ Выберите временной интервал:",
    "فارسی 🇮🇷":    "⏱ بازه زمانی را انتخاب کنید:",
    "हिन्दी 🇮🇳":   "⏱ समय अंतराल चुनें:",
    "Português 🇧🇷":"⏱ Escolha o intervalo de tempo:",
    "Türkçe 🇹🇷":   "⏱ Zaman aralığı seçin:",
    "اردو 🇵🇰":     "⏱ وقت کا وقفہ منتخب کریں:",
    "Deutsch 🇩🇪":  "⏱ Zeitintervall wählen:",
    "Українська 🇺🇦":"⏱ Виберіть часовий інтервал:",
    "Italiano 🇮🇹": "⏱ Scegli l'intervallo di tempo:",
    "Español 🇲🇽":  "⏱ Elige el intervalo de tiempo:",
}


def _fetch_ohlc(symbol, yf_interval, range_):
    """جلب بيانات OHLC من Yahoo Finance."""
    try:
        encoded = requests.utils.quote(symbol, safe='')
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            f"?interval={yf_interval}&range={range_}"
        )
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12).json()
        result = r.get("chart", {}).get("result")
        if not result:
            return None
        quotes = result[0]["indicators"]["quote"][0]
        timestamps = result[0].get("timestamp", [])
        opens  = quotes.get("open",  [])
        closes = quotes.get("close", [])
        highs  = quotes.get("high",  [])
        lows   = quotes.get("low",   [])
        bars = []
        for i in range(len(timestamps)):
            try:
                o = opens[i]; c = closes[i]; h = highs[i]; l = lows[i]
                if None in (o, c, h, l):
                    continue
                bars.append({"ts": timestamps[i], "o": o, "c": c, "h": h, "l": l})
            except Exception:
                continue
        return bars[-10:] if len(bars) > 10 else bars
    except Exception:
        return None


def _crypto_ohlc(symbol, yf_interval, range_):
    """محاولة CoinGecko للعملات الرقمية أولاً، ثم Yahoo Finance."""
    cg_id = CRYPTO_IDS.get(symbol)
    if cg_id:
        days_map = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
        days = days_map.get(range_, 7)
        try:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc?vs_currency=usd&days={days}",
                timeout=12
            ).json()
            bars = []
            for row in r:
                ts, o, h, l, c = row
                bars.append({"ts": ts // 1000, "o": o, "c": c, "h": h, "l": l})
            return bars[-10:] if len(bars) > 10 else bars
        except Exception:
            pass
    return _fetch_ohlc(symbol, yf_interval, range_)


def _fmt_price(v):
    if v is None:
        return "—"
    if v >= 10000:
        return f"{v:,.0f}"
    elif v >= 1:
        return f"{v:,.2f}"
    elif v >= 0.0001:
        return f"{v:.6f}"
    else:
        return f"{v:.8f}"

def _build_text_chart(symbol, bars, interval_key):
    """رسم بياني نصي بشكل شموع ┃█┃ مع الطابع الزمني و High-Low والاتجاه."""
    if not bars:
        return None
    label = CHART_ASSET_LABELS.get(symbol, symbol)
    ivl = CHART_INTERVALS[interval_key]
    ts_fmt = ivl.get("ts_fmt", "%H:%M")

    ranges = [b["h"] - b["l"] for b in bars if b["h"] and b["l"]]
    max_range = max(ranges) if ranges else 1
    MAX_BLOCKS = 8

    header = f"📊 {label} – {ivl['label_en']}"
    divider = "─" * len(header)
    lines = [header, divider, ""]

    prev_close = None
    for bar in bars:
        ts   = bar["ts"]
        o, c, h, l = bar["o"], bar["c"], bar["h"], bar["l"]
        if None in (o, c, h, l):
            continue

        try:
            time_str = datetime.datetime.utcfromtimestamp(ts).strftime(ts_fmt)
        except Exception:
            time_str = "??:??"

        direction = "🔼" if (prev_close is None and c >= o) or (prev_close is not None and c >= prev_close) else "🔽"

        rng = h - l
        blocks = max(1, round((rng / max_range) * MAX_BLOCKS)) if max_range > 0 else 1
        bar_str = "┃" + "█" * blocks + "┃"

        lo_fmt = _fmt_price(l)
        hi_fmt = _fmt_price(h)
        range_str = f"{lo_fmt}-{hi_fmt}"

        lines.append(f"{time_str} │ {bar_str} {range_str} {direction}")
        prev_close = c

    lines.append("")
    last  = bars[-1]
    first = bars[0]
    net   = ((last["c"] - first["o"]) / first["o"]) * 100 if first["o"] else 0
    trend_icon = "📈" if net >= 0 else "📉"
    lines += [
        divider,
        f"{trend_icon}  {net:+.2f}%   🔼 {_fmt_price(max(b['h'] for b in bars))}   🔽 {_fmt_price(min(b['l'] for b in bars))}",
        f"🤖 @{BOT_USERNAME}",
    ]
    return "\n".join(lines)


def _build_chart_categories_markup(lang):
    markup = types.InlineKeyboardMarkup(row_width=2)
    cat_buttons = [
        types.InlineKeyboardButton(label, callback_data=f"chart_cat_{key}")
        for key, (label, _) in CHART_CATEGORIES.items()
    ]
    for i in range(0, len(cat_buttons), 2):
        markup.row(*cat_buttons[i:i+2])
    custom_label = "🔍 رمز مخصص" if lang == "العربية 🇮🇶" else "🔍 Custom Symbol"
    markup.row(types.InlineKeyboardButton(custom_label, callback_data="chart_cat_custom"))
    return markup

def _send_chart_categories(uid, lang, edit_msg_id=None):
    prompt = CHART_CAT_PROMPTS.get(lang, CHART_CAT_PROMPTS["English 🇬🇧"])
    markup = _build_chart_categories_markup(lang)
    if edit_msg_id:
        try:
            bot.edit_message_text(prompt, chat_id=uid, message_id=edit_msg_id,
                                  reply_markup=markup, parse_mode="Markdown")
        except Exception:
            bot.send_message(uid, prompt, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(uid, prompt, reply_markup=markup, parse_mode="Markdown")

def _chart_custom_symbol_step(message):
    uid = message.from_user.id
    if not message.text or message.text.startswith('/'):
        bot.send_message(uid, "⚠️ تم الإلغاء. أرسل /chart للبدء مجدداً.")
        return
    symbol = message.text.strip().upper()
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    prompt = INTERVAL_PROMPTS.get(lang, INTERVAL_PROMPTS["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.row(*[
        types.InlineKeyboardButton(k, callback_data=f"chart_interval_{symbol}_{k}")
        for k in CHART_INTERVALS.keys()
    ])
    label = CHART_ASSET_LABELS.get(symbol, symbol)
    bot.send_message(uid, f"✅ *{label}*\n{prompt}", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=["chart"])
def cmd_chart(m):
    uid = m.from_user.id
    _update_user_last_command(uid, "/chart")
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    _send_chart_categories(uid, lang)

@bot.callback_query_handler(func=lambda c: c.data.startswith("chart_cat_"))
def chart_cat_selected(call):
    uid = call.from_user.id
    cat = call.data.replace("chart_cat_", "")
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    bot.answer_callback_query(call.id)
    if cat == "custom":
        custom_text = (
            "🔍 *أرسل رمز الأصل:*\n\n"
            "🪙 عملات رقمية: `BTC`، `ETH`، `SOL`\n"
            "💱 فوركس: `EURUSD=X`، `GBPUSD=X`\n"
            "🥇 معادن: `GC=F` (ذهب)، `SI=F` (فضة)\n"
            "🛢 سلع: `CL=F` (نفط)، `NG=F` (غاز)\n"
            "📈 أسهم: `AAPL`، `TSLA`، `NVDA`\n"
            "📊 مؤشرات: `^GSPC`، `^IXIC`، `^DJI`"
            if lang == "العربية 🇮🇶" else
            "🔍 *Send the asset symbol:*\n\n"
            "🪙 Crypto: `BTC`, `ETH`, `SOL`\n"
            "💱 Forex: `EURUSD=X`, `GBPUSD=X`\n"
            "🥇 Metals: `GC=F` (Gold), `SI=F` (Silver)\n"
            "🛢 Commodities: `CL=F` (WTI Oil), `NG=F` (Gas)\n"
            "📈 Stocks: `AAPL`, `TSLA`, `NVDA`\n"
            "📊 Indices: `^GSPC`, `^IXIC`, `^DJI`"
        )
        try:
            bot.edit_message_text(custom_text, chat_id=uid,
                                  message_id=call.message.message_id, parse_mode="Markdown")
        except Exception:
            bot.send_message(uid, custom_text, parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, _chart_custom_symbol_step)
        return
    cat_data = CHART_CATEGORIES.get(cat)
    if not cat_data:
        return
    cat_label, assets = cat_data
    prompt = CHART_PROMPTS.get(lang, CHART_PROMPTS["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup(row_width=4)
    buttons = [
        types.InlineKeyboardButton(CHART_ASSET_LABELS.get(s, s), callback_data=f"chart_asset_{s}")
        for s in assets
    ]
    for i in range(0, len(buttons), 4):
        markup.row(*buttons[i:i+4])
    back_label = "⬅️ رجوع" if lang == "العربية 🇮🇶" else "⬅️ Back"
    markup.row(types.InlineKeyboardButton(back_label, callback_data="chart_back_cats"))
    try:
        bot.edit_message_text(
            f"{cat_label}\n{prompt}",
            chat_id=uid,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception:
        bot.send_message(uid, f"{cat_label}\n{prompt}", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data == "chart_back_cats")
def chart_back_cats(call):
    uid = call.from_user.id
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    bot.answer_callback_query(call.id)
    _send_chart_categories(uid, lang, edit_msg_id=call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("chart_asset_"))
def chart_asset_selected(call):
    uid = call.from_user.id
    symbol = call.data.replace("chart_asset_", "")
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    bot.answer_callback_query(call.id)
    prompt = INTERVAL_PROMPTS.get(lang, INTERVAL_PROMPTS["English 🇬🇧"])
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.row(*[
        types.InlineKeyboardButton(k, callback_data=f"chart_interval_{symbol}_{k}")
        for k in CHART_INTERVALS.keys()
    ])
    back_label = "⬅️ رجوع" if lang == "العربية 🇮🇶" else "⬅️ Back"
    markup.row(types.InlineKeyboardButton(back_label, callback_data="chart_back_cats"))
    label = CHART_ASSET_LABELS.get(symbol, symbol)
    try:
        bot.edit_message_text(
            f"✅ *{label}*\n{prompt}",
            chat_id=uid,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception:
        bot.send_message(uid, f"✅ *{label}*\n{prompt}", reply_markup=markup, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data.startswith("chart_interval_"))
def chart_interval_selected(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id, "⏳ جاري تحميل البيانات...")
    parts = call.data.split("_")
    interval_key = parts[-1]
    symbol = "_".join(parts[2:-1])
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    ivl = CHART_INTERVALS.get(interval_key, CHART_INTERVALS["Hours"])
    label = CHART_ASSET_LABELS.get(symbol, symbol)
    bot.edit_message_text(
        f"📊 *{label}* — {ivl['label_en']}\n⏳ جاري تحميل الشموع...",
        chat_id=uid,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )
    if symbol in CRYPTO_IDS:
        bars = _crypto_ohlc(symbol, ivl["yf_interval"], ivl["range"])
    else:
        bars = _fetch_ohlc(symbol, ivl["yf_interval"], ivl["range"])
    if not bars:
        bot.send_message(uid, f"⚠️ لم تتوفر بيانات لـ *{label}* بهذا الفاصل الزمني.", parse_mode="Markdown")
        return
    chart_text = _build_text_chart(symbol, bars, interval_key)
    if not chart_text:
        bot.send_message(uid, "⚠️ تعذّر بناء الرسم البياني.", parse_mode="Markdown")
        return
    bot.send_message(uid, f"<pre>{chart_text}</pre>", parse_mode="HTML")


# ======== أوامر الأخبار والطقس والأسواق ========

@bot.message_handler(commands=["news"])
def cmd_news(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/news")
    if str(uid) not in users:
        bot.send_message(uid, "⚠️ أرسل /start أولاً لإعداد حسابك.")
        return
    send_hourly_news(uid)


@bot.message_handler(commands=["trending"])
def cmd_trending(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/trending")
    if str(uid) not in users:
        bot.send_message(uid, "⚠️ أرسل /start أولاً لإعداد حسابك.")
        return
    send_trending_news(uid)


def send_daily_top3(uid):
    user = users.get(str(uid))
    if not user:
        return
    lang = user.get("lang", "English 🇬🇧")
    feeds = RSS.get(lang, [])
    headlines = []
    for feed_url in feeds:
        try:
            feed = _parse_feed(feed_url)
            if feed is None:
                feed = feedparser.parse(feed_url)
            if not feed:
                continue
            for item in feed.entries[:10]:
                title = getattr(item, 'title', '').strip()
                link  = getattr(item, 'link', '').strip()
                item_sum = getattr(item, 'summary', '') or getattr(item, 'description', '')
                if title and link and _title_in_lang(title, lang):
                    pub_dt = _pub_dt_from_item(item)
                    headlines.append((title, link, item_sum, feed_url, pub_dt))
            if len(headlines) >= 10:
                break
        except Exception:
            pass
    if not headlines:
        bot.send_message(uid, t(lang, "no_news"), parse_mode="Markdown")
        return
    top3 = headlines[:3]
    SUMMARY_HEADER = {
        "العربية 🇮🇶":   "📝 *أبرز 3 أحداث اليوم*\n━━━━━━━━━━━━━━━",
        "English 🇬🇧":  "📝 *Top 3 Events Today*\n━━━━━━━━━━━━━━━",
        "Русский 🇷🇺":  "📝 *Топ-3 события дня*\n━━━━━━━━━━━━━━━",
        "فارسی 🇮🇷":    "📝 *۳ رویداد برتر امروز*\n━━━━━━━━━━━━━━━",
        "हिन्दी 🇮🇳":   "📝 *आज की शीर्ष 3 घटनाएं*\n━━━━━━━━━━━━━━━",
        "Português 🇧🇷":"📝 *Top 3 Eventos de Hoje*\n━━━━━━━━━━━━━━━",
        "Türkçe 🇹🇷":   "📝 *Bugünün En Önemli 3 Olayı*\n━━━━━━━━━━━━━━━",
        "اردو 🇵🇰":     "📝 *آج کے سرفہرست 3 واقعات*\n━━━━━━━━━━━━━━━",
        "Deutsch 🇩🇪":  "📝 *Top 3 Ereignisse des Tages*\n━━━━━━━━━━━━━━━",
        "Українська 🇺🇦":"📝 *Топ-3 події дня*\n━━━━━━━━━━━━━━━",
        "Italiano 🇮🇹": "📝 *I 3 Principali Eventi di Oggi*\n━━━━━━━━━━━━━━━",
        "Español 🇲🇽":  "📝 *Top 3 Eventos de Hoy*\n━━━━━━━━━━━━━━━",
    }
    header = SUMMARY_HEADER.get(lang, SUMMARY_HEADER["English 🇬🇧"])
    bot.send_message(uid, header, parse_mode="Markdown")
    nums = ["1️⃣", "2️⃣", "3️⃣"]
    for i, (title, link, item_sum, feed_url, pub_dt) in enumerate(top3):
        markup = make_news_share_markup(link, title, lang, item_sum)
        src_name = get_source_name_from_url(feed_url)
        pub_time_str = _format_pub_time(pub_dt, lang=lang)
        num_label = nums[i] if i < len(nums) else f"{i+1}."
        label = f"{num_label} {t(lang, 'label_news')}"
        bot.send_message(uid,
            format_news_item(label, title, lang, src_name, pub_time_str, summary=item_sum),
            parse_mode="Markdown",
            reply_markup=markup
        )


@bot.message_handler(commands=["summary"])
def cmd_summary(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/summary")
    if str(uid) not in users:
        bot.send_message(uid, "⚠️ أرسل /start أولاً لإعداد حسابك.")
        return
    send_daily_top3(uid)


@bot.message_handler(commands=["weather"])
def cmd_weather(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/weather")
    user = users.get(str(uid))
    if not user:
        bot.send_message(uid, "⚠️ أرسل /start أولاً لإعداد حسابك.")
        return
    province = user.get("province", "")
    if not province:
        bot.send_message(uid, "⚠️ لم تحدد مدينتك بعد. أرسل /start لإعادة الإعداد.")
        return
    send_detailed_weather(uid)


@bot.message_handler(commands=["currency"])
def cmd_currency(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/currency")
    user = users.get(str(uid))
    if not user:
        bot.send_message(uid, "⚠️ أرسل /start أولاً لإعداد حسابك.")
        return
    send_currency(uid)


@bot.message_handler(commands=["markets"])
def cmd_markets(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/markets")
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    bot.send_message(uid, "⏳ جاري تحميل أسعار الأسواق...", parse_mode="Markdown")

    MARKET_SYMBOLS = [
        ("💎 عملات رقمية", ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE"]),
        ("💱 عملات فيات", ["EUR", "GBP", "IQD", "SAR", "AED", "TRY"]),
        ("🏅 سلع", ["GC=F", "SI=F", "CL=F", "BZ=F"]),
        ("📈 مؤشرات", ["^GSPC", "^IXIC"]),
        ("📊 أسهم كبرى", ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN"]),
    ]

    lines = ["📊 *أسعار الأسواق العالمية*\n━━━━━━━━━━━━━━━"]
    for section_title, symbols in MARKET_SYMBOLS:
        lines.append(f"\n*{section_title}:*")
        for sym in symbols:
            price = fetch_asset_price(sym)
            lines.append(f"  {format_asset_price(sym, price)}")

    lines.append(f"━━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}")
    bot.send_message(uid, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["alerts"])
def cmd_alerts(m):
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    _update_user_last_command(uid, "/alerts")
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")

    tracked = tracked_assets.get(str(uid), {}).get("assets", [])
    current_alert = user.get("currency_alert")

    markup = types.InlineKeyboardMarkup(row_width=1)

    if tracked:
        markup.add(types.InlineKeyboardButton(
            "💰 تنبيه سعر أصل من قائمة التتبع", callback_data="alerts_track"
        ))

    markup.add(types.InlineKeyboardButton(
        "💱 تنبيه سعر صرف الدولار", callback_data="prem_currency_alert"
    ))
    markup.add(types.InlineKeyboardButton(
        "📋 عرض قائمة التتبع", callback_data="alerts_show_track"
    ))

    msg = "🔔 *إدارة التنبيهات الذكية*\n━━━━━━━━━━━━━━━\n\n"
    if tracked:
        msg += f"📌 رموز تتبعك: `{'  '.join(tracked)}`\n"
    if current_alert:
        msg += f"💱 تنبيه الدولار مضبوط عند: `{current_alert}`\n"
    msg += "\nاختر نوع التنبيه:"

    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "alerts_show_track")
def cb_alerts_show_track(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    # إصلاح #7: حُذف متغير وهمي كان هنا — الكود التالي لا يحتاجه
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    user = users.get(str(uid), {})
    lang = user.get("lang", "English 🇬🇧")
    if not assets:
        bot.send_message(uid, t(lang, "track_empty"), parse_mode="Markdown")
        return
    last_prices = data.get("last_prices", {})
    msg = t(lang, "track_list_header")
    for sym in assets:
        price = fetch_asset_price(sym)
        if price:
            tracked_assets[str(uid)]["last_prices"][sym] = price
            save_tracked_assets()
        msg += f"• {format_asset_price(sym, price or last_prices.get(sym))}\n"
    msg += f"━━━━━━━━━━━━━━\n🤖 @{BOT_USERNAME}"
    bot.send_message(uid, msg, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "alerts_track")
def cb_alerts_track(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    data = tracked_assets.get(str(uid), {})
    assets = data.get("assets", [])
    if not assets:
        bot.send_message(uid, "❌ قائمة التتبع فارغة. أضف رموزاً بـ /addtrack")
        return
    markup = types.InlineKeyboardMarkup(row_width=3)
    buttons = [types.InlineKeyboardButton(sym, callback_data=f"alert_asset_{sym}") for sym in assets]
    markup.add(*buttons)
    bot.send_message(uid, "📌 اختر الرمز الذي تريد متابعة سعره:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("alert_asset_"))
def cb_alert_asset(call):
    uid = call.from_user.id
    symbol = call.data.replace("alert_asset_", "")
    bot.answer_callback_query(call.id)
    price = fetch_asset_price(symbol)
    if price:
        markup = types.InlineKeyboardMarkup(row_width=2)
        pct_1_up = price * 1.01
        pct_1_dn = price * 0.99
        pct_5_up = price * 1.05
        pct_5_dn = price * 0.95
        markup.add(
            types.InlineKeyboardButton(f"🔼 +1% (${pct_1_up:,.4f})", callback_data=f"alert_set_{symbol}_{pct_1_up:.6f}"),
            types.InlineKeyboardButton(f"🔽 -1% (${pct_1_dn:,.4f})", callback_data=f"alert_set_{symbol}_{pct_1_dn:.6f}"),
            types.InlineKeyboardButton(f"🔼 +5% (${pct_5_up:,.4f})", callback_data=f"alert_set_{symbol}_{pct_5_up:.6f}"),
            types.InlineKeyboardButton(f"🔽 -5% (${pct_5_dn:,.4f})", callback_data=f"alert_set_{symbol}_{pct_5_dn:.6f}"),
        )
        bot.send_message(uid,
            f"💰 *{symbol}* — السعر الحالي: `${price:,.4f}`\n\nاختر مستوى التنبيه:",
            parse_mode="Markdown", reply_markup=markup
        )
    else:
        bot.send_message(uid, f"⚠️ لم أتمكن من جلب سعر {symbol} الآن.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("alert_set_"))
def cb_alert_set(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id, "✅ تم ضبط التنبيه!")
    parts = call.data.split("_")
    symbol = parts[2]
    target = float(parts[3])
    if str(uid) not in users:
        return
    alerts_list = users[str(uid)].setdefault("price_alerts", [])
    alerts_list.append({"symbol": symbol, "target": target, "notified": False})
    _db_save_user(uid, users[str(uid)])
    bot.send_message(uid,
        f"✅ سيتم تنبيهك عندما يصل *{symbol}* إلى `${target:,.4f}`\n\n"
        f"💡 استخدم /alerts لإدارة التنبيهات.",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["settings"])
def cmd_settings_private(m):
    if m.chat.type != "private":
        return
    uid = m.from_user.id
    user = users.get(str(uid))
    if not user:
        bot.send_message(uid, "⚠️ أرسل /start أولاً.")
        return
    lang = user.get("lang", "English 🇬🇧")
    markup = types.InlineKeyboardMarkup(row_width=2)
    alert_lv  = user.get("alert_level", "all")
    alert_labels = {"all": "🔔 كل الأخبار", "important": "⚡ المهمة فقط", "breaking": "🚨 العاجلة فقط"}
    digest_on = user.get("digest_mode", False)
    custom_hours = user.get("custom_schedule", [])
    sched_txt = ", ".join(f"{h}:00" for h in sorted(custom_hours)) if custom_hours else "طوال اليوم ✅"
    markup.add(
        types.InlineKeyboardButton("🌍 تغيير اللغة",    callback_data="settings_lang"),
        types.InlineKeyboardButton("🌆 تغيير المدينة",  callback_data="settings_city"),
        types.InlineKeyboardButton("🔔 الإشعارات",       callback_data="settings_notif"),
        types.InlineKeyboardButton("📌 الاهتمامات",      callback_data="prem_interests"),
    )
    markup.add(
        types.InlineKeyboardButton(
            f"📡 التنبيه: {alert_labels.get(alert_lv, alert_lv)}",
            callback_data="settings_alert_level"
        ),
        types.InlineKeyboardButton(
            f"{'📰' if digest_on else '📄'} الدايجست: {'رسالة واحدة ✅' if digest_on else 'فردية'}",
            callback_data="settings_digest_toggle"
        ),
    )
    markup.add(
        types.InlineKeyboardButton(
            f"🕐 جدول الاستلام: {sched_txt}",
            callback_data="settings_schedule"
        ),
        types.InlineKeyboardButton("📊 إحصائياتي", callback_data="settings_mystats"),
    )
    notif_status = "✅ مفعّلة" if user.get("notifications", True) else "❌ موقوفة"
    city = user.get("province", "—")
    msg = (
        f"⚙️ *إعداداتك الحالية*\n━━━━━━━━━━━━━━━\n"
        f"🌍 اللغة: `{lang}`\n"
        f"🌆 المدينة: `{city}`\n"
        f"🔔 الإشعارات: {notif_status}\n"
        f"📰 الأخبار: *24/7 بلا توقف* 🟢\n"
        f"📡 مستوى التنبيه: {alert_labels.get(alert_lv, alert_lv)}\n"
        f"{'📰' if digest_on else '📄'} الدايجست: {'✅ رسالة واحدة' if digest_on else 'رسائل فردية'}\n"
        f"🕐 جدول الاستلام: {sched_txt}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"اختر ما تريد تعديله:"
    )
    bot.send_message(uid, msg, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "settings_lang")
def cb_settings_lang(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for lang_name in languages.values():
        markup.add(lang_name)
    bot.send_message(uid, "🌍 اختر لغتك:", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data == "settings_city")
def cb_settings_city(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    bot.send_message(uid, "🌆 أرسل اسم مدينتك بالإنجليزية (مثال: Baghdad, London, Tehran):")
    bot.register_next_step_handler(call.message, lambda m: _save_city_step(m, uid))


def _save_city_step(message, uid):
    city = message.text.strip()
    if str(uid) in users:
        users[str(uid)]["province"] = city
        _db_save_user(uid, users[str(uid)])
        bot.send_message(uid, f"✅ تم تحديث مدينتك إلى: *{city}*\n\nاستخدم /weather لعرض الطقس.", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda c: c.data == "settings_notif")
def cb_settings_notif(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    if str(uid) not in users:
        return
    current = users[str(uid)].get("notifications", True)
    users[str(uid)]["notifications"] = not current
    _db_save_user(uid, users[str(uid)])
    status = "✅ مفعّلة" if not current else "❌ موقوفة"
    bot.send_message(uid, f"🔔 الإشعارات الآن: {status}")


# ======== جدول استلام مخصص ========
@bot.callback_query_handler(func=lambda c: c.data == "settings_schedule")
def cb_settings_schedule(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    current = users.get(str(uid), {}).get("custom_schedule", [])
    cur_txt = ", ".join(f"{h}:00" for h in sorted(current)) if current else "طوال اليوم (افتراضي)"
    msg = bot.send_message(uid,
        f"🕐 *جدول استلام الأخبار*\n\n"
        f"الجدول الحالي: `{cur_txt}`\n\n"
        "أرسل الساعات التي تريد استلام الأخبار فيها مفصولة بمسافات:\n"
        "`7 12 18 21` — ستصلك الأخبار الساعة 7ص، 12م، 6م، 9م\n\n"
        "أرسل `0` لإلغاء الجدول والعودة للاستلام الدائم 24/7.",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, _save_schedule_step)


def _save_schedule_step(message):
    uid = message.from_user.id
    txt = message.text.strip()
    if txt == "0":
        users[str(uid)]["custom_schedule"] = []
        _db_save_user(uid, users[str(uid)])
        bot.send_message(uid, "✅ *تم إلغاء الجدول* — ستصلك الأخبار 24/7 باستمرار.", parse_mode="Markdown")
        return
    try:
        hours = [int(h) for h in txt.split() if 0 <= int(h) <= 23]
        if not hours:
            raise ValueError
        hours = sorted(set(hours))
        users[str(uid)]["custom_schedule"] = hours
        _db_save_user(uid, users[str(uid)])
        sched_txt = ", ".join(f"{h}:00" for h in hours)
        bot.send_message(uid,
            f"✅ *تم حفظ الجدول!*\n\nستصلك الأخبار الساعة: `{sched_txt}`",
            parse_mode="Markdown"
        )
    except Exception:
        bot.send_message(uid, "❌ تنسيق خاطئ. مثال: `7 12 18 21`\nأو أرسل `0` للإلغاء.", parse_mode="Markdown")


# ======== إحصائياتي الشخصية ========
@bot.callback_query_handler(func=lambda c: c.data == "settings_mystats")
def cb_settings_mystats(call):
    bot.answer_callback_query(call.id)
    _show_mystats(call.from_user.id)


@bot.message_handler(commands=["mystats"])
def cmd_mystats(m):
    _show_mystats(m.from_user.id)


@bot.message_handler(commands=["weekly"])
def cmd_weekly(m):
    """يعرض الملخص الأسبوعي فوراً للمستخدم"""
    uid = m.from_user.id
    if uid in banned: return
    if bot_paused: return
    lang = users.get(str(uid), {}).get("lang", "العربية 🇮🇶")
    week_data = _weekly_top_news.get(lang, {})
    if not week_data:
        bot.send_message(uid,
            "📆 *الملخص الأسبوعي*\n\n"
            "لا توجد بيانات كافية بعد لهذا الأسبوع.\n"
            "يُرسل الملخص تلقائياً كل *جمعة الساعة 10:00 صباحاً*.",
            parse_mode="Markdown"
        )
        return
    top = sorted(week_data.values(), key=lambda x: x["count"], reverse=True)[:7]
    week_end   = datetime.date.today().strftime("%Y/%m/%d")
    week_start = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y/%m/%d")
    lines = [f"{i}. [{item['title']}]({item['link']})" for i, item in enumerate(top, 1)]
    msg = (
        f"📆 *الملخص الأسبوعي*\n"
        f"🗓 {week_start} — {week_end}\n"
        f"━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(lines) +
        "\n\n━━━━━━━━━━━━━━\n"
        "_أبرز ما غطّته مصادر متعددة هذا الأسبوع_"
    )
    bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)


def _show_mystats(uid):
    user = users.get(str(uid), {})
    if not user:
        bot.send_message(uid, "⚠️ أرسل /start أولاً.")
        return
    lang          = user.get("lang", "—")
    city          = user.get("province", "—")
    joined        = user.get("joined", "—")
    total_sent    = user.get("total_news_received", 0)
    rated_pos     = user.get("rated_positive", 0)
    rated_neg     = user.get("rated_negative", 0)
    total_rated   = rated_pos + rated_neg
    fav_topics    = user.get("interests", [])
    searches      = user.get("total_searches", 0)
    streak_days   = user.get("reading_streak", 0)
    last_active   = user.get("last_active", "—")
    custom_sched  = user.get("custom_schedule", [])
    sched_txt     = ", ".join(f"{h}:00" for h in sorted(custom_sched)) if custom_sched else "24/7 🟢"
    digest_on     = user.get("digest_mode", False)
    followed      = user.get("followed_stories", [])
    # حساب نسبة الإيجابية
    if total_rated > 0:
        pos_pct = round(rated_pos / total_rated * 100)
        rating_txt = f"{rated_pos}👍 {rated_neg}👎 ({pos_pct}% إيجابية)"
    else:
        rating_txt = "لم تقيّم بعد"
    topics_txt = ", ".join(fav_topics[:5]) if fav_topics else "لم تُحدَّد"
    msg = (
        f"📊 *إحصائياتك الشخصية*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🌍 اللغة: `{lang}`\n"
        f"🌆 المدينة: `{city}`\n"
        f"📅 تاريخ الانضمام: `{joined}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📰 أخبار استقبلتها: *{total_sent:,}*\n"
        f"⭐ التقييمات: {rating_txt}\n"
        f"🔍 عمليات البحث: *{searches}*\n"
        f"🔥 أيام المتابعة: *{streak_days}* يوم\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 اهتماماتك: {topics_txt}\n"
        f"🕐 جدول الاستلام: {sched_txt}\n"
        f"{'📰' if digest_on else '📄'} الدايجست: {'✅' if digest_on else '❌'}\n"
        f"🔔 قصص تتابعها: *{len(followed)}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕒 آخر نشاط: `{last_active}`"
    )
    bot.send_message(uid, msg, parse_mode="Markdown")


# ======== إعدادات مستوى التنبيه ========
@bot.callback_query_handler(func=lambda c: c.data == "settings_alert_level")
def cb_alert_level_menu(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    current = users.get(str(uid), {}).get("alert_level", "all")
    markup = types.InlineKeyboardMarkup(row_width=1)
    options = [
        ("🔔 كل الأخبار (افتراضي)",        "nlevel_all"),
        ("⚡ المهمة والعاجلة فقط",           "nlevel_important"),
        ("🚨 العاجلة فقط (Breaking News)",   "nlevel_breaking"),
    ]
    for label, cb in options:
        check = "✅ " if cb.replace("nlevel_", "") == current else ""
        markup.add(types.InlineKeyboardButton(f"{check}{label}", callback_data=cb))
    bot.send_message(uid, "📡 *اختر مستوى الأخبار التي تريد استقبالها:*", parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda c: c.data.startswith("nlevel_"))
def cb_news_level_set(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    level = call.data.replace("nlevel_", "")
    if level not in ("all", "important", "breaking"):
        return
    users[str(uid)]["alert_level"] = level
    _db_save_user(uid, users[str(uid)])
    labels = {"all": "🔔 كل الأخبار", "important": "⚡ المهمة والعاجلة", "breaking": "🚨 العاجلة فقط"}
    bot.send_message(uid, f"✅ مستوى التنبيه: *{labels[level]}*", parse_mode="Markdown")


# ======== إعداد وضع الدايجست ========
@bot.callback_query_handler(func=lambda c: c.data == "settings_digest_toggle")
def cb_digest_toggle(call):
    bot.answer_callback_query(call.id)
    uid = call.from_user.id
    if str(uid) not in users:
        return
    current = users[str(uid)].get("digest_mode", False)
    users[str(uid)]["digest_mode"] = not current
    _db_save_user(uid, users[str(uid)])
    state = "✅ مفعّل — ستصلك الأخبار في رسالة واحدة منظّمة" if not current else "❌ معطّل — ستصلك الأخبار فرادى"
    bot.send_message(uid,
        f"📰 *وضع الدايجست الآن: {state}*\n\n"
        "_يمكنك التبديل في أي وقت من /settings_",
        parse_mode="Markdown"
    )


# ======== تسجيل الأوامر مع تيليغرام ========
try:
    from telebot.types import BotCommand
    bot.set_my_commands([
        BotCommand("start",       "رسالة الترحيب"),
        BotCommand("restart",     "إعادة ضبط إعداداتك مع الحفاظ على بياناتك"),
        BotCommand("news",        "آخر الأخبار حسب لغتك"),
        BotCommand("sports",      "أخبار ومباريات رياضية مباشرة"),
        BotCommand("trending",    "أبرز الأخبار الرائجة"),
        BotCommand("summary",     "ملخص يومي لأبرز 3 أحداث"),
        BotCommand("weather",     "طقس المدن التي تتابعها"),
        BotCommand("markets",     "أسعار العملات والأسهم والسلع"),
        BotCommand("chart",       "رسم بياني تفاعلي"),
        BotCommand("alerts",      "تنبيهات ذكية عند تغير ±1%"),
        BotCommand("mytrack",     "قائمة الرموز التي تتابعها"),
        BotCommand("addtrack",    "إضافة رمز جديد للتتبع"),
        BotCommand("removetrack", "حذف رمز من التتبع"),
        BotCommand("follow",      "متابعة قصة إخبارية بكلمة مفتاحية"),
        BotCommand("unfollow",    "إلغاء متابعة قصة"),
        BotCommand("weekly",      "ملخص أبرز أخبار الأسبوع"),
        BotCommand("mystats",     "إحصائياتي الشخصية مع البوت"),
        BotCommand("settings",    "تعديل تفضيلاتك"),
        BotCommand("help",        "دليل الاستخدام الكامل"),
        BotCommand("reset",       "إعادة إعداد البوت من البداية"),
    ])
    # أوامر خاصة بالأدمن (تظهر فقط للمشرفين)
    for _admin_uid in ADMINS:
        try:
            bot.set_my_commands([
                BotCommand("admin",         "🔧 لوحة تحكم الأدمن"),
                BotCommand("addchannel",    "📺 إضافة قناة تيليغرام مصدراً للأخبار"),
                BotCommand("removechannel", "🗑 حذف قناة من مصادر الأخبار"),
                BotCommand("discover",      "🔍 اكتشاف RSS تلقائياً من موقع"),
                BotCommand("listsources",   "📋 قائمة مصادر RSS المضافة يدوياً"),
                BotCommand("listchannels", "📺 قائمة قنوات التيليغرام المضافة"),
                BotCommand("news",          "آخر الأخبار"),
                BotCommand("sports",        "الأخبار الرياضية"),
                BotCommand("trending",      "الأخبار الرائجة"),
                BotCommand("summary",       "الملخص اليومي"),
                BotCommand("weather",       "الطقس"),
                BotCommand("markets",       "الأسواق المالية"),
                BotCommand("settings",      "الإعدادات"),
                BotCommand("help",          "دليل الاستخدام"),
            ], scope=types.BotCommandScopeChat(chat_id=_admin_uid))
        except Exception:
            pass
except Exception as _e:
    print(f"[set_my_commands] {_e}")

# ======== Watchdog — يراقب الـ scheduler ويعيد تشغيله لو مات ========
def _scheduler_watchdog():
    while True:
        time.sleep(60)
        try:
            if not scheduler.running:
                scheduler.start()
                try:
                    bot.send_message(ADMIN_ID, "⚠️ الـ scheduler توقف وأُعيد تشغيله تلقائياً!")
                except Exception:
                    pass
        except Exception:
            pass

_watchdog_thread = threading.Thread(target=_scheduler_watchdog, daemon=True)
_watchdog_thread.start()

# ======== تشغيل البوت — يعيد التشغيل تلقائياً عند أي انهيار ========
print("🔄 حذف أي webhook قديم قبل البدء...")
try:
    bot.delete_webhook(drop_pending_updates=True)
    print("✅ تم حذف الـ webhook")
except Exception as _wh_err:
    print(f"⚠️ خطأ في حذف webhook: {_wh_err}")

_retry_count    = 0
_last_poll_ping = time.time()


def _polling_watchdog():
    """
    يراقب حالة البوت الفعلية عبر ping get_me() كل دقيقة.
    إذا فشل 3 مرات متتالية → يُرسل تنبيه send_alert للأدمن.
    """
    fail_count = 0
    _last_alert_time = 0
    while True:
        time.sleep(60)
        try:
            bot.get_me()
            fail_count = 0
        except Exception as _e:
            fail_count += 1
            _logger.warning(f"⚠️ PollingWatchdog: فشل ping #{fail_count} — {_e}")
            if fail_count >= 3:
                now = time.time()
                if now - _last_alert_time > 600:
                    _last_alert_time = now
                    send_alert(
                        message   = f"البوت لا يستجيب — فشل {fail_count} ping متتالية",
                        exc       = _e,
                        func_name = "PollingWatchdog",
                        show_traceback = False
                    )


threading.Thread(target=_polling_watchdog, daemon=True, name="PollingWatchdog").start()

# ═══════════════════════════════════════════════════════════════════════════════
# SELF-HEALING MAIN LOOP — حلقة التشغيل الذاتي الإصلاح
# ═══════════════════════════════════════════════════════════════════════════════
_logger.info("🤖 IraqNow Bot — بدء الحلقة الرئيسية (Self-Healing)")

while True:
    try:
        _logger.info(f"🚀 بدء التشغيل (محاولة #{_retry_count + 1})")
        _retry_count = 0
        bot.infinity_polling(
            allowed_updates=["message", "callback_query", "my_chat_member"],
            timeout=60,
            long_polling_timeout=60,
            none_stop=True,
            restart_on_change=False
        )
        _last_poll_ping = time.time()

    except KeyboardInterrupt:
        _logger.info("🛑 إيقاف يدوي (KeyboardInterrupt) — إغلاق نظيف")
        break

    except Exception as _poll_err:
        _retry_count += 1
        # Exponential backoff: 5s, 10s, 20s... حد أقصى 60s
        _wait = min(5 * (2 ** (_retry_count - 1)), 60)
        _logger.error(f"💥 انهيار في polling (#{_retry_count}): {_poll_err} — إعادة التشغيل خلال {_wait}s")

        # تنبيه الأدمن (أول 5 مرات فقط، ثم كل 10 محاولات)
        if _retry_count <= 5 or _retry_count % 10 == 0:
            send_alert(
                message    = f"البوت انهار وأُعيد تشغيله تلقائياً (محاولة #{_retry_count})",
                exc        = _poll_err,
                func_name  = "infinity_polling",
                show_traceback = True
            )

        # حذف أي webhook قديم قبل إعادة المحاولة
        try:
            bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass

        time.sleep(_wait)
