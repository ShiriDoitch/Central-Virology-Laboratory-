"""מצב פרטיות (PRIVACY_MODE): dev (ברירת מחדל) או production.

dev = העבודה שלנו עם נתונים מזויפים: מטמון תשובות המודל (data/cache/) ושמירת קבצי דיבוג (חיתוכים, p<N>.json) פעילים.
production = מה שהמעבדה מריצה על מטופלים אמיתיים: שום דבר על המטופל לא נכתב לדיסק מעבר לסשן. תשובת המודל נשארת בזיכרון
בלבד (לטבלה ולאקסל).

הערך נקרא ממשתנה הסביבה בכל קריאה (לא נשמר), כדי שאפשר יהיה להחליף אותו בבדיקות. ריק או חסר = dev. ערך שאינו dev
ואינו production (שגיאת כתיב) נחשב production: בטעות הפרטיות נכשלים לצד הבטוח."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEV, PRODUCTION = "dev", "production"


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
