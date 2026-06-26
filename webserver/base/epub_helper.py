#!/usr/bin/env python3
"""
EPUB 文件辅助工具
@author: PoxenStudio, 2026
"""

import io
import logging
import zipfile
from pathlib import Path


class EpubHelper:
    """EPUB 文件处理辅助类"""

    @staticmethod
    def extract_cover(epub_path):
        """
        从 EPUB 文件中提取封面图片，以 BytesIO 形式返回。
        """
        epub_path = str(epub_path)
        try:
            with zipfile.ZipFile(epub_path, "r") as zf:
                file_list = zf.namelist()

                cover_filename = EpubHelper._find_cover_in_zip(file_list)

                if not cover_filename:
                    logging.warning(
                        "EpubHelper: 在 EPUB 中未找到封面图片文件: %s", epub_path
                    )
                    return None

                image_data = zf.read(cover_filename)
                if not image_data:
                    logging.warning(
                        "EpubHelper: 读取到的封面数据为空: %s", cover_filename
                    )
                    return None

                logging.info(
                    "EpubHelper: 成功从 %s 提取封面 %s (%d 字节)",
                    epub_path,
                    cover_filename,
                    len(image_data),
                )
                buf = io.BytesIO(image_data)
                buf.seek(0)
                return buf

        except zipfile.BadZipFile:
            logging.error("EpubHelper: EPUB/ZIP 文件损坏: %s", epub_path)
        except FileNotFoundError:
            logging.error("EpubHelper: 文件不存在: %s", epub_path)
        except Exception as e:
            logging.error("EpubHelper: 提取封面时出错 (%s): %s", epub_path, e)

        return None

    @staticmethod
    def _find_cover_in_zip(file_list):
        IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

        for filename in file_list:
            lower = filename.lower()
            if lower.endswith("cover.jpg") or lower.endswith("cover.jpeg"):
                return filename

        first_image = None
        for filename in file_list:
            lower = filename.lower()
            stem = Path(lower).stem
            ext = Path(lower).suffix
            if ext in IMAGE_EXTS:
                if not first_image:
                    first_image = filename
                if "cover" in stem:
                    return filename

        return first_image
