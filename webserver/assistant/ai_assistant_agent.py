"""
LangGraph ReAct agent backed by the local MyBooks MCP server.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union

from webserver import loader
from webserver.assistant.mcp_client import MCPStreamClient
from webserver.constants import DEEPSEEK_API_BASE

CONF = loader.get_settings()
AI_API_KEY = CONF.get("AI_DEEPSEEK_API_KEY", "")
AI_BASE_URL = CONF.get("AI_API_URL", DEEPSEEK_API_BASE)
AI_MODEL = CONF.get("AI_MODEL", "deepseek-chat")
MCP_TOKEN = CONF.get("AI_MCP_TOKEN", "")
MCP_SERVER_URL = "http://127.0.0.1:80/api/mcp/stream"


def _int_setting(name: str, default: int) -> int:
    try:
        value = int(CONF.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# LangGraph counts supersteps: each model/tool round trip costs about two steps.
# The previous value of 16 only allowed ~7 tool rounds and aborted normal
# multi-step questions with GraphRecursionError.
AGENT_RECURSION_LIMIT = _int_setting("AI_RECURSION_LIMIT", 40)
# Hard cap on tool invocations per user turn, so a confused model cannot loop.
MAX_TOOL_CALLS_PER_TURN = _int_setting("AI_MAX_TOOL_CALLS", 12)

SYSTEM_PROMPT = """你是 MyBooks 书库助手。优先使用提供的工具查询和操作 MyBooks；没有相关工具时再直接回答。
根据工具结果回答，不要声称完成了工具未成功执行的操作。对于删除等需要确认的操作，必须先向用户说明影响并得到明确同意，再调用确认参数。"""

TOOL_GROUPS = {
    "general": {"get_user_info", "library_stats", "reading_stats", "get_books_count", "get_books", "search_books", "get_book"},
    "books": {
        "get_books_count", "get_books", "search_books", "search_by_category", "categories", "list_folders",
        "search_by_folder", "list_authors", "get_author_books", "get_book",
    },
    "metadata": {"query_book_metadata", "auto_fill_book_info", "book_fill"},
    "reading": {
        "reading_stats", "get_book_reading_stats", "update_book_reading_stats", "get_reading_time",
        "set_reading_time", "delete_reading_time", "reading", "list_reading", "read_done", "list_read_done",
        "wants", "list_wants", "favorite", "list_favorites",
    },
    "notes": {"get_notes", "push_notes", "clear_imported_notes"},
    "booklists": {
        "list_my_booklists", "list_public_booklists", "list_liked_booklists", "get_booklist", "create_booklist",
        "update_booklist", "delete_booklist", "booklist_add_books", "booklist_remove_book", "like_booklist",
        "get_book_booklists",
    },
    "management": {"edit_book", "save_meta_to_file", "book_add_by_isbn", "set_folder", "rename_folder", "update_book_info"},
    "delivery": {"mailto", "send_to_device", "download_book", "upload_book"},
    "tts": {
        "tts_save_config", "tts_test_connection", "tts_convert", "tts_progress", "tts_clone_list",
        "tts_clone_delete", "tts_prompt_list", "tts_prompt_save", "tts_prompt_delete",
    },
    "auth": {"login", "logout"},
}

TOOL_GROUP_KEYWORDS = {
    "books": (
        "书", "书库", "图书", "作者", "isbn", "搜索", "查询", "查找", "查一下", "查查", "分类", "目录", "book", "author", "search",
    ),
    "metadata": (
        "元数据", "豆瓣", "在线信息", "网上信息", "补全信息", "查资料", "出版信息", "出版社", "metadata", "douban",
    ),
    "reading": (
        "阅读", "读完", "读了", "看完", "已读", "想读", "进度", "时长", "阅读时间", "分钟", "收藏", "喜欢", "wants", "favorite",
        "reading", "finished",
    ),
    "notes": ("笔记", "划线", "批注", "标注", "书签", "notes", "highlight", "annotation", "bookmark"),
    "booklists": ("书单", "书架", "清单", "booklist", "reading list"),
    "management": (
        "修改", "改成", "编辑", "更新信息", "重命名", "改名", "添加书", "添加实体书", "设置分类", "设置标签",
        "写入", "edit", "update", "rename",
    ),
    "delivery": (
        "发送", "推送", "邮件", "邮箱", "下载", "上传", "设备", "kindle", "send", "email", "download", "device",
    ),
    "tts": ("有声书", "语音", "音频", "tts", "声音", "转换成有声", "克隆音色"),
    "auth": ("登录", "登出", "退出登录", "token", "login", "logout"),
    "general": ("统计", "数量", "多少本", "几本", "我的信息", "账号信息", "user info", "statistics", "book count"),
}

FOLLOW_UP_REFERENCES = ("这本", "这本书", "它", "这个", "那个", "刚才", "然后", "继续", "那呢", "那本")
BOOK_SEARCH_KEYWORDS = ("搜索", "查找", "查一下", "查查", "作者", "isbn", "分类", "目录", "search", "author")


class AIAssistantMCPAgent:
    """Per-connection conversational agent using LangGraph ReAct and MyBooks MCP tools."""

    def __init__(self, cookies: Optional[Dict] = None):
        self.model = AI_MODEL
        self.mcp_client = MCPStreamClient(MCP_SERVER_URL, MCP_TOKEN, cookies)
        self.session_active = True
        self.conversation_history: List[Dict[str, str]] = []
        self._chat_model = None
        self._last_tool_names: set[str] = set()

    async def initialize(self):
        logging.info("Init AI-MCP agent...")
        await self.mcp_client.connect()
        logging.info("AI-MCP agent initialized successfully.")

    @staticmethod
    def select_tools(
        user_input: str,
        tools: List[Dict],
        previous_tool_names: Optional[set[str]] = None,
    ) -> List[Dict]:
        """Select a focused domain toolset and preserve explicit conversational follow-ups."""
        query = user_input.casefold()
        groups = {
            group for group, keywords in TOOL_GROUP_KEYWORDS.items()
            if any(keyword.casefold() in query for keyword in keywords)
        }
        if "general" in groups and "books" in groups and not any(keyword in query for keyword in BOOK_SEARCH_KEYWORDS):
            groups.remove("books")
        follows_previous_turn = any(reference in query for reference in FOLLOW_UP_REFERENCES)
        if not groups and not (follows_previous_turn and previous_tool_names):
            return []

        selected_names = set()
        for group in groups:
            selected_names.update(TOOL_GROUPS[group])
        if follows_previous_turn and previous_tool_names:
            selected_names.update(previous_tool_names)
        if groups & {"reading", "notes", "booklists", "management", "delivery"}:
            selected_names.update({"search_books", "get_book"})
        return [tool for tool in tools if tool.get("name") in selected_names]

    async def format_conversation(self, user_input: str) -> List[Dict[str, str]]:
        """Return the recent user/assistant turns plus the current input."""
        messages = list(self.conversation_history[-10:])
        messages.append({"role": "user", "content": user_input})
        return messages

    @staticmethod
    def _schema_annotation(schema: Dict[str, Any]):
        from typing import Literal

        schema_types = schema.get("type")
        if isinstance(schema_types, list):
            options = [dict(schema, type=type_name) for type_name in schema_types]
            annotations = [AIAssistantMCPAgent._schema_annotation(option) for option in options]
            annotation = Union[tuple(dict.fromkeys(annotations))]
        elif schema.get("anyOf") or schema.get("oneOf"):
            variants = schema.get("anyOf") or schema.get("oneOf")
            annotations = [AIAssistantMCPAgent._schema_annotation(variant) for variant in variants]
            annotation = Union[tuple(dict.fromkeys(annotations))]
        else:
            schema_type = schema.get("type")
            if schema_type == "string":
                annotation = str
            elif schema_type == "integer":
                annotation = int
            elif schema_type == "number":
                annotation = float
            elif schema_type == "boolean":
                annotation = bool
            elif schema_type == "array":
                item_schema = schema.get('items', {})
                annotation = List[AIAssistantMCPAgent._schema_annotation(item_schema)]
            elif schema_type == "object":
                annotation = Dict[str, Any]
            else:
                annotation = Any

        enum_values = schema.get("enum")
        if enum_values:
            annotation = Literal.__getitem__(tuple(enum_values))
        return annotation

    @classmethod
    def _tool_args_schema(cls, tool: Dict):
        from pydantic import Field, create_model

        input_schema = tool.get("inputSchema") or {}
        properties = input_schema.get("properties") or {}
        required = set(input_schema.get("required") or [])
        fields = {}
        for name, property_schema in properties.items():
            annotation = cls._schema_annotation(property_schema)
            default = ... if name in required else property_schema.get("default")
            if name not in required and "default" not in property_schema:
                default = None
                annotation = Optional[annotation]
            fields[name] = (
                annotation,
                Field(default, description=property_schema.get("description", "")),
            )
        model_name = f"MyBooksToolInput_{tool.get('name', 'unknown')}"
        alternatives = [
            [name for name in option.get("required", []) if name in properties]
            for option in input_schema.get("anyOf", [])
            if option.get("required")
        ]
        validators = {}
        config = None
        if alternatives:
            from pydantic import ConfigDict, model_validator

            def require_any_alternative(instance):
                for required_names in alternatives:
                    if all(getattr(instance, name, None) not in (None, "") for name in required_names):
                        return instance
                raise ValueError("At least one valid anyOf alternative is required")

            validators["validate_any_of_required"] = model_validator(mode="after")(require_any_alternative)
            config = ConfigDict(json_schema_extra={"anyOf": [{"required": names} for names in alternatives]})
        return create_model(model_name, __config__=config, __validators__=validators, **fields)

    @staticmethod
    def _tool_result_text(result: Dict[str, Any]) -> str:
        content = result.get("content")
        if isinstance(content, list):
            text_items = [item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
            if text_items:
                return "\n".join(text_items)
        error = result.get("error")
        if error:
            return f"工具调用失败：{error}"
        return json.dumps(result, ensure_ascii=False)

    def _build_react_agent(self, tools: List[Dict], call_state: Optional[Dict[str, Any]] = None):
        from langchain_core.tools import StructuredTool
        from langchain.agents import create_agent

        if call_state is None:
            call_state = {}
        call_state.setdefault("count", 0)
        seen_calls: Dict[Any, str] = call_state.setdefault("seen", {})

        langchain_tools = []
        for tool_info in tools:
            name = tool_info.get("name")
            if not name:
                raise ValueError("MCP tool is missing its name")

            async def invoke_tool(_tool_name=name, **arguments):
                call_key = (
                    _tool_name,
                    json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str),
                )
                if call_key in seen_calls:
                    return (
                        "该工具已使用相同参数调用过，请勿重复调用。上一次的结果如下：\n"
                        f"{seen_calls[call_key]}"
                    )
                if call_state["count"] >= MAX_TOOL_CALLS_PER_TURN:
                    return (
                        "本轮工具调用次数已达上限，请不要再调用工具，"
                        "直接根据已有结果回答用户；若信息不足，请说明还需要哪些信息。"
                    )
                call_state["count"] += 1
                result = await self.mcp_client.call_tool(_tool_name, arguments)
                text = self._tool_result_text(result)
                seen_calls[call_key] = text
                return text

            langchain_tools.append(
                StructuredTool.from_function(
                    name=name,
                    description=tool_info.get("description") or name,
                    args_schema=self._tool_args_schema(tool_info),
                    coroutine=invoke_tool,
                )
            )

        return create_agent(
            self._get_chat_model(),
            langchain_tools,
            system_prompt=SYSTEM_PROMPT,
        )

    def _get_chat_model(self):
        if self._chat_model is None:
            from langchain_openai import ChatOpenAI

            self._chat_model = ChatOpenAI(
                model=self.model,
                api_key=AI_API_KEY,
                base_url=AI_BASE_URL,
                timeout=30.0,
                temperature=0.7,
                max_tokens=2000,
            )
        return self._chat_model

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block if isinstance(block, str) else block.get("text", "")
                for block in content
                if isinstance(block, str) or (isinstance(block, dict) and isinstance(block.get("text"), str))
            )
        return ""

    async def process_user_input(self, user_input: str):
        """Process a user turn and yield the existing WebSocket event format."""
        response_parts: List[str] = []
        hit_step_limit = False
        try:
            from contextlib import aclosing

            from langgraph.errors import GraphRecursionError

            messages = await self.format_conversation(user_input)
            available_tools = await self.mcp_client.list_tools()
            selected_tools = self.select_tools(user_input, available_tools, self._last_tool_names)
            if selected_tools:
                self._last_tool_names = {tool["name"] for tool in selected_tools}
            logging.info("Selected %d of %d MCP tools for assistant turn", len(selected_tools), len(available_tools))

            if selected_tools:
                agent = self._build_react_agent(selected_tools)
                tool_calls_seen = 0
                streamed_runs: set[str] = set()
                try:
                    async with aclosing(agent.astream_events(
                        {"messages": messages},
                        config={"recursion_limit": AGENT_RECURSION_LIMIT},
                        version="v2",
                    )) as event_stream:
                        async for event in event_stream:
                            if event.get("event") == "on_tool_start":
                                tool_calls_seen += 1
                                if tool_calls_seen > MAX_TOOL_CALLS_PER_TURN:
                                    hit_step_limit = True
                                    logging.warning(
                                        "Assistant turn exceeded %d tool calls; stopping the agent early",
                                        MAX_TOOL_CALLS_PER_TURN,
                                    )
                                    break
                                tool_name = event.get("name", "unknown")
                                yield {"type": "status", "content": f"正在调用工具: {tool_name}..."}
                            elif event.get("event") == "on_chat_model_stream":
                                chunk = event.get("data", {}).get("chunk")
                                content = self._content_text(getattr(chunk, "content", ""))
                                if content:
                                    streamed_runs.add(str(event.get("run_id")))
                                    response_parts.append(content)
                                    yield {"type": "content", "content": content}
                            elif event.get("event") == "on_chat_model_end":
                                # Fallback for providers/models that do not stream tokens.
                                if str(event.get("run_id")) in streamed_runs:
                                    continue
                                output = event.get("data", {}).get("output")
                                content = self._content_text(getattr(output, "content", ""))
                                if content:
                                    response_parts.append(content)
                                    yield {"type": "content", "content": content}
                except GraphRecursionError:
                    hit_step_limit = True
                    logging.warning(
                        "Assistant turn reached recursion limit (%d steps); returning partial answer",
                        AGENT_RECURSION_LIMIT,
                    )
            else:
                from langchain_core.messages import SystemMessage

                model_messages = [SystemMessage(content=SYSTEM_PROMPT)]
                model_messages.extend(messages)
                async for chunk in self._get_chat_model().astream(model_messages):
                    content = self._content_text(getattr(chunk, "content", ""))
                    if content:
                        response_parts.append(content)
                        yield {"type": "content", "content": content}

            if hit_step_limit:
                note = "（本轮推理步数已达上限，以上是目前查到的结果。可以让我继续，或把问题范围缩小一些。）"
                response_parts.append(note)
                yield {"type": "content", "content": note}

            final_text = "".join(response_parts).strip()
            self.conversation_history.extend([
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": final_text},
            ])
        except Exception as e:
            logging.exception("Failed to process AI assistant input")
            yield {"type": "error", "content": f"处理请求时出错: {str(e)}"}

    def get_conversation_summary(self) -> str:
        if not self.conversation_history:
            return "暂无对话历史"

        user_count = sum(1 for msg in self.conversation_history if msg["role"] == "user")
        assistant_count = sum(1 for msg in self.conversation_history if msg["role"] == "assistant")
        return f"对话历史：{len(self.conversation_history)}条消息（用户:{user_count}，助手:{assistant_count}）"

    async def close(self):
        await self.mcp_client.close()
        self.session_active = False
