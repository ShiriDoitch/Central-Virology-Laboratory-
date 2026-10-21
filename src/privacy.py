"""מצב פרטיות (PRIVACY_MODE): dev (ברירת מחדל) או production.

dev = העבודה שלנו עם נתונים מזויפים: מטמון תשובות המודל (data/cache/) ושמירת קבצי דיבוג (חיתוכים, p<N>.json) פעילים.
production = מה שהמעבדה מריצה על מטופלים אמיתיים: שום דבר על המטופל לא נכתב לדיסק מעבר לסשן. תשובת המודל נשארת בזיכרון
בלבד (לטבלה ולאקסל).

הערך נקרא ממשתנה הסביבה בכל קריאה (לא נשמר), כדי שאפשר יהיה להחליף אותו בבדיקות. ריק או חסר = dev. ערך שאינו dev
ואינו production (שגיאת כתיב) נחשב production: בטעות הפרטיות נכשלים לצד הבטוח."""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEV, PRODUCTION = "dev", "production"
GENERIC_ERROR_HE = "העיבוד נכשל, אפשר לנסות שוב או לפנות לתמיכה"
_log = logging.getLogger("commitments")
if not _log.handlers:
    _handler = logging.StreamHandler(sys.stderr)      # מסוף השרת בלבד: לא מגיע לדפדפן
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def privacy_mode() -> str:
    value = (os.getenv("PRIVACY_MODE") or "").strip().lower()
    if value in ("", DEV):
        return DEV
    return PRODUCTION


def is_production() -> bool:
    return privacy_mode() == PRODUCTION


def safe_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> bool:
    """כותב קובץ דיבוג שמכיל תשובות מודל (למשל p<N>.json) רק ב-dev. ב-production לא נכתב כלום (גם לא התיקייה).
    מחזיר True אם נכתב."""
    if is_production():
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return True


def log_info(message: str) -> None:
    """שורת מידע למסוף השרת. רק טקסט שנבנה מקודים ומספרים (src/status.py), לעולם לא תוכן מהטופס או טקסט של חריגה."""
    _log.info("%s", message)


def log_server_error(context: str, error: BaseException | str | None) -> None:
    """רושם את הכשל האמיתי למסוף השרת (stderr) בלבד, לא למסך המשתמש. ב-dev: הטקסט המלא (כולל traceback לחריגה), לצורך דיבוג.
    ב-production: רק שם הסוג, כי טקסט של חריגה או של תגובת API עלול להכיל נתוני מטופל (למשל ערך שנכשל באימות)."""
    if is_production():
        name = type(error).__name__ if isinstance(error, BaseException) else "error"
        _log.error("%s failed: %s", context, name)
    elif isinstance(error, BaseException):
        _log.error("%s failed: %s", context, error, exc_info=error)
    else:
        _log.error("%s failed: %s", context, error)
