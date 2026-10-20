"""מחבר תשובת מודל של עמוד לשורות פלט, בעזרת הכללים ב-rules.py וב-senders.py."""
from datetime import date

from .rules import (
    F_MISSING_REQUIRED, F_MODEL_NOT_FORM, F_NOT_RECOGNIZED_AS_FORM, H_FULL_NAME_SPLIT, commitment_from_region,
    commitment_numbers, decide_center, decide_id, decide_name, decide_receipt_date, expand_rows, has_form_signals,
    split_full_name_fields, split_full_name_regions, verify_commitments,
)
from .schema import PageExtraction
from .senders import decide_sender

# שדות שעדיין לא ממומשים (לא נספרים בדיוק הכולל בדוח)
PENDING_FIELDS: set[str] = set()


def page_rows(result: dict, today: date | None = None, regions: dict | None = None,
              barcodes: list[dict] | None = None) -> list[dict]:
    """שורה לכל התחייבות. עמוד שנכשל: אין שורות.
    הדגל is_commitment_form של המודל לא אמין, ולכן עמוד שסומן "לא התחייבות" מדולג רק אם
    לא נמצא בו מספר התחייבות תקין; אם נמצא, הוא נכנס עם סימון כתום.
    regions = תוצאת המעבר השני (אם קיימת), משמשת לבחירת המרכזי.
    barcodes = ברקודים שפוענחו מקומית מהעמוד (src/barcode.py), קורא שני למרכזי בלבד."""
    if not result.get("ok"):
        return []
    page = PageExtraction.model_validate(result)
    commitments = commitment_numbers(page.numbers)
    if not commitments:
        # אין מועמד במעבר הראשון: מה שנקרא בחיתוך אזור ההתחייבות נכנס ככתום בלבד (לעולם לא ירוק)
        commitments = commitment_from_region(regions)
    not_recognized = False
    if not page.is_commitment_form:
        if commitments:
            commitments = [c.model_copy(update={"flags": [*c.flags, F_MODEL_NOT_FORM]}) for c in commitments]
        elif has_form_signals(page):
            # עמוד בלי מספר התחייבות שהמודל סימן "לא טופס", אבל יש בו סימני טופס (חותמת קבלה / ת"ז / שם):
            # שורה אחת שכל שדותיה כתומים, כדי שייכנס לתור הבדיקה במקום להישמט בשקט
            not_recognized = True
        else:
            return []                                   # באמת לא טופס: מדולג, ומופיע ברשימת "עמודים שדולגו"
    commitments = verify_commitments(commitments, regions)     # ירוק רק כששני המעברים מסכימים על הספרות
    first, last, split1 = split_full_name_fields(page.first_name, page.last_name)     # שדה "שם מלא": פיצול בקוד
    name_regions, split2 = split_full_name_regions(regions)
    base = {
        "first_name": decide_name(first, name_regions, "first_name"),
        "last_name": decide_name(last, name_regions, "last_name"),
        "id": decide_id(page.id_numbers, regions, page.numbers),
        "center": decide_center(page.numbers, regions, barcodes),
        "date": decide_receipt_date(page.dates, today, regions=regions, require_two_readings=True),
        "sender": decide_sender(page.sender_mentions),
    }
    if split1 or split2:
        for key in ("first_name", "last_name"):
            d = base[key]
            base[key] = d.model_copy(update={"hints": [*d.hints, H_FULL_NAME_SPLIT]})
    if not base["first_name"].value and not base["last_name"].value:   # שני השמות ריקים: כתום בשניהם
        for key in ("first_name", "last_name"):
            d = base[key]
            if F_MISSING_REQUIRED not in d.flags:
                base[key] = d.model_copy(update={"flags": [*d.flags, F_MISSING_REQUIRED]})
    for key in ("date", "center", "id"):        # אין ריק שקט בעמוד שסווג כטופס התחייבות
        d = base[key]
        if not d.value and F_MISSING_REQUIRED not in d.flags:
            base[key] = d.model_copy(update={"flags": [*d.flags, F_MISSING_REQUIRED]})
    if not_recognized:                  # כל השדות כתומים, עם הדגל שמסביר למה השורה כאן
        for key, d in base.items():
            if F_NOT_RECOGNIZED_AS_FORM not in d.flags:
                base[key] = d.model_copy(update={"flags": [*d.flags, F_NOT_RECOGNIZED_AS_FORM]})
    rows = expand_rows(base, commitments)
    for r in rows:
        if not r["commitment"] and F_MISSING_REQUIRED not in r["commitment_flags"]:
            r["commitment_flags"] = [*r["commitment_flags"], F_MISSING_REQUIRED]
        if not_recognized and F_NOT_RECOGNIZED_AS_FORM not in r["commitment_flags"]:
            r["commitment_flags"] = [*r["commitment_flags"], F_NOT_RECOGNIZED_AS_FORM]
    return rows
