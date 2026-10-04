#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
#
# (PoxenStudio)do_import 是扫描导入的主入口，负责协调整个两阶段流水线导入流程：
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
#       * DJVU/UVZ/CBZ 扫描版先校验容器，以文件名编目为底合并内嵌元数据；仅唯一同名候选才并入，多候选按新书入库。
#   - 若配置 IMPORT_CATEGORY_WITH_FOLDER=True，将文件所在上传目录的第一级子目录名
#     作为书籍分类写入自定义字段。
#   - 若配置 REMOVE_IMPORTED_FILE=True，导入后删除源文件（仅适用于全新导入或已存在的情况）。
#   - 每 20 个文件批量提交一次事务，完成后执行最终提交并清理 scoped_session。
#

import datetime
import errno
import hashlib
import os
import logging
import queue as _queue
import shutil
import threading
import time
import traceback

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from webserver.i18n import _
from webserver.base.epub_helper import EpubHelper
from webserver.base.image_helper import ImageHelper
from webserver.base.image_generator import ImageGenerator
from webserver.base.meta_helper import guess_authors, guess_tags
from webserver.services import AsyncService
from webserver.models import Item, ScanFile, Reader
from webserver import utils, constants
from webserver.services.autofill import AutoFillService
from webserver.services.catalog import CatalogExtractService
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_COLUMN_CATEGORY, CALIBRE_ERROR_FLAG
from webserver.constants import BOOK_TYPE_EBOOK, BOOK_TYPE_PHYSICAL, CALIBRE_COLUMN_DYNAMIC_COVER, CALIBRE_COLUMN_TRANSLATORS
from webserver.constants import SCANNED_DOCUMENT_FORMATS
from webserver.base.book_files import InvalidBookFileError, read_book_metadata, validate_book_file
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver import loader

CONF = loader.get_settings()
MEGA_BYTES = 1024 * 1024
# 可扫描导入的格式与上传一致
SCAN_EXT = constants.ACCEPTED_BOOK_FORMATS


class ScanService(AsyncService):
    static_abort_flag = False
    static_is_importing = False
    static_import_id = 0
    static_import_files_cnt = 0
    static_import_user_id = 0  # 当前正在运行的导入任务的发起用户id，用于权限校验(取消等)
    static_status_cnt: dict[str, int] = {
        ScanFile.READY: 0,
    }
    invalid_folder: set[str] = set()
    # 导入/批量删除/有声书导入"检查对方状态 + 置自己的运行位"必须在这把锁内原子完成
    task_claim_lock = threading.Lock()
    static_bulk_delete: dict = {
        "running": False,
        "done": False,
        "err": "",
        "status": "",
        "delete_files": False,
        "cancel": False,
        "cancelled": False,
        "total": 0,
        "processed": 0,
        "deleted_files": 0,
        "skipped": 0,
    }

    @staticmethod
    def is_importing():
        return ScanService.static_is_importing

    @staticmethod
    def is_bulk_deleting():
        return bool(ScanService.static_bulk_delete.get("running"))

    @staticmethod
    def bulk_delete_state():
        return dict(ScanService.static_bulk_delete)

    @staticmethod
    def can_manage(user_id, is_admin_user):
        """判断某用户是否有权限管理(取消)当前正在运行的导入任务：任务发起者本人或管理员"""
        if is_admin_user:
            return True
        return bool(ScanService.static_import_user_id) and user_id == ScanService.static_import_user_id

    @staticmethod
    def total_files_in_task():
        return ScanService.static_import_files_cnt

    @staticmethod
    def status_count():
        return dict(ScanService.static_status_cnt)

    @staticmethod
    def importing_id():
        return ScanService.static_import_id

    @staticmethod
    def cancel():
        if not ScanService.static_is_importing:
            return
        ScanService.static_abort_flag = True
        logging.info("[IMPORT]Cancel the importing")

    @staticmethod
    def cancel_bulk_delete():
        """请求取消正在运行的批量删除任务：只置标志，由批循环在批次边界生效（已提交的批次不回滚）。"""
        if not ScanService.is_bulk_deleting():
            return
        ScanService.static_bulk_delete["cancel"] = True
        logging.info("[BULK-DELETE]Cancel requested")

    @staticmethod
    def get_invalid_folders():
        if ScanService.invalid_folder:
            logging.info(f"[IMPORT]Invalid folders#0: {ScanService.invalid_folder}")
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

    def _mark_missing_scan_files(self):
        """导入完成后，将源文件已不存在的 NEW/READY 记录标记为 MISSED，避免一直残留在待导入列表中"""
        start_time = time.time()
        session = self.session
        try:
            rows = session.query(ScanFile).filter(ScanFile.status.in_([ScanFile.NEW, ScanFile.READY])).all()
            missed = 0
            for row in rows:
                if row.path and not os.path.exists(row.path):
                    row.status = ScanFile.MISSED
                    row.update_time = datetime.datetime.now()
                    missed += 1
            if missed:
                session.commit()
            logging.info("[IMPORT] Checked %d NEW/READY records, marked %d as missed in %.3f seconds", len(rows), missed, time.time() - start_time)
        except Exception as err:
            logging.error("[IMPORT] Failed to mark missing scan files: %s", err)
            session.rollback()

    @staticmethod
    def resolve_ready_paths(session, mark_missing=True):
        """选择器 "ready"：取出全部 READY 记录的路径，续导取消/中断遗留的待导入文件。

        Phase1 逐行 commit，READY 记录是持久化的，中断后靠本选择器即可续导（哈希复用，
        不重算）；源文件已不存在的记录顺手标 MISSED——取消路径没有 _mark_missing_scan_files
        的清扫，在这里补上，避免一直残留在待导入列表。

        READY 只由电子书扫描阶段写入，这里仍走 status_filter 的电子书口径以防日后漂移。
        """
        paths = []
        dirty = False
        rows = ScanService.status_filter(session.query(ScanFile), ScanFile.READY).all()
        for row in rows:
            if not row.path:
                continue
            if os.path.isfile(row.path):
                paths.append(row.path)
            elif mark_missing:
                row.status = ScanFile.MISSED
                row.update_time = datetime.datetime.now()
                dirty = True
        if dirty:
            try:
                session.commit()
            except Exception as err:
                logging.error("[IMPORT] Failed to mark missing ready records: %s", err)
                session.rollback()
        logging.info("[IMPORT] Ready selector resolved %d paths (%d rows)", len(paths), len(rows))
        return paths

    @staticmethod
    def ebook_scan_filter(query):
        """把查询限定在电子书扫描记录上（排除有声书记录）。

        有声书导入复用同一张 scanfiles 表（import_type=2、path 是目录），它的 IMPORTED/
        EXIST/INVALID 记录是"该目录已处理过"的跳表：一旦被电子书侧的按状态导入/批量删除
        顺手清掉，下次有声书导入会把全部目录当新目录重跑（INVALID 全量重试是真实 IO 开销）。
        两套流程各管各的记录口径，按状态的公共入口统一过这道闸。

        import_type 是后加列（旧库 ALTER TABLE 补 0），NULL 一律按电子书处理。
        """
        return query.filter(
            or_(
                ScanFile.import_type.is_(None),
                ScanFile.import_type != constants.IMPORT_TYPE_AUDIOBOOK,
            )
        )

    @staticmethod
    def status_filter(query, status):
        """批量动作口径：todo = 非 IMPORTED，其余按状态等值过滤，一律排有声书记录。

        选择器解析、导入预检、批量删除共用本实现，防止各处过滤条件漂移；统一经
        ebook_scan_filter 收敛到电子书扫描记录——导入预检的 COUNT 与实际解析、批删执行
        必须是同一口径，否则预检条数会与实际动作对不上。

        注意：本函数排掉有声书记录，所以**不能**用来算管理页页签上的数字（那要与列表
        行数一致，见 list_scan_filter）。
        """
        query = ScanService.ebook_scan_filter(query)
        if status == "todo":
            return query.filter(ScanFile.status.not_in([ScanFile.IMPORTED]))
        return query.filter(ScanFile.status == status)

    @staticmethod
    def list_scan_filter(query, filter_kind="all"):
        """列表/页签口径：作用于**全部**扫描记录（含有声书 import_type=2）。

        - "todo" → 非 IMPORTED
        - "done" → IMPORTED
        - 其它   → 不过滤

        ImportList 的分页查询与页签数字（Scanner.summary 的 todo/done）共用本函数，
        保证「待处理 (N)」恒等于该页签下列表底部的「共 N 条」——两处各写一套过滤条件
        正是历史上页签与列表对不上的原因（exist 一度只被算进"已导入"）。与 status_filter
        的区别：status_filter 是批量动作口径且排有声书。
        """
        if filter_kind == "todo":
            return query.filter(ScanFile.status.not_in([ScanFile.IMPORTED]))
        if filter_kind == "done":
            return query.filter(ScanFile.status.in_([ScanFile.IMPORTED]))
        return query

    @staticmethod
    def resolve_filter_paths(session, filter_kind="todo"):
        """选择器 "filter"：按状态取磁盘上仍存在的记录路径。

        "todo" = 非 IMPORTED（管理页待导入语义）；其余取 ScanFile 状态常量做等值过滤
        （normalize_import_filelist 已挡掉 IMPORTED 与任意字符串）。已消失的文件不改
        状态（记录自身已带 invalid/missed 等状态），只从本次导入剔除。
        """
        query = ScanService.status_filter(session.query(ScanFile.path), filter_kind)
        paths = [p for (p,) in query.all() if p and os.path.isfile(p)]
        logging.info("[IMPORT] Filter selector (%s) resolved %d paths", filter_kind, len(paths))
        return paths

    @staticmethod
    def resolve_dir_paths(scan_upload_path, names):
        """选择器 "dirs"：把扫描目录下的**一级**子目录名解析成绝对路径（去重、保序）。

        严格限定在 scan_upload_path 内（realpath + commonpath 防目录穿越）；名字里带
        路径分隔符的（子路径）一律不收，解析后按相对路径首段复核排除项——隐藏目录、
        ~ 临时目录、有声书目录，内层段绕不过（如 "sf/../audiobooks"）；不存在或越界的
        名字直接丢弃并记日志。
        """
        if not scan_upload_path:
            return []
        base = os.path.realpath(scan_upload_path)
        if not os.path.isdir(base):
            return []
        dirs = []
        for name in names or []:
            if not isinstance(name, str):
                continue
            name = name.strip().strip("/\\")
            if not name or "\x00" in name:
                continue
            try:
                path = os.path.realpath(os.path.join(base, name))
            except (ValueError, OSError):
                logging.warning("[IMPORT] Dir selector skipped invalid dir: %r", name)
                continue
            try:
                inside = os.path.commonpath([base, path]) == base
            except ValueError:
                # Windows 跨盘符等场景 commonpath 直接抛 ValueError
                inside = False
            if not inside or not os.path.isdir(path):
                logging.warning("[IMPORT] Dir selector skipped invalid dir: %r", name)
                continue
            rel = os.path.relpath(path, base)
            if os.sep in rel or (os.altsep and os.altsep in rel):
                # 一级子目录契约：realpath 后仍带分隔符说明请求的是嵌套子路径
                logging.warning("[IMPORT] Dir selector skipped nested path: %r", name)
                continue
            first = rel.split(os.sep)[0]
            # Windows 上目录名大小写不敏感，"AudioBooks" 也要挡（常量本身全小写）
            if first.startswith((".", "~")) or first.lower() == constants.AUDIO_BOOK_IMPORTS:
                logging.warning("[IMPORT] Dir selector skipped excluded dir: %r", name)
                continue
            if path not in dirs:
                dirs.append(path)
        logging.info("[IMPORT] Dir selector resolved %d dirs", len(dirs))
        return dirs

    @staticmethod
    def _real_file_in_scan_dir(fpath, scan_upload_path):
        """realpath + commonpath 判定路径相对扫描导入目录的位置；返回 (realpath, reason)。

        防越界删除的单一闸口：文件位于目录内 → (realpath, None)；目录外 → (None, "outside")；
        缺失/非文件/解析失败（含跨盘 ValueError）→ (None, "missing")。有声书的 path 是
        目录，isfile 闸门保证 audiobooks/ 源目录永不会被本判定放行删除。
        """
        if not fpath or not scan_upload_path:
            return None, "missing"
        try:
            real = os.path.realpath(fpath)
        except (ValueError, OSError):
            return None, "missing"
        if not os.path.isfile(real):
            return None, "missing"
        try:
            inside = os.path.commonpath([scan_upload_path, real]) == scan_upload_path
        except ValueError:
            inside = False
        return (real, None) if inside else (None, "outside")

    @staticmethod
    def _bulk_delete_core(session, status, delete_files, scan_upload_path, progress=None, batch_size=500, should_cancel=None):
        """批量删除指定状态的全部 ScanFile 记录；delete_files 时把扫描导入目录内的源文件一并真删。

        记录一律删除；文件只有 realpath+commonpath 确认位于 scan_upload_path 内才删：
        越界只删记录并计 skip，文件本就不存在不算 skip；delete_files=False 时完全不做
        stat（百万行纯记录删除省去逐行 realpath/isfile）。按 id 排序分批查询、删除、提交，
        内存与表大小解耦；返回 (total, deleted_files, skipped)。

        should_cancel 在每批开始前调用，返回 True 即停在批次边界（已提交的批次不回滚）；
        返回的 total 仍是开工前的全量计数，processed 以 progress 回调最后一次上报为准。

        过滤口径经 status_filter → ebook_scan_filter 收敛：有声书记录（import_type=2）不参与
        本方法——它的 path 是目录（isfile 闸门本就不会真删），而那条记录本身是跳表，不能清。
        """
        base_query = ScanService.status_filter(session.query(ScanFile), status)
        total = base_query.count()
        base = os.path.realpath(scan_upload_path) if scan_upload_path else ""
        processed = deleted_files = skipped = 0
        while True:
            if should_cancel is not None and should_cancel():
                logging.info("[BULK-DELETE]Cancelled after %d/%d records", processed, total)
                break
            rows = base_query.order_by(ScanFile.id).limit(batch_size).all()
            if not rows:
                break
            ids = [row.id for row in rows]
            for row in rows:
                if delete_files:
                    real, reason = ScanService._real_file_in_scan_dir(row.path, base)
                    if reason == "outside":
                        logging.warning("[BULK-DELETE] Skip file outside scan dir: %s", row.path)
                        skipped += 1
                    elif real:
                        try:
                            os.remove(real)
                            deleted_files += 1
                        except OSError as err:
                            logging.error("[BULK-DELETE] Failed to remove %s: %s", real, err)
                            skipped += 1
                processed += 1
            session.query(ScanFile).filter(ScanFile.id.in_(ids)).delete(synchronize_session=False)
            try:
                session.commit()
            except Exception as err:
                logging.error("[BULK-DELETE] Batch commit error: %s", err)
                session.rollback()
                raise
            if progress:
                try:
                    progress(processed, total, deleted_files, skipped)
                except Exception:
                    logging.error("[BULK-DELETE] Progress callback error", exc_info=True)
        return total, deleted_files, skipped

    def _collect_imported_path(self, skip_last=False):
        start_time = time.time()
        base_query = (
            self.session.query(ScanFile.path, ScanFile.import_id)
            .filter(ScanFile.status.in_([ScanFile.IMPORTED, ScanFile.EXIST]))
            .filter(ScanFile.path.isnot(None))
        )

        last_import_id = 0
        if skip_last:
            # Only skip last task's imported directories
            last_row = (
                self.session.query(ScanFile.import_id)
                .filter(ScanFile.status.in_([ScanFile.IMPORTED, ScanFile.EXIST]))
                .filter(ScanFile.path.isnot(None))
                .filter(ScanFile.import_id.isnot(None))
                .order_by(ScanFile.import_id.desc())
                .first()
            )
            if not last_row:
                return [], [], 0
            last_import_id = last_row[0]
            imported_rows = (
                base_query
                .filter(ScanFile.import_id == last_import_id)
                .order_by(ScanFile.id.desc())
                .all()
            )
        else:
            imported_rows = base_query.order_by(ScanFile.import_id.desc(), ScanFile.id.desc()).all()

        if not imported_rows:
            return [], [], 0

        last_imported_dir = None
        imported_dirs = set()
        imported_files_in_last_dir = set()

        for (path, import_id) in imported_rows:
            if not path:
                continue
            if last_import_id == 0:
                last_import_id = import_id
            fpath = os.path.realpath(path)
            fdir = os.path.dirname(fpath)
            if last_imported_dir is None:
                last_imported_dir = fdir
            if fdir == last_imported_dir:
                imported_files_in_last_dir.add(fpath)
            elif fdir:
                imported_dirs.add(fdir)

        if last_imported_dir is None:
            return [], [], 0

        logging.info(
            "[SCAN] Imported path cache loaded: dirs=%d, files_in_last_dir=%d, last_dir=%s, last_import_id=%d, cost=%.3f seconds",
            len(imported_dirs),
            len(imported_files_in_last_dir),
            last_imported_dir,
            last_import_id,
            time.time() - start_time,
        )
        return list(imported_dirs), list(imported_files_in_last_dir), last_import_id

    def _collect_files(self, paths, imported_dirs=None, imported_files=None):
        if paths is None or paths == "all":
            dirs = [CONF.get("scan_upload_path", "")]
            if not dirs[0] or not os.path.isdir(dirs[0]):
                logging.warning("[IMPORT] scan_upload_path is not configured")
                return []
        elif isinstance(paths, str):
            dirs = [paths]
        else:
            dirs = list(paths)

        imported_dir_set = {os.path.realpath(d) for d in (imported_dirs or []) if d}
        imported_file_set = {os.path.realpath(p) for p in (imported_files or []) if p}

        filelist = []
        for p in dirs:
            if os.path.basename(p).startswith("."):
                logging.info(f"[SCAN]Ignore {p}")
                continue
            logging.info(f"[SCAN]scan {p}")
            if os.path.isfile(p):
                fmt = p.split(".")[-1].lower()
                if fmt not in SCAN_EXT:
                    continue
                real_p = os.path.realpath(p)
                if real_p in imported_file_set or os.path.dirname(real_p) in imported_dir_set:
                    continue
                filelist.append(p)
            elif os.path.isdir(p):
                for dirpath, dirnames, filenames in os.walk(p, onerror=ScanService.os_walk_error_handler):
                    real_dirpath = os.path.realpath(dirpath)
                    dirnames[:] = [
                        d for d in dirnames
                        if not d.startswith(".") and os.path.realpath(os.path.join(dirpath, d)) not in imported_dir_set
                    ]
                    # Skip files in this directory if it's already fully imported
                    if real_dirpath in imported_dir_set:
                        continue
                    for fname in filenames:
                        fmt = fname.split(".")[-1].lower()
                        if not fmt or fmt not in SCAN_EXT or fname.startswith('.'):
                            continue
                        fpath = os.path.join(dirpath, fname)
                        if not os.path.isfile(fpath):
                            continue
                        if os.path.realpath(fpath) not in imported_file_set:
                            filelist.append(fpath)
            else:
                logging.warning("[SCAN] Path not found: %s", p)
        return filelist

    @AsyncService.register_service
    def do_import(self, paths, user_id, skip_last_dirs=0, force=False, import_id=0, cleanup_dir=None, selector=None, sole=False):
        """
            force: 为TRUE时不检查重复的图书，直接导入
            import_id: 由调用方预先生成的批次id(如批量上传)，用于调用方在发起后立即拿到id去轮询逐文件结果；
                       为0时按原逻辑自动生成(或复用skip_last_dirs计算出的续跑id)
            cleanup_dir: 本次导入完成/取消后需要清理的暂存目录(如批量上传的暂存文件)，
                         仅当 KEEP_UPLOAD_SOURCE_FILE 配置为 False 时才会删除
            selector: 服务端选择器 ("ready"|"filter", value)，非空时忽略 paths 参数，由本方法
                      在后台服务线程解析出文件清单——全量 .all() + 逐行 stat 在百万行表上会
                      冻住 tornado ioloop，绝不能在 handler 里做（handler 只做 COUNT 预检）
            sole: 本次导入新建的书籍全部设为私藏(Item.sole，仅收藏人可见)；只作用于新建 Item，
                  命中同书加格式/已存在记录不受影响
        """
        with ScanService.task_claim_lock:
            if ScanService.static_is_importing:
                logging.error("Importing is running, please wait...")
                return
            if ScanService.is_bulk_deleting():
                # 二道闸：handler 检查与异步入队之间存在窗口，服务线程入口再拦一次
                logging.error("[IMPORT] Bulk deleting is running, import rejected")
                self.add_msg(user_id=user_id, status="error", msg=_("已有批量删除任务正在运行，请稍后再试"))
                return
            ScanService.static_is_importing = True

        ScanService.invalid_folder.clear()
        ScanService.static_abort_flag = False
        ScanService.static_import_user_id = user_id
        start_time = time.time()

        imported_dirs = []
        imported_files = []
        imported_id = 0
        if skip_last_dirs > 0:
            skip_last = (skip_last_dirs == 1)
            imported_dirs, imported_files, imported_id = self._collect_imported_path(skip_last)
        if import_id:
            imported_id = import_id

        if selector is not None:
            sel_kind, sel_value = selector
            if sel_kind == "ready":
                paths = self.resolve_ready_paths(self.session)
            else:
                paths = self.resolve_filter_paths(self.session, sel_value)

        filelist = self._collect_files(paths, imported_dirs=imported_dirs, imported_files=imported_files)
        logging.info("[IMPORT] Collected %d files in %.3f seconds (skip_last_dirs=%d)", len(filelist), time.time() - start_time, skip_last_dirs)
        if not filelist:
            # 选择器模式下 paths 是全量解析结果（百万行时单条日志上百 MB），只记条数
            candidates = paths if isinstance(paths, str) else "%d paths" % len(paths or [])
            logging.warning("[IMPORT] No valid files found in: %s", candidates)
            if selector is not None:
                # 选择器空跑：记录在库但磁盘上已无对应文件（missed/invalid 等），明确告知而非静默结束
                self.add_msg(
                    user_id=user_id,
                    status="warning",
                    msg=_("选择器没有找到可导入的文件，对应记录可能已失效或源文件已不存在"),
                )
            ScanService.static_is_importing = False
            ScanService.static_import_user_id = 0
            if cleanup_dir and not CONF.get("KEEP_UPLOAD_SOURCE_FILE", False):
                shutil.rmtree(cleanup_dir, ignore_errors=True)
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
            self.do_import_internal(filelist, user_id, task_id, imported_id, force, sole=sole)
            if task_id:
                BackgroundService().complete_task(task_id=task_id)

            if ScanService.static_abort_flag:
                logging.info("[IMPORT] Cancelled by user")
                self.add_msg(
                    user_id=user_id,
                    status="success",
                    msg=_("图书导入被取消, 共%d本，成功%d本，失败%d本") % (
                        ScanService.static_import_files_cnt,
                        ScanService.static_status_cnt.get(ScanFile.IMPORTED, 0),
                        ScanService.static_status_cnt.get(ScanFile.INVALID, 0),
                    ),
                )
            else:
                logging.info("[IMPORT] Completed")
                self._mark_missing_scan_files()
                self.add_msg(
                    user_id=user_id,
                    status="success",
                    msg=_("图书导入完成: 共%d本，成功%d本，失败%d本") % (
                        ScanService.static_import_files_cnt,
                        ScanService.static_status_cnt.get(ScanFile.IMPORTED, 0),
                        ScanService.static_status_cnt.get(ScanFile.INVALID, 0),
                    ),
                )
        except Exception as err:
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
            logging.error(f"[IMPORT] Failed: {err}")
            logging.error(traceback.format_exc())
        finally:
            if cleanup_dir and not CONF.get("KEEP_UPLOAD_SOURCE_FILE", False):
                logging.info("[IMPORT] Cleaning up staging dir: %s", cleanup_dir)
                shutil.rmtree(cleanup_dir, ignore_errors=True)
        ScanService.static_is_importing = False
        ScanService.static_abort_flag = False
        ScanService.static_import_user_id = 0

    def _compute_hash(self, fpath):
        start = time.time()
        sha256 = hashlib.sha256()
        try:
            file_size = os.path.getsize(fpath)
            with open(fpath, "rb") as f:
                if file_size < 6 * MEGA_BYTES:
                    sha256.update(f.read(2 * MEGA_BYTES))
                else:
                    sha256.update(f.read(2 * MEGA_BYTES))
                    f.seek(-2 * MEGA_BYTES, 2)
                    sha256.update(f.read(2 * MEGA_BYTES))
            sha256.update(str(file_size).encode("utf-8"))
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

    def _import_one_file(self, row, user_id, scan_upload_path, session, force, sole=False):
        """
            Read metadata and import one READY ScanFile into calibre.

            Handles all error paths internally (sets row.status, calls save_or_rollback).
            Returns book_id if a new book was successfully linked via Item, else None.
        """
        from calibre.ebooks.metadata.book.base import Metadata

        fpath = row.path
        fname = os.path.basename(fpath)
        fmt = fpath.split(".")[-1].lower()
        start_time = time.time()
        _translators = []
        _authors = []

        try:
            validate_book_file(fpath, fmt)
        except InvalidBookFileError as e:
            logging.error("[IMPORT] Invalid book file %s: %s", fpath, e)
            row.status = ScanFile.INVALID
            row.title = None
            self.save_or_rollback(row, session)
            return None, ScanFile.INVALID

        if fmt == "txt":
            title = fname[:-len(fmt) - 1]
            title = utils.remove_zlibrary_suffix(title)
            title, author = utils.guess_title_author_from_filename(title)
            mi = Metadata(title, [author] if author else [_("佚名")])
            logging.info("[IMPORT] Skipped metadata read for %s: %s", fmt, repr(title))
        else:
            try:
                mi = read_book_metadata(fpath, fmt, fname)
                mi.title = utils.super_strip(mi.title)
                if mi.authors:
                    _authors, _translators = guess_authors(mi.authors)
                else:
                    _authors, _translators = guess_authors([utils.super_strip(mi.author_sort)])
                mi.authors = _authors
                logging.info("[IMPORT] Metadata read [%.3fs]: %s", time.time() - start_time, repr(mi.title))
            except Exception as e:
                logging.error("[IMPORT] Error reading metadata from %s: %s", fpath, e)
                row.status = ScanFile.INVALID
                self.save_or_rollback(row, session)
                return None, ScanFile.INVALID

            if mi is not None and mi.title and mi.title == CALIBRE_ERROR_FLAG:
                # PDF加密导致元数据读取失败，后续会用文件名做标题，作者佚名；其他格式则直接视为无效文件
                if fmt == "pdf":
                    mi = None
                else:
                    logging.error("[IMPORT] Failed to get metadata for %s", fpath)
                    row.status = ScanFile.INVALID
                    row.title = None
                    self.save_or_rollback(row, session)
                    return None, ScanFile.INVALID

            # Normalize title/author for pdf (PDF_TILE_WITH_FILE_NAME=False)
            if fmt == "pdf":
                if mi is None:
                    mi = Metadata(utils.remove_zlibrary_suffix(fname.replace("." + fmt, "")), [_("佚名")])
                elif CONF.get("PDF_TILE_WITH_FILE_NAME", False):
                    mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                    mi.authors = [_("佚名")]
                else:
                    title_ = mi.title.strip() if mi.title else ""
                    if not title_ or title_.find("下载工具") >= 0 or title_ == "SSReader Print.":
                        mi.title = utils.remove_zlibrary_suffix(fname.replace("." + fmt, ""))
                    else:
                        mi.title = utils.remove_zlibrary_suffix(title_)
                    if mi.authors is None or len(mi.authors) == 0 or mi.authors[0].lower() == "unknown":
                        mi.authors = [_("佚名")]

        mi.tags = guess_tags(mi.tags)
        row.title = mi.title
        row.author = mi.authors[0] if mi.authors else mi.author_sort
        row.publisher = mi.publisher
        row.tags = ", ".join(mi.tags)

        new_book_id = None
        try:
            if force or CONF.get("UPLOAD_IGNORE_TITLE_CHECKING", False):
                ids = []
            else:
                ids = self.db.books_with_same_title(mi)
                logging.info("[IMPORT] Same title %d book(s) for: %s", len(ids) if ids else 0, fpath)
            if ids and fmt in SCANNED_DOCUMENT_FORMATS and len(ids) > 1:
                # 扫描版无可信作者元数据：多个同名候选一律按新书入库，避免误并。
                # 注意入口差异（有意保留）：此处沿用 TXT 先例不校验作者，唯一同名候选即并入；
                # 网页上传/分片路径（book.py）则要求作者匹配才并入。
                logging.info("[IMPORT] %d same-title candidates for scanned document, import as new book", len(ids))
                ids = []
            existed_ebook = False
            if ids:
                row.book_id = 0
                for bid in ids:
                    b = self.db.get_metadata(bid, index_is_id=True, get_user_categories=False)
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
                dynamic_cover = False
                mi.title_sort = utils.get_title_sort(mi.title)
                cover_fmt, cover_data = mi.cover_data
                if (cover_fmt is None or cover_data is None) and fmt == "epub":
                    cover_buf = EpubHelper.extract_cover(fpath)
                    if cover_buf:
                        mi.cover_data = ("jpeg", cover_buf.read())
                if CONF.get("USE_DYNAMIC_COVER", False):
                    fmt, data = mi.cover_data
                    if fmt is None or data is None:
                        author = mi.authors[0] if mi.authors else _("佚名")
                        data = ImageGenerator.generate_cover(mi.title, author)
                        if data:
                            mi.cover_data = ("jpeg", data)
                            dynamic_cover = True
                if mi.cover_data and mi.cover_data[1] and mi.cover_data[1][:4] == b"RIFF":
                    mi.cover_data = ("jpeg", ImageHelper.convert_to_jpeg(mi.cover_data[1]))
                detected_language = utils.detect_title_language(mi.title)
                if detected_language:
                    mi.languages = detected_language
                if not mi.languages:
                    mi.languages = CONF.get("DEFAULT_LANGUAGE", constants.DEFAULT_LANGUAGE_CODE)
                row.book_id = self.db.import_book(mi, [fpath], notify=False, import_hooks=False)
                if row.book_id is not None:
                    if dynamic_cover:
                        self.db.new_api.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {row.book_id: 1})
                    if _translators:
                        translators = ",".join(_translators)
                        self.db.new_api.set_field(CALIBRE_COLUMN_TRANSLATORS, {row.book_id: translators})
                row.status = ScanFile.IMPORTED
                logging.info("[IMPORT] Calibre import done, book_id=%d [%.3fs]", row.book_id, time.time() - start_time)

                item = Item()
                item.book_id = row.book_id
                item.collector_id = user_id
                item.sole = bool(sole)
                item.src_path = fpath
                try:
                    item.save()
                    new_book_id = row.book_id
                except Exception as err:
                    logging.error("[IMPORT] save link error: %s", err)

                if CONF.get("IMPORT_CATEGORY_WITH_FOLDER", False):
                    rel = os.path.relpath(os.path.realpath(fpath), scan_upload_path)
                    first_dir = rel.split(os.sep, maxsplit=1)[0] if os.sep in rel else ""
                    if first_dir and first_dir != ".." and len(first_dir) < 10 and not any(c in first_dir for c in ',:;|/\\\'"\t '):
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

        status = row.status
        try:
            self.save_or_rollback(row, session)
        except Exception as err:
            logging.error("[IMPORT] Failed to save ScanFile record for %s: %s", fpath, err)

        logging.info("[IMPORT] File done, status=%s [total %.3fs]: %s", row.status, time.time() - start_time, fpath)
        if time.time() - start_time > 0.25:
            logging.warning("[IMPORT] Slow import detected (%.3fs) for file: %s", time.time() - start_time, fpath)
        return new_book_id, status

    def _importing_worker(self, work_queue, importing_imported, task_id, user_id, scan_upload_path, batch_size, force, sole=False):
        """Worker thread for Phase 2: consumes row IDs from work_queue and imports each file."""
        importing_session = self.scoped_session()
        importing_index = 0
        total_count = 0

        try:
            while True:
                row_id = work_queue.get()
                try:
                    if row_id is None:  # sentinel: Phase 1 finished
                        break
                    if ScanService.static_abort_flag:
                        # Skip all to clear the queue
                        continue

                    row = importing_session.query(ScanFile).get(row_id)
                    if row is None:
                        logging.warning("[IMPORT] ScanFile id=%d not found, skipping", row_id)
                        continue

                    importing_index += 1
                    logging.info("[IMPORT] [TASK:%d] Processing [%d]: %s", task_id, importing_index, row.path)
                    if task_id and importing_index % 10 == 0:
                        status = ScanService.status_count()
                        all_values_sum = sum(status.values())
                        total_count = all_values_sum - status.get(ScanFile.IMPORTED, 0) - status.get(ScanFile.EXIST, 0)
                        processed = all_values_sum - status.get(ScanFile.READY, 0)
                        try:
                            BackgroundService().update_progress(
                                task_id=task_id,
                                progress=min(99, int(processed * 100 / total_count)),
                                progress_data={"stage": "importing", "total": total_count, "imported": processed}
                            )
                        except Exception as e:
                            logging.error("[IMPORT] Failed to update progress: %s", e)

                    new_book_id, status = self._import_one_file(row, user_id, scan_upload_path, importing_session, force, sole)
                    if status:
                        if status in ScanService.static_status_cnt:
                            ScanService.static_status_cnt[status] += 1
                        else:
                            ScanService.static_status_cnt[status] = 1

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

    def _scan_one_file(self, fpath, session, import_id, processed_paths, processed_hashes, force):
        """
            Phase scanning: 处理单个文件：计算哈希，去重，创建/更新 READY 状态的 ScanFile 记录。
        """
        if not os.path.isfile(fpath) or not os.access(fpath, os.R_OK):
            logging.warning("[SCAN] Not a valid file, skip: %s", fpath)
            return None, None

        fmt = fpath.split(".")[-1].lower()
        if not fmt or fmt not in SCAN_EXT:
            logging.info("[SCAN] Unsupported format [%s], skip: %s", fmt, fpath)
            return None, None

        real_fpath = os.path.realpath(fpath)
        if real_fpath in processed_paths:
            logging.info("[SCAN] Already processed in this run, skip: %s", fpath)
            return None, None

        same_path_rows = session.query(ScanFile).filter(ScanFile.path == fpath).all()
        for r in same_path_rows:
            if force:
                break
            if r.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[r.book_id]):
                logging.info("[SCAN] Already imported by path: %s", fpath)
                return None, None
            elif r.status == ScanFile.EXIST:
                logging.info("[SCAN] Found duplicated record with same path %s", fpath)
                return None, None

        # (PoxenStudio) Reuse cached hash if available (NEW/READY record from a previous interrupted run).
        # MISSED/PERMISSION: file was previously inaccessible, reprocess from scratch (no reuse).
        if not force:
            reuse_hash = next(
                (r.hash for r in same_path_rows
                    if r.status in (ScanFile.NEW, ScanFile.READY) and r.hash and r.hash.startswith("sha256:")),
                None,
            )
        else:
            reuse_hash = None
        if reuse_hash:
            logging.info("[SCAN] Reusing cached hash for: %s", fpath)

        hash_val, bad_reason = (reuse_hash, None) if reuse_hash else self._compute_hash(fpath)
        if same_path_rows:
            # Delete all same path records to avoid confusion
            logging.warning("[SCAN] Found multiple records with same path %s, count: %d. Cleaning up...", fpath, len(same_path_rows))
            session.query(ScanFile).filter(ScanFile.path == fpath).delete(synchronize_session=False)
            session.flush()
            same_path_rows = []

        if bad_reason:
            row = ScanFile(fpath, "", import_id)
            row.status = bad_reason
            self.save_or_rollback(row, session)
            return None, bad_reason

        row = ScanFile(fpath, hash_val, import_id)
        if hash_val in processed_hashes:
            # Keep back compatibility to set unique hash.
            row.hash = hashlib.md5(fpath.encode("utf-8")).hexdigest()
            row.status = ScanFile.DROP
            self.save_or_rollback(row, session)
            return None, ScanFile.DROP

        processed_hashes.add(hash_val)
        processed_paths.add(real_fpath)

        # Check already imported by hash
        hash_rows = session.query(ScanFile).filter(ScanFile.hash == hash_val).all()
        for hash_row in hash_rows:
            if force:
                break
            if hash_row.status == ScanFile.IMPORTED and self.db.get_data_as_dict(ids=[hash_row.book_id]):
                logging.info("[SCAN] Already imported by hash: %s", fpath)
                row.hash = hashlib.md5(fpath.encode("utf-8")).hexdigest()
                row.status = ScanFile.DROP
                self.save_or_rollback(row, session)
                return None, ScanFile.DROP

        if hash_rows:
            logging.info("[SCAN] Clear existing rows with same hash: %s, count: %d", hash_val, len(hash_rows))
            session.query(ScanFile).filter(
                ScanFile.hash == hash_val, ScanFile.status != ScanFile.IMPORTED
            ).delete(synchronize_session=False)
            session.flush()
        row.status = ScanFile.READY
        if self.save_or_rollback(row, session):
            return row.id, ScanFile.READY
        return None, None

    def do_import_internal(self, filelist, user_id, task_id=None, imported_id=0, force=False, sole=False):
        """
            并行执行:
            Phase Scanning: 负责遍历文件、计算哈希、去重，并将 READY 状态的 ScanFile 行 ID 放入队列；
            Phase Importing: 从队列中取出 ID，读取对应 ScanFile 行，执行元数据读取和导入操作。
        """
        import_id = int(time.time()) if imported_id == 0 else imported_id
        ScanService.static_import_id = import_id
        scan_upload_path = os.path.realpath(CONF.get("scan_upload_path", ""))
        total_count = len(filelist)
        batch_size = 20

        work_queue = _queue.Queue()
        importing_imported = []

        start_time = time.time()
        logging.info("[IMPORT] Start (Phase 1 + Phase 2 pipelined) for %d files, import_id=%d", total_count, import_id)

        ScanService.static_status_cnt = {
            ScanFile.READY: 0
        }

        importing_thread = threading.Thread(
            target=self._importing_worker,
            args=(work_queue, importing_imported, task_id, user_id, scan_upload_path, batch_size, force, sole),
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
                if ScanService.static_abort_flag:
                    logging.info("[IMPORT] Aborting import during scanning phase at index %d/%d", index, total_count)
                    break
                row_id, state = self._scan_one_file(fpath, session, import_id, processed_paths, processed_hashes, force)
                if row_id is not None:
                    work_queue.put(row_id)
                    queued_count += 1
                if state:
                    if state in ScanService.static_status_cnt:
                        ScanService.static_status_cnt[state] += 1
                    else:
                        ScanService.static_status_cnt[state] = 1
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
            CatalogExtractService().extract_batch(user_id, importing_imported)

            # 私藏批次不发新书通知：邮件会发全站，等于把私藏书的存在与书名公开
            if CONF.get("SEND_MAIL_FOR_NEW_BOOKS", False) and not sole:
                try:
                    book_names = []
                    index = 100
                    for bid in importing_imported:
                        b = self.db.get_metadata(bid, index_is_id=True)
                        if b and b.title:
                            book_names.append(b.title)
                        index -= 1
                        if index <= 0:
                            break

                    if book_names:
                        emails = []
                        readers = self.session.query(Reader).filter(Reader.active.is_(1)).all()
                        for r in readers:
                            if not r.email or not r.active:
                                continue
                            if r.extra and r.extra.get("allow_sending_mail", True) is True:
                                emails.append(r.email)

                        if emails:
                            from webserver.services.mail import MailService
                            site_url = CONF.get("site_url", "")
                            MailService().send_new_book_notification(emails, book_names, site_url=site_url)
                except Exception as e:
                    logging.error("[IMPORT] Failed to trigger new book notification: %s", e)

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
            # (PoxenStudio)尝试使用ScanFile表中的路径进行匹配，兼容之前未设置src_path的情况
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

    @staticmethod
    def _bulk_delete_progress(processed, total, deleted_files, skipped):
        st = ScanService.static_bulk_delete
        st["processed"] = processed
        st["total"] = total
        st["deleted_files"] = deleted_files
        st["skipped"] = skipped
        task_id = st.get("task_id")
        if task_id:
            BackgroundService().update_progress(
                task_id,
                int(processed * 100 / total) if total else 0,
                progress_data={"stage": "deleting", "total": total, "processed": processed, "deleted_files": deleted_files},
            )

    @AsyncService.register_service
    def do_bulk_delete(self, user_id, status, delete_files=False):
        """批量删除后台服务：删除指定状态的电子书记录，可选连同扫描导入目录内的源文件一起真删。

        与 do_import 是各自独立的服务线程，靠状态位互斥（本方法拒绝在导入运行时启动，
        do_import/批量上传/手动删除侧在启动前检查 is_bulk_deleting）；进度写入
        static_bulk_delete 供 /admin/import/bulk_delete/status 轮询。cancel 置位后批循环
        在批次边界停下（已提交批次不回滚），state.cancelled 供前端区分展示。
        """
        # 有声书导入写同一张 scanfiles 表（import_type=2），与批量删除互斥；
        # 批删的作用范围也已排除有声书记录（_bulk_delete_core → status_filter）；
        # 延迟导入避免模块级循环（audios_import → scan_service）
        from webserver.services.audios_import import AudioBookImporter

        with ScanService.task_claim_lock:
            if ScanService.static_is_importing:
                self.add_msg(user_id=user_id, status="error", msg=_("已有导入任务正在运行，请稍后再试"))
                return
            if ScanService.is_bulk_deleting():
                return
            if AudioBookImporter.is_running():
                self.add_msg(user_id=user_id, status="error", msg=_("有声书导入任务正在运行，请稍后再试"))
                return
            ScanService.static_bulk_delete = {
                "running": True,
                "done": False,
                "err": "",
                "status": status,
                "delete_files": bool(delete_files),
                "cancel": False,
                "cancelled": False,
                "total": 0,
                "processed": 0,
                "deleted_files": 0,
                "skipped": 0,
                "task_id": None,
            }
        task_id = None
        try:
            task = BackgroundService().update_task(
                service_type=BackgroundTask.SERVICE_TYPE_BULK_DELETE,
                service_item=_("批量删除导入记录"),
                progress=0,
                progress_data={"stage": "deleting", "total": 0, "processed": 0, "deleted_files": 0},
            )
            task_id = task.id
            ScanService.static_bulk_delete["task_id"] = task_id
        except Exception as e:
            logging.error("[BULK-DELETE] Failed to create background task: %s", e)
        start_time = time.time()
        try:
            total, deleted_files, skipped = self._bulk_delete_core(
                self.session, status, bool(delete_files), CONF.get("scan_upload_path", ""),
                progress=self._bulk_delete_progress,
                should_cancel=lambda: ScanService.static_bulk_delete.get("cancel", False),
            )
            ScanService.static_bulk_delete["total"] = total
            if ScanService.static_bulk_delete.get("cancel"):
                ScanService.static_bulk_delete["cancelled"] = True
                self.add_msg(
                    user_id=user_id,
                    status="warning",
                    msg=_("批量删除已取消: 已处理%d条记录，已删除文件%d个，跳过%d个")
                    % (ScanService.static_bulk_delete["processed"], deleted_files, skipped),
                )
                logging.info(
                    "[BULK-DELETE] Cancelled in %.3fs: status=%s processed=%d/%d files=%d skipped=%d",
                    time.time() - start_time, status,
                    ScanService.static_bulk_delete["processed"], total, deleted_files, skipped,
                )
            else:
                self.add_msg(
                    user_id=user_id,
                    status="success",
                    msg=_("批量删除完成: 共%d条记录，已删除文件%d个，跳过%d个") % (total, deleted_files, skipped),
                )
                logging.info(
                    "[BULK-DELETE] Done in %.3fs: status=%s total=%d files=%d skipped=%d",
                    time.time() - start_time, status, total, deleted_files, skipped,
                )
            if task_id:
                BackgroundService().complete_task(task_id=task_id)
        except Exception as err:
            ScanService.static_bulk_delete["err"] = str(err)
            logging.error("[BULK-DELETE] Failed: %s", err)
            logging.error(traceback.format_exc())
            if task_id:
                BackgroundService().complete_task(task_id=task_id, error_message=str(err))
            self.add_msg(user_id=user_id, status="error", msg=_("批量删除失败: %s") % err)
        finally:
            ScanService.static_bulk_delete["running"] = False
            ScanService.static_bulk_delete["done"] = True
