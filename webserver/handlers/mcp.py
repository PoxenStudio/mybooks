#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""
Talebook MCP Multi-Transport Server
"""
import datetime
import logging
import json

from webserver import loader
from webserver.handlers.base import BaseHandler, ListHandler, js
from webserver.version import VERSION

from webserver.mcp.mcp_service import MCPService

CONF = loader.get_settings()

mcp_service = None


def create_mcp_service(base_handler: BaseHandler = None):
    """Create and return a new MCP service instance."""
    global mcp_service
    if mcp_service is None:
        mcp_service = MCPService(base_handler)
    return mcp_service


class MCPHandler(ListHandler):
    @js
    def get(self):
        """Serve MCP client with the current version and settings."""
        response = {
            "err": "ok",
            "version": VERSION,
            "settings": {
                "base_url": CONF.get("base_url", ""),
                "mcp_enabled": CONF.get("mcp_enabled", False),
                "mcp_version": CONF.get("mcp_version", "1.0"),
            },
            "timestamp": datetime.datetime.now().isoformat(),
        }
        self.write(response)

    @js
    def post(self):
        """Handle MCP over HTTP streaming."""
        logging.info("New HTTP stream connection from MCP client")
        mcp_service = create_mcp_service(self)
        try:
            # Read request body
            body = self.request.body
            if not body:
                self.set_status(400)
                return {"err": "params", "msg": "No request body"}

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
        return {"err": "ok", "status": "healthy", "server": "talebook-mcp"}


def routes():
    return [
        (r"/api/mcp/stream", MCPHandler),
        (r"/api/mcp/health", MCPHealthHandler),
    ]
