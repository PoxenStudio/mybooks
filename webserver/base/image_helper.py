#!/usr/bin/env python3
"""
图片处理工具
@author: PoxenStudio, 2026
"""

import io
import logging
import traceback
from PIL import Image


class ImageHelper:
    """图片处理辅助类，添加图章等操作"""

    @staticmethod
    def add_stamp_to_image(cover_data, stamp_path, position="bottom-right"):
        try:
            cover_img = Image.open(io.BytesIO(cover_data))
            if cover_img.mode != 'RGB' and cover_img.mode != 'RGBA':
                cover_img = cover_img.convert('RGBA')
            stamp_img = Image.open(stamp_path)
            if stamp_img.mode != 'RGBA':
                stamp_img = stamp_img.convert('RGBA')

            cover_width, cover_height = cover_img.size
            grid_width = cover_width // 5
            grid_height = cover_height // 5

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

            grid_x, grid_y = position_map.get(position, (4, 4))
            region_x = grid_x * grid_width
            region_y = grid_y * grid_height
            target_size = int(min(grid_width, grid_height) * 0.8)

            stamp_width, stamp_height = stamp_img.size
            if stamp_width > stamp_height:
                new_width = target_size
                new_height = int(stamp_height * target_size / stamp_width)
            else:
                new_height = target_size
                new_width = int(stamp_width * target_size / stamp_height)

            stamp_resized = stamp_img.resize((new_width, new_height), Image.LANCZOS)
            paste_x = region_x + (grid_width - new_width) // 2
            paste_y = region_y + (grid_height - new_height) // 2
            paste_x = max(0, paste_x)
            paste_y = max(0, paste_y)
            if cover_img.mode != 'RGBA':
                cover_img = cover_img.convert('RGBA')

            cover_img.paste(stamp_resized, (paste_x, paste_y), stamp_resized)

            output = io.BytesIO()
            if cover_data[:3] == b'\xff\xd8\xff':
                if cover_img.mode == 'RGBA':
                    cover_img = cover_img.convert('RGB')
                cover_img.save(output, format='JPEG', quality=90)
            else:
                cover_img.save(output, format='PNG')

            return output.getvalue()

        except Exception as e:
            logging.error(f"Error adding stamp to image: {e}")
            logging.error(traceback.format_exc())
            return None

    @staticmethod
    def convert_to_jpeg(image_data, quality=90):
        img = Image.open(io.BytesIO(image_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality)
        return output.getvalue()

    @staticmethod
    def _get_white_border_thickness(img, tolerance=200):
        """
        计算图像四周符合纯白（R, G, B 均大于等于 tolerance）的白边厚度。
        """
        width, height = img.size
        pixels = img.load()

        def is_white(p):
            if isinstance(p, tuple):
                return p[0] >= tolerance and p[1] >= tolerance and p[2] >= tolerance
            return p >= tolerance

        top = 0
        for y in range(height):
            if all(is_white(pixels[x, y]) for x in range(width)):
                top += 1
            else:
                break

        bottom = 0
        for y in range(height - 1, -1, -1):
            if all(is_white(pixels[x, y]) for x in range(width)):
                bottom += 1
            else:
                break

        left = 0
        for x in range(width):
            if all(is_white(pixels[x, y]) for y in range(height)):
                left += 1
            else:
                break

        right = 0
        for x in range(width - 1, -1, -1):
            if all(is_white(pixels[x, y]) for y in range(height)):
                right += 1
            else:
                break

        return left, top, right, bottom

    @staticmethod
    def crop_white_borders(image_data, color_threshold=200, symmetry_error=3, margin=2):
        """
        根据对称性裁剪白边
        :param image_data: 输入图片数据 (bytes)
        :param color_threshold: 判定为白色的阈值（默认200以上）
        :param symmetry_error: 对称判定的误差范围（像素单位）
        :param margin: 需要保留的边缘大小
        :return: 裁剪后的图片数据 (bytes)，如果没有裁剪则返回 None
        """
        img = Image.open(io.BytesIO(image_data)).convert("RGB")
        width, height = img.size
        logging.info(f"原始图片尺寸: {width}x{height}，开始检测白边...")
        left, top, right, bottom = ImageHelper._get_white_border_thickness(img, color_threshold)
        logging.info(f"检测到的白边厚度 - 左: {left}px, 上: {top}px, 右: {right}px, 下: {bottom}px")
        crop_left, crop_top, crop_right, crop_bottom = 0, 0, width, height
        need_crop = False

        width_symmetry_error = max(symmetry_error, width * 0.01)
        if left > 0 and right > 0 and abs(left - right) <= width_symmetry_error:
            actual_crop_left = max(0, left - margin)
            actual_crop_right = max(0, right - margin)

            if actual_crop_left > 0 or actual_crop_right > 0:
                crop_left = actual_crop_left
                crop_right = width - actual_crop_right
                need_crop = True
                logging.info(f"检测到左右对称白边: 左 {left}px, 右 {right}px。保留 {margin}px 边缘进行左右裁剪。")

        height_symmetry_error = max(symmetry_error, height * 0.01)
        if top > 0 and bottom > 0 and abs(top - bottom) <= height_symmetry_error:
            actual_crop_top = max(0, top - margin)
            actual_crop_bottom = max(0, bottom - margin)

            if actual_crop_top > 0 or actual_crop_bottom > 0:
                crop_top = actual_crop_top
                crop_bottom = height - actual_crop_bottom
                need_crop = True
                logging.info(f"检测到上下对称白边: 上 {top}px, 下 {bottom}px。保留 {margin}px 边缘进行上下裁剪。")

        if not need_crop and (height / width <= 1.1 and height / width >= 0.9):
            logging.info("图片接近正方形，强制进行裁剪以去除可能的单边白边。")
            need_crop = True
            border_top = max(0, top - margin)
            border_bottom = max(0, bottom - margin)
            border_top = border_bottom = max(min(border_top, border_bottom), 0)
            border_left = max(0, left - margin)
            border_right = max(0, right - margin)
            border_left = border_right = max(min(border_left, border_right), 0)
            if border_top > 0 and border_bottom > 0 and border_top > border_left and border_top > border_right:
                crop_top = max(0, border_bottom)
                crop_bottom = max(0, height - border_bottom)
                need_crop = True
            if border_left > 0 and border_right > 0 and border_left > border_top and border_left > border_bottom:
                crop_left = max(0, border_left)
                crop_right = max(0, width - border_right)
                need_crop = True

        if need_crop:
            cropped_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))
            output = io.BytesIO()
            if cropped_img.size == img.size:
                logging.info("裁剪后尺寸与原图相同，跳过保存，已保留原样。")
                return None
            if cropped_img.size < (width * 0.45, height * 0.45):
                logging.warning(f"裁剪后尺寸过小: {cropped_img.size}，可能是误裁剪，已保留原样。")
                return None
            if image_data[:3] == b'\xff\xd8\xff':
                if cropped_img.mode == 'RGBA':
                    cropped_img = cropped_img.convert('RGB')
                cropped_img.save(output, format='JPEG', quality=88)
            else:
                cropped_img.save(output, format='PNG')
            return output.getvalue()

        logging.info("未检测到符合对称条件的白边，跳过裁剪，已保留原样。")
        return None
