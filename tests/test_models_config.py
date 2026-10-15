"""config/models.json: מעבר 1 flash-lite, מעבר 2 gemini-3.8-flash עם גיבוי flash-lite; הסלמה למודל חזק רק לפי ההגדרה, וחזרה שקטה כשהוא לא עונה."""
import json

from src import extractor
from src.schema import RegionsExtraction
from tests.conftest import set_models
from tests.test_retries import BUSY, FakeClient

OK = RegionsExtraction().model_dump_json()


def test_shipped_config_pass1_flash_lite_pass2_38_with_flash_lite_fallback_without_escalation():
    cfg = json.loads(extractor.MODELS_CONFIG_PATH.read_text(encoding="utf-8"))
    assert cfg["first_pass"] == "gemini-3.5-flash-lite" and cfg["second_pass"] == "gemini-3.8-flash"
    assert cfg["second_pass_fallback"] == "gemini-3.5-flash-lite" and cfg["escalate_to_strong"] is False
    assert extractor.model_chain()[0] == "gemini-3.5-flash-lite"
    assert extractor.region_model_chain() == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert "gemini-3.5-flash-lite" not in extractor.strong_model_list()


def test_missing_or_broken_config_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(extractor, "MODELS_CONFIG_PATH", tmp_path / "nope.json")
    assert extractor.region_model_chain() == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(extractor, "MODELS_CONFIG_PATH", tmp_path / "bad.json")
    assert extractor.model_chain()[0] == "gemini-3.5-flash-lite"


def test_escalation_chain_is_strong_models_then_default_last(monkeypatch):
    set_models(monkeypatch, second="lite", escalate=True, strong=["s1", "s2", "s3"])
    assert extractor.region_model_chain() == ["s1", "s2", "lite"]          # עד 3 מודלים; ברירת המחדל אחרונה


def test_no_escalation_ignores_strong_models(monkeypatch):
    set_models(monkeypatch, second="lite", escalate=False, strong=["s1"])
    assert extractor.region_model_chain() == ["lite"]


def test_strong_model_down_silently_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    set_models(monkeypatch, second="lite", escalate=True, strong=["s1"])
    client = FakeClient({"s1": [BUSY()], "lite": [OK]})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is True and result["model"] == "lite" and client.models.calls == ["s1", "lite"]


def test_everything_down_fails_cleanly_without_exception(monkeypatch):
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    set_models(monkeypatch, second="lite", escalate=True, strong=["s1"])
    client = FakeClient({"s1": [BUSY()], "lite": [BUSY()]})
    monkeypatch.setattr(extractor.genai, "Client", lambda **k: client)
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is False                      # השדה נשאר כתום לפי כללי הביטחון, בלי קריסה


def test_app_has_no_model_selection_widgets():
    src = open("app.py", encoding="utf-8").read()
    for word in ("selectbox(\"מודל", "model_chain", "checkbox", "הגדרות מתקדמות", "st.sidebar", "extractor"):
        assert word not in src, word
