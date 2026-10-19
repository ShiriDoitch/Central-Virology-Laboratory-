"""הגדרות אחסון תמונות העמודים (config/storage.json). בלי cache, כדי שאפשר לשנות בלי להפעיל מחדש ובבדיקות.
store_page_images (ברירת מחדל true): בשמירת העלאה נכתבת תמונת כל עמוד ל-data/pages/<מזהה העלאה>/p<עמוד>.jpg. false: לא נכתב כלום.
keep_images_after_approval (ברירת מחדל false): כשכל הרשומות של עמוד אושרו, התמונה נמחקת אוטומטית; true משאיר אותה.
דריסה מהסביבה: STORE_PAGE_IMAGES / KEEP_IMAGES_AFTER_APPROVAL (0/1, true/false)."""
import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "storage.json"
DEFAULTS = {"store_page_images": True, "keep_images_after_approval": False}
_TRUE, _FALSE = {"1", "true", "yes", "on"}, {"0", "false", "no", "off"}


def setting(name: str) -> bool:
    if name not in DEFAULTS:
        raise KeyError(name)
    env = (os.getenv(name.upper()) or "").strip().lower()
    if env in _TRUE:
        return True
    if env in _FALSE:
        return False
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get(name)
        if isinstance(value, bool):
            return value
    except Exception:
        pass
    return DEFAULTS[name]
