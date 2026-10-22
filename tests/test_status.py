"""שורת הסטטוס: בטוחה לפרטיות (קודים ומספרים מרשימה סגורה בלבד), מופיעה בשורת ההתקדמות וגם בלוג השרת. בלי בקשות אמיתיות."""
import logging

import httpx
import pymupdf
import pytest
from google.genai import errors

from src import extractor, pipeline, status, upload
from src.quota import DEFAULT_CONFIG, QuotaTracker
from tests.conftest import set_models
from tests.test_page_budget import Bar, Clock, fake_time, hanging, two_page_pdf  # noqa: F401  (fixtures)
from tests.test_resilience import OK_JSON, gemini  # noqa: F401


class Collect:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)

    @property
    def texts(self):
        return [e["text"] for e in self.events]


@pytest.fixture
def server_log():
    records = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    log = logging.getLogger("commitments")
    h = H()
    log.addHandler(h)
    yield records
    log.removeHandler(h)


def test_unknown_kinds_and_fields_are_dropped_so_no_free_text_gets_through(server_log):
    c = Collect()
    with status.listening(c):
        status.emit("not_a_kind", note="דנה כהן 123456789")
        status.emit("model_call", attempt=2, of=4, error="ת.ז 123456789", filename="secret.pdf", name="דנה", patient=["x"])
        status.emit("stage", stage="דנה כהן")                     # שלב שאינו ברשימה
        status.emit("quota_wait", wait_s="20; DROP", extra=True)  # מחרוזת במקום מספר
        status.emit("retry_wait", wait_s=True, attempt=1, of=4)   # bool אינו מספר
    assert c.texts == ["ממתין למודל (ניסיון 2 מתוך 4)", "ממתין למכסה (כ-? שניות)", "המודל עמוס, מנסה שוב בעוד כ-? שניות (ניסיון 1 מתוך 4)"]
    blob = " ".join(c.texts + server_log)
    for forbidden in ("דנה", "123456789", "secret", "DROP", "ת.ז"):
        assert forbidden not in blob


def test_texts_and_server_log_match(server_log):
    c = Collect()
    with status.listening(c):
        status.emit("quota_wait", wait_s=20)
        status.emit("stage", stage="pass2")
        status.emit("claude_fallback")
    assert c.texts == ["ממתין למכסה (כ-20 שניות)", "קורא אזורים מוגדלים", "עובר לגיבוי אחרון"]
    assert server_log == c.texts


def test_listener_errors_never_break_processing():
    def boom(event):
        raise RuntimeError("ui gone")

    with status.listening(boom):
        status.emit("model_switch")                              # לא זורק


def test_no_listener_still_logs(server_log):
    status.emit("key_switch")
    assert server_log == ["עובר למפתח גיבוי"]


def test_first_pass_reports_one_attempt_per_model_then_switches(gemini, monkeypatch):
    """מעבר ראשון (22.10.2026): ניסיון אחד למודל, בלי המתנה על אותו מודל, ואז מיד המודל הבא."""
    set_models(monkeypatch, first="m1", fallbacks=["m2"])
    busy = lambda: errors.ServerError(503, {"error": {"message": "busy patient-123"}})
    gemini(["a"], {"a": [busy(), OK_JSON]})
    sleeps: list[float] = []
    monkeypatch.setattr(extractor.time, "sleep", sleeps.append)
    c = Collect()
    with status.listening(c):
        res = extractor.extract([b"img"])
    assert res["ok"] and res["model"] == "m2"
    texts = [t for t in c.texts if "מכסה" not in t]                 # מרווח המכסה בין קריאות נבדק בנפרד (test_quota_interval_wait_is_reported)
    assert texts == ["ממתין למודל (ניסיון 1 מתוך 1)", "עובר למודל גיבוי", "ממתין למודל (ניסיון 1 מתוך 1)"]
    assert sleeps == []                                             # בלי המתנה כלשהי בין הניסיון הכושל למודל הבא
    assert "patient-123" not in " ".join(c.texts)


def test_minute_quota_429_moves_on_without_waiting(gemini, monkeypatch):
    """מעבר ראשון (22.10.2026): גם 429 של מגבלת דקה לא ממתין יותר - עובר מיד למודל/מפתח הבא (אין עוד מה להמתין בשביל)."""
    set_models(monkeypatch, first="m1", fallbacks=["m2"])
    minute = lambda: errors.ClientError(429, {"error": {"message": "GenerateRequestsPerMinutePerProjectPerModel"}})
    gemini(["a"], {"a": [minute(), OK_JSON]})
    sleeps: list[float] = []
    monkeypatch.setattr(extractor.time, "sleep", sleeps.append)
    c = Collect()
    with status.listening(c):
        res = extractor.extract([b"img"])
    assert res["ok"] and res["model"] == "m2"
    assert "ממתין למכסה (כ-60 שניות)" not in c.texts
    assert extractor.QUOTA_WAIT_S not in sleeps


def test_key_and_model_switch_events(gemini, monkeypatch):
    set_models(monkeypatch, first="m1", fallbacks=["m2"])
    daily = lambda: errors.ClientError(429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel"}})
    gemini(["a", "b"], {"a": [daily(), daily()], "b": [OK_JSON]})
    c = Collect()
    with status.listening(c):
        assert extractor.extract([b"img"])["ok"]
    assert "עובר למודל גיבוי" in c.texts and "עובר למפתח גיבוי" in c.texts


def test_quota_interval_wait_is_reported():
    t = {"now": 1000.0}
    tracker = QuotaTracker(path=None or __import__("pathlib").Path("unused"), config=DEFAULT_CONFIG, now=lambda: t["now"],
                           sleep=lambda s: t.__setitem__("now", t["now"] + s), today=lambda: "2026-10-14")
    tracker._load = lambda: {"day": "2026-10-14", "models": {}, "last_call": {"small": 1000.0}}
    tracker._save = lambda state: None
    c = Collect()
    with status.listening(c):
        tracker.before_call("small-model")
    assert c.texts == ["ממתין למכסה (כ-5 שניות)"]


def test_pipeline_reports_stages_in_order(monkeypatch, tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "p.pdf"
    doc.save(str(path))
    r1 = {"ok": True, "is_commitment_form": True, "page_quality": "ok", "model": "m"}
    monkeypatch.setattr(pipeline, "cached_extract", lambda images: (r1, True))
    monkeypatch.setattr(pipeline, "needs_second_pass", lambda page: (True, ["x"]))
    monkeypatch.setattr(pipeline, "cached_regions", lambda crops: ({"ok": False, "error": "x"}, True))
    c = Collect()
    with status.listening(c):
        pipeline.process_page(str(path), 1)
    assert c.texts == ["קורא את העמוד", "קורא אזורים מוגדלים"]


def test_process_upload_drives_the_progress_bar_without_leaking_file_name(monkeypatch, tmp_path, server_log):
    monkeypatch.setattr(upload, "UPLOAD_TMP_DIR", tmp_path)
    shown = []

    class RecordingBar:
        def progress(self, value, text=None):
            shown.append(text)

    def fake_page(path, p):
        status.emit("model_call", attempt=2, of=4)
        status.emit("quota_wait", wait_s=20)
        return {"page": p, "pass1": {"ok": False, "error": "x"}, "pass2": None}

    monkeypatch.setattr(pipeline, "process_page", fake_page)
    upload.process_upload("דנה-כהן-123456789.pdf", two_page_pdf(), RecordingBar())
    assert "עמוד 1 מתוך 2 · ממתין למודל (ניסיון 2 מתוך 4)" in shown
    assert "עמוד 2 מתוך 2 · ממתין למכסה (כ-20 שניות)" in shown
    assert not [t for t in shown + server_log if t and ("דנה" in t or "123456789" in t or ".pdf" in t)]


def test_process_upload_custom_status_callback(monkeypatch, tmp_path):
    monkeypatch.setattr(upload, "UPLOAD_TMP_DIR", tmp_path)
    got = []
    monkeypatch.setattr(pipeline, "process_page",
                        lambda path, p: (status.emit("claude_fallback"), {"page": p, "pass1": {"ok": False}, "pass2": None})[1])
    upload.process_upload("f.pdf", two_page_pdf(), Bar(), on_status=lambda p, total, text: got.append((p, total, text)))
    assert (1, 2, "מעבד עמוד 1 מתוך 2") in got and (2, 2, "עובר לגיבוי אחרון") in got
