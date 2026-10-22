"""טקסט שמוצג למשתמשת ואפשר לבדוק אותו לבד: אזהרות על קריאה פחות מדויקת, שורת ההתקדמות, והערות קצרות.

בלי Streamlit ובלי החלטות: רק נוסח. שתי מטרות:
1. מה שהמשתמשת רואה מנוסח במונחים שלה: מה זה אומר על הטופס שלה, בלי שמות מודלים, בלי "גיבוי" ובלי מוני ניסיונות
   (הם נשארים בלוג השרת, src/status.py).
2. ניסוח נייטרלי מגדרית: שמות פעולה ("אישור שורה", "הקלדה ידנית") ולא פנייה בלשון נקבה או זכר.
"""
from . import status

# ---------- אזהרות על עמודים שנקראו אחרת ----------
# סדר ההצגה. כל אזהרה מוצגת רק אם הרשימה שלה אינה ריקה: אין אזהרה "ליתר ביטחון".
NOTICE_ORDER = ("fallback", "claude", "claude_pass1", "quota", "failed")
# מה קרה בפועל לעמוד, במונחים של הקורא: לא שם המודל, לא מי נכשל ולמה (זה נשאר בלוג השרת ובגיליון האודיט).
NOTICE_HOW = {"fallback": "בשיטה פחות מדויקת", "claude": "בשירות חלופי", "claude_pass1": "בשירות חלופי",
              "failed": "בלי הקריאה המדויקת של האזורים"}


def pages_phrase(pages: list[int]) -> tuple[str, str, str]:
    """(הנושא, הפועל, כינוי המושא) לפי מספר העמודים: "עמוד 3" / "נקרא" / "אותו"."""
    if len(pages) == 1:
        return f"עמוד {pages[0]}", "נקרא", "אותו"
    return "עמודים " + ", ".join(str(p) for p in pages), "נקראו", "אותם"


def read_notices(issues: dict[str, list[int]]) -> list[str]:
    """האזהרות שצריך להציג על קריאת העמודים (src/export.pass2_issues). רשימה ריקה = שום אזהרה."""
    out = []
    for key in NOTICE_ORDER:
        pages = issues.get(key) or []
        if not pages:
            continue
        subject, verb, it = pages_phrase(pages)
        if key == "quota":
            out.append(f"{subject} {verb} פעם אחת בלבד (הסתיימה המכסה היומית של הקריאות), ולכן אין בדיקה כפולה לשדות")
        else:
            out.append(f"{subject} {verb} {NOTICE_HOW[key]}, מומלץ לבדוק {it} ידנית")
    return out


# ---------- שורת ההתקדמות ----------
# התווית הקצרה לכל שלב אמיתי בעיבוד של עמוד. אין כאן אחוזים בתוך עמוד: פס ההתקדמות מתמלא לפי עמודים שהסתיימו,
# והתווית אומרת מה נעשה כרגע. כל אירוע אחר (ניסיון חוזר, המתנה למכסה, מעבר למודל אחר) אינו מוצג למשתמשת.
STAGE_LABEL = {"pass1": "קריאת העמוד", "rotation": "סידור כיוון העמוד", "pass1_retry": "בדיקה נוספת",
               "pass2": "קריאת הפרטים", "label_retry": "קריאת הפרטים"}
DEFAULT_STAGE = STAGE_LABEL["pass1"]
PROGRESS_START = "התחלה"
_STAGE_BY_TEXT = {status.STAGE_TEXTS[code]: label for code, label in STAGE_LABEL.items() if code in status.STAGE_TEXTS}


def stage_label(status_text: str | None) -> str | None:
    """התווית הקצרה לשלב, או None אם האירוע אינו שלב (ואז שורת ההתקדמות לא משתנה)."""
    return _STAGE_BY_TEXT.get((status_text or "").strip())


def progress_text(page: int, total: int, stage: str) -> str:
    return f"עמוד {page} מתוך {total} · {stage}"


# ---------- הערות קצרות ----------

def pending_hint(n: int) -> str:
    """ההערה מתחת לכפתור אישור שנעול: כמה שדות עוד מחכים לבדיקה בשורה."""
    return "נותר שדה אחד לבדיקה" if n == 1 else f"נותרו {n} שדות לבדיקה"


ALL_CHECKED_HE = "כל השדות נבדקו, אפשר לאשר את השורה"


def row_check_status(n: int) -> tuple[str, str]:
    """(קוד מצב, טקסט) לפס המצב שמעל כפתור אישור השורה: "warn" (כתום) כל עוד נשארו שדות לבדיקה, "ok" (ירוק) ב-0."""
    return ("warn", pending_hint(n)) if n else ("ok", ALL_CHECKED_HE)
