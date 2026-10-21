"""מסך הרשומות כתור עבודה: סינון ברירת מחדל, מסנן זמן העלאה, מונים לחיצים, "הבאה בתור", וייצוא של הסינון הפעיל. נתונים סינתטיים, בלי API."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import repo, service
from tests.test_repo import confirm_flagged_cells, green_fields

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def utc_of(y, m, d, hh=12, mm=0):
    """חותמת UTC (כמו uploads.created_at) לזמן מקומי נתון."""
    return datetime(y, m, d, hh, mm).astimezone(__import__("datetime").timezone.utc).isoformat(timespec="seconds")


def make_upload(conn, name, sha, when, n_pending=0, n_ready=0, n_approved=0, last_prefix=""):
    uid = repo.create_upload(conn, name, sha, 99)
    conn.execute("UPDATE uploads SET created_at=?, completed_at=? WHERE id=?", (when, when, uid))
    conn.commit()
    ordinal = 0
    ids = {"pending": [], "ready": [], "approved": []}

    def add(status, i):
        nonlocal ordinal
        orange = status == "pending"
        f = green_fields(last_name=(f"{last_prefix}{status[:1]}{i:02d}", "green"),
                         id=("1000" + str(ordinal), "orange", ["handwritten"]) if orange else ("1000" + str(ordinal), "green"))
        rid, _ = repo.save_machine_record(conn, uid, ordinal + 1, 0, f)
        if status == "approved":
            repo.approve_record(conn, rid)
        ids[status].append(rid)
        ordinal += 1

    for i in range(n_pending):
        add("pending", i)
    for i in range(n_ready):
        add("ready", i)
    for i in range(n_approved):
        add("approved", i)
    return uid, ids


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "q.db"
    monkeypatch.setenv("APP_DB_PATH", str(path))
    conn = repo.connect(path)
    yield conn
    conn.close()


def screen():
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    return at


# ---------- לוגיקה: הבאה בתור ----------

def test_pick_next_pending_order_wrap_and_missing():
    items = [(1, "pending"), (2, "ready"), (3, "pending"), (4, "approved"), (5, "pending")]
    assert service.pick_next_pending(items, 1) == 3
    assert service.pick_next_pending(items, 3) == 5
    assert service.pick_next_pending(items, 5) == 1                 # חזרה להתחלה
    assert service.pick_next_pending(items, 2) == 3                 # נוכחית שאינה ממתינה
    assert service.pick_next_pending(items, 99) == 1                # לא ברשימה: הראשונה
    assert service.pick_next_pending([(1, "pending")], 1) is None   # אין אחרת
    assert service.pick_next_pending([(1, "approved"), (2, "ready")], 1) is None
    assert service.pick_next_pending([], None) is None


def test_next_pending_follows_sort_and_filters(db):
    uid, ids = make_upload(db, "a.pdf", "s1", utc_of(2026, 10, 5), n_pending=3, n_ready=1)
    names = {r["id"]: r["last_name"] for r in service.query(db, service.RecordFilter(), limit=None)[0]}
    flt = service.RecordFilter(sort="last_name", descending=True)
    order = [i for i, _ in service.ordered_ids(db, flt)]
    assert [names[i] for i in order] == sorted(names.values(), reverse=True)
    pend = [i for i in order if i in ids["pending"]]
    assert service.next_pending_id(db, flt, pend[0]) == pend[1]
    assert service.next_pending_id(db, flt, pend[-1]) == pend[0]
    # סינון חיפוש חל; סינון הסטטוס אינו חל על "הבאה"
    only = service.RecordFilter(search=names[pend[2]], statuses=["ready"])
    assert service.next_pending_id(db, only, pend[0]) == pend[2]
    assert service.next_pending_id(db, service.RecordFilter(search="no-such"), pend[0]) is None
    assert service.position_in(db, flt, pend[1]) == order.index(pend[1])


# ---------- סינון לפי זמן העלאה ----------

def test_upload_time_filter_uses_local_days_inclusive(db):
    make_upload(db, "early.pdf", "e", utc_of(2026, 10, 1, 0, 5), n_pending=1)          # ממש אחרי חצות מקומי
    make_upload(db, "late.pdf", "l", utc_of(2026, 10, 1, 23, 55), n_pending=1)         # ממש לפני חצות מקומי
    make_upload(db, "next.pdf", "n", utc_of(2026, 10, 2, 0, 5), n_pending=1)
    day1 = service.RecordFilter(uploaded_from="01.10.2026", uploaded_to="01.10.2026")
    rows, total = service.query(db, day1, limit=None)
    assert total == 2 and {r["upload_filename"] for r in rows} == {"early.pdf", "late.pdf"}
    assert service.query(db, service.RecordFilter(uploaded_from="02.10.2026"), limit=None)[1] == 1
    assert service.query(db, service.RecordFilter(uploaded_to="01.10.2026"), limit=None)[1] == 2
    assert service.query(db, service.RecordFilter(uploaded_from="03.10.2026"), limit=None)[1] == 0
    rows, _ = service.query(db, service.RecordFilter(sort="upload", descending=True), limit=None)
    assert [r["upload_filename"] for r in rows] == ["next.pdf", "late.pdf", "early.pdf"]
    assert service.upload_time_label(utc_of(2026, 10, 1, 23, 55)) == "01.10.2026 23:55"


def test_export_respects_status_and_upload_filters(db):
    make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=2, n_approved=1, last_prefix="A")
    make_upload(db, "b.pdf", "b", utc_of(2026, 10, 9), n_pending=1, n_ready=1, last_prefix="B")
    flt = service.RecordFilter(statuses=service.WORK_QUEUE, uploaded_from="05.10.2026", uploaded_to="12.10.2026")
    data, _, _ = service.export_records(db, flt, "json")
    doc = json.loads(data)
    assert doc["count"] == 2 and {r["file"] for r in doc["records"]} == {"b.pdf"}
    assert all(r["status"] in ("pending", "ready") for r in doc["records"])
    all_rows = json.loads(service.export_records(db, service.RecordFilter(), "json")[0])
    assert all_rows["count"] == 5


# ---------- המסך ----------

def table_rows(at):
    return at.dataframe[0].value


def test_default_filter_hides_approved_and_show_all_reveals(db):
    make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=2, n_ready=1, n_approved=2)
    at = screen()
    at.run()
    assert not at.exception
    assert list(at.multiselect(key="rec_status").value) == ["pending", "ready"]
    assert len(table_rows(at)) == 3 and set(table_rows(at)["סטטוס"]) == {"ממתינה", "מוכנה"}
    assert at.session_state["_rec_flt"].statuses == ["pending", "ready"]          # גם הייצוא משתמש בסינון הזה
    next(b for b in at.button if b.key == "rec_cnt_all").click().run()
    assert len(table_rows(at)) == 5 and set(table_rows(at)["סטטוס"]) == {"ממתינה", "מוכנה", "אושרה"}
    next(b for b in at.button if b.key == "rec_cnt_queue").click().run()
    assert len(table_rows(at)) == 3


def test_counters_show_totals_and_filter_on_click(db):
    make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=2, n_ready=1, n_approved=3)
    at = screen()
    at.run()
    labels = {b.key: b.label for b in at.button if b.key and b.key.startswith("rec_cnt_")}
    assert labels["rec_cnt_pending"].endswith("2") and labels["rec_cnt_ready"].endswith("1") and labels["rec_cnt_approved"].endswith("3")
    next(b for b in at.button if b.key == "rec_cnt_approved").click().run()
    assert list(at.multiselect(key="rec_status").value) == ["approved"] and len(table_rows(at)) == 3
    assert set(table_rows(at)["סטטוס"]) == {"אושרה"}
    next(b for b in at.button if b.key == "rec_cnt_ready").click().run()
    assert len(table_rows(at)) == 1 and at.session_state["_rec_flt"].statuses == ["ready"]


def test_table_columns_in_reading_order(db):
    """עמודות הטבלה וסדרן. הרשת מצוירת LTR, ולכן סדר הקריאה (מימין לשמאל) הוא הרשימה ההפוכה."""
    make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=1)
    at = screen()
    at.run()
    assert not at.exception
    assert list(reversed(table_rows(at).columns)) == ["מס' התחייבות", "שם פרטי", "שם משפחה", 'ת"ז', "מרכזי", "גורם שולח",
                                                      "תאריך קבלת דגימה", "עמוד", "סטטוס", "הועלה"]


def test_upload_column_and_upload_date_filter_in_ui(db):
    make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1, 9, 30), n_pending=1)
    make_upload(db, "b.pdf", "b", utc_of(2026, 10, 9, 14, 45), n_pending=2)
    at = screen()
    at.run()
    t = table_rows(at)
    assert "הועלה" in t.columns and set(t["הועלה"]) == {"01.10.2026 09:30", "09.10.2026 14:45"}
    at.date_input(key="rec_upl_dates").set_value((date(2026, 10, 5), date(2026, 10, 12))).run()
    assert not at.exception and len(table_rows(at)) == 2 and set(table_rows(at)["הועלה"]) == {"09.10.2026 14:45"}
    flt = at.session_state["_rec_flt"]
    assert (flt.uploaded_from, flt.uploaded_to) == ("05.10.2026", "12.10.2026")


def test_open_next_pending_moves_in_sort_order_and_across_pages(db):
    uid, ids = make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=30)
    at = screen()
    at.session_state["rec_open"] = ids["pending"][0]
    at.run()
    at.selectbox(key="rec_size").set_value(25).run()
    assert not at.exception and at.session_state["rec_open"] == ids["pending"][0]
    next(b for b in at.button if b.key == f"rec_next_{ids['pending'][0]}").click().run()
    assert at.session_state["rec_open"] == ids["pending"][1]
    # קפיצה לרשומה שבעמוד השני של הטבלה
    at.session_state["rec_open"] = ids["pending"][23]
    at.run()
    next(b for b in at.button if b.key == f"rec_next_{ids['pending'][23]}").click().run()
    next(b for b in at.button if b.key == f"rec_next_{ids['pending'][24]}").click().run()
    assert at.session_state["rec_open"] == ids["pending"][25] and at.number_input(key="rec_page").value == 2


def test_open_prev_pending_moves_backwards_and_wraps(db):
    """הכפתור החדש בסרגל הפעולות: הממתינה הקודמת באותו סדר, עם חזרה לסוף הרשימה."""
    uid, ids = make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=3)
    at = screen()
    at.session_state["rec_open"] = ids["pending"][1]
    at.run()
    assert not at.exception
    next(b for b in at.button if b.key == f"rec_prev_{ids['pending'][1]}").click().run()
    assert at.session_state["rec_open"] == ids["pending"][0]
    next(b for b in at.button if b.key == f"rec_prev_{ids['pending'][0]}").click().run()
    assert at.session_state["rec_open"] == ids["pending"][2]


def test_open_next_skips_approved_and_adds_pending_to_a_hiding_filter(db):
    uid, ids = make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=2, n_ready=2)
    at = screen()
    at.session_state["rec_open"] = ids["ready"][0]
    at.session_state["rec_status"] = ["ready"]
    at.run()
    assert list(at.multiselect(key="rec_status").value) == ["ready"]
    next(b for b in at.button if b.key == f"rec_next_{ids['ready'][0]}").click().run()
    assert at.session_state["rec_open"] == ids["pending"][0]
    assert "pending" in list(at.multiselect(key="rec_status").value)


def test_open_next_without_other_pending_shows_message(db):
    uid, ids = make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=1, n_ready=1)
    at = screen()
    at.session_state["rec_open"] = ids["pending"][0]
    at.run()
    next(b for b in at.button if b.key == f"rec_next_{ids['pending'][0]}").click().run()
    assert any("אין רשומות ממתינות נוספות" in i.value for i in at.info)
    assert at.session_state["rec_open"] == ids["pending"][0]


def test_approve_keeps_record_open_even_though_queue_hides_it(db):
    uid, ids = make_upload(db, "a.pdf", "a", utc_of(2026, 10, 1), n_pending=2)
    rid = ids["pending"][0]
    at = screen()
    at.session_state["rec_open"] = rid
    confirm_flagged_cells(db, rid)                                                   # אחרת כפתור האישור נעול
    at.run()
    next(b for b in at.button if b.key == f"rec_appr_{rid}").click().run()
    assert repo.get_record(db, rid)["status"] == "approved"
    assert len(table_rows(at)) == 1                                                  # נעלמה מתור העבודה
    assert at.session_state["rec_open"] == rid and any(b.key == f"rec_unappr_{rid}" for b in at.button)
    next(b for b in at.button if b.key == f"rec_next_{rid}").click().run()
    assert at.session_state["rec_open"] == ids["pending"][1]
