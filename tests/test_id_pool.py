import pytest

from src import rules
from src.rules import (
    F_CONFLICT, F_HANDWRITTEN, H_ID_CHECKSUM_REPLACED, H_ID_FROM_POOL, check_israeli_id, decide_id, id_pool_extras,
)
from src.schema import NumberCandidate

VALID = "11223344"        # עובר ספרת ביקורת (כמו ת"ז הדוגמאות)
VALID2 = "123456782"      # עובר
INVALID = "058359550"     # נכשל (עמוד 14)


def num(value, label=None, source="handwritten"):
    return NumberCandidate(value=value, label=label, source=source, confidence=0.9)


def idn(value, source="handwritten", label="ת.ז"):
    return NumberCandidate(value=value, label=label, source=source, confidence=0.9)


def test_sanity_of_test_values():
    assert check_israeli_id(VALID) and check_israeli_id(VALID2) and not check_israeli_id(INVALID)


# ---------- המאגר: אילו מספרים כלליים נכנסים ----------

def test_extras_require_handwritten_digits_only_7_to_9_and_valid_checksum():
    numbers = [
        num(VALID),                       # נכנס
        num("12532200"),                  # נכשל ספרת ביקורת
        num(VALID, source="printed"),     # מודפס
        num("1122334455"),                # 10 ספרות
        num("112233"),                    # 6 ספרות
        num("11-22-33-44"),               # לא ספרות בלבד
        num(VALID2, label="מספר התחייבות"),   # תווית אחרת לא פוסלת כתב יד: ממילא עובר ספרת ביקורת
    ]
    assert id_pool_extras(numbers) == [VALID, VALID2]


def test_extras_deduplicate_ignoring_leading_zeros():
    assert id_pool_extras([num("011223344"), num(VALID)]) == ["011223344"]


# ---------- ההחלטה ----------

def test_page_18_no_main_candidate_single_valid_extra_is_orange_value():
    d = decide_id([], numbers=[num(VALID), num("12532200")])
    assert d.value == VALID and d.flags == [F_HANDWRITTEN] and H_ID_FROM_POOL in d.hints


def test_no_main_candidate_two_valid_extras_conflict():
    d = decide_id([], numbers=[num(VALID), num(VALID2)])
    assert d.value is None and d.flags == [F_CONFLICT] and d.alternatives == [VALID, VALID2]


def test_page_14_main_fails_checksum_valid_extra_replaces_it():
    d = decide_id([idn(INVALID)], numbers=[num(VALID)])
    assert d.value == VALID and d.flags == [F_HANDWRITTEN]
    assert d.alternatives == [INVALID] and H_ID_CHECKSUM_REPLACED in d.hints


def test_main_valid_and_different_valid_extra_is_conflict_no_preference_for_handwriting():
    """ת"ז מדפסת תקינה (מודפסת) מול מועמד כללי תקין בכתב יד: סתירה, לא העדפה לכתב יד."""
    d = decide_id([idn(VALID2, source="printed", label="תעודת זהות")], numbers=[num(VALID)])
    assert d.value is None and d.flags == [F_CONFLICT] and d.alternatives == [VALID2, VALID]


def test_main_valid_and_same_extra_is_unchanged():
    d = decide_id([idn(VALID)], numbers=[num(VALID)])
    assert d.value == VALID and d.flags == [F_HANDWRITTEN] and not d.hints.count(H_ID_FROM_POOL)


def test_page_5_extra_failing_checksum_is_not_admitted_so_printed_id_stays():
    """עמוד 5: 01122334 (האמיתית) נכשלת בספרת ביקורת ולכן לא נכנסת; ת"ז המדפסת נשארת (מגבלה ידועה)."""
    d = decide_id([idn("308462795", source="printed", label="תעודת זהות")], numbers=[num("01122334")])
    assert d.value == "308462795" and d.flags == []


def test_main_failing_checksum_with_two_valid_extras_is_conflict():
    d = decide_id([idn(INVALID)], numbers=[num(VALID), num(VALID2)])
    assert d.value is None and d.flags == [F_CONFLICT]


def test_existing_main_conflict_is_not_changed_by_extras():
    d = decide_id([idn("00112233"), idn("11223344")], numbers=[num(VALID2)])
    assert d.value is None and d.flags == [F_CONFLICT] and d.alternatives == ["00112233", "11223344"]


def test_unchanged_without_numbers_argument():
    d = decide_id([idn(INVALID)])
    assert d.value == INVALID


def test_nothing_relevant_in_general_list_is_unchanged():
    d = decide_id([idn(INVALID)], numbers=[num("12532200"), num("730578626", source="printed")])
    assert d.value == INVALID and d.flags == [F_HANDWRITTEN, "id_checksum_failed"]     # הערך נשאר; ספרת ביקורת נכשלת: כתום


def test_region_not_ok_still_flags_after_pool():
    regions = {"ok": True, "patient": {"region_ok": False, "id_number": {"value": None}}, "barcode": {}}
    d = decide_id([], regions, [num(VALID)])
    assert d.value == VALID and rules.F_REGION_NOT_OK in d.flags


def test_assemble_passes_general_numbers_to_id_rule():
    from src.assemble import page_rows
    from src.schema import PageExtraction
    page = PageExtraction(is_commitment_form=True, page_quality="ok", id_numbers=[idn(INVALID)],
                          numbers=[num(VALID), num("730578626", "התחייבות מספר", source="printed")])
    rows = page_rows({"ok": True, "model": "m", **page.model_dump()})
    assert rows[0]["id"].value == VALID


def test_needs_second_pass_sees_the_pool_too():
    from src.pipeline import needs_second_pass
    from src.schema import PageExtraction
    page = PageExtraction(is_commitment_form=True, page_quality="ok", numbers=[num(VALID), num("939376", "מרכזי", "printed")])
    needed, reasons = needs_second_pass(page)
    assert needed and reasons == ["id:handwritten"]          # ת"ז נמצאה (מהמאגר) אבל בכתב יד: עדיין צריך מעבר שני
