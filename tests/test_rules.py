from datetime import date

import pytest

from src import rules
from src.rules import (
    F_CONFLICT, F_HANDWRITTEN, F_INVALID_DATE, F_INVALID_FORMAT, F_LOW_CONFIDENCE,
    F_NO_COMMITMENT, F_NOT_RECEIPT_KIND, F_RECEIPT_BEFORE_SAMPLE, F_YEAR_OUT_OF_RANGE,
    F_ID_CHECKSUM_FAILED, F_ID_NOT_ISRAELI, H_TWO_READS,
)
from src.schema import DateCandidate, Field_, NumberCandidate

TODAY = date(2026, 10, 13)


def num(value, label=None, source="printed", conf=1.0):
    return NumberCandidate(value=value, label=label, source=source, confidence=conf)


def idn(value, label='ת.ז.', source="printed", conf=1.0):
    return NumberCandidate(value=value, label=label, source=source, confidence=conf)


def dt(value, kind="lab_stamp", source="printed", conf=1.0, evidence="stamp"):
    return DateCandidate(value=value, kind=kind, source=source, confidence=conf, evidence=evidence)


# ---------- ת"ז ----------

def test_id_digits_only():
    d = rules.decide_id([idn("001-122 3344")])
    assert d.value == "0011223344"                  # ספרות בלבד, בלי חיתוך אפסים
    assert d.flags == [rules.F_ID_LENGTH] and d.uncertain      # 10 ספרות: אף פעם לא ירוק (tests/test_id_length.py)


@pytest.mark.parametrize("raw", ["1122334", "11223344", "0011223344"])  # 7, 8, 10 ספרות: הערך לא נפסל ולא משתנה
def test_id_lengths_not_rejected(raw):
    d = rules.decide_id([idn(raw)])
    assert d.value == raw
    # 1122334 נכשלת בספרת ביקורת, ו-10 ספרות (0011223344) כתומה בגלל האורך; 8 ספרות תקינות נשארות ירוקות
    assert d.uncertain == (raw in ("1122334", "0011223344"))


def test_id_checksum_failure_is_orange_flag_value_unchanged():
    d = rules.decide_id([idn("11223345")])  # ספרת ביקורת שגויה
    assert d.value == "11223345"          # הערך לא נפסל ולא משתנה
    assert F_ID_CHECKSUM_FAILED in d.flags
    assert d.uncertain                    # כתום


def p2(id_value, source="handwritten"):
    """מעבר שני תקין עם ת"ז אחת."""
    return {"ok": True, "patient": {"region_ok": True, "labels_seen": ["id_number"],
                                    "id_number": {"value": id_value, "source": source, "confidence": 0.9}}}


def test_checksum_pass_and_two_readings_agree_is_green_even_handwritten():
    d = rules.decide_id([idn("11223344", source="handwritten")], p2("11223344"))
    assert d.value == "11223344" and d.flags == [] and H_TWO_READS in d.hints


def test_checksum_pass_single_reading_handwritten_stays_orange():
    d = rules.decide_id([idn("11223344", source="handwritten")])
    assert d.flags == [F_HANDWRITTEN]


def test_checksum_fail_is_orange_even_when_two_readings_agree():
    d = rules.decide_id([idn("11923344", source="handwritten")], p2("11923344"))
    assert d.value == "11923344"                       # הערך לא משתנה
    assert F_ID_CHECKSUM_FAILED in d.flags and d.uncertain
    assert d.alternatives == ["11223344", "11923844", "11923349"]     # כל ההחלפות שעוברות, לפי סדר המיקום


def test_all_passing_replacements_are_suggested_up_to_three():
    assert not rules.check_israeli_id("11923344")
    assert rules.id_checksum_suggestions("11923344") == ["11223344", "11923844", "11923349"]


def test_more_than_three_passing_replacements_means_no_suggestions():
    assert not rules.check_israeli_id("10000000")
    assert rules.id_checksum_suggestions("10000000") == []          # 4 החלפות עוברות: יותר מדי
    d = rules.decide_id([idn("10000000")])
    assert F_ID_CHECKSUM_FAILED in d.flags and d.value == "10000000" and d.alternatives == []


def test_single_suggestion_and_value_is_never_replaced():
    value = "11223348"          # רק 1→7 בספרה השנייה עוברת
    assert not rules.check_israeli_id(value)
    assert rules.id_checksum_suggestions(value) == ["17223348"]
    d = rules.decide_id([idn(value, source="handwritten")], p2(value))
    assert F_ID_CHECKSUM_FAILED in d.flags and d.value == value and d.alternatives == ["17223348"]


def test_leading_zeros_normalized_then_checked():
    assert rules.check_israeli_id("0011223344")             # ספרת הביקורת עוברת אחרי הסרת האפסים...
    d = rules.decide_id([idn("0011223344")])
    assert d.value == "0011223344" and d.flags == [rules.F_ID_LENGTH]     # ...אבל 10 ספרות כפי שנקראו אינן ירוקות
    assert rules.decide_id([idn("011223344")]).flags == []   # 9 ספרות עם אפס מוביל: ללא שינוי


def test_seven_digit_id_fails_checksum():
    assert not rules.check_israeli_id("1122334")
    d = rules.decide_id([idn("1122334")])
    assert F_ID_CHECKSUM_FAILED in d.flags and d.value == "1122334"


def test_letters_mean_not_israeli_format_no_checksum():
    d = rules.decide_id([idn("A1234567")])
    assert F_ID_NOT_ISRAELI in d.flags and F_ID_CHECKSUM_FAILED not in d.flags
    assert d.uncertain and d.alternatives == []


def test_more_than_nine_digits_after_stripping_zeros_is_not_israeli():
    d = rules.decide_id([idn("1234567890123")])
    assert F_ID_NOT_ISRAELI in d.flags and F_ID_CHECKSUM_FAILED not in d.flags


def test_every_suggestion_passes_checksum_and_differs_by_one_digit():
    for v in ["11923344", "11223345", "1122334", "12345678", "00000001"]:
        sugg = rules.id_checksum_suggestions(v)
        assert len(sugg) <= 3
        for x in sugg:
            assert rules.check_israeli_id(x) and not rules.check_israeli_id(v)
            assert len(x) == len(v) and sum(c != d for c, d in zip(x, v)) == 1


def test_checksum_never_rejects_value():
    for v in ["1", "99999999", "123456789012"]:
        assert rules.decide_id([idn(v)]).value == v


def test_sample_ids_pass_checksum():
    """ת"ז של הדוגמאות (11223344 ו-0011223344) עוברות את ספרת הביקורת."""
    assert rules.check_israeli_id("11223344")
    assert rules.check_israeli_id("0011223344")
    assert not rules.check_israeli_id("00112233")


def test_israeli_id_checksum():
    assert rules.check_israeli_id("123456782")
    assert not rules.check_israeli_id("123456783")
    assert not rules.check_israeli_id("12345678901")


def test_id_conflict_different_digits():
    d = rules.decide_id([idn("00112233"), idn("11223344")])
    assert d.value is None
    assert F_CONFLICT in d.flags
    assert d.alternatives == ["00112233", "11223344"]


def test_id_same_after_leading_zeros_is_not_conflict():
    d = rules.decide_id([idn("0011223344"), idn("11223344")])
    assert d.value == "0011223344" and rules.F_CONFLICT not in d.flags      # אותו מספר אחרי הסרת אפסים: לא סתירה
    assert d.flags == [rules.F_ID_LENGTH]                                     # אבל הערך שנבחר הוא 10 ספרות: כתום, בלי חיתוך


def test_id_not_found_is_empty():
    assert rules.decide_id([]) == rules.Decision()
    assert rules.decide_id([idn("---")]).value is None


def test_id_handwritten_is_orange():
    d = rules.decide_id([idn("0011223344", source="handwritten")])
    assert d.value == "0011223344"
    assert F_HANDWRITTEN in d.flags


def test_id_printed_occurrence_cancels_handwritten_flag():
    d = rules.decide_id([idn("11223344", source="handwritten"), idn("11223344", source="printed")])
    assert not d.uncertain


# ---------- תאריכים ----------

@pytest.mark.parametrize("raw,expected", [
    ("18-06-2026", "18.06.2026"),
    ("18.06.2026", "18.06.2026"),
    ("18/06/2026", "18.06.2026"),
    ("1.6.2026", "01.06.2026"),
    ("18 - 06 - 2026", "18.06.2026"),
    ("2026-06-18", "18.06.2026"),
    ("18/06/26", "18.06.2026"),
])
def test_date_format_conversion(raw, expected):
    d = rules.normalize_date(raw, TODAY)
    assert d.value == expected
    assert not d.uncertain


def test_date_invalid_calendar_not_guessed():
    d = rules.normalize_date("31.06.2026", TODAY)
    assert d.value is None
    assert d.raw == "31.06.2026"
    assert F_INVALID_DATE in d.flags


@pytest.mark.parametrize("raw", ["10.08.02026", "30.008.2026", "abc", "18.06"])
def test_date_noise_is_not_fixed(raw):
    """נרמול הוא המרה בלבד (סעיף 16): בלי כללי תיקון."""
    d = rules.normalize_date(raw, TODAY)
    assert d.value is None
    assert F_INVALID_FORMAT in d.flags


def test_date_empty():
    assert rules.normalize_date(None, TODAY) == rules.Decision()
    assert rules.normalize_date("  ", TODAY).value is None


def test_date_year_out_of_range_keeps_value_but_flags():
    d = rules.normalize_date("18.06.2019", TODAY)
    assert d.value == "18.06.2019"
    assert F_YEAR_OUT_OF_RANGE in d.flags


def test_receipt_date_basic():
    d = rules.decide_receipt_date([dt("18-06-2026")], TODAY)
    assert d.value == "18.06.2026"
    assert not d.uncertain


def test_receipt_date_ignores_other_kinds():
    dates = [
        dt("15.06.2026", "print_date"),
        dt("04.12.2009", "birth_date"),
        dt("14.12.2026", "expiry_date"),
        dt("18-06-2026", "lab_stamp"),
    ]
    assert rules.decide_receipt_date(dates, TODAY).value == "18.06.2026"


def test_receipt_date_preferred_over_sample():
    dates = [dt("16.06.2026", "sample_date"), dt("18.06.2026", "lab_stamp")]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "18.06.2026"
    assert not d.uncertain


def test_sample_date_only_is_orange():
    d = rules.decide_receipt_date([dt("18.06.2026", "sample_date")], TODAY)
    assert d.value == "18.06.2026"
    assert F_NOT_RECEIPT_KIND in d.flags


def test_receipt_before_sample_flagged():
    dates = [dt("16.06.2026", "receipt_date"), dt("18.06.2026", "sample_date")]
    d = rules.decide_receipt_date(dates, TODAY)
    assert F_RECEIPT_BEFORE_SAMPLE in d.flags


def test_receipt_conflict():
    dates = [dt("16.06.2026"), dt("17.06.2026")]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value is None
    assert F_CONFLICT in d.flags
    assert d.alternatives == ["16.06.2026", "17.06.2026"]


def test_receipt_same_date_twice_is_not_conflict():
    d = rules.decide_receipt_date([dt("18-06-2026"), dt("18.06.2026")], TODAY)
    assert d.value == "18.06.2026"
    assert not d.uncertain


def test_receipt_invalid_date_is_empty_and_orange():
    d = rules.decide_receipt_date([dt("31.06.2026")], TODAY)
    assert d.value is None
    assert d.raw == "31.06.2026"
    assert d.uncertain


def test_receipt_handwritten_is_orange():
    d = rules.decide_receipt_date([dt("18.06.2026", source="handwritten")], TODAY)
    assert d.value == "18.06.2026"
    assert F_HANDWRITTEN in d.flags


def test_receipt_no_candidates():
    assert rules.decide_receipt_date([], TODAY) == rules.Decision()


# ---------- שמות ----------

def test_name_handwritten_single_reading_is_empty_unconfirmed_even_with_high_confidence():
    """שם בכתב יד בקריאה אחת: ריק + handwritten_unconfirmed, הקריאה ב-alternatives בלבד (בלי raw)."""
    d = rules.decide_name(Field_(value="דנה", confidence=1.0, source="handwritten"))
    assert d.value is None and d.raw is None
    assert d.flags == [rules.F_HANDWRITTEN_UNCONFIRMED]
    assert d.alternatives == ["דנה"]


def test_name_printed_clear_is_not_orange():
    d = rules.decide_name(Field_(value="דנה", confidence=0.95, source="printed", label="שם פרטי"))
    assert not d.uncertain


def test_name_low_confidence_is_orange():
    d = rules.decide_name(Field_(value="דנה", confidence=0.4, source="printed", label="שם פרטי"))
    assert F_LOW_CONFIDENCE in d.flags


@pytest.mark.parametrize("value", [None, "", "   "])
def test_name_unreadable_stays_empty(value):
    d = rules.decide_name(Field_(value=value, source="handwritten"))
    assert d.value is None


# ---------- ערכים מרובים והתחייבויות ----------

def test_split_and_join_multi():
    assert rules.split_multi("937309 ; 937310;937311") == ["937309", "937310", "937311"]
    assert rules.split_multi(None) == []
    assert rules.join_multi(["937309", "937310", "937309", ""]) == "937309 ; 937310"


def test_commitment_numbers_by_label_meaning():
    numbers = [
        num("730578626", "התחייבות מספר"),
        num("939376"),                      # ברקוד בלי תווית
        num("3833", "מוקד"),
        num("035303030", "טלפון"),
        num("87250", "קוד השירות"),
    ]
    result = rules.commitment_numbers(numbers)
    assert [c.value for c in result] == ["730578626"]


@pytest.mark.parametrize("label", ["התחייבות", "דרישה", "מס הדגימה", "אסמכתא תקציבית", "מספר ההתחייבות"])
def test_commitment_label_variants(label):
    assert [c.value for c in rules.commitment_numbers([num("50364186", label)])] == ["50364186"]


def test_commitment_keeps_leading_zeros():
    assert rules.commitment_numbers([num("000302651707", "מספר התחייבות")])[0].value == "000302651707"


def test_multiple_commitments_one_row_each():
    commitments = rules.commitment_numbers([
        num("260005102632", "מספר התחייבות"),
        num("260005102611", "מספר התחייבות"),
        num("260005102644", "מספר התחייבות"),
        num("260005102632", "מספר התחייבות"),   # כפילות
    ])
    rows = rules.expand_rows({"id": "11223344", "center": "948062"}, commitments)
    assert len(rows) == 3
    assert {r["commitment"] for r in rows} == {"260005102632", "260005102611", "260005102644"}
    assert all(r["id"] == "11223344" and r["center"] == "948062" for r in rows)


def test_form_without_commitment_gives_one_flagged_row():
    rows = rules.expand_rows({"id": "11223344"}, [])
    assert len(rows) == 1
    assert rows[0]["commitment"] is None
    assert F_NO_COMMITMENT in rows[0]["commitment_flags"]


# ---------- effective_date_kind: ראיית חותמת ----------

def _lab(evidence, source="printed", value="05-08-2026"):
    return DateCandidate(value=value, kind="lab_stamp", evidence=evidence, source=source, confidence=0.9)


@pytest.mark.parametrize("evidence", ["stamp", "חותמת התקבל", "התקבל", "קבלה", " קבלה ", "קבלה:"])
def test_stamp_evidence_keeps_lab_stamp(evidence):
    """עמוד 14: המודל סיווג נכון את החותמת, והראיה שלו היא המילה "קבלה" לבדה."""
    assert rules.effective_date_kind(_lab(evidence)) == "lab_stamp"


@pytest.mark.parametrize("evidence", ["תאריך קבלה", "תאריך קליטה", "תאריך נטילה", None, "", "הודפס"])
def test_printed_field_labels_are_still_demoted_to_receipt_date(evidence):
    """"תאריך קבלה" הוא שדה מודפס של השולח (עמודים 6 ו-12), לא חותמת של המעבדה."""
    assert rules.effective_date_kind(_lab(evidence)) == "receipt_date"


def test_handwritten_date_without_stamp_evidence_becomes_handwritten_date():
    """kind=lab_stamp בכתב יד בלי ראיית חותמת: תאריך בכתב יד שנוסף לטופס (לא נופל ל-receipt_date)."""
    assert rules.effective_date_kind(_lab(None, source="handwritten")) == "handwritten_date"


def test_page_14_stamp_wins_over_handwritten_date_and_handwriting_goes_to_note():
    """עמוד 14: חותמת 05-08-2026 (ראיה "קבלה") מול 4-8-26 בכתב יד: החותמת מנצחת, בלי conflict ובלי כתום."""
    dates = [
        DateCandidate(value="4-8-26", kind="other", evidence="תאריך", source="handwritten", confidence=0.9),
        DateCandidate(value="05-08-2026", kind="lab_stamp", evidence="קבלה", source="printed", confidence=0.9),
    ]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "05.08.2026" and d.flags == []
    assert d.alternatives == ["04.08.2026"]            # כתב היד בהערה


def test_stamp_with_low_confidence_is_orange_and_keeps_handwritten_in_note():
    dates = [DateCandidate(value="05-08-2026", kind="lab_stamp", evidence="stamp", source="printed", confidence=0.4),
             DateCandidate(value="4-8-26", kind="handwritten_date", source="handwritten", confidence=0.9)]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "05.08.2026" and d.flags == [F_LOW_CONFIDENCE] and d.alternatives == ["04.08.2026"]


def test_handwritten_date_equal_to_stamp_is_not_an_alternative():
    dates = [DateCandidate(value="05-08-2026", kind="lab_stamp", evidence="stamp", source="printed", confidence=0.9),
             DateCandidate(value="5/8/26", kind="handwritten_date", source="handwritten", confidence=0.9)]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "05.08.2026" and d.alternatives == [] and d.flags == []


def test_handwritten_date_beats_printed_receipt_and_is_orange():
    dates = [DateCandidate(value="12/08/2026", kind="receipt_date", evidence="תאריך קבלה", source="printed", confidence=1.0),
             DateCandidate(value="16/8/26", kind="handwritten_date", source="handwritten", confidence=0.9)]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "16.08.2026" and d.flags == [F_HANDWRITTEN]


def test_two_different_handwritten_dates_conflict():
    dates = [DateCandidate(value="16/8/26", kind="handwritten_date", source="handwritten", confidence=0.9),
             DateCandidate(value="10/8/26", kind="handwritten_date", source="handwritten", confidence=0.9)]
    assert F_CONFLICT in rules.decide_receipt_date(dates, TODAY).flags


@pytest.mark.parametrize("kind,source,evidence,expected", [
    ("lab_received", "printed", "stamp", "lab_stamp"),                 # הסכמה הישנה: חותמת
    ("lab_received", "printed", "קבלה", "lab_stamp"),
    ("lab_received", "printed", "תאריך קבלה", "receipt_date"),         # שדה מודפס של השולח
    ("lab_received", "handwritten", None, "handwritten_date"),        # כתב יד שנוסף
    ("lab_received", "handwritten", "stamp", "lab_stamp"),
    ("sample_date", "printed", "x", "sample_date"),                   # סוגים אחרים לא משתנים
    ("other", "handwritten", None, "other"),                          # legacy_date_kind ממיר רק lab_received
])
def test_legacy_date_kind_conversion(kind, source, evidence, expected):
    assert rules.legacy_date_kind(kind, source, evidence) == expected


# ---------- עדיפות תאריך: חותמת/כתב יד של המעבדה, ת"ז לפי תווית ----------

def test_lab_stamp_beats_printed_receipt_date():
    """עמוד 6: "תאריך קליטה" מודפס 17/06 והחותמת של המעבדה 18-06-2026. האמת: החותמת."""
    dates = [dt("17/06/2026", "receipt_date"), dt("17/06/2026", "sample_date"), dt("18-06-2026", "lab_stamp")]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "18.06.2026"
    assert not d.uncertain


def test_handwritten_lab_date_two_digit_year_is_orange():
    """עמוד 12: תאריך בכתב יד 16/8/26."""
    d = rules.decide_receipt_date([dt("16/8/26", "handwritten_date", source="handwritten", evidence=None)], TODAY)
    assert d.value == "16.08.2026"
    assert F_HANDWRITTEN in d.flags


def test_printed_receipt_date_without_lab_stamp_is_orange():
    d = rules.decide_receipt_date([dt("17/06/2026", "receipt_date")], TODAY)
    assert d.value == "17.06.2026"
    assert rules.F_NOT_LAB_RECEIVED in d.flags


def test_two_different_lab_dates_conflict():
    d = rules.decide_receipt_date([dt("18.06.2026"), dt("19.06.2026")], TODAY)
    assert d.value is None
    assert F_CONFLICT in d.flags


@pytest.mark.parametrize("label", ["ת.ז.", 'ת"ז', "ת. זהות", "תעודת זהות", "ת.ז", "מטופל"])
def test_id_labels_accepted(label):
    assert rules.decide_id([idn("11223344", label=label)]).value == "11223344"


@pytest.mark.parametrize("label", [None, "", "נקבה", "מקרה", "תזכורת", "טלפון", "מס' הדגימה"])
def test_printed_id_candidates_without_id_label_are_dropped(label):
    """עמוד 7: מספר בלי תווית ת"ז (30115877) לא נחשב ת"ז; עדיף ריק מניחוש."""
    assert rules.decide_id([idn("30115877", label=label)]).value is None


def test_handwritten_id_without_label_is_accepted_but_orange():
    """עמוד 7: ת"ז בכתב יד בלי תווית (1122334) לצד מספר מקרה מודפס (30115877)."""
    d = rules.decide_id([idn("1122334", label=None, source="handwritten"), idn("30115877", label=None)])
    assert d.value == "1122334"
    assert F_HANDWRITTEN in d.flags


def test_printed_receipt_field_mislabeled_as_lab_stamp_does_not_conflict_with_stamp():
    """עמוד 6: המודל תייג גם את "תאריך קליטה" המודפס כ-lab_stamp."""
    dates = [
        DateCandidate(value="17/06/2026", kind="lab_stamp", evidence="תאריך קליטה", source="printed", confidence=1.0),
        DateCandidate(value="18-06-2026", kind="lab_stamp", evidence="stamp", source="handwritten", confidence=1.0),
    ]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "18.06.2026"
    assert d.alternatives == []


def test_printed_stamp_labeled_lab_stamp_is_kept():
    dates = [DateCandidate(value="21-06-2026", kind="lab_stamp", evidence="stamp", source="printed", confidence=1.0)]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "21.06.2026"
    assert not d.uncertain


def test_handwritten_date_labeled_other_is_treated_as_lab_stamp():
    """עמוד 12: תאריך בכתב יד בתחתית, סווג other."""
    dates = [
        DateCandidate(value="12/08/2026", kind="receipt_date", evidence="תאריך קבלה", source="printed", confidence=1.0),
        DateCandidate(value="16/8/26", kind="other", evidence="handwritten at bottom", source="handwritten", confidence=1.0),
    ]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "16.08.2026"
    assert F_HANDWRITTEN in d.flags


def test_printed_other_date_alone_is_shown_orange_not_ignored():
    """נפילה ל-other (כשאין אף סוג מזוהה): מוצג אבל תמיד כתום, date_kind_unclear."""
    dates = [DateCandidate(value="31.05.2026", kind="other", evidence="top left", source="printed", confidence=1.0)]
    d = rules.decide_receipt_date(dates, TODAY)
    assert d.value == "31.05.2026" and "date_kind_unclear" in d.flags
