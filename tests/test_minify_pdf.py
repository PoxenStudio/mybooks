import io
import sys

import fitz
import pytest
from PIL import Image, features

from tools.pdf.minify_pdf import (
    _apply_dct_denoise,
    _image_color_info,
    _page_has_dct_image,
    _page_render_dpi,
    _quality_to_db,
    _save_pdf,
    main,
)


@pytest.mark.skipif(not features.check_codec("jpg_2000"), reason="Pillow has no JPEG 2000 support")
def test_gray_pages_use_jpeg2000_and_remain_grayscale(tmp_path):
    images = [Image.new("L", (32, 24), 128), Image.new("1", (32, 24), 1)]
    output_pdf = tmp_path / "gray.pdf"

    _save_pdf(images, output_pdf, quality=75, use_jpeg2000=True)

    with fitz.open(output_pdf) as doc:
        gray_xref = doc[0].get_images(full=True)[0][0]
        binary_xref = doc[1].get_images(full=True)[0][0]
        assert doc.xref_get_key(gray_xref, "Filter") == ("name", "/JPXDecode")
        assert doc.extract_image(gray_xref)["cs-name"] == "DeviceGray"
        assert doc.xref_get_key(binary_xref, "Filter") == ("array", "[/CCITTFaxDecode]")


def test_jpeg_fallback_keeps_grayscale_and_dct_encoding(tmp_path):
    image = Image.new("L", (32, 24), 128)
    output_pdf = tmp_path / "fallback.pdf"

    _save_pdf([image], output_pdf, quality=75, use_jpeg2000=False)

    with fitz.open(output_pdf) as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        assert doc.xref_get_key(image_xref, "Filter") == ("name", "/DCTDecode")
        assert doc.extract_image(image_xref)["cs-name"] == "DeviceGray"


@pytest.mark.skipif(not features.check_codec("jpg_2000"), reason="Pillow has no JPEG 2000 support")
def test_lossless_jpeg2000_preserves_gray_and_bilevel_pixels(tmp_path):
    gray = Image.new("L", (32, 24))
    bilevel = Image.new("1", (32, 24))
    for y in range(24):
        for x in range(32):
            gray.putpixel((x, y), (x * 11 + y * 7) % 256)
            bilevel.putpixel((x, y), (x + y) % 2)

    output_pdf = tmp_path / "lossless.pdf"
    _save_pdf([gray, bilevel], output_pdf, quality=75, use_jpeg2000=True, lossless=True)

    with fitz.open(output_pdf) as doc:
        for page, source in zip(doc, (gray, bilevel)):
            image_xref = page.get_images(full=True)[0][0]
            assert doc.xref_get_key(image_xref, "Filter") == ("name", "/JPXDecode")
            extracted = doc.extract_image(image_xref)["image"]
            decoded = Image.open(io.BytesIO(extracted)).convert("L")
            assert decoded.tobytes() == source.convert("L").tobytes()


def test_quality_factor_maps_to_jpeg2000_db():
    assert _quality_to_db(1) == pytest.approx(20.2)
    assert _quality_to_db(75) == pytest.approx(35.0)
    assert _quality_to_db(100) == pytest.approx(40.0)


def test_dct_denoise_removes_speckles_without_erasing_edge():
    image = Image.new("L", (9, 9), 255)
    for y in range(9):
        for x in range(4):
            image.putpixel((x, y), 0)
    image.putpixel((6, 4), 0)

    denoised = _apply_dct_denoise(image, strength=1)

    assert denoised.getpixel((6, 4)) == 255
    assert denoised.getpixel((3, 4)) == 0
    assert denoised.getpixel((4, 4)) == 255


def test_page_has_dct_image_detects_jpeg_only(tmp_path):
    jpeg_path = tmp_path / "image.jpg"
    png_path = tmp_path / "image.png"
    Image.new("RGB", (16, 16), "white").save(jpeg_path, format="JPEG")
    Image.new("RGB", (16, 16), "white").save(png_path, format="PNG")

    with fitz.open() as doc:
        jpeg_page = doc.new_page()
        jpeg_page.insert_image(jpeg_page.rect, filename=str(jpeg_path))
        png_page = doc.new_page()
        png_page.insert_image(png_page.rect, filename=str(png_path))

        assert _page_has_dct_image(doc.load_page(0))
        assert not _page_has_dct_image(doc.load_page(1))


@pytest.mark.parametrize(
    ("colorspace", "bits_per_component", "expected"),
    [
        ("DeviceRGB", 8, ("RGB", 3)),
        ("DeviceGray", 8, ("Gray", 1)),
        ("DeviceGray", 1, ("BW", 1)),
    ],
)
def test_image_color_info_reports_mode_and_channel_count(colorspace, bits_per_component, expected):
    assert _image_color_info(colorspace, "", bits_per_component) == expected


def test_full_page_scan_is_not_upsampled_and_retains_page_size(tmp_path, monkeypatch):
    source_pdf = tmp_path / "scan.pdf"
    source_doc = fitz.open()
    page = source_doc.new_page(width=300, height=450)
    pixels = Image.new("RGB", (400, 600), "white")
    image_buffer = tmp_path / "scan.jpg"
    pixels.save(image_buffer, format="JPEG")
    page.insert_image(page.rect, filename=str(image_buffer))
    assert _page_render_dpi(page) == pytest.approx(96)
    source_doc.save(source_pdf)
    source_doc.close()

    output_dir = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["minify_pdf.py", str(source_pdf), "--output-dir", str(output_dir), "--gray"])
    assert main() == 0

    with fitz.open(output_dir / "scan_minify.pdf") as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        assert doc.extract_image(image_xref)["width"] == 400
        assert doc.extract_image(image_xref)["height"] == 600
        assert doc[0].rect.width == pytest.approx(300)
        assert doc[0].rect.height == pytest.approx(450)


def test_gray_cli_output_is_grayscale_pdf(tmp_path, monkeypatch):
    source_pdf = tmp_path / "source.pdf"
    source_doc = fitz.open()
    page = source_doc.new_page(width=400, height=600)
    page.insert_text((40, 50), "A grayscale PDF conversion check.")
    source_doc.save(source_pdf)
    source_doc.close()

    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "minify_pdf.py",
            str(source_pdf),
            "--output-dir",
            str(output_dir),
            "--max-width",
            "800",
            "--auto",
            "--gray",
            "--blur",
            "0.1",
        ],
    )

    assert main() == 0

    output_pdf = output_dir / "source_minify.pdf"
    with fitz.open(output_pdf) as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        expected_filter = "/JPXDecode" if features.check_codec("jpg_2000") else "/DCTDecode"
        assert doc.xref_get_key(image_xref, "Filter") == ("name", expected_filter)
        assert doc.extract_image(image_xref)["cs-name"] == "DeviceGray"
        assert doc[0].rect.width == pytest.approx(400)
        assert doc[0].rect.height == pytest.approx(600)
        assert doc.metadata["creator"] == "MyBooks(https://mybooks.top)"
        if features.check_codec("jpg_2000"):
            assert doc.xref_get_key(doc.pdf_catalog(), "Version") == ("name", "/1.5")


def test_inspect_cli_reports_distinct_image_info_from_first_five_pages(tmp_path, monkeypatch, capsys):
    source_pdf = tmp_path / "source.pdf"
    image_path = tmp_path / "image.jpg"
    Image.new("RGB", (96, 64), "white").save(image_path, format="JPEG")

    source_doc = fitz.open()
    for page_index in range(6):
        page = source_doc.new_page(width=300, height=400)
        if page_index == 4:
            rect = fitz.Rect(0, 0, 48, 32)
        elif page_index == 5:
            rect = fitz.Rect(0, 0, 24, 16)
        else:
            rect = fitz.Rect(0, 0, 72, 48)
        page.insert_image(rect, filename=str(image_path))
    source_doc.save(source_pdf)
    source_doc.close()

    output_dir = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        ["minify_pdf.py", str(source_pdf), "--inspect", "--output-dir", str(output_dir)],
    )

    assert main() == 0

    output = capsys.readouterr().out
    assert output.count("DCTDecode") == 2
    assert "Page size: 4.17 x 5.56 in | Pages: 1, 2, 3, 4, 5" in output
    assert "96 DPI | RGB (3 channels) | Pages: 1, 2, 3, 4" in output
    assert "144 DPI | RGB (3 channels) | Pages: 5" in output
    assert "Pages: 6" not in output
    assert not output_dir.exists()
