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
#       * 已通过路径或哈希成功导入（状态 IMPORTED）且书库记录仍存在 → 跳过。存在性
#         走 calibre Cache.has_id（纯内存），不再每本一次 get_data_as_dict。
#       * 存在 NEW/READY 状态的记录时复用缓存哈希，避免重复 I/O。
#       * 否则清除同哈希的旧非导入记录，创建新 READY 状态的 ScanFile 行。
#   - 读算与落库分离：去重查询 + 哈希 IO 在无写事务下执行，写操作暂存后攒满
#     PHASE1_BATCH_SIZE 经 _apply_phase1_batch 在短写事务内统一落库并提交；
#     计数与入队只发生在提交成功后（worker 用独立会话，入队晚于提交是跨会话可见的
#     硬要求；commit 失败整批丢弃，计数不虚高，文件在磁盘可下轮自愈）。
#     持久化失败置 static_phase1_persist_failed：本轮不提交目录快照、不清理批量
#     上传暂存目录——否则没落库的路径会被快照剪枝永久漏掉。
#   - 将 READY 行的 ID 放入有界工作队列（最大 50），自然地对阶段二施加背压。
#
# 阶段二（Importing）：独立后台线程执行
#   - 从工作队列中持续取出行 ID，加载对应 ScanFile 记录。
#   - 读取书籍元数据（calibre get_metadata），并根据标题去重：
#       * 标题已存在（电子书）→ 追加格式（add_format）。
#       * 标题不存在 → 全新导入（import_book），同时创建 Item 关联记录。
#       * DJVU/UVZ/CBZ 扫描版先校验容器，以文件名编目为底合并内嵌元数据；仅唯一同名候选才并入，多候选按新书入库。
#   - 若配置 IMPORT_CATEGORY_WITH_FOLDER=True，将文件所在上传目录的第一级子目录名
#     作为书籍分类写入自定义字段（与动态封面/译者列一起攒批写回，批提交节奏对齐）。
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
from webserver.models import Item, ScanFile, Reader, ScanDirSnapshot
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
# Phase1 批量落库窗口：攒够这么多 staged 写操作才开一次短写事务统一落库。
# 读（去重查询）与算（哈希 IO）一律在写事务之外，写事务内只有纯内存对象的
# INSERT/DELETE（亚秒级），避免长写事务横跨磁盘 IO 阻塞 worker 的并发写。
PHASE1_BATCH_SIZE = 500
# calibre 自定义列缓冲的 flush 水位：攒够这么多本就写回一次。durability 窗口上确界
# ≈ 水位×单本耗时（旧逐行同步是毫秒级；20 本一批是分钟级；5 本是折中）。
PENDING_FIELDS_FLUSH_THRESHOLD = 5
# 扫描范围：4 = 全量扫描（不忽略所有目录）——无视目录快照、全量 walk，但保留去重。
# 0 = 全量扫描（默认走目录快照增量）；1/2 为已删除的旧排除选项，发过来按 0 处理并告警。
SCAN_SCOPE_FULL_NO_SKIP = 4
LEGACY_SKIP_SCOPES = (1, 2)
# ScanFile.data 内文件签名的键：[size, mtime_ns, ctime_ns, ino]，一次 os.stat 全取。
# ctime 专防 cp -p/rsync -a 类“保 mtime 换内容”（mtime 能保住，ctime 保不住）。
FILE_SIG_KEY = "file_sig"


class ScanService(AsyncService):
    static_abort_flag = False
    # 本轮 Phase1 是否发生过持久化失败（批量 apply/commit 异常、行级 save 被丢）。
    # 置位后本轮不提交目录快照、不清理批量上传暂存目录：没落库的文件下轮按老快照
    # 全量重走自愈；若照常提交快照，这些路径会被剪枝永久漏掉（union-pending 救不了
    # 没有行的文件）。
    static_phase1_persist_failed = False
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

    def _calibre_book_exists(self, book_id):
        """书库存在性轻量检查：优先走 calibre Cache.has_id（纯内存映射），百万级逐文件调用友好。

        旧实现每次都调 get_data_as_dict(ids=[...])——单次含 SQL 查询、文件系统校验与
        整套字典构造，毫秒级；has_id 只是内存 dict 命中，微秒级。老版本 calibre 或
        异常时回退旧路径；回退也失败则按“不存在”处理（触发重导分支自愈，而非整轮中断）。
        """
        try:
            new_api = getattr(self.db, "new_api", None)
            has_id = getattr(new_api, "has_id", None) if new_api is not None else None
            if callable(has_id):
                return bool(has_id(book_id))
        except Exception as err:
            logging.debug("[SCAN] has_id check failed for book_id=%s: %s", book_id, err)
        try:
            return bool(self.db.get_data_as_dict(ids=[book_id]))
        except Exception as err:
            logging.warning("[SCAN] Existence check failed for book_id=%s, treat as missing: %s", book_id, err)
            return False

    @staticmethod
    def _begin_scan_batch(session):
        """为批量窗口确保驱动层真实 BEGIN（pysqlite 默认模式下，无外层 BEGIN 时
        SAVEPOINT 的释放会被驱动当成提交，批量窗口失效；有则不重复开）。"""
        try:
            connection = session.connection()
            if connection.dialect.name != "sqlite":
                return
            dbapi_conn = connection.connection
            if hasattr(dbapi_conn, "driver_connection"):
                dbapi_conn = dbapi_conn.driver_connection
            if getattr(dbapi_conn, "in_transaction", True):
                return
            connection.exec_driver_sql("BEGIN")
        except Exception as err:
            logging.debug("[SCAN] Begin scan batch skipped: %s", err)

    def _apply_phase1_batch(self, session, staged):
        """在短写事务内执行一批 staged 写操作，返回成功落库的 [(row_id, state)]（按暂存顺序）。

        staged 元素：("del_path", fpath) | ("del_hash", hash) | ("save", row, state)，
        由 _scan_one_file 在读算阶段（无写事务、可横跨任意时长磁盘 IO）里攒出；
        本方法只做纯内存对象的 INSERT/DELETE + flush，持写锁窗口亚秒级。
        单个操作失败只丢该操作（行级 SAVEPOINT），不毒化整批；调用方负责 commit，
        commit 成功后才能计数/入队（跨会话可见性），commit 失败则整批丢弃（文件在
        磁盘，下轮重扫自愈）。
        """
        outcomes = []
        if not staged:
            return outcomes
        self._begin_scan_batch(session)
        for op in staged:
            kind = op[0]
            try:
                with session.begin_nested():
                    if kind == "del_path":
                        session.query(ScanFile).filter(ScanFile.path == op[1]).delete(synchronize_session=False)
                    elif kind == "del_hash":
                        session.query(ScanFile).filter(
                            ScanFile.hash == op[1], ScanFile.status != ScanFile.IMPORTED
                        ).delete(synchronize_session=False)
                    elif kind == "save":
                        session.add(op[1])
                    else:
                        logging.error("[SCAN] Unknown staged op, drop it: %r", kind)
                        continue
                    session.flush()
            except IntegrityError as err:
                logging.error("[SCAN] Staged op %s failed, drop it: %s", kind, err)
                continue
            except Exception:
                logging.exception("[SCAN] Staged op %s failed, drop it", kind)
                continue
            if kind == "save":
                bid = "[ book-id=%s ]" % op[1].book_id if op[1].book_id else ""
                logging.info("update: status=%-5s, path=%s %s", op[1].status, op[1].path, bid)
                outcomes.append((op[1].id, op[2]))
        return outcomes

    def _set_calibre_fields(self, column, mapping):
        """单列批量 set_field；整批失败时逐本重试，全部 best-effort（失败只记日志）。

        旧语义里 dynamic_cover/translators 的单本失败会把整行标 INVALID；批量在 flush
        时机已脱离行上下文，无法再标行——这类失败只可能是 calibre 内部故障（非单本书
        数据问题），记 error 日志，书本身保持已入库（下次重扫跳过，不会无限重试）。
        """
        if not mapping:
            return
        try:
            self.db.new_api.set_field(column, mapping)
            return
        except Exception as err:
            logging.error("[IMPORT] Batch set_field %s failed for %d books, retry per-book: %s", column, len(mapping), err)
        for book_id, value in mapping.items():
            try:
                self.db.new_api.set_field(column, {book_id: value})
            except Exception as err:
                logging.error("[IMPORT] Failed to set %s for book_id=%s: %s", column, book_id, err)

    def _flush_pending_calibre_fields(self, pending):
        """把累积的 calibre 自定义列写回一次性落库并清空缓冲；空缓冲直接返回（无书库调用）。"""
        if not pending:
            return
        cover_ids = pending.get("dynamic_cover") or []
        if cover_ids:
            self._set_calibre_fields(CALIBRE_COLUMN_DYNAMIC_COVER, {bid: 1 for bid in cover_ids})
            del cover_ids[:]
        translators = pending.get("translators") or {}
        if translators:
            self._set_calibre_fields(CALIBRE_COLUMN_TRANSLATORS, dict(translators))
            translators.clear()
        categories = pending.get("category") or {}
        if categories:
            self._set_calibre_fields(CALIBRE_COLUMN_CATEGORY, dict(categories))
            categories.clear()

    @staticmethod
    def _put_work(work_queue, worker_thread, item, timeout=30):
        """有界队列投递：worker 意外退出时不再永久阻塞，而是明确报错结束本轮。

        worker 正常消费慢时阻塞等待（天然背压）；只有 worker 线程已死才抛
        RuntimeError——旧无界队列在同样场景下挂在 join，同样卡死但无声。
        取消请求生效后连续 2 轮超时（grace = 2×timeout，默认 60s）仍投不进去，
        说明 worker 卡死在 calibre/存储调用里无法排空队列——抛错放弃，让本轮
        结束而不是永久挂起（worker 线程泄漏为 daemon，见 do_import_internal）。
        """
        full_waits = 0
        while True:
            try:
                work_queue.put(item, timeout=timeout)
                return
            except _queue.Full:
                if not worker_thread.is_alive():
                    raise RuntimeError("importing worker thread exited unexpectedly")
                if ScanService.static_abort_flag:
                    full_waits += 1
                    if full_waits >= 2:
                        raise RuntimeError("import cancelled and worker not draining queue")
                logging.warning("[IMPORT] Work queue full, waiting for worker...")

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

    @staticmethod
    def file_signature(fpath):
        """一次 stat 取文件签名 [size, mtime_ns, ctime_ns, ino]；失败返回 None。

        ctime 专防 cp -p/rsync -a 类“保 mtime 换内容”（mtime 能保住，ctime 保不住）；
        调用方一律按“签名对不上 = 变了”处理，None 也一样（偏安全方向）。
        全程 follow_symlinks 取目标，与 realpath 口径一致。
        """
        try:
            st = os.stat(fpath)
        except OSError:
            return None
        return [st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino]

    @staticmethod
    def _load_dir_snapshots(session):
        """读出全部目录快照 {dir: (mtime_ns, entry_count)}；失败返回空（= 全量 walk）。"""
        try:
            return {
                d: (m, c)
                for (d, m, c) in session.query(
                    ScanDirSnapshot.dir, ScanDirSnapshot.mtime_ns, ScanDirSnapshot.entry_count
                ).all()
            }
        except Exception as err:
            logging.warning("[IMPORT] Snapshot load failed, full walk: %s", err)
            return {}

    @staticmethod
    def _normalize_scope(skip_last_dirs):
        """扫描范围归一化：1/2 为已删除的旧排除选项，按全量处理（保证同目录新书不漏）。

        任意非法输入（非数、inf/nan 之类 OverflowError）一律回退 0。此函数在
        static_is_importing 置位后调用，抛异常会泄漏导入锁直到重启，故绝不外抛。
        """
        try:
            skip_last_dirs = int(skip_last_dirs)
        except (TypeError, ValueError, OverflowError):
            logging.warning("[IMPORT] Bad skip_last_dirs=%r, treating as full scan", skip_last_dirs)
            return 0
        if skip_last_dirs in LEGACY_SKIP_SCOPES:
            logging.warning("[IMPORT] Legacy skip_last_dirs=%d removed, treating as full scan", skip_last_dirs)
            return 0
        return skip_last_dirs

    @staticmethod
    def _snapshot_active(paths, force, skip_last_dirs):
        """快照剪枝开关：仅「全量扫描」（skip_last_dirs==0，paths 为 None/"all"）时开。

        显式路径/目录选择器是用户明确意图（全走）；force 与选项 4 是“无视快照但保留
        去重”的全量语义；选项 3（按分类）亦不剪枝。抽成函数只为可单测。
        """
        return (paths is None or paths == "all") and not force and skip_last_dirs == 0

    def _commit_dir_snapshots(self, session, visited, scan_root):
        """整轮成功后提交目录快照（单事务原子）：upsert 本轮到访目录 + 清掉已消失目录。

        只在整轮正常完成时调用（abort/异常路径不调）；失败回滚并告警，下轮按老快照
        重走（多干活，不漏活）。另带 abort 熔断做纵深：即使被误调，中止轮次也不落盘。
        vacuum 删两类：扫描根内磁盘上已无的目录 + 已不在
        当前扫描根内的残留行（换过 scan_upload_path 的陈旧水位）。
        """
        if not scan_root:
            return
        if ScanService.static_abort_flag:
            logging.info("[IMPORT] Snapshot commit skipped (aborted)")
            return
        upserted = vacuumed = 0
        try:
            now = datetime.datetime.now()
            for d, (mtime_ns, count) in visited.items():
                row = session.get(ScanDirSnapshot, ScanDirSnapshot.hash_for(d))
                if row is None:
                    session.add(ScanDirSnapshot(d, mtime_ns, count))
                else:
                    row.mtime_ns = mtime_ns
                    row.entry_count = count
                    row.update_time = now
                upserted += 1
            for (d,) in session.query(ScanDirSnapshot.dir).all():
                under_root = d == scan_root or d.startswith(scan_root + os.sep)
                if (under_root and not os.path.isdir(d)) or not under_root:
                    session.query(ScanDirSnapshot).filter(
                        ScanDirSnapshot.dir_hash == ScanDirSnapshot.hash_for(d)
                    ).delete(synchronize_session=False)
                    vacuumed += 1
            session.commit()
        except Exception as err:
            logging.error("[IMPORT] Snapshot commit failed, will rescan fully next run: %s", err)
            try:
                session.rollback()
            except Exception:
                pass
            return
        logging.info("[IMPORT] Snapshots committed: %d upserted, %d vacuumed", upserted, vacuumed)

    def _collect_files(self, paths, use_snapshot=True):
        """收集待导入文件清单，返回 (filelist, visited)。

        use_snapshot=True 时（仅全量扫描）：自顶向下逐目录比对快照，
        mtime_ns + entry_count 双命中则跳过该目录的文件枚举（下钻永远保留——
        深层新增只 bump 直接父目录，剪下钻会漏新书）；剪枝掉的隐藏目录等不建快照
        （规则内本来就不进去）。visited 记录本轮到访过的每个目录现状，供成功后
        提交快照；剪枝只看快照，记录不分模式（显式目录同样记录，值是文件系统事实）。
        """
        if paths is None or paths == "all":
            dirs = [CONF.get("scan_upload_path", "")]
            if not dirs[0] or not os.path.isdir(dirs[0]):
                logging.warning("[IMPORT] scan_upload_path is not configured")
                return [], {}
        elif isinstance(paths, str):
            dirs = [paths]
        else:
            dirs = list(paths)

        snapshots = self._load_dir_snapshots(self.session) if use_snapshot else {}
        filelist = []
        visited: dict = {}
        skipped_dirs = 0
        for p in dirs:
            if os.path.basename(p).startswith("."):
                logging.info(f"[SCAN]Ignore {p}")
                continue
            logging.info(f"[SCAN]scan {p}")
            if os.path.isfile(p):
                fmt = p.split(".")[-1].lower()
                if fmt not in SCAN_EXT:
                    continue
                filelist.append(p)
            elif os.path.isdir(p):
                for dirpath, dirnames, filenames in os.walk(p, onerror=ScanService.os_walk_error_handler):
                    real_dirpath = os.path.realpath(dirpath)
                    # scandir 原始条目数（过滤前口径）：写读两侧必须同一定义，否则隐藏目录
                    # 增删会导致永久 miss 或永久重走。本计数含点开头条目（文件循环里再跳过）。
                    entry_count = len(dirnames) + len(filenames)
                    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                    try:
                        dir_mtime = os.stat(dirpath).st_mtime_ns
                    except OSError:
                        dir_mtime = None
                    # 命中则只跳过本目录的文件枚举，下钻永远保留：深层新增只 bump
                    # 直接父目录，祖先 mtime 不变，剪下钻会漏掉深层新书。
                    snapshot_hit = snapshots.get(real_dirpath) == (dir_mtime, entry_count)
                    skip_files = use_snapshot and dir_mtime is not None and snapshot_hit
                    if skip_files:
                        skipped_dirs += 1
                        continue
                    if dir_mtime is not None:
                        visited[real_dirpath] = (dir_mtime, entry_count)
                    for fname in filenames:
                        fmt = fname.split(".")[-1].lower()
                        if not fmt or fmt not in SCAN_EXT or fname.startswith('.'):
                            continue
                        fpath = os.path.join(dirpath, fname)
                        if not os.path.isfile(fpath):
                            continue
                        filelist.append(fpath)
            else:
                logging.warning("[SCAN] Path not found: %s", p)
        if use_snapshot:
            logging.info("[SCAN] Snapshot prune: %d dirs skipped, %d dirs visited", skipped_dirs, len(visited))
            scan_root = os.path.realpath(CONF.get("scan_upload_path", ""))
            filelist = self._union_pending_paths(filelist, scan_root)
        return filelist, visited

    def _union_pending_paths(self, filelist, scan_root):
        """把库里待处理（NEW/READY/INVALID/PERMISSION）的电子书记录路径并入清单。

        剪枝跳过的目录里可能躺着三类行：中断续导遗留及撕裂占位（NEW/READY）、
        人工修好待重试的（INVALID 文件被覆盖/PERMISSION 被 chmod）。它们数量级小
        （相对全库），逐行 realpath 归一 + isfile 后并入；去重由 Phase1 的
        processed_paths 兜底。DROP（重复标记）/EXIST/IMPORTED（终态成功）/
        MISSED（源文件已无）不并：前三者重跑结论不变，MISSED 走终态口径。

        已知限制（记录不修）：DROP 行是“同内容已另有副本”的标记，若之后把原书从
        calibre 删掉，预 PR 的全量 walk 会重评该文件并补导；剪枝后不再自动补导。
        不把 DROP 并入是为了避免每轮把全库重复文件重新枚举+重算哈希（md5 存量哈希
        吃不到签名复用）。此类孤儿用「全量扫描（不忽略所有目录）」= 选项 4 重扫即愈。
        """
        if not scan_root:
            return filelist
        try:
            rows = (
                ScanService.ebook_scan_filter(self.session.query(ScanFile.path))
                .filter(ScanFile.status.in_([ScanFile.NEW, ScanFile.READY, ScanFile.INVALID, ScanFile.PERMISSION]))
                .filter(ScanFile.path.isnot(None))
                .all()
            )
        except Exception as err:
            logging.warning("[IMPORT] Pending union query failed, skip: %s", err)
            return filelist
        if not rows:
            return filelist
        seen = set(filelist)
        added = 0
        for (p,) in rows:
            if not p or p in seen:
                continue
            try:
                real = os.path.realpath(p)
                inside = real == scan_root or real.startswith(scan_root + os.sep)
            except (ValueError, OSError):
                continue
            if not inside or not os.path.isfile(p):
                continue
            seen.add(p)
            filelist.append(p)
            added += 1
        if added:
            logging.info("[IMPORT] Pending union: %d stalled records re-queued", added)
        return filelist

    @AsyncService.register_service
    def do_import(self, paths, user_id, skip_last_dirs=0, force=False, import_id=0, cleanup_dir=None, selector=None, sole=False):
        """
            force: 为TRUE时不检查重复的图书，直接导入（附带无视目录快照、全量重算）
            skip_last_dirs: 0 = 全量扫描（默认走目录快照增量）；
                3 = 按分类导入（显式目录，不剪枝）；4 = 全量扫描（不忽略所有目录，
                无视快照、全量 walk 但保留去重）；1/2 为已删除的旧排除选项，
                发过来按 0 处理并告警（旧语义“按历史剪枝”在目录复用下会漏新书，
                已由快照增量替代）。
            import_id: 由调用方预先生成的批次id(如批量上传)，用于调用方在发起后立即拿到id去轮询逐文件结果；
                        为0时按原逻辑自动生成
            cleanup_dir: 本次导入完成/取消后需要清理的暂存目录(如批量上传的暂存文件)，
                          仅当 KEEP_UPLOAD_SOURCE_FILE 配置为 False 时才会删除；
                          Phase1 持久化失败时同样保留（快照未提交，留给下轮重扫补导）
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
        ScanService.static_phase1_persist_failed = False
        ScanService.static_import_user_id = user_id
        start_time = time.time()

        imported_id = import_id
        skip_last_dirs = self._normalize_scope(skip_last_dirs)

        if selector is not None:
            sel_kind, sel_value = selector
            if sel_kind == "ready":
                paths = self.resolve_ready_paths(self.session)
            else:
                paths = self.resolve_filter_paths(self.session, sel_value)

        # 快照剪枝只走全量作用域（细则见 _snapshot_active）。
        use_snapshot = ScanService._snapshot_active(paths, force, skip_last_dirs)
        filelist, visited = self._collect_files(paths, use_snapshot=use_snapshot)
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
            # 本轮虽无可导入文件，但目录已成功走完：提交快照，否则“只有非扫描格式的
            # 目录”会每轮重走、增量永远不生效。use_snapshot 为假（显式路径/force/选项4）
            # 时无需提交；abort 由 _commit_dir_snapshots 内部熔断兜底。
            if use_snapshot:
                self._commit_dir_snapshots(
                    self.session, visited, os.path.realpath(CONF.get("scan_upload_path", ""))
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
                # 快照只在整轮正常完成时提交：abort/异常路径不调，下轮按老快照重走
                # （多干活，不漏活）；提交点严格在全部处理之后，崩在提交中途也不产生错误跳过。
                # Phase1 持久化失败同样不提交：失败批次没落库的文件会被快照剪枝永久漏掉。
                if ScanService.static_phase1_persist_failed:
                    logging.error(
                        "[IMPORT] Phase1 persistence failures detected, skip snapshot commit "
                        "(paths without rows would be pruned permanently)"
                    )
                    self.add_msg(
                        user_id=user_id,
                        status="warning",
                        msg=_("部分扫描记录落库失败，本轮目录快照未提交，请重新扫描补齐"),
                    )
                else:
                    self._commit_dir_snapshots(
                        self.session, visited, os.path.realpath(CONF.get("scan_upload_path", ""))
                    )
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
                if ScanService.static_phase1_persist_failed:
                    # 暂存目录在 scan_upload_path 下且本轮快照未提交：保留给下轮重扫补导，
                    # 删了就没源文件可自愈了（补导成功后由管理员按需清理）。
                    logging.warning(
                        "[IMPORT] Phase1 persistence failures detected, keep staging dir: %s", cleanup_dir
                    )
                else:
                    logging.info("[IMPORT] Cleaning up staging dir: %s", cleanup_dir)
                    shutil.rmtree(cleanup_dir, ignore_errors=True)
        ScanService.static_is_importing = False
        ScanService.static_abort_flag = False
        # static_phase1_persist_failed 有意不在此复位：失败轮结束后保持 True 直到下一轮
        # do_import/do_import_internal 开头的复位点（读取点都在复位之后，无陈旧读）。
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

    def _import_one_file(self, row, user_id, scan_upload_path, session, force, sole=False, pending_fields=None):
        """
            Read metadata and import one READY ScanFile into calibre.

            Handles all error paths internally (sets row.status, calls save_or_rollback).
            Returns book_id if a new book was successfully linked via Item, else None.

            pending_fields: worker 内累积的 calibre 自定义列缓冲（dynamic_cover 列表/
                translators 与 category 字典），为 None 时走旧的逐本 set_field。
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
                        if pending_fields is None:
                            self.db.new_api.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {row.book_id: 1})
                        else:
                            pending_fields.setdefault("dynamic_cover", []).append(row.book_id)
                    if _translators:
                        translators = ",".join(_translators)
                        if pending_fields is None:
                            self.db.new_api.set_field(CALIBRE_COLUMN_TRANSLATORS, {row.book_id: translators})
                        else:
                            pending_fields.setdefault("translators", {})[row.book_id] = translators
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
                            if pending_fields is None:
                                self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {row.book_id: first_dir})
                            else:
                                pending_fields.setdefault("category", {})[row.book_id] = first_dir
                            logging.info("[IMPORT] Set category '%s' for book_id=%d", first_dir, row.book_id)
                        except Exception as cat_err:
                            logging.warning("[IMPORT] Failed to set category for book_id=%d: %s", row.book_id, cat_err)
                    else:
                        logging.warning("[IMPORT] Skipping category for '%s': invalid dir name", first_dir)

                if pending_fields is not None:
                    buffered = sum(len(v) for v in pending_fields.values())
                    if buffered >= PENDING_FIELDS_FLUSH_THRESHOLD:
                        self._flush_pending_calibre_fields(pending_fields)

            if CONF.get("REMOVE_IMPORTED_FILE", False) and (not existed_ebook or row.status == ScanFile.EXIST):
                self._remove_imported_file(fpath)
        except Exception as err:
            new_book_id = None
            row.status = ScanFile.INVALID
            logging.error("[IMPORT] Failed to process file %s: %s", fpath, err)
            logging.error(traceback.format_exc())

        status = row.status
        # 行落库失败必须诚实返回 (None, None)：worker 据此跳过计数/入库名单，避免
        # “已计数但未持久化”的虚假成功；行保持旧状态，下轮重扫经标题命中收敛自愈。
        if not self.save_or_rollback(row, session):
            logging.error("[IMPORT] Failed to save ScanFile record for %s, will retry next run", fpath)
            return None, None

        logging.info("[IMPORT] File done, status=%s [total %.3fs]: %s", row.status, time.time() - start_time, fpath)
        if time.time() - start_time > 0.25:
            logging.warning("[IMPORT] Slow import detected (%.3fs) for file: %s", time.time() - start_time, fpath)
        return new_book_id, status

    def _importing_worker(self, work_queue, importing_imported, task_id, user_id, scan_upload_path, batch_size, force, sole=False):
        """Worker thread for Phase 2: consumes row IDs from work_queue and imports each file.

        pending_fields 把 calibre 自定义列写回攒批落库（水位/批提交/尾批与异常路径
        在 finally 里兜底 flush）。
        """
        importing_session = self.scoped_session()
        importing_index = 0
        total_count = 0
        pending_fields = {"dynamic_cover": [], "translators": {}, "category": {}}

        try:
            while True:
                row_id = work_queue.get()
                try:
                    if row_id is None:  # sentinel: Phase 1 finished
                        break
                    if ScanService.static_abort_flag:
                        # Skip all to clear the queue
                        continue

                    row = importing_session.get(ScanFile, row_id)
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

                    new_book_id, status = self._import_one_file(row, user_id, scan_upload_path, importing_session, force, sole, pending_fields)
                    if status:
                        if status in ScanService.static_status_cnt:
                            ScanService.static_status_cnt[status] += 1
                        else:
                            ScanService.static_status_cnt[status] = 1

                    if new_book_id is not None:
                        importing_imported.append(new_book_id)

                    if importing_index % batch_size == 0:
                        # 行已在 _import_one_file 内逐行落库，此处只是安全网（正常无 pending）。
                        try:
                            importing_session.commit()
                            logging.info("[IMPORT] Batch committed at index %d", importing_index)
                        except Exception as err:
                            logging.error("[IMPORT] Batch commit error: %s", err)
                            importing_session.rollback()
                        self._flush_pending_calibre_fields(pending_fields)
                finally:
                    work_queue.task_done()
        except Exception as err:
            logging.error("[IMPORT] Fatal error in worker: %s", err)
            logging.error(traceback.format_exc())
        finally:
            try:
                self._flush_pending_calibre_fields(pending_fields)
            except Exception as err:
                logging.error("[IMPORT] Final fields flush error: %s", err)
            try:
                importing_session.commit()
                logging.info("[IMPORT] Final commit completed")
            except Exception as err:
                logging.error("[IMPORT] Final commit error: %s", err)
                try:
                    importing_session.rollback()
                except Exception:
                    pass
            try:
                self.scoped_session.remove()
            except Exception:
                pass

    def _scan_one_file(self, fpath, session, import_id, processed_paths, processed_hashes, force, staged=None):
        """
            Phase scanning: 处理单个文件：计算哈希，去重，创建/更新 READY 状态的 ScanFile 记录。

            staged 为 None 时走旧的立即落库（逐行 commit，兼容直接调用）；传入 list 时
            只做读（去重查询）与算（哈希 IO），写操作以描述符暂存：
            ("del_path", fpath) | ("del_hash", hash) | ("save", row, state)，
            由调用方攒批后经 _apply_phase1_batch 在短写事务内统一执行。
            读算阶段不持有任何写事务（SELECT 自身的只读快照在 WAL 下不阻塞写者），
            可横跨任意时长磁盘 IO 而不阻塞 worker 的并发写。
            返回 (None, state)：行 id 在批量 flush 后才分配，由 applier 回报。
        """
        if not os.path.isfile(fpath):
            logging.warning("[SCAN] Not a valid file, skip: %s", fpath)
            return None, None
        if not os.access(fpath, os.R_OK):
            # 文件在但读不了（chmod/ACL）：落 PERMISSION 行进 union-pending，权限恢复后
            # 下轮重试——不落行的话目录快照照常提交，该路径会被剪枝永久漏掉。
            # 两类例外不落行（对齐旧预检行为，避免清不掉的残留待办）：同路径已有
            # PERMISSION 行（每轮只留一行）；已导入且书仍在书库（此时只是读不了，
            # 不该再出一条永远重试的待办）。
            logging.error("[SCAN] Permission denied: %s", fpath)
            same_rows = session.query(ScanFile).filter(ScanFile.path == fpath).all()
            imported_alive = any(
                r.status == ScanFile.IMPORTED and self._calibre_book_exists(r.book_id)
                for r in same_rows
            )
            has_perm_row = any(r.status == ScanFile.PERMISSION for r in same_rows)
            if not has_perm_row and not imported_alive:
                row = ScanFile(fpath, "", import_id)
                row.status = ScanFile.PERMISSION
                if staged is None:
                    self.save_or_rollback(row, session)
                else:
                    staged.append(("save", row, ScanFile.PERMISSION))
            return None, None if imported_alive else ScanFile.PERMISSION

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
            if r.status == ScanFile.IMPORTED and self._calibre_book_exists(r.book_id):
                logging.info("[SCAN] Already imported by path: %s", fpath)
                return None, None
            elif r.status == ScanFile.EXIST:
                logging.info("[SCAN] Found duplicated record with same path %s", fpath)
                return None, None

        # (PoxenStudio) Reuse cached hash if available (NEW/READY record from a previous interrupted run).
        # MISSED/PERMISSION: file was previously inaccessible, reprocess from scratch (no reuse).
        # 签名门：缓存哈希只在文件签名（size/mtime_ns/ctime_ns/ino一次 stat 全取）全等时
        # 复用；存量无签名行/签名任一不等/stat 失败一律重算（偏安全方向）。命中用的 stat
        # 结果直接留给行挂签，不重取——两次 stat 之间文件再变会导致（旧哈希，新签名）
        # 的永久错配。
        reuse_hash = None
        reuse_sig = None
        if not force:
            cached = next(
                (r for r in same_path_rows
                    if r.status in (ScanFile.NEW, ScanFile.READY) and r.hash and r.hash.startswith("sha256:")),
                None,
            )
            if cached is not None:
                stored_sig = cached.data.get(FILE_SIG_KEY) if isinstance(cached.data, dict) else None
                current_sig = ScanService.file_signature(fpath)
                if current_sig is not None and stored_sig == current_sig:
                    reuse_hash = cached.hash
                    reuse_sig = current_sig
                    logging.info("[SCAN] Reusing cached hash (signature match) for: %s", fpath)
                else:
                    logging.info("[SCAN] Signature changed, recompute hash for: %s", fpath)

        current_sig = None
        if reuse_hash:
            hash_val, bad_reason = reuse_hash, None
            current_sig = reuse_sig
        else:
            pre_sig = ScanService.file_signature(fpath)
            hash_val, bad_reason = self._compute_hash(fpath)
            if not bad_reason:
                # TOCTOU：哈希读盘期间文件被改写则本次哈希不可信——存空哈希 NEW 行占位，
                # 下轮重扫（状态 NEW 无复用，直接重算），不把撕裂内容的哈希入库。
                post_sig = ScanService.file_signature(fpath)
                if pre_sig is None or post_sig is None or pre_sig != post_sig:
                    logging.warning("[SCAN] File changed during hashing, defer to next run: %s", fpath)
                    torn_row = ScanFile(fpath, "", import_id)
                    torn_row.status = ScanFile.NEW
                    if post_sig is not None:
                        torn_row.data = {FILE_SIG_KEY: post_sig}
                    if staged is None:
                        self.save_or_rollback(torn_row, session)
                    else:
                        staged.append(("save", torn_row, ScanFile.NEW))
                    return None, ScanFile.NEW
                current_sig = post_sig
        if same_path_rows:
            # Delete all same path records to avoid confusion
            logging.warning("[SCAN] Found multiple records with same path %s, count: %d. Cleaning up...", fpath, len(same_path_rows))
            if staged is None:
                session.query(ScanFile).filter(ScanFile.path == fpath).delete(synchronize_session=False)
                session.flush()
            else:
                staged.append(("del_path", fpath))
            same_path_rows = []

        if bad_reason:
            row = ScanFile(fpath, "", import_id)
            row.status = bad_reason
            if staged is None:
                self.save_or_rollback(row, session)
            else:
                staged.append(("save", row, bad_reason))
            return None, bad_reason

        row = ScanFile(fpath, hash_val, import_id)
        if hash_val in processed_hashes:
            # Keep back compatibility to set unique hash.
            row.hash = hashlib.md5(fpath.encode("utf-8")).hexdigest()
            row.status = ScanFile.DROP
            if staged is None:
                self.save_or_rollback(row, session)
            else:
                staged.append(("save", row, ScanFile.DROP))
            return None, ScanFile.DROP

        processed_hashes.add(hash_val)
        processed_paths.add(real_fpath)

        # Check already imported by hash
        hash_rows = session.query(ScanFile).filter(ScanFile.hash == hash_val).all()
        for hash_row in hash_rows:
            if force:
                break
            if hash_row.status == ScanFile.IMPORTED and self._calibre_book_exists(hash_row.book_id):
                logging.info("[SCAN] Already imported by hash: %s", fpath)
                row.hash = hashlib.md5(fpath.encode("utf-8")).hexdigest()
                row.status = ScanFile.DROP
                if staged is None:
                    self.save_or_rollback(row, session)
                else:
                    staged.append(("save", row, ScanFile.DROP))
                return None, ScanFile.DROP

        if hash_rows:
            logging.info("[SCAN] Clear existing rows with same hash: %s, count: %d", hash_val, len(hash_rows))
            if staged is None:
                session.query(ScanFile).filter(
                    ScanFile.hash == hash_val, ScanFile.status != ScanFile.IMPORTED
                ).delete(synchronize_session=False)
                session.flush()
            else:
                staged.append(("del_hash", hash_val))
        row.status = ScanFile.READY
        if current_sig is not None:
            row.data = {FILE_SIG_KEY: current_sig}
        if staged is None:
            if self.save_or_rollback(row, session):
                return row.id, ScanFile.READY
            return None, None
        staged.append(("save", row, ScanFile.READY))
        return None, ScanFile.READY

    def do_import_internal(self, filelist, user_id, task_id=None, imported_id=0, force=False, sole=False):
        """
            并行执行:
            Phase Scanning: 负责遍历文件、计算哈希、去重，并将 READY 状态的 ScanFile 行 ID 放入队列；
            Phase Importing: 从队列中取出 ID，读取对应 ScanFile 行，执行元数据读取和导入操作。
        """
        import_id = int(time.time()) if imported_id == 0 else imported_id
        ScanService.static_import_id = import_id
        ScanService.static_phase1_persist_failed = False
        scan_upload_path = os.path.realpath(CONF.get("scan_upload_path", ""))
        total_count = len(filelist)
        batch_size = 20

        # 有界工作队列：Phase1 攒批提交后一次性入队可达数百 id，上界防止百万级导入
        # 常驻内存；队满时 Phase1 阻塞等待 worker 消费（天然背压，此时不持有写事务）。
        work_queue = _queue.Queue(maxsize=50)
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
        # 读算与落库分离：_scan_one_file 只做去重查询 + 哈希 IO（不持有写事务），写操作
        # 暂存后攒满 PHASE1_BATCH_SIZE 经 _apply_phase1_batch 在短写事务内统一执行。
        # 计数与入队只发生在 commit 成功后（跨会话可见性 + 丢批不虚高进度）；commit 失败
        # 整批丢弃（文件在磁盘，下轮重扫自愈）。尾批（<500）在 finally 里同样提交入队。
        # abort 时同样提交已暂存尾批——与旧逐行 commit 下“已扫行全部持久化”净效果等价。
        session = self.session
        processed_paths: set[str] = set()
        processed_hashes: set[str] = set()
        queued_count = 0
        staged: list = []

        def _commit_phase1_stage():
            nonlocal queued_count
            save_cnt = sum(1 for op in staged if op[0] == "save")
            try:
                outcomes = self._apply_phase1_batch(session, staged)
            except Exception as err:
                logging.error("[IMPORT] Phase1 batch apply error, drop %d staged ops: %s", len(staged), err)
                try:
                    session.rollback()
                except Exception:
                    pass
                staged.clear()
                ScanService.static_phase1_persist_failed = True
                return
            staged.clear()
            try:
                session.commit()
            except Exception as err:
                logging.error("[IMPORT] Phase1 batch commit error, drop %d staged rows: %s", len(outcomes), err)
                session.rollback()
                ScanService.static_phase1_persist_failed = True
                return
            if len(outcomes) < save_cnt:
                # 行级 save 被丢（如遗留 UNIQUE(hash) 约束冲突）：该文件本轮无行，
                # 置持久化失败位阻止本轮快照提交，否则这些路径会被剪枝永久漏掉。
                ScanService.static_phase1_persist_failed = True
            for rid, state in outcomes:
                if state in ScanService.static_status_cnt:
                    ScanService.static_status_cnt[state] += 1
                else:
                    ScanService.static_status_cnt[state] = 1
                # 只有 READY 行进 worker：DROP/INVALID/MISSED 等终态行只计数不导入
                # （旧逐行路径靠返回 None id 实现同一语义）。
                if rid is not None and state == ScanFile.READY:
                    self._put_work(work_queue, importing_thread, rid)
                    queued_count += 1

        put_failure = None
        try:
            for index, fpath in enumerate(filelist):
                if ScanService.static_abort_flag:
                    logging.info("[IMPORT] Aborting import during scanning phase at index %d/%d", index, total_count)
                    break
                self._scan_one_file(fpath, session, import_id, processed_paths, processed_hashes, force, staged=staged)
                if len(staged) >= PHASE1_BATCH_SIZE:
                    _commit_phase1_stage()
        finally:
            if staged:
                try:
                    _commit_phase1_stage()
                except Exception as err:
                    # 取消且 worker 不排空时 _put_work 抛错：放弃尾批投递（行已落库的
                    # 保持 READY，下轮 union-pending 重导）；不让 finally 的异常掩盖本轮收尾。
                    logging.exception("[IMPORT] Phase1 tail commit failed (cancelled?)")
                    put_failure = put_failure or err
            else:
                try:
                    session.commit()
                except Exception as err:
                    logging.error("[IMPORT] Phase1 final commit error: %s", err)
                    session.rollback()
            try:
                self._put_work(work_queue, importing_thread, None)  # sentinel: Phase 1 done
            except Exception as err:
                # worker 已死，或取消后 wedge 投不进：放弃 sentinel。已知残留形态：
                # ① worker 活着但卡死在 get() 上，泄漏为 daemon 线程，进程退出即回收；
                # ② 放弃时队列仍压着未消费的 rid，worker 脱困后（cancel 复位后不再跳过）
                #    可能继续导入这些行——与下一轮导入并发的窗口，概率极低，接受为已知限制。
                logging.error("[IMPORT] Failed to deliver sentinel; worker may linger: %s", err)
                put_failure = put_failure or err

        logging.info("[IMPORT] Phase 1 done: %d files queued. Waiting for Phase 2...", queued_count)

        # Wait for Phase 2 to finish gracefully；取消后给 worker 有界退出窗口
        # （覆盖 busy_timeout 60s 的收尾余量），卡死的 daemon 线程就地放弃。
        if ScanService.static_abort_flag:
            importing_thread.join(timeout=120)
            if importing_thread.is_alive():
                logging.error("[IMPORT] Worker did not exit after cancel; abandoning daemon thread")
        else:
            importing_thread.join()

        if put_failure is not None and not ScanService.static_abort_flag:
            # worker 意外死亡（非取消）：保持旧行为——本轮显式失败，而不是被当成功收尾。
            raise put_failure
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
