import json

import pytest
from google.genai import errors

from tests.conftest import legacy_strong, set_models
from src import extractor
from src.quota import DEFAULT_CONFIG, DailyQuotaExhausted, QuotaTracker, is_daily_quota_error
from src.schema import PageExtraction, RegionsExtraction

STRONG = ["strong-1", "strong-2"]


def tracker_for(tmp_path, clock, day="2026-10-14", name="q.json"):
    return QuotaTracker(path=tmp_path / name, config=DEFAULT_CONFIG, strong_models=lambda: STRONG,
                        now=clock.now, sleep=clock.sleep, today=lambda: day)


@pytest.fixture
def clock(quota_tracker):
    return quota_tracker.clock


# ---------- מרווחים ----------

def test_strong_calls_are_spaced_13_seconds(tmp_path, clock):
    t = tracker_for(tmp_path, clock)
    t.before_call("strong-1")
    assert clock.sleeps == []                    # הקריאה הראשונה: בלי המתנה
    t.before_call("strong-1")
    assert clock.sleeps == [13]


def test_small_calls_are_spaced_5_seconds(tmp_path, clock):
    t = tracker_for(tmp_path, clock)
    t.before_call("small-1")
    t.before_call("small-2")
    assert clock.sleeps == [5]


def test_spacing_is_per_tier_and_counts_elapsed_time(tmp_path, clock):
    t = tracker_for(tmp_path, clock)
    t.before_call("strong-1")
    t.before_call("small-1")                     # דרגה אחרת: בלי המתנה
    assert clock.sleeps == []
    clock.t += 10                                # עברו 10 שניות: נשארו 3 מתוך 13
    t.before_call("strong-2")
    assert clock.sleeps == [pytest.approx(3)]


# ---------- מונה יומי ----------

def test_daily_counter_persists_across_instances_and_resets_next_day(tmp_path, clock):
    t = tracker_for(tmp_path, clock)
    for _ in range(3):
        t.before_call("strong-1")
    assert tracker_for(tmp_path, clock).used("strong-1") == 3          # מופע חדש קורא מהקובץ
    assert tracker_for(tmp_path, clock, day="2026-10-15").used("strong-1") == 0   # יום חדש
    assert json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))["models"]["strong-1"]["calls"] == 3


def test_strong_model_stops_at_18_of_20(tmp_path, clock):
    t = tracker_for(tmp_path, clock)
    for _ in range(18):
        t.before_call("strong-1")
    assert t.remaining("strong-1") == 0
    with pytest.raises(DailyQuotaExhausted) as e:
        t.before_call("strong-1")
    assert e.value.reason == "limit_reached"
    assert t.used("strong-1") == 18                                    # הקריאה ה-19 לא נרשמה
    t.before_call("strong-2")                                          # מודל אחר לא מושפע


def test_mark_exhausted_blocks_model_for_the_day_only(tmp_path, clock):
    t = tracker_for(tmp_path, clock)
    t.mark_exhausted("strong-1")
    with pytest.raises(DailyQuotaExhausted) as e:
        t.check("strong-1")
    assert e.value.reason == "marked_exhausted"
    t.check("strong-2")
    tracker_for(tmp_path, clock, day="2026-10-15").check("strong-1")   # למחרת מותר


def test_report_line(tmp_path, clock):
    t = tracker_for(tmp_path, clock)
    t.before_call("strong-1")
    t.mark_exhausted("strong-2")
    assert t.report(STRONG) == "strong-1: 1/20 | strong-2: 0/20 (מוצה)"


# ---------- זיהוי 429 יומי ----------

def test_is_daily_quota_error():
    daily = errors.ClientError(429, {"error": {"message": "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"}})
    minute = errors.ClientError(429, {"error": {"message": "Quota exceeded: GenerateRequestsPerMinutePerProjectPerModel"}})
    other = errors.ServerError(503, {"error": {"message": "per day busy"}})
    assert is_daily_quota_error(daily) and not is_daily_quota_error(minute) and not is_daily_quota_error(other)


# ---------- שילוב ב-extractor ----------

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


DAILY_429 = lambda: errors.ClientError(429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel exceeded"}})
MINUTE_429 = lambda: errors.ClientError(429, {"error": {"message": "per minute limit"}})
BUSY_503 = lambda: errors.ServerError(503, {"error": {"message": "busy"}})
OK_REGIONS = RegionsExtraction().model_dump_json()


@pytest.fixture
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)


def test_daily_429_marks_model_and_is_not_retried(monkeypatch, no_real_sleep, quota_tracker):
    legacy_strong(monkeypatch, "s1,s2")
    client = FakeClient({"s1": [DAILY_429()]})
    stats = extractor.Counter()
    tried, errs = [], {}
    with pytest.raises(DailyQuotaExhausted):
        extractor._call_with_fallback(client, ["x"], RegionsExtraction, tried, errs, ["s1"], stats)
    assert client.models.calls == ["s1"] and stats["api_calls"] == 1      # בלי ניסיון חוזר
    assert errs == {"s1": "daily_quota"} and stats["daily_quota_hits"] == 1
    assert quota_tracker.remaining("s1") == 0                              # סומן כמוצה לכל היום
    with pytest.raises(DailyQuotaExhausted):
        quota_tracker.check("s1")


def test_model_exhausted_earlier_today_is_skipped_without_api_call(monkeypatch, no_real_sleep, quota_tracker):
    legacy_strong(monkeypatch, "s1,s2")
    quota_tracker.mark_exhausted("s1")
    client = FakeClient({"s2": [OK_REGIONS]})
    tried, errs = [], {}
    text, model = extractor._call_with_fallback(client, ["x"], RegionsExtraction, tried, errs, ["s1", "s2"])
    assert model == "s2" and client.models.calls == ["s2"]                # s1 לא נקרא בכלל
    assert errs == {"s1": "daily_quota"}


def test_all_models_exhausted_reports_clear_message(monkeypatch, no_real_sleep, quota_tracker):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    legacy_strong(monkeypatch, "s1,s2")
    for m in ("s1", "s2"):
        quota_tracker.mark_exhausted(m)
    client = FakeClient({})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is False
    assert result["error"].startswith("מכסה יומית נגמרה")
    assert result["daily_quota_exhausted"] == ["s1", "s2"]
    assert client.models.calls == [] and result["stats"] == {}            # אפס קריאות API


def test_limit_of_18_blocks_strong_model_in_extract_regions(monkeypatch, no_real_sleep, quota_tracker):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    legacy_strong(monkeypatch, "s1")
    client = FakeClient({"s1": [OK_REGIONS] * 20})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    results = [extractor.extract_regions({"patient": b"a", "barcode": b"b"}) for _ in range(19)]
    assert [r["ok"] for r in results] == [True] * 18 + [False]
    assert results[-1]["error"].startswith("מכסה יומית נגמרה")
    assert len(client.models.calls) == 18


def test_regions_one_attempt_per_model_503_moves_to_next_model(monkeypatch, no_real_sleep):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    legacy_strong(monkeypatch, "s1,s2")
    client = FakeClient({"s1": [BUSY_503(), OK_REGIONS], "s2": [OK_REGIONS]})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is True and result["model"] == "s2"
    assert client.models.calls == ["s1", "s2"]                            # בלי ניסיון חוזר על s1
    assert result["stats"]["api_calls"] == 2 and result["model_errors"] == {"s1": "503"}


def test_regions_minute_429_is_not_retried_either(monkeypatch, no_real_sleep):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    legacy_strong(monkeypatch, "s1")
    client = FakeClient({"s1": [MINUTE_429(), OK_REGIONS]})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is False and client.models.calls == ["s1"]


def test_regions_invalid_json_is_not_retried(monkeypatch, no_real_sleep):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    legacy_strong(monkeypatch, "s1")
    client = FakeClient({"s1": ["{bad", OK_REGIONS]})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is False and result["error"] == "model returned invalid JSON"
    assert client.models.calls == ["s1"]


def test_first_pass_falls_back_among_small_models_after_one_attempt(monkeypatch, no_real_sleep):
    """מעבר ראשון (22.10.2026): ניסיון אחד למודל, בלי המתנה, ואז מיד המודל הבא."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    set_models(monkeypatch, first="small-1", fallbacks=["small-2"], strong=["s1"])
    page = PageExtraction(is_commitment_form=True, page_quality="ok").model_dump_json()
    client = FakeClient({"small-1": [BUSY_503()], "small-2": [page]})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor.extract([b"img"])
    assert result["ok"] and result["model"] == "small-2"
    assert client.models.calls == ["small-1", "small-2"]                  # ניסיון אחד, ואז מיד המודל הבא


def test_first_pass_chain_filters_out_strong_models(monkeypatch):
    set_models(monkeypatch, first="small-1", fallbacks=["small-2", "s1", "s2"], strong=["s1", "s2"])
    assert extractor.model_chain() == ["small-1", "small-2"]
    set_models(monkeypatch, first="s1", fallbacks=["small-2", "s1", "s2"], strong=["s1", "s2"])   # גם מודל ראשי חזק מסונן
    assert extractor.model_chain() == ["small-2"]


def test_default_config_has_requested_limits():
    assert DEFAULT_CONFIG["strong"] == {"per_minute": 5, "per_day": 20, "stop_at": 18, "min_interval_s": 13}
    assert DEFAULT_CONFIG["small"]["per_day"] == 500 and DEFAULT_CONFIG["small"]["min_interval_s"] == 5
    from src.quota import load_config
    assert load_config() == DEFAULT_CONFIG                    # הקובץ config/quotas.json תואם לברירות המחדל
