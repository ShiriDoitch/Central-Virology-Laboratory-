"""ניסיון חוזר אחד של המעבר הראשון כשנקבע "לא טופס התחייבות" אבל יש מספר עם תווית (6+ ספרות) או מספר בכתב יד."""
import pytest

from src import pipeline
from src.pipeline import pass1_needs_retry, process_page, sum_stats
from src.schema import NumberCandidate, PageExtraction


def num(value, label=None, source="printed"):
    return NumberCandidate(value=value, label=label, source=source, confidence=0.9)


def r1(is_form, numbers=(), ids=(), **extra):
    p = PageExtraction(is_commitment_form=is_form, page_quality="ok", numbers=list(numbers), id_numbers=list(ids))
    return {"ok": True, "model": "m", "stats": {"api_calls": 1}, **p.model_dump(), **extra}


LABELED6 = [num("990012538", "מידע כללי")]
HAND = [num("11223344", None, "handwritten")]


@pytest.mark.parametrize("res,expected", [
    (r1(False, LABELED6), True),                     # מספר עם תווית, 6+ ספרות
    (r1(False, HAND), True),                         # מספר בכתב יד
    (r1(False, ids=HAND), True),                     # ת"ז בכתב יד
    (r1(False, [num("12345", "מידע")]), False),      # פחות מ-6 ספרות
    (r1(False, [num("990012538")]), False),          # בלי תווית
    (r1(False), False),                              # אין מספרים
    (r1(True, LABELED6), False),                     # כבר טופס
    (r1(False, LABELED6, retried=True), False),      # כבר נוסה מחדש
    ({"ok": False}, False),
])
def test_pass1_needs_retry_conditions(res, expected):
    assert pass1_needs_retry(res) is expected


@pytest.fixture
def env(monkeypatch):
    stored = []
    monkeypatch.setattr(pipeline, "pdf_to_images", lambda path, pages: [b"jpeg"])
    monkeypatch.setattr(pipeline, "render_region", lambda *a, **k: b"crop")
    monkeypatch.setattr(pipeline, "store_result", lambda key, res: stored.append(res))
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: ({"ok": True, "stats": {}}, True))
    return stored


def test_retry_that_says_form_replaces_the_verdict_and_is_counted(monkeypatch, env):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1(False, LABELED6), True))     # מהמטמון
    calls = []
    monkeypatch.setattr(pipeline.extractor, "extract",
                        lambda images: calls.append(1) or r1(True, LABELED6, stats={"api_calls": 1}))
    res = process_page("x.pdf", 1)
    assert len(calls) == 1 and res["pass1"]["is_commitment_form"] is True and res["pass1"]["retried"] is True
    assert sum_stats(*res["stats"].values())["api_calls"] == 1                # נספר (המטמון עלה 0)
    assert env and env[0]["retried"] is True                                   # נשמר, כדי שלא ינסו שוב בהרצה הבאה


def test_retry_still_not_a_form_is_kept_marked_and_skipped_as_before(monkeypatch, env):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1(False, LABELED6), False))
    monkeypatch.setattr(pipeline.extractor, "extract", lambda images: r1(False, LABELED6, stats={"api_calls": 1}))
    res = process_page("x.pdf", 1)
    assert res["pass1"]["is_commitment_form"] is False and res["pass1"]["retried"] is True
    assert sum_stats(*res["stats"].values())["api_calls"] == 2               # מקורית + ניסיון חוזר


def test_failed_retry_keeps_original_and_does_not_store(monkeypatch, env):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1(False, LABELED6), True))
    monkeypatch.setattr(pipeline.extractor, "extract", lambda images: {"ok": False, "error": "503", "stats": {"api_calls": 1}})
    res = process_page("x.pdf", 1)
    assert res["pass1"]["is_commitment_form"] is False and "retried" not in res["pass1"] and not env
    assert sum_stats(*res["stats"].values())["api_calls"] == 1


def test_no_retry_when_conditions_do_not_hold(monkeypatch, env):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1(False, [num("12")]), True))
    monkeypatch.setattr(pipeline.extractor, "extract", lambda images: pytest.fail("no retry expected"))
    assert "pass1_retried" not in process_page("x.pdf", 1)


def test_already_retried_cached_result_is_not_retried_again(monkeypatch, env):
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1(False, LABELED6, retried=True), True))
    monkeypatch.setattr(pipeline.extractor, "extract", lambda images: pytest.fail("no second retry"))
    process_page("x.pdf", 1)
