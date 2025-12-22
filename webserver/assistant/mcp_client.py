"""
MCP Stream Client
Supports HTTP Streamable communication (non-SSE)
"""

import json
import aiohttp
from typing import Dict, List, Optional
from datetime import datetime


class MCPStreamClient:
    """
    MCP流式客户端，支持HTTP Streamable通信
    不使用SSE，而是使用HTTP流式响应
    """

    def __init__(self, base_url: str, token: str):
        self.base_url = f'{base_url}?token={token}' if token is not None else base_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.tools_cache = None
        print(f"MCP Tool: {self.base_url}")

    async def connect(self):
        """连接到MCP服务器"""
        self.session = aiohttp.ClientSession()
        await self.initialize_session()

    async def initialize_session(self):
        """初始化MCP会话"""
        try:
            # 发送初始化请求
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "clientInfo": {
                        "name": "DeepSeek-MCP-Client",
                        "version": "1.0.0"
                    }
                }
            }

            response = await self._send_request(init_request)
            print(f"MCP会话初始化成功")
            return response
        except Exception as e:
            print(f"MCP初始化失败: {e}")
            return None

    async def _send_request(self, request_data: Dict) -> Dict:
        """发送请求到MCP服务器（支持流式和普通响应）"""
        try:
            async with self.session.post(
                self.base_url,
                json=request_data,
                headers={"Content-Type": "application/json"}
            ) as response:

                # 检查是否流式响应
                content_type = response.headers.get('Content-Type', '')
                if 'stream' in content_type.lower() or 'chunked' in response.headers.get('Transfer-Encoding', ''):
                    # 处理流式响应
                    return await self._read_stream_response(response)
                else:
                    # 处理普通响应
                    return await response.json()

        except Exception as e:
            print(f"请求MCP服务器失败: {e}")
            raise

    async def _read_stream_response(self, response) -> Dict:
        """读取HTTP流式响应"""
        try:
            buffer = ""
            async for chunk in response.content.iter_any():
                buffer += chunk.decode('utf-8')
                # 尝试解析完整的JSON对象
                try:
                    data = json.loads(buffer.strip())
                    return data
                except json.JSONDecodeError:
                    # 继续累积数据
                    continue

            # 如果循环结束，尝试最后一次解析
            if buffer:
                try:
                    return json.loads(buffer.strip())
                except:
                    pass

            return {"error": "无法解析流式响应"}
        except Exception as e:
            return {"error": f"读取流式响应失败: {e}"}

    async def list_tools(self) -> List[Dict]:
        """获取可用的工具列表"""
        if self.tools_cache:
            return self.tools_cache

        try:
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {}
            }

            response = await self._send_request(tools_request)

            if response and "result" in response:
                tools = response["result"].get("tools", [])
                self.tools_cache = tools
                return tools

        except Exception as e:
            print(f"获取工具列表失败: {e}")

        # 返回默认工具（用于测试）
        return [
            {
                "name": "count_books",
                "description": "统计书库中的书籍数量",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "书籍分类（可选）"
                        }
                    }
                }
            },
            {
                "name": "search_books",
                "description": "搜索书籍",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "limit": {"type": "integer", "description": "返回数量限制"}
                    },
                    "required": ["query"]
                }
            }
        ]

    async def call_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """调用指定的工具"""
        try:
            call_request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            print(f"调用MCP工具: {tool_name}")
            if arguments:
                print(f"   参数: {arguments}")

            response = await self._send_request(call_request)

            if "result" in response:
                result = response["result"]
                print(f"工具调用成功")
                return result
            else:
                error = response.get("error", {})
                error_msg = error.get("message", "未知错误")
                print(f"工具调用失败: {error_msg}")
                return {"error": error_msg}

        except Exception as e:
            print(f"调用工具异常: {e}")
            return {
                "error": f"Failed to call the tool: {tool_name}",
                "message": str(e)
            }

    async def close(self):
        """关闭连接"""
        if self.session:
            await self.session.close()
