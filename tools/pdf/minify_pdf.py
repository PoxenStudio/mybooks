#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 页面渲染、图像处理与压缩工具。

用法：
    python minify_pdf.py input.pdf [参数...]

参数说明：
    input_pdf
        必填。待处理的 PDF 文件路径。
    --inspect
        输出最多 5 项嵌入图片信息（编码、DPI、像素尺寸和颜色模式），不生成压缩文件。
    --max-width 像素
        指定每页渲染的目标宽度，按比例缩放。设置后优先使用此宽度；
        未设置时通常按 150 DPI 渲染。若页面是单张全页图像且其分辨率低于
        150 DPI，则使用该图像的较低分辨率，避免放大。宽度必须大于 0。
    --bw
        使用 Otsu 阈值将页面转为黑白二值图。与 --gray 互斥。
    --gray
        将页面转为灰度图。与 --bw 互斥。
    --auto
        根据直方图自动校正页面对比度。
    --dry-run-pages 页数
        仅渲染前 N 个保留页面为 PNG 预览图，然后退出，不生成 PDF。默认 0（关闭）。
    --output-dir 目录
        输出目录，默认为当前目录下的 output。
    --blur 半径
        二值化或灰度转换前应用高斯模糊；默认 0（关闭），不能小于 0。
    --dilate 半径
        模糊或二值化前加粗文字笔画；默认 0（关闭）。支持 0.25 像素步进的小数半径，
        小数半径会先按分母放大处理再缩回（例如 0.5 对应 2 倍放大）。
    --closing
        在模糊或二值化前以 2 倍超采样应用 3x3 闭运算，连接小断笔并填补细小缺口。
    --inpaint
        使用 OpenCV 根据局部闭运算检测并补全文字断口；需要安装 opencv-python。
    --dct-denoise 强度
        对含 DCTDecode（JPEG）图片的页面应用 3x3 中值滤波；1–3 表示滤波次数，
        默认 0（关闭）。即使页面列在 --skip-pages 中仍会应用。
    --skip-pages 页码
        逗号分隔的页码（从 1 开始；支持负数表示从末尾倒数），跳过这些页的
        黑白/灰度/自动对比度/闭运算/inpaint/开运算/膨胀/模糊处理，例如 1,3,-1。页面仍会渲染、
        缩放和重新编码；此参数不跳过 --dct-denoise。
    --drop-pages 页码
        逗号分隔的页码，从输出中完全删除；支持负数页码，例如 2,5,-1。
    --quality 数值
        压缩质量，范围 1–100，默认 75。JPEG 2000 模式映射到 20.2–40 dB
        （75 对应 35 dB）；数值越低文件通常越小、损失越明显。
    --lossless
        使用可逆 JPEG 2000 编码，不新增有损压缩伪影；需要 Pillow 支持 JPEG 2000。
        可能使输出文件变大，此时 --quality 不起作用。
    --max-brightness 数值
        仅在 --gray 下使用。将高于此亮度值的像素设为白色，范围 0–255。

注意：
    ENABLE_OPENING（pdf_image_processor.py）控制是否执行 2 倍超采样开运算，默认关闭；启用可能削弱细小笔画。
    页面图像处理集中在 pdf_image_processor.PdfImageProcessor，可单独用该脚本处理单张图片进行调试。
    对最终为 1-bit 的黑白页，程序会比较无损 JBIG2Decode（若系统装有 jbig2enc）、
    JPXDecode 与 FlateDecode 的图像流大小，自动选用较小者。
    --skip-pages 只跳过页面图像处理，不会保留原始页面数据或原始编码。
    --bw 与 --gray 不能同时使用；--max-brightness 必须与 --gray 同时使用。
"""

import argparse
import io
import math
import shutil
import struct
import subprocess
import tempfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Optional

import fitz
from PIL import Image
from PIL import features
from tqdm import tqdm

try:
    from .pdf_image_processor import ENABLE_OPENING, ImageProcessOptions, PdfImageProcessor
except ImportError:
    from pdf_image_processor import ENABLE_OPENING, ImageProcessOptions, PdfImageProcessor

# Resolution used when rendering pages and storing them in the output PDF.
DEFAULT_RENDER_DPI = 150


def _is_bilevel_page(page: fitz.Page) -> bool:
    """True when every image on the page is already 1-bit (a bilevel scan)."""
    images = page.get_images(full=True)
    return bool(images) and all(image[4] == 1 for image in images)


def _page_has_dct_image(page: fitz.Page) -> bool:
    """Return whether the page contains an image encoded with DCT (JPEG)."""
    return any("DCTDecode" in (image[8] or "") for image in page.get_images(full=True))


def _jbig2_encoder_path() -> Optional[str]:
    """Return the path to the jbig2enc executable when it is available."""
    return shutil.which("jbig2")


def _format_file_size(size_bytes: int) -> str:
    """Format a file size in KB or MB, switching to MB at 1024 KB."""
    size_kb = size_bytes / 1024
    if size_kb >= 1024:
        return f"{size_kb / 1024:.2f} MB"
    return f"{size_kb:.2f} KB"


def _pdf_filter_name(use_jpeg2000: bool) -> str:
    """Return the PDF filter used for an image of the given mode."""
    return "JPXDecode" if use_jpeg2000 else "DCTDecode"


def _page_render_dpi(page: fitz.Page) -> float:
    """Avoid upsampling pages that consist of a single full-page raster image."""
    images = page.get_image_info()
    if len(images) != 1:
        return DEFAULT_RENDER_DPI

    image = images[0]
    bbox = fitz.Rect(image["bbox"])
    page_rect = page.rect
    if (
        bbox.x0 > page_rect.x0 + page_rect.width * 0.05
        or bbox.y0 > page_rect.y0 + page_rect.height * 0.05
        or bbox.x1 < page_rect.x1 - page_rect.width * 0.05
        or bbox.y1 < page_rect.y1 - page_rect.height * 0.05
    ):
        return DEFAULT_RENDER_DPI

    image_dpi = min(image["width"] * 72 / bbox.width, image["height"] * 72 / bbox.height)
    return min(DEFAULT_RENDER_DPI, image_dpi) if image_dpi > 0 else DEFAULT_RENDER_DPI


def _image_color_info(colorspace: str, alternate_colorspace: str, bits_per_component: int) -> tuple[str, Optional[int]]:
    """Return a readable color mode and its number of channels."""
    colorspace = (alternate_colorspace or colorspace).lower()
    if "rgb" in colorspace:
        return "RGB", 3
    if "cmyk" in colorspace:
        return "CMYK", 4
    if "gray" in colorspace:
        return ("BW" if bits_per_component == 1 else "Gray"), 1
    if "indexed" in colorspace:
        return "Indexed", 1
    return colorspace or "Unknown", None


def _print_distinct_image_info(doc: fitz.Document) -> None:
    """Print up to five distinct embedded image encodings and resolutions."""
    distinct: dict[tuple[str, float, float, int, int, str, Optional[int]], None] = {}
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        for image in page.get_images(full=True):
            xref, width, height, bits_per_component = image[0], image[2], image[3], image[4]

            filter_type, filter_value = doc.xref_get_key(xref, "Filter")
            encoding = " + ".join(filter_value.strip("[]").replace("/", "").split()) if filter_type != "null" else "Unfiltered"
            color_mode, channels = _image_color_info(image[5], image[6], bits_per_component)
            for _, matrix in page.get_image_rects(xref, transform=True):
                width_pt = math.hypot(matrix.a, matrix.b)
                height_pt = math.hypot(matrix.c, matrix.d)
                if width_pt <= 0 or height_pt <= 0:
                    continue
                dpi_x = round(width * 72 / width_pt, 1)
                dpi_y = round(height * 72 / height_pt, 1)
                distinct.setdefault((encoding, dpi_x, dpi_y, width, height, color_mode, channels), None)
                if len(distinct) >= 5:
                    break
            if len(distinct) >= 5:
                break
        if len(distinct) >= 5:
            break

    if not distinct:
        print("No embedded images found.")
        return

    for index, (encoding, dpi_x, dpi_y, width, height, color_mode, channels) in enumerate(distinct, start=1):
        resolution = f"{dpi_x:g} DPI" if dpi_x == dpi_y else f"{dpi_x:g} x {dpi_y:g} DPI"
        channel_info = str(channels) if channels is not None else "unknown"
        print(
            f"Image {index}: decoder={encoding} | dpi={resolution} | size={width} x {height} px "
            f"| color={color_mode} | channels={channel_info}"
        )


def _quality_to_db(quality: int) -> float:
    """Map the 1-100 quality option to a JPEG 2000 target quality of 20-40 dB."""
    return 20.0 + quality * 0.2


def _encode_jbig2(img: Image.Image, encoder_path: str) -> bytes:
    """Encode a bilevel image as a lossless, PDF-ready JBIG2 generic region."""
    with tempfile.TemporaryDirectory(prefix="minify-pdf-jbig2-") as temp_dir:
        input_path = Path(temp_dir) / "page.png"
        img.save(input_path, format="PNG")
        result = subprocess.run(
            [encoder_path, "-p", str(input_path)],
            capture_output=True,
            check=False,
        )

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"jbig2 encoder failed with exit code {result.returncode}: {detail}")

    encoded = result.stdout
    if len(encoded) < 27:
        raise RuntimeError("jbig2 encoder returned an incomplete PDF-mode stream")
    width, height, _, _ = struct.unpack(">IIII", encoded[11:27])
    if (width, height) != img.size:
        raise RuntimeError(f"jbig2 encoder returned unexpected dimensions: {width} x {height}")
    return encoded


def _bilevel_encoding_candidates(
    img: Image.Image,
    use_jpeg2000: bool,
    jbig2_encoder: Optional[str],
) -> dict[str, bytes]:
    """Return lossless encoded streams for a bilevel page, keyed by PDF filter."""
    candidates = {"FlateDecode": zlib.compress(img.tobytes(), level=9)}
    if use_jpeg2000:
        buffer = io.BytesIO()
        img.convert("L").save(buffer, format="JPEG2000", irreversible=False)
        candidates["JPXDecode"] = buffer.getvalue()
    if jbig2_encoder is not None:
        candidates["JBIG2Decode"] = _encode_jbig2(img, jbig2_encoder)
    return candidates


def _save_pdf(
    images: list[Image.Image],
    output_pdf: Path,
    quality: int,
    use_jpeg2000: bool,
    page_sizes: Optional[list[tuple[float, float]]] = None,
    lossless: bool = False,
) -> Counter[str]:
    # Encode one page at a time so progress can be reported.
    merged = fitz.open()
    filter_counts: Counter[str] = Counter()
    has_bilevel_pages = any(img.mode == "1" for img in images)
    jbig2_encoder = _jbig2_encoder_path() if has_bilevel_pages else None
    if has_bilevel_pages and jbig2_encoder is None:
        encoders = ["FlateDecode"]
        if use_jpeg2000:
            encoders.insert(0, "JPXDecode")
        tqdm.write(f"JBIG2 encoder not found; comparing {' and '.join(encoders)} only.")
    try:
        for index, img in enumerate(tqdm(images, desc="Encoding pages", unit="page")):
            buffer = io.BytesIO()
            page_width, page_height = (
                page_sizes[index]
                if page_sizes is not None
                else (img.width * 72 / DEFAULT_RENDER_DPI, img.height * 72 / DEFAULT_RENDER_DPI)
            )
            if img.mode == "1":
                candidates = _bilevel_encoding_candidates(img, use_jpeg2000, jbig2_encoder)
                filter_name, stream_data = min(candidates.items(), key=lambda candidate: len(candidate[1]))
                page = merged.new_page(width=page_width, height=page_height)
                if filter_name == "JPXDecode":
                    page.insert_image(page.rect, stream=stream_data)
                else:
                    img.save(buffer, format="PNG", optimize=True)
                    xref = page.insert_image(page.rect, stream=buffer.getvalue())
                    merged.update_stream(xref, stream_data, compress=False)
                    merged.xref_set_key(xref, "Filter", f"/{filter_name}")
                filter_counts[filter_name] += 1
            elif use_jpeg2000:
                # Embed a plain (opaque) JPEG 2000 stream. Pillow's PDF writer
                # only emits JPEG 2000 for LA/RGBA and adds SMaskInData, which
                # some readers mis-handle; MuPDF embeds the stream as-is instead.
                if lossless:
                    img.save(buffer, format="JPEG2000", irreversible=False)
                else:
                    img.save(
                        buffer,
                        format="JPEG2000",
                        quality_mode="dB",
                        quality_layers=[_quality_to_db(quality)],
                        irreversible=True,
                    )
                page = merged.new_page(width=page_width, height=page_height)
                page.insert_image(page.rect, stream=buffer.getvalue())
                filter_counts["JPXDecode"] += 1
            else:
                save_options = {"optimize": True, "resolution": img.width * 72 / page_width}
                save_options["quality"] = quality
                img.save(buffer, format="PDF", **save_options)
                page_doc = fitz.open(stream=buffer.getvalue(), filetype="pdf")
                filter_name = _pdf_filter_name(use_jpeg2000)
                merged.insert_pdf(page_doc)
                page_doc.close()
                filter_counts[filter_name] += 1
        merged.save(str(output_pdf))
    finally:
        merged.close()
    return filter_counts


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


def _page_options(args: argparse.Namespace, page: fitz.Page, skip_filters: bool) -> ImageProcessOptions:
    """Build the image processing options for one page."""
    to_bw = (args.bw or _is_bilevel_page(page)) and not skip_filters
    to_gray = args.gray and not skip_filters and not to_bw
    return ImageProcessOptions(
        to_bw=to_bw,
        to_gray=to_gray,
        auto_correct=args.auto and not skip_filters,
        max_brightness=args.max_brightness if to_gray else None,
        dilate=args.dilate if not skip_filters else 0.0,
        blur=args.blur if not skip_filters else 0.0,
        closing=args.closing and not skip_filters,
        opening=ENABLE_OPENING and not skip_filters,
        inpaint=args.inpaint and not skip_filters,
        dct_denoise=args.dct_denoise,
    )


def _render_page(page: fitz.Page, options: ImageProcessOptions, max_width: Optional[int]) -> Image.Image:
    src_width = float(page.rect.width)
    if max_width and src_width > 0:
        scale = max_width / src_width
    else:
        scale = _page_render_dpi(page) / 72.0
    scale = max(scale, 0.01)

    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    mode = "RGB" if pix.n >= 3 else "L"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

    return PdfImageProcessor(options).process(img, has_dct_image=_page_has_dct_image(page))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minify PDF by scaling and optional binarization.")
    parser.add_argument("input_pdf", help="Input PDF path")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Show up to 5 distinct embedded image encodings and resolutions, then exit.",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=None,
        help="Target max page width in pixels. Each page is scaled proportionally.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--bw",
        action="store_true",
        help="Convert color pages into black/white binary pages using Otsu threshold.",
    )
    mode_group.add_argument(
        "--gray",
        action="store_true",
        help="Convert pages to grayscale. Cannot be used with --bw.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-correct each page using histogram-based contrast adjustment.",
    )
    parser.add_argument(
        "--dry-run-pages",
        type=int,
        default=0,
        help="Process first N pages only, export as images, then exit.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory. Defaults to ./output",
    )
    parser.add_argument(
        "--blur",
        type=float,
        default=0.0,
        help="Gaussian blur radius applied to each page image before binarization/grayscale. Useful for smoothing stroke gaps.",
    )
    parser.add_argument(
        "--dilate",
        type=float,
        default=0,
        help="Dilation radius in pixels; supports 0.25-pixel increments with up to 4x supersampling.",
    )
    parser.add_argument(
        "--closing",
        action="store_true",
        help="Apply a supersampled 3x3 morphological closing before blur or binarization.",
    )
    parser.add_argument(
        "--inpaint",
        action="store_true",
        help="Use OpenCV to repair small gaps in dark text strokes. Requires opencv-python.",
    )
    parser.add_argument(
        "--dct-denoise",
        type=int,
        default=0,
        help="DCTDecode pages only: apply 1-3 passes of a 3x3 median filter. 0 disables it; also applies to --skip-pages.",
    )
    parser.add_argument(
        "--skip-pages",
        default="",
        help="Comma-separated pages to skip bw/gray/auto/closing/inpaint/opening/dilation/blur (supports negative, e.g. 1,3,-1).",
    )
    parser.add_argument(
        "--drop-pages",
        default="",
        help="Comma-separated pages to drop from output entirely (supports negative, e.g. 2,5,-1).",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=75,
        help="Quality factor (1-100). JPEG 2000 maps this to 20-40 dB (75 = 35 dB); lower means smaller file.",
    )
    parser.add_argument(
        "--lossless",
        action="store_true",
        help="Use reversible JPEG 2000 encoding to avoid adding compression artifacts. Requires JPEG 2000 support.",
    )
    parser.add_argument(
        "--max-brightness",
        type=int,
        default=None,
        help="In --gray mode, pixels above this brightness (0-255) are set to white.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_path = Path(args.input_pdf).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_path}")
    if input_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input file must be a PDF: {input_path}")
    print(f"Source file size: {input_path.stat().st_size / 1024:.2f} KB")
    jbig2_encoder = _jbig2_encoder_path()
    if jbig2_encoder:
        print(f"JBIG2Enc: available ({jbig2_encoder})")
    else:
        print("JBIG2Enc: not available")
    if args.max_width is not None and args.max_width <= 0:
        raise ValueError("--max-width must be a positive integer")
    if args.dry_run_pages < 0:
        raise ValueError("--dry-run-pages must be >= 0")
    if args.quality < 1 or args.quality > 100:
        raise ValueError("--quality must be in range 1-100")
    ImageProcessOptions(
        to_gray=args.gray,
        max_brightness=args.max_brightness,
        dilate=args.dilate,
        blur=args.blur,
        dct_denoise=args.dct_denoise,
        inpaint=args.inpaint,
    )

    doc = fitz.open(str(input_path))
    total_pages = len(doc)
    if total_pages == 0:
        raise ValueError("Input PDF has no pages")
    if args.inspect:
        _print_distinct_image_info(doc)
        doc.close()
        return 0

    use_jpeg2000 = features.check_codec("jpg_2000")
    if args.lossless and not use_jpeg2000:
        raise ValueError("--lossless requires Pillow JPEG 2000 support")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = output_dir / f"{input_path.stem}_minify.pdf"
    if use_jpeg2000:
        print("JPEG 2000 support: available.")
    else:
        print("Warning: Pillow JPEG 2000 support is unavailable; using JPEG compression.")

    skip_page_indices = _parse_page_selection(args.skip_pages, total_pages, "--skip-pages")
    drop_page_indices = _parse_page_selection(args.drop_pages, total_pages, "--drop-pages")
    kept_page_indices = [index for index in range(total_pages) if index not in drop_page_indices]
    if not kept_page_indices:
        raise ValueError("All pages were dropped by --drop-pages")

    dry_run_pages = min(args.dry_run_pages, len(kept_page_indices))
    if dry_run_pages > 0:
        for output_index, page_index in enumerate(
            tqdm(kept_page_indices[:dry_run_pages], desc="Rendering pages", unit="page"), start=1
        ):
            page = doc.load_page(page_index)
            img = _render_page(page, _page_options(args, page, page_index in skip_page_indices), args.max_width)
            preview_path = output_dir / f"{input_path.stem}_preview_{output_index:04d}.png"
            img.save(preview_path, format="PNG")
            tqdm.write(f"[dry-run] saved: {preview_path}")
        doc.close()
        print(f"Dry run completed: {dry_run_pages} page(s)")
        return 0

    images = []
    page_sizes = []
    for page_index in tqdm(kept_page_indices, desc="Rendering pages", unit="page"):
        page = doc.load_page(page_index)
        img = _render_page(page, _page_options(args, page, page_index in skip_page_indices), args.max_width)
        images.append(img)
        page_sizes.append((page.rect.width, page.rect.height))

    _print_distinct_image_info(doc)
    doc.close()

    filter_counts = _save_pdf(images, output_pdf, args.quality, use_jpeg2000, page_sizes, args.lossless)
    summary = ", ".join(f"{name} x{count}" for name, count in sorted(filter_counts.items()))
    print(f"PDF image encoding ({len(images)} pages): {summary}")
    if "JPXDecode" in filter_counts and not args.lossless and any(img.mode != "1" for img in images):
        print(f"JPEG 2000 target quality: {_quality_to_db(args.quality):.1f} dB")

    # Ensure creator metadata is written in the final PDF.
    meta_doc = fitz.open(str(output_pdf))
    metadata = meta_doc.metadata or {}
    metadata["creator"] = "MyBooks(https://mybooks.top)"
    metadata["title"] = input_path.stem
    meta_doc.set_metadata(metadata)
    if use_jpeg2000:
        # JPXDecode requires PDF 1.5; Pillow's PDF writer emits a 1.4 header.
        meta_doc.xref_set_key(meta_doc.pdf_catalog(), "Version", "/1.5")
    meta_doc.save(str(output_pdf), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    meta_doc.close()

    print(f"Saved minified PDF: {output_pdf}")
    print(f"Output file size: {_format_file_size(output_pdf.stat().st_size)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
