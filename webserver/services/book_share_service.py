#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
书籍匿名分享链接，设计见 document/Share_Visits_GuestBooklist_Design.md。

访客验证通过后获得授权 cookie（share_grants），后续阅读/下载请求按 cookie 实时校验分享状态。
"""

import datetime
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from webserver.models import BookShare

GRANT_COOKIE = "share_grants"
GRANT_TTL_SECONDS = 24 * 3600
MAX_PASSWORD_LEN = 32
MAX_FAILURES = 5
LOCK_SECONDS = 600
SHARED_IDS_TTL_SECONDS = 60

RESULT_OK = "ok"
RESULT_INVALID = "invalid"
RESULT_BAD_PASSWORD = "bad_password"
RESULT_LOCKED = "locked"


class ShareParamError(ValueError):
    pass


class BookShareService:
    _failures: Dict[Tuple[str, str], List[float]] = {}
    _failures_lock = threading.Lock()
    _shared_ids: Set[int] = set()
    _shared_ids_time = 0.0

    @staticmethod
    def fingerprint(share: BookShare) -> str:
        return hashlib.sha256(("%s:%s" % (share.token, share.password)).encode("utf-8")).hexdigest()[:16]

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._shared_ids_time = 0.0

    @classmethod
    def get_by_book(cls, book_id: int) -> Optional[BookShare]:
        return BookShare._session().query(BookShare).filter_by(book_id=book_id).one_or_none()

    @classmethod
    def get_by_token(cls, token: str) -> Optional[BookShare]:
        if not token or len(token) > 64:
            return None
        return BookShare._session().query(BookShare).filter_by(token=token).one_or_none()

    @classmethod
    def get_by_id(cls, share_id: int) -> Optional[BookShare]:
        return BookShare._session().query(BookShare).filter_by(id=share_id).one_or_none()

    @classmethod
    def create_or_update(
        cls,
        book_id: int,
        creator_id: int,
        allow_read: bool,
        allow_download: bool,
        expire_days: int,
        max_views: int,
        password: Optional[str] = None,
    ) -> BookShare:
        """expire_days: 0 永久，-1 保持原有效期（仅更新时有意义），>0 从现在起的天数。password 为 None 表示不修改。"""
        if not (allow_read or allow_download):
            raise ShareParamError("at least one permission is required")
        if max_views < 0 or expire_days < -1:
            raise ShareParamError("invalid limits")
        if password is not None:
            password = password.strip()
            if len(password) > MAX_PASSWORD_LEN:
                raise ShareParamError("password too long")
        db = BookShare._session()
        row = cls.get_by_book(book_id)
        now = datetime.datetime.now()
        expire_time = now + datetime.timedelta(days=expire_days) if expire_days > 0 else None
        reset = False
        if row is None:
            row = BookShare(book_id, secrets.token_urlsafe(16), creator_id, password or "", allow_read, allow_download, expire_time, max_views)
            db.add(row)
        else:
            if row.status != BookShare.STATUS_ACTIVE:
                reset = True
                row.token = secrets.token_urlsafe(16)
                row.view_count = 0
                row.status = BookShare.STATUS_ACTIVE
                row.creator_id = creator_id
                row.create_time = now
                if password is None:
                    row.password = ""
            if password is not None:
                row.password = password
            row.allow_read = allow_read
            row.allow_download = allow_download
            row.max_views = max_views
            if expire_days != -1 or reset:
                row.expire_time = expire_time
            row.update_time = now
        db.commit()
        cls.invalidate_cache()
        return row

    @classmethod
    def cancel(cls, share_id: int) -> bool:
        row = cls.get_by_id(share_id)
        if row is None:
            return False
        db = BookShare._session()
        row.status = BookShare.STATUS_CANCELLED
        row.update_time = datetime.datetime.now()
        db.commit()
        cls.invalidate_cache()
        return True

    @classmethod
    def delete(cls, share_id: int) -> bool:
        db = BookShare._session()
        count = db.query(BookShare).filter_by(id=share_id).delete(synchronize_session=False)
        db.commit()
        cls.invalidate_cache()
        return count > 0

    @classmethod
    def delete_for_book(cls, book_id: int) -> None:
        db = BookShare._session()
        db.query(BookShare).filter_by(book_id=book_id).delete(synchronize_session=False)
        db.commit()
        cls.invalidate_cache()

    @classmethod
    def list_page(cls, start: int, limit: int) -> Tuple[List[BookShare], int]:
        query = BookShare._session().query(BookShare)
        total = query.count()
        rows = query.order_by(BookShare.update_time.desc(), BookShare.id.desc()).offset(start).limit(limit).all()
        return rows, total

    @classmethod
    def state_of(cls, share: BookShare) -> str:
        if share.status != BookShare.STATUS_ACTIVE:
            return "cancelled"
        if share.is_expired():
            return "expired"
        if share.is_exhausted():
            return "exhausted"
        return "active"

    @classmethod
    def shared_book_ids(cls) -> Set[int]:
        now = time.time()
        if now - cls._shared_ids_time > SHARED_IDS_TTL_SECONDS:
            rows = BookShare._session().query(BookShare).filter_by(status=BookShare.STATUS_ACTIVE).all()
            cls._shared_ids = {row.book_id for row in rows if row.is_valid()}
            cls._shared_ids_time = now
        return cls._shared_ids

    @classmethod
    def verify(cls, share: BookShare, password: str, ip: str) -> str:
        key = (ip, share.token)
        now = time.time()
        with cls._failures_lock:
            record = cls._failures.get(key)
            if record and record[1] > now:
                return RESULT_LOCKED
        if not share.is_valid():
            return RESULT_INVALID
        if share.password and not hmac.compare_digest((password or "").encode("utf-8"), share.password.encode("utf-8")):
            with cls._failures_lock:
                record = cls._failures.get(key)
                if record is None or record[1] and record[1] <= now:
                    record = [0, 0.0]
                record[0] += 1
                if record[0] >= MAX_FAILURES:
                    record[1] = now + LOCK_SECONDS
                    record[0] = 0
                cls._failures[key] = record
            return RESULT_BAD_PASSWORD
        with cls._failures_lock:
            cls._failures.pop(key, None)
        db = BookShare._session()
        share.view_count += 1
        share.update_time = datetime.datetime.now()
        db.commit()
        cls.invalidate_cache()
        return RESULT_OK

    @classmethod
    def _read_grants(cls, handler) -> Dict[str, list]:
        raw = handler.get_secure_cookie(GRANT_COOKIE)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def _grant_matches(cls, grants: Dict[str, list], share: BookShare) -> bool:
        entry = grants.get(str(share.id))
        if not isinstance(entry, list) or len(entry) != 2:
            return False
        fingerprint, issued = entry
        if not isinstance(issued, (int, float)) or time.time() - issued > GRANT_TTL_SECONDS:
            return False
        return hmac.compare_digest(str(fingerprint), cls.fingerprint(share))

    @classmethod
    def has_grant(cls, handler, share: BookShare) -> bool:
        if share.status != BookShare.STATUS_ACTIVE or share.is_expired():
            return False
        return cls._grant_matches(cls._read_grants(handler), share)

    @classmethod
    def issue_grant(cls, handler, share: BookShare) -> None:
        grants = {}
        for share_id, entry in cls._read_grants(handler).items():
            if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], (int, float)) and time.time() - entry[1] <= GRANT_TTL_SECONDS:
                grants[share_id] = entry
        grants[str(share.id)] = [cls.fingerprint(share), int(time.time())]
        handler.set_secure_cookie(GRANT_COOKIE, json.dumps(grants))

    @classmethod
    def granted_share(cls, handler, book_id) -> Optional[BookShare]:
        grants = cls._read_grants(handler)
        if not grants:
            return None
        try:
            book_id = int(book_id)
        except (TypeError, ValueError):
            return None
        share = cls.get_by_book(book_id)
        if share is None or share.status != BookShare.STATUS_ACTIVE or share.is_expired():
            return None
        return share if cls._grant_matches(grants, share) else None

    @classmethod
    def any_grant(cls, handler) -> bool:
        grants = cls._read_grants(handler)
        ids = [int(key) for key in grants if str(key).isdigit()]
        if not ids:
            return False
        rows = BookShare._session().query(BookShare).filter(BookShare.id.in_(ids)).all()
        return any(row.status == BookShare.STATUS_ACTIVE and not row.is_expired() and cls._grant_matches(grants, row) for row in rows)
