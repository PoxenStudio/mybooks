import unittest
from types import SimpleNamespace
from unittest.mock import patch

from webserver.assistant.book_ai_client import AIBookInfo, BookAIClient
from webserver.services.ai_fillinfo import AIFillInfoService

BOOK_JSON = (
    '{"category": "小说", "tags": ["历史", "文学"], "authors": ["作者甲"], '
    '"pubdate": "2026-05", "summary": "简介", "author_intro": "作者介绍"}'
)


class FakeResponse:
    def __init__(self, content, search_calls=None, finish_reason="stop"):
        self.choices = [
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
        message = {"content": content}
        if search_calls:
            message["server_tool_calls"] = search_calls
        self._dump = {
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "server_tool_use": {"tool_search": 1 if search_calls else 0},
            },
        }

    def model_dump(self):
        return self._dump


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected extra model call")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses):
        self.base_url = "https://api.deepseek.com"
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


class FakeBadRequest(Exception):
    status_code = 400


def make_client(responses, model="deepseek-v4-flash", url="https://api.deepseek.com"):
    fake = FakeClient(responses)
    client = BookAIClient(url=url, key="test-key", model=model, client=fake)
    return client, fake


@patch("webserver.assistant.book_ai_client.BookSearch.search_books", return_value=[])
class BookAIClientWebSearchTest(unittest.TestCase):
    def test_deep_mode_uses_web_search(self, _mock_search):
        client, fake = make_client([FakeResponse(BOOK_JSON)])
        info = client.get_book_info("书名", ["作者"], search_mode="deep")

        self.assertIsNotNone(info)
        self.assertEqual(client.model, "deepseek-flash")
        call = fake.chat.completions.calls[0]
        self.assertEqual(call["model"], "deepseek-flash")
        self.assertEqual(call["tools"], [{"type": "deepseek_web_search"}])
        self.assertNotIn("response_format", call)
        self.assertEqual(call["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertEqual(call["reasoning_effort"], "high")
        self.assertNotIn("temperature", call)
        self.assertEqual(call["max_tokens"], 100000)

    def test_fast_mode_uses_web_search(self, _mock_search):
        client, fake = make_client([FakeResponse(BOOK_JSON)])
        client.get_book_info("书名", ["作者"], search_mode="fast")

        call = fake.chat.completions.calls[0]
        self.assertEqual(call["tools"], [{"type": "deepseek_web_search"}])
        self.assertNotIn("response_format", call)
        self.assertEqual(call["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertNotIn("temperature", call)
        self.assertEqual(call["max_tokens"], 4000)

    def test_non_deepseek_keeps_json_mode(self, _mock_search):
        client, fake = make_client(
            [FakeResponse(BOOK_JSON)],
            model="gpt-4o-mini",
            url="https://api.openai.com/v1",
        )
        client.get_book_info("书名", ["作者"], search_mode="auto")

        call = fake.chat.completions.calls[0]
        self.assertNotIn("tools", call)
        self.assertNotIn("extra_body", call)
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual(call["temperature"], 0.2)

    def test_tool_400_falls_back_without_tools(self, _mock_search):
        client, fake = make_client(
            [FakeBadRequest("deepseek_web_search is not supported"), FakeResponse(BOOK_JSON)]
        )
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertIsNotNone(info)
        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertIn("tools", fake.chat.completions.calls[0])
        self.assertNotIn("tools", fake.chat.completions.calls[1])
        self.assertEqual(
            fake.chat.completions.calls[1]["response_format"],
            {"type": "json_object"},
        )

    def test_fenced_json_is_parsed_without_second_call(self, _mock_search):
        fenced = "```json\n" + BOOK_JSON + "\n```"
        client, fake = make_client([FakeResponse(fenced)])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertIsNotNone(info)
        self.assertEqual(len(fake.chat.completions.calls), 1)

    def test_parse_failure_runs_json_second_pass(self, _mock_search):
        client, fake = make_client(
            [FakeResponse("这不是 JSON"), FakeResponse(BOOK_JSON)]
        )
        info = client.get_book_info("书名", ["作者"], search_mode="deep")

        self.assertIsNotNone(info)
        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertIn("tools", fake.chat.completions.calls[0])
        self.assertNotIn("tools", fake.chat.completions.calls[1])
        self.assertEqual(
            fake.chat.completions.calls[1]["response_format"],
            {"type": "json_object"},
        )
        self.assertEqual(
            fake.chat.completions.calls[1]["extra_body"],
            {"thinking": {"type": "disabled"}},
        )

    def test_legacy_model_alias_is_resolved_for_deepseek(self, _mock_search):
        client, _fake = make_client([], model="deepseek-chat")
        self.assertEqual(client.model, "deepseek-flash")

        other, _fake_other = make_client(
            [], model="deepseek-chat", url="https://example.com/v1"
        )
        self.assertEqual(other.model, "deepseek-chat")

    def test_search_usage_logging_does_not_crash(self, _mock_search):
        search_calls = [{
            "calls": [{
                "action": {"queries": ["书名"]},
                "sources": [{"url": "https://example.com/book"}],
            }],
        }]
        client, _fake = make_client([FakeResponse(BOOK_JSON, search_calls=search_calls)])
        with self.assertLogs(level="INFO") as logs:
            info = client.get_book_info("书名", ["作者"], search_mode="fast")
        self.assertIsNotNone(info)
        self.assertTrue(any("web search" in line for line in logs.output))

    def test_deep_400_keeps_thinking(self, _mock_search):
        client, fake = make_client([
            FakeBadRequest("deepseek_web_search is not supported"),
            FakeResponse(BOOK_JSON),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="deep")

        self.assertIsNotNone(info)
        self.assertEqual(len(fake.chat.completions.calls), 2)
        second = fake.chat.completions.calls[1]
        self.assertNotIn("tools", second)
        self.assertEqual(second["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertEqual(second["reasoning_effort"], "high")
        self.assertEqual(second["max_tokens"], 100000)
        self.assertEqual(second["timeout"], 600)

    def test_non_tool_400_does_not_block_search(self, _mock_search):
        client, fake = make_client([FakeBadRequest("Content Exists Risk")])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertIsNone(info)
        self.assertEqual(len(fake.chat.completions.calls), 1)

    def test_empty_truncated_response_triggers_second_pass(self, _mock_search):
        client, fake = make_client([
            FakeResponse("", finish_reason="length"),
            FakeResponse(BOOK_JSON),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="deep")

        self.assertIsNotNone(info)
        self.assertEqual(len(fake.chat.completions.calls), 2)

    def test_payload_types_are_normalized(self, _mock_search):
        payload = (
            '{"category": null, "tags": "科幻", "authors": null, '
            '"pubdate": null, "summary": null, "author_intro": ""}'
        )
        client, _fake = make_client([FakeResponse(payload)])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertEqual(info.category, "")
        self.assertEqual(info.tags, ["科幻"])
        self.assertEqual(info.authors, [])
        self.assertEqual(info.summary, "")

    def test_comments_escape_html(self, _mock_search):
        info = AIBookInfo(
            summary='<img src=x onerror="alert(1)">',
            author_intro="<script>alert(1)</script>",
        )
        self.assertNotIn("<img", info.comments)
        self.assertNotIn("<script", info.comments)
        self.assertIn("&lt;img", info.comments)

    def test_v4_pro_disables_default_thinking(self, _mock_search):
        client, fake = make_client([FakeResponse(BOOK_JSON)], model="deepseek-v4-pro")
        client.get_book_info("书名", ["作者"], search_mode="auto")

        call = fake.chat.completions.calls[0]
        self.assertNotIn("tools", call)
        self.assertEqual(call["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual(call["max_tokens"], 3500)
        self.assertEqual(call["temperature"], 0.2)

    def test_non_official_deep_mode_falls_back_to_off(self, _mock_search):
        client, fake = make_client(
            [FakeResponse(BOOK_JSON)],
            model="gpt-4o-mini",
            url="https://api.openai.com/v1",
        )
        client.get_book_info("书名", ["作者"], search_mode="deep")

        call = fake.chat.completions.calls[0]
        self.assertNotIn("tools", call)
        self.assertNotIn("extra_body", call)
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual(call["max_tokens"], 1500)
        self.assertEqual(call["temperature"], 0.2)
        self.assertEqual(call["timeout"], 60)

    def test_invalid_search_mode_defaults_to_auto(self, _mock_search):
        client, fake = make_client([FakeResponse(BOOK_JSON)])
        client.get_book_info("书名", ["作者"], search_mode="bogus")

        call = fake.chat.completions.calls[0]
        self.assertIn("tools", call)
        self.assertEqual(call["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(call["max_tokens"], 4000)
        self.assertNotIn("reasoning_effort", call)

    def test_nested_payload_types_are_dropped(self, _mock_search):
        payload = (
            '{"category": ["科幻"], "tags": [{"name": "甲"}], '
            '"authors": [{"name": "乙"}], "summary": {"text": "abc"}}'
        )
        client, fake = make_client([FakeResponse(payload), FakeResponse("{}")])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertEqual(info.category, "")
        self.assertEqual(info.tags, [])
        self.assertEqual(info.authors, [])
        self.assertEqual(info.summary, "")

    def test_blocked_search_resets_for_next_book(self, _mock_search):
        client, fake = make_client([
            FakeBadRequest("deepseek_web_search is not supported"),
            FakeResponse(BOOK_JSON),
            FakeResponse(BOOK_JSON),
        ])
        client.get_book_info("第一本", ["作者"], search_mode="fast")
        client.get_book_info("第二本", ["作者"], search_mode="fast")

        self.assertEqual(len(fake.chat.completions.calls), 3)
        self.assertIn("tools", fake.chat.completions.calls[2])

    def test_length_keeps_first_valid_payload_when_second_is_empty(self, _mock_search):
        client, fake = make_client([
            FakeResponse(BOOK_JSON, finish_reason="length"),
            FakeResponse("{}"),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="deep")

        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertEqual(info.category, "小说")
        self.assertEqual(info.tags, ["历史", "文学"])

    def test_single_line_fenced_json(self, _mock_search):
        fenced = '```json {"category": "小说", "tags": ["科幻"]} ```'
        client, fake = make_client([FakeResponse(fenced)])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertEqual(len(fake.chat.completions.calls), 1)
        self.assertEqual(info.category, "小说")
        self.assertEqual(info.tags, ["科幻"])

    def test_second_pass_exception_keeps_first_result(self, _mock_search):
        client, fake = make_client([
            FakeResponse(BOOK_JSON, finish_reason="length"),
            RuntimeError("timeout"),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="deep")

        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertEqual(info.category, "小说")
        self.assertEqual(info.tags, ["历史", "文学"])

    def test_pubdate_only_payload_triggers_second_pass(self, _mock_search):
        client, fake = make_client([
            FakeResponse('{"pubdate": "2026"}'),
            FakeResponse(BOOK_JSON),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertEqual(info.category, "小说")

    def test_http_deepseek_is_not_treated_as_official(self, _mock_search):
        client, fake = make_client(
            [FakeResponse(BOOK_JSON)],
            url="http://api.deepseek.com",
        )
        client.get_book_info("书名", ["作者"], search_mode="fast")

        call = fake.chat.completions.calls[0]
        self.assertNotIn("tools", call)
        self.assertEqual(call["response_format"], {"type": "json_object"})

    def test_connection_escapes_unexpected_content(self, _mock_search):
        client, fake = make_client([
            FakeResponse('<img src=x onerror="alert(1)">'),
        ])
        ok, msg = client.test_connection()

        self.assertFalse(ok)
        self.assertIn("&lt;img", msg)
        call = fake.chat.completions.calls[0]
        self.assertEqual(call["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(call["temperature"], 0.0)

    def test_info_valid_with_synopsis_only(self, _mock_search):
        self.assertTrue(AIBookInfo(summary="原书简介").is_valid())
        self.assertTrue(AIBookInfo(author_intro="作者介绍").is_valid())
        self.assertFalse(AIBookInfo().is_valid())

    def test_tool_fallback_malformed_runs_second_pass(self, _mock_search):
        client, fake = make_client([
            FakeBadRequest("deepseek_web_search is not supported"),
            FakeResponse("这不是 JSON"),
            FakeResponse(BOOK_JSON),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertIsNotNone(info)
        self.assertEqual(len(fake.chat.completions.calls), 3)
        self.assertNotIn("tools", fake.chat.completions.calls[1])
        self.assertNotIn("tools", fake.chat.completions.calls[2])
        self.assertEqual(
            fake.chat.completions.calls[2]["response_format"],
            {"type": "json_object"},
        )

    def test_merge_prefers_first_summary(self, _mock_search):
        first = '{"summary": "原书简介原文"}'
        second = '{"summary": "这段是一段更长的模型生成摘要", "category": "小说"}'
        client, fake = make_client([
            FakeResponse(first, finish_reason="length"),
            FakeResponse(second),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertEqual(info.summary, "原书简介原文")
        self.assertEqual(info.category, "小说")

    def test_prompt_requires_original_synopsis_text(self, _mock_search):
        client, fake = make_client([FakeResponse(BOOK_JSON)])
        client.get_book_info("书名", ["作者"], search_mode="fast")

        call = fake.chat.completions.calls[0]
        system_message = call["messages"][0]["content"]
        user_message = call["messages"][1]["content"]
        self.assertIn("原书简介原文", system_message)
        self.assertIn("逐字保留原文", system_message)
        self.assertIn("原书简介", user_message)
        self.assertNotIn("existing_comments", user_message)

    def test_custom_prompt_overrides_default(self, _mock_search):
        with patch.dict(
            "webserver.assistant.book_ai_client.CONF",
            {"AI_FILL_PROMPT": "自定义提示词"},
            clear=False,
        ):
            client, fake = make_client([FakeResponse(BOOK_JSON)])
            client.get_book_info("书名", ["作者"], search_mode="fast")

        system_message = fake.chat.completions.calls[0]["messages"][0]["content"]
        self.assertIn("自定义提示词", system_message)
        self.assertNotIn("你是一个专业的图书信息分析助手", system_message)

    def test_language_hint_edges(self, _mock_search):
        self.assertEqual(
            AIFillInfoService._language_hint(SimpleNamespace(languages=["eng"])),
            "English (eng)",
        )
        self.assertEqual(
            AIFillInfoService._language_hint(SimpleNamespace(languages=[])),
            "中文 (zho)",
        )
        self.assertEqual(
            AIFillInfoService._language_hint(SimpleNamespace(languages=5)),
            "中文 (zho)",
        )

    def test_second_pass_merge_keeps_first_summary(self, _mock_search):
        first = '{"summary": "这是完整的原书简介"}'
        second = '{"category": "小说", "tags": ["文学"]}'
        client, fake = make_client([
            FakeResponse(first, finish_reason="length"),
            FakeResponse(second),
        ])
        info = client.get_book_info("书名", ["作者"], search_mode="fast")

        self.assertEqual(len(fake.chat.completions.calls), 2)
        self.assertEqual(info.summary, "这是完整的原书简介")
        self.assertEqual(info.category, "小说")
        self.assertEqual(info.tags, ["文学"])

    def test_language_is_passed_to_prompt(self, _mock_search):
        client, fake = make_client([FakeResponse(BOOK_JSON)])
        client.get_book_info(
            "书名",
            ["作者"],
            language="English (eng)",
            search_mode="fast",
        )

        call = fake.chat.completions.calls[0]
        system_message = call["messages"][0]["content"]
        user_message = call["messages"][1]["content"]
        self.assertIn("输出语言必须与书籍元信息语言一致", system_message)
        self.assertIn("书籍元信息语言：English (eng)", user_message)
        self.assertIn("忠实翻译", user_message)
        self.assertIn("最终要求", user_message)
        self.assertTrue(user_message.rstrip().endswith("不增删、不改写、不概括。"))


if __name__ == "__main__":
    unittest.main()
