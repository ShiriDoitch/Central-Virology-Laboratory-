import httpx
import pytest
from google.genai import errors

from src import extractor, pipeline
from src.pipeline import needs_second_pass, process_page, sum_stats
from src.schema import NumberCandidate, PageExtraction


def num(value, label=None, source="printed", conf=1.0):
    return NumberCandidate(value=value, label=label, source=source, confidence=conf)


def page(ids=(), numbers=()):
    return PageExtraction(is_commitment_form=True, page_quality="ok", id_numbers=list(ids), numbers=list(numbers))


# ---------- מעבר שני רק כשצריך ----------

def test_skip_when_id_and_center_are_clear():
    p = page(ids=[num("11223344", "ת.ז.")], numbers=[num("939376", "מרכזי")])
    assert needs_second_pass(p) == (False, [])


def test_needed_when_id_handwritten():
    p = page(ids=[num("11223344", "ת.ז.", source="handwritten")], numbers=[num("939376", "מרכזי")])
    needed, reasons = needs_second_pass(p)
    assert needed and reasons == ["id:handwritten"]


def test_needed_when_center_has_no_label():
    p = page(ids=[num("11223344", "ת.ז.")], numbers=[num("939376")])     # רק מספר יחיד בן 6 ספרות: כתום
    needed, reasons = needs_second_pass(p)
    assert needed and reasons == ["center:no_center_label"]


def test_needed_when_missing_or_conflicting():
    needed, reasons = needs_second_pass(page())
    assert needed and reasons == ["id:missing", "center:missing"]
    p = page(ids=[num("00112233", "ת.ז."), num("11223344", "ת.ז.")], numbers=[num("939376", "מרכזי")])
    assert needs_second_pass(p) == (True, ["id:conflict"])       # סתירה: ערך ריק, אבל לא "חסר"


def test_sum_stats():
    assert sum_stats({"api_calls": 2, "quota_failures": 1}, None, {"api_calls": 1}) == {"api_calls": 3, "quota_failures": 1}


# ---------- process_page עם mocks ----------

@pytest.fixture
def fake_io(monkeypatch):
    calls = {"regions": 0}
    monkeypatch.setattr(pipeline, "pdf_to_images", lambda path, pages: [b"jpeg"])
    monkeypatch.setattr(pipeline, "render_region", lambda *a, **k: b"crop")
    return calls


def r1(ids=(), numbers=(), stats=None):
    p = page(ids=ids, numbers=numbers)
    return {"ok": True, "model": "m", "stats": stats or {"api_calls": 1}, **p.model_dump()}


def test_process_page_skips_second_pass(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract",
                        lambda images: (r1([num("11223344", "ת.ז.")], [num("939376", "מרכזי")]), False))
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: pytest.fail("pass 2 must be skipped"))
    res = process_page("x.pdf", 1)
    assert res["second_pass"] == "skipped" and res["pass2"] is None
    assert res["stats"] == {"pass1": {"api_calls": 1}, "pass2": {}}


def test_process_page_runs_second_pass_and_counts_calls(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1([num("11223344", "ת.ז.", "handwritten")]), False))
    monkeypatch.setattr(pipeline, "cached_regions",
                        lambda crops: ({"ok": True, "model": "strong", "stats": {"api_calls": 3, "quota_failures": 2}}, False))
    res = process_page("x.pdf", 1)
    assert res["second_pass"] == "run" and res["pass2"]["model"] == "strong"
    assert res["reasons"] == ["id:handwritten", "center:missing"]
    assert sum_stats(*res["stats"].values()) == {"api_calls": 4, "quota_failures": 2}


def test_process_page_cache_hits_cost_zero_calls(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1(stats={"api_calls": 5}), True))
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: ({"ok": True, "stats": {"api_calls": 7}}, True))
    res = process_page("x.pdf", 1)
    assert sum_stats(*res["stats"].values()) == {}


def test_process_page_force_runs_even_if_clear(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract",
                        lambda images: (r1([num("11223344", "ת.ז.")], [num("939376", "מרכזי")]), False))
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: ({"ok": True, "stats": {}}, True))
    assert process_page("x.pdf", 1, force_second_pass=True)["second_pass"] == "run"


def test_process_page_reports_daily_quota_exhausted_and_failed(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1([num("11223344", "ת.ז.", "handwritten")]), False))
    monkeypatch.setattr(pipeline, "cached_regions",
                        lambda crops: ({"ok": False, "error": "מכסה יומית נגמרה: s1, s2", "stats": {}}, False))
    res = process_page("x.pdf", 1)
    assert res["second_pass"] == "daily_quota_exhausted" and res["stats"]["pass2"] == {}
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: ({"ok": False, "error": "503", "stats": {"api_calls": 1}}, False))
    assert process_page("x.pdf", 1)["second_pass"] == "failed"


def test_process_page_first_pass_failed(monkeypatch, fake_io):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: ({"ok": False, "stats": {"api_calls": 6}}, False))
    res = process_page("x.pdf", 1)
    assert res["second_pass"] == "not_possible"
    assert res["stats"]["pass1"] == {"api_calls": 6}


# ---------- ספירת קריאות ב-extractor ----------

class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def generate_content(self, **kwargs):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return type("R", (), {"text": outcome})()


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)


def test_call_model_counts_attempts_and_failure_types(monkeypatch):
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    stats = extractor.Counter()
    client = FakeClient([errors.ClientError(429, {"error": {"message": "quota"}}), "{}"])
    assert extractor._call_model(client, "m1", ["x"], PageExtraction, stats) == "{}"
    assert stats["api_calls"] == 2 and stats["quota_failures"] == 1 and stats["calls:m1"] == 2


def test_call_with_fallback_counts_all_models(monkeypatch):
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    stats = extractor.Counter()
    # כל מודל: ניסיון + 3 ניסיונות חוזרים (ATTEMPTS_PER_MODEL = 4) לפני המעבר למודל הבא
    outcomes = [errors.ServerError(503, {"error": {"message": "busy"}})] * 4 + [httpx.ReadTimeout("t")] * 4 + ["{}"]
    client = FakeClient(outcomes)
    tried, errs = [], {}
    text, model = extractor._call_with_fallback(client, ["x"], PageExtraction, tried, errs, ["a", "b", "c"], stats)
    assert (text, model) == ("{}", "c")
    assert stats["api_calls"] == 9 and stats["unavailable"] == 4 and stats["timeouts"] == 4
    assert errs == {"a": "503", "b": "ReadTimeout"}
    assert stats["503:a"] == 4 and stats["timeout:b"] == 4 and stats["ok:c"] == 1 and stats["calls:c"] == 1


def test_run_returns_stats_on_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    monkeypatch.setattr(extractor.genai, "Client",
                        lambda **k: FakeClient([errors.ServerError(503, {"error": {"message": "busy"}})] * 4))
    result = extractor._run(["x"], PageExtraction, ["only-model"])
    assert result["ok"] is False
    assert result["stats"]["api_calls"] == 4 and result["stats"]["unavailable"] == 4
