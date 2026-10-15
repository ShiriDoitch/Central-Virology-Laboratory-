import pytest
from google.genai import errors

from tests.conftest import legacy_strong, set_models
from src import extractor
from src.pipeline import render_model_summary, summarize_by_model
from src.schema import PageExtraction, RegionsExtraction


class FakeModels:
    def __init__(self, outcomes_by_model):
        self.outcomes = {m: list(o) for m, o in outcomes_by_model.items()}
        self.calls: list[str] = []

    def generate_content(self, model, **kwargs):
        self.calls.append(model)
        outcome = self.outcomes[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return type("R", (), {"text": outcome})()


class FakeClient:
    def __init__(self, outcomes_by_model):
        self.models = FakeModels(outcomes_by_model)


BUSY = lambda: errors.ServerError(503, {"error": {"message": "busy"}})
NOT_FOUND = lambda: errors.ClientError(404, {"error": {"message": "model not found"}})
MINUTE_429 = lambda: errors.ClientError(429, {"error": {"message": "per minute limit"}})
PAGE = PageExtraction(is_commitment_form=True, page_quality="ok").model_dump_json()


@pytest.fixture
def sleeps(monkeypatch):
    """מקליט את ההמתנות של extractor (ללא jitter) בלי להמתין בפועל."""
    recorded: list[float] = []
    monkeypatch.setattr(extractor.time, "sleep", lambda s: recorded.append(s))
    monkeypatch.setattr(extractor, "_jitter", lambda base: base)
    return recorded


def call_fallback(client, models, stats=None, max_calls=None):
    stats = stats if stats is not None else extractor.Counter()
    tried, errs = [], {}
    try:
        result = extractor._call_with_fallback(client, ["x"], PageExtraction, tried, errs, models, stats, max_calls)
    except Exception as e:
        result = e
    return result, tried, errs, stats


# ---------- המתנות אחרי 503 ----------

def test_503_waits_3_8_20_seconds_on_same_model_then_succeeds(sleeps):
    client = FakeClient({"m1": [BUSY(), BUSY(), BUSY(), PAGE]})
    result, tried, errs, stats = call_fallback(client, ["m1", "m2"])
    assert result == (PAGE, "m1")
    assert sleeps == [3, 8, 20]
    assert client.models.calls == ["m1"] * 4 and stats["api_calls"] == 4


def test_after_three_retries_moves_to_next_model(sleeps):
    client = FakeClient({"m1": [BUSY()] * 4, "m2": [PAGE]})
    result, tried, errs, stats = call_fallback(client, ["m1", "m2"])
    assert result == (PAGE, "m2")
    assert sleeps == [3, 8, 20]                       # אחרי הכישלון הרביעי לא ממתינים: עוברים מודל
    assert client.models.calls == ["m1"] * 4 + ["m2"]
    assert errs == {"m1": "503"}


def test_jitter_stays_within_25_percent():
    values = [extractor._jitter(8) for _ in range(500)]
    assert all(6 <= v <= 10 for v in values)
    assert len(set(values)) > 100                     # באמת אקראי


def test_timeout_is_retried_like_503(sleeps):
    import httpx
    client = FakeClient({"m1": [httpx.ReadTimeout("t"), PAGE]})
    result, _, _, stats = call_fallback(client, ["m1"])
    assert result == (PAGE, "m1") and sleeps == [3] and stats["timeouts"] == 1


def test_minute_429_waits_60_once_then_gives_up_on_model(sleeps):
    client = FakeClient({"m1": [MINUTE_429(), MINUTE_429()], "m2": [PAGE]})
    result, _, errs, stats = call_fallback(client, ["m1", "m2"])
    assert result == (PAGE, "m2")
    assert sleeps == [60] and client.models.calls == ["m1", "m1", "m2"]
    assert errs == {"m1": "429"} and stats["429:m1"] == 2


# ---------- לא יותר מ-3 מודלים לעמוד ----------

def test_at_most_three_models_are_called_per_page(sleeps):
    client = FakeClient({f"m{i}": [BUSY()] * 4 for i in range(1, 6)})
    result, tried, errs, stats = call_fallback(client, ["m1", "m2", "m3", "m4", "m5"])
    assert isinstance(result, Exception)
    assert tried == ["m1", "m2", "m3"] and set(client.models.calls) == {"m1", "m2", "m3"}
    assert stats["api_calls"] == 12


def test_skipped_exhausted_model_does_not_count_toward_the_cap(sleeps, quota_tracker):
    quota_tracker.mark_exhausted("m1")
    client = FakeClient({"m2": [BUSY()] * 4, "m3": [BUSY()] * 4, "m4": [PAGE]})
    result, tried, errs, stats = call_fallback(client, ["m1", "m2", "m3", "m4"])
    assert result == (PAGE, "m4")                      # m1 דולג בלי קריאה, ולכן m4 הוא המודל השלישי שנקרא
    assert errs["m1"] == "daily_quota" and "m1" not in client.models.calls


# ---------- 404 ----------

def test_404_marks_model_unavailable_and_chain_continues(sleeps, quota_tracker):
    client = FakeClient({"bad": [NOT_FOUND()], "good": [PAGE]})
    result, tried, errs, stats = call_fallback(client, ["bad", "good"])
    assert result == (PAGE, "good")
    assert errs == {"bad": "404"} and stats["404:bad"] == 1 and stats["not_found"] == 1
    assert client.models.calls == ["bad", "good"]            # בלי ניסיון חוזר על 404
    assert quota_tracker.remaining("bad") == 0 and "לא קיים" in quota_tracker.report(["bad"])


def test_404_model_is_not_called_again_the_same_day(sleeps):
    client = FakeClient({"bad": [NOT_FOUND()], "good": [PAGE, PAGE]})
    call_fallback(client, ["bad", "good"])
    result, _, errs, _ = call_fallback(client, ["bad", "good"])
    assert result == (PAGE, "good") and client.models.calls == ["bad", "good", "good"]   # "bad" לא נקרא שוב
    assert errs["bad"] == "404"


def test_all_models_404_fails_cleanly(monkeypatch, sleeps):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    client = FakeClient({"a": [NOT_FOUND()], "b": [NOT_FOUND()]})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor._run(["x"], PageExtraction, ["a", "b"])
    assert result["ok"] is False and result["model_errors"] == {"a": "404", "b": "404"}
    assert "daily_quota_exhausted" not in result              # 404 אינו "מכסה יומית"


# ---------- מעבר שני: התקציב נשאר קריאה אחת ----------

def _second_pass(monkeypatch, outcomes, strong):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    legacy_strong(monkeypatch, strong)
    client = FakeClient(outcomes)
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    return client, extractor.extract_regions({"patient": b"a", "barcode": b"b"})


def test_second_pass_503_moves_to_next_strong_model_after_3s(monkeypatch, sleeps, quota_tracker):
    client, result = _second_pass(monkeypatch, {"s1": [BUSY()], "s2": [BUSY()], "s3": ["{}"]}, "s1,s2,s3")
    assert client.models.calls == ["s1", "s2", "s3"] and sleeps == [3, 3]   # ניסיון אחד לכל מודל, 3 שניות בין מודלים
    assert result["ok"] is True and result["model"] == "s3"


def test_second_pass_at_most_three_models(monkeypatch, sleeps):
    client, result = _second_pass(monkeypatch, {f"s{i}": [BUSY()] for i in range(1, 5)}, "s1,s2,s3,s4")
    assert result["ok"] is False and client.models.calls == ["s1", "s2", "s4"] and sleeps == [3, 3]   # 2 חזקים ואחריהם מודל ברירת המחדל (האחרון)


def test_second_pass_timeout_moves_to_next_model(monkeypatch, sleeps):
    import httpx
    client, result = _second_pass(monkeypatch, {"s1": [httpx.ReadTimeout("t")], "s2": ["{}"]}, "s1,s2")
    assert client.models.calls == ["s1", "s2"] and result["model"] == "s2" and sleeps == [3]


def test_503_is_counted_in_local_quota_like_success(monkeypatch, sleeps, quota_tracker):
    _second_pass(monkeypatch, {"s1": [BUSY()], "s2": ["{}"]}, "s1,s2")
    assert quota_tracker.used("s1") == 1          # כל בקשה שנשלחה ל-Google נספרת (גם 503)
    assert quota_tracker.used("s2") == 1


def test_timeout_is_counted_in_local_quota(monkeypatch, sleeps, quota_tracker):
    import httpx
    _second_pass(monkeypatch, {"s1": [httpx.ReadTimeout("t")], "s2": ["{}"]}, "s1,s2")
    assert quota_tracker.used("s1") == 1


def test_429_is_counted_in_local_quota(monkeypatch, sleeps, quota_tracker):
    daily = errors.ClientError(429, {"error": {"message": "exceeded PerDay quota"}})
    _second_pass(monkeypatch, {"s1": [daily], "s2": ["{}"]}, "s1,s2")
    assert quota_tracker.used("s1") == 1


# ---------- סטטיסטיקה לפי מודל ----------

def test_per_model_stats_keys_and_summary(sleeps):
    client = FakeClient({"m1": [BUSY(), BUSY(), PAGE]})
    _, _, _, stats = call_fallback(client, ["m1"])
    assert stats["calls:m1"] == 3 and stats["503:m1"] == 2 and stats["ok:m1"] == 1
    rows = summarize_by_model(dict(stats))
    assert rows == {"m1": {"calls": 3, "ok": 1, "429": 0, "503": 2, "404": 0, "timeout": 0, "other": 0}}


def test_render_model_summary_table_and_total():
    stats = {"calls:a": 5, "ok:a": 3, "429:a": 1, "503:a": 1, "calls:b": 2, "404:b": 1, "ok:b": 1,
             "api_calls": 7, "quota_failures": 1}
    text = render_model_summary(stats)
    lines = text.split("\n")
    assert lines[0].split() == ["model", "calls", "ok", "429", "503", "404", "timeout", "other"]
    assert lines[1].split() == ["a", "5", "3", "1", "1", "0", "0", "0"]
    assert lines[2].split() == ["b", "2", "1", "0", "0", "1", "0", "0"]
    assert lines[-1].split() == ["TOTAL", "7", "4", "1", "1", "1", "0", "0"]
    assert "none" in render_model_summary({})


def test_regions_schema_unchanged_by_retry_work():
    assert "region_ok" in RegionsExtraction.model_json_schema()["$defs"]["PatientRead"]["properties"]
