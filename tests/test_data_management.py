"""ניהול נתונים בתחתית מסך הרשומות: מחיקת הכול (עם תיבת אישור), ללא tooltips תקועים על מוני הסטטוס. בלי API."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import page_store, repo, service
from tests.test_page_images import make_pdf, page_result

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    db = tmp_path / "d.db"
    monkeypatch.setenv("APP_DB_PATH", str(db))
    conn = repo.connect(db)
    pdf = make_pdf(tmp_path / "t.pdf", pages=2)
    store = service.Persister(conn, "f.pdf", b"x")
    store.start(2)
    for p in (1, 2):
        res = page_result(p)
        store.page(res)
        store.save_image(pdf, res)
    store.finish()
    return conn, store.upload_id


def screen(**state):
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception
    return at


def test_status_counters_have_no_tooltip_and_keep_their_keys(seeded):
    at = screen()
    counters = {b.key: b for b in at.button if b.key and b.key.startswith("rec_cnt_")}
    assert set(counters) == {"rec_cnt_queue", "rec_cnt_pending", "rec_cnt_ready", "rec_cnt_approved", "rec_cnt_all"}
    assert all(not b.proto.help for b in counters.values())


def test_data_management_is_a_collapsed_section_at_the_bottom(seeded):
    conn, uid = seeded
    rid = repo.page_records(conn, uid, 1)[0]["id"]
    at = screen(rec_open=rid)                                          # גם כשכרטיס רשומה פתוח: ניהול הנתונים מתחתיו
    labels = [e.label for e in at.expander]
    assert labels[-1] == "ניהול נתונים"
    mgmt = at.expander[-1]
    assert mgmt.proto.expanded is False
    assert any("סופית" in w.value and "הורדת" in w.value for w in at.warning)      # הודעה ברורה: סופי, ולא משפיע על קבצים שהורדו


def test_delete_button_needs_the_confirm_checkbox(seeded):
    conn, uid = seeded
    at = screen()
    btn = next(b for b in at.button if b.key == "rec_wipe_all")
    assert btn.disabled
    at.checkbox(key="rec_wipe_ok").check().run()
    assert not next(b for b in at.button if b.key == "rec_wipe_all").disabled
    assert repo.search_records(conn)[1] == 2 and page_store.exists(uid, 1)         # עוד לא נמחק כלום


def test_delete_all_clears_db_images_and_session(seeded):
    conn, uid = seeded
    at = screen(pages=[{"page": 1}], images={1: b"x"}, name_overrides={(1, "sender"): "x"}, upload_id=uid)
    at.checkbox(key="rec_wipe_ok").check().run()
    next(b for b in at.button if b.key == "rec_wipe_all").click().run()
    assert not at.exception
    for table in ("uploads", "records", "field_states", "record_centers", "page_regions", "audit_log"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert not page_store.exists(uid, 1) and not page_store.exists(uid, 2) and not page_store.root().exists()
    assert any("נמחקו לצמיתות" in s.value for s in at.success)
    assert at.session_state["upload_id"] is None if "upload_id" in at.session_state else True
    assert "pages" not in at.session_state or not at.session_state["pages"]
    assert at.checkbox(key="rec_wipe_ok").value is False                            # תיבת האישור מתאפסת
    assert next(b for b in at.button if b.key == "rec_wipe_all").disabled


def test_delete_all_on_an_empty_database_is_harmless(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "e.db"))
    at = screen()
    at.checkbox(key="rec_wipe_ok").check().run()
    next(b for b in at.button if b.key == "rec_wipe_all").click().run()
    assert not at.exception and any("נמחקו לצמיתות" in s.value for s in at.success)
