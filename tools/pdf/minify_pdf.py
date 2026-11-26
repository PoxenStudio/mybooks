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
        只检查前 5 页，输出不同的页面尺寸、图片编码、有效 DPI 和颜色通道，不生成压缩文件。
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
        模糊或二值化前加粗文字笔画；默认 0（关闭），必须是非负整数。
    --dct-denoise 强度
        对含 DCTDecode（JPEG）图片的页面应用 3x3 中值滤波；1–3 表示滤波次数，
        默认 0（关闭）。即使页面列在 --skip-pages 中仍会应用。
    --skip-pages 页码
        逗号分隔的页码（从 1 开始；支持负数表示从末尾倒数），跳过这些页的
        黑白/灰度/自动对比度/膨胀/模糊处理，例如 1,3,-1。页面仍会渲染、
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
    --skip-pages 只跳过页面图像处理，不会保留原始页面数据或原始编码。
    --bw 与 --gray 不能同时使用；--max-brightness 必须与 --gray 同时使用。
"""

import argparse
import io
import math
from collections import Counter
from pathlib import Path
from typing import Optional

import fitz
from PIL import Image
from PIL import features
from PIL import ImageFilter
from PIL import ImageOps
from tqdm import tqdm

# Resolution used when rendering pages and storing them in the output PDF.
DEFAULT_RENDER_DPI = 150


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


def _is_bilevel_page(page: fitz.Page) -> bool:
    """True when every image on the page is already 1-bit (a bilevel scan)."""
    images = page.get_images(full=True)
    return bool(images) and all(image[4] == 1 for image in images)


def _page_has_dct_image(page: fitz.Page) -> bool:
    """Return whether the page contains an image encoded with DCT (JPEG)."""
    return any("DCTDecode" in (image[8] or "") for image in page.get_images(full=True))


def _apply_dct_denoise(img: Image.Image, strength: int) -> Image.Image:
    """Suppress small DCT ringing and speckles with repeated 3x3 median filtering."""
    for _ in range(strength):
        img = img.filter(ImageFilter.MedianFilter(size=3))
    return img


def _auto_correct_by_histogram(img: Image.Image) -> Image.Image:
    """Auto-correct image contrast based on page histogram."""
    # Use a small cutoff to avoid extreme outliers dominating the stretch.
    return ImageOps.autocontrast(img, cutoff=1)


def _cleanup_gray_background(img: Image.Image, max_brightness: int) -> Image.Image:
    """Whiten brighter grayscale pixels to reduce background noise."""
    gray = img.convert("L")
    return gray.point(lambda value: 255 if value > max_brightness else value)


def _pdf_filter_name(mode: str, use_jpeg2000: bool, lossless: bool = False) -> str:
    """Return the PDF filter used for an image of the given mode."""
    if use_jpeg2000 and (mode != "1" or lossless):
        return "JPXDecode"
    if mode == "1":
        return "CCITTFaxDecode" if features.check("libtiff") else "DCTDecode"
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
    """Print distinct page sizes, image encodings, and effective resolutions."""
    distinct: dict[tuple[str, float, float, str, Optional[int]], set[int]] = {}
    page_sizes: dict[tuple[float, float], set[int]] = {}
    for page_index in range(min(5, len(doc))):
        page = doc.load_page(page_index)
        page_size = (round(page.rect.width / 72, 2), round(page.rect.height / 72, 2))
        page_sizes.setdefault(page_size, set()).add(page_index + 1)
        seen_xrefs = set()
        for image in page.get_images(full=True):
            xref, width, height, bits_per_component = image[0], image[2], image[3], image[4]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

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
                distinct.setdefault((encoding, dpi_x, dpi_y, color_mode, channels), set()).add(page_index + 1)

    for (width_in, height_in), pages in sorted(page_sizes.items()):
        page_list = ", ".join(str(page) for page in sorted(pages))
        print(f"Page size: {width_in:g} x {height_in:g} in | Pages: {page_list}")

    if not distinct:
        print("No embedded images found in the first 5 pages.")
        return

    for (encoding, dpi_x, dpi_y, color_mode, channels), pages in sorted(distinct.items()):
        page_list = ", ".join(str(page) for page in sorted(pages))
        resolution = f"{dpi_x:g} DPI" if dpi_x == dpi_y else f"{dpi_x:g} x {dpi_y:g} DPI"
        channel_info = f"{color_mode} ({channels} channel{'s' if channels != 1 else ''})" if channels else color_mode
        print(f"{encoding} | {resolution} | {channel_info} | Pages: {page_list}")


def _quality_to_db(quality: int) -> float:
    """Map the 1-100 quality option to a JPEG 2000 target quality of 20-40 dB."""
    return 20.0 + quality * 0.2


def _save_pdf(
    images: list[Image.Image],
    output_pdf: Path,
    quality: int,
    use_jpeg2000: bool,
    page_sizes: Optional[list[tuple[float, float]]] = None,
    lossless: bool = False,
) -> None:
    # Encode one page at a time so progress can be reported.
    merged = fitz.open()
    try:
        for index, img in enumerate(tqdm(images, desc="Encoding pages", unit="page")):
            buffer = io.BytesIO()
            page_width, page_height = (
                page_sizes[index]
                if page_sizes is not None
                else (img.width * 72 / DEFAULT_RENDER_DPI, img.height * 72 / DEFAULT_RENDER_DPI)
            )
            if use_jpeg2000 and (img.mode != "1" or lossless):
                # Embed a plain (opaque) JPEG 2000 stream. Pillow's PDF writer
                # only emits JPEG 2000 for LA/RGBA and adds SMaskInData, which
                # some readers mis-handle; MuPDF embeds the stream as-is instead.
                encoded_img = img.convert("L") if img.mode == "1" else img
                if lossless:
                    encoded_img.save(buffer, format="JPEG2000", irreversible=False)
                else:
                    encoded_img.save(
                        buffer,
                        format="JPEG2000",
                        quality_mode="dB",
                        quality_layers=[_quality_to_db(quality)],
                        irreversible=True,
                    )
                page = merged.new_page(width=page_width, height=page_height)
                page.insert_image(page.rect, stream=buffer.getvalue())
            else:
                # 1-bit pages use CCITT; other modes fall back to PIL's JPEG writer.
                save_options = {"optimize": True, "resolution": img.width * 72 / page_width}
                if img.mode != "1":
                    save_options["quality"] = quality
                img.save(buffer, format="PDF", **save_options)
                page_doc = fitz.open(stream=buffer.getvalue(), filetype="pdf")
                merged.insert_pdf(page_doc)
                page_doc.close()
        merged.save(str(output_pdf))
    finally:
        merged.close()


def _apply_dilation(img: Image.Image, dilate: int) -> Image.Image:
    """Apply dilation to thicken text strokes before blur or binarization."""
    if dilate <= 0:
        return img

    size = dilate * 2 + 1
    if size < 3:
        size = 3
    if size % 2 == 0:
        size += 1

    return img.filter(ImageFilter.MaxFilter(size=size))


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
    dilate: int,
    blur: float,
    dct_denoise: int = 0,
) -> Image.Image:
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

    if dct_denoise and _page_has_dct_image(page):
        img = _apply_dct_denoise(img, dct_denoise)

    # print(f"Rendering page {page.number} at scale {scale:.2f}, original width {src_width:.2f}, target width {pix.width:.2f}")

    if auto_correct:
        img = _auto_correct_by_histogram(img)

    if dilate and dilate > 0:
        img = _apply_dilation(img, dilate)

    if blur and blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))

    if to_bw:
        img = _to_binary(img)
    elif to_gray:
        img = img.convert("L")
        if max_brightness is not None:
            img = _cleanup_gray_background(img, max_brightness)
    elif mode != "RGB":
        img = img.convert("RGB")

    return img


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Minify PDF by scaling and optional binarization.")
    parser.add_argument("input_pdf", help="Input PDF path")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Show distinct image encodings and resolutions in the first 5 pages, then exit.",
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
        type=int,
        default=0,
        help="Dilation radius applied to each page image before blur, to thicken text strokes. Must be an integer.",
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
        help="Comma-separated pages to skip bw/gray/auto (supports negative, e.g. 1,3,-1).",
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
    if args.max_width is not None and args.max_width <= 0:
        raise ValueError("--max-width must be a positive integer")
    if args.dry_run_pages < 0:
        raise ValueError("--dry-run-pages must be >= 0")
    if args.quality < 1 or args.quality > 100:
        raise ValueError("--quality must be in range 1-100")
    if args.blur < 0:
        raise ValueError("--blur must be >= 0")
    if args.dilate < 0:
        raise ValueError("--dilate must be >= 0")
    if args.dct_denoise < 0 or args.dct_denoise > 3:
        raise ValueError("--dct-denoise must be in range 0-3")
    if args.max_brightness is not None and (args.max_brightness < 0 or args.max_brightness > 255):
        raise ValueError("--max-brightness must be in range 0-255")
    if args.max_brightness is not None and not args.gray:
        raise ValueError("--max-brightness requires --gray")

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
            skip_filters = page_index in skip_page_indices
            to_bw = (args.bw or _is_bilevel_page(page)) and not skip_filters
            img = _render_page(
                page,
                args.max_width,
                to_bw,
                args.gray and not skip_filters,
                args.auto and not skip_filters,
                args.max_brightness if args.gray and not skip_filters else None,
                args.dilate if not skip_filters else 0,
                args.blur if not skip_filters else 0.0,
                args.dct_denoise,
            )
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
        skip_filters = page_index in skip_page_indices
        to_bw = (args.bw or _is_bilevel_page(page)) and not skip_filters
        img = _render_page(
            page,
            args.max_width,
            to_bw,
            args.gray and not skip_filters,
            args.auto and not skip_filters,
            args.max_brightness if args.gray and not skip_filters else None,
            args.dilate if not skip_filters else 0,
            args.blur if not skip_filters else 0.0,
            args.dct_denoise,
        )
        # Normalize uncommon modes before encoding.
        if img.mode not in ("RGB", "L", "1"):
            img = img.convert("RGB")
        images.append(img)
        page_sizes.append((page.rect.width, page.rect.height))

    filter_counts = Counter(_pdf_filter_name(img.mode, use_jpeg2000, args.lossless) for img in images)
    summary = ", ".join(f"{name} x{count}" for name, count in sorted(filter_counts.items()))
    print(f"PDF image encoding ({len(images)} pages): {summary}")
    if "JPXDecode" in filter_counts and not args.lossless:
        print(f"JPEG 2000 target quality: {_quality_to_db(args.quality):.1f} dB")

    doc.close()

    _save_pdf(images, output_pdf, args.quality, use_jpeg2000, page_sizes, args.lossless)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
