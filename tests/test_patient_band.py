"""חיתוך המטופל כרצועה לרוחב העמוד, שוליים מינימליים, labels_seen וניסיון חוזר אחד."""
import pytest

from src import extractor, pipeline
from src.crop import (BARCODE_MIN_PAD, ENLARGE_RETRY, PATIENT_MIN_PAD_Y, PATIENT_SIDE_MARGIN, patient_band_fractions,
                      region_fractions)
from src.pipeline import process_page
from src.rules import F_REGION_NOT_OK, apply_field_validity, decide_id, decide_name, patient_labels_missing, region_state
from src.schema import Box, Field_, NumberCandidate, PageExtraction, RegionsExtraction
from tests.test_pipeline import num, r1


def b(ymin, xmin, ymax, xmax):
    return Box(ymin=ymin, xmin=xmin, ymax=ymax, xmax=xmax)


# ---------- רצועה לרוחב כל העמוד ----------

@pytest.mark.parametrize("box", [b(100, 600, 250, 950), b(100, 50, 250, 300), b(100, 400, 250, 450), b(100, 0, 250, 1000)])
def test_band_is_full_width_whatever_the_box_x(box):
    """box צר (כמו עמוד 24: רק העמודה הימנית) לא מצמצם את הרוחב."""
    x0, _, x1, _ = patient_band_fractions(box)
    assert x0 == PATIENT_SIDE_MARGIN and x1 == pytest.approx(1 - PATIENT_SIDE_MARGIN)


def test_band_has_at_least_4_percent_padding_above_and_below():
    box = b(300, 100, 340, 900)                       # box דק (4% גובה): קיצוץ שורת שם פרטי
    _, y0, _, y1 = patient_band_fractions(box)
    assert 0.30 - y0 >= PATIENT_MIN_PAD_Y - 1e-9 and y1 - 0.34 >= PATIENT_MIN_PAD_Y - 1e-9


def test_band_padding_scales_for_tall_boxes_and_clamps_to_page():
    _, y0, _, y1 = patient_band_fractions(b(0, 100, 990, 900))
    assert y0 == 0.0 and y1 == 1.0
    _, y0, _, y1 = patient_band_fractions(b(200, 100, 600, 900))
    assert 0.2 - y0 >= 0.4 * 0.15 - 1e-9                   # שוליים יחסיים גדולים מהמינימום


def test_enlarge_retry_grows_band_height_by_1_5_around_center():
    box = b(300, 100, 500, 900)
    _, a0, _, a1 = patient_band_fractions(box)
    _, c0, _, c1 = patient_band_fractions(box, enlarge=ENLARGE_RETRY)
    assert (c1 - c0) == pytest.approx((a1 - a0) * 1.5)
    assert (c0 + c1) / 2 == pytest.approx((a0 + a1) / 2)


def test_enlarge_is_clamped_to_page():
    _, c0, _, c1 = patient_band_fractions(b(50, 100, 900, 900), enlarge=1.5)
    assert c0 >= 0.0 and c1 <= 1.0


def test_region_fractions_dispatch_patient_band_vs_barcode_box():
    box = b(100, 600, 250, 700)
    assert region_fractions("patient", box)[0] == PATIENT_SIDE_MARGIN
    x0, y0, x1, y1 = region_fractions("barcode", box)
    assert 0.6 - x0 >= BARCODE_MIN_PAD - 1e-9 and x1 - 0.7 >= BARCODE_MIN_PAD - 1e-9
    assert 0.1 - y0 >= BARCODE_MIN_PAD - 1e-9 and y1 - 0.25 >= BARCODE_MIN_PAD - 1e-9


def test_barcode_min_padding_for_tiny_box():
    x0, y0, x1, y1 = region_fractions("barcode", b(500, 500, 520, 520))
    assert (0.5 - x0) >= BARCODE_MIN_PAD - 1e-9 and (y1 - 0.52) >= BARCODE_MIN_PAD - 1e-9


# ---------- labels_seen ----------

def regions(labels, region_ok=True):
    r = RegionsExtraction.model_validate({"patient": {"region_ok": region_ok, "labels_seen": labels}, "barcode": {"region_ok": True}})
    return {"ok": True, "model": "m", **r.model_dump()}


def test_schema_and_prompt_include_labels_seen():
    assert "labels_seen" in RegionsExtraction.model_json_schema()["$defs"]["PatientRead"]["properties"]
    assert "labels_seen" in extractor.PROMPT_REGIONS


@pytest.mark.parametrize("labels,missing", [
    (["first_name", "last_name", "id_number"], False),
    (["first_name", "last_name", "id_number", "father_name"], False),
    (["last_name", "id_number"], True),
    (["first_name", "id_number"], True),
    ([], True),
])
def test_patient_labels_missing(labels, missing):
    assert patient_labels_missing(regions(labels)) is missing


def test_labels_check_ignores_failed_or_absent_pass_two():
    assert patient_labels_missing(None) is False
    assert patient_labels_missing({"ok": False}) is False


def with_values(labels, first=None, last=None, id_=None):
    f = lambda v, label=None: {"value": v, "confidence": 0.9, "source": "printed", "label": label}
    r = RegionsExtraction.model_validate({"patient": {"region_ok": True, "labels_seen": labels, "first_name": f(first, "שם פרטי"),
                                                      "last_name": f(last, "שם משפחה"), "id_number": f(id_)}, "barcode": {"region_ok": True}})
    return {"ok": True, "model": "m", **r.model_dump()}


def test_field_validity_follows_labels_seen():
    r = apply_field_validity(with_values(["id_number"]))
    assert r["patient"]["field_ok"] == {"first_name": False, "last_name": False, "id_number": True}
    assert region_state(r, "patient", "id_number") == "ok"
    assert region_state(r, "patient", "first_name") == "not_ok"
    assert region_state(r, "patient") == "ok"                     # החיתוך עצמו תקין


def test_id_is_valid_when_only_id_label_was_seen_even_if_name_labels_missing():
    """עמוד 5: ת"ז נקראה נכון והושלכה כי לא נראו תוויות שמות."""
    r = apply_field_validity(with_values(["id_number"], id_="01122334"))
    d = decide_id([], r)
    assert d.value == "01122334" and F_REGION_NOT_OK not in d.flags


def test_name_valid_only_if_its_own_label_was_seen():
    r = apply_field_validity(with_values(["last_name", "id_number"], first="דנה", last="לוי"))
    first = decide_name(Field_(), r, "first_name")
    last = decide_name(Field_(), r, "last_name")
    assert first.value is None and F_REGION_NOT_OK in first.flags     # התווית של שם פרטי לא נראתה: לא נכנס
    assert F_REGION_NOT_OK not in last.flags and last.value == "לוי"


def test_id_invalid_when_id_label_not_seen():
    r = apply_field_validity(with_values(["first_name", "last_name"], id_="30530668"))
    d = decide_id([], r)
    assert d.value is None and F_REGION_NOT_OK in d.flags


def test_no_labels_at_all_keeps_names_valid_and_invalidates_the_id():
    """שונה ב-20.10.2026: חיתוך תקין בלי אף תווית (שם בכתב יד על קו, צילום מסך) אינו פוסל שם — אין תווית
    לראות, ולכן אין על מה לפסול. הקריאה נכנסת וממשיכה להיות כתומה או צהובה לפי decide_name, לעולם לא ירוקה.
    ת"ז לא נכללה בחריג."""
    r = apply_field_validity(with_values([], first="דנה", last="לוי", id_="30530668"))
    assert region_state(r, "patient", "first_name") == "ok"
    assert region_state(r, "patient", "last_name") == "ok"
    assert region_state(r, "patient", "id_number") == "not_ok"
    assert decide_id([], r).value is None                      # ת"ז בלי תווית: עדיין לא נכנסת


def test_without_field_ok_key_legacy_results_stay_valid():
    assert region_state(with_values([]), "patient", "id_number") == "ok"


# ---------- ניסיון חוזר אחד ----------

@pytest.fixture
def io_mocks(monkeypatch):
    rendered = []
    monkeypatch.setattr(pipeline, "pdf_to_images", lambda path, pages: [b"jpeg"])
    monkeypatch.setattr(pipeline, "render_region", lambda path, page, fr, **k: rendered.append(fr) or repr(fr).encode())
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: ({**r1([num("11223344", "ת.ז.", "handwritten")]),
                                                                    "patient_box": {"ymin": 300, "xmin": 600, "ymax": 450, "xmax": 900}}, False))
    return rendered


def test_missing_label_triggers_exactly_one_retry_with_enlarged_band(monkeypatch, io_mocks):
    seq = [(regions(["last_name"]), False), (regions(["first_name", "last_name"]), False)]
    calls = []
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: calls.append(crops) or seq.pop(0))
    res = process_page("x.pdf", 1)
    assert len(calls) == 2 and res["second_pass"] == "run"
    assert res["pass2"]["patient"]["region_ok"] is True
    first_band, retry_band = io_mocks[0], io_mocks[2]          # patient (1), barcode (2), patient retry (3)
    assert (retry_band[3] - retry_band[1]) == pytest.approx((first_band[3] - first_band[1]) * 1.5)


def test_label_still_missing_after_retry_rejects_region_and_does_not_call_again(monkeypatch, io_mocks):
    calls = []
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: calls.append(1) or (regions(["id_number"]), False))
    res = process_page("x.pdf", 1)
    assert len(calls) == 2                                      # ניסיון חוזר אחד בלבד
    assert res["pass2"]["patient"]["field_ok"] == {"first_name": False, "last_name": False, "id_number": True}


def test_all_labels_present_no_retry(monkeypatch, io_mocks):
    calls = []
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: calls.append(1) or (regions(["first_name", "last_name"]), False))
    process_page("x.pdf", 1)
    assert len(calls) == 1


def test_failed_second_pass_is_not_retried(monkeypatch, io_mocks):
    calls = []
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: calls.append(1) or ({"ok": False, "error": "503", "stats": {}}, False))
    assert process_page("x.pdf", 1)["second_pass"] == "failed" and len(calls) == 1


def test_retry_stats_are_summed(monkeypatch, io_mocks):
    seq = [({**regions([]), "stats": {"api_calls": 1}}, False), ({**regions(["first_name", "last_name"]), "stats": {"api_calls": 1}}, False)]
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: seq.pop(0))
    assert process_page("x.pdf", 1)["stats"]["pass2"] == {"api_calls": 2}
