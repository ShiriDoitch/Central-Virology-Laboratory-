"""ליטוש הממשק (21.10.2026): נוסח האזהרות והשלבים (src/ui_text.py), אישור שורה שנעול עד שאין שדה לבדיקה,
והקלדה ידנית שיושבת בטופס כדי ש-Enter יאשר. בלי קריאות API: נוסח נבדק לבד, והמסכים מול מסד זמני.

כל הטקסט בממשק נייטרלי מגדרית (שמות פעולה, בלי פנייה בלשון נקבה או זכר), והבדיקה האחרונה כאן שומרת על זה."""
import json
import re
from pathlib import Path

import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from src import repo, status, ui_text
from test_guided_review import BLANK, FLAGGED_BLANK, ORANGE, VALUES, YELLOW, cells, seed

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SAMPLE_RUN = Path("outputs/clean_part1_v4b/p1.json")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "p.db"))
    return repo.connect(tmp_path / "p.db")


def records_app(rec_open: int | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    if rec_open is not None:
        at.session_state["rec_open"] = rec_open
    at.run()
    assert not at.exception, at.exception
    return at


# ---------- 1: אזהרה על עמוד שנקרא אחרת, בלשון המשתמשת ----------

def test_no_notice_when_every_page_was_read_normally():
    assert ui_text.read_notices({"fallback": [], "claude": [], "claude_pass1": [], "quota": [], "failed": []}) == []
    assert ui_text.read_notices({}) == []


def test_the_fallback_notice_says_what_it_means_without_model_names():
    assert ui_text.read_notices({"fallback": [7]}) == ["עמוד 7 נקרא בשיטה פחות מדויקת, מומלץ לבדוק אותו ידנית"]
    many = ui_text.read_notices({"fallback": [3, 7]})
    assert many == ["עמודים 3, 7 נקראו בשיטה פחות מדויקת, מומלץ לבדוק אותם ידנית"]
    for text in ui_text.read_notices({"fallback": [1], "claude": [2], "claude_pass1": [3], "quota": [4], "failed": [5]}):
        for word in ("מודל", "גיבוי", "Gemini", "Claude", "מעבר 2", "pass"):
            assert word not in text, text


def test_every_notice_kind_is_covered_and_ordered():
    issues = {"fallback": [1], "claude": [2], "claude_pass1": [3], "quota": [4], "failed": [5]}
    out = ui_text.read_notices(issues)
    assert len(out) == len(issues)
    assert [t.split()[1] for t in out] == ["1", "2", "3", "4", "5"]        # סדר ההצגה = NOTICE_ORDER


@pytest.fixture
def fake_sample(tmp_path, monkeypatch):
    """תיקיית עבודה זמנית עם "ריצה שמורה" של עמוד אחד (מועתקת מהריצה האמיתית) ו-PDF של עמוד אחד,
    כך שכפתור הדוגמה טוען אותה והמסך נבנה כמו בדמו. מחזיר פונקציה שמסמנת את העמוד כנקרא אחרת."""
    page = json.loads(SAMPLE_RUN.read_text(encoding="utf-8"))
    out = tmp_path / "outputs" / "clean_part1_v4b"
    out.mkdir(parents=True)
    (tmp_path / "data").mkdir()
    doc = pymupdf.open()
    doc.new_page()
    doc.save(tmp_path / "data" / "clean_part1.pdf")
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.chdir(tmp_path)

    def write(**flags):
        (out / "p1.json").write_text(json.dumps({**page, **flags}, ensure_ascii=False), encoding="utf-8")
        at = AppTest.from_file(APP, default_timeout=120)
        at.run()
        next(b for b in at.button if "דוגמה" in b.label).click().run()
        assert not at.exception, at.exception
        return at
    return write


@pytest.mark.skipif(not SAMPLE_RUN.exists(), reason="needs the saved sample run")
def test_the_banner_appears_only_for_a_page_that_really_was_read_that_way(fake_sample):
    at = fake_sample(pass2_fallback=False)
    assert [w.value for w in at.warning if "פחות מדויקת" in w.value] == []
    at = fake_sample(pass2_fallback=True)                         # אותו עמוד בדיוק, רק סומן שנקרא אחרת
    assert [w.value for w in at.warning if "פחות מדויקת" in w.value] == \
        ["עמוד 1 נקרא בשיטה פחות מדויקת, מומלץ לבדוק אותו ידנית"]


# ---------- 3: שורת ההתקדמות ----------

def test_the_progress_line_shows_the_page_and_the_stage():
    assert ui_text.progress_text(2, 6, ui_text.DEFAULT_STAGE) == "עמוד 2 מתוך 6 · קריאת העמוד"
    assert ui_text.stage_label(status.STAGE_TEXTS["pass2"]) == "קריאת הפרטים"
    assert set(ui_text.STAGE_LABEL) == set(status.STAGES)          # לכל שלב אמיתי יש תווית


def test_retry_and_wait_events_never_reach_the_progress_line():
    """מוני ניסיונות, המתנה למכסה ומעבר למודל אחר נשארים בלוג השרת: stage_label מחזיר None, ולכן
    הטקסט שמוצג למשתמשת לא משתנה בגללם."""
    for kind in ("model_call", "retry_wait", "quota_wait", "model_switch", "key_switch", "claude_fallback"):
        text = status.describe({"kind": kind, "attempt": 2, "of": 3, "wait_s": 20})
        assert ui_text.stage_label(text) is None, (kind, text)
    assert ui_text.stage_label(status.describe({"kind": "page", "page": 1, "of": 2})) is None
    assert "ניסיון" not in ui_text.progress_text(1, 2, ui_text.DEFAULT_STAGE)


# ---------- 6: אישור שורה נעול עד שאין שדה לבדיקה ----------

def test_a_flagged_value_locks_the_approve_button_and_says_how_many(db):
    uid = seed(db, {1: [cells(id=ORANGE, date=ORANGE)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = records_app(rid)
    assert at.button(key=f"rec_appr_{rid}").disabled
    assert any("נותרו 2 שדות לבדיקה" in c.value for c in at.caption)
    repo.edit_field(db, rid, "id", VALUES["id"])                   # אושר אחד: נשאר אחד
    at.run()
    assert at.button(key=f"rec_appr_{rid}").disabled
    assert any("נותר שדה אחד לבדיקה" in c.value for c in at.caption)
    repo.edit_field(db, rid, "date", VALUES["date"])
    at.run()
    assert not at.button(key=f"rec_appr_{rid}").disabled
    at.button(key=f"rec_appr_{rid}").click().run()
    assert repo.get_record(db, rid)["status"] == "approved"


def test_an_empty_cell_does_not_block_approval(db):
    """שדה יכול באמת לא להופיע בטופס: תא ריק (גם תא ריק שסומן לבדיקה) אינו מונע אישור של השורה."""
    uid = seed(db, {1: [cells(commitment=FLAGGED_BLANK, center=BLANK)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = records_app(rid)
    assert not at.button(key=f"rec_appr_{rid}").disabled
    assert not [c for c in at.caption if "לבדיקה" in c.value and "נות" in c.value]
    at.button(key=f"rec_appr_{rid}").click().run()
    assert repo.get_record(db, rid)["status"] == "approved"


def test_a_yellow_cell_does_not_block_approval(db):
    """זהב = שתי קריאות עצמאיות שמסכימות, "מספיק מבט לאישור", והאישור עצמו הוא המבט."""
    uid = seed(db, {1: [cells(first_name=YELLOW)]})
    rid = repo.find_record(db, uid, 1, 0)
    at = records_app(rid)
    assert not at.button(key=f"rec_appr_{rid}").disabled


def test_the_hint_is_written_once_for_every_screen():
    assert ui_text.pending_hint(1) == "נותר שדה אחד לבדיקה"
    assert ui_text.pending_hint(4) == "נותרו 4 שדות לבדיקה"


# ---------- 7 + 8: הקלדה בטופס, וניסוח נייטרלי ----------

@pytest.mark.skipif(not Path("outputs/clean_part1_v4b").exists() or not Path("data/clean_part1.pdf").exists(),
                    reason="needs the saved sample run")
def test_the_manual_input_sits_in_a_form_so_enter_confirms():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    next(b for b in at.button if "דוגמה" in b.label).click().run()
    at.session_state["selected_cell"] = (0, "שם פרטי")
    at.run()
    assert not at.exception
    field = at.text_input(key="txt_1_first_name")
    assert field.label == "הקלדה ידנית"                            # שם פעולה, בלי "או" ובלי פנייה
    assert field.form_id, "השדה חייב לשבת בטופס, אחרת Enter לא מאשר"
    submit = next(b for b in at.button if b.key == "ok_1_first_name")
    assert submit.label == "אישור הערך שהוקלד" and not submit.disabled


# פנייה בלשון נקבה או זכר. הבדיקה היא על מילה שלמה: "נמחק" או "לדלג" אינם פנייה, "מחק" ו"דלגי" כן.
# ("לחיצה מאשרת" הוא תיאור של הלחיצה ולא פנייה למשתמשת, ולכן אינו ברשימה.)
GENDERED = ("העלי", "לחצי", "בחרי", "אשרי", "בטלי", "שמרי", "הקלידי", "דלגי", "דלג", "פתחי", "נסי", "סמני", "גררי",
            "מחק", "הורד", "טען", "עבדי", "התחילי", "החזירי", "הסתכלי", "מבינה", "לבורנטית", "הצג")
GENDERED_RE = re.compile(r"(?<!\w)(" + "|".join(GENDERED) + r")(?!\w)")
UI_FILES = ("app.py", "records_screen.py", "review_screen.py", "evidence_view.py", "src/ui_theme.py",
            "src/ui_text.py", "src/guided_review.py", "src/confirm.py", "src/privacy.py", "src/export.py")


def test_no_gendered_imperative_is_left_in_the_interface():
    """הממשק מדבר בשמות פעולה ("אישור שורה", "הקלדה ידנית") ולא בפנייה בלשון נקבה או זכר.
    הבדיקה עוברת על הקובץ כולו (כולל הערות), כדי שגם טקסט חדש יישאר באותו סגנון."""
    root = Path(__file__).resolve().parent.parent
    found = {}
    for name in UI_FILES:
        hits = sorted(set(GENDERED_RE.findall((root / name).read_text(encoding="utf-8"))))
        if hits:
            found[name] = hits
    assert found == {}, found
