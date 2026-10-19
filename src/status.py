"""שורת סטטוס בטוחה לפרטיות בזמן המתנה: אירועים עם קודים ומספרים מרשימה סגורה בלבד.
אין כאן טקסט חופשי: לא טקסט של חריגה, לא שמות קבצים ולא ערכים מהטופס. שדה או סוג אירוע שאינם ברשימה נזרקים בשקט, כך שגם באג
בקריאה לא יכול להדליף נתון לממשק או למסוף. כל אירוע נרשם גם ללוג של השרת (אותו טקסט שמוצג בממשק).
המאזין (מסך ההתקדמות) נקבע לריצה הנוכחית בלבד (listening)."""
import contextlib
import contextvars
from typing import Callable

from .privacy import log_info

STAGES = ("pass1", "rotation", "pass1_retry", "pass2", "label_retry")
NUMBER_FIELDS = ("attempt", "of", "wait_s", "page")
TEXTS = {            # אירוע -> תבנית; רק שדות מספריים ו-stage מרשימה סגורה נכנסים לתבנית
    "page": "מעבד עמוד {page} מתוך {of}",
    "model_call": "ממתין למודל (ניסיון {attempt} מתוך {of})",
    "retry_wait": "המודל עמוס, מנסה שוב בעוד כ-{wait_s} שניות (ניסיון {attempt} מתוך {of})",
    "quota_wait": "ממתין למכסה (כ-{wait_s} שניות)",
    "model_switch": "עובר למודל גיבוי",
    "key_switch": "עובר למפתח גיבוי",
    "claude_fallback": "עובר לגיבוי אחרון",
}
STAGE_TEXTS = {
    "pass1": "קורא את העמוד",
    "rotation": "מסובב את העמוד וקורא שוב",
    "pass1_retry": "בדיקה חוזרת של הקריאה הראשונה",
    "pass2": "קורא אזורים מוגדלים",
    "label_retry": "קורא שוב את אזור פרטי המטופל",
}

_listener: contextvars.ContextVar["Callable[[dict], None] | None"] = contextvars.ContextVar("status_listener", default=None)


def _clean(kind: str, fields: dict) -> dict | None:
    if kind != "stage" and kind not in TEXTS:
        return None
    event: dict = {"kind": kind}
    for key, value in fields.items():
        if key in NUMBER_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 100000:
            event[key] = int(round(value))
        elif key == "stage" and value in STAGES:
            event[key] = value
    if kind == "stage" and "stage" not in event:
        return None
    return event


def describe(event: dict) -> str:
    """הטקסט בעברית לאירוע (אחרי ניקוי). אירוע חסר שדות מחזיר טקסט כללי ולא קורס."""
    if event.get("kind") == "stage":
        return STAGE_TEXTS.get(event.get("stage"), "מעבד")
    try:
        return TEXTS[event["kind"]].format(**{k: event.get(k, "?") for k in NUMBER_FIELDS})
    except (KeyError, ValueError):
        return "מעבד"


def emit(kind: str, **fields) -> None:
    """מדווח אירוע: לוג שרת + המאזין הנוכחי (אם יש). לא זורק לעולם: סטטוס לא מפיל עיבוד."""
    event = _clean(kind, fields)
    if event is None:
        return
    text = describe(event)
    try:
        log_info(text)
        listener = _listener.get()
        if listener is not None:
            listener({**event, "text": text})
    except Exception:
        pass


@contextlib.contextmanager
def listening(callback: "Callable[[dict], None] | None"):
    token = _listener.set(callback)
    try:
        yield
    finally:
        _listener.reset(token)
