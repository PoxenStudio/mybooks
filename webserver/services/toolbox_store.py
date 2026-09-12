#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""mybooks.top 工具商店客户端 —— ToolboxStoreClient

对应 document/Toolbox_Dynamic_Design.md 3.4 节。`mybooks.top/toolbox/` 是一个纯静态文件
服务（结构见 `poxenstudio/toolbox_store` 仓库），没有走 3.4 节最初设想的动态 `/api/toolbox/*`
接口 —— 商店索引就是一份托管的 `fulllist.json`（`{"tools": [...]}`），"检查更新"直接在这份
索引里按 `tool_id` 比对 `latest_revision`，不需要单独的查询接口；下载就是普通的静态文件 GET。

本客户端仍受 `ENABLE_TOOLBOX_STORE` 开关控制（3.4.1 节）：开关为 `False`（默认）时，
`get_index()` 不发起任何网络请求，直接返回空结果；`download()` 直接拒绝。
"""
import hashlib
import logging
import os
import tempfile
import time
from urllib.parse import urlparse

import requests

from webserver import loader
from webserver.i18n import _
from webserver.version import VERSION

CONF = loader.get_settings()

# 索引缓存 TTL（秒）：管理员打开 /admin/toolbox 时不必每次都请求外网，见 3.4 节。
INDEX_CACHE_TTL = 60 * 60

# 商店索引里的 icon_url/download_url 必须落在这个域名下才可信——fulllist.json 来自外部
# 服务，一旦被篡改（或未来商店索引其它来源）指向别的主机，图标/zip 下载就可能变成任意 URL，
# 这里做一层白名单校验，拒绝跨域的下载/图标地址。
ALLOWED_HOST = "mybooks.top"


def _is_allowed_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == ALLOWED_HOST


class ToolboxStoreError(Exception):
    """商店请求失败（网络错误、非 200、sha256 校验失败等），供上层 handler 捕获后转成友好错误。"""


class ToolboxStoreClient:
    # mybooks.top/toolbox/ 是静态文件服务，fulllist.json 就是完整商店索引，见
    # poxenstudio/toolbox_store 仓库的发布工具（生成 fulllist.json + logos/*.png）。
    INDEX_URL = "https://mybooks.top/toolbox/fulllist.json"

    def __init__(self):
        self.headers = {"MyBooks-Client": f"MyBooks/{VERSION}"}

    @staticmethod
    def enabled() -> bool:
        return bool(CONF.get("ENABLE_TOOLBOX_STORE", False))

    def get_index(self) -> list:
        """返回商店当前可安装的全部工具列表（`fulllist.json` 的 `tools` 数组）。

        `ENABLE_TOOLBOX_STORE=False` 时直接返回空列表，不发起任何网络请求。条目的
        `icon_url`/`download_url` 必须落在 `mybooks.top` 域名下，否则整条丢弃并记日志
        （见模块顶部 `_is_allowed_url` 的说明）。
        """
        if not self.enabled():
            return []
        try:
            resp = requests.get(self.INDEX_URL, headers=self.headers, timeout=30, verify=True)
            resp.raise_for_status()
            tools = resp.json().get("tools", [])
            if not isinstance(tools, list):
                return []
            result = []
            for entry in tools:
                if not isinstance(entry, dict):
                    continue
                if not _is_allowed_url(entry.get("download_url")) or not _is_allowed_url(entry.get("icon_url")):
                    logging.warning(
                        "[ToolboxStore] 忽略 tool_id=%s：icon_url/download_url 不在 %s 域名下",
                        entry.get("tool_id"), ALLOWED_HOST,
                    )
                    continue
                result.append(entry)
            return result
        except Exception as err:
            logging.error("[ToolboxStore] get_index failed: %s", err)
            return []

    def download(self, download_url: str, expected_sha256: str) -> str:
        """下载 zip 到本地临时文件并校验 sha256（**必须**校验，3.4 节），返回临时文件路径。

        调用方负责在用完（无论成功还是失败）后删除返回的临时文件。
        :raises ToolboxStoreError: 商店未开启 / 下载地址不在白名单域名下 / 下载失败 /
            sha256 校验不通过。
        """
        if not self.enabled():
            raise ToolboxStoreError(_("工具商店未开启"))
        if not expected_sha256:
            raise ToolboxStoreError(_("商店索引缺少 sha256 校验码，拒绝安装"))
        if not _is_allowed_url(download_url):
            raise ToolboxStoreError(_("下载地址不在 %s 域名下，已拒绝") % ALLOWED_HOST)

        fd, path = tempfile.mkstemp(prefix="mybooks_tool_store_", suffix=".zip")
        try:
            with os.fdopen(fd, "wb") as f:
                with requests.get(
                    download_url, headers=self.headers, timeout=60, stream=True, verify=True
                ) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            actual = _sha256_of(path)
            if actual.lower() != expected_sha256.lower():
                raise ToolboxStoreError(_("下载文件的 sha256 校验失败，已拒绝安装"))
            return path
        except ToolboxStoreError:
            _remove_quietly(path)
            raise
        except Exception as err:
            _remove_quietly(path)
            raise ToolboxStoreError(_("下载失败：%s") % err) from err


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 索引缓存（3.4 节：TTL 1 小时，避免每次打开 /admin/toolbox 都请求外网）
# ---------------------------------------------------------------------------

_index_cache = {"tools": [], "ts": 0.0}


def get_cached_index(force: bool = False) -> list:
    """带 TTL 缓存的商店索引；`ENABLE_TOOLBOX_STORE=False` 时缓存内容恒为空列表。"""
    now = time.time()
    if force or now - _index_cache["ts"] > INDEX_CACHE_TTL:
        _index_cache["tools"] = ToolboxStoreClient().get_index()
        _index_cache["ts"] = now
    return _index_cache["tools"]


def find_in_index(tool_id: str) -> dict:
    """从缓存索引里按 tool_id 查找一条记录，找不到返回空 dict。"""
    for entry in get_cached_index():
        if entry.get("tool_id") == tool_id:
            return entry
    return {}
