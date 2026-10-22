"""חיתוך לבדיקה אנושית (מסך האישור) נדיב: לא חותך את הספרות האחרונות של מספר ההתחייבות, גם כשהאזור המאומת מקומית צר או קרוב לקצה."""
from pathlib import Path

import pytest

from src.confirm import field_crop, field_fractions
from src.crop import REVIEW_MARGIN, REVIEW_MIN_PAD, review_fractions
from src.intake import render_region

PDF = Path("data/clean_part1.pdf")


def test_review_window_adds_margin_on_every_side_inside_the_page():
    x0, y0, x1, y1 = 0.40, 0.50, 0.60, 0.54
    rx0, ry0, rx1, ry1 = review_fractions((x0, y0, x1, y1))
    assert rx0 <= x0 - (x1 - x0) * REVIEW_MARGIN + 1e-9 and rx1 >= x1 + (x1 - x0) * REVIEW_MARGIN - 1e-9
    assert ry0 <= y0 - REVIEW_MIN_PAD + 1e-9 and ry1 >= y1 + REVIEW_MIN_PAD - 1e-9     # גובה צר: מינימום 3% מהעמוד
    assert 0 <= rx0 < x0 and x1 < rx1 <= 1 and 0 <= ry0 < y0 and y1 < ry1 <= 1


def test_review_window_at_page_edge_is_shifted_inward_not_cut():
    rx0, _ry0, rx1, _ry1 = review_fractions((0.0, 0.5, 0.2, 0.55))
    assert rx0 == 0.0 and rx1 - rx0 >= 0.2 * (1 + 2 * REVIEW_MARGIN) - 1e-9           # הגודל נשמר, הרחבה לצד השני


def test_commitment_review_crop_is_wider_and_taller_than_the_verified_barcode_box():
    """החיתוך שמוצג לאדם (field_crop) רחב וגבוה מתיבת הברקוד המאומתת עצמה (אלא אם כבר בקצה העמוד): אותה הרחבה
    שהייתה קיימת סביב ה-box של המודל חלה עכשיו סביב האזור המאומת מקומית (ראו test_confirm.py לאימות עצמו)."""
    import io

    from PIL import Image

    page = {"page": 1, "rotation": {"applied": 0},
            "barcodes": [{"format": "Code128", "text": "50364186", "box": [0.3, 0.6, 0.5, 0.62]}]}
    model_fr = field_fractions(page, "commitment", "50364186")
    assert model_fr is not None
    old = render_region(str(PDF), page["page"], model_fr, scale=3.0, rotation=0) if PDF.exists() else None
    new = field_crop(str(PDF) if PDF.exists() else "no_such_file.pdf", page, "commitment", "50364186")
    if old is None or not new:
        pytest.skip("no sample pdf")
    w_old, h_old = Image.open(io.BytesIO(old)).size
    w_new, h_new = Image.open(io.BytesIO(new)).size
    assert w_new >= w_old * 1.1 and h_new >= h_old * 1.1


def test_page_with_a_barcode_near_the_edge_the_review_window_is_shifted_inward_not_cut():
    """תיבת ברקוד מאומתת שצמודה לקצה העמוד (ימין): החלון לבדיקה מתרחב לכיוון הפנים ולא נחתך, ולא קטן מהתיבה המקורית."""
    page = {"page": 1, "rotation": {"applied": 0},
            "barcodes": [{"format": "Code128", "text": "260005102632", "box": [0.9, 0.3, 0.995, 0.34]}]}
    x0, y0, x1, y1 = field_fractions(page, "commitment", "260005102632")
    rx0, ry0, rx1, ry1 = review_fractions((x0, y0, x1, y1))
    assert rx1 <= 1.0 and rx0 < x0                                          # לא נחתך בקצה, והורחב פנימה
    assert (rx1 - rx0) >= (x1 - x0) and (ry1 - ry0) >= (y1 - y0) * 1.3
