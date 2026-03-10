#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
# fmt: off
# flake8: noqa

import os

settings = {
    'installed'     : False,
    "autoreload"    : True,
    "xsrf_cookies"  : False,
    "static_host"   : "",
    "nuxt_env_path" : os.path.join(os.path.dirname(__file__), "../app/.env"),
    "html_path"     : os.path.join(os.path.dirname(__file__), "../app/dist"),
    "i18n_path"     : os.path.join(os.path.dirname(__file__), "i18n"),
    "static_path"   : os.path.join(os.path.dirname(__file__), "../app/dist"),
    "resource_path" : os.path.join(os.path.dirname(__file__), "resources"),
    "settings_path" : "/data/books/settings/",
    "progress_path" : "/data/books/progress/",
    "convert_path"  : "/data/books/convert/",
    "upload_path"   : "/data/books/upload/",
    "scan_upload_path"   : "/data/books/imports/",
    "extract_path"  : "/data/books/extract/",
    "with_library"  : "/data/books/library/",
    "cookie_secret" : "cookie_secret",
    "cookie_expire" : 7*86400,
    "login_url"     : "/login",
    "user_database" : 'sqlite:////data/books/calibre-webserver.db',
    "site_title"    : u"书屋",
    "site_language" : "zh",
    "site_theme"    : "dark",
    "ssl_crt_file"  : "/data/books/ssl/ssl.crt",
    "ssl_key_file": "/data/books/ssl/ssl.key",

    "push_title": u"%(site_title)s：推送给您一本书《%(title)s》",
    "push_content": u"为您奉上一本《%(title)s》, 欢迎常来访问%(site_title)s！%(site_url)s",

    "convert_timeout" : 300,

    # https://analytics.google.com/
    "google_analytics_id" : "G-LLF01B5ZZ8",

    "ENABLE_OPDS_SERVICE"      : True,
    "opds_will_display"        : ["*"],
    "opds_wont_display"        : [],
    "opds_max_tags_shown"      : 10240,
    "opds_max_items"           : 50,
    "opds_max_ungrouped_items" : 100,
    "opds_url_prefix"          : "",

    "db_engine_args": {
        "echo": False,
    },

    # 100MB, tornado default max_buffer_size value
    "MAX_UPLOAD_SIZE": "100MB",

    # Chunked upload size threshold (0 means disabled, >0 means files larger than this will be uploaded in chunks)
    "CHUNK_UPLOAD_SIZE": "0MB",

    "ENABLE_BOOKBARN": False,
    "BOOKBARN_TOKEN": "",
    "ENABLE_RECEIVING_BOOKS": False,
    "BOOKBARN_COLLECTION_HOUR": 3,
    "USE_BOOKBARN_PROXY": False,
    "BOOK2AUDIO_PROXY": "",
    "ENABLE_PHYSICAL_BOOKS": True,
    "ALLOW_GUEST_UPLOAD": False,
    "AI_ENABLED": False,
    "AI_MODEL": "deepseek-chat",
    "AI_MCP_TOKEN": "",
    "AI_DEEPSEEK_API_KEY": "",
    "MAIN_PAGE_RANDOM_COUNT": 12,
    "MAIN_PAGE_RECENT_COUNT": 12,
    "DEFAULT_PAGE_SIZE": 60,
    "ENABLE_AUDIO_CONVERSION_LOG": False,

    "CALIBRE_CACHE_CLEAN_ENABLED": False,
    "CALIBRE_CACHE_CLEAN_INTERVAL": 1800,

    "META_SELECTED_SOURCES": ["douban", "baidu", "xinhua"],

    "EPUB_VIEWER": "epubjs.html",
    "CANDLE_READER_SERVER": "https://brs.talebook.org",
    "PDF_VIEWER": "/static/pdfjs/web/viewer.html?file=%(pdf_url)s",
    "WEBDAV_SYNC_FOLDER": False,

    "SOCIAL_AUTH_LOGIN_URL"          : '/',
    "SOCIAL_AUTH_LOGIN_REDIRECT_URL" : '/api/done/',
    "SOCIAL_AUTH_USER_MODEL"         : 'webserver.models.Reader',
    "SOCIAL_AUTH_AUTHENTICATION_BACKENDS" : (
        'social_core.backends.qq.QQOAuth2',
        'social_core.backends.weibo.WeiboOAuth2',
        'social_core.backends.amazon.AmazonOAuth2',
        'social_core.backends.github.GithubOAuth2',
    ),

    # See: http://open.weibo.com/developers
    'SOCIAL_AUTH_WEIBO_KEY'            : '',
    'SOCIAL_AUTH_WEIBO_SECRET'         : '',

    # See: https://connect.qq.com/
    'SOCIAL_AUTH_QQ_KEY'               : '',
    'SOCIAL_AUTH_QQ_SECRET'            : '',

    # See: https://github.com/settings/applications/new
    'SOCIAL_AUTH_GITHUB_KEY'           : '',
    'SOCIAL_AUTH_GITHUB_SECRET'        : '',

    # See: http://service.mail.qq.com/cgi-bin/help?subtype=1&&no=1001256&&id=28
    'smtp_server'       : "smtp.126.com",
    'smtp_encryption'   : "TLS",
    'smtp_username'     : "sender@126.com",
    'smtp_password'     : "password",
    'douban_apikey'     : "0df993c66c0c636e29ecbb5344252a4a",
    'douban_baseurl'    : "http://douban-rs-api:80/",
    'douban_max_count'  : 2,
    'auto_fill_meta'    : False,

    'avatar_service'    : "https://cravatar.cn",

    'BOOK_NAMES_FORMAT': 'en',
    'BOOK_NAV'          : '''文化=心理学/哲学/传记/文化/社会学/设计/艺术/政治/社会/宗教/电影/政治学/回忆录/思想/国学/音乐/人文/戏剧/人物传记/绘画/艺术史/佛教/军事/西方哲学/自由主义/考古/美术
历史=历史/近代史/中国历史/历史军事/二战/资本主义/中国史/国史/历史学/战争/欧洲史\n科学=数学/物理/建筑/统计学/地理/生物/统计/世界史/大数据
生活=爱情/旅行/生活/励志/成长/摄影/心理/女性/职场/美食/游记/教育/灵修/情感/健康/手工/养生/两性/家居/人际关系/自助游/口才
科技=科普/互联网/编程/科学/交互设计/用户体验/算法/web/科技/UE/UCD/通信/交互/神经网络/程序\n经管=经济学/管理/经济/金融/商业/投资/营销/理财/创业/广告/股票/企业史/策划/法律/经管/经济读物/宏观/金融学/企业管理/成功
文学=小说/外国文学/文学/随笔/中国文学/经典/散文/日本文学/村上春树/童话/诗歌/王小波/杂文/张爱玲/儿童文学/余华/古典文学/名著/钱钟书/当代文学/鲁迅/外国名著/诗词/茨威格/杜拉斯/米兰·昆德拉/港台/Novel
''',

    'INVITE_MODE'   : False,
    'INVITE_CODE'   : 'talebook',
    'INVITE_MESSAGE': u'''本站为私人图书馆，需输入密码才可进行访问''',

    'ALLOW_GUEST_READ' : True,
    'ALLOW_GUEST_PUSH' : True,
    'ALLOW_GUEST_DOWNLOAD' : True,
    'ALLOW_REGISTER' : False,
    'HEADER': '',
    'FOOTER': '',

    'FRIENDS': [
        { "text": u"书格", "href": "https://www.shuge.org/" },
        { "text": u"读书派", "href": "https://dushupai.com" }
    ],
    'SOCIALS': [
    ],
    'DEVICES': [
    ],
    'SIGNUP_MAIL_TITLE': u'欢迎注册个人书屋',
    'SIGNUP_MAIL_CONTENT': u'''
Hi, %(username)s！
欢迎注册%(site_title)s，这里虽然是个小小的图书馆，但是希望你找到所爱。

点击链接激活你的账号: %(active_link)s
''',

    'RESET_MAIL_TITLE': u'密码重置',
    'RESET_MAIL_CONTENT': u'''
Hi, %(username)s！

你刚刚在网站上提交了密码重置，请妥善保存你的新密码: %(password)s
''',

}
