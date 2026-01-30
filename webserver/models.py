#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import datetime
import hashlib
import logging
import time
import json
import os
from gettext import gettext as _

from social_sqlalchemy.storage import JSONType, SQLAlchemyMixin
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.orm import relationship, declarative_base


BOOK_TYPE_EBOOK = 0  # 电子书
BOOK_TYPE_PHYSICAL = 1  # 实体书

# 阅读状态常量
READ_STATE_UNREAD = 0      # 未读
READ_STATE_READING = 1     # 在读
READ_STATE_FINISHED = 2    # 已读完

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
    # 权限位
    SPECIAL = 0b00000001  # 未开启说明是默认权限
    LOGIN = 0b00000010  # 登录
    VIEW = 0b00000100  # 浏览
    READ = 0b00001000  # 阅读
    UPLOAD = 0b00010000  # 上传
    DOWNLOAD = 0b00100000  # 下载

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

    def __str__(self):
        return "<id=%d, username=%s, email=%s, admin:%d>" % (self.id, self.username, self.email, self.admin)

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
        return super().save()

    def init_default_user(self):
        class DefaultUserInfo:
            extra_data = {"username": _(u"默认用户")}
            provider = "qq"
            uid = 123456789

        self.init(DefaultUserInfo())

    def init(self, social_user):
        self.username = self.get_social_username(social_user)
        self.create_time = datetime.datetime.now()
        self.update_time = datetime.datetime.now()
        self.access_time = datetime.datetime.now()
        self.extra = {"kindle_email": ""}
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
            self.avatar = "https://avatars.githubusercontent.com/u/%s" % social_user.extra_data["id"]

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
            elif message.update_time < datetime.datetime.now() - datetime.timedelta(days=days):
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
    count_visit = Column(Integer, default=0, nullable=False)
    count_download = Column(Integer, default=0, nullable=False)
    website = Column(String(255), default="", nullable=False)

    collector_id = Column(Integer, ForeignKey("readers.id"))
    collector = relationship(Reader, backref="items")
    sole = Column(Boolean, default=False, nullable=False)
    book_type = Column(Integer, default=0, nullable=False)
    book_count = Column(Integer, default=1, nullable=False)
    create_time = Column(DateTime)

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


class ScanFile(Base, SQLAlchemyMixin):
    __tablename__ = "scanfiles"
    id = Column(Integer, primary_key=True)
    scan_id = Column(Integer, default=0)
    import_id = Column(Integer, default=0)

    name = Column(String(512))
    path = Column(String(1024))
    hash = Column(String(512), unique=True)
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
    INVALID_ISBN = "invalid"
    MISSED = "missed"
    PERMISSION = "permission"

    def __init__(self, path, hash_value, scan_id):
        super(ScanFile, self).__init__()
        self.name = os.path.basename(path)
        self.path = path
        self.hash = hash_value
        self.scan_id = scan_id
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


def user_syncdb(engine):
    Base.metadata.create_all(engine)
