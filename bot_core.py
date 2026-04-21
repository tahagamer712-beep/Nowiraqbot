# -*- coding: utf-8 -*-
"""
bot_core.py — كائن البوت + دوال الإرسال الآمن + الـ Logger + الإشارات

ما يحتويه (re-exports من bot_legacy):
    bot                      — كائن TeleBot الرئيسي
    _logger                  — الـ logger المركزي
    _log_exc                 — مساعد تسجيل الاستثناءات الصامتة
    safe_send_message        — إرسال نصي مع retry و backoff
    safe_send_audio          — إرسال صوتي مع retry
    safe_send_photo          — إرسال صور مع retry
    queue_send               — إرسال عبر طابور (للحماية من rate-limit)
    send_alert               — تنبيه الأدمن عند خطأ خطير
    notify_admin_error       — إشعار الأدمن بأخطاء عامة
    _handle_sigterm          — معالج إنهاء Heroku
    _now_sa, _sa_str         — توقيت السعودية/العراق (UTC+3)
    _sanitize_input          — تنظيف مدخلات المستخدم
    is_admin                 — التحقق من صلاحية الأدمن

استورد منه هكذا:
    from .bot_core import bot, _logger, safe_send_message
"""

from .bot_legacy import (
    bot,
    _logger,
    _log_exc,
    safe_send_message,
    safe_send_audio,
    safe_send_photo,
    queue_send,
    send_alert,
    notify_admin_error,
    _handle_sigterm,
    _now_sa,
    _sa_str,
    _sanitize_input,
    is_admin,
)

__all__ = [
    "bot", "_logger", "_log_exc",
    "safe_send_message", "safe_send_audio", "safe_send_photo",
    "queue_send", "send_alert", "notify_admin_error",
    "_handle_sigterm", "_now_sa", "_sa_str", "_sanitize_input", "is_admin",
]
