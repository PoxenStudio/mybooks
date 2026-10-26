# -*- coding: utf-8 -*-
"""
wuming_client.py — 无名图书 (book345.com) HTTP 客户端

不依赖 MyBooks 服务器与任何凭据，直接通过公开 HTTP API 读取图书元数据。
所有接口只读，不修改书库、不上传任何本地数据。

API 端点：
  搜索   GET https://www.book345.com/api/search?key={关键词}&count={数量}
  详情   GET https://www.book345.com/api/detail/{isbn}
  AI摘要 GET https://www.book345.com/api/getBookSummarys/{isbn}
  榜单   GET https://www.book345.com/api/toplist?type=top&count=10
  热门   GET https://www.book345.com/api/recentHot?count=10[&tag=分类]
  分类   GET https://www.book345.com/api/tags
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

BASE = "https://www.book345.com/api"
TIMEOUT = 30


def _tolerant_ctx() -> ssl.SSLContext:
    """默认上下文 + 容忍服务端不发 TLS close_notify。

    背景：urllib 默认发送 `Connection: close`，而 Cloudflare 前端响应后直接关闭
    TCP 且不发送 close_notify，Python 3.13+ 的严格模式会在 read() 阶段抛
    UNEXPECTED_EOF_WHILE_READING（curl / keep-alive 客户端不受影响）。
    OP_IGNORE_UNEXPECTED_EOF 可消除该误报。
    """
    ctx = ssl.create_default_context()
    if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
        ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
    return ctx


_CTX = _tolerant_ctx()
# 直连 opener：系统代理链路失败时的兜底通道（须携带同一 SSL 上下文）
_NO_PROXY = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=_CTX),
)


def _read_json(resp) -> Dict[str, Any]:
    return json.loads(resp.read().decode("utf-8"))


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """GET 并解析 JSON；失败统一返回 ``{"status": "error", "message": ...}``。

    优先走默认链路（含系统代理）；网络层失败时自动重试直连。HTTPError 表示
    服务端已应答，不重试。

    注意：每次尝试都必须新建 Request 对象 —— urllib 走代理时会把代理设置写进
    Request（``req.set_proxy``），复用同一对象会导致重试仍然打向代理。
    """
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    def _fresh() -> urllib.request.Request:
        return urllib.request.Request(url, headers={"User-Agent": "mybooks-skill/1.0"})

    try:
        try:
            with urllib.request.urlopen(_fresh(), timeout=TIMEOUT, context=_CTX) as resp:
                return _read_json(resp)
        except urllib.error.HTTPError:
            raise
        except Exception:
            with _NO_PROXY.open(_fresh(), timeout=TIMEOUT) as resp:
                return _read_json(resp)
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"网络错误: {e.reason}"}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"JSON 解析失败: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"未知错误: {e}"}


def search_books(query: str, count: int = 10) -> Dict[str, Any]:
    """按书名/作者/ISBN/关键词搜索。返回 ``books`` 列表（含 isbn/title/author/
    publisher/pubDate/rate/summary/tags/img）。"""
    return _get("/search", {"key": query, "count": count})


def get_book_detail(isbn: str) -> Dict[str, Any]:
    """按 ISBN 获取详情：作者、出版社、出版日期、定价、评分、简介、目录等。"""
    return _get(f"/detail/{isbn}")


def get_book_guide(isbn: str) -> Dict[str, Any]:
    """AI 导读：编辑书评、核心看点、读者共识、章节摘要。

    源站对部分书目返回 ``summarys: null``，属正常行为，不是调用失败。
    """
    return _get(f"/getBookSummarys/{isbn}")


def get_toplist(book_type: str = "top", count: int = 10) -> Dict[str, Any]:
    """精选榜单。type：top 高分 / cold 遗珠 / new 新书 / weekly 周更 /
    law / social / career / history / tech。"""
    return _get("/toplist", {"type": book_type, "count": count})


def get_recent_hot(tag: Optional[str] = None, count: int = 10) -> Dict[str, Any]:
    """近期热门更新图书，可按分类 tag 过滤。"""
    params: Dict[str, Any] = {"count": count}
    if tag:
        params["tag"] = tag
    return _get("/recentHot", params)


def list_book_tags() -> Dict[str, Any]:
    """全部分类 tag。"""
    return _get("/tags")
