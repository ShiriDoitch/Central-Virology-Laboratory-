"""מכסות Gemini: מרווח בין קריאות לפי דרגה (חזק/קטן), ומונה יומי לפי מודל שנשמר בקובץ.
המצב נשמר ב-data/quota_state.json (מוחרג מגיט) כדי שיישמר גם בין הרצות.
היום מתאפס לפי שעון האוקיינוס השקט (כך Google מאפסת את המכסה היומית)."""
import json
import time
from datetime import date, datetime
from pathlib import Path

STATE_PATH = Path("data/quota_state.json")
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "quotas.json"
DEFAULT_CONFIG = {
    "strong": {"per_minute": 5, "per_day": 20, "stop_at": 18, "min_interval_s": 13},
    "small": {"per_minute": 15, "per_day": 500, "stop_at": 490, "min_interval_s": 5},
}


class DailyQuotaExhausted(Exception):
    """המכסה היומית של מודל נגמרה (או שהגענו לסף העצירה). לא נשלחת בקשה."""

    def __init__(self, model: str, reason: str):
        super().__init__(f"daily quota exhausted for {model} ({reason})")
        self.model = model
        self.reason = reason            # "limit_reached" | "429_daily" | "marked_exhausted"


class ModelNotFound(Exception):
    """404 ממודל: השם לא קיים או לא זמין. המודל מסומן כלא זמין להיום ומדולג, והשרשרת ממשיכה."""

    def __init__(self, model: str):
        super().__init__(f"model not found / unavailable: {model}")
        self.model = model


def load_config(path: Path = CONFIG_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return DEFAULT_CONFIG


def quota_day() -> str:
    """תאריך המכסה (שעון האוקיינוס השקט)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return date.today().isoformat()


def is_daily_quota_error(e: Exception) -> bool:
    """429 שההודעה שלו מציינת מכסה יומית (PerDay / daily). 429 אחר = מגבלת דקה."""
    if getattr(e, "code", None) != 429:
        return False
    text = str(e).lower()
    return any(w in text for w in ("perday", "per day", "per_day", "daily"))


class QuotaTracker:
    def __init__(self, path: Path = STATE_PATH, config: dict | None = None, strong_models=lambda: (),
                 now=time.time, sleep=time.sleep, today=quota_day):
        self.path = Path(path)
        self.config = config or load_config()
        self._strong = strong_models
        self._now = now
        self._sleep = sleep
        self._today = today

    def tier(self, model: str) -> str:
        return "strong" if model in set(self._strong()) else "small"

    # ---- מצב ----
    def _load(self) -> dict:
        state = {"day": self._today(), "models": {}, "last_call": {}}
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                state["last_call"] = saved.get("last_call", {})
                if saved.get("day") == state["day"]:      # יום חדש: המונים מתאפסים
                    state["models"] = saved.get("models", {})
            except (OSError, ValueError):
                pass
        return state

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    def used(self, model: str) -> int:
        return self._load()["models"].get(model, {}).get("calls", 0)

    def stop_at(self, model: str) -> int:
        return self.config[self.tier(model)]["stop_at"]

    def remaining(self, model: str) -> int:
        """כמה קריאות נותרו עד סף העצירה (0 אם המודל סומן כמוצה)."""
        m = self._load()["models"].get(model, {})
        if m.get("exhausted") or m.get("unavailable"):
            return 0
        return max(0, self.stop_at(model) - m.get("calls", 0))

    # ---- בדיקה, מרווח, ספירה ----
    def check(self, model: str) -> None:
        """זורק ModelNotFound אם המודל סומן כלא זמין (404), ו-DailyQuotaExhausted אם הוא מוצה או הגיע לסף."""
        m = self._load()["models"].get(model, {})
        if m.get("unavailable"):
            raise ModelNotFound(model)
        if m.get("exhausted"):
            raise DailyQuotaExhausted(model, "marked_exhausted")
        if m.get("calls", 0) >= self.stop_at(model):
            raise DailyQuotaExhausted(model, "limit_reached")

    def before_call(self, model: str) -> None:
        """לפני כל בקשה: בדיקת מכסה, המתנה למרווח המינימלי בין קריאות מאותה דרגה, ורישום הקריאה."""
        self.check(model)
        tier = self.tier(model)
        state = self._load()
        wait = state["last_call"].get(tier, 0) + self.config[tier]["min_interval_s"] - self._now()
        if wait > 0:
            self._sleep(wait)
        entry = state["models"].setdefault(model, {"calls": 0, "exhausted": False})
        entry["calls"] += 1
        state["last_call"][tier] = self._now()
        self._save(state)

    def mark_unavailable(self, model: str) -> None:
        """404: לא ננסה את המודל שוב היום."""
        state = self._load()
        state["models"].setdefault(model, {"calls": 0, "exhausted": False})["unavailable"] = True
        self._save(state)

    def mark_exhausted(self, model: str) -> None:
        """429 יומי: לא ננסה את המודל שוב היום."""
        state = self._load()
        state["models"].setdefault(model, {"calls": 0, "exhausted": False})["exhausted"] = True
        self._save(state)

    def report(self, models: list[str]) -> str:
        """שורת סטטוס קריאה למשתמשת."""
        state = self._load()["models"]
        parts = []
        for m in models:
            e = state.get(m, {})
            limit = self.config[self.tier(m)]["per_day"]
            mark = " (מוצה)" if e.get("exhausted") else (" (לא קיים, 404)" if e.get("unavailable") else "")
            parts.append(f"{m}: {e.get('calls', 0)}/{limit}{mark}")
        return " | ".join(parts)
