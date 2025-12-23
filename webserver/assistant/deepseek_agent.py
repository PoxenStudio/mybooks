"""
DeepSeek + MCP Conversation Agent
Supports continuous conversation and tool calling
"""

import json
import re
from typing import Dict, List, Optional
from openai import OpenAI
from webserver import loader

from webserver.assistant.mcp_client import MCPStreamClient

CONF = loader.get_settings()
DEEPSEEK_API_KEY = CONF.get("AI_DEEPSEEK_API_KEY", "")
MCP_TOKEN = CONF.get("MCP_TOKEN", "")

DEEPSEEK_API_BASE = "https://api.deepseek.com"
MCP_SERVER_URL = "http://127.0.0.1:8082/api/mcp/stream"


class DeepSeekMCPAgent:
    """
    DeepSeek + MCP会话代理
    支持持续对话和工具调用
    """

    def __init__(self):
        # 初始化DeepSeek客户端
        self.deepseek_client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_API_BASE,
            timeout=30.0
        )

        # 初始化MCP客户端
        self.mcp_client = MCPStreamClient(MCP_SERVER_URL, MCP_TOKEN)

        # 会话状态
        self.session_active = True
        self.conversation_history = []

    async def initialize(self):
        """初始化代理"""
        print("初始化DeepSeek-MCP代理...")
        await self.mcp_client.connect()
        print("代理初始化完成")
        print("-" * 60)

    async def format_conversation_for_deepseek(self, user_input: str) -> List[Dict]:
        """格式化对话历史给DeepSeek"""
        # 构建系统提示
        tools = await self.mcp_client.list_tools()
        tool_descriptions = "\n".join([
            f"- {tool['name']}: {tool.get('description', '无描述')}"
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

请在需要时使用上述格式调用工具。"""

        messages = [{"role": "system", "content": system_message}]

        # 添加历史对话（最近5轮）
        recent_history = self.conversation_history[-10:]  # 保留最近10条消息
        for msg in recent_history:
            messages.append(msg)

        # 添加当前用户输入
        messages.append({"role": "user", "content": user_input})

        return messages

    def extract_tool_call(self, response_text: str) -> Optional[Dict]:
        """从DeepSeek响应中提取工具调用"""
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
        messages = await self.format_conversation_for_deepseek(user_input)

        try:
            # 第一次调用：获取思考过程或工具调用
            response = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
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
                yield {"type": "status", "content": f"正在调用工具: {tool_call.get('tool')}..."}

                # 执行工具调用
                tool_name = tool_call.get("tool")
                arguments = tool_call.get("arguments", {})

                if tool_name:
                    # 调用MCP工具
                    tool_result = await self.mcp_client.call_tool(tool_name, arguments)
                    tool_result_str = json.dumps(tool_result, ensure_ascii=False, indent=2)

                    # 将工具结果添加到对话
                    new_messages = messages.copy()
                    new_messages.append({"role": "assistant", "content": full_response_text})
                    new_messages.append({
                        "role": "user",
                        "content": f"工具调用结果：\n{tool_result_str}\n\n请根据这个结果回答我的问题。"
                    })

                    # 第二次调用DeepSeek（获得针对工具结果的最终回答）
                    final_response = self.deepseek_client.chat.completions.create(
                        model="deepseek-chat",
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

                    # 保存到对话历史
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
        """获取对话摘要"""
        if not self.conversation_history:
            return "暂无对话历史"

        user_count = sum(1 for msg in self.conversation_history if msg["role"] == "user")
        assistant_count = sum(1 for msg in self.conversation_history if msg["role"] == "assistant")

        return f"对话历史：{len(self.conversation_history)}条消息（用户:{user_count}，助手:{assistant_count}）"

    async def close(self):
        """关闭代理"""
        await self.mcp_client.close()
        self.session_active = False
