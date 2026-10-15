"""חיתוך אזורים לפי box מנורמל (0..1000, ymin/xmin/ymax/xmax). CLAUDE.md סעיף 14."""
import io

from PIL import Image

from .schema import Box

# חיתוך קבוע לפי יחסים כשהמודל לא החזיר box או שהוא חשוד (מסומן כתום)
FALLBACK_BOXES = {
    "patient": Box(ymin=0, xmin=0, ymax=500, xmax=1000),
    "barcode": Box(ymin=0, xmin=0, ymax=300, xmax=1000),
}
# שוליים יחסית לגודל ה-box: ברקוד רחב יותר כדי לא לחתוך את המילה המסובבת "מרכזי" שליד המדבקה
MARGINS = {"patient": 0.15, "barcode": 0.25}
MIN_AREA = 0.002   # פחות מ-0.2% מהעמוד: חשוד
COMMITMENT_MIN_AREA = 0.0003   # מספר התחייבות קטן בהרבה מאזור פרטי המטופל
MAX_AREA = 0.9     # יותר מ-90% מהעמוד: לא חיתוך


def is_valid_box(box: Box | None, min_area: float = MIN_AREA) -> bool:
    if box is None:
        return False
    if not all(0 <= v <= 1000 for v in (box.ymin, box.xmin, box.ymax, box.xmax)):
        return False
    if box.ymax <= box.ymin or box.xmax <= box.xmin:
        return False
    area = (box.ymax - box.ymin) * (box.xmax - box.xmin) / 1_000_000
    return min_area <= area <= MAX_AREA


def choose_box(kind: str, box: Box | None) -> tuple[Box, bool]:
    """מחזיר (box לשימוש, האם נפלנו לחיתוך קבוע)."""
    if is_valid_box(box):
        return box, False
    return FALLBACK_BOXES[kind], True


def box_to_fractions(box: Box, margin: float = 0.05, min_pad: float = 0.01) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) כשברים 0..1 של העמוד, עם שוליים (margin = חלק מגודל ה-box, לפחות min_pad מהעמוד).
    לפי סוג האזור: MARGINS[kind]."""
    x0, x1 = box.xmin / 1000, box.xmax / 1000
    y0, y1 = box.ymin / 1000, box.ymax / 1000
    pad_x = max((x1 - x0) * margin, min_pad)
    pad_y = max((y1 - y0) * margin, min_pad)
    return (max(0.0, x0 - pad_x), max(0.0, y0 - pad_y), min(1.0, x1 + pad_x), min(1.0, y1 + pad_y))


# ---------- אזורי המעבר השני (סעיף 14): רצועה לרוחב כל העמוד לפרטי המטופל, ושוליים מינימליים לברקוד ----------
PATIENT_SIDE_MARGIN = 0.02    # הרצועה מכסה x מ-0 עד 1, פחות שוליים קטנים בצדדים
PATIENT_MIN_PAD_Y = 0.04      # לפחות 4% מגובה העמוד מעל ומתחת ל-box (המודל הקטן מחזיר box צר ולא מדויק)
BARCODE_MIN_PAD = 0.04        # שוליים מינימליים לברקוד, בשני הצירים
COMMITMENT_MARGIN, COMMITMENT_MIN_PAD = 0.3, 0.02   # מספר ההתחייבות: שוליים יחסיים, ומינימום 2% מהעמוד
ENLARGE_RETRY = 1.5           # הגדלת הרצועה בניסיון החוזר כשחסרה תווית שם


def patient_band_fractions(box: Box, enlarge: float = 1.0) -> tuple[float, float, float, float]:
    """רצועה לרוחב העמוד: x מ-PATIENT_SIDE_MARGIN עד 1-PATIENT_SIDE_MARGIN, ו-y מה-box עם שוליים של לפחות 4%.
    enlarge > 1: הרצועה כולה מוגדלת בגובהה ביחס למרכזה (למשל 1.5 בניסיון החוזר). ה-x של ה-box לא נבדק:
    עמודות חסרות בגלל box צר היו הבעיה."""
    y0, y1 = box.ymin / 1000, box.ymax / 1000
    pad = max((y1 - y0) * MARGINS["patient"], PATIENT_MIN_PAD_Y)
    y0, y1 = max(0.0, y0 - pad), min(1.0, y1 + pad)
    if enlarge != 1.0:
        mid, half = (y0 + y1) / 2, (y1 - y0) / 2 * enlarge
        y0, y1 = max(0.0, mid - half), min(1.0, mid + half)
    return (PATIENT_SIDE_MARGIN, y0, 1.0 - PATIENT_SIDE_MARGIN, y1)


def region_fractions(kind: str, box: Box, enlarge: float = 1.0) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) לחיתוך האזור: patient = רצועה מלאה לרוחב; barcode = box עם שוליים (לפחות BARCODE_MIN_PAD)."""
    if kind == "patient":
        return patient_band_fractions(box, enlarge)
    if kind == "commitment":
        return box_to_fractions(box, margin=COMMITMENT_MARGIN, min_pad=COMMITMENT_MIN_PAD)
    return box_to_fractions(box, margin=MARGINS[kind], min_pad=BARCODE_MIN_PAD)


# ---------- חיתוך אזור הקבלה (חותמת "התקבל" / מרכזי בכתב יד עם התאריך): שוליים נדיבים, ועוד למטה ----------
RECEIPT_MARGIN = 0.30          # לפחות 30% מגודל ה-box מכל צד
RECEIPT_EXTRA_BOTTOM = 0.60    # ועוד למטה: תאריך בכתב יד נוטה ויוצא מה-box
RECEIPT_MIN_PAD = 0.02         # ולפחות 2% מהעמוד
EDGE_STRIP = 0.02              # רצועת הקצה (חלק מהצלע) שבודקים בה אם דיו נוגע בקצה החיתוך
EDGE_INK_FRACTION = 0.04       # יותר מזה דיו ברצועה = הכתב נחתך בקצה
RECEIPT_ENLARGE = 0.4          # הרחבת צד שבו הדיו נוגע בקצה (חלק מגודל החיתוך), פעם אחת


def _shift_into_page(lo: float, hi: float) -> tuple[float, float]:
    """אם החלון חורג מהעמוד: מזיזים אותו פנימה ומרחיבים לצד השני, במקום לקצץ (שומרים על הגודל)."""
    if lo < 0:
        lo, hi = 0.0, min(1.0, hi - lo)
    if hi > 1:
        lo, hi = max(0.0, lo - (hi - 1)), 1.0
    return lo, hi


def receipt_region_fractions(box: Box) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) כשברים 0..1 של העמוד: ה-box עם שוליים של 30% מכל צד ועוד 60% מגובהו למטה.
    ה-box נוגע בקצה העמוד: החלון מוזז פנימה (גודל נשמר) ולא מקוצץ."""
    x0, x1 = box.xmin / 1000, box.xmax / 1000
    y0, y1 = box.ymin / 1000, box.ymax / 1000
    pad_x = max((x1 - x0) * RECEIPT_MARGIN, RECEIPT_MIN_PAD)
    pad_y = max((y1 - y0) * RECEIPT_MARGIN, RECEIPT_MIN_PAD)
    extra = max((y1 - y0) * RECEIPT_EXTRA_BOTTOM, RECEIPT_MIN_PAD)
    fx0, fx1 = _shift_into_page(x0 - pad_x, x1 + pad_x)
    fy0, fy1 = _shift_into_page(y0 - pad_y, y1 + pad_y + extra)
    return (fx0, fy0, fx1, fy1)


def edges_touching_ink(jpeg: bytes) -> set[str]:
    """אילו קצוות של תמונת החיתוך (left/right/top/bottom, כפי שהחיתוך נראה) נוגעים בדיו: חלק הפיקסלים הכהים ברצועה
    צרה לאורך הקצה גדול מ-EDGE_INK_FRACTION. מצביע על כתב שנחתך בקצה ולכן החיתוך צריך להתרחב."""
    import cv2
    import numpy as np

    gray = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None or gray.size == 0:
        return set()
    _, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = ink.shape
    t_h, t_w = max(2, int(h * EDGE_STRIP)), max(2, int(w * EDGE_STRIP))
    strips = {"top": ink[:t_h, :], "bottom": ink[h - t_h:, :], "left": ink[:, :t_w], "right": ink[:, w - t_w:]}
    return {side for side, s in strips.items() if s.size and float(s.mean()) > EDGE_INK_FRACTION}


def expand_receipt_fractions(fractions: tuple[float, float, float, float], sides: set[str],
                             factor: float = RECEIPT_ENLARGE) -> tuple[float, float, float, float]:
    """מרחיב את הצדדים שהדיו נוגע בהם (עד קצה העמוד). צד שכבר בקצה העמוד לא משתנה."""
    x0, y0, x1, y1 = fractions
    w, h = x1 - x0, y1 - y0
    if "left" in sides:
        x0 = max(0.0, x0 - w * factor)
    if "right" in sides:
        x1 = min(1.0, x1 + w * factor)
    if "top" in sides:
        y0 = max(0.0, y0 - h * factor)
    if "bottom" in sides:
        y1 = min(1.0, y1 + h * factor)
    return (x0, y0, x1, y1)


def crop_image(img: bytes, fractions: tuple[float, float, float, float], scale: float = 2.0, quality: int = 90) -> bytes:
    """לקלט שהוא תמונה (צילום) ולא PDF: חיתוך והגדלה עם Pillow."""
    im = Image.open(io.BytesIO(img)).convert("RGB")
    w, h = im.size
    x0, y0, x1, y1 = fractions
    region = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
    region = region.resize((int(region.width * scale), int(region.height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    region.save(out, "JPEG", quality=quality)
    return out.getvalue()
