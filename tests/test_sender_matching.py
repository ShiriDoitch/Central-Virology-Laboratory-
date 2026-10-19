"""התאמת גורם שולח: מילים מבדילות בלבד בבדיקת שם המעבדה ובהתאמה המקורבת (fuzzy), כינויים דו-משמעיים, והמוסדות שנוספו מרשימת החבר.
בלי API. הרשימה עצמה: config/senders.json."""
import pytest

from src.schema import SenderMention
from src.senders import F_FUZZY_MATCH, F_UNKNOWN_SENDER, OTHER, SenderMatcher, decide_sender, load_matcher

M = load_matcher()
LABS = ["המעבדה המרכזית לנגיפים", "המרכז הרפואי המשולב"]


def mention(text, where="header", role="sender", conf=1.0):
    return SenderMention(text=text, where=where, role=role, confidence=conf)


def bare_matcher(**canonical):
    """מתאם קטן בלי כינויים מהקובץ: בודק את הלוגיקה עצמה."""
    return SenderMatcher(canonical or {"מרכז רפואי וולפסון": ["וולפסון"]}, {}, LABS)


# ---------- שלב 1: שם המעבדה מול מוסד עם אותן מילים גנריות ----------

@pytest.mark.parametrize("text", ["המרכז הרפואי זיו", "המרכז הרפואי יוספטל", "מרכז רפואי בני ציון", "המרכז הרפואי כרמל", "בית החולים אלישע"])
def test_generic_words_shared_with_the_lab_name_do_not_make_an_institution_the_lab(text):
    assert bare_matcher().match(text)[1] is False


@pytest.mark.parametrize("text", ["המרכז הרפואי המטולב", "המטולב", "מרכז רפואי המשולב", "המרכז הרפואי המשלוב"])
def test_noisy_lab_spellings_are_still_the_lab(text):
    assert bare_matcher().match(text) == (None, True)


def test_exact_lab_names_and_generic_only_text_behave_as_before():
    m = bare_matcher()
    assert m.match("המעבדה המרכזית לנגיפים") == (None, True)
    assert m.match("המרכז הרפואי המשולב") == (None, True)
    assert m.match("המרכז הרפואי") == (None, False)       # טקסט גנרי בלבד: אין מידע, כמו קודם (השוואה מלאה למעבדה, מתחת לסף)


def test_ziv_is_a_sender_not_the_lab_with_the_real_config():
    assert M.match("המרכז הרפואי זיו") == ("מרכז רפואי זיו", False)
    d = decide_sender([mention("המרכז הרפואי זיו", "header")], M)
    assert d.value == "מרכז רפואי זיו" and not d.uncertain


def test_real_lab_stamp_with_noise_is_still_excluded_end_to_end():
    ms = [mention("כללית", "logo", "destination"), mention("המרכז הרפואי המטולב", "stamp", "sender")]
    assert decide_sender(ms, M).value == "כללית"


# ---------- שלב 2: fuzzy על מילים מבדילות ----------

def test_bnei_zion_does_not_fuzzy_match_ziv():
    m = bare_matcher(**{"מרכז רפואי זיו": ["זיו צפת"]})
    assert m.fuzzy("מרכז רפואי בני ציון") is None
    assert m.match("מרכז רפואי בני ציון") == (None, False)
    d = decide_sender([mention("מרכז רפואי בני ציון", "header")], m)
    assert d.value == OTHER and F_UNKNOWN_SENDER in d.flags          # לא מוכר: "אחר", כתום


def test_generic_words_alone_never_create_a_fuzzy_match():
    m = bare_matcher(**{"מרכז רפואי זיו": ["זיו צפת"], "מרכז רפואי קפלן": ["קפלן רחובות"]})
    for text in ("מרכז רפואי", "בית החולים", "המרכז הרפואי הדסה"):
        assert m.fuzzy(text) is None


def test_real_noisy_institution_spelling_still_fuzzy_matches_and_is_orange():
    m = bare_matcher()
    assert m.fuzzy("מרכז רפואי וולפסו") == "מרכז רפואי וולפסון"
    d = decide_sender([mention("מרכז רפואי וולפסו", "header")], m)
    assert d.value == "מרכז רפואי וולפסון" and F_FUZZY_MATCH in d.flags


def test_fuzzy_ignores_ambiguous_aliases_without_keyword_or_trusted_mention():
    m = SenderMatcher({"מרכז רפואי בילינסון": ["בילינסון"]}, {}, LABS, ambiguous=["בילינסון"])
    assert m.fuzzy("דר בילינסוו כהן") is None                                   # שם משפחה בכתיב רועש
    assert m.fuzzy("בילינסוו", trusted=True) == "מרכז רפואי בילינסון"             # אותו טקסט כלוגו / כותרת / חותמת
    assert m.fuzzy("מרכז רפואי בילינסוו") == "מרכז רפואי בילינסון"                # או עם מילת מפתח
