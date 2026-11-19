#!/usr/bin/env python3
"""
EPUB 文件辅助工具
@author: PoxenStudio, 2026
"""

import io
import logging
import zipfile
from pathlib import Path

from webserver.base.image_helper import ImageHelper


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

                # 部分 EPUB 的封面文件只是占位/损坏图片，或 Qt 不支持的 webp，
                # 直接交给 calibre 写封面会失败并留下 0 字节 cover.jpg
                image_data = ImageHelper.sanitize_cover_data((None, image_data))[1]
                if not image_data:
                    logging.warning(
                        "EpubHelper: 封面图片无法解码，已忽略: %s", cover_filename
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
            zip_file = Path(filename)
            if len(zip_file.name) < 6:
                continue
            lower = filename.lower()
            stem = zip_file.stem
            ext = zip_file.suffix
            if ext in IMAGE_EXTS:
                if not first_image:
                    first_image = filename
                if "cover" in stem:
                    return filename

        return first_image
