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

MAX_PAGES = 40
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


def process_upload(name: str, data: bytes, progress) -> tuple[list[dict], dict[int, bytes], dict[int, bytes | None]]:
    """מריץ את הצינור המלא (שני מעברים) על כל עמוד. הקובץ הזמני נמחק בסיום; אין שמירה של PII."""
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
            raise ValueError(f"הקובץ כולל {total} עמודים (מקסימום {MAX_PAGES})")
        pages, images, crops = [], {}, {}
        for p in range(1, total + 1):
            progress.progress((p - 1) / total, text=f"מעבד עמוד {p} מתוך {total}")
            try:
                res = process_page(tmp, p)
            except Exception as e:                       # עמוד אחד שנכשל לא מפיל את כל הריצה
                res = {"page": p, "pass1": {"ok": False, "error": type(e).__name__}, "pass2": None}
            pages.append(res)
            img = pdf_to_images(tmp, dpi=110, pages=[p])[0]
            applied = (res.get("rotation") or {}).get("applied")
            images[p] = rotate_jpeg(img, applied) if applied else img
            if (res.get("pass1") or {}).get("ok"):
                for region in dict.fromkeys(FIELD_REGION.values()):         # patient / barcode / commitment / receipt
                    key = next(k for k, r in FIELD_REGION.items() if r == region)
                    crops[(p, region)] = field_crop(tmp, res, key)
        progress.progress(1.0, text="הסתיים")
        return pages, images, crops
    finally:
        Path(tmp).unlink(missing_ok=True)
