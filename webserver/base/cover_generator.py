#!/usr/bin/env python3
import io
import logging
import os
import random
import time
import traceback
import math
from PIL import Image, ImageDraw, ImageFont


DEFAULT_FONT_PATH = "/var/www/talebook/app/dist/static/epubreader/assets/font/HuiwenFangSong.ttf"


class CoverGenerator:
    COLORS = [
        "#003e19", "#028c6a", "#283b42", "#1d6a96", "#a46843",
        "#370d00", "#072a24", "#280e3b", "#002c2f", "#023459",
        "#00142f", "#4A2B31"
    ]
    ENABLE_GRADIENT = True
    ENABLE_AUTO_OUTPUT = False
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
        if time.time() - start > 0.08:
            logging.warning(f"[COVER] Gradient generation took {time.time() - start:.2f}s, disable it.")
            cls.ENABLE_GRADIENT = False
        return base

    @classmethod
    def generate_cover(cls, title, author, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, font_path=DEFAULT_FONT_PATH, bk_img_path=None, no_graident=False, debug=False):
        start = time.time()
        try:
            if bk_img_path and os.path.exists(bk_img_path):
                img = Image.open(bk_img_path).convert("RGB")
            elif cls.ENABLE_GRADIENT and not no_graident:
                img = cls._create_rotated_gradient(width, height)
            else:
                img = Image.new("RGB", (width, height), random.choice(cls.COLORS))
            draw = ImageDraw.Draw(img)

            title_size = height // 12 if height > 400 else height // 9
            author_size = title_size // 2 if height > 400 else title_size // 1.5
            logging.info(f"[Cover] 图片尺寸: {width}x{height} | 标题字号: {title_size} | 作者字号: {author_size}")

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
                    logging.warning(f"[COVER] 字体文件不存在，使用默认字体(不可缩放)")

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

            current_y = height // 5
            for i, line in enumerate(title_lines):
                bbox = draw.textbbox((0, 0), line, font=t_font)
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x = (width - w) // 2
                draw.text((x, current_y), line, font=t_font, fill=(255, 255, 255))
                current_y += h + (title_size // 10)

            if cls.ENABLE_AUTO_OUTPUT and author and height > 300:
                current_y += (title_size // 4)  # 标题与作者间距
                bbox = draw.textbbox((0, 0), author, font=a_font)
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x = (width - w) // 2
                draw.text((x, current_y), author, font=a_font, fill=(255, 255, 255))
                logging.info(f"[Cover] 作者: {author} | 位置: ({x}, {current_y})")

            output = io.BytesIO()
            img.save(output, format='JPEG', quality=95)
            data = output.getvalue()

            if debug:
                with open("/tmp/cover_debug.jpg", "wb") as f: f.write(data)
            end = time.time()
            logging.info(f"[Cover] 封面生成完成，耗时: {end - start:.2f}s")
            return data

        except Exception as e:
            logging.error(f"[Error] {e}")
            logging.error(traceback.format_exc())
            return None


if __name__ == "__main__":
    cover_bytes = CoverGenerator.generate_cover(
        title="简体中文测试书籍封面生成",
        author="测试作者过长的名字显示效果",
        font_path="/Volumes/data/workspace/fonts/HuiwenFangSong.ttf",
        debug=False
    )
