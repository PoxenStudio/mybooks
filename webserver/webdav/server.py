# -*- coding: UTF-8 -*-
import logging
from wsgidav.wsgidav_app import WsgiDAVApp
from .dav_provider import TalebookProvider

def create_webdav_app(calibre_cache, sqlite_session):
    """
    Create and configure WsgiDAV application for Talebook.

    Args:
        calibre_cache: Calibre library cache (new_api)
        sqlite_session: SQLAlchemy scoped session for user authentication

    Returns:
        WsgiDAVApp instance configured for Talebook
    """

    # Create a function to get session
    def get_session():
        return sqlite_session()

    # Create the custom provider with session function
    provider = TalebookProvider(calibre_cache, get_session_func=get_session)


    # Configure WsgiDAV with v4.x configuration format
    # Use module path for domain controller
    config = {
        "host": "0.0.0.0",
        "port": 8080,
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
        # Store sqlite_session in config for domain controller to access
        "talebook_session": sqlite_session,
    }

    logging.info("Creating WebDAV application with WsgiDAV v4.x configuration")
    app = WsgiDAVApp(config)

    return app
