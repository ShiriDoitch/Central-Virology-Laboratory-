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
    וזה המצב מאז שהקריאה בכתב יד מוצגת בתא ככתום.) אישור מזניק אוטומטית לתא הבא שדורש בדיקה, ולכן חוזרים
    לבחור את השדה הזה במפורש לפני שממשיכים לבטל את האישור שלו."""
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    at.text_input(key="txt_1_first_name").set_value("דנה")
    button(at, "ok_1_first_name").click().run()                                # Enter בטופס = אותו נתיב
    rid = repo.find_record(conn, uid, 1, 0)
    rec = repo.get_record(conn, rid)
    assert rec["first_name"] == "דנה" and rec["fields"]["first_name"]["human_edited"]
    assert repo.audit_entries(conn, rid)[-1]["action"] == "edit"
    select(at, pages, 1, "שם פרטי")
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


def test_confirmed_value_shows_as_a_status_line_not_a_button(app):
    """אחרי אישור: שורת סטטוס ("✓ אושר: ...") וכפתור "ביטול אישור" בלבד, בלי כפתור-שהוא-תג ("הערך אושר").
    ביטול ואז הקלדת ערך אחר כותבים ערך חדש כרגיל (אין יותר אפשרות לשלוח ערך אחר בלי לבטל קודם)."""
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    assert button(at, "ok_1_first_name").label == "אישור הערך שהוקלד"
    at.text_input(key="txt_1_first_name").set_value("ישראל")
    button(at, "ok_1_first_name").click().run()
    assert repo.get_record(conn, rid)["first_name"] == "ישראל"
    select(at, pages, 1, "שם פרטי")                      # האישור הזניק לתא הבא; חוזרים לבדוק את השדה הזה
    assert any("✓ אושר: ישראל" in m.value for m in at.markdown)
    assert not [b for b in at.button if b.key == "ok_1_first_name"]
    button(at, "clr_1_first_name").click().run()
    at.text_input(key="txt_1_first_name").set_value("ישראלה")                  # ביטול, ואז ערך אחר: נשמר כרגיל
    button(at, "ok_1_first_name").click().run()
    assert repo.get_record(conn, rid)["first_name"] == "ישראלה"


def test_confirmed_status_follows_db_not_session(app):
    at, conn, uid, pages = app
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    repo.edit_field(conn, rid, "first_name", "דנה")                            # אושר ממקום אחר (מסך הרשומות)
    at.text_input(key="txt_1_first_name").set_value("דנה")
    button(at, "ok_1_first_name").click().run()
    assert any("✓ אושר: דנה" in m.value for m in at.markdown)
    assert not [b for b in at.button if b.key == "ok_1_first_name"]
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


def test_pending_fields_shown_as_a_pill_above_the_approve_button(app):
    """פס מצב קריא מעל כפתור "אישור שורה" (לא טקסט אפור קטן מתחתיו): כתום כל עוד נשארו שדות לבדיקה,
    ירוק כש"כל השדות נבדקו, אפשר לאשר את השורה"."""
    at, conn, uid, pages = app
    er = row_of_page(pages, 1)
    n_pending = sum(1 for cell in er.cells.values() if cell.orange and cell.value)
    assert n_pending, "הבדיקה מניחה שבעמוד 1 יש שדה כתום עם ערך (אחרת אין מה למדוד)"
    select(at, pages, 1, "שם פרטי")
    rid = repo.find_record(conn, uid, 1, 0)
    from src import ui_text
    expected = ui_text.pending_hint(n_pending)
    assert any(expected in m.value and "row-check warn" in m.value for m in at.markdown)
    assert next(b for b in at.button if b.key == f"appr_{rid}").disabled
    clear_pending(at, er)
    select(at, pages, 1, "שם פרטי")
    assert any(ui_text.ALL_CHECKED_HE in m.value and "row-check ok" in m.value for m in at.markdown)
    assert not next(b for b in at.button if b.key == f"appr_{rid}").disabled


def test_guided_review_cta_is_the_primary_action_when_cells_need_checking(app):
    """במסך העיבוד, כש"יש" תאים לבדיקה בקובץ השמור: "התחלת בדיקה מודרכת" ראשית, וכפתור התא הבודד
    (עריכה נקודתית מהטבלה) משני."""
    at, conn, uid, pages = app
    at.run()
    cta = next(b for b in at.button if b.key == "start_guided")
    point_edit = next(b for b in at.button if b.key == "first_cell")
    assert cta.proto.type == "primary" and point_edit.proto.type == "secondary"
    assert point_edit.label == "התחלה מהתא הראשון (עריכה נקודתית)"
