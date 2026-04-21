# -*- coding: utf-8 -*-
"""
handlers.py — معالجات الرسائل والأزرار

في الكود الحالي، جميع الـ @bot.message_handler و @bot.callback_query_handler
مُسجَّلة تلقائياً عند استيراد bot_legacy.py (لأن الديكوريتر يسجلها على
كائن bot عند تنفيذ الملف).

لذلك هذا الملف لا يحتاج إلى re-export — مجرد استيراد bot_legacy في
main.py يكفي لتسجيل كل المعالجات.

الدوال الـ public القابلة للاستدعاء المباشر:
"""

from .bot_legacy import (
    admin_command,
    help_command,
    stop_command,
    admin_panel,
)
