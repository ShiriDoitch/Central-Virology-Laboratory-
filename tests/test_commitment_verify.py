"""C(i): אימות מספר ההתחייבות בקריאה שנייה מחיתוך מוגדל."""
import pytest

from src import cache, extractor, pipeline
from src.assemble import page_rows
from src.crop import COMMITMENT_MIN_AREA, is_valid_box, region_fractions
from src.pipeline import needs_second_pass, process_page
from src.rules import (F_COMMITMENT_MISMATCH, F_COMMITMENT_SINGLE_SOURCE, F_WEAK_LABEL, Decision, verify_commitments)
from src.schema import Box, NumberCandidate, PageExtraction, RegionsExtraction
from tests.conftest import legacy_strong  # noqa: F401  (שימוש עתידי)
from tests.test_pipeline import num, r1
from tests.test_retries import FakeClient


def regions(number=None, region_ok=True, ok=True):
    r = RegionsExtraction.model_validate({"patient": {"region_ok": True, "labels_seen": ["first_name", "last_name", "id_number"]},
                                          "barcode": {"region_ok": True},
                                          "commitment": {"region_ok": region_ok,
                                                         "number": {"value": number, "confidence": 0.95, "source": "printed"}}})
    return {"ok": ok, "model": "m", **r.model_dump()}


def d(value, *flags):
    return Decision(value=value, raw=value, flags=list(flags))


# ---------- הכלל ----------

def test_agreement_on_digits_keeps_green():
    out = verify_commitments([d("251120160")], regions("251120160"))
    assert out[0].value == "251120160" and not out[0].flags


def test_difference_is_orange_empty_with_both_values_and_flag():
    out = verify_commitments([d("251120150")], regions("251120160"))
    assert out[0].value is None and F_COMMITMENT_MISMATCH in out[0].flags
    assert out[0].alternatives == ["251120150", "251120160"]


@pytest.mark.parametrize("r", [None, {"ok": False}, regions(None), regions("123456", region_ok=False)])
def test_second_pass_did_not_read_is_orange_single_source(r):
    out = verify_commitments([d("251120160")], r)
    assert out[0].value == "251120160" and F_COMMITMENT_SINGLE_SOURCE in out[0].flags


def test_weak_label_stays_orange_even_when_both_agree():
    out = verify_commitments([d("304497989", F_WEAK_LABEL)], regions("304497989"))
    assert F_WEAK_LABEL in out[0].flags and out[0].uncertain


def test_leading_zeros_are_part_of_the_digits():
    out = verify_commitments([d("00123456")], regions("123456"))
    assert F_COMMITMENT_MISMATCH in out[0].flags


def test_several_commitments_only_the_one_that_agrees_is_verified():
    out = verify_commitments([d("111111"), d("222222")], regions("222222"))
    assert not out[1].flags and F_COMMITMENT_SINGLE_SOURCE in out[0].flags


def test_no_commitment_rows_unchanged():
    assert verify_commitments([], regions("123456")) == []


def test_page_rows_applies_verification():
    p = PageExtraction(is_commitment_form=True, page_quality="ok",
                       numbers=[NumberCandidate(value="9974511", label="מספר התחייבות", confidence=1.0)])
    row = page_rows({"ok": True, "model": "x", **p.model_dump()}, regions=regions("9874511"))[0]
    assert row["commitment"] is None and row["commitment_alternatives"] == ["9974511", "9874511"]
    assert F_COMMITMENT_MISMATCH in row["commitment_flags"]


# ---------- סכמה, הוראה, בקשה, מטמון ----------

def test_schema_has_commitment_box_and_commitment_read():
    assert "commitment_box" in PageExtraction.model_json_schema()["properties"]
    assert "commitment" in RegionsExtraction.model_json_schema()["properties"]
    assert "commitment_box" in extractor.PROMPT and "Image 3" in extractor.PROMPT_REGIONS


def test_third_image_is_sent_in_the_same_request(monkeypatch):
    seen = []
    class Models:
        def generate_content(self, model, contents, config):
            seen.append(sum(1 for c in contents if not isinstance(c, str)))
            return type("R", (), {"text": RegionsExtraction().model_dump_json()})()
    client = type("C", (), {"models": Models()})()
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    extractor.extract_regions({"patient": b"a", "barcode": b"b", "commitment": b"c"})
    extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert seen == [3, 2]                          # בקשה אחת בכל מקרה


def test_cache_key_depends_on_commitment_crop():
    base = {"patient": b"a", "barcode": b"b"}
    assert cache.regions_cache_key(base) != cache.regions_cache_key({**base, "commitment": b"c"})
    assert cache.regions_cache_key({**base, "commitment": b"c"}) != cache.regions_cache_key({**base, "commitment": b"d"})


# ---------- חיתוך ----------

def test_small_commitment_box_is_valid_only_with_commitment_min_area():
    small = Box(ymin=500, xmin=100, ymax=510, xmax=200)         # שטח 0.1% מהעמוד: קטן
    assert not is_valid_box(small) and is_valid_box(small, COMMITMENT_MIN_AREA)


def test_commitment_crop_has_padding():
    x0, y0, x1, y1 = region_fractions("commitment", Box(ymin=500, xmin=400, ymax=520, xmax=480))
    assert 0.4 - x0 >= 0.02 - 1e-9 and 0.5 - y0 >= 0.02 - 1e-9 and x1 - 0.48 >= 0.02 - 1e-9


# ---------- צינור ----------

@pytest.fixture
def io(monkeypatch):
    rendered = []
    monkeypatch.setattr(pipeline, "pdf_to_images", lambda path, pages: [b"jpeg"])
    monkeypatch.setattr(pipeline, "render_region", lambda path, page, fr, **k: rendered.append(fr) or b"crop")
    return rendered


def page1(box):
    return {**r1([num("11223344", "ת.ז.")], [num("939376", "מרכזי"), num("730578626", "התחייבות מספר")]),
            "patient_box": {"ymin": 200, "xmin": 100, "ymax": 300, "xmax": 900}, "commitment_box": box}


def test_commitment_in_page_forces_second_pass_with_third_crop(monkeypatch, io):
    box = {"ymin": 600, "xmin": 100, "ymax": 640, "xmax": 400}
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (page1(box), False))
    got = []
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: got.append(set(crops)) or (regions("730578626"), False))
    res = process_page("x.pdf", 1)
    assert res["second_pass"] == "run" and "commitment:unverified" in res["reasons"]
    assert got == [{"patient", "barcode", "commitment"}] and "commitment" in res["boxes"]


def test_no_commitment_box_means_no_third_crop_and_no_forced_pass(monkeypatch, io):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (page1(None), False))
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: pytest.fail("pass 2 must be skipped"))
    res = process_page("x.pdf", 1)
    assert res["second_pass"] == "skipped"


def test_needs_second_pass_reason_only_with_box_and_number():
    p = PageExtraction(is_commitment_form=True, page_quality="ok",
                       id_numbers=[num("11223344", "ת.ז.")], numbers=[num("939376", "מרכזי"), num("730578626", "התחייבות מספר")])
    assert needs_second_pass(p) == (False, [])
    p2 = p.model_copy(update={"commitment_box": Box(ymin=600, xmin=100, ymax=640, xmax=400)})
    assert needs_second_pass(p2) == (True, ["commitment:unverified"])
