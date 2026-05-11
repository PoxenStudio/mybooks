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
    "site_title"    : "书屋",
    "site_language" : "auto",
    "site_theme"    : "dark",
    "ssl_crt_file"  : "/data/books/ssl/ssl.crt",
    "ssl_key_file"  : "/data/books/ssl/ssl.key",

    "push_title": "%(site_title)s：推送给您一本书《%(title)s》",
    "push_content": "为您奉上一本《%(title)s》, 欢迎常来访问%(site_title)s！%(site_url)s",

    "convert_timeout" : 300,

    # https://analytics.google.com/
    "google_analytics_id" : "G-LLF01B5ZZ8",

    "ENABLE_OPDS_SERVICE"      : True,
    "ENABLE_OPDS_AUTH"         : False,
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
    "AI_API_URL": "https://api.deepseek.com",
    "MAIN_PAGE_RANDOM_COUNT": 12,
    "MAIN_PAGE_RECENT_COUNT": 12,
    "DEFAULT_PAGE_SIZE": 60,
    "ENABLE_AUDIO_CONVERSION_LOG": False,
    "LOG_LEVEL_DEBUG": False,
    "USE_DYNAMIC_COVER": True,

    "CALIBRE_CACHE_CLEAN_ENABLED": False,
    "CALIBRE_CACHE_CLEAN_INTERVAL": 1800,
    "ENABLE_TXT_TO_TXTZ_PLUGIN": False,

    "META_SELECTED_SOURCES": ["douban", "baidu", "xinhua"],

    "ENABLE_STAMP_FEATURE": False,
    "STAMP_POSITION": "bottom-right",

    "EPUB_VIEWER": "epubjs.html",
    "CANDLE_READER_SERVER": "https://brs.talebook.org",
    "PDF_VIEWER": "/static/pdfjs/web/viewer.html?file=%(pdf_url)s",
    "ENABLE_PODCAST_SERVICE": False,
    "ENABLE_WEBDAV_SERVICE": True,
    "WEBDAV_SYNC_FOLDER": False,
    "ALLOW_NEW_USER_MANAGE_BOOK": True,
    "ALLOW_NEW_USER_PUSH_BOOK": True,

    "ALLOW_READ_RANGE_SETTING": False,
    "IMPORT_BY_INOTIFY": False,
    "IMPORT_CATEGORY_WITH_FOLDER": False,
    "UPDATE_CATEGORY_WITH_FOLDER_RENAME": False,
    "SEND_MAIL_FOR_NEW_BOOKS" : False,
    "REMOVE_IMPORTED_FILE": False,

    "PDF_TILE_WITH_FILE_NAME": False,

    "SOCIAL_AUTH_LOGIN_URL"          : '/',
    "SOCIAL_AUTH_LOGIN_REDIRECT_URL" : '/api/done/',
    "SOCIAL_AUTH_USER_MODEL"         : 'webserver.models.Reader',
    "SOCIAL_AUTH_AUTHENTICATION_BACKENDS" : (
        'social_core.backends.qq.QQOAuth2',
        'social_core.backends.weibo.WeiboOAuth2',
        'social_core.backends.amazon.AmazonOAuth2',
        'social_core.backends.github.GithubOAuth2',
        'social_core.backends.weixin.WeixinOAuth2',
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

    'BOOK_NAMES_FORMAT': 'utf8',
    'BOOK_NAV'          : '''经济金融=经济学/管理/经济/金融/商业/投资/营销/理财/创业/广告/股票/企业史/策划/经济管理/中国经济/市场营销/财政/投资理财/金融学/个人理财/企业与企业家/企业管理/经管/世界经济/经济学理论/管理学/经济金融/商业模式/银行/各行业经济/货币/金融史/经济史/管理学理论/新经济/价值投资/投资 交易/金融危机/证券/财经/商业管理/零售/电商/宏观经济/流行财经读物/对冲基金/经济与管理/商战/投资交易/金融投资/货币史/贸易经济/经管经管
教育=小学书单/高中书单/初中书单/书单/小学语文阅读推荐/教育/古籍/绘本/国学/音乐/戏剧/绘画/艺术史/国学入门/少儿/童书/文艺/儿童/宋词/唐诗
心理学=心理学/心理/励志/女性/自我管理/治愈/成长/个人成长/职场/沟通/成功/人生/个人修养与自我完善/治愈系/社会以与交往/生活/个人管理/旅行/健康/自我成长/自我提升/成功心理学/时间管理/职业规划/成功心理学/女性主义/情感/人性/心灵/灵修/社会心理学/个人提升/心理學/认知心理学/进化心理学/西学/心灵成长/思维方式/鸡汤/认识精进/疗愈/人生哲学/心理自助/人际关系/自我发现/职业
社科=人文社科/哲学/传记/社会学/文化/设计/艺术/政治/社会/建筑/宗教/电影/数学/政治学/回忆录/人物传记/佛教/军事/西方哲学/自由主义/美术/纪实/海外中国研究/思想史/社会科学/方法论/人类学/管理/社科/法律/理想国/社会史/中国政治/认知/佛学/政治经济学/传播学/日本研究/领导力/社交/韩国/逻辑/生命/思维/国际政治/政治理论/世界政治/政治哲学/法学/王阳明/社会学家/道德哲学/基督教/日本文化/中国哲学/哲学理论/世界哲学/中国研究/存在主义/精神分析/哲学入门/社会科学总论/政治人物/道教/社科历史/宗教伦理与研究/哲學/社会理论/哲学史/法律法规/人口学/科学哲学/资本主义/地缘政治/信仰/美国政治/道家/民俗学/宗教知识读物/制度史/
历史=历史/中国历史/近代史/思想/二战/考古/中国/世界历史/美国/日本/英国/法国/世界史/史学理论/德国/历史知识读物/意大利/战争/军事史/历史人物/明清史/欧洲史/清史/中国近/欧洲/全球史/中东/印度/罗马/清朝/俄国/土耳其/历史思考/英国史/民国/明史/历史学/政治史/中国史/俄罗斯/以色列/中世纪/中国近代史/明朝/晚清/中国近现代史/中国当代史/东南亚/清代/半小时漫画/日本史/非洲/三国/美国史/西班牙/历史与记忆/加拿大/瑞典/古罗马/古代史/国际关系/中国古代史/台湾/宋史/历史文化/区域国别史/中国通史/史料/蒙元史/民国史/苏联/秦汉史/中国史料典籍/近现代史/当代史/唐史/先秦史/中国专门史/罗马史/明清/二战史/一战/唐朝/史部/歷史/世界军事/通史/宋代/先秦/文明史/人类史/晚清史/太平天国/阿富汗/奥斯曼帝国/宋朝/历史地理/秦汉/蒙古/魏晋南北朝史/
科技=科普/互联网/编程/科学/交互设计/用户体验/算法/web/科技/UE/UCD/通信/交互/神经网络/程序/科学技术/自然/自然科学/计算机/生物学/天文/进化/动物/宇宙/科学史/计算机科学/脑科学/物理/物理学/科普读物/其他科普知识/人工智能/地理/科普文化/植物/生物/博物/博物学/产品设计/科技科技/博弈论/量子力学/自然科学相关/生物科学/数据分析/软件开发/大数据/区块链/密码学/数学文化/计算科学/网络安全/产品经理/科技史/地理学/工具
科幻小说=科幻小说/科幻/世界科幻大师丛书/硬科幻/科幻经典/中国科幻
医学养生=医学/中医/饮食/健身/养生/神经科学/医疗史/营养学/减肥/身心灵/食物/癌症
文学=文学艺术/小说/外国文学/文学/随笔/中国文学/经典/散文/日本文学/童话/诗歌/杂文/儿童文学/古典文学/名著/钱钟书/当代文学/外国名著/诗词/散文随笔/日系推理/中国当代小说/美国文学/青春/奇幻/短篇小说/推理小说/悬疑/非虚构/爱情/侦探/历史小说/法国文学/文学研究/文化史/文学理论/短篇/都市小说/中国古典小说/欧美推理/小说类/外国文学作品集/日本推理/世界名著/中国文化/语言文字/文学天地/言情小说/网络小说/午夜文库/俄罗斯文学/青春文学/传统文化/文学研究/文学评论/小说类/拉美文学/魔幻/推理/外国小说/英国文学/悬疑小说/台湾文学/外国散文随笔/言情/文化研究/文学史/日本文化/文学评论与研究/悬疑推理/人文/长篇/诗人/西方奇幻/匈牙利文学/写作/现代文学/苏俄文学/土耳其文学/玄幻/文学史/短篇集/长篇小说/漫画/游记/纪实文学/诗歌词曲赋/中国文学作品集/犯罪/当代散文随笔/文化理论/東野圭吾/武侠小说/侦探小说/言情小说/爱尔兰文学/汉学/日本小说/茅盾文学奖/中国小说/小說/奇幻小说/加拿大文学/推理悬疑/中篇小说/欧美文学/烧脑/文学名著/国产推理/玄幻小说/恐怖/集部/自传/章回小说/中国当代文学/神话/俄国文学/中国现当代文学/历险小说/中国当代文学/文学届/FICTION/意大利文学/青春言情/现当代文学/轻小说/西方文学/中国现代小说
''',

    'INVITE_MODE'   : False,
    'INVITE_CODE'   : 'talebook',
    'INVITE_MESSAGE': '''本站为私人图书馆，需输入密码才可进行访问''',

    'ALLOW_GUEST_READ' : True,
    'ALLOW_GUEST_PUSH' : True,
    'ALLOW_GUEST_DOWNLOAD' : True,
    'ALLOW_REGISTER' : False,
    'HEADER': '',
    'FOOTER': '',

    'FRIENDS': [
        { "text": "书格", "href": "https://www.shuge.org/" },
        { "text": "读书派", "href": "https://dushupai.com" }
    ],
    'SOCIALS': [],
    'DEVICES': [],
    'SIGNUP_MAIL_TITLE': '欢迎注册个人书屋',
    'SIGNUP_MAIL_CONTENT': '''
Hi, %(username)s！
欢迎注册%(site_title)s，这里虽然是个小小的图书馆，但是希望你找到所爱。

点击链接激活你的账号: %(active_link)s
''',

    'RESET_MAIL_TITLE': '密码重置',
    'RESET_MAIL_CONTENT': '''
Hi, %(username)s！

你刚刚在网站上提交了密码重置，请妥善保存你的新密码: %(password)s
''',
    'NEW_BOOK_MAIL_TITLE': '',
    'NWE_BOOK_MAIL_HEADER': ''
}
