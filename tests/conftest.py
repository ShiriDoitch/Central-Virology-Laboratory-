"""בכל בדיקה: מעקב המכסות מוחלף בגרסה עם קובץ זמני ושעון מדומה, כך שהבדיקות לא נוגעות ב-data/quota_state.json
ולא ממתינות בפועל למרווחים."""
import pytest

from src import extractor
from src.quota import DEFAULT_CONFIG, QuotaTracker


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture(autouse=True)
def dev_privacy_mode(monkeypatch):
    """הבדיקות רצות ב-dev (כמו ברירת המחדל), גם אם ב-.env של המפתחת הוגדר PRIVACY_MODE אחר. בדיקות production מגדירות אותו בעצמן."""
    monkeypatch.delenv("PRIVACY_MODE", raising=False)


@pytest.fixture(autouse=True)
def no_real_api_fallbacks(monkeypatch):
    """בבדיקות אסור שיישלחו בקשות אמיתיות: בלי גיבוי Claude (גם אם ANTHROPIC_API_KEY ב-.env של המפתחת) ובלי רשימת מפתחות Gemini
    מהסביבה. בדיקות של הגיבוי ושל סיבוב המפתחות מגדירות אותם בעצמן ומחליפות את הלקוחות בלקוחות מדומים."""
    monkeypatch.setenv("CLAUDE_FALLBACK", "0")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setattr("src.extractor._EXTRA_TRACKERS", {})
    monkeypatch.setattr("src.extractor.REGION_ATTEMPTS", 1)      # בדיקות שרשרת המודלים של מעבר 2 קובעות סדר מודלים, לא ניסיונות חוזרים; tests/test_resilience.py בודק את ברירת המחדל (2)


@pytest.fixture(autouse=True)
def quota_tracker(monkeypatch, tmp_path):
    clock = FakeClock()
    tracker = QuotaTracker(path=tmp_path / "quota_state.json", config=DEFAULT_CONFIG,
                           strong_models=extractor.strong_model_list, now=clock.now, sleep=clock.sleep,
                           today=lambda: "2026-10-14")
    tracker.clock = clock
    monkeypatch.setattr(extractor, "TRACKER", tracker)
    monkeypatch.setattr(extractor, "_make_extra_tracker", lambda i: extractor._ExtraKeyTracker(QuotaTracker(
        path=tmp_path / f"quota_state_key{i + 1}.json", config=DEFAULT_CONFIG, strong_models=lambda: (),
        now=clock.now, sleep=clock.sleep, today=lambda: "2026-10-14")))      # מפתחות נוספים: אותו שעון מדומה, בלי כתיבה ל-data/
    return tracker


def set_models(monkeypatch, first="small-1", fallbacks=(), second="small-2", escalate=False, strong=()):
    """מחליף את הגדרת config/models.json בבדיקה."""
    cfg = {"first_pass": first, "first_pass_fallbacks": list(fallbacks), "second_pass": second,
           "escalate_to_strong": escalate, "strong_models": list(strong)}
    monkeypatch.setattr(extractor, "load_models_config", lambda: dict(cfg))


def legacy_strong(monkeypatch, names: str):
    """מעבר שני על שרשרת נתונה "s1,s2": כל המודלים בדרגת strong, והאחרון הוא מודל ברירת המחדל של השרשרת."""
    lst = [n.strip() for n in names.split(",")]
    set_models(monkeypatch, escalate=True, strong=lst[:-1], second=lst[-1])
    monkeypatch.setattr(extractor.TRACKER, "_strong", lambda: lst)
