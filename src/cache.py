"""מטמון מקומי לתשובות המודל (במצב פיתוח, על דוגמאות מזויפות בלבד).
המפתח = תמונות + הפרומפט + סכמת הפלט + רשימת המודלים המוגדרת (ראשי וגיבוי, לפי הסדר).
שינוי פרומפט, סכמה או מודל מבטל את המטמון, כך שתשובה של מודל אחד לא מוחזרת כשהוגדר מודל אחר.
נשמרות רק תשובות מוצלחות; השדה "model" בתשובה אומר איזה מודל ענה בפועל."""
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from .extractor import provider, PROMPT, PROMPT_REGIONS, extract, extract_regions, model_chain, region_model_chain
from .rules import legacy_date_kind
from .schema import PageExtraction, RegionsExtraction

CACHE_DIR = Path("data/cache")


def _dir() -> Path:
    """תיקיית המטמון. ספק Anthropic שומר בנפרד (data/cache/anthropic) כדי שמטמוני Gemini לא יושפעו."""
    return CACHE_DIR / "anthropic" if provider() == "anthropic" else CACHE_DIR


def _key(images: list[bytes], prompt: str, schema: type[BaseModel], chain: list[str]) -> str:
    h = hashlib.sha256()
    for img in images:
        h.update(hashlib.sha256(img).digest())
    h.update(prompt.encode("utf-8"))
    h.update(json.dumps(schema.model_json_schema(), sort_keys=True).encode("utf-8"))
    h.update(" > ".join(chain).encode("utf-8"))
    return h.hexdigest()[:20]


def cache_key(images: list[bytes]) -> str:
    return _key(images, PROMPT, PageExtraction, model_chain())


def regions_cache_key(crops: dict[str, bytes]) -> str:
    slots = [n for n in ("patient", "barcode", "commitment", "receipt") if n in crops]
    return _key([crops[n] for n in slots], PROMPT_REGIONS + "|" + ",".join(slots), RegionsExtraction, region_model_chain())


def _cached(key: str, fn, arg) -> tuple[dict, bool]:
    path = _dir() / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")), True
    result = fn(arg)
    # תשובה שנתן מודל הגיבוי (fallback) לא נשמרת: כשהמודל החזק יחזור, לא נחזיר תשובה חלשה מהמטמון
    if result.get("ok") and not result.get("fallback"):
        _dir().mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result, False


SNAPSHOT_PATH = Path("data/part1_snapshot.json")


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict[int, dict]:
    """תצלום של תשובות המעבר הראשון של חלק 1 (נשמר כשמפתח המטמון השתנה). {עמוד: תוצאה}; ריק אם אין קובץ.
    התצלום נוצר בסכמה הישנה: סוג התאריך lab_received מומר לסכמה החדשה (lab_stamp / handwritten_date /
    receipt_date, לפי הראיות), כדי שהוא יעבור אימות. שדות שנוספו בסכמה החדשה מקבלים ברירות מחדל."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = {int(p): r for p, r in data["pages"].items()}
    for result in pages.values():
        for d in result.get("dates", []):
            d["kind"] = legacy_date_kind(d.get("kind", "other"), d.get("source", "unknown"), d.get("evidence"))
    return pages


def store_result(key: str, result: dict) -> None:
    """כותב תשובה מוצלחת למטמון, כולל דריסה של תשובה קיימת (למשל תוצאת ניסיון חוזר של המעבר הראשון)."""
    _dir().mkdir(parents=True, exist_ok=True)
    (_dir() / f"{key}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def cached_extract(images: list[bytes], extract_fn=extract) -> tuple[dict, bool]:
    """מעבר ראשון. מחזיר (תוצאה, from_cache)."""
    return _cached(cache_key(images), extract_fn, images)


def cached_regions(crops: dict[str, bytes], extract_fn=extract_regions) -> tuple[dict, bool]:
    """מעבר שני. מחזיר (תוצאה, from_cache)."""
    return _cached(regions_cache_key(crops), extract_fn, crops)
