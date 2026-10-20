"""scripts/eval_extra.py: טבלת האמת של סט ההערכה הנוסף.
שורה לכל התחייבות (כמה שורות עם אותו מספר עמוד מקובצות), מרכזי מרובה בתא אחד מופרד ב-";".
בלי שום קריאה למודל: התוצאות נקראות מקובצי p<N>.json בתיקייה זמנית."""
import json

import pytest

from scripts.eval_extra import (ALL_FIELDS, categories, cells, commitment_cells, load_truth_csv, row_disagreements,
                                truth_filled)
from src.schema import DateCandidate, Field_, NumberCandidate, PageExtraction, SenderMention

HEADER = "page,first_name,last_name,id,center,receipt_date,sender,commitment\n"
EMPTY_ROWS = "".join(f"{p},,,,,,,\n" for p in range(2, 7))


def write_truth(tmp_path, *rows: str):
    path = tmp_path / "truth.csv"
    path.write_text(HEADER + "".join(rows), encoding="utf-8")
    return path


def page_result(centers=("944963",), commitments=("107646",), first="ישראל", last="ישראלי", id_value="11223344",
                date="18.06.2026", sender="כללית"):
    """תוצאת מעבר ראשון סינתטית: כל השדות מודפסים ומתויגים, כדי שהכללים יחזירו ערך בלי דגלים."""
    numbers = [NumberCandidate(value=v, label="מרכזי", confidence=0.95, source="printed") for v in centers]
    numbers += [NumberCandidate(value=v, label="התחייבות", confidence=0.95, source="printed") for v in commitments]
    page = PageExtraction(
        is_commitment_form=True, page_quality="ok", rotation_degrees="0", numbers=numbers,
        id_numbers=[NumberCandidate(value=id_value, label='ת.ז', confidence=0.95, source="printed")],
        dates=[DateCandidate(value=date, kind="lab_stamp", confidence=0.95, source="printed", evidence="חותמת התקבל")],
        first_name=Field_(value=first, confidence=0.95, source="printed", label="שם פרטי"),
        last_name=Field_(value=last, confidence=0.95, source="printed", label="שם משפחה"),
        sender_mentions=[SenderMention(text=sender, where="header", role="sender", confidence=0.9, evidence="לוגו")],
    )
    return {"ok": True, "model": "fake", **page.model_dump()}


def save_page(out_dir, page: int, result: dict):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"p{page}.json").write_text(
        json.dumps({"page": page, "pass1": result, "pass2": None, "second_pass": "skipped", "barcodes": None},
                   ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """תיקיית ריצה זמנית, כך שהבדיקה לא נוגעת ב-outputs/eval_extra."""
    out = tmp_path / "run"
    monkeypatch.setattr("scripts.eval_extra.OUT", out)
    return out


# ---- טבלת האמת: שורה לכל התחייבות ----

def test_two_rows_for_one_page_are_grouped(tmp_path):
    """שתי התחייבויות = שתי שורות עם אותו מספר עמוד: השנייה לא דורסת את הראשונה."""
    truth = load_truth_csv(write_truth(tmp_path,
                                       "1,ישראל,ישראלי,11223344,944963,18.06.2026,כללית,107646\n",
                                       "1,ישראל,ישראלי,11223344,944963,18.06.2026,כללית,107647\n",
                                       EMPTY_ROWS))
    assert len(truth[1]) == 2
    assert [r["commitment"] for r in truth[1]] == ["107646", "107647"]
    for r in truth[1]:                              # פרטי המטופל חוזרים בשתי השורות
        assert (r["id"], r["first_name"], r["center"], r["date"], r["sender"]) == \
               ("11223344", "ישראל", "944963", "18.06.2026", "כללית")
    assert sorted(truth) == [1, 2, 3, 4, 5, 6]
    assert truth_filled(truth[1]) and not truth_filled(truth[2])


def test_multi_commitment_cell_also_expands(tmp_path):
    """תא התחייבות עם ";" נסבל גם הוא ומתפצל לשורה לכל התחייבות."""
    truth = load_truth_csv(write_truth(tmp_path, "1,א,ב,11223344,944963,18.06.2026,כללית,107646 ; 107647\n", EMPTY_ROWS))
    assert [r["commitment"] for r in truth[1]] == ["107646", "107647"]


def test_row_disagreement_is_reported(tmp_path):
    """שדה שאמור לחזור זהה ונכתב שונה בין השורות: אזהרה (ההשוואה לוקחת את השורה הראשונה)."""
    truth = load_truth_csv(write_truth(tmp_path,
                                       "1,ישראל,ישראלי,11223344,944963,18.06.2026,כללית,107646\n",
                                       "1,ישראל,ישראלי,99999999,944963,18.06.2026,מכבי,107647\n",
                                       EMPTY_ROWS))
    assert row_disagreements(truth[1]) == ["sender", "id"]
    assert row_disagreements(load_truth_csv(write_truth(tmp_path, "1,א,ב,1,2,18.06.2026,כללית,7\n", EMPTY_ROWS))[1]) == []


# ---- מרכזי: כמה ערכים בתא אחד ----

def test_two_centers_in_one_cell_match_both_values(tmp_path, run_dir):
    """תא מרכזי "944963 ; 944964" מתפצל, ושני המספרים שנקראו מתאימים לו בדיוק."""
    truth = load_truth_csv(write_truth(tmp_path, "1,ישראל,ישראלי,11223344,944963 ; 944964,18.06.2026,כללית,107646\n",
                                       EMPTY_ROWS))
    save_page(run_dir, 1, page_result(centers=("944963", "944964")))
    c = cells(truth, [1])[1]["center"]
    assert c["category"] == "confident_ok"
    assert c["truth"] == "944963 ; 944964"
    assert c["pred"] == "944963 ; 944964"


def test_two_centers_but_only_one_read_is_wrong(tmp_path, run_dir):
    truth = load_truth_csv(write_truth(tmp_path, "1,ישראל,ישראלי,11223344,944963 ; 944964,18.06.2026,כללית,107646\n",
                                       EMPTY_ROWS))
    save_page(run_dir, 1, page_result(centers=("944963",)))
    c = cells(truth, [1])[1]["center"]
    assert c["category"] == "confident_wrong"
    assert c["pred"] == "944963"


def test_center_order_in_the_cell_does_not_matter(tmp_path, run_dir):
    truth = load_truth_csv(write_truth(tmp_path, "1,ישראל,ישראלי,11223344,944964 ; 944963,18.06.2026,כללית,107646\n",
                                       EMPTY_ROWS))
    save_page(run_dir, 1, page_result(centers=("944963", "944964")))
    assert cells(truth, [1])[1]["center"]["category"] == "confident_ok"


# ---- התחייבות: תא לכל שורה ----

def pred_rows(*items: tuple[str | None, list[str]]):
    return [{"commitment": v, "commitment_flags": flags} for v, flags in items]


def test_each_commitment_row_is_compared_separately(tmp_path):
    truth = load_truth_csv(write_truth(tmp_path, "1,א,ב,1,2,18.06.2026,כללית,107646\n",
                                       "1,א,ב,1,2,18.06.2026,כללית,107647\n", EMPTY_ROWS))
    out = commitment_cells(truth[1], pred_rows(("107646", []), ("107647", ["commitment_single_source"])))
    assert [c["category"] for c in out] == ["confident_ok", "orange_ok"]


def test_missing_second_commitment_is_counted_once(tmp_path):
    """המערכת הפיקה רק אחת משתי ההתחייבויות: אחת exact, השנייה ריקה ומסומנת."""
    truth = load_truth_csv(write_truth(tmp_path, "1,א,ב,1,2,18.06.2026,כללית,107646\n",
                                       "1,א,ב,1,2,18.06.2026,כללית,107647\n", EMPTY_ROWS))
    out = commitment_cells(truth[1], pred_rows(("107646", []), (None, ["missing_required_field"])))
    assert [(c["truth"], c["pred"], c["category"]) for c in out] == \
           [("107646", "107646", "confident_ok"), ("107647", "", "empty_flagged")]


def test_wrong_commitment_without_flag_is_wrong_green(tmp_path):
    truth = load_truth_csv(write_truth(tmp_path, "1,א,ב,1,2,18.06.2026,כללית,107646\n", EMPTY_ROWS))
    out = commitment_cells(truth[1], pred_rows(("999999", [])))
    assert [(c["truth"], c["pred"], c["category"]) for c in out] == [("107646", "999999", "confident_wrong")]


def test_extra_row_the_system_invented_is_wrong(tmp_path):
    truth = load_truth_csv(write_truth(tmp_path, "1,א,ב,1,2,18.06.2026,כללית,107646\n", EMPTY_ROWS))
    out = commitment_cells(truth[1], pred_rows(("107646", []), ("999999", [])))
    assert [c["category"] for c in out] == ["confident_ok", "confident_wrong"]


def test_no_commitment_in_truth_and_none_found_is_one_empty_cell(tmp_path):
    truth = load_truth_csv(write_truth(tmp_path, "1,א,ב,1,2,18.06.2026,כללית,\n", EMPTY_ROWS))
    out = commitment_cells(truth[1], pred_rows((None, ["no_commitment"])))
    assert [c["category"] for c in out] == ["empty_ok"]          # no_commitment לבדו אינו דגל לבדיקה


def test_commitment_counted_per_row_other_fields_per_page(tmp_path, run_dir):
    """עמוד עם שתי התחייבויות: n=2 להתחייבות, n=1 לשאר השדות (אותם פרטי מטופל בשתי השורות)."""
    truth = load_truth_csv(write_truth(tmp_path, "1,ישראל,ישראלי,11223344,944963,18.06.2026,כללית,107646\n",
                                       "1,ישראל,ישראלי,11223344,944963,18.06.2026,כללית,107647\n", EMPTY_ROWS))
    save_page(run_dir, 1, page_result(commitments=("107646", "107647")))
    cmp = cells(truth, [1])
    assert sum(categories(cmp, "commitment", [1]).values()) == 2
    for f in ALL_FIELDS:
        if f != "commitment":
            assert sum(categories(cmp, f, [1]).values()) == 1
    assert categories(cmp, "commitment", [1])["confident_ok"] + \
           categories(cmp, "commitment", [1])["orange_ok"] == 2
