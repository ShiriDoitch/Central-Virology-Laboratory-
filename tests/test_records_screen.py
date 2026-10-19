"""מסך הרשומות (records_screen.py + service.query / edit_record_field): חיפוש, סינון, עימוד, תיקון ואישור מול DB זמני. בלי API."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import repo, service

APP = str(Path(__file__).resolve().parent.parent / "app.py")
RUN = Path("outputs/clean_part1_v4b")
pytestmark = pytest.mark.skipif(not RUN.exists(), reason="needs the saved sample run")


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    db = tmp_path / "r.db"
    monkeypatch.setenv("APP_DB_PATH", str(db))
    pages = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(RUN.glob("p*.json"), key=lambda x: int(x.stem[1:]))]
    conn = repo.connect(db)
    store = service.Persister(conn, "f.pdf", b"bytes")
    store.start(len(pages))
    for p in pages:
        store.page(p)
    store.finish()
    return conn, store.upload_id


def records_app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    return at


def test_edit_record_field_normalizes_and_validates(seeded):
    conn, uid = seeded
    rid = service.query(conn, service.RecordFilter(upload_id=uid), limit=1)[0][0]["id"]
    service.edit_record_field(conn, rid, "id", " 12-34 56 ")
    assert repo.get_record(conn, rid)["national_id"] == "123456"
    service.edit_record_field(conn, rid, "center", "111111, 222222")
    assert repo.get_record(conn, rid)["center"] == "111111 ; 222222"
    for key, bad in (("id", "abc"), ("date", "31.06.2026"), ("center", "x1"), ("nope", "1")):
        with pytest.raises(ValueError):
            service.edit_record_field(conn, rid, key, bad)
    assert repo.get_record(conn, rid)["national_id"] == "123456"


def test_query_filters_combine(seeded):
    conn, uid = seeded
    all_rows, total = service.query(conn, service.RecordFilter(), limit=None)
    assert total == len(all_rows) > 20
    some = next(r for r in all_rows if r["sender"])
    flt = service.RecordFilter(senders=[some["sender"]], statuses=[some["status"]], search=some["commitment_no"] or "")
    rows, n = service.query(conn, flt, limit=None)
    assert n >= 1 and all(r["sender"] == some["sender"] for r in rows)
    assert service.query(conn, service.RecordFilter(search="zzzz-no-match"))[1] == 0


def test_screen_renders_and_search_filters_table(seeded):
    conn, uid = seeded
    at = records_app()
    at.run()
    assert not at.exception
    full = len(at.dataframe[0].value)
    some = repo.search_records(conn, limit=1)[0][0]
    term = some["commitment_no"] or some["national_id"] or some["first_name"]
    at.text_input(key="rec_search").set_value(term).run()
    assert not at.exception and 1 <= len(at.dataframe[0].value) <= full


def test_screen_empty_db_shows_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "e.db"))
    at = records_app()
    at.run()
    assert not at.exception and any("אין עדיין רשומות" in m.value for m in at.markdown)


def test_screen_pagination(seeded):
    conn, uid = seeded
    at = records_app()
    at.run()
    at.selectbox(key="rec_size").set_value(25).run()
    total = repo.search_records(conn, limit=1)[1]
    first = len(at.dataframe[0].value)
    assert first == min(25, total)
    if total > 25:
        at.number_input(key="rec_page").set_value(2).run()
        assert len(at.dataframe[0].value) == min(25, total - 25)


def test_detail_edit_save_and_approve_roundtrip(seeded):
    conn, uid = seeded
    rid = repo.search_records(conn, limit=1)[0][0]["id"]
    at = records_app()
    at.session_state["rec_open"] = rid
    at.run()
    assert not at.exception
    at.text_input(key=f"rec_in_{rid}_sender").set_value("מכבי").run()
    next(b for b in at.button if b.key == f"rec_save_{rid}").click().run()
    rec = repo.get_record(conn, rid)
    assert rec["sender"] == "מכבי" and rec["fields"]["sender"]["human_edited"]
    next(b for b in at.button if b.key == f"rec_appr_{rid}").click().run()
    assert repo.get_record(conn, rid)["status"] == "approved"
    # רשומה מאושרת נעולה: אין שדות קלט בכלל (גם לא מושתקים), הערכים מוצגים כטקסט, ואין כפתור שמירה
    assert not [t for t in at.text_input if t.key == f"rec_in_{rid}_sender"]
    assert any("מכבי" in m.value for m in at.markdown)
    assert not [b for b in at.button if b.key == f"rec_save_{rid}"]
    next(b for b in at.button if b.key == f"rec_unappr_{rid}").click().run()
    assert repo.get_record(conn, rid)["status"] in ("pending", "ready")
    assert at.text_input(key=f"rec_in_{rid}_sender").value == "מכבי"


def test_invalid_edit_shows_error_and_writes_nothing(seeded):
    conn, uid = seeded
    rid = repo.search_records(conn, limit=1)[0][0]["id"]
    before = repo.get_record(conn, rid)["national_id"]
    at = records_app()
    at.session_state["rec_open"] = rid
    at.run()
    at.text_input(key=f"rec_in_{rid}_id").set_value("abc").run()
    next(b for b in at.button if b.key == f"rec_save_{rid}").click().run()
    assert repo.get_record(conn, rid)["national_id"] == before
    assert any("לא תקין" in e.value for e in at.error)


def test_screen_offers_three_downloads(seeded):
    at = records_app()
    at.run()
    assert not at.exception
    labels = [b.proto.label for b in at.get("download_button")]
    assert labels == ["Excel", "CSV", "JSON"]
