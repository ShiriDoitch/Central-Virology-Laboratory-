"""שלב 2: אזור הקבלה (receipt_box + חיתוך), חלון תאריכים, מעבר שני במודל חזק עם גיבוי, והאזהרה במסך."""
import io
import json
from datetime import date

import pytest
from PIL import Image

from src import cache, extractor, pipeline
from src.crop import (edges_touching_ink, expand_receipt_fractions, receipt_region_fractions)
from src.export import pass2_issues
from src.rules import (F_CONFLICT, F_DATE_OUTSIDE_WINDOW, F_DATE_SINGLE_SOURCE, F_HANDWRITTEN, F_RECEIPT_BEFORE_SAMPLE,
                       H_TWO_READS, date_window, decide_center, decide_receipt_date)
from src.schema import Box, DateCandidate, NumberCandidate, PageExtraction, RegionsExtraction
from tests.test_retries import BUSY, FakeClient, MINUTE_429

TODAY = date(2026, 10, 16)


def dt(value, kind, source="printed", evidence=None, conf=0.95):
    return DateCandidate(value=value, kind=kind, source=source, evidence=evidence, confidence=conf)


def receipt_regions(value, alternatives=(), source="handwritten", central=None, region_ok=True):
    """תוצאת מעבר 2 עם חיתוך קבלה בלבד (שאר החיתוכים ברירת מחדל)."""
    r = RegionsExtraction.model_validate({"receipt": {
        "region_ok": region_ok,
        "date": {"value": value, "source": source, "confidence": 0.9, "alternatives": list(alternatives)},
        "central_number": {"value": central, "source": "handwritten", "confidence": 0.9} if central else {}}})
    return {"ok": True, "model": "m", **r.model_dump()}


# עמוד 19: דגימה 12.08, שליחה 13.08, התקבל 13.08 (כתב יד), הודפס 16.08
PAGE19 = [dt("12.08.2026", "sample_date"), dt("13.08.2026", "shipping_date"),
          dt("13.8.26", "handwritten_date", "handwritten", "handwriting"), dt("16.08.2026", "print_date")]


# ---------- חלון תאריכים ----------

def test_page_19_window_sample_ship_received_printed_is_inside():
    lo, hi = date_window(PAGE19, TODAY)
    assert lo == date(2026, 8, 12) and hi == date(2026, 8, 27)       # שליחה 13.08 + 14 יום; תאריך ההדפסה לא משפיע
    d = decide_receipt_date(PAGE19, TODAY)
    assert d.value == "13.08.2026" and F_DATE_OUTSIDE_WINDOW not in d.flags and F_RECEIPT_BEFORE_SAMPLE not in d.flags


def test_print_date_is_never_the_lower_bound():
    dates = [dt("12.08.2026", "sample_date"), dt("16.08.2026", "print_date"), dt("13.08.2026", "lab_stamp", evidence="stamp")]
    d = decide_receipt_date(dates, TODAY)
    assert d.value == "13.08.2026" and d.flags == []               # קבלה לפני ההדפסה: תקין (טופס שנשלח שוב בפקס)


def test_receipt_after_upper_bound_is_orange_value_untouched():
    dates = [dt("12.08.2026", "sample_date"), dt("30.08.2026", "lab_stamp", evidence="stamp")]    # 18 יום אחרי הדגימה
    d = decide_receipt_date(dates, TODAY)
    assert d.value == "30.08.2026" and d.flags == [F_DATE_OUTSIDE_WINDOW]


def test_receipt_before_sample_is_outside_window():
    dates = [dt("12.08.2026", "sample_date"), dt("10.08.2026", "lab_stamp", evidence="stamp")]
    d = decide_receipt_date(dates, TODAY)
    assert d.value == "10.08.2026" and F_DATE_OUTSIDE_WINDOW in d.flags and F_RECEIPT_BEFORE_SAMPLE in d.flags


def test_future_date_is_outside_window():
    dates = [dt("12.08.2026", "sample_date"), dt("25.08.2026", "lab_stamp", evidence="stamp")]
    d = decide_receipt_date(dates, date(2026, 8, 20))              # "היום" 20.08: 25.08 בעתיד
    assert d.value == "25.08.2026" and d.flags == [F_DATE_OUTSIDE_WINDOW]


def test_expiry_date_caps_the_window():
    dates = [dt("12.08.2026", "sample_date"), dt("20.08.2026", "expiry_date"), dt("22.08.2026", "lab_stamp", evidence="stamp")]
    assert date_window(dates, TODAY)[1] == date(2026, 8, 20)
    assert decide_receipt_date(dates, TODAY).flags == [F_DATE_OUTSIDE_WINDOW]


def test_shipping_date_extends_the_upper_bound_from_the_shipping_day():
    dates = [dt("01.08.2026", "sample_date"), dt("10.08.2026", "shipping_date"), dt("20.08.2026", "lab_stamp", evidence="stamp")]
    assert date_window(dates, TODAY)[1] == date(2026, 8, 24)       # 10.08 + 14, לא 01.08 + 14
    assert decide_receipt_date(dates, TODAY).flags == []


def test_no_sample_date_means_no_window():
    dates = [dt("16.08.2026", "print_date"), dt("30.01.2026", "lab_stamp", evidence="stamp")]
    assert date_window(dates, TODAY) is None
    assert F_DATE_OUTSIDE_WINDOW not in decide_receipt_date(dates, TODAY).flags


def test_two_different_sample_dates_skip_the_window():
    dates = [dt("12.08.2026", "sample_date"), dt("13.08.2026", "sample_date"), dt("01.01.2026", "lab_stamp", evidence="stamp")]
    assert date_window(dates, TODAY) is None


# ---------- קריאה שנייה מחיתוך הקבלה, וכלל הירוק ----------

def test_green_needs_two_readings_agree_and_inside_window_even_handwritten():
    d = decide_receipt_date(PAGE19, TODAY, regions=receipt_regions("13.8.26"), require_two_readings=True)
    assert d.value == "13.08.2026" and d.flags == [] and H_TWO_READS in d.hints          # ירוק, למרות כתב יד


def test_single_reading_is_orange():
    d = decide_receipt_date(PAGE19, TODAY, regions=None, require_two_readings=True)
    assert d.value == "13.08.2026" and F_DATE_SINGLE_SOURCE in d.flags and F_HANDWRITTEN in d.flags
    printed = [dt("13.08.2026", "lab_stamp", evidence="stamp")]
    assert decide_receipt_date(printed, TODAY).flags == []                                # בלי הדרישה: כמו קודם
    assert decide_receipt_date(printed, TODAY, require_two_readings=True).flags == []     # הדפסה ברורה (printed, ביטחון 0.95): בלי דגל
    weak = [dt("13.08.2026", "lab_stamp", evidence="stamp", conf=0.90)]
    assert decide_receipt_date(weak, TODAY, require_two_readings=True).flags == [F_DATE_SINGLE_SOURCE]       # ביטחון נמוך: נשאר
    for conf in (0.80, 0.99):                                                                                # כתב יד: נשאר, בכל ביטחון
        hand = [dt("13.08.2026", "handwritten_date", source="handwritten", conf=conf)]
        assert F_DATE_SINGLE_SOURCE in decide_receipt_date(hand, TODAY, require_two_readings=True).flags


def test_two_readings_agree_but_outside_window_is_orange():
    dates = [dt("12.08.2026", "sample_date"), dt("30.08.2026", "lab_stamp", evidence="stamp")]
    d = decide_receipt_date(dates, TODAY, regions=receipt_regions("30.8.26", source="printed"), require_two_readings=True)
    assert d.value == "30.08.2026" and d.flags == [F_DATE_OUTSIDE_WINDOW]


def test_two_readings_agree_without_sample_date_skips_window_green():
    dates = [dt("13.08.2026", "handwritten_date", "handwritten", "handwriting")]
    d = decide_receipt_date(dates, TODAY, regions=receipt_regions("13.08.2026"), require_two_readings=True)
    assert d.flags == []


def test_two_readings_disagree_is_conflict_with_inside_window_first():
    dates = [dt("12.08.2026", "sample_date"), dt("19.08.2026", "handwritten_date", "handwritten", "handwriting")]
    regions = receipt_regions("10.08.2026", alternatives=["13.08.2026"])
    d = decide_receipt_date(dates, TODAY, regions=regions, require_two_readings=True)
    assert d.value is None and F_CONFLICT in d.flags
    assert d.alternatives == ["19.08.2026", "13.08.2026", "10.08.2026"]      # הפנימיים בחלון קודם (19.08, 13.08); 10.08 לפני הדגימה


def test_window_only_reorders_suggestions_value_never_changes():
    dates = [dt("12.08.2026", "sample_date"), dt("10.08.2026", "handwritten_date", "handwritten", "handwriting")]
    regions = receipt_regions("10.08.2026", alternatives=["10.08.2025", "13.08.2026"])
    d = decide_receipt_date(dates, TODAY, regions=regions, require_two_readings=True)
    assert d.value == "10.08.2026" and F_DATE_OUTSIDE_WINDOW in d.flags            # נשאר, מחוץ לחלון, כתום
    assert d.alternatives == ["13.08.2026", "10.08.2025"]                          # ההצעה שבתוך החלון קודם


def test_no_date_on_page_one_but_crop_read_one_is_single_source_orange():
    d = decide_receipt_date([], TODAY, regions=receipt_regions("13.8.26"), require_two_readings=True)
    assert d.value == "13.08.2026" and F_DATE_SINGLE_SOURCE in d.flags and F_HANDWRITTEN in d.flags


def test_crop_with_region_not_ok_is_ignored():
    d = decide_receipt_date(PAGE19, TODAY, regions=receipt_regions("01.01.2026", region_ok=False), require_two_readings=True)
    assert d.value == "13.08.2026" and F_DATE_SINGLE_SOURCE in d.flags and H_TWO_READS not in d.hints


# ---------- מרכזי: חיתוך הקבלה כקריאה שנייה ----------

def full_regions(receipt_central=None, barcode_ok=True):
    r = RegionsExtraction.model_validate({"barcode": {"region_ok": barcode_ok},
                                          "receipt": {"region_ok": True,
                                                      "central_number": {"value": receipt_central, "source": "handwritten",
                                                                         "confidence": 0.9} if receipt_central else {}}})
    return {"ok": True, "model": "m", **r.model_dump()}


def test_receipt_crop_central_agrees_with_page_reading():
    numbers = [NumberCandidate(value="946019", label="מרכזי", source="printed", confidence=0.95)]
    d = decide_center(numbers, full_regions("946019"))
    assert d.value == "946019" and d.flags == []


def test_receipt_crop_central_disagreeing_with_page_reading_is_orange():
    numbers = [NumberCandidate(value="946019", label="מרכזי", source="printed", confidence=0.95)]
    d = decide_center(numbers, full_regions("947000"))
    assert "center_mismatch" in d.flags and set(d.alternatives) == {"946019", "947000"}


def test_receipt_crop_alone_gives_handwritten_orange_central():
    d = decide_center([], full_regions("946019"))
    assert d.value == "946019" and F_HANDWRITTEN in d.flags


def test_receipt_crop_central_counts_even_when_barcode_region_is_not_ok():
    d = decide_center([], full_regions("946019", barcode_ok=False))
    assert d.value == "946019" and "region_not_ok" in d.flags                   # חיתוך הברקוד נפסל: הדגל נשאר


# ---------- גיאומטריית החיתוך ----------

def test_receipt_crop_has_generous_margins_and_extra_at_bottom():
    x0, y0, x1, y1 = receipt_region_fractions(Box(ymin=400, xmin=100, ymax=500, xmax=300))
    assert (x0, x1) == pytest.approx((0.04, 0.36))                 # 30% מרוחב ה-box (0.2) = 0.06 מכל צד
    assert y0 == pytest.approx(0.37)                               # 30% מגובה ה-box (0.1) = 0.03 למעלה
    assert y1 == pytest.approx(0.59)                               # 0.03 + עוד 60% מהגובה (0.06) למטה
    assert (y1 - 0.5) > (0.4 - y0)                                 # למטה יותר מלמעלה


def test_receipt_crop_at_page_edge_is_shifted_not_clipped():
    x0, y0, x1, y1 = receipt_region_fractions(Box(ymin=900, xmin=0, ymax=1000, xmax=200))
    assert x0 == 0 and y1 == 1.0
    assert (x1 - x0) == pytest.approx(0.32) and (y1 - y0) == pytest.approx(0.22)   # הגודל נשמר (לא קוצץ)


def _jpeg(ink_bottom=False, ink_left=False):
    im = Image.new("L", (400, 200), 255)
    px = im.load()
    for x in range(400):
        for y in range(200):
            if (ink_bottom and y >= 195) or (ink_left and x < 5):
                px[x, y] = 0
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_edges_touching_ink_detects_clipped_writing():
    assert edges_touching_ink(_jpeg()) == set()
    assert edges_touching_ink(_jpeg(ink_bottom=True)) == {"bottom"}
    assert edges_touching_ink(_jpeg(ink_left=True)) == {"left"}
    assert edges_touching_ink(b"not an image") == set()


def test_expand_receipt_fractions_expands_only_touched_sides_up_to_page():
    out = expand_receipt_fractions((0.2, 0.3, 0.6, 0.5), {"bottom", "left"})
    assert out == pytest.approx((0.04, 0.3, 0.6, 0.58))
    assert expand_receipt_fractions((0.0, 0.3, 0.6, 0.98), {"left", "bottom"}) == pytest.approx((0.0, 0.3, 0.6, 1.0))


# ---------- סכמה, פרומפט ובקשה ----------

def test_schema_and_prompts_have_receipt_box_and_receipt_crop():
    assert "receipt_box" in PageExtraction.model_json_schema()["properties"]
    assert "receipt" in RegionsExtraction.model_json_schema()["properties"]
    assert "receipt_box" in extractor.PROMPT and "התקבל" in extractor.PROMPT
    assert "shipping_date" in extractor.PROMPT
    assert ("This is a received stamp or a handwritten receipt date, format day-month-year. Read digit by digit. "
            "If a digit is unclear, give the alternatives.") in extractor.PROMPT_REGIONS
    assert "central number" in extractor.PROMPT_REGIONS


def test_fourth_image_keeps_its_slot_number_when_commitment_is_missing(monkeypatch):
    seen = []

    class Models:
        def generate_content(self, model, contents, config):
            seen.append([c for c in contents if isinstance(c, str) and c.startswith("Image")])
            return type("R", (), {"text": RegionsExtraction().model_dump_json()})()

    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: type("C", (), {"models": Models()})())
    extractor.extract_regions({"patient": b"a", "barcode": b"b", "receipt": b"r"})
    assert seen == [["Image 1:", "Image 2:", "Image 4:"]]


def test_cache_key_depends_on_receipt_crop():
    base = {"patient": b"a", "barcode": b"b"}
    assert cache.regions_cache_key(base) != cache.regions_cache_key({**base, "receipt": b"r"})
    assert cache.regions_cache_key({**base, "receipt": b"r"}) != cache.regions_cache_key({**base, "receipt": b"s"})


# ---------- מודל מעבר 2 וגיבוי ----------

OK = RegionsExtraction().model_dump_json()


@pytest.fixture
def two_models(monkeypatch):
    cfg = {"first_pass": "lite", "first_pass_fallbacks": [], "second_pass": "big", "second_pass_fallback": "lite",
           "escalate_to_strong": False, "strong_models": ["big"]}
    monkeypatch.setattr(extractor, "load_models_config", lambda: dict(cfg))
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")


def _client(monkeypatch, outcomes):
    client = FakeClient(outcomes)
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    return client


def test_shipped_config_pass2_is_36_with_flash_lite_fallback_pass1_unchanged():
    cfg = json.loads(extractor.MODELS_CONFIG_PATH.read_text(encoding="utf-8"))
    assert cfg["first_pass"] == "gemini-3.5-flash-lite"
    assert extractor.model_chain() == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]       # מעבר 1 לא השתנה
    assert extractor.region_model_chain() == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    assert "gemini-3.6-flash" in extractor.strong_model_list()                                 # דרגת מכסה חזקה (20 ליום)


def test_pass2_uses_strong_model_and_records_it(monkeypatch, two_models):
    client = _client(monkeypatch, {"big": [OK]})
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] and result["model"] == "big" and result["fallback"] is False and client.models.calls == ["big"]


def test_pass2_falls_back_to_flash_lite_on_503(monkeypatch, two_models):
    client = _client(monkeypatch, {"big": [BUSY()], "lite": [OK]})
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] and result["model"] == "lite" and result["fallback"] is True
    assert result["fallback_from"] == {"big": "503"} and client.models.calls == ["big", "lite"]


def test_pass2_falls_back_when_strong_model_is_out_of_daily_quota(monkeypatch, two_models, quota_tracker):
    quota_tracker.mark_exhausted("big")
    client = _client(monkeypatch, {"lite": [OK]})
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] and result["model"] == "lite" and result["fallback"] is True
    assert client.models.calls == ["lite"]                           # המודל החזק לא נקרא כלל


def test_pass2_falls_back_on_minute_429_and_on_broken_json(monkeypatch, two_models):
    client = _client(monkeypatch, {"big": [MINUTE_429(), "{bad"], "lite": [OK, OK]})
    assert extractor.extract_regions({"patient": b"a", "barcode": b"b"})["model"] == "lite"
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})            # JSON שבור במודל החזק
    assert result["ok"] and result["model"] == "lite" and result["fallback"] is True
    assert client.models.calls == ["big", "lite", "big", "lite"]


def test_pass2_both_models_out_of_quota_reports_daily_quota(monkeypatch, two_models, quota_tracker):
    quota_tracker.mark_exhausted("big")
    quota_tracker.mark_exhausted("lite")
    client = _client(monkeypatch, {})
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is False and result["error"].startswith("מכסה יומית נגמרה")
    assert client.models.calls == [] and result["daily_quota_exhausted"] == ["big", "lite"]


def test_pass2_calls_at_most_two_models_one_call_each(monkeypatch, two_models):
    client = _client(monkeypatch, {"big": [BUSY()], "lite": [BUSY()]})
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is False and client.models.calls == ["big", "lite"]


def test_fallback_answer_is_not_cached_but_strong_answer_is(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    crops = {"patient": b"a", "barcode": b"b"}
    assert cache.cached_regions(crops, lambda c: {"ok": True, "model": "lite", "fallback": True})[1] is False
    assert cache.cached_regions(crops, lambda c: {"ok": True, "model": "big", "fallback": False})[1] is False   # לא היה במטמון
    assert cache.cached_regions(crops, lambda c: pytest.fail("must come from cache"))[1] is True


# ---------- צינור: חיתוך קבלה, מודל לעמוד, אזהרות ----------

@pytest.fixture
def fake_io(monkeypatch):
    monkeypatch.setattr(pipeline, "pdf_to_images", lambda path, pages: [b"jpeg"])
    monkeypatch.setattr(pipeline, "render_region", lambda *a, **k: b"crop")


def _r1(**extra):
    p = PageExtraction(is_commitment_form=True, page_quality="ok", **extra)
    return {"ok": True, "model": "m", "stats": {"api_calls": 1}, **p.model_dump()}


def test_receipt_box_makes_second_pass_run_and_adds_receipt_crop(monkeypatch, fake_io):
    p = PageExtraction(is_commitment_form=True, page_quality="ok",
                       id_numbers=[NumberCandidate(value="11223344", label="ת.ז.", confidence=1.0)],
                       numbers=[NumberCandidate(value="939376", label="מרכזי", confidence=1.0)],
                       receipt_box=Box(ymin=100, xmin=600, ymax=200, xmax=900))
    assert pipeline.needs_second_pass(p) == (True, ["date:unverified"])
    r1 = {"ok": True, "model": "m", "stats": {}, **p.model_dump()}
    seen = {}
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1, False))
    monkeypatch.setattr(pipeline, "cached_regions",
                        lambda crops: (seen.update(crops=sorted(crops)) or {"ok": True, "model": "big", "fallback": False,
                                                                           "stats": {"api_calls": 1}}, False))
    res = pipeline.process_page("x.pdf", 1)
    assert "receipt" in seen["crops"] and res["boxes"]["receipt"]["raw"] == r1["receipt_box"]
    assert res["pass2_model"] == "big" and res["pass2_fallback"] is False


def test_no_receipt_box_no_receipt_reason():
    p = PageExtraction(is_commitment_form=True, page_quality="ok",
                       id_numbers=[NumberCandidate(value="11223344", label="ת.ז.", confidence=1.0)],
                       numbers=[NumberCandidate(value="939376", label="מרכזי", confidence=1.0)])
    assert pipeline.needs_second_pass(p) == (False, [])


def test_pipeline_records_fallback_model_per_page(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract",
                        lambda images: (_r1(id_numbers=[NumberCandidate(value="11223344", label="ת.ז.", source="handwritten")]), False))
    monkeypatch.setattr(pipeline, "cached_regions",
                        lambda crops: ({"ok": True, "model": "lite", "fallback": True, "stats": {}}, False))
    res = pipeline.process_page("x.pdf", 1)
    assert res["pass2_model"] == "lite" and res["pass2_fallback"] is True


def test_retry_patient_labels_can_be_disabled(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract",
                        lambda images: (_r1(id_numbers=[NumberCandidate(value="11223344", label="ת.ז.", source="handwritten")]), False))
    calls = []
    monkeypatch.setattr(pipeline, "cached_regions",
                        lambda crops: (calls.append(1) or {"ok": True, "model": "big", "stats": {},
                                                           "patient": {"region_ok": True, "labels_seen": []}}, False))
    pipeline.process_page("x.pdf", 1)                                  # חסרות תוויות שם: ניסיון חוזר
    assert len(calls) == 2
    calls.clear()
    pipeline.process_page("x.pdf", 1, retry_patient_labels=False)
    assert len(calls) == 1


def test_pass2_issues_lists_fallback_quota_and_failed_pages():
    pages = [{"page": 1, "second_pass": "run", "pass2_fallback": False},
             {"page": 2, "second_pass": "run", "pass2_fallback": True},
             {"page": 3, "second_pass": "daily_quota_exhausted"},
             {"page": 4, "second_pass": "failed"},
             {"page": 5, "second_pass": "skipped"}]
    assert pass2_issues(pages) == {"fallback": [2], "claude": [], "claude_pass1": [], "quota": [3], "failed": [4]}


def test_app_shows_pass2_warning_and_receipt_crop_for_date():
    """המסך מציג אזהרה לעמודים שנקראו אחרת, בנוסח של src/ui_text.py (בלי שמות מודלים; ראו tests/test_ui_polish.py)."""
    from src import ui_text
    src = open("app.py", encoding="utf-8").read()
    assert "pass2_issues(pages)" in src and "ui_text.read_notices(issues)" in src and "st.warning" in src
    assert ui_text.read_notices({"fallback": [2]}) == ["עמוד 2 נקרא בשיטה פחות מדויקת, מומלץ לבדוק אותו ידנית"]
    from src.confirm import FIELD_REGION
    assert FIELD_REGION["date"] == "receipt"


# ---------- תקרת הקריאות של סקריפט המדידה (בלי API) ----------

def test_budget_tracker_stops_at_the_limit_and_skips_unlisted_models():
    from run_step2_dates import BudgetReached, BudgetTracker
    from src.quota import DailyQuotaExhausted

    class Inner:
        calls: list[str] = []

        def before_call(self, model):
            self.calls.append(model)

    inner = Inner()
    t = BudgetTracker(inner, {"big": 2, "lite": 1})
    t.before_call("big")
    t.before_call("big")
    with pytest.raises(BudgetReached):
        t.before_call("big")                                       # השלישית נחסמת לפני שנשלחה
    t.before_call("lite")
    with pytest.raises(DailyQuotaExhausted):
        t.before_call("gemini-3.1-flash-lite")                     # מודל שלא בתקציב: מדולג בלי בקשה
    assert inner.calls == ["big", "big", "lite"] and dict(t.count) == {"big": 2, "lite": 1}
    assert not issubclass(BudgetReached, Exception)                # BaseException: לא נבלע בשום מקום בצינור


def test_budget_tracker_stops_immediately_when_strong_model_returns_404():
    from run_step2_dates import BudgetTracker, StrongModelNotFound

    class Inner:
        marked: list[str] = []

        def mark_unavailable(self, model):
            self.marked.append(model)

    inner = Inner()
    t = BudgetTracker(inner, {"gemini-3.8-flash": 12})
    t.mark_unavailable("gemini-3.5-flash-lite")                    # 404 של מודל אחר: לא עוצר
    with pytest.raises(StrongModelNotFound):
        t.mark_unavailable("gemini-3.8-flash")
    assert inner.marked == ["gemini-3.5-flash-lite", "gemini-3.8-flash"] and not issubclass(StrongModelNotFound, Exception)
