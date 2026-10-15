import pytest

from src import confirm
from src.export import Cell


def test_set_override_saves_trims_and_clears():
    o: dict = {}
    confirm.set_override(o, 3, "first_name", "  ישראל ")
    assert o == {(3, "first_name"): "ישראל"}
    confirm.set_override(o, 3, "first_name", "")
    assert o == {}


def test_unknown_field_and_invalid_values_are_rejected_without_changing_state():
    o = {(3, "id"): "111"}
    with pytest.raises(ValueError):
        confirm.set_override(o, 3, "color", "x")
    for key, bad in (("id", "12ab"), ("commitment#0", "abc"), ("center", "12;x"), ("date", "31.06.2026")):
        with pytest.raises(ValueError):
            confirm.set_override(o, 3, key, bad)
    assert o == {(3, "id"): "111"}


def test_every_field_can_be_confirmed_with_normalized_values():
    o: dict = {}
    for key, typed in (("id", " 0112 233-44 "), ("center", "937309, 937310 ;937309"), ("date", "18-06-2026"),
                       ("commitment#2", "50 364-186"), ("sender", " כללית "), ("last_name", " לוי ")):
        confirm.set_override(o, 5, key, typed)
    assert o == {(5, "id"): "011223344", (5, "center"): "937309 ; 937310", (5, "date"): "18.06.2026",
                 (5, "commitment#2"): "50364186", (5, "sender"): "כללית", (5, "last_name"): "לוי"}
    confirm.set_override(o, 5, "id", "  ")                           # ערך ריק מבטל
    assert (5, "id") not in o


def test_override_key_is_per_row_only_for_commitment():
    assert confirm.override_key("commitment", 2) == "commitment#2" and confirm.override_key("center", 2) == "center"


def test_field_fractions_use_the_region_of_each_field():
    page = {"page": 1, "boxes": {"patient": {"fractions": [0, 0.1, 1, 0.2]}, "barcode": {"fractions": [0.5, 0.5, 1, 0.6]},
                                  "commitment": {"fractions": [0, 0.7, 0.4, 0.8]}}}
    assert confirm.field_fractions(page, "id") == (0, 0.1, 1, 0.2) == confirm.field_fractions(page, "first_name")
    assert confirm.field_fractions(page, "center") == (0.5, 0.5, 1, 0.6)
    assert confirm.field_fractions(page, "commitment") == (0, 0.7, 0.4, 0.8)
    assert confirm.field_fractions(page, "date") is None and confirm.field_fractions(page, "sender") is None
    assert confirm.field_crop("no_such_file.pdf", page, "center") is None and confirm.field_crop("x.pdf", page, "date") is None


def test_suggestions_are_value_then_alternatives_without_duplicates_or_blanks():
    cell = Cell(None, None, ["handwritten_unconfirmed"], alternatives=["ישראל", " ישראל ", "", "ישראלה"])
    assert confirm.name_suggestions(cell) == ["ישראל", "ישראלה"]
    cell = Cell("דנה", "דנה", [], alternatives=["דנה", "דינה"])
    assert confirm.name_suggestions(cell) == ["דנה", "דינה"]
    confirmed = Cell("דני", "דני", [], confirmed=True, original="דנה", alternatives=["דינה"])
    assert confirm.name_suggestions(confirmed) == ["דנה", "דינה"]          # ההצעה המקורית נשארת לחיצה


def test_crop_fractions_prefer_what_the_second_pass_cut_then_pass1_box_then_fixed_band():
    assert confirm.name_row_fractions({"boxes": {"patient": {"fractions": [0.02, 0.2, 0.98, 0.4]}}}) == (0.02, 0.2, 0.98, 0.4)
    wide = {"boxes": {"patient": {"fractions": [0.02, 0.2, 0.98, 0.4], "retry_fractions": [0.02, 0.1, 0.98, 0.5]}}}
    assert confirm.name_row_fractions(wide) == (0.02, 0.1, 0.98, 0.5)
    from_box = confirm.name_row_fractions({"pass1": {"patient_box": {"ymin": 266, "xmin": 96, "ymax": 341, "xmax": 913}}})
    assert from_box[0] == 0.02 and 0.2 < from_box[1] < 0.27 and 0.34 < from_box[3] < 0.45
    fixed = confirm.name_row_fractions({"pass1": {}})
    assert fixed[1] == 0.0 and fixed[3] > 0.5                              # חיתוך קבוע (מעל חצי עמוד)


def test_name_row_crop_fails_softly():
    assert confirm.name_row_crop("no_such_file.pdf", {"page": 1}) is None


def test_name_row_crop_renders_a_wide_jpeg_from_the_clean_pdf():
    import io
    from pathlib import Path
    from PIL import Image
    pdf = Path("data/clean_part1.pdf")
    if not pdf.exists():
        pytest.skip("no sample pdf")
    data = confirm.name_row_crop(str(pdf), {"page": 20, "boxes": {"patient": {"fractions": [0.02, 0.226, 0.98, 0.381]}}})
    im = Image.open(io.BytesIO(data))
    assert im.width > 3 * im.height > 0


def test_id_checksum_suggestions_become_one_click_buttons_after_the_read_value():
    from src.rules import decide_id
    from src.schema import NumberCandidate
    d = decide_id([NumberCandidate(value="11923344", label="ת.ז.", source="handwritten", confidence=0.9)])
    cell = Cell(d.value, d.raw, list(d.flags), list(d.hints), list(d.alternatives))
    assert confirm.name_suggestions(cell, "id") == ["11923344", "11223344", "11923844", "11923349"]
    overrides: dict = {}
    confirm.set_override(overrides, 1, "id", "11223344")                           # בחירה בלחיצה נשמרת כערך מאושר
    assert overrides == {(1, "id"): "11223344"}


def test_suggestions_for_empty_non_name_cell_and_barcode_values():
    empty = Cell(None, None, ["no_center_label"], alternatives=["111111", "222222"])
    assert confirm.name_suggestions(empty, "center") == ["111111", "222222"]
    differs = Cell("333333", "333333", ["low_confidence"], hints=["center_barcode_differs:111111 ; 222222"])
    assert confirm.name_suggestions(differs, "center") == ["333333", "111111", "222222"]
    assert confirm.name_suggestions(differs, "id") == ["333333"]       # הרמז רק למרכזי
