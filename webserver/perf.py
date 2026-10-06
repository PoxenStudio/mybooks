import logging

from webserver import loader

CONF = loader.get_settings()

MODES = ("normal", "lite")
LITE_GROUPS = {
    "LITE_GROUP_LISTING": ("LITE_SEARCH_FAST", "LITE_PAGE_SIZE", "LITE_LIST_SLIM", "LITE_BOOK_CACHE", "LITE_HOME_CACHE"),
    "LITE_GROUP_RECOMMEND": ("LITE_NO_RECOMMEND",),
    "LITE_GROUP_FILES": ("LITE_THUMB_CACHE_ONLY", "LITE_NO_DYNAMIC_COVER", "LITE_DOWNLOAD_PATH_CACHE", "LITE_NO_SOURCE_COPY"),
    "LITE_GROUP_BACKGROUND": ("LITE_SKIP_AFTER_UPLOAD", "LITE_ONE_HEAVY_TASK", "LITE_BG_SLOWER", "LITE_FLUSH_SLOWER"),
    "LITE_GROUP_RESOURCES": ("LITE_THROTTLE", "LITE_POOLS_SMALL", "LITE_GC_TUNE", "LITE_SQLITE_RELAXED", "LITE_LOG_LEVEL"),
}
ITEM_GROUP = {item: group for group, items in LITE_GROUPS.items() for item in items}


def is_lite():
    return CONF.get("PERFORMANCE_MODE", "normal") == "lite"


def lite_on(name):
    return is_lite() and bool(CONF.get(ITEM_GROUP.get(name, name), True))


def setting_keys():
    return ["PERFORMANCE_MODE", *LITE_GROUPS]


def sanitize(args, current):
    mode = args.get("PERFORMANCE_MODE", current.get("PERFORMANCE_MODE", "normal"))
    args["PERFORMANCE_MODE"] = mode if mode in MODES else "normal"
    for key in LITE_GROUPS:
        args[key] = bool(args.get(key, current.get(key, True)))
    return args


_saved_level = None


def apply_logging():
    global _saved_level
    root = logging.getLogger()
    if lite_on("LITE_LOG_LEVEL"):
        if _saved_level is None:
            _saved_level = root.level
        root.setLevel(logging.WARNING)
    elif _saved_level is not None:
        root.setLevel(_saved_level)
        _saved_level = None
