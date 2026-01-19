# -*- coding: UTF-8 -*-
import logging
from tornado.web import RequestHandler
from tornado.wsgi import WSGIContainer


class WebDAVHandler(RequestHandler):
    """
    Tornado request handler to bridge WebDAV WSGI app.
    支持WebDAV查询、下载和写入操作（sync目录可写）。
    """

    # Add WebDAV methods to supported methods list
    SUPPORTED_METHODS = RequestHandler.SUPPORTED_METHODS + (
        'PROPFIND',    # 查询文件/目录属性
        'MKCOL',       # 创建目录
    )

    def initialize(self, wsgi_app):
        """
        Initialize the handler with a WSGI application.

        Args:
            wsgi_app: WsgiDAV application instance
        """
        self.wsgi_container = WSGIContainer(wsgi_app)

    def prepare(self):
        """Called before any HTTP method handler."""
        # Handle collection URL without trailing slash - redirect to add slash
        request_path = self.request.path
        if (request_path == "/books"
            or (request_path.startswith("/books/")
                and not request_path.endswith("/")
                and self.request.method == "GET")):
            # Check if this might be a collection (directory)
            # For /books specifically, always redirect
            if request_path == "/books":
                self.redirect(request_path + "/", permanent=False)
                self._finished = True
                return

        self._handle_request()
        self._finished = True

    def _handle_request(self):
        """Delegate the request to the WSGI application."""
        # Create WSGI environ from Tornado request
        try:
            self.wsgi_container(self.request)
        except Exception as e:
            logging.error(f"WebDAV handler error: {e}")
            import traceback
            logging.error(traceback.format_exc())
            self.set_status(500)
            self.finish("Internal Server Error")

    # Support all HTTP methods used by WebDAV (read-only)
    def get(self, *args, **kwargs):
        pass  # Handled in prepare()

    def head(self, *args, **kwargs):
        pass

    def options(self, *args, **kwargs):
        pass

    def propfind(self, *args, **kwargs):
        """WebDAV PROPFIND method - 查询文件/目录属性"""
        pass

    def mkcol(self, *args, **kwargs):
        """WebDAV MKCOL method - 创建目录"""
        pass

    def put(self, *args, **kwargs):
        """HTTP PUT method - 上传文件"""
        pass

    def delete(self, *args, **kwargs):
        """HTTP DELETE method - 删除文件/目录"""
        pass


def setup_webdav_handler(wsgi_app):
    """
    Create a Tornado request handler configured with the WebDAV WSGI app.

    Args:
        wsgi_app: WsgiDAV application instance

    Returns:
        Configured handler class
    """
    return lambda: WebDAVHandler(wsgi_app=wsgi_app)
