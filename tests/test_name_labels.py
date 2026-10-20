"""תוויות שם בחיתוך המטופל (20.10.2026, מהממצאים על data/eval_extra):
1. תווית "שם" לבדה = שדה שם יחיד, בדיוק כמו "שם מלא" (החלפת תוויות פרטי/משפחה + פיצול הערך).
2. חיתוך תקין שלא נראתה בו אף תווית (labels_seen ריק) אינו פוסל שם: הקריאה נכנסת, צהובה או כתומה, לעולם לא ירוקה.
3. region_ok=false ממשיך לפסול (region_not_ok).
המקרים מדמים את עמודים 1, 3, 4, 5 של סט ההערכה הנוסף."""
from src.export import Cell, display_name_cell
from src.rules import (
    F_CONFLICT, F_HANDWRITTEN, F_HANDWRITTEN_UNCONFIRMED, F_REGION_NOT_OK, H_TWO_READS, apply_field_validity,
    decide_name, is_full_name_label, patient_labels_missing, region_state, split_full_name_fields,
)
from src.schema import Field_


def hand(value, label=None, conf=0.9):
    return Field_(value=value, confidence=conf, source="handwritten", label=label)


def regions(first=None, last=None, labels_seen=(), label=None, region_ok=True, source="handwritten"):
    """מעבר שני עם חיתוך מטופל, אחרי apply_field_validity (כמו בצינור האמיתי)."""
    def f(v):
        return {"value": v, "confidence": 0.9, "source": source, "label": label, "alternatives": []}
    out = {"ok": True, "model": "m",
           "patient": {"region_ok": region_ok, "labels_seen": list(labels_seen),
                       "first_name": f(first), "last_name": f(last), "id_number": f(None), "birth_date": f(None)},
           "barcode": {"region_ok": True}}
    return apply_field_validity(out)


def as_cell(d) -> Cell:
    return Cell(d.value, d.raw, list(d.flags), list(d.hints), list(d.alternatives))


# ---------- 1. תווית "שם" לבדה (כמו עמוד 1) ----------

def test_bare_name_label_counts_as_full_name_label():
    assert is_full_name_label("שם") and is_full_name_label("שם:") and is_full_name_label(" שם ")
    assert not is_full_name_label("שם פרטי") and not is_full_name_label("שם משפחה")
    assert not is_full_name_label("שם האב") and not is_full_name_label("שמות")


def test_bare_name_label_splits_a_full_name_value():
    first, last, did = split_full_name_fields(hand("טובה גרין", label="שם"), Field_())
    assert did and (first.value, last.value) == ("טובה", "גרין")
    assert first.source == "handwritten"                      # כתב יד נשאר כתב יד: לא יהפוך לירוק


def test_bare_name_label_replaces_first_last_labels():
    """עמוד 1: labels_seen מכיל רק ת"ז ושם האב, אבל התווית בשדה היא "שם" -> השמות תקפים."""
    r = regions(first="טובה", last="גרין", labels_seen=("id_number", "father_name"), label="שם")
    assert r["patient"]["field_ok"] == {"first_name": True, "last_name": True, "id_number": True}
    assert not patient_labels_missing(r)                       # אין קריאה חוזרת מיותרת על החיתוך
    d = decide_name(hand("טובה", label="שם"), r, "first_name")
    assert F_REGION_NOT_OK not in d.flags
    assert d.value == "טובה" and d.flags == [F_HANDWRITTEN] and H_TWO_READS in d.hints


# ---------- 2. אין אף תווית בחיתוך (כמו עמודים 4, 5, 6) ----------

def test_no_labels_at_all_keeps_the_name_fields_valid():
    r = regions(first="טובה", last="גרין", labels_seen=())
    assert r["patient"]["field_ok"]["first_name"] and r["patient"]["field_ok"]["last_name"]
    assert r["patient"]["field_ok"]["id_number"] is False      # ת"ז לא נכללה בחריג
    assert region_state(r, "patient", "first_name") == "ok"


def test_page5_like_two_agreeing_readings_without_labels_are_yellow_with_value():
    """עמוד 5: צילום מסך בלי תוויות, שני המעברים קראו "טובה" -> ערך, צהוב, לעולם לא ירוק."""
    d = decide_name(hand("טובה"), regions(first="טובה", last="גרין", labels_seen=()), "first_name")
    assert d.value == "טובה"
    assert d.flags == [F_HANDWRITTEN] and H_TWO_READS in d.hints
    assert d.uncertain                                          # כתום/צהוב, לא ירוק
    cell = display_name_cell(as_cell(d))
    assert cell.value == "טובה" and cell.yellow and not cell.orange


def test_page4_like_disagreeing_readings_without_labels_are_orange_not_green():
    """עמוד 4: מעבר 1 קרא "אביטל", מעבר 2 קרא "מאור" -> סתירה, כתום, בלי ערך ירוק."""
    d = decide_name(hand("אביטל"), regions(first="מאור", labels_seen=()), "first_name")
    assert F_CONFLICT in d.flags and F_HANDWRITTEN_UNCONFIRMED in d.flags
    assert d.value is None and d.uncertain
    assert set(d.alternatives) == {"אביטל", "מאור"}             # שתי הקריאות נשמרות
    cell = display_name_cell(as_cell(d))
    assert not cell.yellow and cell.orange and not cell.value


def test_single_reading_without_labels_stays_empty_and_flagged():
    """מעבר 2 לא קרא שם: קריאה אחת בכתב יד נשארת ריקה וכתומה (CLAUDE.md סעיפים 16-17)."""
    d = decide_name(hand("טובה"), regions(first=None, labels_seen=()), "first_name")
    assert d.value is None and F_HANDWRITTEN_UNCONFIRMED in d.flags
    assert d.alternatives == ["טובה"] and d.uncertain


# ---------- 3. region_ok=false ממשיך לפסול ----------

def test_region_not_ok_still_discards_the_reading():
    r = regions(first="טובה", labels_seen=(), region_ok=False)
    assert region_state(r, "patient", "first_name") == "not_ok"
    d = decide_name(hand("טובה"), r, "first_name")
    assert F_REGION_NOT_OK in d.flags and d.value is None


# ---------- 4. סתירה עם תוויות ממשיכה להיות מסומנת (כמו עמוד 3) ----------

def test_page3_like_conflict_with_labels_stays_flagged():
    r = regions(last="פינקוביץ", labels_seen=("first_name", "last_name", "id_number"), label="משפחה")
    d = decide_name(hand("דרזון", label="משפחה"), r, "last_name")
    assert F_CONFLICT in d.flags and d.value is None and d.uncertain
    assert set(d.alternatives) == {"דרזון", "פינקוביץ"}
    assert not display_name_cell(as_cell(d)).value


def test_printed_name_with_a_known_label_is_still_green():
    """לא נשבר: שם מודפס עם תווית מוכרת נשאר ירוק (בלי דגלים)."""
    printed = Field_(value="ישראל", confidence=0.95, source="printed", label="שם פרטי")
    d = decide_name(printed, regions(first="ישראל", labels_seen=("first_name", "last_name"), source="printed",
                                     label="שם פרטי"), "first_name")
    assert d.value == "ישראל" and d.flags == [] and not d.uncertain
    assert display_name_cell(as_cell(d)).value == "ישראל"
