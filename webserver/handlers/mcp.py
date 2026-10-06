#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
(PoxenStudio)MyBooks MCP Multi-Transport Server
"""
import datetime
import logging
import json

from webserver import loader
from webserver.handlers.base import BaseHandler, ListHandler, js
from webserver.i18n import _
from webserver.version import VERSION


CONF = loader.get_settings()


class MCPHandler(ListHandler):
    mcp_service_single = None
    mcp_service_with_token = None
    last_service_token = None

    @classmethod
    def create_mcp_service(cls, base_handler: BaseHandler = None, token: str = None):
        """
        Create and return a new MCP service instance.
        Different instances are created based on whether a token is provided.
        """
        from webserver.mcp.mcp_service import MCPService
        if token is None or token == "":
            if cls.mcp_service_single is None:
                cls.mcp_service_single = MCPService(base_handler, token=token)
            service = cls.mcp_service_single
        elif cls.last_service_token is not None and token == cls.last_service_token \
                and cls.mcp_service_with_token is not None:
            service = cls.mcp_service_with_token
        else:
            cls.mcp_service_with_token = MCPService(base_handler, token=token)
            cls.last_service_token = token
            service = cls.mcp_service_with_token
        # 服务实例被复用，但 handler 是每个请求独立的（request/session 等），需更新为当前请求
        if base_handler is not None:
            service.base_handler = base_handler
        return service

    @js
    def get(self):
        """Serve MCP client with the current version and settings."""
        response = {
            "err": "ok",
            "version": VERSION,
            "settings": {
                "base_url": CONF.get("base_url", ""),
                "mcp_version": CONF.get("mcp_version", VERSION),
            },
            "timestamp": datetime.datetime.now().isoformat(),
        }
        self.write(response)

    @js
    def post(self):
        """Handle MCP over HTTP streaming."""
        logging.info("New HTTP stream connection from MCP client")
        # get token parameter from query string
        token = self.get_argument("token", None)
        mcp_service = self.create_mcp_service(self, token=token)
        try:
            # Read request body
            body = self.request.body
            if not body:
                self.set_status(400)
                return {"err": "params", "msg": _("No request body")}

            request_data = json.loads(body)
            logging.info(f"HTTP stream request: {request_data}")

            response = mcp_service.handle_request(request_data)
            return response

        except Exception as e:
            logging.error(f"Error in HTTP stream handler: {e}")
            self.set_status(500)
            return {
                "err": "ok",
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(e)}
            }


class MCPHealthHandler(BaseHandler):
    @js
    def get(self):
        return {"err": "ok", "status": "healthy", "server": "mybooks-mcp"}


def routes():
    return [
        (r"/api/mcp/stream", MCPHandler),
        (r"/api/mcp/health", MCPHealthHandler),
    ]
