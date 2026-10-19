"""ת"ז ירוקה רק באורך 5 עד 9 ספרות כפי שנקראה (כולל אפסים מובילים). 10 ספרות ומעלה / פחות מ-5: כתום עם id_length, הערך נשמר כמות שהוא."""
import pytest

from src import rules
from src.assemble import page_rows
from src.confirm import normalize_override
from src.export import build_rows
from src.rules import F_CONFLICT, F_HANDWRITTEN, F_ID_CHECKSUM_FAILED, F_ID_LENGTH, F_ID_NOT_ISRAELI, H_TWO_READS, check_israeli_id, decide_id
from src.schema import NumberCandidate

NINE = "123456782"                 # 9 ספרות, עובר ספרת ביקורת
TEN = "0" + NINE                   # 10 ספרות: אחרי הסרת האפס זהה ל-NINE ולכן עובר ספרת ביקורת (המקרה שהיה יוצא ירוק)
EIGHT = "11223344"                 # 8 ספרות, עובר ספרת ביקורת (ת"ז הדוגמאות)


def idn(value, source="printed", label="ת.ז", confidence=0.99):
    return NumberCandidate(value=value, label=label, source=source, confidence=confidence)


def p2(value, source="handwritten"):
    return {"ok": True, "patient": {"region_ok": True, "labels_seen": ["id_number"],
                                    "id_number": {"value": value, "source": source, "confidence": 0.95}}}


def test_the_values_used_here():
    assert check_israeli_id(NINE) and check_israeli_id(TEN) and check_israeli_id(EIGHT) and len(TEN) == 10


# ---------- 10 ספרות: אף פעם לא ירוק ----------

def test_ten_digits_pass1_printed_is_orange_not_green():
    d = decide_id([idn(TEN)])
    assert d.value == TEN and d.flags == [F_ID_LENGTH] and d.uncertain          # הערך נשאר בתא, בלי חיתוך


def test_ten_digits_pass1_handwritten_is_orange_with_length_flag():
    d = decide_id([idn(TEN, source="handwritten")])
    assert d.value == TEN and F_ID_LENGTH in d.flags and d.uncertain


def test_ten_digits_pass2_only_is_orange():
    d = decide_id([], p2(TEN))
    assert d.value == TEN and F_ID_LENGTH in d.flags and d.uncertain


def test_ten_digits_both_readings_agree_is_still_orange():
    d = decide_id([idn(TEN, source="handwritten")], p2(TEN))
    assert d.value == TEN and H_TWO_READS in d.hints                  # שתי הקריאות הסכימו (רמז נשמר)...
    assert F_ID_LENGTH in d.flags and d.uncertain                      # ...אבל זה לא מספיק לירוק


def test_ten_digits_with_leading_zeros_agree_with_nine_digit_reading_is_not_green():
    # קריאה אחת 10 ספרות עם אפס מוביל, השנייה 9 ספרות: אותו מספר אחרי הסרת אפסים (הסכמה), אבל הערך שנבחר הוא 10 ספרות
    d = decide_id([idn(TEN, source="handwritten")], p2(NINE))
    assert not (d.value and not d.flags)


def test_length_flag_gives_no_checksum_suggestions_and_no_checksum_flag():
    d = decide_id([idn("0000112233", source="handwritten")])
    assert d.value == "0000112233" and F_ID_LENGTH in d.flags
    assert F_ID_CHECKSUM_FAILED not in d.flags and d.alternatives == []


@pytest.mark.parametrize("value", ["12345678901", "123456789012"])
def test_more_than_nine_after_stripping_has_both_flags(value):
    d = decide_id([idn(value)])
    assert d.value == value and F_ID_LENGTH in d.flags and F_ID_NOT_ISRAELI in d.flags and d.uncertain


@pytest.mark.parametrize("value", ["1234", "12", "1"])
def test_fewer_than_five_digits_is_orange(value):
    d = decide_id([idn(value)])
    assert d.value == value and F_ID_LENGTH in d.flags and d.uncertain


# ---------- 5-9 ספרות: ללא שינוי ----------

def test_nine_digits_printed_stays_green():
    d = decide_id([idn(NINE)])
    assert d.value == NINE and d.flags == [] and not d.uncertain


def test_nine_digits_two_readings_agree_stays_green():
    d = decide_id([idn(NINE, source="handwritten")], p2(NINE))
    assert d.value == NINE and d.flags == [] and H_TWO_READS in d.hints


def test_eight_digits_behave_as_before():
    assert decide_id([idn(EIGHT)]).flags == []                                      # מודפס ועובר ספרת ביקורת: ירוק
    d = decide_id([idn(EIGHT, source="handwritten")], p2(EIGHT))
    assert d.flags == [] and H_TWO_READS in d.hints
    assert decide_id([idn(EIGHT, source="handwritten")]).flags == [F_HANDWRITTEN]   # קריאה אחת בכתב יד: כתום, כמו קודם


def test_five_digits_not_flagged_for_length():
    d = decide_id([idn("12340")])
    assert F_ID_LENGTH not in d.flags


# ---------- סתירה ממשיכה לעבוד ----------

def test_two_readings_disagree_is_still_a_conflict():
    d = decide_id([idn(TEN, source="handwritten")], p2("987654321"))
    assert d.value is None and F_CONFLICT in d.flags and d.uncertain


def test_conflict_between_two_ten_digit_readings():
    d = decide_id([idn("0011223344", source="handwritten")], p2("0099887766"))
    assert d.value is None and F_CONFLICT in d.flags


# ---------- דרך ההקלדה הידנית ----------

def test_manual_input_validation_is_unchanged():
    assert normalize_override("id", " 12-34 56 ") == "123456"
    assert normalize_override("id", "12ab") is None
    assert normalize_override("id", "") is None
    assert normalize_override("id", "0011223344") == "0011223344"      # החלטת אדם: מותרת (מאושרת, כחולה), לא ירוקה אוטומטית


def test_typed_ten_digit_value_is_confirmed_blue_not_green():
    page = {"page": 1, "pass1": {"ok": True, "is_commitment_form": True, "page_quality": "ok",
                                 "id_numbers": [{"value": TEN, "label": "ת.ז", "source": "printed", "confidence": 0.99}],
                                 "numbers": [{"value": "107646", "label": "התחייבות", "source": "printed", "confidence": 0.9}]},
            "pass2": None}
    auto = build_rows(page)[0].cells["id"]
    assert auto.value == TEN and F_ID_LENGTH in auto.flags and auto.orange and not auto.confirmed
    typed = build_rows(page, {(1, "id"): "0011223344"})[0].cells["id"]
    assert typed.confirmed and typed.value == "0011223344" and not typed.orange


def test_assembled_row_shows_orange_ten_digit_value():
    page = {"ok": True, "is_commitment_form": True, "page_quality": "ok",
            "id_numbers": [{"value": TEN, "label": "ת.ז", "source": "printed", "confidence": 0.99}],
            "numbers": [{"value": "107646", "label": "התחייבות", "source": "printed", "confidence": 0.9}]}
    row = page_rows(page)[0]
    assert row["id"].value == TEN and row["id"].uncertain
