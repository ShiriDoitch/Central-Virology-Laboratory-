"""טקסט שמקורו בטופס (קריאת מודל או הקלדה) לא הופך לתגית HTML, קישור או תמונה בממשק (app.py, src/confirm.py)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.confirm import flag_chips_html, md_code, md_text, zoom_html

PAYLOAD = "<img src=x onerror=alert(1)>"
BS = "\\"
APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_flag_chips_escape_html():
    out = flag_chips_html([PAYLOAD, "רגיל"])
    assert "<img" not in out and "&lt;img src=x onerror=alert(1)&gt;" in out
    assert out.count("<span class='flag'>") == 2       # רק התגיות שאנחנו כתבנו


def test_md_text_neutralizes_tags_links_images_and_code_spans():
    out = md_text(f"{PAYLOAD} ![x](http://evil/p.png) [l](javascript:alert(1)) `c`")
    assert f"{BS}<img" in out
    assert f"{BS}!{BS}[x{BS}]{BS}(" in out and f"{BS}[l{BS}]{BS}(" in out
    assert f"{BS}`c{BS}`" in out
    assert md_text("דנה 18.06.2026 11223344") == "דנה 18.06.2026 11223344"      # עברית, ספרות ונקודות לא משתנות


def test_md_code_cannot_close_the_span():
    out = md_code("12`<img src=x>")
    assert out.startswith("`") and out.endswith("`") and out.count("`") == 2


def test_zoom_html_contains_only_base64_and_numbers():
    html = zoom_html(b"\xff\xd8abc", 200)
    assert html.count("<img") == 1 and "base64," in html


@pytest.mark.skipif(not Path("outputs/clean_part1_v4b").exists() or not Path("data/clean_part1.pdf").exists(),
                    reason="needs the saved sample run")
def test_app_renders_hostile_name_as_literal_text_not_a_tag():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    next(b for b in at.button if "דוגמה" in b.label).click().run()
    at.session_state["name_overrides"] = {(1, "first_name"): PAYLOAD}      # שם חופשי שהוקלד / שנקרא מהטופס
    at.session_state["selected_cell"] = (0, "שם פרטי")
    at.run()
    assert not at.exception
    shown = [e.value for group in (at.markdown, at.success, at.info, at.warning) for e in group]
    hostile = [v for v in shown if "onerror" in v]
    assert hostile, "the value should be displayed somewhere"
    assert all(v.count("<img") == v.count(BS + "<img") for v in hostile), hostile      # כל "<" עבר escape, אין תגית חשופה
