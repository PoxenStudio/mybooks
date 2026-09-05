#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import hashlib
import logging
import re
import time
import json
import os
import zlib
from webserver.i18n import _

from social_sqlalchemy.storage import JSONType, SQLAlchemyMixin
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.orm import relationship, declarative_base
from webserver.constants import BOOK_TYPE_EBOOK


# 阅读状态常量
READ_STATE_UNREAD = 0  # 未读
READ_STATE_READING = 1  # 在读
READ_STATE_FINISHED = 2  # 已读完

Base = declarative_base()


def mksalt():
    import random
    import string

    # for python3, just use: crypt.mksalt(crypt.METHOD_SHA512)
    saltchars = string.ascii_letters + string.digits + "./"
    salt = []
    for c in range(32):
        idx = int(random.random() * 10000) % len(saltchars)
        salt.append(saltchars[idx])
    return "".join(salt)


Base = declarative_base()


def bind_session(session):
    def _session(self):
        return session

    Base._session = classmethod(_session)
    SQLAlchemyMixin._session = classmethod(_session)
    logging.info("Bind modles._session()")


def to_dict(self):
    return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}


Base.to_dict = to_dict


class MutableDict(Mutable, dict):
    @classmethod
    def coerce(cls, key, value):
        "Convert plain dictionaries to MutableDict."
        if isinstance(value, MutableDict):
            return value
        if isinstance(value, dict):
            return MutableDict(value)
        return Mutable.coerce(key, value)

    def __setitem__(self, key, value):
        "Detect dictionary set events and emit change events."
        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key):
        "Detect dictionary del events and emit change events."
        dict.__delitem__(self, key)
        self.changed()

    def __getitem__(self, key):
        if not dict.__contains__(self, key):
            return ""
        return dict.__getitem__(self, key)


class Reader(Base, SQLAlchemyMixin):
    DEFAULT_PERMISSION = ""
    DISABLE_MANAGE = "USED"
    DISABLE_PUSH = "P"

    OVERSIZE_SHRINK_RATE = 0.8
    SQLITE_MAX_LENGTH = 32 * 1024.0

    RE_EMAIL = r"[^@]+@[^@]+\.[^@]+"
    RE_USERNAME = r"[a-z][a-z0-9_]*"
    RE_PASSWORD = r'[a-zA-Z0-9!@#$%^&*()_+\-=[\]{};\':",./<>?\|]*'

    __tablename__ = "readers"
    id = Column(Integer, primary_key=True)
    username = Column(String(200))
    password = Column(String(200), default="")
    salt = Column(String(200))
    name = Column(String(100))
    email = Column(String(200))
    avatar = Column(String(200))
    admin = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    permission = Column(String(100), default="")
    create_time = Column(DateTime)
    update_time = Column(DateTime)
    access_time = Column(DateTime)
    extra = Column(MutableDict.as_mutable(JSONType), default={})
    vipquota = Column(Integer, default=0)  # VIP用户的下载配额
    vipexpire = Column(DateTime)  # VIP用户的到期时间
    read_limit = Column(Integer, default=0)
    limit_categories = Column(String(512), default="")
    limit_tags = Column(String(512), default="")
    podcast_token = Column(String(128), default="")
    total_reading_seconds = Column(Integer, default=0, nullable=False)  # 累计阅读时长（秒），来自 Reading(action=read) 心跳累加
    download_count = Column(Integer, default=0, nullable=False)  # 累计下载次数，仅 action=download 事件
    push_count = Column(Integer, default=0, nullable=False)  # 累计推送次数，仅 action=push 事件；不回填历史数据，从功能上线时刻起累计
    allow_statistic = Column(Boolean, default=True, nullable=False)  # 是否采集该用户的阅读/下载统计，默认采集（opt-out）
    show_home_recommendations = Column(Boolean, default=True, nullable=False)  # 首页展示其他用户推荐，见 plan/Social_Reading_Plan.md
    allow_review = Column(Boolean, default=True, nullable=False)  # 是否允许发表评论（管理员可禁止）

    def __str__(self):
        return "<id=%d, username=%s, email=%s, admin:%d>" % (
            self.id,
            self.username,
            self.email,
            self.admin,
        )

    def shrink_column_extra(self):
        # Clear the unused item in the extra
        self.extra["upload_history"] = []
        self.extra["download_history"] = []
        # check whether the length of `extra` column is out of limit 32KB
        text = json.dumps(self.extra)
        shrink = min(self.OVERSIZE_SHRINK_RATE, self.SQLITE_MAX_LENGTH / len(text))
        if len(text) > self.SQLITE_MAX_LENGTH:
            for k, v in self.extra.items():
                if k.endswith("_history") and isinstance(v, list):
                    new_length = int(len(v) * shrink)
                    self.extra[k] = v[:new_length]

    def save(self):
        self.shrink_column_extra()
        result = super().save()
        from webserver.services.reader_cache import ReaderStatsCache
        ReaderStatsCache().set_allow_statistic(self.id, self.allow_statistic)
        return result

    def init_default_user(self):
        class DefaultUserInfo:
            extra_data = {"username": _("默认用户")}
            provider = ""
            uid = 123456789

        self.init(DefaultUserInfo())

    def init(self, social_user):
        self.username = self.get_social_username(social_user)
        self.create_time = datetime.datetime.now()
        self.update_time = datetime.datetime.now()
        self.access_time = datetime.datetime.now()
        self.extra = {"kindle_email": "", "allow_sending_mail": True}
        self.init_avatar(social_user)

    def reset_password(self):
        s = "%s%s%s" % (self.username, self.create_time.strftime("%s"), time.time())
        p = hashlib.md5(s.encode("UTF-8")).hexdigest()[:16]
        self.set_secure_password(p)
        return p

    def get_secure_password(self, raw_password):
        p1 = hashlib.sha256(raw_password.encode("UTF-8")).hexdigest()
        p2 = hashlib.sha256((self.salt + p1).encode("UTF-8")).hexdigest()
        return p2

    def set_secure_password(self, raw_password):
        self.salt = mksalt()
        self.password = self.get_secure_password(raw_password)

    def init_avatar(self, social_user):
        anyone = "http://tva1.sinaimg.cn/default/images/default_avatar_male_50.gif"
        url = social_user.extra_data.get("profile_image_url", anyone)
        self.avatar = url.replace("http://q.qlogo.cn", "//q.qlogo.cn")

        if social_user.provider == "github":
            self.avatar = (
                "https://avatars.githubusercontent.com/u/%s"
                % social_user.extra_data["id"]
            )

    def get_active_code(self):
        return self.get_secure_password(self.create_time.strftime("%Y-%m-%d %H:%M:%S"))

    def get_social_username(self, si):
        for k in ["username", "login"]:
            if k in si.extra_data:
                return si.extra_data[k]
        return "%s_%s" % (si.provider, si.uid)

    def check_and_update(self, social_user):
        name = self.get_social_username(social_user)
        if self.username != name:
            logging.info("userid[%s] username needs update to [%s]" % (self.id, name))
            self.username = name

    def set_permission(self, operations):
        ALL = "delprsuv"
        if not isinstance(operations, str):
            raise "bug"
        v = list(self.permission)
        for p in operations:
            if p.lower() not in ALL:
                continue
            r = p.upper() if p.islower() else p.lower()
            try:
                v.remove(r)
            except:
                pass
            v.append(p)
        self.permission = "".join(sorted(v))

    def has_permission(self, operation, default=True):
        if operation.lower() in self.permission:
            return True
        if operation.upper() in self.permission:
            return False
        return default

    def can_delete(self):
        return self.has_permission("d")

    def can_edit(self):
        return self.has_permission("e")

    def can_login(self):
        return self.has_permission("l")

    def can_push(self):
        return self.has_permission("p")

    def can_read(self):
        return self.has_permission("r")

    def can_save(self):
        return self.has_permission("s")

    def can_upload(self):
        return self.has_permission("u")

    def can_view(self):
        return self.has_permission("v")

    def is_active(self):
        return self.active

    def is_admin(self):
        return self.admin


class ReaderLog(Base, SQLAlchemyMixin):
    ACTION_LOGIN = 1
    ACTION_DISABLE = 2
    ACTION_ENABLE = 3
    ACTION_UPDATE_EXPIRE = 10
    ACTION_UPDATE_QUOTA = 11
    ACTION_COLLECTION_DOWNLOAD = 20
    ACTION_COLLECTION_DOWNLOAD_START = 21
    ACTION_COLLECTION_DOWNLOAD_FINISHED = 22
    ACTION_PURCHASE = 30

    __tablename__ = "readerlogs"
    id = Column(Integer, primary_key=True)
    reader_id = Column(Integer, ForeignKey("readers.id"))
    action = Column(Integer, default=0)
    create_time = Column(DateTime)
    extra = Column(MutableDict.as_mutable(JSONType), default={})
    revision = Column(String(100), default=0)
    operator_id = Column(Integer, ForeignKey("readers.id"), default=0)

    def __init__(self, reader_id, action, operator_id=0, revision=""):
        super(ReaderLog, self).__init__()
        self.reader_id = reader_id
        self.action = action
        self.operator_id = operator_id
        self.revision = revision
        self.create_time = datetime.datetime.now()

    def set_extra(self, key, value):
        if not self.extra:
            self.extra = {}
        self.extra[key] = value

    def get_extra(self, key, default=None):
        if not self.extra:
            self.extra = {}
        return self.extra.get(key, default)


###
# 存放一些业务相关的Key
# 像下载业务，在下载链接后面加上一个key，防止盗链
###
class BizKey(Base, SQLAlchemyMixin):
    TYPE_DOWNLOAD = 1

    __tablename__ = "biz_key"
    id = Column(Integer, primary_key=True)
    reader_id = Column(Integer, ForeignKey("readers.id"))
    key = Column(String(100))
    expire = Column(DateTime)
    create_time = Column(DateTime)
    type = Column(Integer)

    def __init__(self, reader_id, key, expire, type=0):
        super(BizKey, self).__init__()
        self.reader_id = reader_id
        self.key = key
        self.expire = expire
        self.create_time = datetime.datetime.now()
        self.type = type


class Message(Base, SQLAlchemyMixin):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    title = Column(String(200))
    status = Column(String(100))
    unread = Column(Boolean, default=True)
    create_time = Column(DateTime)
    update_time = Column(DateTime)
    data = Column(MutableDict.as_mutable(JSONType), default={})

    reader_id = Column(Integer, ForeignKey("readers.id"))
    reader = relationship(Reader, backref="messages")

    def __init__(self, user_id, status, msg):
        super(Message, self).__init__()
        self.reader_id = user_id
        self.status = status
        self.create_time = datetime.datetime.now()
        self.update_time = datetime.datetime.now()
        self.data = {"message": msg}

    @classmethod
    def cleanup_messages(cls, reader_id, msg_content, days=31):
        """清理指定用户的匹配消息内容的消息"""
        session = cls._session()
        messages = session.query(cls).filter_by(reader_id=reader_id).all()

        removed_count = 0
        for message in messages:
            if message.data.get("message") == msg_content:
                session.delete(message)
                removed_count += 1
            elif message.update_time < datetime.datetime.now() - datetime.timedelta(
                days=days
            ):
                session.delete(message)
                removed_count += 1

        if removed_count > 0:
            session.commit()

        return removed_count

    @classmethod
    def cleanup_old_messages(cls, days=31):
        """清理指定天数以前的消息"""
        session = cls._session()
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)

        old_messages = session.query(cls).filter(cls.create_time < cutoff_date).all()
        removed_count = len(old_messages)

        for message in old_messages:
            session.delete(message)

        if removed_count > 0:
            session.commit()
            logging.info(f"Cleaned up {removed_count} messages older than {days} days")

        return removed_count


class Item(Base, SQLAlchemyMixin):
    # 图书信息
    __tablename__ = "items"

    book_id = Column(Integer, default=0, primary_key=True)
    count_guest = Column(Integer, default=0, nullable=False)
    count_visit = Column(Integer, default=0, nullable=False)  # 首次阅读次数：某用户首次产生该书的 Reading(action=read) 记录时 +1，由 ReadingWriteBuffer.flush() 维护
    count_download = Column(Integer, default=0, nullable=False)  # 下载+推送次数：每新增一条 Reading(action=download/push) 记录 +1，由 ReadingWriteBuffer.flush() 维护
    website = Column(String(255), default="", nullable=False)

    collector_id = Column(Integer, ForeignKey("readers.id"))
    collector = relationship(Reader, backref="items")
    sole = Column(Boolean, default=False, nullable=False)
    book_type = Column(Integer, default=0, nullable=False)
    book_count = Column(Integer, default=1, nullable=False)
    create_time = Column(DateTime)
    src_path = Column(String(4096), default="", nullable=False)

    def __init__(self):
        super(Item, self).__init__()
        self.count_guest = 0
        self.count_visit = 0
        self.count_download = 0
        self.collector_id = 1
        self.sole = False
        self.book_type = BOOK_TYPE_EBOOK  # 0:电子书, 1:实体书
        self.book_count = 1
        self.create_time = datetime.datetime.now()
        self.src_path = ""


class ScanFile(Base, SQLAlchemyMixin):
    __tablename__ = "scanfiles"
    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, default=0)
    import_id = Column(Integer, default=0)
    import_type = Column(Integer, default=0)

    name = Column(String(512))
    path = Column(String(1024))
    hash = Column(String(512))
    status = Column(String(24))

    title = Column(String(100))
    author = Column(String(100))
    publisher = Column(String(100))
    tags = Column(String(100))

    create_time = Column(DateTime)
    update_time = Column(DateTime)
    book_id = Column(Integer, default=0)
    data = Column(MutableDict.as_mutable(JSONType), default={})

    # STATUS
    NEW = "new"
    DROP = "drop"
    READY = "ready"
    EXIST = "exist"
    IMPORTED = "imported"
    INVALID = "invalid"
    MISSED = "missed"
    PERMISSION = "permission"

    def __init__(self, path, hash_value, import_id):
        super(ScanFile, self).__init__()
        self.name = os.path.basename(path)
        self.path = path
        self.hash = hash_value
        self.import_id = import_id
        self.status = self.NEW
        self.create_time = datetime.datetime.now()
        self.update_time = datetime.datetime.now()


class ReaderPaidBook(Base, SQLAlchemyMixin):
    __tablename__ = "reader_paid_books"

    id = Column(Integer, primary_key=True)
    reader_id = Column(Integer, ForeignKey("readers.id"))
    book_id = Column(Integer)
    order_id = Column(String(100))
    create_time = Column(DateTime)
    price = Column(Integer, default=0)  # 价格
    reader = relationship(Reader, backref="paid_books")

    def __init__(self, reader_id, book_id, order_id=None, price=1):
        super(ReaderPaidBook, self).__init__()
        self.reader_id = reader_id
        self.book_id = book_id
        self.order_id = order_id
        self.price = price
        self.create_time = datetime.datetime.now()


# 用户对某本书的阅读状态
class ReadingState(Base, SQLAlchemyMixin):
    __tablename__ = "reading_state"

    book_id = Column(Integer, primary_key=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), primary_key=True)
    favorite = Column(Integer, default=0)  # 0:为未收藏,1:已收藏
    favorite_date = Column(DateTime)
    wants = Column(Integer, default=0)  # 0:未标记为待读,1:标记为待读
    wants_date = Column(DateTime)
    read_state = Column(Integer, default=0, nullable=False)  # 0:未读, 1:在读, 2:已读完
    read_date = Column(DateTime)
    online_read = Column(Integer, default=0)  # 0:未在线阅读, 1:已在线阅读
    download = Column(Integer, default=0)  # 0:未下载,1:已下载

    # 建立关系
    reader = relationship(Reader, backref="reading_states")

    def __init__(self, book_id, reader_id):
        super(ReadingState, self).__init__()
        self.book_id = book_id
        self.reader_id = reader_id
        self.favorite = 0
        self.wants = 0
        self.read_state = 0

    def set_favorite(self, favorite_status):
        """设置收藏状态"""
        self.favorite = 1 if favorite_status else 0
        self.favorite_date = datetime.datetime.now()

    def is_favorite(self):
        """检查是否已收藏"""
        return self.favorite == 1

    def set_wants(self, wants_status):
        """设置待读状态"""
        self.wants = 1 if wants_status else 0
        self.wants_date = datetime.datetime.now()

    def is_wants(self):
        """检查是否标记为待读"""
        return self.wants == 1

    def set_read_state(self, read_state):
        """设置阅读状态 0:未读, 1:在读, 2:已读完"""
        if read_state in [0, 1, 2]:
            self.read_state = read_state
            self.read_date = datetime.datetime.now()
        if read_state > READ_STATE_UNREAD:
            self.wants = 0

    def get_read_state(self):
        """获取当前阅读状态"""
        return self.read_state

    def set_online_read(self, online_read_status):
        """设置在线阅读状态"""
        self.online_read = 1 if online_read_status else 0

    def set_download(self, download_status):
        """设置下载状态"""
        self.download = 1 if download_status else 0


# 用户对某本书的阅读/下载/推送行为记录（详见 document/Reading_Stats_Design.md）
# action=read: 每个 (reader_id, book_id, date) 只保留一行（date 是 UTC 日期，不含时间，
#              用于按天统计阅读时长），duration 是当天累计时长，start_time 是当天"最近一次
#              阅读会话"的开始时间；由 ux_readings_read 部分唯一索引 + upsert 维护（见 async_service.py）
# action=download/push: 事件制，每次都新插入一行；date 取事件发生当天，不参与唯一性约束
class Reading(Base, SQLAlchemyMixin):
    __tablename__ = "readings"

    ACTION_READ = "read"
    ACTION_DOWNLOAD = "download"
    ACTION_PUSH = "push"

    PROTOCOL_WEB = "web"          # action=read | download
    PROTOCOL_APP = "app"          # action=read（MyReader）
    PROTOCOL_OPDS = "opds"        # action=download
    PROTOCOL_WEBDAV = "webdav"    # action=download
    PROTOCOL_DEVICE = "device"    # action=push
    PROTOCOL_EMAIL = "email"      # action=push

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    book_id = Column(Integer, nullable=False)
    book_title = Column(String(512), default="")  # 保留字段，本轮不填充
    action = Column(String(16), nullable=False)    # read | download | push
    protocol = Column(String(16), nullable=False)  # 见 PROTOCOL_* 常量，按 action 区分含义
    date = Column(Date, nullable=False)  # UTC 日期（不含时间）；action=read 时是唯一键的一部分
    start_time = Column(DateTime, nullable=False)  # UTC；read=当天最近一次阅读会话开始时间，download/push=事件发生时间
    duration = Column(Integer, default=0, nullable=False)  # 秒；仅 action=read 有意义，download/push 恒为 0
    update_time = Column(DateTime, nullable=False)  # UTC；read=最后一次心跳时间，download/push=事件发生时间

    reader = relationship(Reader, backref="readings")

    def __init__(self, reader_id, book_id, action, protocol, start_time, duration=0, update_time=None, date=None):
        super(Reading, self).__init__()
        self.reader_id = reader_id
        self.book_id = book_id
        self.action = action
        self.protocol = protocol
        self.start_time = start_time
        self.duration = duration
        self.update_time = update_time or start_time
        self.date = date or self.update_time.date()


# 单本书 · 分格式的阅读时长/进度统计
# 与 Reading 表（全局、按天分桶、不分格式）是两条并行的统计线：这张表关心"这一遍完整地
# 读了多久、从哪天开始、哪天读完"，(reader_id, book_id, format) 唯一，一行代表"当前/最近一轮"。
class BookReadingStats(Base, SQLAlchemyMixin):
    __tablename__ = "book_reading_stats"

    STATE_READING = 0
    STATE_FINISHED = 1

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    book_id = Column(Integer, nullable=False)
    format = Column(String(16), nullable=False)  # epub/pdf/mobi/azw3/txt 等，统一小写

    state = Column(Integer, default=STATE_READING, nullable=False)  # 0=在读 1=已完成
    total_seconds = Column(Integer, default=0, nullable=False)      # 这个格式的累计阅读时长（秒），跨轮次累加

    progress_current = Column(Integer)  # 来自 sync progress=[current,total] 的 current
    progress_total = Column(Integer)    # 来自 sync progress=[current,total] 的 total
    progress_percent = Column(Float)    # 0~100，两位小数；与 current/total 一起存，避免查询时现算

    start_time = Column(DateTime)   # UTC；当前/最近一轮的开始时间
    finish_time = Column(DateTime)  # UTC；当前/最近一轮的完成时间；重新开始阅读时清空
    start_count = Column(Integer, default=0, nullable=False)  # 开始阅读的次数（含首次）

    create_time = Column(DateTime, nullable=False)  # 这一行第一次创建的时间，不随轮次变化
    update_time = Column(DateTime, nullable=False)  # 最后一次写入时间（心跳或手动更新）

    reader = relationship(Reader)

    __table_args__ = (
        UniqueConstraint("reader_id", "book_id", "format", name="ux_book_reading_stats"),
        Index("ix_book_reading_stats_reader_book", "reader_id", "book_id"),
    )

    def format_dict(self):
        return {
            "format": self.format,
            "state": self.state,
            "total_seconds": self.total_seconds or 0,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "progress_percent": 100.0 if self.state == self.STATE_FINISHED else self.progress_percent,
            # start_time/finish_time/update_time 存的是 UTC naive datetime（见类注释），
            # isoformat() 后补一个 "Z" 后缀，避免前端 `new Date(...)` 把它当成本地时间解析
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "finish_time": self.finish_time.isoformat() + "Z" if self.finish_time else None,
            "start_count": self.start_count or 0,
            "update_time": self.update_time.isoformat() + "Z" if self.update_time else None,
        }


# 管理菜单"阅读时间补录"：每 (reader_id, book_id, date) 一行，记录当前生效的补录时长。
# 再次编辑同一天是更新这一行而不是追加流水，保留 duration_seconds 是为了编辑/删除时能
# 算出与上一次的差值，增量同步到 Reading.duration / BookReadingStats.total_seconds /
# Reader.total_reading_seconds，避免统计翻倍或对不上。
class ManualReadingLog(Base, SQLAlchemyMixin):
    __tablename__ = "manual_reading_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    book_id = Column(Integer, nullable=False)
    format = Column(String(16), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(String(5))
    end_time = Column(String(5))
    duration_seconds = Column(Integer, default=0, nullable=False)
    create_time = Column(DateTime, nullable=False)
    update_time = Column(DateTime, nullable=False)

    reader = relationship(Reader)

    __table_args__ = (
        UniqueConstraint("reader_id", "book_id", "date", name="ux_manual_reading_logs"),
        Index("ix_manual_reading_logs_reader_book", "reader_id", "book_id"),
    )

    def format_dict(self):
        return {
            "date": self.date.strftime("%Y-%m-%d"),
            "format": self.format,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds or 0,
        }


# MyBooks 云端书籍的 book_hash 形如 "cloud-8502-epub"，8502 是 Calibre book_id；
# 与 webserver/services/reading_stats_service.py::_CLOUD_BOOK_HASH_RE 保持一致（含义相同，
# 避免相互 import 造成循环依赖，两处各自维护一份同样的正则）。
_CLOUD_BOOK_HASH_RE = re.compile(r"^cloud-(\d+)-[a-zA-Z0-9]+$")


def parse_book_id_from_reading_record_hash(book_hash):
    """把 `book_hash` 换算成 ReadingRecord.book_id：

    - 云端书籍（`cloud-<id>-<fmt>`）：返回真实的正整数 Calibre book_id。
    - 本地/无法识别的 book_hash：返回一个稳定的负数占位值（同一 book_hash 每次算出来的
      结果一致），保证：① 恒为负数，天然不会撞上真实 book_id（恒为正）；② 跨用户共读查询
      只需加 `book_id > 0` 条件即可自动排除所有本地书籍，不需要额外的"是否本地书籍"标记列。
      见 document/../plan/Social_Reading_Plan.md §5.2。
    """
    if book_hash:
        m = _CLOUD_BOOK_HASH_RE.match(book_hash)
        if m:
            return int(m.group(1))
    return -(zlib.crc32((book_hash or "").encode("utf-8")) & 0x7FFFFFFF) or -1


# 用户阅读器数据同步记录（books/configs/notes 三类），替代原先按
# <MYREADER_SYNC_PATH>/<uid>/<book_hash>/{kind}.json 的文件存储方案。
# 详见 plan/Social_Reading_Plan.md §5.2、§7，以及 webserver/services/sync_service.py。
class ReadingRecord(Base, SQLAlchemyMixin):
    __tablename__ = "reading_records"

    KIND_BOOKS = "books"
    KIND_CONFIGS = "configs"
    KIND_NOTES = "notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    book_hash = Column(String(64), nullable=False)      # 原始 book_hash，记录身份仍以它为准
    book_id = Column(Integer, nullable=False)           # 从 book_hash 提取的整型 id，供跨用户查询走整型索引
    kind = Column(String(16), nullable=False)           # books | configs | notes
    record_id = Column(String(64), nullable=False)      # books/configs: 固定用 book_hash 占位；notes: 记录自带的 id
    uid = Column(Integer, nullable=False)                # 冗余存一份 reader_id，同时也是要求写入 payload 内的 "uid"
    payload = Column(MutableDict.as_mutable(JSONType), nullable=False, default={})  # 记录原始 JSON 内容
    updated_at = Column(BigInteger, nullable=False)      # 毫秒时间戳，来自 payload.updated_at，冗余出来做索引/排序
    deleted_at = Column(BigInteger, nullable=True)       # 同上，冗余自 payload.deleted_at

    reader = relationship(Reader)

    __table_args__ = (
        UniqueConstraint("reader_id", "book_hash", "kind", "record_id", name="ux_reading_record"),
        Index("ix_reading_record_lookup", "reader_id", "kind", "updated_at"),
        Index("ix_reading_record_book_kind", "book_id", "kind", "updated_at"),
    )


# 用户对某本书的评分 + 评论（"共读"里的评价 = 推荐，见 plan/Social_Reading_Plan.md §5.1）。
# 每个用户对每本书最多一条（唯一约束），自行删除是软删除（deleted_at），管理员屏蔽是把
# status 置为 hidden（prev_status 记录屏蔽前的状态，供"恢复"用），两者语义不同、互不覆盖。
class BookReview(Base, SQLAlchemyMixin):
    __tablename__ = "book_reviews"

    STATUS_PENDING = "pending"    # 未审核
    STATUS_APPROVED = "approved"  # 通过
    STATUS_HIDDEN = "hidden"      # 管理员屏蔽

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    book_id = Column(Integer, nullable=False)
    rating = Column(Integer, nullable=False)             # 沿用 book.rating 刻度（0-10）
    comment = Column(Text, default="")                    # 允许为空
    status = Column(String(16), nullable=False, default=STATUS_APPROVED)
    prev_status = Column(String(16), nullable=True)       # 进入 hidden 前的状态快照，供"恢复"使用
    create_time = Column(DateTime, nullable=False)
    update_time = Column(DateTime, nullable=False)
    deleted_at = Column(DateTime, nullable=True)           # 用户自行删除（软删除）

    reader = relationship(Reader)

    __table_args__ = (
        UniqueConstraint("reader_id", "book_id", name="ux_book_review"),
        Index("ix_book_review_book", "book_id", "status", "update_time"),
    )


class Device(Base, SQLAlchemyMixin):
    """用户阅读设备"""

    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    name = Column(String(64), nullable=False, default="")
    device_type = Column(String(32), nullable=False, default="duokan")
    ip = Column(String(128), default="")
    port = Column(Integer, default=12121)
    schema = Column(String(8), default="http")
    mailbox = Column(String(2048), default="")
    create_time = Column(DateTime, default=datetime.datetime.now)
    update_time = Column(DateTime, default=datetime.datetime.now)

    reader = relationship(Reader, backref="devices")

    def __init__(
        self,
        reader_id,
        name,
        device_type="duokan",
        ip="",
        port=12121,
        schema="http",
        mailbox="",
    ):
        super(Device, self).__init__()
        self.reader_id = reader_id
        self.name = name
        self.device_type = device_type
        self.ip = ip
        self.port = port
        self.schema = schema
        self.mailbox = mailbox
        self.create_time = datetime.datetime.now()
        self.update_time = datetime.datetime.now()

    def to_dict(self):
        result = {
            "name": self.name,
            "type": self.device_type,
            "ip": self.ip,
            "port": self.port,
            "schema": self.schema,
            "mailbox": self.mailbox,
        }
        if self.device_type == "ftp":
            try:
                extra = json.loads(self.mailbox or "{}")
            except Exception:
                extra = {}
            result["ftp_username"] = extra.get("username", "")
            result["ftp_password"] = extra.get("password", "")
            result["ftp_path"] = extra.get("path", "")
            result["mailbox"] = ""
        return result


class Authors(Base, SQLAlchemyMixin):
    """作者信息, author_id为后台返回的id"""

    __tablename__ = "authors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    author_id = Column(Integer, nullable=True, default=0)
    sort = Column(String(128), nullable=True, default="")
    bio = Column(String(4096), nullable=True, default="")
    region = Column(String(128), nullable=True, default="")
    avatar = Column(String(512), nullable=True, default="")
    create_time = Column(DateTime, default=datetime.datetime.now)

    def __init__(self, name, sort, bio="", region="", avatar=""):
        super(Authors, self).__init__()
        self.name = name
        self.sort = sort
        self.bio = bio
        self.region = region
        self.avatar = avatar
        self.create_time = datetime.datetime.now()


class StickyItem(Base, SQLAlchemyMixin):
    """置顶项目 - 用于置顶作者或标签"""

    __tablename__ = "sticky_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    item_type = Column(Integer, nullable=False)  # 0:作者, 1:Tag
    value = Column(String(256), nullable=False)  # 存储具体的作者或Tag名称
    create_time = Column(DateTime, default=datetime.datetime.now)

    # 建立关系
    reader = relationship(Reader, backref="sticky_items")

    def __init__(self, reader_id, item_type, value):
        super(StickyItem, self).__init__()
        self.reader_id = reader_id
        self.item_type = item_type
        self.value = value
        self.create_time = datetime.datetime.now()


class ExpectedItem(Base, SQLAlchemyMixin):
    """缺书登记项目"""

    __tablename__ = "expected_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    title = Column(String(256), nullable=False)  # 书籍标题
    author = Column(String(128), nullable=True, default="")  # 书籍作者
    publisher = Column(String(256), nullable=True, default="")  # 出版社
    create_time = Column(DateTime, default=datetime.datetime.now)

    # 建立关系
    reader = relationship(Reader, backref="expected_items")

    def __init__(self, reader_id, title, author="", publisher=""):
        super(ExpectedItem, self).__init__()
        self.reader_id = reader_id
        self.title = title
        self.author = author
        self.publisher = publisher
        self.create_time = datetime.datetime.now()


class Memo(Base, SQLAlchemyMixin):
    """网站留言"""

    MEMO_TYPE_SUGGESTION = 0  # 建议
    MEMO_TYPE_BOOK_REQUEST = 1  # 求书
    MEMO_TYPE_HELP = 2  # 求助

    STAGE_NEW = "new"
    STAGE_SUSPEND = "suspend"
    STAGE_DONE = "done"

    __tablename__ = "memo"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False, default=0)
    memo = Column(String(2048), nullable=False, default="")
    reply = Column(String(2048), nullable=False, default="")
    memo_type = Column(Integer, nullable=False, default=0)
    stage = Column(String(10), nullable=False, default="new")
    create_date = Column(DateTime, default=datetime.datetime.now)
    update_date = Column(DateTime, default=datetime.datetime.now)

    # 建立关系
    reader = relationship(Reader, backref="memos")

    def __init__(self, reader_id, memo, memo_type=0, stage="new"):
        super(Memo, self).__init__()
        self.reader_id = reader_id
        self.memo = memo
        self.memo_type = memo_type
        self.stage = stage
        self.reply = None
        self.create_date = datetime.datetime.now()
        self.update_date = datetime.datetime.now()


class InstalledTool(Base, SQLAlchemyMixin):
    """Toolbox 工具安装记录：内置工具 + 外部工具统一记录在这张表里，
    见 document/Toolbox_Dynamic_Design.md 3.3.2 节。

    MyBooks 里统一用"工具"（tool）指代 Toolbox 的功能单元，不用"插件"（plugin）这个词——
    type 只有 builtin（内置）/ tool（通过 zip 安装的非内置工具）两种。"""
    __tablename__ = "installed_tools"

    TYPE_BUILTIN = "builtin"
    TYPE_TOOL = "tool"

    SOURCE_BUNDLED = "bundled"  # 随仓库自带（仅 builtin）
    SOURCE_STORE = "store"      # 通过 mybooks.top 商店安装/更新；ENABLE_TOOLBOX_STORE=False（默认）时商店索引恒为空，实际不会产生此来源的记录
    SOURCE_DEV = "dev"          # 开发者模式本地 zip 上传安装/更新

    tool_id = Column(String(128), primary_key=True)
    type = Column(String(16), nullable=False)  # builtin | tool，写入后不再改变
    installed_revision = Column(String(32), default="", nullable=False)
    source = Column(String(16), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)  # 仅对 type=tool 有意义，builtin 恒为 True
    install_time = Column(DateTime)
    update_time = Column(DateTime)
    installed_by = Column(Integer, ForeignKey("readers.id"), nullable=True)

    def __init__(self, tool_id, type_, source, installed_revision="", enabled=True, installed_by=None):
        super(InstalledTool, self).__init__()
        self.tool_id = tool_id
        self.type = type_
        self.source = source
        self.installed_revision = installed_revision
        self.enabled = enabled
        now = datetime.datetime.now()
        self.install_time = now
        self.update_time = now
        self.installed_by = installed_by

    @classmethod
    def get(cls, tool_id):
        return cls._query().filter_by(tool_id=tool_id).first()

    @classmethod
    def all(cls):
        return cls._query().all()

    def delete(self):
        session = self._session()
        session.delete(self)
        session.commit()

    def to_dict(self):
        return {
            "tool_id": self.tool_id,
            "type": self.type,
            "source": self.source,
            "installed_revision": self.installed_revision,
            "enabled": self.enabled,
            "install_time": self.install_time.isoformat() if self.install_time else None,
            "update_time": self.update_time.isoformat() if self.update_time else None,
            "installed_by": self.installed_by,
        }


class BookList(Base, SQLAlchemyMixin):
    """用户自建书单，见 document/BookList_Design.md。删除为物理硬删除（非关键数据，不做软删除），
    关联的 BookListBook / BookListLike 记录在 service 层同一事务里一并删除。"""

    __tablename__ = "booklists"

    COLORS = ("marine", "velvet", "night_blue", "green", "yellow", "red", "purple", "orange")
    DEFAULT_COLOR = "marine"
    MAX_PER_USER = 20

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), default="", nullable=False)
    color = Column(String(16), nullable=False, default=DEFAULT_COLOR)
    is_public = Column(Boolean, nullable=False, default=False)
    is_sticky = Column(Boolean, nullable=False, default=False)
    sticky_order = Column(Integer, nullable=True)
    view_count = Column(Integer, nullable=False, default=0)
    like_count = Column(Integer, nullable=False, default=0)
    book_count = Column(Integer, nullable=False, default=0)
    create_time = Column(DateTime, nullable=False)
    update_time = Column(DateTime, nullable=False)

    reader = relationship(Reader)

    __table_args__ = (
        Index("ix_booklist_reader", "reader_id", "update_time"),
        Index("ix_booklist_public", "is_public", "is_sticky", "update_time"),
    )

    def __init__(self, reader_id, name, description="", color=None, is_public=False):
        super(BookList, self).__init__()
        self.reader_id = reader_id
        self.name = name
        self.description = description or ""
        self.color = color if color in self.COLORS else self.DEFAULT_COLOR
        self.is_public = is_public
        self.is_sticky = False
        self.view_count = 0
        self.like_count = 0
        self.book_count = 0
        now = datetime.datetime.now()
        self.create_time = now
        self.update_time = now


class BookListBook(Base, SQLAlchemyMixin):
    """书单-书籍关联表。book_id 不建跨库外键（Calibre 库独立管理，同 Item.book_id 的做法），
    书籍被删除后本表记录成为悬空引用，展示层需要跳过/兼容。"""

    __tablename__ = "booklist_books"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booklist_id = Column(Integer, ForeignKey("booklists.id"), nullable=False)
    book_id = Column(Integer, nullable=False)
    update_time = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("booklist_id", "book_id", name="ux_booklist_book"),
        Index("ix_booklist_books_booklist", "booklist_id", "update_time"),
    )

    def __init__(self, booklist_id, book_id):
        super(BookListBook, self).__init__()
        self.booklist_id = booklist_id
        self.book_id = book_id
        self.update_time = datetime.datetime.now()


class BookListLike(Base, SQLAlchemyMixin):
    """书单点赞/收藏关系表。侧边栏"收藏书单" = 当前用户在本表中的所有记录对应的书单。"""

    __tablename__ = "booklist_likes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    booklist_id = Column(Integer, ForeignKey("booklists.id"), nullable=False)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    create_time = Column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("booklist_id", "reader_id", name="ux_booklist_like"),
        Index("ix_booklist_likes_reader", "reader_id", "create_time"),
    )

    def __init__(self, booklist_id, reader_id):
        super(BookListLike, self).__init__()
        self.booklist_id = booklist_id
        self.reader_id = reader_id
        self.create_time = datetime.datetime.now()


def user_syncdb(engine):
    Base.metadata.create_all(engine)


# 表结构随功能迭代新增的表，不希望依赖运维方手动重新执行 `--syncdb` 才能用上
# （`docker/start.sh` 每次启动都会跑 --syncdb，但手工部署/测试环境不一定会），
# 在正常的 make_app() 启动路径里也顺带补建一次，checkfirst=True 天然幂等。
_NEW_TABLES_AUTO_ENSURE = (ReadingRecord, BookReview, InstalledTool, BookReadingStats, BookList, BookListBook, BookListLike, ManualReadingLog)


def ensure_new_tables(engine):
    Base.metadata.create_all(engine, tables=[m.__table__ for m in _NEW_TABLES_AUTO_ENSURE], checkfirst=True)
