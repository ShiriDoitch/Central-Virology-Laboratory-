"""הקטנת תמונות גדולות לפני השליחה למודל (src/intake.py): רק מעל הסף; מתחתיו אותם בתים בדיוק. בלי API."""
import io
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from src import intake


def make_pdf(path, width_pt, height_pt, text="טופס בדיקה"):
    doc = pymupdf.open()
    page = doc.new_page(width=width_pt, height=height_pt)
    page.insert_text((50, 100), "commitment 123456", fontsize=40)
    doc.save(path)
    doc.close()
    return str(path)


def size_of(jpeg):
    return Image.open(io.BytesIO(jpeg)).size


def test_normal_page_is_byte_identical_to_the_old_behaviour(tmp_path):
    path = make_pdf(tmp_path / "a4.pdf", 595, 842)
    doc = pymupdf.open(path)
    expected = doc[0].get_pixmap(dpi=200).tobytes("jpeg", jpg_quality=intake.JPEG_QUALITY)
    doc.close()
    assert intake.pdf_to_images(path)[0] == expected
    assert size_of(expected) in {(1654, 2339), (1653, 2339)}


def test_saved_sample_pdf_unchanged_if_present():
    sample = Path("data/clean_part1.pdf")
    if not sample.exists():
        pytest.skip("no sample pdf")
    doc = pymupdf.open(str(sample))
    expected = doc[1].get_pixmap(dpi=200).tobytes("jpeg", jpg_quality=intake.JPEG_QUALITY)
    doc.close()
    assert intake.pdf_to_images(str(sample), pages=[2])[0] == expected


def test_oversized_page_is_rendered_at_reduced_size(tmp_path):
    path = make_pdf(tmp_path / "huge.pdf", 2250, 3000)           # צילום 3000x4000 שהומר ל-PDF: 52 מגה-פיקסל ב-200 DPI
    jpeg = intake.pdf_to_images(path)[0]
    w, h = size_of(jpeg)
    assert max(w, h) == intake.IMAGE_LONG_SIDE and abs(w / h - 2250 / 3000) < 0.01
    assert w * h <= intake.IMAGE_MAX_PIXELS and len(jpeg) < 2 * 1024 * 1024


def test_just_below_the_pixel_threshold_is_not_touched(tmp_path):
    # 2000x2400 pt ב-200 DPI = 5555x6666 = 37Mpx (מעל); 1100x1300 pt = 3055x3611 = 11Mpx (מתחת)
    path = make_pdf(tmp_path / "mid.pdf", 1100, 1300)
    doc = pymupdf.open(path)
    expected = doc[0].get_pixmap(dpi=200).tobytes("jpeg", jpg_quality=intake.JPEG_QUALITY)
    doc.close()
    assert size_of(expected)[0] * size_of(expected)[1] <= intake.IMAGE_MAX_PIXELS
    assert intake.pdf_to_images(path)[0] == expected


def test_byte_threshold_shrinks_even_when_pixels_are_below_limit(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "a4.pdf", 595, 842)
    monkeypatch.setattr(intake, "IMAGE_MAX_BYTES", 1000)             # כל JPEG "כבד מדי"
    monkeypatch.setattr(intake, "IMAGE_LONG_SIDE", 1000)
    jpeg = intake.pdf_to_images(path)[0]
    assert max(size_of(jpeg)) == 1000


def test_shrink_jpeg_contract():
    im = Image.new("RGB", (3000, 2000), "white")
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    big = buf.getvalue()
    small = intake.shrink_jpeg(big, 1000)
    assert size_of(small) == (1000, 667)
    assert intake.shrink_jpeg(small, 1000) is small                  # כבר קטן: אותם בתים (אובייקט זהה)
    assert intake.shrink_jpeg(b"not an image") == b"not an image"     # בייטים לא תקינים: לא קורס
