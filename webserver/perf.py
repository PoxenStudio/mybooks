from webserver import loader

CONF = loader.get_settings()

MODES = ("normal", "lite")
LITE_ITEMS = ("LITE_BOOK_CACHE",)


def is_lite():
    return CONF.get("PERFORMANCE_MODE", "normal") == "lite"


def lite_on(name):
    return is_lite() and bool(CONF.get(name, True))


def setting_keys():
    return ["PERFORMANCE_MODE", *LITE_ITEMS]


def sanitize(args, current):
    mode = args.get("PERFORMANCE_MODE", current.get("PERFORMANCE_MODE", "normal"))
    args["PERFORMANCE_MODE"] = mode if mode in MODES else "normal"
    for key in LITE_ITEMS:
        args[key] = bool(args.get(key, current.get(key, True)))
    return args
