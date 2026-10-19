"""התאמת גורם שולח: מילים מבדילות בלבד בבדיקת שם המעבדה ובהתאמה המקורבת (fuzzy), כינויים דו-משמעיים, והמוסדות שנוספו מרשימת החבר.
בלי API. הרשימה עצמה: config/senders.json."""
import json
from pathlib import Path

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


# ---------- שלב 3: המוסדות שנוספו מרשימת החבר ----------

NEW_INSTITUTIONS = [   # השם הקנוני בדיוק כפי שנכתב ברשימה
    "מרכז רפואי קפלן", "המרכז הרפואי יוספטל", "בית החולים אוגוסטה ויקטוריה", "בית החולים סנט ג'וזף", "בית החולים אל-מקאסד",
    "לניאדו - מרכז רפואי צאנז", "מרכז רפואי מעיני הישועה", "בית החולים האיטלקי (חיפה)", "בית החולים נצרת (האנגלי)",
    'בית החולים המשפחה ה"קדושה" (האיטלקי)', "בית החולים סן ונסן דה פול (הצרפתי)", "הרצליה מדיקל סנטר", "בית החולים אלישע",
    "בית החולים רפאל", "משגב לדך", "מרכז רפואי בני ציון",
]
ITALIAN_HAIFA, HOLY_FAMILY = "בית החולים האיטלקי (חיפה)", 'בית החולים המשפחה ה"קדושה" (האיטלקי)'
CONFIG = json.loads(Path("config/senders.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", NEW_INSTITUTIONS)
def test_new_institutions_are_recognized_by_their_exact_list_name(name):
    assert name in M.canonical
    assert M.match(name) == (name, False)
    d = decide_sender([mention(name, "header")], M)
    assert d.value == name and not d.uncertain


def test_ziv_and_galilee_variants_from_the_list_map_to_existing_entries():
    assert M.match("המרכז הרפואי זיו")[0] == "מרכז רפואי זיו"
    assert M.match("המרכז הרפואי לגליל")[0] == "מרכז רפואי הגליל"
    assert M.match("בית החולים זיו")[0] == "מרכז רפואי זיו"


def test_existing_canonical_names_were_not_renamed():
    for name in ("כללית", "מכבי", "מאוחדת", "לאומית", 'רמב"ם', "מרכז רפואי כרמל", "מרכז רפואי שערי צדק", "מרכז רפואי צפון פוריה",
                 "המרכז הרפואי שמיר", 'המרכז הרפואי הגריאטרי ביה"ח שמואל הרופא', "המרכז הלאומי לרפואה משפטית", 'רוזנבלט מעבדה רפואית בע"מ',
                 "הרשות הפלסטינאית", 'צה"ל חיל הרפואה', "משרד הביטחון", "מרכז רפואי הלל יפה", "מרכז רפואי שניידר"):
        assert name in M.canonical, name


def test_laniado_and_sanz_are_one_entry():
    canon = "לניאדו - מרכז רפואי צאנז"
    for text in ("לניאדו", "צאנז", "מרכז רפואי לניאדו", "בית החולים לניאדו", "מרכז רפואי צאנז", canon):
        assert M.match(text)[0] == canon, text
    assert len([c for c in M.canonical if "לניאדו" in c or "צאנז" in c]) == 1


def test_one_canonical_entry_for_all_assuta_sites():
    assert [c for c in M.canonical if "אסותא" in c] == ["מרכז רפואי אסותא"]
    for site in ("בית החולים האוניברסיטאי אסותא אשדוד", "בית החולים אסותא רמת החייל", "המרכז הרפואי אסותא רעננה", "אסותא חיפה"):
        assert M.match(site)[0] == "מרכז רפואי אסותא"


@pytest.mark.parametrize("text,expected", [
    ("בית החולים האיטלקי בחיפה", ITALIAN_HAIFA), ("האיטלקי חיפה", ITALIAN_HAIFA), ("Italian Hospital Haifa", ITALIAN_HAIFA),
    ("המשפחה הקדושה", HOLY_FAMILY), ("בית החולים המשפחה הקדושה", HOLY_FAMILY), ("האיטלקי נצרת", HOLY_FAMILY),
])
def test_italian_hospitals_in_haifa_and_nazareth_are_two_separate_entries(text, expected):
    assert M.match(text)[0] == expected
    assert decide_sender([mention(text, "header")], M).value == expected


@pytest.mark.parametrize("text", ["האיטלקי", "בית חולים איטלקי", "בית החולים האיטלקי", 'בי"ח איטלקי', "Italian Hospital"])
@pytest.mark.parametrize("where", ["header", "logo", "stamp", "handwritten"])
def test_italian_without_a_city_matches_neither_and_is_unknown_orange(text, where):
    assert M.match(text, trusted=True) == (None, False)
    assert M.fuzzy(text, trusted=True) is None
    d = decide_sender([mention(text, where)], M)
    assert d.value == OTHER and F_UNKNOWN_SENDER in d.flags and d.uncertain


# ---------- שמות פרטיים / משפחה שהם גם שמות בתי חולים ----------

FIRST_NAME_HOSPITALS = ["אלישע", "רפאל", "קפלן", "זיו", "הלל", "מאיר"]


def test_first_name_hospitals_have_no_bare_alias():
    for word in FIRST_NAME_HOSPITALS:
        assert M.match(word, trusted=True)[0] is None, word                     # גם בלוגו / כותרת: אין התאמה לשם בודד
        for canon, aliases in CONFIG["canonical"].items():
            assert word not in aliases and word != canon, (word, canon)


@pytest.mark.parametrize("word", FIRST_NAME_HOSPITALS)
@pytest.mark.parametrize("template", ['ד"ר {w} כהן', "שם המטופל: {w} לוי", "רחוב {w} 12 תל אביב"])
@pytest.mark.parametrize("where", ["clinic_or_doctor", "other", "handwritten", "header"])
def test_first_name_hospitals_do_not_match_people_or_streets(word, template, where):
    d = decide_sender([mention(template.format(w=word), where)], M)
    assert d.value in (None, OTHER)


@pytest.mark.parametrize("text,expected", [
    ("בית החולים אלישע", "בית החולים אלישע"), ("מרכז רפואי רפאל", "בית החולים רפאל"), ("המרכז הרפואי קפלן", "מרכז רפואי קפלן"),
    ("המרכז הרפואי זיו", "מרכז רפואי זיו"), ("מרכז רפואי הלל יפה", "מרכז רפואי הלל יפה"), ("מרכז רפואי מאיר", "מרכז רפואי מאיר"),
])
def test_first_name_hospitals_match_with_an_institution_keyword(text, expected):
    assert decide_sender([mention(text, "other")], M).value == expected


# ---------- שלב 4: כינויים דו-משמעיים ----------

AMBIGUOUS_WITH_ALIAS = ["כרמל", "כללית", "לאומית", "רבין", "השרון", "נהריה", "פוריה", "הדסה", "בילינסון", "סורוקה", "ברזילי"]
UNTRUSTED = ["clinic_or_doctor", "other", "handwritten"]
SENTENCES = ['ד"ר {w} כהן, רופא מומחה', "שם המטופל: {w} לוי", "רחוב {w} 12 תל אביב", "בדיקה {w} לפי הנחיות"]


def test_the_ambiguous_list_in_the_config_is_complete():
    assert set(AMBIGUOUS_WITH_ALIAS + FIRST_NAME_HOSPITALS) <= set(CONFIG["ambiguous"])
    assert set(FIRST_NAME_HOSPITALS) == set(CONFIG["keyword_required"])           # אלו דורשים מילת מפתח גם בלוגו / כותרת


def test_a_prefixed_clalit_in_a_logo_is_still_a_noisy_clalit():
    assert decide_sender([mention("מכללית", "logo")], M).value == "כללית"          # "מכללית" = "מהכללית": התאמה מקורבת (כתומה), לא התאמה שגויה


@pytest.mark.parametrize("word", AMBIGUOUS_WITH_ALIAS)
@pytest.mark.parametrize("template", SENTENCES)
@pytest.mark.parametrize("where", UNTRUSTED)
def test_ambiguous_alias_used_as_a_doctor_patient_or_street_is_not_a_match(word, template, where):
    text = template.format(w=word)
    assert M.match(text, trusted=False)[0] is None
    d = decide_sender([mention(text, where)], M)
    assert d.value == OTHER and F_UNKNOWN_SENDER in d.flags                       # לא מוכר: "אחר", כתום. לא בית חולים / קופה בטעות


@pytest.mark.parametrize("word", AMBIGUOUS_WITH_ALIAS)
@pytest.mark.parametrize("where", ["logo", "header", "stamp"])
def test_ambiguous_alias_alone_matches_when_the_mention_is_a_logo_header_or_stamp(word, where):
    d = decide_sender([mention(word, where)], M)
    assert d.value not in (None, OTHER)


@pytest.mark.parametrize("word", AMBIGUOUS_WITH_ALIAS)
@pytest.mark.parametrize("keyword", ["קופת חולים", "מרכז רפואי", "בית החולים", 'ביה"ח', "המרכז הרפואי"])
def test_ambiguous_alias_matches_with_an_institution_keyword_even_when_not_a_logo(word, keyword):
    expected = M.match(word, trusted=True)[0]
    d = decide_sender([mention(f"{keyword} {word}", "other")], M)
    assert d.value == expected


@pytest.mark.parametrize("text", ["כרמלי", "כרמלית", "הכרמלים", "רבינוביץ", "בילינסונית"])
def test_ambiguous_alias_inside_a_longer_word_never_matches_even_in_a_logo(text):
    assert decide_sender([mention(text, "logo")], M).value == OTHER


def test_trusted_flag_is_decided_in_decide_sender_from_where():
    assert M.match("כרמל") == (None, False)                         # match() לבדו מקבל טקסט בלבד: ברירת מחדל לא מהימן
    assert M.match("כרמל", trusted=True)[0] == "מרכז רפואי כרמל"
    assert decide_sender([mention("כרמל", "stamp")], M).value == "מרכז רפואי כרמל"
    assert decide_sender([mention("כרמל", "clinic_or_doctor")], M).value == OTHER


def test_non_ambiguous_aliases_are_unchanged():
    for text, canon in (("מאוחדת", "מאוחדת"), ("שיבא", "מרכז רפואי שיבא"), ("מכבי", "מכבי"), ("אסותא", "מרכז רפואי אסותא")):
        assert decide_sender([mention(text, "handwritten")], M).value == canon


def test_branch_evidence_check_follows_the_same_guard():
    assert M.is_branch("רבין", trusted=True) and not M.is_branch("רבין")
    assert M.is_branch("מרכז רפואי רבין")


def test_bare_hmo_name_in_the_patient_insurer_field_still_counts():
    for hmo in ("כללית", "לאומית"):
        d = decide_sender([mention(hmo, "patient_field", "unknown")], M)
        assert d.value == hmo and d.flags == []                       # שדה "קופה" בתיבת המטופל: מהימן, כמו לפני ההגבלה
    assert decide_sender([mention("כרמל", "patient_field", "unknown")], M).value == "מרכז רפואי כרמל"
