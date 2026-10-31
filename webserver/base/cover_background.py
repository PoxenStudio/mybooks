#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""封面背景图库：管理员上传的底图，生成动态封面时按书名稳定选一张铺底。"""

import hashlib
import logging
import os
import threading
import time
from io import BytesIO

from PIL import Image, ImageOps

from webserver import loader
from webserver.i18n import _

CONF = loader.get_settings()

COVER_BACKGROUND_DIR = "/data/books/resources/cover_backgrounds"
TARGET_WIDTH = 1200
TARGET_HEIGHT = 1600
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BACKGROUNDS = 50
JPEG_QUALITY = 90
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP", "GIF", "BMP")
_NAME_PREFIX = "bg_"
_NAME_DIGEST_LEN = 16
_LIST_CACHE_TTL = 1.0

_RESAMPLING = getattr(Image, "Resampling", Image)


class CoverBackgroundError(Exception):
    """上传/删除被业务规则拒绝，消息可直接展示给用户。"""


class CoverBackgroundService:
    """目录按内容哈希命名，选图只依赖 seed，因此无需保存「哪本书用了哪张」。"""

    _write_lock = threading.Lock()
    _list_cache = (0.0, ())

    @classmethod
    def directory(cls):
        return COVER_BACKGROUND_DIR

    @classmethod
    def enabled(cls):
        return bool(CONF.get("USE_COVER_BACKGROUND", True))

    @classmethod
    def is_valid_name(cls, name):
        stem, ext = os.path.splitext(os.path.basename(name or ""))
        if ext.lower() != ".jpg" or not stem.startswith(_NAME_PREFIX):
            return False
        digest = stem[len(_NAME_PREFIX):]
        if len(digest) != _NAME_DIGEST_LEN:
            return False
        return all(ch in "0123456789abcdef" for ch in digest)

    @classmethod
    def list_backgrounds(cls):
        """返回排好序的文件名元组；短暂缓存避免逐本书生成封面时反复 listdir。"""
        now = time.time()
        expire, names = cls._list_cache
        if expire > now:
            return names
        try:
            names = tuple(sorted(
                name for name in os.listdir(cls.directory()) if cls.is_valid_name(name)
            ))
        except OSError:
            names = ()
        cls._list_cache = (now + _LIST_CACHE_TTL, names)
        return names

    @classmethod
    def count(cls):
        return len(cls.list_backgrounds())

    @classmethod
    def invalidate_cache(cls):
        cls._list_cache = (0.0, ())

    @classmethod
    def pick_for(cls, seed):
        if not cls.enabled():
            return None
        names = cls.list_backgrounds()
        if not names:
            return None
        digest = hashlib.md5(str(seed).encode("utf-8")).hexdigest()
        index = int(digest, 16) % len(names)
        return os.path.join(cls.directory(), names[index])

    @classmethod
    def _normalize(cls, image):
        """统一裁成 3:4 竖图，透明通道垫白，避免输出尺寸跟着原图走。"""
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            image = image.convert("RGBA")
            canvas = Image.new("RGB", image.size, (255, 255, 255))
            canvas.paste(image, mask=image.split()[-1])
            image = canvas
        else:
            image = image.convert("RGB")
        image = ImageOps.fit(image, (TARGET_WIDTH, TARGET_HEIGHT), method=_RESAMPLING.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buffer.getvalue()

    @classmethod
    def save(cls, fileinfo):
        """校验并入库，返回文件名；同内容重复上传按幂等成功处理。"""
        body = (fileinfo or {}).get("body") or b""
        if not body:
            raise CoverBackgroundError(_("请选择要上传的图片"))
        if len(body) > MAX_UPLOAD_BYTES:
            raise CoverBackgroundError(_("图片不能超过 10MB"))
        with cls._write_lock:
            if cls.count() >= MAX_BACKGROUNDS:
                raise CoverBackgroundError(_("背景图库最多 %d 张，请先删除再上传") % MAX_BACKGROUNDS)
        try:
            with Image.open(BytesIO(body)) as image:
                if (image.format or "").upper() not in ALLOWED_FORMATS:
                    raise CoverBackgroundError(_("只支持 JPEG、PNG、WEBP 格式的图片"))
                data = cls._normalize(image)
        except CoverBackgroundError:
            raise
        except Exception:
            logging.warning("[CoverBackground] 无法解析上传的图片")
            raise CoverBackgroundError(_("图片文件无法解析，请换一张试试"))

        name = _NAME_PREFIX + hashlib.md5(data).hexdigest()[:_NAME_DIGEST_LEN] + ".jpg"
        os.makedirs(cls.directory(), exist_ok=True)
        path = os.path.join(cls.directory(), name)
        if not os.path.exists(path):
            temp_path = path + ".tmp"
            with open(temp_path, "wb") as stream:
                stream.write(data)
            os.replace(temp_path, path)
        cls.invalidate_cache()
        return name

    @classmethod
    def delete(cls, name):
        if not cls.is_valid_name(name):
            raise CoverBackgroundError(_("背景图不存在"))
        path = os.path.join(cls.directory(), name)
        if not os.path.exists(path):
            return False
        os.remove(path)
        cls.invalidate_cache()
        return True

    @classmethod
    def read(cls, name):
        if not cls.is_valid_name(name):
            return None
        try:
            with open(os.path.join(cls.directory(), name), "rb") as stream:
                return stream.read()
        except OSError:
            return None
