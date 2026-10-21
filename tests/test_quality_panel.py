"""לוח "איכות המערכת בשימוש" במסך הרשומות (records_screen.render_quality_panel דרך app.py): המספרים נמדדים
ממה שכבר שמור (מצבי השדות ויומן השינויים), ותא ירוק שתוקן ידנית מוצג בבירור עם קישור לרשומה.
בלי קריאות API ובלי מספרים מוערכים: מסד זמני שנזרע ביד."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import repo
from test_guided_review import ORANGE, VALUES, cells, seed

APP = str(Path(__file__).resolve().parent.parent / "app.py")
INVENTED = ("נחסך", "נחסכו", "חוסך", "שעות עבודה", "משוער", "הערכה")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "q.db"))
    return repo.connect(tmp_path / "q.db")


def records_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    at.run()
    assert not at.exception, at.exception
    return at


def panel(at: AppTest) -> str:
    """ה-HTML של הלוח. בלוק העיצוב מדולג: הוא מכיל את שם המחלקה עצמה (.rv-metrics)."""
    return next(m.value for m in at.markdown if "rv-metrics" in m.value and not m.value.startswith("<style>"))


def test_the_panel_counts_green_cells_and_reviews(db):
    uid = seed(db, {1: [cells(id=ORANGE)], 2: [cells()]})            # 6 + 7 ירוקים, כתום אחד
    rid = repo.find_record(db, uid, 1, 0)
    repo.edit_field(db, rid, "id", "123456")                         # תיקון של תא כתום
    repo.edit_field(db, rid, "sender", VALUES["sender"])             # אישור בלי שינוי
    body = panel(records_app())
    assert "תאים שהמערכת שמרה כירוקים</span><b>13</b>" in body
    assert "מהם שתוקנו ידנית (צריך 0)</span><b>0</b>" in body
    assert "תאים שנבדקו</span><b>2</b>" in body
    assert "אושרו בלי שינוי</span><b>1</b>" in body and "תוקנו</span><b>1</b>" in body
    assert "class='ok'" in body                                      # 0 ירוקים שתוקנו: הגוון התקין


def test_a_corrected_green_cell_is_shown_clearly_with_a_link_to_the_record(db):
    uid = seed(db, {1: [cells()]})
    rid = repo.find_record(db, uid, 1, 0)
    repo.edit_field(db, rid, "first_name", "אברהם")                  # המערכת הייתה בטוחה וטעתה
    at = records_app()
    body = panel(at)
    assert "מהם שתוקנו ידנית (צריך 0)</span><b>1</b>" in body and "class='bad'" in body
    assert any("תאים שהמערכת שמרה כירוקים תוקנו ידנית" in e.value for e in at.error)
    opener = next(b for b in at.button if b.key == f"rec_gw_{rid}_first_name")
    assert f"רשומה {rid}" in opener.label and "שם פרטי" in opener.label
    opener.click().run()
    assert not at.exception and at.session_state["rec_open"] == rid   # הקישור פותח את הרשומה
    assert any(f"רשומה {rid}" in m.value for m in at.markdown)


def test_the_panel_shows_no_invented_numbers(db):
    seed(db, {1: [cells(id=ORANGE)]})
    at = records_app()
    body = "\n".join(c.value for c in at.caption) + panel(at)
    for word in INVENTED:
        assert word not in body


def test_the_panel_is_quiet_on_an_untouched_database(db):
    seed(db, {1: [cells(id=ORANGE)]})
    body = panel(records_app())
    assert "תאים שנבדקו</span><b>0</b>" in body and "class='ok'" in body


def test_the_panel_works_in_production_mode(db, monkeypatch):
    monkeypatch.setenv("PRIVACY_MODE", "production")
    uid = seed(db, {1: [cells()]})
    repo.edit_field(db, repo.find_record(db, uid, 1, 0), "last_name", "כהן")
    at = records_app()
    assert "מהם שתוקנו ידנית (צריך 0)</span><b>1</b>" in panel(at)
    assert not at.exception
