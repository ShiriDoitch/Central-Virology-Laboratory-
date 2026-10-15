"""קורא שני למספר המרכזי: פענוח ברקודים מקומי (zxing-cpp, בלי API) מרינדור ה-PDF הנקי בכמה רזולוציות.
הפענוח לא תלוי במודל. rules.apply_center_barcode מחליט מה עושים עם התוצאה."""
import re

import numpy as np
import pymupdf
import zxingcpp

from .center_config import in_center_range

BARCODE_DPIS = (200, 300, 400)
CENTER_BARCODE_FORMAT = "Code128"


def decode_pdf_page(pdf_path: str, page: int, dpis: tuple[int, ...] = BARCODE_DPIS) -> list[dict] | None:
    """כל הברקודים שנפענחו בעמוד (page מבוסס 1): [{"format", "text"}], בלי כפילויות, לפי סדר הגילוי.
    None = הפענוח עצמו נכשל (למשל PDF לא נגיש); [] = לא נמצא ברקוד. בשני המקרים אין שינוי בהחלטות."""
    try:
        doc = pymupdf.open(pdf_path)
        try:
            p = doc[page - 1]
            found: dict[tuple[str, str], None] = {}
            for dpi in dpis:
                pix = p.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), colorspace=pymupdf.csGRAY)
                img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
                for r in zxingcpp.read_barcodes(img, try_rotate=True, try_downscale=True):
                    found.setdefault((str(r.format).replace("BarcodeFormat.", "").replace(" ", ""), r.text), None)
            return [{"format": f, "text": t} for f, t in found]
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
