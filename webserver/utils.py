#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import logging
import re
import traceback


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


# 常见繁体中文专有字符（在 Simplified 中对应不同字形），用于 fallback 检测
_TRADITIONAL_ONLY_CHARS = frozenset(
    "書電來說話這個時會對學問國務現實際應當來們點進開關處還"
    "歡樂體動設計資訊傳說標準環境網絡變換預算發展運動認識"
    "義務條件結構機制選擇統計監督繼續識別溝通維護數據處理"
    "歷史文化藝術哲學經濟組織機構協議協作協調決策執行方針"
    "與並從內外長短廣狹強弱快慢遠近輕重高低深淺寬窄早晚"
    "後前左右東西南北上下中外新舊多少大小"
    # 常見繁體字
    "與與來來說說國國時時個個會對對學問問處還還變發電書樂"
)


def _fallback_has_traditional(text: str) -> bool:
    return any(c in _TRADITIONAL_ONLY_CHARS for c in text)


def is_traditional_chinese(text: str) -> bool:
    if not text:
        return False
    # 若全为 ASCII，直接跳过
    if all(ord(c) < 128 for c in text):
        return False

    try:
        import opencc
        converter = opencc.OpenCC("t2s")
        converted = converter.convert(text)
        return converted != text
    except Exception as exc:
        logging.debug("[review_cht] OpenCC unavailable (%s), using fallback", exc)
        return _fallback_has_traditional(text)


def compare_books_by_rating_or_id(x, y):
    a = x.get("rating", 0)
    b = y.get("rating", 0)

    if a != b:
        return 1 if a > b else -1
    return 1 if x["id"] > y["id"] else -1


def compare_books_by_series_index_or_name(x, y):
    x_index = x.get("series_index", 0)
    y_index = y.get("series_index", 0)

    if x_index != y_index:
        return 1 if x_index > y_index else -1

    x_title_sort = x.get("title_sort", "")
    y_title_sort = x.get("title_sort", "")
    return 1 if x_title_sort > y_title_sort else -1


def super_strip(s):
    # 删除掉所有不可见的字符
    # issue: https://github.com/talebook/talebook/issues/304
    return ''.join(c for c in s.strip() if c.isprintable())


# 为保持向后兼容，从新位置重新导出
from webserver.base.formatter import SimpleBookFormatter, MCPBookFormatter, BookFormatter, ReadingStateFormatter

__all__ = ["SimpleBookFormatter", "MCPBookFormatter", "BookFormatter", "ReadingStateFormatter"]


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
