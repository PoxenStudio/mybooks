#!/usr/bin/python
# -*- coding: UTF-8 -*-


CHROME_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
}

CHROME_MOBILE_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36"
}

ZLIBRARY_SUFFIX = "(Z-Library)"
CALIBRE_ERROR_FLAG = "<*ERROR*>"
SUPPORTED_EBOOK_FORMATS = ["azw3", "epub", "mobi", "pdf", "txt"]

COLUMN_CATEGORY = "category"
CALIBRE_COLUMN_CATEGORY = "#category"

# Audio related constants
ENABLE_VIP_QUOTA_KEY = "ENABLE_VIP_QUOTA"
ENABLE_AUDIO_CONVERSION_LOG = "ENABLE_AUDIO_CONVERSION_LOG"
