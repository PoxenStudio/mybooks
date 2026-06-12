#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import os
import re
import sys
from webserver.handlers import static_files
from webserver.i18n import _
from logging.handlers import RotatingFileHandler
import traceback

import tornado.httpserver
import tornado.ioloop
import tornado.log
from tornado.httpclient import AsyncHTTPClient
from social_tornado.models import init_social
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import scoped_session, sessionmaker
from tornado import web
from tornado.options import define, options

from webserver import loader, models, social_routes
from webserver.base.setting_saver import SettingsSaver
from webserver.services import AsyncService
from webserver.services.book_barn import BookBarnService
from webserver.services.item_sync import ItemSyncService
from webserver.constants import COLUMN_CATEGORY, COLUMN_PHY_COUNT, COLUMN_BOOK_TYPE
from webserver.constants import COLUMN_EXT_LINK, CUSTOM_COVER_IMAGE, COLUMN_DYNAMIC_COVER
from webserver.constants import COLUMN_LOCATION
from webserver.version import VERSION

CONF = loader.get_settings()
define("host", default="", type=str, help=_("The host address on which to listen"))
define("port", default=8080, type=int, help=_("The port on which to listen."))
define(
    "path-calibre",
    default="/usr/lib/calibre",
    type=str,
    help=_("Path to calibre package."),
)
define(
    "path-resources",
    default="/usr/share/calibre",
    type=str,
    help=_("Path to calibre resources."),
)
define(
    "path-plugins",
    default="/usr/lib/calibre/calibre/plugins",
    type=str,
    help=_("Path to calibre plugins."),
)
define(
    "path-bin", default="/usr/bin", type=str, help=_("Path to calibre binary programs.")
)
define(
    "with-library",
    default=CONF["with_library"],
    type=str,
    help=_("Path to the library folder"),
)
define("syncdb", default=False, type=bool, help=_("Create all tables"))
define(
    "update-config",
    default=False,
    type=bool,
    help=_("update config when system upgrade"),
)

# Set the maximum memory allocation for Qt image processing to prevent crashes with large images
os.environ["QT_IMAGEIO_MAXALLOC"] = "400"


def drop_old_table_as_needed(session):
    if not session:
        return
    result = session.execute(text("""
        PRAGMA table_info(items)
    """)).fetchall()
    columns = [row[1] for row in result]
    if "scope" not in columns:
        return
    session.execute(text("""
        DROP TABLE items
    """))


def add_meta_in_calibre(calibre_db, key, name, datatype):
    found = False
    for k, v in calibre_db.field_metadata.items():
        if k.startswith("#") and k.lstrip("#") == key:
            found = True
            break
    if found:
        logging.info("No need to create key: [%s] in calibre, already exists." % key)
        return False
    try:
        calibre_db.create_custom_column(label=key, name=name, datatype=datatype, is_multiple=False)
    except Exception as e:
        logging.error(f"Error creating custom field: {e}")
        return False
    return True


def config_calibre():
    from calibre.db.backend import DB

    db = DB(options.with_library)
    if not db:
        return
    if ("expire_old_trash_after" in db.prefs and db.prefs["expire_old_trash_after"] == 7 * 24 * 3600):
        logging.info("Calibre trash expire time already set to 7 days, no need to update.")
        return
    db.prefs["expire_old_trash_after"] = 7 * 24 * 3600
    logging.info("Set calibre trash expire time to 7 days.")


def init_calibre():
    path = options.path_calibre
    if path not in sys.path:
        sys.path.insert(0, path)
    sys.resources_location = options.path_resources
    sys.extensions_location = options.path_plugins
    sys.executables_location = options.path_bin
    try:
        import calibre  # noqa: F401
    except Exception as e:
        logging.error(traceback.format_exc())
        raise ImportError(
            _("Can not import calibre. Please set the corrent options.\n%s" % e)
        )

    if not options.with_library:
        sys.stderr.write(
            _(
                "No saved library path. Use the --with-library option"
                " to specify the path to the library you want to use."
            )
        )
        sys.stderr.write("\n")
        sys.exit(2)
    else:
        logging.info("Using library path: [%s]" % options.with_library)


def safe_filename(filename):
    return re.sub(r"[\/\\\:\*\?\"\<\>\|]", "_", filename)  # 替换为下划线


# the codes is from calibre source code. just change 'ascii_filename' to 'safe_filename'
def utf8_construct_path_name(book_id, title, author):
    from calibre.db.backend import DB, WINDOWS_RESERVED_NAMES

    book_id = " (%d)" % book_id
    lm = DB.PATH_LIMIT - (len(book_id) // 2) - 2
    lm = lm // 4  # UTF8 is 1~4 char
    author = safe_filename(author)[:lm]
    title = safe_filename(title.lstrip())[:lm].rstrip()
    if not title:
        title = "Unknown"[:lm]
    try:
        while author[-1] in (" ", "."):
            author = author[:-1]
    except IndexError:
        author = ""
    if not author:
        author = _("佚名")
    if author.upper() in WINDOWS_RESERVED_NAMES:
        author += "w"
    return "%s/%s%s" % (author, title, book_id)


def utf8_construct_file_name(book_id, title, author, extlen):
    from calibre.db.backend import DB

    extlen = max(extlen, 14)  # 14 accounts for ORIGINAL_EPUB
    lm = (DB.PATH_LIMIT - extlen - 2) // 2
    lm = lm // 4  # UTF8 is 1~4 char
    if lm < 5:
        raise ValueError("Extension length too long: %d" % extlen)
    author = safe_filename(author)[:lm]
    title = safe_filename(title.lstrip())[:lm].rstrip()
    if not title:
        title = "Unknown"[:lm]
    name = title + " - " + author
    while name.endswith("."):
        name = name[:-1]
    if not name:
        name = safe_filename(_("Unknown"))
    return name


def bind_utf8_book_names(cache):
    cache.backend.construct_path_name = utf8_construct_path_name
    cache.backend.construct_file_name = utf8_construct_file_name
    return


def bind_topdir_book_names(cache):
    old_construct_path_name = cache.backend.construct_path_name

    def new_construct_path_name(*args, **kwargs):
        s = old_construct_path_name(*args, **kwargs)
        ns = s[0] + "/" + s
        logging.debug("new str = %s" % ns)
        return ns

    cache.backend.construct_path_name = new_construct_path_name
    return


def configure_plugins():
    """
      1. 配置 Amazon 插件，将 server 选项设置为 'amazon'
      2. 禁用TXT to TXTZ插件，避免不必要的TXT文件处理
    """
    try:
        from calibre.customize.ui import metadata_plugins, disable_plugin, enable_plugin

        for plugin in metadata_plugins({"identify"}):
            if plugin.name == "Amazon.com":
                plugin.prefs["server"] = "amazon"
                break
        if not CONF.get("ENABLE_TXT_TO_TXTZ_PLUGIN", False):
            disable_plugin('TXT to TXTZ')
        else:
            enable_plugin('TXT to TXTZ')
    except Exception as e:
        logging.error("[INIT]Failed to configure plugins: %s" % e)


def make_app():
    auth_db_path = CONF["user_database"]
    logging.info("Revision:: [%s]" % VERSION)
    logging.info("Init library with [%s]" % options.with_library)
    logging.info("Init AuthDB  with [%s]" % auth_db_path)
    logging.info("Init Static  with [%s]" % CONF["resource_path"])
    logging.info("Init HTML    with [%s]" % CONF["html_path"])
    logging.info("Init Nuxtjs  with [%s]" % CONF["nuxt_env_path"])
    banner_width = 90
    border_top = "╭" + "─" * banner_width + "╮"
    border_bottom = "╰" + "─" * banner_width + "╯"
    banner_lines = [
        "",
        border_top,
        "|" + " __  __       ____              _        ".center(banner_width) + "|",
        "|" + "|  \\/  |_   _| __ )  ___   ___ | | _____ ".center(banner_width) + "|",
        "|" + "| |\\/| | | | |  _ \\ / _ \\ / _ \\| |/ / __|".center(banner_width) + "|",
        "|" + "| |  | | |_| | |_) | (_) | (_) |   <\\__ \\".center(banner_width) + "|",
        "|" + "|_|  |_|\\__, |____/ \\___/ \\___/|_|\\_\\___/".center(banner_width) + "|",
        "|" + "        |___/                            ".center(banner_width) + "|",
        "|" + "    ____                                 _____   __                __    _        ".center(banner_width) + "|",
        "|" + "   / __ \\  ____    _  __  ___    ____   / ___/  / /_  __  __  ____/ /   (_)  ____ ".center(banner_width) + "|",
        "|" + "  / /_/ / / __ \\  | |/_/ / _ \\  / __ \\  \\__ \\  / __/ / / / / / __  /   / /  / __ \\".center(banner_width) + "|",
        "|" + " / ____/ / /_/ / _>  <  /  __/ / / / / ___/ / / /_  / /_/ / / /_/ /   / /  / /_/ /".center(banner_width) + "|",
        "|" + "/_/      \\____/ /_/|_|  \\___/ /_/ /_/ /____/  \\__/  \\__,_/  \\__,_/   /_/   \\____/ ".center(banner_width) + "|",
        "|" + (" " * 60 + f"{VERSION}").center(banner_width) + "|",
        border_bottom,
    ]

    if options.update_config:
        logging.info("updating configs ...")
        SettingsSaver().update_nuxtjs_env()
        logging.info("done")
        sys.exit(0)

    # build sql session factory
    engine = create_engine(auth_db_path, **CONF["db_engine_args"])

    if auth_db_path.startswith("sqlite"):
        # Set WAL mode once
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
            logging.info("SQLite journal_mode set to WAL")
        except Exception as e:
            logging.warning(f"Failed to set SQLite WAL mode (falling back to default journal mode): {e}")

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(db_connection, connection_record):
            cursor = db_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout=30000")
            except Exception as e:
                logging.warning(f"Failed to set SQLite busy_timeout: {e}")
            cursor.close()

    ScopedSession = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
    try:
        models.bind_session(ScopedSession)
        init_social(models.Base, ScopedSession, CONF)
    except Exception as e:
        logging.error(f"Error binding session: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)

    if options.syncdb:
        drop_old_table_as_needed(ScopedSession)
        models.user_syncdb(engine)
        logging.info("Create tables into DB")
        sys.exit(0)

    logging.info("\n%s", "\n".join(banner_lines))

    try:
        init_calibre()
        config_calibre()
    except Exception as e:
        logging.error(f"Error initializing calibre: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)

    from calibre import gui2
    from calibre.db.legacy import LibraryDatabase
    from calibre.utils.date import fromtimestamp
    from calibre.ebooks.metadata.sources.update import patch_plugins

    need_sync_item_to_calibre = False
    try:
        logging.info("Initializing library database...")
        book_db = LibraryDatabase(os.path.expanduser(options.with_library))
        cache = book_db.new_api
        try:
            if hasattr(cache.backend, "prefs"):
                cache.backend.prefs.set("fts_enabled", False)
                logging.info("FTS disabled successfully")
        except Exception as e:
            logging.warning(f"Failed to disable FTS: {e}")

        added_category = add_meta_in_calibre(cache, COLUMN_CATEGORY, "Book Category", "text")
        added_phy_count = add_meta_in_calibre(cache, COLUMN_PHY_COUNT, "Physical Book Count", "int")
        added_source = add_meta_in_calibre(cache, COLUMN_BOOK_TYPE, "Book Type", "int")
        added_location = add_meta_in_calibre(cache, COLUMN_LOCATION, "Location", "text")
        _ = add_meta_in_calibre(cache, COLUMN_EXT_LINK, "External Link", "text")
        _ = add_meta_in_calibre(cache, COLUMN_DYNAMIC_COVER, "Dynamic Cover", "int")
        if added_source or added_category or added_phy_count or added_location:
            need_sync_item_to_calibre = True
            book_db = LibraryDatabase(os.path.expanduser(options.with_library))
            cache = book_db.new_api
    except Exception as e:
        logging.error(f"Error initializing library database: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)

    # patch calibre plugins and config amazon plugins
    patch_plugins()
    configure_plugins()

    # hook 1: 按字母作为第一级目录，解决书库子目录太多的问题
    logging.info("Patching calibre book names format...")
    if CONF["BOOK_NAMES_FORMAT"].lower() == "utf8":
        bind_utf8_book_names(cache)
    else:
        bind_topdir_book_names(cache)

    # hook 2: don't force GUI
    logging.info("Patching calibre GUI requirement...")
    old_must_use_qt = gui2.must_use_qt

    def new_must_use_qt(headless=True):
        try:
            old_must_use_qt(headless)
        except Exception:
            pass

    gui2.must_use_qt = new_must_use_qt

    logging.info("Loading default cover image...")
    path = CONF["resource_path"] + "/calibre/default_cover.jpg"
    if os.path.exists(CUSTOM_COVER_IMAGE):
        path = CUSTOM_COVER_IMAGE
    with open(path, "rb") as cover_file:
        default_cover = cover_file.read()

    # Initialize database lock for thread-safe calibre database access
    import threading
    from webserver.handlers.base import BaseHandler

    BaseHandler.db_lock = threading.RLock()

    app_settings = dict(CONF)
    app_settings.update({
        "legacy": book_db,
        "cache": cache,
        "ScopedSession": ScopedSession,
        "build_time": fromtimestamp(os.stat(path).st_mtime),
        "default_cover": default_cover,
        "autoreload": VERSION == "v0.0.1",
    })

    is_upgrade = CONF.get("installed_version", "") != VERSION
    logging.info(f"The installed version is {CONF.get("installed_version", "NONE")}, {"" if is_upgrade else "no"} need to check or upgrade table structure.")
    need_sync_item_time = AsyncService().setup(book_db, ScopedSession, need_check_db=is_upgrade)
    if is_upgrade and CONF.get("installed", False):
        SettingsSaver().save_extra_settings(CONF)

    logging.info("Now, Running...")
    # WebDAV route is always registered; the handler checks ENABLE_WEBDAV_SERVICE at
    # request time and lazily initialises the WSGI app on first use.
    from webserver.webdav.handler import WebDAVHandler
    webdav_routes = [
        (r"/books/?(.*)", WebDAVHandler, dict(cache=cache, session=ScopedSession)),
    ]

    # Assemble routes carefully:
    # WebDAV must come before files.routes() because files has a catch-all (r"/(.*)")
    # We need to get routes from handlers module without files, add webdav, then add files
    from webserver.handlers import assistant, mcp, admin, barcode, scan, opds, book, user, meta, audio, toolbox

    app_routes = []
    app_routes += social_routes.SOCIAL_AUTH_ROUTES
    app_routes += assistant.routes()
    app_routes += mcp.routes()
    app_routes += admin.routes()
    app_routes += barcode.routes()
    app_routes += scan.routes()
    app_routes += opds.routes()
    app_routes += book.routes()
    app_routes += user.routes()
    app_routes += meta.routes()
    app_routes += audio.routes()
    app_routes += toolbox.routes()

    # Podcast routes are always registered; each handler calls check_podcast_enabled()
    # at request time, so toggling ENABLE_PODCAST_SERVICE takes effect without restart.
    from webserver.handlers.podcast import routes as podcast_route_func
    app_routes += podcast_route_func()

    # WAP routes: server-side rendered HTML pages for Kindle browsers.
    # Must be registered BEFORE static_files.routes() so they take precedence
    # over the Vue SPA assets served at /wap/*.
    from webserver.handlers import wap as wap_handler
    app_routes += wap_handler.routes()

    # Insert WebDAV routes BEFORE files.routes()
    app_routes += webdav_routes
    # files.routes() contains catch-all r"/(.*)" so must be last
    app_routes += static_files.routes()

    app = web.Application(app_routes, **app_settings)
    app._engine = engine

    # Start background service
    BookBarnService().get_daily_books()

    # Automatically start AI Assistant if configured
    if CONF.get("AI_DEEPSEEK_API_KEY"):
        from webserver.handlers.assistant import AssistantWebSocketHandler
        from webserver.assistant.ai_assistant_agent import AIAssistantMCPAgent

        def init_ai_agent():
            agent = AIAssistantMCPAgent()
            AssistantWebSocketHandler._agent = agent
            # Note: initialization will happen on first connection or we can trigger it here
            # But deepseek_agent.initialize() is async, so we need to run it in the ioloop
            tornado.ioloop.IOLoop.current().spawn_callback(agent.initialize)

        init_ai_agent()

    # Start item create_time sync service if needed
    if need_sync_item_time:
        logging.info("Starting item create_time sync service")
        ItemSyncService().sync_item_create_time()
    if need_sync_item_to_calibre:
        logging.info("Starting item to calibre sync service")
        ItemSyncService().sync_items_to_calibre()

    # Start performance profiling service if enabled
    from webserver.constants import ENABLE_PROFILE

    if CONF.get(ENABLE_PROFILE) is True:
        from webserver.services.profile_service import get_profile_service
        profile_service = get_profile_service()
        profile_service.start()

    if CONF.get("CALIBRE_CACHE_CLEAN_ENABLED", True):
        from webserver.services.calibre_cache_clean import get_cache_clean_service
        cache_clean_service = get_cache_clean_service()
        cache_clean_service.setup(cache)
        cache_clean_service.start()

    if CONF.get("IMPORT_BY_INOTIFY", False):
        from webserver.services.monitor_service import get_monitor_service
        get_monitor_service().start()

    return app


def get_upload_size():
    n = 1
    s = CONF["MAX_UPLOAD_SIZE"].lower().strip()
    if s.endswith("k") or s.endswith("kb"):
        n = 1024
        s = s.split("k")[0]
    elif s.endswith("m") or s.endswith("mb"):
        n = 1024 * 1024
        s = s.split("m")[0]
    elif s.endswith("g") or s.endswith("gb"):
        n = 1024 * 1024 * 1024
        s = s.split("g")[0]
    s = s.strip()
    return int(s) * n


def setup_logging():
    logger = logging.getLogger()
    log_level = logging.DEBUG if CONF.get("LOG_LEVEL_DEBUG", False) or VERSION == "v0.0.1" else logging.INFO
    if options.log_file_prefix:
        # remove tornado default file handler to avoid duplicate logs
        logger.handlers = [h for h in logger.handlers if not isinstance(h, logging.FileHandler)]
        file_handler = RotatingFileHandler(options.log_file_prefix, maxBytes=5 * 1024 * 1024, backupCount=5)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(tornado.log.LogFormatter())
        logger.addHandler(file_handler)
    logger.setLevel(log_level)
    logging.debug("**Debug logging is enabled.**")


def main():
    tornado.options.parse_command_line()
    setup_logging()

    # 配置异步 HTTP 客户端的最大连接数
    AsyncHTTPClient.configure(None, max_clients=200)

    try:
        app = make_app()
    except Exception as e:
        logging.error(f"Error making app: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)

    logging.info("Starting server...")
    logging.debug("Max upload size set to: %d bytes", get_upload_size())
    http_server = tornado.httpserver.HTTPServer(app, xheaders=True, max_buffer_size=get_upload_size())
    http_server.listen(options.port, options.host)
    tornado.ioloop.IOLoop.instance().start()

    from flask.ext.sqlalchemy import _EngineDebuggingSignalEvents
    _EngineDebuggingSignalEvents(app._engine, app.import_name).register()


if __name__ == "__main__":
    sys.path.append(os.path.dirname(__file__))
    sys.exit(main())
