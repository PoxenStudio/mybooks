# -*- coding: utf-8 -*-
"""EPUB 合集工具入口（Toolbox 5 件套之一）。

与 `merge_formats_tool`（跨书复制格式文件）不同，本工具做内容级 N→1 合并：
多本 EPUB 的正文按指定顺序拼接为一本新书入库，原书默认保留。

流程骨架抄 `text_replace.py`（参数前置校验 + task_id=None 守卫 +
单任务锁 `acquired` 标记释放），多本加权进度抄 `epub_beautify.py` 的 `_pct`，
文件校验与入库抄 `utils/book_utils.py`（`get_book_file` 直接调用，
`import_as_new_book` 为 N 源改写于 `_import_merged_book`）。
"""
import logging
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


def _ordered_unique(values) -> list:
    """strip 去空保序去重（作者/标签/ISBN 并集用）。"""
    seen = set()
    out = []
    for v in values or []:
        s = (v or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _default_title(titles: list) -> str:
    """默认合集标题：源书名用 `，` 连接 + `合集`，超限硬截断（前后端双截）。"""
    title = "，".join([t for t in titles if t]) + "合集"
    return title[:_TITLE_MAX]


class EpubMergeTool(BaseTool):
    """多本 EPUB 内容合并为一本新书。"""

    service_item_name = "EPUB合并"

    _run_lock = threading.Lock()
    _last_task_id: Optional[int] = None

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
        """校验并归一化 ID 列表（2–20 本整数，无重复）。"""
        if not isinstance(book_ids, list) or not (2 <= len(book_ids) <= 20):
            raise RuntimeError(_("请选择 2–20 本书进行合并"))
        ids = []
        for bid in book_ids:
            try:
                ids.append(int(bid))
            except (TypeError, ValueError):
                raise RuntimeError(_("书籍 ID 非法：%r") % (bid,)) from None
        if len(set(ids)) != len(ids):
            raise RuntimeError(_("书籍重复选择，请去重后再试"))
        return ids

    # ---------------------------------------------------------------- 预览

    def _load_book_summary(self, book_id: int) -> dict:
        """单本摘要（封面/元数据/EPUB 解析），失败抛 RuntimeError（调用方隔离）。

        解析走 lite 模式（仅解压 container/OPF/NCX 小条目）且直接传路径：
        preview 在请求线程内同步执行，既不能全量解压、也不该把整本读进内存。
        """
        epub_path = book_utils.get_book_file(self, book_id, "EPUB")
        info = epub_merge_lib.analyze_epub(epub_path, lite=True)

        mi = self.get_book_metadata(book_id)
        title = utils.super_strip(mi.title or info["title"] or "")
        authors = _ordered_unique(list(mi.authors or []) or info["authors"])
        isbns = _ordered_unique(
            ([mi.isbn] if getattr(mi, "isbn", "") else []) + info["isbns"])
        cover = self.api.calibre.cover(book_id)

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
            "has_cover": bool(cover),
            "error": None,
            "warnings": info["warnings"],
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
        import io as _io
        try:
            img = Image.open(_io.BytesIO(data)).convert("RGB")
        except Exception as err:
            # 截断文件抛 OSError、超大像素抛 DecompressionBombError 等，统一转业务错误
            raise ValueError(_("封面图片无法解析：%s") % err) from err
        w, h = img.size
        if w > 1080:
            img = img.resize((1080, max(1, int(h * 1080 / w))), Image.LANCZOS)
            w, h = img.size
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        token = uuid.uuid4().hex[:16]
        out = os.path.join(self.get_work_dir(""), "cover_%s.jpg" % token)
        self._gc_cover_uploads()
        with open(out, "wb") as f:
            f.write(buf.getvalue())
        return {"token": token, "width": w, "height": h}

    def _resolve_cover(self, cover: dict, book_ids: list) -> tuple:
        """决议封面字节。返回 ((ext, data) | None, warning | None)。

        calibre 书库封面优先；缺失时降级读该书 EPUB 内嵌封面
        （`epub_merge_lib.extract_cover`）；仍无则 warn 继续。
        """
        if not cover:
            return None, None
        ctype = (cover.get("type") or "first").strip()
        bid = None
        try:
            if ctype == "first":
                bid = book_ids[0]
                raw = self.api.calibre.cover(bid)
                ext = "jpg"
            elif ctype.startswith("book:"):
                try:
                    bid = int(ctype.split(":", 1)[1])
                except (TypeError, ValueError):
                    raise ValueError(_("封面来源书籍 ID 非法：%s") % ctype) from None
                if bid not in book_ids:
                    raise ValueError(_("封面来源书籍不在合并列表中"))
                raw = self.api.calibre.cover(bid)
                ext = "jpg"
            elif ctype.startswith("upload:"):
                token = ctype.split(":", 1)[1]
                path = self._cover_token_path(token)
                with open(path, "rb") as f:
                    raw = f.read()
                ext = "jpg"  # 上传已统一重编码为 JPEG
                # 不在此处删除：合并失败时保留文件，用户可重试；成功入库后由
                # `_delete_cover_upload` 删除，放弃的残留由 `_gc_cover_uploads` 回收
            else:
                raise ValueError(_("封面类型未知：%s") % ctype)
        except ValueError:
            raise
        except Exception as err:
            logging.error("[EpubMergeTool] Resolve cover failed: %s", err)
            return None, _("封面读取失败，已使用无封面继续")
        if not raw and bid is not None:
            try:
                epub_path = book_utils.get_book_file(self, bid, "EPUB")
                # 传路径：只解压封面候选条目，不把整本读进内存
                raw, ext = epub_merge_lib.extract_cover(epub_path)
                if raw:
                    logging.info("[EpubMergeTool] Cover fallback to embedded: book_id=%d", bid)
            except Exception as err:
                logging.error("[EpubMergeTool] Embedded cover failed: %s", err)
                raw = None
        if not raw:
            return None, _("所选书籍无封面，已使用无封面继续")
        return ((ext or "jpg"), raw), None

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
            divider = bool(options.get("divider", True))
            delete_source = bool(options.get("delete_source", False))

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
            # out_path 模式：lib 直接把合并结果流式写入文件（不在内存里拼整包）
            epub_merge_lib.merge_epubs(
                inputs,
                {"title": title, "authors": authors, "languages": [language],
                 "tags": tags, "description": description, "publisher": publisher},
                {"divider": divider,
                 "out_path": out_path,
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
            if task_id is not None:
                if error_message is None:
                    self.update_task_progress(
                        task_id, 100,
                        {"status": "completed", "new_book_id": new_book_id})
                self.complete_task(task_id, error_message=error_message)
            if acquired:
                EpubMergeTool._run_lock.release()
