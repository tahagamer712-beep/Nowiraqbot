# bot_utils.py
import re
import datetime
import hashlib
import calendar
import urllib.parse
from config import SA_TZ_OFFSET, SOURCE_NAMES, _TG_CHANNEL_NAMES

# =============================================================================
# 1. دوال التاريخ والوقت
# =============================================================================
def _now_sa():
    """يُعيد الوقت الحالي بتوقيت السعودية / العراق (UTC+3)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + SA_TZ_OFFSET

def _sa_str(fmt="%H:%M:%S — %d/%m/%Y"):
    """يُعيد الوقت الحالي كنص بتوقيت السعودية بالصيغة المطلوبة."""
    return _now_sa().strftime(fmt)

def _pub_dt_from_item(item):
    """استخراج pub_dt من feedparser item."""
    pub_struct = (getattr(item, 'published_parsed', None) or getattr(item, 'updated_parsed', None))
    if pub_struct:
        try:
            return datetime.datetime.utcfromtimestamp(calendar.timegm(pub_struct))
        except:
            pass
    return None

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
    "Français 🇫🇷": ("à l'instant", "il y a {} min", "il y a {} h"),
}

def _format_pub_time(pub_dt, lang=None):
    if pub_dt is None:
        patterns = _PUB_TIME_I18N.get(lang) or _PUB_TIME_I18N["العربية 🇮🇶"]
        return f"🕐 {patterns[0]}"
    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        diff_min = int((now_utc - pub_dt).total_seconds() / 60)
        if diff_min < 0:
            diff_min = 0
        patterns = _PUB_TIME_I18N.get(lang) or _PUB_TIME_I18N["العربية 🇮🇶"]
        just_now_txt, min_fmt, hr_fmt = patterns
        if diff_min < 2:
            label = just_now_txt
        elif diff_min < 60:
            label = min_fmt.format(diff_min)
        elif diff_min < 1440:
            label = hr_fmt.format(diff_min // 60)
        else:
            local_dt = pub_dt + datetime.timedelta(hours=3)
            label = local_dt.strftime("%d/%m %H:%M")
        return f"🕐 {label}"
    except:
        return ""

# =============================================================================
# 2. دوال تنظيف وتنسيق النصوص
# =============================================================================
def escape_md(text):
    if not text:
        return ""
    for ch in ['_', '*', '`', '[', ']', '\\']:
        text = text.replace(ch, '')
    return text

def _clean_html(text):
    """إزالة وسوم HTML والروابط من الملخص."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    text = re.sub(r'https?://t\.me/\S*', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'@[A-Za-z0-9_]{3,}', '', text)
    text = re.sub(r'(المصدر|Source|via|©|حصري)[^\n]*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s{3,}', ' ', text)
    return text.strip()

# =============================================================================
# 3. دوال استخراج المصادر والأسماء
# =============================================================================
def get_source_name_from_url(feed_url):
    """استخراج اسم المصدر من رابط الـ RSS أو رابط تلغرام"""
    try:
        if "t.me/" in feed_url:
            clean_url = feed_url.replace("https://", "").replace("http://", "")
            parts = clean_url.split("/")
            handle = parts[1] if len(parts) > 1 else parts[0].split("t.me/")[-1]
            handle = handle.split("?")[0].strip()
            if handle in _TG_CHANNEL_NAMES:
                return _TG_CHANNEL_NAMES[handle]
            for key, name in SOURCE_NAMES.items():
                if key.startswith("t.me/") and key.split("t.me/")[-1].lower() == handle.lower():
                    return name
            return f"@{handle}"
        host = urllib.parse.urlparse(feed_url).netloc.lower()
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
    except:
        return ""

def get_source_name_from_feed(feed_obj, feed_url=""):
    try:
        feed_meta = getattr(feed_obj, 'feed', None)
        if feed_meta:
            feed_title = getattr(feed_meta, 'title', '')
            if feed_title and len(feed_title.strip()) > 1:
                clean = feed_title.strip().split('|')[0].split(' - ')[0].strip()
                if clean and len(clean) < 60:
                    return clean
    except:
        pass
    return get_source_name_from_url(feed_url)

# =============================================================================
# 4. دوال التحقق من اللغة والعناوين
# =============================================================================
def _title_in_lang(title, lang):
    """هل عنوان الخبر بالفعل بلغة المستخدم؟"""
    if lang in ("Deutsch 🇩🇪","Türkçe 🇹🇷","Português 🇧🇷","Italiano 🇮🇹","Español 🇲🇽","English 🇬🇧","Français 🇫🇷"):
        return True
    non_space = [c for c in title if not c.isspace()]
    if not non_space:
        return True
    ar_chars = len(re.findall(r'[\u0600-\u06FF]', title))
    return ar_chars / len(non_space) >= 0.25

# =============================================================================
# 5. دوال التقييم والأهمية
# =============================================================================
_IMPORTANCE_HIGH = {
    'عاجل','انفجار','اغتيال','زلزال','هجوم','breaking','urgent','explosion',
    'attack','killed','earthquake','war','crisis','missile','strike'
}
_IMPORTANCE_MEDIUM = {
    'مهم','تحذير','قرار','احتجاج','أزمة','warning','alert','protest','election'
}

def _news_importance_score(title):
    if not title:
        return 0
    words = set(re.sub(r'[^\w\s]', ' ', title.lower()).split())
    if words & _IMPORTANCE_HIGH:
        return 2
    if words & _IMPORTANCE_MEDIUM:
        return 1
    return 0

# =============================================================================
# 6. دوال التجزئة والمفاتيح
# =============================================================================
def _normalize_news_link(url: str) -> str:
    if not url:
        return url
    try:
        p = urllib.parse.urlparse(url.strip())
        clean = urllib.parse.urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))
        return clean.lower() if clean else url
    except:
        return url

def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:16]
