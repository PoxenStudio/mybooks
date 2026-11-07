import sys

import fitz
import pytest
from PIL import Image, features

from tools.pdf.minify_pdf import _prepare_pdf_image, _quality_to_db, _save_pdf, main


@pytest.mark.skipif(not features.check_codec("jpg_2000"), reason="Pillow has no JPEG 2000 support")
def test_gray_pages_use_jpeg2000_and_remain_grayscale(tmp_path):
    images = [
        _prepare_pdf_image(Image.new("L", (32, 24), 128), use_jpeg2000=True),
        _prepare_pdf_image(Image.new("1", (32, 24), 1), use_jpeg2000=True),
    ]
    output_pdf = tmp_path / "gray.pdf"

    _save_pdf(images, output_pdf, qualify=75, use_jpeg2000=True)

    with fitz.open(output_pdf) as doc:
        gray_xref = doc[0].get_images(full=True)[0][0]
        binary_xref = doc[1].get_images(full=True)[0][0]
        assert doc.xref_get_key(gray_xref, "Filter") == ("name", "/JPXDecode")
        assert doc.extract_image(gray_xref)["cs-name"] == "DeviceGray"
        assert doc.xref_get_key(binary_xref, "Filter") == ("array", "[/CCITTFaxDecode]")


def test_jpeg_fallback_keeps_grayscale_and_dct_encoding(tmp_path):
    image = _prepare_pdf_image(Image.new("L", (32, 24), 128), use_jpeg2000=False)
    output_pdf = tmp_path / "fallback.pdf"

    _save_pdf([image], output_pdf, qualify=75, use_jpeg2000=False)

    with fitz.open(output_pdf) as doc:
        image_xref = doc[0].get_images(full=True)[0][0]
        assert doc.xref_get_key(image_xref, "Filter") == ("name", "/DCTDecode")
        assert doc.extract_image(image_xref)["cs-name"] == "DeviceGray"


def test_quality_factor_maps_to_jpeg2000_db():
    assert _quality_to_db(1) == pytest.approx(20.2)
    assert _quality_to_db(75) == pytest.approx(35.0)
    assert _quality_to_db(100) == pytest.approx(40.0)


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
        assert doc.metadata["creator"] == "MyBooks(https://mybooks.top)"
        if features.check_codec("jpg_2000"):
            assert doc.xref_get_key(doc.pdf_catalog(), "Version") == ("name", "/1.5")
