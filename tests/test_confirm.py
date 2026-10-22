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


def test_sender_has_no_region_concept_at_all():
    """לשולח אין מושג אזור כלל (לא ב-FIELD_REGION): (None, False) בלי שום ניסיון, גם עם ערך ועם ברקודים בעמוד."""
    page = {"page": 1, "barcodes": [{"format": "Code128", "text": "123456", "box": [0.1, 0.1, 0.2, 0.15]}]}
    assert confirm.field_fractions(page, "sender", "כללית") == (None, False)


def test_date_without_any_model_box_or_matching_barcode_has_no_region_either():
    """לתאריך יש מושג אזור (FIELD_REGION["date"]), אבל בלי box שהמודל הצהיר עליו ובלי ברקוד תואם, אין שום אזור
    להציע - לא מאומת ולא משוער."""
    page = {"page": 1, "barcodes": [{"format": "Code128", "text": "123456", "box": [0.1, 0.1, 0.2, 0.15]}]}
    assert confirm.field_fractions(page, "date", "18.06.2026") == (None, False)
    assert confirm.field_crop("x.pdf", page, "date", "18.06.2026") == (None, False)


def test_field_fractions_never_trusts_the_models_box_blindly_a_wrong_barcode_is_not_verification():
    """רגרסיה: ה-box שהמודל "הצהיר" (patient_box / barcode_box וכו') לא נבדק מקומית ולכן לא נספר כ"מאומת". בדוגמה
    מהשטח: מרכזי 939376 נקרא נכון, אבל ה-box של המודל הצביע על ברקוד אחר בעמוד (תאריך ההנפקה, 0046025783, קרוב
    לפינה הנגדית). הערך שהוחלט שווה בדיוק לברקוד הנכון - האימות המקומי מצליח ומחזיר את האזור הנכון, לא את ה-box
    השגוי של המודל."""
    page = {"page": 1, "rotation": {"applied": 0},
            "barcodes": [{"format": "Code128", "text": "939376", "box": [0.05, 0.05, 0.22, 0.10]},
                         {"format": "Code128", "text": "0046025783", "box": [0.65, 0.72, 0.92, 0.77]}]}
    fr, verified = confirm.field_fractions(page, "center", "939376")
    assert verified is True and fr is not None
    x0, y0, x1, y1 = fr
    assert x1 < 0.5 and y1 < 0.5                          # לא קרוב לברקוד השגוי (האחר, שליד תאריך ההנפקה)
    assert x0 <= 0.05 and y0 <= 0.05 and x1 >= 0.22 and y1 >= 0.10     # מכיל את תיבת הברקוד הנכון (עם שוליים, לא פחות)


def test_center_without_a_verifying_barcode_shows_nothing_not_even_the_models_box():
    """החריג (NO_APPROX_REGION): למרכזי, שהאזור שלו הוא בחירה בין כמה ברקודים אפשריים בעמוד, אין נפילה לאזור
    המודל בלי אימות - זו בדיוק התקלה שתוקנה (box שמצביע על ברקוד לא נכון). (None, False) גם כש-boxes.barcode קיים."""
    page = {"page": 1, "rotation": {"applied": 0}, "boxes": {"barcode": {"fractions": [0.65, 0.72, 0.92, 0.77]}},
            "barcodes": [{"format": "Code128", "text": "0046025783", "box": [0.65, 0.72, 0.92, 0.77]}]}
    assert confirm.field_fractions(page, "center", "939376") == (None, False)


def test_a_field_with_no_barcode_dependence_falls_back_to_the_models_box_marked_as_approximate():
    """הכלל הכללי (לא "מרכזי"): בלי אימות מקומי, האזור שהמודל "הצהיר" עליו מוצג בכל זאת, מאומת=False - קירוב בלבד,
    לא פסילה. התחייבות עם box שהמודל דיווח, ובלי ברקוד תואם לערך."""
    page = {"page": 3, "rotation": {"applied": 0}, "boxes": {"commitment": {"fractions": [0.3, 0.6, 0.5, 0.65]}},
            "barcodes": []}
    fr, verified = confirm.field_fractions(page, "commitment", "107646")
    assert verified is False and fr == (0.3, 0.6, 0.5, 0.65)


def test_field_fractions_use_the_decoded_barcode_position_when_it_matches_the_value():
    """אימות מקומי: ערך שהוחלט ששווה בדיוק לטקסט שפוענח מברקוד (src/barcode.py) - האזור המוצג הוא מיקום הברקוד,
    לא box של המודל (אין כזה כלל כאן), ומאומת=True."""
    page = {"page": 3, "rotation": {"applied": 0}, "barcodes": [{"format": "Code128", "text": "50364186", "box": [0.3, 0.6, 0.5, 0.65]}]}
    (x0, y0, x1, y1), verified = confirm.field_fractions(page, "commitment", "50364186")
    assert verified is True
    assert x0 < 0.3 and y0 < 0.6 and x1 > 0.5 and y1 > 0.65          # מורחב (שוליים), לא קטן מתיבת הברקוד
    # ערך שאינו טקסט של אף ברקוד, ובלי box של המודל לנפול אליו: לא מאומת ובלי קירוב
    assert confirm.field_fractions(page, "commitment", "99999999") == (None, False)


def test_field_fractions_rotates_the_decoded_barcode_position_to_match_the_applied_rotation():
    """הברקוד מפוענח מה-PDF בלי הסיבוב הנוסף שהקוד מחיל לפני השליחה למודל (src/barcode.py); כשיש rotation.applied
    המיקום ממופה לעמוד המסובב (src/crop.rotate_fractions_cw), אחרת הסימון היה נופל במקום הלא נכון אחרי סיבוב."""
    base = {"page": 1, "barcodes": [{"format": "Code128", "text": "937309", "box": [0.0, 0.0, 0.1, 0.1]}]}
    unrotated, v1 = confirm.field_fractions({**base, "rotation": {"applied": 0}}, "center", "937309")
    rotated, v2 = confirm.field_fractions({**base, "rotation": {"applied": 90}}, "center", "937309")
    assert v1 is True and v2 is True and unrotated != rotated
    assert rotated[2] > 0.8                                           # הפינה השמאלית-עליונה עברה לפינה הימנית-עליונה


def test_field_fractions_with_no_barcodes_at_all_cannot_be_verified():
    """נפילה בטוחה: בלי ברקודים (או בלי פענוח), לכל ערך, אין שום אזור מאומת. שדה שאינו "מרכזי" מקבל במקום זאת
    את אזור המודל (קירוב, מאומת=False) אם יש כזה; "מרכזי" (NO_APPROX_REGION) לא מקבל אפילו את זה."""
    fr, verified = confirm.field_fractions({"page": 1}, "id", "123456789")
    assert verified is False and fr is not None                      # patient: יש חיתוך קבוע (region_fractions fallback)
    assert confirm.field_fractions({"page": 1, "barcodes": None}, "center", "937309") == (None, False)
    assert confirm.field_fractions({"page": 1, "barcodes": []}, "commitment", "50364186") == (None, False)
    crop, verified = confirm.field_crop("no_such_file.pdf", {"page": 1}, "center", "937309")
    assert crop is None and verified is False


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
