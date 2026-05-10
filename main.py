# -*- coding: utf-8 -*-
import time, atexit

import config  # noqa: F401
import bot_legacy as _legacy

# FIX: حُذف استبدال الـ executor — كان يسبب race condition لأن الـ scheduler يبدأ في bot_legacy.py
# قبل وصول main.py، استبدال الـ executor بعد التشغيل يُعطّل بعض الـ jobs

import bot_core, db, ai, features_news, features_sports, features_users, handlers  # noqa: F401

bot        = _legacy.bot
_logger    = _legacy._logger
_log_exc   = _legacy._log_exc
send_alert = _legacy.send_alert
_retry_count = 0

def _shutdown():
    try:
        s = getattr(_legacy, "scheduler", None)
        if s and s.running:
            s.shutdown(wait=False)
    except Exception:
        pass
    try:
        e = getattr(_legacy, "_AI_EXECUTOR", None)
        if e:
            e.shutdown(wait=False)
    except Exception:
        pass

atexit.register(_shutdown)

def run():
    global _retry_count
    while True:
        try:
            _logger.info(f"🚀 بدء التشغيل (محاولة #{_retry_count + 1})")
            bot.infinity_polling(
                allowed_updates=["message", "callback_query", "my_chat_member"],
                timeout=60, long_polling_timeout=60,
                none_stop=True, restart_on_change=False,
            )
            _retry_count = 0
        except KeyboardInterrupt:
            _logger.info("🛑 إيقاف يدوي")
            _shutdown()
            break
        except RuntimeError as _re:
            if "cannot schedule new futures" in str(_re):
                time.sleep(3)
                continue
            _retry_count += 1
            time.sleep(min(5 * (2 ** (_retry_count - 1)), 60))
        except Exception as _err:
            _retry_count += 1
            _wait = min(5 * (2 ** (_retry_count - 1)), 60)
            _logger.error(f"💥 انهيار #{_retry_count}: {_err} — إعادة خلال {_wait}s")
            if _retry_count <= 5:
                try:
                    send_alert(message=f"كراش #{_retry_count}", exc=_err,
                               func_name="polling", show_traceback=True)
                except Exception:
                    pass
            try:
                bot.delete_webhook(drop_pending_updates=True)
            except Exception:
                pass
            time.sleep(_wait)

if __name__ == "__main__":
    run()
