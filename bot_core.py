# bot_core.py
import telebot
import logging
import threading
import queue
import time
import sys
import os

from config import BOT_TOKEN, ADMIN_ID

# =============================================================================
# 1. تهيئة كائن البوت (The Bot Instance)
# =============================================================================
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, num_threads=1)

# =============================================================================
# 2. نظام تسجيل الأخطاء (Logging)
# =============================================================================
_logger = logging.getLogger("IraqNow")
_logger.setLevel(logging.DEBUG)
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
_logger.addHandler(_ch)

# =============================================================================
# 3. نظام الإرسال عبر قائمة الانتظار (Queue System) - "محرك الخلود"
# =============================================================================
_QUEUE_MAX_SIZE = 20000
_QUEUE_WORKERS = 5
_send_queue = queue.Queue(maxsize=_QUEUE_MAX_SIZE)
_delivery_stats = {
    "sent_ok": 0, "sent_fail": 0, "retried": 0, "rate_limited": 0,
    "auto_resolved": 0, "admin_alerted": 0
}

def _classify_error(err_str: str) -> str:
    e = err_str.lower()
    if "429" in e or "too many requests" in e: return "rate_limit"
    if any(x in e for x in ("blocked", "deactivated", "chat not found")): return "delivery"
    if "can't parse" in e: return "parse"
    if any(x in e for x in ("network", "timeout", "connection")): return "network"
    if any(x in e for x in ("400", "401", "403", "500")): return "telegram_api"
    return "unknown"

def _exponential_backoff(attempt: int, cap: float = 60.0) -> float:
    return min(cap, 1.0 * (2 ** attempt))

def _queue_worker():
    while True:
        try:
            chat_id, text, kwargs = _send_queue.get(timeout=1)
            sent = False
            for attempt in range(5):
                try:
                    bot.send_message(chat_id, text, **kwargs)
                    sent = True
                    _delivery_stats["sent_ok"] += 1
                    if attempt > 0: _delivery_stats["retried"] += 1
                    break
                except Exception as e:
                    err_str = str(e)
                    err_type = _classify_error(err_str)
                    if err_type == "rate_limit":
                        try:
                            retry_after = int(e.result_json.get('parameters', {}).get('retry_after', 30))
                        except:
                            retry_after = 30
                        time.sleep(retry_after + 1)
                    elif err_type == "delivery":
                        _delivery_stats["auto_resolved"] += 1
                        break
                    elif err_type == "parse":
                        plain_kwargs = {k: v for k, v in kwargs.items() if k != 'parse_mode'}
                        bot.send_message(chat_id, text, **plain_kwargs)
                        sent = True
                        _delivery_stats["sent_ok"] += 1
                        _delivery_stats["auto_resolved"] += 1
                        break
                    else:
                        wait = _exponential_backoff(attempt)
                        time.sleep(wait)
            if not sent:
                _delivery_stats["sent_fail"] += 1
            _send_queue.task_done()
            time.sleep(0.05)
        except queue.Empty:
            continue
        except Exception:
            time.sleep(1)

_queue_threads = []
for i in range(_QUEUE_WORKERS):
    t = threading.Thread(target=_queue_worker, daemon=True, name=f"SendWorker-{i+1}")
    t.start()
    _queue_threads.append(t)

def queue_send(chat_id, text, **kwargs):
    try:
        _send_queue.put_nowait((chat_id, text, kwargs))
    except queue.Full:
        try:
            _send_queue.get_nowait()
            _send_queue.task_done()
            _send_queue.put_nowait((chat_id, text, kwargs))
        except:
            pass

# =============================================================================
# 4. دوال الإرسال الآمنة (Safe Send Wrappers)
# =============================================================================
def safe_send_message(chat_id, text, max_retries=4, **kwargs):
    for attempt in range(max_retries):
        try:
            return bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Flood" in err_str:
                time.sleep(30)
                continue
            if any(x in err_str for x in ("blocked", "deactivated", "chat not found")):
                return None
            if "can't parse" in err_str:
                plain_kwargs = {k: v for k, v in kwargs.items() if k != 'parse_mode'}
                try:
                    return bot.send_message(chat_id, text, **plain_kwargs)
                except:
                    return None
            wait = _exponential_backoff(attempt)
            time.sleep(wait)
    return None

def safe_send_photo(chat_id, photo, max_retries=3, **kwargs):
    caption = kwargs.pop("caption", "")
    for attempt in range(max_retries):
        try:
            return bot.send_photo(chat_id, photo, caption=caption, **kwargs)
        except Exception as e:
            err_str = str(e)
            if any(x in err_str for x in ("blocked", "deactivated")):
                return None
            if "429" in err_str:
                time.sleep(30)
                continue
            wait = _exponential_backoff(attempt)
            time.sleep(wait)
    if caption:
        try:
            return safe_send_message(chat_id, f"🖼 {caption}")
        except:
            pass
    return None

def safe_send_audio(chat_id, audio, max_retries=3, **kwargs):
    caption = kwargs.pop("caption", "")
    for attempt in range(max_retries):
        try:
            return bot.send_audio(chat_id, audio, caption=caption, **kwargs)
        except Exception as e:
            err_str = str(e)
            if any(x in err_str for x in ("blocked", "deactivated")):
                return None
            if "429" in err_str:
                time.sleep(30)
                continue
            wait = _exponential_backoff(attempt)
            time.sleep(wait)
    if caption:
        try:
            return safe_send_message(chat_id, f"🔊 {caption}")
        except:
            pass
    return None

# =============================================================================
# 5. نظام التنبيهات والإشعارات للأدمن (Admin Alerts)
# =============================================================================
def send_alert(message: str, exc: Exception = None, func_name: str = ""):
    try:
        alert_text = f"🚨 *تنبيه فوري — IraqNow Bot*\n📌 `{func_name}`\n📋 {message}"
        if exc:
            alert_text += f"\n❌ `{type(exc).__name__}: {str(exc)[:200]}`"
        safe_send_message(ADMIN_ID, alert_text, parse_mode="Markdown")
    except Exception:
        pass

def notify_admin_error(msg: str, exc: Exception = None):
    send_alert(msg, exc, func_name="unknown")
    _logger.error(msg + (f" | {exc}" if exc else ""))

# =============================================================================
# 6. دوال إدارة الذاكرة والمراقبة (Health & Memory)
# =============================================================================
def _auto_memory_cleanup():
    import gc
    gc.collect()
    _logger.info("🧹 auto_memory_cleanup: تنظيف ذاكرة تام")

def _get_sys_metrics():
    ram = cpu = disk = 0.0
    try:
        import psutil
        ram = psutil.virtual_memory().percent
        cpu = psutil.cpu_percent(interval=0.5)
        disk = psutil.disk_usage('/').percent
    except ImportError:
        pass
    return {"ram_pct": ram, "cpu_pct": cpu, "disk_pct": disk}

_sys_health = {"ram_pct": 0.0, "cpu_pct": 0.0, "disk_pct": 0.0, "recoveries": 0}

def _system_health_monitor():
    import time
    while True:
        time.sleep(60)
        try:
            m = _get_sys_metrics()
            _sys_health.update(m)
            if m["ram_pct"] > 92:
                _auto_memory_cleanup()
        except Exception:
            pass

threading.Thread(target=_system_health_monitor, daemon=True, name="HealthMon").start()
