"""אישור ערכים על ידי המשתמש (כל שבעת השדות): חיתוך האזור הרלוונטי מהעמוד הנקי, והצעות לשדה (אותן אלטרנטיבות שהמערכת שמרה).
המסך (app.py) רק מציג; ההחלטה מה הערך הסופי נשמרת ב-overrides ונכנסת לאקסל דרך export.build_rows."""
import base64
import html
import re

from .crop import (BARCODE_MIN_PAD, MARGINS, REVIEW_MAX_GROW, choose_box, crop_image, edges_touching_ink, expand_receipt_fractions,
                   pad_fractions, region_fractions, review_fractions, rotate_fractions_cw)
from .export import COMMITMENT_ROW_KEY, FIELD_KEYS, NAME_KEYS, Cell
from .intake import render_region
from .rules import normalize_date
from .schema import Box

_MD_SPECIAL = re.compile(r"([\\`*_\[\]()<>!|~&$#{}])")


def md_text(value) -> str:
    """טקסט שמקורו בטופס (קריאת מודל), בטוח להצגה בתוך st.markdown: תווי Markdown ו-HTML מקבלים backslash, כך שאין תגית, קישור או תמונה."""
    return _MD_SPECIAL.sub(lambda m: "\\" + m.group(1), str(value))


def md_code(value) -> str:
    """קוד מילולי (ת"ז, מרכזי, התחייבות) בגופן מונוספייס; backtick בערך מוחלף כדי שלא יסגור את הטווח."""
    return "`" + str(value).replace("`", "'").replace("\n", " ") + "`"


def flag_chips_html(labels) -> str:
    """תוויות דגל לתוך st.markdown(unsafe_allow_html=True). התווית עוברת html.escape: תווית שמקורה בטופס לא תהפוך לתגית."""
    return " ".join(f"<span class='flag'>{html.escape(str(label))}</span>" for label in labels)


NAME_CROP_SCALE = 3.0     # רזולוציה גבוהה: הקורא האנושי מגדיל את התמונה


def name_row_fractions(page_res: dict) -> tuple[float, float, float, float]:
    """אותה רצועת מטופל שהמעבר השני חתך (אם נחתכה), אחרת לפי patient_box של המעבר הראשון (או חיתוך קבוע)."""
    used = ((page_res.get("boxes") or {}).get("patient") or {})
    if used.get("retry_fractions"):
        return tuple(used["retry_fractions"])
    if used.get("fractions"):
        return tuple(used["fractions"])
    raw = (page_res.get("pass1") or {}).get("patient_box")
    box, _fallback = choose_box("patient", Box(**raw) if raw else None)
    return region_fractions("patient", box)


def name_row_crop(pdf_path: str, page_res: dict) -> bytes | None:
    """JPEG של שורת פרטי המטופל, מרונדר מחדש מה-PDF הנקי ברזולוציה גבוהה, עם אותו סיבוב שהוחל על העמוד.
    נכשל (למשל PDF לא נגיש): None, והמסך מציג את העמוד המלא."""
    try:
        applied = (page_res.get("rotation") or {}).get("applied") or 0
        return render_region(pdf_path, page_res["page"], name_row_fractions(page_res), scale=NAME_CROP_SCALE, rotation=applied)
    except Exception:
        return None


def name_suggestions(cell: Cell, key: str | None = None) -> list[str]:
    """ההצעות של המערכת לתא (ערך אם יש, ואחריו האלטרנטיבות), בלי כפילויות ובלי ריקים; גם לתא ריק. לא ערכים מאושרים.
    למרכזי: גם ערכי הברקוד שנבדלו מקריאת המודל (הרמז center_barcode_differs)."""
    out: list[str] = []
    extra = [v for h in cell.hints if key == "center" and h.startswith("center_barcode_differs:")
             for v in h.split(":", 1)[1].split(" ; ")]
    for v in [cell.original if cell.confirmed else cell.value, *cell.alternatives, *extra]:
        v = (v or "").strip()
        if v and v not in out:
            out.append(v)
    return out


# לאיזה שדה יש מושג "אזור בטופס" בכלל (ולכן נסיון אימות, אחרת העמוד המלא בלי שום ניסיון): שמות ות"ז, מרכזי, התחייבות,
# תאריך. שולח: אין אזור, אין נסיון אימות, ואין שינוי בהודעה הקיימת ("אין חיתוך זמין לשדה הזה").
FIELD_REGION = {"first_name": "patient", "last_name": "patient", "id": "patient", "center": "barcode", "commitment": "commitment",
                "date": "receipt"}

# ראיה שלא אומתה מקומית לעולם לא מוצגת כסימון/חיתוך (CLAUDE.md: "המודל מתאר, הקוד מחליט" חל גם על תצוגת הראיה):
# box שהמודל "הצהיר" עליו (patient_box / barcode_box / commitment_box / receipt_box) יכול להצביע על מקום שגוי בעמוד
# (למשל ברקוד אחר), והבודקת מאשרת לפי התמונה - תמונה שגויה גרועה מהיעדר תמונה. האימות היחיד שיש היום: מספר שפוענח
# מקומית מברקוד (src/barcode.py, בלי API) ושווה בדיוק לערך שהוחלט; אין עוד הסתמכות על ה-box של המודל לתצוגה (pipeline.py
# עדיין משתמש בו לחיתוך שנשלח למעבר השני - זה לא השתנה). ערך שלא נמצא בשום ברקוד: בלי חיתוך, בלי סימון, העמוד המלא
# עם ההערה NOT_VERIFIED_NOTE.
NOT_VERIFIED_NOTE = "המיקום המדויק לא ידוע, יש לחפש בטופס"


def override_key(key: str, row_index: int = 0) -> str:
    """מפתח האישור של תא: התחייבות לפי שורה בעמוד, כל שדה אחר לפי עמוד."""
    return COMMITMENT_ROW_KEY.format(row_index) if key == "commitment" else key


def verified_barcode_box(barcodes: list[dict] | None, applied_rotation: int, value: str | None) -> tuple[float, float, float, float] | None:
    """תיבת השברים המאומתת מקומית לערך (אחרי הסיבוב שהוחל על העמוד): כל חלקי value (אם כמה, מחוברים ב-" ; ") הם הטקסט
    שפוענח מברקוד שהמיקום שלו ידוע (src/barcode.py). None = אין ברקוד תואם לכל חלקי הערך (או שאין ברקודים/ערך כלל)."""
    value = (value or "").strip()
    if not value or not barcodes:
        return None
    parts = [p for p in value.split(" ; ") if p]
    if not parts:
        return None
    boxes = []
    for part in parts:
        box = next((b.get("box") for b in barcodes if b.get("box") and (b.get("text") or "").strip() == part), None)
        if not box:
            return None
        boxes.append(box)
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    rotated = rotate_fractions_cw((x0, y0, x1, y1), applied_rotation or 0)
    return pad_fractions(rotated, margin=MARGINS["barcode"], min_pad=BARCODE_MIN_PAD)


def field_fractions(page_res: dict, key: str, value: str | None = None) -> tuple[float, float, float, float] | None:
    """האזור המאומת מקומית לשדה (ראו verified_barcode_box), או None: לשדה הזה אין מושג אזור כלל (FIELD_REGION), או
    שאין אימות מקומי לערך שהוחלט (גם אם למודל "יש box" - הוא לא נבדק ולא מוצג). value = הערך שהוחלט לשדה; None = בלי
    ניסיון אימות (למשל כש-value עדיין לא ידוע בנקודה הזאת)."""
    if not FIELD_REGION.get(key):
        return None
    applied = (page_res.get("rotation") or {}).get("applied") or 0
    return verified_barcode_box(page_res.get("barcodes"), applied, value)


def field_crop(pdf_path: str, page_res: dict, key: str, value: str | None = None) -> bytes | None:
    """JPEG של האזור המאומת שממנו נקרא השדה, מרונדר מחדש מה-PDF הנקי ברזולוציה גבוהה, עם אותו סיבוב שהוחל על העמוד.
    None = אין אזור מאומת לשדה הזה: המסך מציג את העמוד המלא, בלי סימון שלא אומת."""
    try:
        fr = field_fractions(page_res, key, value)
        if not fr:
            return None
        applied = (page_res.get("rotation") or {}).get("applied") or 0
        return review_crop(lambda f: render_region(pdf_path, page_res["page"], f, scale=NAME_CROP_SCALE, rotation=applied), fr)
    except Exception:
        return None


def review_crop(render, fr: tuple[float, float, float, float]) -> bytes:
    """החיתוך שמוצג לאדם: חלון נדיב יותר מזה שהמודל קרא (review_fractions; הקריאה עצמה לא משתנה), ודיו שעדיין נוגע בקצה = ספרות
    שנחתכו: מרחיבים את הצד הזה ומרנדרים שוב. render(fractions) -> JPEG. משותף למסך העיבוד (רינדור מה-PDF) ולכרטיס הרשומה (חיתוך
    מתמונת העמוד השמורה), כך ששניהם מציגים אותו אזור באותה לוגיקה."""
    fr = review_fractions(fr)
    jpeg = render(fr)
    for _ in range(REVIEW_MAX_GROW):
        sides = edges_touching_ink(jpeg)
        if not sides:
            break
        wider = expand_receipt_fractions(fr, sides & {"left", "right", "top", "bottom"})
        if wider == fr:
            break
        fr = wider
        jpeg = render(fr)
    return jpeg


def stored_field_fractions(page_res: dict, values: dict[str, str | None] | None = None) -> dict[str, list[float]]:
    """אזור מאומת מקומית לכל שדה (שברים 0..1 של העמוד אחרי הסיבוב), לשמירה לצד תמונת העמוד: ראיה לכרטיס הרשומה ולמסך
    הבדיקה המונחית אחרי רענון, בלי PDF זמין (אין יותר מעבר על box שהמודל דיווח). שדה בלי אימות לא נכלל (ולא רק שולח/תאריך).
    values = הערך שהוחלט לכל שדה (בעמוד עם כמה התחייבויות: הערך של השורה הראשונה - מרכזי ופרטי המטופל משותפים לכל השורות
    באותו עמוד; מגבלה ידועה לגבי התחייבות עצמה, שכבר הייתה קיימת: אזור אחד נשמר לעמוד, לא לפי שורה)."""
    values = values or {}
    out = {}
    for key in FIELD_REGION:
        try:
            fr = field_fractions(page_res, key, values.get(key))
        except Exception:
            fr = None
        if fr:
            out[key] = [round(float(x), 4) for x in fr]
    return out


def field_crop_from_image(image: bytes, fractions: list[float] | tuple | None) -> bytes | None:
    """חיתוך השדה מתמונת העמוד השמורה (JPEG אחרי הסיבוב). None אם אין אזור או שהחיתוך נכשל."""
    if not fractions:
        return None
    try:
        return review_crop(lambda f: crop_image(image, f, scale=2.0), tuple(fractions))
    except Exception:
        return None


_DIGITS = re.compile(r"\d+")


def normalize_override(key: str, text: str | None) -> str | None:
    """מה שהמשתמש הקליד -> הערך הסופי של התא, או None אם לא תקין. ריק -> None.
    ת"ז והתחייבות: ספרות בלבד (רווחים ומקפים מוסרים); מרכזי: ספרות, כמה ערכים מופרדים ב-; או , (מחוברים ב-" ; ");
    תאריך: dd.mm.yyyy לפי אותו נרמול של המערכת (פורמט בלבד, לא מתקן); שם וגורם שולח: טקסט חופשי."""
    text = (text or "").strip()
    if not text:
        return None
    base = key.split("#")[0]
    if base in ("id", "commitment"):
        digits = re.sub(r"[\s\-]", "", text)
        return digits if _DIGITS.fullmatch(digits) else None
    if base == "center":
        parts = [re.sub(r"[\s\-]", "", p) for p in re.split(r"[;,\n]", text) if p.strip()]
        return " ; ".join(dict.fromkeys(parts)) if parts and all(_DIGITS.fullmatch(p) for p in parts) else None
    if base == "date":
        return normalize_date(text).value
    return text


# מה מותר להקליד בכל שדה (בדיוק מה ש-normalize_override מקבל). מוצג לצד שדה הקלט בכל מסך שבו מקלידים ערך.
INPUT_HINTS = {"id": "ספרות בלבד", "commitment": "ספרות בלבד", "center": "ספרות; כמה ערכים מופרדים ב-;", "date": "dd.mm.yyyy"}


def set_override(overrides: dict, page: int, key: str, value: str | None) -> None:
    """שומר את הערך שהמשתמש הקליד או בחר כערך סופי לתא בעמוד. ערך ריק מבטל את האישור. ערך לא תקין לשדה (למשל אותיות
    בת"ז): ValueError והאישור הקודם לא משתנה. key = שם שדה, או "commitment#<שורה>" להתחייבות (override_key)."""
    if key.split("#")[0] not in FIELD_KEYS:
        raise ValueError(f"unknown field {key!r}")
    if not (value or "").strip():
        overrides.pop((page, key), None)
        return
    normalized = normalize_override(key, value)
    if not normalized:
        raise ValueError(f"invalid value for {key}")
    overrides[(page, key)] = normalized


ZOOM_BASE_PX = 480        # רוחב התמונה בהגדלה 100%; ההגדלה האמיתית = ZOOM_BASE_PX * zoom / 100 פיקסלים
ZOOM_BOX_HEIGHT_PX = 320


def zoom_html(jpeg: bytes, zoom_pct: int, base_px: int = ZOOM_BASE_PX, box_height_px: int = ZOOM_BOX_HEIGHT_PX) -> str:
    """תמונה ברוחב מפורש בפיקסלים (base_px * zoom_pct / 100) בתוך מיכל נגלל. st.image(width=...) מוגבל לרוחב העמודה ולכן
    ההגדלה לא נראתה; כאן max-width:none, והמיכל נגלל (direction:rtl: הגלילה מתחילה בצד הימני, שם נמצאים השמות)."""
    width = round(base_px * zoom_pct / 100)
    src = base64.b64encode(jpeg).decode()
    return (f'<div class="name-zoom" data-width="{width}" style="overflow:auto; max-height:{box_height_px}px; border:1px solid #ccc; '
            f'direction:rtl; background:#fff"><img alt="שורת פרטי המטופל" src="data:image/jpeg;base64,{src}" '
            f'style="width:{width}px; max-width:none; display:block"></div>')


def region_zoom_html(jpeg: bytes, zoom_pct: int, fractions: tuple | list | None = None, base_px: int = 720,
                     box_height_px: int = ZOOM_BOX_HEIGHT_PX) -> str:
    """העמוד המלא בתוך מיכל נגלל, עם מסגרת מסומנת סביב האזור שממנו נקרא השדה (שברי x0,y0,x1,y1 של העמוד,
    כפי שנשמרו לצד התמונה). בלי שברים: העמוד בלבד, בלי סימון. שום נתון מהטופס לא נכנס ל-HTML: רק מספרים."""
    width = round(base_px * zoom_pct / 100)
    src = base64.b64encode(jpeg).decode()
    mark = ""
    if fractions and len(tuple(fractions)) == 4:
        x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in fractions)
        mark = (f'<div class="pg-mark" style="left:{x0 * 100:.2f}%; top:{y0 * 100:.2f}%; '
                f'width:{max(x1 - x0, 0.0) * 100:.2f}%; height:{max(y1 - y0, 0.0) * 100:.2f}%"></div>')
    return (f'<div class="name-zoom" data-width="{width}" style="overflow:auto; max-height:{box_height_px}px; border:1px solid #ccc; '
            f'direction:rtl; background:#fff"><div class="pg-wrap" style="position:relative; width:{width}px">'
            f'<img alt="העמוד המקורי עם סימון האזור של השדה" src="data:image/jpeg;base64,{src}" '
            f'style="width:{width}px; max-width:none; display:block">{mark}</div></div>')
