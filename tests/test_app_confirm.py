"""מסך אישור השם (app.py), בדוגמה השמורה: לחיצה על הצעה או הקלדה שומרות ערך סופי; בלי אישור הערך נשאר כתום."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
pytestmark = pytest.mark.skipif(not Path("outputs/clean_part1_v4b").exists() or not Path("data/clean_part1.pdf").exists(),
                                reason="needs the saved sample run")


def row_of(page: int) -> int:
    """אינדקס השורה הראשונה של העמוד בטבלה (בסדר העמודים; עמוד שדולג לא נספר; עמוד 25 הוא שלוש שורות)."""
    import json
    from src.export import build_rows, skip_reason
    row = 0
    for p in range(1, page):
        res = json.loads(Path(f"outputs/clean_part1_v4b/p{p}.json").read_text(encoding="utf-8"))
        row += 0 if skip_reason(res) else len(build_rows(res))
    return row


def loaded_app(page: int = 1, column: str = "שם פרטי"):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    next(b for b in at.button if b.label.startswith("טען")).click().run()
    at.session_state["selected_cell"] = (row_of(page), column)
    at.run()
    assert not at.exception
    return at


def button(at, key):
    return next(b for b in at.button if b.key == key)


def test_unreadable_name_shows_no_suggestions_and_says_to_type():
    at = loaded_app(1)                                            # עמוד 1: אין שתי קריאות מסכימות
    assert not [b for b in at.button if b.key and b.key.startswith("sg_")]
    assert any("לא נקרא, יש להקליד" in w.value for w in at.warning)
    assert at.session_state["name_overrides"] == {}


def test_suggestion_exists_only_where_two_readings_agree_and_clicking_saves_it():
    at = loaded_app(12)                                           # עמוד 12: "ישראל" בשתי קריאות
    keys = [b.key for b in at.button if b.key and b.key.startswith("sg_12_first_name_")]
    assert keys == ["sg_12_first_name_0"] and button(at, keys[0]).label == "ישראל"
    button(at, keys[0]).click().run()
    assert not at.exception
    assert at.session_state["name_overrides"] == {(12, "first_name"): "ישראל"}
    assert any("אושר על ידי המשתמש: ישראל" in s.value for s in at.success)
    assert at.text_input(key="txt_12_first_name").value == "ישראל"


def test_typed_value_is_saved_and_can_be_cleared():
    at = loaded_app(1)
    at.text_input(key="txt_1_first_name").set_value("  ישראל ").run()
    button(at, "ok_1_first_name").click().run()
    assert at.session_state["name_overrides"] == {(1, "first_name"): "ישראל"}
    button(at, "clr_1_first_name").click().run()
    assert at.session_state["name_overrides"] == {}


def test_confirmation_is_not_applied_to_other_fields_or_pages():
    at = loaded_app(12)
    button(at, "sg_12_first_name_0").click().run()
    assert set(at.session_state["name_overrides"]) == {(12, "first_name")}


def test_missing_field_flag_names_the_actual_field():
    at = loaded_app(10, "מרכזי")                             # עמוד 10: אין מועמד מרכזי ואין ברקוד מרכזי
    text = " ".join(w.value for w in at.warning) + " ".join(m.value for m in at.markdown)
    assert "מרכזי חסר" in text
    assert "שם פרטי ושם משפחה חסרים" not in text


def test_center_cell_shows_candidates_as_buttons_and_clicking_confirms_all_fields():
    at = loaded_app(14, "מרכזי")                                  # עמוד 14: שני מרכזיים (מועמדים), כתום
    keys = [b.key for b in at.button if b.key and b.key.startswith("sg_14_center_")]
    assert keys, "candidates should be buttons"
    button(at, keys[0]).click().run()
    assert not at.exception
    assert at.session_state["name_overrides"][(14, "center")] == at.text_input(key="txt_14_center").value
    assert any("אושר על ידי המשתמש" in s.value for s in at.success)
    button(at, "clr_14_center").click().run()
    assert at.session_state["name_overrides"] == {}


def test_id_typed_value_is_validated_and_saved_and_sender_has_no_crop_but_can_be_typed():
    at = loaded_app(5, 'ת"ז')
    at.text_input(key="txt_5_id").set_value("12ab").run()
    button(at, "ok_5_id").click().run()
    assert at.session_state["name_overrides"] == {} and any("לא תקין" in e.value for e in at.error)
    at.text_input(key="txt_5_id").set_value(" 123 456-789 ").run()
    button(at, "ok_5_id").click().run()
    assert at.session_state["name_overrides"] == {(5, "id"): "123456789"}
    at2 = loaded_app(5, "גורם שולח")
    assert any("אין חיתוך" in c.value for c in at2.caption)
    at2.text_input(key="txt_5_sender").set_value("מכבי").run()
    button(at2, "ok_5_sender").click().run()
    assert at2.session_state["name_overrides"] == {(5, "sender"): "מכבי"}
