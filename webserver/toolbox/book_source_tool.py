"""
book_source_tool — 书源管理工具（MyBooks Toolbox 集成）

提供书源的 CRUD、搜索测试、下载/EPUB 生成、ZIP 导入等功能。
"""

import ipaddress
import json
import logging
import os
import re
import socket
import tempfile
import threading
import traceback
from typing import Callable, Optional
from urllib.parse import urlparse, urlunparse

import requests

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool
from webserver.toolbox.book_source_engine import (
    BookSource,
    load_sources_from_json,
    dump_sources_to_json,
    search_books,
    fetch_book_info,
    fetch_toc,
    fetch_content,
    parse_explore_categories,
    fetch_explore,
    SearchTaskService,
)
from webserver.toolbox.book_source_engine.epub_helper import generate_epub as _generate_epub

logger = logging.getLogger(__name__)

_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/125.0.0.0 Safari/537.36")


def _iter_all_rule_strings(item: dict):
    """递归遍历书源的规则字段，产出 (field_path, string_value)。"""
    if not isinstance(item, dict):
        return
    for key, val in item.items():
        path = str(key)
        if isinstance(val, str):
            yield path, val
        elif isinstance(val, dict):
            for k2, v2 in val.items():
                sub = f"{path}.{k2}"
                if isinstance(v2, str):
                    yield sub, v2
                elif isinstance(v2, list):
                    for i, el in enumerate(v2):
                        if isinstance(el, str):
                            yield f"{sub}[{i}]", el
                        elif isinstance(el, dict):
                            for k3, v3 in el.items():
                                if isinstance(v3, str):
                                    yield f"{sub}[{i}].{k3}", v3


class BookSourceTool(BaseTool):
    """书源管理工具"""

    service_item_name = "书源管理"

    # 每个用户最近一次下载/生成任务（多用户互不干扰）
    _last_task_ids: dict[int, int] = {}
    _tasks_lock = threading.Lock()

    # 书源文件读写锁（防止并发保存互相覆盖）
    _sources_lock = threading.RLock()

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "book_source",
            "name": _("书源管理"),
            "description": _("书源管理工具，支持添加/编辑/测试/下载书源"),
            "revision": "1.2.0",
            "author": "MyBooks",
            "publish_date": "2025-07-01",
        }

    # ── 并发控制 ────────────────────────────────────────────────

    @classmethod
    def is_running(cls, user_id: int = 1) -> bool:
        task = cls.get_last_task(user_id)
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls, user_id: int = 1) -> Optional[dict]:
        with cls._tasks_lock:
            task_id = cls._last_task_ids.get(user_id)
        if task_id is None:
            return None
        return BackgroundService().get_task(task_id)

    @classmethod
    def set_last_task(cls, user_id: int, task_id: int):
        with cls._tasks_lock:
            cls._last_task_ids[user_id] = task_id

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """SSRF 防护：仅允许公网 http/https，拒绝私有/回环/链路本地等地址。"""
        if not url:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        try:
            infos = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
        except OSError:
            return False
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                return False
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
                return False
        return True

    # ── 书源 CRUD ──────────────────────────────────────────────

    @AsyncService.register_function
    def list_sources(self) -> list[dict]:
        """列出所有已保存的书源。"""
        sources = self._load_sources()
        return [s.to_dict() if hasattr(s, "to_dict") else s for s in sources]

    @AsyncService.register_function
    def get_source(self, name: str) -> Optional[dict]:
        """按书源名查找。"""
        for s in self._load_sources():
            if s.bookSourceName == name:
                return s.to_dict() if hasattr(s, "to_dict") else s
        return None

    @AsyncService.register_function
    def add_source(self, source_data: dict) -> dict:
        """添加或更新一个书源。"""
        with self._sources_lock:
            sources = self._load_sources()
            new_source = BookSource.from_dict(source_data)
            for i, s in enumerate(sources):
                if s.bookSourceName == new_source.bookSourceName:
                    sources[i] = new_source
                    self._save_sources(sources)
                    return {"status": "updated", "name": new_source.bookSourceName}
            sources.append(new_source)
            self._save_sources(sources)
            return {"status": "added", "name": new_source.bookSourceName}

    @AsyncService.register_function
    def delete_source(self, name: str) -> dict:
        """删除一个书源。"""
        with self._sources_lock:
            sources = self._load_sources()
            before = len(sources)
            sources = [s for s in sources if s.bookSourceName != name]
            if len(sources) == before:
                return {"status": "not_found", "name": name}
            self._save_sources(sources)
            return {"status": "deleted", "name": name}

    @AsyncService.register_function
    def toggle_source(self, name: str, enabled: bool = None) -> dict:
        """启用/禁用一个书源。"""
        with self._sources_lock:
            sources = self._load_sources()
            for s in sources:
                if s.bookSourceName == name:
                    if enabled is not None:
                        s.enabled = enabled
                    else:
                        s.enabled = not s.enabled
                    self._save_sources(sources)
                    return {"status": "toggled", "name": name, "enabled": s.enabled}
            return {"status": "not_found", "name": name}

    # ── 书源校验 ──────────────────────────────────────────────

    @staticmethod
    def _iter_rule_values(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from BookSourceTool._iter_rule_values(v)
        elif isinstance(value, list):
            for v in value:
                yield from BookSourceTool._iter_rule_values(v)

    @staticmethod
    def _has_unsupported_js(value):
        if not isinstance(value, str):
            return False
        low = value.lower()
        return "<js>" in low or "{{js." in low or "{{java" in low or "java.ajax" in low or "java.post" in low

    @staticmethod
    def _requires_js(raw):
        rule_search = raw.get("ruleSearch") or {}
        rule_content = raw.get("ruleContent") or {}
        search_url = raw.get("searchUrl", "")
        search_js_blocked = BookSourceTool._has_unsupported_js(search_url) or (
            "@js:" in search_url and not search_url.strip().startswith("@js:")
        )
        return (
            search_js_blocked
            or BookSourceTool._has_unsupported_js(rule_search.get("bookList", ""))
            or BookSourceTool._has_unsupported_js(rule_content.get("content", ""))
        )

    @staticmethod
    def _source_tags(raw):
        tags = []
        if not isinstance(raw, dict):
            return tags
        if raw.get("bookSourceType") is not None:
            tags.append("text" if str(raw.get("bookSourceType") or "0") == "0" else "non-text")
        url = (raw.get("bookSourceUrl") or "").strip()
        if url.lower().startswith("https://"):
            tags.append("https")
        elif url:
            tags.append("http")
        rule_search = raw.get("ruleSearch") or {}
        rule_book = raw.get("ruleBookInfo") or {}
        rule_toc = raw.get("ruleToc") or {}
        rule_content = raw.get("ruleContent") or {}
        if raw.get("searchUrl") and rule_search.get("bookList"):
            tags.append("search")
        if rule_book:
            tags.append("info")
        if rule_toc.get("chapterList"):
            tags.append("toc")
        if rule_content.get("content"):
            tags.append("content")
        if raw.get("exploreUrl"):
            tags.append("explore")
        if raw.get("loginUrl"):
            tags.append("login-needed")
        if rule_content.get("webJs"):
            tags.append("webjs-unsupported")
        if rule_content.get("imageStyle"):
            tags.append("image-style")
        values = list(BookSourceTool._iter_rule_values(raw))
        if any(v.strip().startswith(("$", "@json:")) for v in values):
            tags.append("json")
        if any("@css:" in v or "class." in v or "tag." in v or "id." in v for v in values):
            tags.append("html")
        if any("@js:" in v or "<js>" in v for v in values):
            tags.append("js-runtime")
        return tags

    @staticmethod
    def _missing_required_features(raw):
        rule_search = raw.get("ruleSearch") or {}
        rule_book = raw.get("ruleBookInfo") or {}
        rule_toc = raw.get("ruleToc") or {}
        rule_content = raw.get("ruleContent") or {}
        checks = [
            ("bookSourceName", raw.get("bookSourceName")),
            ("bookSourceUrl", raw.get("bookSourceUrl")),
            ("searchUrl", raw.get("searchUrl")),
            ("ruleSearch.bookList", rule_search.get("bookList")),
            ("ruleSearch.name", rule_search.get("name")),
            ("ruleSearch.bookUrl", rule_search.get("bookUrl")),
            ("ruleToc.chapterList", rule_toc.get("chapterList")),
            ("ruleToc.chapterName", rule_toc.get("chapterName")),
            ("ruleToc.chapterUrl", rule_toc.get("chapterUrl")),
            ("ruleContent.content", rule_content.get("content")),
        ]
        return [name for name, value in checks if not value]

    @AsyncService.register_function
    def validate_source(self, raw: dict, timeout: int = 8) -> dict:
        """校验书源连通性和功能完整性。"""
        if not isinstance(raw, dict):
            return {"ok": False, "status": "invalid", "message": "书源格式无效", "tags": []}
        if not raw.get("bookSourceName") or not raw.get("bookSourceUrl"):
            return {"ok": False, "status": "invalid", "message": "缺少 bookSourceName 或 bookSourceUrl"}

        tags = self._source_tags(raw)

        # DNS + HTTP 连通性
        source_url = (raw.get("bookSourceUrl") or "").strip()
        if "://" not in source_url:
            source_url = "http://" + source_url
        parsed = urlparse(source_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {"ok": False, "status": "invalid", "message": "书源 URL 无效", "tags": tags}

        probe_url = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        network_tags = []
        try:
            socket.getaddrinfo(host, port)
            network_tags.append("dns-ok")
        except OSError as err:
            network_tags.append("dns-failed")
            return {
                "ok": False, "status": "dns_failed",
                "message": f"DNS 解析失败：{err}", "tags": sorted(set(tags + network_tags)),
            }

        try:
            resp = requests.get(probe_url, timeout=timeout, allow_redirects=True, stream=True,
                                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                       "Chrome/125.0.0.0 Safari/537.36"})
            resp.close()
            network_tags.append("connect-ok")
            network_tags.append("http-%s" % resp.status_code)
            if resp.status_code >= 500:
                return {
                    "ok": False, "status": "connect_failed",
                    "message": f"HTTP 状态 {resp.status_code}", "tags": sorted(set(tags + network_tags)),
                }
        except requests.exceptions.SSLError as err:
            network_tags.append("ssl-failed")
            return {
                "ok": False, "status": "ssl_failed",
                "message": f"SSL 校验失败：{err}", "tags": sorted(set(tags + network_tags)),
            }
        except Exception as err:
            network_tags.append("connect-failed")
            return {
                "ok": False, "status": "connect_failed",
                "message": f"连通性测试失败：{err}", "tags": sorted(set(tags + network_tags)),
            }

        tags = sorted(set(tags + network_tags))

        # JS 依赖检测
        if self._requires_js(raw):
            return {
                "ok": False, "status": "js_unsupported",
                "message": "关键规则依赖 JS，暂不支持", "tags": tags,
            }

        # 功能完整性检查（非阻塞，仅提示）
        missing = self._missing_required_features(raw)
        if missing:
            return {
                "ok": False, "status": "incomplete",
                "message": f"缺少关键规则：{', '.join(missing[:4])}", "tags": tags,
            }

        return {"ok": True, "status": "ok", "message": "检测通过", "tags": tags}

    @staticmethod
    def _check_engine_compatible(item: dict) -> tuple[bool, str]:
        """检查书源是否与当前引擎兼容（不依赖网络）。

        只检查关键规则字段 — searchUrl、bookList、chapterList、content、header。
        非关键字段（coverUrl、exploreUrl、init、jsLib 等）不阻塞导入。
        """
        critical_fields = {
            "searchUrl", "ruleSearch.bookList", "ruleSearch.name",
            "ruleSearch.author", "ruleSearch.bookUrl",
            "ruleToc.chapterList", "ruleToc.chapterName", "ruleToc.chapterUrl",
            "ruleContent.content",
        }
        for field, value in _iter_all_rule_strings(item):
            if field not in critical_fields:
                continue
            if BookSourceTool._has_unsupported_js(value):
                return False, f"{field} 含不支持的 JS 调用"

        header = item.get("header", "")
        if isinstance(header, str) and (header.startswith("@js:") or header.startswith("<js>")):
            return False, "header 为 JS 动态，不支持"

        return True, ""

    @AsyncService.register_function
    def import_sources_from_url(self, url: str) -> dict:
        """从远程 URL 批量导入书源（Legado 书源订阅）。跳过引擎不兼容的书源。"""
        if not self._is_safe_url(url):
            return {"status": "fetch_failed", "added": 0,
                    "message": "URL 无效或指向内网地址（已阻止）"}
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": _DEFAULT_UA})
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("import book source from url failed: %s", exc)
            return {"status": "fetch_failed", "added": 0, "message": f"拉取书源 URL 失败：{exc}"}

        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return {"status": "format_error", "added": 0, "message": "书源格式应为 JSON 数组或对象"}

        added = 0
        updated = 0
        skipped = 0
        errors = []
        for item in data:
            if not isinstance(item, dict):
                errors.append("invalid item")
                continue
            name = item.get("bookSourceName", "unknown")
            if not name or not item.get("bookSourceUrl"):
                errors.append(f"missing fields: {name}")
                continue

            ok, reason = self._check_engine_compatible(item)
            if not ok:
                skipped += 1
                errors.append(f"{name}: 跳过 — {reason}")
                continue

            result = self.add_source(item)
            if result["status"] == "added":
                added += 1
            else:
                updated += 1

        msg = f"导入: 新增 {added}, 更新 {updated}, 跳过 {skipped}"
        if errors:
            msg += f", 详情: {'; '.join(errors[:5])}"
        return {"status": "ok", "added": added, "updated": updated, "skipped": skipped, "errors": errors[:10]}

    @AsyncService.register_function
    def import_sources_from_zip(self, zip_path: str) -> dict:
        """从 ZIP 文件导入书源。跳过引擎不兼容的书源。"""
        import zipfile
        added = 0
        updated = 0
        skipped = 0
        errors = []

        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmpdir)

            for root, _dirs, files in os.walk(tmpdir):
                for fn in files:
                    if fn in ("importBookSource.json", "importBookSource.txt"):
                        fpath = os.path.join(root, fn)
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                data = json.load(f)
                        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                            errors.append(f"{fn}: 解析失败 — {exc}")
                            continue
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            name = item.get("bookSourceName", "unknown") if isinstance(item, dict) else "?"
                            if not isinstance(item, dict):
                                errors.append(f"{name}: invalid item")
                                continue

                            ok, reason = self._check_engine_compatible(item)
                            if not ok:
                                skipped += 1
                                errors.append(f"{name}: 跳过 — {reason}")
                                continue

                            result = self.add_source(item)
                            if result["status"] == "added":
                                added += 1
                            else:
                                updated += 1
                        break

        return {"status": "ok", "added": added, "updated": updated, "skipped": skipped, "errors": errors[:10]}

    # ── 搜索与测试 ──────────────────────────────────────────────

    @AsyncService.register_function
    def search(self, source_name: str, keyword: str) -> list[dict]:
        """在指定书源中搜索（同步）。"""
        source = self._find_source(source_name)
        if not source:
            raise ValueError(_("书源不存在: %s") % source_name)
        results = search_books(source, keyword)
        return [
            {
                "name": r.get("name", ""),
                "author": r.get("author", ""),
                "kind": r.get("kind", ""),
                "wordCount": r.get("wordCount", ""),
                "lastChapter": r.get("lastChapter", ""),
                "intro": r.get("intro", ""),
                "coverUrl": r.get("coverUrl", ""),
                "bookUrl": r.get("bookUrl", ""),
            }
            for r in results
        ]

    @AsyncService.register_function
    def search_async(self, keyword: str, source_names: Optional[list[str]] = None) -> dict:
        """异步多书源并发搜索，立即返回 task_id。

        source_names 为 None 时搜索所有已启用的书源。
        """
        all_sources = self._load_sources()
        targets = all_sources if source_names is None else [
            s for s in all_sources if s.bookSourceName in source_names
        ]
        targets = [s for s in targets if s.enabled]
        if not targets:
            return {"task_id": "", "total": 0, "error": _("没有可用的书源")}
        sources = [{"name": s.bookSourceName, "source": s} for s in targets]
        svc = SearchTaskService()
        return svc.create_task(keyword, sources)

    @AsyncService.register_function
    def get_search_status(self, task_id: str) -> dict | None:
        """查询异步搜索任务进度。"""
        return SearchTaskService().get_status(task_id)

    @AsyncService.register_function
    def search_all(self, keyword: str, timeout: int = 60) -> list[dict]:
        """同步搜索所有已启用的书源（等待全部完成）。"""
        import time as _time
        all_sources = self._load_sources()
        enabled = [s for s in all_sources if s.enabled]
        if not enabled:
            return []
        sources = [{"name": s.bookSourceName, "source": s} for s in enabled]
        svc = SearchTaskService()
        result = svc.create_task(keyword, sources)
        task_id = result["task_id"]
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            status = svc.get_status(task_id)
            if status and status["finished"]:
                break
            _time.sleep(0.5)
        status = svc.get_status(task_id) or {}
        if not status.get("finished"):
            logger.warning("search_all 超时（%ds），返回部分结果 %d 条", timeout, len(status.get("results", [])))
        books = []
        for r in status.get("results", []):
            for b in r.get("books", []):
                b["_source"] = r["source_name"]
                books.append(b)
        return books

    @AsyncService.register_function
    def test_source(self, source_name: str) -> dict:
        """测试书源连通性，返回搜索结果示例。"""
        source = self._find_source(source_name)
        if not source:
            raise ValueError(_("书源不存在: %s") % source_name)
        results = self.search(source_name, _("测试"))
        return {
            "source": source_name,
            "reachable": True,
            "sample_count": len(results),
            "samples": results[:3],
        }

    # ── Explore / 分类浏览 ─────────────────────────────────────

    @AsyncService.register_function
    def explore_categories(self, source_name: str) -> list[dict]:
        """解析书源的 exploreUrl 返回分类列表。"""
        source = self._find_source(source_name)
        if not source:
            raise ValueError(_("书源不存在: %s") % source_name)
        return parse_explore_categories(source.exploreUrl)

    @AsyncService.register_function
    def explore(self, source_name: str, url: str) -> list[dict]:
        """从分类 URL 获取书籍列表。"""
        source = self._find_source(source_name)
        if not source:
            raise ValueError(_("书源不存在: %s") % source_name)
        if not self._is_safe_url(url):
            raise ValueError(_("分类 URL 无效或指向内网地址（已阻止）"))
        return fetch_explore(source, url)

    # ── 下载 ────────────────────────────────────────────────────

    @AsyncService.register_service
    def download_book(
        self,
        source_name: str,
        book_url: str,
        book_title: str = "",
        max_chapters: int = 9999,
        user_id: int = 1,
        callback: Optional[Callable[[int], None]] = None,
    ):
        """异步下载书籍，生成 EPUB 并导入 Calibre。"""
        source = self._find_source(source_name)
        if not source:
            raise ValueError(_("书源不存在: %s") % source_name)

        task_id = self.create_task({"progress": 0, "status": _("初始化")})
        self.set_last_task(user_id, task_id)
        try:
            self._do_download(source, book_url, book_title, max_chapters, user_id, task_id)
        except Exception as exc:
            logger.error("下载失败: %s", exc, exc_info=True)
            self.complete_task(task_id, error_message=str(exc))

    @AsyncService.register_function
    def generate_epub(self, source_name: str, book_url: str,
                      book_title: str = "", max_chapters: int = 9999) -> str:
        """同步生成 EPUB 文件，不导入 Calibre。

        Returns:
            EPUB 文件路径
        """
        source = self._find_source(source_name)
        if not source:
            raise ValueError(_("书源不存在: %s") % source_name)

        detail = fetch_book_info(source, book_url)
        title = book_title or detail.get("name", _("未知书籍"))
        author = detail.get("author", _("未知作者"))
        cover_url = detail.get("coverUrl", "")

        toc = fetch_toc(source, book_url)
        # 卷头行（isVolume 为真）不是实际章节，跳过
        to_download = [e for e in toc if not e.get("isVolume")][:max_chapters]

        chapters = []
        for i, entry in enumerate(to_download, 1):
            ch_title = entry.get("chapterName", _("第 %d 章") % i)
            ch_url = entry.get("chapterUrl", "")
            content = fetch_content(source, ch_url)
            if content:
                chapters.append({"title": ch_title, "content": content, "url": ch_url})

        if not chapters:
            raise ValueError(_("未获取到有效章节内容"))

        # 生成 EPUB
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', title)
        output_path = os.path.join(self.get_work_dir(book_url), f"{safe_name}.epub")
        return _generate_epub(
            title=title, author=author, chapters=chapters,
            cover_url=cover_url, output_path=output_path,
            referer=source.bookSourceUrl,
        )

    @AsyncService.register_service
    def generate_epub_task(
        self,
        source_name: str,
        book_url: str,
        book_title: str = "",
        max_chapters: int = 9999,
        user_id: int = 1,
    ):
        """异步生成 EPUB（不入库、不清理文件），完成后路径写入任务进度。"""
        source = self._find_source(source_name)
        if not source:
            raise ValueError(_("书源不存在: %s") % source_name)

        task_id = self.create_task({"progress": 0, "status": _("初始化")})
        self.set_last_task(user_id, task_id)
        try:
            self._do_generate_epub(source, book_url, book_title, max_chapters, task_id)
        except Exception as exc:
            logger.error("生成 EPUB 失败: %s", exc, exc_info=True)
            self.complete_task(task_id, error_message=str(exc))

    def get_last_epub_path(self, user_id: int = 1) -> str:
        """返回用户最近一次生成任务的 EPUB 文件路径（未完成/失败返回空）。"""
        task = self.get_last_task(user_id)
        if not task or task.get("status") != BackgroundTask.STATUS_COMPLETED:
            return ""
        progress_data = task.get("progress_data") or {}
        path = progress_data.get("epub_path", "")
        if path and os.path.exists(path):
            return path
        return ""

    def _do_generate_epub(self, source, book_url: str, book_title: str,
                          max_chapters: int, task_id: int):
        """后台生成 EPUB（不导入 Calibre）。"""
        self.update_task_progress(task_id, 5, {"status": _("获取书籍信息")})
        detail = fetch_book_info(source, book_url)
        title = book_title or detail.get("name", _("未知书籍"))
        author = detail.get("author", _("未知作者"))
        cover_url = detail.get("coverUrl", "")

        self.update_task_progress(task_id, 15, {"status": _("获取目录")})
        toc = fetch_toc(source, book_url)
        to_download = [e for e in toc if not e.get("isVolume")][:max_chapters]

        chapters = []
        total = len(to_download)
        for i, entry in enumerate(to_download, 1):
            ch_title = entry.get("chapterName", _("第 %d 章") % i)
            ch_url = entry.get("chapterUrl", "")
            pct = 15 + int(70 * i / total)
            self.update_task_progress(
                task_id, pct,
                {"status": _("下载章节 [%d/%d]: %s") % (i, total, ch_title)},
            )
            content = fetch_content(source, ch_url)
            if content:
                chapters.append({"title": ch_title, "content": content, "url": ch_url})

        if not chapters:
            raise ValueError(_("未获取到有效章节内容"))

        self.update_task_progress(task_id, 90, {"status": _("生成 EPUB")})
        work_dir = self.get_work_dir(book_url)
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', title)
        epub_path = os.path.join(work_dir, f"{safe_name}.epub")
        _generate_epub(
            title=title, author=author, chapters=chapters,
            cover_url=cover_url, output_path=epub_path,
            referer=source.bookSourceUrl,
        )
        self.update_task_progress(task_id, 100, {"status": _("生成完成"), "epub_path": epub_path})
        self.complete_task(task_id)

    # ── 内部方法 ────────────────────────────────────────────────

    def _load_sources(self):
        """从默认位置加载书源列表。"""
        path = self._sources_path()
        if not os.path.exists(path):
            return []
        try:
            return load_sources_from_json(path)
        except Exception as exc:
            logger.error("加载书源失败: %s", exc)
            return []

    def _save_sources(self, sources):
        """原子保存书源列表到默认位置（tmp + os.replace）。"""
        path = self._sources_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        dump_sources_to_json(sources, tmp_path)
        os.replace(tmp_path, path)

    def _sources_path(self) -> str:
        return os.path.join(self.TOOL_DATA_ROOT, self.tool_id(), "sources.json")

    def _find_source(self, name: str):
        for s in self._load_sources():
            if s.bookSourceName == name:
                return s
        return None

    def _do_download(self, source, book_url: str, book_title: str,
                     max_chapters: int, user_id: int, task_id: int):
        """后台下载任务。"""
        self.update_task_progress(task_id, 5, {"status": _("获取书籍信息")})
        detail = fetch_book_info(source, book_url)
        title = book_title or detail.get("name", _("未知书籍"))
        author = detail.get("author", _("未知作者"))
        cover_url = detail.get("coverUrl", "")

        self.update_task_progress(task_id, 15, {"status": _("获取目录")})
        toc = fetch_toc(source, book_url)
        # 卷头行（isVolume 为真）不是实际章节，跳过
        to_download = [e for e in toc if not e.get("isVolume")][:max_chapters]

        chapters = []
        total = len(to_download)
        for i, entry in enumerate(to_download, 1):
            ch_title = entry.get("chapterName", _("第 %d 章") % i)
            ch_url = entry.get("chapterUrl", "")
            pct = 15 + int(70 * i / total)
            self.update_task_progress(
                task_id, pct,
                {"status": _("下载章节 [%d/%d]: %s") % (i, total, ch_title)},
            )
            content = fetch_content(source, ch_url)
            if content:
                chapters.append({"title": ch_title, "content": content, "url": ch_url})

        if not chapters:
            raise ValueError(_("未获取到有效章节内容"))

        self.update_task_progress(task_id, 90, {"status": _("生成 EPUB")})
        work_dir = self.get_work_dir(book_url)
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', title)
        epub_path = os.path.join(work_dir, f"{safe_name}.epub")
        _generate_epub(
            title=title, author=author, chapters=chapters,
            cover_url=cover_url, output_path=epub_path,
            referer=source.bookSourceUrl,
        )

        self.update_task_progress(task_id, 95, {"status": _("导入 Calibre")})
        try:
            self.import_file(user_id, epub_path, title, [author])
            self.complete_task(task_id)
        except Exception as exc:
            logger.error("Calibre 导入失败: %s", exc)
            self.complete_task(task_id, error_message=str(exc))

        self.cleanup_work_dir(work_dir)

    # ── 资源清理 ────────────────────────────────────────────────

    def cleanup(self):
        pass
