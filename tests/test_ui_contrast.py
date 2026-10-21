"""ניגודיות הטקסט בממשק (WCAG AA, 4.5:1): כל טקסט של כפתור, תג, גלולה ומדד נבדק מול הרקע שהוא יושב עליו.
הצבעים נקראים מתוך src/ui_theme.CSS עצמו, ולכן שינוי גוון שמפיל טקסט מתחת ל-4.5:1 מפיל בדיקה.

מהכשל שתוקן ב-21.10.2026 (כפתור "עבד" ו"הורד אקסל" בשרת המוארח): Streamlit עוטף את תווית הכפתור ב-<p>
שיש לו הצהרת color משל עצמו (כלל הטיפוגרפיה בסעיף 2 של ה-CSS), והצהרה על האלמנט גוברת תמיד על צבע
שנורש מההורה. לכן "color: #fff" על הכפתור הראשי לא הגיע לטקסט, והטקסט הכהה נשאר על הטורקיז הכהה:
2.26:1 במצב רגיל ו-1.74:1 במעבר עכבר. test_button_label_inherits_the_button_colour שומר על התיקון."""
import re

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


def rules() -> list[tuple[str, str]]:
    """ה-CSS כרשימת (בורר, גוף), כדי לבדוק כלל ולא רק הימצאות טקסט."""
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^}]*)\}", ui.CSS)]


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


def test_button_label_inherits_the_button_colour():
    """התווית חייבת לרשת את צבע הכפתור. בלי הכלל הזה כל צבע שנקבע לכפתור לא מגיע לטקסט שלו."""
    bodies = [body for sel, body in rules()
              if '.stButton > button [data-testid="stMarkdownContainer"] p' in sel and "color: inherit" in body]
    assert bodies, "חסר כלל שמחזיר את תווית הכפתור לצבע הכפתור"
    assert all("!important" in body for body in bodies), "הכלל של <p> בסעיף 2 גובר בלי !important"


def test_primary_button_text_is_white_and_bold_in_every_state():
    """רגיל, מעבר עכבר, מיקוד, לחיצה ומושבת: לבן על טורקיז, ומודגש."""
    primary = [(sel, body) for sel, body in rules() if 'kind="primary"' in sel or "stBaseButton-primary" in sel]
    assert any("font-weight: 700" in body for _, body in primary)
    for state in ("", ":hover", ":focus", ":focus-visible", ":active", ":disabled"):
        matching = [body for sel, body in primary if f'button[kind="primary"]{state}' in sel]
        assert matching, state
        assert all("var(--on-accent)" in body for body in matching), state


def test_no_rule_dims_text_with_opacity():
    """opacity על טקסט מערבב אותו עם הרקע ומוריד את היחס (opacity: .8 על ספירת הגלולה ירד ל-3.85 עד 4.12)."""
    dimmed = [sel for sel, body in rules() if re.search(r"(?<!-)\bopacity:\s*(0|\.\d|0\.\d)", body)]
    assert dimmed == []
