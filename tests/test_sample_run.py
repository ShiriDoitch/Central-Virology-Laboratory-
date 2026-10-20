"""הריצה השמורה שהאפליקציה טוענת (outputs/clean_part1_v4b): מה שהמסך והאקסל מציגים מול דוח ההערכה ומול הכללים."""
import json
from collections import Counter
from pathlib import Path

import pytest

from src.assemble import page_rows
from src.evaluate import compare_page, evaluate, load_run, load_truth, render
from src.export import FIELD_KEYS, build_rows

RUN = Path("outputs/clean_part1_v4b")
pytestmark = pytest.mark.skipif(not RUN.exists() or not Path("data/truth_part1.xlsx").exists(), reason="needs the saved run")


def pages():
    return {p: json.loads((RUN / f"p{p}.json").read_text(encoding="utf-8")) for p in range(1, 27)}


def test_app_sample_dir_is_the_v4b_reference_run():
    import re
    assert re.search(r'SAMPLE_DIR = Path\("outputs/clean_part1_v4b"\)', open("app.py", encoding="utf-8").read())


def test_page_25_has_three_rows_with_center_948062_in_orange():
    rows = build_rows(pages()[25])
    assert len(rows) == 3
    for r in rows:
        assert r.cells["center"].value == "948062" and r.cells["center"].orange


def test_unconfirmed_name_cells_are_never_green():
    """שונה ב-20.10.2026: קריאת שם מוצגת בתא כהצעה. שם לא מאושר הוא **תמיד** צהוב (שתי קריאות מסכימות)
    או כתום, ולעולם לא ירוק; תא ריק הוא תמיד כתום."""
    yellow = {}
    for p, res in pages().items():
        for r in build_rows(res):
            for k in ("first_name", "last_name"):
                c = r.cells[k]
                assert c.flags, (p, k, c.value)                     # אף שם אינו ירוק בלי אישור
                assert c.yellow or c.orange, (p, k, c.value)
                if c.yellow:
                    yellow[(p, k)] = c.value
    assert yellow == {(12, "first_name"): "ישראל"}                  # צהוב רק כששתי קריאות עצמאיות מסכימות


def test_page_19_names_are_orange_suggestions_not_green():
    """עמוד 19: הקריאה בכתב יד אינה אמינה ("רמי.רמי."), ולכן היא מוצגת ככתום בלבד - הצעה שממתינה לאישור."""
    for r in build_rows(pages()[19]):
        for k in ("first_name", "last_name"):
            c = r.cells[k]
            assert c.orange and not c.yellow, (k, c.value)
            assert "כהן" not in c.alternatives


def test_non_name_columns_match_the_evaluation_decisions():
    for p, res in pages().items():
        shown = build_rows(res)
        decided = page_rows(res["pass1"], regions=res["pass2"] if (res.get("pass2") or {}).get("ok") else None,
                           barcodes=res.get("barcodes"))
        assert len(shown) == len(decided)
        for er, row in zip(shown, decided):
            for k in ("id", "center", "date", "sender"):
                assert er.cells[k].value == row[k].value and bool(er.cells[k].flags) == row[k].uncertain, (p, k)
            assert er.cells["commitment"].value == row["commitment"] and bool(er.cells["commitment"].flags) == bool(row["commitment_flags"])


def test_evaluation_report_for_the_run_is_the_saved_one():
    saved = (RUN / "eval_report.md").read_text(encoding="utf-8")
    assert render(evaluate(run_dir=RUN)) == saved


def test_sender_patient_field_only_is_now_green_in_the_evaluation():
    c = evaluate(run_dir=RUN)["counts"]["sender"]
    # היה 16 / 7 לפני כלל patient_field_only. orange_ok עלה מ-2 ל-3 ב-20.10.2026: עמוד 8 היה נשמט בשקט
    # (המודל סימן "לא טופס") ועכשיו נכנס כשורה כתומה עם הגורם השולח הנכון (not_recognized_as_form).
    assert c["confident_ok"] == 21 and c["orange_ok"] == 3 and c["confident_wrong"] == 0
    assert c["empty_missed"] == 0                                # שגיאה בלי סימון: אין


def test_name_suggestions_follow_the_shown_value():
    """שונה ב-20.10.2026: כל תא שם שמוצג בו ערך מציע אותו (ואת הקריאה האחרת) כלחצן לאישור.
    תא שלא נקרא כלל נשאר בלי הצעות: "לא נקרא, יש להקליד"."""
    from src.confirm import name_suggestions
    for p, res in pages().items():
        for r in build_rows(res):
            for k in ("first_name", "last_name"):
                c = r.cells[k]
                if c.value:
                    assert name_suggestions(c)[0] == c.value, (p, k)
                elif not c.alternatives:
                    assert name_suggestions(c) == [], (p, k)
    page3 = build_rows(pages()[3])[0].cells["last_name"]
    assert page3.shown == "" and page3.orange and page3.alternatives == []    # קריאה שנפסלה: בלי הצעה


def test_center_filters_on_the_saved_run_page_3_is_clean_and_page_14_keeps_both_centers():
    from src.rules import decide_center
    from src.schema import PageExtraction

    def center(p):
        d = pages()[p]
        r2 = d["pass2"] if d.get("pass2") and d["pass2"].get("ok") else None
        return decide_center(PageExtraction.model_validate(d["pass1"]).numbers, r2)

    p3 = center(3)
    assert p3.value == "939273" and p3.flags == ["no_center_label"] and p3.alternatives == []   # בלי 113001 (מבטח) ובלי 074934 (שעה)
    assert center(14).value == "944963 ; 944964"


def test_claude_run_page_3_shows_its_own_reading_in_orange_never_green():
    import json as _json
    from src.rules import decide_center
    from src.schema import PageExtraction
    d = _json.loads(Path("outputs/clean_part1_claude/p3.json").read_text(encoding="utf-8"))
    x = decide_center(PageExtraction.model_validate(d["pass1"]).numbers, None)
    assert x.value == "939973" and "no_center_label" in x.flags           # קריאת Claude (שגויה): כתומה, לא ירוקה
