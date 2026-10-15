import pytest

from src import rules
from src.rules import F_HANDWRITTEN, F_NO_CENTER_LABEL, decide_center, is_center_label
from src.schema import NumberCandidate, RegionsExtraction


def num(value, label=None, source="printed", conf=1.0):
    return NumberCandidate(value=value, label=label, source=source, confidence=conf)


def regions(numbers=(), central=None, central_source="printed", region_ok=True):
    r = RegionsExtraction.model_validate({
        "patient": {"region_ok": True},
        "barcode": {
            "region_ok": region_ok,
            "numbers": [{"value": v, "label": lb, "orientation": "normal", "confidence": 1.0} for v, lb in numbers],
            "central_number": {"value": central, "confidence": 0.9, "source": central_source},
        },
    })
    return {"ok": True, "model": "m", **r.model_dump()}


@pytest.mark.parametrize("label", ["מרכזי", "מרכז", "מס' מרכזי", "מרכז:", "מרכזי 944963", "המספר מרכז"])
def test_center_label_matches_as_whole_word(label):
    assert is_center_label(label)


@pytest.mark.parametrize("label", [None, "", "מרכזית", "המעבדה המרכזית", "מרכזיה", "ממרכז", "המרכז", "התחייבות", "מוקד"])
def test_center_label_rejects_longer_words(label):
    assert not is_center_label(label)


def test_page_14_label_merkaz_gives_both_centers_green():
    """עמוד 14: שני המרכזיים נקראו עם התווית "מרכז" (בלי י'); 944963 הופיע פעמיים."""
    nums = [num("944963", "מרכז"), num("944963", "מרכז"), num("944964", "מרכז"),
            num("11223344", None, source="handwritten")]
    d = decide_center(nums)
    assert d.value == "944963 ; 944964"
    assert not d.uncertain


def test_commitment_like_label_with_word_markazit_is_not_a_center():
    d = decide_center([num("251493", "המעבדה המרכזית")])
    assert d.value is None or F_NO_CENTER_LABEL in d.flags      # לא נכנס כמרכזי מסומן-ירוק


def test_labeled_center_in_page_numbers_is_green():
    d = decide_center([num("939376", "מרכזי"), num("730578626", "התחייבות מספר")])
    assert d.value == "939376"
    assert not d.uncertain


def test_multiple_labeled_centers_joined():
    d = decide_center([num("937309", "מרכזי"), num("937310", "מרכזי"), num("937311", "מרכזי"), num("937309", "מרכזי")])
    assert d.value == "937309 ; 937310 ; 937311"


def test_central_number_from_second_pass_counts_as_labeled():
    d = decide_center([], regions(central="946284"))
    assert d.value == "946284"
    assert not d.uncertain


def test_label_in_barcode_area_numbers():
    d = decide_center([], regions(numbers=[("945504", "מרכזי"), ("2026", None)]))
    assert d.value == "945504"
    assert not d.uncertain


def test_handwritten_labeled_center_is_orange():
    d = decide_center([num("937188", "מרכזי", source="handwritten")])
    assert d.value == "937188"
    assert F_HANDWRITTEN in d.flags


def test_single_six_digit_in_barcode_area_without_label_is_orange():
    d = decide_center([], regions(numbers=[("1122334", None), ("937188", None), ("251120160", None)]))
    assert d.value == "937188"
    assert F_NO_CENTER_LABEL in d.flags


def test_two_six_digit_candidates_gives_flagged_empty():
    d = decide_center([], regions(numbers=[("937188", None), ("945504", None)]))
    assert d.value is None
    assert F_NO_CENTER_LABEL in d.flags
    assert d.alternatives == ["937188", "945504"]


def test_labeled_numbers_are_excluded_from_fallback():
    """מספר בן 6 ספרות עם תווית אחרת (למשל התחייבות) אינו מועמד למרכזי."""
    d = decide_center([], regions(numbers=[("251493", "מספר התחייבות")]))
    assert d.value is None and not d.alternatives


def test_no_second_pass_falls_back_to_page_numbers():
    d = decide_center([num("939376"), num("0046025783"), num("87250", "קוד השירות")])
    assert d.value == "939376"
    assert F_NO_CENTER_LABEL in d.flags


def test_label_beats_fallback():
    d = decide_center([num("111111"), num("222222", "מרכזי")])
    assert d.value == "222222"
    assert not d.uncertain


def test_nothing_found_is_empty():
    assert decide_center([], regions(numbers=[("2026", None)])) == rules.Decision()
    assert decide_center([]) == rules.Decision()


def test_failed_second_pass_is_ignored():
    d = decide_center([num("939376", "מרכזי")], {"ok": False})
    assert d.value == "939376"


def test_single_unlabeled_with_foreign_labeled_six_digit_number_keeps_value_with_competitors():
    """עמוד 14: 944963 עם תווית לא נכונה ("נסיובי") ו-944964 בלי תווית: לא בוחרים אחד."""
    from src.rules import decide_center
    from src.schema import NumberCandidate
    ns = [NumberCandidate(value="944963", label="נסיובי", confidence=0.95),
          NumberCandidate(value="944964", label=None, confidence=0.95)]
    d = decide_center(ns)
    assert d.value == "944964" and d.flags == ["no_center_label"] and d.alternatives == ["944963"]


def test_commitment_or_id_labeled_six_digit_number_does_not_block_center():
    from src.rules import decide_center
    from src.schema import NumberCandidate
    ns = [NumberCandidate(value="107646", label="מספר התחייבות", confidence=0.95),
          NumberCandidate(value="123456", label="ת.ז", confidence=0.95),
          NumberCandidate(value="944964", label=None, confidence=0.95)]
    assert decide_center(ns).value == "944964"


# ---------- שני מעברים: מועמד שלא אושר / מעברים שונים = כתום ----------
import itertools

from src.rules import F_CENTER_MISMATCH


def test_page_24_case_two_page_candidates_and_empty_barcode_pass_is_orange_with_candidates():
    """עמוד 24: שני מועמדים בעמוד, המעבר השני לא מצא כלום: לא ריק בלי דגל."""
    d = decide_center([num("947769"), num("947770")], regions(numbers=[("2026", None)]))
    assert d.uncertain and F_CENTER_MISMATCH in d.flags
    assert d.alternatives == ["947769", "947770"]


def test_page_14_case_different_candidates_in_two_passes_is_orange_and_not_chosen():
    """עמוד 14: העמוד נתן 944964 (בלי תווית), המעבר השני 944963 (מרכזי): סתירה, לא בוחרים."""
    d = decide_center([num("944964")], regions(central="944963"))
    assert d.value is None and F_CENTER_MISMATCH in d.flags
    assert set(d.alternatives) == {"944963", "944964"}


def test_candidate_missing_from_second_pass_is_kept_in_orange():
    d = decide_center([num("944963", "מרכז"), num("944964", "מרכז")], regions(central="944963"))
    assert d.value == "944963 ; 944964" and F_CENTER_MISMATCH in d.flags
    assert set(d.alternatives) == {"944963", "944964"}


def test_both_passes_agree_stays_green():
    d = decide_center([num("944963", "מרכזי")], regions(central="944963"))
    assert d.value == "944963" and not d.uncertain


def test_zero_candidates_in_all_passes_is_empty_without_flag():
    d = decide_center([num("11223344")], regions(numbers=[("2026", None)]))
    assert d.value is None and not d.flags and not d.alternatives


def test_pool_is_union_of_page_and_barcode_numbers():
    """מספר אחד בן 6 ספרות בעמוד ואחר באזור הברקוד: שניהם מועמדים (לא רק הברקוד)."""
    d = decide_center([num("937188")], regions(numbers=[("945504", None)]))
    assert d.uncertain and set(d.alternatives) == {"937188", "945504"}


def test_page_only_without_second_pass_is_unchanged():
    assert decide_center([num("939376", "מרכזי")]).value == "939376"
    assert decide_center([num("937188")]).flags == [F_NO_CENTER_LABEL]


def _scenarios():
    sets = [(), ("111111",), ("222222",), ("111111", "222222")]
    for page, bar, page_labeled, bar_labeled in itertools.product(sets, sets, (True, False), (True, False)):
        yield page, bar, page_labeled, bar_labeled


def test_principle_candidates_never_lost_silently():
    """כל צירוף של מועמדים בעמוד ובאזור הברקוד: אם יש מועמד כלשהו וערך התא ריק או חלקי, התא כתום וכל המועמדים
    ב-alternatives. בלי אף מועמד: ריק בלי דגל."""
    for page, bar, pl, bl in _scenarios():
        nums = [num(v, "מרכזי" if pl else None) for v in page]
        reg = regions(numbers=[(v, "מרכזי" if bl else None) for v in bar])
        d = decide_center(nums, reg)
        allc = set(page) | set(bar)
        got = set(d.value.split(" ; ")) if d.value else set()
        if not allc:
            assert d.value is None and not d.flags and not d.alternatives, (page, bar, pl, bl)
        elif got != allc:
            assert d.uncertain and allc <= set(d.alternatives), (page, bar, pl, bl, d)


# ---------- שברי התחייבות ומועמדים נוספים (15.10.2026) ----------

def test_commitment_fragment_is_dropped_before_the_mismatch_is_computed():
    """000351 הוא סיומת של התחייבות 944000351: הוא יוצא מהמאגר לפני ההשוואה בין המעברים, ולכן אינו יוצר center_mismatch."""
    numbers = [num("945504"), num("944000351", "מספר התחייבות:"), num("000351")]
    d = decide_center(numbers, regions(numbers=[("945504", None)]))
    assert d.value == "945504" and rules.F_CENTER_MISMATCH not in d.flags and "center_fragment_dropped:000351" in d.hints


def test_page_15_mismatch_is_about_pass_two_not_confirming_the_candidate_not_about_the_fragment():
    """בריצת v4b המעבר השני קרא רק מספר באורך 13 (944000351 + 2026) ולא את 945504: מועמד שמעבר אחד מצא ולא אושר = כתום."""
    numbers = [num("945504"), num("944000351", "מספר התחייבות:"), num("000351")]
    d = decide_center(numbers, regions(numbers=[("9440003512026", None)]))
    assert d.value == "945504" and rules.F_CENTER_MISMATCH in d.flags and d.alternatives == ["945504"]


def test_labeled_center_does_not_hide_an_unlabeled_second_center():
    """ניסוי שנדחה (15.10.2026): "המספר עם התווית מרכזי גובר על מספרים בלי תווית" שבר את עמוד 14 ב-v4b: האמת היא שני
    מרכזיים (944963 ; 944964) ורק אחד מהם מסומן במילה. לכן המועמד בלי תווית נשאר בערך, וכל השורה כתומה."""
    numbers = [num("944963"), num("944964")]
    d = decide_center(numbers, regions(central="944963"))
    assert d.value == "944963 ; 944964" and rules.F_CENTER_MISMATCH in d.flags


# ---------- מסנני מועמדי מרכזי: תווית שאינה מרכזי, שעה/תאריך, ומועמד בודד בתווית זרה (15.10.2026) ----------

def page3_numbers():
    """צורת עמוד 3: המרכזי האמיתי בכתב יד תחת תווית שנקראה לא נכון, קוד מבטח מודפס תחת "מבטח", והתחייבות."""
    return [num("939273", "מספר ארכיון", source="handwritten", conf=0.9), num("127138045", "מספר התחייבות"),
            num("113001", "מבטח")]


def test_page3_insurer_code_and_time_never_become_candidates():
    d = decide_center(page3_numbers(), regions(numbers=[("07:49:34", "שעה"), ("939273", "מספר")]))
    assert d.value == "939273" and d.flags == [F_NO_CENTER_LABEL]        # המועמד היחיד שנשאר: ערך כתום
    assert d.alternatives == []                                          # לא 113001 (מבטח) ולא 074934 (07:49:34)


@pytest.mark.parametrize("raw", ["07:49:34", "7:49", "09.08.26", "17-06-2026", "09-2-025"])
def test_time_and_date_shapes_are_not_candidates_even_without_a_label(raw):
    assert decide_center([], regions(numbers=[(raw, None)])).value is None
    assert decide_center([], regions(numbers=[(raw, None), ("939273", None)])).value == "939273"


@pytest.mark.parametrize("label", ["מבטח", "שעה", "תאריך", "ת.קבלה", "רופא שולח:", "גורם שולח", "מספר בקשה :", "מספר רישיון :", "טלפון", "גיל"])
def test_labels_of_other_categories_exclude_the_number(label):
    assert decide_center([num("112233", label)], None).value is None and decide_center([num("112233", label)], None).alternatives == []


@pytest.mark.parametrize("label", ["מספר ארכיון", "מספר", "ברקוד", "מסף מחפי", "central barcode sticker"])
def test_a_single_candidate_under_another_foreign_label_is_an_orange_value(label):
    """מרכזי אמיתי מופיע גם תחת תוויות כאלה, ולכן הוא נכנס; מועמד יחיד = ערך כתום no_center_label (כמו בלי תווית)."""
    d = decide_center([num("939273", label)], None)
    assert d.value == "939273" and d.flags == [F_NO_CENTER_LABEL] and d.alternatives == []


def test_several_candidates_under_foreign_labels_stay_empty_with_suggestions_only():
    d = decide_center([num("939273", "מספר ארכיון"), num("944963", "ברקוד")], None)
    assert d.value is None and d.flags == [F_NO_CENTER_LABEL] and d.alternatives == ["939273", "944963"]


def test_a_labeled_center_is_untouched_by_the_filters():
    d = decide_center([num("939273", "מרכזי"), num("113001", "מבטח")], None)
    assert d.value == "939273" and d.flags == []


def test_two_centers_with_only_one_labeled_still_work():
    """עמוד 14: האמת היא שני מרכזיים (944963 ; 944964) ורק אחד מהם עם המילה. המסננים לא מורידים את השני."""
    d = decide_center([num("944963", "ברקוד"), num("944964", "ברקוד")], regions(central="944963"))
    assert d.value == "944963 ; 944964" and rules.F_CENTER_MISMATCH in d.flags
    d = decide_center([num("944963"), num("944964")], regions(central="944963"))
    assert d.value == "944963 ; 944964"


def test_label_list_is_a_single_named_constant_built_from_part_1():
    assert isinstance(rules.NON_CENTER_LABEL_WORDS, tuple) and "מבטח" in rules.NON_CENTER_LABEL_WORDS
    assert "חלק 2" in open("src/rules.py", encoding="utf-8").read().split("NON_CENTER_LABEL_WORDS =")[0].rsplit("\n\n", 1)[-1]
