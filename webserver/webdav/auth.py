# -*- coding: UTF-8 -*-
import logging
# from wsgidav.dc.base_dc import BaseDomainController # This import is no longer needed


class TalebookDomainController:
    """
    Custom authentication controller for WebDAV service.
    Uses the same authentication mechanism as user.SignIn.

    Implements the WsgiDAV DomainController interface without inheritance.
    """

    def __init__(self, wsgidav_app, config):
        """
        Initialize domain controller.

        Args:
            wsgidav_app: The WsgiDAV application instance
            config: Configuration dictionary
        """
        # Get the sqlite_session from config
        self.sqlite_session = config.get('talebook_session', None)
        if not self.sqlite_session:
            logging.error("DomainController: sqlite_session not found in config")

    def require_authentication(self, realm, environ):
        """Return True to require authentication for this path."""
        return True

    def basic_auth_user(self, realm, user_name, password, environ):
        """
        Validate user credentials.
        Returns True if authentication succeeds, False otherwise.

        Uses the same logic as webserver.handlers.user.SignIn
        """
        from webserver.models import Reader

        try:
            username = user_name.strip().lower()
            password = password.strip()

            if not username or not password:
                logging.warning("WebDAV auth failed: empty username or password")
                return False

            # Query user from database
            user = self.sqlite_session().query(Reader).filter(
                Reader.username == username
            ).first()

            if not user:
                logging.warning(f"WebDAV auth failed: user '{username}' not found")
                return False

            # Verify password using the same method as SignIn
            if user.get_secure_password(password) != user.password:
                logging.warning(f"WebDAV auth failed: invalid password for user '{username}'")
                return False

            # Check if user can login
            if not user.can_login():
                logging.warning(f"WebDAV auth failed: user '{username}' cannot login")
                return False

            logging.info(f"WebDAV auth success: user '{username}'")
            # Store user info in environ for later use
            environ["talebook.user"] = user
            return True

        except Exception as e:
            logging.error(f"WebDAV authentication error: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False

    def supports_http_digest_auth(self):
        """We only support Basic Auth for simplicity"""
        return False

    def get_domain_realm(self, path_info, environ):
        """Return the realm for the given path."""
        return "MyBooks WebDAV"

    def is_share_anonymous(self, share):
        """Return True if the share allows anonymous access."""
        return False

    def auth_domain_user(self, realm, user_name, environ):
        """
        Called to check if user_name is a valid user.
        Return True if user exists.
        """
        from webserver.models import Reader

        try:
            username = user_name.strip().lower()
            user = self.sqlite_session().query(Reader).filter(
                Reader.username == username
            ).first()
            return user is not None
        except Exception:
            return False
