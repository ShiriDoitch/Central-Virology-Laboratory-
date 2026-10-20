"""הכלל הראשי של הפרויקט (CLAUDE.md סעיף 9): **שגיאה שלא סומנה = 0**, בכל שדה.
עד כה הוא נבדק רק למרכזי (test_center_barcode) ולגורם שולח (test_sample_run); הבדיקה הזאת מכסה את כל שבעת
השדות בשתי הריצות השמורות של חלק 1, פעמיים: כפי שנשמרו, ועם apply_field_validity מחושב מחדש (כלל התוויות
שבקוד **עכשיו**, כי field_ok נכתב לתוך p<N>.json בזמן הריצה וריצה שמורה "קופאת" על הכלל שהיה אז).
בלי קריאות API. מדלגת כשאין ריצות שמורות (outputs/ אינו ב-git)."""
from pathlib import Path

import pytest

from src.assemble import page_rows
from src.evaluate import OVERALL_FIELDS, SEPARATE_FIELDS, compare_page, load_barcodes, load_run, load_truth
from src.rules import apply_field_validity

RUNS = {"v4b": Path("outputs/clean_part1_v4b"), "claude": Path("outputs/clean_part1_claude")}
FIELDS = OVERALL_FIELDS + SEPARATE_FIELDS
pytestmark = pytest.mark.skipif(not Path("data/truth_part1.xlsx").exists(), reason="needs the truth table")


def wrong_greens(run_dir: Path, recompute: bool) -> list[tuple]:
    truth = load_truth()
    pages = sorted(truth)
    results, regions = load_run(run_dir, pages)
    barcodes = load_barcodes(run_dir, pages)
    out = []
    for p in pages:
        if not results[p].get("ok"):
            continue
        r2 = regions.get(p)
        if recompute and r2 and r2.get("ok") and "patient" in r2:
            r2 = apply_field_validity(r2)
        cmp = compare_page(truth[p], page_rows(results[p], regions=r2, barcodes=barcodes.get(p)))
        out += [(p, f, cmp[f].get("truth"), cmp[f].get("pred")) for f in FIELDS
                if cmp[f]["category"] == "confident_wrong"]
    return out


@pytest.mark.parametrize("run", list(RUNS))
@pytest.mark.parametrize("recompute", [False, True])
def test_no_unflagged_error_in_any_field(run, recompute):
    if not (RUNS[run] / "p1.json").exists():
        pytest.skip("needs the saved run")
    assert wrong_greens(RUNS[run], recompute) == []


@pytest.mark.parametrize("run", list(RUNS))
def test_names_are_never_green(run):
    """שם לעולם אינו ירוק בלי אישור המשתמשת (CLAUDE.md סעיפים 16/17): confident_ok של שמות הוא 0."""
    if not (RUNS[run] / "p1.json").exists():
        pytest.skip("needs the saved run")
    truth = load_truth()
    pages = sorted(truth)
    results, regions = load_run(RUNS[run], pages)
    barcodes = load_barcodes(RUNS[run], pages)
    greens = []
    for p in pages:
        if not results[p].get("ok"):
            continue
        r2 = regions.get(p)
        if r2 and r2.get("ok") and "patient" in r2:
            r2 = apply_field_validity(r2)
        cmp = compare_page(truth[p], page_rows(results[p], regions=r2, barcodes=barcodes.get(p)))
        greens += [(p, f) for f in ("first_name", "last_name")
                   if cmp[f]["category"] in ("confident_ok", "confident_wrong")]
    assert greens == []
