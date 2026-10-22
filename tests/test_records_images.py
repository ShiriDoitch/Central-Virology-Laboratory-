"""כרטיס הרשומה מציג את תמונת העמוד השמורה (ניתנת להגדלה) ואת חיתוך כל שדה, באותו רכיב כמו מסך העיבוד; בלי תמונה: הודעה, והעריכה
והאישור ממשיכים לעבוד. בלי API."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import page_store, repo, service
from tests.test_repo import confirm_flagged_cells
from tests.test_page_images import make_pdf, page_result

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    db = tmp_path / "r.db"
    monkeypatch.setenv("APP_DB_PATH", str(db))
    conn = repo.connect(db)
    pdf = make_pdf(tmp_path / "t.pdf", pages=1)
    store = service.Persister(conn, "f.pdf", b"x")
    store.start(1)
    res = page_result(1, n_rows=1)
    store.page(res)
    store.save_image(pdf, res)
    store.finish()
    rid = repo.page_records(conn, store.upload_id, 1)[0]["id"]
    return conn, store.upload_id, rid


def card(rid):
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    at.session_state["rec_open"] = rid
    at.run()
    assert not at.exception
    return at


def test_card_with_image_shows_zoomable_page_and_field_crops(seeded):
    conn, uid, rid = seeded
    at = card(rid)
    assert not any(service.IMAGE_MISSING_TEXT in i.value for i in at.info)
    keys = {s.key for s in at.slider}
    assert f"rec_pagezoom_{rid}" in keys                                   # העמוד המלא, ניתן להגדלה
    assert f"rec_zoom_{rid}_id" in keys                 # חיתוך מאומת מקומית מול הברקוד (אותו רכיב כמו במסך העיבוד)
    assert f"rec_zoom_{rid}_first_name" in keys         # אין ברקוד לשם, אבל יש אזור שהמודל הצהיר עליו: חיתוך משוער, לא מאומת
    assert any("אזור משוער" in c.value for c in at.caption)               # ההערה על החיתוך הלא-מאומת
    assert any("המיקום המדויק לא ידוע" in c.value for c in at.caption)    # מרכזי/התחייבות/תאריך: בלי שום אזור בעמוד הזה
    assert f"rec_zoom_{rid}_sender" not in keys                            # לשולח אין אזור כלל
    html = " ".join(m.value for m in at.markdown)
    assert html.count("name-zoom") >= 2 and "data:image/jpeg;base64" in html
    at.slider(key=f"rec_pagezoom_{rid}").set_value(300).run()
    assert not at.exception and "data-width=\"2160\"" in " ".join(m.value for m in at.markdown)       # 720 * 300% בפיקסלים


def test_card_without_image_shows_message_and_editing_still_works(seeded):
    conn, uid, rid = seeded
    page_store.delete(uid, 1)
    at = card(rid)
    assert any(service.IMAGE_MISSING_TEXT in i.value for i in at.info)
    assert not [s for s in at.slider if s.key and s.key.startswith("rec_zoom_")]
    at.text_input(key=f"rec_in_{rid}_sender").set_value("מכבי").run()
    next(b for b in at.button if b.key == f"rec_save_{rid}").click().run()
    assert repo.get_record(conn, rid)["sender"] == "מכבי"
    confirm_flagged_cells(conn, rid)                                       # אחרת כפתור האישור נעול
    at.run()
    next(b for b in at.button if b.key == f"rec_appr_{rid}").click().run()
    assert repo.get_record(conn, rid)["status"] == "approved"


def test_card_survives_a_corrupt_image_file(seeded):
    conn, uid, rid = seeded
    page_store.image_path(uid, 1).write_bytes(b"not a jpeg")
    at = card(rid)
    assert not at.exception                                               # תמונה פגומה = כרטיס בלי חיתוכים, לא קריסה
    at.text_input(key=f"rec_in_{rid}_sender").set_value("לאומית").run()
    next(b for b in at.button if b.key == f"rec_save_{rid}").click().run()
    assert repo.get_record(conn, rid)["sender"] == "לאומית"


def test_cancelling_approval_after_the_image_was_deleted_shows_the_missing_message(seeded):
    conn, uid, rid = seeded
    confirm_flagged_cells(conn, rid)                                           # אחרת כפתור האישור נעול
    at = card(rid)
    next(b for b in at.button if b.key == f"rec_appr_{rid}").click().run()      # העמוד אושר במלואו: התמונה נמחקת
    assert not page_store.exists(uid, 1)
    assert any(service.IMAGE_MISSING_TEXT in i.value for i in at.info)
    next(b for b in at.button if b.key == f"rec_unappr_{rid}").click().run()
    assert any(service.IMAGE_MISSING_TEXT in i.value for i in at.info)
    at.text_input(key=f"rec_in_{rid}_sender").set_value("כללית").run()
    next(b for b in at.button if b.key == f"rec_save_{rid}").click().run()
    assert repo.get_record(conn, rid)["sender"] == "כללית"


def test_processing_screen_evidence_still_uses_the_shared_component():
    sample = Path("outputs/clean_part1_v4b")
    if not sample.exists() or not Path("data/clean_part1.pdf").exists():
        pytest.skip("needs the saved sample run")
    from tests.test_app_confirm import loaded_app
    at = loaded_app(5, 'ת"ז')
    # אין ברקוד שמאמת את הת"ז בעמוד הזה (CLAUDE.md סעיף 22), אבל יש אזור שהמודל הצהיר עליו (patient): חיתוך משוער,
    # מסומן ככזה ולא כאימות (CLAUDE.md סעיף 24)
    assert any(s.key == "zoom_5_patient" for s in at.slider)
    assert any("אזור משוער" in c.value for c in at.caption)
