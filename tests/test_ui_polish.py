"""ליטוש הממשק (21.10.2026): נוסח האזהרות והשלבים (src/ui_text.py), אישור שורה שנעול עד שאין שדה לבדיקה,
והקלדה ידנית שיושבת בטופס כדי ש-Enter יאשר. בלי קריאות API: נוסח נבדק לבד, והמסכים מול מסד זמני.

כל הטקסט בממשק נייטרלי מגדרית (שמות פעולה, בלי פנייה בלשון נקבה או זכר), והבדיקה האחרונה כאן שומרת על זה."""
import json
import re
from pathlib import Path

import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from src import repo, service, status, ui_text
from src import ui_theme as ui
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


# ---------- 2: מקרא הצבעים ותוויות הקבוצות ----------

SAMPLE_READY = Path("outputs/clean_part1_v4b").exists() and Path("data/clean_part1.pdf").exists()
needs_sample = pytest.mark.skipif(not SAMPLE_READY, reason="needs the saved sample run")


def loaded_screen(monkeypatch, mode: str = "dev", cell=None) -> AppTest:
    """מסך העיבוד עם תוצאות (הדוגמה השמורה, בלי קריאות API), ואם נתון cell גם כרטיס הבדיקה פתוח."""
    monkeypatch.setenv("PRIVACY_MODE", mode)
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    next(b for b in at.button if "דוגמה" in b.label).click().run()
    if cell is not None:
        at.session_state["selected_cell"] = cell
        at.run()
    assert not at.exception, at.exception
    return at


def screen_text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown if not m.value.startswith("<style>"))


@needs_sample
def test_the_legend_explains_every_colour_in_one_place(monkeypatch):
    body = screen_text(loaded_screen(monkeypatch))
    assert body.count("class='legend'") == 1                      # מקום אחד קבוע, מתחת לטבלה
    for state, meaning in (("green", "נקרא בביטחון"), ("yellow", "שתי קריאות הסכימו, מספיק מבט"),
                           ("orange", "לבדיקה"), ("confirmed", "אושר ידנית"), ("empty", "לא נמצא בטופס")):
        assert f"state {state}'><i class='dot'></i>{meaning}" in body, (state, meaning)
    assert "כתום = לבדיקה אנושית" not in body                     # הכיתוב הישן בכותרת הוסר


@needs_sample
def test_the_two_groups_say_what_they_do(monkeypatch):
    """הגלולות מסננות שורות, המונים סופרים שדות: לכל קבוצה תווית משלה."""
    body = screen_text(loaded_screen(monkeypatch))
    assert "סינון שורות" in body and "אילו שורות מוצגות בטבלה" in body
    assert "ספירת שדות" in body and "כמה שדות יש בכל מצב" in body


# ---------- 3: קריאות גולמיות של המודל רק ב-dev ----------

RAW_READINGS = "קריאות גולמיות של המודל"


@needs_sample
def test_raw_model_readings_are_a_dev_tool_only(tmp_path, monkeypatch):
    """ב-production הכפתור "טעינת דוגמה" אינו קיים, ולכן המסך נטען כאן דרך אסימון ריצה (כמו אחרי רענון),
    שאינו תלוי במצב הפרטיות."""
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "raw.db"))
    conn = repo.connect(tmp_path / "raw.db")
    page = json.loads((Path("outputs/clean_part1_v4b") / "p1.json").read_text(encoding="utf-8"))
    store = service.Persister(conn, "a.pdf", b"raw-bytes")
    store.start(1)
    store.page(page)
    store.finish()

    def screen(mode: str) -> AppTest:
        monkeypatch.setenv("PRIVACY_MODE", mode)
        at = AppTest.from_file(APP, default_timeout=120)
        at.query_params["run"] = store.token
        at.run()
        at.session_state["selected_cell"] = (0, "שם פרטי")
        at.run()
        assert not at.exception, (mode, at.exception)
        return at

    dev = screen("dev")
    assert RAW_READINGS in [e.label for e in dev.get("expander")]
    prod = screen("production")
    labels = [e.label for e in prod.get("expander")]
    assert RAW_READINGS not in labels
    assert labels, "שאר המרחיבים במסך נשארים"


# ---------- 2: פס ההתקדמות מתמלא מימין לשמאל ----------

PROGRESS_RULES = {sel.strip(): body for sel, body in
                  [(m.group(1), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", ui.CSS, flags=re.S))]
                  if "stProgress" in sel}


def test_the_progress_bar_fills_from_the_right():
    """הממשק עברית, ולכן הפס מתמלא מהקצה הימני שמאלה. direction: rtl לבד אינו מספיק: המילוי הוא div
    ברוחב 100% שמוזז ב-transform (כך בנוי הרכיב ב-Streamlit), ולכן המסילה עצמה משוקפת."""
    rtl = [body for sel, body in PROGRESS_RULES.items() if '[data-testid="stProgress"]' in sel]
    assert rtl and any("direction: rtl" in body for body in rtl)
    track = [body for sel, body in PROGRESS_RULES.items()
             if '[data-testid="stProgressBarTrack"]' in sel and "> div" not in sel]
    assert track and all("scaleX(-1)" in body for body in track)


def test_both_progress_bars_get_the_same_rule():
    """כלל הכיוון אינו מוגבל למסך אחד (אין בו .st-key-), ולכן הוא חל על פס העיבוד ועל פס הבדיקה גם יחד.
    כלל מרווח של פס מסוים כן יכול להיות ממוקד: הוא אינו נוגע בכיוון."""
    direction = [sel for sel, body in PROGRESS_RULES.items() if "direction: rtl" in body or "scaleX(-1)" in body]
    assert direction and all("st-key-" not in sel for sel in direction)


# ---------- 3 + 4: הכפתור נושא את הרמז, ובלי שורת עזר מתחתיו ----------

@needs_sample
def test_the_enter_hint_lives_only_on_the_button(tmp_path, monkeypatch):
    """ההסבר "Enter מאשר את מה שבשדה..." הוסר מהמסך; המילה Enter נשארת על הכפתור, והכלל עצמו
    (ערך זהה = אישור, ערך שונה = תיקון) מתועד ב-README."""
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "hint.db"))
    conn = repo.connect(tmp_path / "hint.db")
    page = json.loads((Path("outputs/clean_part1_v4b") / "p1.json").read_text(encoding="utf-8"))
    store = service.Persister(conn, "a.pdf", b"hint-bytes")
    store.start(1)
    store.page(page)
    store.finish()
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["view"] = "records"
    at.run()
    at.button(key="rev_start").click().run()
    assert not at.exception, at.exception
    labels = [b.label for b in at.button if b.key and b.key.startswith("FormSubmitter")]
    assert labels == ["אישור · Enter"]
    for text in [c.value for c in at.caption]:
        assert "Enter" not in text, text
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert "ערך זהה למה שהמערכת קראה נרשם כאישור, ערך שונה נרשם כתיקון" in readme


def test_the_review_banner_keeps_every_number_with_hierarchy():
    """כל המספרים של guided_review.progress מופיעים בשבבים, עם המספר מודגש."""
    chips = ui.stat_chips([("טופס", 2, "מתוך 2", False), ("נשארו", 4, "תאים", True)])
    assert "טופס <b>2</b> מתוך 2" in chips and "נשארו <b>4</b> תאים" in chips
    assert "class='rv-chip accent'" in chips                      # "נשארו" מודגש בגוון המותג
    card = ui.banner("בדיקה במבט אחד", "שורת הסבר", chips)
    assert "class='rv-title'" in card and "class='rv-sub'" in card and chips in card
