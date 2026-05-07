"""
OpenAI compatible API + MCP Conversation Agent
Supports continuous conversation and tool calling
"""

import json
import logging
import re
from typing import Dict, List, Optional
from openai import OpenAI
from webserver import loader

from webserver.assistant.mcp_client import MCPStreamClient
from webserver.constants import DEEPSEEK_API_BASE

CONF = loader.get_settings()
AI_API_KEY = CONF.get("AI_DEEPSEEK_API_KEY", "")
AI_BASE_URL = CONF.get("AI_API_URL", DEEPSEEK_API_BASE)
AI_MODEL = CONF.get("AI_MODEL", "deepseek-chat")
MCP_TOKEN = CONF.get("AI_MCP_TOKEN", "")
MCP_SERVER_URL = "http://127.0.0.1:80/api/mcp/stream"


class AIAssistantMCPAgent:
    """
    AI + MCP会话代理
    支持持续对话和工具调用
    """

    def __init__(self, cookies: Optional[Dict] = None):
        self.ai_client = OpenAI(
            api_key=AI_API_KEY,
            base_url=AI_BASE_URL,
            timeout=30.0
        )
        self.model = AI_MODEL
        logging.debug(f"Initialized AI client with model: {self.model}, base_url: {AI_BASE_URL}")

        self.mcp_client = MCPStreamClient(MCP_SERVER_URL, MCP_TOKEN, cookies)
        self.session_active = True
        self.conversation_history = []

    async def initialize(self):
        logging.info("Init AI-MCP agent...")
        await self.mcp_client.connect()
        logging.info("AI-MCP agent initialized successfully.")
        logging.info("-" * 60)

    def format_tool_schema(self, tool: Dict) -> str:
        """格式化单个工具的schema为可读描述"""
        name = tool.get('name', '')
        description = tool.get('description', '无描述')
        input_schema = tool.get('inputSchema', {})

        # 基础描述
        result = f"- {name}: {description}"

        # 添加参数说明
        if input_schema and 'properties' in input_schema:
            properties = input_schema['properties']
            required = input_schema.get('required', [])

            if properties:
                result += "\n  参数："
                for param_name, param_info in properties.items():
                    param_type = param_info.get('type', 'any')
                    param_desc = param_info.get('description', '')
                    is_required = '必填' if param_name in required else '可选'
                    result += f"\n    - {param_name} ({param_type}, {is_required}): {param_desc}"

        return result

    async def format_conversation(self, user_input: str) -> List[Dict]:
        """格式化对话历史给AI模型"""
        # 构建系统提示
        tools = await self.mcp_client.list_tools()
        tool_descriptions = "\n\n".join([
            self.format_tool_schema(tool)
            for tool in tools
        ])

        system_message = f"""你是一个智能助手，可以调用本地Talebook工具来帮助用户。
你可以使用的工具有：
{tool_descriptions}

当用户需要时，你可以调用这些工具。工具调用格式：
<tool_call>
{{
    "tool": "工具名称",
    "arguments": {{"参数": "值"}}
}}
</tool_call>

工具调用示例：
用户：查询《三体》这本书
助手：<tool_call>
{{
    "tool": "query_book_metadata",
    "arguments": {{"query": "三体"}}
}}
</tool_call>

请根据工具的参数说明，使用正确的参数名称和类型调用工具。"""

        messages = [{"role": "system", "content": system_message}]

        # 添加历史对话（最近10条消息，只包含用户问题和最终回答）
        recent_history = self.conversation_history[-10:]
        for msg in recent_history:
            messages.append(msg)

        # 添加当前用户输入
        messages.append({"role": "user", "content": user_input})

        return messages

    def extract_tool_call(self, response_text: str) -> Optional[Dict]:
        """从AI模型响应中提取工具调用"""
        # 匹配工具调用格式
        pattern = r'<tool_call>\s*({.*?})\s*</tool_call>'
        match = re.search(pattern, response_text, re.DOTALL)

        if match:
            try:
                tool_call = json.loads(match.group(1))
                return tool_call
            except json.JSONDecodeError:
                json_str = match.group(1).replace('\n', ' ').strip()
                try:
                    tool_call = json.loads(json_str)
                    return tool_call
                except:
                    pass
        return None

    def clean_response_text(self, response_text: str) -> str:
        """清理响应文本，移除工具调用标记"""
        # 移除工具调用标记
        cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', response_text, flags=re.DOTALL)
        # 移除多余空行
        cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
        return cleaned.strip()

    async def process_user_input(self, user_input: str):
        """处理用户输入，可能涉及工具调用，由WebSocketHandler调用"""

        # 格式化对话
        messages = await self.format_conversation(user_input)

        try:
            # 第一次调用：获取思考过程或工具调用
            response = self.ai_client.chat.completions.create(
                model=AI_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                stream=True
            )

            full_response_text = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response_text += content
                    yield {"type": "content", "content": content}

            # 检查是否包含工具调用
            tool_call = self.extract_tool_call(full_response_text)

            if tool_call:
                logging.info(f"Detected tool call: {tool_call}")

                yield {"type": "status", "content": f"正在调用工具: {tool_call.get('tool')}..."}

                # 执行工具调用
                tool_name = tool_call.get("tool")
                arguments = tool_call.get("arguments", {})

                if tool_name:
                    # 调用MCP工具
                    tool_result = await self.mcp_client.call_tool(tool_name, arguments)
                    logging.info(f"Tool result: {tool_result}")
                    tool_result_str = json.dumps(tool_result, ensure_ascii=False, indent=2)

                    # 将工具结果添加到对话
                    new_messages = messages.copy()
                    new_messages.append({"role": "assistant", "content": full_response_text})
                    new_messages.append({
                        "role": "user",
                        "content": f"工具调用结果：\n{tool_result_str}\n\n请根据这个结果回答我的问题。"
                    })

                    # 第二次调用AI模型（获得针对工具结果的最终回答）
                    final_response = self.ai_client.chat.completions.create(
                        model=AI_MODEL,
                        messages=new_messages,
                        temperature=0.7,
                        max_tokens=2000,
                        stream=True
                    )

                    final_text = ""
                    for chunk in final_response:
                        if chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            final_text += content
                            yield {"type": "content", "content": content}

                    # 只保存用户问题和最终回答到对话历史（节省token）
                    # 工具调用的示例已经在system message中提供
                    self.conversation_history.extend([
                        {"role": "user", "content": user_input},
                        {"role": "assistant", "content": final_text}
                    ])
                else:
                    # 工具名称无效
                    cleaned_result = self.clean_response_text(full_response_text)
                    self.conversation_history.extend([
                        {"role": "user", "content": user_input},
                        {"role": "assistant", "content": cleaned_result}
                    ])
            else:
                logging.info("No tool call detected in response.")
                # 没有工具调用
                cleaned_result = self.clean_response_text(full_response_text)
                self.conversation_history.extend([
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": cleaned_result}
                ])

        except Exception as e:
            error_msg = f"处理请求时出错: {str(e)}"
            yield {"type": "error", "content": error_msg}

    def get_conversation_summary(self) -> str:
        if not self.conversation_history:
            return "暂无对话历史"

        user_count = sum(1 for msg in self.conversation_history if msg["role"] == "user")
        assistant_count = sum(1 for msg in self.conversation_history if msg["role"] == "assistant")

        return f"对话历史：{len(self.conversation_history)}条消息（用户:{user_count}，助手:{assistant_count}）"

    async def close(self):
        await self.mcp_client.close()
        self.session_active = False
