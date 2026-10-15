from src import rules
from src.rules import F_CONFLICT, F_HANDWRITTEN, F_REGION_NOT_OK, decide_center, decide_id, decide_name, region_state
from src.schema import Field_, NumberCandidate, RegionsExtraction


def idn(value, source="handwritten"):
    return NumberCandidate(value=value, label="ת.ז.", source=source, confidence=1.0)


def regions(patient_ok=True, barcode_ok=True, id_value=None, first=None, last=None, numbers=(), ok=True):
    r = RegionsExtraction.model_validate({
        "patient": {"region_ok": patient_ok,
                    "id_number": {"value": id_value, "confidence": 0.9, "source": "handwritten"},
                    "first_name": {"value": first, "confidence": 0.9, "source": "handwritten"},
                    "last_name": {"value": last, "confidence": 0.9, "source": "handwritten"}},
        "barcode": {"region_ok": barcode_ok,
                    "numbers": [{"value": v, "label": lb, "orientation": "normal", "confidence": 1.0} for v, lb in numbers]},
    })
    return {"ok": ok, "model": "m", **r.model_dump()}


def test_region_state():
    assert region_state(None, "patient") == "absent"
    assert region_state({"ok": False}, "patient") == "absent"
    assert region_state(regions(), "patient") == "ok"
    assert region_state(regions(patient_ok=False), "patient") == "not_ok"
    assert region_state(regions(barcode_ok=False), "barcode") == "not_ok"


def test_second_pass_id_agrees_with_first():
    d = decide_id([idn("11223344")], regions(id_value="11223344"))
    assert d.value == "11223344"
    assert F_CONFLICT not in d.flags and F_REGION_NOT_OK not in d.flags
    assert d.flags == []                       # שתי קריאות מסכימות ו-11223344 עוברת ספרת ביקורת: ירוק, גם בכתב יד


def test_second_pass_id_disagrees_is_conflict():
    d = decide_id([idn("11223344")], regions(id_value="11923344"))
    assert d.value is None
    assert F_CONFLICT in d.flags
    assert d.alternatives == ["11223344", "11923344"]


def test_second_pass_id_alone_when_first_missing():
    d = decide_id([], regions(id_value="01122334"))
    assert d.value == "01122334"
    assert F_HANDWRITTEN in d.flags


def test_region_not_ok_ignores_second_pass_id_and_flags_orange():
    d = decide_id([idn("11223344", source="printed")], regions(patient_ok=False, id_value="99999999"))
    assert d.value == "11223344"               # רק המעבר הראשון
    assert F_REGION_NOT_OK in d.flags
    assert d.uncertain


def test_region_not_ok_flags_even_when_empty():
    d = decide_id([], regions(patient_ok=False, id_value="99999999"))
    assert d.value is None
    assert F_REGION_NOT_OK in d.flags


def test_no_second_pass_means_no_region_flag():
    d = decide_id([idn("11223344", source="printed")], None)
    assert not d.uncertain
    assert not decide_id([idn("11223344", source="printed")], {"ok": False}).uncertain


def test_name_agreement_and_conflict():
    f = Field_(value="ישראל", confidence=0.9, source="handwritten")
    agree = decide_name(f, regions(first="ישראל"), "first_name")
    assert agree.value == "ישראל" and F_CONFLICT not in agree.flags
    assert agree.flags == [F_HANDWRITTEN]                 # שתי קריאות מסכימות: ערך, כתום (כתב יד)
    differ = decide_name(f, regions(first="רבקה"), "first_name")
    assert differ.value is None and F_CONFLICT in differ.flags and differ.alternatives == ["ישראל", "רבקה"]


def test_name_from_second_pass_only_is_single_reading_so_unconfirmed():
    d = decide_name(Field_(), regions(last="ישראלי"), "last_name")
    assert d.value is None and d.flags == [rules.F_HANDWRITTEN_UNCONFIRMED] and d.alternatives == ["ישראלי"]


def test_name_region_not_ok_ignored_and_flagged():
    d = decide_name(Field_(), regions(patient_ok=False, first="רבקה"), "first_name")
    assert d.value is None
    assert F_REGION_NOT_OK in d.flags


def test_center_region_not_ok_ignores_barcode_numbers_and_flags():
    d = decide_center([], regions(barcode_ok=False, numbers=[("937188", None)]))
    assert d.value is None                     # המספר מהחיתוך הפסול לא נכנס
    assert F_REGION_NOT_OK in d.flags


def test_center_region_not_ok_keeps_first_pass_label():
    d = decide_center([NumberCandidate(value="939539", label="מרכזי", source="printed", confidence=1.0)],
                      regions(barcode_ok=False, numbers=[("111111", "מרכזי")]))
    assert d.value == "939539"
    assert F_REGION_NOT_OK in d.flags


def test_missing_region_ok_field_defaults_to_not_ok():
    r = RegionsExtraction.model_validate({"patient": {}, "barcode": {}})
    assert region_state({"ok": True, **r.model_dump()}, "patient") == "not_ok"


def test_rules_module_exports_flag():
    assert rules.F_REGION_NOT_OK == "region_not_ok"
