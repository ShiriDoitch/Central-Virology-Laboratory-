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


def test_unconfirmed_name_cells_show_only_handwritten_only_agreed_values():
    shown = {}
    for p, res in pages().items():
        for r in build_rows(res):
            for k in ("first_name", "last_name"):
                c = r.cells[k]
                if c.value:
                    assert c.flags == ["handwritten"] and c.yellow and not c.orange, (p, k, c.value, c.flags)   # צהוב, לעולם לא ירוק
                    shown[(p, k)] = c.value
                else:
                    assert not c.raw and not c.shown, (p, k)
    assert shown == {(12, "first_name"): "ישראל"}                                    # עמוד 26 (יונתן / פייר) ריק


def test_page_19_names_are_empty_and_orange_with_no_cohen():
    for r in build_rows(pages()[19]):
        for k in ("first_name", "last_name"):
            assert not r.cells[k].shown and r.cells[k].orange
            assert "כהן" not in r.cells[k].alternatives


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
    assert c["confident_ok"] == 21 and c["orange_ok"] == 2 and c["confident_wrong"] == 0     # היה 16 / 7: חמשת patient_field_only


def test_name_suggestions_appear_only_where_two_independent_readings_agree():
    """רעש מכתב יד לא קריא (למשל "רפאל-ושוב" בעמוד 3) אינו מוצג כהצעה: ריק, כתום, "לא נקרא, יש להקליד"."""
    from src.confirm import name_suggestions
    suggested = {}
    for p, res in pages().items():
        for r in build_rows(res):
            for k in ("first_name", "last_name"):
                if name_suggestions(r.cells[k]):
                    suggested[(p, k)] = name_suggestions(r.cells[k])
    assert suggested == {(12, "first_name"): ["ישראל"]}
    page3 = build_rows(pages()[3])[0].cells["last_name"]
    assert page3.shown == "" and page3.orange and page3.alternatives == []


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
