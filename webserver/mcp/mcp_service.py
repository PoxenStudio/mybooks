#!/usr/bin/env python3
"""
MCP Service Module

统一处理MCP协议请求的服务模块，供不同传输协议调用。
"""

import logging
import uuid
from typing import Any, Sequence, Dict, Optional

from mcp.server import Server
from mcp.types import Tool, TextContent


class MCPService:
    """MCP协议处理服务类"""

    def __init__(self):
        """初始化MCP服务"""
        self.server = Server("talebook-mcp")
        self._setup_tools()

    def _setup_tools(self):
        """设置工具定义"""
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools."""
            return [
                Tool(
                    name="get_books_count",
                    description="Get the current count of books in the collection",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Sequence[TextContent]:
            """Handle tool calls."""
            if name == "get_books_count":
                return await self.get_books_count(arguments or {})
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def get_books_count(self, arguments: dict[str, Any]) -> Sequence[TextContent]:
        """Get the current count of books in the collection."""
        try:
            books_count = 1
            result = f"Current books count: {books_count}"
            logging.info(f"Books count requested, returning: {books_count}")
            return [TextContent(type="text", text=result)]
        except Exception as e:
            error_msg = f"Error getting books count: {str(e)}"
            logging.error(error_msg)
            return [TextContent(type="text", text=error_msg)]

    async def list_tools(self) -> list[Tool]:
        """获取可用工具列表"""
        return [
            Tool(
                name="get_books_count",
                description="Get the current count of books in the talebook collection",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            )
        ]

    def create_initialization_options(self) -> Dict[str, Any]:
        """创建初始化选项，包含会话ID"""
        session_id = str(uuid.uuid4())
        logging.info(f"Creating MCP server with session ID: {session_id}")

        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "talebook-mcp",
                "version": "1.0.0"
            },
            "sessionId": session_id
        }

    async def handle_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        统一处理MCP请求

        Args:
            request_data: JSON-RPC请求数据

        Returns:
            JSON-RPC响应数据
        """
        method = request_data.get("method")
        request_id = request_data.get("id")
        params = request_data.get("params", {})

        try:
            # 处理初始化请求
            if method == "initialize":
                init_options = self.create_initialization_options()
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": init_options
                }

            # 处理工具列表请求（支持新旧两种方法名）
            elif method == "tools/list":
                tools = await self.list_tools()
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tools": [tool.model_dump(exclude_none=True) for tool in tools]}
                }

            # 处理工具调用请求（支持新旧两种方法名）
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if tool_name == "get_books_count":
                    result = await self.get_books_count(arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": result[0].text}]}
                    }
                else:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                    }

            # 未知方法
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }

        except Exception as e:
            logging.error(f"Error handling MCP request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"}
            }

# 创建全局MCP服务实例
mcp_service = MCPService()
