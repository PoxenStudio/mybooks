# -*- coding: utf-8 -*-
"""EPUB 合集工具入口（Toolbox 5 件套之一）。

与 `merge_formats_tool`（跨书复制格式文件）不同，本工具做内容级 N→1 合并：
多本 EPUB 的正文按指定顺序拼接为一本新书入库，原书默认保留。

流程骨架抄 `text_replace.py`（参数前置校验 + task_id=None 守卫 +
单任务锁 `acquired` 标记释放），多本加权进度抄 `epub_beautify.py` 的 `_pct`，
文件校验与入库抄 `utils/book_utils.py`（`get_book_file` 直接调用，
`import_as_new_book` 为 N 源改写于 `_import_merged_book`）。
"""
import io
import logging
import math
import os
import re
import threading
import time
import traceback
import uuid
from typing import Optional

from calibre.ebooks.metadata.book.base import Metadata

from webserver import utils
from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool

from webserver.toolbox.utils import book_utils
from webserver.toolbox import epub_merge_lib

_TITLE_MAX = 100
_DESCRIPTION_MAX = 50000
_PREVIEW_TEXT_MAX = 200000  # 简介预填上限（抄 text_replace PREVIEW_LIMIT 思路）
_COVER_MAX_BYTES = 3 * 1024 * 1024
_COVER_ALLOWED_EXT = (".jpg", ".jpeg", ".png", ".webp")
_COVER_TOKEN_RE = re.compile(r"^[a-f0-9]{16}$")
# 上传封面惰性回收：仅在 merge 成功读取时删除，用户上传后放弃的残留
# 靠这里兜底（工具根目录不随任务清理）
_COVER_GC_SECONDS = 24 * 3600

# analyze 告警码 → 本地化文案（lib 只回码，边界翻译；catalog 缺翻译时回退中文）
_WARN_MESSAGES = {
    epub_merge_lib.WARN_NO_NCX: "无 NCX 目录，合并时改用 EPUB3 导航 / spine 顺序兜底",
    epub_merge_lib.WARN_NO_SPINE: "未定位到正文条目",
    epub_merge_lib.WARN_ENCRYPTED_ASSETS: "含字体混淆资源，合并时将剔除",
}


def _ordered_unique(values) -> list:
    """strip 去空保序去重（实现下沉 lib，便于 standalone 单测）。"""
    return epub_merge_lib.ordered_unique(values)


def _default_title(titles: list) -> str:
    """默认合集标题（实现下沉 lib）。"""
    return epub_merge_lib.default_merge_title(titles, _TITLE_MAX)


class EpubMergeTool(BaseTool):
    """多本 EPUB 内容合并为一本新书。"""

    service_item_name = "EPUB合并"

    _run_lock = threading.Lock()
    _last_task_id: Optional[int] = None
    # 取消信号：handler 置位、合并线程每本开始前检查
    _cancel_event = threading.Event()
    # preview 的 EPUB 摘要缓存（仅分析结果，不缓存 calibre 元数据）：
    # 以 (路径, mtime_ns, size) 失效，避免每次选书变更重复解压小条目
    _analyze_cache = {}
    _analyze_cache_lock = threading.Lock()
    _ANALYZE_CACHE_MAX = 256

    @classmethod
    def request_cancel(cls) -> bool:
        """请求取消当前合并任务（无任务时返回 False）。"""
        if not cls.is_running():
            return False
        cls._cancel_event.set()
        return True

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "epub_merge",
            "name": "EPUB合并",
            "description": "将多本 EPUB 按指定顺序合并为一本新书（目录拼接、资源去重），原书默认保留",
            "revision": "0.1.0",
            "author": "You",
            "publish_date": "2026-09-04",
        }

    @classmethod
    def is_running(cls) -> bool:
        task = cls.get_last_task()
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls) -> Optional[dict]:
        if cls._last_task_id is None:
            return None
        return BackgroundService().get_task(cls._last_task_id)

    # ------------------------------------------------------------ 参数校验

    @staticmethod
    def _normalize_ids(book_ids) -> list:
        """校验并归一化 ID 列表（2–20 本整数，无重复；逻辑在 lib）。"""
        try:
            return epub_merge_lib.normalize_book_ids(book_ids)
        except ValueError as err:
            raise RuntimeError(_(str(err))) from None

    def _analyze_cached(self, epub_path: str) -> dict:
        """analyze_epub(lite) 带缓存（以文件 mtime/size 失效）。"""
        try:
            st = os.stat(epub_path)
            key = (epub_path, st.st_mtime_ns, st.st_size)
        except OSError:
            return epub_merge_lib.analyze_epub(epub_path, lite=True)
        with EpubMergeTool._analyze_cache_lock:
            hit = EpubMergeTool._analyze_cache.get(key)
        if hit is not None:
            return hit
        info = epub_merge_lib.analyze_epub(epub_path, lite=True)
        with EpubMergeTool._analyze_cache_lock:
            if len(EpubMergeTool._analyze_cache) >= EpubMergeTool._ANALYZE_CACHE_MAX:
                EpubMergeTool._analyze_cache.clear()
            EpubMergeTool._analyze_cache[key] = info
        return info

    # ---------------------------------------------------------------- 预览

    def _load_book_summary(self, book_id: int) -> dict:
        """单本摘要（封面/元数据/EPUB 解析），失败抛 RuntimeError（调用方隔离）。

        解析走 lite 模式（仅解压 container/OPF/NCX 小条目）且直接传路径：
        preview 在请求线程内同步执行，既不能全量解压、也不该把整本读进内存。
        """
        epub_path = book_utils.get_book_file(self, book_id, "EPUB")
        info = self._analyze_cached(epub_path)

        mi = self.get_book_metadata(book_id)
        title = utils.super_strip(mi.title or info["title"] or "")
        authors = _ordered_unique(list(mi.authors or []) or info["authors"])
        isbns = _ordered_unique(
            ([mi.isbn] if getattr(mi, "isbn", "") else []) + info["isbns"])

        return {
            "book_id": book_id,
            "title": title,
            "authors": authors,
            "isbns": isbns,
            "tags": _ordered_unique(list(mi.tags or [])),
            "publisher": utils.super_strip(mi.publisher or ""),
            "languages": list(mi.languages or []) or info["languages"],
            "comments": mi.comments or "",
            "spine_count": info["spine_count"],
            "toc_count": info["toc_count"],
            "size": info["size"],
            # 封面只判有无（mi.has_cover 由 calibre 元数据带出），不取整包字节：
            # preview 在请求线程同步跑，20 本整封面读入纯属浪费
            "has_cover": bool(getattr(mi, "has_cover", False)),
            "error": None,
            # 告警码在此翻译（lib 不依赖 i18n；未知码原样透出）
            "warnings": [_(_WARN_MESSAGES.get(w, w)) for w in info["warnings"]],
        }

    @AsyncService.register_function
    def preview(self, book_ids: list) -> dict:
        """同步返回每本摘要 + 合集默认值（标题/作者/ISBN/标签/简介），供前端确认排序。

        单本失败只标该项 `error`，不中断整体（抄 beautify 批量隔离）。
        """
        ids = self._normalize_ids(book_ids)
        books = []
        for bid in ids:
            try:
                books.append(self._load_book_summary(bid))
            except Exception as err:
                # 单本隔离：analyze_epub 抛 ValueError、db/封面读取抛各自异常，
                # 一本坏书不得拖垮整个 preview
                logging.error("[EpubMergeTool] Preview failed for book_id=%s: %s", bid, err)
                books.append({"book_id": bid, "error": str(err)})

        ok_books = [b for b in books if not b.get("error")]
        titles = [b["title"] for b in ok_books]
        default_title = _default_title(titles)
        authors_union = _ordered_unique([a for b in ok_books for a in b["authors"]])
        isbns_union = _ordered_unique([i for b in ok_books for i in b["isbns"]])
        tags_union = _ordered_unique([t for b in ok_books for t in b["tags"]])
        publisher_default = next((b["publisher"] for b in ok_books if b["publisher"]), "")
        language_default = next(
            (lang for b in ok_books for lang in b["languages"]), "zho")

        description = epub_merge_lib.compose_description(
            default_title,
            [{"title": b["title"], "comments": b["comments"]} for b in ok_books],
            isbns_union)
        truncated = False
        if len(description) > _PREVIEW_TEXT_MAX:
            description = description[:_PREVIEW_TEXT_MAX]
            truncated = True

        return {
            "books": books,
            "default_title": default_title,
            "authors_union": authors_union,
            "isbns_union": isbns_union,
            "tags_union": tags_union,
            "publisher_default": publisher_default,
            "language_default": language_default,
            "description_default": description,
            "truncated": truncated,
        }

    # ------------------------------------------------------------ 封面上传

    def _cover_token_path(self, token: str) -> str:
        """token 转文件路径（格式非法或不存在抛 ValueError，防穿越）。"""
        if not token or not _COVER_TOKEN_RE.match(token):
            raise ValueError(_("封面 token 非法"))
        path = os.path.join(self.get_work_dir(""), "cover_%s.jpg" % token)
        if not os.path.isfile(path):
            raise ValueError(_("封面已过期，请重新上传"))
        return path

    def _gc_cover_uploads(self) -> None:
        """清理超过 `_COVER_GC_SECONDS` 的历史上传封面（失败静默，不阻塞上传）。"""
        try:
            now = time.time()
            work_dir = self.get_work_dir("")
            for name in os.listdir(work_dir):
                if not (name.startswith("cover_") and name.endswith(".jpg")):
                    continue
                path = os.path.join(work_dir, name)
                try:
                    if now - os.path.getmtime(path) > _COVER_GC_SECONDS:
                        os.remove(path)
                except OSError:
                    continue
        except OSError as err:
            logging.warning("[EpubMergeTool] Cover GC failed: %s", err)

    @staticmethod
    def _encode_cover_jpeg(img) -> tuple:
        """PIL RGB 图 → (jpeg bytes, width, height)，宽>1080 等比缩小。"""
        from PIL import Image
        w, h = img.size
        if w > 1080:
            img = img.resize((1080, max(1, int(h * 1080 / w))), Image.LANCZOS)
            w, h = img.size
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        return buf.getvalue(), w, h

    def save_cover_upload(self, data: bytes, filename: str) -> dict:
        """保存自定义封面：PIL 统一重编码为 JPEG（宽>1080 等比缩小）。

        校验思路抄 `EpubBeautifyTool.save_bg_image`；token 一次性使用，
        merge 成功读取后删除，上传后放弃的残留由 `_gc_cover_uploads` 回收。
        :raises ValueError: 格式/大小不合法或图片无法解析。
        """
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in _COVER_ALLOWED_EXT:
            raise ValueError(_("封面仅支持 jpg / png / webp 格式"))
        if len(data) > _COVER_MAX_BYTES:
            raise ValueError(_("封面不能超过 3MB"))
        try:
            from PIL import Image
        except ImportError as err:
            raise RuntimeError(_("服务器缺少图像处理组件(PIL)，无法处理封面")) from err
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as err:
            # 截断文件抛 OSError、超大像素抛 DecompressionBombError 等，统一转业务错误
            raise ValueError(_("封面图片无法解析：%s") % err) from err
        jpeg, w, h = self._encode_cover_jpeg(img)
        token = uuid.uuid4().hex[:16]
        out = os.path.join(self.get_work_dir(""), "cover_%s.jpg" % token)
        self._gc_cover_uploads()
        with open(out, "wb") as f:
            f.write(jpeg)
        return {"token": token, "width": w, "height": h}

    def _normalize_cover(self, raw: bytes, ext: str) -> tuple:
        """库内/内嵌封面统一重编码为 JPEG；PIL 缺失或解析失败时原样返回。"""
        if not raw:
            return None, None
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            jpeg, _w, _h = self._encode_cover_jpeg(img)
            return "jpg", jpeg
        except Exception as err:
            logging.warning("[EpubMergeTool] Normalize cover skipped: %s", err)
            return (ext or "jpg").lower(), raw

    def _embedded_cover(self, bid: int) -> tuple:
        """读源书 EPUB 内嵌封面（传路径，只解压候选条目）。失败返回 (None, None)。"""
        try:
            epub_path = book_utils.get_book_file(self, bid, "EPUB")
            return epub_merge_lib.extract_cover(epub_path)
        except Exception as err:
            logging.error("[EpubMergeTool] Embedded cover failed: %s", err)
            return None, None

    def _first_available_cover(self, book_ids: list) -> tuple:
        """按合并顺序找第一本有封面的书（库封面 → 内嵌封面）。"""
        for bid in book_ids:
            try:
                raw = self.api.calibre.cover(bid)
            except Exception as err:
                logging.warning("[EpubMergeTool] Library cover failed: %s", err)
                raw = None
            if raw:
                return raw, "jpg"
            raw, ext = self._embedded_cover(bid)
            if raw:
                logging.info("[EpubMergeTool] Cover fallback to embedded: book_id=%d", bid)
                return raw, ext
        return None, None

    def _collect_book_covers(self, book_ids: list, limit: int = 9) -> list:
        """收集前 N 本源书封面原始字节（拼图封面用）。"""
        out = []
        for bid in book_ids[:limit]:
            try:
                raw = self.api.calibre.cover(bid)
            except Exception as err:
                logging.warning("[EpubMergeTool] Grid cover failed: %s", err)
                raw = None
            if not raw:
                raw, _ext = self._embedded_cover(bid)
            if raw:
                out.append(raw)
        return out

    def _make_cover_grid(self, images: list):
        """前 9 张封面按最多 3 列拼图 → ("jpg", bytes)；无图/PIL 缺失返回 None。"""
        try:
            from PIL import Image
        except ImportError:
            return None
        imgs = []
        for raw in (images or [])[:9]:
            try:
                imgs.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            except Exception:
                continue
        if not imgs:
            return None
        cell = 360
        cols = max(1, min(3, math.ceil(math.sqrt(len(imgs)))))
        rows = math.ceil(len(imgs) / cols)
        canvas = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
        for i, img in enumerate(imgs):
            img.thumbnail((cell, cell))
            x = (i % cols) * cell + (cell - img.width) // 2
            y = (i // cols) * cell + (cell - img.height) // 2
            canvas.paste(img, (x, y))
        data, _w, _h = self._encode_cover_jpeg(canvas)
        return "jpg", data

    def _resolve_cover(self, cover: dict, book_ids: list) -> tuple:
        """决议封面字节。返回 ((ext, data) | None, warning | None)。

        - first：按合并顺序取第一本有封面的书（库封面优先，内嵌兜底）；
        - book:<id>：指定源书，非法 ID / 不在列表给业务错误；
        - upload:<token>：上传图，token 失效降级为无封面（封面可选，不阻断合并）；
        - grid：前 9 本封面拼图，PIL 不可用/无图时降级 first。
        库内封面与内嵌封面统一重编码 JPEG（PIL 不可用时原样）。
        """
        if not cover:
            return None, None
        ctype = (cover.get("type") or "first").strip()
        try:
            if ctype == "first":
                raw, ext = self._first_available_cover(book_ids)
                if not raw:
                    return None, _("所选书籍无封面，已使用无封面继续")
            elif ctype.startswith("book:"):
                try:
                    bid = int(ctype.split(":", 1)[1])
                except (TypeError, ValueError):
                    raise ValueError(_("封面来源书籍 ID 非法：%s") % ctype) from None
                if bid not in book_ids:
                    raise ValueError(_("封面来源书籍不在合并列表中"))
                raw = self.api.calibre.cover(bid)
                ext = "jpg"
                if not raw:
                    raw, ext = self._embedded_cover(bid)
                if not raw:
                    return None, _("所选书籍无封面，已使用无封面继续")
            elif ctype.startswith("upload:"):
                token = ctype.split(":", 1)[1]
                try:
                    path = self._cover_token_path(token)
                    with open(path, "rb") as f:
                        raw = f.read()
                except ValueError as err:
                    # 封面可选：过期/非法 token 不应让已进行的合并失败
                    logging.warning("[EpubMergeTool] Cover upload unavailable: %s", err)
                    return None, _("封面已过期或无效，已使用无封面继续")
                # 上传时已统一重编码 JPEG，直接使用
                return ("jpg", raw), None
            elif ctype == "grid":
                grid = self._make_cover_grid(self._collect_book_covers(book_ids))
                if grid:
                    return grid, None
                raw, ext = self._first_available_cover(book_ids)
                if not raw:
                    return None, _("所选书籍无封面，已使用无封面继续")
            else:
                raise ValueError(_("封面类型未知：%s") % ctype)
        except ValueError:
            raise
        except Exception as err:
            logging.error("[EpubMergeTool] Resolve cover failed: %s", err)
            return None, _("封面读取失败，已使用无封面继续")
        return self._normalize_cover(raw, ext), None

    def _delete_cover_upload(self, cover: dict) -> None:
        """入库成功后删除本次使用的一次性上传封面（失败静默，残留由 GC 回收）。"""
        ctype = (cover or {}).get("type") or ""
        if not ctype.startswith("upload:"):
            return
        try:
            path = self._cover_token_path(ctype.split(":", 1)[1])
        except ValueError:
            return
        try:
            os.remove(path)
        except OSError as err:
            logging.warning("[EpubMergeTool] Remove cover upload failed: %s", err)

    # ---------------------------------------------------------------- 合并

    def _import_merged_book(self, out_path: str, title: str, authors: list,
                            tags: list, publisher: str, language: str,
                            description: str, isbns: list, cover_data,
                            user_id: int) -> int:
        """以新书身份入库（N 源版 import_as_new_book：全字段外部给定）。"""
        mi = Metadata(title, authors)
        mi.title_sort = utils.get_title_sort(mi.title)
        mi.tags = tags
        if publisher:
            mi.publisher = publisher
        mi.comments = description
        mi.languages = [language] if language else ["zho"]
        if isbns:
            mi.isbn = isbns[0]
            # 全量 ISBN 落入 identifiers（isbn/isbn13），不再只保留首个
            identifiers = dict(getattr(mi, "identifiers", None) or {})
            for value in isbns:
                cleaned = value.replace("-", "").replace(" ", "")
                if len(cleaned) == 13 and cleaned.isdigit():
                    identifiers.setdefault("isbn13", value)
                elif len(cleaned) == 10 and cleaned.isdigit():
                    identifiers.setdefault("isbn", value)
            if identifiers:
                mi.identifiers = identifiers
        if cover_data:
            ext = (cover_data[0] or "jpg").lower()
            mi.cover_data = ("jpeg" if ext in ("jpg", "jpeg") else ext, cover_data[1])
        new_book_id = self.api.calibre.import_book(mi, [out_path])
        if new_book_id is None:
            raise RuntimeError(_("导入合集失败：%s") % title)
        try:
            self.api.db.create_item(new_book_id, user_id)
        except Exception as err:
            logging.error(
                "[EpubMergeTool] Failed to create Item for book_id=%s: %s",
                new_book_id, err)
        return new_book_id

    @AsyncService.register_service
    def merge(self, book_ids: list, title: str, authors: list,
              options: Optional[dict], user_id: int) -> None:
        """后台合并并入库（单任务锁 + 加权进度 + 完成通知）。"""
        acquired = EpubMergeTool._run_lock.acquire(blocking=False)
        if not acquired:
            # 抄 beautify P3/P4：抢锁失败落一条失败任务给前端终止态（否则抢跑方
            # 要么永远轮询不到任务、要么轮询到别人正在跑的任务）；但仅在无在跑
            # 任务时才更新 _last_task_id，防覆盖在跑任务的轮询句柄
            logging.warning("[EpubMergeTool] Already running [uid:%d]", user_id)
            skip_task_id = self.create_task(progress_data={"status": "failed"})
            self.complete_task(
                skip_task_id,
                error_message=_("已有 EPUB 合并任务正在执行，请等待完成后再试"))
            # 仅在无在跑任务可轮询时才落 skip id，避免覆盖在跑任务的轮询句柄
            # （抄 EpubBeautifyTool P3 守卫；否则 A 的合并跑着时 B 触发一次抢锁，
            # A 前端会跳失败态而后台仍在跑）
            if not EpubMergeTool.is_running():
                EpubMergeTool._last_task_id = skip_task_id
            return
        EpubMergeTool._cancel_event.clear()

        task_id = None
        error_message = None
        work_dir = None
        new_book_id = None
        options = options or {}

        try:
            # 任务先建：参数校验失败也落一条失败任务，前端轮询拿到终止态，
            # 不会读到上一个任务的 completed 而误报「合并成功」
            task_id = self.create_task(progress_data={"status": "starting"})
            EpubMergeTool._last_task_id = task_id

            ids = self._normalize_ids(book_ids)
            title = utils.super_strip(title or "")[:_TITLE_MAX]
            if not title:
                raise RuntimeError(_("请填写合集标题"))
            authors = _ordered_unique(authors)
            description = (options.get("description") or "")[:_DESCRIPTION_MAX]
            isbns = _ordered_unique(options.get("isbns"))
            # ISBN 弱校验 warn 不阻断：疑似有误的照常入库，仅记日志并在成功
            # 消息里提醒（校验函数见 epub_merge_lib.is_valid_isbn）
            invalid_isbns = [i for i in isbns if not epub_merge_lib.is_valid_isbn(i)]
            if invalid_isbns:
                logging.warning(
                    "[EpubMergeTool] Suspicious ISBNs (kept, non-blocking): %s",
                    invalid_isbns)
            tags = _ordered_unique(options.get("tags"))
            publisher = utils.super_strip(options.get("publisher") or "")
            language = (options.get("language") or "").strip() or "zho"
            divider = epub_merge_lib.coerce_bool(options.get("divider"), True)
            delete_source = epub_merge_lib.coerce_bool(options.get("delete_source"), False)

            total = len(ids)
            seg = 70.0 / total
            inputs = []
            loaded_bytes = 0
            for idx, bid in enumerate(ids):
                base = idx * seg
                self.update_task_progress(
                    task_id, int(base + seg * 0.1),
                    {"status": "running", "stage": "loading",
                     "book_index": idx + 1, "book_total": total, "book_id": bid})
                epub_path = book_utils.get_book_file(self, bid, "EPUB")
                # 只传路径不读内容：lib 逐本按需读取，峰值内存与源书总大小解耦
                try:
                    loaded_bytes += os.path.getsize(epub_path)
                except OSError as err:
                    raise RuntimeError(
                        _("EPUB 源文件不可读：%s") % err) from err
                # 加载期逐本累计校验：比 lib 在合并前的总体检查更早失败
                if loaded_bytes > epub_merge_lib.MERGE_MAX_INPUT_TOTAL:
                    raise RuntimeError(
                        _("合集源文件总体积超过上限（2GB），请减少本数或分批合并"))
                mi = self.get_book_metadata(bid)
                book_title = utils.super_strip(mi.title or "")
                if not book_title:
                    raise RuntimeError(_("书籍不存在或标题为空：ID=%d") % bid)
                inputs.append({"path": epub_path, "title": book_title})
                self.update_task_progress(
                    task_id, int(base + seg * 0.9),
                    {"status": "running", "stage": "loading",
                     "book_index": idx + 1, "book_total": total, "book_id": bid})

            self.update_task_progress(task_id, 72, {"status": "running", "stage": "cover"})
            cover_data, cover_warning = self._resolve_cover(options.get("cover"), ids)

            self.update_task_progress(task_id, 75, {"status": "running", "stage": "merging"})
            work_dir = self.get_work_dir("-".join(str(i) for i in ids))
            out_path = os.path.join(work_dir, "merged_%d.epub" % int(time.time()))

            def _on_book(book_index, book_total):
                # 75→84 按本细分（此前 75→85 一跳，大书期间进度条长时间不动）；
                # 封顶 84：85 留给 validating，若这里封到 89，最后一本处理完后
                # validating 又设 85，进度条会肉眼可见地倒退
                pct = 75 + int(15.0 * (book_index - 1) / max(1, book_total))
                self.update_task_progress(
                    task_id, min(pct, 84),
                    {"status": "running", "stage": "merging",
                     "book_index": book_index, "book_total": book_total})

            # out_path 模式：lib 直接把合并结果流式写入文件（不在内存里拼整包）
            epub_merge_lib.merge_epubs(
                inputs,
                {"title": title, "authors": authors, "languages": [language],
                 "tags": tags, "description": description, "publisher": publisher},
                {"divider": divider,
                 "out_path": out_path,
                 "progress_cb": _on_book,
                 "cancel_event": EpubMergeTool._cancel_event,
                 "cover": ({"data": cover_data[1], "ext": cover_data[0]}
                           if cover_data else None)})
            self.update_task_progress(task_id, 85, {"status": "running", "stage": "validating"})
            epub_merge_lib.validate_output(out_path)

            self.update_task_progress(task_id, 90, {"status": "running", "stage": "saving"})
            new_book_id = self._import_merged_book(
                out_path, title, authors, tags, publisher, language,
                description, isbns, cover_data, user_id)
            self._delete_cover_upload(options.get("cover"))
            logging.info(
                "[EpubMergeTool] Merged %d books -> new book_id=%d [%s] [uid:%d]",
                total, new_book_id, title, user_id)
            self.cleanup_work_dir(work_dir)
            work_dir = None

            extra = ""
            if invalid_isbns:
                extra += _("（以下 ISBN 疑似有误，仅提醒未阻断：%s）") % "、".join(invalid_isbns)
            if cover_warning:
                extra += "（%s）" % cover_warning
            if delete_source:
                failed = []
                for sid in ids:
                    try:
                        self.api.calibre.delete_book(sid)
                    except Exception as err:
                        failed.append(sid)
                        logging.error(
                            "[EpubMergeTool] Delete source failed book_id=%d: %s", sid, err)
                if failed:
                    extra += _("（源书删除失败：%s）") % "、".join(str(i) for i in failed)

            self.add_msg(user_id, "success", _("合集 [%s] 生成成功！%s") % (title, extra))

        except epub_merge_lib.MergeCancelled:
            error_message = _("任务已取消")
            logging.info("[EpubMergeTool] Cancelled by user [uid:%d]", user_id)
            try:
                self.add_msg(user_id, "info", _("合集任务已取消"))
            except Exception:
                pass
        except Exception as err:
            error_message = str(err)
            logging.error("[EpubMergeTool] Unexpected error [uid:%d]: %s", user_id, err)
            logging.error(traceback.format_exc())
            try:
                self.add_msg(user_id, "danger", _("合集生成失败：%s") % error_message)
            except Exception:
                pass
        finally:
            if work_dir is not None:
                self.cleanup_work_dir(work_dir)
            EpubMergeTool._cancel_event.clear()
            if task_id is not None:
                if error_message is None:
                    self.update_task_progress(
                        task_id, 100,
                        {"status": "completed", "new_book_id": new_book_id})
                self.complete_task(task_id, error_message=error_message)
            if acquired:
                EpubMergeTool._run_lock.release()
