"""ספק Anthropic (ניסוי) מאחורי אותו ממשק: ברירת מחדל Gemini, מטמון נפרד, תקרת תקציב, כישלון בלי קריסה."""
import json
from types import SimpleNamespace

import pytest

from src import cache, extractor
from src.schema import RegionsExtraction


def set_cfg(monkeypatch, **extra):
    cfg = dict(extractor.DEFAULT_MODELS_CONFIG)
    cfg.update(extra)
    monkeypatch.setattr(extractor, "load_models_config", lambda: dict(cfg))


def test_default_provider_is_gemini(monkeypatch):
    monkeypatch.delenv("EXTRACT_PROVIDER", raising=False)
    assert json.loads(extractor.MODELS_CONFIG_PATH.read_text(encoding="utf-8"))["provider"] == "gemini"
    assert extractor.provider() == "gemini"
    assert extractor.model_chain()[0].startswith("gemini")


def test_env_and_config_select_anthropic(monkeypatch):
    monkeypatch.delenv("EXTRACT_PROVIDER", raising=False)
    set_cfg(monkeypatch, provider="anthropic")
    assert extractor.provider() == "anthropic"
    assert extractor.model_chain() == ["claude-sonnet-5-5"] == extractor.region_model_chain()
    set_cfg(monkeypatch)
    monkeypatch.setenv("EXTRACT_PROVIDER", "anthropic")
    assert extractor.provider() == "anthropic"
    monkeypatch.setenv("EXTRACT_PROVIDER", "nonsense")
    assert extractor.provider() == "gemini"


def test_anthropic_cache_is_a_separate_namespace(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.delenv("EXTRACT_PROVIDER", raising=False)
    assert cache._dir() == tmp_path / "cache"
    monkeypatch.setenv("EXTRACT_PROVIDER", "anthropic")
    assert cache._dir() == tmp_path / "cache" / "anthropic"
    cache.store_result("k", {"ok": True})
    assert (tmp_path / "cache" / "anthropic" / "k.json").exists() and not (tmp_path / "cache" / "k.json").exists()


class FakeMessages:
    def __init__(self, texts, calls):
        self.texts, self.calls = list(texts), calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.texts.pop(0)
        if isinstance(text, Exception):
            raise text
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


def fake_client(monkeypatch, texts):
    import anthropic
    calls: list = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **k: SimpleNamespace(messages=FakeMessages(texts, calls)))
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    return calls


def test_anthropic_extract_regions_ok_and_counts_usage(monkeypatch):
    monkeypatch.setenv("EXTRACT_PROVIDER", "anthropic")
    set_cfg(monkeypatch)
    extractor.SPEND.reset(2.0)
    calls = fake_client(monkeypatch, ['{"patient": {"region_ok": true}}'])
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] and result["model"] == "claude-sonnet-5-5" and result["patient"]["region_ok"] is True
    assert result["stats"]["input_tokens"] == 1000 and result["stats"]["api_calls"] == 1
    assert extractor.SPEND.usd == pytest.approx((1000 * 2 + 500 * 10) / 1e6)
    block_types = [b["type"] for b in calls[0]["messages"][0]["content"]]
    assert block_types == ["text", "image", "text", "image", "text"]           # Image 1:, תמונה, Image 2:, תמונה, ההנחיה
    assert "output_config" in calls[0]


def test_anthropic_broken_json_fails_cleanly_in_pass2(monkeypatch):
    monkeypatch.setenv("EXTRACT_PROVIDER", "anthropic")
    set_cfg(monkeypatch)
    extractor.SPEND.reset(2.0)
    fake_client(monkeypatch, ["not json"])
    result = extractor.extract_regions({"patient": b"a", "barcode": b"b"})
    assert result["ok"] is False and result["stats"]["api_calls"] == 1


def test_anthropic_transient_error_is_retried_and_counted(monkeypatch):
    import anthropic
    monkeypatch.setenv("EXTRACT_PROVIDER", "anthropic")
    set_cfg(monkeypatch)
    extractor.SPEND.reset(2.0)
    err = anthropic.APIConnectionError(request=SimpleNamespace())
    fake_client(monkeypatch, [err, "{}"])
    result = extractor._run_anthropic(["x"], RegionsExtraction, None, None)
    assert result["ok"] and result["stats"]["api_calls"] == 2 and result["stats"]["other_errors"] == 1


def test_budget_guard_stops_before_sending(monkeypatch):
    monkeypatch.setenv("EXTRACT_PROVIDER", "anthropic")
    set_cfg(monkeypatch)
    extractor.SPEND.reset(0.001)
    calls = fake_client(monkeypatch, ["{}", "{}"])
    first = extractor._run_anthropic(["x"], RegionsExtraction, None, None)
    assert first["ok"]                                      # הבקשה הראשונה עברה את התקרה בעלותה
    second = extractor._run_anthropic(["x"], RegionsExtraction, None, None)
    assert second["ok"] is False and second["budget_exceeded"] is True and len(calls) == 1
    extractor.SPEND.reset()
