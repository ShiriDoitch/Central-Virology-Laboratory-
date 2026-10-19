"""שמירה בזמן החילוץ (src/service.py + process_upload): בלי API. נשען על הריצה השמורה outputs/clean_part1_v4b (קיימת רק אצל המפתחת)."""
import json
from pathlib import Path

import pytest

from src import repo, service
from src.export import build_rows

RUN = Path("outputs/clean_part1_v4b")
pytestmark = pytest.mark.skipif(not RUN.exists(), reason="הריצה השמורה לא קיימת")


def saved_pages(n=26):
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(RUN.glob("p*.json"), key=lambda x: int(x.stem[1:]))][:n]


@pytest.fixture
def conn():
    c = repo.connect(":memory:")
    yield c
    c.close()


def persist(conn, pages, data=b"pdf-bytes"):
    store = service.Persister(conn, "f.pdf", data)
    store.start(len(pages))
    for p in pages:
        store.page(p)
    store.finish()
    return store


def test_rows_saved_match_export_rows(conn):
    pages = saved_pages()
    store = persist(conn, pages)
    expected = sum(len(build_rows(p)) for p in pages if (p.get("pass1") or {}).get("ok"))
    rows, total = repo.search_records(conn, upload_id=store.upload_id, limit=None)
    assert total == expected == len(rows) > 20
    assert store.errors == 0 and repo.find_upload(conn, store.sha)["completed_at"]


def test_values_flags_and_status_stored(conn):
    pages = saved_pages()
    store = persist(conn, pages)
    p = next(p for p in pages if build_rows(p))
    er = build_rows(p)[0]
    rec = repo.get_record(conn, repo.find_record(conn, store.upload_id, p["page"], er.index))
    assert rec["commitment_no"] == (er.cells["commitment"].value or None)
    assert rec["fields"]["id"]["flags"] == er.cells["id"].flags
    assert rec["status"] in ("pending", "ready")


def test_same_file_is_found_not_reprocessed(conn):
    pages = saved_pages()
    persist(conn, pages, b"same")
    found = service.find_completed_upload(conn, b"same")
    assert found and found["record_count"] > 20
    assert service.find_completed_upload(conn, b"other") is None


def test_interrupted_upload_is_not_complete_and_resumes_without_duplicates(conn):
    pages = saved_pages()
    store = service.Persister(conn, "f.pdf", b"x")
    store.start(len(pages))
    for p in pages[:5]:
        store.page(p)                                    # נקטע באמצע: בלי finish
    assert service.find_completed_upload(conn, b"x") is None
    first = repo.search_records(conn, limit=None)[1]
    persist(conn, pages, b"x")                           # עיבוד חוזר של אותו קובץ
    total = repo.search_records(conn, limit=None)[1]
    assert total >= first and total == sum(len(build_rows(p)) for p in pages if (p.get("pass1") or {}).get("ok"))
    assert len(repo.list_uploads(conn)) == 1


def test_reprocess_preserves_approved_and_edits(conn):
    pages = saved_pages()
    store = persist(conn, pages, b"y")
    rows, _ = repo.search_records(conn, upload_id=store.upload_id, limit=None)
    approved, edited = rows[0], rows[1]
    repo.approve_record(conn, approved["id"])
    repo.edit_field(conn, edited["id"], "sender", "ידני")
    persist(conn, pages, b"y")
    assert repo.get_record(conn, approved["id"])["status"] == "approved"
    assert repo.get_record(conn, edited["id"])["sender"] == "ידני"


def test_failed_pages_and_non_forms_create_no_rows(conn):
    store = service.Persister(conn, "f.pdf", b"z")
    store.start(2)
    store.page({"page": 1, "pass1": {"ok": False, "error": "X"}, "pass2": None})
    store.page({"page": 2, "pass1": None, "pass2": None})
    store.finish()
    assert repo.search_records(conn)[1] == 0 and store.errors == 0


def test_db_error_does_not_raise_and_blocks_completion(conn):
    store = service.Persister(conn, "f.pdf", b"w")
    store.start(1)
    conn.execute("DROP TABLE field_states")
    store.page(next(p for p in saved_pages() if build_rows(p)))
    store.finish()
    assert store.errors == 1 and repo.find_upload(conn, store.sha)["completed_at"] is None


def test_process_upload_calls_store_hooks(monkeypatch, tmp_path):
    from src import upload, pipeline
    import pymupdf

    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page()
    pdf = doc.tobytes()
    calls = []

    class Store:
        def start(self, n): calls.append(("start", n))
        def page(self, r): calls.append(("page", r["page"]))
        def finish(self): calls.append(("finish",))

    class Bar:
        def progress(self, *a, **k): pass

    monkeypatch.setattr(pipeline, "process_page", lambda path, p: {"page": p, "pass1": {"ok": False}, "pass2": None})
    monkeypatch.setattr(upload, "UPLOAD_TMP_DIR", tmp_path)
    upload.process_upload("a.pdf", pdf, Bar(), store=Store())
    assert calls == [("start", 2), ("page", 1), ("page", 2), ("finish",)]


# ---------- שלב 3 ----------

def first_rows(conn, pages, store):
    p = next(p for p in pages if len(build_rows(p)) >= 1)
    return p, build_rows(p)


def test_save_override_roundtrip_and_load(conn):
    pages = saved_pages()
    store = persist(conn, pages)
    p, rows = first_rows(conn, pages, store)
    service.save_override(conn, store.upload_id, p["page"], "sender", "ידני", p)
    service.save_override(conn, store.upload_id, p["page"], "commitment#0", "5551234", p)
    ov = service.load_overrides(conn, store.upload_id)
    assert ov[(p["page"], "sender")] == "ידני" and ov[(p["page"], "commitment#0")] == "5551234"
    rid = repo.find_record(conn, store.upload_id, p["page"], 0)
    assert repo.get_record(conn, rid)["commitment_no"] == "5551234"


def test_clear_override_restores_machine_value_and_color(conn):
    pages = saved_pages()
    store = persist(conn, pages)
    p, rows = first_rows(conn, pages, store)
    before = repo.get_record(conn, repo.find_record(conn, store.upload_id, p["page"], 0))
    service.save_override(conn, store.upload_id, p["page"], "date", "01.01.2026", p)
    service.save_override(conn, store.upload_id, p["page"], "date", None, p)
    after = repo.get_record(conn, before["id"])
    assert after["receipt_date"] == before["receipt_date"]
    assert after["fields"]["date"]["color"] == before["fields"]["date"]["color"]
    assert (p["page"], "date") not in service.load_overrides(conn, store.upload_id)


def test_page_level_override_applies_to_every_row_of_page(conn):
    pages = saved_pages()
    store = persist(conn, pages)
    multi = next((p for p in pages if len(build_rows(p)) > 1), None)
    if multi is None:
        pytest.skip("אין עמוד עם כמה שורות בריצה")
    assert service.save_override(conn, store.upload_id, multi["page"], "id", "123456", multi) == len(build_rows(multi))


def test_approved_row_blocks_ui_edits_and_survives(conn):
    pages = saved_pages()
    store = persist(conn, pages)
    p, _ = first_rows(conn, pages, store)
    info = service.row_info(conn, store.upload_id, p["page"], 0)
    service.approve_row(conn, info["id"])
    with pytest.raises(service.RecordLocked):
        service.save_override(conn, store.upload_id, p["page"], "sender", "x", p)
    assert service.row_info(conn, store.upload_id, p["page"], 0)["status"] == "approved"
    service.unapprove_row(conn, info["id"])
    service.save_override(conn, store.upload_id, p["page"], "sender", "x", p)


def test_unknown_field_rejected(conn):
    pages = saved_pages()
    store = persist(conn, pages)
    p, _ = first_rows(conn, pages, store)
    with pytest.raises(ValueError):
        service.save_override(conn, store.upload_id, p["page"], "bogus", "x", p)
