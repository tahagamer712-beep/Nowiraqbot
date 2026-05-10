# -*- coding: utf-8 -*-
"""
ai.py — محرك الذكاء الاصطناعي متعدد المزودين (مستخرج فعلياً من bot_legacy.py)

يحتوي على:
- _ai_generate: دالة fallback عبر Gemini → Groq → OpenRouter → Mistral → Together → Cohere
- Fact Check, البحث المؤرشف, كاشف التناقضات, تقرير الأزمات, محقق الشائعات
- ذاكرة الأمة (هذا اليوم في التاريخ)
- InsightX: Why it Matters, What Might Happen Next, Impact Score, Bias, Sentiment,
Entity Extraction, Risk Level, Historical Context, Feature Gating, Quality Score,
Smart Semantic Deduplication, Rate Limiter
"""

import os, sys, json, time, threading, datetime, hashlib, re, random
from concurrent.futures import ThreadPoolExecutor

# نستورد lazy من bot_legacy لتجنب الاستيراد الدائري
# (هذه الوحدة تُحمَّل قبل إنشاء كائن bot في bot_legacy)
import bot_legacy as _legacy

# الأسماء التالية مُعرَّفة في bot_legacy قبل سطر استيراد ai (السطر 2191):
_logger              = _legacy._logger
_log_exc             = _legacy._log_exc
_GEMINI_KEYS         = _legacy._GEMINI_KEYS
_now_sa              = _legacy._now_sa
_sa_str              = _legacy._sa_str
_sanitize_input      = _legacy._sanitize_input

# bot يُنشَأ لاحقاً في bot_legacy — نستخدم proxy كسول
class _BotProxy:
    """وكيل كسول للوصول إلى bot بعد إنشائه في bot_legacy."""
    def __getattr__(self, name):
        return getattr(_legacy.bot, name)
bot = _BotProxy()

  # ════════════════════════════════════════════════════════════════════
  # FIX: استيراد كل الـ globals الناقصة من bot_legacy
  # (بدون هذه الكتلة كل دالة هنا تنفجر بـ NameError عند الاستدعاء)
  # ════════════════════════════════════════════════════════════════════
import re as _re

_AI_AVAILABLE        = getattr(_legacy, "_AI_AVAILABLE", False)
_AI_MODEL            = getattr(_legacy, "_AI_MODEL", None)
_AI_EXECUTOR         = getattr(_legacy, "_AI_EXECUTOR", None) or ThreadPoolExecutor(max_workers=4, thread_name_prefix="AIWorker")
_DS_GROQ_KEY         = getattr(_legacy, "_DS_GROQ_KEY", "")
_DS_OPENROUTER_KEY   = getattr(_legacy, "_DS_OPENROUTER_KEY", "")
_DS_TOGETHER_KEY     = getattr(_legacy, "_DS_TOGETHER_KEY", "")
_DS_MISTRAL_KEY      = getattr(_legacy, "_DS_MISTRAL_KEY", "")
_DS_COHERE_KEY       = getattr(_legacy, "_DS_COHERE_KEY", "")
_gemini_key_idx      = 0

_AI_PROVIDER_LOCK    = threading.Lock()
_AI_PROVIDER_ERRORS  = {}

_USER_DAILY_AI       = {}
_USER_DAILY_LOCK     = threading.Lock()
_DAILY_LIMITS        = {
      "ask":        (10, 30),
      "profile":    (5,  20),
      "influence":  (5,  15),
      "verify":     (8,  25),
      "timeline":   (8,  25),
      "deepsearch": (2,  8),
      "econ":       (10, -1),
      "weather":    (10, -1),
}

_AI_CACHE            = {}
_AI_CACHE_LOCK       = threading.Lock()
_AI_CACHE_TTL        = 3 * 3600

  # ── Lazy proxies للوصول إلى dict/dataset أحياء في bot_legacy ──────────
class _LazyDictProxy:
      """وكيل كسول لـ dict موجود في bot_legacy (يبقى مزامنناً مع التعديلات)."""
      def __init__(self, name): self._name = name
      def _src(self): return getattr(_legacy, self._name)
      def __getitem__(self, k): return self._src()[k]
      def __setitem__(self, k, v): self._src()[k] = v
      def __delitem__(self, k): del self._src()[k]
      def __contains__(self, k): return k in self._src()
      def __iter__(self): return iter(self._src())
      def __len__(self): return len(self._src())
      def get(self, k, d=None): return self._src().get(k, d)
      def keys(self): return self._src().keys()
      def values(self): return self._src().values()
      def items(self): return self._src().items()
      def setdefault(self, k, d=None): return self._src().setdefault(k, d)
      def update(self, *a, **kw): return self._src().update(*a, **kw)
      def pop(self, k, *a): return self._src().pop(k, *a)

users = _LazyDictProxy("users")

def is_admin(uid):
      return _legacy.is_admin(uid)

def is_premium(uid):
      return _legacy.is_premium(uid)

def _ui(*a, **kw):
      return _legacy._ui(*a, **kw)
  # ════════════════════════════════════════════════════════════════════
  # نهاية كتلة الإصلاح
  # ════════════════════════════════════════════════════════════════════

  

# ════════════════════════════════════════════════════════════════════
# الكود المُستخرَج فعلياً من bot_legacy.py (الأسطر 2191–3557 الأصلية)
# ════════════════════════════════════════════════════════════════════

def _export_all_to(target_globals):
    """ينسخ كل الأسماء (حتى التي تبدأ بـ _) إلى namespace المستدعي."""
    for _k, _v in list(globals().items()):
        if _k.startswith('__'):
            continue
        target_globals[_k] = _v


# =============================================================================
# Multi-Provider AI Engine — يجرب كل provider بالترتيب عند الفشل أو نفاد الحصة
# الترتيب: Gemini → Groq → OpenRouter → Mistral → Together → Cohere
# =============================================================================
_AI_PROVIDER_LOCK = threading.Lock()
_AI_PROVIDER_ERRORS: dict = {}   # provider -> consecutive_failures

def _ai_generate(prompt: str, timeout: int = 10) -> str:
    """
    دالة مركزية لاستدعاء AI بنظام fallback تلقائي.
    تجرب كل provider بالترتيب — تُعيد النص أو "" عند الفشل الكلي.
    """
    # ── 1. Gemini (مع دوران بين المفاتيح) ───────────────────────────
    global _gemini_key_idx
    if _AI_AVAILABLE and _AI_MODEL:
        _result_holder = [""]
        def _call():
            try:
                r = _AI_MODEL.generate_content(prompt)
                if r and r.text:
                    _result_holder[0] = r.text.strip()
            except Exception as _e:
                err = str(_e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
                    # دوران بين مفاتيح Gemini المتعددة
                    if len(_GEMINI_KEYS) > 1:
                        with _AI_PROVIDER_LOCK:
                            _gemini_key_idx = (_gemini_key_idx + 1) % len(_GEMINI_KEYS)
                        _logger.info("🔄 Gemini key rotated → key #%d", _gemini_key_idx)
                raise
        try:
            _AI_EXECUTOR.submit(_call).result(timeout=timeout)
            if _result_holder[0]:
                return _result_holder[0]
        except Exception:
            pass

    # ── 2. Groq (llama-3.1-70b-versatile — مجاني) ────────────────────
    if _DS_GROQ_KEY:
        try:
            import requests as _r
            resp = _r.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {_DS_GROQ_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "llama-3.1-70b-versatile",
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 800, "temperature": 0.3},
                timeout=timeout
            )
            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
                if txt:
                    return txt
        except Exception as _ge:
            _log_exc(_ge, "Groq")

    # ── 3. OpenRouter (google/gemini-flash-1.5 مجاني) ─────────────────
    if _DS_OPENROUTER_KEY:
        try:
            import requests as _r
            resp = _r.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {_DS_OPENROUTER_KEY}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://t.me/Iraqnowbot"},
                json={"model": "google/gemini-flash-1.5",
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 800},
                timeout=timeout
            )
            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
                if txt:
                    return txt
        except Exception as _oe:
            _log_exc(_oe, "OpenRouter")

    # ── 4. Mistral (mistral-small-latest) ────────────────────────────
    if _DS_MISTRAL_KEY:
        try:
            import requests as _r
            resp = _r.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {_DS_MISTRAL_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "mistral-small-latest",
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 800},
                timeout=timeout
            )
            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
                if txt:
                    return txt
        except Exception as _me:
            _log_exc(_me, "Mistral")

    # ── 5. Together AI (meta-llama/Llama-3-70b-chat-hf) ──────────────
    if _DS_TOGETHER_KEY:
        try:
            import requests as _r
            resp = _r.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={"Authorization": f"Bearer {_DS_TOGETHER_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "meta-llama/Llama-3-70b-chat-hf",
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 800, "temperature": 0.3},
                timeout=timeout
            )
            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
                if txt:
                    return txt
        except Exception as _te:
            _log_exc(_te, "Together")

    # ── 6. Cohere (command-r) ─────────────────────────────────────────
    if _DS_COHERE_KEY:
        try:
            import requests as _r
            resp = _r.post(
                "https://api.cohere.com/v1/generate",
                headers={"Authorization": f"Bearer {_DS_COHERE_KEY}",
                         "Content-Type": "application/json"},
                json={"model": "command-r", "prompt": prompt,
                      "max_tokens": 800, "temperature": 0.3},
                timeout=timeout
            )
            if resp.status_code == 200:
                txt = resp.json().get("generations", [{}])[0].get("text", "").strip()
                if txt:
                    return txt
        except Exception as _ce:
            _log_exc(_ce, "Cohere")

    return ""   # كل الـ providers فشلت

def _ai_available_any() -> bool:
    """يُعيد True إذا أي provider متاح."""
    return bool(_AI_AVAILABLE or _DS_GROQ_KEY or _DS_OPENROUTER_KEY
                or _DS_MISTRAL_KEY or _DS_TOGETHER_KEY or _DS_COHERE_KEY)

# =============================================================================
# مساعد الأخطاء — يُحوّل استثناءات AI إلى رسائل عربية مفهومة للمستخدم
# =============================================================================
def _ai_friendly_error(e: Exception, feature: str = "", lang: str = "العربية 🇮🇶") -> str:
    """يُعيد رسالة خطأ بلغة المستخدم بدل عرض الخطأ التقني الخام."""
    err = str(e)
    if "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower():
        return _ui("ai_err_quota", lang)
    if "timeout" in err.lower() or "deadline" in err.lower() or "timed out" in err.lower():
        return _ui("ai_err_timeout", lang)
    if "network" in err.lower() or "connection" in err.lower() or "unreachable" in err.lower():
        return _ui("ai_err_network", lang)
    if "AI غير متاح" in err or not _AI_AVAILABLE:
        return _ui("ai_err_unavail", lang)
    return _ui("ai_err_generic", lang)

# حصة يومية للمستخدمين (لحماية quota Gemini)
_USER_DAILY_AI: dict = {}        # {uid_str: {date_str: {feature: count}}}
_USER_DAILY_LOCK = threading.Lock()
_DAILY_LIMITS: dict = {          # الحد الأقصى يومياً لكل ميزة (free / premium)
    "ask":        (10, 30),  # (مجاني, مميز)
    "profile":    (5,  20),
    "influence":  (5,  15),
    "verify":     (8,  25),
    "timeline":   (8,  25),
    "deepsearch": (2,  8),   # بحث عميق — ثقيل جداً على الـ quota
    "econ":       (10, -1),  # -1 = بلا حد
    "weather":    (10, -1),
}

def _check_daily_ai_limit(uid, feature: str) -> tuple[bool, int, int]:
    """
    يتحقق من الحصة اليومية للمستخدم.
    يُعيد (مسموح: bool, استُخدم: int, الحد: int)
    """
    if is_admin(uid):
        return True, 0, -1
    prem = is_premium(uid)
    limits = _DAILY_LIMITS.get(feature)
    if not limits:
        return True, 0, -1
    limit = limits[1] if prem else limits[0]
    if limit < 0:
        return True, 0, -1
    today = _now_sa().strftime("%Y-%m-%d")
    uid_s = str(uid)
    with _USER_DAILY_LOCK:
        user_data = _USER_DAILY_AI.setdefault(uid_s, {})
        # تنظيف بيانات أمس
        for old_date in list(user_data.keys()):
            if old_date != today:
                del user_data[old_date]
        today_data = user_data.setdefault(today, {})
        used = today_data.get(feature, 0)
        if used >= limit:
            return False, used, limit
        today_data[feature] = used + 1
    return True, used + 1, limit

_AI_CACHE = {}           # link -> (cleaned_text, timestamp)
_AI_CACHE_LOCK = threading.Lock()
_AI_CACHE_TTL  = 3 * 3600   # ساعات 3 — الأخبار تفقد أهميتها بعدها

def _ai_cache_get(key: str):
    """يُعيد القيمة من الكاش إذا لم تنتهِ صلاحيتها، وإلا None."""
    entry = _AI_CACHE.get(key)
    if entry is None:
        return None
    value, ts = entry
    if time.time() - ts > _AI_CACHE_TTL:
        return None      # منتهية الصلاحية — تجاهلها
    return value

def _ai_cache_set(key: str, value):
    """يُخزّن القيمة مع طابع زمني، وينظف الكاش إذا تضخّم."""
    with _AI_CACHE_LOCK:
        _AI_CACHE[key] = (value, time.time())
        if len(_AI_CACHE) > 1000:
            # احذف الإدخالات المنتهية أولاً، ثم الأقدم إذا لزم
            now = time.time()
            expired = [k for k, (_, t) in _AI_CACHE.items() if now - t > _AI_CACHE_TTL]
            for k in expired:
                _AI_CACHE.pop(k, None)
            if len(_AI_CACHE) > 800:
                oldest = sorted(_AI_CACHE.items(), key=lambda x: x[1][1])[:200]
                for k, _ in oldest:
                    _AI_CACHE.pop(k, None)

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
        _cached = _ai_cache_get(cache_key)
        if _cached is not None:
            return _cached

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
        result = _ai_generate(prompt, timeout=5) or _result_holder[0]
        # رفض النتيجة إذا أشارت AI بأنه محتوى ترويجي
        if result and result.strip().upper() == "SKIP":
            return None
        # لا نقبل نتيجة فارغة أو طويلة جداً
        if not result or len(result) > 600:
            result = clean_title
        with _AI_CACHE_LOCK:
            _ai_cache_set(cache_key, result)
        return result
    except Exception:
        return clean_title


_AI_SUMMARY_CACHE = {}   # cache_key -> (summary, timestamp)
_AI_SUMMARY_LOCK  = __import__('threading').Lock()
_AI_SUMMARY_TTL   = 3 * 3600   # نفس TTL كاش التنظيف

def _summary_cache_get(key: str):
    entry = _AI_SUMMARY_CACHE.get(key)
    if entry is None:
        return None
    value, ts = entry
    return value if time.time() - ts <= _AI_SUMMARY_TTL else None

def _summary_cache_set(key: str, value: str):
    with _AI_SUMMARY_LOCK:
        _AI_SUMMARY_CACHE[key] = (value, time.time())
        if len(_AI_SUMMARY_CACHE) > 500:
            now = time.time()
            expired = [k for k, (_, t) in _AI_SUMMARY_CACHE.items() if now - t > _AI_SUMMARY_TTL]
            for k in expired:
                _AI_SUMMARY_CACHE.pop(k, None)
            if len(_AI_SUMMARY_CACHE) > 400:
                oldest = sorted(_AI_SUMMARY_CACHE.items(), key=lambda x: x[1][1])[:100]
                for k, _ in oldest:
                    _AI_SUMMARY_CACHE.pop(k, None)

def _ai_generate_summary(text, title="", lang="العربية 🇮🇶"):
    """
    يُولّد ملخصاً صحفياً احترافياً من نص الخبر أو منشور القناة.
    يستخدم Gemini إذا متاح، وإلا يُعيد النص مباشرة.
    المخرج: 3-5 جمل بلغة المستخدم.
    """
    cache_key = (title or text[:60]) + lang
    with _AI_SUMMARY_LOCK:
        _cached_sum = _summary_cache_get(cache_key)
        if _cached_sum is not None:
            return _cached_sum

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
        "Français 🇫🇷": "Écris le résumé en français",
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
        result = _ai_generate(prompt, timeout=8) or clean[:800]
        if not result or len(result) < 20:
            result = clean[:800]
        with _AI_SUMMARY_LOCK:
            _summary_cache_set(cache_key, result)
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

    fallback = _smart_fallback_fact(title)

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
                _resp_ai = _ai_generate(prompt)
                if _resp_ai:
                    _holder[0] = _resp_ai.strip()
            except Exception as _exc:
                _log_exc(_exc)
        try:

            _AI_EXECUTOR.submit(_call).result(timeout=6)

        except Exception:

            pass
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
        _h_result = _ai_generate(prompt, timeout=12)
        return _h_result or "تعذر التحليل"
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
        _h_result = _ai_generate(prompt, timeout=7)
        return _h_result or ""
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
        _h_result = _ai_generate(prompt, timeout=15)
        return _h_result or ""
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
        _h_result = _ai_generate(prompt, timeout=10)
        raw = _h_result or ""
        import json as _j3
        raw_c = _re.sub(r'```json|```', '', raw).strip()
        return _j3.loads(raw_c)
    except Exception:
        return {"verdict": "⚠️", "confidence": 0, "explanation": "تعذر التحليل", "first_source": ""}


# ─── ذاكرة الأمة (هذا اليوم في التاريخ) ────────────────────────
def _ai_nation_memory(lang: str = "العربية 🇮🇶") -> str:
    """يُولّد ملخصاً: ماذا جرى في مثل هذا اليوم في تاريخ العراق"""
    if not _AI_AVAILABLE or not _AI_MODEL:
        return _ai_friendly_error(Exception("AI غير متاح"), "")
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
        _h_result = _ai_generate(prompt, timeout=12)
        return _h_result or "لا توجد بيانات لهذا اليوم"
    except Exception:
        return "تعذر الاسترداد"


# ─── لماذا يهمك هذا الخبر؟ (InsightX: Why it Matters) ──────────────────────
_WHY_MATTERS_CACHE: dict = {}
_WHY_MATTERS_LOCK = threading.Lock()

def _ai_why_it_matters(title: str, summary: str = "", lang: str = "العربية 🇮🇶") -> str:
    """
    يشرح لماذا يهمّ هذا الخبر المستخدم العادي:
    - التأثير المباشر على الحياة اليومية
    - الأطراف المتأثرة
    - الأهمية الاستراتيجية
    يُعيد نصاً بلغة المستخدم (3-4 جمل).
    """
    cache_key = title[:80] + lang
    with _WHY_MATTERS_LOCK:
        cached = _WHY_MATTERS_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 3600:
            return cached["text"]

    fallback = _smart_fallback_why(title)
    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    lang_map = {
        "العربية 🇮🇶": "العربية الفصحى", "English 🇬🇧": "English",
        "Русский 🇷🇺": "Russian", "فارسی 🇮🇷": "Persian",
        "Türkçe 🇹🇷": "Turkish", "Deutsch 🇩🇪": "German",
        "Español 🇲🇽": "Spanish", "Français 🇫🇷": "French",
    }
    write_lang = lang_map.get(lang, "Arabic")
    full = f"{title}\n{summary[:400]}" if summary else title
    prompt = (
        f"أنت محلل أخبار متخصص. الخبر التالي:\n\"{full[:600]}\"\n\n"
        f"اشرح بـ 3 جمل مختصرة باللغة {write_lang}:\n"
        "1. ما التأثير المباشر لهذا الخبر على المواطن العادي؟\n"
        "2. من هم أبرز المتأثرين به؟\n"
        "3. لماذا هو مهم الآن؟\n"
        "ابدأ مباشرة بدون مقدمة."
    )
    _h_result = _ai_generate(prompt, timeout=8)
    result = _h_result if _h_result and len(_h_result) > 20 else fallback
    with _WHY_MATTERS_LOCK:
        _WHY_MATTERS_CACHE[cache_key] = {"text": result, "ts": time.time()}
        if len(_WHY_MATTERS_CACHE) > 800:
            for k in list(_WHY_MATTERS_CACHE.keys())[:200]:
                del _WHY_MATTERS_CACHE[k]
    return result


# ─── ماذا قد يحدث بعدها؟ (InsightX: What Might Happen Next) ─────────────────
_WHAT_NEXT_CACHE: dict = {}
_WHAT_NEXT_LOCK = threading.Lock()

def _ai_what_next(title: str, summary: str = "", lang: str = "العربية 🇮🇶") -> str:
    """
    يتنبأ بما قد يحدث بعد هذا الخبر:
    - التطورات المتوقعة خلال 24-72 ساعة
    - ردود الفعل المحتملة
    - السيناريوهات الممكنة
    يُعيد 3-5 جمل بلغة المستخدم.
    """
    cache_key = title[:80] + lang
    with _WHAT_NEXT_LOCK:
        cached = _WHAT_NEXT_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 1800:
            return cached["text"]

    fallback = _smart_fallback_next(title)
    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    lang_map = {
        "العربية 🇮🇶": "العربية الفصحى", "English 🇬🇧": "English",
        "Русский 🇷🇺": "Russian", "فارسی 🇮🇷": "Persian",
        "Türkçe 🇹🇷": "Turkish", "Deutsch 🇩🇪": "German",
        "Español 🇲🇽": "Spanish", "Français 🇫🇷": "French",
    }
    write_lang = lang_map.get(lang, "Arabic")
    full = f"{title}\n{summary[:400]}" if summary else title
    prompt = (
        f"أنت محلل استراتيجي. بناءً على هذا الخبر:\n\"{full[:600]}\"\n\n"
        f"اكتب باللغة {write_lang} في 3-4 جمل:\n"
        "• ما الذي قد يحدث خلال الـ 24-72 ساعة القادمة؟\n"
        "• ما ردود الفعل المتوقعة من الأطراف المعنية؟\n"
        "• ما السيناريو الأرجح؟\n"
        "كن واقعياً وموضوعياً. ابدأ مباشرة بدون مقدمة."
    )
    _h_result = _ai_generate(prompt, timeout=8)
    result = _h_result if _h_result and len(_h_result) > 20 else fallback
    with _WHAT_NEXT_LOCK:
        _WHAT_NEXT_CACHE[cache_key] = {"text": result, "ts": time.time()}
        if len(_WHAT_NEXT_CACHE) > 800:
            for k in list(_WHAT_NEXT_CACHE.keys())[:200]:
                del _WHAT_NEXT_CACHE[k]
    return result


# ─── Impact Score 0-100 + Bias Detection (InsightX) ─────────────────────────
_IMPACT_CACHE: dict = {}
_IMPACT_LOCK = threading.Lock()

def _ai_impact_and_bias(title: str, summary: str = "") -> dict:
    """
    يُحسب:
    - impact_score: 0-100 (أهمية الخبر للمجتمع)
    - bias: none | slight | moderate | strong
    - bias_direction: left | right | pro_govt | anti_govt | neutral
    يُعيد dict مع fallback آمن.
    """
    cache_key = title[:80]
    with _IMPACT_LOCK:
        cached = _IMPACT_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 3600:
            return cached["data"]

    # حساب بسيط بدون AI كـ fallback
    score = min(100, _news_importance_score(title) * 35 + len(title.split()) * 2)
    fallback = {"impact_score": score, "bias": "unknown", "bias_direction": "neutral"}

    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    full = f"{title}\n{summary[:300]}" if summary else title
    prompt = (
        "حلّل الخبر التالي وأجب بـ JSON فقط:\n"
        '{"impact_score": رقم 0-100, "bias": "none"|"slight"|"moderate"|"strong", '
        '"bias_direction": "neutral"|"pro_govt"|"anti_govt"|"left"|"right"|"religious"|"nationalist"}\n\n'
        "معايير impact_score:\n"
        "90-100: كارثة أو حرب أو قرار تاريخي\n"
        "70-89: حدث مهم يؤثر على المجتمع\n"
        "50-69: خبر متوسط الأهمية\n"
        "30-49: خبر عادي محلي\n"
        "0-29: خبر هامشي\n\n"
        f"الخبر:\n{full[:500]}"
    )
    _h_result = _ai_generate(prompt, timeout=6)
    result = fallback
    if _h_result:
        try:
            import json as _j
            raw = _re.sub(r'```json|```', '', _h_result).strip()
            parsed = _j.loads(raw)
            result = {
                "impact_score":   max(0, min(100, int(parsed.get("impact_score", score)))),
                "bias":           parsed.get("bias", "unknown"),
                "bias_direction": parsed.get("bias_direction", "neutral"),
                "ts":             time.time(),
            }
        except Exception:
            result = fallback
    with _IMPACT_LOCK:
        _IMPACT_CACHE[cache_key] = {"data": result, "ts": time.time()}
        if len(_IMPACT_CACHE) > 600:
            for k in list(_IMPACT_CACHE.keys())[:150]:
                del _IMPACT_CACHE[k]
    return result


# ─── Click Tracking لتحسين التوصيات الشخصية (InsightX Personalization) ──────
_user_click_log: dict = {}   # uid -> [{"title": .., "ts": ..}, ...]
_click_log_lock = threading.Lock()
_CLICK_LOG_MAX = 50          # آخر 50 تفاعل لكل مستخدم

def _track_user_click(uid, title: str, action: str = "click"):
    """
    يُسجّل تفاعل المستخدم مع الخبر (ضغط زر، مشاركة، إلخ).
    يُستخدم لاحقاً لتحسين ترتيب الأخبار بناءً على اهتمامات كل مستخدم.
    """
    with _click_log_lock:
        log = _user_click_log.setdefault(str(uid), [])
        log.append({"title": title[:120], "action": action, "ts": time.time()})
        if len(log) > _CLICK_LOG_MAX:
            _user_click_log[str(uid)] = log[-_CLICK_LOG_MAX:]

def _get_user_interest_keywords(uid) -> list:
    """
    يستخرج الكلمات الأكثر تكراراً في نقرات المستخدم
    لاستخدامها في ترتيب الأخبار الشخصية.
    """
    with _click_log_lock:
        log = list(_user_click_log.get(str(uid), []))
    if not log:
        return []
    from collections import Counter
    word_counts = Counter()
    stop = {'و','في','من','على','إلى','أن','هذا','هذه','ذلك','the','a','an','of','in'}
    for entry in log:
        words = _re.sub(r'[^\w\s]', ' ', entry["title"].lower()).split()
        for w in words:
            if len(w) > 3 and w not in stop:
                word_counts[w] += 1
    return [w for w, _ in word_counts.most_common(15)]

def _rank_news_by_interests(items: list, uid) -> list:
    """
    يُرتّب قائمة الأخبار حسب اهتمامات المستخدم.
    الأخبار التي تحتوي كلمات من سجل النقرات تأتي أولاً.
    """
    keywords = _get_user_interest_keywords(uid)
    if not keywords:
        return items
    def _score(item):
        title = (item[1] if len(item) > 1 else "").lower()
        return sum(1 for kw in keywords if kw in title)
    urgent = [i for i in items if _news_importance_score(i[1] if len(i) > 1 else "") >= 2]
    normal = [i for i in items if _news_importance_score(i[1] if len(i) > 1 else "") < 2]
    normal_sorted = sorted(normal, key=_score, reverse=True)
    return urgent + normal_sorted


# ─── Sentiment Analysis (InsightX Layer 3) ───────────────────────────────────
_SENTIMENT_AI_CACHE: dict = {}
_SENTIMENT_AI_LOCK = threading.Lock()

def _ai_sentiment_analysis(title: str, summary: str = "") -> dict:
    """
    تحليل مشاعر الخبر عبر AI:
    positive / negative / neutral / alarming
    يُعيد: {sentiment, emoji, score: 0-100, label}
    """
    cache_key = title[:80]
    with _SENTIMENT_AI_LOCK:
        cached = _SENTIMENT_AI_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 3600:
            return cached["data"]

    words = set(title.lower().split())
    pos = len(words & _SENTIMENT_POSITIVE)
    neg = len(words & _SENTIMENT_NEGATIVE)
    alarming_words = {'عاجل','انفجار','مجزرة','اغتيال','كارثة','زلزال','قتلى','حرب','أزمة',
                      'attack','explosion','killed','war','crisis','blast','massacre'}
    is_alarming = bool(words & alarming_words)
    if is_alarming:
        fallback = {"sentiment": "alarming", "emoji": "🚨", "score": 85, "label": "مقلق"}
    elif neg > pos:
        fallback = {"sentiment": "negative", "emoji": "😟", "score": min(90, 40 + neg * 15), "label": "سلبي"}
    elif pos > neg:
        fallback = {"sentiment": "positive", "emoji": "😊", "score": min(90, 40 + pos * 15), "label": "إيجابي"}
    else:
        fallback = {"sentiment": "neutral", "emoji": "😐", "score": 50, "label": "محايد"}

    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    full = f"{title}\n{summary[:300]}" if summary else title
    prompt = (
        'حلّل مشاعر هذا الخبر وأجب بـ JSON فقط:\n'
        '{"sentiment":"positive"|"negative"|"neutral"|"alarming",'
        '"emoji":"😊"|"😟"|"😐"|"🚨",'
        '"score":رقم 0-100,"label":"كلمة واحدة بالعربية"}\n\n'
        f'الخبر: {full[:500]}'
    )
    _h_result = _ai_generate(prompt, timeout=6)
    result = fallback
    if _h_result:
        try:
            import json as _j
            raw = _re.sub(r'```json|```', '', _h_result).strip()
            parsed = _j.loads(raw)
            result = {
                "sentiment": parsed.get("sentiment", fallback["sentiment"]),
                "emoji":     parsed.get("emoji", fallback["emoji"]),
                "score":     max(0, min(100, int(parsed.get("score", 50)))),
                "label":     parsed.get("label", fallback["label"]),
            }
        except Exception:
            result = fallback
    with _SENTIMENT_AI_LOCK:
        _SENTIMENT_AI_CACHE[cache_key] = {"data": result, "ts": time.time()}
        if len(_SENTIMENT_AI_CACHE) > 800:
            for k in list(_SENTIMENT_AI_CACHE.keys())[:200]:
                del _SENTIMENT_AI_CACHE[k]
    return result


# ─── Entity Extraction (InsightX Layer 8) ────────────────────────────────────
_ENTITY_CACHE: dict = {}
_ENTITY_LOCK = threading.Lock()

def _ai_extract_entities(title: str, summary: str = "") -> dict:
    """
    يستخرج الكيانات الرئيسية:
    people / places / organizations
    يُعيد dict بقوائم الأسماء.
    """
    cache_key = title[:80]
    with _ENTITY_LOCK:
        cached = _ENTITY_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 3600:
            return cached["data"]

    fallback = {"people": [], "places": [], "organizations": []}
    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    full = f"{title}\n{summary[:400]}" if summary else title
    prompt = (
        'استخرج الكيانات من الخبر التالي وأجب بـ JSON فقط:\n'
        '{"people":["الأشخاص والمسؤولون"],'
        '"places":["الأماكن والدول والمناطق"],'
        '"organizations":["الحكومات والأحزاب والمنظمات"]}\n'
        'اترك القائمة [] إذا لم توجد عناصر. أبقِ الأسماء بلغتها الأصلية.\n\n'
        f'الخبر: {full[:600]}'
    )
    _h_result = _ai_generate(prompt, timeout=7)
    result = fallback
    if _h_result:
        try:
            import json as _j
            raw = _re.sub(r'```json|```', '', _h_result).strip()
            parsed = _j.loads(raw)
            result = {
                "people":        parsed.get("people", [])[:6],
                "places":        parsed.get("places", [])[:6],
                "organizations": parsed.get("organizations", [])[:5],
            }
        except Exception:
            result = fallback
    with _ENTITY_LOCK:
        _ENTITY_CACHE[cache_key] = {"data": result, "ts": time.time()}
        if len(_ENTITY_CACHE) > 600:
            for k in list(_ENTITY_CACHE.keys())[:150]:
                del _ENTITY_CACHE[k]
    return result


# ─── Risk/Crisis Level per-news (InsightX Layer 7) ───────────────────────────
_RISK_CACHE: dict = {}
_RISK_LOCK = threading.Lock()

def _ai_risk_level(title: str, summary: str = "") -> dict:
    """
    يُقيّم مستوى خطورة كل خبر:
    low / medium / high / critical
    يُعيد {level, color, reason}.
    """
    cache_key = title[:80]
    with _RISK_LOCK:
        cached = _RISK_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 1800:
            return cached["data"]

    score = _news_importance_score(title)
    if score >= 2:
        fallback = {"level": "high",   "color": "🟠", "reason": "خبر عاجل ذو أهمية عالية"}
    elif score == 1:
        fallback = {"level": "medium", "color": "🟡", "reason": "خبر مهم"}
    else:
        fallback = {"level": "low",    "color": "🟢", "reason": "خبر عادي"}

    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    full = f"{title}\n{summary[:300]}" if summary else title
    prompt = (
        'قيّم مستوى خطورة هذا الخبر وأجب بـ JSON فقط:\n'
        '{"level":"low"|"medium"|"high"|"critical",'
        '"color":"🟢"|"🟡"|"🟠"|"🔴",'
        '"reason":"سبب مختصر جملة واحدة بالعربية"}\n'
        'critical=حرب/كارثة/مجزرة | high=عمليات عسكرية/أزمة | medium=قرارات/احتجاجات | low=عادي\n\n'
        f'الخبر: {full[:500]}'
    )
    _h_result = _ai_generate(prompt, timeout=6)
    result = fallback
    if _h_result:
        try:
            import json as _j
            raw = _re.sub(r'```json|```', '', _h_result).strip()
            parsed = _j.loads(raw)
            result = {
                "level":  parsed.get("level",  fallback["level"]),
                "color":  parsed.get("color",  fallback["color"]),
                "reason": parsed.get("reason", fallback["reason"]),
            }
        except Exception:
            result = fallback
    with _RISK_LOCK:
        _RISK_CACHE[cache_key] = {"data": result, "ts": time.time()}
        if len(_RISK_CACHE) > 600:
            for k in list(_RISK_CACHE.keys())[:150]:
                del _RISK_CACHE[k]
    return result


# ─── Historical Context Builder (InsightX Layer 9) ───────────────────────────
_CONTEXT_CACHE: dict = {}
_CONTEXT_LOCK = threading.Lock()

def _ai_build_context(title: str, summary: str = "", lang: str = "العربية 🇮🇶") -> str:
    """
    يبني السياق التاريخي للخبر:
    - الجذور والأسباب العميقة
    - الصلة بأحداث سابقة
    - الخلفية الضرورية للفهم الكامل
    يُعيد نصاً بلغة المستخدم (3-5 جمل).
    """
    cache_key = title[:80] + lang
    with _CONTEXT_LOCK:
        cached = _CONTEXT_CACHE.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < 7200:
            return cached["text"]

    fallback = _smart_fallback_context(title)
    if not _AI_AVAILABLE or not _AI_MODEL:
        return fallback

    lang_map = {
        "العربية 🇮🇶": "العربية الفصحى", "English 🇬🇧": "English",
        "Русский 🇷🇺": "Russian", "فارسی 🇮🇷": "Persian",
        "Türkçe 🇹🇷": "Turkish", "Deutsch 🇩🇪": "German",
        "Español 🇲🇽": "Spanish", "Français 🇫🇷": "French",
    }
    write_lang = lang_map.get(lang, "Arabic")
    full = f"{title}\n{summary[:400]}" if summary else title
    prompt = (
        f"أنت مؤرخ ومحلل سياسي. الخبر التالي:\n\"{full[:600]}\"\n\n"
        f"اكتب باللغة {write_lang} في 3-5 جمل مختصرة:\n"
        "• ما الجذور التاريخية أو الأسباب العميقة لهذا الحدث؟\n"
        "• كيف يرتبط بأحداث أو صراعات سابقة؟\n"
        "• ما الخلفية الضرورية لفهم الصورة الكاملة؟\n"
        "ابدأ مباشرة بدون مقدمة."
    )
    _h_result = _ai_generate(prompt, timeout=9)
    result = _h_result if _h_result and len(_h_result) > 30 else fallback
    with _CONTEXT_LOCK:
        _CONTEXT_CACHE[cache_key] = {"text": result, "ts": time.time()}
        if len(_CONTEXT_CACHE) > 600:
            for k in list(_CONTEXT_CACHE.keys())[:150]:
                del _CONTEXT_CACHE[k]
    return result


# ─── Feature Gating + Usage Limits (InsightX Monetization Engine) ────────────
# Admin يُفعّل الـ gating عبر /featuregate  — افتراضياً: كل شيء مجاني
_FEATURE_GATING_ACTIVE: bool = False   # True = تطبيق الحدود، False = مجاني للجميع

# ─────────────────────────────────────────────────────────────────
#  Feature Registry الشاملة — كل الميزات بتصنيفاتها ومستوياتها
#  mode:
#    "free"         → متاح للجميع بلا حدود
#    "limited"      → متاح للجميع لكن بحد يومي (free_daily)
#    "premium_only" → للمستخدم المميز فقط (العادي يُمنع تماماً)
#  free_daily  : -1 = غير محدود
#  prem_daily  : -1 = غير محدود
# ─────────────────────────────────────────────────────────────────
_FEATURE_REGISTRY: dict = {
    # ─── أزرار AI على الأخبار ───
    "why_matters":   {"label": "💡 لماذا يهمك؟",        "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "what_next":     {"label": "🔮 ماذا بعد؟",           "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "intel_report":  {"label": "🧠 تقرير ذكي شامل",     "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "context":       {"label": "📚 السياق التاريخي",     "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "factcheck":     {"label": "🔍 التحقق من الخبر",     "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "summary":       {"label": "📄 ملخص الخبر",          "mode": "free",    "free_daily": -1, "prem_daily": -1},
    # ─── أوامر المستخدم ───
    "compare":       {"label": "🔄 مقارنة المصادر",      "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "storyline":     {"label": "🗓 خط الأحداث",          "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "audiobriefing": {"label": "🎙 الموجز الإخباري",     "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "catchup":       {"label": "⏩ ماذا فاتني؟",         "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "deepdive":      {"label": "🔬 تحليل عميق",          "mode": "free",    "free_daily": -1, "prem_daily": -1},
    # ─── ميزات متقدمة ───
    "entity_track":  {"label": "📡 تتبع شخص/شركة",      "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "custom_rss":    {"label": "📰 مصادر مخصصة",         "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "bookmark":      {"label": "🔖 حفظ الأخبار",         "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "audio_podcast": {"label": "🎧 بودكاست يومي",        "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "cross_lang":    {"label": "🌍 مقارنة متعددة اللغات","mode": "free",    "free_daily": -1, "prem_daily": -1},
    "weekly_report": {"label": "📆 تقرير أسبوعي",        "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "keywords_alert":{"label": "🔑 تنبيه كلمات مفتاحية","mode": "free",    "free_daily": -1, "prem_daily": -1},
    "sleep_mode":    {"label": "😴 وضع الصمت الذكي",     "mode": "free",    "free_daily": -1, "prem_daily": -1},
    "news_quiz":     {"label": "🧩 اختبار الأخبار",      "mode": "free",    "free_daily": -1, "prem_daily": -1},
}

# الأوضاع الممكنة وأوصافها
_MODE_LABELS = {
    "free":         "🟢 مجاني",
    "limited":      "🔢 محدود",
    "premium_only": "⭐ مميز فقط",
    "disabled":     "🚫 ملغية",
}
_MODE_CYCLE = ["free", "limited", "premium_only", "disabled"]   # دوران عند الضغط

# الحدود القديمة — تُقرأ دائماً من _FEATURE_REGISTRY
_FEATURE_DAILY_LIMITS: dict = {
    k: {"free": v["free_daily"], "premium": v["prem_daily"]}
    for k, v in _FEATURE_REGISTRY.items()
}

_user_daily_usage: dict = {}   # {uid_str: {date: {feature: count}}}
_daily_usage_lock = threading.Lock()


def _save_feature_registry():
    """يحفظ الـ Registry في stats حتى تبقى بعد إعادة تشغيل البوت."""
    try:
        stats["feature_registry"] = {
            k: {"mode": v["mode"], "free_daily": v["free_daily"], "prem_daily": v["prem_daily"]}
            for k, v in _FEATURE_REGISTRY.items()
        }
        save_stats()
    except Exception as _exc:
        _log_exc(_exc)


def _load_feature_registry():
    """يُحمّل الـ Registry المحفوظ عند بدء التشغيل."""
    saved = stats.get("feature_registry", {})
    for k, v in saved.items():
        if k in _FEATURE_REGISTRY:
            _FEATURE_REGISTRY[k]["mode"]       = v.get("mode", _FEATURE_REGISTRY[k]["mode"])
            _FEATURE_REGISTRY[k]["free_daily"] = v.get("free_daily", _FEATURE_REGISTRY[k]["free_daily"])
            _FEATURE_REGISTRY[k]["prem_daily"] = v.get("prem_daily", _FEATURE_REGISTRY[k]["prem_daily"])


# تحميل الإعدادات المحفوظة فور التعريف
try:
    _load_feature_registry()
    # استعادة حالة التحكم العام
    if "feature_gating_active" in stats:
        _FEATURE_GATING_ACTIVE = bool(stats["feature_gating_active"])
except Exception as _exc:
    _log_exc(_exc)

def _check_and_consume_feature(uid, feature: str) -> bool:
    """
    البوابة الموحّدة للتحقق من صلاحية الميزة واستهلاك الرصيد اليومي.

    المنطق:
      1. mode="disabled" → False للجميع دائماً (حتى الأدمن يُمنع في _check_and_consume، لكن _feat_ok يُخفي الزر فقط)
      2. أدمن → True دائماً (ماعدا disabled)
      3. _FEATURE_GATING_ACTIVE=False → True للجميع (ماعدا disabled)
      4. mode="free"         → True دائماً
      5. mode="premium_only" → True فقط للمميز
      6. mode="limited"      → تطبيق الحد اليومي (free_daily / prem_daily)
    """
    reg  = _FEATURE_REGISTRY.get(feature, {"mode": "free", "free_daily": -1, "prem_daily": -1})
    mode = reg.get("mode", "free")

    # mode = disabled → ملغية للجميع دائماً (أعلى أولوية)
    if mode == "disabled":
        return False

    if is_admin(uid):
        _log_feature_stat(feature)
        return True

    if not _FEATURE_GATING_ACTIVE:
        _log_feature_stat(feature)
        return True

    prem = is_premium(uid)

    # mode = free → مفتوح للجميع
    if mode == "free":
        _log_feature_stat(feature)
        return True

    # mode = premium_only → المميز فقط
    if mode == "premium_only":
        if prem:
            _log_feature_stat(feature)
            return True
        return False          # مُمنوع → _get_limit_msg ستظهر رسالة

    # mode = limited → الجميع لكن بحد يومي
    daily_limit = reg["prem_daily"] if prem else reg["free_daily"]
    if daily_limit == -1:
        _log_feature_stat(feature)
        return True

    today   = datetime.datetime.now().strftime("%Y-%m-%d")
    uid_str = str(uid)
    with _daily_usage_lock:
        day_data = _user_daily_usage.setdefault(uid_str, {}).setdefault(today, {})
        used = day_data.get(feature, 0)
        if used >= daily_limit:
            return False
        day_data[feature] = used + 1
        for old_d in [d for d in list(_user_daily_usage[uid_str].keys()) if d != today]:
            del _user_daily_usage[uid_str][old_d]
    _log_feature_stat(feature)
    return True


def _get_limit_msg(lang: str, feature: str = "") -> str:
    """رسالة مناسبة حسب سبب المنع (حد يومي أم مميز فقط أم ملغية)."""
    reg  = _FEATURE_REGISTRY.get(feature, {})
    mode = reg.get("mode", "limited")
    if mode == "disabled":
        return {
            "العربية 🇮🇶": "🚫 هذه الميزة معطّلة حالياً.",
            "English 🇬🇧":  "🚫 This feature is currently disabled.",
            "Русский 🇷🇺":  "🚫 Эта функция временно отключена.",
            "فارسی 🇮🇷":    "🚫 این ویژگی در حال حاضر غیرفعال است.",
            "हिन्दी 🇮🇳":   "🚫 यह सुविधा अभी अक्षम है।",
            "Türkçe 🇹🇷":   "🚫 Bu özellik şu anda devre dışı.",
            "Deutsch 🇩🇪":  "🚫 Diese Funktion ist derzeit deaktiviert.",
            "Español 🇲🇽":  "🚫 Esta función está desactivada.",
            "Português 🇧🇷":"🚫 Este recurso está desativado.",
            "Italiano 🇮🇹": "🚫 Questa funzione è disabilitata.",
            "Українська 🇺🇦":"🚫 Ця функція наразі вимкнена.",
            "اردو 🇵🇰":     "🚫 یہ خصوصیت ابھی غیر فعال ہے۔",
            "Français 🇫🇷": "🚫 Cette fonctionnalité est désactivée.",
        }.get(lang, "🚫 This feature is currently disabled.")
    if mode == "premium_only":
        return {
            "العربية 🇮🇶": "⭐ هذه الميزة للمستخدمين المميزين فقط.\nأرسل /subscribe لمعرفة كيف تحصل عليها!",
            "English 🇬🇧":  "⭐ This feature is for premium users only.\nSend /subscribe to upgrade!",
            "Русский 🇷🇺":  "⭐ Эта функция только для премиум пользователей.\nОтправьте /subscribe!",
        }.get(lang, "⭐ Premium only. Send /subscribe to upgrade!")
    return {
        "العربية 🇮🇶": "⚠️ وصلت لحد الاستخدام اليومي لهذه الميزة.\n⭐ ادعُ أصدقاءك أو اشترك مميزاً للحصول على حد أعلى!",
        "English 🇬🇧":  "⚠️ Daily limit reached for this feature.\n⭐ Invite friends or subscribe for a higher limit!",
        "Русский 🇷🇺":  "⚠️ Дневной лимит исчерпан.\n⭐ Пригласите друзей или подпишитесь на премиум!",
    }.get(lang, "⚠️ Daily limit reached. Invite friends or subscribe to unlock more!")


# ─── Global Feature Usage Stats (InsightX Analytics Engine) ─────────────────
_feature_usage_stats: dict = {}   # {feature: total_count}
_stats_lock = threading.Lock()

def _log_feature_stat(feature: str):
    """يُسجّل استخدام ميزة في الإحصائيات الإجمالية."""
    with _stats_lock:
        _feature_usage_stats[feature] = _feature_usage_stats.get(feature, 0) + 1


# ─── Content Quality Score (InsightX Layer 16) ───────────────────────────────
def _content_quality_score(title: str, summary: str = "") -> int:
    """
    يُقيّم جودة محتوى الخبر بدون AI (سريع):
    - طول العنوان ومحتواه
    - وجود أرقام وتفاصيل
    - غياب كلمات ترويجية
    يُعيد نقاط 0-100.
    """
    if not title:
        return 0
    score = 0
    tl = title.lower()
    # طول مناسب (20-150 حرف)
    tlen = len(title)
    if 20 <= tlen <= 150:
        score += 25
    elif tlen > 0:
        score += 10
    # وجود أرقام أو إحصاءات
    if any(c.isdigit() for c in title):
        score += 15
    # وجود ملخص
    if summary and len(summary) > 50:
        score += 20
    # كلمات مؤشرة على التفاصيل
    detail_words = {'قال','أكد','أعلن','كشف','أفاد','رصد','وثّق','وثق','said','announced','confirmed','revealed'}
    if any(w in tl for w in detail_words):
        score += 15
    # عقوبة على كلمات ترويجية
    promo_words = {'شارك','اشترك','تابعنا','قناتنا','subscribe','follow','join','forward','انضم'}
    if any(w in tl for w in promo_words):
        score -= 30
    # خبر عاجل = جودة عالية في العادة
    if _news_importance_score(title) >= 2:
        score += 25
    elif _news_importance_score(title) == 1:
        score += 10
    return max(0, min(100, score))


# ─── Smart Semantic Deduplication (اقتراح 1) ─────────────────────────────────
# منع بث خبرين يحملان نفس المعنى من مصادر مختلفة (Jaccard similarity)
_recent_sent_titles: dict = {}   # {lang: [(frozenset(words), ts), ...]}
_semantic_dedup_lock = threading.Lock()
_SEMANTIC_DEDUP_WINDOW = 2 * 3600   # نافذة 2 ساعة
_SEMANTIC_DEDUP_THRESHOLD = 0.85    # تشابه ≥ 85% = نسخة مكررة

def _is_semantic_duplicate(title: str, lang: str) -> bool:
    """
    يكتشف إذا كان الخبر مكرراً معنوياً مقارنةً بالأخبار المبثوثة مؤخراً.
    يستخدم Jaccard similarity على مستوى الكلمات.
    يُعيد True إذا كان مكرراً.
    """
    if not title or len(title) < 15:
        return False
    stop = {'و','في','من','على','إلى','أن','هذا','هذه','ذلك','أو','the','a','an','of','in','is','are'}
    words = frozenset(w for w in _re.sub(r'[^\w\s]', ' ', title.lower()).split()
                      if len(w) > 2 and w not in stop)
    if not words:
        return False
    now = time.time()
    with _semantic_dedup_lock:
        entries = _recent_sent_titles.get(lang, [])
        # تنظيف المنتهية الصلاحية
        entries = [(w, ts) for w, ts in entries if now - ts < _SEMANTIC_DEDUP_WINDOW]
        for stored_words, _ in entries:
            if not stored_words:
                continue
            inter = len(words & stored_words)
            union = len(words | stored_words)
            if union > 0 and inter / union >= _SEMANTIC_DEDUP_THRESHOLD:
                _recent_sent_titles[lang] = entries
                return True
        # FIX: حُذف التسجيل التلقائي هنا — كان يُسجّل كل خبر لمجرد فحصه
        # فيمنع إرساله في الدورة التالية حتى لو لم يُرسَل فعلاً.
        # التسجيل الصحيح يتم عبر _register_broadcast_title بعد الإرسال الفعلي.
        _recent_sent_titles[lang] = entries   # نحدّث فقط بعد تنظيف المنتهية
    return False

def _register_broadcast_title(title: str, lang: str):
    """يُسجّل عنوان الخبر بعد بثّه لمنع التكرار المعنوي مستقبلاً."""
    if not title or len(title) < 15:
        return
    stop = {'و','في','من','على','إلى','أن','هذا','هذه','ذلك','أو','the','a','an','of','in','is','are'}
    words = frozenset(w for w in _re.sub(r'[^\w\s]', ' ', title.lower()).split()
                      if len(w) > 2 and w not in stop)
    now = time.time()
    with _semantic_dedup_lock:
        entries = _recent_sent_titles.setdefault(lang, [])
        entries.append((words, now))
        _recent_sent_titles[lang] = entries[-300:]


# ─── Rate Limiter لأزرار AI (اقتراح للاستقرار) ───────────────────────────────
# يمنع إساءة الاستخدام وحماية حصة Gemini API
_user_ai_cooldown: dict = {}   # {uid_str: {feature: last_ts}}
_cooldown_lock = threading.Lock()
_FEATURE_COOLDOWN: dict = {    # ثوانٍ بين استدعاءات نفس الميزة من نفس المستخدم
    # ── أزرار inline (خفيفة) ─────────────────────────────────────
    "why_matters":  4,
    "what_next":    4,
    "intel_report": 6,
    "context":      5,
    "factcheck":    3,
    "summary":      3,
    "audio":        10,
    "compare":      8,
    # ── أوامر نصية (ثقيلة — تستهلك quota أكثر) ──────────────────
    "ask":          45,    # /ask  — محادثة مع الأخبار
    "verify":       60,    # /verify — التحقق من شائعة
    "profile":      120,   # /profile — ملف شخصية
    "influence":    120,   # /influence — خريطة نفوذ
    "timeline":     60,    # /timeline — جدول زمني
    "search":       5,     # /search — بحث (خفيف)
    "deepsearch":   300,   # /deepsearch — بحث عميق (5 دقائق بين كل بحث)
    "econ":         30,    # /econ — الاقتصاد
    "weather":      30,    # /weather — الطقس
}

def _is_rate_limited(uid, feature: str) -> bool:
    """
    يُعيد True إذا نادى المستخدم هذه الميزة في الثوانٍ الأخيرة.
    يُعيد False ويُحدّث الطابع الزمني إذا كان مسموحاً.
    """
    cooldown = _FEATURE_COOLDOWN.get(feature, 3)
    now = time.time()
    uid_str = str(uid)
    with _cooldown_lock:
        # تنظيف دوري: أزل المستخدمين غير النشطين منذ ساعة لمنع تضخم الذاكرة
        if len(_user_ai_cooldown) > 100:
            cutoff = now - 3600
            stale = [k for k, v in list(_user_ai_cooldown.items())
                     if all(t < cutoff for t in v.values())]
            for k in stale:
                _user_ai_cooldown.pop(k, None)
        user_cd = _user_ai_cooldown.setdefault(uid_str, {})
        last = user_cd.get(feature, 0.0)
        if now - last < cooldown:
            return True
        user_cd[feature] = now
    return False


