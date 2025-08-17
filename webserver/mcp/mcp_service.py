#!/usr/bin/env python3
"""
MCP Service Module

统一处理MCP协议请求的服务模块，供不同传输协议调用。
"""

import logging
import json
import traceback
import uuid
import time
import secrets
from gettext import gettext as _
from typing import Any, Sequence, Dict, Optional

from mcp.server import Server
from mcp.types import Tool, TextContent
from webserver.handlers.base import BaseHandler
from webserver.utils import SimpleBookFormatter


class MCPService:
    """MCP协议处理服务类"""
    MAX_BOOKS_COUNT_IN_RESULT = 20  # 返回结果中最大书籍数量限制
    TOKEN_EXPIRE_HOURS = 24  # Token过期时间（小时）

    def __init__(self, base_handler: BaseHandler = None):
        """初始化MCP服务"""
        self.server = Server("talebook-mcp")
        self.base_handler = base_handler
        self.authenticated_tokens = {}  # 存储有效的token和用户信息
        self._setup_tools()

    def _setup_tools(self):
        """设置工具定义"""
        pass

    def _generate_token(self, user_id: int, username: str) -> str:
        """生成访问令牌（基础版本）"""
        return self._generate_token_with_user_info_basic(user_id, username)

    def _generate_token_with_user_info_basic(self, user_id: int, username: str) -> str:
        """生成访问令牌（基础版本）"""
        # 生成token
        token = secrets.token_urlsafe(32)

        # 存储token信息
        self.authenticated_tokens[token] = {
            "user_id": user_id,
            "username": username,
            "created_at": time.time(),
            "expires_at": time.time() + (self.TOKEN_EXPIRE_HOURS * 3600)
        }

        return token

    def _generate_token_with_user_info(self, user) -> str:
        """生成访问令牌（包含完整用户信息）"""
        # 生成token
        token = secrets.token_urlsafe(32)

        # 存储token信息（包含更多用户信息便于复用）
        self.authenticated_tokens[token] = {
            "user_id": user.id,
            "username": user.username,
            "name": user.name,
            "is_admin": user.is_admin(),
            "is_active": user.is_active(),
            "created_at": time.time(),
            "expires_at": time.time() + (self.TOKEN_EXPIRE_HOURS * 3600)
        }

        return token

    def _find_existing_token(self, username: str) -> Optional[str]:
        """查找用户的现有有效token"""
        current_time = time.time()

        for token, token_info in self.authenticated_tokens.items():
            if (token_info["username"] == username and current_time < token_info["expires_at"]):
                return token

        return None

    def _validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证token是否有效"""
        if not token or token not in self.authenticated_tokens:
            return None

        token_info = self.authenticated_tokens[token]

        # 检查是否过期
        if time.time() > token_info["expires_at"]:
            del self.authenticated_tokens[token]
            return None

        return token_info

    def _require_auth(self, arguments: dict[str, Any]) -> Optional[Dict[str, Any]]:
        """检查请求是否已认证，返回用户信息或None"""
        token = arguments.get("token")
        if not token:
            return None

        return self._validate_token(token)

    def _cleanup_expired_tokens(self):
        """清理过期的token"""
        current_time = time.time()
        expired_tokens = [token for token, info in self.authenticated_tokens.items()
                          if current_time > info["expires_at"]]

        for token in expired_tokens:
            del self.authenticated_tokens[token]

        if expired_tokens:
            logging.info(f"Cleaned up {len(expired_tokens)} expired tokens")

    def get_authenticated_users(self) -> Dict[str, Any]:
        """获取当前已认证的用户列表（用于调试/管理）"""
        self._cleanup_expired_tokens()
        return {
            "active_tokens": len(self.authenticated_tokens),
            "users": [
                {
                    "username": info["username"],
                    "created_at": info["created_at"],
                    "expires_at": info["expires_at"]
                }
                for info in self.authenticated_tokens.values()
            ]
        }

    async def login(self, arguments: dict[str, Any]) -> Sequence[TextContent]:
        """用户登录获取访问令牌"""
        try:
            from webserver.models import Reader

            username = arguments.get("username", "").strip().lower()
            password = arguments.get("password", "").strip()

            if not username or not password:
                return [TextContent(type="text",
                                    text=json.dumps({"status": "error", "message": "Missing username or password"}))]

            if not self.base_handler:
                return [TextContent(type="text",
                                    text=json.dumps({"status": "error", "message": "Service not available"}))]

            # 检查是否已经有该用户的有效token（支持token复用）
            existing_token = self._find_existing_token(username)
            if existing_token:
                logging.info(f"Reusing existing token for user: {username}")
                token_info = self.authenticated_tokens[existing_token]

                result = {
                    "status": "success",
                    "token": existing_token,
                    "user": {
                        "id": token_info["user_id"],
                        "username": token_info["username"],
                        "name": token_info.get("name", ""),
                        "is_admin": token_info.get("is_admin", False),
                        "is_active": token_info.get("is_active", True)
                    },
                    "expires_in_hours": self.TOKEN_EXPIRE_HOURS,
                    "reused": True
                }
                return [TextContent(type="text", text=json.dumps(result))]

            # 查找用户
            user = self.base_handler.session.query(Reader).filter(Reader.username == username).first()
            if not user:
                return [TextContent(type="text",
                                    text=json.dumps({"status": "error", "message": "Invalid username or password"}))]

            # 验证密码
            if user.get_secure_password(password) != user.password:
                return [TextContent(type="text",
                                    text=json.dumps({"status": "error", "message": "Invalid username or password"}))]

            # 检查用户权限
            if not user.can_login():
                return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Access denied"}))]

            # 生成新token
            token = self._generate_token_with_user_info(user)

            logging.info(f"Generated new token for user {username}: {token}, total tokens: {len(self.authenticated_tokens)}")

            result = {
                "status": "success",
                "token": token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "is_admin": user.is_admin(),
                    "is_active": user.is_active()
                },
                "expires_in_hours": self.TOKEN_EXPIRE_HOURS,
                "reused": False
            }

            logging.info(f"MCP login successful for user: {username}")
            return [TextContent(type="text", text=json.dumps(result))]

        except Exception as e:
            error_msg = f"Login failed: {str(e)}"
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

    async def get_books(self, arguments: dict[str, Any]) -> Sequence[TextContent]:
        """获取书籍列表"""
        # 验证token
        user_info = self._require_auth(arguments)
        if not user_info:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Authentication required"}))]

        try:
            page = max(0, arguments.get("page", 1) - 1)
            page_size = arguments.get("page_size", 20)
            page_size = max(min(page_size, 20), 10)
            cmts = arguments.get("include_comments", False)
            desc = arguments.get("desc", True)

            self.base_handler.db.sort(field="id", ascending=(not desc))
            start = page * page_size
            end = start + page_size
            all_ids = list(self.base_handler.cache.search(""))
            all_ids.sort(reverse=desc)

            books = []
            page_ids = all_ids[start:end]
            if page_ids:
                cdn_url = self.base_handler.cdn_url
                books = [SimpleBookFormatter(b, cdn_url).format(cmts) for b in self.base_handler.get_books(ids=page_ids)]

            if not books:
                return [TextContent(type="text", text=json.dumps({"status": "success", "message": _(u"没有找到书籍"), "books": []}))]
            return [TextContent(type="text", text=json.dumps(books))]
        except Exception as e:
            logging.error(f"Error listing books: {e}")
            logging.error(traceback.format_exc())
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": _(u"列举书籍时发生错误: %s") % str(e)}))]

    async def search_books(self, arguments: dict[str, Any]) -> Sequence[TextContent]:
        # 验证token
        user_info = self._require_auth(arguments)
        if not user_info:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Authentication required"}))]

        name = arguments.get("name", "")
        if not name:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Invalid parameter 'name'"}))]

        include_comments = arguments.get("include_comments", False)

        title = _(u"搜索：%(name)s") % {"name": name}
        try:
            import opencc
            ids = self.base_handler.cache.search(name)
            for profile in {'s2t', "t2s"}:
                if len(ids) >= self.MAX_BOOKS_COUNT_IN_RESULT:
                    break
                converted_name = opencc.OpenCC(profile).convert(name)
                if converted_name == name:
                    continue
                ids2 = self.base_handler.cache.search(converted_name)
                if len(ids2) > 0:
                    ids = ids.union(ids, ids2)
                    break

            if not ids:
                return [TextContent(type="text", text=json.dumps({"status": "success",
                                                                  "message": _(u"没有找到相关书籍"), "books": []}))]

            total_books_count = len(ids)
            if len(ids) > self.MAX_BOOKS_COUNT_IN_RESULT:
                # 将set转换为list，按值从大到小排序，再进行切片操作
                ids_list = sorted(list(ids), reverse=True)
                ids = ids_list[:self.MAX_BOOKS_COUNT_IN_RESULT]

            book_list = self.base_handler.get_book_list([], ids=ids, title=title, include_comments=include_comments)
            book_list["total"] = total_books_count
            return [TextContent(type="text", text=json.dumps({"status": "success", "data": book_list}))]
        except Exception as e:
            logging.error(f"Error processing book: {e}")
            logging.error(traceback.format_exc())
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": _(u"搜索书籍时发生错误: %s") % str(e)}))]

    async def update_book_info(self, arguments: dict[str, Any]) -> Sequence[TextContent]:
        """更新书籍详细信息"""
        # 验证token
        user_info = self._require_auth(arguments)
        if not user_info:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Authentication required"}))]

        try:
            book_id = arguments.get("book_id")
            if not book_id:
                return [TextContent(type="text", text=json.dumps({"status": "error",
                                                                  "message": "Missing required parameter: book_id"}))]

            # 支持的字段
            supported_keys = ["title", "authors", "isbn", "comments", "tags"]

            # 获取书籍
            try:
                book = self.base_handler.get_book(book_id)
                bid = book["id"]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps({"status": "error", "message": f"Book not found: {str(e)}"}))]

            # 检查权限 - 需要管理员权限或者是书籍拥有者
            from webserver.models import Reader
            user = self.base_handler.session.query(Reader).get(user_info["user_id"])
            if not user:
                return [TextContent(type="text", text=json.dumps({"status": "error", "message": "User not found"}))]

            # 检查是否有编辑权限
            if not user.can_edit():
                return [TextContent(type="text", text=json.dumps({"status": "error",
                                                                  "message": "Permission denied: cannot edit books"}))]

            if not (user.is_admin() or self.base_handler.is_book_owner(bid, user_info["user_id"])):
                return [TextContent(type="text", text=json.dumps({"status": "error",
                                                                  "message": "Permission denied: not book owner or admin"}))]

            # 获取当前书籍元数据
            mi = self.base_handler.db.get_metadata(bid, index_is_id=True)
            if not mi:
                return [TextContent(type="text", text=json.dumps({"status": "error",
                                                                  "message": "Failed to get book metadata"}))]

            # 记录更新的字段
            updated_fields = []

            # 更新指定的字段
            for key in supported_keys:
                if key in arguments and key != "token":  # 排除token字段
                    val = arguments[key]
                    if key == "authors" and isinstance(val, str):
                        # 如果authors是字符串，转换为列表
                        val = [val.strip()] if val.strip() else []
                    elif key in ("authors", "tags") and isinstance(val, list):
                        # 确保authors&tags列表中的每个元素都是字符串
                        val = [str(author).strip() for author in val if str(author).strip()]

                    mi.set(key, val)
                    updated_fields.append(f"{key}: {val}")

            if not updated_fields:
                return [TextContent(type="text", text=json.dumps({"status": "error",
                                                                  "message": "No valid fields to update"}))]

            # 保存元数据
            self.base_handler.db.set_metadata(bid, mi)

            result = {
                "status": "success",
                "message": f"Successfully updated book (ID: {bid})",
                "updated_fields": updated_fields,
                "updated_by": user_info["username"]
            }
            logging.info(f"Book {bid} updated via MCP by {user_info['username']}: {updated_fields}")

            return [TextContent(type="text", text=json.dumps(result))]

        except Exception as e:
            error_msg = f"Error updating book info: {str(e)}"
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

    async def logout(self, arguments: dict[str, Any]) -> Sequence[TextContent]:
        """用户登出，删除token"""
        try:
            token = arguments.get("token")
            if not token:
                return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Missing token parameter"}))]

            if token in self.authenticated_tokens:
                username = self.authenticated_tokens[token]["username"]
                del self.authenticated_tokens[token]
                logging.info(f"User {username} logged out, token removed")
                return [TextContent(type="text", text=json.dumps({"status": "success", "message": "Logged out successfully"}))]
            else:
                return [TextContent(type="text", text=json.dumps({"status": "error",
                                                                  "message": "Token not found or already expired"}))]

        except Exception as e:
            error_msg = f"Logout failed: {str(e)}"
            logging.error(error_msg)
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

    async def get_books_count(self, arguments: dict[str, Any]) -> Sequence[TextContent]:
        """Get the current count of books in the collection."""
        # 验证token
        user_info = self._require_auth(arguments)
        if not user_info:
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": "Authentication required"}))]

        try:
            if self.base_handler is None:
                books_count = 0
                author_count = 0
            else:
                db = self.base_handler.db
                books_count = db.count()
                author_count = len(db.all_authors())

            result = {
                "status": "success",
                "data": {
                    "books": books_count,
                    "authors": author_count
                },
                "message": f"Total {books_count} books, and {author_count} authors."
            }
            logging.info(f"Books count requested by {user_info['username']}, returning: {books_count}")
            return [TextContent(type="text", text=json.dumps(result))]
        except Exception as e:
            error_msg = f"Error getting books count: {str(e)}"
            logging.error(error_msg)
            return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

    async def list_tools(self) -> list[Tool]:
        """获取可用工具列表"""
        return [
            Tool(
                name="login",
                description="Authenticate with username and password to get access token",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "username": {
                            "type": "string",
                            "description": "Username for authentication"
                        },
                        "password": {
                            "type": "string",
                            "description": "Password for authentication"
                        }
                    },
                    "required": ["username", "password"]
                }
            ),
            Tool(
                name="logout",
                description="Logout and invalidate the authentication token obtained from login",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Authentication token to invalidate"
                        }
                    },
                    "required": ["token"]
                }
            ),
            Tool(
                name="get_books_count",
                description="Get the current count of books in the talebook collection."
                            "Requires authentication token from login."
                            "If authentication fails, call login tool again.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Authentication token obtained from login"
                        }
                    },
                    "required": ["token"]
                }
            ),
            Tool(
                name="get_books",
                description="Get a list of books in the collection by page. Requires authentication token from login.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Authentication token obtained from login"
                        },
                        "page": {
                            "type": "number",
                            "description": "Page number to retrieve books from, starting from 1"
                        },
                        "page_size": {
                            "type": "number",
                            "description": "Number of books per page, default and maximum is 10",
                            "default": 10
                        },
                        "desc": {
                            "type": "boolean",
                            "description": "Whether to sort the books id in descending order."
                        },
                        "include_comments": {
                            "type": "boolean",
                            "description": "Whether to include book comments in the response."
                                           "It could save tokens if not include comments.",
                            "default": False
                        }
                    },
                    "required": ["token", "page"]
                }
            ),
            Tool(
                name="search_books",
                description="Search for books in the collection. Requires authentication token from login. "
                            "If authentication fails, call login tool again.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Authentication token obtained from login"
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the book, author to search for"
                        },
                        "include_comments": {
                            "type": "boolean",
                            "description": "Whether to include book comments in the response."
                                           "It could save tokens if not include comments.",
                            "default": False
                        }
                    },
                    "required": ["token", "name"]
                }
            ),
            Tool(
                name="update_book_info",
                description="Update book information including title, authors, ISBN, and comments."
                            "Requires authentication token from login and appropriate permissions."
                            "If authentication fails, call login tool again.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Authentication token obtained from login"
                        },
                        "book_id": {
                            "type": ["string", "integer"],
                            "description": "ID of the book to update"
                        },
                        "title": {
                            "type": "string",
                            "description": "Book title"
                        },
                        "authors": {
                            "type": ["string", "array"],
                            "description": "Author name (string) or list of author names (array)",
                            "items": {
                                "type": "string"
                            }
                        },
                        "isbn": {
                            "type": "string",
                            "description": "ISBN number of the book"
                        },
                        "comments": {
                            "type": "string",
                            "description": "Book description or comments.For HTML contents, do not convert <> to &lt; and &gt;"
                        },
                        "tags": {
                            "type": ["string", "array"],
                            "description": "Tag name (string) or list of tag names (array)",
                            "items": {
                                "type": "string"
                            }
                        },
                    },
                    "required": ["token", "book_id"]
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
                "version": "0.1.0",
                "description": "Local ebooks management system developed by Talebook(PoxenStudio)"
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

                if tool_name == "login":
                    result = await self.login(arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": result[0].text}]}
                    }
                elif tool_name == "logout":
                    result = await self.logout(arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": result[0].text}]}
                    }
                elif tool_name == "get_books_count":
                    result = await self.get_books_count(arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": result[0].text}]}
                    }
                elif tool_name == "get_books":
                    result = await self.get_books(arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": result[0].text}]}
                    }
                elif tool_name == "search_books":
                    result = await self.search_books(arguments)
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": result[0].text}]}
                    }
                elif tool_name == "update_book_info":
                    result = await self.update_book_info(arguments)
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
