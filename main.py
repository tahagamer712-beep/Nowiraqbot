# -*- coding: utf-8 -*-
"""
main.py — نقطة الدخول الوحيدة للبوت

تشغيل:
    python -m IraqNowBot.main
"""

import time

# 1) تحميل الإعدادات أولاً (يضمن وجود متغيرات البيئة قبل أي شيء)
from . import config  # noqa: F401

# 2) تحميل الكود الكامل (بدون أن يبدأ polling بفضل فصلنا له)
from . import bot_legacy as _legacy

# 3) تسجيل الـ namespaces المنظّمة (re-exports فقط للملاحة المنطقية)
from . import bot_core, db, ai, features_news, features_sports, features_users, handlers  # noqa: F401

# 4) تشغيل حلقة polling (مع إعادة محاولة ذكية)
bot       = _legacy.bot
_logger   = _legacy._logger
_log_exc  = _legacy._log_exc
send_alert = _legacy.send_alert

_retry_count    = 0
_last_poll_ping = time.time()


def run() -> None:
    """تشغيل البوت مع حلقة إعادة محاولة وحماية من السقوط."""
    global _retry_count, _last_poll_ping
    while True:
        try:
            _logger.info(f"🚀 بدء التشغيل (محاولة #{_retry_count + 1})")
            bot.infinity_polling(
                allowed_updates=["message", "callback_query", "my_chat_member"],
                timeout=60,
                long_polling_timeout=60,
                none_stop=True,
                restart_on_change=False,
            )
            _retry_count    = 0
            _last_poll_ping = time.time()

        except KeyboardInterrupt:
            _logger.info("🛑 إيقاف يدوي (KeyboardInterrupt) — إغلاق نظيف")
            break

        except Exception as _poll_err:
            _retry_count += 1
            _wait = min(5 * (2 ** (_retry_count - 1)), 60)
            _logger.error(
                f"💥 انهيار في polling (#{_retry_count}): {_poll_err} — "
                f"إعادة التشغيل خلال {_wait}s"
            )
            if _retry_count <= 5 or _retry_count % 10 == 0:
                send_alert(
                    message=f"البوت انهار وأُعيد تشغيله تلقائياً (محاولة #{_retry_count})",
                    exc=_poll_err,
                    func_name="infinity_polling",
                    show_traceback=True,
                )
            try:
                bot.delete_webhook(drop_pending_updates=True)
            except Exception as _exc:
                _log_exc(_exc)
            time.sleep(_wait)


if __name__ == "__main__":
    run()
