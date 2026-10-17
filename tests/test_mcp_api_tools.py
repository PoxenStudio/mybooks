#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""MCP skill-aligned tools: parity with skills/mybooks and loopback HTTP calls."""

import asyncio
import json
import os
import re
import types
import unittest

import tornado.web
from tornado.options import options, define
from tornado.testing import AsyncHTTPTestCase, gen_test

from webserver.mcp.api_tools import API_TOOLS
from webserver.mcp.mcp_service import MCPService

SKILL_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "skills", "mybooks", "scripts", "mybooks_api.py")
# 读写调用方本地文件的 skill 工具，MCP 上会变成读写服务器文件，刻意不暴露
MCP_EXCLUDED = {"book_upload", "tts_clone_upload", "tts_clone_audio"}


def skill_tool_names():
    src = open(SKILL_SCRIPT, encoding="utf-8").read()
    m = re.search(r"available_tools = \[(.*?)\]", src, re.S)
    return set(re.findall(r'"(\w+)"', m.group(1)))


class TestToolParity(unittest.TestCase):
    def test_same_tools_as_skill(self):
        self.assertEqual(skill_tool_names() - MCP_EXCLUDED, set(API_TOOLS))

    def test_schema_required_fields_exist(self):
        for t in API_TOOLS.values():
            for name in t.required:
                self.assertIn(name, t.properties, t.name)


class TestToolRequests(unittest.TestCase):
    def run_tool(self, name, args):
        calls = []

        async def call(method, path, params=None, json=None):
            calls.append((method, path, params, json))
            return {"err": "ok", "books": [{"id": 7}]}

        result = asyncio.run(API_TOOLS[name].func(call, args))
        return result, calls

    def test_search_books_fields(self):
        _, calls = self.run_tool("search_books", {"author": "余华", "exact": True, "page": 2, "num": 10})
        self.assertEqual(calls, [("GET", "/api/search", {"num": 10, "start": 10, "author": "余华", "exact": 1}, None)])

    def test_search_books_requires_condition(self):
        result, calls = self.run_tool("search_books", {})
        self.assertEqual(result["err"], "params.invalid")
        self.assertEqual(calls, [])

    def test_delete_requires_confirm(self):
        result, calls = self.run_tool("delete_booklist", {"booklist_id": 3})
        self.assertEqual(result["err"], "confirm.required")
        self.assertEqual([c[0] for c in calls], ["GET"])

    def test_refer_search_sends_only_given_conditions(self):
        _, calls = self.run_tool("book_refer_search", {"book_id": 42, "isbn": "9787536692930"})
        self.assertEqual(calls, [("GET", "/api/book/42/refer", {"isbn": "9787536692930"}, None)])

        _, calls = self.run_tool("book_refer_search", {"book_id": 42})
        self.assertEqual(calls, [("GET", "/api/book/42/refer", {}, None)])

    def test_refer_apply_modes(self):
        # 表单参数走 query 串（handler 用 get_argument，读不到 JSON body），三种模式各自一个 flag
        for mode, flag in (("only_meta", "only_meta"), ("only_cover", "only_cover"),
                           ("only_author_comments", "only_author_comments")):
            _, calls = self.run_tool("book_refer_apply",
                                     {"book_id": 42, "provider_key": "douban", "provider_value": "2567698", "mode": mode})
            self.assertEqual(calls, [("POST", "/api/book/42/refer",
                                      {"provider_key": "douban", "provider_value": "2567698", flag: "yes"}, None)], mode)

    def test_refer_apply_full_mode_and_metadata(self):
        candidate = {"title": "三体", "cover_url": "https://example.com/c.jpg", "provider_value": "2567698"}
        _, calls = self.run_tool("book_refer_apply",
                                 {"book_id": 42, "provider_key": "neodb", "provider_value": "2567698", "metadata": candidate})
        self.assertEqual(calls, [("POST", "/api/book/42/refer",
                                  {"provider_key": "neodb", "provider_value": "2567698",
                                   "metadata": json.dumps(candidate, ensure_ascii=False)}, None)])

    def test_refer_apply_requires_candidate(self):
        result, calls = self.run_tool("book_refer_apply", {"book_id": 42, "provider_key": "douban"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(calls, [])

        result, calls = self.run_tool("book_refer_apply",
                                      {"book_id": 42, "provider_key": "douban", "provider_value": "1", "mode": "meta"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(calls, [])

    def test_refer_apply_douban_needs_no_metadata(self):
        # 豆瓣源按 provider_value 重新拉取，metadata 可省
        _, calls = self.run_tool("book_refer_apply",
                                 {"book_id": 42, "provider_key": "douban", "provider_value": "2567698"})
        self.assertEqual(calls, [("POST", "/api/book/42/refer", {"provider_key": "douban", "provider_value": "2567698"}, None)])

    def test_refer_apply_metadata_required_for_other_sources(self):
        # 非豆瓣源不带候选时 handler 会退回书自身元数据并返回 ok（静默空操作），因此直接拦下
        result, calls = self.run_tool("book_refer_apply",
                                      {"book_id": 42, "provider_key": "neodb", "provider_value": "2567698"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(calls, [])

    def test_epub_fix_body(self):
        _, calls = self.run_tool("epub_fix", {"book_ids": 42, "backup": True})
        self.assertEqual(calls, [("POST", "/api/toolbox/epub_fixer/repair", None, {"book_ids": [42], "backup": True})])

        _, calls = self.run_tool("epub_fix", {"book_ids": [42, 43]})
        self.assertEqual(calls, [("POST", "/api/toolbox/epub_fixer/repair", None, {"book_ids": [42, 43]})])

    def test_epub_fix_string_booleans(self):
        # handler 对 backup/reconvert 用 bool(...)，字符串 "false" 会变 True —— 必须先归一
        _, calls = self.run_tool("epub_fix", {"book_ids": [42], "backup": "false", "reconvert": "0"})
        self.assertEqual(calls, [("POST", "/api/toolbox/epub_fixer/repair", None, {"book_ids": [42], "backup": False, "reconvert": False})])

        _, calls = self.run_tool("epub_fix", {"book_ids": [42], "backup": "true", "reconvert": "yes"})
        self.assertEqual(calls, [("POST", "/api/toolbox/epub_fixer/repair", None, {"book_ids": [42], "backup": True, "reconvert": True})])

    def test_epub_fix_accepts_single_id_in_schema(self):
        # 宽松客户端会按 schema 校验；单个整数必须合法，否则单本修复在客户端就被挡下
        schema = API_TOOLS["epub_fix"].properties["book_ids"]
        self.assertEqual(schema["oneOf"], [{"type": "integer"}, {"type": "array", "items": {"type": "integer"}}])

    def test_epub_fix_progress(self):
        _, calls = self.run_tool("epub_fix_progress", {})
        self.assertEqual(calls, [("GET", "/api/toolbox/epub_fixer/progress", None, None)])

    def test_legacy_search_args(self):
        args = MCPService._legacy_search_args({"name": "三体", "rating": ">=4", "tags": "科幻,长篇"})
        self.assertEqual(args, {"name": '(title:"三体" OR authors:"三体") AND rating:>=4 AND tags:"科幻" AND tags:"长篇"'})
        self.assertEqual(MCPService._legacy_search_args({"name": "x"}), {"name": "x"})


class EchoHandler(tornado.web.RequestHandler):
    def get(self, *a):
        uid = self.get_secure_cookie("user_id")
        self.write({"err": "ok", "uid": uid.decode() if uid else None, "host": self.request.headers.get("X-Forwarded-Host"),
                    "query": {k: v[0].decode() for k, v in self.request.query_arguments.items()}})

    def post(self, *a):
        self.write({"err": "ok", "uid": self.get_secure_cookie("user_id").decode(), "body": json.loads(self.request.body or b"{}")})


class TestLoopback(AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application([(r"/api/(.*)", EchoHandler)], cookie_secret="test-secret")

    def setUp(self):
        super().setUp()
        for name, default, typ in (("port", 8080, int), ("host", "", str)):
            if name not in options.as_dict():
                define(name, default=default, type=typ)
        self._saved = (options.port, options.host)
        options.port, options.host = self.get_http_port(), "127.0.0.1"
        svc = MCPService.__new__(MCPService)
        svc.token = None
        svc.need_login = True
        svc.need_login_prompt = ""
        svc.authenticated_tokens = {"tk": {"user_id": 5, "username": "u", "expires_at": 9e12}}
        req = types.SimpleNamespace(headers={}, host="books.example.com", protocol="https", remote_ip="1.2.3.4")
        svc.base_handler = types.SimpleNamespace(application=self._app, request=req)
        self.svc = svc

    def tearDown(self):
        options.port, options.host = self._saved
        super().tearDown()

    async def call(self, name, args):
        return json.loads((await self.svc.call_api_tool(name, args))[0].text)

    @gen_test
    async def test_get_as_mcp_user(self):
        d = await self.call("search_books", {"token": "tk", "isbn": "978-7-5366-9293-0"})
        self.assertEqual(d["uid"], "5")
        self.assertEqual(d["host"], "books.example.com")
        self.assertEqual(d["query"]["isbn"], "978-7-5366-9293-0")

    @gen_test
    async def test_post_json_body(self):
        d = await self.call("edit_book", {"token": "tk", "book_id": 3, "title": "新书名"})
        self.assertEqual(d, {"err": "ok", "uid": "5", "body": {"title": "新书名"}})

    @gen_test
    async def test_requires_auth(self):
        d = await self.call("get_book", {"book_id": 1})
        self.assertEqual(d["status"], "error")

    @gen_test
    async def test_tools_list_contains_api_tools(self):
        names = [t.name for t in await self.svc.list_tools()]
        self.assertTrue(set(API_TOOLS) <= set(names))
        self.assertIn("login", names)


if __name__ == "__main__":
    unittest.main()
