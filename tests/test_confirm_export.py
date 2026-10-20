"""אישור שם על ידי המשתמש: ערך שהוקלד או נבחר הוא הערך הסופי, מסומן "אושר על ידי המשתמש" (כחול, לא כתום).
בלי אישור, שם בכתב יד אף פעם לא ירוק על סמך המודל לבדו."""
from openpyxl import load_workbook

from src import export
from src.export import CONFIRMED, ORANGE, build_rows, export_excel
from src.schema import Field_
from test_export import good_page

CONFIRMED_RGB = CONFIRMED.fgColor.rgb[-6:]
ORANGE_RGB = ORANGE.fgColor.rgb[-6:]
GREEN_RGB = export.GREEN.fgColor.rgb[-6:]


def handwritten_page():
    hw = Field_(value="ישראל", confidence=0.99, source="handwritten", label="שם פרטי", alternatives=["ישראל", "ישראלה"])
    return good_page(1, first_name=hw, last_name=Field_(value="ישראלי", confidence=0.99, source="handwritten", label="שם משפחה"))


def save(tmp_path, pages, overrides=None):
    path = tmp_path / "out.xlsx"
    summary = export_excel(pages, path, overrides)
    return load_workbook(path), summary


def test_handwritten_name_is_never_green_without_user_confirmation(tmp_path):
    """שונה ב-20.10.2026: הקריאה מוצגת בתא כהצעה, אבל התא **כתום ולא ירוק** עד שהמשתמשת מאשרת."""
    wb, _ = save(tmp_path, [handwritten_page()])
    first = wb["תוצאות"].cell(row=2, column=1)
    assert first.fill.fgColor.rgb[-6:] == ORANGE_RGB and first.fill.fgColor.rgb[-6:] != GREEN_RGB
    assert first.value == "ישראל"                                    # ההצעה מוצגת, בכתום


def test_confirmed_name_is_exported_as_user_confirmed_not_orange(tmp_path):
    wb, summary = save(tmp_path, [handwritten_page()], {(1, "first_name"): "ישראל", (1, "last_name"): " ישראלי "})
    ws = wb["תוצאות"]
    first, last = ws.cell(row=2, column=1), ws.cell(row=2, column=2)
    assert (first.value, last.value) == ("ישראל", "ישראלי")                 # הערך שהמשתמש אישר, בלי רווחים מיותרים
    for cell in (first, last):
        assert cell.fill.fgColor.rgb[-6:] == CONFIRMED_RGB                # לא כתום ולא ירוק
        assert "אושר על ידי המשתמש" in cell.comment.text
    audit = wb["audit"]
    flags = {audit.cell(row=r, column=3).value: audit.cell(row=r, column=6).value for r in range(2, audit.max_row + 1)}
    assert flags["first_name"] == flags["last_name"] == "confirmed_by_user"
    assert summary["by_field"]["first_name"].get("confirmed") == 1 and summary["totals"]["confirmed"] == 2
    legend = [wb["סיכום"].cell(row=r, column=2).value for r in range(2, 6)]
    assert any("אושר על ידי המשתמש" in (v or "") for v in legend)


def test_confirmed_name_replaces_a_model_value_and_keeps_the_original_in_the_comment(tmp_path):
    page = good_page(1)                                               # שם מודפס ירוק: דנה לוי
    wb, _ = save(tmp_path, [page], {(1, "first_name"): "דני"})
    cell = wb["תוצאות"].cell(row=2, column=1)
    assert cell.value == "דני" and cell.fill.fgColor.rgb[-6:] == CONFIRMED_RGB and "דנה" in cell.comment.text
    assert wb["תוצאות"].cell(row=2, column=2).fill.fgColor.rgb[-6:] == GREEN_RGB    # שם המשפחה לא נגע


def test_blank_input_is_ignored_and_other_fields_can_be_confirmed(tmp_path):
    page = handwritten_page()
    rows = build_rows(page, {(1, "id"): "999", (1, "first_name"): "   "})
    assert rows[0].cells["id"].confirmed is True and rows[0].cells["id"].value == "999"
    assert rows[0].cells["id"].original == "11223344" and rows[0].cells["id"].orange is False
    assert rows[0].cells["first_name"].confirmed is False
    assert rows[0].cells["center"].confirmed is False                 # שדות אחרים לא נגעו


def test_confirmed_non_name_cells_are_blue_in_excel_with_original_in_the_comment(tmp_path):
    page = handwritten_page()
    overrides = {(1, "id"): "999", (1, "center"): "123456 ; 654321", (1, "commitment#0"): "777", (1, "date"): "01.01.2026", (1, "sender"): "מכבי"}
    wb, summary = save(tmp_path, [page], overrides)
    ws = wb["תוצאות"]
    blue = [c for c in ws[2] if c.fill.fgColor.rgb[-6:] == CONFIRMED_RGB]
    assert len(blue) == 5 and all("אושר על ידי המשתמש" in c.comment.text for c in blue)
    assert summary["totals"].get("confirmed", 0) == 5


def test_commitment_confirmation_is_per_row_not_per_page():
    page = good_page(1)
    from src.export import build_rows as br
    base = br(page)
    assert len(base) >= 1
    rows = br(page, {(1, "commitment#0"): "555"})
    assert rows[0].cells["commitment"].value == "555" and rows[0].cells["commitment"].confirmed
    assert all(r.cells["commitment"].confirmed is False for r in rows[1:])
    assert [r.index for r in rows] == list(range(len(rows)))


def test_confirmed_name_is_formula_protected(tmp_path):
    wb, _ = save(tmp_path, [handwritten_page()], {(1, "first_name"): "=HYPERLINK(\"x\")"})
    assert wb["תוצאות"].cell(row=2, column=1).value.startswith("'=")


def test_confirmation_applies_per_page_not_to_other_pages(tmp_path):
    """האישור חל על עמוד 1 בלבד: שם מאושר = כחול, ואותו שם בעמוד 2 נשאר הצעה כתומה."""
    wb, _ = save(tmp_path, [handwritten_page(), {**handwritten_page(), "page": 2}], {(1, "first_name"): "ישראל"})
    ws = wb["תוצאות"]
    confirmed, suggested = ws.cell(row=2, column=1), ws.cell(row=3, column=1)
    assert confirmed.value == "ישראל" and confirmed.fill.fgColor.rgb[-6:] == CONFIRMED_RGB
    assert suggested.value == "ישראל" and suggested.fill.fgColor.rgb[-6:] == ORANGE_RGB



def test_two_agreeing_handwritten_readings_are_shown_yellow_never_green():
    """הדגל היחיד הוא handwritten (שתי קריאות עצמאיות מסכימות): הערך בתא, צהוב (לא כתום ולא ירוק)."""
    from src.schema import RegionsExtraction
    hw = Field_(value="ישראל", confidence=0.99, source="handwritten", label="שם פרטי")
    page = good_page(1, first_name=hw)
    page["pass2"] = {"ok": True, "model": "m", **RegionsExtraction.model_validate({"patient": {
        "region_ok": True, "labels_seen": ["first_name", "last_name"], "first_name": hw.model_dump()}}).model_dump()}
    first = build_rows(page)[0].cells["first_name"]
    assert first.value == "ישראל" and first.flags == ["handwritten"] and first.yellow and not first.orange


def test_printed_clean_name_stays_green_and_single_handwritten_reading_gets_no_suggestion():
    assert build_rows(good_page(1))[0].cells["first_name"].value == "דנה"
    single = good_page(1, first_name=Field_(value="ישראל", confidence=0.99, source="handwritten", label="שם פרטי"))
    single["pass2"] = None
    c = build_rows(single)[0].cells["first_name"]
    assert not c.value and c.orange and c.alternatives == []                # handwritten_unconfirmed: בלי הצעה


import pytest  # noqa: E402


@pytest.mark.parametrize("flags", [["region_not_ok"], ["father_name"], ["name_label_unknown"], ["name_label_missing"],
                                   ["handwritten", "region_not_ok"]])
def test_value_with_a_structural_flag_is_hidden_and_suggested_only_if_two_readings_agree(flags):
    from src.rules import H_TWO_READS
    single = export.display_name_cell(export.Cell("יונתן", "יונתן", flags, alternatives=["יוני"]))
    assert single.value is None and single.raw is None and single.shown == "" and single.orange
    assert single.alternatives == [] and single.flags == flags                  # קריאה בודדת: רעש, בלי הצעות
    agreed = export.display_name_cell(export.Cell("יונתן", "יונתן", flags, [H_TWO_READS], alternatives=["יוני"]))
    assert agreed.value is None and agreed.alternatives == ["יונתן", "יוני"]    # שתי קריאות מסכימות: ההצעות נשארות


def test_unreadable_name_cell_has_no_suggestions_and_says_to_type(tmp_path):
    """ריק, כתום, בלי הצעות: הערה "לא נקרא, יש להקליד"; גם alternatives של שם האב / שמות לא מוכרים לא מוצגים."""
    cell = export.display_name_cell(export.Cell(None, None, ["handwritten_unconfirmed"], alternatives=["רפאל-ושוב"]))
    assert cell.alternatives == [] and cell.orange and cell.shown == ""
    from src.confirm import name_suggestions
    assert name_suggestions(cell) == []


@pytest.mark.parametrize("flags", [["handwritten_unconfirmed"], ["conflict"], ["handwritten", "conflict"],
                                   ["handwritten", "low_confidence"], ["low_confidence"]])
def test_value_with_a_reading_flag_is_shown_in_orange(flags):
    """שונה ב-20.10.2026: ערך שנושא רק דגלי קריאה (כתב יד, סתירה, ביטחון) מוצג בתא ככתום, עם הקריאה
    האחרת כהצעה. לעולם לא ירוק."""
    cell = export.display_name_cell(export.Cell("יונתן", "יונתן", flags, alternatives=["יוני"]))
    assert cell.value == "יונתן" and cell.shown == "יונתן" and cell.orange and not cell.yellow
    assert cell.alternatives == ["יוני"]


def test_display_rule_keeps_handwritten_only_with_two_readings_and_unflagged_values():
    from src.rules import H_TWO_READS
    agreed = export.display_name_cell(export.Cell("ישראל", "ישראל", ["handwritten"], [H_TWO_READS]))
    assert agreed.value == "ישראל" and agreed.yellow and not agreed.orange            # שתי קריאות: צהוב
    single = export.display_name_cell(export.Cell("ישראל", "ישראל", ["handwritten"]))
    assert single.value == "ישראל" and single.orange and not single.yellow            # קריאה אחת: כתום עם ערך
    assert export.display_name_cell(export.Cell("דנה", "דנה", [])).value == "דנה"
    assert export.display_name_cell(export.Cell(None, None, ["missing_required_field"])).value is None
