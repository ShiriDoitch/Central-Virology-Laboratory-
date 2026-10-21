"""413 / 400 INVALID_ARGUMENT: לא חוזרים עליהן בכל מודל ומפתח. ניסיון אחד נוסף עם תמונה מוקטנת, ואם אין מה להקטין: נכשל מיד עם error_code.
בלי בקשה אמיתית (לקוחות Gemini מדומים)."""
import io

from google.genai import errors
from PIL import Image

from src import extractor
from tests.conftest import set_models
from tests.test_resilience import BAD_400, OK_JSON, claude, gemini  # noqa: F401  (fixtures)

TOO_BIG_413 = lambda: errors.ClientError(413, {"error": {"message": "Request payload size exceeds the limit", "status": "FAILED_PRECONDITION"}})
INVALID_400 = lambda: errors.ClientError(400, {"error": {"message": "bad", "status": "INVALID_ARGUMENT"}})


def jpeg(width, height):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "JPEG")
    return buf.getvalue()


def capture_image_sizes(monkeypatch):
    sizes = []
    real = extractor._image_part

    def spy(data):
        sizes.append(Image.open(io.BytesIO(data)).size if data[:2] == b"\xff\xd8" else None)
        return real(data)

    monkeypatch.setattr(extractor, "_image_part", spy)
    return sizes


def test_413_retries_once_with_a_smaller_image_and_succeeds(gemini, monkeypatch):
    set_models(monkeypatch, first="m1", fallbacks=["m2"])
    log = gemini(["a", "b"], {"a": [TOO_BIG_413(), OK_JSON], "b": [OK_JSON]})
    sizes = capture_image_sizes(monkeypatch)
    res = extractor.extract([jpeg(3000, 2000)])
    assert res["ok"] and res["downscaled_retry"] is True
    assert log == ["a", "a"]                                    # לא מודל נוסף ולא מפתח נוסף
    assert sizes == [(3000, 2000), (1600, 1067)]
    assert res["stats"]["api_calls"] == 2


def test_413_twice_fails_fast_with_code_and_no_key_rotation_or_claude(gemini, claude, monkeypatch):
    set_models(monkeypatch, first="m1", fallbacks=["m2", "m3"])
    log = gemini(["a", "b"], {"a": [TOO_BIG_413(), TOO_BIG_413()], "b": [OK_JSON]})
    res = extractor.extract([jpeg(3000, 2000)])
    assert not res["ok"] and res["error_code"] == "payload_too_large"
    assert log == ["a", "a"] and claude == []
    assert res["stats"]["api_calls"] == 2                       # בלי 4 ניסיונות לכל מודל


def test_400_with_nothing_to_shrink_fails_after_a_single_call(gemini, claude, monkeypatch):
    set_models(monkeypatch, first="m1", fallbacks=["m2"])
    log = gemini(["a", "b"], {"a": [INVALID_400()], "b": [OK_JSON]})
    res = extractor.extract([jpeg(800, 600)])                   # כבר קטן מ-1600: אין מה להקטין
    assert not res["ok"] and res["error_code"] == "invalid_payload"
    assert log == ["a"] and claude == [] and "downscaled_retry" not in res


def test_400_on_garbage_image_bytes_does_not_crash(gemini, monkeypatch):
    set_models(monkeypatch, first="m1")
    log = gemini(["a"], {"a": [BAD_400()]})
    res = extractor.extract([b"not a jpeg"])
    assert not res["ok"] and res["error_code"] == "invalid_payload" and log == ["a"]


def test_400_then_success_on_the_downscaled_image(gemini, monkeypatch):
    set_models(monkeypatch, first="m1")
    log = gemini(["a"], {"a": [INVALID_400(), OK_JSON]})
    res = extractor.extract([jpeg(2500, 2500)])
    assert res["ok"] and res["downscaled_retry"] and log == ["a", "a"]


def test_other_failures_do_not_trigger_the_downscale_retry(gemini, monkeypatch):
    set_models(monkeypatch, first="m1")
    log = gemini(["a"], {"a": [errors.ClientError(403, {"error": {"message": "x"}})]})
    res = extractor.extract([jpeg(3000, 2000)])
    assert not res["ok"] and "downscaled_retry" not in res and log == ["a"]


def test_regions_payload_error_stops_the_model_chain(gemini, monkeypatch):
    set_models(monkeypatch, second="s1")
    monkeypatch.setattr(extractor, "region_model_chain", lambda: ["s1", "s2"])
    log = gemini(["a"], {"a": [INVALID_400(), OK_JSON]})
    res = extractor.extract_regions({"patient": jpeg(50, 50), "barcode": jpeg(50, 50)})
    assert not res["ok"] and res["error_code"] == "invalid_payload" and log == ["a"]


def test_page_level_error_code_and_clear_reason():
    from src.export import skip_reason
    from src import pipeline
    assert "גדולה מדי" in skip_reason({"pass1": {"ok": False, "error_code": "payload_too_large"}})
    assert "יש להעלות שוב" in skip_reason({"pass1": {"ok": False, "error_code": "page_timeout"}})
    assert "פרטים במסוף" in skip_reason({"pass1": {"ok": False, "error": "x"}})
