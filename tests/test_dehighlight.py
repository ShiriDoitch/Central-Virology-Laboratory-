"""scripts/make_dehighlighted.py: ערוץ האפור min(R,G) מוציא את ההדגש הצהוב ומשאיר דיו שחור וכחול כהים.
מקומי לגמרי, בלי שום קריאה למודל."""
import pymupdf
import pytest
from PIL import Image

from scripts.make_dehighlighted import dehighlight_image, dehighlight_pdf, render_pages, save_pdf

YELLOW = (255, 255, 0)
HIGHLIGHTER = (250, 237, 90)        # צהוב מדגש אמיתי, לא רווי לגמרי
BLACK = (0, 0, 0)
BLUE = (20, 30, 160)
PEN_BLUE = (60, 80, 180)
WHITE = (255, 255, 255)
NEAR_WHITE = 230                    # מעל זה נחשב "כמעט לבן" (צהוב רווי: 255; דיו מדגש אמיתי: ~237)
DARK = 100                          # מתחת לזה נחשב כהה


def one_pixel(color) -> int:
    """מחזיר את ערך האפור של פיקסל יחיד אחרי הסרת ההדגש."""
    img = Image.new("RGB", (1, 1), color)
    out = dehighlight_image(img)
    assert out.mode == "L"
    return out.getpixel((0, 0))


def test_yellow_becomes_near_white():
    assert one_pixel(YELLOW) >= NEAR_WHITE
    assert one_pixel(HIGHLIGHTER) >= NEAR_WHITE


def test_black_stays_dark():
    assert one_pixel(BLACK) <= DARK


def test_blue_stays_dark():
    assert one_pixel(BLUE) <= DARK
    assert one_pixel(PEN_BLUE) <= DARK


def test_white_stays_white():
    assert one_pixel(WHITE) >= NEAR_WHITE


def test_black_text_under_yellow_highlight_stays_dark():
    """הדגשה צהובה מעל כתב שחור: הצהוב מתבהר, הכתב נשאר כהה (אותה תמונה, שני פיקסלים)."""
    img = Image.new("RGB", (2, 1), YELLOW)
    img.putpixel((1, 0), BLACK)
    out = dehighlight_image(img)
    assert out.getpixel((0, 0)) >= NEAR_WHITE
    assert out.getpixel((1, 0)) <= DARK


def test_dimensions_and_mode_preserved():
    out = dehighlight_image(Image.new("RGB", (7, 3), YELLOW))
    assert out.size == (7, 3)
    assert out.mode == "L"


def _yellow_pdf(path, pages: int = 2):
    """PDF קטן: עמוד צהוב עם ריבוע שחור."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=200, height=200)
        page.draw_rect(pymupdf.Rect(0, 0, 200, 200), color=None, fill=(1, 1, 0))
        page.draw_rect(pymupdf.Rect(20, 20, 80, 80), color=None, fill=(0, 0, 0))
    doc.save(path)
    doc.close()


def test_dehighlight_pdf_keeps_page_count_and_clears_yellow(tmp_path):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _yellow_pdf(src, pages=2)
    cleaned = dehighlight_pdf(src, out, dpi=72)
    assert out.exists()
    assert len(cleaned) == 2
    with pymupdf.open(out) as doc:
        assert doc.page_count == 2
    page = cleaned[0]
    assert page.getpixel((page.width - 2, page.height - 2)) >= NEAR_WHITE    # היה צהוב
    assert page.getpixel((page.width // 8, page.height // 8)) <= DARK        # הריבוע השחור


def test_render_pages_selects_pages(tmp_path):
    src = tmp_path / "in.pdf"
    _yellow_pdf(src, pages=3)
    assert len(render_pages(src, dpi=72)) == 3
    assert len(render_pages(src, dpi=72, pages=[2])) == 1


def test_save_pdf_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        save_pdf([], tmp_path / "x.pdf")
