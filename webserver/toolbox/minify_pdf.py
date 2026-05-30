"""
PDF 扫描档瘦身工具
"""
import logging
import os
import shutil
from pathlib import Path
from typing import Callable, Optional

import fitz
from PIL import Image

from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool

import io
from PIL import ImageOps


def _otsu_threshold(gray_img: Image.Image) -> int:
    """Compute Otsu threshold from a grayscale image."""
    hist = gray_img.histogram()
    total = sum(hist)
    if total == 0:
        return 127

    sum_total = 0
    for i, count in enumerate(hist):
        sum_total += i * count

    sum_bg = 0
    weight_bg = 0
    var_max = -1.0
    threshold = 127

    for i, count in enumerate(hist):
        weight_bg += count
        if weight_bg == 0:
            continue

        weight_fg = total - weight_bg
        if weight_fg == 0:
            break

        sum_bg += i * count
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg

        var_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var_between > var_max:
            var_max = var_between
            threshold = i

    return threshold


def _to_binary(img: Image.Image) -> Image.Image:
    """Convert image to black/white with Otsu threshold."""
    gray = img.convert("L")
    threshold = _otsu_threshold(gray)
    return gray.point(lambda x: 255 if x > threshold else 0, mode="1")


def _auto_correct_by_histogram(img: Image.Image) -> Image.Image:
    """Auto-correct image contrast based on page histogram."""
    # Use a small cutoff to avoid extreme outliers dominating the stretch.
    return ImageOps.autocontrast(img, cutoff=1)


def _cleanup_gray_background(img: Image.Image, max_brightness: int) -> Image.Image:
    """Whiten brighter grayscale pixels to reduce background noise."""
    gray = img.convert("L")
    return gray.point(lambda value: 255 if value > max_brightness else value)


def _apply_qualify(img: Image.Image, qualify: int) -> Image.Image:
    """Apply quality factor by JPEG re-encode for each page image."""
    if img.mode == "1":
        return img

    work_img = img if img.mode in ("RGB", "L") else img.convert("RGB")
    buffer = io.BytesIO()
    work_img.save(buffer, format="JPEG", quality=qualify, optimize=True)
    buffer.seek(0)
    jpeg_img = Image.open(buffer)
    result = jpeg_img.copy()
    jpeg_img.close()
    return result


def _parse_page_selection(page_spec: str, total_pages: int, option_name: str) -> set[int]:
    """Parse comma-separated page numbers (1-based, supports negative reverse index)."""
    if not page_spec.strip():
        return set()

    parsed: set[int] = set()
    tokens = [item.strip() for item in page_spec.split(",") if item.strip()]
    for token in tokens:
        try:
            number = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid page number in {option_name}: {token}") from exc

        if number == 0:
            raise ValueError(f"Page number 0 is invalid in {option_name}")

        if number > 0:
            index = number - 1
        else:
            index = total_pages + number

        if index < 0 or index >= total_pages:
            raise ValueError(f"Page number out of range in {option_name}: {token}")

        parsed.add(index)

    return parsed


def _render_page(
    page: fitz.Page,
    max_width: Optional[int],
    to_bw: bool,
    to_gray: bool,
    auto_correct: bool,
    max_brightness: Optional[int],
) -> Image.Image:
    src_width = float(page.rect.width)
    if not max_width:
        max_width = 800
    else:
        max_width = min(max(max_width, 600), 2048)

    if src_width > 0:
        scale = max_width / src_width
    else:
        scale = 1.0
    scale = max(scale, 0.01)

    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    mode = "RGB" if pix.n >= 3 else "L"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

    if auto_correct:
        img = _auto_correct_by_histogram(img)

    if to_bw:
        img = _to_binary(img)
    elif to_gray:
        img = img.convert("L")
        if max_brightness is not None:
            img = _cleanup_gray_background(img, max_brightness)
    elif mode != "RGB":
        img = img.convert("RGB")

    return img


class MinifyPdfTool(BaseTool):
    # 后台任务面板中显示的任务名称
    service_item_name = "PDF瘦身"
    cleaned = False

    # 记录任务状态: input_pdf -> { "status": str, "output_pdf": str, "progress": int, "message": str }
    _tasks: dict = {}

    @classmethod
    def is_running(cls) -> bool:
        for info in cls._tasks.values():
            if info.get("status") == "running":
                return True
        return False

    @classmethod
    def get_task_info(cls, input_pdf: str) -> dict:
        return cls._tasks.get(input_pdf, {})

    @classmethod
    def update_task_info(cls, input_pdf: str, **kwargs):
        if input_pdf not in cls._tasks:
            cls._tasks[input_pdf] = {
                "status": "running",
                "output_pdf": "",
                "progress": 0,
                "message": ""
            }
        cls._tasks[input_pdf].update(kwargs)

    @classmethod
    def cleanup_old_files(cls):
        """清除 work dir 下 sources / processed 目录里的文件"""
        if cls.cleaned:
            return
        cls.cleaned = True

        logging.info("[MinifyPdfTool] cleaning up old files in work dir")
        tool = cls()
        work_dir = tool.get_work_dir("")
        for d in ["sources", "processed"]:
            dir_path = os.path.join(work_dir, d)
            if os.path.exists(dir_path):
                try:
                    for filename in os.listdir(dir_path):
                        filepath = os.path.join(dir_path, filename)
                        if os.path.isfile(filepath):
                            os.remove(filepath)
                        elif os.path.isdir(filepath):
                            shutil.rmtree(filepath)
                except Exception as e:
                    logging.error("[MinifyPdfTool] cleanup failed for %s: %s", dir_path, e)

    @staticmethod
    def info():
        return {
            "tool_id": "minify_pdf",
            "name": "PDF瘦身器",
            "description": "对扫描版PDF进行缩放、二值化、灰度化、对比度调整以减小文件体积",
            "revision": "0.1.0",
            "author": "MyBooks",
            "publish_date": "2026-05-30",
        }

    @staticmethod
    def get_pdf_info(pdf_path: str) -> dict:
        """获取 PDF 基础信息，如分辨率、色彩空间、尺寸等"""
        try:
            doc = fitz.open(pdf_path)
            info = {
                "page_count": len(doc),
                "file_size": os.path.getsize(pdf_path),
            }
            if len(doc) > 0:
                page = doc.load_page(0)
                info["page_width"] = round(page.rect.width, 2)
                info["page_height"] = round(page.rect.height, 2)

                images = page.get_images()
                if images:
                    xref = images[0][0]
                    img = doc.extract_image(xref)
                    info["colorspace"] = img.get("colorspace", "unknown")
                    info["image_width"] = img.get("width")
                    info["image_height"] = img.get("height")
                    if page.rect.width > 0:
                        dpi = int((img.get("width", 0) * 72) / page.rect.width)
                        info["dpi"] = dpi
            doc.close()
            return info
        except Exception as e:
            logging.error("[MinifyPdfTool] get_pdf_info failed: %s", e)
            return {"error": str(e)}

    @AsyncService.register_service
    def minify(self, input_pdf: str, params: dict, user_id: int, callback: Optional[Callable[[int], None]] = None) -> Optional[dict]:
        """异步处理PDF文件并导入。

        :param input_pdf: 原 PDF 路径
        :param params: 参数字典，包含 max_width, bw, gray, auto, skip_pages, drop_pages, qualify, max_brightness 等
        :param user_id: 入库操作关联的用户 ID
        :param callback: 进度回调，参数为 0-100 的整数进度值
        :return: {"title": str, "pdf_path": str, "book_id": int}；异步模式下返回 None
        """
        task_id = self.create_task(progress_data={"input_pdf": input_pdf})
        progress_callback = self.make_progress_callback(
            task_id,
            progress_data_factory=lambda p: {"input_pdf": input_pdf},
            outer_callback=callback,
        )

        MinifyPdfTool.update_task_info(input_pdf, status="running", progress=0, message="started")

        try:
            input_path = Path(input_pdf).expanduser().resolve()
            if not input_path.exists():
                raise FileNotFoundError(f"PDF 文件不存在: {input_path}")

            # 解析参数
            max_width = params.get("max_width", None)
            bw = params.get("bw", False)
            gray = params.get("gray", False)
            auto_correct = params.get("auto", False)
            skip_pages_str = params.get("skip_pages", "")
            drop_pages_str = params.get("drop_pages", "")
            qualify = params.get("qualify", 75)
            max_brightness = params.get("max_brightness", None)

            work_dir = self.get_work_dir("")
            processed_dir = os.path.join(work_dir, "processed")
            os.makedirs(processed_dir, exist_ok=True)
            output_pdf = Path(processed_dir) / f"{input_path.stem}_minify.pdf"

            logging.info("[MinifyPdfTool] start minify: %s -> %s", input_pdf, output_pdf)

            doc = fitz.open(str(input_path))
            total_pages = len(doc)
            if total_pages == 0:
                raise ValueError("PDF 文件没有页面")

            skip_page_indices = _parse_page_selection(skip_pages_str, total_pages, "skip_pages")
            drop_page_indices = _parse_page_selection(drop_pages_str, total_pages, "drop_pages")
            kept_page_indices = [idx for idx in range(total_pages) if idx not in drop_page_indices]

            if not kept_page_indices:
                raise ValueError("所有页面均被丢弃")

            images = []
            total_kept = len(kept_page_indices)

            for i, page_index in enumerate(kept_page_indices):
                page = doc.load_page(page_index)
                skip_filters = page_index in skip_page_indices

                img = _render_page(
                    page,
                    max_width,
                    bw and not skip_filters,
                    gray and not skip_filters,
                    auto_correct and not skip_filters,
                    max_brightness if gray and not skip_filters else None,
                )

                if img.mode not in ("RGB", "L", "1"):
                    img = img.convert("RGB")
                img = _apply_qualify(img, qualify)
                images.append(img)

                if progress_callback:
                    # 前90%进度用于处理图片
                    progress = int((i + 1) / total_kept * 90)
                    progress_callback(progress)
                    MinifyPdfTool.update_task_info(input_pdf, progress=progress)

            doc.close()

            # 保存处理后的 PDF
            first, *rest = images
            first.save(
                output_pdf,
                save_all=True,
                append_images=rest,
                optimize=True,
                resolution=150,
            )

            # 写回 metadata
            meta_doc = fitz.open(str(output_pdf))
            metadata = meta_doc.metadata or {}
            metadata["creator"] = "MyBooks(https://mybooks.top) MinifyTool"
            metadata["title"] = input_path.stem
            meta_doc.set_metadata(metadata)
            meta_doc.save(str(output_pdf), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            meta_doc.close()

            MinifyPdfTool.update_task_info(input_pdf, progress=95, output_pdf=str(output_pdf))

            if progress_callback:
                progress_callback(100)

            self.complete_task(task_id)
            MinifyPdfTool.update_task_info(input_pdf, progress=100, status="completed", message="done")

            return {
                "title": f"{input_path.stem} (Minified)",
                "pdf_path": str(output_pdf),
            }

        except Exception as err:
            logging.error("[MinifyPdfTool] minify failed: %s", err)
            MinifyPdfTool.update_task_info(input_pdf, status="error", message=str(err))
            self.complete_task(task_id, error_message=str(err))
            raise
