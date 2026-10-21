"""אישור קבוצתי של רשומות בטוחות במסך הרשומות (records_screen.render_bulk_approve דרך app.py): המספר מוצג
קודם, האישור דורש תיבת סימון, ורשומה שיש בה תא לבדיקה לא מאושרת גם אם לוחצים. בלי קריאות API: מסד זמני שנזרע ביד."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import repo
from test_guided_review import BLANK, ORANGE, cells, seed

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "b.db"))
    return repo.connect(tmp_path / "b.db")


def records_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    at.run()
    assert not at.exception, at.exception
    return at


def statuses(conn) -> dict:
    return {r["page_no"]: r["status"] for r in repo.search_records(conn, limit=None)[0]}


def test_the_count_is_shown_and_the_button_needs_the_checkbox(db):
    seed(db, {1: [cells()], 2: [cells(id=ORANGE)], 3: [cells()]})
    at = records_app()
    assert any("<b>2</b> רשומות בטוחות לאישור" in m.value for m in at.markdown)
    assert at.button(key="rec_bulk_go").disabled                     # בלי סימון: הכפתור נעול
    at.checkbox(key="rec_bulk_ok").set_value(True).run()
    assert not at.button(key="rec_bulk_go").disabled


def test_approving_takes_only_the_safe_records_and_says_how_many(db):
    seed(db, {1: [cells()], 2: [cells(id=ORANGE)], 3: [cells(date=BLANK)], 4: [cells()]})
    at = records_app()
    at.checkbox(key="rec_bulk_ok").set_value(True).run()
    at.button(key="rec_bulk_go").click().run()
    assert not at.exception
    assert statuses(db) == {1: "approved", 2: "pending", 3: "pending", 4: "approved"}
    assert any("אושרו 2 רשומות" in s.value for s in at.success)
    assert at.checkbox(key="rec_bulk_ok").value is False             # התיבה חוזרת למצב לא מסומן


def test_a_record_with_a_cell_to_review_is_never_approved(db):
    seed(db, {1: [cells(id=ORANGE)], 2: [cells(center=BLANK)]})
    at = records_app()
    assert at.button(key="rec_bulk_go").disabled                     # 0 בטוחות: אין מה לאשר
    at.checkbox(key="rec_bulk_ok").set_value(True).run()
    at.button(key="rec_bulk_go").click().run()
    assert not at.exception and repo.status_counts(db)["approved"] == 0


def test_the_approval_can_be_undone_in_the_record_card(db):
    uid = seed(db, {1: [cells()]})
    rid = repo.find_record(db, uid, 1, 0)
    at = records_app()
    at.checkbox(key="rec_bulk_ok").set_value(True).run()
    at.button(key="rec_bulk_go").click().run()
    assert repo.get_record(db, rid)["status"] == "approved"
    at.session_state["rec_open"] = rid
    at.run()
    next(b for b in at.button if b.key == f"rec_unappr_{rid}").click().run()
    assert not at.exception and repo.get_record(db, rid)["status"] == "ready"


def test_approving_respects_the_active_filter(db):
    seed(db, {1: [cells()], 2: [cells(sender={"value": "כללית"})]})
    at = records_app()
    at.multiselect(key="rec_sender").set_value(["כללית"]).run()
    at.checkbox(key="rec_bulk_ok").set_value(True).run()
    at.button(key="rec_bulk_go").click().run()
    assert statuses(db) == {1: "ready", 2: "approved"}


def test_bulk_approve_in_production_mode(db, monkeypatch):
    monkeypatch.setenv("PRIVACY_MODE", "production")
    seed(db, {1: [cells()]})
    at = records_app()
    at.checkbox(key="rec_bulk_ok").set_value(True).run()
    at.button(key="rec_bulk_go").click().run()
    assert not at.exception and repo.status_counts(db)["approved"] == 1
