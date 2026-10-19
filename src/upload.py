"""העלאת קובץ -> עיבוד כל העמודים (שני מעברים) -> עמודים, תמונות תצוגה וחיתוכי תצוגה. בלי תלות ב-Streamlit (לבדיקות).
הקובץ הזמני נמחק בסיום העיבוד, גם בחריגה; התוצאות נשארות בזיכרון בלבד."""
import io
import os
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from .confirm import FIELD_REGION, field_crop
from .intake import pdf_to_images, rotate_jpeg
from . import status
from .privacy import log_server_error

MAX_PAGES = 40


class UploadRejected(ValueError):
    """דחיית קובץ בהודעה שכתבנו בעצמנו (בטוחה להצגה למשתמש). כל חריגה אחרת מוצגת בהודעה כללית והפרטים נרשמים בשרת."""
# קובצי ה-PDF הזמניים של ההעלאות נכתבים לתיקייה ייעודית בפרויקט (ב-.gitignore) ולא לשורש ה-temp של המערכת, כדי שאם התהליך
# נהרג באמצע, שאריות עם נתוני מטופל יימצאו במקום ידוע וינוקו בהפעלה הבאה (cleanup_stale_uploads).
UPLOAD_TMP_DIR = Path(__file__).resolve().parent.parent / "tmp_uploads"


def cleanup_stale_uploads(directory: Path | str | None = None) -> int:
    """מוחק כל קובץ שנשאר בתיקיית ההעלאות הזמניות. נקרא פעם אחת בהפעלת השרת: כל קובץ כזה הוא בהכרח משארית של ריצה קודמת
    שקרסה (בסשן חי הקובץ קיים רק בזמן העיבוד, ובפועל רק בתוך ריצה שנמשכת). בטוח בשני מצבי הפרטיות. מחזיר כמה קבצים נמחקו;
    כשל במחיקת קובץ אחד לא עוצר את השאר."""
    directory = Path(directory) if directory else UPLOAD_TMP_DIR
    if not directory.is_dir():
        return 0
    removed = 0
    for f in directory.iterdir():
        if f.is_file():
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def to_pdf_bytes(name: str, data: bytes) -> bytes:
    """PDF נשאר; תמונה (כולל צילום טלפון עם EXIF) הופכת ל-PDF של עמוד אחד."""
    if name.lower().endswith(".pdf"):
        return data
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return pymupdf.open(stream=buf.getvalue(), filetype="jpeg").convert_to_pdf()


def process_upload(name: str, data: bytes, progress, store=None, on_status=None) -> tuple[list[dict], dict[int, bytes], dict[int, bytes | None]]:
    """מריץ את הצינור המלא (שני מעברים) על כל עמוד. הקובץ הזמני נמחק בסיום.
    store (אופציונלי, src/service.Persister): מקבל start(מספר עמודים), page(תוצאת עמוד) אחרי כל עמוד, ו-finish() בסוף.
    on_status(page, total, text) (אופציונלי): נקרא בזמן העיבוד עם שורת סטטוס בטוחה לפרטיות (src/status.py: קודים ומספרים בלבד, בלי
    טקסט חריגה, שמות קבצים או ערכים). ברירת מחדל: כתיבת הטקסט לשורת ההתקדמות."""
    from src.pipeline import process_page  # ייבוא מאוחר: טעינת הדוגמה לא דורשת מפתח API

    pdf_bytes = to_pdf_bytes(name, data)
    UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=UPLOAD_TMP_DIR)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)
        with pymupdf.open(tmp) as doc:
            total = len(doc)
        if total > MAX_PAGES:
            raise UploadRejected(f"הקובץ כולל {total} עמודים (מקסימום {MAX_PAGES})")
        pages, images, crops = [], {}, {}
        if store is not None:
            store.start(total)
        for p in range(1, total + 1):
            progress.progress((p - 1) / total, text=f"מעבד עמוד {p} מתוך {total}")
            def show(event, p=p):
                text = event["text"]
                if on_status is not None:
                    on_status(p, total, text)
                else:
                    progress.progress((p - 1) / total, text=f"עמוד {p} מתוך {total} · {text}")

            try:
                with status.listening(show):
                    status.emit("page", page=p, of=total)
                    res = process_page(tmp, p)
            except Exception as e:                       # עמוד אחד שנכשל לא מפיל את כל הריצה
                log_server_error(f"process_page {p}", e)
                res = {"page": p, "pass1": {"ok": False, "error": type(e).__name__}, "pass2": None}
            if not (res.get("pass1") or {}).get("ok"):
                log_server_error(f"extract page {p}", (res.get("pass1") or {}).get("error"))     # תגובת ה-API המלאה: רק בשרת
            pages.append(res)
            if store is not None:
                store.page(res)
            img = pdf_to_images(tmp, dpi=110, pages=[p])[0]
            applied = (res.get("rotation") or {}).get("applied")
            images[p] = rotate_jpeg(img, applied) if applied else img
            if (res.get("pass1") or {}).get("ok"):
                for region in dict.fromkeys(FIELD_REGION.values()):         # patient / barcode / commitment / receipt
                    key = next(k for k, r in FIELD_REGION.items() if r == region)
                    crops[(p, region)] = field_crop(tmp, res, key)
        if store is not None:
            store.finish()
        progress.progress(1.0, text="הסתיים")
        return pages, images, crops
    finally:
        Path(tmp).unlink(missing_ok=True)
