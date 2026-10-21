"""שכבת הנתונים (src/repo.py): סכמה, שמירה, אי-דריסה של אישור אנושי / רשומה מאושרת, audit, חיפוש וסינון. בלי API."""
import pytest

from src import repo


@pytest.fixture
def conn():
    c = repo.connect(":memory:")
    yield c
    c.close()


def fields(**over):
    base = {k: {"value": None, "color": "empty", "flags": [], "alternatives": []} for k in repo.FIELDS}
    for k, v in over.items():
        base[k] = {"value": v[0], "color": v[1], "flags": v[2] if len(v) > 2 else [], "alternatives": v[3] if len(v) > 3 else []}
    return base


def green_fields(**over):
    base = dict(first_name=("דנה", "green"), last_name=("כהן", "green"), id=("123456789", "green"), center=("944963 ; 944964", "green"),
                date=("18.06.2026", "green"), sender=("כללית", "green"), commitment=("107646", "green"))
    base.update(over)
    return fields(**base)


def confirm_flagged_cells(conn, record_id: int) -> list[str]:
    """מאשר את כל התאים הכתומים שיש בהם ערך, כדי שכפתור "אישור רשומה" / "אישור שורה" לא יהיה נעול
    (records_screen.pending_fields, app.pending_fields). מחזיר את השדות שאושרו."""
    done = []
    for field, state in (repo.get_record(conn, record_id)["fields"] or {}).items():
        if state["color"] == "orange" and state["machine_value"]:
            repo.edit_field(conn, record_id, field, state["machine_value"])
            done.append(field)
    return done


def test_schema_tables_and_foreign_keys(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"uploads", "records", "record_centers", "field_states", "audit_log"} <= names
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_upload_sha_unique(conn):
    uid = repo.create_upload(conn, "a.pdf", "abc", 3)
    assert repo.find_upload(conn, "abc")["id"] == uid
    assert repo.find_upload(conn, "zzz") is None
    with pytest.raises(Exception):
        repo.create_upload(conn, "b.pdf", "abc", 1)


def test_save_record_splits_centers_and_status(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, outcome = repo.save_machine_record(conn, uid, 1, 0, green_fields())
    assert outcome == "created"
    rec = repo.get_record(conn, rid)
    assert rec["status"] == "ready" and rec["center"] == "944963 ; 944964" and rec["national_id"] == "123456789"
    assert [r[0] for r in conn.execute("SELECT center_no FROM record_centers ORDER BY position")] == ["944963", "944964"]
    rid2, _ = repo.save_machine_record(conn, uid, 1, 1, green_fields(id=(None, "orange", ["handwritten"])))
    assert repo.get_record(conn, rid2)["status"] == "pending"


def test_flags_stored_as_codes(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(id=("1", "orange", ["handwritten", "conflict"], ["2"])))
    st = repo.get_record(conn, rid)["fields"]["id"]
    assert st["flags"] == ["handwritten", "conflict"] and st["alternatives"] == ["2"]


def test_edit_confirms_and_audits(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(first_name=(None, "orange", ["handwritten_unconfirmed"])))
    assert repo.get_record(conn, rid)["status"] == "pending"
    repo.edit_field(conn, rid, "first_name", "רונית")
    rec = repo.get_record(conn, rid)
    f = rec["fields"]["first_name"]
    assert rec["first_name"] == "רונית" and f["human_edited"] and f["cell_confirmed"] and f["color"] == "confirmed"
    assert rec["status"] == "ready"
    last = repo.audit_entries(conn, rid)[-1]
    assert (last["action"], last["field"], last["old"], last["new"]) == ("edit", "first_name", None, "רונית")


def test_confirm_same_value_is_not_an_edit(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(id=("123456789", "orange", ["handwritten"])))
    repo.edit_field(conn, rid, "id", "123456789")
    f = repo.get_record(conn, rid)["fields"]["id"]
    assert f["cell_confirmed"] and not f["human_edited"]
    assert repo.audit_entries(conn, rid)[-1]["action"] == "confirm"


def test_edit_center_rewrites_rows(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields())
    repo.edit_field(conn, rid, "center", "111111")
    assert repo.get_record(conn, rid)["center"] == "111111"
    assert conn.execute("SELECT COUNT(*) FROM record_centers WHERE record_id=?", (rid,)).fetchone()[0] == 1


def test_reprocess_keeps_human_edit_but_updates_machine(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(first_name=(None, "orange", ["handwritten_unconfirmed"])))
    repo.edit_field(conn, rid, "first_name", "רונית")
    rid2, outcome = repo.save_machine_record(conn, uid, 1, 0, green_fields(first_name=("שרה", "green"), sender=("מכבי", "green")))
    assert rid2 == rid and outcome == "updated"
    rec = repo.get_record(conn, rid)
    assert rec["first_name"] == "רונית" and rec["sender"] == "מכבי"
    assert rec["fields"]["first_name"]["machine_value"] == "שרה" and rec["fields"]["first_name"]["color"] == "confirmed"


def test_approved_record_never_overwritten(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields())
    repo.approve_record(conn, rid)
    _, outcome = repo.save_machine_record(conn, uid, 1, 0, green_fields(first_name=("אחר", "green")))
    assert outcome == "skipped_approved"
    rec = repo.get_record(conn, rid)
    assert rec["first_name"] == "דנה" and rec["status"] == "approved" and rec["reviewed_at"]
    with pytest.raises(repo.RecordLocked):
        repo.edit_field(conn, rid, "first_name", "x")
    assert repo.prune_page_records(conn, uid, 1, 0) == 0


def test_unapprove_recomputes_and_audits(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(id=(None, "orange", ["x"])))
    repo.approve_record(conn, rid)
    repo.unapprove_record(conn, rid)
    assert repo.get_record(conn, rid)["status"] == "pending"
    assert [a["action"] for a in repo.audit_entries(conn, rid)][-2:] == ["approve", "unapprove"]


def test_revert_field(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(id=("123456789", "orange", ["handwritten"])))
    repo.edit_field(conn, rid, "id", "999")
    repo.revert_field(conn, rid, "id", color="orange")
    rec = repo.get_record(conn, rid)
    assert rec["national_id"] == "123456789" and rec["fields"]["id"]["color"] == "orange" and not rec["fields"]["id"]["cell_confirmed"]


def test_version_conflict(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields())
    v = repo.get_record(conn, rid)["version"]
    repo.edit_field(conn, rid, "sender", "מכבי", expected_version=v)
    with pytest.raises(repo.StaleVersion):
        repo.edit_field(conn, rid, "sender", "לאומית", expected_version=v)


def test_prune_removes_stale_untouched_rows(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    repo.save_machine_record(conn, uid, 1, 0, green_fields())
    r1, _ = repo.save_machine_record(conn, uid, 1, 1, green_fields())
    assert repo.prune_page_records(conn, uid, 1, 1) == 1
    assert repo.get_record(conn, r1) is None
    assert repo.audit_entries(conn, r1)[-1]["action"] == "delete"


def test_invalid_field_and_empty_value(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields())
    with pytest.raises(ValueError):
        repo.edit_field(conn, rid, "bogus", "x")
    with pytest.raises(ValueError):
        repo.edit_field(conn, rid, "id", "  ")


def test_search_filter_sort_paginate(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 3)
    repo.save_machine_record(conn, uid, 1, 0, green_fields())
    repo.save_machine_record(conn, uid, 2, 0, green_fields(first_name=("אבי", "green"), last_name=("לוי", "green"), id=("55500011", "green"),
                                                           center=("700001", "green"), date=("02.07.2026", "green"), sender=("מכבי", "green"),
                                                           commitment=("222333", "green")))
    rid3, _ = repo.save_machine_record(conn, uid, 3, 0, green_fields(date=("30.05.2026", "orange", ["handwritten"]), commitment=("999", "green")))
    rows, total = repo.search_records(conn, search="לוי")
    assert total == 1 and rows[0]["page_no"] == 2
    assert repo.search_records(conn, search="55500011")[1] == 1
    assert repo.search_records(conn, search="222333")[1] == 1
    assert repo.search_records(conn, search="944964")[1] == 2          # מרכזי שני ברשימה
    assert repo.search_records(conn, search="דנה כהן")[1] == 2          # שם מלא
    assert repo.search_records(conn, search="%")[1] == 0                 # תו מיוחד אינו wildcard
    assert repo.search_records(conn, senders=["מכבי"])[1] == 1
    assert repo.search_records(conn, statuses=["pending"])[1] == 1
    assert repo.search_records(conn, date_from="01.06.2026", date_to="30.06.2026")[1] == 1
    assert repo.search_records(conn, date_from="01.06.2026")[1] == 2
    rows, total = repo.search_records(conn, sort="date", descending=True, limit=2, offset=0)
    assert total == 3 and [r["receipt_date"] for r in rows] == ["02.07.2026", "18.06.2026"]
    rows, _ = repo.search_records(conn, sort="date", descending=True, limit=2, offset=2)
    assert [r["receipt_date"] for r in rows] == ["30.05.2026"]
    assert repo.status_counts(conn) == {"pending": 1, "ready": 2, "approved": 0}
    assert repo.list_senders(conn) == ["כללית", "מכבי"]


def test_sql_injection_in_search_is_inert(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    repo.save_machine_record(conn, uid, 1, 0, green_fields())
    assert repo.search_records(conn, search="'; DROP TABLE records; --")[1] == 0
    assert repo.search_records(conn, sort="id; DROP TABLE records")[1] == 1
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_connect_creates_file_under_env_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "sub" / "x.db"))
    c = repo.connect()
    c.close()
    assert (tmp_path / "sub" / "x.db").exists()


def test_repeated_identical_confirm_is_a_noop(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(id=("123", "orange", ["handwritten"])))
    repo.edit_field(conn, rid, "id", "999")
    before = repo.get_record(conn, rid)
    n_audit = len(repo.audit_entries(conn, rid))
    repo.edit_field(conn, rid, "id", "999")                                   # לחיצה כפולה
    repo.edit_field(conn, rid, "id", "999", expected_version=before["version"] - 1)     # גם עם גרסה שהתיישנה: בלי שגיאה
    after = repo.get_record(conn, rid)
    assert after["version"] == before["version"] and after["updated_at"] == before["updated_at"]
    assert len(repo.audit_entries(conn, rid)) == n_audit
    repo.edit_field(conn, rid, "id", "1000")                                  # ערך אחר כן נרשם
    assert len(repo.audit_entries(conn, rid)) == n_audit + 1


def test_confirming_machine_value_twice_is_a_noop_but_first_confirm_counts(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(id=("123", "orange", ["handwritten"])))
    repo.edit_field(conn, rid, "id", "123")
    v = repo.get_record(conn, rid)["version"]
    repo.edit_field(conn, rid, "id", "123")
    assert repo.get_record(conn, rid)["version"] == v
    assert [a["action"] for a in repo.audit_entries(conn, rid)].count("confirm") == 1


def test_same_value_after_revert_is_a_real_confirm_again(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields(id=("123", "orange", ["handwritten"])))
    repo.edit_field(conn, rid, "id", "999")
    repo.revert_field(conn, rid, "id")
    v = repo.get_record(conn, rid)["version"]
    repo.edit_field(conn, rid, "id", "999")
    assert repo.get_record(conn, rid)["version"] == v + 1


def test_approved_record_with_same_confirmed_value_is_silent_noop(conn):
    uid = repo.create_upload(conn, "a.pdf", "s1", 1)
    rid, _ = repo.save_machine_record(conn, uid, 1, 0, green_fields())
    repo.edit_field(conn, rid, "sender", "מכבי")
    repo.approve_record(conn, rid)
    repo.edit_field(conn, rid, "sender", "מכבי")             # לחיצה כפולה שהגיעה אחרי האישור: לא שגיאת נעילה
    with pytest.raises(repo.RecordLocked):
        repo.edit_field(conn, rid, "sender", "אחר")
