"""תמונות העמודים השמורות (src/page_store.py + service): נכתבות בשמירה, לא נכתבות כשהאפשרות כבויה, נמחקות רק כשכל רשומות העמוד
אושרו, ונמחקות בניקוי כללי. נתיבים מספריים בלבד. בלי API."""
import io

import pymupdf
import pytest
from PIL import Image

from src import page_store, repo, service

SECRET_NAME = "דנה-כהן-123456789.pdf"
SECRET_ID = "123456782"


def page_result(page=1, n_rows=1):
    numbers = [{"value": str(107646 + i), "label": "התחייבות", "source": "printed", "confidence": 0.95} for i in range(n_rows)]
    return {"page": page, "boxes": {"patient": {"fractions": [0.1, 0.1, 0.9, 0.3]}},
            "barcodes": [{"format": "Code128", "text": SECRET_ID, "box": [0.1, 0.1, 0.5, 0.15]}],   # מאמת מקומית את הת"ז בלבד
            "pass1": {"ok": True, "is_commitment_form": True, "page_quality": "ok", "numbers": numbers,
                      "id_numbers": [{"value": SECRET_ID, "label": "ת.ז", "source": "printed", "confidence": 0.99}]},
            "pass2": None}


def make_pdf(path, pages=1):
    doc = pymupdf.open()
    for _ in range(pages):
        p = doc.new_page()
        p.insert_text((60, 120), "form", fontsize=30)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def conn():
    c = repo.connect(":memory:")
    yield c
    c.close()


def persist(conn, tmp_path, n_rows=1, pages=(1,), filename=SECRET_NAME):
    pdf = make_pdf(tmp_path / "tmp.pdf", pages=max(pages))
    store = service.Persister(conn, filename, b"bytes-" + str(n_rows).encode())
    store.start(len(pages))
    for p in pages:
        res = page_result(p, n_rows)
        store.page(res)
        store.save_image(pdf, res)
    store.finish()
    return store


def all_files():
    root = page_store.root()
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def test_image_and_regions_written_on_persist(conn, tmp_path):
    store = persist(conn, tmp_path)
    path = page_store.image_path(store.upload_id, 1)
    assert path.is_file() and path.parent.name == str(store.upload_id)
    img = Image.open(io.BytesIO(path.read_bytes()))
    assert img.size[0] > 100
    regions = repo.get_page_regions(conn, store.upload_id, 1)
    assert regions["id"]["verified"] is True                      # מאומת מקומית מול הברקוד
    assert regions["first_name"]["verified"] is False             # אין ברקוד לשם: קירוב בלבד, אזור ה-box שהמודל הצהיר עליו


def test_paths_are_numeric_only_and_contain_no_name_or_id(conn, tmp_path):
    persist(conn, tmp_path)
    files = all_files()
    assert files
    for f in files:
        rel = f.relative_to(page_store.root())
        folder, name = rel.parts
        assert folder.isdigit() and name.startswith("p") and name.endswith(".jpg") and name[1:-4].isdigit(), rel
        assert SECRET_NAME not in str(f) and SECRET_ID not in str(f) and "דנה" not in str(f)


def test_nothing_written_when_store_page_images_is_false(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_PAGE_IMAGES", "0")
    store = persist(conn, tmp_path)
    assert all_files() == [] and not page_store.root().exists()
    assert repo.get_page_regions(conn, store.upload_id, 1) is None
    assert repo.search_records(conn)[1] == 1                      # הרשומות עצמן נשמרו


def test_failed_pages_and_pages_without_records_store_no_image(conn, tmp_path):
    pdf = make_pdf(tmp_path / "t.pdf")
    store = service.Persister(conn, "f.pdf", b"x")
    store.start(1)
    bad = {"page": 1, "pass1": {"ok": False}, "pass2": None}
    store.page(bad)
    assert store.save_image(pdf, bad) is False and all_files() == []


def test_image_is_stored_after_the_rotation_that_was_applied(conn, tmp_path):
    pdf = make_pdf(tmp_path / "t.pdf")
    store = service.Persister(conn, "f.pdf", b"x")
    store.start(1)
    res = page_result(1)
    res["rotation"] = {"applied": 90}
    store.page(res)
    store.save_image(pdf, res)
    w, h = Image.open(io.BytesIO(page_store.read(store.upload_id, 1))).size
    assert w > h                                                   # עמוד לאורך סובב לרוחב


def test_delete_functions(conn, tmp_path):
    store = persist(conn, tmp_path, pages=(1, 2))
    assert page_store.exists(store.upload_id, 1) and page_store.exists(store.upload_id, 2)
    assert service.delete_page_image(store.upload_id, 1) is True
    assert service.delete_page_image(store.upload_id, 1) is False          # שוב: לא קורס
    assert page_store.exists(store.upload_id, 2)
    assert service.delete_upload_images(store.upload_id) == 1
    assert not (page_store.root() / str(store.upload_id)).exists()


def first_ids(conn, store):
    return [r["id"] for r in repo.page_records(conn, store.upload_id, 1)]


def test_image_kept_while_any_record_on_the_page_is_open(conn, tmp_path):
    store = persist(conn, tmp_path, n_rows=2)
    a, b = first_ids(conn, store)
    service.approve_row(conn, a)
    assert page_store.exists(store.upload_id, 1)                  # b עדיין ממתינה / מוכנה


def test_image_deleted_after_the_last_record_is_approved(conn, tmp_path):
    store = persist(conn, tmp_path, n_rows=2)
    a, b = first_ids(conn, store)
    service.approve_row(conn, a)
    service.approve_row(conn, b)
    assert not page_store.exists(store.upload_id, 1)
    assert repo.get_record(conn, a)["status"] == "approved"


def test_single_record_page_image_deleted_on_approval_and_other_pages_untouched(conn, tmp_path):
    store = persist(conn, tmp_path, pages=(1, 2))
    r1 = repo.page_records(conn, store.upload_id, 1)[0]["id"]
    service.approve_row(conn, r1)
    assert not page_store.exists(store.upload_id, 1) and page_store.exists(store.upload_id, 2)


def test_keep_images_after_approval_true_keeps_the_image(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("KEEP_IMAGES_AFTER_APPROVAL", "1")
    store = persist(conn, tmp_path)
    service.approve_row(conn, first_ids(conn, store)[0])
    assert page_store.exists(store.upload_id, 1)


def test_approve_twice_and_cancel_approval_do_not_break_when_image_is_gone(conn, tmp_path):
    store = persist(conn, tmp_path)
    rid = first_ids(conn, store)[0]
    service.approve_row(conn, rid)
    service.approve_row(conn, rid)                                  # לחיצה כפולה
    service.unapprove_row(conn, rid)
    assert not page_store.exists(store.upload_id, 1)
    image, crops = service.record_images(conn, repo.get_record(conn, rid))
    assert image is None and crops == {}                            # הכרטיס יציג הודעה, העריכה ממשיכה
    service.save_override(conn, store.upload_id, 1, "sender", "מכבי", page_result(1))


def test_record_images_returns_crops_from_the_stored_image(conn, tmp_path):
    store = persist(conn, tmp_path)
    rid = first_ids(conn, store)[0]
    image, crops = service.record_images(conn, repo.get_record(conn, rid))
    assert image and set(crops) == {"first_name", "last_name", "id", "center", "date", "sender", "commitment"}
    id_crop, id_verified = crops["id"]
    assert id_verified is True and id_crop and Image.open(io.BytesIO(id_crop)).size[0] > 50       # מאומת מקומית מול הברקוד
    name_crop, name_verified = crops["first_name"]
    assert name_verified is False and name_crop                  # קירוב: אזור ה-box שהמודל הצהיר עליו (patient), לא אומת
    assert crops["sender"] == (None, False)                         # אין אזור לשולח


def test_delete_all_leaves_nothing_in_db_or_on_disk(conn, tmp_path):
    store = persist(conn, tmp_path, n_rows=2, pages=(1, 2))
    service.approve_row(conn, first_ids(conn, store)[0])
    counts = service.delete_all_data(conn)
    assert counts["records"] >= 4 and counts["images"] == 2 and counts["uploads"] == 1
    for table in ("uploads", "records", "field_states", "record_centers", "page_regions", "audit_log"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert all_files() == [] and not page_store.root().exists()


def test_delete_all_removes_only_numeric_upload_folders_and_jpg_names(conn, tmp_path):
    root = page_store.root()
    (root / "123").mkdir(parents=True)
    (root / "123" / "p1.jpg").write_bytes(b"x")
    (root / "notes").mkdir()
    (root / "notes" / "keep.txt").write_text("keep")
    (root / "124").mkdir()
    (root / "124" / "other.txt").write_text("keep")
    service.delete_all_data(conn)
    assert not (root / "123" / "p1.jpg").exists()
    assert (root / "notes" / "keep.txt").exists() and (root / "124" / "other.txt").exists()   # לא מוחקים מה שאינו שלנו
