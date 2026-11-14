#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
#
# (PoxenStudio)do_import 是扫描导入的主入口，负责协调整个两阶段流水线导入流程：
# 前置阶段：收集文件列表，创建后台任务记录，初始化状态。
#
# 阶段一（Scanning）：主线程执行（去重预检/落库；哈希 IO 可投线程池并行，
#   CONF scan_hash_workers 控制线程数，默认 4，1=串行）
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
#     持久化失败置 static_phase1_persist_failed：此后不再推进任何目录快照（增量与
#     整轮末尾都停）、不清理批量上传暂存目录——否则没落库的路径会被快照剪枝永久漏掉
#     （此前已随成功批落盘的增量快照不回滚，但其目录文件均已落行，安全）。
#   - 将 READY 行的 ID 放入有界工作队列（最大 50），自然地对阶段二施加背压。
#
# 阶段二（Importing）：独立后台线程执行
#   - 从工作队列中持续取出行 ID，加载对应 ScanFile 记录。
#   - 读取书籍元数据（calibre get_metadata），并根据标题去重：
#       * 标题已存在（电子书）→ 追加格式（add_format）。
#       * 标题不存在 → 全新导入（import_book），同时创建 Item 关联记录。
#       * DJVU/UVZ/CBZ 扫描版先校验容器，以文件名编目为底合并内嵌元数据；仅唯一同名候选才并入，多候选按新书入库。
#   - 若配置 IMPORT_CATEGORY_WITH_FOLDER=True，将文件所在上传目录的第一级子目录名
#     作为书籍分类写入自定义字段（与动态封面/译者列一样逐本 set_field 写回）。
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
import sqlite3
import stat
import tempfile
import threading
import time
import traceback
import weakref
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import or_, inspect
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
# 扫描范围：4 = 全量扫描（不忽略所有目录）——无视目录快照、全量 walk，但保留去重。
# 0 = 全量扫描（默认走目录快照增量）；1/2 为已删除的旧排除选项，发过来按 0 处理并告警。
SCAN_SCOPE_FULL_NO_SKIP = 4
LEGACY_SKIP_SCOPES = (1, 2)
# ScanFile.data 内文件签名的键：[size, mtime_ns, ctime_ns, ino]，一次 os.stat 全取。
# ctime 专防 cp -p/rsync -a 类“保 mtime 换内容”（mtime 能保住，ctime 保不住）。
FILE_SIG_KEY = "file_sig"
# 标题判重索引的批量门限：本轮待导入书目 ≥ 该值才构建运行级落盘索引（一次 O(库)
# 构建 + 每本 O(log) 点查），否则逐本走 calibre 全库扫描（每本 O(库) icu_lower）。
# 划算与否只跟批量有关（legacy 总成本≈批量×库，建索引≈库，比值≈批量），与库
# 大小无关——单本/几本上传到百万库为一次判重建索引是纯浪费。
TITLE_INDEX_MIN_BOOKS = 50
# 目录快照「本轮不可剪枝」占位：entry_count 用不可能的真实取值，使读取侧
# (mtime_ns, count) 相等比较永不成立 → 该目录每轮重新枚举。用于目录内出现
# stat 失败/悬空符号链接这类「既无法落行、又不该被剪枝」的条目（见
# _classify_scan_entry）：它们的目标将来就位不会改动本目录 mtime。
SNAPSHOT_NO_PRUNE = -1


@dataclass
class ImportOptions:
    """导入选项"""
    # 0=全量扫描(默认走目录快照增量)；3=按目录导入(显式目录，不剪枝)；
    # 4=全量扫描(无视快照、全量 walk 但保留去重)；1/2 为已删除的旧选项，按 0 处理并告警
    skip_last_dirs: int = 0
    # TRUE 时不检查重复的图书直接导入（附带无视目录快照、全量重算）
    force: bool = False
    # 调用方预先生成的批次id(如批量上传)，用于发起后立即轮询逐文件结果；0=自动生成
    import_id: int = 0
    # 导入完成/取消后需清理的暂存目录(如批量上传暂存)；仅 KEEP_UPLOAD_SOURCE_FILE=False 时删除；
    # Phase1 持久化失败时保留（快照未提交，留给下轮重扫补导）
    cleanup_dir: str = None
    # 服务端选择器 ("ready"|"filter", value)，非空时忽略 paths，由 do_import 在后台服务线程解析
    # 文件清单——绝不能在 handler 里做（百万行 .all()+stat 会冻住 ioloop，handler 只做 COUNT 预检）
    selector: tuple = None
    # 新建书籍全部设为私藏(Item.sole，仅收藏人可见)；只作用于新建 Item，命中已存在记录不受影响
    sole: bool = False


@dataclass
class ImportInternalOptions:
    """导入操作的调用链（do_import_internal/_importing_worker/_import_one_file）共享的只读上下文。
    scan_upload_path/batch_size 由 do_import_internal 在启动 worker 前一次性回填，之后全链只读。"""
    user_id: int = 1
    # 后台任务id（进度上报用）；None=未建任务
    task_id: int = None
    # 批次id；0=按时间戳自动生成
    imported_id: int = 0
    # TRUE 时不检查重复的图书直接导入（附带无视目录快照、全量重算）
    force: bool = False
    # 直接以私有书籍导入
    sole: bool = False
    scan_upload_path: str = None
    # Phase2 攒批提交窗口（行/链接每 N 本一次短写事务）
    batch_size: int = 20


class _TitleDedupIndex:
    """运行级标题判重索引：icu_lower 规范化后落盘 SQLite。

    语义与 calibre LegacyDB.books_with_same_title 逐位一致：键与查询用同一个
    calibre.utils.icu.lower 折叠 + 等值比较（icu_lower 不做 NFC/NFD 规范化，
    SQLite BINARY 比较对同码点序列与 Python str == 等价，全角/半角、组合字符
    等边界两侧行为相同）。取代 calibre 的"每次调用全库 icu_lower"线性扫描
    （百万库每次 1-2s，Phase2 最大的既有瓶颈）：构建一次 O(库)，点查 O(log)。

    可丢弃派生数据：journal_mode=OFF + synchronous=OFF 换构建速度，崩溃安全
    不需要（崩溃即丢，下轮重建）；内存只占页缓存——与已试败的 title_map
    常驻内存方案（350-700MB/百万书）的本质区别（构建期有一次 get_id_map 的
    瞬态 dict 拷贝，约几十 MB/百万书，随构建完成释放）。线程约定：仅
    Phase2 worker 线程构建/查询/回填，不加锁；close 在 join 后的主线程调用，
    连接必须 check_same_thread=False。快照窗口：索引只反映构建时刻的书库 +
    本 worker 回填，运行期间其他来源（网页上传/BookBarn 等）新增的书不可见，
    极端并发下可能漏判而重建重复书——已接受的取舍（单管理员 NAS 概率低，
    do_import 互斥保证不会与另一轮扫描叠跑）。**注意：重复书不会"下轮重扫
    自愈"**（该路径已 IMPORTED，重扫被跳过，没有再比标题的时机），需人工删书；
    只有"行留在 READY"的那类（如中断）才靠 union-pending 自愈。运行结束
    close() 销毁；weakref.finalize 兜底异常路径的临时文件清理。
    """

    def __init__(self, db):
        from calibre import force_unicode
        from calibre.utils.icu import lower as icu_lower

        self._icu_lower = icu_lower
        self._force_unicode = force_unicode
        self._conn = None
        title_map = db.new_api.get_id_map("title")
        fd, self._path = tempfile.mkstemp(prefix="scan_title_idx_", suffix=".sqlite")
        os.close(fd)  # sqlite 按路径自行打开，mkstemp 的 fd 不关会逐轮泄漏
        weakref.finalize(self, _title_index_cleanup, self._path)
        try:
            # check_same_thread=False：连接在 worker 线程创建、close 在 join 后的
            # 主线程调用；close 与 worker 无并发（join 已返回），可丢弃数据下
            # 与 lingering worker 的理论并发最坏是一次被吞的 sqlite 异常
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("CREATE TABLE t (title_lc TEXT NOT NULL, book_id INTEGER NOT NULL)")
            conn.execute("CREATE INDEX ix_title_lc ON t (title_lc)")
            conn.executemany(
                "INSERT INTO t VALUES (?, ?)",
                ((icu_lower(t), bid) for bid, t in title_map.items() if t is not None),
            )
            conn.commit()
            self._conn = conn
            self.size = len(title_map)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            try:
                os.unlink(self._path)
            except OSError:
                pass
            raise

    def lookup(self, title):
        """同名候选书 id 集合；语义与 books_with_same_title 逐位一致：守卫只看
        原始标题真假（照抄 legacy 的 if title:），**不额外过滤"折叠键为空"**——
        icu_lower 把 U+FEFF/U+FFFE 折成空串，legacy 会把空键与全库逐个比较，
        多一道 if not key 守卫会让第二本此类书漏判重建重复书。"""
        if not title:
            return set()
        key = self._icu_lower(self._force_unicode(title))
        rows = self._conn.execute("SELECT book_id FROM t WHERE title_lc = ?", (key,)).fetchall()
        return {r[0] for r in rows}

    def add(self, title, book_id):
        """运行内增量回填：import_book 新建书后调用，同批次同名书判重要能命中。

        与 lookup/构建同口径：不做"折叠键为空就跳过"的过滤（理由同 lookup）；
        title 为 None 时按 legacy 的存储侧口径取空串折叠键（get_id_map 里的标题
        恒为 str）。"""
        if book_id is None:
            return
        key = self._icu_lower(self._force_unicode(title)) if title is not None else ""
        self._conn.execute("INSERT INTO t VALUES (?, ?)", (key, book_id))
        self._conn.commit()

    def close(self):
        try:
            if self._conn is not None:
                self._conn.close()
        finally:
            self._conn = None
            try:
                os.unlink(self._path)
            except OSError:
                pass


def _title_index_cleanup(path):
    """weakref.finalize 兜底：索引对象被回收时临时文件必须消失（异常路径未走
    显式 close 也不留盘）。"""
    try:
        os.unlink(path)
    except OSError:
        pass


class ScanService(AsyncService):
    static_abort_flag = False
    # 本轮 Phase1 是否发生过持久化失败（批量 apply/commit 异常、行级 save 被丢）。
    # 置位后本轮不提交目录快照、不清理批量上传暂存目录：没落库的文件下轮按老快照
    # 全量重走自愈；若照常提交快照，这些路径会被剪枝永久漏掉（union-pending 救不了
    # 没有行的文件）。
    static_phase1_persist_failed = False
    # 运行级标题判重索引（_TitleDedupIndex）：None=未尝试，False=构建失败不再
    # 重试（回退 calibre 全库扫描），对象=可用。仅 Phase2 worker 线程读写，
    # do_import_internal 收尾销毁。
    static_title_index = None
    # 本轮待导入书目数（索引构建门限的输入），do_import_internal 每轮重置。
    static_title_index_total = 0
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

    def _title_dedup_ids(self, mi):
        """标题判重入口：批量达标时用运行级落盘索引点查（语义与 calibre
        books_with_same_title 逐位一致——同 icu_lower 折叠 + 等值比较），未达
        门限/构建失败/查询异常一律回退 calibre 全库扫描（百万库每次调用全量
        icu_lower，Phase2 最大的既有瓶颈）。索引为可丢弃派生数据，
        do_import_internal 收尾销毁。"""
        index = ScanService.static_title_index
        if index is None and ScanService.static_title_index_total >= TITLE_INDEX_MIN_BOOKS:
            try:
                index = _TitleDedupIndex(self.db)
                ScanService.static_title_index = index
                logging.info("[IMPORT] Title dedup index built for %d books", index.size)
            except Exception as err:
                # False 哨兵：构建失败本轮不再重试（每次重试都是一次全库遍历）
                ScanService.static_title_index = False
                logging.warning("[IMPORT] Title dedup index build failed, fallback to calibre scan: %s", err)
        if index:
            try:
                return index.lookup(mi.title)
            except Exception as err:
                logging.warning("[IMPORT] Title index lookup failed, fallback to calibre scan: %s", err)
        return self.db.books_with_same_title(mi)

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

    def _apply_phase2_batch(self, session, staged_ops):
        """在短写事务内执行一批 Phase2 行/链接写操作，返回对账结果。

        staged_ops 元素：("save_row", row) | ("save_item", item)，由 _import_one_file
        在 worker 内暂存；本方法逐 op SAVEPOINT 落库，持写锁窗口亚秒级。调用方负责
        commit 并按 outcomes 对账计数：
        {"saved_rows": set(row_id), "dropped_rows": set(row_id), "dropped_items": n}。

        隔离边界（实测钉住，勿轻信「单个失败只丢该操作」）：SAVEPOINT 只对「新建对象
        插入失败」成立——失败对象被 expunge，同批其余 op 照常落库（见
        test_phase2_row_isolation_on_integrity_error）。而 Phase2 生产形态是「持久行
        就地改属性」，其 ORM flush 失败会把 session 打成 deactivated，而 pysqlite 下
        SAVEPOINT 无法恢复会话语境（后续 op 只会抛 PendingRollbackError）——故本方法
        检测到失败即停手，余下 op 交由 _apply_phase2_batch_checked 整批回滚 + 计数对账：
        净效果为丢掉本批（≤batch_size 行，保持旧状态待下轮重扫自愈），绝不虚高进度。
        要做到真正的逐行隔离需把 op 改写成 Core 语句（列为后续项，见 PR 已知限制）。
        """
        outcomes = {"saved_rows": set(), "dropped_rows": set(), "dropped_items": 0}
        if not staged_ops:
            return outcomes
        self._begin_scan_batch(session)
        for op in staged_ops:
            kind, obj = op
            # id 用 inspect().identity 取：flush 失败会把 session 打成 deactivated 并
            # expire 对象，此时 getattr(obj, "id") 会触发 refresh 而抛 PendingRollbackError，
            # 把「单行被丢」升级成整批外抛。
            rid_before = None
            if kind == "save_row":
                ident = inspect(obj).identity
                rid_before = ident[0] if ident else None
            try:
                with session.begin_nested():
                    session.add(obj)
                    session.flush()
                if kind == "save_row":
                    outcomes["saved_rows"].add(obj.id)
            except Exception as err:
                if kind == "save_row":
                    logging.error("[IMPORT] Phase2 row save dropped (id=%s): %s", rid_before, err)
                    outcomes["dropped_rows"].add(rid_before)
                else:
                    logging.error("[IMPORT] Phase2 item link save dropped: %s", err)
                    outcomes["dropped_items"] += 1
                if not session.is_active:
                    logging.error("[IMPORT] Phase2 session deactivated after row failure, dropping rest of batch")
                    break
        return outcomes

    def _apply_phase2_batch_checked(self, session, staged_ops, batch_row_status):
        """_apply_phase2_batch + commit + 计数对账：被丢/整批丢的行把 worker 先行
        计入的状态数回调（净效果等价旧 save_or_rollback 失败 → (None, None) 不计数）。
        batch_row_status: row_id → status（本批暂存过的行）。操作后两个暂存容器清空。"""
        if not staged_ops:
            return

        def _uncount_all(ids):
            for rid in ids:
                status = batch_row_status.pop(rid, None)
                if status and ScanService.static_status_cnt.get(status, 0) > 0:
                    ScanService.static_status_cnt[status] -= 1

        try:
            outcomes = self._apply_phase2_batch(session, staged_ops)
        except Exception as err:
            logging.error("[IMPORT] Phase2 batch apply error, drop %d staged ops: %s", len(staged_ops), err)
            try:
                session.rollback()
            except Exception:
                pass
            _uncount_all(list(batch_row_status.keys()))
            staged_ops.clear()
            return
        staged_ops.clear()
        try:
            session.commit()
        except Exception as err:
            logging.error("[IMPORT] Phase2 batch commit error, drop %d staged rows: %s", len(batch_row_status), err)
            session.rollback()
            _uncount_all(list(batch_row_status.keys()))
            return
        if outcomes["dropped_rows"] or outcomes["dropped_items"]:
            _uncount_all(outcomes["dropped_rows"])
            if outcomes["dropped_items"]:
                logging.error("[IMPORT] Phase2 dropped %d item link(s): books exist but user link lost; restore by deleting the book and re-importing", outcomes["dropped_items"])
        batch_row_status.clear()

    def _apply_phase1_batch(self, session, staged):
        """在短写事务内执行一批 staged 写操作，返回成功落库的 [(row_id, state)]（按暂存顺序）。

        staged 元素：("del_path", fpath) | ("del_hash", hash) | ("save", row, state)，
        由 _scan_one_file 在读算阶段（无写事务、可横跨任意时长磁盘 IO）里攒出；
        本方法只做纯内存对象的 INSERT/DELETE + flush，持写锁窗口亚秒级。
        单个文件失败只丢该文件（整组 SAVEPOINT），不毒化整批；调用方负责 commit，
        commit 成功后才能计数/入队（跨会话可见性），commit 失败则整批丢弃（文件在
        磁盘，下轮重扫自愈）。

        同一文件的 op（del_path / del_hash / save）**必须同生共死**：按「以 save 收尾」
        切组，整组共用同一个 SAVEPOINT。逐 op 各自 SAVEPOINT 时，save 失败只丢自己而
        del_path/del_hash 已释放保存点随批提交——该路径在库里从此没有任何 ScanFile 行，
        union 回填也无行可并，目录快照命中即被剪枝永久漏书（旧 save_or_rollback 失败会
        session.rollback() 把同一文件的删除一并回滚，语义等价于本组的整组丢弃）。
        """
        outcomes = []
        if not staged:
            return outcomes
        self._begin_scan_batch(session)
        # _scan_finalize 每个文件的 op 序列恒为 [del_path?] [del_hash?] save，故以 save 收尾切组。
        groups = []
        buf = []
        for op in staged:
            buf.append(op)
            if op[0] == "save":
                groups.append(buf)
                buf = []
        if buf:
            groups.append(buf)
        for group in groups:
            try:
                with session.begin_nested():
                    for op in group:
                        kind = op[0]
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
                logging.error("[SCAN] Staged file op group failed, drop it: %s", err)
                continue
            except Exception:
                logging.exception("[SCAN] Staged file op group failed, drop it")
                continue
            for op in group:
                if op[0] != "save":
                    continue
                row = op[1]
                bid = "[ book-id=%s ]" % row.book_id if row.book_id else ""
                logging.info("update: status=%-5s, path=%s %s", row.status, row.path, bid)
                outcomes.append((row.id, op[2]))
        return outcomes

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
            if not ScanService.static_abort_flag and not worker_thread.is_alive():
                # 队列尚有余量时 put 会立即成功——旧实现只在 Full 分支查存活，worker 已死
                # 而队列未满时每条投递都静默成功，整轮报「成功 0 本」却不报错。取消路径
                # 不走此处（保留下面有界放弃的语义）。
                raise RuntimeError("importing worker thread exited unexpectedly")
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
    def _scan_ignore_dir_names():
        """SCAN_IGNORE_DIRS 的归一化集合：只保留合法目录名，非法/空值忽略。"""
        raw = CONF.get("SCAN_IGNORE_DIRS", [])
        if not isinstance(raw, (list, tuple, set)):
            return frozenset()
        names = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            name = item.strip()
            if not name or name in (".", ".."):
                continue
            if any(ch in name for ch in '/\\:*?"<>|') or any(ord(ch) < 32 for ch in name):
                continue
            names.add(name)
        return frozenset(names)

    @staticmethod
    def _is_ignored_scan_subpath(fpath, ignore_names, is_dir=None, real_path=None, scan_root=None):
        """路径是否位于忽略目录之下：只比对相对扫描根的目录层级名。

        扫描根本身不跳过；扫描根之外的路径（上传临时目录等）不受影响。
        """
        if not ignore_names:
            return False
        root = scan_root if scan_root is not None else CONF.get("scan_upload_path", "")
        if not root:
            return False
        try:
            root_real = os.path.realpath(root)
            real = real_path if real_path is not None else os.path.realpath(fpath)
        except (OSError, ValueError):
            return False
        if real != root_real and not real.startswith(root_real + os.sep):
            return False
        rel = os.path.relpath(real, root_real)
        if rel == ".":
            return False
        parts = rel.split(os.sep)
        if is_dir is None:
            is_dir = os.path.isdir(fpath)
        if not is_dir:
            parts = parts[:-1]
        return any(part in ignore_names for part in parts)

    @staticmethod
    def _classify_scan_entry(fpath):
        """目录条目分类，供剪枝安全判定（扫描目录里的每本书都必须能落行或被剪枝排除）：

        - 'file'   常规文件，可扫描；
        - 'skip'   确定不是常规文件（目录/设备/管道），或 scandir 列出后此刻已不存在
                   （ENOENT 且非符号链接——删除本身会 bump 目录 mtime，快照下轮自然失配）。
                   合法跳过，**不影响本目录的剪枝资格**；
        - 'unsure' stat 失败（NAS/SMB 抖动、ACL 异常）或悬空符号链接：其目标将来就位不会
                   改动本目录 mtime，若既不落清单又让快照照常提交，该条目下轮起被剪枝永久
                   漏掉（无行可被 union 回填）。调用方据此放弃本轮剪枝或落占位行。
        """
        try:
            st = os.stat(fpath)
        except OSError as err:
            if err.errno in (errno.ENOENT, errno.ENOTDIR) and not os.path.islink(fpath):
                return "skip"
            return "unsure"
        if not stat.S_ISREG(st.st_mode):
            return "skip"
        return "file"

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

    def _upsert_dir_snapshots(self, session, subset):
        """把一批目录快照行 upsert 进 session（不 commit、不 vacuum）；返回条数。"""
        now = datetime.datetime.now()
        for d, (mtime_ns, count) in subset.items():
            row = session.get(ScanDirSnapshot, ScanDirSnapshot.hash_for(d))
            if row is None:
                session.add(ScanDirSnapshot(d, mtime_ns, count))
            else:
                row.mtime_ns = mtime_ns
                row.entry_count = count
                row.update_time = now
        return len(subset)

    def _incremental_snapshot_allowed(self, scan_root):
        """增量目录快照是否允许落盘（与 _commit_dir_snapshots 同口径的门控）。

        要求：scan root 配置且是真实存在的目录；非 abort 轮；且本轮尚无 Phase1
        行丢持久化（丢行说明有文件无行，其目录一旦被剪枝将永久漏掉）。
        """
        if not CONF.get("scan_upload_path", "").strip() or not scan_root or not os.path.isdir(scan_root):
            return False
        return not (ScanService.static_abort_flag or ScanService.static_phase1_persist_failed)

    def _commit_dir_snapshots(self, session, visited, scan_root):
        """整轮成功后提交目录快照（单事务原子）：upsert 本轮到访目录 + 清掉已消失目录。

        只在整轮正常完成时调用（abort/异常路径不调）；失败回滚并告警，下轮按老快照
        重走（多干活，不漏活）。另带 abort 熔断做纵深：即使被误调，中止轮次也不落盘。
        增量提交（Phase1 中随批同事务 upsert 已完成的目录）已落盘的目录在此重复 upsert
        幂等；
        vacuum 删两类：扫描根内磁盘上已无的目录 + 已不在
        当前扫描根内的残留行（换过 scan_upload_path 的陈旧水位）。
        """
        # realpath("") = cwd（truthy），仅判 not scan_root 挡不住未配置/卷掉挂：
        # 两种情况下 vacuum 的 not under_root 会把全部快照行清空（方向安全——
        # 下轮全量重建——但纯浪费），scan_root 必须是真实存在的目录才落盘。
        # 未配置 scan_upload_path 时 realpath("") 恰是 cwd（也是目录），故先显式判空。
        if not CONF.get("scan_upload_path", "").strip() or not scan_root or not os.path.isdir(scan_root):
            logging.warning("[IMPORT] Snapshot commit skipped: scan root missing or not a directory")
            return
        if ScanService.static_abort_flag:
            logging.info("[IMPORT] Snapshot commit skipped (aborted)")
            return
        upserted = vacuumed = 0
        try:
            upserted = self._upsert_dir_snapshots(session, visited)
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
        """收集待导入文件清单，返回 (filelist, visited, file_dir)。

        use_snapshot=True 时（仅全量扫描）：自顶向下逐目录比对快照，
        mtime_ns + entry_count 双命中则跳过该目录的文件枚举（下钻永远保留——
        深层新增只 bump 直接父目录，剪下钻会漏新书）；剪枝掉的隐藏目录等不建快照
        （规则内本来就不进去）。visited 记录本轮到访过的每个目录现状，供成功后
        提交快照；剪枝只看快照，记录不分模式（显式目录同样记录，值是文件系统事实）。
        file_dir 记录每个枚举文件（fpath → 所属目录快照键 real_dirpath），供
        do_import_internal 在某目录的文件全部落库后增量提交该目录快照（崩溃恢复
        到 Phase2 时不退回全量 walk）；union-pending 并入的路径不在其中（其目录
        若是本轮剪枝目录则本就不在 visited，无需增量提交）。
        """
        if paths is None or paths == "all":
            dirs = [CONF.get("scan_upload_path", "")]
            if not dirs[0] or not os.path.isdir(dirs[0]):
                logging.warning("[IMPORT] scan_upload_path is not configured")
                return [], {}, {}
        elif isinstance(paths, str):
            dirs = [paths]
        else:
            dirs = list(paths)

        snapshots = self._load_dir_snapshots(self.session) if use_snapshot else {}
        filelist = []
        visited: dict = {}
        file_dir: dict = {}
        skipped_dirs = 0
        ignore_names = self._scan_ignore_dir_names()
        for p in dirs:
            # 归一化扫描根：尾斜杠/冗余斜杠会让下面「根一次 realpath + 后缀拼接」
            # 产生坏键（realpath 吞尾斜杠而 dirpath 切片不随——"…/imports/" 的
            # 子目录键会变成 "…/importssub"，随后被快照 vacuum 以 under_root 判定
            # 删除，增量剪枝静默失效；官方默认 scan_upload_path 即带尾斜杠）。
            # 顺带让隐藏根目录与 walk 内的隐藏目录过滤同口径。
            p = os.path.normpath(p)
            if os.path.basename(p).startswith("."):
                logging.info(f"[SCAN]Ignore {p}")
                continue
            if ScanService._is_ignored_scan_subpath(p, ignore_names):
                logging.info("[SCAN] Ignore by scan_ignore_dirs: %s", p)
                continue
            logging.info(f"[SCAN]scan {p}")
            if os.path.isfile(p):
                fmt = p.split(".")[-1].lower()
                if fmt not in SCAN_EXT:
                    continue
                filelist.append(p)
            elif os.path.isdir(p):
                # 每个扫描根只 realpath 一次，子目录快照键用拼接。os.walk 不跟随
                # 目录符号链接（followlinks=False），p 子树内每个分量都是真实目录
                # → realpath(子) ≡ realpath(根) + 后缀。逐目录 O(深度) lstat 链降为
                # O(1) 拼接：快照剪枝砍掉每文件 stat 后，逐目录 realpath（NFS/SMB
                # 上是逐分量 round-trip）成为重扫剩余成本的大头。键值与逐目录
                # realpath 逐字节相等，存量 scan_dir_snapshots 零迁移。
                root_real = os.path.realpath(p)
                for dirpath, dirnames, filenames in os.walk(p, onerror=ScanService.os_walk_error_handler):
                    if dirpath.startswith(p):
                        real_dirpath = root_real if dirpath == p else root_real + dirpath[len(p):]
                    else:
                        # 防御分支：walk 只产出 p 子树内路径，此分支不可达；万一
                        # 上游语义变化，回退逐目录 realpath 保正确性。
                        real_dirpath = os.path.realpath(dirpath)
                    # scandir 原始条目数（过滤前口径）：写读两侧必须同一定义，否则隐藏目录
                    # 增删会导致永久 miss 或永久重走。本计数含点开头条目（文件循环里再跳过）。
                    entry_count = len(dirnames) + len(filenames)
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ignore_names]
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
                    prune_ok = True
                    for fname in filenames:
                        fmt = fname.split(".")[-1].lower()
                        if not fmt or fmt not in SCAN_EXT or fname.startswith('.'):
                            continue
                        fpath = os.path.join(dirpath, fname)
                        kind = ScanService._classify_scan_entry(fpath)
                        if kind == "skip":
                            continue
                        if kind == "unsure":
                            # stat 失败/悬空符号链接：既不落清单、又不能提交快照（否则本目录
                            # 被剪枝后该路径永久漏掉）。本轮放弃本目录的剪枝资格，下轮重新枚举。
                            prune_ok = False
                            logging.warning("[SCAN] Unstable entry, keep %s unpruned this round: %s", dirpath, fpath)
                            continue
                        filelist.append(fpath)
                        file_dir[fpath] = real_dirpath
                    if dir_mtime is not None:
                        visited[real_dirpath] = (
                            dir_mtime, entry_count if prune_ok else SNAPSHOT_NO_PRUNE
                        )
            else:
                logging.warning("[SCAN] Path not found: %s", p)
        if use_snapshot:
            logging.info("[SCAN] Snapshot prune: %d dirs skipped, %d dirs visited", skipped_dirs, len(visited))
            scan_root = os.path.realpath(CONF.get("scan_upload_path", ""))
            filelist = self._union_pending_paths(filelist, scan_root)
        return filelist, visited, file_dir

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
        ignore_names = self._scan_ignore_dir_names()
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
            if ScanService._is_ignored_scan_subpath(
                p, ignore_names, is_dir=False, real_path=real, scan_root=scan_root
            ):
                continue
            seen.add(p)
            filelist.append(p)
            added += 1
        if added:
            logging.info("[IMPORT] Pending union: %d stalled records re-queued", added)
        return filelist

    @AsyncService.register_service
    def do_import(self, paths, user_id, options=None):
        """
            paths: 目录/文件列表，或 "all"（配合 options.selector 时可为任意占位）
            options: 导入选项，各字段含义见 ImportOptions 定义
        """
        if options is None:
            options = ImportOptions()
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

        imported_id = options.import_id
        options.skip_last_dirs = self._normalize_scope(options.skip_last_dirs)

        if options.selector is not None:
            sel_kind, sel_value = options.selector
            if sel_kind == "ready":
                paths = self.resolve_ready_paths(self.session)
            else:
                paths = self.resolve_filter_paths(self.session, sel_value)

        # 快照剪枝只走全量作用域（细则见 _snapshot_active）。
        use_snapshot = ScanService._snapshot_active(paths, options.force, options.skip_last_dirs)
        if use_snapshot and CONF.get("SCAN_REPLACE_SAME_TITLE", False):
            # 原地修改文件内容不会 bump 父目录 mtime（目录快照命中 → 整个目录文件被跳过），
            # 要识别「同名但内容已变」必须每轮实际枚举文件并比对签名，因此关闭快照剪枝。
            use_snapshot = False
            logging.info(
                "[SCAN] SCAN_REPLACE_SAME_TITLE enabled, bypass dir snapshot pruning "
                "to detect modified files"
            )
        filelist, visited, file_dir = self._collect_files(paths, use_snapshot=use_snapshot)
        logging.info("[IMPORT] Collected %d files in %.3f seconds (skip_last_dirs=%d)", len(filelist), time.time() - start_time, options.skip_last_dirs)
        if not filelist:
            # 选择器模式下 paths 是全量解析结果（百万行时单条日志上百 MB），只记条数
            candidates = paths if isinstance(paths, str) else "%d paths" % len(paths or [])
            logging.warning("[IMPORT] No valid files found in: %s", candidates)
            if options.selector is not None:
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
            if options.cleanup_dir and not CONF.get("KEEP_UPLOAD_SOURCE_FILE", False):
                shutil.rmtree(options.cleanup_dir, ignore_errors=True)
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
            internal_opts = ImportInternalOptions(user_id=user_id, task_id=task_id, imported_id=imported_id, force=options.force, sole=options.sole)
            self.do_import_internal(filelist, visited=visited, file_dir=file_dir, opts=internal_opts)
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
                # 整轮末尾的快照兜底提交：upsert visited 全集 + vacuum 已消失目录。
                # 注意快照并非只在此提交——Phase1 中某目录全部文件落库后，其快照已随批
                # 同事务增量落盘（崩溃落在 Phase2 也能下轮剪枝）。此处 abort/异常路径不调，
                # 下轮按老快照重走（多干活，不漏活）；Phase1 持久化失败同样不提交：失败批次
                # 没落库的文件会被快照剪枝永久漏掉。
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
            if options.cleanup_dir and not CONF.get("KEEP_UPLOAD_SOURCE_FILE", False):
                if ScanService.static_phase1_persist_failed:
                    # 暂存目录在 scan_upload_path 下且本轮快照未提交：保留给下轮重扫补导，
                    # 删了就没源文件可自愈了（补导成功后由管理员按需清理）。
                    logging.warning(
                        "[IMPORT] Phase1 persistence failures detected, keep staging dir: %s", options.cleanup_dir
                    )
                else:
                    logging.info("[IMPORT] Cleaning up staging dir: %s", options.cleanup_dir)
                    shutil.rmtree(options.cleanup_dir, ignore_errors=True)
        ScanService.static_is_importing = False
        ScanService.static_abort_flag = False
        # static_phase1_persist_failed 有意不在此复位：失败轮结束后保持 True 直到下一轮
        # do_import/do_import_internal 开头的复位点（读取点都在复位之后，无陈旧读）。
        ScanService.static_import_user_id = 0
        logging.info("[IMPORT] Finished importing task, imported %d files, cost: %.3f seconds", ScanService.static_import_files_cnt, time.time() - start_time)

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

    def _scan_files_same_content(self, target_path, source_path, source_hash):
        """书库文件与待导入文件内容比对：先属性签名，再大小，最后哈希。

        True=相同，False=不同；无法安全判定（stat/哈希失败）返回 None，
        调用方按“不替换”保守处理，避免误覆盖书库文件。
        """
        if not target_path or not os.path.isfile(target_path):
            return False
        target_sig = ScanService.file_signature(target_path)
        source_sig = ScanService.file_signature(source_path)
        if target_sig is None or source_sig is None:
            return None
        if target_sig == source_sig:
            return True
        if target_sig[0] != source_sig[0]:
            return False
        target_hash, bad_reason = self._compute_hash(target_path)
        if bad_reason or not target_hash:
            return None
        return target_hash == source_hash

    def _import_one_file(self, row, session, staged_ops=None, opts=None):
        """
            Read metadata and import one READY ScanFile into calibre.

            Handles all error paths internally (sets row.status, calls save_or_rollback).
            Returns book_id if a new book was successfully linked via Item, else None.

            staged_ops: worker 内累积的 ("save_row", row) | ("save_item", item) 暂存，
                为 None 时行/链接走旧的逐条 commit（save_or_rollback/item.save）；
                提供时写操作全部暂存，由 worker 攒批经 _apply_phase2_batch 在短写
                事务内统一落库（2-3 次 fsync/本 → ≤1 次/批）。暂存路径下返回的
                status 是乐观值，落库失败由调用方按 outcomes 对账回调。
        """
        if opts is None:
            opts = ImportInternalOptions()
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
            if staged_ops is None:
                self.save_or_rollback(row, session)
            else:
                staged_ops.append(("save_row", row))
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
                if staged_ops is None:
                    self.save_or_rollback(row, session)
                else:
                    staged_ops.append(("save_row", row))
                return None, ScanFile.INVALID

            if mi is not None and mi.title and mi.title == CALIBRE_ERROR_FLAG:
                # PDF加密导致元数据读取失败，后续会用文件名做标题，作者佚名；其他格式则直接视为无效文件
                if fmt == "pdf":
                    mi = None
                else:
                    logging.error("[IMPORT] Failed to get metadata for %s", fpath)
                    row.status = ScanFile.INVALID
                    row.title = None
                    if staged_ops is None:
                        self.save_or_rollback(row, session)
                    else:
                        staged_ops.append(("save_row", row))
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
            if opts.force or CONF.get("UPLOAD_IGNORE_TITLE_CHECKING", False):
                ids = []
            else:
                ids = self._title_dedup_ids(mi)
                logging.info("[IMPORT] Same title %d book(s) for: %s", len(ids) if ids else 0, fpath)
            if ids and fmt in SCANNED_DOCUMENT_FORMATS and len(ids) > 1:
                # 扫描版无可信作者元数据：多个同名候选一律按新书入库，避免误并。
                # 注意入口差异（有意保留）：此处沿用 TXT 先例不校验作者，唯一同名候选即并入；
                # 网页上传/分片路径（book.py）则要求作者匹配才并入。
                logging.info("[IMPORT] %d same-title candidates for scanned document, import as new book", len(ids))
                ids = []
            existed_ebook = False
            replaced_ebook = False
            if ids:
                row.book_id = 0
                for bid in ids:
                    b = self.db.get_metadata(bid, index_is_id=True, get_user_categories=False)
                    if b.get(CALIBRE_COLUMN_BOOK_TYPE, BOOK_TYPE_EBOOK) == BOOK_TYPE_PHYSICAL:
                        continue
                    existed_ebook = True
                    row.book_id = bid
                    if b.formats and fmt.upper() in b.formats:
                        if not CONF.get("SCAN_REPLACE_SAME_TITLE", False):
                            row.status = ScanFile.EXIST
                            break
                        target_path = self.db.format_abspath(bid, fmt.upper(), index_is_id=True)
                        same_content = self._scan_files_same_content(target_path, fpath, row.hash)
                        if same_content is False:
                            logging.info(
                                "[IMPORT] Replace existing %s file for book %d with different file: %s",
                                fmt.upper(), bid, fpath,
                            )
                            self.db.add_format(bid, fmt.upper(), fpath, True)
                            row.status = ScanFile.IMPORTED
                            replaced_ebook = True
                        else:
                            if same_content is None:
                                logging.warning(
                                    "[IMPORT] Cannot compare existing %s file for book %d, keep it: %s",
                                    fmt.upper(), bid, fpath,
                                )
                            row.status = ScanFile.EXIST
                        break
                if existed_ebook and not replaced_ebook and row.status != ScanFile.EXIST:
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
                    idx = ScanService.static_title_index
                    if idx:
                        # 运行内增量回填：本批后导入的同名书判重要能命中新书。
                        # best-effort：书已在 calibre，回填失败只丢加速不丢书，
                        # 不能让异常把已成功的导入打成 INVALID；降级置 False
                        # 防止条目缺失导致同批同名漏判重、重复建书
                        try:
                            idx.add(mi.title, row.book_id)
                        except Exception as err:
                            logging.warning("[IMPORT] Title index add failed for book_id=%s: %s", row.book_id, err)
                            try:
                                idx.close()
                            except Exception:
                                pass
                            ScanService.static_title_index = False
                    if dynamic_cover:
                        self.db.new_api.set_field(CALIBRE_COLUMN_DYNAMIC_COVER, {row.book_id: 1})
                    if _translators:
                        translators = ",".join(_translators)
                        self.db.new_api.set_field(CALIBRE_COLUMN_TRANSLATORS, {row.book_id: translators})
                row.status = ScanFile.IMPORTED
                logging.info("[IMPORT] Calibre import done, book_id=%d [%.3fs]", row.book_id, time.time() - start_time)

                item = Item()
                item.book_id = row.book_id
                item.collector_id = opts.user_id
                item.sole = bool(opts.sole)
                item.src_path = fpath
                if staged_ops is None:
                    try:
                        item.save()
                        new_book_id = row.book_id
                    except Exception as err:
                        logging.error("[IMPORT] save link error: %s", err)
                else:
                    staged_ops.append(("save_item", item))
                    new_book_id = row.book_id

                if CONF.get("IMPORT_CATEGORY_WITH_FOLDER", False):
                    rel = os.path.relpath(os.path.realpath(fpath), opts.scan_upload_path)
                    first_dir = rel.split(os.sep, maxsplit=1)[0] if os.sep in rel else ""
                    if first_dir and first_dir != ".." and len(first_dir) < 10 and not any(c in first_dir for c in ',:;|/\\\'"\t '):
                        try:
                            self.db.new_api.set_field(CALIBRE_COLUMN_CATEGORY, {row.book_id: first_dir})
                            logging.info("[IMPORT] Set category '%s' for book_id=%d", first_dir, row.book_id)
                        except Exception as cat_err:
                            logging.warning("[IMPORT] Failed to set category for book_id=%d: %s", row.book_id, cat_err)
                    else:
                        logging.warning("[IMPORT] Skipping category for '%s': invalid dir name", first_dir)

            if CONF.get("REMOVE_IMPORTED_FILE", False) and (
                not existed_ebook or row.status == ScanFile.EXIST or replaced_ebook
            ):
                self._remove_imported_file(fpath)
        except Exception as err:
            new_book_id = None
            row.status = ScanFile.INVALID
            logging.error("[IMPORT] Failed to process file %s: %s", fpath, err)
            logging.error(traceback.format_exc())

        status = row.status
        # 行落库失败必须诚实返回 (None, None)（旧逐行路径）：worker 据此跳过计数/
        # 入库名单，避免“已计数但未持久化”的虚假成功；行保持旧状态，下轮重扫经
        # 标题命中收敛自愈。批量路径先乐观计数，落库失败由 worker 按 outcomes 回调。
        if staged_ops is None:
            if not self.save_or_rollback(row, session):
                logging.error("[IMPORT] Failed to save ScanFile record for %s, will retry next run", fpath)
                return None, None
        else:
            staged_ops.append(("save_row", row))

        logging.info("[IMPORT] File done, status=%s [total %.3fs]: %s", row.status, time.time() - start_time, fpath)
        if time.time() - start_time > 0.25:
            logging.warning("[IMPORT] Slow import detected (%.3fs) for file: %s", time.time() - start_time, fpath)
        return new_book_id, status

    def _importing_worker(self, work_queue, importing_imported, opts):
        """Worker thread for Phase 2: consumes row IDs from work_queue and imports each file.

        行/Item 链接写走 staged_ops 攒批（每 batch_size 本
        一个短写事务 + 计数对账，尾批与异常路径 finally 兜底）——旧逐条 commit
        （2-3 次 fsync/本）降为 ≤1 次/批。
        """
        importing_session = self.scoped_session()
        # 行写只允许在 _apply_phase2_batch 的批边界 SAVEPOINT 内 flush。全局 session 是
        # autoflush=True，若放任：worker 每轮开头的 importing_session.get() 会把上一本改
        # 脏的行刷出去，驱动层写事务就此打开并一直持有到每 batch_size 本一次的批提交——
        # 一次写事务横跨整批的元数据读取/import_book 磁盘 IO，正是 Phase1 修掉的那类反
        # 模式；NAS 上批量慢于 busy_timeout 时与 Phase1 批提交双写撞锁（最多丢整批 500 行
        # + 本轮停推快照 → 下轮重扫；已完成目录若已随早前成功批落盘增量快照则可部分剪枝）。
        importing_session.autoflush = False
        importing_index = 0
        total_count = 0
        staged_ops = []       # ("save_row", row) | ("save_item", item)，本批待落库
        batch_row_status = {}  # row_id → status，落库对账用（本批暂存过的行）

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
                    logging.info("[IMPORT] [TASK:%d] Processing [%d]: %s", opts.task_id, importing_index, row.path)
                    if opts.task_id and importing_index % 10 == 0:
                        status = ScanService.status_count()
                        all_values_sum = sum(status.values())
                        total_count = all_values_sum - status.get(ScanFile.IMPORTED, 0) - status.get(ScanFile.EXIST, 0)
                        processed = all_values_sum - status.get(ScanFile.READY, 0)
                        try:
                            BackgroundService().update_progress(
                                task_id=opts.task_id,
                                progress=min(99, int(processed * 100 / total_count)),
                                progress_data={"stage": "importing", "total": total_count, "imported": processed}
                            )
                        except Exception as e:
                            logging.error("[IMPORT] Failed to update progress: %s", e)

                    new_book_id, status = self._import_one_file(row, importing_session, staged_ops, opts)
                    if status:
                        if status in ScanService.static_status_cnt:
                            ScanService.static_status_cnt[status] += 1
                        else:
                            ScanService.static_status_cnt[status] = 1
                        if row.id is not None:
                            batch_row_status[row.id] = status

                    if new_book_id is not None:
                        importing_imported.append(new_book_id)

                    if importing_index % opts.batch_size == 0:
                        # 行/链接在 _import_one_file 内已暂存，此处短写事务统一落库
                        # 并按 outcomes 对账（被丢行回调状态计数，净效果等价旧的
                        # save_or_rollback 失败 → (None, None) 不计数）。
                        self._apply_phase2_batch_checked(importing_session, staged_ops, batch_row_status)
                finally:
                    work_queue.task_done()
        except Exception as err:
            logging.error("[IMPORT] Fatal error in worker: %s", err)
            logging.error(traceback.format_exc())
        finally:
            # 尾批（<batch_size）与 abort/异常残留的暂存操作照常落库——与旧逐行
            # commit 下“已处理行全部持久化”净效果等价。
            try:
                self._apply_phase2_batch_checked(importing_session, staged_ops, batch_row_status)
            except Exception as err:
                logging.error("[IMPORT] Final Phase2 batch error: %s", err)
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
            Phase scanning（串行兼容入口）：处理单个文件：计算哈希，去重，创建/更新 READY 状态的 ScanFile 记录。

            staged 为 None 时走旧的立即落库（逐行 commit，兼容直接调用）；传入 list 时
            只做读（去重查询）与算（哈希 IO），写操作以描述符暂存：
            ("del_path", fpath) | ("del_hash", hash) | ("save", row, state)，
            由调用方攒批后经 _apply_phase1_batch 在短写事务内统一执行。
            本方法是 _scan_prepare → _hash_job → _scan_finalize 的同步串行组合，
            供测试与直调使用；do_import_internal 走三者拆开的并行流水线，
            finalize 顺序与串行逐位一致。
            返回 (None, state)：行 id 在批量 flush 后才分配，由 applier 回报。
        """
        ctx, state = self._scan_prepare(fpath, session, import_id, processed_paths, force, staged=staged)
        if ctx is None:
            return None, state
        result = self._hash_job(ctx)
        return self._scan_finalize(ctx, result, session, processed_paths, processed_hashes, staged=staged)

    def _scan_prepare(self, fpath, session, import_id, processed_paths, force, staged=None):
        """Phase1 前半：会话绑定的去重预检（无哈希 IO，快）。返回 (ctx, state)。

        ctx 为 None 表示终态（state=None 或 PERMISSION，PERMISSION 行已暂存）；
        否则 ctx 只携带纯数据（无 ORM 对象、无会话引用），可安全投入线程池。
        """
        if not os.path.isfile(fpath):
            # stat 失败/悬空符号链接不能静默丢弃：本路径由 _collect_files 收集而来，
            # 其目录快照本轮可能照常提交，命中剪枝后该路径永久漏掉。落 NEW 占位行进
            # union-pending（与撕裂读同路径），下轮重扫重算；真不存在则由 MISSED 终态收敛。
            if ScanService._classify_scan_entry(fpath) == "unsure":
                logging.warning("[SCAN] Unstable entry, defer to next run: %s", fpath)
                deferred = ScanFile(fpath, "", import_id)
                deferred.status = ScanFile.NEW
                if staged is None:
                    self.save_or_rollback(deferred, session)
                else:
                    staged.append(("save", deferred, ScanFile.NEW))
                return None, ScanFile.NEW
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
        reimport_row = None
        replace_same_title = bool(CONF.get("SCAN_REPLACE_SAME_TITLE", False))
        for r in same_path_rows:
            if force:
                break
            if r.status == ScanFile.IMPORTED and self._calibre_book_exists(r.book_id):
                if not replace_same_title:
                    logging.info("[SCAN] Already imported by path: %s", fpath)
                    return None, None
                stored_sig = r.data.get(FILE_SIG_KEY) if isinstance(r.data, dict) else None
                current_sig = ScanService.file_signature(fpath)
                if current_sig is None or current_sig == stored_sig:
                    # stat 失败（瞬时不可达）沿用旧行为保留记录，避免误判为缺失；
                    # 签名一致则确定未变化。
                    logging.info("[SCAN] Already imported by path and unchanged: %s", fpath)
                    return None, None
                logging.info("[SCAN] Already imported by path but file changed, re-evaluate: %s", fpath)
                reimport_row = r
            elif r.status == ScanFile.EXIST:
                logging.info("[SCAN] Found duplicated record with same path %s", fpath)
                return None, None

        # (PoxenStudio) Reuse cached hash if available (NEW/READY record from a previous interrupted run).
        # MISSED/PERMISSION: file was previously inaccessible, reprocess from scratch (no reuse).
        # 这里只选复用候选；签名 stat 与比对属于哈希 IO 段，放 _hash_job（并行化后不占主线程）。
        reuse_hash = None
        reuse_stored_sig = None
        if not force:
            cached = next(
                (r for r in same_path_rows
                    if r.status in (ScanFile.NEW, ScanFile.READY) and r.hash and r.hash.startswith("sha256:")),
                None,
            )
            if cached is not None:
                reuse_hash = cached.hash
                reuse_stored_sig = cached.data.get(FILE_SIG_KEY) if isinstance(cached.data, dict) else None
        return {
            "fpath": fpath,
            "import_id": import_id,
            "force": force,
            "real_fpath": real_fpath,
            "stale_rows": len(same_path_rows),
            "reuse_hash": reuse_hash,
            "reuse_stored_sig": reuse_stored_sig,
            "reimport_row_id": reimport_row.id if reimport_row is not None else None,
            "reimport_hash": reimport_row.hash if reimport_row is not None else None,
        }, None

    def _hash_job(self, ctx):
        """Phase1 中段：纯文件系统 IO（签名 stat + 哈希 + TOCTOU 复核），无会话无
        ORM，线程池安全；返回 {"hash","bad_reason","sig"} 或 {"torn","post_sig"}。

        签名门：缓存哈希只在文件签名（size/mtime_ns/ctime_ns/ino一次 stat 全取）
        全等时复用；存量无签名行/签名任一不等/stat 失败一律重算（偏安全方向）。
        命中用的 stat 结果直接留给行挂签，不重取——两次 stat 之间文件再变会导致
        （旧哈希，新签名）的永久错配。
        """
        fpath = ctx["fpath"]
        if ctx["reuse_hash"]:
            current_sig = ScanService.file_signature(fpath)
            if current_sig is not None and ctx["reuse_stored_sig"] == current_sig:
                logging.info("[SCAN] Reusing cached hash (signature match) for: %s", fpath)
                return {"hash": ctx["reuse_hash"], "bad_reason": None, "sig": current_sig}
            logging.info("[SCAN] Signature changed, recompute hash for: %s", fpath)
        pre_sig = ScanService.file_signature(fpath)
        hash_val, bad_reason = self._compute_hash(fpath)
        if bad_reason:
            return {"hash": None, "bad_reason": bad_reason, "sig": None}
        # TOCTOU：哈希读盘期间文件被改写则本次哈希不可信——交由 finalize 存空哈希
        # NEW 行占位，下轮重扫（状态 NEW 无复用，直接重算），不把撕裂内容的哈希入库。
        post_sig = ScanService.file_signature(fpath)
        if pre_sig is None or post_sig is None or pre_sig != post_sig:
            return {"torn": True, "post_sig": post_sig}
        return {"hash": hash_val, "bad_reason": None, "sig": post_sig}

    def _scan_finalize(self, ctx, result, session, processed_paths, processed_hashes, staged=None):
        """Phase1 后半：主线程按提交序消费哈希结果，落终态/READY 行（全部写操作走
        staged 描述符或旧逐行落库）。返回 (rid, state)，语义与旧 _scan_one_file 相同。"""
        fpath = ctx["fpath"]
        import_id = ctx["import_id"]
        force = ctx["force"]
        if result.get("torn"):
            logging.warning("[SCAN] File changed during hashing, defer to next run: %s", fpath)
            torn_row = ScanFile(fpath, "", import_id)
            torn_row.status = ScanFile.NEW
            post_sig = result.get("post_sig")
            if post_sig is not None:
                torn_row.data = {FILE_SIG_KEY: post_sig}
            if staged is None:
                self.save_or_rollback(torn_row, session)
            else:
                staged.append(("save", torn_row, ScanFile.NEW))
            return None, ScanFile.NEW
        hash_val = result.get("hash")
        bad_reason = result.get("bad_reason")
        current_sig = result.get("sig")
        reimport_row_id = ctx.get("reimport_row_id")
        reimport_hash = ctx.get("reimport_hash")
        if (reimport_row_id and reimport_hash and hash_val and hash_val == reimport_hash
                and current_sig is not None):
            # 已导入文件仅属性变化（如 touch/cp -p），内容哈希未变：保留原行并更新签名，
            # 不再重复比对/替换书库文件。
            old_row = session.get(ScanFile, reimport_row_id)
            if old_row is not None and old_row.status == ScanFile.IMPORTED:
                data = dict(old_row.data) if isinstance(old_row.data, dict) else {}
                data[FILE_SIG_KEY] = current_sig
                old_row.data = data
                if staged is None:
                    self.save_or_rollback(old_row, session)
                else:
                    staged.append(("save", old_row, old_row.status))
                logging.info("[SCAN] File attributes changed but content identical, update signature: %s", fpath)
                return None, None
        if ctx["stale_rows"]:
            # Delete all same path records to avoid confusion
            logging.warning("[SCAN] Clean up stale records with same path %s, count: %d", fpath, ctx["stale_rows"])
            if staged is None:
                session.query(ScanFile).filter(ScanFile.path == fpath).delete(synchronize_session=False)
                session.flush()
            else:
                staged.append(("del_path", fpath))

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
        processed_paths.add(ctx["real_fpath"])

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

    def do_import_internal(self, filelist, visited=None, file_dir=None, opts=None):
        """
            并行执行:
            Phase Scanning: 负责遍历文件、计算哈希、去重，并将 READY 状态的 ScanFile 行 ID 放入队列；
            Phase Importing: 从队列中取出 ID，读取对应 ScanFile 行，执行元数据读取和导入操作。

            visited / file_dir: 由调用方 do_import 从 _collect_files 透传的目录快照与
                文件→目录映射（直接调用本方法时可为 None）。提供时在 Phase1 中按目录
                增量提交快照，使崩溃/重启落在 Phase2 时下轮仍能剪枝。
            opts: 导入上下文（ImportInternalOptions），字段含义见其定义
        """
        if opts is None:
            opts = ImportInternalOptions()
        import_id = int(time.time()) if opts.imported_id == 0 else opts.imported_id
        ScanService.static_import_id = import_id
        ScanService.static_phase1_persist_failed = False
        ScanService.static_title_index = None
        opts.scan_upload_path = os.path.realpath(CONF.get("scan_upload_path", ""))
        # 同一路径在 filelist 里出现两次时（库里同路径多行——force 重导会留下 IMPORTED+READY
        # 两行，而 resolve_ready_paths/resolve_filter_paths 都不去重，手动勾选的原样透传）：
        # 串行分支必跳过第二次（prepare+finalize 是同一次调用，processed_paths 在第二次
        # prepare 前已登记），并行分支的 prepare 却发生在收割之前（登记只在 _scan_finalize），
        # 第二条照样过检查 → 多算一次哈希，并可能多落一条 DROP 记录，或让「清同哈希行再建
        # READY」这条路径把同一文件重复入队。入口按原字符串保序去重（不引入逐文件 realpath，
        # 热路径不增 syscall）即可让两分支严格等价——去重掉的正是串行本来就会跳过的那部分；
        # 残留的「同一文件但字符串不同」形态（符号链接变体）仍由 _scan_prepare 的 realpath 检查兜底。
        # 注：调用方 do_import 的 static_import_files_cnt 仍按去重前长度计（保持既有消息口径）。
        if len(filelist) > 1:
            filelist = list(dict.fromkeys(filelist))
        total_count = len(filelist)
        ScanService.static_title_index_total = total_count
        opts.batch_size = 20

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
            args=(work_queue, importing_imported, opts),
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

        # 增量目录快照：某目录下的全部文件在 Phase1 落库后即可提交该目录快照，使崩溃/
        # 重启落在 Phase2（import_book，最耗时那段）时下轮仍能剪枝，不再全量 walk。
        # dir_remaining 记录每个目录在 filelist 中尚未走完 Phase1 的文件数；pending_snapshots
        # 收集「已完成」目录，随 Phase1 批提交一并落盘（只在零丢行时提交，保证剪枝目录
        # 的每个文件都有行，可被 union-pending 并回）。
        dir_remaining: dict = {}
        pending_snapshots: dict = {}
        if visited and file_dir:
            for _fp in filelist:
                _d = file_dir.get(_fp)
                if _d is not None:
                    dir_remaining[_d] = dir_remaining.get(_d, 0) + 1

        def _note_dir_complete(fpath):
            d = file_dir.get(fpath) if file_dir else None
            if d is None:
                return
            rem = dir_remaining.get(d)
            if rem is None:
                return
            rem -= 1
            if rem <= 0:
                dir_remaining.pop(d, None)
                snap = visited.get(d)
                if snap is not None:
                    pending_snapshots[d] = snap
            else:
                dir_remaining[d] = rem

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
                pending_snapshots.clear()
                return
            staged.clear()
            if len(outcomes) < save_cnt:
                # 行级 save 被丢（如遗留 UNIQUE(hash) 约束冲突）：该文件本轮无行，
                # 置持久化失败位阻止本轮增量快照提交，否则这些路径会被剪枝永久漏掉。
                ScanService.static_phase1_persist_failed = True
                pending_snapshots.clear()
            elif pending_snapshots:
                # 零丢行：把已走完 Phase1 的目录快照与本批行**同事务** upsert（省一次写
                # 事务/写锁获取）。pending 里的目录其每个文件都已落库或正在本批落库，
                # 与行同事务提交即原子；upsert 失败只放弃本批增量（行照常提交，下轮重走）。
                if self._incremental_snapshot_allowed(opts.scan_upload_path):
                    try:
                        n = self._upsert_dir_snapshots(session, pending_snapshots)
                        logging.info("[IMPORT] Snapshot incremental upsert: %d dirs (same txn)", n)
                    except Exception as err:
                        # 不 rollback：本批行在同一事务里，回滚会连行一起丢。已 upsert 的
                        # 部分快照随下面的 commit 落盘也是安全的——pending 里的目录其文件
                        # 必有行（丢行分支已提前清空 pending），快照语义是"该目录本轮已到
                        # 终态"，与逐目录全有/全无无关。
                        logging.error("[IMPORT] Snapshot incremental upsert failed (skip this batch): %s", err)
                pending_snapshots.clear()
            try:
                session.commit()
            except Exception as err:
                logging.error("[IMPORT] Phase1 batch commit error, drop %d staged rows: %s", len(outcomes), err)
                session.rollback()
                ScanService.static_phase1_persist_failed = True
                return
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

        # 并行哈希流水线：prepare（主线程，会话绑定）→ _hash_job（线程池，纯 IO）
        # → finalize（主线程，按提交序收割）。收割严格按 filelist 序，processed_
        # hashes/路径去重/DROP/批边界与串行逐位等价；scan_hash_workers=1 时完全
        # 退化为串行直算（零线程开销，NAS 机械盘兜底）。
        # 提交窗口封顶：百万级 filelist 的未收割 future 不能常驻内存，超窗按提交序
        # 阻塞收割队头（天然背压）。线程池线程非 daemon：进程退出时若有哈希卡在
        # 病态文件系统上会等它——旧串行路径同位置同样卡，接受为已知取舍。
        # 解析绝不外抛：此时 importing_thread 已启动，异常外抛会泄漏挂在 get()
        # 上的 daemon worker 与 scoped session（对齐 _normalize_scope 的同款取舍）；
        # auto.py 手写脏值回退默认 4
        try:
            hash_workers = max(1, int(CONF.get("scan_hash_workers", 4) or 1))
        except (TypeError, ValueError, OverflowError):
            # auto.py 手写脏值（如 1e400 == inf）int() 会抛 OverflowError，与 TypeError/
            # ValueError 同口径回退；漏掉会在 sentinel 的 try/finally 之前外抛，泄漏挂在
            # queue.get() 上的 daemon worker（对齐 _normalize_scope 的捕获集合）。
            logging.warning("[IMPORT] Invalid scan_hash_workers value, fallback to 4")
            hash_workers = 4
        hash_pool = None
        if hash_workers > 1:
            hash_pool = ThreadPoolExecutor(max_workers=hash_workers, thread_name_prefix="scan_hash")
        submit_window = max(8, hash_workers * 4)
        pending = deque()  # (ctx, future)，按提交序收割

        def _drain_one(block):
            if not pending:
                return
            if not block and not pending[0][1].done():
                return
            ctx, fut = pending.popleft()
            result = fut.result()  # 线程内未预期异常在主线程重抛（与串行同语义）
            self._scan_finalize(ctx, result, session, processed_paths, processed_hashes, staged=staged)
            _note_dir_complete(ctx["fpath"])
            if len(staged) >= PHASE1_BATCH_SIZE:
                _commit_phase1_stage()

        put_failure = None
        try:
            for index, fpath in enumerate(filelist):
                if ScanService.static_abort_flag:
                    logging.info("[IMPORT] Aborting import during scanning phase at index %d/%d", index, total_count)
                    break
                ctx, _state = self._scan_prepare(fpath, session, import_id, processed_paths, opts.force, staged=staged)
                if ctx is None:
                    # 终态（跳过或 PERMISSION 行已暂存），批提交水位照查
                    _note_dir_complete(fpath)
                    if len(staged) >= PHASE1_BATCH_SIZE:
                        _commit_phase1_stage()
                    continue
                if hash_pool is None:
                    result = self._hash_job(ctx)
                    self._scan_finalize(ctx, result, session, processed_paths, processed_hashes, staged=staged)
                    _note_dir_complete(fpath)
                    if len(staged) >= PHASE1_BATCH_SIZE:
                        _commit_phase1_stage()
                    continue
                while len(pending) >= submit_window:
                    _drain_one(block=True)
                pending.append((ctx, hash_pool.submit(self._hash_job, ctx)))
                while pending and pending[0][1].done():
                    _drain_one(block=False)
            # 收尾：按提交序阻塞收割全部在途 job（abort 时同样收割——结果仍走
            # finalize 入 staged，finally 尾批统一提交；abort 不提交快照，下轮重扫）。
            while pending:
                _drain_one(block=True)
        except Exception as err:
            # Phase1 主体异常（哈希 job 重抛、_put_work 放弃等）记入 put_failure 而非直接
            # 外抛：收尾（join / 标题索引销毁 / abort 抑制）必须照常执行，否则 worker 已死
            # 或取消的场景会跳过全部收尾，把取消误报成失败、并泄漏标题索引临时文件。
            # 非取消场景在收尾后按原语义 raise（行为不变）。
            logging.exception("[IMPORT] Phase1 loop error, capturing for teardown")
            put_failure = put_failure or err
        finally:
            if hash_pool is not None:
                hash_pool.shutdown(wait=False, cancel_futures=True)
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
                    # 无尾批残留行：把尚未落盘的已完成目录快照同事务落库（正常为空，
                    # 因为每个完成目录都随其所在批次的提交一并落盘）。
                    if pending_snapshots and self._incremental_snapshot_allowed(opts.scan_upload_path):
                        self._upsert_dir_snapshots(session, pending_snapshots)
                    pending_snapshots.clear()
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

        # 标题判重索引为可丢弃派生数据：无论成败收尾即销毁（weakref.finalize 兜底
        # 异常路径——对象被回收时临时文件自动清理）。先清门限：abort 超时被放弃的
        # lingering worker 脱困后不再重建孤儿索引。
        ScanService.static_title_index_total = 0
        title_index = ScanService.static_title_index
        if title_index:
            try:
                title_index.close()
            except Exception as err:
                logging.warning("[IMPORT] Title index close failed: %s", err)
        ScanService.static_title_index = None

        if put_failure is not None and not ScanService.static_abort_flag:
            # worker 意外死亡（非取消）：保持旧行为——本轮显式失败，而不是被当成功收尾。
            raise put_failure
        logging.info("[IMPORT] Both phases done in %.3fs. Queued: %d, Imported: %d",
                     time.time() - start_time, queued_count, len(importing_imported))

        if opts.task_id:
            try:
                BackgroundService().update_progress(
                    task_id=opts.task_id,
                    progress=100,
                    progress_data={"stage": "completed", "total": queued_count, "imported": len(importing_imported)}
                )
            except Exception as e:
                logging.error("[IMPORT] Failed to update final progress: %s", e)

        if importing_imported:
            logging.info("[IMPORT] Starting auto-fill for %d imported books", len(importing_imported))
            AutoFillService().auto_fill_all(importing_imported)
            # 目录提取会顺带给含 TXT 的书生成阅读索引（skipped 的书也预热），
            # 所以这里不再单独排一遍预热 —— 否则同一本新书会被两个线程各整本扫一次
            CatalogExtractService().extract_batch(opts.user_id, importing_imported)

            # 私藏批次不发新书通知：邮件会发全站，等于把私藏书的存在与书名公开
            if CONF.get("SEND_MAIL_FOR_NEW_BOOKS", False) and not opts.sole:
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
