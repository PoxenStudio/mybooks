#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import contextlib
import json
import logging
import re
import threading
from queue import Queue

from sqlalchemy.sql import text
from webserver import perf
from webserver.startup_status import upgrade_step
from webserver.models import Message


def _ensure_scanfiles_indexes(session) -> bool:
    """为 scanfiles 建查询索引（幂等），返回是否新建了索引。

    扫描导入 Phase1 对每个文件做 path/hash 两次等值查询（ScanService._scan_one_file），
    批量上传进度轮询按 import_id 过滤（BookUploadBatchStatus）；表随已导入记录增长到
    几十万行以上后，无索引时这些查询都是全表扫，是重复全量扫描耗时的大头。
    hash 列在 talebook 血统的存量库上已带 UNIQUE 隐式索引（mybooks 模型去掉了 unique，
    但旧库的约束仍在），按"首列为 hash 的既有索引"判断避免重复建；CREATE INDEX 在大表上
    首次执行需要一次全表扫描，仅发生在版本升级后的首次启动。

    status 做成 (status, import_type) 复合索引：按状态的公共查询（选择器解析、导入预检
    COUNT、批量删除、summary 的 GROUP BY）统一带电子书口径过滤（ScanService.
    ebook_scan_filter 排除有声书记录），复合索引能整段覆盖——单列 status 索引仍要逐行
    回表取 import_type。status 等值查询照样吃这个索引的最左前缀。

    调用方需保证 import_type 列已存在（adjust_scanfile_table 先 ALTER 再建索引）。

    索引只是性能优化：先提交调用方已有的变更，每个索引单独提交，失败只回滚该索引并告警，
    不能连累同一事务里其它表的补列迁移（SQLITE_FULL/BUSY 可能让 SQLite 回滚整个事务）。
    """
    session.commit()
    existing = {}
    try:
        for row in session.execute(text('PRAGMA index_list("scanfiles")')).fetchall():
            idx_name = row[1]
            # 防御性检查：索引名来自数据库目录，仍拒绝无法安全内插进 PRAGMA 的名字
            if not isinstance(idx_name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", idx_name):
                logging.warning("[DB] Skip unsafe index name on scanfiles: %r", idx_name)
                continue
            cols = [
                c[2]
                for c in session.execute(text(f'PRAGMA index_info("{idx_name}")')).fetchall()
            ]
            existing[idx_name] = cols
    except Exception as err:
        # 拿不到既有索引就无法判断旧库的 UNIQUE(hash)，宁可本次不建，下次启动再试
        logging.warning("[DB] Failed to inspect scanfiles indexes, skip creating: %s", err)
        session.rollback()
        return False
    wanted = {
        "ix_scanfiles_path": ("path",),
        "ix_scanfiles_import_id": ("import_id",),
        "ix_scanfiles_status_import_type": ("status", "import_type"),
    }
    if not any(cols and cols[0] == "hash" for cols in existing.values()):
        wanted["ix_scanfiles_hash"] = ("hash",)
    changed = False
    for name, columns in wanted.items():
        if name in existing:
            continue
        try:
            session.execute(
                text(f"CREATE INDEX IF NOT EXISTS {name} ON scanfiles ({', '.join(columns)})")
            )
            session.commit()
            changed = True
        except Exception as err:
            logging.warning("[DB] Failed to create index %s on scanfiles: %s", name, err)
            session.rollback()
    return changed


class SingletonType(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(SingletonType, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class AsyncService(metaclass=SingletonType):
    db = None
    session = None
    scoped_session = None
    running = {}  # name -> (thread, queue)
    # 常驻型服务名集合（以 heavy=False 注册）：不参与极速模式的单一大任务锁。
    # 这类服务内部循环、永不返回，参与锁会在启动后永久持锁，饿死其它后台任务。
    heavy_lock_exempt = set()

    def __init__(self):
        self.scoped_session = lambda: "no-session"

    def setup(self, calibre_db=None, scoped_session=None, need_check_db=False):
        self.db = calibre_db
        self.scoped_session = scoped_session
        self.session = scoped_session()
        need_sync_item_time = False

        # alter table as needed
        if need_check_db and self.session is not None:
            logging.info("[AsyncService] Need to check db table.")
            # Alter the item table to add a new bool column sole if it doesn't exist
            try:
                with upgrade_step("db_items"):
                    need_sync_item_time, changed = self.adjust_item_table()
                with upgrade_step("db_readers"):
                    reader_changed = self.adjust_reader_table()
                with upgrade_step("db_scanfiles"):
                    scanfile_changed = self.adjust_scanfile_table()
                with upgrade_step("db_readings"):
                    self.adjust_readings_table()
                with upgrade_step("db_booklists"):
                    self.adjust_booklist_table()
                changed = changed or reader_changed or scanfile_changed or True  # readings index creation is idempotent but must always be committed
                if changed:
                    self.session.commit()
            except Exception as err:
                logging.warning("Failed to alter tables: %s", err)
                self.session.rollback()
        if self.session is not None:
            try:
                self.ensure_readings_indexes()
                self.session.commit()
            except Exception as err:
                logging.warning("Failed to ensure readings indexes: %s", err)
                self.session.rollback()
            try:
                self.adjust_messages_table()
                self.session.commit()
            except Exception as err:
                logging.warning("Failed to adjust messages table: %s", err)
                self.session.rollback()
        # logging.info("<%s> setup: db=%s, session=%s", self, self.db, self.session)
        logging.info("AsyncService setup completed")
        return need_sync_item_time

    def adjust_item_table(self):
        result = self.session.execute(text("""
            PRAGMA table_info(items)
        """)).fetchall()
        columns = [row[1] for row in result]

        changed = False
        need_sync_item_time = False
        # Check if the 'sole' column exists, and add it if it doesn't
        if "sole" not in columns:
            self.session.execute(text("""
                ALTER TABLE items ADD COLUMN sole BOOLEAN DEFAULT FALSE
            """))
            changed = True

        # Check if the 'book_type' and 'book_count' columns exists, and add it if it doesn't
        if ("book_type" not in columns or "book_count" not in columns or "create_time" not in columns):
            if "book_type" not in columns:
                self.session.execute(text("""
                    ALTER TABLE items ADD COLUMN book_type INTEGER DEFAULT 0
                """))
                changed = True
            if "book_count" not in columns:
                self.session.execute(text("""
                    ALTER TABLE items ADD COLUMN book_count INTEGER DEFAULT 0
                """))
                changed = True
            if "create_time" not in columns:
                self.session.execute(text("""
                    ALTER TABLE items ADD COLUMN create_time DATETIME
                """))
                need_sync_item_time = True
                changed = True
        if "src_path" not in columns:
            self.session.execute(text("""
                ALTER TABLE items ADD COLUMN src_path STRING(4096) DEFAULT ''
            """))
            changed = True
        return need_sync_item_time, changed

    def adjust_reader_table(self):
        result = self.session.execute(text("""
            PRAGMA table_info(readers)
        """)).fetchall()
        columns = [row[1] for row in result]

        changed = False
        if "vipquota" not in columns:
            changed = True
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN vipquota INTEGER DEFAULT 0
            """))
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN vipexpire DATETIME
            """))

        if "read_limit" not in columns:
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN read_limit INTEGER DEFAULT 0
            """))
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN limit_categories STRING(512) DEFAULT ''
            """))
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN limit_tags STRING(512) DEFAULT ''
            """))
            changed = True

        if "podcast_token" not in columns:
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN podcast_token STRING(128) DEFAULT ''
            """))
            changed = True

        if "total_reading_seconds" not in columns:
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN total_reading_seconds INTEGER DEFAULT 0
            """))
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN download_count INTEGER DEFAULT 0
            """))
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN allow_statistic BOOLEAN DEFAULT 1
            """))
            changed = True

        if "push_count" not in columns:
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN push_count INTEGER DEFAULT 0
            """))
            changed = True

        if "show_home_recommendations" not in columns:
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN show_home_recommendations BOOLEAN DEFAULT 1
            """))
            self.session.execute(text("""
                ALTER TABLE readers ADD COLUMN allow_review BOOLEAN DEFAULT 1
            """))
            changed = True
        return changed

    def adjust_booklist_table(self):
        columns = [row[1] for row in self.session.execute(text("PRAGMA table_info(booklists)")).fetchall()]
        if columns and "guest_read" not in columns:
            self.session.execute(text("ALTER TABLE booklists ADD COLUMN guest_read BOOLEAN NOT NULL DEFAULT 0"))

    def adjust_messages_table(self):
        columns = [row[1] for row in self.session.execute(text("PRAGMA table_info(messages)")).fetchall()]
        if not columns:
            return
        if "content_hash" not in columns:
            self.session.execute(text("ALTER TABLE messages ADD COLUMN content_hash STRING(40)"))
            for msg_id, data in self.session.execute(text("SELECT id, data FROM messages")).fetchall():
                try:
                    content = json.loads(data).get("message") if isinstance(data, str) else (data or {}).get("message")
                except Exception:
                    continue
                self.session.execute(text("UPDATE messages SET content_hash=:h WHERE id=:i"), {"h": Message.hash_content(content), "i": msg_id})
        self.session.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_reader_unread_id ON messages (reader_id, unread, id)"))
        self.session.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_reader_id ON messages (reader_id, id)"))

    def adjust_readings_table(self):
        # Reading 表本身随 Base.metadata.create_all() 自动创建。
        result = self.session.execute(text("PRAGMA table_info(readings)")).fetchall()
        columns = [row[1] for row in result]
        if "date" not in columns:
            self.session.execute(text("ALTER TABLE readings ADD COLUMN date DATE"))
            # 回填历史行的 date（早期版本按 reader_id+book_id 全局一行，没有按天分桶）
            self.session.execute(text("UPDATE readings SET date = DATE(update_time) WHERE date IS NULL"))
            # 旧的部分唯一索引是 (reader_id, book_id)，与新的 (reader_id, book_id, date) 定义不同，需要重建
            self.session.execute(text("DROP INDEX IF EXISTS ux_readings_read"))

        # 部分唯一索引，支撑 action=read 的 upsert（同一 reader_id+book_id+date 只保留一行，见 §11 upsert）
        self.ensure_readings_indexes()

    def ensure_readings_indexes(self):
        if not self.session.execute(text("PRAGMA table_info(readings)")).fetchall():
            return
        self.session.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_readings_read
            ON readings (reader_id, book_id, date) WHERE action = 'read'
        """))
        self.session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_readings_reader_book_action
            ON readings (reader_id, book_id, action)
        """))
        # 支撑首页阅读统计 Banner 的按 reader_id+date 区间回补查询（见 document/Reading_Dashboard_Design.md）
        self.session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_readings_reader_date
            ON readings (reader_id, date)
        """))
        # 支撑阅读时长排行榜的"跨用户日期窗口聚合"（reading_dashboard_service._rank_seconds）：
        # date 前导 + read 部分索引，成本只与窗口内行数成正比。此前周/月档要 SCAN 全量
        # ux_readings_read（成本随全库总行数线性），"百万书"级库会在 ioloop 上同步跑出秒级冻结。
        # duration 特意不进索引——心跳 upsert 每 60s 改写 duration，放进索引等于每次心跳多一处
        # 写放大；窗口行的 rowid 回表足够便宜。
        self.session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_readings_date_read
            ON readings (date, reader_id) WHERE action = 'read'
        """))

    def adjust_scanfile_table(self):
        result = self.session.execute(text("PRAGMA table_info(scanfiles)")).fetchall()
        columns = [row[1] for row in result]
        changed = False
        if "import_type" not in columns:
            self.session.execute(text("ALTER TABLE scanfiles ADD COLUMN import_type INTEGER DEFAULT 0"))
            changed = True
        if _ensure_scanfiles_indexes(self.session):
            changed = True
        return changed

    def get_queue(self, service_name) -> Queue | None:
        if service_name in self.running:
            return self.running[service_name][1]

        matches = [
            q for key, (_, q) in self.running.items()
            if key == service_name or key.endswith("." + service_name)
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _service_key(self, service_func) -> str:
        return f"{service_func.__module__}.{service_func.__qualname__}"

    def start_service(self, service_func) -> Queue:
        name = self._service_key(service_func)
        if name in self.running:
            return self.running[name][1]

        logging.info("** Start Thread Service <%s> ** from %s", name, self.__class__.__name__)
        q = Queue()
        t = threading.Thread(target=self.loop, args=(service_func, q))
        t.name = self.__class__.__name__ + "." + service_func.__name__
        t.daemon = True
        t.start()
        self.running[name] = (t, q)
        return q

    heavy_task_lock = threading.Lock()

    def loop(self, service_func, q):
        name = self._service_key(service_func)
        while True:
            args, kwargs = q.get()
            # 在子线程中重新生成session
            self.session = AsyncService().scoped_session()
            logging.info(
                "create new session_id=%s for thread %s",
                self.session.hash_key,
                threading.current_thread().name,
            )
            logging.info("call: func=%s", name)
            try:
                use_heavy_lock = perf.lite_on("LITE_ONE_HEAVY_TASK") and name not in AsyncService.heavy_lock_exempt
                with AsyncService.heavy_task_lock if use_heavy_lock else contextlib.nullcontext():
                    service_func(self, *args, **kwargs)
            except Exception as err:
                logging.exception("run task error: %s", err)
            logging.info("end : func=%s", name)
            self.scoped_session.remove()

    # 一些常用的工具库
    def add_msg(self, user_id, status, msg):
        Message.cleanup_messages(user_id, msg)
        m = Message(user_id, status, msg)
        if m.reader_id:
            m.save()

    def remove_duplicated_messages(self, msg):
        pass

    # 注册服务
    def async_mode(self):
        """for unittest"""
        return True

    @staticmethod
    def register_function(service_func):
        name = f"{service_func.__module__}.{service_func.__qualname__}"

        def func_wrapper(ins: AsyncService, *args, **kwargs):
            s = AsyncService()
            ins.setup(s.db, s.scoped_session)
            logging.info("[FUNC ] service call %s(%s, %s)", name, args, kwargs)
            return service_func(ins, *args, **kwargs)

        return func_wrapper

    @staticmethod
    def register_service(service_func=None, *, heavy=True):
        """注册后台异步服务。

        heavy=False 用于常驻型服务（函数内部循环、永不返回）：这类服务若参与
        极速模式的单一大任务锁（LITE_ONE_HEAVY_TASK），会永久持锁并饿死其它
        后台任务，故登记为不参与该锁；普通服务保持默认 heavy=True。
        """
        if service_func is None:
            return lambda func: AsyncService.register_service(func, heavy=heavy)

        name = f"{service_func.__module__}.{service_func.__qualname__}"
        if not heavy:
            AsyncService.heavy_lock_exempt.add(name)

        def func_wrapper(ins: AsyncService, *args, **kwargs):
            s = AsyncService()
            ins.setup(s.db, s.scoped_session)

            if not s.async_mode():
                logging.debug("[FUNC ] service call %s(%s, %s)", name, args, kwargs)
                return service_func(ins, *args, **kwargs)

            logging.info("[ASYNC] service call %s", name)
            q = ins.start_service(service_func)
            q.put((args, kwargs))
            return None

        return func_wrapper
