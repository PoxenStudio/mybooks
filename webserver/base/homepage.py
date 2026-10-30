#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import re

HOMEPAGE_KEY = "HOMEPAGE_CONFIG"
HOMEPAGE_VERSION = 1

BUILTIN_SECTIONS = (
    "libraryStats",
    "readingStats",
    "index.myReading",
    "index.socialRecommendation",
    "index.booklistRecommendation",
    "index.randomRecommendation",
    "index.newRecommendation",
)

CUSTOM_TYPES = ("author", "tag", "series", "language", "rating")
CUSTOM_SORTS = ("new", "title", "rating", "series", "random")
CUSTOM_LIMITS = (6, 12, 24, 48)
MAX_CUSTOM_CARDS = 30
MAX_VALUE_LEN = 200

CUSTOM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def default_homepage():
    return {
        "version": HOMEPAGE_VERSION,
        "order": list(BUILTIN_SECTIONS),
        "hidden": [],
        "custom": [],
    }


def default_sort_for(card_type):
    if card_type == "series":
        return "series"
    if card_type == "rating":
        return "rating"
    return "new"


def _clean_text(value, limit):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def normalize_homepage(raw):
    if not isinstance(raw, dict):
        return default_homepage()

    custom = []
    used_ids = set()
    raw_custom = raw.get("custom")
    if isinstance(raw_custom, list):
        for index, item in enumerate(raw_custom):
            if len(custom) >= MAX_CUSTOM_CARDS:
                break
            if not isinstance(item, dict):
                continue
            card_type = _clean_text(item.get("type"), 20).lower()
            if card_type not in CUSTOM_TYPES:
                continue
            raw_value = item.get("value")
            value = raw_value.strip()[:MAX_VALUE_LEN] if isinstance(raw_value, str) else ""
            card_id = _clean_text(item.get("id"), 40)
            if not CUSTOM_ID_RE.match(card_id) or card_id in used_ids:
                card_id = "c%d" % (index + 1)
                while card_id in used_ids:
                    card_id += "x"
            sort = _clean_text(item.get("sort"), 20).lower()
            if sort not in CUSTOM_SORTS:
                sort = default_sort_for(card_type)
            try:
                limit = int(item.get("limit"))
            except (TypeError, ValueError):
                limit = 12
            if limit not in CUSTOM_LIMITS:
                limit = 12
            custom.append(
                {
                    "id": card_id,
                    "type": card_type,
                    "value": value,
                    "sort": sort,
                    "limit": limit,
                }
            )
            used_ids.add(card_id)

    known = set(BUILTIN_SECTIONS)
    known.update("custom:" + card["id"] for card in custom)

    order = []
    raw_order = raw.get("order")
    if isinstance(raw_order, list):
        for section in raw_order:
            if isinstance(section, str) and section in known and section not in order:
                order.append(section)
    for section in BUILTIN_SECTIONS:
        if section not in order:
            order.append(section)
    for card in custom:
        section = "custom:" + card["id"]
        if section not in order:
            order.append(section)

    hidden = []
    raw_hidden = raw.get("hidden")
    if isinstance(raw_hidden, list):
        for section in raw_hidden:
            if isinstance(section, str) and section in known and section not in hidden:
                hidden.append(section)

    return {
        "version": HOMEPAGE_VERSION,
        "order": order,
        "hidden": hidden,
        "custom": custom,
    }


def homepage_from_legacy(settings):
    hidden = []
    if not settings.get("ENABLE_HOMEPAGE_READING_STATS", True):
        hidden.append("readingStats")
    if not settings.get("ENABLE_HOMEPAGE_READING_BOOKS", True):
        hidden.append("index.myReading")
    if not settings.get("ENABLE_HOMEPAGE_BOOKLISTS", False):
        hidden.append("index.booklistRecommendation")
    if not settings.get("ENABLE_BOOK_RECOMMEND_TO_OTHERS", True):
        hidden.append("index.socialRecommendation")
    try:
        if int(settings.get("MAIN_PAGE_RANDOM_COUNT", 12)) <= 0:
            hidden.append("index.randomRecommendation")
    except (TypeError, ValueError):
        pass
    return normalize_homepage({"hidden": hidden})


def get_homepage_config(apply_modules=True):
    from webserver import loader

    settings = loader.get_settings()
    raw = settings.get(HOMEPAGE_KEY)
    # 没配过、或 auto.py 里被手改成非 dict：都回退到旧开关推导，
    # 否则 normalize_homepage 会返回"全部可见"，让默认关闭的卡片突然出现
    if not isinstance(raw, dict) or not raw:
        config = homepage_from_legacy(settings)
    else:
        config = normalize_homepage(raw)
    return apply_module_visibility(config) if apply_modules else config


# 首页卡片 ↔ 功能模块。模块关闭时卡片强制视为隐藏，只影响运行期下发；
# 设置页必须用 apply_modules=False 取原样配置——否则管理员关闭模块期间保存一次，
# 这份「强制隐藏」就会被写进用户存的 HOMEPAGE_CONFIG，重新打开模块后卡片也回不来。
CARD_MODULES = {
    "index.booklistRecommendation": "community",
}


def apply_module_visibility(config):
    from webserver.base import modules as feature_modules

    hidden = list(config.get("hidden") or [])
    changed = False
    for section, module_id in CARD_MODULES.items():
        if section in hidden:
            continue
        if not feature_modules.module_enabled(module_id):
            hidden.append(section)
            changed = True
    if not changed:
        return config
    result = dict(config)
    result["hidden"] = hidden
    return result
