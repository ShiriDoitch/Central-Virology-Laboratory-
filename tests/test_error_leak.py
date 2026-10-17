"""טקסט חריגה או תגובת API לא מגיע למסך המשתמש: הודעה כללית במסך, הפרטים האמיתיים נרשמים רק למסוף השרת (stderr)."""
import io
import logging
import sys

import pytest

from src import upload
from src.export import skip_reason
from src.privacy import GENERIC_ERROR_HE, log_server_error

SECRET = "SECRET-PATIENT-ID-11223344 C:\\internal\\path.pdf"


@pytest.fixture
def server_log():
    """תופס את מה שנרשם ללוגר של השרת (ה-handler שלו כותב ל-stderr)."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("commitments")
    logger.addHandler(handler)
    yield stream
    logger.removeHandler(handler)


def test_skip_reason_does_not_show_the_api_error_text():
    page = {"pass1": {"ok": False, "error": f"ServerError: 503 UNAVAILABLE. {SECRET}"}}
    reason = skip_reason(page)
    assert reason and "SECRET" not in reason and "503" not in reason and "החילוץ נכשל" in reason


def test_log_server_error_dev_writes_full_text_to_the_server_log(server_log):
    try:
        raise RuntimeError(SECRET)
    except RuntimeError as e:
        log_server_error("process_upload", e)
    assert SECRET in server_log.getvalue()


def test_log_server_error_production_writes_only_the_exception_type(server_log, monkeypatch):
    monkeypatch.setenv("PRIVACY_MODE", "production")
    log_server_error("process_upload", RuntimeError(SECRET))
    log_server_error("extract page 1", SECRET)
    out = server_log.getvalue()
    assert "RuntimeError" in out and "SECRET" not in out


def test_log_goes_to_stderr_not_stdout(capsys):
    log_server_error("ctx", "boom")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_failed_page_is_logged_with_the_real_error_but_result_holds_only_the_type(monkeypatch, server_log):
    import pymupdf

    def boom(*_a, **_k):
        raise RuntimeError(SECRET)

    monkeypatch.setattr("src.pipeline.process_page", boom)
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()

    class P:
        def progress(self, *_a, **_k):
            pass

    pages, _images, _crops = upload.process_upload("form.pdf", data, P())
    assert pages[0]["pass1"] == {"ok": False, "error": "RuntimeError"}      # במסך ובאקסל: רק שם הסוג
    assert SECRET in server_log.getvalue()                                    # הפרטים בשרת בלבד


def test_page_limit_message_is_ours_and_safe_to_show():
    assert issubclass(upload.UploadRejected, ValueError)
    assert GENERIC_ERROR_HE == "העיבוד נכשל, נסי שוב או פני לתמיכה"
