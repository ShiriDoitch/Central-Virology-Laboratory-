from tests.conftest import legacy_strong, set_models
from src import cache

IMAGES = [b"fake-image-bytes"]


def fake_extract(model_name):
    calls = []

    def fn(images):
        calls.append(1)
        return {"ok": True, "model": model_name}

    fn.calls = calls
    return fn


def use_models(monkeypatch, tmp_path, primary, fallbacks=""):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    set_models(monkeypatch, first=primary, fallbacks=[f for f in fallbacks.split(",") if f])


def test_same_models_hit_cache(monkeypatch, tmp_path):
    use_models(monkeypatch, tmp_path, "lite")
    fn = fake_extract("lite")
    _, first = cache.cached_extract(IMAGES, fn)
    result, second = cache.cached_extract(IMAGES, fn)
    assert (first, second) == (False, True)
    assert result["model"] == "lite"
    assert len(fn.calls) == 1


def test_changing_primary_model_does_not_return_old_answer(monkeypatch, tmp_path):
    use_models(monkeypatch, tmp_path, "lite")
    cache.cached_extract(IMAGES, fake_extract("lite"))

    use_models(monkeypatch, tmp_path, "strong")
    strong = fake_extract("strong")
    result, from_cache = cache.cached_extract(IMAGES, strong)
    assert from_cache is False
    assert result["model"] == "strong"
    assert len(strong.calls) == 1


def test_changing_fallback_list_invalidates_cache(monkeypatch, tmp_path):
    use_models(monkeypatch, tmp_path, "strong", "lite")
    cache.cached_extract(IMAGES, fake_extract("strong"))
    use_models(monkeypatch, tmp_path, "strong", "other")
    _, from_cache = cache.cached_extract(IMAGES, fake_extract("strong"))
    assert from_cache is False


def test_failures_are_not_cached(monkeypatch, tmp_path):
    use_models(monkeypatch, tmp_path, "lite")
    cache.cached_extract(IMAGES, lambda images: {"ok": False, "error": "503"})
    fn = fake_extract("lite")
    _, from_cache = cache.cached_extract(IMAGES, fn)
    assert from_cache is False
    assert len(fn.calls) == 1
