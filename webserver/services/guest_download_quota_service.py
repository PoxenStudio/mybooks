#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""未登录访客按 IP 的每日下载本数限制。

调用方是 BookDownload._charge_download，且已排除 HEAD 与分享链接下载。
计数口径：同一 IP、同一站点日、同一本书只算一本；每日按站点时区零点切换。
"""

import datetime
import ipaddress
import logging
import threading
from typing import NamedTuple

from sqlalchemy.exc import IntegrityError

from webserver import loader, site_time
from webserver.models import GuestDownloadDaily

CONF = loader.get_settings()

DEFAULT_QUOTA = 10
RETENTION_DAYS = 7


class GuestQuotaResult(NamedTuple):
    allowed: bool
    used: int
    quota: int


class GuestDownloadQuotaService:
    _lock = threading.Lock()
    _last_prune_day = None

    @classmethod
    def enabled(cls) -> bool:
        return bool(CONF.get("ENABLE_GUEST_DOWNLOAD_QUOTA", False))

    @classmethod
    def quota(cls) -> int:
        try:
            value = int(CONF.get("GUEST_DOWNLOAD_QUOTA", DEFAULT_QUOTA) or 0)
        except (TypeError, ValueError):
            value = DEFAULT_QUOTA
        return max(0, value)

    @staticmethod
    def normalize_ip(ip: str) -> str:
        raw = (ip or "").strip()
        if not raw:
            return ""
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            return raw[:45]
        if addr.version == 6:
            if addr.ipv4_mapped:
                return str(addr.ipv4_mapped)
            # 一个家庭/设备通常持有一整个 /64，逐地址计数会被 IPv6 隐私地址轮换绕过
            return str(ipaddress.ip_network("%s/64" % addr, strict=False).network_address)
        return str(addr)

    @classmethod
    def get_usage(cls, ip: str, book_id=None) -> GuestQuotaResult:
        quota = cls.quota()
        key = cls.normalize_ip(ip)
        if not key or not cls.enabled() or quota == 0:
            return GuestQuotaResult(True, 0, quota)
        day = site_time.site_today()
        db = GuestDownloadDaily._session()
        used = cls._count(db, key, day)
        if book_id is not None:
            try:
                book_id = int(book_id)
            except (TypeError, ValueError):
                book_id = None
        if book_id is not None and cls._recorded(db, key, day, book_id):
            return GuestQuotaResult(True, used, quota)
        return GuestQuotaResult(used < quota, used, quota)

    @classmethod
    def charge(cls, ip: str, book_id: int) -> GuestQuotaResult:
        quota = cls.quota()
        key = cls.normalize_ip(ip)
        if not key or not cls.enabled() or quota == 0:
            return GuestQuotaResult(True, 0, quota)
        try:
            book_id = int(book_id)
        except (TypeError, ValueError):
            return GuestQuotaResult(True, 0, quota)

        day = site_time.site_today()
        db = GuestDownloadDaily._session()
        with cls._lock:
            used = cls._count(db, key, day)
            if cls._recorded(db, key, day, book_id):
                return GuestQuotaResult(True, used, quota)
            if used >= quota:
                return GuestQuotaResult(False, used, quota)
            try:
                db.add(GuestDownloadDaily(key, day, book_id))
                db.commit()
            except IntegrityError:
                # 主键兜底并发插入同一本书，按已计入处理
                db.rollback()
                return GuestQuotaResult(True, used, quota)
            cls._prune(db, day)
            return GuestQuotaResult(True, used + 1, quota)

    @classmethod
    def _count(cls, db, key, day) -> int:
        return db.query(GuestDownloadDaily).filter_by(ip=key, day=day).count()

    @classmethod
    def _recorded(cls, db, key, day, book_id) -> bool:
        return db.query(GuestDownloadDaily).filter_by(ip=key, day=day, book_id=book_id).first() is not None

    @classmethod
    def _prune(cls, db, today):
        if cls._last_prune_day == today:
            return
        cutoff = today - datetime.timedelta(days=RETENTION_DAYS)
        try:
            db.query(GuestDownloadDaily).filter(GuestDownloadDaily.day < cutoff).delete(synchronize_session=False)
            db.commit()
            cls._last_prune_day = today
        except Exception:
            db.rollback()
            logging.warning("[guest_download_quota] prune failed", exc_info=True)
