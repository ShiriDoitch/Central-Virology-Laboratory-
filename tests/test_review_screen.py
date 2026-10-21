"""מסך "בדיקה במבט אחד" (review_screen.py דרך app.py): פתיחת הבדיקה מהרשומות, מה מוצג בתא, אישור ותיקון
(אותם נתיבים של src/service.py, כולל יומן שינויים), דלג וחזרה, וסוף הבדיקה. בלי קריאות API: מסד זמני שנזרע ביד.

הבדיקה רצה גם ב-PRIVACY_MODE=production, וגם בלי תמונות עמוד שמורות (כמו בפריסה מוארחת עם מסד ארעי)."""
import io
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

import review_screen
from src import page_store, repo, service
from src.confirm import md_text
from test_guided_review import BLANK, ORANGE, YELLOW, cells, seed

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def jpeg(size=(240, 320)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (250, 248, 240)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "rv.db"))
    return repo.connect(tmp_path / "rv.db")


def records_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    return at


def start_review(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, at.exception
    at.button(key="rev_start").click().run()
    assert not at.exception, at.exception
    return at


def current(at: AppTest):
    return at.session_state["rv_session"].current


def submit(at: AppTest, value: str | None = None) -> AppTest:
    """מה ש-Enter בשדה הקלט עושה: שולח את הטופס עם מה שבשדה (כפתור השליחה הוא אותו נתיב בדיוק)."""
    item = current(at)
    if value is not None:
        at.text_input(key=f"rv_in_{item.record_id}_{item.field}").set_value(value)
    next(b for b in at.button if b.key.startswith("FormSubmitter:")).click().run()
    assert not at.exception, at.exception
    return at


def texts(at: AppTest) -> str:
    """כל ה-markdown של המסך חוץ מבלוק העיצוב (ה-CSS מכיל את שמות המחלקות עצמן, ולכן "היה מוצא" כל סימון)."""
    return "\n".join(m.value for m in at.markdown if not m.value.startswith("<style>"))


# ---------- פתיחה ----------

def test_the_bar_starts_a_review_and_shows_the_first_cell(db):
    seed(db, {1: [cells(id=ORANGE, center=BLANK)], 2: [cells()]})
    at = start_review(records_app())
    item = current(at)
    assert (item.page_no, item.field) == (1, "id")                      # סדר השדות: ת"ז לפני מרכזי
    assert len(at.session_state["rv_session"].items) == 2                # העמוד הירוק לא נכנס
    body = texts(at)
    assert "בדיקה במבט אחד" in body and "טופס <b>1</b> מתוך 1" in body and "נשארו 2 תאים" in body
    assert "סתירה בין קריאות" in body                                    # הדגל בעברית
    assert at.text_input(key="rv_in_1_id").value == "11223344"           # מה שהמערכת קראה, כהצעה
    assert [b.key for b in at.button if b.key in ("rv_skip", "rv_back", "rv_end")] == ["rv_skip", "rv_back", "rv_end"]


def test_the_review_replaces_the_table_and_the_data_management_box(db):
    seed(db, {1: [cells(id=ORANGE)]})
    at = start_review(records_app())
    assert at.dataframe == []
    assert [b.key for b in at.button if b.key in ("rec_wipe_all", "rev_start")] == []
    at.button(key="rv_end").click().run()
    at.button(key="rv_exit").click().run()
    assert not at.exception and len(at.dataframe) == 1                   # חזרה לטבלה


def test_the_button_is_disabled_when_nothing_needs_review(db):
    seed(db, {1: [cells()]})
    at = records_app()
    at.run()
    assert at.button(key="rev_start").disabled


# ---------- אישור ותיקון ----------

def test_enter_on_the_unchanged_suggestion_is_recorded_as_a_confirmation(db):
    uid = seed(db, {1: [cells(sender=ORANGE)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = start_review(records_app())
    submit(at)                                                           # בלי לשנות את מה שהמערכת קראה
    rec = repo.get_record(db, rid)
    assert rec["sender"] == "מכבי"
    assert rec["fields"]["sender"]["cell_confirmed"] and not rec["fields"]["sender"]["human_edited"]
    assert rec["fields"]["sender"]["color"] == "confirmed"
    assert [a["action"] for a in repo.audit_entries(db, rid) if a["field"] == "sender"] == ["confirm"]
    assert at.session_state["rv_session"].done                           # ההתקדמות אוטומטית לתא הבא


def test_a_changed_value_is_recorded_as_an_edit(db):
    uid = seed(db, {1: [cells(first_name=ORANGE)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = start_review(records_app())
    submit(at, "אברהם")
    rec = repo.get_record(db, rid)
    assert rec["first_name"] == "אברהם" and rec["fields"]["first_name"]["human_edited"]
    assert [a["action"] for a in repo.audit_entries(db, rid) if a["field"] == "first_name"] == ["edit"]
    assert rec["fields"]["first_name"]["machine_value"] == "ישראל"          # קריאת המכונה נשמרת כפי שהייתה


def test_the_typed_value_is_normalized_like_everywhere_else(db):
    uid = seed(db, {1: [cells(id=ORANGE)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = start_review(records_app())
    submit(at, " 12-34 56 ")
    assert repo.get_record(db, rid)["national_id"] == "123456"


def test_clicking_an_alternative_confirms_that_reading(db):
    uid = seed(db, {1: [cells(center={"color": "orange", "flags": ["center_mismatch"], "alternatives": ["944964"]})]})
    rid = repo.find_record(db, uid, 1, 0)
    at = start_review(records_app())
    at.button(key="rv_alt_0").click().run()
    assert not at.exception
    assert repo.get_record(db, rid)["center"] == "944964"
    assert at.session_state["rv_session"].done


def test_an_invalid_value_is_not_saved_and_the_cell_stays(db):
    uid = seed(db, {1: [cells(id=ORANGE)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = start_review(records_app())
    submit(at, "abc")
    assert repo.get_record(db, rid)["national_id"] == "11223344"
    assert any("לא תקין" in e.value for e in at.error)
    assert current(at).field == "id"                                     # נשארים על אותו תא


def test_an_empty_input_asks_for_a_value_and_writes_nothing(db):
    uid = seed(db, {1: [cells(id=BLANK)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = start_review(records_app())
    assert at.text_input(key="rv_in_1_id").value == ""                   # תא ריק נשאר ריק: בלי ניחוש בשדה
    submit(at)
    assert repo.get_record(db, rid)["national_id"] is None
    assert any("דלגי" in w.value for w in at.warning)
    assert current(at).field == "id"


def test_the_review_never_approves_a_record(db):
    """אישור כל התאים הופך את הרשומה ל"מוכנה" לפי הכללים הקיימים, אבל לא ל"אושרה": זה נשאר החלטה של המשתמשת."""
    uid = seed(db, {1: [cells(id=ORANGE, date=ORANGE)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = start_review(records_app())
    submit(at)
    assert repo.get_record(db, rid)["status"] == "pending"               # עוד נשאר תא לבדיקה
    submit(at)
    assert repo.get_record(db, rid)["status"] == "ready"
    assert at.session_state["rv_session"].done


# ---------- דלג, חזרה, סיום ----------

def test_skip_sends_the_cell_to_the_end_and_it_comes_back(db):
    seed(db, {1: [cells(first_name=ORANGE, id=ORANGE)]})
    at = start_review(records_app())
    assert current(at).field == "first_name"
    at.button(key="rv_skip").click().run()
    assert current(at).field == "id"
    submit(at)
    assert current(at).field == "first_name"                             # התא שדולג חזר בסוף


def test_back_returns_to_the_previous_cell(db):
    seed(db, {1: [cells(first_name=ORANGE, id=ORANGE)]})
    at = start_review(records_app())
    assert at.button(key="rv_back").disabled                             # בתא הראשון אין לאן לחזור
    submit(at, "אברהם")
    assert current(at).field == "id"
    at.button(key="rv_back").click().run()
    assert current(at).field == "first_name"
    assert at.text_input(key="rv_in_1_first_name").value == "אברהם"      # מה שנשמר מוצג


def test_the_summary_shows_measured_numbers_only(db):
    seed(db, {1: [cells(id=ORANGE, date=ORANGE)]})
    at = start_review(records_app())
    submit(at)
    at.button(key="rv_end").click().run()
    body = texts(at)
    assert "הבדיקה נעצרה" in body and "נשארו 1 תאים" in body
    assert "תאים שאושרו או תוקנו</span><b>1</b>" in body and "טפסים שנבדקו</span><b>1</b>" in body
    assert "זמן הבדיקה" in body and "שניות לתא" in body
    for invented in ("נחסך", "נחסכו", "חוסך", "הערכה", "משוער"):
        assert invented not in body
    at.button(key="rv_resume").click().run()                             # אפשר להמשיך מאותה נקודה
    assert not at.exception and current(at).field == "date"


def test_finishing_the_whole_queue_shows_the_end_screen(db):
    seed(db, {1: [cells(id=ORANGE)]})
    at = start_review(records_app())
    submit(at)
    body = texts(at)
    assert "הבדיקה הסתיימה" in body and "כל תאי התור נבדקו" in body
    assert [b.key for b in at.button if b.key == "rv_resume"] == []


# ---------- התמונה של הטופס ----------

def test_the_saved_page_is_shown_with_the_region_marked(db):
    uid = seed(db, {1: [cells(id=ORANGE)]})
    page_store.write(uid, 1, jpeg())
    repo.save_page_regions(db, uid, 1, {"id": [0.1, 0.2, 0.6, 0.3]})
    at = start_review(records_app())
    assert at.toggle(key="rv_full_page").value is False                  # ברירת המחדל: החיתוך של האזור
    assert "name-zoom" in texts(at) and "pg-mark" not in texts(at)
    at.toggle(key="rv_full_page").set_value(True).run()
    body = texts(at)
    assert "pg-mark" in body and "left:10.00%" in body and "top:20.00%" in body


def test_a_field_without_a_saved_region_falls_back_to_the_whole_page(db):
    uid = seed(db, {1: [cells(sender=ORANGE)]})
    page_store.write(uid, 1, jpeg())
    repo.save_page_regions(db, uid, 1, {"id": [0.1, 0.2, 0.6, 0.3]})     # לגורם שולח אין אזור
    at = start_review(records_app())
    assert "pg-mark" not in texts(at)
    assert any("אין אזור שמור" in c.value for c in at.caption)


def test_without_a_saved_image_the_cell_can_still_be_confirmed(db):
    """פריסה מוארחת עם מסד ארעי ובלי data/: אין תמונות עמוד, והבדיקה עובדת בלעדיהן."""
    uid = seed(db, {1: [cells(id=ORANGE)]})
    assert not page_store.exists(uid, 1)
    at = start_review(records_app())
    assert any(service.IMAGE_MISSING_TEXT in i.value for i in at.info)
    submit(at, "123456")
    assert repo.get_record(db, repo.find_record(db, uid, 1, 0))["national_id"] == "123456"


def test_the_review_works_in_production_mode(db, monkeypatch):
    monkeypatch.setenv("PRIVACY_MODE", "production")
    uid = seed(db, {1: [cells(id=ORANGE, last_name=YELLOW)]})
    at = start_review(records_app())
    assert "בדיקה במבט אחד" in texts(at)
    assert [i.field for i in at.session_state["rv_session"].items] == ["last_name", "id"]
    submit(at)                                                           # שם משפחה: שתי קריאות מסכימות, אישור במבט
    submit(at, "123456")
    rid = repo.find_record(db, uid, 1, 0)
    rec = repo.get_record(db, rid)
    assert rec["national_id"] == "123456" and rec["fields"]["last_name"]["cell_confirmed"]
    assert at.session_state["rv_session"].done


# ---------- טקסט מהטופס ומיקוד אוטומטי ----------

PAYLOAD = "<img src=x onerror=alert(1)>"


def test_a_hostile_reading_is_shown_as_text_not_as_a_tag(db):
    """ערך וחלופה שמקורם בטופס עוברים ב-ui_theme / md_text, ולכן אינם הופכים לתגית במסך הבדיקה."""
    seed(db, {1: [cells(first_name={"color": "orange", "flags": ["conflict"], "value": PAYLOAD,
                                    "alternatives": [PAYLOAD + "2"]})]})
    at = start_review(records_app())
    shown = [v for v in texts(at).split("\n") if "onerror" in v]
    assert shown, "הערך אמור להופיע במסך"
    assert all("&lt;img" in v and v.count("<img") == 0 for v in shown), shown
    assert [b.label for b in at.button if b.key == "rv_alt_0"] == [md_text(PAYLOAD + "2")]   # גם תווי Markdown


def test_the_focus_script_carries_no_form_data(db):
    """סקריפט המיקוד סטטי: רק מספר רשומה ושם שדה (קודים של המערכת), בלי שום טקסט מהטופס."""
    script = review_screen.focus_script("7:first_name")
    assert script.startswith("<script>") and "/* 7:first_name */" in script
    assert "aria-label=\"הערך הנכון\"" in script and ".focus()" in script
    seed(db, {1: [cells(id=ORANGE)]})
    at = start_review(records_app())
    assert not at.exception                                              # st.html לא מפיל את המסך
