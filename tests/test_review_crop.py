"""חיתוך לבדיקה אנושית (מסך האישור) נדיב: לא חותך את הספרות האחרונות של מספר ההתחייבות, גם כשה-box של המודל צר או מוסט."""
import json
from pathlib import Path

import pytest

from src.confirm import field_crop, field_fractions
from src.crop import REVIEW_MARGIN, REVIEW_MIN_PAD, review_fractions
from src.intake import render_region

RUN = Path("outputs/clean_part1_v4b")
PDF = Path("data/clean_part1.pdf")
needs_sample = pytest.mark.skipif(not (RUN / "p1.json").exists() or not PDF.exists(), reason="needs the saved sample run")


def test_review_window_adds_margin_on_every_side_inside_the_page():
    x0, y0, x1, y1 = 0.40, 0.50, 0.60, 0.54
    rx0, ry0, rx1, ry1 = review_fractions((x0, y0, x1, y1))
    assert rx0 <= x0 - (x1 - x0) * REVIEW_MARGIN + 1e-9 and rx1 >= x1 + (x1 - x0) * REVIEW_MARGIN - 1e-9
    assert ry0 <= y0 - REVIEW_MIN_PAD + 1e-9 and ry1 >= y1 + REVIEW_MIN_PAD - 1e-9     # גובה צר: מינימום 3% מהעמוד
    assert 0 <= rx0 < x0 and x1 < rx1 <= 1 and 0 <= ry0 < y0 and y1 < ry1 <= 1


def test_review_window_at_page_edge_is_shifted_inward_not_cut():
    rx0, _ry0, rx1, _ry1 = review_fractions((0.0, 0.5, 0.2, 0.55))
    assert rx0 == 0.0 and rx1 - rx0 >= 0.2 * (1 + 2 * REVIEW_MARGIN) - 1e-9           # הגודל נשמר, הרחבה לצד השני


def _commitment_pages():
    out = []
    for f in sorted(RUN.glob("p*.json"), key=lambda x: int(x.stem[1:])):
        res = json.loads(f.read_text(encoding="utf-8"))
        if field_fractions(res, "commitment"):
            out.append(res)
    return out


@needs_sample
def test_saved_run_commitment_crop_is_wider_and_taller_than_the_model_crop():
    """בכל עמוד בדוגמה השמורה שיש בו חיתוך התחייבות: החיתוך שמוצג לאדם רחב וגבוה מזה של המודל (אלא אם כבר בקצה העמוד)."""
    import io

    from PIL import Image

    pages = _commitment_pages()
    assert pages, "the sample run should contain commitment crops"
    for res in pages:
        model_fr = field_fractions(res, "commitment")
        rot = (res.get("rotation") or {}).get("applied") or 0
        old = render_region(str(PDF), res["page"], model_fr, scale=3.0, rotation=rot)
        new = field_crop(str(PDF), res, "commitment")
        assert new, res["page"]
        w_old, h_old = Image.open(io.BytesIO(old)).size
        w_new, h_new = Image.open(io.BytesIO(new)).size
        assert w_new >= w_old * 1.3 or model_fr[0] < 0.01 or model_fr[2] > 0.99, (res["page"], w_old, w_new)
        assert h_new >= h_old * 1.3 or model_fr[1] < 0.01 or model_fr[3] > 0.99, (res["page"], h_old, h_new)


@needs_sample
def test_page25_three_stacked_commitments_the_original_window_cut_the_digits_the_review_window_has_room():
    """עמוד 25 (שלוש התחייבויות זו מעל זו, 260005102632 / 260005102611 / 260005102644): ה-box של המודל מסתיים באמצע הספרות
    (קצה העמוד מימין), והחיתוך לבדיקה מתרחב לכיוון הפנים עד שהספרות הסופיות נכנסות. נבדק גם שהחלון לא קטן מהחלון המקורי."""
    res = json.loads((RUN / "p25.json").read_text(encoding="utf-8"))
    x0, y0, x1, y1 = field_fractions(res, "commitment")
    rx0, ry0, rx1, ry1 = review_fractions((x0, y0, x1, y1))
    assert rx0 <= x0 - 0.1 and ry0 <= y0 - 0.02 and ry1 >= y1 + 0.02        # נוסף מרווח בצד שאינו קצה העמוד, ומעל ומתחת
    assert (rx1 - rx0) >= (x1 - x0) * 1.3 and (ry1 - ry0) >= (y1 - y0) * 1.3
