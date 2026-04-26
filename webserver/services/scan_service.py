#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
#
# do_import 是扫描导入的主入口，负责协调整个两阶段流水线导入流程：
# 前置阶段：收集文件列表，创建后台任务记录，初始化状态。
#
# 阶段一（Scanning）：主线程执行
#   - 遍历指定路径（目录或文件列表），收集合法格式的文件路径。
#   - 对每个文件计算部分 SHA-256 哈希（小于 10MB 取前 4MB；大于等于 10MB 取首尾各 3MB）。
#   - 根据路径和哈希进行去重：
#       * 已通过路径或哈希成功导入（状态 IMPORTED）且书库记录仍存在 → 跳过。
#       * 存在 NEW/READY 状态的记录时复用缓存哈希，避免重复 I/O。
#       * 否则清除同哈希的旧非导入记录，创建新 READY 状态的 ScanFile 行。
#   - 将 READY 行的 ID 放入有界工作队列（最大 50），自然地对阶段二施加背压。
#
# 阶段二（Importing）：独立后台线程执行
#   - 从工作队列中持续取出行 ID，加载对应 ScanFile 记录。
#   - 读取书籍元数据（calibre get_metadata），并根据标题去重：
#       * 标题已存在（电子书）→ 追加格式（add_format）。
#       * 标题不存在 → 全新导入（import_book），同时创建 Item 关联记录。
#   - 若配置 IMPORT_CATEGORY_WITH_FOLDER=True，将文件所在上传目录的第一级子目录名
#     作为书籍分类写入自定义字段。
#   - 若配置 REMOVE_IMPORTED_FILE=True，导入后删除源文件（仅适用于全新导入或已存在的情况）。
#   - 每 20 个文件批量提交一次事务，完成后执行最终提交并清理 scoped_session。
#

import errno
import hashlib
import os
import logging
import queue as _queue
import threading
import time
import traceback

from webserver.i18n import _
from sqlalchemy.exc import IntegrityError

from webserver import utils
from webserver.models import Item, ScanFile
from webserver.services import AsyncService
from webserver.services.autofill import AutoFillService
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_COLUMN_CATEGORY, CALIBRE_ERROR_FLAG
from webserver.constants import BOOK_TYPE_EBOOK, BOOK_TYPE_PHYSICAL
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver import loader

CONF = loader.get_settings()
MEGA_BYTES = 1024 * 1024
SCAN_EXT = ["azw", "azw3", "epub", "mobi", "pdf", "txt"]


class ScanService(AsyncService):
    static_is_importing = False
    static_import_id = 0
    static_import_files_cnt = 0
    invalid_folder: set[str] = set()

    @staticmethod
    def is_importing():
        return ScanService.static_is_importing

    @staticmethod
    def total_files_in_task():
        return ScanService.static_import_files_cnt

    @staticmethod
    def importing_id():
        return ScanService.static_import_id

    @staticmethod
    def get_invalid_folders():
        if ScanService.invalid_folder:
            logging.info(f"Invalid folders#0: {ScanService.invalid_folder}")
        return list(ScanService.invalid_folder)

    @staticmethod
    def os_walk_error_handler(e):
        if e.errno == errno.EACCES:
            logging.error(f"[IMPORT]权限不足，跳过目录: {e.filename}")
            ScanService.invalid_folder.add(e.filename)
        elif e.errno == errno.ENOENT:
            logging.error(f"[IMPORT]目录消失: {e.filename}")
        else:
            ScanService.invalid_folder.add(e.filename)
            logging.error(f"[IMPORT]访问目录时发生错误: {e.filename}, 错误码: {e.errno}")

    @staticmethod
    def _remove_imported_file(fpath):
        try:
            os.remove(fpath)
            logging.info(f"Removed imported file: {fpath}")
        except Exception as e:
            logging.error(f"Failed to remove imported file {fpath}: {e}")

    def save_or_rollback(self, row, session=None):
        session = session or self.session
        bid = "[ book-id=%s ]" % row.book_id if row.book_id else ""
        logging.info("update: status=%-5s, path=%s %s", row.status, row.path, bid)
        try:
            row.save()
            session.commit()
            return True
        except IntegrityError as err:
            logging.error("IntegrityError: Duplicate hash detected: %s, %s", row.hash, err)
        except Exception as err:
            logging.exception("save error: %s", err)
        session.rollback()
        return False

    def _collect_files(self, paths):
        if paths is None or paths == "all":
            dirs = [CONF.get("scan_upload_path", "")]
            if not dirs[0] or not os.path.isdir(dirs[0]):
                logging.warning("[IMPORT] scan_upload_path is not configured")
                return []
        elif isinstance(paths, str):
            dirs = [paths]
        else:
            dirs = list(paths)

        filelist = []
        for p in dirs:
            if os.path.isfile(p):
                fmt = p.split(".")[-1].lower()
                if fmt in SCAN_EXT:
                    filelist.append(p)
            elif os.path.isdir(p):
                for dirpath, __, filenames in os.walk(p, onerror=ScanService.os_walk_error_handler):
                    for fname in filenames:
                        fmt = fname.split(".")[-1].lower()
                        if not fmt or fmt not in SCAN_EXT or fname.startswith('.'):
                            continue
                        fpath = os.path.join(dirpath, fname)
                        if os.path.isfile(fpath):
                            filelist.append(fpath)
            else:
                logging.warning("[SCAN] Path not found: %s", p)
        return filelist

    @AsyncService.register_service
    def do_import(self, paths, user_id):
        if ScanService.static_is_importing:
            logging.error("Importing is running, please wait...")
            return

        ScanService.invalid_folder.clear()
        ScanService.static_is_importing = True
        start_time = time.time()

        filelist = self._collect_files(paths)
        logging.info("[IMPORT] Collected %d files in %.3f seconds", len(filelist), time.time() - start_time)
        if not filelist:
            logging.warning("[IMPORT] No valid files found in: %s", paths)
            ScanService.static_is_importing = False
            return

        task_id = None
        try:
            service_item = _("导入图书")
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_SCAN,
                service_item=service_item,
                progress=0,
                progress_data={"stage": "importing", "total": len(filelist), "imported": 0}
            )
            task_id = task.id
        except Exception as e:
            logging.error(f"Failed to create background task: {e}")

        ScanService.static_import_files_cnt = len(filelist)
        try:
            self.do_import_internal(filelist, user_id, task_id)
            if task_id:
                BackgroundService().complete_task(task_id=task_id)
            logging.info("[IMPORT] Completed")
        except Exception as err:
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
            logging.error(f"[IMPORT] Failed: {err}")
            logging.error(traceback.format_exc())
        ScanService.static_is_importing = False

    def _compute_hash(self, fpath):
        start = time.time()
        sha256 = hashlib.sha256()
        try:
            file_size = os.path.getsize(fpath)
            with open(fpath, "rb") as f:
                if file_size < 10 * MEGA_BYTES:
                    sha256.update(f.read(4 * MEGA_BYTES))
                else:
                    sha256.update(f.read(3 * MEGA_BYTES))
                    f.seek(-3 * MEGA_BYTES, 2)
                    sha256.update(f.read(3 * MEGA_BYTES))
            logging.info("[HASH] Computed hash for %s, size:%d in %.3f seconds", fpath, file_size, time.time() - start)
            return "sha256:" + sha256.hexdigest(), None
        except FileNotFoundError:
            logging.error("[IMPORT] File not found: %s", fpath)
            return None, ScanFile.MISSED
        except PermissionError:
            logging.error("[IMPORT] Permission denied: %s", fpath)
            return None, ScanFile.PERMISSION
        except Exception as e:
            logging.error("[IMPORT] Error reading file %s: %s", fpath, e)
            return None, ScanFile.INVALID

    def _import_one_file(self, row, user_id, scan_upload_path, session):
        """
            Read metadata and import one READY ScanFile into calibre.

            Handles all error paths internally (sets row.status, calls save_or_rollback).
            Returns book_id if a new book was successfully linked via Item, else None.
        """
        from calibre.ebooks.metadata.meta import get_metadata
        from calibre.ebooks.metadata.book.base import Metadata

        fpath = row.path
        fname = os.path.basename(fpath)
        fmt = fpath.split(".")[-1].lower()
        start_time = time.time()

        # Skip metadata reading when title/author are derived from filename
        skip_metadata = (fmt == "txt") or (fmt == "pdf" and CONF.get("PDF_TILE_WITH_FILE_NAME", False))
        if skip_metadata:
            title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
            author = None
            if fmt == "txt":
                title, author = utils._guess_title_author_from_filename(title)
            mi = Metadata(title, [author] if author else [_("佚名")])
            logging.info("[IMPORT] Skipped metadata read for %s: %s", fmt, repr(title))
        else:
            try:
                with open(fpath, "rb") as stream:
                    mi = get_metadata(stream, stream_type=fmt, use_libprs_metadata=True)
                    mi.title = utils.super_strip(mi.title)
                    mi.authors = [utils.super_strip(s) for s in mi.authors]
                logging.info("[IMPORT] Metadata read [%.3fs]: %s", time.time() - start_time, repr(mi.title))
            except Exception as e:
                logging.error("[IMPORT] Error reading metadata from %s: %s", fpath, e)
                row.status = ScanFile.INVALID
                self.save_or_rollback(row, session)
                return None

            if mi.title and mi.title == CALIBRE_ERROR_FLAG:
                logging.error("[IMPORT] Failed to get metadata for %s", fpath)
                row.status = ScanFile.INVALID
                row.title = None
                self.save_or_rollback(row, session)
                return None

            # Normalize title/author for pdf (PDF_TILE_WITH_FILE_NAME=False)
            if fmt == "pdf":
                title_ = mi.title.strip() if mi.title else ""
                if not title_ or title_.find("下载工具") >= 0 or title_ == "SSReader Print.":
                    mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                else:
                    mi.title = title_
                if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                    mi.authors = [_("佚名")]

        row.title = mi.title
        row.author = mi.authors[0] if mi.authors else mi.author_sort
        row.publisher = mi.publisher
        row.tags = ", ".join(mi.tags)

        new_book_id = None
        try:
            ids = self.db.books_with_same_title(mi)
            existed_ebook = False
            logging.info("[IMPORT] Same title %d book(s) for: %s", len(ids) if ids else 0, fpath)
            if ids:
                row.book_id = 0
                for bid in ids:
                    b = self.db.get_metadata(bid, index_is_id=True)
                    if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                        continue
                    existed_ebook = True
                    row.book_id = bid
                    if b.formats and fmt.upper() in b.formats:
                        row.status = ScanFile.EXIST
                        break
                if existed_ebook and row.status != ScanFile.EXIST:
                    logging.info("[IMPORT] Adding format %s to existing book %d", fmt, row.book_id)
                    self.db.add_format(row.book_id, fmt.upper(), fpath, True)
                    row.status = ScanFile.IMPORTED
                    logging.info("[IMPORT] Added format to existing book, book_id=%d [%.3fs]", row.book_id, time.time() - start_time)

            if not existed_ebook:
                logging.info("[IMPORT] Importing new book [%s] from %s", repr(mi.title), fpath)
                mi.title_sort = utils.get_title_sort(mi.title)
                row.book_id = self.db.import_book(mi, [fpath], notify=False, import_hooks=False)
                row.status = ScanFile.IMPORTED
                logging.info("[IMPORT] Calibre import done, book_id=%d [%.3fs]", row.book_id, time.time() - start_time)

                item = Item()
                item.book_id = row.book_id
                item.collector_id = user_id
                item.src_path = fpath
                try:
                    item.save()
                    new_book_id = row.book_id
                except Exception as err:
                    logging.error("[IMPORT] save link error: %s", err)

                if CONF.get("IMPORT_CATEGORY_WITH_FOLDER", False):
                    rel = os.path.relpath(os.path.realpath(fpath), scan_upload_path)
                    first_dir = rel.split(os.sep)[0] if os.sep in rel else ""
                    if first_dir and len(first_dir) < 10 and not any(c in first_dir for c in ',:;|/\\\'"\t '):
                        try:
                            self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {row.book_id: first_dir})
                            logging.info("[IMPORT] Set category '%s' for book_id=%d", first_dir, row.book_id)
                        except Exception as cat_err:
                            logging.warning("[IMPORT] Failed to set category for book_id=%d: %s", row.book_id, cat_err)
                    else:
                        logging.warning("[IMPORT] Skipping category for '%s': invalid dir name", first_dir)

            if CONF.get("REMOVE_IMPORTED_FILE", False) and (not existed_ebook or row.status == ScanFile.EXIST):
                self._remove_imported_file(fpath)
        except Exception as err:
            new_book_id = None
            row.status = ScanFile.INVALID
            logging.error("[IMPORT] Failed to process file %s: %s", fpath, err)
            logging.error(traceback.format_exc())

        if not new_book_id:
            return None

        try:
            self.save_or_rollback(row, session)
        except Exception as err:
            logging.error("[IMPORT] Failed to save ScanFile record for %s: %s", fpath, err)

        logging.info("[IMPORT] File done, status=%s [total %.3fs]: %s", row.status, time.time() - start_time, fpath)
        if time.time() - start_time > 0.25:
            logging.warning("[IMPORT] Slow import detected (%.3fs) for file: %s", time.time() - start_time, fpath)
        return new_book_id

    def _importing_worker(self, work_queue, importing_imported, task_id, total_count, user_id, scan_upload_path, batch_size):
        """Worker thread for Phase 2: consumes row IDs from work_queue and imports each file."""
        importing_session = self.scoped_session()
        importing_index = 0
        try:
            while True:
                row_id = work_queue.get()
                try:
                    if row_id is None:  # sentinel: Phase 1 finished
                        break

                    row = importing_session.query(ScanFile).get(row_id)
                    if row is None:
                        logging.warning("[IMPORT] ScanFile id=%d not found, skipping", row_id)
                        continue

                    importing_index += 1
                    logging.info("[IMPORT] Processing [%d]: %s", importing_index, row.path)

                    if task_id and total_count > 0:
                        try:
                            BackgroundService().update_progress(
                                task_id=task_id,
                                progress=min(99, 30 + int(importing_index * 70 / total_count)),
                                progress_data={"stage": "importing", "total": total_count, "imported": len(importing_imported)}
                            )
                        except Exception as e:
                            logging.error("[IMPORT] Failed to update progress: %s", e)

                    new_book_id = self._import_one_file(row, user_id, scan_upload_path, importing_session)
                    if new_book_id is not None:
                        importing_imported.append(new_book_id)

                    if importing_index % batch_size == 0:
                        try:
                            importing_session.commit()
                            logging.info("[IMPORT] Batch committed at index %d", importing_index)
                        except Exception as err:
                            logging.error("[IMPORT] Batch commit error: %s", err)
                            importing_session.rollback()
                finally:
                    work_queue.task_done()
        except Exception as err:
            logging.error("[IMPORT] Fatal error in worker: %s", err)
            logging.error(traceback.format_exc())
        finally:
            try:
                importing_session.commit()
                logging.info("[IMPORT] Final commit completed")
            except Exception as err:
                logging.error("[IMPORT] Final commit error: %s", err)
                importing_session.rollback()
            try:
                self.scoped_session.remove()
            except Exception:
                pass

    def _scan_one_file(self, fpath, session, import_id, processed_paths, processed_hashes):
        """
            Phase scanning: 处理单个文件：计算哈希，去重，创建/更新 READY 状态的 ScanFile 记录。
        """
        if not os.path.isfile(fpath) or not os.access(fpath, os.R_OK):
            logging.warning("[SCAN] Not a valid file, skip: %s", fpath)
            return None

        fmt = fpath.split(".")[-1].lower()
        if not fmt or fmt not in SCAN_EXT:
            logging.info("[SCAN] Unsupported format [%s], skip: %s", fmt, fpath)
            return None

        real_fpath = os.path.realpath(fpath)
        if real_fpath in processed_paths:
            logging.info("[SCAN] Already processed in this run, skip: %s", fpath)
            return None

        same_path_rows = session.query(ScanFile).filter(ScanFile.path == fpath).all()
        for r in same_path_rows:
            if r.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[r.book_id]):
                logging.info("[SCAN] Already imported by path: %s", fpath)
                return None
            elif r.status == ScanFile.EXIST:
                logging.info("[SCAN] Found duplicated record with same path %s", fpath)
                return None

        # Reuse cached hash if available (NEW/READY record from a previous interrupted run).
        # MISSED/PERMISSION: file was previously inaccessible, reprocess from scratch (no reuse).
        reuse_hash = next(
            (r.hash for r in same_path_rows
             if r.status in (ScanFile.NEW, ScanFile.READY) and r.hash and r.hash.startswith("sha256:")),
            None,
        )
        if reuse_hash:
            logging.info("[SCAN] Reusing cached hash for: %s", fpath)

        if same_path_rows:
            # Delete all same path records to avoid confusion
            logging.warning("[SCAN] Found multiple records with same path %s, count: %d. Cleaning up...", fpath, len(same_path_rows))
            session.query(ScanFile).filter(ScanFile.path == fpath).delete(synchronize_session=False)
            session.flush()
            same_path_rows = []

        hash_val, bad_reason = (reuse_hash, None) if reuse_hash else self._compute_hash(fpath)
        if bad_reason:
            row = ScanFile(fpath, "", import_id)
            row.status = bad_reason
            self.save_or_rollback(row, session)
            return None

        row = ScanFile(fpath, hash_val, import_id)

        if hash_val in processed_hashes:
            # Keep back compatibility to set unique hash.
            row.hash = hashlib.md5(fpath.encode("utf-8")).hexdigest()
            row.status = ScanFile.EXIST
            self.save_or_rollback(row, session)
            return None

        processed_hashes.add(hash_val)
        processed_paths.add(real_fpath)

        # Check already imported by hash
        hash_rows = session.query(ScanFile).filter(ScanFile.hash == hash_val).all()
        for hash_row in hash_rows:
            if hash_row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[hash_row.book_id]):
                logging.info("[SCAN] Already imported by hash: %s", fpath)
                row.hash = hashlib.md5(fpath.encode("utf-8")).hexdigest()
                row.status = ScanFile.EXIST
                self.save_or_rollback(row, session)
                return None

        if hash_rows:
            logging.info("[SCAN] Clear existing rows with same hash: %s, count: %d", hash_val, len(hash_rows))
            session.query(ScanFile).filter(
                ScanFile.hash == hash_val and ScanFile.status != ScanFile.IMPORTED
            ).delete(synchronize_session=False)
            session.flush()
        row.status = ScanFile.READY
        if self.save_or_rollback(row, session):
            return row.id
        return None

    def do_import_internal(self, filelist, user_id, task_id=None):
        """
            并行执行:
            Phase Scanning: 负责遍历文件、计算哈希、去重，并将 READY 状态的 ScanFile 行 ID 放入队列；
            Phase Importing: 从队列中取出 ID，读取对应 ScanFile 行，执行元数据读取和导入操作。
        """
        import_id = int(time.time())
        ScanService.static_import_id = import_id
        scan_upload_path = os.path.realpath(CONF.get("scan_upload_path", ""))
        total_count = len(filelist)
        batch_size = 20

        # maxsize limits memory if Phase 2 is slower than Phase 1.
        work_queue = _queue.Queue(maxsize=50)
        importing_imported = []

        start_time = time.time()
        logging.info("[IMPORT] Start (Phase 1 + Phase 2 pipelined) for %d files", total_count)

        importing_thread = threading.Thread(
            target=self._importing_worker,
            args=(work_queue, importing_imported, task_id, total_count, user_id, scan_upload_path, batch_size),
            name="ScanService.importing",
            daemon=True,
        )
        importing_thread.start()

        # ─── Phase 1: compute sha256, dedup, create READY ScanFile records ────────
        session = self.session
        processed_paths: set[str] = set()
        processed_hashes: set[str] = set()
        queued_count = 0
        try:
            for index, fpath in enumerate(filelist):
                if task_id and total_count > 0 and index % 50 == 0:
                    try:
                        BackgroundService().update_progress(
                            task_id=task_id,
                            progress=int(index * 30 / total_count),
                            progress_data={"stage": "importing", "total": total_count, "imported": 0}
                        )
                    except Exception as e:
                        logging.error("[SCAN] Failed to update progress: %s", e)

                row_id = self._scan_one_file(fpath, session, import_id, processed_paths, processed_hashes)
                if row_id is not None:
                    work_queue.put(row_id)
                    queued_count += 1
        finally:
            work_queue.put(None)  # sentinel: Phase 1 done

        logging.info("[IMPORT] Phase 1 done: %d files queued. Waiting for Phase 2...", queued_count)

        # Wait for Phase 2 to finish gracefully
        importing_thread.join()

        logging.info("[IMPORT] Both phases done in %.3fs. Queued: %d, Imported: %d",
                     time.time() - start_time, queued_count, len(importing_imported))

        if task_id:
            try:
                BackgroundService().update_progress(
                    task_id=task_id,
                    progress=100,
                    progress_data={"stage": "completed", "total": queued_count, "imported": len(importing_imported)}
                )
            except Exception as e:
                logging.error("[IMPORT] Failed to update final progress: %s", e)

        if importing_imported:
            logging.info("[IMPORT] Starting auto-fill for %d imported books", len(importing_imported))
            AutoFillService().auto_fill_all(importing_imported)

    @AsyncService.register_service
    def do_rename_category(self, old_dir_path, new_dir_path, scan_upload_path):
        """目录重命名/移动后，将 src_path 在旧目录下的书籍分类更新为新目录对应的一级子目录名"""
        old_dir_path = os.path.realpath(old_dir_path)
        new_dir_path = os.path.realpath(new_dir_path)
        scan_upload_path = os.path.realpath(scan_upload_path)

        # 计算新分类名：新路径在 scan_upload_path 下的第一级子目录名
        try:
            rel = os.path.relpath(new_dir_path, scan_upload_path)
        except ValueError:
            logging.warning("[RENAME DIR] 新目录不在 scan_upload_path 下: %s", new_dir_path)
            return

        parts = rel.split(os.sep)
        new_category = parts[0] if parts else ""

        if not new_category or new_category in ('.', '..'):
            logging.warning("[RENAME DIR] 无效的分类名: %s", new_category)
            return
        if len(new_category) >= 10 or any(c in new_category for c in ',:;|/\'"\t '):
            logging.warning("[RENAME DIR] 分类名含非法字符或过长，跳过: '%s'", new_category)
            return

        # 查找 src_path 在旧目录下的所有 Item
        sep = os.sep
        session = self.session
        all_items = session.query(Item).all()
        affected = [
            item for item in all_items
            if item.src_path and (
                os.path.realpath(item.src_path) == old_dir_path or os.path.realpath(item.src_path).startswith(old_dir_path + sep)
            )
        ]

        if not affected:
            logging.info("[RENAME DIR] Not found books which src_path in '%s', no need to update", old_dir_path)
            return

        logging.info("[RENAME DIR] Found %d books，update category to '%s'", len(affected), new_category)
        for item in affected:
            try:
                self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {item.book_id: new_category})
                # 同步更新 src_path 为新路径，方便后续重命名链式追踪
                suffix = os.path.realpath(item.src_path)[len(old_dir_path):]
                item.src_path = new_dir_path + suffix
                logging.info("[RENAME DIR] book_id=%d category->%s, src_path->%s",
                             item.book_id, new_category, item.src_path)
            except Exception as e:
                logging.error("[RENAME DIR] Failed to update book_id=%d,: %s", item.book_id, e)

        try:
            session.commit()
            logging.info("[RENAME DIR] category updated successfully")
        except Exception as e:
            logging.error("[RENAME DIR] Failed to commit: %s", e)
            session.rollback()

    @AsyncService.register_service
    def do_moved_file(self, old_file_path, new_file_path, scan_upload_path):
        """文件重命名/移动后，将 src_path 在旧目录下的书籍分类更新为新目录对应的一级子目录名"""
        old_file_path = os.path.realpath(old_file_path)
        new_file_path = os.path.realpath(new_file_path)
        scan_upload_path = os.path.realpath(scan_upload_path)

        if os.path.isdir(new_file_path):
            logging.warning("[RENAME FILE] 路径是目录，跳过: %s", new_file_path)
            return

        # 计算新分类名：新路径在 scan_upload_path 下的第一级子目录名
        try:
            rel = os.path.relpath(new_file_path, scan_upload_path)
        except ValueError:
            logging.warning("[RENAME FILE] 新目录不在 scan_upload_path 下: %s", new_file_path)
            return

        parts = rel.split(os.sep)
        new_category = parts[0] if parts else ""

        if not new_category or new_category in ('.', '..'):
            logging.warning("[RENAME FILE] 无效的分类名: %s", new_category)
            return
        if len(new_category) > 10 or any(c in new_category for c in ',:;|/\'"\t '):
            logging.warning("[RENAME FILE] 分类名含非法字符或过长，跳过: '%s'", new_category)
            return

        session = self.session
        affected = session.query(Item).filter(Item.src_path == old_file_path).all()
        if not affected:
            # 尝试使用ScanFile表中的路径进行匹配，兼容之前未设置src_path的情况
            logging.info("[RENAME FILE] 在 Item 表中未找到 src_path 为 '%s' 的书籍，尝试在 ScanFile 表中查找", old_file_path)
            scan_files = session.query(ScanFile).filter(ScanFile.path == old_file_path).all()
            if scan_files:
                book_ids = [sf.book_id for sf in scan_files if sf.book_id]
                affected = session.query(Item).filter(Item.book_id.in_(book_ids)).all()
        if not affected:
            logging.info("[RENAME FILE] 未找到 src_path 为 '%s' 的书籍，无需更新", old_file_path)
            return

        logging.info("[RENAME FILE] Found %d books，update category to '%s'", len(affected), new_category)
        for item in affected:
            try:
                self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {item.book_id: new_category})
                item.src_path = new_file_path
                logging.info("[RENAME FILE] book_id=%d category->%s, src_path->%s", item.book_id, new_category, item.src_path)
            except Exception as e:
                logging.error("[RENAME FILE] Failed to update book_id=%d, %s", item.book_id, e)

        try:
            session.commit()
            logging.info("[RENAME FILE] Succeed to update categories")
        except Exception as e:
            logging.error("[RENAME FILE] Failed to commit: %s", e)
            session.rollback()
