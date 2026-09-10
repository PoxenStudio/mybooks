#!/usr/bin/python
# -*- coding: UTF-8 -*-
CHROME_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
}

CHROME_MOBILE_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Linux; U; Android 16;) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36",
}

CUSTOM_COVER_IMAGE = "/data/books/logo/default_cover.jpg"

CALIBRE_ERROR_FLAG = "<*ERROR*>"
SUPPORTED_EBOOK_FORMATS = ["azw3", "epub", "mobi", "pdf", "txt", "azw", "docx"]
SUPPORTED_AUDIO_FORMATS = ['.mp3', ".m4a", ".m4b", ".wav", ".wma", ".opus"]
# 有声书字幕文件格式（与音频文件同目录同名，如 0001_第一章.wav -> 0001_第一章.srt）
SUPPORTED_SUBTITLE_FORMATS = ['.srt', '.vtt']

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

# 外部链接
COLUMN_EXT_LINK = "ext_link"
CALIBRE_COLUMN_EXT_LINK = "#ext_link"

# 实体书的位置
COLUMN_LOCATION = "location"
CALIBRE_COLUMN_LOCATION = "#location"

# 动态封面
COLUMN_DYNAMIC_COVER = "dynamic_cover"
CALIBRE_COLUMN_DYNAMIC_COVER = "#dynamic_cover"

# 译者
COLUMN_TRANSLATORS = "translators"
CALIBRE_COLUMN_TRANSLATORS = "#translators"

# 书籍目录结构（markdown格式，保留层次），见 webserver/services/catalog.py
COLUMN_CATALOG = "catalog"
CALIBRE_COLUMN_CATALOG = "#catalog"

# Audio related constants
ENABLE_VIP_QUOTA_KEY = "ENABLE_VIP_QUOTA"
ENABLE_AUDIO_CONVERSION_LOG = "ENABLE_AUDIO_CONVERSION_LOG"

# 每用户每日下载配额，见 webserver/services/download_quota_service.py
ENABLE_DOWNLOAD_QUOTA_KEY = "ENABLE_DOWNLOAD_QUOTA"
GLOBAL_DOWNLOAD_QUOTA_KEY = "GLOBAL_DOWNLOAD_QUOTA"

# Performance profiling options
# 当设置中此选项设为True时，表示每隔5分钟对后台占用的内存进行统计分析
# 统计的结果输出到/data/logs/profiling.log中
# 同时统计后台各接口调用的次数、平均耗时、最大耗时的数据
ENABLE_PROFILE = "ENABLE_PROFILE"
PROFILE_INTERVAL = "PROFILE_INTERVAL"
PROFILE_OUTPUT_INTERVAL = 5 * 60  # 每5分钟输出一次性能分析结果（单位：秒）
PROFILE_LOG_PATH = "/data/log/profiling.log"  # 性能分析日志文件路径

ENABLE_OPDS_SERVICE = "ENABLE_OPDS_SERVICE"
ENABLE_PODCAST_SERVICE = "ENABLE_PODCAST_SERVICE"

DEEPSEEK_API_BASE = "https://api.deepseek.com"

AUTO_FILL_META = "auto_fill_meta"
META_SELECTED_SOURCES = "META_SELECTED_SOURCES"
META_SOURCE_GOOGLE = "google"
META_SOURCE_AMAZON = "amazon"
META_SOURCE_XHSD = "xinhua"
META_SOURCE_DOUBAN = "douban"
META_SOURCE_DOUBAN_V2 = "douban_v2"
META_SOURCE_BAIDU = "baidu"
META_SOURCE_YOUSHU = "youshu"
META_SOURCE_NEODB = "neodb"
META_SOURCE_UJXSW = "ujxsw"

# User reading range setting
ALLOW_READ_RANGE_SETTING = "ALLOW_READ_RANGE_SETTING"
DEFAULT_READ_RANGE = "DEFAULT_READ_RANGE"

# audio books
AUDIO_BOOK_IMPORTS = "audiobooks"
AUDIO_META_ALBUM = "album"
AUDIO_META_ARTIST = "artist"
IMPORT_TYPE_EBOOK = 0
IMPORT_TYPE_AUDIOBOOK = 2

TRADITIONAL_CHINESE_CODE = "zha"
DEFAULT_LANGUAGE_CODE = "zho"
JAPANESE_CODE = "jpn"

UPGRABLE_REVISION = "UPGRABLE_REVISION"
