"""בדיקה במבט אחד: תור התאים שדורשים עין אנושית, הניווט בו, והמדדים הכנים של הבדיקה.

לוגיקה בלבד: בלי Streamlit ובלי SQL (המסך ב-review_screen.py, השאילתות ב-src/repo.py), כדי שאפשר לבדוק אותה לבד.
אין כאן שום כלל חילוץ ושום סף: הערכים, הצבעים והדגלים נקראים מהמסד כפי ש-src/rules.py החליט, והתור רק בוחר
מה המערכת לא בטוחה בו ובאיזה סדר להציג את זה."""
from dataclasses import dataclass, field

from .export import FIELD_KEYS

# צבעי התא (src/service.cell_color): כתום = דגל, זהב = שתי קריאות מסכימות, ריק = לא נמצא ובלי דגל.
# שלושתם דורשים עין אנושית (אותה סמנטיקה כמו ATTENTION ב-src/review.py); ירוק ומאושר ידנית = תקין.
ATTENTION_COLORS = ("orange", "yellow", "empty")


@dataclass(frozen=True)
class ReviewItem:
    """תא אחד בתור: שדה אחד של רשומה אחת. color = הצבע בזמן בניית התור (התצוגה נקראת מהמסד מחדש)."""
    record_id: int
    upload_id: int
    page_no: int
    ordinal: int
    field: str
    color: str


def needs_review(state: dict) -> bool:
    """תא שדורש בדיקה: כתום, זהב או ריק, ושהמשתמשת לא אישרה אותו."""
    return not state.get("cell_confirmed") and state.get("color") in ATTENTION_COLORS


def build_queue(records: list[dict], states: dict[int, dict[str, dict]]) -> list[ReviewItem]:
    """תור הבדיקה: records = שורות הרשומות בסדר שהסינון החזיר (ברירת המחדל במסך היא סדר העמודים),
    states = {מזהה רשומה: {שדה: מצב}}. תא אחד לכל שדה שדורש בדיקה, בסדר רשומה ואז סדר שבעת השדות.
    רשומה מאושרת מדולגת כולה, וכך גם תא ירוק או מאושר."""
    out: list[ReviewItem] = []
    for rec in records:
        if rec.get("status") == "approved":
            continue
        fields = states.get(rec["id"]) or {}
        for key in FIELD_KEYS:
            state = fields.get(key)
            if state and needs_review(state):
                out.append(ReviewItem(record_id=rec["id"], upload_id=rec["upload_id"], page_no=rec["page_no"],
                                      ordinal=rec["ordinal"], field=key, color=state["color"]))
    return out


@dataclass
class ReviewSession:
    """מצב הבדיקה הנוכחית: התור, המקום בו, ומה נעשה בפועל (למדדים בסוף). נשמר ב-session_state של Streamlit."""
    items: list[ReviewItem]
    started_at: float = 0.0
    pos: int = 0
    skips: int = 0
    closed: bool = False
    acted: set = field(default_factory=set)        # (רשומה, שדה) שאושרו או תוקנו בבדיקה הזאת

    @property
    def done(self) -> bool:
        return self.pos >= len(self.items)

    @property
    def current(self) -> ReviewItem | None:
        return None if self.done else self.items[self.pos]

    def advance(self) -> None:
        self.pos = min(self.pos + 1, len(self.items))

    def back(self) -> None:
        self.pos = max(self.pos - 1, 0)

    def skip(self) -> None:
        """התא עובר לסוף התור ויחזור בסופה; המקום בתור לא מתקדם, ולכן העוקב נכנס לאותו אינדקס.
        תא שהיה כבר האחרון בתור: אין לאן להזיז אותו, והסבב נגמר (הוא יחזור בתור הבא)."""
        if self.done:
            return
        item = self.items.pop(self.pos)
        self.items.append(item)
        self.skips += 1
        if self.items[self.pos] is item:
            self.pos += 1

    def record_action(self, item: ReviewItem) -> None:
        self.acted.add((item.record_id, item.field))

    def remaining(self) -> int:
        """כמה תאים נשארו בסבב הזה, כולל התא המוצג."""
        return max(0, len(self.items) - self.pos)

    def progress(self) -> dict:
        """מספרי ההתקדמות לכותרת: הטופס הנוכחי מתוך הטפסים שבתור, התא בתוך הטופס, וכמה תאים נשארו."""
        cur = self.current
        records = list(dict.fromkeys(i.record_id for i in self.items))
        if cur is None:
            return {"record_i": len(records), "records": len(records), "cell_i": 0, "cells": 0, "remaining": 0}
        same = [i for i in self.items if i.record_id == cur.record_id]
        return {"record_i": records.index(cur.record_id) + 1, "records": len(records),
                "cell_i": same.index(cur) + 1, "cells": len(same), "remaining": self.remaining()}

    def summary(self, now: float) -> dict:
        """מה שנמדד בפועל בבדיקה הזאת, בלי שום הערכה: טפסים, תאים, זמן, ושניות לתא (None בלי תאים)."""
        cells = len(self.acted)
        seconds = max(0.0, now - self.started_at)
        return {"records": len({rid for rid, _ in self.acted}), "cells": cells, "seconds": seconds,
                "skips": self.skips, "per_cell": (seconds / cells) if cells else None}


def duration_he(seconds: float) -> str:
    """משך זמן בעברית: שניות עד דקה, אחר כך דקות ושניות."""
    total = int(round(max(0.0, seconds)))
    if total < 60:
        return f"{total} שניות"
    return f"{total // 60} דק' ו-{total % 60} שניות"


def queue_counts(records: list[dict], states: dict[int, dict[str, dict]]) -> dict[str, int]:
    """מה שהכפתור מעל הטבלה מציג: כמה תאים דורשים בדיקה ובכמה טפסים."""
    items = build_queue(records, states)
    return {"cells": len(items), "records": len({i.record_id for i in items})}
