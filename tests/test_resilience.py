"""חוסן קריאות ה-API: מפתחות Gemini מרובים (סיבוב), ניסיון חוזר ב-503/504, וגיבוי Claude אחרון. בלי שום בקשה אמיתית:
לקוחות Gemini ו-_run_anthropic מוחלפים בלקוחות מדומים, וההמתנות מוחלפות בשעון מדומה."""
import base64

import pytest
from google.genai import errors, types

from src import cache, extractor
from src.export import pass2_issues
from src.schema import PageExtraction, RegionsExtraction

OK_JSON = '{"is_commitment_form": true, "page_quality": "ok"}'
DAILY_429 = lambda: errors.ClientError(429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel exceeded"}})
MINUTE_429 = lambda: errors.ClientError(429, {"error": {"message": "GenerateRequestsPerMinutePerProjectPerModel"}})
BUSY_503 = lambda: errors.ServerError(503, {"error": {"message": "busy"}})
BAD_400 = lambda: errors.ClientError(400, {"error": {"message": "bad request"}})
AUTH_403 = lambda: errors.ClientError(403, {"error": {"message": "API key not valid"}})


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, key, plan, log):
        self.key, self.plan, self.log = key, plan, log

    def generate_content(self, **kwargs):
        self.log.append(self.key)
        outcome = self.plan[self.key].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


class FakeClient:
    def __init__(self, key, plan, log):
        self.models = FakeModels(key, plan, log)


@pytest.fixture
def gemini(monkeypatch):
    """gemini(keys, plan): מגדיר GEMINI_API_KEYS, ולכל מפתח רשימת תוצאות (חריגה = כשל, מחרוזת = טקסט תשובה)."""
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def setup(keys, plan):
        monkeypatch.setenv("GEMINI_API_KEYS", ",".join(keys))
        log: list[str] = []
        state = {k: list(v) for k, v in plan.items()}
        monkeypatch.setattr(extractor.genai, "Client", lambda api_key=None, **kw: FakeClient(api_key, state, log))
        return log

    return setup


@pytest.fixture
def claude(monkeypatch):
    """מפעיל את גיבוי Claude ומחליף את הקריאה האמיתית (_run_anthropic) בגרסה שרושמת מה נשלח."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("CLAUDE_FALLBACK", "1")
    calls: list[dict] = []

    def fake(contents, schema, models, max_calls):
        calls.append({"contents": contents, "schema": schema})
        return {"ok": True, "model": "claude-test", "model_errors": {}, "stats": {"api_calls": 1, "calls:claude-test": 1},
                **schema.model_validate_json(OK_JSON).model_dump()}

    monkeypatch.setattr(extractor, "_run_anthropic", fake)
    return calls


# ---------- מפתחות ----------

def test_keys_list_is_parsed_deduped_and_wins_over_the_single_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "a, b,,a ,c")
    monkeypatch.setenv("GEMINI_API_KEY", "single")
    assert extractor.gemini_api_keys() == ["a", "b", "c"]


def test_single_key_is_used_when_it_is_the_only_one_set(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", " single ")
    assert extractor.gemini_api_keys() == ["single"]
    monkeypatch.delenv("GEMINI_API_KEY")
    assert extractor.gemini_api_keys() == []


# ---------- סיבוב מפתחות ----------

def test_quota_on_key1_503_on_key2_success_on_key3_uses_and_records_key3(gemini):
    log = gemini(["k1", "k2", "k3"], {"k1": [DAILY_429()], "k2": [BUSY_503()] * 4, "k3": [OK_JSON]})
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert res["ok"] and res["provider"] == "gemini"
    assert res["api_key_index"] == 2 and res["model"] == "m1"
    assert set(res["key_errors"]) == {0, 1}
    assert log == ["k1", "k2", "k2", "k2", "k2", "k3"]            # k1: מכסה יומית בלי ניסיון חוזר; k2: ניסיון + 3 חוזרים; k3: הצליח
    assert res["stats"]["key_rotations"] == 2 and res["stats"]["calls:m1"] == 6


def test_first_key_success_records_index_zero_and_no_rotation(gemini):
    log = gemini(["k1", "k2"], {"k1": [OK_JSON], "k2": [OK_JSON]})
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert res["ok"] and res["api_key_index"] == 0 and "key_errors" not in res
    assert log == ["k1"]


def test_auth_error_on_a_key_rotates_to_the_next_one(gemini):
    log = gemini(["bad", "good"], {"bad": [AUTH_403()], "good": [OK_JSON]})
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert res["ok"] and res["api_key_index"] == 1 and log == ["bad", "good"]


def test_bad_request_400_is_not_retried_rotated_or_sent_to_claude(gemini, claude):
    log = gemini(["k1", "k2"], {"k1": [BAD_400()], "k2": [OK_JSON]})
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert not res["ok"] and log == ["k1"]                        # בלי ניסיון חוזר ובלי מפתח הבא
    assert claude == []                                           # וגם בלי Claude: אותה בקשה פגומה


def test_503_is_retried_with_short_backoff_on_the_same_key_before_rotating(gemini, monkeypatch):
    sleeps: list[float] = []
    log = gemini(["k1", "k2"], {"k1": [BUSY_503(), BUSY_503(), OK_JSON], "k2": [OK_JSON]})
    monkeypatch.setattr(extractor.time, "sleep", sleeps.append)
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert res["ok"] and res["api_key_index"] == 0 and log == ["k1", "k1", "k1"]
    assert len(sleeps) == 2 and all(0 < s <= 30 for s in sleeps)


def test_key_text_never_appears_in_the_error(gemini):
    secret = "AIza-SECRET-KEY-123"
    gemini([secret], {secret: [RuntimeError(f"boom {secret}")]})
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert not res["ok"] and secret not in res["error"] and "***" in res["error"]


# ---------- גיבוי Claude ----------

def test_all_gemini_attempts_failing_falls_back_to_claude_and_records_it(gemini, claude):
    log = gemini(["k1", "k2"], {"k1": [BUSY_503()] * 4, "k2": [BUSY_503()] * 4})
    part = types.Part.from_bytes(data=b"\xff\xd8fakejpeg", mime_type="image/jpeg")
    res = extractor._run([part, "prompt text"], PageExtraction, ["m1"])
    assert len(claude) == 1 and len(log) == 8
    assert res["ok"] and res["provider"] == "anthropic" and res["model"] == "claude-test"
    assert res["fallback"] is True and set(res["fallback_from"]) == {0, 1}
    assert res["stats"]["claude_fallback_calls"] == 1 and res["stats"]["calls:m1"] == 8      # גם הניסיונות של Gemini נספרו
    sent = claude[0]["contents"]
    assert sent[1] == "prompt text" and sent[0]["type"] == "image"                        # אותה בקשה: תמונה כבלוק Anthropic + אותו טקסט
    assert base64.standard_b64decode(sent[0]["source"]["data"]) == b"\xff\xd8fakejpeg"


def test_claude_is_not_used_when_gemini_succeeds(gemini, claude):
    gemini(["k1"], {"k1": [OK_JSON]})
    assert extractor._run(["x"], PageExtraction, ["m1"])["provider"] == "gemini" and claude == []


def test_without_anthropic_key_the_page_fails_as_before(gemini, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_FALLBACK", "1")
    gemini(["k1"], {"k1": [BUSY_503()] * 4})
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert not res["ok"] and "503" in res["error"] and res.get("provider") == "gemini"


def test_claude_fallback_can_be_switched_off(gemini, claude, monkeypatch):
    monkeypatch.setenv("CLAUDE_FALLBACK", "0")
    gemini(["k1"], {"k1": [BUSY_503()] * 4})
    assert not extractor._run(["x"], PageExtraction, ["m1"])["ok"] and claude == []


def test_claude_failure_is_reported_not_raised(gemini, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "t")
    monkeypatch.setenv("CLAUDE_FALLBACK", "1")
    monkeypatch.setattr(extractor, "_run_anthropic", lambda *a, **k: {"ok": False, "error": "RateLimitError: 429", "stats": {}})
    gemini(["k1"], {"k1": [BUSY_503()] * 4})
    res = extractor._run(["x"], PageExtraction, ["m1"])
    assert not res["ok"] and res["provider"] == "anthropic" and "429" in res["error"]


# ---------- מעבר 2 ----------

def regions_run(contents, chain):
    return extractor._run_regions_with_fallback(contents, chain)


def test_pass2_retries_503_once_on_the_same_model_by_default(gemini, monkeypatch):
    monkeypatch.setattr(extractor, "REGION_ATTEMPTS", 2)
    log = gemini(["k1"], {"k1": [BUSY_503(), OK_JSON]})
    res = regions_run(["x"], ["strong"])
    assert res["ok"] and res["model"] == "strong" and res["fallback"] is False and len(log) == 2


def test_pass2_minute_429_moves_on_without_waiting_60_seconds(gemini, monkeypatch):
    monkeypatch.setattr(extractor, "REGION_ATTEMPTS", 2)
    sleeps: list[float] = []
    gemini(["k1"], {"k1": [MINUTE_429(), OK_JSON]})
    monkeypatch.setattr(extractor.time, "sleep", sleeps.append)
    res = regions_run(["x"], ["strong", "lite"])
    assert res["ok"] and res["model"] == "lite" and res["fallback"] is True
    assert extractor.QUOTA_WAIT_S not in sleeps


def test_pass2_claude_is_called_once_after_the_whole_chain_fails(gemini, claude, monkeypatch):
    monkeypatch.setattr(extractor, "REGION_ATTEMPTS", 2)
    log = gemini(["k1", "k2"], {"k1": [BUSY_503()] * 4, "k2": [BUSY_503()] * 4})
    res = regions_run(["x"], ["strong", "lite"])
    assert len(claude) == 1 and claude[0]["schema"] is RegionsExtraction
    assert len(log) == 8                                           # 2 מודלים x 2 מפתחות x 2 ניסיונות
    assert res["ok"] and res["provider"] == "anthropic" and res["fallback"] is True and res["model"] == "claude-test"


def test_pass2_key_rotation_inside_a_model(gemini, monkeypatch):
    monkeypatch.setattr(extractor, "REGION_ATTEMPTS", 2)
    log = gemini(["k1", "k2"], {"k1": [DAILY_429()], "k2": [OK_JSON]})
    res = regions_run(["x"], ["strong", "lite"])
    assert res["ok"] and res["model"] == "strong" and res["fallback"] is False and res["api_key_index"] == 1
    assert log == ["k1", "k2"]


# ---------- מטמון ודוחות ----------

def test_answer_from_a_later_key_is_cached_but_claude_fallback_is_not(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    ok_key2 = {"ok": True, "model": "m1", "provider": "gemini", "api_key_index": 1}
    claude_res = {"ok": True, "model": "claude-test", "provider": "anthropic", "fallback": True}
    assert cache._cached("k_gemini", lambda _a: ok_key2, None) == (ok_key2, False)
    assert (tmp_path / "k_gemini.json").exists()
    cache._cached("k_claude", lambda _a: claude_res, None)
    assert not (tmp_path / "k_claude.json").exists()


def test_pass2_issues_lists_claude_pages_separately_from_weak_fallback():
    pages = [{"page": 1, "pass2_fallback": True, "pass2": {"ok": True, "provider": "anthropic"}, "pass1": {"ok": True}},
             {"page": 2, "pass2_fallback": True, "pass2": {"ok": True, "provider": "gemini"}, "pass1": {"ok": True}},
             {"page": 3, "pass2_fallback": False, "pass2": {"ok": True}, "pass1": {"ok": True, "provider": "anthropic"}}]
    out = pass2_issues(pages)
    assert out["claude"] == [1] and out["fallback"] == [2] and out["claude_pass1"] == [3]
