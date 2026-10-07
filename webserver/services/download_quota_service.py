#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Per-reader daily download quota enforcement.
@author: PoxenStudio, 2026-08

No new column is added to Reader; the state lives entirely in the existing
`extra` JSON column under the "downloads" key:

    reader.extra["downloads"] = {
        "daily_quota": -1,        # 用户自己的每日下载配额，-1=跟随全局设置，0=不限制，>0=具体配额
        "download": 1,            # 当天（按 last_download 所在自然日）已下载次数
        "last_download": 1699999999.0,  # 最近一次下载时间，unix 时间戳（秒），用于判断是否跨天
    }

`ENABLE_DOWNLOAD_QUOTA` / `GLOBAL_DOWNLOAD_QUOTA` (webserver/settings.py) control whether the
limit is enforced at all, and the default quota used when a reader hasn't overridden it.

check_and_consume() is the single entry point: it reads the current usage, resets it if the
last download happened on a previous day, checks it against the effective quota and, if there's
room, atomically consumes one unit and persists it. The read-modify-write is guarded by a
per-reader lock so concurrent downloads from the same reader can't race past the same quota
before either save() flushes.
"""

import datetime
import logging
import threading
import time
from typing import NamedTuple

from webserver import loader
from webserver.models import Reader

CONF = loader.get_settings()

DOWNLOAD_QUOTA_FOLLOW_GLOBAL = -1
DOWNLOAD_QUOTA_UNLIMITED = 0


class QuotaResult(NamedTuple):
    allowed: bool
    used: int  # 当天已使用的下载次数（含本次，若allowed为True）
    quota: int  # 生效的配额，0表示不限制


class DownloadQuotaService:
    # 同一用户同一本书同一格式在窗口期内的多次请求（分段、续传、重试）只算一次下载
    CHARGE_WINDOW = 600
    _CHARGED_MAX = 2048
    _charged = {}
    _charged_guard = threading.Lock()

    _locks_guard = threading.Lock()
    _reader_locks = {}

    @classmethod
    def _lock_for(cls, reader_id: int) -> threading.Lock:
        with cls._locks_guard:
            lock = cls._reader_locks.get(reader_id)
            if lock is None:
                lock = threading.Lock()
                cls._reader_locks[reader_id] = lock
            return lock

    @classmethod
    def _effective_quota(cls, daily_quota: int) -> int:
        if daily_quota != DOWNLOAD_QUOTA_FOLLOW_GLOBAL:
            return daily_quota
        try:
            return int(CONF.get("GLOBAL_DOWNLOAD_QUOTA", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def check_and_consume(cls, reader: Reader) -> QuotaResult:
        """检查reader的每日下载配额，若还有余量则原子地消耗一次并落库。

        当ENABLE_DOWNLOAD_QUOTA未开启、或reader为管理员时，始终放行且不改动extra["downloads"]。
        """
        if not CONF.get("ENABLE_DOWNLOAD_QUOTA", False) or reader.is_admin():
            return QuotaResult(True, 0, 0)

        with cls._lock_for(reader.id):
            downloads = reader.extra.get("downloads") if reader.extra else None
            if not isinstance(downloads, dict):
                downloads = {}

            daily_quota = downloads.get("daily_quota", DOWNLOAD_QUOTA_FOLLOW_GLOBAL)
            try:
                daily_quota = int(daily_quota)
            except (TypeError, ValueError):
                daily_quota = DOWNLOAD_QUOTA_FOLLOW_GLOBAL
            quota = cls._effective_quota(daily_quota)

            now = time.time()
            last_download = downloads.get("last_download") or 0
            today = datetime.datetime.fromtimestamp(now).date()
            last_day = datetime.datetime.fromtimestamp(last_download).date() if last_download else None
            used = downloads.get("download", 0) if last_day == today else 0

            if quota != DOWNLOAD_QUOTA_UNLIMITED and used >= quota:
                return QuotaResult(False, used, quota)

            used += 1
            downloads["daily_quota"] = daily_quota
            downloads["download"] = used
            downloads["last_download"] = now
            if not reader.extra:
                reader.extra = {}
            reader.extra["downloads"] = downloads
            try:
                reader.save()
            except Exception:
                logging.error("[download_quota] failed to persist download quota for reader %s", reader.id, exc_info=True)
            return QuotaResult(True, used, quota)

    @classmethod
    def get_usage(cls, reader: Reader) -> QuotaResult:
        """只读地返回reader当天已用下载次数和生效配额，不做跨天重置以外的任何改动/落库。"""
        downloads = reader.extra.get("downloads") if reader.extra else None
        if not isinstance(downloads, dict):
            downloads = {}

        daily_quota = downloads.get("daily_quota", DOWNLOAD_QUOTA_FOLLOW_GLOBAL)
        try:
            daily_quota = int(daily_quota)
        except (TypeError, ValueError):
            daily_quota = DOWNLOAD_QUOTA_FOLLOW_GLOBAL
        quota = cls._effective_quota(daily_quota)

        last_download = downloads.get("last_download") or 0
        today = datetime.datetime.fromtimestamp(time.time()).date()
        last_day = datetime.datetime.fromtimestamp(last_download).date() if last_download else None
        used = downloads.get("download", 0) if last_day == today else 0
        return QuotaResult(True, used, quota)

    @classmethod
    def charge(cls, reader: Reader, book_id, fmt: str, protocol: str, consume_quota: bool = True) -> QuotaResult:
        """一次真实下载的统一入口：窗口期内去重 -> （可选）扣配额 -> 记录下载统计。

        窗口期内重复请求返回allowed=True且不再扣配额/记统计；配额不足返回allowed=False，
        此时既不记统计也不占用窗口，调用方负责拒绝本次下载。
        """
        from webserver.services.reading_stats_service import ReadingStatsService

        key = (reader.id, int(book_id), str(fmt).lower())
        now = time.time()
        with cls._charged_guard:
            if cls._charged.get(key, 0) >= now:
                cls._charged[key] = now + cls.CHARGE_WINDOW
                return cls.get_usage(reader)
        result = cls.check_and_consume(reader) if consume_quota else cls.get_usage(reader)
        if not result.allowed:
            return result
        ReadingStatsService.record_download(reader.id, int(book_id), protocol)
        with cls._charged_guard:
            if len(cls._charged) >= cls._CHARGED_MAX:
                for stale in [k for k, expire in cls._charged.items() if expire < now]:
                    del cls._charged[stale]
            cls._charged[key] = now + cls.CHARGE_WINDOW
        return result
