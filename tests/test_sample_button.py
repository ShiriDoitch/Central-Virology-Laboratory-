"""כפתור "טען דוגמה מחלק 1" הוא לדמו בלבד (ראו CLAUDE.md סעיף 18): ב-production, שהוא הפריסה המוארחת
של המעבדה, הוא אינו מוצג כלל - ולא רק מושבת - וגם המצב הריק לא מזכיר אותו אלא רק את דרך ההעלאה.
ב-dev הוא נשאר, כי הדמו רץ עליו. בלי קריאות API: האפליקציה עולה ריקה דרך AppTest."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PRODUCTION_HINT = "העלי קובץ PDF או תמונה ולחצי עבד"


def run_app(monkeypatch, mode: str) -> AppTest:
    monkeypatch.setenv("PRIVACY_MODE", mode)
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    return at


def empty_state(at: AppTest) -> str:
    texts = [m.value for m in at.markdown if "אין עדיין תוצאות" in m.value]
    assert len(texts) == 1
    return texts[0]


def test_dev_keeps_the_sample_button(monkeypatch):
    at = run_app(monkeypatch, "dev")
    assert [b.label for b in at.button if "דוגמה" in b.label] == ["טען דוגמה מחלק 1"]
    assert "טען דוגמה מחלק 1" in empty_state(at)


def test_production_does_not_render_the_sample_button_at_all(monkeypatch):
    at = run_app(monkeypatch, "production")
    assert [b.label for b in at.button if "דוגמה" in b.label] == []
    assert "עבד" in [b.label for b in at.button]          # שאר כרטיס הפעולה במקומו


def test_production_empty_state_says_only_how_to_upload(monkeypatch):
    at = run_app(monkeypatch, "production")
    text = empty_state(at)
    assert PRODUCTION_HINT in text
    assert "דוגמה" not in text


def test_a_typo_in_privacy_mode_is_treated_as_production(monkeypatch):
    """src/privacy.py נכשל לצד הבטוח: ערך שאינו dev נחשב production, ולכן גם כאן אין כפתור דוגמה."""
    at = run_app(monkeypatch, "producton")
    assert [b.label for b in at.button if "דוגמה" in b.label] == []
    assert PRODUCTION_HINT in empty_state(at)
