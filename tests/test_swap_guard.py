"""מניעת "ירוק הפוך" בין מרכזי להתחייבות: שני המספרים מתחלפים בין השדות כשהמודל (או האזורים שנחתכו) מחליף
ביניהם. נמצא על טופס שמיר בכתב יד (22.10.2026, בלי נתוני מטופל כאן: הכול סינתטי).

שלוש הגנות, כל אחת עם בדיקה נפרדת:
(1) decide_center/_center_groups: שדה מבנה (central_number) עם תווית שסותרת אותו (אומרת "התחייבות"), או בלי
    תווית ובאורך לא סביר למרכזי (config/center.json, "barcode_match"): לא נכנס כמתויג.
(2) verify_commitments: הקריאה השנייה מסכימה על הספרות אבל התווית שלה אומרת "מרכזי"/"מרכז": לא אישור עצמאי.
(3) swap_claim_sets/apply_swap_guard: רשת הגנה אחרונה על כל הצינור (page_rows): אם מספר נטען בראיות הגולמיות
    של אזורי המעבר השני גם כמרכזי וגם כהתחייבות, אף אחד מהשדות לא ירוק."""
from src.rules import (
    F_CENTER_COMMITMENT_SWAP, F_COMMITMENT_MISMATCH, Decision, apply_swap_guard, decide_center,
    swap_claim_sets, verify_commitments,
)
from src.schema import NumberCandidate, RegionsExtraction
from src.assemble import page_rows
from src.schema import PageExtraction


def num(value, label=None, source="printed", conf=1.0):
    return NumberCandidate(value=value, label=label, source=source, confidence=conf)


def regions(barcode_central=None, barcode_central_label=None, barcode_numbers=(), commitment_number=None,
            commitment_label=None, region_ok=True):
    r = RegionsExtraction.model_validate({
        "patient": {"region_ok": True},
        "barcode": {
            "region_ok": region_ok,
            "numbers": [{"value": v, "label": lb, "orientation": "normal", "confidence": 0.99} for v, lb in barcode_numbers],
            "central_number": {"value": barcode_central, "label": barcode_central_label, "confidence": 0.95, "source": "printed"},
        },
        "commitment": {"region_ok": region_ok,
                       "number": {"value": commitment_number, "label": commitment_label, "confidence": 0.95, "source": "printed"}},
    })
    return {"ok": True, "model": "m", **r.model_dump()}


def d(value, *flags):
    return Decision(value=value, raw=value, flags=list(flags))


# ---------- (1) _center_groups: שדה מבנה בלי אימוץ עיוור ----------

def test_central_number_with_commitment_label_is_not_adopted_as_center():
    """שחזור הבאג: אזור הברקוד קרא central_number=2646, אבל התווית שהוא עצמו קרא לידו אומרת "מספר התחייבות"."""
    reg = regions(barcode_central="2646", barcode_central_label="מספר התחייבות")
    out = decide_center([], reg)
    assert out.value is None


def test_central_number_with_correct_center_label_is_still_adopted():
    reg = regions(barcode_central="947768", barcode_central_label="מרכזי")
    out = decide_center([], reg)
    assert out.value == "947768" and not out.uncertain


def test_central_number_without_label_but_implausible_length_is_not_adopted():
    """בלי תווית סותרת, אבל גם בלי תווית מרכזי בכלל: עדיין חייב אורך סביר (config/center.json, barcode_match)."""
    reg = regions(barcode_central="2646")   # 4 ספרות, מחוץ ל-5-9
    assert decide_center([], reg).value is None


def test_central_number_without_label_and_plausible_length_is_adopted():
    reg = regions(barcode_central="946284")   # בלי תווית, 6 ספרות: כמו קודם (test_center.py)
    out = decide_center([], reg)
    assert out.value == "946284" and not out.uncertain


# ---------- (2) verify_commitments: הסכמה על הספרות לא מספיקה כשהתווית סותרת ----------

def test_commitment_agreement_with_center_label_is_flagged_not_confirmed():
    """הקריאה השנייה של אזור ההתחייבות מסכימה על הספרות (947768), אבל קראה לידו את התווית "מרכזי"."""
    out = verify_commitments([d("947768")], regions(commitment_number="947768", commitment_label="מרכזי"))
    assert out[0].value == "947768"              # הספרות לא משתנות, רק מסומנות
    assert F_CENTER_COMMITMENT_SWAP in out[0].flags
    assert out[0].uncertain


def test_commitment_agreement_with_commitment_label_is_still_confirmed():
    out = verify_commitments([d("947768")], regions(commitment_number="947768", commitment_label="מספר התחייבות"))
    assert out[0].value == "947768" and not out[0].flags


def test_commitment_agreement_with_no_label_is_unaffected():
    out = verify_commitments([d("947768")], regions(commitment_number="947768"))
    assert out[0].value == "947768" and not out[0].flags


def test_real_mismatch_unrelated_to_center_label_is_unaffected():
    out = verify_commitments([d("111111")], regions(commitment_number="222222"))
    assert out[0].value is None and F_COMMITMENT_MISMATCH in out[0].flags
    assert F_CENTER_COMMITMENT_SWAP not in out[0].flags


# ---------- (3) swap_claim_sets / apply_swap_guard ----------

def test_swap_claim_sets_detects_crossed_structural_fields():
    """central_number (מבנה) מתויג בטעות "התחייבות", ו-commitment.number (מבנה) מתויג בטעות "מרכזי": שני
    המספרים נטענים משני הצדדים."""
    reg = regions(barcode_central="2646", barcode_central_label="מספר התחייבות",
                   barcode_numbers=[("2646", "מספר התחייבות")],
                   commitment_number="947768", commitment_label="מרכזי")
    center_claims, commitment_claims = swap_claim_sets(reg)
    assert center_claims == {"2646", "947768"}
    assert commitment_claims == {"2646", "947768"}


def test_swap_claim_sets_clean_regions_have_no_overlap():
    """אותו טופס, קרוא נכון: אין חפיפה, גם כששני השדות מופיעים בנפרד."""
    reg = regions(barcode_central="947768", barcode_central_label="מרכזי",
                   barcode_numbers=[("2646", "מספר התחייבות")],
                   commitment_number="2646", commitment_label="מספר התחייבות")
    center_claims, commitment_claims = swap_claim_sets(reg)
    assert center_claims == {"947768"}
    assert commitment_claims == {"2646"}
    assert not (center_claims & commitment_claims)


def test_apply_swap_guard_demotes_both_green_values():
    center = d("2646")
    commitments = [d("947768")]
    reg = regions(barcode_central="2646", barcode_central_label="מספר התחייבות",
                   commitment_number="947768", commitment_label="מרכזי")
    new_center, new_commitments = apply_swap_guard(center, commitments, reg)
    assert F_CENTER_COMMITMENT_SWAP in new_center.flags and new_center.uncertain
    assert set(new_center.alternatives) == {"947768"}
    assert F_CENTER_COMMITMENT_SWAP in new_commitments[0].flags and new_commitments[0].uncertain
    assert set(new_commitments[0].alternatives) == {"2646"}


def test_apply_swap_guard_fills_empty_center_with_both_candidates():
    """decide_center כבר דחה את שני המועמדים הסותרים (ריק): עדיין מוצגת סיבה מפורשת ושני המספרים כהצעה."""
    center = Decision()
    commitments = [d("947768")]
    reg = regions(barcode_central="2646", barcode_central_label="מספר התחייבות",
                   commitment_number="947768", commitment_label="מרכזי")
    new_center, _ = apply_swap_guard(center, commitments, reg)
    assert new_center.value is None
    assert F_CENTER_COMMITMENT_SWAP in new_center.flags
    assert set(new_center.alternatives) == {"2646", "947768"}


def test_apply_swap_guard_no_effect_without_overlap():
    center = d("947768")
    commitments = [d("2646")]
    reg = regions(barcode_central="947768", barcode_central_label="מרכזי",
                   commitment_number="2646", commitment_label="מספר התחייבות")
    new_center, new_commitments = apply_swap_guard(center, commitments, reg)
    assert new_center == center
    assert new_commitments == commitments


def test_apply_swap_guard_ignores_pass1_whole_page_label_alone():
    """מדידה על outputs/part2_final עמוד 1 (22.10.2026): תווית שגויה במעבר הראשון (קריאת העמוד השלם) לא
    מספיקה בלי סתירה באזורי המעבר השני עצמם: אחרת תא ירוק-נכון שאושש גם בברקוד מקומי היה הופך לכתום בלי
    שום ראיה סותרת אמיתית. swap_claim_sets לא מקבלת כלל את רשימת numbers של המעבר הראשון."""
    center = d("947768")              # האזורים נקיים ועצמם לא סותרים
    commitments = [d("2646")]
    reg = regions(barcode_central="947768", barcode_central_label="מרכזי",
                   commitment_number="2646", commitment_label="מספר התחייבות")
    new_center, new_commitments = apply_swap_guard(center, commitments, reg)
    assert new_center == center and new_commitments == commitments


def test_apply_swap_guard_handles_no_regions():
    center = d("947768")
    new_center, new_commitments = apply_swap_guard(center, [d("2646")], None)
    assert new_center == center


# ---------- קצה-לקצה: page_rows ----------

def test_page_rows_neither_field_is_green_on_a_swapped_page():
    """שחזור מלא, בלי נתוני מטופל: מעבר ראשון קורא את שני המספרים (אחד מתויג "התחייבות" בטעות, השני בלי
    תווית), ואזורי המעבר השני חוצים ביניהם: central_number מתויג "התחייבות", commitment.number מתויג "מרכזי"."""
    page = PageExtraction(is_commitment_form=True, page_quality="ok",
                          numbers=[num("947768", "מספר התחייבות"), num("2646")])
    reg = regions(barcode_central="2646", barcode_central_label="מספר התחייבות",
                   barcode_numbers=[("2646", "מספר התחייבות")],
                   commitment_number="947768", commitment_label="מרכזי")
    rows = page_rows({"ok": True, "model": "m", **page.model_dump()}, regions=reg)
    assert len(rows) == 1
    row = rows[0]
    assert row["center"].value is None
    assert F_CENTER_COMMITMENT_SWAP in row["center"].flags
    assert set(row["center"].alternatives) >= {"2646", "947768"}
    assert row["commitment"] == "947768"           # הספרות שהמעבר השני קרא כהתחייבות, לא ירוק
    assert F_CENTER_COMMITMENT_SWAP in row["commitment_flags"]


def test_page_rows_clean_matching_page_stays_green():
    """ביקורת: אותו טופס בלי החלפה (קרוא נכון) נשאר ירוק כמו קודם."""
    page = PageExtraction(is_commitment_form=True, page_quality="ok",
                          numbers=[num("947768", "מרכזי"), num("2646", "מספר התחייבות")])
    reg = regions(barcode_central="947768", barcode_central_label="מרכזי",
                   commitment_number="2646", commitment_label="מספר התחייבות")
    rows = page_rows({"ok": True, "model": "m", **page.model_dump()}, regions=reg)
    row = rows[0]
    assert row["center"].value == "947768" and not row["center"].uncertain
    assert row["commitment"] == "2646" and not row["commitment_flags"]
