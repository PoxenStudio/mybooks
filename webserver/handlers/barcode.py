#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import os
import tempfile
import logging
from pyzbar.pyzbar import decode
from PIL import Image

from webserver.handlers.base import BaseHandler, auth, js


class BarcodeRecognition(BaseHandler):
    @js
    @auth
    def post(self):
        """识别图片中的条形码"""
        try:
            # 获取上传的图片文件
            fileinfo = self.request.files.get('barcode_image')
            if not fileinfo:
                return {"err": "no_file", "msg": "未选择图片文件"}

            fileinfo = fileinfo[0]
            img_data = fileinfo['body']

            # 创建临时文件保存图片
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                temp_file.write(img_data)
                temp_file_path = temp_file.name

            try:
                # 打开图片并识别条形码
                image = Image.open(temp_file_path)
                decoded_objects = decode(image)

                if not decoded_objects:
                    return {"err": "no_barcode", "msg": "未在图片中识别到条形码"}

                # 查找13位或10位的ISBN条形码
                isbn_candidates = []
                for obj in decoded_objects:
                    data = obj.data.decode('utf-8', errors='ignore')
                    # 移除非数字字符（除了X）
                    clean_data = ''.join(c for c in data if c.isdigit() or c.upper() == 'X')

                    # 检查是否为有效的ISBN长度
                    if len(clean_data) == 13 or len(clean_data) == 10:
                        isbn_candidates.append(clean_data)

                if isbn_candidates:
                    # 优先返回13位ISBN
                    isbn13 = [isbn for isbn in isbn_candidates if len(isbn) == 13]
                    if isbn13:
                        return {"err": "ok", "isbn": isbn13[0]}
                    else:
                        return {"err": "ok", "isbn": isbn_candidates[0]}
                else:
                    # 如果没有找到标准长度的ISBN，返回第一个识别到的条形码
                    first_barcode = decoded_objects[0].data.decode('utf-8', errors='ignore')
                    return {"err": "no_isbn", "msg": f"识别到条形码但不是标准ISBN格式: {first_barcode}"}

            finally:
                # 清理临时文件
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            logging.error(f"条形码识别失败: {str(e)}")
            return {"err": "recognition_failed", "msg": f"条形码识别失败: {str(e)}"}


def routes():
    return [
        (r"/api/admin/barcode", BarcodeRecognition),
    ]
