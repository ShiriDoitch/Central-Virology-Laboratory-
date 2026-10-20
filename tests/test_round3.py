"""504 לא נספר במכסה, המתנה של 3 שניות בין מודלים במעבר השני, התאמה מקורבת לגורם שולח, missing_required_field."""
import httpx
from google.genai import errors

from src import extractor
from src.assemble import page_rows
from src.rules import F_MISSING_REQUIRED
from src.schema import Field_, PageExtraction, SenderMention
from src.senders import F_FUZZY_MATCH, F_UNKNOWN_SENDER, OTHER, decide_sender, load_matcher
from tests.test_retries import BUSY, PAGE, FakeClient, _second_pass

M = load_matcher()
GATEWAY = lambda: errors.ServerError(504, {"error": {"message": "deadline"}})


def mention(text, where="header", role="sender", conf=0.95):
    return SenderMention(text=text, where=where, role=role, confidence=conf)


# ---------- 504 ----------

def test_504_is_counted_in_local_quota(monkeypatch, quota_tracker):
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    _second_pass(monkeypatch, {"s1": [GATEWAY()], "s2": ["{}"]}, "s1,s2")
    assert quota_tracker.used("s1") == 1 and quota_tracker.used("s2") == 1


# ---------- המתנה בין מודלים ----------

def test_second_pass_sleeps_3_seconds_between_failed_models(monkeypatch):
    sleeps = []
    monkeypatch.setattr(extractor.time, "sleep", lambda s: sleeps.append(s))
    client, result = _second_pass(monkeypatch, {"s1": [BUSY()], "s2": [GATEWAY()], "s3": ["{}"]}, "s1,s2,s3")
    assert result["ok"] is True and client.models.calls == ["s1", "s2", "s3"]
    assert sleeps == [3, 3]                      # בין s1 ל-s2 ובין s2 ל-s3; לא לפני הראשון ולא אחרי ההצלחה


def test_no_sleep_after_last_failure_or_on_first_success(monkeypatch):
    sleeps = []
    monkeypatch.setattr(extractor.time, "sleep", lambda s: sleeps.append(s))
    _second_pass(monkeypatch, {"s1": ["{}"]}, "s1")
    _second_pass(monkeypatch, {"s1": [httpx.ReadTimeout("t")]}, "s1")
    assert sleeps == []


def test_first_pass_has_no_fallback_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(extractor.time, "sleep", lambda s: sleeps.append(s))
    client = FakeClient({"m1": [GATEWAY()], "m2": [PAGE]})
    tried, errs = [], {}
    extractor._call_with_fallback(client, ["x"], PageExtraction, tried, errs, ["m1", "m2"], extractor.Counter(),
                                  max_calls=2, attempts_per_model=1)
    assert sleeps == []


# ---------- התאמה מקורבת ----------

def test_fuzzy_match_page_14_case_is_orange_with_original_text_kept():
    ms = [mention("צפון", "logo"), mention("מרכז רפואי צפון פוריאה", "header"),
          mention("המעבדה המרכזית לנגיפים המרכז הרפואי המשולב", "stamp", "destination")]
    d = decide_sender(ms, M)
    assert d.value == "מרכז רפואי צפון פוריה" and F_FUZZY_MATCH in d.flags and d.uncertain
    assert "מרכז רפואי צפון פוריאה" in d.alternatives
    assert F_UNKNOWN_SENDER not in d.flags


def test_north_alone_is_not_an_alias_and_stays_other():
    d = decide_sender([mention("צפון", "logo")], M)
    assert d.value == OTHER and F_UNKNOWN_SENDER in d.flags and F_FUZZY_MATCH not in d.flags


def test_exact_match_has_no_fuzzy_flag():
    d = decide_sender([mention("מרכז רפואי צפון פוריה")], M)
    assert d.value == "מרכז רפואי צפון פוריה" and F_FUZZY_MATCH not in d.flags


def test_unrelated_text_is_not_fuzzy_matched():
    d = decide_sender([mention("מכון בדיקות ביתי")], M)
    assert d.value == OTHER and F_FUZZY_MATCH not in d.flags


def test_fuzzy_never_applies_to_destination_mentions():
    d = decide_sender([mention("מרכז רפואי צפון פוריאה", "stamp", "destination")], M)
    assert d.value is None and F_FUZZY_MATCH not in d.flags


# ---------- missing_required_field ----------

def _page(first=None, last=None):
    def f(v):
        return Field_(value=v, confidence=0.95, source="printed", label="שם פרטי") if v else Field_()
    p = PageExtraction(is_commitment_form=True, page_quality="ok", first_name=f(first), last_name=f(last),
                       numbers=[{"value": "123456", "label": "התחייבות", "confidence": 1.0, "source": "printed"}])
    return {"ok": True, "model": "x", **p.model_dump()}


def test_both_names_empty_flagged_missing_required_in_both():
    row = page_rows(_page())[0]
    assert F_MISSING_REQUIRED in row["first_name"].flags and F_MISSING_REQUIRED in row["last_name"].flags
    assert row["first_name"].value is None and row["last_name"].value is None      # הערך לא מנוחש


def test_one_name_present_flags_only_the_missing_one():
    """שונה ב-20.10.2026: שם ריק בלי דגל אחר מקבל missing_required_field, גם כשהשם השני נקרא.
    קודם הוא נשאר ריק ובלי סימון, וכך שגיאה יכלה לעבור בשקט (עמוד 19 ב-v4b)."""
    row = page_rows(_page(first="דנה"))[0]
    assert F_MISSING_REQUIRED not in row["first_name"].flags
    assert F_MISSING_REQUIRED in row["last_name"].flags and row["last_name"].uncertain
