"""קלט: PDF -> רשימת עמודים כתמונות JPEG (bytes)."""
import io

import pymupdf
from PIL import Image

JPEG_QUALITY = 88  # ~600KB לעמוד ב-200 DPI במקום ~2.7MB ב-PNG: העלאה מהירה יותר ל-API


def rotate_jpeg(img: bytes, degrees: int, quality: int = JPEG_QUALITY) -> bytes:
    """מסובב תמונה ב-degrees מעלות עם כיוון השעון (90 / 180 / 270), כך שהטקסט יהיה ישר."""
    im = Image.open(io.BytesIO(img)).convert("RGB")
    out = io.BytesIO()
    im.rotate(-degrees, expand=True).save(out, "JPEG", quality=quality)
    return out.getvalue()


def render_region(path: str, page: int, fractions: tuple[float, float, float, float],
                  scale: float = 4.0, quality: int = JPEG_QUALITY, rotation: int = 0) -> bytes:
    """מרנדר מחדש אזור מהעמוד ברזולוציה גבוהה (פי scale מ-72 DPI), במקום להגדיל תמונה קיימת.
    fractions = (x0, y0, x1, y1) כשברים 0..1 של העמוד כפי שהוא נראה אחרי הסיבוב.
    rotation = מעלות עם כיוון השעון (0/90/180/270) שמסובבים את העמוד לפני הרינדור (מתאים לתמונה שסובבה
    ב-rotate_jpeg). page מבוסס 1."""
    doc = pymupdf.open(path)
    try:
        p = doc[page - 1]
        if rotation:
            p.set_rotation((p.rotation + rotation) % 360)
        r = p.rect
        x0, y0, x1, y1 = fractions
        clip = pymupdf.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
        pix = p.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip)
        return pix.tobytes("jpeg", jpg_quality=quality)
    finally:
        doc.close()


def pdf_to_images(path: str, dpi: int = 200, pages: list[int] | None = None) -> list[bytes]:
    """ממיר עמודי PDF ל-JPEG. pages = מספרי עמודים מבוססי 1; None = כולם."""
    doc = pymupdf.open(path)
    try:
        idx = range(len(doc)) if pages is None else [p - 1 for p in pages]
        return [doc[i].get_pixmap(dpi=dpi).tobytes("jpeg", jpg_quality=JPEG_QUALITY) for i in idx]
    finally:
        doc.close()
