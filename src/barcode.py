"""קורא שני למספר המרכזי: פענוח ברקודים מקומי (zxing-cpp, בלי API) מרינדור ה-PDF הנקי בכמה רזולוציות.
הפענוח לא תלוי במודל. rules.apply_center_barcode מחליט מה עושים עם התוצאה."""
import re

import numpy as np
import pymupdf
import zxingcpp

from .center_config import in_center_range

BARCODE_DPIS = (200, 300, 400)
CENTER_BARCODE_FORMAT = "Code128"


def _box_fractions(position, width: int, height: int) -> list[float] | None:
    """תיבת השברים (x0,y0,x1,y1 כ-0..1 של העמוד) של סימן הברקוד, מארבע הפינות שה-decoder מחזיר ביחידות פיקסל
    של התמונה שפוענחה (position תמיד במערכת הצירים של התמונה שהוזנה, בלי תלות בסיבוב הפנימי של הסימן).
    זו תיבת השברים של העמוד *כפי שפוענח* (בלי rotation.applied); confirm.verified_barcode_box מסבב אותה בהתאם."""
    if position is None or not width or not height:
        return None
    xs = (position.top_left.x, position.top_right.x, position.bottom_left.x, position.bottom_right.x)
    ys = (position.top_left.y, position.top_right.y, position.bottom_left.y, position.bottom_right.y)
    return [min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height]


def decode_pdf_page(pdf_path: str, page: int, dpis: tuple[int, ...] = BARCODE_DPIS) -> list[dict] | None:
    """כל הברקודים שנפענחו בעמוד (page מבוסס 1): [{"format", "text", "box"}], בלי כפילויות, לפי סדר הגילוי.
    box = תיבת השברים של הסימן בעמוד (ראו _box_fractions), או None אם המיקום לא זמין.
    None (לא רשימה) = הפענוח עצמו נכשל (למשל PDF לא נגיש); [] = לא נמצא ברקוד. בשני המקרים אין שינוי בהחלטות."""
    try:
        doc = pymupdf.open(pdf_path)
        try:
            p = doc[page - 1]
            found: dict[tuple[str, str], list[float] | None] = {}
            for dpi in dpis:
                pix = p.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), colorspace=pymupdf.csGRAY)
                img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
                for r in zxingcpp.read_barcodes(img, try_rotate=True, try_downscale=True):
                    key = (str(r.format).replace("BarcodeFormat.", "").replace(" ", ""), r.text)
                    if key not in found:
                        found[key] = _box_fractions(r.position, pix.width, pix.height)
            return [{"format": f, "text": t, "box": box} for (f, t), box in found.items()]
        finally:
            doc.close()
    except Exception:
        return None


def center_barcode_values(barcodes: list[dict] | None, kind: str = "barcode_match") -> list[str]:
    """ערכי מרכזי אפשריים מהברקודים: Code128, ספרות בלבד, באורך מרכזי לפי kind (center_config: barcode_match / barcode_fill), בלי כפילויות."""
    out: list[str] = []
    for b in barcodes or []:
        text = (b.get("text") or "").strip()
        if str(b.get("format", "")).replace(" ", "").upper() == CENTER_BARCODE_FORMAT.upper() and \
                re.fullmatch(r"\d+", text) and in_center_range(text, kind) and text not in out:
            out.append(text)
    return out
