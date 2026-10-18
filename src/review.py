"""סינון שורות לבדיקה בממשק (app.py): מסננים מהירים, מצב פוקוס, והתא הבא שדורש בדיקה.
עובד על טבלת הצבעים של התצוגה (תא = קוד צבע hex מ-src/export.py, או "" לתא ריק בלי דגל). בלי Streamlit, כדי שאפשר לבדוק."""
import pandas as pd

from src.export import COLUMNS, CONFIRMED, FIELD_KEYS, GREEN, ORANGE, YELLOW

GREEN_HEX, ORANGE_HEX = "#" + GREEN.fgColor.rgb[-6:], "#" + ORANGE.fgColor.rgb[-6:]
YELLOW_HEX, CONFIRMED_HEX = "#" + YELLOW.fgColor.rgb[-6:], "#" + CONFIRMED.fgColor.rgb[-6:]
EMPTY = ""                                            # תא ריק בלי דגל
ATTENTION = (ORANGE_HEX, YELLOW_HEX, EMPTY)           # דורש עין אנושית: כתום, צהוב, ריק. ירוק ומאושר (כחול) = תקין
FILTER_KEYS = ("all", "green", "orange", "yellow", "empty")
_TITLES = dict(COLUMNS)


def field_titles() -> list[str]:
    """עמודות השדות בסדר הקריאה (בלי עמודת העמוד ושאר עמודות התצוגה)."""
    return [_TITLES[k] for k in FIELD_KEYS]


def row_masks(colors: pd.DataFrame) -> dict[str, pd.Series]:
    """לכל מסנן: אילו שורות מתאימות. "attention" = יש בשורה לפחות שדה אחד כתום, צהוב או ריק.
    "green" (תקין) = אין שדה כזה: כל השדות ירוקים או מאושרים על ידי המשתמש."""
    fc = colors[field_titles()]
    has = {"orange": (fc == ORANGE_HEX).any(axis=1), "yellow": (fc == YELLOW_HEX).any(axis=1), "empty": (fc == EMPTY).any(axis=1)}
    attention = has["orange"] | has["yellow"] | has["empty"]
    return {"all": pd.Series(True, index=colors.index), "green": ~attention, **has, "attention": attention}


def visible_rows(colors: pd.DataFrame, status_filter: str = "all", focus: bool = False) -> pd.Series:
    """השורות שמוצגות. במצב פוקוס שורה תקינה (בלי אף שדה כתום / צהוב / ריק) לעולם לא מוצגת, בכל מסנן."""
    masks = row_masks(colors)
    mask = masks.get(status_filter, masks["all"])
    return mask & masks["attention"] if focus else mask


def filter_counts(colors: pd.DataFrame, focus: bool = False) -> dict[str, int]:
    """כמה שורות יוצגו בכל מסנן, בהתחשב במצב הפוקוס (כך שהמספר על הכפתור הוא מה שיופיע בטבלה)."""
    return {k: int(visible_rows(colors, k, focus).sum()) for k in FILTER_KEYS}


def next_attention_cell(colors: pd.DataFrame, rows, current) -> tuple[int, str] | None:
    """התא הבא שדורש בדיקה אחרי current (שורה, ואז שדה בסדר הקריאה), עם חזרה להתחלה. None אם אין אחר."""
    titles = field_titles()
    cells = [(int(r), t) for r in rows for t in titles if colors.at[r, t] in ATTENTION]
    if not cells:
        return None
    if current is None:
        return cells[0]

    def pos(c):
        return c[0], titles.index(c[1]) if c[1] in titles else -1

    later = [c for c in cells if pos(c) > pos(tuple(current))]
    nxt = later[0] if later else cells[0]
    return None if nxt == tuple(current) else nxt
