#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
from typing import Optional

import fitz
from PIL import Image
from PIL import features
from PIL import ImageFilter
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


def _prepare_pdf_image(img: Image.Image, use_jpeg2000: bool) -> Image.Image:
    """Prepare images so Pillow's PDF writer uses JPEG 2000 for continuous tones."""
    if not use_jpeg2000 or img.mode == "1":
        return img

    if img.mode == "L":
        return img.convert("LA")
    if img.mode == "RGB":
        return img.convert("RGBA")
    raise ValueError(f"Unsupported image mode for PDF output: {img.mode}")


def _quality_to_db(qualify: int) -> float:
    """Map the 1-100 quality option to a JPEG 2000 target quality of 20-40 dB."""
    return 20.0 + qualify * 0.2


def _save_pdf(images: list[Image.Image], output_pdf: Path, qualify: int, use_jpeg2000: bool) -> None:
    first, *rest = images
    encoder_options = {"quality_mode": "dB", "quality_layers": [_quality_to_db(qualify)], "irreversible": True}
    if not use_jpeg2000:
        encoder_options = {"quality": qualify}

    first.save(
        output_pdf,
        save_all=True,
        append_images=rest,
        optimize=True,
        resolution=150,
        **encoder_options,
    )


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
) -> Image.Image:
    src_width = float(page.rect.width)
    if max_width and src_width > 0:
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
        "--qualify",
        type=int,
        default=75,
        help="Quality factor (1-100). JPEG 2000 maps this to 20-40 dB (75 = 35 dB); lower means smaller file.",
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
    if args.qualify < 1 or args.qualify > 100:
        raise ValueError("--qualify must be in range 1-100")
    if args.blur < 0:
        raise ValueError("--blur must be >= 0")
    if args.dilate < 0:
        raise ValueError("--dilate must be >= 0")
    if args.max_brightness is not None and (args.max_brightness < 0 or args.max_brightness > 255):
        raise ValueError("--max-brightness must be in range 0-255")
    if args.max_brightness is not None and not args.gray:
        raise ValueError("--max-brightness requires --gray")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    output_pdf = output_dir / f"{input_path.stem}_minify.pdf"
    use_jpeg2000 = features.check_codec("jpg_2000")
    if not use_jpeg2000:
        print("Warning: Pillow JPEG 2000 support is unavailable; using JPEG compression.")

    doc = fitz.open(str(input_path))
    total_pages = len(doc)
    if total_pages == 0:
        raise ValueError("Input PDF has no pages")
    skip_page_indices = _parse_page_selection(args.skip_pages, total_pages, "--skip-pages")
    drop_page_indices = _parse_page_selection(args.drop_pages, total_pages, "--drop-pages")
    kept_page_indices = [index for index in range(total_pages) if index not in drop_page_indices]
    if not kept_page_indices:
        raise ValueError("All pages were dropped by --drop-pages")

    dry_run_pages = min(args.dry_run_pages, len(kept_page_indices))
    if dry_run_pages > 0:
        for output_index, page_index in enumerate(kept_page_indices[:dry_run_pages], start=1):
            page = doc.load_page(page_index)
            skip_filters = page_index in skip_page_indices
            img = _render_page(
                page,
                args.max_width,
                args.bw and not skip_filters,
                args.gray and not skip_filters,
                args.auto and not skip_filters,
                args.max_brightness if args.gray and not skip_filters else None,
                args.dilate if not skip_filters else 0,
                args.blur if not skip_filters else 0.0,
            )
            preview_path = output_dir / f"{input_path.stem}_preview_{output_index:04d}.png"
            img.save(preview_path, format="PNG")
            print(f"[dry-run] saved: {preview_path}")
        doc.close()
        print(f"Dry run completed: {dry_run_pages} page(s)")
        return 0

    images = []
    for page_index in kept_page_indices:
        page = doc.load_page(page_index)
        skip_filters = page_index in skip_page_indices
        img = _render_page(
            page,
            args.max_width,
            args.bw and not skip_filters,
            args.gray and not skip_filters,
            args.auto and not skip_filters,
            args.max_brightness if args.gray and not skip_filters else None,
            args.dilate if not skip_filters else 0.0,
            args.blur if not skip_filters else 0.0,
        )
        # Normalize uncommon modes before encoding.
        if img.mode not in ("RGB", "L", "1"):
            img = img.convert("RGB")
        img = _prepare_pdf_image(img, use_jpeg2000)
        images.append(img)

    doc.close()

    _save_pdf(images, output_pdf, args.qualify, use_jpeg2000)

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
