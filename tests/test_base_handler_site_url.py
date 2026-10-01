#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Unit tests for BaseHandler.set_hosts() — external site URL under reverse proxies.

反代（Nginx/NPM）部署下，激活邮件、推书邮件、Podcast RSS 等场景生成的外链
依赖 set_hosts() 解析 X-Forwarded-* 头。这里用假请求直接验证其解析契约，
不启动真实服务。
"""

import unittest

from webserver.handlers.base import CONF, BaseHandler


class _FakeRequest:
    def __init__(self, headers=None, host="127.0.0.1:8000", protocol="http"):
        self.headers = headers or {}
        self.host = host
        self.protocol = protocol


def _make_handler(request):
    # 跳过 RequestHandler.__init__（需要 application/db），set_hosts 只触及
    # request/site_url/api_url/cdn_url，裸实例足够
    handler = BaseHandler.__new__(BaseHandler)
    handler.request = request
    return handler


class TestSetHosts(unittest.TestCase):
    def setUp(self):
        # set_hosts 会写全局 CONF["site_url"]，测试后还原避免污染其他用例
        self._saved_site_url = CONF.get("site_url")

    def tearDown(self):
        if self._saved_site_url is not None:
            CONF["site_url"] = self._saved_site_url

    def test_no_proxy_headers_uses_request(self):
        handler = _make_handler(_FakeRequest(host="192.168.1.5:8000", protocol="http"))
        handler.set_hosts()
        self.assertEqual(handler.site_url, "http://192.168.1.5:8000")

    def test_forwarded_host_proto_port(self):
        # talebook#498 同款场景：NPM 反代，外网 https + 非标准端口
        handler = _make_handler(_FakeRequest(
            headers={
                "X-Forwarded-Host": "books.example.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Port": "40443",
            },
            host="127.0.0.1:8000",
            protocol="http",
        ))
        handler.set_hosts()
        self.assertEqual(handler.site_url, "https://books.example.com:40443")

    def test_standard_port_not_appended(self):
        handler = _make_handler(_FakeRequest(
            headers={
                "X-Forwarded-Host": "books.example.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Port": "443",
            },
            host="127.0.0.1:8000",
            protocol="http",
        ))
        handler.set_hosts()
        self.assertEqual(handler.site_url, "https://books.example.com")

    def test_forwarded_host_with_port_wins(self):
        # Host 头自带端口时不再叠加 X-Forwarded-Port
        handler = _make_handler(_FakeRequest(
            headers={
                "X-Forwarded-Host": "books.example.com:8443",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Port": "40443",
            },
            host="127.0.0.1:8000",
            protocol="http",
        ))
        handler.set_hosts()
        self.assertEqual(handler.site_url, "https://books.example.com:8443")

    def test_multi_proxy_comma_split(self):
        # 多级代理取第一跳
        handler = _make_handler(_FakeRequest(
            headers={
                "X-Forwarded-Host": "books.example.com, internal.local",
                "X-Forwarded-Proto": "https, http",
                "X-Forwarded-Port": "40443, 8000",
            },
            host="127.0.0.1:8000",
            protocol="http",
        ))
        handler.set_hosts()
        self.assertEqual(handler.site_url, "https://books.example.com:40443")

    def test_scheme_fallback(self):
        # 只透传 X-Scheme 的老代理
        handler = _make_handler(_FakeRequest(
            headers={
                "X-Forwarded-Host": "books.example.com",
                "X-Scheme": "https",
            },
            host="127.0.0.1:8000",
            protocol="http",
        ))
        handler.set_hosts()
        self.assertEqual(handler.site_url, "https://books.example.com")

    def test_ipv6_forwarded_host_with_port(self):
        handler = _make_handler(_FakeRequest(
            headers={
                "X-Forwarded-Host": "[2001:db8::1]",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Port": "50006",
            },
            host="127.0.0.1:8000",
            protocol="http",
        ))
        handler.set_hosts()
        self.assertEqual(handler.site_url, "https://[2001:db8::1]:50006")


if __name__ == "__main__":
    unittest.main()
