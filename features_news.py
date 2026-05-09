# -*- coding: utf-8 -*-
"""
features_news.py — كل ما يتعلق بالأخبار

ما يحتويه (re-exports من bot_legacy):
    # ── جلب RSS ──────────────────────────────────────────────
    _parse_feed, _fetch_one_feed, _parallel_fetch_feeds
    _get_cached_feed, _rss_prefetcher
    _validate_rss_feed, _rss_auto_discover

    # ── السكرابينغ ──────────────────────────────────────────
    _scrape_telegram_channel, _scrape_news_site, get_scraped_news
    _fetch_dollariraqi_market

    # ── تنسيق الأخبار ───────────────────────────────────────
    escape_md, format_news_item
    make_news_share_markup
    _format_clustered_news
    _get_og_image, _normalize_news_link

    # ── البث ────────────────────────────────────────────────
    broadcast_news               — للمستخدمين
    broadcast_to_channels        — للقنوات والمجموعات
    _broadcast_watchdog          — حارس الأمان
    _eternal_broadcast_keeper    — يضمن استمرار البث

    # ── التصفية والترتيب ───────────────────────────────────
    _news_importance_score
    _dedup_news_list, _is_similar_title, _cosine_similarity_titles
    _is_quiet_hours, _passes_alert_level
    _sentiment_emoji, _should_send_with_image
    _register_broadcast_title

    # ── النشر للسوشال ميديا ─────────────────────────────────
    _post_to_facebook, _post_to_instagram, _post_social_media
    _upload_to_imgbb
"""

from bot_legacy import (
    # RSS
    _parse_feed,
    _fetch_one_feed,
    _parallel_fetch_feeds,
    _get_cached_feed,
    _rss_prefetcher,
    _validate_rss_feed,
    _rss_auto_discover,
    # Scraping
    _scrape_telegram_channel,
    _scrape_news_site,
    get_scraped_news,
    _fetch_dollariraqi_market,
    # Formatting
    escape_md,
    format_news_item,
    make_news_share_markup,
    _format_clustered_news,
    _get_og_image,
    _normalize_news_link,
    # Broadcast
    broadcast_news,
    broadcast_to_channels,
    _broadcast_watchdog,
    _eternal_broadcast_keeper,
    # Filtering & ranking
    _news_importance_score,
    _dedup_news_list,
    _is_similar_title,
    _cosine_similarity_titles,
    _is_quiet_hours,
    _passes_alert_level,
    _sentiment_emoji,
    _should_send_with_image,
    _register_broadcast_title,
    # Social media
    _post_to_facebook,
    _post_to_instagram,
    _post_social_media,
    _upload_to_imgbb,
)
