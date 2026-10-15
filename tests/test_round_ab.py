"""A: נפילת תאריך ל-other, התחייבות עם תווית חלשה, אין ריק שקט. B: שבר התחייבות אינו מרכזי."""
from src import rules
from src.assemble import page_rows
from src.rules import (F_DATE_KIND_UNCLEAR, F_MISSING_REQUIRED, F_WEAK_LABEL, commitment_numbers, decide_center,
                       decide_receipt_date)
from src.schema import DateCandidate, NumberCandidate, PageExtraction, RegionsExtraction
from datetime import date

TODAY = date(2026, 10, 13)


def dc(value, kind="other", source="printed", ev=None):
    return DateCandidate(value=value, kind=kind, evidence=ev, source=source, confidence=1.0)


def num(value, label=None, source="printed"):
    return NumberCandidate(value=value, label=label, source=source, confidence=1.0)


# ---------- A: תאריכים ----------

def test_other_single_distinct_value_shown_orange_date_kind_unclear():
    d = decide_receipt_date([dc("30.08.2026"), dc("30.08.2026"), dc("12.11.1971", "birth_date"), dc("31.12.9999", "expiry_date")], TODAY)
    assert d.value == "30.08.2026" and F_DATE_KIND_UNCLEAR in d.flags and d.uncertain


def test_other_several_values_is_conflict_with_all_in_alternatives():
    d = decide_receipt_date([dc("22.02.2026"), dc("21.06.2026"), dc("17.06.2026")], TODAY)
    assert d.value is None and "conflict" in d.flags
    assert d.alternatives == ["22.02.2026", "21.06.2026", "17.06.2026"]


def test_birth_expiry_print_never_used_even_as_fallback():
    for kind in ("birth_date", "expiry_date", "print_date"):
        assert decide_receipt_date([dc("30.08.2026", kind)], TODAY).value is None


def test_known_kinds_win_over_other():
    d = decide_receipt_date([dc("01.01.2026"), dc("18.06.2026", "sample_date")], TODAY)
    assert d.value == "18.06.2026" and F_DATE_KIND_UNCLEAR not in d.flags


# ---------- A: התחייבות ----------

def test_weak_label_single_value_is_orange_only():
    c = commitment_numbers([num("304497989", "מספר:"), num("5303030", "תור:")])
    assert [d.value for d in c] == ["304497989"] and F_WEAK_LABEL in c[0].flags and c[0].uncertain


def test_weak_label_variants_and_requirements():
    assert commitment_numbers([num("123456", "מספר")])[0].flags[0] == F_WEAK_LABEL
    assert commitment_numbers([num("12", "מספר")]) == []                       # קצר מדי
    assert commitment_numbers([num("123456", "מספר טלפון")]) == []             # לא בדיוק "מספר"
    assert commitment_numbers([num("123456", "מספר:"), num("654321", "מספר:")]) == []   # עמום: לא נבחר


def test_strong_label_beats_weak_and_stays_green():
    c = commitment_numbers([num("304497989", "מספר:"), num("251120150", "מספר התחייבות")])
    assert [d.value for d in c] == ["251120150"] and not c[0].uncertain


# ---------- A: אין ריק שקט ----------

def page(**kw):
    p = PageExtraction(is_commitment_form=True, page_quality="ok", **kw)
    return {"ok": True, "model": "x", **p.model_dump()}


def test_every_required_empty_cell_gets_missing_required_field():
    row = page_rows(page())[0]
    for key in ("first_name", "last_name", "date", "center", "id"):
        assert F_MISSING_REQUIRED in row[key].flags, key
    assert F_MISSING_REQUIRED in row["commitment_flags"] and "no_commitment" in row["commitment_flags"]


def test_filled_cells_do_not_get_the_flag():
    row = page_rows(page(numbers=[num("939376", "מרכזי"), num("730578626", "התחייבות מספר")],
                         id_numbers=[num("11223344", "ת.ז.")],
                         dates=[dc("18.06.2026", "lab_stamp", ev="חותמת התקבל")]))[0]
    for key in ("center", "date", "id"):
        assert F_MISSING_REQUIRED not in row[key].flags
    assert F_MISSING_REQUIRED not in row["commitment_flags"]


def test_non_commitment_form_without_number_has_no_rows():
    p = PageExtraction(is_commitment_form=False, page_quality="ok")
    assert page_rows({"ok": True, "model": "x", **p.model_dump()}) == []


# ---------- B: שבר התחייבות ----------

def test_center_candidate_equal_to_commitment_tail_is_dropped_and_audited():
    nums = [num("945504", "מרכזי"), num("000351"), num("944000351", "מספר התחייבות")]
    d = decide_center(nums)
    assert d.value == "945504" and not d.uncertain
    assert "center_fragment_dropped:000351" in d.hints


def test_fragment_rule_is_generic_6_and_5_digits():
    d = decide_center([num("12345"), num("99912345", "דרישה")])               # 5 ספרות
    assert d.value is None and "center_fragment_dropped:12345" in d.hints
    d = decide_center([num("654321"), num("7654321", "התחייבות")])
    assert "center_fragment_dropped:654321" in d.hints


def test_non_suffix_center_is_kept():
    d = decide_center([num("939376", "מרכזי"), num("730578626", "התחייבות מספר")])
    assert d.value == "939376" and not d.hints


def test_fragment_dropped_from_barcode_region_numbers_too():
    r = RegionsExtraction.model_validate({"patient": {"region_ok": True}, "barcode": {"region_ok": True, "numbers": [
        {"value": "000351", "label": None, "orientation": "normal", "confidence": 1.0},
        {"value": "945504", "label": "מרכזי", "orientation": "normal", "confidence": 1.0}]}})
    d = decide_center([num("944000351", "מספר התחייבות")], {"ok": True, "model": "m", **r.model_dump()})
    assert d.value == "945504" and "center_fragment_dropped:000351" in d.hints
