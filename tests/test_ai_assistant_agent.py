import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

import webserver.assistant.ai_assistant_agent as assistant_agent_module
from webserver.assistant.ai_assistant_agent import AIAssistantMCPAgent, TOOL_GROUPS
from webserver.assistant.mcp_client import MCPStreamClient
from webserver.mcp.api_tools import API_TOOLS
from webserver.mcp.mcp_service import MCPService


def test_tool_selection_limits_tools_to_matching_domains():
    tools = [
        {"name": "search_books"},
        {"name": "get_book"},
        {"name": "tts_convert"},
        {"name": "edit_book"},
    ]

    selected_names = {tool["name"] for tool in AIAssistantMCPAgent.select_tools("帮我查一下《三体》", tools)}

    assert selected_names == {"search_books", "get_book"}


def test_tool_selection_includes_all_requested_domains():
    tools = [
        {"name": "search_books"},
        {"name": "get_notes"},
        {"name": "tts_convert"},
    ]

    selected_names = {tool["name"] for tool in AIAssistantMCPAgent.select_tools("查询这本书的笔记并转换成有声书", tools)}

    assert selected_names == {"search_books", "get_notes", "tts_convert"}


def test_unrelated_input_does_not_expose_mcp_tools():
    assert AIAssistantMCPAgent.select_tools("你好，查看天气怎么样？", [{"name": "search_books"}]) == []


def test_library_statistics_route_to_the_small_general_toolset():
    tools = [
        {"name": "get_books_count"},
        {"name": "search_books"},
        {"name": "tts_convert"},
        {"name": "delete_booklist"},
    ]

    selected_names = {tool["name"] for tool in AIAssistantMCPAgent.select_tools("书库里有多少本书？", tools)}

    assert selected_names == {"get_books_count", "search_books"}


def test_explicit_follow_up_keeps_the_previous_turn_toolset():
    tools = [
        {"name": "search_books"},
        {"name": "get_book"},
        {"name": "reading"},
        {"name": "tts_convert"},
    ]

    selected_names = {
        tool["name"]
        for tool in AIAssistantMCPAgent.select_tools("然后呢？", tools, {"search_books", "get_book"})
    }

    assert selected_names == {"search_books", "get_book"}


def test_current_intent_and_follow_up_toolsets_are_combined():
    tools = [
        {"name": "search_books"},
        {"name": "get_book"},
        {"name": "reading"},
        {"name": "tts_convert"},
    ]

    selected_names = {
        tool["name"]
        for tool in AIAssistantMCPAgent.select_tools("把它标记为已读", tools, {"search_books", "get_book"})
    }

    assert selected_names == {"search_books", "get_book", "reading"}


def test_every_mcp_tool_is_assigned_to_a_routing_group(monkeypatch):
    monkeypatch.setattr(assistant_agent_module, "AI_API_KEY", "test-key")
    service = MCPService.__new__(MCPService)
    service.need_login = False
    service.need_login_prompt = ""
    mcp_tools = asyncio.run(service.list_tools())
    routed_names = set().union(*TOOL_GROUPS.values())

    assert set(API_TOOLS) <= routed_names
    assert {tool.name for tool in mcp_tools} <= routed_names
    selected_count_tools = AIAssistantMCPAgent.select_tools(
        "书库里有多少本书？",
        [tool.model_dump() for tool in mcp_tools],
    )
    assert {tool["name"] for tool in selected_count_tools} == TOOL_GROUPS["general"]
    graph = AIAssistantMCPAgent()._build_react_agent([tool.model_dump() for tool in mcp_tools])
    assert callable(graph.astream_events)


def test_mcp_schema_is_converted_to_validated_tool_arguments():
    schema = AIAssistantMCPAgent._tool_args_schema({
        "name": "reading",
        "inputSchema": {
            "type": "object",
            "properties": {
                "book_id": {"type": "integer", "description": "Book ID"},
                "read_state": {"type": "integer", "enum": [0, 1, 2]},
                "note": {"type": "string"},
            },
            "required": ["book_id", "read_state"],
        },
    })

    assert schema.model_validate({"book_id": 7, "read_state": 1}).book_id == 7
    with pytest.raises(ValidationError):
        schema.model_validate({"book_id": 7, "read_state": 4})
    with pytest.raises(ValidationError):
        schema.model_validate({"read_state": 1})


def test_mcp_schema_any_of_requirements_are_preserved():
    schema = AIAssistantMCPAgent._tool_args_schema({
        "name": "query_book_metadata",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "isbn": {"type": "string"},
            },
            "anyOf": [{"required": ["title"]}, {"required": ["isbn"]}],
        },
    })

    assert schema.model_validate({"isbn": "9780000000000"}).isbn == "9780000000000"
    assert schema.model_json_schema()["anyOf"] == [{"required": ["title"]}, {"required": ["isbn"]}]
    with pytest.raises(ValidationError):
        schema.model_validate({})


def test_react_graph_builds_from_an_mcp_tool_definition(monkeypatch):
    monkeypatch.setattr(assistant_agent_module, "AI_API_KEY", "test-key")
    agent = AIAssistantMCPAgent()

    graph = agent._build_react_agent([{
        "name": "search_books",
        "description": "Search the library",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Search term"}},
            "required": ["name"],
        },
    }])

    assert callable(graph.astream_events)


def test_mcp_tool_listing_failure_is_reported_instead_of_using_fake_tools():
    client = MCPStreamClient("http://localhost/mcp", "")
    client._send_request = AsyncMock(return_value={"error": {"message": "not available"}})

    with pytest.raises(RuntimeError, match="not available"):
        asyncio.run(client.list_tools())


class _FakeMCPClient:
    async def list_tools(self):
        return [{"name": "search_books"}]

    async def close(self):
        return None


class _FakeGraph:
    async def astream_events(self, input_data, config, version):
        assert input_data["messages"][-1]["content"] == "查询《三体》"
        assert config["recursion_limit"] == 16
        assert version == "v2"
        yield {"event": "on_tool_start", "name": "search_books"}
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": SimpleNamespace(content="找到了这本书。")},
        }


def test_react_events_keep_the_existing_websocket_event_shape():
    agent = AIAssistantMCPAgent()
    agent.mcp_client = _FakeMCPClient()

    def build_graph(selected_tools):
        assert [tool["name"] for tool in selected_tools] == ["search_books"]
        return _FakeGraph()

    agent._build_react_agent = build_graph

    events = asyncio.run(_collect_events(agent.process_user_input("查询《三体》")))

    assert events == [
        {"type": "status", "content": "正在调用工具: search_books..."},
        {"type": "content", "content": "找到了这本书。"},
    ]
    assert agent.conversation_history == [
        {"role": "user", "content": "查询《三体》"},
        {"role": "assistant", "content": "找到了这本书。"},
    ]


async def _collect_events(events):
    return [event async for event in events]
