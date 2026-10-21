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


def clear_pending(at, er):
    """ממלא את האישורים בסשן לכל תא כתום בשורה (כמו משתמשת שאישרה אותם), כדי שכפתור "אישור שורה" ייפתח:
    הוא נעול כל עוד נשאר בשורה שדה כתום שיש בו ערך (app.pending_fields)."""
    from src.confirm import override_key
    overrides = at.session_state["name_overrides"] or {}
    at.session_state["name_overrides"] = overrides
    for key, cell in er.cells.items():
        if cell.orange and cell.value:
            overrides[(er.page, override_key(key, er.index))] = cell.value


def row_of_page(pages, page):
    from src.export import build_rows
    return build_rows(next(p for p in pages if p["page"] == page))[0]


def select(at, pages, page, column):
    from tests.test_app_confirm import row_of
    at.session_state["selected_cell"] = (row_of(page), column)
    at.run()
    assert not at.exception


def button(at, key):
    return next(b for b in at.button if b.key == key)


def test_typed_value_is_written_to_db_and_cleared(app):
    """ערך שהוקלד ושונה מהצעת המכונה נרשם כעריכה. (ערך זהה להצעה נרשם כאישור; ראו repo.edit_field,
    וזה המצב מאז שהקריאה בכתב יד מוצגת בתא ככתום.)"""
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    at.text_input(key="txt_1_first_name").set_value("דנה")
    button(at, "ok_1_first_name").click().run()                                # Enter בטופס = אותו נתיב
    rid = repo.find_record(conn, uid, 1, 0)
    rec = repo.get_record(conn, rid)
    assert rec["first_name"] == "דנה" and rec["fields"]["first_name"]["human_edited"]
    assert repo.audit_entries(conn, rid)[-1]["action"] == "edit"
    button(at, "clr_1_first_name").click().run()
    assert repo.get_record(conn, rid)["fields"]["first_name"]["cell_confirmed"] is False


def test_invalid_value_not_written(app):
    at, conn, uid, pages = app
    select(at, pages, 1, 'ת"ז')
    at.text_input(key="txt_1_id").set_value("abc")
    button(at, "ok_1_id").click().run()
    assert at.session_state["name_overrides"] == {}
    assert not repo.get_record(conn, repo.find_record(conn, uid, 1, 0))["fields"]["id"]["cell_confirmed"]


def test_approve_locks_row_and_blocks_edit(app):
    at, conn, uid, pages = app
    clear_pending(at, row_of_page(pages, 1))                                   # אחרת כפתור האישור נעול
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
    next(b for b in at.button if "דוגמה" in b.label).click().run()
    assert not at.exception and not db.exists()


def test_confirm_button_says_when_the_typed_value_is_already_saved(app):
    """ההקלדה בטופס מגיעה לשרת רק עם השליחה, ולכן הכפתור אינו נעול לפי מה שמוקלד (אחרת אי אפשר היה
    להחליף ערך: Enter על כפתור נעול לא שולח כלום). הוא אומר אם הערך שבשדה כבר אושר, ואישור חוזר של
    אותו ערך אינו כותב דבר."""
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    assert button(at, "ok_1_first_name").label == "אישור הערך שהוקלד"
    at.text_input(key="txt_1_first_name").set_value("ישראל")
    button(at, "ok_1_first_name").click().run()
    assert repo.get_record(conn, rid)["first_name"] == "ישראל"
    assert button(at, "ok_1_first_name").label == "הערך אושר" and not button(at, "ok_1_first_name").disabled
    version, n = repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))
    button(at, "ok_1_first_name").click().run()                                # שליחה חוזרת של אותו ערך
    assert (repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))) == (version, n)
    at.text_input(key="txt_1_first_name").set_value("ישראלה")                  # ערך אחר: נשמר, גם אחרי "הערך אושר"
    button(at, "ok_1_first_name").click().run()
    assert repo.get_record(conn, rid)["first_name"] == "ישראלה"


def test_confirm_label_follows_db_not_session(app):
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    repo.edit_field(conn, rid, "first_name", "דנה")                            # אושר ממקום אחר (מסך הרשומות)
    at.text_input(key="txt_1_first_name").set_value("דנה")
    button(at, "ok_1_first_name").click().run()
    assert button(at, "ok_1_first_name").label == "הערך אושר"
    repo.revert_field(conn, rid, "first_name")                                 # בוטל ממקום אחר
    at.run()
    assert button(at, "ok_1_first_name").label == "אישור הערך שהוקלד"


def test_double_submit_of_same_value_writes_once(app):
    """לחיצה שנייה (ששודרה לפני שהכפתור ננעל): לא מוסיפה audit, לא מגדילה גרסה ולא מציגה שגיאה."""
    from src import service
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    at.text_input(key="txt_1_first_name").set_value("ישראל")
    button(at, "ok_1_first_name").click().run()
    v, n = repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))
    service.save_override(conn, uid, 1, "first_name", "ישראל", pages[0])
    service.save_override(conn, uid, 1, "first_name", "ישראל", pages[0])
    assert (repo.get_record(conn, rid)["version"], len(repo.audit_entries(conn, rid))) == (v, n)
    assert not at.error
