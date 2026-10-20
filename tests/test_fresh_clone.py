"""מה שקורה בעותק טרי של הקוד, בלי data/ ובלי outputs/ (שאינם ב-git) - מבדיקת התקנה נקייה, 21.10.2026.
בלי קריאות API: האפליקציה רצה דרך AppTest בתיקיית עבודה ריקה."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def fresh_cwd(tmp_path, monkeypatch):
    """תיקיית עבודה ריקה: כמו עותק טרי של המאגר, שבו outputs/ ו-data/ עדיין לא קיימים."""
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_app_boots_with_no_env_file_no_db_and_no_sample(fresh_cwd):
    """עליית המסך אינה דורשת .env, מפתח API, מסד קיים או ריצה שמורה."""
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    assert any("עיבוד ובדיקה" in str(s.options) for s in at.segmented_control)


def test_the_records_screen_boots_on_an_empty_database(fresh_cwd):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.session_state["view"] = "records"
    at.run()
    assert not at.exception


def test_sample_button_says_the_sample_is_missing_instead_of_doing_nothing(fresh_cwd):
    """הכפתור "טען דוגמה מחלק 1" היה "מצליח" בשקט עם 0 עמודים (glob על תיקייה חסרה מחזיר רשימה ריקה),
    והמסך נשאר ריק בלי הסבר. עכשיו מוצגת שגיאה שאומרת שהדוגמה אינה בעותק הזה."""
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    next(b for b in at.button if b.label.startswith("טען")).click().run()
    assert not at.exception
    assert any("הדוגמה" in e.value for e in at.error), [e.value for e in at.error]
    assert not at.session_state.get("pages")


def test_db_and_pages_paths_come_from_the_environment(tmp_path, monkeypatch):
    """אין נתיב מוחלט בקוד: המסד ותמונות העמודים נקבעים לפי משתני סביבה (מתועדים ב-.env.example)."""
    from src import page_store, repo
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("PAGES_DIR", str(tmp_path / "pages"))
    assert repo.db_path() == tmp_path / "x.db"
    assert page_store.root() == tmp_path / "pages"
    monkeypatch.delenv("APP_DB_PATH")
    assert repo.db_path() == Path(repo.DEFAULT_DB_PATH)
