#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import logging
import re
import threading
from queue import Queue

from sqlalchemy.sql import text
from webserver.models import Message


def _ensure_scanfiles_indexes(session) -> bool:
    """为 scanfiles 建查询索引（幂等），返回是否新建了索引。

    扫描导入 Phase1 对每个文件做 path/hash 两次等值查询（ScanService._scan_one_file），
    批量上传进度轮询按 import_id 过滤（BookUploadBatchStatus）；表随已导入记录增长到
    几十万行以上后，无索引时这些查询都是全表扫，是重复全量扫描耗时的大头。
    hash 列在 talebook 血统的存量库上已带 UNIQUE 隐式索引（mybooks 模型去掉了 unique，
    但旧库的约束仍在），按"首列为 hash 的既有索引"判断避免重复建；CREATE INDEX 在大表上
    首次执行需要一次全表扫描，仅发生在版本升级后的首次启动。
    """
    existing = {}
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
    wanted = {"ix_scanfiles_path": "path", "ix_scanfiles_import_id": "import_id"}
    if not any(cols and cols[0] == "hash" for cols in existing.values()):
        wanted["ix_scanfiles_hash"] = "hash"
    changed = False
    for name, col in wanted.items():
        if name in existing:
            continue
        session.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON scanfiles ({col})"))
        changed = True
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
                need_sync_item_time, changed = self.adjust_item_table()
                reader_changed = self.adjust_reader_table()
                scanfile_changed = self.adjust_scanfile_table()
                self.adjust_readings_table()
                changed = changed or reader_changed or scanfile_changed or True  # readings index creation is idempotent but must always be committed
                if changed:
                    self.session.commit()
            except Exception as err:
                logging.warning("Failed to alter tables: %s", err)
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
    def register_service(service_func):
        name = f"{service_func.__module__}.{service_func.__qualname__}"

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
