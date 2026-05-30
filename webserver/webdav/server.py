# -*- coding: UTF-8 -*-
import logging
from wsgidav.wsgidav_app import WsgiDAVApp
from .dav_provider import MyBooksDavProvider
from webserver import loader


CONF = loader.get_settings()


def create_webdav_app(calibre_cache, sqlite_session):
    """
    Create and configure WsgiDAV application.

    Args:
        calibre_cache: Calibre library cache (new_api)
        sqlite_session: SQLAlchemy scoped session for user authentication

    Returns:
        WsgiDAVApp instance configured
    """

    # Create a function to get session
    def get_session():
        return sqlite_session()

    # Create the custom provider with session function
    provider = MyBooksDavProvider(calibre_cache, get_session_func=get_session)

    # Configure WsgiDAV with v4.x configuration format
    # Use module path for domain controller
    config = {
        "host": "0.0.0.0",
        "port": 8080,
        "app_title": "PoxenStudio/MyBooks",
        "provider_mapping": {
            "/books": provider,
        },
        "http_authenticator": {
            # Pass the module path as string so WsgiDAV can import it
            "domain_controller": "webserver.webdav.auth.TalebookDomainController",
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        },
        "verbose": 1,
        "logging": {
            "enable_loggers": [],
        },
        "property_manager": True,
        "lock_storage": True,
        # Customize directory browser appearance
        "dir_browser": {
            "icon": False,  # Hide default logo.png
            "davmount": False,  # Disable MS Office mount helper
            "ms_sharepoint_support": False,
            "ignore": [".DS_Store", "Thumbs.db", "._*"],
            "show_user": True,
            "show_logout": True,
            "htdocs_path": CONF["resource_path"] + "/webdav/",
        },
        # Store sqlite_session in config for domain controller to access
        "talebook_session": sqlite_session,
    }

    # 猴子补丁：覆盖 WsgiDavDirBrowser._get_context 恢复原始顺序
    from wsgidav.dir_browser._dir_browser import WsgiDavDirBrowser

    if not getattr(WsgiDavDirBrowser, "_patched_for_order", False):
        original_get_context = WsgiDavDirBrowser._get_context

        def custom_get_context(self, environ, dav_res):
            context = original_get_context(self, environ, dav_res)
            # dav_res.get_member_list() 会返回未被破坏的原始列表（ID倒序）
            if hasattr(dav_res, "get_member_list") and context.get("rows"):
                original_names = [
                    m.get_display_name() for m in dav_res.get_member_list()
                ]
                name_to_row = {row["display_name"]: row for row in context["rows"]}

                # 按照 original_names 重新组装 rows
                sorted_rows = []
                for name in original_names:
                    if name in name_to_row:
                        sorted_rows.append(name_to_row[name])

                # 保持原有的逻辑：目录排前面，文件排后面
                dirs = [r for r in sorted_rows if r.get("is_collection")]
                files = [r for r in sorted_rows if not r.get("is_collection")]
                context["rows"] = dirs + files

            return context

        WsgiDavDirBrowser._get_context = custom_get_context
        WsgiDavDirBrowser._patched_for_order = True

    logging.info("Creating WebDAV application with WsgiDAV v4.x configuration")
    app = WsgiDAVApp(config)

    return app
