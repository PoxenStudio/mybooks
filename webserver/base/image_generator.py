#!/usr/bin/env python3
import io
import logging
import os
import random
import time
import traceback
import math
from PIL import Image, ImageDraw, ImageFont, ImageOps

from webserver.base.cover_background import CoverBackgroundService


DEFAULT_FONT_PATH = "/var/www/mybooks/app/dist/static/epubreader/assets/font/HuiwenZhengKai.ttf"
_RESAMPLING = getattr(Image, "Resampling", Image)


class ImageGenerator:
    COLORS = [
        "#003e19", "#028c6a", "#283b42", "#1d6a96", "#a46843",
        "#370d00", "#072a24", "#280e3b", "#002c2f", "#023459",
        "#00142f", "#4A2B31"
    ]
    ENABLE_GRADIENT = True
    ENABLE_AUTHOR_OUTPUT = False
    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 1600

    _title_font_map = dict()
    _author_font_map = dict()

    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @classmethod
    def _create_rotated_gradient(cls, width, height):
        start = time.time()
        c1_hex, c2_hex = random.sample(cls.COLORS, 2)
        color1, color2 = cls._hex_to_rgb(c1_hex), cls._hex_to_rgb(c2_hex)
        base, top = Image.new('RGB', (width, height), color1), Image.new('RGB', (width, height), color2)
        diag = int(math.sqrt(width**2 + height**2))
        mask = Image.new('L', (diag, diag), 0)
        mask_draw = ImageDraw.Draw(mask)
        for i in range(diag):
            mask_draw.line([(i, 0), (i, diag)], fill=int(255 * (i / diag)))
        mask = mask.rotate(random.randint(0, 360), resample=Image.BICUBIC)
        l, t = (diag - width) // 2, (diag - height) // 2
        mask = mask.crop((l, t, l + width, t + height))
        base.paste(top, (0, 0), mask)
        cost = time.time() - start
        if cost > 0.025:
            cls.ENABLE_GRADIENT = False
        elif cost < 0.010:
            cls.ENABLE_GRADIENT = True
        return base

    @classmethod
    def _create_background(cls, title, width, height, bk_img_path, no_graident):
        """返回 (底图, 是否照片背景)；照片背景用描边保证文字可读。"""
        background_path = bk_img_path or CoverBackgroundService.pick_for(title)
        if background_path and os.path.exists(background_path):
            try:
                with Image.open(background_path) as image:
                    fitted = ImageOps.fit(image.convert("RGB"), (width, height), method=_RESAMPLING.LANCZOS)
                return fitted, True
            except Exception as err:
                logging.warning(f"[Cover] 背景图加载失败，回退渐变: {background_path} {err}")
        if cls.ENABLE_GRADIENT and not no_graident:
            return cls._create_rotated_gradient(width, height), False
        return Image.new("RGB", (width, height), random.choice(cls.COLORS)), False

    @classmethod
    def generate_cover(cls, title, author, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, font_path=DEFAULT_FONT_PATH, bk_img_path=None, no_graident=False, debug=False):
        try:
            img, has_background = cls._create_background(title, width, height, bk_img_path, no_graident)
            draw = ImageDraw.Draw(img)

            if width < 120 and height < 120:
                title_size = width // 2
                author_size = title_size
            else:
                title_size = height // 12 if height > 400 else height // 9 - 3
                author_size = title_size // 2 if height > 400 else title_size // 1.5

            if title_size in cls._title_font_map and author_size in cls._author_font_map:
                t_font, a_font = cls._title_font_map[title_size], cls._author_font_map[author_size]
            else:
                if font_path and os.path.exists(font_path):
                    t_font = ImageFont.truetype(font_path, title_size)
                    a_font = ImageFont.truetype(font_path, author_size)
                    cls._title_font_map[title_size] = t_font
                    cls._author_font_map[author_size] = a_font
                    logging.info(f"[Cover] 字体加载成功: {font_path}")
                else:
                    t_font = a_font = ImageFont.load_default()
                    cls._title_font_map[title_size] = t_font
                    cls._author_font_map[author_size] = a_font
                    logging.warning("[COVER] 字体文件不存在，使用默认字体(不可缩放)")

            title_lines = []
            current_line = ""
            title_line_cnt = 3 if height > 200 else 1
            for char in title:
                test_line = current_line + char
                bbox = draw.textbbox((0, 0), test_line, font=t_font)
                if (bbox[2] - bbox[0]) <= (width * 0.9):
                    current_line = test_line
                else:
                    title_lines.append(current_line)
                    current_line = char
                    if len(title_lines) >= title_line_cnt:
                        break
            if len(title_lines) < title_line_cnt and current_line:
                title_lines.append(current_line)
            title_lines = title_lines[:title_line_cnt]
            if len(title_lines) > 1 and len(title_lines[-1]) < 2:
                title_lines[-2] += title_lines[-1]
                title_lines.pop()

            stroke_width = max(1, title_size // 24) if has_background else 0
            current_y = height // 5
            for i, line in enumerate(title_lines):
                bbox = draw.textbbox((0, 0), line, font=t_font)
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x = (width - w) // 2
                if stroke_width:
                    draw.text((x, current_y), line, font=t_font, fill=(255, 255, 255), stroke_width=stroke_width, stroke_fill=(0, 0, 0))
                else:
                    draw.text((x, current_y), line, font=t_font, fill=(255, 255, 255))
                current_y += h + (title_size // 10) + stroke_width * 2

            if cls.ENABLE_AUTHOR_OUTPUT and author and height > 300:
                current_y += (title_size // 4)  # 标题与作者间距
                bbox = draw.textbbox((0, 0), author, font=a_font)
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x = (width - w) // 2
                draw.text((x, current_y), author, font=a_font, fill=(255, 255, 255))

            output = io.BytesIO()
            img.save(output, format='JPEG', quality=95)
            data = output.getvalue()

            if debug:
                with open("/tmp/cover_debug.jpg", "wb") as f:
                    f.write(data)
            return data

        except Exception as e:
            logging.error(f"[Error] {e}")
            logging.error(traceback.format_exc())
            return None


if __name__ == "__main__":
    # cover_bytes = ImageGenerator.generate_cover(
    #     title="简体中文测试书籍封面生成",
    #     author="测试作者过长的名字显示效果",
    #     font_path="/Volumes/data/workspace/fonts/HuiwenFangSong.ttf",
    #     debug=False
    # )
    avatar_bytes = ImageGenerator.generate_cover(title="测", author="", width=64, height=64, font_path="/tmp/HuiwenZhengKai.ttf", debug=True)
    # write to file for testing
    with open("/tmp/cover_test.jpg", "wb") as f:
        f.write(avatar_bytes)
    print("Cover image generated and saved to /tmp/cover_test.jpg")
