"""מקורות נוספים למספר התחייבות (20.10.2026, מהממצאים על data/eval_extra). שניהם **כתומים בלבד, לעולם לא ירוקים**:
1. קריאת אזור ההתחייבות מהמעבר השני, כשאין מועמד מתויג במעבר הראשון (עמוד 4: 66608489).
2. מספר בצורת אות לטינית + 6 ספרות בלי תווית (עמודים 2 ו-3: X132767 / X132797), שגם לא נכנס למאגר המרכזי.
בלי קריאות API: נתונים בנויים ותשובות שמורות."""
import json
from pathlib import Path

import pytest

from src.assemble import page_rows
from src.rules import (
    F_COMMITMENT_FROM_REGION, F_COMMITMENT_LETTER_PREFIX, F_COMMITMENT_SINGLE_SOURCE, commitment_from_region,
    commitment_numbers, decide_center, is_letter_prefix_number, is_non_center_number,
)
from src.schema import NumberCandidate, PageExtraction, RegionsExtraction

RUN = Path("outputs/eval_extra")


def num(value, label=None, source="printed", conf=0.95):
    return NumberCandidate(value=value, label=label, confidence=conf, source=source)


def regions(value, label=None, region_ok=True, ok=True, conf=0.95):
    """תשובת מעבר שני מלאה (דרך הסכמה), שבה רק אזור ההתחייבות תקין."""
    r = RegionsExtraction.model_validate(
        {"patient": {"region_ok": False}, "barcode": {"region_ok": False},
         "commitment": {"region_ok": region_ok,
                        "number": {"value": value, "label": label, "confidence": conf, "source": "printed"}}})
    return {"ok": ok, "model": "m", **r.model_dump()}


def result(numbers, is_form=True):
    p = PageExtraction(is_commitment_form=is_form, page_quality="ok", numbers=list(numbers))
    return {"ok": True, "model": "m", **p.model_dump()}


# ---------- 1. קריאת אזור ההתחייבות (מעבר 2) ----------

def test_region_reading_becomes_an_orange_candidate():
    d = commitment_from_region(regions("66608489"))
    assert len(d) == 1 and d[0].value == "66608489"
    assert d[0].flags == [F_COMMITMENT_FROM_REGION] and d[0].uncertain      # כתום, לעולם לא ירוק


def test_region_reading_is_used_only_when_pass1_has_no_candidate():
    """יש מועמד מתויג במעבר 1: קריאת האזור ממשיכה לשמש לאימות בלבד (הסכמה = ערך, אי-הסכמה = mismatch),
    ולא נכנסת כמועמד נוסף."""
    labeled = result([num("107646", "התחייבות")])
    agree = page_rows(labeled, regions=regions("107646"))
    assert agree[0]["commitment"] == "107646" and F_COMMITMENT_FROM_REGION not in agree[0]["commitment_flags"]
    differ = page_rows(labeled, regions=regions("999999"))
    assert differ[0]["commitment"] is None                                   # אי-הסכמה: לא בוחרים
    assert F_COMMITMENT_FROM_REGION not in differ[0]["commitment_flags"]
    rows = page_rows(result([num("050-8101585", "טל")]), regions=regions("66608489"))
    assert rows[0]["commitment"] == "66608489"
    assert F_COMMITMENT_FROM_REGION in rows[0]["commitment_flags"]


def test_known_non_commitment_label_is_rejected():
    """עמוד 1: המעבר השני קרא שם מספר עם התווית "מקרה:" (מספר מקרה, לא התחייבות)."""
    assert commitment_from_region(regions("12043017", "מקרה:")) == []
    assert commitment_from_region(regions("297456", "מבטח")) == []
    assert commitment_from_region(regions("948023", "מרכזי")) == []


def test_region_not_ok_or_too_short_or_missing_is_rejected():
    assert commitment_from_region(regions("66608489", region_ok=False)) == []
    assert commitment_from_region(regions("66608489", ok=False)) == []
    assert commitment_from_region(regions("123")) == []                      # פחות מ-4 ספרות
    assert commitment_from_region(regions(None)) == []
    assert commitment_from_region(None) == []


def test_region_candidate_never_turns_green_even_if_it_agrees_with_itself():
    rows = page_rows(result([]), regions=regions("66608489"))
    assert rows[0]["commitment"] == "66608489"
    assert rows[0]["commitment_flags"]                                       # תמיד יש דגל


# ---------- 2. אות + 6 ספרות ----------

def test_letter_prefix_pattern():
    assert is_letter_prefix_number("X132767") and is_letter_prefix_number("x132767")
    assert not is_letter_prefix_number("132767")            # בלי אות
    assert not is_letter_prefix_number("XY132767")          # שתי אותיות
    assert not is_letter_prefix_number("X13276")            # 5 ספרות
    assert not is_letter_prefix_number("X1327677")          # 7 ספרות
    assert not is_letter_prefix_number(None)


def test_letter_prefix_number_is_an_orange_commitment_candidate():
    d = commitment_numbers([num("X132767"), num("050-8101585", "טל")])
    assert len(d) == 1 and d[0].value == "X132767"
    assert F_COMMITMENT_LETTER_PREFIX in d[0].flags and d[0].uncertain


def test_two_different_letter_prefix_numbers_are_ambiguous():
    assert commitment_numbers([num("X132767"), num("Y999888")]) == []


def test_labeled_candidate_still_wins_over_letter_prefix():
    d = commitment_numbers([num("X132767"), num("107646", "מס' התחייבות")])
    assert [x.value for x in d] == ["107646"]


def test_letter_prefix_digits_do_not_enter_the_center_field():
    """עמוד 3: X132797 הוא מספר התחייבות; 132797 לא ייכנס כמרכזי."""
    assert is_non_center_number(num("X132797"))
    center = decide_center([num("X132797"), num("948246", "מרכזי")])
    assert center.value == "948246"
    assert "132797" not in (center.value or "")


def test_a_number_labelled_center_is_still_a_center():
    assert not is_non_center_number(num("X132797", "מרכזי"))


# ---------- המקרים האמיתיים מהריצה השמורה ----------

@pytest.mark.skipif(not (RUN / "p2.json").exists(), reason="needs the saved eval_extra run")
@pytest.mark.parametrize("page,expected,flag", [(2, "X132767", F_COMMITMENT_LETTER_PREFIX),
                                                (3, "X132797", F_COMMITMENT_LETTER_PREFIX),
                                                (4, "66608489", F_COMMITMENT_FROM_REGION)])
def test_cached_eval_extra_pages_now_find_the_commitment(page, expected, flag):
    d = json.loads((RUN / f"p{page}.json").read_text(encoding="utf-8"))
    rows = page_rows(d["pass1"], regions=d.get("pass2"), barcodes=d.get("barcodes"))
    values = [r["commitment"] for r in rows]
    assert expected in values
    row = next(r for r in rows if r["commitment"] == expected)
    assert flag in row["commitment_flags"] and row["commitment_flags"] != []     # כתום, לא ירוק


@pytest.mark.skipif(not (RUN / "p3.json").exists(), reason="needs the saved eval_extra run")
def test_cached_page3_center_no_longer_holds_the_commitment_digits():
    d = json.loads((RUN / "p3.json").read_text(encoding="utf-8"))
    rows = page_rows(d["pass1"], regions=d.get("pass2"), barcodes=d.get("barcodes"))
    assert "132797" not in (rows[0]["center"].value or "")
    assert rows[0]["center"].value == "948246"


@pytest.mark.skipif(not (RUN / "p1.json").exists(), reason="needs the saved eval_extra run")
def test_cached_page1_region_reading_is_still_rejected():
    """עמוד 1: המעבר השני קרא "מקרה:" ולכן לא נוצר מספר התחייבות שגוי."""
    d = json.loads((RUN / "p1.json").read_text(encoding="utf-8"))
    rows = page_rows(d["pass1"], regions=d.get("pass2"), barcodes=d.get("barcodes"))
    assert rows[0]["commitment"] is None


def test_single_source_flag_still_applies_to_a_letter_prefix_candidate():
    rows = page_rows(result([num("X132767")]), regions=regions("X132767"))
    assert rows[0]["commitment"] == "X132767"
    assert F_COMMITMENT_SINGLE_SOURCE in rows[0]["commitment_flags"] or F_COMMITMENT_LETTER_PREFIX in rows[0]["commitment_flags"]
