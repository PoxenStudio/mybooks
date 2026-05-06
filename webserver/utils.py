#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import datetime
import logging
import re
import traceback
from webserver.i18n import _
from webserver.constants import CALIBRE_COLUMN_BOOK_TYPE, CALIBRE_COLUMN_PHY_COUNT
from webserver.constants import CALIBRE_COLUMN_EXT_LINK, CALIBRE_COLUMN_CATEGORY
from webserver.constants import BOOK_TYPE_EBOOK, CALIBRE_COLUMN_DYNAMIC_COVER


# 匹配包含z-library的括号内容，例如 (z-library.sk, 1lib.sk, z-lib.sk)
ZLIBRARY_PATTERN = re.compile(r'\([^)]*?(?:z-?lib(?:rary)?|1lib)[^)]*?\)', re.IGNORECASE)


def remove_zlibrary_suffix(text):
    """移除文件名中包含z-library的括号内容"""
    if not text:
        return text
    return ZLIBRARY_PATTERN.sub('', text).strip()


def guess_title_author_from_filename(name):
    if not name:
        return name, None
    title = name.strip()
    author = None
    if "作者" in title:
        parts = re.split(r"作者[:：]", title, maxsplit=1)
        if len(parts) >= 2:
            title = parts[0].strip()
            author = parts[1].strip()
            # 去除title尾部的([（，【四种符号，author尾部的）】]四种符号
            title = re.sub(r'[\s\(\[【（，,、]+$', '', title)
            if title.startswith('《') and title.endswith('》'):
                title = title[1:-1]
            author = re.sub(r'[\s\)\]】）]+$', '', author)
    return title, author


def ascii_text(orig):
    from calibre.utils.localization import get_udc
    from calibre.constants import preferred_encoding
    udc = get_udc()
    try:
        ascii = udc.decode(orig)
    except Exception:
        if isinstance(orig, str):
            orig = orig.encode('ascii', 'replace')
        ascii = orig.decode(preferred_encoding, 'replace')
    if isinstance(ascii, bytes):
        ascii = ascii.decode('ascii', 'replace')
    return ascii.strip()


def get_title_sort(title):
    if not title:
        return title
    try:
        return ascii_text(title).lower()
    except Exception as e:
        logging.error(f"Error converting title to ASCII for sorting: {e}")
        return title


class SimpleBookFormatter:
    """格式化calibre book的字段"""

    def __init__(self, calibre_book_item, cdn_url):
        self.cdn_url = cdn_url
        self.book = calibre_book_item

    def get_collector(self):
        collector = self.book.get("collector", None)
        if isinstance(collector, dict):
            collector = collector.get("username", None)
        elif collector:
            collector = collector.username
        return collector

    def val(self, k, default_value=_("Unknown")):
        v = self.book.get(k, None)
        if not v:
            v = default_value
        if isinstance(v, datetime.datetime):
            return f'{v.year:04}-{v.month:02}-{v.day:02}'
        return v

    def get_files(self):
        files = []
        for fmt in self.book.get("available_formats", []):
            item = {
                "format": fmt,
                "size": 0
            }
            files.append(item)
        return files

    def format(self, include_comments=True):
        b = self.book
        b["ts"] = int(b["timestamp"].timestamp())
        category = self.val(CALIBRE_COLUMN_CATEGORY, '').strip()
        book_type = self.val(CALIBRE_COLUMN_BOOK_TYPE, self.book.get("book_type", BOOK_TYPE_EBOOK))
        book_count = self.val(CALIBRE_COLUMN_PHY_COUNT, self.book.get("book_count", 1))
        ext_link = self.val(CALIBRE_COLUMN_EXT_LINK, '').strip()
        dynamic_cover = self.book.get(CALIBRE_COLUMN_DYNAMIC_COVER, 0)
        return {
            "id": b["id"],
            "title": b["title"],
            "rating": b["rating"],
            "timestamp": self.val("timestamp"),
            "pubdate": self.val("pubdate"),
            "author": ", ".join(b["authors"]),
            "authors": b["authors"],
            "author_sort": self.val("author_sort"),
            "tag": " / ".join(b["tags"]),
            "tags": b["tags"],
            "publisher": self.val("publisher"),
            "comments": self.val("comments", _(u"暂无简介")) if include_comments else "",
            "series": self.val("series", None),
            "languages": self.val("languages", None),
            "isbn": self.val("isbn", None),
            "img": self.cdn_url + "/get/cover/%(id)s.jpg?t=%(ts)s" % b,
            "thumb": self.cdn_url + "/get/thumb_240_320/%(id)s.jpg?t=%(ts)s&size=240x320" % b,
            # 额外填充的字段
            "collector": self.get_collector(),
            "count_visit": self.val("count_visit", 0),
            "count_download": self.val("count_download", 0),
            "sole": self.val("sole", False),
            "has_audio": self.val("has_audio", 0),
            "book_type": self.book.get("book_type", book_type),
            "book_count": self.book.get("book_count", book_count),
            "state": self.book.get("state", {}),
            'category': category,
            'ext_link': ext_link,
            'files': self.get_files(),
            'dynamic_cover': dynamic_cover,
        }


class MCPBookFormatter:
    """格式化calibre book的字段"""

    def __init__(self, calibre_book_item, cdn_url):
        self.cdn_url = cdn_url
        self.book = calibre_book_item

    def val(self, k, default_value=_("Unknown")):
        v = self.book.get(k, None)
        if not v:
            v = default_value
        if isinstance(v, datetime.datetime):
            return f'{v.year:04}-{v.month:02}-{v.day:02}'
        return v

    def format(self, include_comments=True):
        b = self.book
        b["ts"] = b["timestamp"].strftime("%s")
        return {
            "id": b["id"],
            "title": b["title"],
            "rating": b["rating"],
            "pubdate": self.val("pubdate"),
            "author": ", ".join(b["authors"]),
            "tag": " / ".join(b["tags"]),
            "publisher": self.val("publisher"),
            "comments": self.val("comments", _(u"暂无简介")) if include_comments else "",
            "languages": self.val("languages", None),
            "isbn": self.val("isbn", None),
            'category': self.val('#category', ''),
        }


class BookFormatter:
    def __init__(self, tornado_handler, calibre_book_item):
        self.db = tornado_handler.calibre_db
        self.book = calibre_book_item
        self.cdn_url = tornado_handler.cdn_url
        self.api_url = tornado_handler.api_url
        self.handler = tornado_handler

    def get_files(self):
        files = []
        book_id = self.book["id"]
        for fmt in self.book.get("available_formats", []):
            try:
                filesize = self.db.sizeof_format(book_id, fmt, index_is_id=True)
            except:
                continue
            item = {
                "format": fmt,
                "size": filesize,
                "href": self.cdn_url + "/api/book/%s.%s" % (book_id, fmt),
            }
            files.append(item)
        return files

    def get_permissions(self):
        h = self.handler
        return {
            # 图书权限数据
            "is_public": True,
            "is_owner": h.is_admin() or h.is_book_owner(self.book["id"], h.user_id()),
        }

    def format(self, with_files=False, with_perms=False, include_comments=True):
        f = SimpleBookFormatter(self.book, self.cdn_url)
        data = f.format(include_comments=include_comments)
        data.update(
            {
                "author_url": self.api_url + "/author/" + f.val("author_sort"),
                "publisher_url": self.api_url + "/publisher/" + f.val("publisher"),
            }
        )
        if with_files:
            data["files"] = self.get_files()
        if with_perms:
            data.update(self.get_permissions())
        return data


def compare_books_by_rating_or_id(x, y):
    a = x.get("rating", 0) or 0
    b = y.get("rating", 0) or 0

    if a > b:
        return 1
    elif a < b:
        return -1
    elif x["id"] > y["id"]:
        return 1
    else:
        return -1


def super_strip(s):
    # 删除掉所有不可见的字符
    # issue: https://github.com/talebook/talebook/issues/304
    return ''.join(c for c in s.strip() if c.isprintable())


class ReadingStateFormatter:
    """处理阅读状态数据格式化的工具类"""

    @staticmethod
    def format_reading_state(reading_state):
        """
        将ReadingState对象转换为字典格式

        Args:
            reading_state: ReadingState对象

        Returns:
            dict: 格式化的状态数据
        """
        if not reading_state:
            return {
                "favorite": 0,
                "favorite_date": None,
                "wants": 0,
                "wants_date": None,
                "read_state": 0,
                "read_date": None,
                "online_read": 0,
                "download": 0
            }

        return {
            "favorite": reading_state.favorite,
            "favorite_date": reading_state.favorite_date.isoformat() if reading_state.favorite_date else None,
            "wants": reading_state.wants,
            "wants_date": reading_state.wants_date.isoformat() if reading_state.wants_date else None,
            "read_state": reading_state.read_state,
            "read_date": reading_state.read_date.isoformat() if reading_state.read_date else None,
            "online_read": reading_state.online_read or 0,
            "download": reading_state.download or 0
        }

    @staticmethod
    def format_reading_state_with_api_format(reading_state):
        """
        将ReadingState对象转换为API返回格式的字典
        用于单个书籍状态查询的场景

        Args:
            reading_state: ReadingState对象

        Returns:
            dict: 格式化的状态数据（包含err字段）
        """
        if reading_state:
            return {
                "err": "ok",
                "read_state": reading_state.get_read_state(),
                "favorite": reading_state.is_favorite(),
                "wants": reading_state.is_wants(),
                "online_read": reading_state.online_read or 0,
                "download": reading_state.download or 0,
                "read_date": reading_state.read_date.isoformat() if reading_state.read_date else None,
                "favorite_date": reading_state.favorite_date.isoformat() if reading_state.favorite_date else None,
                "wants_date": reading_state.wants_date.isoformat() if reading_state.wants_date else None
            }
        else:
            return {
                "err": "ok",
                "read_state": 0,
                "favorite": False,
                "wants": False,
                "online_read": 0,
                "download": 0,
                "read_date": None,
                "favorite_date": None,
                "wants_date": None
            }


class ImageHelper:
    """图片处理辅助类，添加图章等操作"""

    @staticmethod
    def add_stamp_to_image(cover_data, stamp_path, position="bottom-right"):
        try:
            from PIL import Image
            import io

            # 加载原始封面
            cover_img = Image.open(io.BytesIO(cover_data))
            if cover_img.mode != 'RGB' and cover_img.mode != 'RGBA':
                cover_img = cover_img.convert('RGBA')

            # 加载图章
            stamp_img = Image.open(stamp_path)
            if stamp_img.mode != 'RGBA':
                stamp_img = stamp_img.convert('RGBA')

            # 获取封面尺寸
            cover_width, cover_height = cover_img.size

            # 将封面分成5x5网格
            grid_width = cover_width // 5
            grid_height = cover_height // 5

            # 根据位置确定网格坐标（5x5网格）
            position_map = {
                "top-left": (0, 0),
                "top-center": (2, 0),
                "top-right": (4, 0),
                "center-left": (0, 2),
                "center": (2, 2),
                "center-right": (4, 2),
                "bottom-left": (0, 4),
                "bottom-center": (2, 4),
                "bottom-right": (4, 4),
            }

            grid_x, grid_y = position_map.get(position, (4, 4))  # 默认右下

            # 计算网格区域
            region_x = grid_x * grid_width
            region_y = grid_y * grid_height

            # 计算图章缩放尺寸（占网格区域的80%）
            target_size = int(min(grid_width, grid_height) * 0.8)

            # 保持图章宽高比缩放
            stamp_width, stamp_height = stamp_img.size
            if stamp_width > stamp_height:
                new_width = target_size
                new_height = int(stamp_height * target_size / stamp_width)
            else:
                new_height = target_size
                new_width = int(stamp_width * target_size / stamp_height)

            # 缩放图章
            stamp_resized = stamp_img.resize((new_width, new_height), Image.LANCZOS)

            # 计算图章在网格中居中的位置
            paste_x = region_x + (grid_width - new_width) // 2
            paste_y = region_y + (grid_height - new_height) // 2

            # 确保坐标非负
            paste_x = max(0, paste_x)
            paste_y = max(0, paste_y)

            # 创建新图片（确保是RGBA模式以支持透明度）
            if cover_img.mode != 'RGBA':
                cover_img = cover_img.convert('RGBA')

            # 粘贴图章（使用alpha通道作为mask）
            cover_img.paste(stamp_resized, (paste_x, paste_y), stamp_resized)

            # 转换回RGB（如果原始是RGB）并保存
            output = io.BytesIO()
            if cover_data[:3] == b'\xff\xd8\xff':  # JPEG格式
                if cover_img.mode == 'RGBA':
                    cover_img = cover_img.convert('RGB')
                cover_img.save(output, format='JPEG', quality=95)
            else:  # PNG或其他格式
                cover_img.save(output, format='PNG')

            return output.getvalue()

        except Exception as e:
            logging.error(f"Error adding stamp to image: {e}")
            logging.error(traceback.format_exc())
            return None


if __name__ == "__main__":
    # 测试_guess_title_author_from_filename
    test_cases = [
        "《宝鉴》（校对版全本）作者：打眼",
        "《三体》作者：刘慈欣",
        "《平凡的世界（》作者：路遥",
        "《无人生还》(作者：阿加莎·克里斯蒂)",
    ]
    for filename in test_cases:
        title, author = guess_title_author_from_filename(filename)
        print(f"Filename: {filename}\n  Title: {title}\n  Author: {author}\n")
