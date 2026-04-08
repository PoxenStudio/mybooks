#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import contextvars
import json
import locale
import logging
import os
from typing import Dict

SUPPORTED_LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "zh"
TEXT_DOMAIN = "messages"

_current_language = contextvars.ContextVar("talebook_i18n_language", default=None)
_catalog_cache: Dict[str, Dict[str, str]] = {}

_DEFAULT_SETTINGS_ZH = {
    "site_title": "书屋",
    "push_title": "%(site_title)s：推送给您一本书《%(title)s》",
    "push_content": "为您奉上一本《%(title)s》, 欢迎常来访问%(site_title)s！%(site_url)s",
    "INVITE_MESSAGE": "本站为私人图书馆，需输入密码才可进行访问",
    "SIGNUP_MAIL_TITLE": "欢迎注册个人书屋",
    "RESET_MAIL_TITLE": "密码重置",
}

_DEFAULT_SETTINGS_EN = {
    "site_title": "Library",
    "push_title": "%(site_title)s: A book has been pushed to you: %(title)s",
    "push_content": "A book %(title)s is prepared for you. Welcome back to %(site_title)s! %(site_url)s",
    "INVITE_MESSAGE": "This is a private library. Please enter an invite code to access",
    "SIGNUP_MAIL_TITLE": "Welcome to register your library",
    "RESET_MAIL_TITLE": "Password reset",
}


def normalize_language(lang: str) -> str:
    if not lang:
        return ""
    lang = str(lang).strip().lower().replace("_", "-")
    if lang.startswith("zh"):
        return "zh"
    if lang.startswith("en"):
        return "en"
    return ""


def detect_system_language() -> str:
    candidates = []
    env_lang = os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LANG")
    if env_lang:
        candidates.append(env_lang)
    try:
        sys_locale = locale.getdefaultlocale()[0]
        if sys_locale:
            candidates.append(sys_locale)
    except Exception:
        pass

    for cand in candidates:
        lang = normalize_language(cand)
        if lang in SUPPORTED_LANGUAGES:
            return lang
    return DEFAULT_LANGUAGE


def _load_catalog(lang: str) -> Dict[str, str]:
    lang = normalize_language(lang) or DEFAULT_LANGUAGE
    if lang in _catalog_cache:
        return _catalog_cache[lang]

    if lang == "zh":
        _catalog_cache[lang] = {}
        return _catalog_cache[lang]

    base_dir = os.path.join(os.path.dirname(__file__), "i18n")
    file_path = os.path.join(base_dir, f"{lang}.json")
    if not os.path.exists(file_path):
        logging.warning("i18n catalog not found for language %s: %s", lang, file_path)
        _catalog_cache[lang] = {}
        return _catalog_cache[lang]

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _catalog_cache[lang] = data if isinstance(data, dict) else {}
    except Exception:
        logging.exception("Failed to load i18n catalog: %s", file_path)
        _catalog_cache[lang] = {}
    return _catalog_cache[lang]


def set_default_language(lang: str) -> str:
    global DEFAULT_LANGUAGE
    normalized = normalize_language(lang)
    if normalized in SUPPORTED_LANGUAGES:
        DEFAULT_LANGUAGE = normalized
    else:
        DEFAULT_LANGUAGE = detect_system_language()
    return DEFAULT_LANGUAGE


def set_language(lang: str) -> str:
    normalized = normalize_language(lang)
    if normalized not in SUPPORTED_LANGUAGES:
        normalized = DEFAULT_LANGUAGE
    _current_language.set(normalized)
    return normalized


def get_language() -> str:
    lang = _current_language.get()
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return DEFAULT_LANGUAGE


def parse_accept_language(accept_language: str):
    if not accept_language:
        return []
    items = []
    for chunk in accept_language.split(","):
        part = chunk.strip()
        if not part:
            continue
        lang = part.split(";")[0].strip()
        normalized = normalize_language(lang)
        if normalized:
            items.append(normalized)
    return items


def choose_language(site_language: str = "", accept_language: str = "") -> str:
    selected = normalize_language(site_language)
    if selected in SUPPORTED_LANGUAGES:
        return selected

    for lang in parse_accept_language(accept_language):
        if lang in SUPPORTED_LANGUAGES:
            return lang

    return DEFAULT_LANGUAGE


def apply_localized_default_settings(conf: dict, lang: str):
    lang = normalize_language(lang)
    if lang != "en":
        return
    for key, zh_val in _DEFAULT_SETTINGS_ZH.items():
        if conf.get(key) == zh_val:
            conf[key] = _DEFAULT_SETTINGS_EN[key]


def gettext(message: str) -> str:
    lang = get_language()
    if lang == "zh" or not message:
        return message
    catalog = _load_catalog(lang)
    return catalog.get(message, message)


def ngettext(singular: str, plural: str, n: int) -> str:
    message = singular if n == 1 else plural
    return gettext(message)


def _(message: str) -> str:
    return gettext(message)
