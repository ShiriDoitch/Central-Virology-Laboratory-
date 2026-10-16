"""קורא שני מקומי למרכזי: ברקוד Code128 בן 6 ספרות (src/barcode.py + rules.apply_center_barcode). כללים כלליים, ערכים סינתטיים."""
import json
from pathlib import Path

import numpy as np
import pymupdf
import pytest
import zxingcpp

from src.barcode import center_barcode_values, decode_pdf_page
from src.rules import Decision, apply_center_barcode, decide_center
from src.schema import NumberCandidate

BC = lambda *texts, fmt="Code128": [{"format": fmt, "text": t} for t in texts]


def make_pdf(path: Path, texts: list[tuple[str, "zxingcpp.BarcodeFormat"]]) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, (text, fmt) in enumerate(texts):
        bc = zxingcpp.write_barcode(fmt, text, width=320, height=80)
        arr = np.array(bc)
        pix = pymupdf.Pixmap(pymupdf.csGRAY, arr.shape[1], arr.shape[0], arr.tobytes(), False)
        page.insert_image(pymupdf.Rect(60, 60 + i * 120, 300, 60 + i * 120 + 70), pixmap=pix)
    doc.save(str(path))


# ---------- פענוח ----------

def test_decoder_reads_generated_code128_and_filters_center_values(tmp_path):
    pdf = tmp_path / "bc.pdf"
    make_pdf(pdf, [("123456", zxingcpp.BarcodeFormat.Code128), ("1234567", zxingcpp.BarcodeFormat.Code128),
                   ("654321", zxingcpp.BarcodeFormat.Code39)])
    found = decode_pdf_page(str(pdf), 1)
    assert {b["text"] for b in found} >= {"123456", "1234567", "654321"}
    assert center_barcode_values(found) == ["123456", "1234567"]      # Code128 ספרות בלבד באורך הטווח (5 עד 9)


def test_decoder_failure_returns_none_not_exception(tmp_path):
    assert decode_pdf_page(str(tmp_path / "missing.pdf"), 1) is None


def test_decoder_blank_page_returns_empty_list(tmp_path):
    pdf = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(pdf))
    assert decode_pdf_page(str(pdf), 1) == []


def test_center_values_ignore_non_digits_other_formats_and_duplicates():
    found = BC("123456", "123456", "12345a", "1234", "1234567890") + BC("777777", fmt="Code39")
    assert center_barcode_values(found) == ["123456"]
    assert center_barcode_values(None) == [] and center_barcode_values([]) == []


# ---------- כללי ההחלטה ----------

def test_a_model_equals_barcode_set_becomes_green_without_flags():
    d = Decision(value="111111 ; 222222", raw="111111 ; 222222", flags=["low_confidence"], alternatives=["111111", "222222"])
    out = apply_center_barcode(d, BC("222222", "111111"))
    assert out.value == "111111 ; 222222" and out.flags == [] and out.alternatives == []
    assert "center_barcode_agrees" in out.hints


def test_a_multi_value_with_center_mismatch_is_not_cleared_by_the_barcode():
    """center_mismatch = כמה מספרים בלי תווית מתחרים על התפקיד; הברקוד מאשר קריאה בלבד (ראו רגרסיה חלק 2 עמוד 5)."""
    d = Decision(value="111111 ; 222222", raw="111111 ; 222222", flags=["center_mismatch"], alternatives=["111111", "222222"])
    out = apply_center_barcode(d, BC("222222", "111111"))
    assert out.flags == ["center_mismatch"] and "center_barcode_agrees" not in out.hints


def test_a_requires_equality_not_containment():
    d = Decision(value="111111", raw="111111", flags=["no_center_label"])
    out = apply_center_barcode(d, BC("111111", "222222"))       # המודל קרא רק אחד מתוך שניים
    assert out.value == "111111" and out.flags == ["no_center_label"]
    assert not any(h == "center_barcode_agrees" for h in out.hints)
    assert out.hints == ["center_barcode_differs:111111 ; 222222"]


def test_b_empty_model_takes_barcode_values_orange():
    d = Decision(flags=["region_not_ok"])
    out = apply_center_barcode(d, BC("111111", "222222"))
    assert out.value == "111111 ; 222222" and out.raw == out.value
    assert out.flags == ["region_not_ok", "center_from_barcode_only"]


def test_c_different_values_keep_current_decision():
    d = Decision(value="333333", raw="333333", flags=["low_confidence"])
    out = apply_center_barcode(d, BC("111111"))
    assert out.value == "333333" and out.flags == ["low_confidence"] and out.alternatives == d.alternatives


def test_d_no_barcode_changes_nothing():
    d = Decision(value="333333", raw="333333", flags=["low_confidence"])
    for bcs in (None, [], BC("1234"), BC("111111", fmt="Code39")):
        assert apply_center_barcode(d, bcs) == d


def test_decide_center_end_to_end_green_when_model_and_barcode_agree():
    numbers = [NumberCandidate(value="123456", label=None, confidence=0.9)]      # מספר בלי תווית: כתום ללא ברקוד
    assert decide_center(numbers, None).flags == ["no_center_label"]
    out = decide_center(numbers, None, BC("123456"))
    assert out.value == "123456" and out.flags == []


# ---------- דוגמה שמורה ----------

RUNS = {"v4b": Path("outputs/clean_part1_v4b"), "claude": Path("outputs/clean_part1_claude")}


@pytest.mark.skipif(not (RUNS["v4b"] / "p1.json").exists(), reason="needs the saved sample run")
def test_saved_run_with_barcodes_never_creates_a_wrong_green_center():
    from src.assemble import page_rows
    from src.evaluate import compare_page, load_barcodes, load_run, load_truth
    truth = load_truth()
    pages = sorted(truth)
    for name, run in RUNS.items():
        if not (run / "p1.json").exists():
            continue
        results, regions = load_run(run, pages)
        barcodes = load_barcodes(run, pages)
        assert any(barcodes.values()), "run was not backfilled with barcodes"
        for p in pages:
            if results[p].get("ok"):
                cat = compare_page(truth[p], page_rows(results[p], regions=regions.get(p), barcodes=barcodes.get(p)))["center"]["category"]
                assert cat != "confident_wrong", (name, p)


@pytest.mark.skipif(not (RUNS["v4b"] / "p9.json").exists(), reason="needs the saved sample run")
def test_saved_page_with_empty_model_center_gets_barcode_values_in_orange():
    from src.export import build_rows
    res = json.loads((RUNS["v4b"] / "p9.json").read_text(encoding="utf-8"))
    assert res.get("barcodes"), "run was not backfilled with barcodes"
    cell = build_rows(res)[0].cells["center"]
    assert cell.value == "937309 ; 937310 ; 937311" and cell.flags == ["center_from_barcode_only"] and cell.orange


# ---------- טווח אורך מרכזי (config/center.json) ----------

def with_ranges(monkeypatch, **ranges):
    from src import center_config
    monkeypatch.setattr(center_config, "center_digit_range", lambda kind="unlabeled": ranges.get(kind, (5, 9)))


def test_default_range_is_five_to_nine_when_config_has_no_key(monkeypatch, tmp_path):
    from src import center_config
    monkeypatch.setattr(center_config, "CONFIG_PATH", tmp_path / "none.json")
    center_config.center_digit_range.cache_clear()
    try:
        assert center_config.center_digit_range("unlabeled") == (5, 9)
        assert center_config.in_center_range("12345") and center_config.in_center_range("123456789")
        assert not center_config.in_center_range("1234") and not center_config.in_center_range("1234567890")
    finally:
        center_config.center_digit_range.cache_clear()


def test_unlabeled_candidates_follow_the_configured_range(monkeypatch):
    from src.rules import _center_unlabeled
    pool = [NumberCandidate(value=v, label=None, confidence=0.9) for v in ("12345", "123456", "1234567")]
    with_ranges(monkeypatch, unlabeled=(6, 6))
    assert _center_unlabeled(pool)[0] == ["123456"]
    with_ranges(monkeypatch, unlabeled=(5, 9))
    assert _center_unlabeled(pool)[0] == ["12345", "123456", "1234567"]


def test_barcode_fill_uses_its_own_conservative_range(monkeypatch):
    with_ranges(monkeypatch, barcode_match=(5, 9), barcode_fill=(6, 6))
    out = apply_center_barcode(Decision(), BC("111111", "2222222", "333333333"))
    assert out.value == "111111" and out.flags == ["center_from_barcode_only"]


def test_barcode_equal_to_commitment_number_is_not_counted_as_center(monkeypatch):
    with_ranges(monkeypatch, barcode_match=(5, 9))
    d = Decision(value="111111", raw="111111", flags=["center_mismatch"])
    # בלי הוצאה: הברקוד השני (מספר התחייבות) מונע שוויון; עם הוצאה: שוויון, ירוק
    assert apply_center_barcode(d, BC("111111", "944000351")).flags == ["center_mismatch"]
    out = apply_center_barcode(d, BC("111111", "944000351"), exclude={"944000351"})
    assert out.flags == [] and "center_barcode_agrees" in out.hints
    assert apply_center_barcode(Decision(), BC("944000351"), exclude={"944000351"}).value is None


# ---------- רגרסיה: חלק 2 עמוד 5 (ירוק שגוי) ----------

P5 = Path("outputs/part2_eval/p5.json")


@pytest.mark.skipif(not P5.exists(), reason="needs the saved part 2 run")
def test_part2_page5_center_stays_orange():
    """הבאג המקורי, מהתשובה השמורה של עמוד 5 בחלק 2: מעבר 1 + מעבר 2 נותנים "436703 ; 946622" (436703 הוא מספר ההתחייבות)
    עם center_mismatch, והברקוד מכיל בדיוק את שני המספרים. הדגל חייב להישאר (קודם הוצג ירוק)."""
    from src.schema import PageExtraction
    d = json.loads(P5.read_text(encoding="utf-8"))
    r = PageExtraction.model_validate(d["pass1"])
    out = decide_center(r.numbers, d["pass2"], d["barcodes"])
    assert "center_mismatch" in out.flags
    assert out.value == "436703 ; 946622"


def test_barcode_agreement_still_greens_a_single_value_and_labeled_values():
    numbers = [NumberCandidate(value="946622", label="מרכזי", confidence=0.95)]
    assert decide_center(numbers, None, BC("946622")).flags == []
    two_labeled = [NumberCandidate(value="944963", label="מרכזי", confidence=0.95),
                   NumberCandidate(value="944964", label="מרכזי", confidence=0.95)]
    assert decide_center(two_labeled, None, BC("944963", "944964")).flags == []
