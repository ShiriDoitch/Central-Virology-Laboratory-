"""שם כהצעה כתומה (20.10.2026): כשיש מעבר שני תקין (region_ok=true) ואין שתי קריאות מסכימות, הקריאה מוצגת
בתא ככתום במקום להשאיר אותו ריק. לעולם לא ירוק; צהוב נשאר רק לשתי קריאות מסכימות.
המקרים מדמים את עמודים 3, 4 ו-5 של data/eval_extra. בלי קריאות API."""
import pytest

from src.export import Cell, display_name_cell
from src.rules import (
    F_CONFLICT, F_FATHER_NAME, F_HANDWRITTEN, F_HANDWRITTEN_UNCONFIRMED, F_NAME_LABEL_UNKNOWN, F_REGION_NOT_OK,
    H_TWO_READS, decide_name,
)
from src.schema import Field_


def hand(value, label=None, evidence=None, conf=0.9):
    return Field_(value=value, confidence=conf, source="handwritten", label=label, evidence=evidence)


def regions(first=None, last=None, labels_seen=(), region_ok=True, label=None, evidence=None, source="handwritten"):
    def f(v):
        return {"value": v, "confidence": 0.9, "source": source, "label": label, "evidence": evidence,
                "alternatives": []}
    patient = {"region_ok": region_ok, "labels_seen": list(labels_seen), "first_name": f(first), "last_name": f(last),
               "id_number": f(None), "birth_date": f(None),
               "field_ok": {"first_name": True, "last_name": True, "id_number": True}}
    return {"ok": True, "model": "m", "patient": patient, "barcode": {"region_ok": True}}


def cell(d) -> Cell:
    return display_name_cell(Cell(d.value, d.raw, list(d.flags), list(d.hints), list(d.alternatives)))


def test_page4_like_shows_the_pass2_reading_in_orange():
    """עמוד 4: מעבר 1 קרא "אביטל", מעבר 2 קרא "מאור" (הנכון) -> מוצג "מאור", כתום."""
    d = decide_name(hand("אביטל"), regions(first="מאור"), "first_name")
    assert d.value == "מאור" and d.raw == "מאור"
    assert F_CONFLICT in d.flags and F_HANDWRITTEN_UNCONFIRMED in d.flags
    assert d.alternatives == ["אביטל"]                     # הקריאה האחרת נשמרת
    assert d.uncertain
    c = cell(d)
    assert c.value == "מאור" and c.orange and not c.yellow      # כתום, לעולם לא ירוק


def test_page4_like_last_name_too():
    d = decide_name(hand("מור"), regions(last="אזולאי"), "last_name")
    assert d.value == "אזולאי" and d.alternatives == ["מור"]
    assert cell(d).value == "אזולאי" and cell(d).orange


def test_page3_like_differing_readings_show_the_pass2_value():
    """עמוד 3: "דרזון" מול "פינקוביץ" -> מוצגת קריאת המעבר השני, כתום, עם האחרת כהצעה."""
    d = decide_name(hand("דרזון", label="משפחה"), regions(last="פינקוביץ", label="משפחה"), "last_name")
    assert d.value == "פינקוביץ" and d.alternatives == ["דרזון"]
    assert F_CONFLICT in d.flags and cell(d).orange


def test_single_reading_with_a_valid_region_is_shown_in_orange():
    """רק מעבר 2 קרא שם (מעבר 1 ריק): הערך מוצג ככתום עם handwritten_unconfirmed."""
    d = decide_name(Field_(), regions(first="טובה"), "first_name")
    assert d.value == "טובה" and d.flags == [F_HANDWRITTEN_UNCONFIRMED]
    assert d.uncertain and cell(d).value == "טובה" and cell(d).orange


def test_single_reading_from_pass1_only_is_shown_when_the_region_is_valid():
    d = decide_name(hand("טובה"), regions(first=None), "first_name")
    assert d.value == "טובה" and d.flags == [F_HANDWRITTEN_UNCONFIRMED]
    assert cell(d).value == "טובה"


def test_two_agreeing_readings_stay_yellow():
    """עמוד 5: שתי קריאות עצמאיות שמסכימות -> צהוב (לא כתום ולא ירוק)."""
    d = decide_name(hand("טובה"), regions(first="טובה"), "first_name")
    assert d.value == "טובה" and d.flags == [F_HANDWRITTEN] and H_TWO_READS in d.hints
    c = cell(d)
    assert c.value == "טובה" and c.yellow and not c.orange


def test_region_not_ok_is_still_empty_and_flagged():
    """region_ok=false: הקריאה נפסלת, התא ריק וכתום."""
    d = decide_name(hand("טובה"), regions(first="מאור", region_ok=False), "first_name")
    assert d.value is None and F_REGION_NOT_OK in d.flags and d.uncertain
    assert not cell(d).value and cell(d).orange


def test_without_a_second_pass_a_single_reading_stays_empty():
    """בלי מעבר שני בכלל (לא רץ / נכשל): ההתנהגות הישנה נשמרת - ריק וכתום, הקריאה ב-alternatives."""
    d = decide_name(hand("טובה"))
    assert d.value is None and d.flags == [F_HANDWRITTEN_UNCONFIRMED] and d.alternatives == ["טובה"]
    assert not cell(d).value


def test_father_name_is_never_shown():
    d = decide_name(hand("חיים", evidence="שם האב: חיים"), regions(first="חיים"), "first_name")
    assert d.value is None and F_FATHER_NAME in d.flags
    assert not cell(d).value


def test_unknown_label_reading_is_never_shown():
    d = decide_name(hand("פנקסוביץ", label="מין"), regions(last="פנקסוביץ", label="מין"), "last_name")
    assert d.value is None and F_NAME_LABEL_UNKNOWN in d.flags
    assert not cell(d).value


def test_printed_name_with_a_known_label_stays_green():
    printed = Field_(value="ישראל", confidence=0.95, source="printed", label="שם פרטי")
    d = decide_name(printed, regions(first="ישראל", label="שם פרטי", source="printed"), "first_name")
    assert d.value == "ישראל" and d.flags == [] and not d.uncertain
    c = cell(d)
    assert c.value == "ישראל" and not c.orange and not c.yellow


@pytest.mark.parametrize("first,second", [("אביטל", "מאור"), (None, "מאור"), ("אביטל", None)])
def test_a_shown_name_is_never_green(first, second):
    d = decide_name(hand(first) if first else Field_(), regions(first=second), "first_name")
    if d.value:
        assert d.uncertain and d.flags                     # יש ערך -> חייב דגל, אף פעם לא ירוק
        assert cell(d).orange or cell(d).yellow
