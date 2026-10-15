"""כללי החלטה בקוד (לא במודל).

נרמול = המרה לפורמט אחיד בלבד, בלי "תיקון" שגיאות (CLAUDE.md סעיף 16).
ערך שאי אפשר להמיר או שאינו חוקי נשאר ריק ומסומן; לא מנחשים.

flags = סיבות להצגה בכתום ("לא בטוח"). hints = רמזים רכים שלא צובעים בכתום.
"""
import re
from datetime import date, timedelta

from pydantic import BaseModel, Field

from .center_config import in_center_range
from .schema import DateCandidate, Field_, NumberCandidate

LOW_CONFIDENCE = 0.7   # מתחת לזה: ביטחון נמוך (לא לסמוך על הביטחון שהמודל מצהיר; זה רק סימן נוסף)
YEAR_SPAN = 1          # טווח שנים סביר סביב השנה הנוכחית

# דגלים (כתום)
F_HANDWRITTEN = "handwritten"
F_LOW_CONFIDENCE = "low_confidence"
F_CONFLICT = "conflict"
F_INVALID_FORMAT = "invalid_format"
F_INVALID_DATE = "invalid_date"
F_YEAR_OUT_OF_RANGE = "year_out_of_range"
F_RECEIPT_BEFORE_SAMPLE = "receipt_before_sample"
F_NOT_RECEIPT_KIND = "not_receipt_kind"
F_NOT_LAB_RECEIVED = "not_lab_received"
F_NON_DIGIT = "non_digit"
F_NO_COMMITMENT = "no_commitment"
F_NO_CENTER_LABEL = "no_center_label"
F_CENTER_MISMATCH = "center_mismatch"
F_ID_SINGLE_SOURCE = "id_single_source"
F_REGION_NOT_OK = "region_not_ok"
F_HANDWRITTEN_UNCONFIRMED = "handwritten_unconfirmed"
F_FATHER_NAME = "father_name"
F_NAME_LABEL_UNKNOWN = "name_label_unknown"
F_NAME_LABEL_MISSING = "name_label_missing"
F_MISSING_REQUIRED = "missing_required_field"
F_DATE_KIND_UNCLEAR = "date_kind_unclear"
F_WEAK_LABEL = "weak_label"
F_COMMITMENT_MISMATCH = "commitment_mismatch"
F_COMMITMENT_SINGLE_SOURCE = "commitment_single_source"
F_MODEL_NOT_FORM ="model_says_not_commitment_form"
F_CENTER_FROM_BARCODE_ONLY = "center_from_barcode_only"
F_DATE_OUTSIDE_WINDOW = "date_outside_window"    # תאריך קבלה מחוץ לחלון [תאריך דגימה, שליחה/דגימה + 14 יום, לא בעתיד, לא אחרי תוקף]
F_DATE_SINGLE_SOURCE = "date_single_source"      # תאריך שנקרא פעם אחת בלבד (בלי קריאה שנייה מחיתוך אזור הקבלה): כתום
F_ID_CHECKSUM_FAILED = "id_checksum_failed"      # ספרת ביקורת נכשלה: תמיד כתום (הערך לא נפסל ולא משתנה)
F_ID_NOT_ISRAELI = "id_not_israeli_format"       # יותר מ-9 ספרות אחרי הסרת אפסים, או אותיות (דרכון): לא בודקים ספרת ביקורת

# רמזים (לא כתום)
H_ID_FROM_POOL = "id_from_general_list"
H_ID_CHECKSUM_REPLACED = "id_replaced_by_valid_checksum"
H_TWO_DIGIT_YEAR = "two_digit_year"
H_FULL_NAME_SPLIT = "split_from_full_name"
H_CENTER_BARCODE_AGREES = "center_barcode_agrees"     # קורא שני למרכזי: הברקוד שווה בדיוק לקריאת המודל
H_TWO_READS = "two_readings_agree"       # מעבר ראשון + מעבר שני תקין קראו את אותו ערך (רק ת"ז ושמות): תנאי לצהוב

COMMITMENT_LABEL_WORDS = ("התחייבות", "דרישה", "דגימה", "אסמכתא")
MIN_FALLBACK_DIGITS = 4  # בטבלת האמת מספר ההתחייבות הקצר ביותר הוא 4 ספרות


class Decision(BaseModel):
    value: str | None = None
    raw: str | None = None
    flags: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)

    @property
    def uncertain(self) -> bool:
        return bool(self.flags)


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _uncertainty_flags(items: list[tuple[str, float]]) -> list[str]:
    """items = (source, confidence) של כל ההופעות שמסכימות על אותו ערך.
    כתב יד מסומן רק אם כולן בכתב יד (הופעה מודפסת מסכימה = ודאות)."""
    flags = []
    if items and all(s == "handwritten" for s, _ in items):
        flags.append(F_HANDWRITTEN)
    if items and max(c for _, c in items) < LOW_CONFIDENCE:
        flags.append(F_LOW_CONFIDENCE)
    return flags


# ---------- ת"ז ----------

def normalize_digits(raw: str | None) -> str | None:
    """ספרות בלבד (בלי רווחים/מקפים). ריק -> None."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits or None


def check_israeli_id(digits: str) -> bool:
    """ספרות בלבד: הסרת אפסים מובילים, ריפוד ל-9 ספרות ובדיקת ספרת ביקורת. ריק (כולו אפסים) או יותר מ-9 ספרות: False.
    משמשת לצבע התא (decide_id), להצעות תיקון (id_checksum_suggestions) ולסינון מועמדים נוספים (id_pool_extras);
    לעולם לא פוסלת ערך."""
    n = digits.lstrip("0")
    if not n or len(n) > 9:
        return False
    total = 0
    for i, ch in enumerate(n.zfill(9)):
        d = int(ch) * (1 if i % 2 == 0 else 2)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


# זוגות ספרות שנוטים להתבלבל בקריאה (שני הכיוונים): 1↔7, 2↔9, 3↔8, 5↔6, 0↔8, 4↔9
_CONFUSABLE = {"1": "7", "7": "1", "2": "9", "9": "24", "3": "8", "8": "30", "5": "6", "6": "5", "0": "8", "4": "9"}


MAX_ID_SUGGESTIONS = 3


def id_checksum_suggestions(digits: str) -> list[str]:
    """לערך שנכשל בספרת הביקורת: כל החלפות הספרה האחת (לפי _CONFUSABLE) שעוברות את הבדיקה, לפי סדר המיקום, עד
    MAX_ID_SUGGESTIONS. אם עוברות יותר מזה: אף אחת (יותר מדי כדי להיות הצעה שימושית). הצעות בלבד, לעולם לא ממלאים
    אוטומטית."""
    passing = list(dict.fromkeys(
        digits[:i] + alt + digits[i + 1:]
        for i, ch in enumerate(digits) for alt in _CONFUSABLE.get(ch, "")
        if check_israeli_id(digits[:i] + alt + digits[i + 1:])))
    return passing if len(passing) <= MAX_ID_SUGGESTIONS else []


_ID_LABEL = re.compile(r"(?<![א-ת])ת[\"״'.\s]*ז(?![א-ת])|זהות|מטופל")


def is_id_label(label: str | None) -> bool:
    """תווית שמזהה ת"ז של מטופל: ת.ז / ת"ז / תעודת זהות / מטופל."""
    return bool(label and _ID_LABEL.search(label))


def is_id_candidate(c: NumberCandidate) -> bool:
    """מועמד ת"ז: תווית ת"ז, או ערך בכתב יד (ת"ז בטפסים נכתבת ביד, לפעמים בלי תווית; כתום ממילא).
    מספר מודפס בלי תווית ת"ז (מספר מקרה, ברקוד, טלפון) אינו מועמד."""
    return is_id_label(c.label) or c.source == "handwritten"


def region_state(regions: dict | None, kind: str, field: str | None = None) -> str:
    """מצב חיתוך של המעבר השני (kind = "patient" | "barcode"):
    absent = אין מעבר שני (לא רץ, דולג או נכשל); ok = region_ok=true; not_ok = המודל אמר שזה לא האזור הנכון.
    field (לחיתוך המטופל: first_name | last_name | id_number): תקינות לפי שדה. שדה שהתווית שלו לא נראתה
    בחיתוך (patient.field_ok, ראו apply_field_validity) הוא not_ok גם כשהחיתוך תקין לשדות אחרים."""
    if not regions or not regions.get("ok"):
        return "absent"
    if not regions.get(kind, {}).get("region_ok"):
        return "not_ok"
    if field and (regions[kind].get("field_ok") or {}).get(field) is False:
        return "not_ok"
    return "ok"


def patient_labels_missing(regions: dict | None) -> bool:
    """במעבר שני תקין: האם חסרה תווית שם פרטי או שם משפחה בחיתוך המטופל (לפי labels_seen של המודל)."""
    if not regions or not regions.get("ok") or "patient" not in regions:
        return False
    seen = set(regions["patient"].get("labels_seen") or [])
    if full_name_label_seen(regions):
        seen |= {"first_name", "last_name"}              # שדה "שם מלא" במקום שתי תוויות
    return not {"first_name", "last_name"} <= seen


_FIELD_LABELS = ("first_name", "last_name", "id_number")


def apply_field_validity(regions: dict) -> dict:
    """תקינות לפי שדה בחיתוך המטופל: שדה תקין רק אם התווית שלו נראתה (labels_seen). ת"ז תקפה גם כשתוויות השמות
    לא נראו, ושם תקף רק אם התווית שלו נראתה. שדה לא תקין: הקריאה ממנו לא נכנסת, והשדה כתום (region_not_ok)."""
    seen = set(regions["patient"].get("labels_seen") or [])
    if full_name_label_seen(regions):
        seen |= {"first_name", "last_name"}
    patient = {**regions["patient"], "field_ok": {f: f in seen for f in _FIELD_LABELS}}
    return {**regions, "patient": patient}


def _with_region_flag(d: Decision, state: str) -> Decision:
    """חיתוך שנפסל (region_ok=false): הקריאה ממנו לא נכנסת, והשדה כתום (גם אם ריק)."""
    if state != "not_ok":
        return d
    return d.model_copy(update={"flags": _dedupe([*d.flags, F_REGION_NOT_OK])})


ID_POOL_MIN_DIGITS, ID_POOL_MAX_DIGITS = 7, 9


def id_pool_extras(numbers: list[NumberCandidate]) -> list[str]:
    """מועמדי ת"ז נוספים מהרשימה הכללית: מספרים בכתב יד, ספרות בלבד, 7-9 ספרות, **ורק אם עוברים ספרת ביקורת**
    (ספרת הביקורת מסננת מספרים אחרים בכתב יד, כמו מספרי התחייבות). בלי כפילויות (אחרי הסרת אפסים מובילים)."""
    out: list[str] = []
    for n in numbers:
        v = n.value.strip()
        if (n.source == "handwritten" and v.isdigit() and ID_POOL_MIN_DIGITS <= len(v) <= ID_POOL_MAX_DIGITS
                and check_israeli_id(v) and all(v.lstrip("0") != o.lstrip("0") for o in out)):
            out.append(v)
    return out


def _apply_id_pool(core: Decision, extras: list[str]) -> Decision:
    """מוסיף למאגר את המועמדים הכלליים (id_pool_extras). אין העדפה לכתב יד: ערכים שונים = סתירה.
    - אין קריאה ראשית כלל: מועמד כללי יחיד = ערך (כתום, כתב יד); כמה = סתירה.
    - הקריאה הראשית נכשלת בספרת ביקורת ויש מועמד כללי תקין יחיד: הוא נבחר (הראשית ב-alternatives).
    - הקריאה הראשית עוברת ספרת ביקורת ויש מועמד כללי תקין שונה: סתירה.
    - סתירה קיימת בין הקריאות הראשיות: ללא שינוי."""
    own = core.value.lstrip("0") if core.value else None
    extras = [e for e in extras if e.lstrip("0") != own]
    if not extras:
        return core
    if core.value is None:
        if core.flags:
            return core
        if len(extras) == 1:
            return Decision(value=extras[0], raw=extras[0], flags=[F_HANDWRITTEN], hints=[H_ID_FROM_POOL])
        return Decision(flags=[F_CONFLICT], alternatives=extras)
    if not check_israeli_id(core.value) and len(extras) == 1:
        return Decision(value=extras[0], raw=extras[0], flags=[F_HANDWRITTEN], alternatives=[core.value],
                        hints=[H_ID_FROM_POOL, H_ID_CHECKSUM_REPLACED])
    return Decision(flags=[F_CONFLICT], alternatives=_dedupe([core.value, *extras]))


def decide_id(candidates: list[NumberCandidate], regions: dict | None = None,
              numbers: list[NumberCandidate] | None = None) -> Decision:
    """ת"ז מהמעבר הראשון, ואם קיים וחיתוך המטופל תקין (region_ok) גם מהמעבר השני כקריאה נוספת:
    הסכמה = ערך, אי-הסכמה = סתירה. חיתוך שנפסל: לא נכנס, והשדה כתום.
    numbers = הרשימה הכללית של המספרים: ממנה נכנסים למאגר מועמדים נוספים לפי id_pool_extras.
    ת"ז שנקראה רק במעבר השני (במעבר הראשון אין מועמד שתויג כת"ז): כתום, דגל id_single_source, והמספר ב-alternatives."""
    state = region_state(regions, "patient", "id_number")
    cands = list(candidates)
    pass2_digits = None
    if state == "ok":
        f = regions["patient"]["id_number"]
        if f.get("value"):
            pass2_digits = normalize_digits(f["value"])
            cands.append(NumberCandidate(value=f["value"], label="ת.ז.", source=f.get("source", "unknown"),
                                         confidence=f.get("confidence", 0.0)))
    # מספר שנקרא רק במעבר השני ולא תויג כת"ז במעבר הראשון: מקור יחיד (בלי ספרת ביקורת כהכרעה)
    first_pass_tagged = any(is_id_candidate(c) and normalize_digits(c.value) for c in candidates)
    core = _decide_id_core(cands)
    # שתי קריאות עצמאיות מסכימות: המעבר הראשון תייג ת"ז, והמעבר השני (חיתוך תקין) קרא אותה ספרה אחר ספרה
    two_reads = bool(pass2_digits and first_pass_tagged and core.value and set(core.flags) <= {F_HANDWRITTEN}
                     and core.value.lstrip("0") == pass2_digits.lstrip("0"))
    if numbers:
        core = _apply_id_pool(core, id_pool_extras(numbers))
    if two_reads and core.value and core.value.lstrip("0") == pass2_digits.lstrip("0"):
        core = core.model_copy(update={"hints": _dedupe([*core.hints, H_TWO_READS])})
    core = _apply_id_checksum(core)
    if pass2_digits and core.value == pass2_digits and not first_pass_tagged:
        core = core.model_copy(update={"flags": _dedupe([*core.flags, F_ID_SINGLE_SOURCE]),
                                       "alternatives": _dedupe([*core.alternatives, core.value])})
    return _with_region_flag(core, state)


def _apply_id_checksum(core: Decision) -> Decision:
    """ספרת הביקורת מחליטה רק צבע והצעה; היא לא פוסלת ולא משנה את הערך.
    - ערך עם אותיות (דרכון) או יותר מ-9 ספרות אחרי הסרת אפסים: לא בודקים; דגל id_not_israeli_format (כתום).
    - עוברת ושתי קריאות עצמאיות מסכימות (רמז two_readings_agree, הדגל היחיד handwritten): ירוק, גם בכתב יד.
    - עוברת בלי שתי קריאות: ללא שינוי (כתב יד נשאר כתום).
    - נכשלת: תמיד כתום, id_checksum_failed, גם כששתי הקריאות מסכימות. אם החלפת ספרה אחת (זוגות מבולבלים) נותנת
      עד 3 ערכים שעוברים: הם ב-alternatives כהצעות (יותר מ-3: אין הצעות)."""
    if not core.value:
        return core
    if F_ID_NOT_ISRAELI in core.flags:
        return core
    if len(core.value.lstrip("0")) > 9:
        return core.model_copy(update={"flags": _dedupe([*core.flags, F_ID_NOT_ISRAELI])})
    if check_israeli_id(core.value):
        if H_TWO_READS in core.hints and core.flags == [F_HANDWRITTEN]:
            return core.model_copy(update={"flags": []})
        return core
    return core.model_copy(update={"flags": _dedupe([*core.flags, F_ID_CHECKSUM_FAILED]),
                                   "alternatives": _dedupe([*core.alternatives, *id_checksum_suggestions(core.value)])})


def _decide_id_core(candidates: list[NumberCandidate]) -> Decision:
    """ת"ז מכל ההופעות. רק מועמדים לפי is_id_candidate (לא כל מספר ארוך).
    אורך/ספרת ביקורת לא פוסלים. ערכים שונים (אחרי הסרת אפסים מובילים) = סתירה."""
    groups: dict[str, list[tuple[str, NumberCandidate]]] = {}
    for c in candidates:
        if not is_id_candidate(c):
            continue
        digits = normalize_digits(c.value)
        if digits is None:
            continue
        groups.setdefault(digits.lstrip("0") or "0", []).append((digits, c))
    if not groups:
        return Decision()
    if len(groups) > 1:
        alts = _dedupe([items[0][0] for items in groups.values()])
        return Decision(flags=[F_CONFLICT], alternatives=alts)
    items = next(iter(groups.values()))
    digits = items[0][0]
    flags = _uncertainty_flags([(c.source, c.confidence) for _, c in items])
    if any(re.search(r"[^\W\d_]", c.value) for _, c in items):      # אותיות בערך שנקרא (דרכון): הספרות בלבד נשמרות
        flags.append(F_ID_NOT_ISRAELI)
    return Decision(value=digits, raw=digits, flags=flags)


# ---------- תאריכים ----------

_DMY = re.compile(r"^\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{2}|\d{4})\s*$")
_ISO = re.compile(r"^\s*(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\s*$")


def to_date(value: str) -> date:
    """מפרש dd.mm.yyyy (פלט של normalize_date)."""
    d, m, y = value.split(".")
    return date(int(y), int(m), int(d))


def normalize_date(raw: str | None, today: date | None = None) -> Decision:
    """ממיר ל-dd.mm.yyyy. לא מתקן: פורמט לא מזוהה או תאריך לא חוקי -> value=None + דגל."""
    if raw is None or not raw.strip():
        return Decision()
    today = today or date.today()
    hints: list[str] = []
    m = _DMY.match(raw)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
            hints.append(H_TWO_DIGIT_YEAR)
    else:
        m = _ISO.match(raw)
        if not m:
            return Decision(raw=raw, flags=[F_INVALID_FORMAT])
        y, mo, d = m.groups()
    try:
        parsed = date(int(y), int(mo), int(d))
    except ValueError:
        return Decision(raw=raw, flags=[F_INVALID_DATE])
    flags = []
    if abs(parsed.year - today.year) > YEAR_SPAN:
        flags.append(F_YEAR_OUT_OF_RANGE)
    return Decision(value=parsed.strftime("%d.%m.%Y"), raw=raw, flags=flags, hints=hints)


_STAMP_EVIDENCE = re.compile(r"stamp|חותמת|התקבל|^\W*קבלה\W*$", re.IGNORECASE)


def _classify_kind(kind: str, source: str, evidence: str | None) -> str:
    """סוג תאריך אפקטיבי: lab_stamp | handwritten_date | receipt_date | sample_date | ... (המודל לא תמיד מסווג נכון).
    - ראיית חותמת (stamp / חותמת / התקבל, או "קבלה" לבדה): lab_stamp. "תאריך קבלה" היא תווית של שדה מודפס
      של השולח ואינה סימן חותמת.
    - kind=lab_stamp (או lab_received מהסכמה הישנה) בלי ראיית חותמת: בכתב יד = handwritten_date, אחרת receipt_date.
    - kind=other בכתב יד = handwritten_date (תאריך שנוסף לטופס ביד)."""
    stamp_evidence = bool(_STAMP_EVIDENCE.search(evidence or ""))
    if kind in ("lab_stamp", "lab_received"):
        if stamp_evidence:
            return "lab_stamp"
        return "handwritten_date" if source == "handwritten" else "receipt_date"
    if kind == "other" and source == "handwritten":
        return "handwritten_date"
    return kind


def effective_date_kind(c: DateCandidate) -> str:
    return _classify_kind(c.kind, c.source, c.evidence)


def legacy_date_kind(kind: str, source: str, evidence: str | None) -> str:
    """ממיר סוג תאריך מהסכמה הישנה (lab_received) לסכמה החדשה, לטעינת תצלומים ישנים."""
    return _classify_kind(kind, source, evidence) if kind == "lab_received" else kind


def _decide_receipt_core(dates: list[DateCandidate], today: date | None = None) -> Decision:
    """תאריך קבלת דגימה מהמעבר הראשון בלבד (decide_receipt_date מוסיף קריאה שנייה וחלון). עדיפות:
    1. lab_stamp: חותמת "התקבל" של המעבדה. מנצחת גם תאריך בכתב יד שונה: הוא נשמר ב-alternatives (בהערה),
       בלי conflict; כתום רק לפי כללי הביטחון הרגילים (ביטחון נמוך, כתב יד).
    2. handwritten_date: תאריך שנוסף ביד (כתום, כתב יד). כך בטבלת האמת בעמודים 7 ו-12.
    3. receipt_date: תאריך קבלה שהודפס בטופס (של השולח): מוצג אבל כתום.
    4. sample_date: מוצג אבל כתום.
    5. other: רק כשאין אף סוג מ-1 עד 4. ערך אחד שונה: מוצג, כתום, date_kind_unclear; כמה ערכים: סתירה עם כולם ב-alternatives.
    הדפסה/לידה/תוקף מתעלמים תמיד. כמה ערכים שונים באותה רמה = סתירה."""
    today = today or date.today()

    def of_kind(kind: str):
        return [(normalize_date(c.value, today), c) for c in dates if effective_date_kind(c) == kind]

    stamp, hand = of_kind("lab_stamp"), of_kind("handwritten_date")
    printed, samples = of_kind("receipt_date"), of_kind("sample_date")
    if stamp:
        pool, extra = stamp, []
    elif hand:
        pool, extra = hand, []
    elif printed:
        pool, extra = printed, [F_NOT_LAB_RECEIVED]
    elif samples:
        pool, extra = samples, [F_NOT_RECEIPT_KIND]
    else:
        # אין אף סוג מזוהה: נופלים לתאריכים מסוג "other" בלבד (לא לידה, תוקף או הדפסה). כתום תמיד
        pool, extra = of_kind("other"), [F_DATE_KIND_UNCLEAR]
    if not pool:
        return Decision()
    valid = [(n, c) for n, c in pool if n.value]
    if not valid:
        first = pool[0][0]
        return Decision(raw=first.raw, flags=list(first.flags))

    groups: dict[str, list[tuple[Decision, DateCandidate]]] = {}
    for n, c in valid:
        groups.setdefault(n.value, []).append((n, c))
    if len(groups) > 1:
        return Decision(flags=[F_CONFLICT], alternatives=list(groups))

    value, items = next(iter(groups.items()))
    flags = list(extra)
    for n, _ in items:
        flags += n.flags
    flags += _uncertainty_flags([(c.source, c.confidence) for _, c in items])
    if stamp or hand or printed:
        sample_dates = [to_date(n.value) for n, _ in samples if n.value]
        if any(to_date(value) < s for s in sample_dates):
            flags.append(F_RECEIPT_BEFORE_SAMPLE)
    alternatives = []
    if stamp:                                 # תאריך בכתב יד שונה מהחותמת: בהערה בלבד
        alternatives = _dedupe([n.value for n, _ in hand if n.value and n.value != value])
    hints = _dedupe([h for n, _ in items for h in n.hints])
    return Decision(value=value, raw=items[0][0].raw, flags=_dedupe(flags), hints=hints, alternatives=alternatives)


WINDOW_DAYS = 14


def _distinct_dates(dates: list[DateCandidate], kind: str, today: date) -> list[date]:
    out: list[date] = []
    for c in dates:
        if effective_date_kind(c) == kind:
            n = normalize_date(c.value, today)
            if n.value and to_date(n.value) not in out:
                out.append(to_date(n.value))
    return out


def date_window(dates: list[DateCandidate], today: date | None = None) -> tuple[date, date] | None:
    """חלון תאריך הקבלה, לצבע והצעות בלבד (לא משנה ולא מוחק ערך). None = אין חלון (מדלגים).
    גבול תחתון: תאריך הדגימה (sample_date) בלבד; לא הדפסה, פקס או הוצאת הטופס (טופס יכול להישלח שוב אחרי שהדגימה התקבלה).
    גבול עליון: תאריך השליחה (shipping_date, אם יש) או הדגימה, ועוד WINDOW_DAYS ימים; לא בעתיד; ולא אחרי תוקף ההתחייבות
    (expiry_date; כמה תוקפים: המוקדם). אין תאריך דגימה אחד ברור (אין או כמה שונים): אין חלון."""
    today = today or date.today()
    samples = _distinct_dates(dates, "sample_date", today)
    if len(samples) != 1:
        return None
    ships = _distinct_dates(dates, "shipping_date", today)
    base = ships[0] if len(ships) == 1 else samples[0]
    high = min(base + timedelta(days=WINDOW_DAYS), today)
    expiries = _distinct_dates(dates, "expiry_date", today)
    if expiries:
        high = min(high, min(expiries))
    return samples[0], high


def _receipt_reading(regions: dict | None, today: date) -> tuple[str | None, str | None, list[str], str]:
    """הקריאה השנייה: חיתוך אזור הקבלה (regions["receipt"], רק אם region_ok). מחזיר (ערך מנורמל או None, הערך כפי שנקרא,
    חלופות מנורמלות, מקור). ערך שאי אפשר להמיר: ערך None (נשאר ב-raw)."""
    if region_state(regions, "receipt") != "ok":
        return None, None, [], "unknown"
    f = regions["receipt"].get("date") or {}
    raw = (f.get("value") or "").strip() or None
    value = normalize_date(raw, today).value if raw else None
    alts = _dedupe([v for a in f.get("alternatives") or [] if (v := normalize_date(a, today).value)])
    return value, raw, [a for a in alts if a != value], f.get("source", "unknown")


def decide_receipt_date(dates: list[DateCandidate], today: date | None = None, regions: dict | None = None,
                        require_two_readings: bool = False) -> Decision:
    """תאריך קבלה: ההחלטה מהמעבר הראשון (_decide_receipt_core), קריאה שנייה מחיתוך אזור הקבלה, וחלון תאריכים.
    - שתי קריאות מסכימות (רמז two_readings_agree): הדגל handwritten יורד; ירוק אם אין דגל אחר ובתוך החלון (או שאין חלון).
    - הקריאות שונות: סתירה, בלי ערך, שתיהן (וחלופות החיתוך) ב-alternatives, מה שבתוך החלון קודם.
    - המעבר הראשון בלי תאריך והחיתוך קרא: הערך מהחיתוך, כתום date_single_source (כמו ת"ז ממקור יחיד).
    - require_two_readings: ערך שנקרא פעם אחת בלבד (גם חותמת מודפסת) כתום date_single_source. (page_rows מפעיל; ברירת מחדל כבויה
      כדי שבדיקות של ההחלטה מהמעבר הראשון לא ישתנו.)
    - חלון (date_window): ערך מחוץ לו: כתום date_outside_window. החלון משפיע רק על צבע והצעות: ערך אף פעם לא משתנה בגללו;
      הצעה (חלופה) בתוך החלון מוצגת לפני האחרות."""
    today = today or date.today()
    d = _decide_receipt_core(dates, today)
    flags, hints, alts = list(d.flags), list(d.hints), list(d.alternatives)
    value, raw = d.value, d.raw
    read, read_raw, read_alts, read_source = _receipt_reading(regions, today)
    window = date_window(dates, today)

    def inside(v: str) -> bool:
        return window is None or window[0] <= to_date(v) <= window[1]

    def preferred(items: list[str]) -> list[str]:        # החלופות שבתוך החלון קודם (הסדר שאר: יציב)
        items = _dedupe([i for i in items if i and i != value])
        return sorted(items, key=lambda a: not inside(a))

    if read:
        if value and read == value:
            hints = _dedupe([*hints, H_TWO_READS])
            alts = [*alts, *read_alts]
        elif value:                                       # שתי קריאות שונות: לא בוחרים
            return Decision(flags=[F_CONFLICT], alternatives=preferred_pair([value, read, *read_alts, *alts], inside))
        elif not flags:                                   # אין תאריך במעבר הראשון: קריאה בודדת מהחיתוך
            value, raw = read, read_raw
            flags = [F_DATE_SINGLE_SOURCE, *_uncertainty_flags([(read_source, 1.0)])]
            alts = [*alts, *read_alts]
        else:                                             # המעבר הראשון עם סתירה/פורמט לא חוקי: לא מכריעים, רק מציעים
            alts = [*alts, read, *read_alts]
    elif read_alts:
        alts = [*alts, *read_alts]

    if value and H_TWO_READS in hints:
        flags = [f for f in flags if f != F_HANDWRITTEN]
    elif value and require_two_readings and F_DATE_SINGLE_SOURCE not in flags:
        flags.append(F_DATE_SINGLE_SOURCE)
    if value and window is not None and not inside(value):
        flags.append(F_DATE_OUTSIDE_WINDOW)
    return Decision(value=value, raw=raw, flags=_dedupe(flags), hints=hints, alternatives=preferred(alts))


def preferred_pair(items: list[str], inside) -> list[str]:
    """סתירה בין קריאות: כל הערכים, מה שבתוך החלון קודם."""
    return sorted(_dedupe([i for i in items if i]), key=lambda a: not inside(a))


# ---------- שמות ----------

_FATHER_LABEL = re.compile(r"שם\s*ה?אב|(?<![א-ת])ה?אב\s*:")


def is_father_evidence(evidence: str | None) -> bool:
    """הראיה או התווית (Field_.label / evidence) היא תווית של שם האב ("שם האב" / "האב:" / "אב:").
    בכוונה מצומצם: רק מה שיש לו דוגמה אמיתית (בלי בן/בת); "אביב" או "בן דוד" לא מתאימים."""
    return bool(evidence and _FATHER_LABEL.search(evidence))


_PATIENT_LABEL = re.compile(r"פרטי|משפחה|מטופל|חולה|נבדק|שם\s*מלא")


def is_unknown_name_label(label: str | None) -> bool:
    """יש תווית, והיא אינה תווית מטופל מוכרת (שם פרטי / שם משפחה / שם המטופל / החולה / הנבדק).
    בלי תווית בכלל: לא נחשב לא מוכר (המודל לא תמיד מחזיר תווית)."""
    return bool(label and label.strip() and not _PATIENT_LABEL.search(label))


# ---------- שדה "שם מלא" ----------

_FULL_NAME_LABEL = re.compile(r"שם\s*מלא")


def is_full_name_label(label: str | None) -> bool:
    """התווית היא "שם מלא" (שדה אחד לשם פרטי ושם משפחה יחד)."""
    return bool(label and _FULL_NAME_LABEL.search(label))


def _split_words(text: str) -> tuple[str, str]:
    """המילה הראשונה בקריאה מימין לשמאל (הסדר הלוגי של הטקסט העברי) = שם פרטי; כל השאר = שם משפחה."""
    words = text.split()
    return (words[0], " ".join(words[1:])) if words else ("", "")


def split_full_name_fields(first: Field_, last: Field_) -> tuple[Field_, Field_, bool]:
    """טופס עם שדה אחד "שם מלא": המודל מחזיר את כל הכיתוב בשדה אחד (או בשניהם). הקוד מפצל: המילה הראשונה
    (מימין לשמאל) = שם פרטי, השאר = שם משפחה. הביטחון, המקור (כתב יד) והראיה נשמרים, כך שכתב יד נשאר כתום ולא מאושר.
    חלופות מפוצלות באותו אופן. מחזיר (פרטי, משפחה, האם פוצל).
    לא מפצלים כש: אין שדה עם תווית "שם מלא" ושתי מילים לפחות; או שהשדות מכילים ערכים שונים של "שם מלא" (סתירה
    נשארת כמו שהיא, ו-decide_name מטפל בה)."""
    full = [f for f in (first, last) if is_full_name_label(f.label) and f.value and len(f.value.split()) >= 2]
    if not full or len({" ".join(f.value.split()) for f in full}) > 1:
        return first, last, False
    src = full[0]
    fn, ln = _split_words(src.value)
    alt_first, alt_last = [], []
    for alt in src.alternatives:
        a, b = _split_words(alt)
        if a:
            alt_first.append(a)
        if b:
            alt_last.append(b)
    new_first = src.model_copy(update={"value": fn, "alternatives": _dedupe(alt_first)})
    new_last = src.model_copy(update={"value": ln or None, "alternatives": _dedupe(alt_last)})
    return new_first, new_last, True


def split_full_name_regions(regions: dict | None) -> tuple[dict | None, bool]:
    """אותו פיצול על קריאת המעבר השני (חיתוך המטופל). מחזיר (regions חדש, האם פוצל); המקור לא משתנה."""
    if not regions or not regions.get("ok") or "patient" not in regions:
        return regions, False
    patient = regions["patient"]
    first, last, did = split_full_name_fields(Field_.model_validate(patient["first_name"]),
                                              Field_.model_validate(patient["last_name"]))
    if not did:
        return regions, False
    return {**regions, "patient": {**patient, "first_name": first.model_dump(), "last_name": last.model_dump()}}, True


def full_name_label_seen(regions: dict | None) -> bool:
    """בחיתוך המטופל נראתה תווית "שם מלא" (בתווית של אחת הקריאות): היא מחליפה את תוויות שם פרטי ושם משפחה."""
    if not regions or not regions.get("ok") or "patient" not in regions:
        return False
    return any(is_full_name_label((regions["patient"].get(k) or {}).get("label")) for k in ("first_name", "last_name"))


def decide_name(f: Field_, regions: dict | None = None, which: str = "first_name") -> Decision:
    """שם פרטי/משפחה (which = first_name | last_name).
    - קריאה שהראיה שלה היא שם האב נדחית: דגל father_name, והקריאה ב-alternatives (לא נספרת כקריאה מסכימה).
    - שם שכל קריאותיו בכתב יד ואין שתי קריאות מסכימות (מעבר ראשון + שני תקין): value ריק, דגל
      handwritten_unconfirmed, והקריאה ב-alternatives בלבד (בלי raw: התא נשאר ריק וכתום).
    - שתי קריאות מסכימות: ערך, כתום אם כולן בכתב יד. שמות שונים: סתירה.
    - קריאה שיש לה תווית שאינה תווית מטופל מוכרת: ריק, דגל name_label_unknown, והקריאה ב-alternatives.
    - שם מודפס חייב תווית מטופל מוכרת; בלי תווית (כותרת מודפסת שנקראה כשם) הוא עובר ל-alternatives בלבד, דגל
      name_label_missing. חיתוך שנפסל (region_ok=false): לא נכנס, והשדה כתום."""
    state = region_state(regions, "patient", which)
    fields = [f]
    if state == "ok":
        fields.append(Field_.model_validate(regions["patient"][which]))
    groups: dict[str, list[Field_]] = {}
    rejected: list[str] = []                 # קריאות של שם האב
    unknown_label: list[str] = []            # קריאות שהתווית שלהן אינה תווית מטופל מוכרת
    unlabeled_printed: list[str] = []        # קריאות מודפסות בלי שום תווית (לא מועמד: alternatives בלבד)
    for fld in fields:
        value = (fld.value or "").strip()
        if not value:
            continue
        if is_father_evidence(fld.label) or is_father_evidence(fld.evidence):
            rejected.append(value)
        elif is_unknown_name_label(fld.label):
            unknown_label.append(value)
        elif fld.source != "handwritten" and not (fld.label and fld.label.strip()):
            unlabeled_printed.append(value)          # שם מודפס בלי תווית מטופל מוכרת (למשל כותרת): הצעה בלבד
        else:
            groups.setdefault(value, []).append(fld)

    flags: list[str] = [F_FATHER_NAME] if rejected else []
    if unknown_label:
        flags.append(F_NAME_LABEL_UNKNOWN)
        rejected = [*rejected, *unknown_label]
    if unlabeled_printed:
        flags.append(F_NAME_LABEL_MISSING)
        rejected = [*rejected, *unlabeled_printed]
    if not groups:
        d = Decision(flags=flags, alternatives=_dedupe(rejected))
    elif len(groups) > 1:
        all_items = [x for items in groups.values() for x in items]
        if all(x.source == "handwritten" for x in all_items):
            flags.append(F_HANDWRITTEN_UNCONFIRMED)
        d = Decision(flags=[F_CONFLICT, *flags], alternatives=_dedupe([*groups, *rejected]))
    else:
        value, items = next(iter(groups.items()))
        if all(x.source == "handwritten" for x in items) and len(items) < 2:
            d = Decision(flags=[F_HANDWRITTEN_UNCONFIRMED, *flags], alternatives=_dedupe([value, *rejected]))
        else:
            d = Decision(value=value, raw=value, alternatives=_dedupe(rejected),
                         flags=[*_uncertainty_flags([(x.source, x.confidence) for x in items]), *flags],
                         hints=[H_TWO_READS] if len(items) >= 2 else [])
    return _with_region_flag(d, state)


# ---------- ערכים מרובים, מספרי התחייבות ----------

def split_multi(text: str | None) -> list[str]:
    """מפרק "a ; b ; c" (גם ; או , או שורה חדשה) לרשימה."""
    if not text:
        return []
    return [p.strip() for p in re.split(r"[;,\n]", text) if p.strip()]


def join_multi(values: list[str]) -> str:
    """מחבר ב-" ; " בלי כפילויות, לפי סדר הופעה."""
    return " ; ".join(_dedupe([v for v in values if v]))


def _longest_digit_run(s: str) -> int:
    return max((len(m) for m in re.findall(r"\d+", s)), default=0)


def commitment_numbers(numbers: list[NumberCandidate]) -> list[Decision]:
    """מספרי התחייבות לפי משמעות התווית (התחייבות/דרישה/דגימה/אסמכתא), אחד לכל ערך שונה.
    מועמד חייב להיות ספרות בלבד. אם אין אף אחד כזה, מוצג המועמד הטוב ביותר בכתום
    (הערך כפי שנקרא, בלי תיקון), ובלבד שיש בו רצף של לפחות MIN_FALLBACK_DIGITS ספרות
    (שעה כמו 10:44 אינה מספר התחייבות)."""
    labeled = [n for n in numbers
               if n.label and any(w in n.label for w in COMMITMENT_LABEL_WORDS) and n.value.strip()]
    groups: dict[str, list[NumberCandidate]] = {}
    for n in labeled:
        value = re.sub(r"\s+", "", n.value)
        if value.isdigit():
            groups.setdefault(value, []).append(n)
    if groups:
        return [Decision(value=v, raw=v, flags=_uncertainty_flags([(c.source, c.confidence) for c in items]))
                for v, items in groups.items()]

    fallback = [(n, _longest_digit_run(n.value)) for n in labeled]
    fallback = [(n, run) for n, run in fallback if run >= MIN_FALLBACK_DIGITS]
    if not fallback:
        return _weak_commitment(numbers)
    best, _ = max(fallback, key=lambda x: (x[1], x[0].confidence))
    value = best.value.strip()
    flags = [F_NON_DIGIT] + [f for f in _uncertainty_flags([(best.source, best.confidence)])]
    return [Decision(value=value, raw=value, flags=flags)]


def verify_commitments(commitments: list[Decision], regions: dict | None) -> list[Decision]:
    """אימות מספר ההתחייבות מול הקריאה השנייה (חיתוך מוגדל, regions["commitment"]).
    - שתי הקריאות מסכימות על הספרות: ללא שינוי (ירוק רק אם אין דגל אחר, למשל weak_label).
    - הקריאות שונות: כתום, ערך ריק, שני הערכים ב-alternatives, דגל commitment_mismatch (לא בוחרים).
    - המעבר השני לא קרא (לא רץ, אין חיתוך, region_ok=false, אין ספרות): כתום, commitment_single_source.
    - כמה התחייבויות בעמוד וקריאה שנייה אחת: רק זו שמסכימה עם הקריאה מאומתת, האחרות single_source."""
    p2 = None
    if regions and regions.get("ok"):
        c = regions.get("commitment") or {}
        if c.get("region_ok"):
            p2 = normalize_digits((c.get("number") or {}).get("value"))
    others = {normalize_digits(d.value) for d in commitments if d.value}
    out: list[Decision] = []
    for d in commitments:
        if not d.value:
            out.append(d)
            continue
        digits = normalize_digits(d.value)
        if p2 is not None and digits == p2:
            out.append(d)
        elif p2 is None or (len(commitments) > 1 and p2 in others):
            out.append(d.model_copy(update={"flags": _dedupe([*d.flags, F_COMMITMENT_SINGLE_SOURCE])}))
        else:
            out.append(Decision(flags=_dedupe([*d.flags, F_COMMITMENT_MISMATCH]), alternatives=_dedupe([d.value, p2])))
    return out


_WEAK_LABEL = re.compile(r"^\s*מספר\s*[:：]?\s*$")


def _weak_commitment(numbers: list[NumberCandidate]) -> list[Decision]:
    """מועמד חלש: ספרות בלבד (לפחות MIN_FALLBACK_DIGITS) עם התווית "מספר" / "מספר:" בלבד. תמיד כתום (weak_label),
    לעולם לא ירוק. רק ערך אחד שונה: כמה ערכים חלשים שונים הם עמומים ולא נבחרים (כדי לא ליצור שורות מנוחשות)."""
    groups: dict[str, list[NumberCandidate]] = {}
    for n in numbers:
        value = re.sub(r"\s+", "", n.value or "")
        if n.label and _WEAK_LABEL.match(n.label) and value.isdigit() and len(value) >= MIN_FALLBACK_DIGITS:
            groups.setdefault(value, []).append(n)
    if len(groups) != 1:
        return []
    value, items = next(iter(groups.items()))
    flags = [F_WEAK_LABEL, *_uncertainty_flags([(c.source, c.confidence) for c in items])]
    return [Decision(value=value, raw=value, flags=_dedupe(flags))]


_CENTER_LABEL = re.compile(r"(?<![א-ת])מרכזי?(?![א-ת])")


def is_center_label(label: str | None) -> bool:
    """התווית "מרכזי" או "מרכז" (המילה המסובבת ליד הברקוד נקראת לפעמים בלי היו"ד), כמילה שלמה:
    "מרכזית" / "המעבדה המרכזית" אינן תווית מרכזי."""
    return bool(label and _CENTER_LABEL.search(label))


def decide_center(numbers: list[NumberCandidate], regions: dict | None = None, barcodes: list[dict] | None = None) -> Decision:
    """מספר מרכזי. אין בו כלל "הברקוד הוא המרכזי" כללי; ההחלטה:
    1. מועמד עם התווית "מרכזי" (ברשימת המספרים של העמוד, או באזור הברקוד, או central_number של המעבר השני):
       ערך (אחד או כמה, מחוברים ב-" ; "), כתום רק לפי כללי הביטחון הרגילים.
    2. אם אין תווית: מספר יחיד בן 6 ספרות ללא תווית (באזור הברקוד אם יש מעבר שני, אחרת ברשימת העמוד): כתום.
       כמה מספרים כאלה: ריק, מסומן, והמועמדים ב-alternatives.
    3. אחרת: ריק."""
    state = region_state(regions, "barcode")
    usable = state == "ok" or region_state(regions, "receipt") == "ok"       # חיתוך הקבלה הוא קריאה שנייה בלתי תלויה של המרכזי
    d = _with_region_flag(_decide_center_core(numbers, regions if usable else None), state)
    commitments = {c.value for c in commitment_numbers(numbers) if c.value}      # ברקוד שהוא מספר ההתחייבות של העמוד אינו מרכזי
    return apply_center_barcode(d, barcodes, exclude=commitments)


def apply_center_barcode(d: Decision, barcodes: list[dict] | None, exclude: set[str] | None = None) -> Decision:
    """קורא שני בלתי תלוי למרכזי: ברקודי Code128 באורך מרכזי שפוענחו מקומית (src/barcode.py). רק המרכזי.
    (א) ערכי המודל שווים בדיוק לקבוצת הברקודים (לא רק מוכלים בה): ירוק, בלי דגלים (רמז center_barcode_agrees).
    (ב) המודל לא החליט על ערך אבל יש ברקודים: הערכים מהברקוד, מחוברים ב-" ; ", כתום (center_from_barcode_only).
    (ג) שונים: ההחלטה הנוכחית ללא שינוי (רק רמז לביקורת). (ד) אין ברקוד: ללא שינוי.
    exclude = ערכים שאינם מרכזי (מספרי ההתחייבות שהמודל מצא בעמוד): לא נספרים מהברקודים."""
    from .barcode import center_barcode_values

    model = [v for v in (normalize_digits(x) for x in split_multi(d.value)) if v]
    if not model:
        fill = [v for v in center_barcode_values(barcodes, "barcode_fill") if v not in (exclude or ())]   # כלל ב: טווח שמרני משלו
        if not fill:
            return d
        return d.model_copy(update={"value": join_multi(fill), "raw": join_multi(fill),
                                    "flags": _dedupe([*d.flags, F_CENTER_FROM_BARCODE_ONLY])})
    values = [v for v in center_barcode_values(barcodes) if v not in (exclude or ())]   # לבדיקת השוויון (כלל א) ולרמז (כלל ג)
    if not values:
        return d
    if set(model) == set(values):
        return d.model_copy(update={"flags": [], "alternatives": [], "hints": _dedupe([*d.hints, H_CENTER_BARCODE_AGREES])})
    return d.model_copy(update={"hints": _dedupe([*d.hints, f"center_barcode_differs:{join_multi(values)}"])})


def _barcode_numbers(regions: dict | None) -> tuple[list[NumberCandidate], list[tuple[str, Field_]]]:
    """מספרי אזור הברקוד של המעבר השני, ו-central_number שלו (ספרות בלבד, עם השדה המקורי)."""
    from .schema import RegionsExtraction  # ייבוא מקומי: rules לא תלוי במעבר שני כשאין צורך

    if not (regions and regions.get("ok")):
        return [], []
    model = RegionsExtraction.model_validate(regions)
    numbers: list[NumberCandidate] = []
    central: list[tuple[str, Field_]] = []
    if region_state(regions, "barcode") == "ok":
        bc = model.barcode
        numbers = [NumberCandidate(value=n.value, label=n.label, confidence=n.confidence) for n in bc.numbers]
        digits = normalize_digits(bc.central_number.value)
        if digits:
            central.append((digits, bc.central_number))
    if region_state(regions, "receipt") == "ok":              # המרכזי שבחיתוך הקבלה (כתב יד ליד התאריך): קריאה שנייה
        rc = model.receipt.central_number
        digits = normalize_digits(rc.value)
        if digits:
            central.append((digits, rc))
    return numbers, central


def _center_groups(numbers: list[NumberCandidate], central: list[tuple[str, Field_]]) -> dict[str, list[tuple[str, float]]]:
    """מועמדים עם תווית מרכזי: ערך -> [(מקור, ביטחון)]."""
    groups: dict[str, list[tuple[str, float]]] = {}
    for n in numbers:
        digits = normalize_digits(n.value)
        if digits and is_center_label(n.label):
            groups.setdefault(digits, []).append((n.source, n.confidence))
    for digits, f in central:
        groups.setdefault(digits, []).append((f.source, f.confidence))
    return groups


def _center_unlabeled(pool: list[NumberCandidate]) -> tuple[list[str], list[str]]:
    """מספרים באורך מרכזי (center_config, ברירת מחדל 5 עד 9 ספרות) בלי תווית מרכזי: (בלי תווית בכלל, עם תווית זרה שאינה התחייבות/ת"ז)."""
    candidates = _dedupe([d for n in pool if not n.label and (d := normalize_digits(n.value)) and in_center_range(d)])
    # מספר בן 6 ספרות עם תווית זרה (לא מרכזי, לא התחייבות, לא ת"ז; למשל תווית מרכזי שנקראה לא נכון) הוא עדיין
    # מתחרה: הערך נשאר (כתום) והמתחרים ב-alternatives, בהערת התא
    foreign = _dedupe([d for n in pool if n.label and not any(w in n.label for w in COMMITMENT_LABEL_WORDS)
                       and not is_id_label(n.label) and (d := normalize_digits(n.value))
                       and in_center_range(d) and d not in candidates and not is_center_label(n.label)])
    return candidates, foreign


def _pass_candidates(numbers: list[NumberCandidate], central: list[tuple[str, Field_]]) -> list[str]:
    """כל המועמדים של מעבר אחד: עם תווית מרכזי אם יש, אחרת בני 6 ספרות בלי תווית (או עם תווית זרה)."""
    groups = _center_groups(numbers, central)
    if groups:
        return list(groups)
    candidates, foreign = _center_unlabeled(numbers)
    return [*candidates, *foreign]


FRAGMENT_DIGITS = (5, 6)

# מילים בתווית שמראות שהמספר אינו מרכזי (מבטח/ביטוח, שעה/תאריך, טלפון, רופא/גורם שולח, מספר בקשה/רישיון/נוהל, גיל...).
# תווית כזו פוסלת מועמד למרכזי; תווית זרה אחרת (למשל "מספר ארכיון", "מספר", "ברקוד", תווית מרכזי שנקראה לא נכון) לא
# פוסלת, כי גם מרכזי אמיתי מופיע תחתיה. **הרשימה נבנתה מתוויות של חלק 1 בלבד (ריצות v4b ו-Claude) וחייבת בדיקה
# מחדש על חלק 2** לפני שסומכים עליה: תווית חדשה שלא ברשימה תיכנס למאגר כמו קודם.
NON_CENTER_LABEL_WORDS = ("מבטח", "מבוטח", "ביטוח", "קופ", "שעה", "זמן", "תאריך", "קבלה", "טלפון", "נייד", "פקס",
                          "רופא", "גורם", "שולח", "ספרן", "מטפל", "בקשה", "רישיון", "נוהל", "מקרה", "גיל")
_NON_CENTER_LABEL = re.compile("|".join(NON_CENTER_LABEL_WORDS))
# ערך שנראה כשעה (HH:MM או HH:MM:SS) או כתאריך עם מפרידים (dd.mm.yy / dd-mm-yyyy): הנרמול מוחק את המפרידים, ו-07:49:34
# הופך ל-074934 (6 ספרות). המסנן בודק את הערך כפי שנקרא, לפני הנרמול. תמיד יחד עם NON_CENTER_LABEL_WORDS, לא לבד.
_TIME_OR_DATE_RAW = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s*$|\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}")


def is_non_center_number(n: NumberCandidate) -> bool:
    """מספר שאסור שייכנס למאגר המרכזי: תווית שאינה תווית מרכזי ושמעידה על קטגוריה אחרת (NON_CENTER_LABEL_WORDS), או ערך
    בצורת שעה/תאריך (_TIME_OR_DATE_RAW). שני המסננים פועלים יחד: (ב) לבד משאיר מועמדים חלקיים וגורע (נבדק על חלק 1)."""
    if n.label and not is_center_label(n.label) and _NON_CENTER_LABEL.search(n.label):
        return True
    return bool(_TIME_OR_DATE_RAW.search(n.value or ""))


def _commitment_fragments(numbers: list[NumberCandidate]) -> set[str]:
    """ערכים בני 5-6 ספרות שהם סיומת של מספר התחייבות שנמצא באותו עמוד (למשל 000351 מתוך 944000351):
    זה שבר של ההתחייבות, לא מרכזי."""
    commits = [d.value for d in commitment_numbers(numbers) if d.value and d.value.isdigit()]
    return {c[-k:] for c in commits for k in FRAGMENT_DIGITS if len(c) > k}


def _decide_center_core(numbers: list[NumberCandidate], regions: dict | None) -> Decision:
    """מסנן שברי התחייבות (_commitment_fragments) ממאגר המועמדים של שני המעברים, ומתעד אותם ב-hints
    (center_fragment_dropped:<ערך>, מוצג בגיליון audit); ההחלטה עצמה ב-_decide_center_pool."""
    fragments = _commitment_fragments(numbers)
    barcode_numbers, central_values = _barcode_numbers(regions)
    dropped: list[str] = []

    def keep(digits: str | None) -> bool:
        if digits in fragments:
            dropped.append(digits)
            return False
        return True

    def keep_num(n: NumberCandidate) -> bool:
        return not is_non_center_number(n) and keep(normalize_digits(n.value))

    numbers = [n for n in numbers if keep_num(n)]
    barcode_numbers = [n for n in barcode_numbers if keep_num(n)]
    central_values = [(d, f) for d, f in central_values if keep(d)]
    d = _decide_center_pool(numbers, barcode_numbers, central_values, bool(regions and regions.get("ok")))
    if dropped:
        d = d.model_copy(update={"hints": _dedupe([*d.hints, *[f"center_fragment_dropped:{x}" for x in dropped]])})
    return d


def _decide_center_pool(numbers: list[NumberCandidate], barcode_numbers: list[NumberCandidate],
                        central_values: list[tuple[str, Field_]], second_pass_ok: bool) -> Decision:
    """עיקרון: מועמד שמעבר אחד מצא ולא אושר במעבר השני, או שני מעברים עם מועמדים שונים = כתום, והמועמדים
    ב-alternatives (value = האיחוד אם אחד המעברים מוכל בשני, אחרת ריק). ערך ריק או חלקי בלי דגל רק כשאין אף
    מועמד בשום מעבר. מאגר המועמדים הוא האיחוד של מספרי העמוד ומספרי אזור הברקוד (לא אחד במקום השני).
    חריג מוסכם: עמוד בלי אף מועמד והמעבר השני מצא (המילה המסובבת שהעמוד השלם לא קרא): ללא סתירה, כללי הביטחון הרגילים."""
    if second_pass_ok:
        c1 = _pass_candidates(numbers, [])
        c2 = _pass_candidates(barcode_numbers, central_values)
        if c1 and set(c1) != set(c2):     # עמוד בלי מועמדים והמעבר השני מצא: הוא הקורא החוזר, ללא סתירה
            union = _dedupe([*c1, *c2])
            subset = set(c1) <= set(c2) or set(c2) <= set(c1)
            flags = [F_CENTER_MISMATCH]
            groups = _center_groups([*numbers, *barcode_numbers], central_values)
            for items in groups.values():
                flags += _uncertainty_flags(items)
            value = join_multi(union) if subset else None     # מועמדים סותרים: לא בוחרים
            return Decision(value=value, raw=value, flags=_dedupe(flags), alternatives=union)

    groups = _center_groups([*numbers, *barcode_numbers], central_values)
    if groups:
        flags: list[str] = []
        for items in groups.values():
            flags += _uncertainty_flags(items)
        return Decision(value=join_multi(list(groups)), raw=join_multi(list(groups)), flags=_dedupe(flags))

    candidates, foreign = _center_unlabeled([*numbers, *barcode_numbers])
    if len(candidates) == 1 and foreign:
        return Decision(value=candidates[0], raw=candidates[0], flags=[F_NO_CENTER_LABEL], alternatives=foreign)
    if len(candidates) == 1:
        return Decision(value=candidates[0], raw=candidates[0], flags=[F_NO_CENTER_LABEL])
    if candidates:
        return Decision(flags=[F_NO_CENTER_LABEL], alternatives=candidates)
    if len(foreign) == 1:   # מועמד יחיד בתווית זרה שאינה קטגוריה אחרת (למשל "מספר ארכיון"): ערך כתום, כמו מועמד יחיד בלי תווית
        return Decision(value=foreign[0], raw=foreign[0], flags=[F_NO_CENTER_LABEL])
    if foreign:             # כמה כאלה: התא ריק וכתום, והם הצעות בלבד
        return Decision(flags=[F_NO_CENTER_LABEL], alternatives=foreign)
    return Decision()


def expand_rows(base: dict, commitments: list[Decision]) -> list[dict]:
    """שורה לכל התחייבות, עם אותם פרטי מטופל ומרכזי. בלי התחייבות: שורה אחת עם הדגל no_commitment."""
    if not commitments:
        return [{**base, "commitment": None, "commitment_flags": [F_NO_COMMITMENT], "commitment_alternatives": []}]
    return [{**base, "commitment": c.value, "commitment_flags": list(c.flags), "commitment_alternatives": list(c.alternatives)}
            for c in commitments]
