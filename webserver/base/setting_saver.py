import logging
import os
import time
import traceback
import threading


from webserver import loader
from webserver.i18n import _
from webserver.version import VERSION

CONF = loader.get_settings()


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
            target=_delayed_restart, name="talebook-restart", daemon=True
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
