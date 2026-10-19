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


IMAGE_MAX_PIXELS = 20_000_000          # מעל זה העמוד המרונדר נחשב גדול מדי למודל
IMAGE_MAX_BYTES = 8 * 1024 * 1024      # גם JPEG מעל גודל זה נחשב גדול מדי
IMAGE_LONG_SIDE = 2500                 # הצלע הארוכה אחרי הקטנה (פיקסלים)
RETRY_LONG_SIDE = 1600                 # הקטנה חזקה יותר לניסיון החוזר אחרי שגיאת "בקשה גדולה / לא תקינה"


def shrink_jpeg(img: bytes, long_side: int | None = None, quality: int = JPEG_QUALITY) -> bytes:
    """מקטין JPEG כך שהצלע הארוכה היא long_side לכל היותר. תמונה שכבר קטנה מזה, או שאינה תמונה תקינה: מוחזרת כמות שהיא (אותם בתים)."""
    long_side = long_side or IMAGE_LONG_SIDE
    try:
        im = Image.open(io.BytesIO(img))
        if max(im.size) <= long_side:
            return img
        scale = long_side / max(im.size)
        out = io.BytesIO()
        im.convert("RGB").resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS).save(
            out, "JPEG", quality=quality)
        return out.getvalue()
    except Exception:
        return img


def pdf_to_images(path: str, dpi: int = 200, pages: list[int] | None = None) -> list[bytes]:
    """ממיר עמודי PDF ל-JPEG. pages = מספרי עמודים מבוססי 1; None = כולם.
    עמוד שהרינדור שלו היה עולה על IMAGE_MAX_PIXELS (למשל צילום גדול שהומר ל-PDF) מרונדר ישר בגודל מוקטן (צלע ארוכה IMAGE_LONG_SIDE),
    ותוצאה שעדיין עוברת IMAGE_MAX_BYTES מוקטנת בנוסף. כל עמוד אחר: אותם בתים בדיוק כמו תמיד (מפתחות המטמון והריצות השמורות לא משתנים)."""
    doc = pymupdf.open(path)
    try:
        idx = range(len(doc)) if pages is None else [p - 1 for p in pages]
        return [_render_page(doc[i], dpi) for i in idx]
    finally:
        doc.close()


def _render_page(page, dpi: int) -> bytes:
    rect = page.rect
    width_px, height_px = rect.width * dpi / 72, rect.height * dpi / 72
    if width_px * height_px > IMAGE_MAX_PIXELS:
        zoom = IMAGE_LONG_SIDE / max(width_px, height_px) * dpi / 72
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    jpeg = page.get_pixmap(dpi=dpi).tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    return shrink_jpeg(jpeg) if len(jpeg) > IMAGE_MAX_BYTES else jpeg
