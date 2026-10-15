import pytest

from src import rules
from src.rules import (
    F_CONFLICT, F_FATHER_NAME, F_HANDWRITTEN, F_HANDWRITTEN_UNCONFIRMED, F_LOW_CONFIDENCE, decide_id,
    decide_name, is_father_evidence,
)
from src.schema import Field_, NumberCandidate, RegionsExtraction


def fld(value, source="handwritten", conf=0.9, evidence=None, label="שם פרטי"):
    return Field_(value=value, confidence=conf, source=source, evidence=evidence, label=label)


def regions(first=None, last=None, source="handwritten", evidence=None, patient_ok=True):
    def f(v):
        return {"value": v, "confidence": 0.9, "source": source, "evidence": evidence}
    r = RegionsExtraction.model_validate({"patient": {"region_ok": patient_ok, "first_name": f(first), "last_name": f(last)},
                                          "barcode": {"region_ok": True}})
    return {"ok": True, "model": "m", **r.model_dump()}


# ---------- handwritten_unconfirmed ----------

def test_single_handwritten_reading_is_empty_with_reading_as_alternative_only():
    d = decide_name(fld("רחל"))
    assert d.value is None and d.raw is None
    assert d.flags == [F_HANDWRITTEN_UNCONFIRMED]
    assert d.alternatives == ["רחל"]
    assert d.uncertain


def test_two_agreeing_handwritten_readings_keep_value_in_orange():
    d = decide_name(fld("רחל"), regions(first="רחל"), "first_name")
    assert d.value == "רחל" and d.flags == [F_HANDWRITTEN]


def test_two_different_handwritten_readings_conflict_and_unconfirmed():
    d = decide_name(fld("רחל"), regions(first="רבקה"), "first_name")
    assert d.value is None
    assert d.flags == [F_CONFLICT, F_HANDWRITTEN_UNCONFIRMED]
    assert d.alternatives == ["רחל", "רבקה"]


def test_printed_name_is_unchanged():
    d = decide_name(fld("דנה", source="printed", conf=0.95))
    assert d.value == "דנה" and d.flags == []


def test_printed_low_confidence_still_orange_with_value():
    d = decide_name(fld("דנה", source="printed", conf=0.4))
    assert d.value == "דנה" and d.flags == [F_LOW_CONFIDENCE]


def test_printed_reading_confirms_handwritten_reading():
    d = decide_name(fld("דנה", source="printed", conf=0.95), regions(first="דנה"), "first_name")
    assert d.value == "דנה" and d.flags == []            # הופעה מודפסת מסכימה = ודאות


def test_unreadable_name_stays_plain_empty():
    assert decide_name(fld(None, source="unknown", conf=0.0)) == rules.Decision()


def test_id_and_numbers_are_not_affected_by_handwriting_rule():
    cand = NumberCandidate(value="11223344", label="ת.ז.", source="handwritten", confidence=1.0)
    d = decide_id([cand])
    assert d.value == "11223344" and d.flags == [F_HANDWRITTEN]      # כמו קודם: ערך, כתום
    assert rules.decide_center([NumberCandidate(value="939376", label="מרכזי", source="handwritten", confidence=1.0)]).value == "939376"


def test_region_not_ok_second_reading_ignored_name_stays_unconfirmed_and_flagged():
    d = decide_name(fld("רחל"), regions(first="רחל", patient_ok=False), "first_name")
    assert d.value is None
    assert d.flags == [F_HANDWRITTEN_UNCONFIRMED, rules.F_REGION_NOT_OK]


# ---------- father_name ----------

@pytest.mark.parametrize("evidence", ["שם האב:אריה צבי", "אב: יונתן פייר", "האב: דוד", "שם האב דוד", "שם אב: דוד"])
def test_father_evidence_matches(evidence):
    assert is_father_evidence(evidence)


@pytest.mark.parametrize("evidence", [None, "", "שם פרטי : יסמין", "נבדק: יוסף ישפה", "פנינה כהן", "שם מלא - רחל כהן",
                                       "תל אביב", "אביב", "בן דוד", "בן: דוד", "בת: שרה", "אבו כביר", "אב-טיפוס"])
def test_non_father_evidence_does_not_match(evidence):
    """כולל בן/בת: אין להם דוגמה אמיתית ולכן אין להם כלל."""
    assert not is_father_evidence(evidence)


def test_father_name_printed_is_rejected_with_reading_in_alternatives():
    """עמוד 26: המודל קרא את שם האב המודפס."""
    d = decide_name(fld("יונתן", source="printed", conf=0.95, evidence="אב: יונתן פייר"))
    assert d.value is None and d.raw is None
    assert d.flags == [F_FATHER_NAME] and d.alternatives == ["יונתן"]


def test_father_name_handwritten_is_rejected_not_just_unconfirmed():
    """עמוד 16: שם האב בכתב יד."""
    d = decide_name(fld("אריה", evidence="שם האב:אריה צבי"))
    assert d.value is None and d.flags == [F_FATHER_NAME] and d.alternatives == ["אריה"]


def test_father_reading_does_not_count_as_agreeing_reading():
    f = fld("אריה", evidence="שם האב:אריה צבי")
    d = decide_name(f, regions(first="אריה", evidence="שם האב:אריה צבי"), "first_name")
    assert d.value is None and d.flags == [F_FATHER_NAME] and d.alternatives == ["אריה"]


def test_non_father_second_reading_survives_when_first_is_father():
    d = decide_name(fld("אריה", evidence="שם האב:אריה צבי"), regions(first="רחל"), "first_name")
    assert d.value is None                                  # קריאה אחת בכתב יד: לא מאושרת
    assert d.flags == [F_HANDWRITTEN_UNCONFIRMED, F_FATHER_NAME]
    assert d.alternatives == ["רחל", "אריה"]


def test_father_rule_applies_to_last_name_too():
    d = decide_name(fld("צבי", evidence="שם האב:אריה צבי"), None, "last_name")
    assert d.value is None and d.flags == [F_FATHER_NAME]


# ---------- תווית שם לא מוכרת ----------

from src.rules import F_NAME_LABEL_UNKNOWN, is_unknown_name_label  # noqa: E402


def test_unknown_printed_label_gives_empty_flagged_with_alternative():
    d = decide_name(Field_(value="יונתן", confidence=0.95, source="printed", label="שם הפרט:"))
    assert d.value is None and d.flags == [F_NAME_LABEL_UNKNOWN] and d.alternatives == ["יונתן"]


@pytest.mark.parametrize("label", ["שם פרטי", "שם פרטי:", "שם משפחה", "שם המטופל", "מטופל:", "שם החולה"])
def test_known_label_is_not_unknown_and_printed_name_passes(label):
    assert not is_unknown_name_label(label)
    assert decide_name(Field_(value="דנה", confidence=0.95, source="printed", label=label)).value == "דנה"


@pytest.mark.parametrize("label", [None, ""])
def test_missing_label_is_not_unknown_label_but_printed_name_without_label_is_suggestion_only(label):
    """שם מודפס בלי תווית מטופל (למשל כותרת "ביק.ראש." שנקראה כשם): alternatives בלבד, name_label_missing."""
    assert not is_unknown_name_label(label)
    d = decide_name(Field_(value="דנה", confidence=0.95, source="printed", label=label))
    assert d.value is None and d.alternatives == ["דנה"] and "name_label_missing" in d.flags


def test_handwritten_name_without_label_is_not_affected_by_the_printed_rule():
    d = decide_name(Field_(value="דנה", confidence=0.9, source="handwritten", label=None))
    assert "name_label_missing" not in d.flags and d.flags == ["handwritten_unconfirmed"]


def test_printed_heading_read_as_name_page_25_pattern():
    """ביק.ראש. הופיע כשם פרטי ושם משפחה: מודפס, בלי תווית. לא ערך."""
    first = decide_name(Field_(value="ביק", confidence=0.8, source="printed", evidence="ביק.ראש."))
    last = decide_name(Field_(value="ראש", confidence=0.8, source="printed", evidence="ביק.ראש."))
    assert first.value is None and last.value is None and first.alternatives == ["ביק"]


# ---------- id_single_source: ת"ז שנקראה רק במעבר השני ----------

def _p2_id(value, source="printed"):
    r = RegionsExtraction.model_validate({"patient": {"region_ok": True, "id_number": {"value": value, "confidence": 0.95, "source": source}},
                                          "barcode": {"region_ok": True}})
    return {"ok": True, "model": "m", **r.model_dump()}


def test_id_only_in_second_pass_is_orange_single_source_with_alternative():
    d = decide_id([], _p2_id("30530668"))
    assert d.value == "30530668" and "id_single_source" in d.flags and d.alternatives == ["30530668"]


def test_id_single_source_even_when_checksum_passes():
    d = decide_id([], _p2_id("123456782"))              # ספרת ביקורת תקינה: לא מכריעה
    assert "id_single_source" in d.flags


def test_id_labeled_in_first_pass_and_confirmed_stays_green():
    d = decide_id([NumberCandidate(value="11223344", label="ת.ז.", source="printed", confidence=1.0)], _p2_id("11223344"))
    assert d.value == "11223344" and not d.flags


def test_id_first_pass_only_unchanged_and_no_second_pass_no_flag():
    d = decide_id([NumberCandidate(value="11223344", label="ת.ז.", source="printed", confidence=1.0)])
    assert d.value == "11223344" and not d.flags


def test_id_second_pass_with_region_not_ok_is_not_single_source():
    r = _p2_id("30530668"); r["patient"]["region_ok"] = False
    assert "id_single_source" not in decide_id([], r).flags
