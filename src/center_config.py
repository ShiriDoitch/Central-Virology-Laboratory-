"""טווח אורך מספר מרכזי (config/center.json), לפי שימוש; ברירת מחדל 5 עד 9 ספרות כשהמפתח חסר. לא קבוע בקוד.
unlabeled = מועמדי מרכזי בלי תווית מהמודל; barcode_match = ברקודים שנספרים בבדיקת השוויון (כלל א: ירוק);
barcode_fill = ברקודים שמוזנים לתא ריק (כלל ב; שמרני יותר, ראו CLAUDE.md). מרכזי עם תווית לא תלוי באורך."""
import json
from functools import lru_cache
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "center.json"
DEFAULT_RANGE = (5, 9)
KINDS = ("unlabeled", "barcode_match", "barcode_fill")


@lru_cache(maxsize=None)
def center_digit_range(kind: str = "unlabeled") -> tuple[int, int]:
    if kind not in KINDS:
        raise ValueError(f"unknown center range kind {kind!r}")
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get(kind) or {}
        lo, hi = int(cfg["min_digits"]), int(cfg["max_digits"])
        if 1 <= lo <= hi:
            return lo, hi
    except Exception:
        pass
    return DEFAULT_RANGE


def in_center_range(digits: str | None, kind: str = "unlabeled") -> bool:
    lo, hi = center_digit_range(kind)
    return bool(digits) and digits.isdigit() and lo <= len(digits) <= hi
