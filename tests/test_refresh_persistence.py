"""רענון הדפדפן אינו מאבד את מסך העיבוד: לכל ריצה יש אסימון שנשמר ב-URL, והמסך נבנה מחדש מהמסד
(תוצאות העמודים, האישורים ותמונות העמודים). בלי קריאות API: הזריעה היא דרך service.Persister על הריצה השמורה.

מה שנבדק כאן: אותן שורות אחרי "סשן חדש" עם אותו אסימון; בלי אסימון, אסימון שגוי ואסימון של ריצה אחרת
מתחילים ריק ובלי שגיאה (לעולם לא נתונים של מישהו אחר)."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import page_store, repo, service

APP = str(Path(__file__).resolve().parent.parent / "app.py")
RUN = Path("outputs/clean_part1_v4b")
pytestmark = pytest.mark.skipif(not RUN.exists(), reason="needs the saved sample run")
EMPTY_STATE = "אין עדיין תוצאות"


def saved_pages(limit: int = 3) -> list[dict]:
    files = sorted(RUN.glob("p*.json"), key=lambda x: int(x.stem[1:]))[:limit]
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "r.db"))
    return repo.connect(tmp_path / "r.db")


def process(conn, pages, filename="a.pdf", sha=b"bytes-a") -> service.Persister:
    """מה ש-src/upload.process_upload עושה מול המסד, בלי קריאות למודל: ריצה חדשה ושמירת כל עמוד."""
    store = service.Persister(conn, filename, sha)
    store.start(len(pages))
    for page in pages:
        store.page(page)
    store.finish()
    return store


def app(token: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    if token is not None:
        at.query_params["run"] = token
    at.run()
    assert not at.exception, at.exception
    return at


def session_app(pages, upload_id) -> AppTest:
    """אותו מסך כמו בסוף העיבוד (לפני רענון): התוצאות בזיכרון הסשן."""
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["pages"], at.session_state["images"], at.session_state["field_crops"] = pages, {}, {}
    at.session_state["is_sample"], at.session_state["upload_id"] = False, upload_id
    at.session_state["name_overrides"] = {}
    at.run()
    assert not at.exception, at.exception
    return at


def texts(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown if not m.value.startswith("<style>"))


# ---------- אותו מסך אחרי רענון ----------

def test_a_refresh_with_the_run_token_shows_the_same_rows(db):
    pages = saved_pages()
    store = process(db, pages)
    before = session_app(pages, store.upload_id).dataframe[0].value       # המסך שהיה פתוח
    at = app(store.token)                                                 # סשן חדש (רענון), אותו אסימון
    assert at.dataframe[0].value.equals(before)
    assert EMPTY_STATE not in texts(at)
    assert [p["page"] for p in at.session_state["pages"]] == [p["page"] for p in pages]
    assert at.session_state["upload_id"] == store.upload_id and at.session_state["is_sample"] is False
    assert at.query_params["run"] == store.token                          # הקישור נשאר תקף לרענון הבא


def test_without_a_token_the_screen_starts_empty(db):
    process(db, saved_pages())                                            # יש נתונים במסד, אבל אין אסימון בקישור
    at = app()
    assert EMPTY_STATE in texts(at) and at.dataframe == []
    assert not at.session_state.get("pages")


def test_an_unknown_token_starts_empty_without_an_error(db):
    process(db, saved_pages())
    for bad in ("", "deadbeef", "0" * 32, "../../etc/passwd", "1"):
        at = app(bad)
        assert not at.exception, (bad, at.exception)
        assert at.error == [] and at.dataframe == []
        assert EMPTY_STATE in texts(at), bad


def test_a_token_of_another_run_never_shows_this_run(db):
    """שני קבצים שעובדו, שני אסימונים: כל אסימון מחזיר את הריצה שלו בלבד."""
    a = process(db, saved_pages(2), "a.pdf", b"bytes-a")
    b = process(db, saved_pages(3)[2:], "b.pdf", b"bytes-b")
    assert a.token != b.token and a.upload_id != b.upload_id
    at_a, at_b = app(a.token), app(b.token)
    assert [p["page"] for p in at_a.session_state["pages"]] == [1, 2]
    assert [p["page"] for p in at_b.session_state["pages"]] == [3]
    assert len(at_a.dataframe[0].value) > len(at_b.dataframe[0].value)


def test_every_run_gets_its_own_unguessable_token(db):
    pages = saved_pages(1)
    first, second = process(db, pages), process(db, pages)                 # אותו קובץ, שתי ריצות
    assert first.upload_id == second.upload_id                             # אותה העלאה (אותו sha256)
    assert first.token != second.token
    for token in (first.token, second.token):
        assert len(token) == 32 and all(c in "0123456789abcdef" for c in token)
    assert sorted(repo.runs_of_upload(db, first.upload_id)) == sorted([first.token, second.token])


def test_user_confirmations_come_back_after_a_refresh(db):
    pages = saved_pages(1)
    store = process(db, pages)
    rid = repo.find_record(db, store.upload_id, 1, 0)
    repo.edit_field(db, rid, "first_name", "אברהם")                        # תיקון שנשמר לפני הרענון
    at = app(store.token)
    assert at.session_state["name_overrides"][(1, "first_name")] == "אברהם"
    assert "אברהם" in str(at.dataframe[0].value.to_dict())


def test_page_images_and_crops_come_back_after_a_refresh(db):
    pages = saved_pages(1)
    store = process(db, pages)
    image = b"\xff\xd8\xff" + b"0" * 64                                    # לא JPEG תקין: החיתוך נכשל בשקט
    page_store.write(store.upload_id, 1, image)
    repo.save_page_regions(db, store.upload_id, 1, {"id": {"fr": [0.1, 0.2, 0.6, 0.3], "verified": True}})
    run = service.load_run(db, store.token)
    assert run["images"] == {1: image} and (1, "id") in run["field_crops"]
    crop, verified = run["field_crops"][(1, "id")]
    assert crop is None and verified is True                              # התמונה לא JPEG תקין: החיתוך נכשל, המאומד נשאר
    at = app(store.token)
    assert not at.exception and at.session_state["images"] == {1: image}


def test_a_run_whose_data_was_deleted_starts_empty(db):
    store = process(db, saved_pages(1))
    service.delete_all_data(db)
    assert service.load_run(db, store.token) is None
    at = app(store.token)
    assert not at.exception and EMPTY_STATE in texts(at)


def test_the_sample_clears_a_stale_token_from_the_url(db):
    """הדוגמה אינה ריצה שמורה: אחרי טעינתה לא נשאר בקישור אסימון של ריצה אחרת."""
    store = process(db, saved_pages(1))
    at = app(store.token)
    next(b for b in at.button if "דוגמה" in b.label).click().run()
    assert not at.exception and "run" not in at.query_params


def test_load_run_is_the_only_way_in_and_needs_no_session(db):
    """בדיקת השכבה עצמה: אסימון -> תוצאות העמודים והאישורים, בלי Streamlit ובלי session_state."""
    store = process(db, saved_pages(2))
    run = service.load_run(db, store.token)
    assert [p["page"] for p in run["pages"]] == [1, 2] and run["upload_id"] == store.upload_id
    assert service.load_run(db, None) is None and service.load_run(db, "x" * 32) is None
    assert repo.page_results(db, store.upload_id) == run["pages"]
