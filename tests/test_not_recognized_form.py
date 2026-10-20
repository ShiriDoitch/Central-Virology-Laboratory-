"""עמוד לא נשמט בשקט (20.10.2026, מהממצא על עמוד 2 בסט eval_extra):
- המודל סימן is_commitment_form=false אבל יש סימני טופס (חותמת קבלה / ת"ז / שם) -> שורה אחת, כל השדות כתומים,
  עם הדגל not_recognized_as_form, כך שהעמוד נכנס לתור העבודה.
- עמוד שבאמת אינו טופס (בלי סימנים) ממשיך להידלג, ומופיע ברשימת העמודים שדולגו גם במסך הרשומות.
- עמוד מסובב ששתי הקריאות שלו חלוקות: "טופס" באחד הכיוונים מספיק (src/pipeline.py).
בלי קריאות API: הכול מתשובות שמורות ומנתונים בנויים."""
import json
from pathlib import Path

import pytest

import records_screen
from src.assemble import page_rows
from src.export import FIELD_KEYS, build_rows, skip_reason
from src.rules import F_MISSING_REQUIRED, F_NOT_RECOGNIZED_AS_FORM, has_form_signals
from src.schema import DateCandidate, Field_, NumberCandidate, PageExtraction

EVAL_P2 = Path("outputs/eval_extra/p2.json")


def page(is_form=False, dates=(), ids=(), first=None, last=None, numbers=()):
    p = PageExtraction(
        is_commitment_form=is_form, page_quality="ok",
        dates=[DateCandidate(value=v, kind=k, evidence=e, confidence=0.9, source=s) for v, k, e, s in dates],
        id_numbers=[NumberCandidate(value=v, label='ת.ז', confidence=0.9, source="handwritten") for v in ids],
        numbers=[NumberCandidate(value=v, label=lbl, confidence=0.9, source="printed") for v, lbl in numbers],
        first_name=Field_(value=first, confidence=0.9, source="handwritten") if first else Field_(),
        last_name=Field_(value=last, confidence=0.9, source="handwritten") if last else Field_(),
    )
    return {"ok": True, "model": "m", **p.model_dump()}


STAMP = ("24.08.2026", "lab_stamp", "התקבל 24-08-2026", "printed")


# ---------- סימני טופס ----------

def test_receipt_stamp_is_a_form_signal():
    assert has_form_signals(PageExtraction.model_validate(page(dates=[STAMP])))


def test_id_number_is_a_form_signal():
    assert has_form_signals(PageExtraction.model_validate(page(ids=["11223344"])))


def test_patient_name_is_a_form_signal():
    assert has_form_signals(PageExtraction.model_validate(page(first="מאור")))
    assert has_form_signals(PageExtraction.model_validate(page(last="אזולאי")))


def test_page_without_any_signal_is_not_a_form():
    assert not has_form_signals(PageExtraction.model_validate(page(numbers=[("050-8101585", "טל")])))
    assert not has_form_signals(PageExtraction.model_validate(
        page(dates=[("23.08.2026", "sample_date", "23/08/2026 08:55", "printed")])))


# ---------- שורה כתומה במקום השמטה ----------

def test_not_a_form_with_signals_produces_one_orange_row():
    rows = page_rows(page(dates=[STAMP], ids=["11223344"], first="מאור", last="אזולאי"))
    assert len(rows) == 1
    row = rows[0]
    for key in ("first_name", "last_name", "id", "center", "date", "sender"):
        assert F_NOT_RECOGNIZED_AS_FORM in row[key].flags, key
        assert row[key].uncertain, key                       # כל שדה כתום
    assert F_NOT_RECOGNIZED_AS_FORM in row["commitment_flags"]
    assert F_MISSING_REQUIRED in row["commitment_flags"]


def test_not_a_form_without_signals_is_still_skipped():
    assert page_rows(page(numbers=[("050-8101585", "טל")])) == []


def test_a_real_form_is_untouched():
    rows = page_rows(page(is_form=True, ids=["11223344"], numbers=[("107646", "התחייבות")]))
    assert len(rows) == 1
    assert F_NOT_RECOGNIZED_AS_FORM not in rows[0]["id"].flags
    assert rows[0]["commitment"] == "107646"


def test_orange_row_reaches_the_export_and_the_work_queue():
    """השורה נכנסת ל-build_rows (ומשם ל-DB ולטבלה), ו-skip_reason כבר לא מדלג עליה."""
    result = {"page": 2, "pass1": page(dates=[STAMP], ids=["11223344"], first="מאור")}
    rows = build_rows(result)
    assert len(rows) == 1
    assert skip_reason(result) is None                        # לא "דולג"
    assert all(rows[0].cells[k].orange or not rows[0].cells[k].value for k in FIELD_KEYS)


def test_truly_not_a_form_is_reported_as_skipped():
    result = {"page": 9, "pass1": page(numbers=[("050-8101585", "טל")])}
    assert build_rows(result) == []
    assert skip_reason(result) == "המודל סימן: לא טופס התחייבות (ולא נמצא מספר התחייבות)"
    assert records_screen.skipped_pages([result]) == [(9, skip_reason(result))]


def test_skipped_list_is_empty_for_a_normal_page():
    assert records_screen.skipped_pages([{"page": 1, "pass1": page(is_form=True, ids=["11223344"])}]) == []


# ---------- המקרה האמיתי: עמוד 2 של eval_extra ----------

@pytest.mark.skipif(not EVAL_P2.exists(), reason="needs the saved eval_extra run")
def test_cached_eval_extra_page2_is_no_longer_dropped():
    """התשובה השמורה של עמוד 2: is_commitment_form=false, בלי מספר התחייבות, אבל עם חותמת "התקבל", ת"ז ושם."""
    result = json.loads(EVAL_P2.read_text(encoding="utf-8"))
    p1 = result["pass1"]
    assert p1["is_commitment_form"] is False and p1["retried"] is True
    assert has_form_signals(PageExtraction.model_validate(p1))
    rows = page_rows(p1, regions=result.get("pass2"), barcodes=result.get("barcodes"))
    assert len(rows) == 1
    assert F_NOT_RECOGNIZED_AS_FORM in rows[0]["id"].flags
    assert rows[0]["id"].uncertain and rows[0]["date"].uncertain
    assert skip_reason({"page": 2, "pass1": p1}) is None
