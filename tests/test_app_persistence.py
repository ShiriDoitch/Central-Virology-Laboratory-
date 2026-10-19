"""app.py מול מסד נתונים אמיתי (קובץ זמני): תיקון ואישור נכתבים ל-DB, שורה מאושרת נעולה. בלי API; נשען על הריצה השמורה."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import repo, service

APP = str(Path(__file__).resolve().parent.parent / "app.py")
RUN = Path("outputs/clean_part1_v4b")
pytestmark = pytest.mark.skipif(not RUN.exists(), reason="needs the saved sample run")


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("APP_DB_PATH", str(db))
    pages = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(RUN.glob("p*.json"), key=lambda x: int(x.stem[1:]))]
    conn = repo.connect(db)
    store = service.Persister(conn, "f.pdf", b"bytes")
    store.start(len(pages))
    for p in pages:
        store.page(p)
    store.finish()
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["pages"], at.session_state["images"], at.session_state["field_crops"] = pages, {}, {}
    at.session_state["is_sample"], at.session_state["upload_id"], at.session_state["name_overrides"] = False, store.upload_id, {}
    return at, conn, store.upload_id, pages


def select(at, pages, page, column):
    from tests.test_app_confirm import row_of
    at.session_state["selected_cell"] = (row_of(page), column)
    at.run()
    assert not at.exception


def button(at, key):
    return next(b for b in at.button if b.key == key)


def test_typed_value_is_written_to_db_and_cleared(app):
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    at.text_input(key="txt_1_first_name").set_value("ישראל").run()
    button(at, "ok_1_first_name").click().run()
    rid = repo.find_record(conn, uid, 1, 0)
    rec = repo.get_record(conn, rid)
    assert rec["first_name"] == "ישראל" and rec["fields"]["first_name"]["human_edited"]
    assert repo.audit_entries(conn, rid)[-1]["action"] == "edit"
    button(at, "clr_1_first_name").click().run()
    assert repo.get_record(conn, rid)["fields"]["first_name"]["cell_confirmed"] is False


def test_invalid_value_not_written(app):
    at, conn, uid, pages = app
    select(at, pages, 1, 'ת"ז')
    at.text_input(key="txt_1_id").set_value("abc").run()
    button(at, "ok_1_id").click().run()
    assert at.session_state["name_overrides"] == {}
    assert not repo.get_record(conn, repo.find_record(conn, uid, 1, 0))["fields"]["id"]["cell_confirmed"]


def test_approve_locks_row_and_blocks_edit(app):
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    next(b for b in at.button if b.key == f"appr_{rid}").click().run()
    assert repo.get_record(conn, rid)["status"] == "approved"
    assert button(at, "ok_1_first_name").disabled
    assert any("נעולה" in w.value for w in at.warning)
    button(at, f"unappr_{rid}").click().run()
    assert repo.get_record(conn, rid)["status"] in ("pending", "ready")
    assert not button(at, "ok_1_first_name").disabled


def test_sample_mode_does_not_touch_db(tmp_path, monkeypatch):
    db = tmp_path / "s.db"
    monkeypatch.setenv("APP_DB_PATH", str(db))
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    next(b for b in at.button if b.label.startswith("טען")).click().run()
    assert not at.exception and not db.exists()


def test_confirm_button_locks_when_value_equals_saved_and_unlocks_on_change(app):
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    assert button(at, "ok_1_first_name").label == "אשרי את הערך שהוקלד"
    at.text_input(key="txt_1_first_name").set_value("ישראל").run()
    assert not button(at, "ok_1_first_name").disabled
    button(at, "ok_1_first_name").click().run()
    assert button(at, "ok_1_first_name").disabled and button(at, "ok_1_first_name").label == "הערך אושר"
    version, n = repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))
    at.run()                                                                   # rerun: המצב נגזר מהרשומה השמורה
    assert button(at, "ok_1_first_name").disabled
    at.text_input(key="txt_1_first_name").set_value("ישראלה").run()
    assert not button(at, "ok_1_first_name").disabled and button(at, "ok_1_first_name").label == "אשרי את הערך שהוקלד"
    at.text_input(key="txt_1_first_name").set_value(" ישראל ").run()           # חזרה לערך השמור (אחרי נרמול): נעול שוב
    assert button(at, "ok_1_first_name").disabled
    assert (repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))) == (version, n)


def test_lock_follows_db_not_session(app):
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    repo.edit_field(conn, rid, "first_name", "דנה")                            # אושר ממקום אחר (מסך הרשומות)
    at.text_input(key="txt_1_first_name").set_value("דנה").run()
    assert button(at, "ok_1_first_name").disabled
    repo.revert_field(conn, rid, "first_name")
    at.run()
    assert not button(at, "ok_1_first_name").disabled


def test_double_submit_of_same_value_writes_once(app):
    """לחיצה שנייה (ששודרה לפני שהכפתור ננעל): לא מוסיפה audit, לא מגדילה גרסה ולא מציגה שגיאה."""
    from src import service
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    at.text_input(key="txt_1_first_name").set_value("ישראל").run()
    button(at, "ok_1_first_name").click().run()
    v, n = repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))
    service.save_override(conn, uid, 1, "first_name", "ישראל", pages[0])
    service.save_override(conn, uid, 1, "first_name", "ישראל", pages[0])
    assert (repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))) == (v, n)
    assert not at.error
