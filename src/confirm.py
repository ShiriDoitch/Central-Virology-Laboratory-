"""אישור ערכים על ידי המשתמש (כל שבעת השדות): חיתוך האזור הרלוונטי מהעמוד הנקי, והצעות לשדה (אותן אלטרנטיבות שהמערכת שמרה).
המסך (app.py) רק מציג; ההחלטה מה הערך הסופי נשמרת ב-overrides ונכנסת לאקסל דרך export.build_rows."""
import base64
import html
import re

from .crop import REVIEW_MAX_GROW, choose_box, crop_image, edges_touching_ink, expand_receipt_fractions, region_fractions, review_fractions
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


# איזה אזור מהעמוד מציגים לכל שדה: שורת המטופל (שמות, ת"ז), אזור הברקוד (מרכזי), אזור ההתחייבות, אזור הקבלה (תאריך; רק אם המודל
# החזיר receipt_box, אחרת העמוד המלא); שולח: אין חיתוך
FIELD_REGION = {"first_name": "patient", "last_name": "patient", "id": "patient", "center": "barcode", "commitment": "commitment",
                "date": "receipt"}


def override_key(key: str, row_index: int = 0) -> str:
    """מפתח האישור של תא: התחייבות לפי שורה בעמוד, כל שדה אחר לפי עמוד."""
    return COMMITMENT_ROW_KEY.format(row_index) if key == "commitment" else key


def field_fractions(page_res: dict, key: str) -> tuple[float, float, float, float] | None:
    region = FIELD_REGION.get(key)
    if region == "patient":
        return name_row_fractions(page_res)
    used = ((page_res.get("boxes") or {}).get(region) or {}) if region else {}
    return tuple(used["fractions"]) if used.get("fractions") else None


def field_crop(pdf_path: str, page_res: dict, key: str) -> bytes | None:
    """JPEG של האזור שממנו נקרא השדה, מרונדר מחדש מה-PDF הנקי ברזולוציה גבוהה, עם אותו סיבוב שהוחל על העמוד.
    None = אין אזור לשדה הזה (תאריך, שולח) או שהרינדור נכשל: המסך מציג את העמוד המלא."""
    try:
        fr = field_fractions(page_res, key)
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


def stored_field_fractions(page_res: dict) -> dict[str, list[float]]:
    """אזור כל שדה (שברים 0..1 של העמוד אחרי הסיבוב) לשמירה לצד תמונת העמוד. שדה בלי אזור (שולח) לא נכלל."""
    out = {}
    for key in FIELD_REGION:
        try:
            fr = field_fractions(page_res, key)
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
