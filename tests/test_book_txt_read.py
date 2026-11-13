#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""TxtRead（/api/read/txt/<id>）的匿名放行契约。

分享访客（以及全局 ALLOW_GUEST_READ 下的游客）没有 current_user，但正文接口
必须按 BookAccessService 的判定放行。这里锁死的是「handler 不再被 @auth 提前
拦成 user.need_login」——否则分享落地页能打开，点进 TXT 阅读器却会被前端
$backend 统一跳回登录页。

走真实的 @js 装饰器路径（捕获 self.write 的 payload），不是直接调方法体：
接线（@auth 是否还在）错了单测方法体是看不出来的。
"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from webserver.handlers.book import TxtRead


class TestTxtReadGuestAccess(unittest.TestCase):
    def setUp(self):
        fd, self.txt_path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "wb") as f:
            f.write("第一章\n正文".encode("utf-8"))
        self.addCleanup(os.remove, self.txt_path)

    def _call(self, guest_read_allowed):
        handler = TxtRead.__new__(TxtRead)
        handler.request = mock.Mock(headers={})
        handler.write = mock.Mock()
        handler.finish = mock.Mock()
        handler.set_header = mock.Mock()
        handler.get_argument = lambda name, default="": {
            "start": "0", "end": "-1"}.get(name, default)
        handler.get_book = lambda bid, raise_exception=False: {
            "id": 7, "title": "测试书", "fmt_txt": self.txt_path}
        # 匿名访客：没有登录态
        handler.current_user = None

        with mock.patch("webserver.handlers.book.BookAccessService") as access:
            access.guest_read_allowed.return_value = guest_read_allowed
            access.share_read_granted.return_value = guest_read_allowed
            asyncio.run(handler.get("7"))
        return handler.write.call_args[0][0]

    def test_anonymous_share_guest_can_read(self):
        rsp = self._call(guest_read_allowed=True)
        self.assertEqual(rsp["err"], "ok")
        self.assertIn("正文", rsp["content"])

    def test_anonymous_without_grant_is_rejected(self):
        rsp = self._call(guest_read_allowed=False)
        self.assertEqual(rsp["err"], "user.need_login")


if __name__ == "__main__":
    unittest.main()
