# -*- coding: utf-8 -*-
"""
features_users.py — كل ما يتعلق بالمستخدم

ما يحتويه (re-exports من bot_legacy):
    is_premium                     — هل المستخدم مميز؟
    has_feature                    — هل يملك ميزة معينة؟
    check_referral_rewards         — مكافآت الإحالات
    send_feature_choice_menu       — قائمة اختيار الميزات
    update_stats                   — تحديث الإحصائيات
    save_users, save_stats         — حفظ المستخدمين والإحصائيات
    save_extra_admins              — حفظ قائمة الأدمن الإضافيين
    _is_iraqi_user                 — هل المستخدم عراقي؟
    _is_dead_chat, _blacklist_chat — معالجة المحادثات الميتة
"""

from .bot_legacy import (
    is_premium,
    has_feature,
    check_referral_rewards,
    send_feature_choice_menu,
    update_stats,
    save_users,
    save_stats,
    save_extra_admins,
    _is_iraqi_user,
    _is_dead_chat,
    _blacklist_chat,
)
