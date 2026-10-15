from src import evaluate as ev
from src import rules
from src.assemble import page_rows
from src.rules import Decision
from src.schema import PageExtraction


def test_classify_all_categories():
    assert ev.classify(True, True, False) == "confident_ok"
    assert ev.classify(False, True, False) == "confident_wrong"   # שגיאה שלא סומנה
    assert ev.classify(True, True, True) == "orange_ok"
    assert ev.classify(False, True, True) == "orange_wrong"
    assert ev.classify(True, False, False) == "empty_ok"
    assert ev.classify(False, False, False) == "empty_missed"
    assert ev.classify(False, False, True) == "empty_flagged"     # ריק + מסומן לבדיקה: לא שגיאה
    assert ev.classify(True, False, True) == "empty_flagged"


def test_norm_id_ignores_leading_zeros_and_separators():
    assert ev.norm_value("id", "0011223344") == ev.norm_value("id", "11-223344")


def test_norm_sender_ignores_quotes_and_spaces():
    assert ev.norm_value("sender", 'רמב"ם') == ev.norm_value("sender", "רמב״ם")


def truth_row(**kw):
    base = {"file_page": "חלק 1 עמ 1", "sender": "מאוחדת", "first_name": "ישראל", "last_name": "ישראלי",
            "id": "11223344", "center": "939376 ; 939377", "date": "18.06.2026", "commitment": "730578626", "check": None}
    return {**base, **kw}


def pred_row(**kw):
    base = {"first_name": Decision(), "last_name": Decision(), "id": Decision(value="11223344"),
            "center": Decision(value="939376 ; 939377"), "date": Decision(value="18.06.2026"),
            "sender": Decision(value="מאוחדת"), "commitment": "730578626", "commitment_flags": []}
    return {**base, **kw}


def test_compare_page_all_correct():
    cmp = ev.compare_page([truth_row()], [pred_row()])
    assert cmp["date"]["category"] == "confident_ok"
    assert cmp["center"]["category"] == "confident_ok"      # השוואת קבוצות, לא סדר
    assert cmp["commitment"]["category"] == "confident_ok"


def test_compare_page_unflagged_error_is_detected():
    cmp = ev.compare_page([truth_row()], [pred_row(date=Decision(value="19.06.2026"))])
    assert cmp["date"]["category"] == "confident_wrong"


def test_compare_page_no_prediction_rows():
    cmp = ev.compare_page([truth_row()], [])
    assert cmp["date"]["category"] == "empty_missed"
    assert cmp["commitment"]["category"] == "empty_missed"


def test_unconvertible_date_is_empty_flagged_not_error():
    """תאריך שאי אפשר להמיר: value ריק, raw נשמר, מסומן. נספר "ריק, מסומן לבדיקה"."""
    dec = rules.normalize_date("31.06.2026")
    assert dec.value is None and dec.raw == "31.06.2026" and dec.uncertain
    cmp = ev.compare_page([truth_row()], [pred_row(date=dec)])
    assert cmp["date"]["category"] == "empty_flagged"


def test_empty_flagged_is_not_listed_as_error(monkeypatch):
    dec = rules.normalize_date("31.06.2026")
    cmp = ev.compare_page([truth_row()], [pred_row(date=dec)])
    errors = [f for f, i in cmp.items() if i["category"] in ("confident_wrong", "orange_wrong", "empty_missed")]
    assert "date" not in errors


def test_truth_field_marked_uncertain_is_excluded():
    cmp = ev.compare_page([truth_row(check='ת"ז')], [pred_row(id=Decision(value="99999999"))])
    assert cmp["id"]["category"] == "excluded"


def test_truth_without_commitment_and_none_predicted_is_correct():
    cmp = ev.compare_page([truth_row(commitment=None)], [pred_row(commitment=None, commitment_flags=["no_commitment"])])
    assert cmp["commitment"]["category"] == "empty_ok"


def test_multiple_commitments_compared_as_set():
    t = [truth_row(commitment="1"), truth_row(commitment="2"), truth_row(commitment="3")]
    p = [pred_row(commitment="3"), pred_row(commitment="1"), pred_row(commitment="2")]
    assert ev.compare_page(t, p)["commitment"]["category"] == "confident_ok"


def test_page_rows_skips_failed_and_non_commitment_pages():
    page = PageExtraction(is_commitment_form=False, page_quality="ok")
    assert page_rows({"ok": False}) == []
    assert page_rows({"ok": True, **page.model_dump()}) == []


def test_yellow_counts_are_reported_separately_from_orange():
    """צהוב = ת"ז/שם עם הדגל handwritten בלבד ושתי קריאות עצמאיות מסכימות; הוא תת-קבוצה של הכתום ונספר בנפרד."""
    from src.assemble import page_rows
    from src.schema import DateCandidate, NumberCandidate, RegionsExtraction
    truth = [{"file_page": "חלק 1 עמ 1", "sender": None, "first_name": None, "last_name": None, "id": "11223344", "center": None,
              "date": "10.08.2026", "commitment": None, "center_where": None, "date_where": None, "commitment_label": None,
              "notes": None, "check": None}]

    def run(conf=0.95, second=True):
        page = PageExtraction(is_commitment_form=True, page_quality="ok",
                              id_numbers=[NumberCandidate(value="11223344", label="ת.ז.", source="handwritten", confidence=conf)],
                              dates=[DateCandidate(value="10.08.2026", kind="handwritten_date", evidence="handwriting",
                                                   source="handwritten", confidence=0.95)])
        regions = {"ok": True, "model": "m", **RegionsExtraction.model_validate({"patient": {
            "region_ok": True, "id_number": {"value": "11223344", "source": "handwritten", "confidence": conf, "label": "ת.ז."}}}).model_dump()}
        return ev.compare_page(truth, page_rows({"ok": True, **page.model_dump()}, regions=regions if second else None))

    r = run()
    # ת"ז שעוברת ספרת ביקורת בשתי קריאות מסכימות: ירוק (לא צהוב); הצהוב נשאר לשמות
    assert r["id"]["category"] == "confident_ok" and r["id"]["only_handwritten"] is False
    assert r["date"]["category"] == "orange_ok" and r["date"]["only_handwritten"] is False       # תאריך: קריאה אחת, לא צהוב
    single = run(second=False)["id"]                                                             # ת"ז בקריאה אחת: כתום, לא צהוב
    assert single["category"] == "orange_ok" and single["only_handwritten"] is False
    assert run(conf=0.3)["id"]["category"] == "orange_ok"                                        # + low_confidence: כתום
