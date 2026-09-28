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
