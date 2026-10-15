import io

import pymupdf
import pytest
from PIL import Image

from src import pipeline
from src.intake import render_region, rotate_jpeg
from src.pipeline import plan_rotation, process_page
from src.schema import PageExtraction


def jpeg(width, height, color=(255, 255, 255)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG")
    return buf.getvalue()


def size(img_bytes):
    return Image.open(io.BytesIO(img_bytes)).size


# ---------- rotate_jpeg ----------

@pytest.mark.parametrize("degrees,expected", [(90, (400, 300)), (270, (400, 300)), (180, (300, 400))])
def test_rotate_jpeg_dimensions(degrees, expected):
    assert size(rotate_jpeg(jpeg(300, 400), degrees)) == expected


def test_rotate_clockwise_moves_top_left_corner_to_top_right():
    im = Image.new("RGB", (300, 400), "white")
    im.paste((255, 0, 0), (0, 0, 50, 50))                    # פינה שמאלית עליונה אדומה
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    out = Image.open(io.BytesIO(rotate_jpeg(buf.getvalue(), 90))).convert("RGB")   # עם כיוון השעון
    r, g, b = out.getpixel((out.width - 20, 20))               # שמאל-עליון עובר לימין-עליון
    assert r > 200 and g < 80 and b < 80


# ---------- render_region עם rotation ----------

@pytest.fixture
def pdf_path(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=400)
    page.draw_rect(pymupdf.Rect(0, 0, 200, 100), color=(1, 0, 0), fill=(1, 0, 0))   # פס אדום בראש העמוד
    path = tmp_path / "t.pdf"
    doc.save(path)
    doc.close()
    return str(path)


def test_render_region_without_rotation(pdf_path):
    assert size(render_region(pdf_path, 1, (0, 0, 1, 0.5), scale=1)) == (200, 200)


def test_render_region_with_rotation_swaps_page_dimensions(pdf_path):
    # אחרי 90 מעלות העמוד רחב 400 וגבוה 200: החצי העליון הוא 400x100
    assert size(render_region(pdf_path, 1, (0, 0, 1, 0.5), scale=1, rotation=90)) == (400, 100)


def test_render_region_rotation_moves_the_red_band(pdf_path):
    """אחרי 90 מעלות עם כיוון השעון הפס האדום (ראש העמוד) עובר לצד ימין."""
    img = Image.open(io.BytesIO(render_region(pdf_path, 1, (0, 0, 1, 1), scale=1, rotation=90))).convert("RGB")
    assert img.size == (400, 200)
    right = img.getpixel((350, 100))
    left = img.getpixel((50, 100))
    assert right[0] > 200 and right[1] < 80          # אדום בצד ימין
    assert left[0] > 200 and left[1] > 200            # לבן בצד שמאל


# ---------- plan_rotation ----------

@pytest.mark.parametrize("axis,reported,expected", [
    ("vertical", "270", [270]),
    ("vertical", "90", [90]),
    ("vertical", "0", [90]),          # הגלאי המקומי אומר אנכי, המודל אומר 0: ניחוש 90
    ("vertical", "180", [90]),
    ("horizontal", "0", []),
    ("horizontal", "180", [180]),
    ("horizontal", "90", []),         # המודל מדווח 90 אבל המבנה אופקי: מתעלמים
    ("unknown", "270", [270]),        # אין מידע מקומי: סומכים על המודל
    ("unknown", "0", []),
])
def test_plan_rotation(axis, reported, expected):
    assert plan_rotation(axis, reported) == expected


# ---------- process_page: זרימת הסיבוב (mocks, בלי API) ----------

def page_result(degrees="0", stats=None):
    p = PageExtraction(is_commitment_form=True, page_quality="ok", rotation_degrees=degrees)
    return {"ok": True, "model": "m", "stats": stats or {"api_calls": 1}, **p.model_dump()}


@pytest.fixture
def flow(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "pdf_to_images", lambda path, pages: [b"original"])
    monkeypatch.setattr(pipeline, "rotate_jpeg", lambda img, deg: f"{img.decode()}+{deg}".encode())
    monkeypatch.setattr(pipeline, "render_region", lambda *a, **k: b"crop")
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: ({"ok": False, "error": "x", "stats": {}}, True))
    return calls


def set_pass1(monkeypatch, answers, calls):
    """answers: {image_bytes: תוצאה}. מתעד אילו תמונות נשלחו."""
    def fake(images):
        calls.append(images[0])
        return answers[images[0]], False
    monkeypatch.setattr(pipeline, "cached_extract", fake)


def test_upright_page_is_not_rotated(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("horizontal", 0.9))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("0")}, calls)
    res = process_page("x.pdf", 1)
    assert calls == [b"original"] and res["rotation"]["applied"] is None and not res["page_flags"]


def test_known_direction_reruns_once_and_uses_rotated_result(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("270", {"api_calls": 1}),
                            b"original+270": page_result("0", {"api_calls": 1})}, calls)
    res = process_page("x.pdf", 14)
    assert calls == [b"original", b"original+270"]
    assert res["rotation"] == {"local_axis": "vertical", "reported": "270", "applied": 270, "attempts": 1, "unresolved": False}
    assert res["pass1"]["rotation_degrees"] == "0" and res["page_flags"] == []
    assert res["stats"]["pass1"] == {"api_calls": 2}              # שתי קריאות קטנות למעבר הראשון


def test_guessed_direction_wrong_tries_opposite_once_more(monkeypatch, flow):
    """המודל אמר 0, הגלאי המקומי אמר אנכי: ניחוש 90; התברר הפוך (180) ← 270."""
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("0"), b"original+90": page_result("180"),
                            b"original+270": page_result("0")}, calls)
    res = process_page("x.pdf", 22)
    assert calls == [b"original", b"original+90", b"original+270"]
    assert res["rotation"]["applied"] == 270 and res["rotation"]["attempts"] == 2 and not res["rotation"]["unresolved"]


def test_guessed_direction_correct_stops_after_one_rerun(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("0"), b"original+90": page_result("0")}, calls)
    res = process_page("x.pdf", 22)
    assert calls == [b"original", b"original+90"] and res["rotation"]["applied"] == 90


def test_still_rotated_after_rerun_is_flagged_unresolved_without_more_attempts(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("270"), b"original+270": page_result("90")}, calls)
    res = process_page("x.pdf", 3)
    assert calls == [b"original", b"original+270"]                 # לא ממשיכים
    assert res["rotation"]["unresolved"] is True and res["page_flags"] == ["rotation_unresolved"]


def test_rotated_rerun_failure_keeps_original_and_flags(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("270"), b"original+270": {"ok": False, "error": "503", "stats": {}}}, calls)
    res = process_page("x.pdf", 3)
    assert res["pass1"]["ok"] and res["page_flags"] == ["rotation_unresolved"]


def test_upside_down_page_reported_180_is_rotated(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("horizontal", 0.9))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("180"), b"original+180": page_result("0")}, calls)
    res = process_page("x.pdf", 8)
    assert calls == [b"original", b"original+180"] and res["rotation"]["applied"] == 180


def test_second_pass_crops_use_the_applied_rotation(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4))
    seen = []
    monkeypatch.setattr(pipeline, "render_region", lambda path, page, fr, **k: seen.append(k.get("rotation")) or b"crop")
    p = PageExtraction(is_commitment_form=True, page_quality="ok", rotation_degrees="0")   # בלי ת"ז: מעבר שני נדרש
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("270"), b"original+270": {"ok": True, "model": "m", "stats": {}, **p.model_dump()}}, calls)
    process_page("x.pdf", 14)
    assert seen == [270, 270]                                       # שני החיתוכים (מטופל, ברקוד)


def test_page22_model_direction_wrong_horizontal_but_upside_down_tries_opposite(monkeypatch, flow):
    """עמוד 22: המודל אמר 90 (שגוי), אחרי 90 הטקסט אופקי אבל הפוך והמודל אמר 270: מנסים 270 פעם אחת."""
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4) if img == b"original" else ("horizontal", 0.4))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("90"), b"original+90": page_result("270"),
                            b"original+270": page_result("0")}, calls)
    res = process_page("x.pdf", 22)
    assert calls == [b"original", b"original+90", b"original+270"]
    assert res["rotation"]["applied"] == 270 and res["rotation"]["attempts"] == 2 and not res["rotation"]["unresolved"]


def test_opposite_attempt_also_wrong_is_unresolved_after_two_attempts(monkeypatch, flow):
    monkeypatch.setattr(pipeline, "text_axis", lambda img: ("vertical", -0.4) if img == b"original" else ("horizontal", 0.4))
    calls = []
    set_pass1(monkeypatch, {b"original": page_result("90"), b"original+90": page_result("270"),
                            b"original+270": page_result("180")}, calls)
    res = process_page("x.pdf", 22)
    assert len(calls) == 3 and res["rotation"]["unresolved"] is True
