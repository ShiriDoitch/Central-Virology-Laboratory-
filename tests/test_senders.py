import json

import pytest

from src import senders
from src.rules import F_CONFLICT, F_HANDWRITTEN
from src.schema import SenderMention
from src.senders import F_UNKNOWN_SENDER, OTHER, decide_sender, load_matcher

M = load_matcher()


def mention(text, where="header", role="sender", conf=1.0):    # (text, where, role, confidence)
    return SenderMention(text=text, where=where, role=role, confidence=conf)


@pytest.mark.parametrize("text,expected", [
    ("מאוחדת", "מאוחדת"),
    ("קופת חולים מאוחדת", "מאוחדת"),
    ("קופת לאומית תא", "לאומית"),                       # כתיב רועש
    ("שהרותי בריאות כללית מח דן", "כללית"),
    ("מכבי שרותי בריאות תא", "מכבי"),
    ('קופ"ח מכבי-מעבדה שולחת', "מכבי"),
    ('בי"ח רמב"ם', 'רמב"ם'),
    ("הרשות הפלסטינית", "הרשות הפלסטינאית"),
    ("רבין", "כללית"),                                  # סניף -> קופת אם
])
def test_aliases_and_noisy_spellings(text, expected):
    assert decide_sender([mention(text)], M).value == expected


def test_lab_names_excluded_even_when_model_says_sender():
    """עמוד 6: המודל סימן את חותמת המעבדה כ"שולח" ואת הלוגו כ"יעד"."""
    ms = [
        mention("כללית", "logo", "destination"),
        mention("המרכז הרפואי המטולב", "stamp", "sender"),   # כתיב רועש של שם המעבדה
        mention("מעבדה מרכזית", "header", "destination"),
    ]
    d = decide_sender(ms, M)
    assert d.value == "כללית"
    assert not d.uncertain


def test_only_lab_stamp_gives_empty():
    ms = [mention("המעבדה המרכזית לנגיפים המרכז הרפואי המשולב", "stamp", "sender")]
    assert decide_sender(ms, M).value is None


def test_sheba_and_tel_hashomer_are_not_blanket_excluded():
    assert decide_sender([mention("בי\"ח תל השומר ע\"ש שיבא")], M).value == "מרכז רפואי שיבא"


def test_weak_destination_does_not_create_conflict():
    ms = [mention("מאוחדת", "logo", "sender"), mention("בי\"ח תל השומר", "header", "destination")]
    d = decide_sender(ms, M)
    assert d.value == "מאוחדת"
    assert not d.uncertain


def test_disagreement_is_orange_and_logo_wins():
    """כתוב ביד "תל השומר" אבל הלוגו הלל יפה."""
    ms = [mention("הלל יפה", "logo", "sender"), mention("תל השומר", "handwritten", "sender")]
    d = decide_sender(ms, M)
    assert d.value == "מרכז רפואי הלל יפה"
    assert F_CONFLICT in d.flags
    assert "מרכז רפואי שיבא" in d.alternatives


def test_tie_is_conflict_without_value():
    ms = [mention("כללית", "header"), mention("מכבי", "header")]
    d = decide_sender(ms, M)
    assert d.value is None
    assert F_CONFLICT in d.flags


def test_handwritten_only_is_orange():
    d = decide_sender([mention("מכבי", "handwritten")], M)
    assert d.value == "מכבי"
    assert F_HANDWRITTEN in d.flags


def test_unknown_sender_is_other_and_orange():
    d = decide_sender([mention("מרפאת השלום הכחולה")], M)
    assert d.value == OTHER
    assert F_UNKNOWN_SENDER in d.flags
    assert d.alternatives == ["מרפאת השלום הכחולה"]


def test_unknown_destination_only_is_ignored():
    assert decide_sender([mention("מקום כלשהו", "header", "destination")], M).value is None


def test_no_mentions():
    assert decide_sender([], M).value is None


# ---------- כללי קדימות R1 ו-R2 (אזכורים אמיתיים מחלק 1) ----------

def test_page_26_institution_beats_hmo_without_logo():
    """עמוד 26: המודל סימן את שמיר "יעד" ואת "קופ"ח: מאוחדת" (שדה בתווית המטופל) "שולח"."""
    ms = [
        mention("המרכז הרפואי שמיר (אסף הרופא) אגף המעבדות", "header", "destination", 0.99),
        mention("מאוחדת", "header", "sender", 0.95),
        mention("מרכז רפואי שמיר (אסף הרופא)", "stamp", "destination", 0.95),
    ]
    d = decide_sender(ms, M)
    assert d.value == "המרכז הרפואי שמיר"
    assert d.flags == [F_CONFLICT]                      # נדרסה קופה שאזכורה "שולח": כתום
    assert d.alternatives == ["מאוחדת"]                 # המועמד שנדרס נשמר


def test_page_24_logo_beats_header_regardless_of_role():
    """עמוד 24: לוגו המרכז הלאומי לרפואה משפטית סומן "יעד", ושיבא (כותרת) סומנה "שולח"."""
    ms = [
        mention("MINISTRY OF HEALTH The National Center of Forensic Medicine", "logo", "destination"),
        mention("משרד הבריאות המרכז הלאומי לרפואה משפטית", "logo", "destination"),
        mention('מעבדת נגיפים ביה"ח ע"ש שיבא, תל השומר', "header", "sender"),
    ]
    d = decide_sender(ms, M)
    assert d.value == "המרכז הלאומי לרפואה משפטית"
    assert d.flags == [F_CONFLICT]
    assert d.alternatives == ["מרכז רפואי שיבא"]


def test_page_1_unchanged_hmo_logo_with_lab_stamp():
    ms = [mention("מאוחדת", "logo", "sender"),
          mention("המעבדה המרכזית לנגיפים המרכז הרפואי המשולב", "stamp", "destination")]
    d = decide_sender(ms, M)
    assert d.value == "מאוחדת" and d.flags == [] and d.alternatives == []


def test_page_10_unchanged_hmo_logo_with_sheba_header_as_destination():
    """שיבא כיעד בלבד (ניקוד נמוך) נדרסת, נשמרת בחלופות, ולא יוצרת כתום."""
    ms = [mention("מכבי", "logo", "sender"), mention('בי"ח תל השומר ע"ש שיבא', "header", "destination")]
    d = decide_sender(ms, M)
    assert d.value == "מכבי" and d.flags == []
    assert d.alternatives == ["מרכז רפואי שיבא"]


def test_page_15_unchanged_institution_logo_with_sheba_destination_twice():
    ms = [mention('רמב"ם', "logo", "sender"), mention("שיבא תל השומר", "header", "destination"),
          mention('רמב"ם', "header", "sender"), mention("שיבא", "stamp", "destination")]
    d = decide_sender(ms, M)
    assert d.value == 'רמב"ם' and d.flags == []


def test_r1_does_not_apply_when_hmo_has_logo():
    ms = [mention("מכבי", "logo", "sender"), mention("הלל יפה", "header", "destination"),
          mention("הלל יפה", "stamp", "destination")]
    d = decide_sender(ms, M)
    assert d.value == "מכבי"                             # הלוגו מנצח; R1 לא דורס קופה שיש לה לוגו
    assert d.flags == [F_CONFLICT]                      # שני אזכורים של מוסד אחר = אי-הסכמה אמיתית (ניקוד >= חצי)
    assert d.alternatives == ["מרכז רפואי הלל יפה"]


def test_r1_needs_a_strong_institution_not_a_single_weak_mention():
    ms = [mention("מכבי", "header", "sender"), mention("הלל יפה", "header", "destination")]
    d = decide_sender(ms, M)
    assert d.value == "מכבי" and d.flags == []           # מוסד באזכור יחיד: לא דורס


def test_r1_institution_logo_beats_hmo_header():
    ms = [mention("לאומית", "header", "sender"), mention("הלל יפה", "logo", "sender")]
    d = decide_sender(ms, M)
    assert d.value == "מרכז רפואי הלל יפה" and d.flags == [F_CONFLICT] and d.alternatives == ["לאומית"]


def test_two_institutions_without_logo_use_normal_scoring():
    ms = [mention("הלל יפה", "header", "sender"), mention("שניידר", "header", "destination")]
    d = decide_sender(ms, M)
    assert d.value == "מרכז רפואי הלל יפה" and d.alternatives == ["מרכז רפואי שניידר"]


def test_hmos_are_defined_in_config():
    assert M.hmos == {"כללית", "מכבי", "מאוחדת", "לאומית"}


def test_learned_alias_from_config(tmp_path):
    (tmp_path / "senders.json").write_text(
        json.dumps({"canonical": {"כללית": []}, "branches": {}, "lab_names": []}, ensure_ascii=False), encoding="utf-8")
    assert decide_sender([mention("מרפאת ארבל")], load_matcher(tmp_path)).value == OTHER
    senders.add_alias("ארבל", "כללית", tmp_path)
    assert decide_sender([mention("מרפאת ארבל")], load_matcher(tmp_path)).value == "כללית"
