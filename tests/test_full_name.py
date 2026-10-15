"""שדה "שם מלא": הפיצול נעשה בקוד. המילה הראשונה (בקריאה מימין לשמאל) = שם פרטי, השאר = שם משפחה."""
from src.assemble import page_rows
from src.rules import (
    F_NAME_LABEL_UNKNOWN, F_REGION_NOT_OK, H_FULL_NAME_SPLIT, apply_field_validity, is_full_name_label,
    patient_labels_missing, split_full_name_fields, split_full_name_regions,
)
from src.schema import Field_, PageExtraction, RegionsExtraction


def full(value, source="handwritten", conf=0.95, label="שם מלא", alts=()):
    return Field_(value=value, confidence=conf, source=source, label=label, alternatives=list(alts))


def test_label_detection():
    assert is_full_name_label("שם מלא") and is_full_name_label("שם  מלא:") and is_full_name_label("שם המטופל - שם מלא")
    assert not is_full_name_label("שם פרטי") and not is_full_name_label(None) and not is_full_name_label("מלאי")


def test_two_words_split_first_word_is_first_name():
    first, last, did = split_full_name_fields(full("ישראל ישראלי"), Field_())
    assert did and first.value == "ישראל" and last.value == "ישראלי"
    assert first.source == last.source == "handwritten" and first.confidence == 0.95      # המקור והביטחון נשמרים


def test_more_than_two_words_rest_is_last_name():
    first, last, did = split_full_name_fields(Field_(), full("ישראל בן דוד"))              # הערך בשדה השני
    assert did and first.value == "ישראל" and last.value == "בן דוד"


def test_single_word_or_other_label_is_not_split():
    f, l = full("ישראל"), Field_()
    assert split_full_name_fields(f, l) == (f, l, False)
    g = full("ישראל ישראלי", label="שם פרטי")
    assert split_full_name_fields(g, Field_()) == (g, Field_(), False)
    h = full("ישראל ישראלי", label=None)
    assert split_full_name_fields(h, Field_()) == (h, Field_(), False)


def test_different_full_values_are_left_for_conflict_handling():
    a, b = full("ישראל ישראלי"), full("דנה לוי")
    assert split_full_name_fields(a, b) == (a, b, False)


def test_alternatives_are_split_too():
    first, last, _ = split_full_name_fields(full("ישראל ישראלי", alts=["ישראל ישראלה", "יוסי"]), Field_())
    assert first.alternatives == ["ישראל", "יוסי"] and last.alternatives == ["ישראלה"]


def page(first, last):
    p = PageExtraction(is_commitment_form=True, page_quality="ok", first_name=first, last_name=last)
    return {"ok": True, **p.model_dump()}


def test_handwritten_full_name_is_never_green_on_model_output_alone():
    r = page_rows(page(full("ישראל ישראלי"), Field_()), regions=None)[0]
    assert r["first_name"].value is None and F_NAME_LABEL_UNKNOWN not in r["first_name"].flags     # קריאה אחת בכתב יד: לא מאושרת
    agree = {"ok": True, "model": "m", **RegionsExtraction.model_validate({"patient": {
        "region_ok": True, "labels_seen": [],
        "first_name": full("ישראל ישראלי").model_dump(), "last_name": Field_().model_dump()}}).model_dump()}
    r = page_rows(page(full("ישראל ישראלי"), Field_()), regions=apply_field_validity(agree))[0]
    assert (r["first_name"].value, r["last_name"].value) == ("ישראל", "ישראלי")                      # שתי קריאות מסכימות: ערך
    assert r["first_name"].flags and r["last_name"].flags                                            # אבל כתום, כי כתב יד
    assert H_FULL_NAME_SPLIT in r["first_name"].hints and F_REGION_NOT_OK not in r["first_name"].flags


def test_printed_full_name_with_label_is_a_clean_value():
    r = page_rows(page(full("דנה לוי", source="printed", conf=0.95), Field_()), regions=None)[0]
    assert (r["first_name"].value, r["last_name"].value) == ("דנה", "לוי")
    assert not r["first_name"].flags and not r["last_name"].flags


def test_regions_full_name_label_counts_as_both_labels_seen():
    reg = {"ok": True, "patient": {"region_ok": True, "labels_seen": [], "first_name": full("ישראל ישראלי").model_dump(),
                                   "last_name": Field_().model_dump()}}
    assert patient_labels_missing(reg) is False                      # אין סיבה לחיתוך חוזר רחב יותר
    split, did = split_full_name_regions(reg)
    assert did and split["patient"]["first_name"]["value"] == "ישראל" and reg["patient"]["first_name"]["value"] == "ישראל ישראלי"
