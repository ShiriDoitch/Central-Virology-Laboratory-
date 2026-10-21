"""בדיקה במבט אחד, הלוגיקה (src/guided_review.py + src/repo.py + src/service.py): מה נכנס לתור הבדיקה,
באיזה סדר, הניווט בו (דלג / חזרה), האישור הקבוצתי של רשומות בטוחות, ומדדי האיכות.
בלי API ובלי Streamlit: מסד נתונים זמני שנזרע ביד, בלי תלות בריצה השמורה של חלק 1."""
import pytest

from src import guided_review, repo, service
from src.export import FIELD_KEYS


# ערכי ברירת מחדל חוקיים לכל שדה (כמו בטופס אמיתי), כדי שאישור של הערך שנקרא יעבור את הנרמול של normalize_override
VALUES = {"first_name": "ישראל", "last_name": "ישראלי", "id": "11223344", "center": "944963",
          "date": "18.06.2026", "sender": "מכבי", "commitment": "107646"}


def cells(**over) -> dict:
    """מצב המכונה לכל שבעת השדות: ברירת מחדל ערך ירוק, ושינוי לפי שם שדה. למשל cells(id={"color": "orange", "flags": ["conflict"]})."""
    base = {k: {"value": VALUES[k], "color": "green", "flags": [], "alternatives": []} for k in FIELD_KEYS}
    for key, patch in over.items():
        base[key] = {**base[key], **patch}
    return base


ORANGE = {"color": "orange", "flags": ["conflict"], "alternatives": ["אחר"]}
YELLOW = {"color": "yellow", "flags": ["handwritten"]}
BLANK = {"value": None, "color": "empty", "flags": []}
FLAGGED_BLANK = {"value": None, "color": "orange", "flags": ["missing_required_field"]}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    return repo.connect(tmp_path / "t.db")


def seed(conn, pages: dict, filename: str = "f.pdf", sha: str = "sha-1") -> int:
    """pages = {עמוד: [מצבי שדות לכל שורה]}. מחזיר את מזהה ההעלאה."""
    uid = repo.create_upload(conn, filename, sha, len(pages))
    for page, rows in pages.items():
        for ordinal, fields in enumerate(rows):
            repo.save_machine_record(conn, uid, page, ordinal, fields)
    repo.complete_upload(conn, uid)
    return uid


def queue_of(conn, flt=None):
    return service.review_queue(conn, flt or service.RecordFilter())


# ---------- תוכן התור וסדרו ----------

def test_queue_holds_only_cells_that_need_a_human(conn):
    """כתום, זהב וריק נכנסים; ירוק לא. תא שהמשתמשת אישרה יוצא מהתור גם אם היה כתום."""
    seed(conn, {1: [cells(id=ORANGE, date=YELLOW, center=BLANK, commitment=FLAGGED_BLANK)]})
    assert {i.field for i in queue_of(conn)} == {"id", "date", "center", "commitment"}
    rid = repo.search_records(conn, limit=1)[0][0]["id"]
    repo.edit_field(conn, rid, "id", "123456")
    assert {i.field for i in queue_of(conn)} == {"date", "center", "commitment"}


def test_queue_order_is_record_then_the_seven_field_order(conn):
    seed(conn, {2: [cells(commitment=ORANGE, first_name=ORANGE)], 1: [cells(sender=ORANGE, id=ORANGE)]})
    assert [(i.page_no, i.field) for i in queue_of(conn)] == [(1, "id"), (1, "sender"), (2, "first_name"), (2, "commitment")]


def test_queue_skips_approved_records_entirely(conn):
    uid = seed(conn, {1: [cells(id=ORANGE)], 2: [cells(id=ORANGE)]})
    rid = repo.find_record(conn, uid, 1, 0)
    repo.approve_record(conn, rid)
    assert [i.page_no for i in queue_of(conn)] == [2]


def test_queue_respects_the_active_filter(conn):
    seed(conn, {1: [cells(id=ORANGE)], 2: [cells(id=ORANGE, sender={"value": "כללית"})]})
    assert [i.page_no for i in queue_of(conn, service.RecordFilter(senders=["מכבי"]))] == [1]
    assert queue_of(conn, service.RecordFilter(search="zzz")) == []
    assert [i.page_no for i in queue_of(conn, service.RecordFilter(descending=True))] == [2, 1]


def test_a_page_with_two_rows_gives_a_cell_per_row(conn):
    seed(conn, {1: [cells(commitment=ORANGE), cells(commitment=ORANGE)]})
    assert [(i.ordinal, i.field) for i in queue_of(conn)] == [(0, "commitment"), (1, "commitment")]


def test_review_counts_match_the_queue(conn):
    seed(conn, {1: [cells(id=ORANGE, date=ORANGE)], 2: [cells()], 3: [cells(center=BLANK)]})
    assert service.review_counts(conn, service.RecordFilter()) == {"cells": 3, "records": 2, "safe": 1}


# ---------- הניווט ----------

def items(n: int) -> list:
    return [guided_review.ReviewItem(record_id=1 + i // 2, upload_id=1, page_no=1 + i // 2, ordinal=0,
                                     field=FIELD_KEYS[i % 2], color="orange") for i in range(n)]


def test_skip_moves_the_cell_to_the_end_and_comes_back(conn):
    sess = guided_review.ReviewSession(items=items(3))
    first = sess.current
    sess.skip()
    # המקום בתור לא התקדם, ולכן העוקב נכנס לאותו אינדקס והתא שדולג עבר לסוף
    assert sess.pos == 0 and sess.current is not first and sess.items[-1] is first and sess.skips == 1
    sess.advance()
    sess.advance()
    assert sess.current is first                      # התא שדולג חוזר בסוף התור
    assert sess.remaining() == 1


def test_skip_on_the_last_cell_ends_the_round(conn):
    sess = guided_review.ReviewSession(items=items(1))
    sess.skip()
    assert sess.done and sess.remaining() == 0


def test_back_returns_to_the_previous_cell_and_stops_at_the_first(conn):
    sess = guided_review.ReviewSession(items=items(3))
    sess.advance()
    sess.advance()
    sess.back()
    assert sess.pos == 1
    sess.back()
    sess.back()
    assert sess.pos == 0


def test_progress_counts_forms_and_cells(conn):
    sess = guided_review.ReviewSession(items=items(4))         # שתי רשומות, שני תאים לכל אחת
    assert sess.progress() == {"record_i": 1, "records": 2, "cell_i": 1, "cells": 2, "remaining": 4}
    sess.advance()
    sess.advance()
    assert sess.progress() == {"record_i": 2, "records": 2, "cell_i": 1, "cells": 2, "remaining": 2}


def test_summary_reports_only_what_was_measured(conn):
    sess = guided_review.ReviewSession(items=items(4), started_at=100.0)
    for item in sess.items[:3]:
        sess.record_action(item)
    s = sess.summary(130.0)
    assert s == {"records": 2, "cells": 3, "seconds": 30.0, "skips": 0, "per_cell": 10.0}
    assert guided_review.ReviewSession(items=[], started_at=5.0).summary(5.0)["per_cell"] is None
    assert guided_review.duration_he(30) == "30 שניות" and guided_review.duration_he(95) == "1 דק' ו-35 שניות"


# ---------- אישור קבוצתי של רשומות בטוחות ----------

def test_safe_record_needs_every_cell_green_without_a_flag_or_confirmed(conn):
    assert guided_review.is_safe_cell({"color": "green", "flags": [], "cell_confirmed": False})
    assert guided_review.is_safe_cell({"color": "orange", "flags": ["conflict"], "cell_confirmed": True})
    assert not guided_review.is_safe_cell({"color": "green", "flags": ["handwritten"], "cell_confirmed": False})
    for color in ("orange", "yellow", "empty"):
        assert not guided_review.is_safe_cell({"color": color, "flags": [], "cell_confirmed": False})
    fields = {k: {"color": "green", "flags": [], "cell_confirmed": False} for k in FIELD_KEYS}
    assert guided_review.is_safe_record({"status": "ready"}, fields)
    assert not guided_review.is_safe_record({"status": "approved"}, fields)
    assert not guided_review.is_safe_record({"status": "ready"}, {k: v for k, v in fields.items() if k != "id"})


def test_bulk_approve_takes_only_the_safe_records_and_is_undoable(conn):
    uid = seed(conn, {1: [cells()], 2: [cells(id=ORANGE)], 3: [cells(date=BLANK)], 4: [cells()]})
    safe = {repo.find_record(conn, uid, 1, 0), repo.find_record(conn, uid, 4, 0)}
    assert set(service.safe_record_ids(conn, service.RecordFilter())) == safe
    assert service.approve_safe_records(conn, service.RecordFilter()) == 2
    assert {r["id"] for r in repo.search_records(conn, statuses=["approved"], limit=None)[0]} == safe
    assert service.approve_safe_records(conn, service.RecordFilter()) == 0          # כבר מאושרות: אין מה לאשר שוב
    for rid in safe:                                     # שורה ביומן השינויים לכל רשומה, וביטול האישור עובד
        assert [a["action"] for a in repo.audit_entries(conn, rid) if a["action"] == "approve"] == ["approve"]
        repo.unapprove_record(conn, rid)
        assert repo.get_record(conn, rid)["status"] == "ready"


def test_bulk_approve_never_touches_a_record_with_a_cell_to_review(conn):
    seed(conn, {1: [cells(first_name=YELLOW)], 2: [cells(center=FLAGGED_BLANK)], 3: [cells(sender=ORANGE)]})
    assert service.approve_safe_records(conn, service.RecordFilter()) == 0
    assert repo.status_counts(conn)["approved"] == 0


def test_bulk_approve_includes_a_record_the_user_confirmed(conn):
    uid = seed(conn, {1: [cells(id=ORANGE)]})
    rid = repo.find_record(conn, uid, 1, 0)
    assert service.safe_record_ids(conn, service.RecordFilter()) == []
    repo.edit_field(conn, rid, "id", "123456")                                      # תיקון ידני = תא מאושר
    assert service.safe_record_ids(conn, service.RecordFilter()) == [rid]


def test_bulk_approve_respects_the_filter(conn):
    seed(conn, {1: [cells()], 2: [cells(sender={"value": "כללית"})]})
    assert service.approve_safe_records(conn, service.RecordFilter(senders=["כללית"])) == 1
    assert repo.status_counts(conn)["approved"] == 1


def test_an_approved_record_leaves_the_review_queue(conn):
    """אישור קבוצתי ותור הבדיקה מסתכלים על אותם נתונים: רשומה שאושרה לא תוצג יותר לבדיקה."""
    uid = seed(conn, {1: [cells()], 2: [cells(id=ORANGE)]})
    service.approve_safe_records(conn, service.RecordFilter())
    assert [i.page_no for i in queue_of(conn)] == [2]
    assert service.review_counts(conn, service.RecordFilter())["safe"] == 0


# ---------- מדדי איכות ----------

def test_quality_counts_green_cells_and_the_green_ones_a_user_corrected(conn):
    uid = seed(conn, {1: [cells(id=ORANGE, date=BLANK)]})           # חמישה ירוקים, כתום אחד, ריק אחד
    rid = repo.find_record(conn, uid, 1, 0)
    assert service.quality_stats(conn) == {"green": 5, "green_edited": 0, "reviewed": 0, "corrected": 0,
                                           "confirmed_unchanged": 0}
    repo.edit_field(conn, rid, "id", "123456")                      # תיקון של תא כתום: לא נוגע בירוקים
    repo.edit_field(conn, rid, "sender", VALUES["sender"])          # אישור של ירוק (אותו ערך) = בלי שינוי
    q = service.quality_stats(conn)
    assert (q["green"], q["green_edited"], q["reviewed"], q["corrected"], q["confirmed_unchanged"]) == (5, 0, 2, 1, 1)
    assert service.green_edited_cells(conn) == []
    repo.edit_field(conn, rid, "first_name", "אברהם")               # תיקון של תא שהמכונה שמרה כירוק
    q = service.quality_stats(conn)
    assert q["green_edited"] == 1 and q["corrected"] == 2
    assert [(c["field"], c["machine_value"], c["corrected"], c["page_no"]) for c in service.green_edited_cells(conn)]         == [("first_name", "ישראל", "אברהם", 1)]


def test_a_yellow_cell_is_not_counted_as_green(conn):
    """זהב וכתום נושאים דגלים, ולכן תיקון שלהם אינו "ירוק שתוקן"."""
    uid = seed(conn, {1: [cells(first_name=YELLOW)]})
    rid = repo.find_record(conn, uid, 1, 0)
    assert service.quality_stats(conn)["green"] == 6
    repo.edit_field(conn, rid, "first_name", "אברהם")
    assert service.quality_stats(conn)["green_edited"] == 0 and service.quality_stats(conn)["corrected"] == 1


def test_the_green_counter_survives_a_confirmation_and_a_revert(conn):
    """אישור משנה את הצבע ל-confirmed, אבל machine_value והדגלים נשמרים, ולכן "ירוק של המכונה" לא נעלם."""
    uid = seed(conn, {1: [cells()]})
    rid = repo.find_record(conn, uid, 1, 0)
    repo.edit_field(conn, rid, "id", "999")
    assert service.quality_stats(conn)["green"] == 7 and service.quality_stats(conn)["green_edited"] == 1
    repo.revert_field(conn, rid, "id")
    assert service.quality_stats(conn)["green"] == 7
    assert service.quality_stats(conn)["green_edited"] == 1          # היומן זוכר שהמערכת טעתה, גם אחרי ביטול


def test_a_machine_rerun_is_not_counted_as_a_user_correction(conn):
    """עיבוד חוזר כותב machine_update ביומן; רק confirm ו-edit הם פעולות של המשתמשת."""
    uid = seed(conn, {1: [cells()]})
    repo.save_machine_record(conn, uid, 1, 0, cells(first_name={"value": "דוד"}))
    rid = repo.find_record(conn, uid, 1, 0)
    assert [a["action"] for a in repo.audit_entries(conn, rid) if a["field"] == "first_name"] == ["machine_update"]
    q = service.quality_stats(conn)
    assert (q["green_edited"], q["reviewed"], q["corrected"]) == (0, 0, 0)


def test_field_states_for_many_records_matches_get_record(conn):
    uid = seed(conn, {p: [cells(id=ORANGE)] for p in range(1, 6)})
    ids = [r["id"] for r in repo.search_records(conn, limit=None)[0]]
    states = repo.field_states_for(conn, ids)
    assert set(states) == set(ids)
    assert states[ids[0]] == repo.get_record(conn, ids[0])["fields"]
    assert repo.field_states_for(conn, []) == {}
