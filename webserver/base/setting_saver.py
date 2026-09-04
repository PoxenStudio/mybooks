import logging
import os
import time
import traceback
import threading


from webserver import loader
from webserver.i18n import _
from webserver.version import VERSION

CONF = loader.get_settings()

# Keys that AdminSettings (app/src/pages/admin/settings.vue) persists to auto.py.
# Kept in sync with the `KEYS` whitelist in webserver.handlers.admin.AdminSettings.post —
# anything outside this set (e.g. computed path settings) must never be written to auto.py.
PERSISTABLE_KEYS = frozenset({
    "ALLOW_GUEST_DOWNLOAD", "ALLOW_GUEST_PUSH", "ALLOW_GUEST_READ", "ALLOW_GUEST_UPLOAD",
    "ALLOW_REGISTER", "BOOK_NAMES_FORMAT", "BOOK_NAV", "EPUB_VIEWER", "FRIENDS", "FOOTER",
    "FOOTER_WATERMARK", "HIDE_PROJECT_LINKS", "HEADER", "INVITE_CODE", "INVITE_MESSAGE",
    "INVITE_MODE", "MAX_UPLOAD_SIZE", "CHUNK_UPLOAD_SIZE", "RESET_MAIL_CONTENT", "RESET_MAIL_TITLE",
    "SIGNUP_MAIL_CONTENT", "SIGNUP_MAIL_TITLE", "SOCIALS", "autoreload", "cookie_secret",
    "scan_upload_path", "convert_timeout", "douban_apikey", "douban_baseurl", "douban_max_count",
    "auto_fill_meta", "push_title", "push_content", "site_title", "smtp_password", "smtp_server",
    "smtp_username", "smtp_encryption", "static_host", "xsrf_cookies", "settings_path",
    "avatar_service", "google_analytics_id", "site_language", "site_theme", "site_icon",
    "ENABLE_BOOKBARN", "ENABLE_PHYSICAL_BOOKS", "BOOKBARN_COLLECTION_HOUR", "BOOKBARN_TOKEN",
    "ENABLE_RECEIVING_BOOKS", "USE_BOOKBARN_PROXY", "BOOK2AUDIO_PROXY", "LAST_REVISION", "DEVICES",
    "AI_ENABLED", "AI_MODEL", "AI_MCP_TOKEN", "AI_DEEPSEEK_API_KEY", "AI_API_URL",
    "AI_ALLOW_SET_CATEGORY",
    "MAIN_PAGE_RANDOM_COUNT", "MAIN_PAGE_RECENT_COUNT", "INDEX_PAGE_TYPE", "DEFAULT_PAGE_SIZE",
    "ENABLE_WEBDAV_SERVICE", "WEBDAV_SYNC_FOLDER", "ENABLE_AUDIO_CONVERSION_LOG",
    "ENABLE_OPDS_SERVICE", "ENABLE_OPDS_AUTH", "ENABLE_PODCAST_SERVICE", "META_SELECTED_SOURCES",
    "PDF_TILE_WITH_FILE_NAME", "ALLOW_NEW_USER_MANAGE_BOOK", "ALLOW_NEW_USER_PUSH_BOOK",
    "ALLOW_READ_RANGE_SETTING", "DEFAULT_READ_RANGE", "ENABLE_AUTO_NEW_USER_APPROVAL", "IMPORT_BY_INOTIFY",
    "IMPORT_CATEGORY_WITH_FOLDER", "REMOVE_IMPORTED_FILE", "UPDATE_CATEGORY_WITH_FOLDER_RENAME",
    "LOG_LEVEL_DEBUG", "ENABLE_STAMP_FEATURE", "STAMP_POSITION", "ENABLE_TXT_TO_TXTZ_PLUGIN",
    "SEND_MAIL_FOR_NEW_BOOKS", "USE_DYNAMIC_COVER", "BATCH_ADD_IN_FORCE", "DEFAULT_LANGUAGE",
    "ENABLE_DATA_SYNC", "ENABLE_AUTHOR_INFO", "ALLOW_USER_DISABLE_STATISTIC",
    "ENABLE_HOMEPAGE_READING_STATS", "ENABLE_HOMEPAGE_READING_BOOKS",
    "ENABLE_BOOK_REVIEW", "REVIEW_REQUIRES_APPROVAL", "ENABLE_BOOK_RECOMMEND_TO_OTHERS", "ENABLE_SHARED_NOTES",
    "ENABLE_TOOLBOX_DEV_MODE", "ENABLE_TOOLBOX_STORE", "AUTO_CHECKING_NEW_VERSION",
})


class SettingsSaver:
    # Settings that are read once at process startup and therefore require a
    # server restart before changes take effect.  Everything else in KEYS is
    # read dynamically from CONF on every request, so no restart is needed.
    RESTART_REQUIRED_KEYS = frozenset({
        "cookie_secret",              # Tornado cookie signing – set at app startup
        "xsrf_cookies",               # Tornado XSRF protection – set at app startup
        "static_host",                # Passed to web.Application via app_settings at startup
        "MAX_UPLOAD_SIZE",            # HTTPServer max_buffer_size computed at startup
        "BOOK_NAMES_FORMAT",          # Calibre path-naming hook applied at startup
        "ENABLE_TXT_TO_TXTZ_PLUGIN",  # Calibre plugin enabled/disabled at startup
        "LOG_LEVEL_DEBUG",            # Logging level configured in setup_logging() at startup
    })

    def _check_restart_needed(self, args):
        """Return True if any setting that requires a restart has actually changed."""
        for key in self.RESTART_REQUIRED_KEYS:
            if key in args and args.get(key) != CONF.get(key):
                logging.info("Restart required due to changed setting: %s", key)
                return True
        return False

    def _apply_dynamic_settings(self, args):
        """Apply side effects for settings that take effect at runtime without restart."""
        # IMPORT_BY_INOTIFY: start or stop the file-system monitor service on the fly.
        if "IMPORT_BY_INOTIFY" in args:
            from webserver.services.monitor_service import MonitorService
            if CONF.get("IMPORT_BY_INOTIFY", False):
                MonitorService().start()
            else:
                MonitorService().stop()

        # ENABLE_WEBDAV_SERVICE or WEBDAV_SYNC_FOLDER changed: discard the cached
        # WSGI app so it is recreated with up-to-date settings on the next request.
        if "ENABLE_WEBDAV_SERVICE" in args or "WEBDAV_SYNC_FOLDER" in args:
            try:
                from webserver.webdav.handler import WebDAVHandler
                WebDAVHandler.reset_app()
            except Exception:
                logging.error(traceback.format_exc())

    def restart_async(self):
        def _delayed_restart():
            try:
                # 留一点时间给当前请求把响应写回客户端
                time.sleep(0.3)
                logging.info("Triggering async restart by exiting current process")
            except Exception:
                logging.error(traceback.format_exc())
            finally:
                # 退出当前进程，由 supervisor/docker 的 autorestart 拉起新进程
                os._exit(0)

        threading.Thread(
            target=_delayed_restart, name="mybooks-restart", daemon=True
        ).start()

    def update_nuxtjs_env(self):
        # update nuxtjs .env file
        nuxtjs_env = (
            """
TITLE="%(site_title)s"
TITLE_TEMPLATE="%%s | %(site_title)s"
"""
            % CONF
        )

        if len(CONF.get("google_analytics_id", "").strip()) > 0:
            logging.debug("google_analytics_id is %s" % CONF.get("google_analytics_id", ""))
            nuxtjs_env += "GOOGLE_ANALYTICS_ID=%s\n" % CONF["google_analytics_id"]

        with open(CONF["nuxt_env_path"], "w", encoding="utf-8") as f:
            f.write(nuxtjs_env)

    def save_partial(self, overrides: dict) -> dict:
        """Persist a small set of settings changes without wiping unrelated
        settings previously saved to auto.py.

        Seeds the args with every currently-active persistable setting from
        CONF, then applies ``overrides`` on top, so keys untouched by the
        caller keep their existing value in auto.py instead of disappearing.
        """
        args = loader.SettingsLoader()
        args.clear()
        for key, val in CONF.items():
            if key in PERSISTABLE_KEYS or key.startswith("SOCIAL_AUTH"):
                args[key] = val
        args.update(overrides)
        return self.save_extra_settings(args)

    def save_extra_settings(self, args):
        # Must check before CONF.update() so we can compare old vs. new values.
        restart_needed = self._check_restart_needed(args)

        if args != CONF:
            CONF.update(args)

        try:
            self.update_nuxtjs_env()
        except Exception:
            logging.error(traceback.format_exc())
            return {
                "err": "file.permission",
                "msg": _("更新配置文件失败！请确保文件的权限为可写入！"),
            }

        args["installed"] = True
        args["installed_version"] = VERSION
        try:
            args.dumpfile()
        except Exception:
            logging.error(traceback.format_exc())
            return {
                "err": "file.permission",
                "msg": _("更新磁盘配置文件失败！请确保配置文件的权限为可写入！"),
            }

        CONF["installed"] = True
        self._apply_dynamic_settings(args)
        if CONF.get("autoreload", False):
            if restart_needed:
                # 异步执行重启命令，避免阻塞当前请求
                self.restart_async()
                return {"err": "ok", "msg": _("保存成功！可能需要5~10秒钟生效！")}
            else:
                return {"err": "ok", "rsp": CONF, "msg": _("设置已保存！")}
        else:
            return {"err": "ok", "rsp": CONF, "msg": _("设置已保存，请重启服务生效！")}
