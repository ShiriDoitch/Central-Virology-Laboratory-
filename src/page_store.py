"""תמונות העמודים השמורות מקומית: data/pages/<מזהה העלאה>/p<עמוד>.jpg.
שמות הקבצים והתיקיות הם מספרים בלבד: אף פעם לא שם הקובץ המקורי, ת"ז או שם. התיקייה (PAGES_DIR) ניתנת לדריסה לבדיקות.
המחיקה מוגבלת במכוון: רק קבצי p<מספר>.jpg ותיקיות מספריות מתחת לתיקיית השורש, כך שנתיב שגוי לא ימחק דבר אחר."""
import os
import re
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "pages"
_FILE = re.compile(r"^p\d+\.jpg$")


def root() -> Path:
    return Path(os.getenv("PAGES_DIR") or DEFAULT_ROOT)


def image_path(upload_id: int, page: int) -> Path:
    return root() / str(int(upload_id)) / f"p{int(page)}.jpg"


def write(upload_id: int, page: int, jpeg: bytes) -> Path:
    path = image_path(upload_id, page)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(jpeg)
    tmp.replace(path)                  # כתיבה אטומית: אין קובץ חצי-כתוב
    return path


def read(upload_id: int, page: int) -> bytes | None:
    try:
        return image_path(upload_id, page).read_bytes()
    except OSError:
        return None


def exists(upload_id: int, page: int) -> bool:
    return image_path(upload_id, page).is_file()


def delete(upload_id: int, page: int) -> bool:
    """מוחק תמונת עמוד אחת. True אם הייתה קיימת. תיקיית ההעלאה הריקה נמחקת גם היא."""
    path = image_path(upload_id, page)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    try:
        path.parent.rmdir()            # רק אם ריקה
    except OSError:
        pass
    return True


def delete_upload(upload_id: int) -> int:
    """מוחק את כל תמונות ההעלאה. מחזיר כמה קבצים נמחקו."""
    folder = root() / str(int(upload_id))
    if not folder.is_dir():
        return 0
    n = 0
    for f in folder.iterdir():
        if f.is_file() and (_FILE.match(f.name) or f.suffix == ".tmp"):
            f.unlink()
            n += 1
    try:
        folder.rmdir()
    except OSError:
        pass
    return n


def delete_all() -> int:
    """מוחק את כל התמונות השמורות (רק תיקיות מספריות עם קבצי p<מספר>.jpg). מחזיר כמה קבצים נמחקו."""
    base = root()
    if not base.is_dir():
        return 0
    n = 0
    for folder in base.iterdir():
        if folder.is_dir() and folder.name.isdigit():
            n += delete_upload(int(folder.name))
    try:
        base.rmdir()                   # רק אם ריקה
    except OSError:
        pass
    return n
