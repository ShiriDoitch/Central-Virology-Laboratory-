"""ניגודיות הטקסט בממשק (WCAG AA, 4.5:1): כל טקסט של כפתור, תג, גלולה ומדד נבדק מול הרקע שהוא יושב עליו.
הצבעים נקראים מתוך src/ui_theme.CSS עצמו, ולכן שינוי גוון שמפיל טקסט מתחת ל-4.5:1 מפיל בדיקה.

מהכשל שתוקן ב-21.10.2026 (כפתור "עבד" ו"הורד אקסל" בשרת המוארח): Streamlit עוטף את תווית הכפתור ב-<p>
שיש לו הצהרת color משל עצמו (כלל הטיפוגרפיה בסעיף 2 של ה-CSS), והצהרה על האלמנט גוברת תמיד על צבע
שנורש מההורה. לכן "color: #fff" על הכפתור הראשי לא הגיע לטקסט, והטקסט הכהה נשאר על הטורקיז הכהה:
2.26:1 במצב רגיל ו-1.74:1 במעבר עכבר. test_button_label_inherits_the_button_colour שומר על התיקון."""
import re
from pathlib import Path

from src import ui_theme as ui

AA = 4.5
TOKENS = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", ui.CSS))


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    """בהירות יחסית לפי WCAG 2.1."""
    h = color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


COMMENT = re.compile(r"/\*.*?\*/", re.S)


def rules() -> list[tuple[str, str]]:
    """ה-CSS כרשימת (בורר, גוף), כדי לבדוק כלל ולא רק הימצאות טקסט. ההערות מוסרות קודם: בלעדי זה
    ההערה שלפני כלל נדבקת לבורר הראשון ברשימה, והבדיקה "מפספסת" אותו."""
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^}]*)\}", COMMENT.sub("", ui.CSS))]


def pairs() -> list[tuple[str, str, str]]:
    """(מה זה, צבע הטקסט, צבע הרקע) לכל טקסט שמוצג על משטח צבעוני בממשק."""
    t, out = TOKENS, []
    out += [
        ("כפתור ראשי, רגיל ובמיקוד", t["on-accent"], t["accent"]),
        ("כפתור ראשי, מעבר עכבר", t["on-accent"], t["accent-hover"]),
        ("כפתור ראשי, מושבת", t["on-accent"], t["accent-muted"]),
        ("כפתור משני, רגיל", t["ink"], t["paper"]),
        ("כפתור משני, מעבר עכבר", t["accent"], t["paper"]),
        ("כפתור משני, מושבת", t["ink-disabled"], t["wash"]),
        ("גלולת הצעה בפאנל הפירוט", t["accent-ink"], t["accent-soft"]),
        ("גלולת הצעה, מעבר עכבר", t["accent-ink"], "#DCE8EA"),
        ("מונה רשומות, לא נבחר", t["ink-2"], t["wash"]),
        ("תג סינון פעיל", t["accent-ink"], t["accent-soft"]),
        ("גלולת סינון \"הכול\", לא נבחרת", t["ink-2"], t["wash"]),
        ("גלולת סינון \"הכול\", נבחרת", t["on-accent"], t["accent"]),
        ("גלולת סינון \"ריק\", לא נבחרת", t["ink-3"], t["paper"]),
        ("שורה שקטה על רקע בהיר", t["ink-3"], t["wash"]),
    ]
    for state in ui.STATES:
        out += [
            (f"תג מצב {state}", ui.STATE_INK[state], ui.STATE_FILL[state]),
            (f"מילת מצב {state} על רקע הדף", ui.STATE_INK[state], t["canvas"]),
            (f"תא טבלה {state}", ui.STATE_INK[state], ui.PAPER),
            (f"מספר בפס המדדים, {state}", ui.STATE_INK[state], ui.PAPER),
            (f"גלולת סינון {state}, נבחרת", t["on-accent"], ui.STATE_INK[state]),
        ]
    return out


def test_every_button_and_badge_text_meets_wcag_aa():
    low = [(name, fg, bg, round(contrast(fg, bg), 2)) for name, fg, bg in pairs() if contrast(fg, bg) < AA]
    assert low == []


def test_no_rule_dims_text_with_opacity():
    """opacity על טקסט מערבב אותו עם הרקע ומוריד את היחס (opacity: .8 על ספירת הגלולה ירד ל-3.85 עד 4.12)."""
    dimmed = [sel for sel, body in rules() if re.search(r"(?<!-)\bopacity:\s*(0|\.\d|0\.\d)", body)]
    assert dimmed == []


# ============================================================
# ביקורת הכפתורים: כל סוג כפתור שהאפליקציה מרנדרת, בכל מצב
# ============================================================
# Streamlit שם data-testid="stBaseButton-<סוג>" על אלמנט ה-button עצמו (popover שם testid משלו). העוטף
# (.stButton / .stDownloadButton / .stFormSubmitButton / .stPopover) שונה לכל סוג, ולכן כלל שנכתב לעוטף
# אחד אינו חל על האחרים - וכך נשארה תווית "אישור · Enter" (כפתור שליחת טופס) כהה על הטורקיז הכהה.
# הבדיקות כאן פותרות את ה-CSS כמו דפדפן (important, אחריו ספציפיות, אחריו סדר הקובץ) ובודקות את הזוג
# צבע-טקסט / רקע שיוצא לכל סוג ולכל מצב. התכונה kind אינה קיימת ב-DOM בגרסה הזאת, ולכן בורר שמסתמך
# עליה בלבד אינו נספר כאן (הוא נשאר ב-CSS לגרסה שתחזיר אותה).
BUTTON_TESTIDS = {
    "stBaseButton-primary": 'st.button(type="primary"), st.download_button(type="primary")',
    "stBaseButton-primaryFormSubmit": 'st.form_submit_button(type="primary"): "אישור · Enter"',
    "stBaseButton-secondary": "st.button(), st.download_button()",
    "stBaseButton-secondaryFormSubmit": 'st.form_submit_button(): "הערך אושר"',
    "stBaseButton-segmented_control": "st.segmented_control: פריט שאינו נבחר",
    "stBaseButton-segmented_controlActive": "st.segmented_control: הפריט הנבחר",
    "stPopoverButton": "st.popover: הכפתור שפותח את התפריט",
}
STATES = ("", ":hover", ":focus-visible", ":active", ":disabled")
STATE_PSEUDOS = {"hover", "active", "disabled", "focus", "focus-visible"}
TEAL_TOKENS = {"accent", "accent-hover", "accent-ink", "accent-muted"}
ANY_ATTR = re.compile(r"\[[^\]]+\]")
TESTID_ATTR = re.compile(r'\[data-testid(?P<op>[\^*$]?=)"(?P<val>[^"]*)"\]')
NOT_PART = re.compile(r":not\(([^)]*)\)")
PSEUDO = re.compile(r":(?!not\()([a-z-]+)")
LABEL_TAGS = ("p", "div", "span", '[data-testid="stMarkdownContainer"]')


def _attr_matches(op: str, value: str, testid: str) -> bool:
    return {"=": testid == value, "^=": testid.startswith(value),
            "*=": value in testid, "$=": testid.endswith(value)}[op]


def matches(part: str, testid: str, state: str = "") -> bool:
    """האם בורר אחד (בלי צירוף יורש) חל על הכפתור הזה במצב הזה."""
    part = part.strip()
    if not part or " " in part or ">" in part:
        return False                                  # בורר של אלמנט פנימי (התווית), לא של הכפתור
    core = NOT_PART.sub("", part)
    attrs = TESTID_ATTR.findall(core)
    if not attrs or not all(_attr_matches(op, val, testid) for op, val in attrs):
        return False
    for inner in NOT_PART.findall(part):              # החרגה שחלה = הבורר אינו חל
        excluded = TESTID_ATTR.findall(inner)
        if excluded and all(_attr_matches(op, val, testid) for op, val in excluded):
            return False
    pseudos = set(PSEUDO.findall(core)) & STATE_PSEUDOS
    if not pseudos:
        return True                                   # בלי פסאודו של מצב: חל בכל המצבים
    return bool(state) and pseudos == {state.lstrip(":")}


def specificity(part: str) -> int:
    return len(ANY_ATTR.findall(part)) + len(PSEUDO.findall(part))


def resolved(prop: str, testid: str, state: str = "") -> str | None:
    """ההצהרה המנצחת של התכונה על הכפתור: !important קודם, אחריו ספציפיות, ואחריה סדר הקובץ."""
    best, winner = None, None
    for i, (sel, body) in enumerate(rules()):
        for part in sel.split(","):
            if not matches(part, testid, state):
                continue
            for m in re.finditer(rf"(?:^|;)\s*{prop}:\s*([^;]+)", body):
                raw = m.group(1).strip()
                rank = (1 if "!important" in raw else 0, specificity(part), i)
                if best is None or rank > best:
                    best, winner = rank, raw.replace("!important", "").strip()
    return winner


def token_colour(value: str | None) -> str | None:
    """הופך "var(--accent)" או "#RRGGBB" לצבע ממשי; אסימון שאינו מוכר מחזיר None."""
    if not value:
        return None
    name = re.fullmatch(r"var\(--([a-z0-9-]+)\)", value.strip())
    if name:
        return TOKENS.get(name.group(1))
    return value.strip() if re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()) else None


def token_name(value: str | None) -> str | None:
    name = re.fullmatch(r"var\(--([a-z0-9-]+)\)", (value or "").strip())
    return name.group(1) if name else None


def test_every_button_type_declares_a_readable_pair_in_every_state():
    """לכל סוג כפתור ולכל מצב (רגיל, מעבר עכבר, מיקוד, לחיצה, מושבת): יש צבע טקסט ורקע מוצהרים,
    והיחס ביניהם 4.5:1 לפחות. כאן נבדק גם כפתור שליחת הטופס, שלא היה מכוסה כלל."""
    bad = []
    for testid, where in BUTTON_TESTIDS.items():
        for state in STATES:
            fg, bg = resolved("color", testid, state), resolved("background", testid, state)
            fg_hex, bg_hex = token_colour(fg), token_colour(bg)
            if not fg_hex or not bg_hex:
                bad.append((testid, state or "רגיל", where, "חסר צבע או רקע", fg, bg))
            elif contrast(fg_hex, bg_hex) < AA:
                bad.append((testid, state or "רגיל", where, round(contrast(fg_hex, bg_hex), 2), fg, bg))
    assert bad == [], bad


def test_no_dark_teal_button_gets_a_dark_label():
    """הכשל מהכיוון ההפוך: כפתור שהרקע שלו טורקיז כהה חייב תווית לבנה (--on-accent) ומודגשת."""
    for testid in BUTTON_TESTIDS:
        for state in STATES:
            if token_name(resolved("background", testid, state)) in TEAL_TOKENS:
                assert resolved("color", testid, state) == "var(--on-accent)", (testid, state)
                assert resolved("font-weight", testid, state) == "700", (testid, state)


def test_every_button_label_inherits_the_colour_of_its_button():
    """התווית בתוך הכפתור (<p> בתוך stMarkdownContainer) חייבת לרשת את צבע הכפתור בכל סוג כפתור.
    בלי זה כלל הטיפוגרפיה של סעיף 2 צובע אותה כהה גם על רקע כהה (2.26:1): זה היה הכשל של
    "אישור · Enter", שכלל ה-inherit נכתב ל-.stButton ולכן לא חל על הכפתור שבתוך st.form."""
    for testid in BUTTON_TESTIDS:
        covering = []
        for sel, body in rules():
            if "color: inherit" not in body or "!important" not in body:
                continue
            for part in sel.split(","):
                pieces = part.strip().split()
                if len(pieces) > 1 and pieces[-1] in LABEL_TAGS and matches(pieces[0], testid):
                    covering.append(part.strip())
        assert covering, testid


BUTTON_WIDGETS = {"st.button", "st.download_button", "st.form_submit_button", "st.popover", "st.segmented_control"}
BUTTON_LIKE = BUTTON_WIDGETS | {"st.link_button", "st.pills", "st.feedback", "st.page_link"}
UI_FILES = ("app.py", "records_screen.py", "review_screen.py", "evidence_view.py")


def test_no_button_widget_in_the_app_is_left_out_of_the_audit():
    """אם נוסף לממשק סוג כפתור שאינו ברשימה (st.link_button, st.pills...), הבדיקה נכשלת עד שמוסיפים
    לו כלל ב-src/ui_theme.py ושורה ב-BUTTON_TESTIDS."""
    root = Path(__file__).resolve().parent.parent
    found = set()
    for name in UI_FILES:
        found |= {w for w in re.findall(r"st\.[a-z_]+", (root / name).read_text(encoding="utf-8")) if w in BUTTON_LIKE}
    assert found <= BUTTON_WIDGETS, found - BUTTON_WIDGETS
    assert "st.form_submit_button" in found, "כפתור שליחת הטופס חייב להישאר מכוסה"
