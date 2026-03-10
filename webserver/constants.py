#!/usr/bin/python
# -*- coding: UTF-8 -*-
CHROME_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
}

CHROME_MOBILE_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36"
}

CALIBRE_ERROR_FLAG = "<*ERROR*>"
SUPPORTED_EBOOK_FORMATS = ["azw3", "epub", "mobi", "pdf", "txt"]

COLUMN_CATEGORY = "category"
CALIBRE_COLUMN_CATEGORY = "#category"

# 书籍来源
COLUMN_BOOK_TYPE = "book_type"
CALIBRE_COLUMN_BOOK_TYPE = "#book_type"
BOOK_TYPE_EBOOK = 0  # 电子书
BOOK_TYPE_PHYSICAL = 1  # 实体书

# 物理书籍数量
COLUMN_PHY_COUNT = "book_count"
CALIBRE_COLUMN_PHY_COUNT = "#book_count"

# Audio related constants
ENABLE_VIP_QUOTA_KEY = "ENABLE_VIP_QUOTA"
ENABLE_AUDIO_CONVERSION_LOG = "ENABLE_AUDIO_CONVERSION_LOG"

# Performance profiling options
# 当设置中此选项设为True时，表示每隔5分钟对后台占用的内存进行统计分析
# 统计的结果输出到/data/logs/profiling.log中
# 同时统计后台各接口调用的次数、平均耗时、最大耗时的数据
ENABLE_PROFILE = "ENABLE_PROFILE"
PROFILE_INTERVAL = "PROFILE_INTERVAL"
PROFILE_OUTPUT_INTERVAL = 5 * 60  # 每5分钟输出一次性能分析结果（单位：秒）
PROFILE_LOG_PATH = "/data/log/profiling.log"  # 性能分析日志文件路径

ENABLE_OPDS_SERVICE = "ENABLE_OPDS_SERVICE"

DEEPSEEK_API_BASE = "https://api.deepseek.com"

AUTO_FILL_META = "auto_fill_meta"
META_SELECTED_SOURCES = "META_SELECTED_SOURCES"
META_SOURCE_GOOGLE = "google"
META_SOURCE_AMAZON = "amazon"
META_SOURCE_XHSD = "xinhua"
META_SOURCE_DOUBAN = "douban"
META_SOURCE_BAIDU = "baidu"
