#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import os
import re
import sys
from gettext import gettext as _
import traceback

import tornado.httpserver
import tornado.ioloop
import tornado.log
from social_tornado.models import init_social
from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker
from tornado import web
from tornado.options import define, options

from webserver import loader, models, social_routes
from webserver.services import AsyncService
from webserver.services.book_barn import BookBarnService
from webserver.services.item_sync import ItemSyncService

CONF = loader.get_settings()
define("host", default="", type=str, help=_("The host address on which to listen"))
define("port", default=8080, type=int, help=_("The port on which to listen."))
define("path-calibre", default="/usr/lib/calibre", type=str, help=_("Path to calibre package."))
define("path-resources", default="/usr/share/calibre", type=str, help=_("Path to calibre resources."))
define("path-plugins", default="/usr/lib/calibre/calibre/plugins", type=str, help=_("Path to calibre plugins."))
define("path-bin", default="/usr/bin", type=str, help=_("Path to calibre binary programs."))
define("with-library", default=CONF["with_library"], type=str, help=_("Path to the library folder"))
define("syncdb", default=False, type=bool, help=_("Create all tables"))
define("update-config", default=False, type=bool, help=_("update config when system upgrade"))

CATEGORY_KEY = "category"


def add_category_meta_in_calibre(calibre_db):
    found = False
    for key, meta in calibre_db.field_metadata.items():
        if key.startswith('#') and key.lstrip('#') == CATEGORY_KEY:
            found = True
            break
    if found:
        logging.info("No need to create category key")
        return False
    try:
        calibre_db.create_custom_column(
            label=CATEGORY_KEY,
            name='Book Category',
            datatype='text',
            is_multiple=False
        )
    except Exception as e:
        logging.error(f"Error creating custom field: {e}")
        return False
    return True


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
        import traceback
        logging.error(traceback.format_exc())
        raise ImportError(_("Can not import calibre. Please set the corrent options.\n%s" % e))

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
        author = safe_filename(_("Unknown"))
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


def make_app():
    auth_db_path = CONF["user_database"]
    logging.debug("Init library with [%s]" % options.with_library)
    logging.debug("Init AuthDB  with [%s]" % auth_db_path)
    logging.debug("Init Static  with [%s]" % CONF["resource_path"])
    logging.debug("Init HTML    with [%s]" % CONF["html_path"])
    logging.debug("Init Nuxtjs  with [%s]" % CONF["nuxt_env_path"])

    if options.update_config:
        logging.info("updating configs ...")
        # 触发一次空白配置更新
        from webserver.handlers.admin import SettingsSaverLogic
        logic = SettingsSaverLogic()
        logic.update_nuxtjs_env()
        logging.info("done")
        sys.exit(0)

    # build sql session factory
    engine = create_engine(auth_db_path, **CONF["db_engine_args"])

    if auth_db_path.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(db_connection, connection_record):
            cursor = db_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=30000")
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
        models.user_syncdb(engine)
        logging.info("Create tables into DB")
        sys.exit(0)

    try:
        init_calibre()
    except Exception as e:
        logging.error(f"Error initializing calibre: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)

    from calibre.db.legacy import LibraryDatabase
    from calibre.utils.date import fromtimestamp

    try:
        logging.info("Initializing library database...")
        book_db = LibraryDatabase(os.path.expanduser(options.with_library))
        cache = book_db.new_api
        if add_category_meta_in_calibre(cache):
            book_db = LibraryDatabase(os.path.expanduser(options.with_library))
            cache = book_db.new_api
    except Exception as e:
        logging.error(f"Error initializing library database: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)

    # hook 1: 按字母作为第一级目录，解决书库子目录太多的问题
    logging.info("Patching calibre book names format...")
    if CONF["BOOK_NAMES_FORMAT"].lower() == "utf8":
        bind_utf8_book_names(cache)
    else:
        bind_topdir_book_names(cache)

    # hook 2: don't force GUI
    logging.info("Patching calibre GUI requirement...")
    from calibre import gui2
    old_must_use_qt = gui2.must_use_qt

    def new_must_use_qt(headless=True):
        try:
            old_must_use_qt(headless)
        except Exception:
            pass
    gui2.must_use_qt = new_must_use_qt

    logging.info("Loading default cover image...")
    path = CONF["resource_path"] + "/calibre/default_cover.jpg"
    with open(path, "rb") as cover_file:
        default_cover = cover_file.read()

    # Initialize database lock for thread-safe calibre database access
    import threading
    from webserver.handlers.base import BaseHandler
    BaseHandler.db_lock = threading.RLock()
    logging.info("Database lock initialized")

    app_settings = dict(CONF)
    app_settings.update(
        {
            "legacy": book_db,
            "cache": cache,
            "ScopedSession": ScopedSession,
            "build_time": fromtimestamp(os.stat(path).st_mtime),
            "default_cover": default_cover,
        }
    )

    logging.info("Now, Running...")
    need_sync_item_time = AsyncService().setup(book_db, ScopedSession)

    # Initialize WebDAV service
    from webserver.webdav.server import create_webdav_app
    from webserver.webdav.handler import WebDAVHandler

    try:
        logging.info("Initializing WebDAV service on /books path...")
        webdav_app = create_webdav_app(cache, ScopedSession)

        # Create routes with WebDAV at /books/*
        webdav_routes = [
            (r"/books/?(.*)", WebDAVHandler, dict(wsgi_app=webdav_app)),
        ]
        logging.info("WebDAV service initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize WebDAV service: {e}")
        import traceback
        logging.error(traceback.format_exc())
        webdav_routes = []

    # Assemble routes carefully:
    # WebDAV must come before files.routes() because files has a catch-all (r"/(.*)")
    # We need to get routes from handlers module without files, add webdav, then add files
    from webserver.handlers import assistant, mcp, admin, barcode, scan, opds, book, user, meta, audio, files

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
    # Insert WebDAV routes BEFORE files.routes()
    app_routes += webdav_routes
    # files.routes() contains catch-all r"/(.*)" so must be last
    app_routes += files.routes()

    app = web.Application(app_routes, **app_settings)
    app._engine = engine

    # Start background service
    BookBarnService().get_daily_books()

    # Automatically start AI Assistant if configured
    if CONF.get("AI_DEEPSEEK_API_KEY"):
        logging.info("DeepSeek API Key found. Initializing AI Assistant...")
        from webserver.handlers.assistant import AssistantWebSocketHandler
        from webserver.assistant.deepseek_agent import DeepSeekMCPAgent

        def init_ai_agent():
            agent = DeepSeekMCPAgent()
            AssistantWebSocketHandler._agent = agent
            # Note: initialization will happen on first connection or we can trigger it here
            # But deepseek_agent.initialize() is async, so we need to run it in the ioloop
            tornado.ioloop.IOLoop.current().spawn_callback(agent.initialize)

        init_ai_agent()

    # Start item create_time sync service if needed
    if need_sync_item_time:
        logging.info("Starting item create_time sync service")
        ItemSyncService().sync_item_create_time()

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
    # tornado 的 默认log 已在supervisor中配置为file了，这里再增加一个console的
    # 创建控制台处理程序并设置格式
    logger = logging.getLogger()
    if options.log_file_prefix:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(tornado.log.LogFormatter())
        logger.addHandler(console_handler)


def main():
    tornado.options.parse_command_line()
    setup_logging()
    try:
        app = make_app()
    except Exception as e:
        logging.error(f"Error making app: {e}")
        logging.error(traceback.format_exc())
        sys.exit(1)

    logging.info("Starting server...")
    http_server = tornado.httpserver.HTTPServer(app, xheaders=True, max_buffer_size=get_upload_size())
    http_server.listen(options.port, options.host)
    tornado.ioloop.IOLoop.instance().start()
    from flask.ext.sqlalchemy import _EngineDebuggingSignalEvents

    _EngineDebuggingSignalEvents(app._engine, app.import_name).register()


if __name__ == "__main__":
    sys.path.append(os.path.dirname(__file__))
    sys.exit(main())
