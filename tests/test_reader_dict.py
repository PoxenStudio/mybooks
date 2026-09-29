#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import json
import unittest
from unittest import mock

from tornado.httpclient import HTTPClientError

from tests.test_main import TestWithAdminUser, TestWithUserLogin, setUpModule as init
from webserver import loader
from webserver.handlers import reader_dict

CONF = loader.get_settings()

SITE_DICTS = [
    {"id": "d1", "name": "汉语", "url": "https://dict.example.com/sub", "token": "sk-secret", "enabled": True},
    {"id": "d2", "name": "English", "url": "http://10.0.0.2:8080", "token": "", "enabled": False},
]


def setUpModule():
    init()


class FakeResponse:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {}


class TestHelpers(unittest.TestCase):
    def test_sanitize_drops_bad_entries(self):
        out = reader_dict.sanitize_mydicts(
            [
                {"id": "ok", "url": "https://a.com", "token": " t ", "name": ""},
                {"id": "ok", "url": "https://dup.com"},
                {"id": "bad id", "url": "https://a.com"},
                {"id": "x", "url": "ftp://a.com"},
                "junk",
            ]
        )
        self.assertEqual(
            out, [{"id": "ok", "name": "ok", "url": "https://a.com", "token": "t", "enabled": True}]
        )
        self.assertEqual(reader_dict.sanitize_mydicts(None), [])

    def test_build_query_url(self):
        self.assertEqual(
            reader_dict.build_query_url("https://a.com/dict/", "你好"),
            "https://a.com/dict/api/v1/query?word=%E4%BD%A0%E5%A5%BD&full_style=true&all_langs=true",
        )
        self.assertTrue(
            reader_dict.build_query_url("https://a.com/api/v1/query", "w").startswith(
                "https://a.com/api/v1/query?"
            )
        )

    def test_build_res_url_stays_under_prefix(self):
        self.assertEqual(
            reader_dict.build_res_url("https://a.com/sub", "dict-res/3/res/a b.css"),
            "https://a.com/dict-res/3/res/a%20b.css",
        )
        self.assertIsNone(reader_dict.build_res_url("https://a.com", "dict-res/../etc/passwd"))
        self.assertIsNone(reader_dict.build_res_url("https://a.com", "api/v1/query"))


class TestReaderDictHandlers(TestWithUserLogin):
    def setUp(self):
        super().setUp()
        self._saved = {k: CONF.get(k) for k in ("READER_MYDICTS", "READER_DICT_BAIKE_ENABLED")}
        CONF["READER_MYDICTS"] = SITE_DICTS
        CONF["READER_DICT_BAIKE_ENABLED"] = False

    def tearDown(self):
        CONF.update(self._saved)
        super().tearDown()

    def test_config_hides_urls_and_tokens(self):
        d = self.json("/api/reader/dict-config")
        self.assertEqual(d["baike"], False)
        self.assertEqual(
            d["mydicts"],
            [
                {"id": "d1", "name": "汉语", "enabled": True},
                {"id": "d2", "name": "English", "enabled": False},
            ],
        )
        self.assertNotIn("sk-secret", json.dumps(d))

    def test_query_relays_with_token(self):
        body = json.dumps({"results": []}).encode()
        with _upstream(return_value=_resolved(FakeResponse(body))) as fetch:
            rsp = self.fetch("/api/reader/dict/d1/query?word=%E5%A5%BD")
        self.assertEqual(rsp.code, 200)
        self.assertEqual(json.loads(rsp.body), {"results": []})
        request = fetch.call_args[0][0]
        self.assertTrue(request.url.startswith("https://dict.example.com/sub/api/v1/query?word="))
        self.assertEqual(request.headers["Authorization"], "Bearer sk-secret")

    def test_disabled_dict_still_answers(self):
        body = b'{"results": []}'
        with _upstream(return_value=_resolved(FakeResponse(body))) as fetch:
            rsp = self.fetch("/api/reader/dict/d2/query?word=a")
        self.assertEqual(rsp.code, 200)
        self.assertNotIn("Authorization", fetch.call_args[0][0].headers)

    def test_unknown_dict_404(self):
        self.assertEqual(self.fetch("/api/reader/dict/nope/query?word=a").code, 404)
        self.assertEqual(self.fetch("/api/reader/dict/nope/res/dict-res/1/a.png").code, 404)

    def test_upstream_error_status(self):
        with _upstream(side_effect=HTTPClientError(401)):
            self.assertEqual(self.fetch("/api/reader/dict/d1/query?word=a").code, 401)
        with _upstream(side_effect=HTTPClientError(500)):
            self.assertEqual(self.fetch("/api/reader/dict/d1/query?word=a").code, 502)

    def test_resource_relay(self):
        rsp_obj = FakeResponse(b"body{}", {"Content-Type": "text/css"})
        with _upstream(return_value=_resolved(rsp_obj)) as fetch:
            rsp = self.fetch("/api/reader/dict/d1/res/dict-res/3/res/style.css")
        self.assertEqual(rsp.code, 200)
        self.assertEqual(rsp.body, b"body{}")
        self.assertEqual(rsp.headers["Content-Type"], "text/css")
        self.assertEqual(fetch.call_args[0][0].url, "https://dict.example.com/dict-res/3/res/style.css")
        self.assertNotIn("Authorization", fetch.call_args[0][0].headers)

    def test_resource_outside_prefix_rejected(self):
        self.assertEqual(self.fetch("/api/reader/dict/d1/res/api/v1/query").code, 400)


class TestReaderDictAdminTest(TestWithAdminUser):
    def post_test(self, payload):
        return self.json("/api/admin/reader/dict/test", method="POST", body=json.dumps(payload))

    def test_ok_counts_results(self):
        body = json.dumps({"results": [{}, {}]}).encode()
        with _upstream(return_value=_resolved(FakeResponse(body))) as fetch:
            d = self.post_test({"url": "https://unsaved.example.com", "token": "tk"})
        self.assertEqual(d["err"], "ok")
        self.assertEqual(d["count"], 2)
        request = fetch.call_args[0][0]
        self.assertTrue(request.url.startswith("https://unsaved.example.com/api/v1/query?word=test&"))
        self.assertEqual(request.headers["Authorization"], "Bearer tk")

    def test_invalid_url_not_fetched(self):
        with _upstream() as fetch:
            d = self.post_test({"url": "file:///etc/passwd"})
        self.assertEqual(d["err"], "params.invalid")
        fetch.assert_not_called()

    def test_upstream_errors(self):
        for code, err in ((404, "dict.not_mydict"), (401, "dict.unauthorized"), (500, "dict.http_error")):
            with _upstream(side_effect=HTTPClientError(code)):
                self.assertEqual(self.post_test({"url": "https://a.com"})["err"], err)
        with _upstream(return_value=_resolved(FakeResponse(b"<html>"))):
            self.assertEqual(self.post_test({"url": "https://a.com"})["err"], "dict.bad_response")


class _upstream:
    """Patch only reader_dict's AsyncHTTPClient — the test's own self.fetch
    uses the real one."""

    def __init__(self, **fetch_kwargs):
        self.fetch = mock.Mock(**fetch_kwargs)
        self._patch = mock.patch.object(reader_dict, "AsyncHTTPClient")

    def __enter__(self):
        self._patch.start().return_value.fetch = self.fetch
        return self.fetch

    def __exit__(self, *exc):
        self._patch.stop()


def _resolved(value):
    from tornado.concurrent import Future

    f = Future()
    f.set_result(value)
    return f
