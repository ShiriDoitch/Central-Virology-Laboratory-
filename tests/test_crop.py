import io

import pytest
from PIL import Image

from src import cache, extractor
from src.crop import FALLBACK_BOXES, box_to_fractions, choose_box, crop_image, is_valid_box, pad_fractions, rotate_fractions_cw
from src.schema import Box


def b(ymin, xmin, ymax, xmax):
    return Box(ymin=ymin, xmin=xmin, ymax=ymax, xmax=xmax)


@pytest.mark.parametrize("box", [b(100, 100, 300, 400), b(0, 0, 1000, 800)])
def test_valid_boxes(box):
    assert is_valid_box(box)


@pytest.mark.parametrize("box", [
    None,
    b(300, 100, 100, 400),     # ymax < ymin
    b(100, 400, 300, 100),     # xmax < xmin
    b(100, 100, 100, 400),     # שטח אפס
    b(-5, 0, 300, 400),        # מחוץ ל-0..1000
    b(0, 0, 1200, 1000),
    b(500, 500, 502, 502),     # זעיר: חשוד
    b(0, 0, 1000, 1000),       # כל העמוד: לא חיתוך
])
def test_invalid_boxes(box):
    assert not is_valid_box(box)


def test_choose_box_falls_back_when_invalid():
    box, fallback = choose_box("patient", None)
    assert fallback and box == FALLBACK_BOXES["patient"]
    good = b(100, 100, 300, 400)
    box, fallback = choose_box("barcode", good)
    assert not fallback and box == good


# ---------- מיקום ברקוד שפוענח ישירות מה-PDF (בלי הסיבוב הנוסף): מיפוי לעמוד המסובב לתצוגה ----------

def test_rotate_fractions_cw_is_identity_at_zero():
    fr = (0.1, 0.2, 0.3, 0.4)
    assert rotate_fractions_cw(fr, 0) == fr


def test_rotate_fractions_cw_90_moves_top_left_to_top_right():
    # תיבה צרה בפינה השמאלית-עליונה של העמוד הלא-מסובב: אחרי סיבוב 90 בכיוון השעון היא בפינה הימנית-עליונה
    x0, y0, x1, y1 = rotate_fractions_cw((0.0, 0.0, 0.1, 0.2), 90)
    assert x0 == pytest.approx(0.8) and x1 == pytest.approx(1.0) and y0 == pytest.approx(0.0) and y1 == pytest.approx(0.1)


def test_rotate_fractions_cw_180_is_the_opposite_corner():
    assert rotate_fractions_cw((0.1, 0.2, 0.3, 0.4), 180) == pytest.approx((0.7, 0.6, 0.9, 0.8))


def test_rotate_fractions_cw_270_moves_top_left_to_bottom_left():
    x0, y0, x1, y1 = rotate_fractions_cw((0.0, 0.0, 0.1, 0.2), 270)
    assert x0 == pytest.approx(0.0) and x1 == pytest.approx(0.2) and y0 == pytest.approx(0.9) and y1 == pytest.approx(1.0)


def test_rotate_fractions_cw_three_times_is_270():
    fr = (0.1, 0.15, 0.3, 0.4)
    once = rotate_fractions_cw(fr, 90)
    thrice = rotate_fractions_cw(rotate_fractions_cw(once, 90), 90)
    assert thrice == pytest.approx(rotate_fractions_cw(fr, 270))


def test_rotate_fractions_cw_rejects_non_right_angles():
    with pytest.raises(ValueError):
        rotate_fractions_cw((0, 0, 0.1, 0.1), 45)


def test_pad_fractions_adds_margin_without_cutting_at_the_page_edge():
    x0, y0, x1, y1 = pad_fractions((0.4, 0.5, 0.5, 0.52), margin=0.25, min_pad=0.02)
    assert x0 < 0.4 and x1 > 0.5 and y1 - y0 >= 0.02 * 2           # גובה צר: מינימום 2% מהעמוד מכל צד
    x0, _y0, x1, _y1 = pad_fractions((0.0, 0.5, 0.1, 0.55), margin=0.25, min_pad=0.02)
    assert x0 == 0.0 and x1 > 0.1                                  # בקצה העמוד: הוזז פנימה, לא נחתך


def test_fractions_have_margin_and_stay_inside_page():
    x0, y0, x1, y1 = box_to_fractions(b(100, 200, 300, 600))
    assert x0 < 0.2 and x1 > 0.6 and y0 < 0.1 and y1 > 0.3
    assert 0 <= x0 and x1 <= 1 and 0 <= y0 and y1 <= 1
    assert box_to_fractions(b(0, 0, 100, 100))[:2] == (0.0, 0.0)          # נחתך בקצה
    assert box_to_fractions(b(900, 900, 1000, 1000))[2:] == (1.0, 1.0)


def test_crop_image_size_and_scale():
    im = Image.new("RGB", (1000, 2000), "white")
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    out = Image.open(io.BytesIO(crop_image(buf.getvalue(), (0.1, 0.1, 0.5, 0.3), scale=3)))
    assert out.size == (1200, 1200)    # 400x400 מוגדל פי 3


# ---------- מעבר שני: JSON שבור לא מקריס ----------

def _fake_client(monkeypatch, text):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(extractor, "_call_with_fallback", lambda *a, **k: (text, "fake-model"))


def test_regions_broken_json_does_not_crash(monkeypatch):
    _fake_client(monkeypatch, "{not json")
    result = extractor.extract_regions({"patient": b"x", "barcode": b"y"})
    assert result["ok"] is False
    assert result["error"] == "model returned invalid JSON"


def test_regions_valid_json_parses(monkeypatch):
    _fake_client(monkeypatch, '{"patient": {}, "barcode": {"visible_words": ["x"]}}')
    result = extractor.extract_regions({"patient": b"x", "barcode": b"y"})
    assert result["ok"] and result["model"] == "fake-model"
    assert result["barcode"]["visible_words"] == ["x"]
    assert result["barcode"]["central_number"]["value"] is None


def test_first_pass_broken_json_does_not_crash(monkeypatch):
    _fake_client(monkeypatch, "oops")
    assert extractor.extract([b"img"])["ok"] is False


def test_regions_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = []

    def fn(crops):
        calls.append(1)
        return {"ok": True, "model": "m"}

    crops = {"patient": b"a", "barcode": b"b"}
    assert cache.cached_regions(crops, fn)[1] is False
    assert cache.cached_regions(crops, fn)[1] is True
    assert cache.cached_regions({"patient": b"a", "barcode": b"c"}, fn)[1] is False   # חיתוך אחר
    assert len(calls) == 2
    assert cache.regions_cache_key(crops) != cache.cache_key([b"a", b"b"])             # מפתחות נפרדים לשני המעברים
