"""
EPUB 修复工具

两种修复手段，默认组成「精修 → 重转 → 写回」流水线：

1. **精修**（``repair``）：``utils/epub_fixer_lib.py`` 在 zip 层做外科手术式
   结构清理（删垃圾文件/断链条目/未登记文件/未用图片/JS、补登记、修 NCX 与
   EPUB3 nav、统一 UTF-8 等，详见该库 docstring），不碰排版与元数据语义；
2. **重转**（``fix``，历史行为保留）：epub→epub 强制转换重建规范结构，
   会重排版，作为流水线的兜底阶段（可关闭）。

写回两种模式：覆盖原 EPUB（``add_format``，calibre 缓存自动失效）或另存
为新书（``book_utils.import_as_new_book``）。

@author: PoxenStudio, 2026
"""
import logging
import os
import shutil
import threading
import traceback
from typing import Callable, Optional

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool
from webserver.toolbox.utils import book_utils, epub_fixer_lib as fixer_lib


class EpubFixerTool(BaseTool):
    """对指定书籍执行 EPUB 结构精修 / epub→epub 重转修复。"""

    service_item_name = "EPUB修复"

    _fix_lock = threading.Lock()
    _last_task_id: Optional[int] = None

    @classmethod
    def is_running(cls) -> bool:
        task = cls.get_last_task()
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls) -> Optional[dict]:
        if cls._last_task_id is None:
            return None
        return BackgroundService().get_task(cls._last_task_id)

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "epub_fixer",
            "name": "EPUB修复",
            "description": "对指定书籍做 EPUB 结构精修（删垃圾文件/断链条目/未用图片/JS，修目录断链，统一编码）与 epub→epub 重转修复，默认先精修再重转，可覆盖原文件或另存新书",
            "revision": "0.2.0",
            "author": "MyBooks",
            "publish_date": "2026-06-09",
        }

    # ------------------------------------------------------------------
    # 重转修复（历史行为，保留：单本 epub→epub 强制转换）
    # ------------------------------------------------------------------

    @AsyncService.register_service
    def fix(self, book_id: int, backup: bool, user_id: int) -> None:
        """执行 epub→epub 修复转换，通过 register_service 在后台线程中运行。

        :param book_id: Calibre 书籍 ID。
        :param backup:  是否在转换前备份原始 EPUB 文件。
        :param user_id: 操作用户 ID（记录日志用）。
        """
        if not EpubFixerTool._fix_lock.acquire(blocking=False):
            logging.warning("[EpubFixerTool] Already running, skipping fix for book_id=%d [uid:%d]", book_id, user_id)
            return

        try:
            task_id = self.create_task(progress_data={"status": "starting", "book_id": book_id})
        except Exception as setup_err:
            # 任务创建失败也必须释放锁，否则工具永久卡死到重启
            EpubFixerTool._fix_lock.release()
            logging.error("[EpubFixerTool] create_task failed: %s", setup_err)
            self.add_msg(user_id, "danger", _(u"EPUB 修复任务创建失败：%s") % setup_err)
            return

        EpubFixerTool._last_task_id = task_id
        progress_callback = self.make_progress_callback(task_id)
        error_message = None
        book_title = "Unknown"

        try:
            books = self.api.calibre.get_data_as_dict([book_id])
            if not books:
                error_message = _("书籍不存在：ID=%d") % book_id
                logging.error("[EpubFixerTool] Book not found: ID=%d [uid:%d]", book_id, user_id)
                return

            book = books[0]
            book_title = book.get("title", "Unknown")
            fmts = [f.upper() for f in (book.get("available_formats") or [])]
            if "EPUB" not in fmts:
                error_message = _("该书籍没有 EPUB 格式，无法执行修复")
                logging.error("[EpubFixerTool] No EPUB format for book_id=%d [uid:%d]", book_id, user_id)
                return

            epub_path = self.api.calibre.format_abspath(book_id, "EPUB")
            if not epub_path or not os.path.exists(epub_path):
                error_message = _("找不到 EPUB 文件，可能已被移除")
                logging.error("[EpubFixerTool] EPUB file missing for book_id=%d [uid:%d]", book_id, user_id)
                return

            self.update_task_progress(task_id, 10, {"status": "running", "stage": "backup"})
            progress_callback(10)

            work_dir = self.get_work_dir(str(book_id))

            if backup:
                backup_path = os.path.join(work_dir, os.path.basename(epub_path))
                shutil.copy2(epub_path, backup_path)
                logging.info("[EpubFixerTool] Backed up epub to %s [uid:%d]", backup_path, user_id)

            self.update_task_progress(task_id, 20, {"status": "running", "stage": "converting"})
            progress_callback(20)

            fixed_path = os.path.join(work_dir, "fixed.epub")
            log_path = os.path.join(work_dir, "convert.log")

            from webserver.services.converter import ConverterService
            converter = ConverterService()
            logging.info("[EpubFixerTool] Starting epub→epub fix for book_id=%d [uid:%d]", book_id, user_id)
            ok = converter.do_ebook_convert(epub_path, fixed_path, log_path)

            if not ok:
                error_message = _("EPUB 转换失败，请检查文件是否损坏（日志：%s）") % log_path
                logging.error("[EpubFixerTool] Conversion failed for book_id=%d, log: %s", book_id, log_path)
                return

            self.update_task_progress(task_id, 80, {"status": "running", "stage": "saving"})
            progress_callback(80)

            with open(fixed_path, "rb") as f:
                self.api.calibre.add_format(book_id, "EPUB", f)
            logging.info("[EpubFixerTool] Replaced EPUB for book_id=%d [uid:%d]", book_id, user_id)

            try:
                os.remove(fixed_path)
            except Exception as err:
                logging.warning("[EpubFixerTool] Failed to remove temp file %s: %s", fixed_path, err)

            self.add_msg(user_id, "success", _(u"书籍 [%s] EPUB 修复成功！") % book_title)

        except Exception as err:
            error_message = str(err)
            self.add_msg(user_id, "danger", _(u"书籍 [%s] EPUB 修复失败！") % book_title)
            logging.error("[EpubFixerTool] Unexpected error for book_id=%d: %s", book_id, err)
            logging.error(traceback.format_exc())
        finally:
            self.complete_task(task_id, error_message=error_message)
            if error_message is None:
                self.update_task_progress(task_id, 100, {"status": "completed", "book_id": book_id})
            EpubFixerTool._fix_lock.release()

    # ------------------------------------------------------------------
    # 精修：只读检测（后台任务。全量解压+逐文档解码较重，不能在请求线程
    # 里同步跑阻塞 ioloop；结果经 /progress 的 results 轮询取回）
    # ------------------------------------------------------------------

    @AsyncService.register_service
    def analyze_books(self, book_ids: list, user_id: int = 0) -> None:
        """逐本做结构问题检测，后台线程运行，结果写入任务 progress_data.results。

        单本失败只标 ``error`` 不中断整体（抄 epub_merge preview 的隔离策略）。
        results 元素：``{"book_id", "title", "drm", "findings", "error"}``。
        """
        if not EpubFixerTool._fix_lock.acquire(blocking=False):
            logging.warning("[EpubFixerTool] Already running, skipping analyze [uid:%d]", user_id)
            return

        try:
            task_id = self.create_task(progress_data={
                "status": "starting", "stage": "analyze",
                "book_total": len(book_ids), "results": []})
        except Exception as setup_err:
            EpubFixerTool._fix_lock.release()
            logging.error("[EpubFixerTool] create_task failed: %s", setup_err)
            return

        EpubFixerTool._last_task_id = task_id
        results = []
        error_message = None
        try:
            total = max(len(book_ids), 1)
            for idx, book_id in enumerate(book_ids):
                try:
                    books = self.api.calibre.get_data_as_dict([book_id])
                    if not books:
                        raise RuntimeError(_("书籍不存在：ID=%d") % book_id)
                    book = books[0]
                    title = book.get("title", "Unknown")
                    fmts = [f.upper() for f in (book.get("available_formats") or [])]
                    if "EPUB" not in fmts:
                        raise RuntimeError(_("该书籍没有 EPUB 格式"))
                    epub_path = self.api.calibre.format_abspath(book_id, "EPUB")
                    if not epub_path or not os.path.exists(epub_path):
                        raise RuntimeError(_("找不到 EPUB 文件，可能已被移除"))
                    info = fixer_lib.analyze_epub(epub_path)
                    results.append({
                        "book_id": book_id,
                        "title": title,
                        "drm": info["drm"],
                        "findings": info["findings"],
                        "error": "",
                    })
                except Exception as err:  # noqa: BLE001
                    logging.error("[EpubFixerTool] Analyze failed for book_id=%s: %s",
                                  book_id, err)
                    results.append({
                        "book_id": book_id,
                        "title": "",
                        "drm": False,
                        "findings": {},
                        "error": str(err),
                    })
                self.update_task_progress(task_id, int(100 * (idx + 1) / total), {
                    "status": "running", "stage": "analyze",
                    "book_index": idx + 1, "book_total": len(book_ids),
                    "results": results,
                })
        except Exception as err:  # noqa: BLE001
            error_message = str(err)
            logging.error("[EpubFixerTool] Unexpected analyze error: %s", err)
            logging.error(traceback.format_exc())
        finally:
            self.complete_task(task_id, error_message=error_message)
            if error_message is None:
                self.update_task_progress(task_id, 100, {
                    "status": "completed", "stage": "analyze", "results": results})
            EpubFixerTool._fix_lock.release()

    # ------------------------------------------------------------------
    # 精修 → 重转 → 写回（后台批量流水线）
    # ------------------------------------------------------------------

    @AsyncService.register_service
    def repair(self, book_ids: list, ops: Optional[list] = None,
               reconvert: bool = True, write_mode: str = "overwrite",
               backup: bool = False, suffix: str = u"（精修）",
               user_id: int = 0) -> None:
        """批量执行「精修 → 重转 → 写回」，后台线程运行。

        :param book_ids:  书籍 ID 列表。
        :param ops:       精修勾选项（None 用默认集，见 fixer_lib.DEFAULT_OPS）。
        :param reconvert: 精修后是否 epub→epub 重转兜底。
        :param write_mode: "overwrite"=覆盖原文件；"new_book"=另存为新书。
        :param backup:    覆盖模式下是否先备份原 EPUB 到工具工作目录。
        :param suffix:    另存新书时的标题后缀。
        :param user_id:   操作用户 ID。
        """
        if not EpubFixerTool._fix_lock.acquire(blocking=False):
            logging.warning("[EpubFixerTool] Already running, skipping repair [uid:%d]", user_id)
            return

        try:
            task_id = self.create_task(progress_data={
                "status": "starting", "book_total": len(book_ids), "results": []})
        except Exception as setup_err:
            # 任务创建失败也必须释放锁，否则工具永久卡死到重启
            EpubFixerTool._fix_lock.release()
            logging.error("[EpubFixerTool] create_task failed: %s", setup_err)
            self.add_msg(user_id, "danger", _(u"EPUB 修复任务创建失败：%s") % setup_err)
            return

        EpubFixerTool._last_task_id = task_id
        results = []
        error_message = None

        def _report(partial: list, stage: str, title: str, idx: int, pct: int):
            self.update_task_progress(task_id, pct, {
                "status": "running", "stage": stage, "current_title": title,
                "book_index": idx + 1, "book_total": len(book_ids),
                "results": partial,
            })

        try:
            total = max(len(book_ids), 1)
            for idx, book_id in enumerate(book_ids):
                title = "Unknown"
                try:
                    books = self.api.calibre.get_data_as_dict([book_id])
                    if not books:
                        raise RuntimeError(_("书籍不存在：ID=%d") % book_id)
                    title = books[0].get("title", "Unknown")

                    def _inner(inner_pct: int, stage: str):
                        # 精修库的 5-99 进度映射到本书在总进度中的区间
                        # （闭包在本书迭代内同步调用，title/idx 为当前值）
                        _report(results, stage, title, idx,
                                int(100 * (idx + inner_pct / 100.0) / total))

                    _report(results, "repair", title, idx, int(100 * idx / total))
                    result = self._repair_one(
                        book_id, books[0], title, ops=ops, reconvert=reconvert,
                        write_mode=write_mode, backup=backup, suffix=suffix,
                        user_id=user_id, progress_cb=_inner)
                    results.append(result)
                except Exception as err:  # noqa: BLE001
                    logging.error("[EpubFixerTool] Repair failed for book_id=%s: %s",
                                  book_id, err)
                    logging.error(traceback.format_exc())
                    results.append({
                        "book_id": book_id, "title": title, "ok": False,
                        "error": str(err), "ops": {}, "reconverted": False,
                        "new_book_id": 0, "warnings": [],
                    })
                _report(results, "repair", results[-1].get("title", ""),
                        idx, int(100 * (idx + 1) / total))

            ok_count = sum(1 for r in results if r.get("ok"))
            fail_count = len(results) - ok_count
            if fail_count == 0:
                self.add_msg(user_id, "success", _(u"EPUB 精修完成：%d 本全部成功") % ok_count)
            elif ok_count:
                self.add_msg(user_id, "danger", _(u"EPUB 精修完成：%d 本成功，%d 本失败，详情见任务详情") % (ok_count, fail_count))
            else:
                self.add_msg(user_id, "danger", _(u"EPUB 精修失败：%d 本全部未成功，详情见任务详情") % fail_count)
                error_message = _(u"%d 本全部未成功") % fail_count
        except Exception as err:
            error_message = str(err)
            logging.error("[EpubFixerTool] Unexpected repair error: %s", err)
            logging.error(traceback.format_exc())
        finally:
            self.complete_task(task_id, error_message=error_message)
            if error_message is None:
                self.update_task_progress(task_id, 100, {
                    "status": "completed", "results": results})
            EpubFixerTool._fix_lock.release()

    def _repair_one(self, book_id: int, book: dict, title: str, *, ops,
                    reconvert: bool, write_mode: str, backup: bool,
                    suffix: str, user_id: int,
                    progress_cb: Callable[[int, str], None]) -> dict:
        """单本「精修 → 重转 → 写回」；失败抛异常，由调用方隔离。"""
        fmts = [f.upper() for f in (book.get("available_formats") or [])]
        if "EPUB" not in fmts:
            raise RuntimeError(_("该书籍没有 EPUB 格式，无法执行修复"))
        epub_path = self.api.calibre.format_abspath(book_id, "EPUB")
        if not epub_path or not os.path.exists(epub_path):
            raise RuntimeError(_("找不到 EPUB 文件，可能已被移除"))

        work_dir = self.get_work_dir(str(book_id))
        if backup:
            backup_path = os.path.join(work_dir, os.path.basename(epub_path))
            shutil.copy2(epub_path, backup_path)
            logging.info("[EpubFixerTool] Backed up epub to %s [uid:%d]", backup_path, user_id)

        repaired_path = os.path.join(work_dir, "repaired.epub")
        if ops:
            report = fixer_lib.repair_epub(
                epub_path, repaired_path, ops=ops, progress_cb=progress_cb)
        else:
            report = {"ops": {k: 0 for k in fixer_lib.OP_KEYS}, "warnings": []}
        surgical_applied = any(report["ops"].values())
        final_path = repaired_path if surgical_applied else epub_path

        warnings = []
        reconverted = False
        if reconvert:
            converted_path = os.path.join(work_dir, "converted.epub")
            log_path = os.path.join(work_dir, "convert.log")
            from webserver.services.converter import ConverterService
            ok = ConverterService().do_ebook_convert(final_path, converted_path, log_path)
            if ok:
                final_path = converted_path
                reconverted = True
            elif surgical_applied:
                warnings.append(_("重转失败，已使用精修产物"))
            else:
                raise RuntimeError(_("EPUB 转换失败，请检查文件是否损坏（日志：%s）") % log_path)

        if not surgical_applied and not reconvert:
            # 无事可做：不写回（避免把原文件无意义地重新入库一遍）
            warnings.append(_("未勾选任何精修项且未启用重转，本书未做修改"))
            return {
                "book_id": book_id,
                "title": title,
                "ok": True,
                "ops": report["ops"],
                "reconverted": False,
                "new_book_id": 0,
                "warnings": warnings,
                "error": "",
            }

        new_book_id = 0
        if write_mode == "new_book":
            new_book_id = book_utils.import_as_new_book(
                self, book_id, final_path, suffix, user_id)
        else:
            with open(final_path, "rb") as f:
                self.api.calibre.add_format(book_id, "EPUB", f)
            logging.info("[EpubFixerTool] Replaced EPUB for book_id=%d [uid:%d]", book_id, user_id)

        for tmp in (repaired_path, os.path.join(work_dir, "converted.epub")):
            try:
                if os.path.exists(tmp) and tmp != epub_path:
                    os.remove(tmp)
            except OSError as err:
                logging.warning("[EpubFixerTool] Failed to remove temp %s: %s", tmp, err)

        return {
            "book_id": book_id,
            "title": title,
            "ok": True,
            "ops": report["ops"],
            "reconverted": reconverted,
            "new_book_id": new_book_id,
            "warnings": warnings,
            "error": "",
        }
