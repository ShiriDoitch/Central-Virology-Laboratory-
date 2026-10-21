"""בדיקה במבט אחד, הלוגיקה (src/guided_review.py + src/repo.py + src/service.py): מה נכנס לתור הבדיקה,
באיזה סדר, והניווט בו (דלג / חזרה). בלי API ובלי Streamlit: מסד נתונים זמני שנזרע ביד, בלי תלות בריצה השמורה של חלק 1."""
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
    assert service.review_counts(conn, service.RecordFilter()) == {"cells": 3, "records": 2}


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


def test_field_states_for_many_records_matches_get_record(conn):
    uid = seed(conn, {p: [cells(id=ORANGE)] for p in range(1, 6)})
    ids = [r["id"] for r in repo.search_records(conn, limit=None)[0]]
    states = repo.field_states_for(conn, ids)
    assert set(states) == set(ids)
    assert states[ids[0]] == repo.get_record(conn, ids[0])["fields"]
    assert repo.field_states_for(conn, []) == {}
