# -*- coding: utf-8 -*-
"""
features_sports.py — نظام الرياضة بأكمله (PATCH v5 + v6, مستخرج فعلياً من bot_legacy.py)

يحتوي على:
- 40+ ميزة تفاعل/إدمان (PATCH v5)
- نظام تفاصيل المباراة بأسلوب 365score (PATCH v6)
- جلب البيانات من ESPN, إحصائيات المباريات, التشكيلات
- التحديث التلقائي للنتائج المباشرة كل 10 ثواني
"""

import os, sys, json, time, threading, datetime, re, random
from concurrent.futures import ThreadPoolExecutor

# في وقت تحميل هذه الوحدة (آخر شيء في bot_legacy)، bot وكل شيء آخر
# مُعرَّف بالكامل، لذا الاستيراد المباشر آمن:
import bot_legacy as _legacy
_logger     = _legacy._logger
_log_exc    = _legacy._log_exc
bot         = _legacy.bot

  # ════════════════════════════════════════════════════════════════════
  # FIX: استيراد كل الـ globals الناقصة من bot_legacy
  # ════════════════════════════════════════════════════════════════════
_db_lock               = getattr(_legacy, '_db_lock', None)
_db_conn               = getattr(_legacy, '_db_conn', None)
_save_users            = getattr(_legacy, 'save_users', lambda: None)
safe_send_message      = getattr(_legacy, 'safe_send_message', lambda *a,**k: None)
_news_importance_score = getattr(_legacy, '_news_importance_score', lambda *a,**k: 0)
_ai_why_it_matters     = getattr(_legacy, '_ai_why_it_matters', lambda *a,**k: '')
_ai_what_next          = getattr(_legacy, '_ai_what_next', lambda *a,**k: '')
_AI_MODEL              = getattr(_legacy, '_AI_MODEL', None)
_AI_EXECUTOR           = getattr(_legacy, '_AI_EXECUTOR', None)
_ai_generate           = getattr(_legacy, '_ai_generate', lambda *a,**k: '')

class _LazyDictProxy:
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
  # ════════════════════════════════════════════════════════════════════

  

# ════════════════════════════════════════════════════════════════════
# الكود المُستخرَج فعلياً من bot_legacy.py (الأسطر 33793–35793 الأصلية)
# ════════════════════════════════════════════════════════════════════

def _export_all_to(target_globals):
    """ينسخ كل الأسماء (حتى التي تبدأ بـ _) إلى namespace المستدعي."""
    for _k, _v in list(globals().items()):
        if _k.startswith('__'):
            continue
        target_globals[_k] = _v



# ═══════════════════════════════════════════════════════════════════════════
# PATCH v5  –  40+ ENGAGEMENT / ADDICTION FEATURES
# ═══════════════════════════════════════════════════════════════════════════
import hashlib   as _v5_hashlib
import datetime  as _v5_dt
import threading as _v5_threading

# ────────────────────────────────────────────────
# 1. جداول قاعدة البيانات
# ────────────────────────────────────────────────
def _v5_init_tables():
    with _db_lock:
        _db_conn.executescript("""
            -- نظام التنبؤ (Prediction Game)
            CREATE TABLE IF NOT EXISTS v5_predictions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                news_key    TEXT,
                title       TEXT,
                opt_a TEXT, opt_b TEXT, opt_c TEXT,
                correct_idx INTEGER DEFAULT -1,
                created_at  REAL,
                resolves_at REAL
            );
            CREATE TABLE IF NOT EXISTS v5_pred_votes (
                uid     TEXT,
                pred_id INTEGER,
                opt_idx INTEGER,
                voted_at REAL,
                PRIMARY KEY (uid, pred_id)
            );
            -- الكبسولة الزمنية (Time Capsule)
            CREATE TABLE IF NOT EXISTS v5_capsule (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                uid         TEXT,
                news_title  TEXT,
                comment     TEXT,
                created_at  REAL,
                remind_at   REAL
            );
            -- ساعة الحقيقة (Truth Hour)
            CREATE TABLE IF NOT EXISTS v5_truth (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                title    TEXT,
                source   TEXT,
                is_real  INTEGER,
                sent_at  REAL,
                revealed INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS v5_truth_votes (
                uid      TEXT,
                truth_id INTEGER,
                vote     INTEGER,
                voted_at REAL,
                PRIMARY KEY (uid, truth_id)
            );
            -- نبضة الرأي (Opinion Pulse)
            CREATE TABLE IF NOT EXISTS v5_opinion (
                news_key  TEXT PRIMARY KEY,
                votes_json TEXT DEFAULT '{}'
            );
            -- نبضة الشارع (Street Pulse)
            CREATE TABLE IF NOT EXISTS v5_street (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT,
                sent_at  REAL,
                active   INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS v5_street_ans (
                uid         TEXT,
                pulse_id    INTEGER,
                answer      TEXT,
                answered_at REAL,
                PRIMARY KEY (uid, pulse_id)
            );
            -- القضايا المتسلسلة (Story Arcs)
            CREATE TABLE IF NOT EXISTS v5_arcs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                title     TEXT,
                topic_key TEXT UNIQUE,
                created_at REAL,
                chapter   INTEGER DEFAULT 0,
                active    INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS v5_arc_subs (
                uid     TEXT,
                arc_id  INTEGER,
                PRIMARY KEY (uid, arc_id)
            );
            CREATE TABLE IF NOT EXISTS v5_arc_chapters (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                arc_id  INTEGER,
                chapter INTEGER,
                content TEXT,
                sent_at REAL
            );
            -- مساهمات المستخدم (Citizen Tips)
            CREATE TABLE IF NOT EXISTS v5_tips (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                uid     TEXT,
                tip     TEXT,
                status  TEXT DEFAULT 'pending',
                sent_at REAL
            );
            -- تتبع القراءة (News Reads - for IQ, leaderboard, badges)
            CREATE TABLE IF NOT EXISTS v5_reads (
                uid      TEXT,
                news_key TEXT,
                read_at  REAL,
                PRIMARY KEY (uid, news_key)
            );
            -- الخيط الحي (Live Thread)
            CREATE TABLE IF NOT EXISTS v5_live (
                news_key TEXT PRIMARY KEY,
                title    TEXT,
                upd_json TEXT DEFAULT '[]',
                last_upd REAL,
                active   INTEGER DEFAULT 1
            );
            -- أخبار تختفي (Vanishing News)
            CREATE TABLE IF NOT EXISTS v5_vanish (
                news_key   TEXT PRIMARY KEY,
                title      TEXT,
                expires_at REAL,
                expired    INTEGER DEFAULT 0
            );
            -- تحدي الأصدقاء (Friend Challenge)
            CREATE TABLE IF NOT EXISTS v5_challenges (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                uid_a      TEXT,
                uid_b      TEXT,
                questions  TEXT,
                score_a    INTEGER DEFAULT 0,
                score_b    INTEGER DEFAULT 0,
                created_at REAL,
                finished   INTEGER DEFAULT 0
            );
            -- خبر الغد (Tomorrow Headlines)
            CREATE TABLE IF NOT EXISTS v5_tomorrow (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction  TEXT,
                created_at  REAL,
                resolved    INTEGER DEFAULT 0
            );
        """)
        _db_conn.commit()
    _logger.info("✅ v5 tables ready")

try:
    _v5_init_tables()
except Exception as _e:
    _logger.error(f"v5 table init error: {_e}")

# ────────────────────────────────────────────────
# 2. مساعدات عامة
# ────────────────────────────────────────────────
def _v5_news_key(title: str) -> str:
    return _v5_hashlib.md5(title.encode()).hexdigest()[:12]

def _v5_ai(prompt: str, timeout: int = 25) -> str:
    """استدعاء AI جنيريك لميزات v5."""
    try:
        def _call():
            if _AI_MODEL:
                _r_ai = _ai_generate(prompt)
                return (_r_ai or "")
            return ""
        return _AI_EXECUTOR.submit(_call).result(timeout=timeout)
    except Exception as _e:
        _logger.warning(f"v5_ai error: {_e}")
        return ""

def _v5_user_flag(uid, key, default=None):
    """يقرأ علامة مستخدم من users dict."""
    try:
        u = users.get(str(uid), {})
        return u.get(key, default)
    except Exception:
        return default

def _v5_set_flag(uid, key, val):
    """يحفظ علامة مستخدم في users dict."""
    try:
        uid = str(uid)
        if uid not in users:
            users[uid] = {}
        users[uid][key] = val
        _save_users()
    except Exception as _e:
        _logger.warning(f"v5_set_flag: {_e}")

def _v5_mk(rows):
    """ينشئ InlineKeyboardMarkup من قائمة أزرار."""
    from telebot import types as _t
    m = _t.InlineKeyboardMarkup(row_width=len(rows[0]) if rows else 1)
    for row in rows:
        m.row(*[_t.InlineKeyboardButton(b[0], callback_data=b[1]) for b in row])
    return m

# ────────────────────────────────────────────────
# 3. نظام الأوضاع (Modes)
# ────────────────────────────────────────────────
_V5_MODES = {
    "normal":       "📰 عادي – كل الأخبار",
    "busy":         "⚡ مشغول – 8 كلمات فقط",
    "wave":         "🌊 موجة – ملخص يومي واحد",
    "analyst":      "🧠 محلل – 3 أسئلة مع كل خبر",
    "one_per_hour": "⏱ خبر/ساعة – حصري",
}

@bot.message_handler(commands=["mode"])
def _v5_cmd_mode(msg):
    uid = str(msg.from_user.id)
    cur = _v5_user_flag(uid, "v5_mode", "normal")
    rows = [[(_V5_MODES[k] + (" ✅" if k == cur else ""), f"v5mode_{k}")]
            for k in _V5_MODES]
    safe_send_message(uid, "🎛 *اختر وضع استقبال الأخبار:*",
                      parse_mode="Markdown", reply_markup=_v5_mk(rows))

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5mode_"))
def _v5_cb_mode(call):
    uid  = str(call.from_user.id)
    mode = call.data.split("_", 1)[1]
    if mode not in _V5_MODES:
        return
    _v5_set_flag(uid, "v5_mode", mode)
    bot.answer_callback_query(call.id, f"✅ تم: {_V5_MODES[mode]}")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                  reply_markup=None)

def _v5_format_for_mode(uid, title, summary, link=""):
    """يُشكّل الخبر حسب وضع المستخدم."""
    mode = _v5_user_flag(uid, "v5_mode", "normal")
    # درجة حرارة الخبر
    score = _news_importance_score(title)
    temp  = {0: "🔵 بارد", 1: "🟡 دافئ", 2: "🔴 حارق"}.get(score, "🔵 بارد")

    if mode == "busy":
        prompt = f"لخّص هذا الخبر بـ 8 كلمات بالعربية فقط:\n{title}"
        short  = _v5_ai(prompt) or title[:60]
        return f"{temp} {short}"
    elif mode == "analyst":
        qs = ("❓ من يستفيد؟\n❓ ما المعلومة الغائبة؟\n❓ ما التاريخي المشابه؟")
        return (f"{temp} *{title}*\n\n{summary}\n\n"
                f"━━━━━━━━━━━━━━━━━\n🧠 *أسئلة التحليل:*\n{qs}")
    else:  # normal / one_per_hour / wave
        # Zero-Click News
        why  = _ai_why_it_matters(title, summary)
        what = _ai_what_next(title, summary)
        body = (f"{temp}\n"
                f"🔴 *ماذا حدث:* {title}\n"
                f"🟡 *لماذا يهمك:* {why}\n"
                f"🟢 *ماذا بعد:* {what}")
        if link:
            body += f"\n\n🔗 [التفاصيل]({link})"
        return body

# ────────────────────────────────────────────────
# 4. القبيلة الإخبارية (News Tribe)
# ────────────────────────────────────────────────
_V5_TRIBES = {
    "rational":  "🧩 العقلانيون – نحلل قبل نحكم",
    "skeptic":   "🔍 المتشككون – نسأل عن الدليل",
    "optimist":  "🌟 المتفائلون – نرى الفرصة في الأزمة",
}

@bot.message_handler(commands=["tribe"])
def _v5_cmd_tribe(msg):
    uid = str(msg.from_user.id)
    cur = _v5_user_flag(uid, "v5_tribe", None)
    rows = [[(_V5_TRIBES[k] + (" ✅" if k == cur else ""), f"v5tribe_{k}")]
            for k in _V5_TRIBES]
    safe_send_message(uid,
        "🏛 *اختر قبيلتك الإخبارية:*\nستتلقى الأخبار بأسلوب يناسب تفكيرك.",
        parse_mode="Markdown", reply_markup=_v5_mk(rows))

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5tribe_"))
def _v5_cb_tribe(call):
    uid   = str(call.from_user.id)
    tribe = call.data.split("_", 1)[1]
    if tribe not in _V5_TRIBES:
        return
    _v5_set_flag(uid, "v5_tribe", tribe)
    bot.answer_callback_query(call.id, f"✅ انضممت لـ {_V5_TRIBES[tribe][:20]}")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                  reply_markup=None)
    safe_send_message(uid,
        f"🎖 أنت الآن من *{_V5_TRIBES[tribe]}*\n"
        f"ستصلك الأخبار بزاوية مميزة تناسب تفكيرك.",
        parse_mode="Markdown")

# ────────────────────────────────────────────────
# 5. نظام التنبؤ (Prediction Game)
# ────────────────────────────────────────────────
def _v5_create_prediction(news_key, title):
    """ينشئ تنبؤاً بعد خبر مهم."""
    try:
        prompt = (
            f"بناءً على هذا الخبر العراقي:\n{title}\n\n"
            f"اكتب سؤالاً واحداً عن ما سيحدث خلال 48 ساعة "
            f"مع 3 خيارات (أ، ب، ج) بالعربية.\n"
            f"الصيغة:\nالسؤال: ...\nأ: ...\nب: ...\nج: ..."
        )
        resp = _v5_ai(prompt)
        lines = [l.strip() for l in resp.split("\n") if l.strip()]
        q = a = b = c = ""
        for l in lines:
            if l.startswith("السؤال:"): q = l[7:].strip()
            elif l.startswith("أ:"): a = l[2:].strip()
            elif l.startswith("ب:"): b = l[2:].strip()
            elif l.startswith("ج:"): c = l[2:].strip()
        if not (q and a and b and c):
            return
        now = time.time()
        with _db_lock:
            _db_conn.execute(
                "INSERT INTO v5_predictions(news_key,title,opt_a,opt_b,opt_c,created_at,resolves_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (news_key, q, a, b, c, now, now + 172800))
            pid = _db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            _db_conn.commit()
        # أرسل لكل المشتركين
        markup = _v5_mk([
            [(f"أ) {a[:30]}", f"v5pred_{pid}_0"),
             (f"ب) {b[:30]}", f"v5pred_{pid}_1")],
            [(f"ج) {c[:30]}", f"v5pred_{pid}_2")],
        ])
        txt = f"🔮 *سؤال التنبؤ:*\n{q}\n\n⏳ ستُكشف النتيجة بعد 48 ساعة"
        for uid in list(users.keys()):
            try:
                safe_send_message(uid, txt, parse_mode="Markdown", reply_markup=markup)
                time.sleep(0.07)
            except Exception as _exc:
                _log_exc(_exc)
    except Exception as _e:
        _logger.warning(f"create_prediction: {_e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5pred_"))
def _v5_cb_pred(call):
    uid = str(call.from_user.id)
    parts = call.data.split("_")
    if len(parts) < 3:
        return
    pid, opt = int(parts[1]), int(parts[2])
    now = time.time()
    with _db_lock:
        existing = _db_conn.execute(
            "SELECT opt_idx FROM v5_pred_votes WHERE uid=? AND pred_id=?",
            (uid, pid)).fetchone()
        if existing:
            bot.answer_callback_query(call.id, "⚠️ سبق وصوّتَ على هذا التنبؤ.")
            return
        _db_conn.execute(
            "INSERT INTO v5_pred_votes(uid,pred_id,opt_idx,voted_at) VALUES(?,?,?,?)",
            (uid, pid, opt, now))
        _db_conn.commit()
    opts = ["أ", "ب", "ج"]
    bot.answer_callback_query(call.id, f"✅ اخترتَ الخيار {opts[opt]} — انتظر 48 ساعة!")

def _v5_resolve_predictions():
    """يُحلّل التنبؤات المنتهية (يُشغَّل كل ساعة)."""
    try:
        now = time.time()
        with _db_lock:
            pending = _db_conn.execute(
                "SELECT id,title,opt_a,opt_b,opt_c FROM v5_predictions "
                "WHERE correct_idx=-1 AND resolves_at<=?", (now,)).fetchall()
        for pid, title, a, b, c in pending:
            prompt = (
                f"بناءً على الأحداث الأخيرة في العراق، أي خيار من الثلاثة "
                f"هو الأكثر احتمالاً لخبر: '{title}'؟\n"
                f"أ: {a}\nب: {b}\nج: {c}\n"
                f"أجب برقم فقط: 0 أو 1 أو 2"
            )
            resp = _v5_ai(prompt).strip()
            idx  = int(resp) if resp in ("0", "1", "2") else 0
            opts = [a, b, c]
            with _db_lock:
                _db_conn.execute(
                    "UPDATE v5_predictions SET correct_idx=? WHERE id=?", (idx, pid))
                votes = _db_conn.execute(
                    "SELECT uid,opt_idx FROM v5_pred_votes WHERE pred_id=?", (pid,)).fetchall()
                _db_conn.commit()
            winners = [v[0] for v in votes if v[1] == idx]
            total   = len(votes) or 1
            pct     = round(len(winners) / total * 100)
            txt = (f"🔮 *نتيجة التنبؤ:*\n_{title}_\n\n"
                   f"✅ الإجابة الصحيحة: *{opts[idx]}*\n"
                   f"🏆 {len(winners)} من {total} توقّعوا صحيحاً ({pct}%)")
            for uid, opted in votes:
                msg = txt
                if opted == idx:
                    pct_rank = round((1 - pct/100) * 100)
                    msg += f"\n\n🎖 *توقعك كان صحيحاً — أذكى من {pct_rank}% من المستخدمين!*"
                    # رفع مستوى الـ IQ
                    old_iq = _v5_user_flag(uid, "v5_iq", 50.0)
                    _v5_set_flag(uid, "v5_iq", round(min(100, old_iq + 1.5), 1))
                try:
                    safe_send_message(uid, msg, parse_mode="Markdown")
                except Exception as _exc:
                    _log_exc(_exc)
    except Exception as _e:
        _logger.warning(f"resolve_predictions: {_e}")

# ────────────────────────────────────────────────
# 6. الكبسولة الزمنية (Time Capsule)
# ────────────────────────────────────────────────
_V5_CAPSULE_WAIT = {}  # uid -> news_title

@bot.message_handler(commands=["capsule"])
def _v5_cmd_capsule(msg):
    uid = str(msg.from_user.id)
    safe_send_message(uid,
        "⏳ *الكبسولة الزمنية*\n\n"
        "أرسل تعليقك على أي خبر الآن.\n"
        "سأُرسله لك في مثل هذا اليوم العام القادم.\n\n"
        "اكتب تعليقك:",
        parse_mode="Markdown")
    _V5_CAPSULE_WAIT[uid] = "__any__"

@bot.message_handler(func=lambda m: str(m.from_user.id) in _V5_CAPSULE_WAIT
                     and not m.text.startswith("/"))
def _v5_capsule_receive(msg):
    uid   = str(msg.from_user.id)
    topic = _V5_CAPSULE_WAIT.pop(uid, "")
    if not topic:
        return
    now      = time.time()
    remind   = now + 365 * 86400
    with _db_lock:
        _db_conn.execute(
            "INSERT INTO v5_capsule(uid,news_title,comment,created_at,remind_at) VALUES(?,?,?,?,?)",
            (uid, topic, msg.text[:500], now, remind))
        _db_conn.commit()
    safe_send_message(uid,
        "✅ *حُفظت كبسولتك!*\n"
        f"سأُذكّرك بها في {_v5_dt.date.today().replace(year=_v5_dt.date.today().year+1)}\n\n"
        f"_كتبتَ: {msg.text[:100]}_",
        parse_mode="Markdown")

def _v5_check_capsules():
    """يُرسل الكبسولات المنتهية (يُشغَّل يومياً)."""
    try:
        now = time.time()
        with _db_lock:
            rows = _db_conn.execute(
                "SELECT id,uid,news_title,comment,created_at FROM v5_capsule "
                "WHERE remind_at<=? AND remind_at>0", (now,)).fetchall()
        for rid, uid, title, comment, created in rows:
            d = _v5_dt.date.fromtimestamp(created).strftime("%d/%m/%Y")
            safe_send_message(uid,
                f"📦 *كبسولة زمنية!*\n\n"
                f"في {d} كتبتَ:\n\n_{comment}_",
                parse_mode="Markdown")
            with _db_lock:
                _db_conn.execute("UPDATE v5_capsule SET remind_at=0 WHERE id=?", (rid,))
                _db_conn.commit()
    except Exception as _e:
        _logger.warning(f"check_capsules: {_e}")

# ────────────────────────────────────────────────
# 7. ساعة الحقيقة (Truth Hour)
# ────────────────────────────────────────────────
_V5_TRUTH_ACTIVE = {}  # uid -> truth_id (انتظار التصويت)

def _v5_send_truth_hour():
    """يُرسل ساعة الحقيقة اليومية."""
    try:
        with _db_lock:
            row = _db_conn.execute(
                "SELECT id,title,source,is_real FROM v5_truth "
                "WHERE revealed=0 ORDER BY RANDOM() LIMIT 1").fetchone()
        if not row:
            # ولّد خبراً حقيقياً وآخر مزيفاً
            prompt = ("اكتب عنواناً لخبر عراقي حقيقي حدث عام 2024 وعنواناً واحداً مزيفاً."
                      "\nالصيغة:\nحقيقي: ...\nمزيف: ...")
            resp = _v5_ai(prompt)
            real_title = fake_title = ""
            for l in resp.split("\n"):
                if l.startswith("حقيقي:"): real_title = l[6:].strip()
                elif l.startswith("مزيف:"): fake_title = l[5:].strip()
            if real_title:
                with _db_lock:
                    _db_conn.execute(
                        "INSERT INTO v5_truth(title,source,is_real,sent_at) VALUES(?,?,?,?)",
                        (real_title, "مصدر موثّق", 1, time.time()))
                    if fake_title:
                        _db_conn.execute(
                            "INSERT INTO v5_truth(title,source,is_real,sent_at) VALUES(?,?,?,?)",
                            (fake_title, "مصدر مشكوك", 0, time.time()))
                    _db_conn.commit()
            return

        tid, title, source, is_real = row
        markup = _v5_mk([[
            ("✅ حقيقي", f"v5truth_{tid}_1"),
            ("❌ مزيف",  f"v5truth_{tid}_0"),
        ]])
        txt = (f"⚖️ *ساعة الحقيقة اليومية*\n\n"
               f"هل هذا الخبر حقيقي أم مزيف؟\n\n"
               f"📰 _{title}_\n\n"
               f"⏰ لديك 60 دقيقة للتصويت")
        for uid in list(users.keys()):
            try:
                safe_send_message(uid, txt, parse_mode="Markdown", reply_markup=markup)
                time.sleep(0.07)
            except Exception as _exc:
                _log_exc(_exc)
        # كشف بعد ساعة
        def _reveal():
            time.sleep(3600)
            try:
                with _db_lock:
                    votes = _db_conn.execute(
                        "SELECT uid,vote FROM v5_truth_votes WHERE truth_id=?", (tid,)).fetchall()
                    _db_conn.execute("UPDATE v5_truth SET revealed=1 WHERE id=?", (tid,))
                    _db_conn.commit()
                label = "✅ حقيقي" if is_real else "❌ مزيف"
                total = len(votes) or 1
                correct = [v[0] for v in votes if v[1] == is_real]
                pct = round(len(correct) / total * 100)
                for uid, vote in votes:
                    ok = (vote == is_real)
                    msg = (f"⚖️ *نتيجة ساعة الحقيقة:*\n\n"
                           f"الخبر كان: *{label}*\n"
                           f"أجاب {pct}% بشكل صحيح\n\n"
                           f"{'🎯 أحسنتَ!' if ok else '❌ لم تُصِب هذه المرة'}")
                    if ok:
                        old = _v5_user_flag(uid, "v5_iq", 50.0)
                        _v5_set_flag(uid, "v5_iq", round(min(100, old + 1.0), 1))
                    try:
                        safe_send_message(uid, msg, parse_mode="Markdown")
                    except Exception as _exc:
                        _log_exc(_exc)
            except Exception as _re:
                _logger.warning(f"truth reveal: {_re}")
        _v5_threading.Thread(target=_reveal, daemon=True).start()
    except Exception as _e:
        _logger.warning(f"truth_hour: {_e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5truth_"))
def _v5_cb_truth(call):
    uid   = str(call.from_user.id)
    parts = call.data.split("_")
    if len(parts) < 3:
        return
    tid, vote = int(parts[1]), int(parts[2])
    now = time.time()
    with _db_lock:
        ex = _db_conn.execute(
            "SELECT 1 FROM v5_truth_votes WHERE uid=? AND truth_id=?", (uid, tid)).fetchone()
        if ex:
            bot.answer_callback_query(call.id, "⚠️ سبق وصوّتَ!")
            return
        _db_conn.execute(
            "INSERT INTO v5_truth_votes(uid,truth_id,vote,voted_at) VALUES(?,?,?,?)",
            (uid, tid, vote, now))
        _db_conn.commit()
    lbl = "حقيقي ✅" if vote == 1 else "مزيف ❌"
    bot.answer_callback_query(call.id, f"صوّتَ: {lbl} — انتظر الإجابة!")

# ────────────────────────────────────────────────
# 8. نبضة الرأي (Opinion Pulse)
# ────────────────────────────────────────────────
_V5_PULSE_OPTS = ["😡 غاضب", "😢 حزين", "😮 مصدوم", "💪 متفائل"]

def _v5_add_opinion_buttons(news_key, markup=None):
    """يُضيف أزرار التفاعل العاطفي لأي خبر."""
    from telebot import types as _t
    if markup is None:
        markup = _t.InlineKeyboardMarkup(row_width=4)
    btns = [_t.InlineKeyboardButton(o, callback_data=f"v5pulse_{news_key}_{i}")
            for i, o in enumerate(_V5_PULSE_OPTS)]
    markup.row(*btns)
    return markup

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5pulse_"))
def _v5_cb_pulse(call):
    uid   = str(call.from_user.id)
    parts = call.data.split("_")
    if len(parts) < 3:
        return
    news_key, idx = parts[1], int(parts[2])
    with _db_lock:
        row = _db_conn.execute(
            "SELECT votes_json FROM v5_opinion WHERE news_key=?", (news_key,)).fetchone()
        votes = json.loads(row[0]) if row else {}
        # ترقية العداد
        key = str(idx)
        votes[key] = votes.get(key, 0) + 1
        total = sum(votes.values())
        if row:
            _db_conn.execute(
                "UPDATE v5_opinion SET votes_json=? WHERE news_key=?",
                (json.dumps(votes), news_key))
        else:
            _db_conn.execute(
                "INSERT INTO v5_opinion(news_key,votes_json) VALUES(?,?)",
                (news_key, json.dumps(votes)))
        _db_conn.commit()
    # عرض التوزيع
    lines = []
    for i, opt in enumerate(_V5_PULSE_OPTS):
        cnt = votes.get(str(i), 0)
        pct = round(cnt / total * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"{opt}  {bar} {pct}%")
    bot.answer_callback_query(call.id,
        "📊 توزيع ردود الفعل:\n" + "\n".join(lines), show_alert=True)

# ────────────────────────────────────────────────
# 9. وضع المواجهة (Debate Mode)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["debate"])
def _v5_cmd_debate(msg):
    uid   = str(msg.from_user.id)
    parts = msg.text.split(None, 1)
    topic = parts[1] if len(parts) > 1 else ""
    if not topic:
        safe_send_message(uid,
            "🥊 أرسل موضوعاً للنقاش:\n/debate [الموضوع]\n\nمثال:\n/debate رفع سعر الدولار")
        return
    safe_send_message(uid, "⏳ أُحضّر الحجج...", parse_mode="Markdown")
    def _gen():
        prompt = (
            f"موضوع النقاش: {topic}\n\n"
            f"اكتب حجة مؤيدة (3 نقاط) وحجة معارضة (3 نقاط) بالعربية الفصحى.\n"
            f"الصيغة:\n🟢 المؤيدون:\n- ...\n- ...\n- ...\n\n🔴 المعارضون:\n- ...\n- ...\n- ..."
        )
        resp = _v5_ai(prompt) or "تعذّر توليد الحجج."
        markup = _v5_mk([[
            ("🟢 أنا مع المؤيدين", f"v5debate_{_v5_news_key(topic)}_0"),
            ("🔴 أنا مع المعارضين", f"v5debate_{_v5_news_key(topic)}_1"),
        ]])
        safe_send_message(uid,
            f"🥊 *{topic}*\n\n{resp}\n\nأي الجانبين تختار؟",
            parse_mode="Markdown", reply_markup=markup)
    _AI_EXECUTOR.submit(_gen)

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5debate_"))
def _v5_cb_debate(call):
    uid   = str(call.from_user.id)
    parts = call.data.split("_")
    side  = int(parts[2]) if len(parts) > 2 else 0
    key   = parts[1]
    # تخزين اختيار
    field = f"v5debate_{key}"
    old   = _v5_user_flag(uid, field, None)
    if old is not None:
        bot.answer_callback_query(call.id, "⚠️ اخترتَ بالفعل.")
        return
    _v5_set_flag(uid, field, side)
    lbl = "🟢 المؤيدين" if side == 0 else "🔴 المعارضين"
    bot.answer_callback_query(call.id, f"اخترتَ {lbl}")

# ────────────────────────────────────────────────
# 10. نبضة الشارع (Street Pulse)
# ────────────────────────────────────────────────
_V5_STREET_QUESTIONS = [
    "ما أكثر موضوع تسمعه في محادثات الناس اليوم؟",
    "ما أكثر مشكلة تؤثر على حياتك اليومية الآن؟",
    "هل تشعر بتحسّن اقتصادي مقارنة بالعام الماضي؟",
    "ما أكثر خبر أثّر فيك هذا الأسبوع؟",
    "ما توقعك للأشهر القادمة في العراق؟",
]

def _v5_send_street_pulse():
    """يُرسل سؤال نبضة الشارع اليومية."""
    try:
        import random as _r
        q   = _r.choice(_V5_STREET_QUESTIONS)
        now = time.time()
        with _db_lock:
            _db_conn.execute(
                "UPDATE v5_street SET active=0")
            _db_conn.execute(
                "INSERT INTO v5_street(question,sent_at,active) VALUES(?,?,1)", (q, now))
            pid = _db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            _db_conn.commit()
        markup = _v5_mk([[
            ("💬 أرسل رأيك", f"v5street_{pid}"),
        ]])
        txt = f"🌍 *نبضة الشارع اليومية:*\n\n{q}"
        for uid in list(users.keys()):
            try:
                safe_send_message(uid, txt, parse_mode="Markdown", reply_markup=markup)
                time.sleep(0.07)
            except Exception as _exc:
                _log_exc(_exc)
    except Exception as _e:
        _logger.warning(f"street_pulse: {_e}")

_V5_STREET_WAIT = {}  # uid -> pulse_id

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5street_"))
def _v5_cb_street(call):
    uid = str(call.from_user.id)
    pid = int(call.data.split("_")[1])
    _V5_STREET_WAIT[uid] = pid
    bot.answer_callback_query(call.id, "اكتب ردّك والبوت يُشاركه مع الجميع")
    safe_send_message(uid, "💬 اكتب رأيك:")

@bot.message_handler(func=lambda m: str(m.from_user.id) in _V5_STREET_WAIT
                     and not m.text.startswith("/"))
def _v5_street_receive(msg):
    uid = str(msg.from_user.id)
    pid = _V5_STREET_WAIT.pop(uid, None)
    if not pid:
        return
    now  = time.time()
    name = msg.from_user.first_name or "مجهول"
    with _db_lock:
        _db_conn.execute(
            "INSERT OR IGNORE INTO v5_street_ans(uid,pulse_id,answer,answered_at) VALUES(?,?,?,?)",
            (uid, pid, msg.text[:300], now))
        _db_conn.commit()
        total = _db_conn.execute(
            "SELECT COUNT(*) FROM v5_street_ans WHERE pulse_id=?", (pid,)).fetchone()[0]
    safe_send_message(uid, f"✅ شكراً! {total} شخص أجاب حتى الآن.")
    # أرسل للأدمن
    try:
        safe_send_message(str(ADMIN_ID),
            f"📊 إجابة نبضة الشارع:\n👤 {name} ({uid})\n💬 {msg.text[:300]}")
    except Exception as _exc:
        _log_exc(_exc)

# ────────────────────────────────────────────────
# 11. القضايا المتسلسلة (Story Arc)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["arc"])
def _v5_cmd_arc(msg):
    uid   = str(msg.from_user.id)
    parts = msg.text.split(None, 1)
    if len(parts) < 2:
        # عرض الأقواس النشطة
        with _db_lock:
            arcs = _db_conn.execute(
                "SELECT id,title FROM v5_arcs WHERE active=1").fetchall()
        if not arcs:
            safe_send_message(uid, "لا توجد قضايا متسلسلة نشطة حالياً.")
            return
        rows = [[(f"📖 {a[1][:40]}", f"v5arc_sub_{a[0]}")] for a in arcs]
        safe_send_message(uid, "📚 *اختر قضية تتابعها:*",
                          parse_mode="Markdown", reply_markup=_v5_mk(rows))
    else:
        # الأدمن ينشئ قوساً جديداً
        if str(msg.from_user.id) != str(ADMIN_ID):
            safe_send_message(uid, "⛔ هذا الأمر للأدمن فقط.")
            return
        title = parts[1]
        key   = _v5_news_key(title)
        now   = time.time()
        with _db_lock:
            _db_conn.execute(
                "INSERT OR IGNORE INTO v5_arcs(title,topic_key,created_at) VALUES(?,?,?)",
                (title, key, now))
            _db_conn.commit()
        safe_send_message(uid, f"✅ تم إنشاء القضية: {title}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5arc_sub_"))
def _v5_cb_arc_sub(call):
    uid    = str(call.from_user.id)
    arc_id = int(call.data.split("_")[-1])
    with _db_lock:
        ex = _db_conn.execute(
            "SELECT 1 FROM v5_arc_subs WHERE uid=? AND arc_id=?", (uid, arc_id)).fetchone()
        if ex:
            _db_conn.execute(
                "DELETE FROM v5_arc_subs WHERE uid=? AND arc_id=?", (uid, arc_id))
            _db_conn.commit()
            bot.answer_callback_query(call.id, "❌ إلغاء المتابعة")
        else:
            _db_conn.execute(
                "INSERT OR IGNORE INTO v5_arc_subs(uid,arc_id) VALUES(?,?)", (uid, arc_id))
            _db_conn.commit()
            bot.answer_callback_query(call.id, "✅ تم الاشتراك في القضية")

# ────────────────────────────────────────────────
# 12. مساهمات المستخدم (Citizen Tip)
# ────────────────────────────────────────────────
_V5_TIP_WAIT = set()

@bot.message_handler(commands=["tip"])
def _v5_cmd_tip(msg):
    uid   = str(msg.from_user.id)
    parts = msg.text.split(None, 1)
    if len(parts) > 1:
        tip = parts[1][:500]
    else:
        _V5_TIP_WAIT.add(uid)
        safe_send_message(uid, "📲 أرسل خبرك أو ملاحظتك من الشارع:")
        return
    _v5_save_tip(uid, tip, msg.from_user.first_name)

@bot.message_handler(func=lambda m: str(m.from_user.id) in _V5_TIP_WAIT
                     and not m.text.startswith("/"))
def _v5_tip_receive(msg):
    uid = str(msg.from_user.id)
    _V5_TIP_WAIT.discard(uid)
    _v5_save_tip(uid, msg.text[:500], msg.from_user.first_name)

def _v5_save_tip(uid, tip, name):
    now = time.time()
    with _db_lock:
        _db_conn.execute(
            "INSERT INTO v5_tips(uid,tip,sent_at) VALUES(?,?,?)", (uid, tip, now))
        tip_id = _db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _db_conn.commit()
    safe_send_message(uid,
        "✅ *شكراً! وصلنا خبرك*\n"
        "فريق التحرير سيراجعه ويتحقق منه.\n"
        "إذا نُشر ستحصل على شارة 📡 *مراسل ميداني*",
        parse_mode="Markdown")
    try:
        markup = _v5_mk([[
            ("✅ نشر", f"v5tip_pub_{tip_id}"),
            ("❌ رفض", f"v5tip_rej_{tip_id}"),
        ]])
        safe_send_message(str(ADMIN_ID),
            f"📡 مساهمة مستخدم #{tip_id}\n👤 {name} ({uid})\n\n💬 {tip}",
            reply_markup=markup)
    except Exception as _exc:
        _log_exc(_exc)

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5tip_"))
def _v5_cb_tip(call):
    parts  = call.data.split("_")
    action = parts[1]
    tid    = int(parts[2])
    with _db_lock:
        row = _db_conn.execute(
            "SELECT uid,tip FROM v5_tips WHERE id=?", (tid,)).fetchone()
        if not row:
            return
        uid_owner, tip = row
        status = "published" if action == "pub" else "rejected"
        _db_conn.execute("UPDATE v5_tips SET status=? WHERE id=?", (status, tid))
        _db_conn.commit()
    if action == "pub":
        # شارة مراسل ميداني
        badges = _v5_user_flag(uid_owner, "v5_badges", [])
        if "مراسل ميداني 📡" not in badges:
            badges.append("مراسل ميداني 📡")
            _v5_set_flag(uid_owner, "v5_badges", badges)
        safe_send_message(uid_owner,
            "🎉 *تم نشر مساهمتك!*\n"
            "حصلتَ على شارة 📡 *مراسل ميداني*",
            parse_mode="Markdown")
        bot.answer_callback_query(call.id, "✅ تم النشر")
    else:
        safe_send_message(uid_owner,
            "📨 شكراً على مساهمتك — لم يتم نشرها هذه المرة.")
        bot.answer_callback_query(call.id, "❌ تم الرفض")

# ────────────────────────────────────────────────
# 13. السفر الزمني (Time Travel)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["today5y", "today3y", "today1y"])
def _v5_cmd_time_travel(msg):
    uid  = str(msg.from_user.id)
    cmd  = msg.text.split()[0].lstrip("/")
    yrs  = {"today5y": 5, "today3y": 3, "today1y": 1}.get(cmd, 5)
    today = _v5_dt.date.today()
    past  = today.replace(year=today.year - yrs)
    prompt = (
        f"اذكر 5 أخبار مهمة حدثت في العراق والمنطقة في {past.strftime('%d %B %Y')} تقريباً.\n"
        f"كل خبر في سطر واحد مع رمز مناسب."
    )
    safe_send_message(uid, f"⏳ أبحث في تاريخ {past}...")
    def _gen():
        resp = _v5_ai(prompt) or "لا توجد بيانات."
        safe_send_message(uid,
            f"📅 *في مثل هذا اليوم قبل {yrs} سنوات ({past}):*\n\n{resp}",
            parse_mode="Markdown")
    _AI_EXECUTOR.submit(_gen)

# ────────────────────────────────────────────────
# 14. الخيط الحي (Live Thread)  — أدمن فقط
# ────────────────────────────────────────────────
@bot.message_handler(commands=["live"])
def _v5_cmd_live(msg):
    uid = str(msg.from_user.id)
    if str(uid) != str(ADMIN_ID):
        return
    parts = msg.text.split(None, 1)
    if len(parts) < 2:
        safe_send_message(uid, "الاستخدام:\n/live [عنوان الحدث]")
        return
    title = parts[1]
    key   = _v5_news_key(title)
    now   = time.time()
    with _db_lock:
        _db_conn.execute(
            "INSERT OR REPLACE INTO v5_live(news_key,title,upd_json,last_upd,active) VALUES(?,?,?,?,1)",
            (key, title, json.dumps([]), now))
        _db_conn.commit()
    safe_send_message(uid,
        f"🔴 *خيط حي بدأ:*\n{title}\n\n"
        f"أرسل تحديثاً:\n/liveupd {key} [النص]",
        parse_mode="Markdown")

@bot.message_handler(commands=["liveupd"])
def _v5_cmd_liveupd(msg):
    uid = str(msg.from_user.id)
    if str(uid) != str(ADMIN_ID):
        return
    parts = msg.text.split(None, 2)
    if len(parts) < 3:
        return
    key, text = parts[1], parts[2]
    now = time.time()
    with _db_lock:
        row = _db_conn.execute(
            "SELECT title,upd_json FROM v5_live WHERE news_key=? AND active=1", (key,)).fetchone()
        if not row:
            safe_send_message(uid, "❌ لا يوجد خيط حي بهذا المفتاح.")
            return
        title, upd_json = row
        updates = json.loads(upd_json)
        t = _v5_dt.datetime.now().strftime("%H:%M")
        updates.append(f"⏱ {t} — {text}")
        _db_conn.execute(
            "UPDATE v5_live SET upd_json=?,last_upd=? WHERE news_key=?",
            (json.dumps(updates), now, key))
        _db_conn.commit()
    # إرسال التحديث للجميع
    formatted = "\n".join(f"  {u}" for u in updates[-5:])
    txt = f"🔴 *{title}* — تحديث مباشر\n\n{formatted}"
    for _uid in list(users.keys()):
        try:
            safe_send_message(_uid, txt, parse_mode="Markdown")
            time.sleep(0.06)
        except Exception as _exc:
            _log_exc(_exc)

# ────────────────────────────────────────────────
# 15. أخبار تختفي (Vanishing News)
# ────────────────────────────────────────────────
def _v5_send_vanishing(title, hours=6):
    """يُرسل خبراً عاجلاً حصرياً يختفي بعد X ساعات."""
    try:
        key     = _v5_news_key(title)
        expires = time.time() + hours * 3600
        with _db_lock:
            _db_conn.execute(
                "INSERT OR REPLACE INTO v5_vanish(news_key,title,expires_at) VALUES(?,?,?)",
                (key, title, expires))
            _db_conn.commit()
        exp_str = _v5_dt.datetime.fromtimestamp(expires).strftime("%H:%M")
        txt = (f"⏳ *خبر حصري — يختفي الساعة {exp_str}*\n\n"
               f"🔴 {title}\n\n"
               f"_هذا الخبر متاح لـ {hours} ساعات فقط_")
        for uid in list(users.keys()):
            try:
                safe_send_message(uid, txt, parse_mode="Markdown")
                time.sleep(0.07)
            except Exception as _exc:
                _log_exc(_exc)
    except Exception as _e:
        _logger.warning(f"vanishing: {_e}")

def _v5_check_vanishing():
    """يُحقق من الأخبار المنتهية ويُشعر الأدمن."""
    try:
        now = time.time()
        with _db_lock:
            expired = _db_conn.execute(
                "SELECT news_key,title FROM v5_vanish WHERE expires_at<=? AND expired=0",
                (now,)).fetchall()
            for key, title in expired:
                _db_conn.execute(
                    "UPDATE v5_vanish SET expired=1 WHERE news_key=?", (key,))
        _db_conn.commit()
    except Exception as _e:
        _logger.warning(f"check_vanishing: {_e}")

# ────────────────────────────────────────────────
# 16. خبر الغد (Tomorrow's Headlines)
# ────────────────────────────────────────────────
def _v5_tomorrow_headlines():
    """AI يتنبأ بأخبار الغد — يُرسل كل ليلة."""
    try:
        today = _v5_dt.date.today().strftime("%d/%m/%Y")
        prompt = (
            f"بناءً على الأحداث الجارية في العراق والمنطقة ({today})،\n"
            f"توقّع 3 أخبار قد تحدث غداً مع شرح قصير لكل منها.\n"
            f"الصيغة:\n1. [العنوان] — [السبب]\n2. ...\n3. ..."
        )
        resp = _v5_ai(prompt) or "تعذّر التنبؤ."
        now  = time.time()
        with _db_lock:
            _db_conn.execute(
                "INSERT INTO v5_tomorrow(prediction,created_at) VALUES(?,?)", (resp, now))
            _db_conn.commit()
        txt = (f"🔮 *توقعات أخبار الغد — {today}*\n\n{resp}\n\n"
               f"_هذه توقعات AI — شاركنا رأيك غداً_")
        for uid in list(users.keys()):
            try:
                safe_send_message(uid, txt, parse_mode="Markdown")
                time.sleep(0.07)
            except Exception as _exc:
                _log_exc(_exc)
    except Exception as _e:
        _logger.warning(f"tomorrow_headlines: {_e}")

# ────────────────────────────────────────────────
# 17. طبخة النوم (Bedtime Edition)
# ────────────────────────────────────────────────
def _v5_bedtime_edition():
    """ملخص إيجابي قبل النوم — 22:00."""
    try:
        prompt = (
            "اذكر 5 أخبار إيجابية أو مشجّعة حدثت في العراق اليوم أو مؤخراً.\n"
            "ركّز على الإنجازات والتطورات الجيدة.\n"
            "كل خبر في سطر مع رمز ✅ أو 🌟 أو 🏆"
        )
        resp = _v5_ai(prompt) or "لم أجد أخباراً إيجابية اليوم — لكن غداً أحسن!"
        txt  = (f"🌙 *طبخة قبل النوم — أخبار تُريح البال*\n\n"
                f"{resp}\n\n_تصبح على خير 🇮🇶_")
        for uid in list(users.keys()):
            try:
                safe_send_message(uid, txt, parse_mode="Markdown")
                time.sleep(0.07)
            except Exception as _exc:
                _log_exc(_exc)
    except Exception as _e:
        _logger.warning(f"bedtime: {_e}")

# ────────────────────────────────────────────────
# 18. لوح الشرف الأسبوعي (Weekly Leaderboard)
# ────────────────────────────────────────────────
def _v5_weekly_leaderboard():
    """يُرسل أسرع 10 قراء كل جمعة."""
    try:
        week_ago = time.time() - 7 * 86400
        with _db_lock:
            rows = _db_conn.execute(
                "SELECT uid,COUNT(*) as cnt FROM v5_reads "
                "WHERE read_at>=? GROUP BY uid ORDER BY cnt DESC LIMIT 10",
                (week_ago,)).fetchall()
        if not rows:
            return
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines  = []
        for i, (uid, cnt) in enumerate(rows):
            name = users.get(uid, {}).get("name", f"مستخدم {uid[:4]}")
            lines.append(f"{medals[i]} {name} — {cnt} خبر")
        txt = ("🏆 *لوح الشرف الأسبوعي — أكثر القراء*\n\n" +
               "\n".join(lines) + "\n\nهل اسمك هنا الأسبوع القادم؟")
        for uid in list(users.keys()):
            try:
                safe_send_message(uid, txt, parse_mode="Markdown")
                time.sleep(0.07)
            except Exception as _exc:
                _log_exc(_exc)
    except Exception as _e:
        _logger.warning(f"leaderboard: {_e}")

# ────────────────────────────────────────────────
# 19. تحدي الأصدقاء (Friend Challenge)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["challenge"])
def _v5_cmd_challenge(msg):
    uid   = str(msg.from_user.id)
    parts = msg.text.split()
    if len(parts) < 2:
        safe_send_message(uid,
            "استخدم: /challenge @username أو /challenge [user_id]")
        return
    target = parts[1].lstrip("@")
    # ابحث عن المستخدم
    target_uid = None
    for u, data in list(users.items()):
        if data.get("username", "").lower() == target.lower() or u == target:
            target_uid = u
            break
    if not target_uid:
        safe_send_message(uid, "❌ لم أجد هذا المستخدم.")
        return
    # ولّد 5 أسئلة
    prompt = (
        "اكتب 5 أسئلة ثقافية عامة عن العراق والمنطقة مع إجابة كل منها.\n"
        "الصيغة:\nس: ...\nج: ...\n"
    )
    def _gen():
        resp = _v5_ai(prompt)
        lines = [l.strip() for l in resp.split("\n") if l.strip()]
        qs = []
        i  = 0
        while i < len(lines) - 1:
            if lines[i].startswith("س:") and lines[i+1].startswith("ج:"):
                qs.append({"q": lines[i][2:].strip(), "a": lines[i+1][2:].strip()})
                i += 2
            else:
                i += 1
        if len(qs) < 3:
            safe_send_message(uid, "❌ تعذّر إنشاء الأسئلة. جرّب لاحقاً.")
            return
        now = time.time()
        with _db_lock:
            _db_conn.execute(
                "INSERT INTO v5_challenges(uid_a,uid_b,questions,created_at) VALUES(?,?,?,?)",
                (uid, target_uid, json.dumps(qs), now))
            cid = _db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            _db_conn.commit()
        name_a = msg.from_user.first_name or "منافسك"
        safe_send_message(uid,
            f"✅ تحدي أُرسل! انتظر نتيجة {target}.")
        markup = _v5_mk([[("⚡ اقبل التحدي", f"v5chal_{cid}_start")]])
        safe_send_message(target_uid,
            f"⚡ *تحدي من {name_a}!*\n\n"
            f"5 أسئلة عن العراق — من يُجيب أكثر يفوز!\n\n"
            f"هل تقبل؟",
            parse_mode="Markdown", reply_markup=markup)
    _AI_EXECUTOR.submit(_gen)

@bot.callback_query_handler(func=lambda c: c.data.startswith("v5chal_"))
def _v5_cb_challenge(call):
    uid   = str(call.from_user.id)
    parts = call.data.split("_")
    cid   = int(parts[1])
    with _db_lock:
        row = _db_conn.execute(
            "SELECT uid_a,uid_b,questions FROM v5_challenges WHERE id=?", (cid,)).fetchone()
    if not row:
        return
    uid_a, uid_b, qjson = row
    qs = json.loads(qjson)
    bot.answer_callback_query(call.id, "⚡ بدأ التحدي!")
    # إرسال أول سؤال
    markup = _v5_mk([[
        ("أ) " + qs[0]["a"][:20], f"v5chalans_{cid}_{uid}_0_0"),
    ]])
    safe_send_message(uid,
        f"⚡ *السؤال 1 من {len(qs)}:*\n\n{qs[0]['q']}\n\n"
        f"⚠️ الميزة: سرعة الإجابة تُحسب!",
        parse_mode="Markdown")

# ────────────────────────────────────────────────
# 20. بطاقة الهوية الإخبارية (My Card)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["mycard", "my_card"])
def _v5_cmd_mycard(msg):
    uid  = str(msg.from_user.id)
    name = msg.from_user.first_name or "مجهول"
    with _db_lock:
        reads = _db_conn.execute(
            "SELECT COUNT(*) FROM v5_reads WHERE uid=?", (uid,)).fetchone()[0]
        tips  = _db_conn.execute(
            "SELECT COUNT(*) FROM v5_tips WHERE uid=? AND status='published'", (uid,)).fetchone()[0]
    iq      = _v5_user_flag(uid, "v5_iq", 50.0)
    badges  = _v5_user_flag(uid, "v5_badges", [])
    streak  = _v5_user_flag(uid, "v5_streak", 0)
    tribe   = _v5_user_flag(uid, "v5_tribe", "none")
    tribe_n = _V5_TRIBES.get(tribe, "غير محدد")
    mode    = _v5_user_flag(uid, "v5_mode", "normal")
    badges_txt = " | ".join(badges) if badges else "لا شارات بعد"
    card = (
        f"┌─────────────────────────┐\n"
        f"│  🇮🇶 IraqNow — بطاقتي   │\n"
        f"├─────────────────────────┤\n"
        f"│  👤 {name[:20]:<20} │\n"
        f"│  📰 الأخبار: {reads:<12} │\n"
        f"│  🧠 IQ الإخباري: {iq:<8} │\n"
        f"│  🔥 سلسلة: {streak} يوم       │\n"
        f"│  🏛 القبيلة: {tribe_n[:12]:<12} │\n"
        f"│  📡 مساهمات منشورة: {tips}  │\n"
        f"├─────────────────────────┤\n"
        f"│  🏅 {badges_txt[:22]:<22} │\n"
        f"└─────────────────────────┘\n"
        f"_شارك بطاقتك وادعُ أصدقاءك!_"
    )
    safe_send_message(uid, f"```\n{card}\n```", parse_mode="Markdown")

# ────────────────────────────────────────────────
# 21. نظام الإحالة (Referral System)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["invite", "ref"])
def _v5_cmd_invite(msg):
    uid  = str(msg.from_user.id)
    link = f"https://t.me/Iraqnowbot?start=ref_{uid}"
    refs = _v5_user_flag(uid, "v5_refs", 0)
    lvl  = _v5_user_flag(uid, "v5_level", 1)
    safe_send_message(uid,
        f"🔗 *رابط دعوتك الشخصي:*\n`{link}`\n\n"
        f"📊 دعوت حتى الآن: *{refs}* شخص\n"
        f"⭐ مستواك: *{lvl}*\n\n"
        f"كل دعوة ترفع مستواك وتفتح ميزات جديدة!",
        parse_mode="Markdown")

def _v5_handle_ref_start(uid, referrer_uid):
    """يُعالج /start ref_XXXX."""
    try:
        if referrer_uid == uid:
            return
        old = _v5_user_flag(referrer_uid, "v5_ref_by_me", {})
        if uid in old:
            return
        old[uid] = time.time()
        _v5_set_flag(referrer_uid, "v5_ref_by_me", old)
        refs = _v5_user_flag(referrer_uid, "v5_refs", 0) + 1
        _v5_set_flag(referrer_uid, "v5_refs", refs)
        # رفع المستوى كل 5 إحالات
        lvl = (refs // 5) + 1
        _v5_set_flag(referrer_uid, "v5_level", lvl)
        safe_send_message(referrer_uid,
            f"🎉 انضم شخص جديد بدعوتك!\n"
            f"إجمالي إحالاتك: {refs}\n"
            f"مستواك الحالي: ⭐ {lvl}")
    except Exception as _e:
        _logger.warning(f"ref_start: {_e}")

# ────────────────────────────────────────────────
# 22. النمط الوقت المثالي (Perfect Timing AI)
# ────────────────────────────────────────────────
def _v5_track_activity(uid):
    """يسجّل وقت نشاط المستخدم."""
    try:
        hour = _v5_dt.datetime.now().hour
        acts = _v5_user_flag(uid, "v5_hours", {})
        acts[str(hour)] = acts.get(str(hour), 0) + 1
        _v5_set_flag(uid, "v5_hours", acts)
        # احسب الوقت المثالي
        if sum(acts.values()) >= 10:
            best = max(acts, key=lambda h: acts[h])
            _v5_set_flag(uid, "v5_opt_hour", int(best))
    except Exception as _exc:
        _log_exc(_exc)

def _v5_is_optimal_time(uid) -> bool:
    """صح إذا الوقت الحالي قريب من الوقت المثالي للمستخدم."""
    opt = _v5_user_flag(uid, "v5_opt_hour", None)
    if opt is None:
        return True  # لا بيانات → أرسل دائماً
    cur = _v5_dt.datetime.now().hour
    return abs(cur - opt) <= 1 or abs(cur - opt) >= 23

# ────────────────────────────────────────────────
# 23. الختم الأسبوعي (Weekly Seal)
# ────────────────────────────────────────────────
_V5_SEALS = {
    7:  "🔵 ختم المراقب",
    14: "🟢 ختم المتابع",
    30: "🟡 ختم المحلل",
    60: "🟠 ختم الخبير",
    90: "🔴 ختم المرجع",
}

def _v5_update_streak(uid):
    """يُحدّث سلسلة القراءة اليومية ويمنح الختم إذا استحق."""
    try:
        today    = _v5_dt.date.today().isoformat()
        last     = _v5_user_flag(uid, "v5_last_day", "")
        streak   = _v5_user_flag(uid, "v5_streak", 0)
        yesterday = (_v5_dt.date.today() - _v5_dt.timedelta(days=1)).isoformat()
        if last == today:
            return
        if last == yesterday:
            streak += 1
        else:
            streak = 1
        _v5_set_flag(uid, "v5_streak", streak)
        _v5_set_flag(uid, "v5_last_day", today)
        # منح الختم
        for days, seal in sorted(_V5_SEALS.items()):
            if streak == days:
                badges = _v5_user_flag(uid, "v5_badges", [])
                if seal not in badges:
                    badges.append(seal)
                    _v5_set_flag(uid, "v5_badges", badges)
                    safe_send_message(uid,
                        f"🎖 *مبروك! حصلتَ على ختم جديد:*\n{seal}\n\n"
                        f"قرأتَ الأخبار {days} يوماً متواصلاً! 🔥",
                        parse_mode="Markdown")
    except Exception as _e:
        _logger.warning(f"streak: {_e}")

# ────────────────────────────────────────────────
# 24. معيار الذكاء الإخباري (News IQ)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["iq", "newsiq"])
def _v5_cmd_iq(msg):
    uid = str(msg.from_user.id)
    iq  = _v5_user_flag(uid, "v5_iq", 50.0)
    with _db_lock:
        reads = _db_conn.execute(
            "SELECT COUNT(*) FROM v5_reads WHERE uid=?", (uid,)).fetchone()[0]
    tips_ok = sum(1 for u, d in users.items()
                  if u == uid and d.get("v5_badges") and "مراسل ميداني 📡" in d.get("v5_badges", []))
    bar = "█" * int(iq // 10) + "░" * (10 - int(iq // 10))
    rank = "مبتدئ" if iq < 60 else "متوسط" if iq < 75 else "متقدم" if iq < 90 else "خبير"
    safe_send_message(uid,
        f"🧠 *ذكاؤك الإخباري*\n\n"
        f"[{bar}] {iq}/100\n"
        f"الرتبة: *{rank}*\n\n"
        f"📰 إجمالي القراءات: {reads}\n"
        f"🎯 ترفع IQ عبر:\n"
        f"  • الإجابة الصحيحة في ساعة الحقيقة +1\n"
        f"  • تنبؤ صحيح +1.5\n"
        f"  • قراءة متواصلة +0.5/يوم",
        parse_mode="Markdown")

# ────────────────────────────────────────────────
# 25. وضع الأطفال (Kids Mode)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["kids"])
def _v5_cmd_kids(msg):
    uid   = str(msg.from_user.id)
    parts = msg.text.split(None, 1)
    if len(parts) < 2:
        safe_send_message(uid,
            "👶 أرسل عنوان الخبر وسأشرحه لطفل عمره 10 سنوات:\n\n/kids [عنوان الخبر]")
        return
    title = parts[1]
    safe_send_message(uid, "⏳ أُعيد الصياغة بأسلوب الأطفال...")
    def _gen():
        prompt = (
            f"اشرح هذا الخبر بأسلوب بسيط جداً يفهمه طفل عمره 10 سنوات:\n{title}\n\n"
            f"استخدم كلمات بسيطة وأمثلة من الحياة اليومية. لا سياسة معقدة."
        )
        resp = _v5_ai(prompt) or title
        safe_send_message(uid,
            f"👶 *شرح للأطفال:*\n\n{resp}",
            parse_mode="Markdown")
    _AI_EXECUTOR.submit(_gen)

# ────────────────────────────────────────────────
# 26. الخبر المعكوس (Reverse News)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["reverse"])
def _v5_cmd_reverse(msg):
    uid   = str(msg.from_user.id)
    parts = msg.text.split(None, 1)
    if len(parts) < 2:
        safe_send_message(uid, "استخدم: /reverse [عنوان الخبر]")
        return
    title = parts[1]
    def _gen():
        prompt = (
            f"للخبر: {title}\n\n"
            f"أجب على: ما الذي يجب أن يكون صحيحاً حتى لا يكون هذا الخبر مهماً؟\n"
            f"ثم: من يستفيد من نشر هذا الخبر؟\n"
            f"ثم: ما المعلومة الغائبة؟\n"
            f"بإيجاز وعمق."
        )
        resp = _v5_ai(prompt) or "تعذّر التحليل."
        safe_send_message(uid,
            f"🔄 *الخبر المعكوس — تفكير نقدي:*\n\n{resp}",
            parse_mode="Markdown")
    _AI_EXECUTOR.submit(_gen)

# ────────────────────────────────────────────────
# 27. "ما لم يُقَل" (Untold Story)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["untold"])
def _v5_cmd_untold(msg):
    uid   = str(msg.from_user.id)
    parts = msg.text.split(None, 1)
    if len(parts) < 2:
        safe_send_message(uid, "استخدم: /untold [عنوان الخبر]")
        return
    title = parts[1]
    def _gen():
        prompt = (
            f"للخبر: {title}\n\n"
            f"اكشف الزاوية التي أغفلتها وسائل الإعلام في 3 نقاط:\n"
            f"1. السياق الغائب\n2. التأثير غير المرئي\n3. السؤال الذي لم يُطرح"
        )
        resp = _v5_ai(prompt) or "تعذّر استخراج الزاوية الغائبة."
        safe_send_message(uid,
            f"🕵️ *ما لم يُقَل عن هذا الخبر:*\n\n{resp}",
            parse_mode="Markdown")
    _AI_EXECUTOR.submit(_gen)

# ────────────────────────────────────────────────
# 28. التعلم الخفي (Stealth Learning)
# ────────────────────────────────────────────────
_V5_CONCEPTS = {
    "دولار": "💡 الدولار عملة الاحتياطي العالمي — ارتفاعه يرفع تكلفة الاستيراد.",
    "تضخم": "💡 التضخم = انخفاض القوة الشرائية — إذا ارتفع بـ10% فسعر البضاعة يرتفع بـ10%.",
    "ناتج محلي": "💡 الناتج المحلي الإجمالي = مجموع ما ينتجه البلد — يقيس حجم الاقتصاد.",
    "فيتو": "💡 الفيتو = حق النقض — يمنح مجلس الأمن صلاحية إلغاء أي قرار.",
    "ميليشيا": "💡 الميليشيا = قوة مسلحة خارج الجيش الرسمي — غير خاضعة لسلطة الدولة.",
    "برلمان": "💡 البرلمان = مجلس النواب — يُشرّع القوانين ويراقب الحكومة.",
    "مركزي": "💡 البنك المركزي = بنك الحكومة — يتحكم بالنقد والفائدة والتضخم.",
}

def _v5_stealth_concept(title: str) -> str:
    """يُعيد مفهوماً تعليمياً إذا وُجد في العنوان."""
    for kw, concept in _V5_CONCEPTS.items():
        if kw in title:
            return concept
    return ""

# ────────────────────────────────────────────────
# 29. أوامر الوضع المخصصة (Busy / Wave / Analyst)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["busy"])
def _v5_cmd_busy(msg):
    uid = str(msg.from_user.id)
    _v5_set_flag(uid, "v5_mode", "busy")
    safe_send_message(uid, "⚡ *وضع المشغول مُفعَّل*\nستصلك الأخبار بـ 8 كلمات فقط.",
                      parse_mode="Markdown")

@bot.message_handler(commands=["wave"])
def _v5_cmd_wave(msg):
    uid = str(msg.from_user.id)
    _v5_set_flag(uid, "v5_mode", "wave")
    safe_send_message(uid, "🌊 *وضع الموجة مُفعَّل*\nستصلك موجة يومية واحدة منظمة.",
                      parse_mode="Markdown")

@bot.message_handler(commands=["analyst"])
def _v5_cmd_analyst(msg):
    uid = str(msg.from_user.id)
    _v5_set_flag(uid, "v5_mode", "analyst")
    safe_send_message(uid, "🧠 *وضع المحلل مُفعَّل*\nكل خبر يأتيك مع 3 أسئلة تحليلية.",
                      parse_mode="Markdown")

@bot.message_handler(commands=["normal"])
def _v5_cmd_normal(msg):
    uid = str(msg.from_user.id)
    _v5_set_flag(uid, "v5_mode", "normal")
    safe_send_message(uid, "📰 *الوضع العادي*\nالأخبار كالمعتاد.",
                      parse_mode="Markdown")

# ────────────────────────────────────────────────
# 30. دعوة مخصصة لمستخدم (Wave Digest)
# ────────────────────────────────────────────────
_V5_WAVE_QUEUE = {}  # uid -> [titles]

def _v5_queue_for_wave(uid, title):
    """يُضيف الخبر لقائمة انتظار موجة المستخدم."""
    if uid not in _V5_WAVE_QUEUE:
        _V5_WAVE_QUEUE[uid] = []
    _V5_WAVE_QUEUE[uid].append(title)

def _v5_send_wave_digests():
    """يُرسل الموجة اليومية لمستخدمي وضع wave."""
    try:
        for uid, titles in list(_V5_WAVE_QUEUE.items()):
            mode = _v5_user_flag(uid, "v5_mode", "normal")
            if mode != "wave" or not titles:
                continue
            today = _v5_dt.date.today().strftime("%d/%m/%Y")
            lines = "\n".join(f"• {t}" for t in titles[-20:])
            safe_send_message(uid,
                f"🌊 *موجة أخبار {today}*\n\n{lines}\n\n"
                f"_إجمالي أخبار اليوم: {len(titles)}_",
                parse_mode="Markdown")
            _V5_WAVE_QUEUE[uid] = []
    except Exception as _e:
        _logger.warning(f"wave_digest: {_e}")

# ────────────────────────────────────────────────
# 31. مساعد الأوامر (Help v5)
# ────────────────────────────────────────────────
@bot.message_handler(commands=["features", "v5help"])
def _v5_cmd_help(msg):
    uid = str(msg.from_user.id)
    safe_send_message(uid,
        "🚀 *مميزات IraqNow المتقدمة:*\n\n"
        "🎛 *أوضاع الاستقبال:*\n"
        "/mode — اختر طريقة استقبال الأخبار\n"
        "/busy — وضع 8 كلمات فقط\n"
        "/wave — موجة يومية واحدة\n"
        "/analyst — مع أسئلة تحليلية\n\n"
        "🏛 *الهوية والانتماء:*\n"
        "/tribe — اختر قبيلتك الإخبارية\n"
        "/mycard — بطاقة هويتك الإخبارية\n"
        "/iq — ذكاؤك الإخباري\n\n"
        "🎮 *تفاعل وترفيه:*\n"
        "/debate [موضوع] — نقاش الحجج\n"
        "/kids [خبر] — شرح للأطفال\n"
        "/reverse [خبر] — تفكير نقدي عكسي\n"
        "/untold [خبر] — ما لم يُقَل\n\n"
        "🕰 *الزمن والذاكرة:*\n"
        "/capsule — اكتب للمستقبل\n"
        "/today5y — أخبار اليوم قبل 5 سنوات\n"
        "/today3y — قبل 3 سنوات\n"
        "/today1y — قبل سنة\n\n"
        "📡 *المساهمة:*\n"
        "/tip — أرسل خبراً من الشارع\n"
        "/arc — القضايا المتسلسلة\n"
        "/invite — ادعُ أصدقاءك\n"
        "/challenge @user — تحدّ صديقك",
        parse_mode="Markdown")

# ────────────────────────────────────────────────
# 32. جدولة المهام (Scheduler Jobs v5)
# ────────────────────────────────────────────────
def _v5_scheduler():
    """المجدول الرئيسي لميزات v5."""
    import random as _rnd
    while True:
        try:
            now  = _v5_dt.datetime.now()
            hour = now.hour
            minute = now.minute

            # ساعة الحقيقة — 12 ظهراً
            if hour == 12 and minute == 0:
                _v5_send_truth_hour()

            # نبضة الشارع — 5 مساءً
            if hour == 17 and minute == 0:
                _v5_send_street_pulse()

            # طبخة النوم — 10 مساءً
            if hour == 22 and minute == 0:
                _v5_bedtime_edition()

            # خبر الغد — 11 مساءً
            if hour == 23 and minute == 0:
                _v5_tomorrow_headlines()

            # لوح الشرف — جمعة 8 مساءً
            if now.weekday() == 4 and hour == 20 and minute == 0:
                _v5_weekly_leaderboard()

            # تحليل التنبؤات — كل ساعة
            if minute == 30:
                _v5_resolve_predictions()

            # كبسولات زمنية — منتصف الليل
            if hour == 0 and minute == 0:
                _v5_check_capsules()

            # موجة الأخبار — 8 صباح و8 مساء
            if (hour == 8 or hour == 20) and minute == 0:
                _v5_send_wave_digests()

            # تنظيف الأخبار المنتهية — كل 30 دقيقة
            if minute in (0, 30):
                _v5_check_vanishing()

        except Exception as _e:
            _logger.warning(f"v5_scheduler error: {_e}")
        time.sleep(60)

_v5_threading.Thread(target=_v5_scheduler, daemon=True, name="v5-sched").start()
_logger.info("🚀 v5 scheduler started — 40+ features active")

# ────────────────────────────────────────────────
# 33. تعديل /start لمعالجة الإحالات
# ────────────────────────────────────────────────
_V5_ORIG_START = None
for _hndlr in bot.message_handlers:
    if hasattr(_hndlr, "filters") and _hndlr.filters.get("commands") == ["start"]:
        _V5_ORIG_START = _hndlr.function
        break

if _V5_ORIG_START:
    bot.message_handlers = [h for h in bot.message_handlers
                              if not (hasattr(h, "filters")
                                      and h.filters.get("commands") == ["start"])]

    @bot.message_handler(commands=["start"])
    def _v5_start_wrapper(msg):
        uid  = str(msg.from_user.id)
        text = msg.text or ""
        # تتبع النشاط
        _v5_track_activity(uid)
        _v5_update_streak(uid)
        # معالجة الإحالة
        if "ref_" in text:
            try:
                ref_uid = text.split("ref_")[1].strip()
                _v5_handle_ref_start(uid, ref_uid)
            except Exception as _exc:
                _log_exc(_exc)
        if _V5_ORIG_START:
            _V5_ORIG_START(msg)

_logger.info("✅ v5 features block loaded successfully")
# ═══════════════════════════════════════════════════════════════════════════
# END PATCH v5
# ═══════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════
# PATCH v6 — 365score-style Match Detail System
# ═══════════════════════════════════════════════════════════════════════════

def _get_match_full_detail(espn_slug: str, event_id: str) -> dict:
    """يجلب تفاصيل المباراة الكاملة: أحداث + إحصائيات + تشكيلة"""
    try:
        sport, league_slug = espn_slug.split('/', 1)
        url = (f"https://site.api.espn.com/apis/site/v2/sports"
               f"/{sport}/{league_slug}/summary?event={event_id}")
        r = requests.get(url, timeout=12,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return {}
        data = r.json()
        result = {
            'event_id': event_id, 'sport': sport, 'espn_slug': espn_slug,
            'home': '?', 'away': '?', 'home_id': '', 'away_id': '',
            'home_score': '-', 'away_score': '-',
            'state': 'pre', 'clock': '', 'period_text': '', 'venue': '',
            'events': [], 'stats': {}, 'stats_names': [],
            'lineup_home': [], 'lineup_away': [],
            'lineup_home_subs': [], 'lineup_away_subs': [],
        }
        comp = (data.get('header', {}).get('competitions', [{}]))[0]
        for c in comp.get('competitors', []):
            side = 'home' if c.get('homeAway') == 'home' else 'away'
            result[side]            = c.get('team', {}).get('displayName', '?')
            result[f'{side}_score'] = c.get('score', '-')
            result[f'{side}_id']    = str(c.get('team', {}).get('id', ''))
        status  = comp.get('status', {})
        st_type = status.get('type', {})
        result['state']       = st_type.get('state', 'pre')
        result['clock']       = status.get('displayClock', '')
        result['period_text'] = st_type.get('shortDetail', '')
        result['venue']       = comp.get('venue', {}).get('fullName', '')

        IMPORTANT = {
            'football':   ['goal', 'score', 'red card', 'yellow card',
                           'penalty', 'substitut', 'own goal', 'var', 'injury time'],
            'basketball': ['made', '3-pt', 'free throw', 'timeout', 'end of period'],
            'tennis':     ['set', 'ace', 'break point'],
            'racing':     ['pit stop', 'overtake', 'crash', 'safety car',
                           'fastest lap', 'retire'],
        }
        imp_keys = IMPORTANT.get(sport, [])

        for play in data.get('plays', []):
            pt_obj = play.get('type', {})
            ptype  = (pt_obj.get('text', '') or pt_obj.get('name', '')).lower()
            if sport == 'football' and not any(k in ptype for k in imp_keys):
                continue
            clock_obj = play.get('clock', {})
            clock     = (clock_obj.get('displayValue', '')
                         if isinstance(clock_obj, dict) else str(clock_obj))
            period    = play.get('period', {})
            period_n  = (period.get('number', 0)
                         if isinstance(period, dict) else period)
            parts_p   = play.get('participants', [])
            player = team_id = ''
            if parts_p:
                a       = parts_p[0].get('athlete', {})
                player  = a.get('displayName', a.get('shortName', ''))
                team_id = str(parts_p[0].get('team', {}).get('id', ''))
            result['events'].append({
                'type': ptype, 'clock': clock, 'period': period_n,
                'player': player, 'team_id': team_id,
                'home_score': str(play.get('homeScore', '')),
                'away_score': str(play.get('awayScore', '')),
                'text': play.get('text', ''),
            })

        boxscore = data.get('boxscore', {})
        for ts in boxscore.get('teams', []):
            tid  = str(ts.get('team', {}).get('id', ''))
            side = 'home' if tid == result['home_id'] else 'away'
            stats = {}
            for s in ts.get('statistics', []):
                n = s.get('name', '')
                v = s.get('displayValue', s.get('value', ''))
                stats[n] = str(v)
            result['stats'][side] = stats

        for team_pl in boxscore.get('players', []):
            tid  = str(team_pl.get('team', {}).get('id', ''))
            side = 'home' if tid == result['home_id'] else 'away'
            starters, subs = [], []
            for cat in team_pl.get('statistics', []):
                for ath in cat.get('athletes', []):
                    ai    = ath.get('athlete', {})
                    nm    = ai.get('displayName', ai.get('shortName', ''))
                    pos   = ai.get('position', {})
                    pos_a = (pos.get('abbreviation', '')
                             if isinstance(pos, dict) else str(pos))
                    entry = f"{nm}({pos_a})" if pos_a else nm
                    if ath.get('starter', False):
                        starters.append(entry)
                    else:
                        subs.append(entry)
            result[f'lineup_{side}']      = starters[:11]
            result[f'lineup_{side}_subs'] = subs[:7]
        return result
    except Exception as _e:
        _logger.warning(f"get_match_full_detail: {_e}")
        return {}


def _format_match_365(detail: dict) -> str:
    """يُنسّق تفاصيل المباراة بأسلوب 365score"""
    sport = detail.get('sport', 'football')
    home  = detail.get('home', '?')
    away  = detail.get('away', '?')
    hs    = detail.get('home_score', '-')
    as_   = detail.get('away_score', '-')
    state = detail.get('state', 'pre')
    clock = detail.get('clock', '')
    ptext = detail.get('period_text', '')
    venue = detail.get('venue', '')
    SEP   = "━━━━━━━━━━━━━━━━━━━━"

    if state == 'in':
        icon  = "🔴 *مباشر الآن*"
        score = f"🏠 *{home}*   `{hs} — {as_}`   *{away}* ✈️"
        tim   = f"⏱ {clock}" + (f"   |   {ptext}" if ptext else "")
    elif state == 'post':
        icon  = "✅ *المباراة انتهت*"
        score = f"🏠 *{home}*   `{hs} — {as_}`   *{away}* ✈️"
        tim   = ptext or "انتهت المباراة"
    else:
        icon  = "🕐 *لم تبدأ بعد*"
        score = f"🏠 *{home}*   vs   *{away}* ✈️"
        tim   = ptext or ""

    text = f"{icon}\n{SEP}\n{score}\n{tim}"
    if venue:
        text += f"\n🏟 {venue}"

    events  = detail.get('events', [])
    home_id = detail.get('home_id', '')
    if events:
        text += f"\n{SEP}\n📋 *الأحداث الرئيسية:*\n"
        for ev in events:
            emoji   = _event_to_emoji(ev['type'], sport)
            clk     = ev.get('clock', '')
            player  = ev.get('player', '')
            hs_ev   = ev.get('home_score', '')
            as_ev   = ev.get('away_score', '')
            score_s = f" `{hs_ev}-{as_ev}`" if hs_ev and as_ev else ""
            is_home = (ev.get('team_id') == home_id)
            team_lb = home[:10] if is_home else away[:10]
            pl_txt  = f" *{player}*" if player else ""
            text   += f"  {emoji} `{clk}` {team_lb}{pl_txt}{score_s}\n"

    stats   = detail.get('stats', {})
    hs_st   = stats.get('home', {})
    as_st   = stats.get('away', {})
    STAT_LBL = {
        'possessionPct':    '🔵 الاستحواذ',
        'totalShots':       '🎯 التسديدات',
        'shotsOnTarget':    '⚡ على المرمى',
        'saves':            '🧤 التصديات',
        'fouls':            '⚠️ الأخطاء',
        'corners':          '🔄 الزوايا',
        'offsides':         '🚩 تسلل',
        'yellowCards':      '🟨 بطاقات صفراء',
        'redCards':         '🟥 بطاقات حمراء',
        'passes':           '🎽 التمريرات',
        'passAccuracy':     '✅ دقة التمرير',
        'threePointers':    '3️⃣ ثلاثيات',
        'rebounds':         '🔃 ارتداد',
        'assists':          '🤝 تمريرات حاسمة',
        'steals':           '🤚 استحواذ',
        'blocks':           '🛡️ تصديات',
    }
    if hs_st or as_st:
        text += f"\n{SEP}\n📊 *الإحصائيات:*\n"
        text += f"  {'الإحصاء':<18} {home[:8]:^12} {away[:8]:^12}\n"
        shown = 0
        for key, lbl in STAT_LBL.items():
            hv = hs_st.get(key, '')
            av = as_st.get(key, '')
            if not hv and not av:
                continue
            text += f"  {lbl:<18} {str(hv):^12} {str(av):^12}\n"
            shown += 1
            if shown >= 10:
                break

    lh   = detail.get('lineup_home', [])
    la   = detail.get('lineup_away', [])
    lhs  = detail.get('lineup_home_subs', [])
    las  = detail.get('lineup_away_subs', [])
    if lh:
        text += f"\n{SEP}\n👕 *تشكيلة {home}:*\n"
        text += "  " + " • ".join(lh[:11]) + "\n"
        if lhs:
            text += f"  🔄 *بدلاء:* " + " • ".join(lhs[:5]) + "\n"
    if la:
        text += f"\n👕 *تشكيلة {away}:*\n"
        text += "  " + " • ".join(la[:11]) + "\n"
        if las:
            text += f"  🔄 *بدلاء:* " + " • ".join(las[:5]) + "\n"

    return text[:4096]


def _get_live_matches_with_ids(espn_slug: str) -> list:
    """يجلب المباريات مع event_id لكل مباراة"""
    try:
        sport, league_slug = espn_slug.split('/', 1)
        url = (f"https://site.api.espn.com/apis/site/v2/sports"
               f"/{sport}/{league_slug}/scoreboard")
        r = requests.get(url, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        results = []
        for ev in r.json().get('events', []):
            event_id = str(ev.get('id', ''))
            comp     = ev.get('competitions', [{}])[0]
            status   = comp.get('status', {})
            st_type  = status.get('type', {})
            state    = st_type.get('state', 'pre')
            home_t = away_t = ''
            home_s = away_s = '-'
            for c in comp.get('competitors', []):
                if c.get('homeAway') == 'home':
                    home_t = c.get('team', {}).get('displayName', '?')
                    home_s = c.get('score', '-')
                else:
                    away_t = c.get('team', {}).get('displayName', '?')
                    away_s = c.get('score', '-')
            results.append({
                'id': event_id, 'home': home_t, 'away': away_t,
                'home_score': home_s, 'away_score': away_s,
                'state': state, 'clock': status.get('displayClock', ''),
                'date': comp.get('date', ''),
            })
        return results
    except Exception:
        return []


def _send_live_scores_365(uid, chat_id, msg_id=None):
    """النتائج المباشرة بأسلوب 365score مع أزرار تفاصيل كل مباراة"""
    prefs     = _get_user_sports(uid)
    selected  = prefs.get('leagues', [])
    tz_offset = _get_user_tz_offset(uid)

    if not selected:
        text = ("🔴 *النتائج المباشرة*\n\n"
                "لم تختر أي دوري بعد.\n"
                "اضغط /sports ثم اختر رياضتك.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🏅 اختر دورياتك", callback_data="sp_sports"))
        try:
            if msg_id:
                bot.edit_message_text(text, chat_id, msg_id,
                                      parse_mode="Markdown", reply_markup=kb)
            else:
                bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb)
        return

    text = "🔴 *النتائج المباشرة*\n\n"
    match_buttons = []

    for key in selected:
        league = SPORTS_LEAGUES.get(key)
        if not league:
            continue
        sport = league.get('sport', 'football')
        if not league.get('espn') and not league.get('scores365_id'):
            text += f"{league['flag']} *{league['name']}*\n  ⚠️ غير متاح\n\n"
            continue
        if league.get('espn'):
            matches = _get_live_matches_with_ids(league['espn'])
        else:
            matches = _get_365scores_matches(league['scores365_id'])
        live    = [m for m in matches if m['state'] == 'in']
        recent  = [m for m in matches if m['state'] == 'post'][:2]
        display = live or recent
        if not display:
            continue
        text += f"\n{league['flag']} *{league['name']}*\n"
        for m in display:
            text += f"  {_format_match_line(m, sport, tz_offset)}\n"
            # أزرار التفاصيل متاحة فقط لدوريات ESPN
            if m.get('id') and m['state'] in ('in', 'post') and league.get('espn'):
                eid  = m['id']
                enc  = league['espn'].replace('/', '_', 1)
                lbl  = f"🔍 {m['home'][:10]} vs {m['away'][:10]}"
                match_buttons.append(
                    types.InlineKeyboardButton(lbl,
                        callback_data=f"sp_m_{enc}_{eid}")
                )

    kb = types.InlineKeyboardMarkup(row_width=1)
    for btn in match_buttons[:10]:
        kb.add(btn)
    kb.row(
        types.InlineKeyboardButton("🔄 تحديث", callback_data="sp_live"),
        types.InlineKeyboardButton("📅 الجدول", callback_data="sp_schedule"),
    )
    kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_main"))
    try:
        if msg_id:
            bot.edit_message_text(text[:4096], chat_id, msg_id,
                                  parse_mode="Markdown", reply_markup=kb)
        else:
            bot.send_message(chat_id, text[:4096],
                             parse_mode="Markdown", reply_markup=kb)
    except Exception:
        try:
            bot.send_message(chat_id, text[:4096],
                             parse_mode="Markdown", reply_markup=kb)
        except Exception as _exc:
            _log_exc(_exc)


# ── نظام التحديث التلقائي للنتائج المباشرة ──────────────────────
# يخزّن: uid → (chat_id, msg_id, timestamp_last_refresh)
_live_score_viewers: dict = {}
_live_score_viewers_lock = threading.Lock()

def _register_live_viewer(uid, chat_id, msg_id):
    """يسجّل المستخدم كمشاهد نشط للنتائج المباشرة."""
    with _live_score_viewers_lock:
        _live_score_viewers[str(uid)] = (chat_id, msg_id, time.time())

def _unregister_live_viewer(uid):
    with _live_score_viewers_lock:
        _live_score_viewers.pop(str(uid), None)

def _auto_refresh_live_scores():
    """يُحدّث رسائل النتائج المباشرة كل 10 ثواني تلقائياً."""
    with _live_score_viewers_lock:
        viewers = dict(_live_score_viewers)
    for uid_s, (chat_id, msg_id, last_ts) in list(viewers.items()):
        # إزالة المشاهدين الذين مضى على آخر تسجيل أكثر من 90 دقيقة
        if time.time() - last_ts > 90 * 60:
            _unregister_live_viewer(uid_s)
            continue
        try:
            _send_live_scores_365(int(uid_s), chat_id, msg_id)
            # تحديث الـ timestamp
            with _live_score_viewers_lock:
                if uid_s in _live_score_viewers:
                    _live_score_viewers[uid_s] = (chat_id, msg_id, last_ts)
        except Exception as _exc:
            _log_exc(_exc)

# ── Override: _send_live_scores → النسخة المحسّنة ───────────────
_send_live_scores = _send_live_scores_365


@bot.callback_query_handler(func=lambda c: c.data.startswith("sp_m_"))
def cb_match_detail_365(call):
    """تفاصيل مباراة واحدة بأسلوب 365score"""
    raw   = call.data[5:]           # بعد "sp_m_"
    # آخر جزء هو event_id (رقم) — ما قبله هو enc_slug
    parts = raw.rsplit("_", 1)
    if len(parts) < 2 or not parts[1].isdigit():
        bot.answer_callback_query(call.id, "❌ بيانات خاطئة")
        return
    enc_slug, event_id = parts
    espn_slug = enc_slug.replace("_", "/", 1)
    uid = call.from_user.id

    bot.answer_callback_query(call.id, "⏳ جاري تحميل تفاصيل المباراة...")

    def _fetch_and_show(_uid=uid, _chat=call.message.chat.id):
        detail = _get_match_full_detail(espn_slug, event_id)
        if not detail:
            try:
                bot.send_message(_chat, "❌ تعذّر جلب تفاصيل المباراة. حاول لاحقاً.")
            except Exception as _exc:
                _log_exc(_exc)
            return
        text = _format_match_365(detail)
        enc  = espn_slug.replace('/', '_', 1)
        kb   = types.InlineKeyboardMarkup(row_width=2)
        kb.row(
            types.InlineKeyboardButton("🔄 تحديث", callback_data=f"sp_m_{enc}_{event_id}"),
            types.InlineKeyboardButton("🔙 رجوع", callback_data="sp_live"),
        )
        try:
            bot.send_message(_chat, text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            try:
                bot.send_message(_chat,
                                 text.replace("*","").replace("`",""),
                                 reply_markup=kb)
            except Exception as _exc:
                _log_exc(_exc)

    _AI_EXECUTOR.submit(_fetch_and_show)


# ─── إعادة تعريف sp_live لاستخدام النظام الجديد ──────────────────
@bot.callback_query_handler(func=lambda c: c.data == "sp_live_365")
def _dummy_live_365(call):
    pass  # placeholder — sp_live الأصلي سيستخدم _send_live_scores المُحدَّث

# ── تسجيل job التحديث التلقائي للنتائج المباشرة ─────────────────
try:
    _sched_ref = globals().get('scheduler')
    if _sched_ref is not None:
        _sched_ref.add_job(
            _safe_job(_auto_refresh_live_scores),
            'interval', seconds=10,
            id="auto_refresh_live_scores_job",
            replace_existing=True, max_instances=1
        )
        _logger.info("✅ auto_refresh_live_scores_job مُسجَّل — يعمل كل 10 ثواني")
except Exception as _arc_exc:
    _log_exc(_arc_exc)

# ── END PATCH v6 ─────────────────────────────────────────────────
