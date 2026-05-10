# -*- coding: utf-8 -*-
"""
db.py — كل ما يتعلق بقاعدة بيانات SQLite (مستخرج فعلياً من bot_legacy.py)

يحتوي على:
- _init_db: إنشاء الجداول وضبط WAL
- _heroku_auto_restore_on_startup: استعادة من قناة البكاب
- جداول: users_store, channels_store, dead_users, broadcast_checkpoint, button_cache
- دوال load/save للمستخدمين والقنوات والأزرار
- ترحيل من JSON القديم
"""

import os, sys, json, sqlite3, threading, datetime, time, base64, tempfile

# نستورد من bot_legacy الأشياء التي تحتاجها هذه الوحدة
# في وقت تحميل هذه الوحدة، bot_legacy يكون محمَّلاً جزئياً (حتى السطر الذي
# استورد من db) — لكن جميع الأسماء التالية مُعرَّفة قبل ذلك السطر:
import bot_legacy as _legacy
_logger           = _legacy._logger
_log_exc          = _legacy._log_exc
bot               = _legacy.bot
ADMIN_ID          = _legacy.ADMIN_ID
BACKUP_CHANNEL_ID = _legacy.BACKUP_CHANNEL_ID
# FIX B3: BACKUP_STATE_MSG_ID كان يُستخدم في _heroku_auto_restore_on_startup دون
# أن يُستورد → NameError فوري يُوقف الاستعادة التلقائية دائماً بصمت.
BACKUP_STATE_MSG_ID = getattr(_legacy, "BACKUP_STATE_MSG_ID", 0)

  # ════════════════════════════════════════════════════════════════════
  # FIX: استيراد _FF من bot_legacy (يستخدم في _bc_save_checkpoint)
  # ════════════════════════════════════════════════════════════════════
_FF = getattr(_legacy, "_FF", {})
  # ════════════════════════════════════════════════════════════════════

  

# ════════════════════════════════════════════════════════════════════
# الكود المُستخرَج فعلياً من bot_legacy.py (الأسطر 5287–5733 الأصلية)
# ════════════════════════════════════════════════════════════════════

def _export_all_to(target_globals):
    """ينسخ كل الأسماء (حتى التي تبدأ بـ _) إلى namespace المستدعي."""
    for _k, _v in list(globals().items()):
        if _k.startswith('__'):
            continue
        target_globals[_k] = _v

# ======== SQLite للمستخدمين ========
DB_FILE = "bot_data.db"
_db_lock = threading.Lock()

# FIX: fallback — بعض الدوال تحتاج هذا الثابت حتى لا تنكسر بـ NameError
_USER_SENT_TTL = 6 * 3600   # FIX C2: 6 ساعات — يجب أن يتطابق مع bot_legacy؛ وإلا _export_all_to يُعيد كتابة القيمة الصحيحة بـ 2h

def _init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    # HEROKU FIX v4: WAL mode — prevents "database is locked" under concurrent load
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # faster, still safe with WAL
    conn.execute("PRAGMA cache_size=-32000")    # 32 MB page cache
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

# ═══════════════════════════════════════════════════════════════════════
# HEROKU AUTO-RESTORE
# ═══════════════════════════════════════════════════════════════════════
def _heroku_auto_restore_on_startup():
    """
    هيروكو يمسح كل الملفات عند كل إعادة تشغيل.
    هذه الدالة تستعيد آخر نسخة احتياطية من تيليغرام قبل فتح قاعدة البيانات.
    """
    if not BACKUP_CHANNEL_ID or not BACKUP_STATE_MSG_ID:
        _logger.info("⏭ الاستعادة التلقائية: BACKUP_CHANNEL_ID أو BACKUP_STATE_MSG_ID غير مُعيَّن — تخطي")
        return
    _logger.info("🔄 هيروكو: جاري استعادة البيانات من تيليغرام (msg_id=%d)...", BACKUP_STATE_MSG_ID)
    try:
        import json as _jr, zipfile as _zf, io as _ior
        try:
            fwd = bot.forward_message(
                chat_id=ADMIN_ID,
                from_chat_id=BACKUP_CHANNEL_ID,
                message_id=BACKUP_STATE_MSG_ID
            )
        except Exception as _e:
            _logger.warning("⚠️ فشل جلب رسالة الحالة: %s", _e)
            return
        state_text = fwd.text or fwd.caption or ""
        try:
            bot.delete_message(ADMIN_ID, fwd.message_id)
        except Exception:
            pass
        if not state_text.strip().startswith("{"):
            _logger.warning("⚠️ رسالة الحالة لا تحتوي JSON صحيح")
            return
        state     = _jr.loads(state_text)
        db_fid    = state.get("db_file_id")
        zip_fid   = state.get("zip_file_id")
        timestamp = state.get("ts", "غير معروف")
        restored  = []
        if db_fid:
            try:
                fi   = bot.get_file(db_fid)
                data = bot.download_file(fi.file_path)
                with open(DB_FILE, "wb") as _f:
                    _f.write(data)
                restored.append(f"✅ قاعدة البيانات ({len(data):,} bytes)")
                _logger.info("✅ تم استعادة DB (%d bytes) — نسخة: %s", len(data), timestamp)
            except Exception as _e:
                _logger.warning("⚠️ فشل استعادة DB: %s", _e)
        if zip_fid:
            try:
                fi   = bot.get_file(zip_fid)
                data = bot.download_file(fi.file_path)
                with _zf.ZipFile(_ior.BytesIO(data)) as _z:
                    for name in _z.namelist():
                        if name.endswith(".json") and not name.startswith("backup_report"):
                            _z.extract(name, ".")
                restored.append("✅ ملفات الإعدادات (قنوات، إعدادات، ...)")
                _logger.info("✅ تم استعادة ZIP الإعدادات")
            except Exception as _e:
                _logger.warning("⚠️ فشل استعادة ZIP: %s", _e)
        if restored:
            _logger.info("🎉 الاستعادة التلقائية ناجحة: %s", " | ".join(restored))
            try:
                bot.send_message(
                    ADMIN_ID,
                    "🟢 *استعادة تلقائية ناجحة* (هيروكو)\n"
                    f"🕐 نسخة محفوظة: `{timestamp}`\n\n"
                    + "\n".join(restored),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            _logger.warning("⚠️ لم يتم استعادة أي شيء — تحقق من BACKUP_STATE_MSG_ID")
    except Exception as _e:
        _logger.warning("⚠️ خطأ عام في الاستعادة التلقائية: %s", _e)

# تشغيل الاستعادة التلقائية قبل فتح قاعدة البيانات
_heroku_auto_restore_on_startup()

_db_conn = _init_db()
# =============================================================================
# HEROKU FIX: Shared bounded executor for AI calls (replaces per-call threads)
# =============================================================================
from concurrent.futures import ThreadPoolExecutor as _TPE
_AI_EXECUTOR = _TPE(max_workers=15, thread_name_prefix="AIWorker")


# =============================================================================
# HEROKU FIX v4: Broadcast Checkpoint — resume after crash without re-sending
# =============================================================================
# =============================================================================
# HEROKU FIX v4: Persistent Dead User Set
# Users who block the bot are stored in SQLite so future broadcasts skip them
# in O(1) without waiting for a failed send.
# =============================================================================
_dead_users: set = set()
_dead_users_lock = threading.Lock()


def _init_dead_users_table():
    try:
        with _db_lock:
            _db_conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_users (
                    uid TEXT PRIMARY KEY,
                    blocked_at REAL NOT NULL
                )
            """)
            _db_conn.commit()
        # Load existing dead users into RAM
        rows = _db_conn.execute("SELECT uid FROM dead_users").fetchall()
        with _dead_users_lock:
            _dead_users.update(r[0] for r in rows)
        _logger.info("Dead users loaded: %d", len(_dead_users))
    except Exception as _due:
        _logger.debug("_init_dead_users_table: %s", _due)

_init_dead_users_table()


def _mark_dead_user(uid):
    """Mark a user as dead (bot blocked / deactivated) and persist to DB."""
    uid_s = str(uid)
    with _dead_users_lock:
        if uid_s in _dead_users:
            return   # already known
        _dead_users.add(uid_s)
    try:
        with _db_lock:
            _db_conn.execute(
                "INSERT OR IGNORE INTO dead_users(uid, blocked_at) VALUES(?,?)",
                (uid_s, time.time())
            )
            _db_conn.commit()
    except Exception as _me:
        _logger.debug("_mark_dead_user: %s", _me)


def _is_dead_user(uid) -> bool:
    with _dead_users_lock:
        return str(uid) in _dead_users


def _init_broadcast_checkpoint_table():
    try:
        with _db_lock:
            _db_conn.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_checkpoint (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            _db_conn.commit()
    except Exception as _bce:
        _logger.debug("_init_broadcast_checkpoint_table: %s", _bce)

_init_broadcast_checkpoint_table()


def _bc_save_checkpoint(session_id: str, last_uid: str, sent_count: int):
    """Save broadcast progress so we can resume after a crash."""
    if not _FF.get("bc_checkpoint", True):
        return
    try:
        import json as _jbc
        val = _jbc.dumps({"session": session_id, "last_uid": last_uid,
                           "sent": sent_count, "ts": time.time()})
        with _db_lock:
            _db_conn.execute(
                "INSERT OR REPLACE INTO broadcast_checkpoint(key,value) VALUES(?,?)",
                ("active", val)
            )
            _db_conn.commit()
    except Exception as _bce:
        _logger.debug("_bc_save_checkpoint: %s", _bce)


def _bc_clear_checkpoint():
    """Clear checkpoint after broadcast completes successfully."""
    try:
        with _db_lock:
            _db_conn.execute(
                "DELETE FROM broadcast_checkpoint WHERE key=?", ("active",))
            _db_conn.commit()
    except Exception as _exc:
        _log_exc(_exc)


def _bc_load_checkpoint() -> dict:
    """Load last incomplete broadcast checkpoint (returns {} if none)."""
    try:
        import json as _jbc
        with _db_lock:
            row = _db_conn.execute(
                "SELECT value FROM broadcast_checkpoint WHERE key=?",
                ("active",)
            ).fetchone()
        if row:
            data = _jbc.loads(row[0])
            age = time.time() - data.get("ts", 0)
            if age < 7200:   # only resume if less than 2 hours old
                return data
        return {}
    except Exception:
        return {}


def _init_button_cache_table():
    with _db_lock:
        _db_conn.execute(
            "CREATE TABLE IF NOT EXISTS button_cache ("
            "cache_name TEXT NOT NULL, "
            "cache_key TEXT NOT NULL, "
            "cache_val TEXT NOT NULL, "
            "PRIMARY KEY (cache_name, cache_key))"
        )
        _db_conn.commit()


def _save_button_cache(cache_name, cache_dict):
    import json as _jj
    try:
        rows = [(cache_name, k, _jj.dumps(v, ensure_ascii=False))
                for k, v in cache_dict.items()]
        with _db_lock:
            _db_conn.executemany(
                "INSERT OR REPLACE INTO button_cache "
                "(cache_name, cache_key, cache_val) VALUES (?,?,?)",
                rows
            )
            _db_conn.commit()
    except Exception as _exc:
        _log_exc(_exc)


def _load_button_cache(cache_name):
    import json as _jj
    try:
        with _db_lock:
            rows = _db_conn.execute(
                "SELECT cache_key, cache_val FROM button_cache WHERE cache_name=?",
                (cache_name,)
            ).fetchall()
        result = {}
        for k, v in rows:
            try:
                result[k] = _jj.loads(v)
            except Exception:
                result[k] = v
        return result
    except Exception:
        return {}


# HEROKU FIX v2: Prune old button_cache entries to prevent DB bloat
def _prune_button_cache_db():
    try:
        # Keep only the 2000 most recent entries per cache_name
        with _db_lock:
            _db_conn.execute("""
                DELETE FROM button_cache
                WHERE rowid NOT IN (
                    SELECT rowid FROM button_cache
                    ORDER BY rowid DESC LIMIT 20000
                )
            """)
            _db_conn.commit()
        _logger.info("button_cache pruned")
    except Exception as _pe:
        _logger.debug("_prune_button_cache_db: %s", _pe)


def _db_load_users():
    result = {}
    with _db_lock:
        rows = _db_conn.execute("SELECT uid, data FROM users_store").fetchall()
    for uid, raw in rows:
        try:
            d = json.loads(raw)
            # BUGFIX: sent_news must be dict {link: timestamp}, NOT a set.
            # Now saved as dict → load and filter expired entries by TTL.
            sn = d.get("sent_news", {})
            if isinstance(sn, dict):
                now_load = time.time()
                d["sent_news"] = {lnk: ts for lnk, ts in sn.items()
                                  if (now_load - ts) < _USER_SENT_TTL}
            else:
                d["sent_news"] = {}  # reset any legacy set/list format
            result[uid] = d
        except Exception as _exc:
            _log_exc(_exc)
    return result

def _db_save_user(uid, user_data):
    d = dict(user_data)
    if "sent_news" in d:
        sn = d["sent_news"]
        if isinstance(sn, dict):
            # حفظ آخر 5000 رابط فقط مع timestamps (للـ TTL)
            items = sorted(sn.items(), key=lambda x: x[1], reverse=True)[:5000]
            d["sent_news"] = dict(items)
        else:
            d["sent_news"] = {}
    raw = json.dumps(d, ensure_ascii=False)
    with _db_lock:
        _db_conn.execute(
            "INSERT OR REPLACE INTO users_store (uid, data) VALUES (?, ?)",
            (str(uid), raw)
        )
        _db_conn.commit()

def _db_save_all_users(users_dict):
    global _db_conn
    rows = []
    for uid, user_data in users_dict.items():
        d = dict(user_data)
        if "sent_news" in d:
            sn = d["sent_news"]
            if isinstance(sn, dict):
                items = sorted(sn.items(), key=lambda x: x[1], reverse=True)[:5000]
                d["sent_news"] = dict(items)
            else:
                d["sent_news"] = {}
        rows.append((str(uid), json.dumps(d, ensure_ascii=False)))
    # FIX: reconnect+retry INSIDE the lock — prevents race condition where
    # another thread closes the connection after the guard check but before executemany
    with _db_lock:
        for _attempt in range(2):
            try:
                _db_conn.executemany(
                    "INSERT OR REPLACE INTO users_store (uid, data) VALUES (?, ?)",
                    rows
                )
                _db_conn.commit()
                break
            except Exception as _e:
                if _attempt == 0:
                    _logger.warning("⚠️ _db_save_all_users: اتصال مغلق — إعادة الاتصال... (%s)", _e)
                    try:
                        _db_conn = _init_db()
                    except Exception as _re:
                        _logger.error("❌ فشل إعادة الاتصال بـ SQLite: %s", _re)
                        break
                else:
                    _logger.error("❌ _db_save_all_users: فشل بعد إعادة الاتصال: %s", _e)

def _migrate_users_from_json():
    if not os.path.exists(_legacy.USERS_FILE):
        return
    try:
        with open(_legacy.USERS_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        if old_data:
            _db_save_all_users(old_data)
            os.rename(_legacy.USERS_FILE, _legacy.USERS_FILE + ".migrated")
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
            except Exception as _exc:
                _log_exc(_exc)
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
    global _db_conn
    rows = []
    for ch_data in ch_list:
        d = dict(ch_data)
        if "sent_news" in d:
            sn = d["sent_news"]
            if isinstance(sn, dict):
                _now_db = time.time()
                d["sent_news"] = [lnk for lnk, ts in sn.items()
                                  if (_now_db - ts) < _USER_SENT_TTL][-2000:]
            else:
                d["sent_news"] = list(sn)[-2000:]
        rows.append((int(d["id"]), json.dumps(d, ensure_ascii=False)))
    # FIX: reconnect+retry INSIDE the lock — same pattern as _db_save_all_users
    with _db_lock:
        for _attempt in range(2):
            try:
                _db_conn.executemany(
                    "INSERT OR REPLACE INTO channels_store (chat_id, data) VALUES (?, ?)",
                    rows
                )
                _db_conn.commit()
                break
            except Exception as _e:
                if _attempt == 0:
                    _logger.warning("⚠️ _db_save_all_channels: اتصال مغلق — إعادة الاتصال... (%s)", _e)
                    try:
                        _db_conn = _init_db()
                    except Exception as _re:
                        _logger.error("❌ فشل إعادة الاتصال بـ SQLite: %s", _re)
                        break
                else:
                    _logger.error("❌ _db_save_all_channels: فشل بعد إعادة الاتصال: %s", _e)

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

