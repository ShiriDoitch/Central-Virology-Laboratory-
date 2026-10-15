from src.assemble import page_rows
from src.rules import F_MODEL_NOT_FORM, F_NON_DIGIT, commitment_numbers
from src.schema import NumberCandidate, PageExtraction, RegionsExtraction


def num(value, label=None, conf=1.0, source="printed"):
    return NumberCandidate(value=value, label=label, confidence=conf, source=source)


def result(is_form=True, numbers=()):
    page = PageExtraction(is_commitment_form=is_form, page_quality="ok", numbers=list(numbers))
    return {"ok": True, "model": "x", **page.model_dump()}


def test_non_digit_candidates_dropped_when_digit_only_exists():
    """עמוד 9: 606/50364186 ו-04-61619993555 לא נכנסים כשיש 50364186."""
    c = commitment_numbers([num("606/50364186", "דרישה"), num("04-61619993555", "ת.דרישה"), num("50364186", "דרישה")])
    assert [d.value for d in c] == ["50364186"]
    assert not c[0].uncertain


def test_no_digit_only_shows_best_candidate_in_orange():
    c = commitment_numbers([num("606/50364186", "דרישה"), num("04-9", "ת.דרישה")])
    assert [d.value for d in c] == ["606/50364186"]       # הערך כפי שנקרא, בלי תיקון
    assert F_NON_DIGIT in c[0].flags
    assert c[0].uncertain


def test_time_like_value_is_not_suggested():
    """עמוד 8: 10:44 עם התווית "זמן דגימה" הוא שעה."""
    assert commitment_numbers([num("10:44", "זמן דגימה")]) == []


def test_failed_page_has_no_rows():
    assert page_rows({"ok": False}) == []


def test_not_a_form_without_commitment_is_skipped():
    assert page_rows(result(is_form=False)) == []


def test_model_says_not_form_but_commitment_found_is_kept_in_orange():
    """עמודים 6/9: המודל סימן "לא התחייבות" אבל יש מספר התחייבות."""
    rows = page_rows(result(is_form=False, numbers=[num("483263113", "מס' הדגימה")]))
    assert len(rows) == 1
    assert rows[0]["commitment"] == "483263113"
    assert F_MODEL_NOT_FORM in rows[0]["commitment_flags"]


def _p2(commitment=None, region_ok=True):
    return {"ok": True, "model": "m", **RegionsExtraction.model_validate({
        "patient": {"region_ok": True}, "barcode": {"region_ok": True},
        "commitment": {"region_ok": region_ok, "number": {"value": commitment, "confidence": 0.95, "source": "printed"}}}).model_dump()}


def test_regular_form_row_has_clean_commitment():
    """ירוק רק כששני המעברים מסכימים על הספרות."""
    rows = page_rows(result(numbers=[num("730578626", "התחייבות מספר")]), regions=_p2("730578626"))
    assert rows[0]["commitment"] == "730578626"
    assert rows[0]["commitment_flags"] == []
