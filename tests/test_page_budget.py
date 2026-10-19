"""תקציב זמן לעמוד: נבדק בין ניסיונות, מודלים ומפתחות, בשעון מדומה. חריגה = error_code "page_timeout", שאר העמודים ממשיכים,
וההעלאה נשארת לא שלמה (העלאה חוזרת ממשיכה). בלי שום בקשה אמיתית."""
import httpx
import pymupdf
import pytest

from src import extractor, pipeline, repo, service, upload
from tests.conftest import set_models
from tests.test_resilience import OK_JSON, claude  # noqa: F401  (fixture)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def fake_time(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(extractor, "_clock", clock.now)
    monkeypatch.setattr(extractor.time, "sleep", clock.sleep)
    monkeypatch.setattr(extractor, "_jitter", lambda base: base)
    return clock


@pytest.fixture
def hanging(monkeypatch, fake_time):
    """לקוח Gemini שכל קריאה אליו "נתקעת" עד ה-timeout שנשלח בבקשה (60 שניות לכל היותר) ואז נכשלת ב-timeout."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    calls: list[tuple[str, int]] = []

    class Models:
        def __init__(self, key):
            self.key = key

        def generate_content(self, **kwargs):
            timeout_ms = kwargs["config"].http_options.timeout if kwargs["config"].http_options else extractor.TIMEOUT_MS
            calls.append((self.key, timeout_ms))
            fake_time.t += timeout_ms / 1000
            raise httpx.ReadTimeout("slow")

    class Client:
        def __init__(self, key):
            self.models = Models(key)

    def setup(keys):
        monkeypatch.setenv("GEMINI_API_KEYS", ",".join(keys))
        monkeypatch.setattr(extractor.genai, "Client", lambda api_key=None, **kw: Client(api_key))
        return calls

    return setup


def test_pass1_stops_at_the_budget_across_attempts_models_and_keys(hanging, fake_time, claude, monkeypatch):
    set_models(monkeypatch, first="m1", fallbacks=["m2"])
    calls = hanging(["a", "b"])
    start = fake_time.t
    with extractor.page_budget(180) as state:
        res = extractor.extract([b"img"])
    assert not res["ok"] and res["error_code"] == "page_timeout" and state.exceeded
    assert calls == [("a", 60000), ("a", 60000), ("a", 49000)]          # הניסיון השלישי מוגבל לזמן שנשאר
    assert fake_time.t - start <= 180.01
    assert claude == []                                                   # חריגה בזמן: בלי גיבוי Claude ובלי מפתח נוסף


def test_not_enough_time_left_skips_the_wait_and_the_attempt(hanging, fake_time, monkeypatch):
    set_models(monkeypatch, first="m1")
    calls = hanging(["a"])
    start = fake_time.t
    with extractor.page_budget(66):
        res = extractor.extract([b"img"])
    assert res["error_code"] == "page_timeout"
    assert calls == [("a", 60000)]                      # נשארו 6 שניות: אחרי המתנה של 3 לא יישאר מינימום לניסיון, אז לא ממתינים
    assert fake_time.t - start <= 66.01


def test_no_budget_context_keeps_the_old_behaviour(hanging, fake_time, monkeypatch):
    set_models(monkeypatch, first="m1", fallbacks=["m2"])
    calls = hanging(["a"])
    res = extractor.extract([b"img"])
    assert "error_code" not in res or res["error_code"] != "page_timeout"
    assert len(calls) == 8 and all(t == 60000 for _, t in calls)         # 4 ניסיונות x 2 מודלים, כמו קודם


def test_regions_chain_stops_on_budget(hanging, fake_time, claude, monkeypatch):
    monkeypatch.setattr(extractor, "region_model_chain", lambda: ["s1", "s2"])
    calls = hanging(["a"])
    with extractor.page_budget(20):
        res = extractor.extract_regions({"patient": b"x", "barcode": b"y"})
    assert not res["ok"] and res["error_code"] == "page_timeout"
    assert calls == [("a", 20000)] and claude == []


def test_budget_env_is_configurable_and_validated(monkeypatch):
    monkeypatch.delenv("PAGE_BUDGET_S", raising=False)
    assert extractor.page_budget_s() == 180
    monkeypatch.setenv("PAGE_BUDGET_S", "45")
    assert extractor.page_budget_s() == 45
    for bad in ("abc", "0", "-5", ""):
        monkeypatch.setenv("PAGE_BUDGET_S", bad)
        assert extractor.page_budget_s() == 180


def test_process_page_returns_failed_page_with_code(hanging, fake_time, monkeypatch, tmp_path):
    set_models(monkeypatch, first="m1")
    calls = hanging(["a"])
    monkeypatch.setenv("PAGE_BUDGET_S", "30")
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (extractor.extract(images), False))
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "p.pdf"
    doc.save(str(path))
    out = pipeline.process_page(str(path), 1)
    assert out["error_code"] == "page_timeout" and out["pass1"]["error_code"] == "page_timeout" and out["pass1"]["ok"] is False
    assert calls == [("a", 30000)]


def test_pass2_budget_exhaustion_marks_the_page_but_keeps_pass1(monkeypatch, tmp_path):
    clock = Clock()
    monkeypatch.setattr(extractor, "_clock", clock.now)
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "p.pdf"
    doc.save(str(path))
    r1 = {"ok": True, "is_commitment_form": True, "page_quality": "ok", "model": "m"}
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1, True))
    monkeypatch.setattr(pipeline, "needs_second_pass", lambda page: (True, ["x"]))
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: ({"ok": False, "error": "x", "error_code": "page_timeout"}, False))
    out = pipeline.process_page(str(path), 1)
    assert out["pass1"]["ok"] and out["second_pass"] == "failed" and out["error_code"] == "page_timeout"


# ---------- העלאה: ממשיכים לעמוד הבא, ההעלאה נשארת לא שלמה, והעלאה חוזרת ממשיכה ----------

class Bar:
    def progress(self, *a, **k):
        pass


def two_page_pdf():
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    return doc.tobytes()


def test_timeout_page_leaves_upload_incomplete_and_reupload_resumes(monkeypatch, tmp_path):
    monkeypatch.setattr(upload, "UPLOAD_TMP_DIR", tmp_path)
    conn = repo.connect(":memory:")
    data = two_page_pdf()
    seen = []

    def first_run(path, p):
        seen.append(p)
        if p == 1:
            return {"page": 1, "pass1": {"ok": False, "error_code": "page_timeout"}, "pass2": None, "error_code": "page_timeout"}
        return {"page": 2, "pass1": {"ok": False, "error": "x"}, "pass2": None}

    monkeypatch.setattr(pipeline, "process_page", first_run)
    store = service.Persister(conn, "f.pdf", data)
    pages, _, _ = upload.process_upload("f.pdf", data, Bar(), store=store)
    assert seen == [1, 2] and len(pages) == 2                            # העמוד השני עובד למרות החריגה בראשון
    assert store.incomplete_pages == [1]
    assert service.find_completed_upload(conn, data) is None             # לא שלם: העלאה חוזרת תעבד שוב

    monkeypatch.setattr(pipeline, "process_page", lambda path, p: {"page": p, "pass1": {"ok": False, "error": "x"}, "pass2": None})
    store2 = service.Persister(conn, "f.pdf", data)
    upload.process_upload("f.pdf", data, Bar(), store=store2)
    assert store2.upload_id == store.upload_id and not store2.incomplete_pages
    assert service.find_completed_upload(conn, data) is not None         # עכשיו שלם
    assert len(repo.list_uploads(conn)) == 1
