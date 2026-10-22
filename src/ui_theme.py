"""העיצוב של הממשק במקום אחד: אסימוני עיצוב (מרווחים, מדרג גופן, צבעים נייטרליים), בלוק CSS אחד שמוזרק פעם אחת ב-app.py,
ועזרי HTML קטנים (תג מצב, נקודה + מילה, ערך לקריאה בלבד).

תצוגה בלבד. אין כאן שום כלל חילוץ או החלטה: צבעי המצב (ירוק / כתום / צהוב / אושר ידנית / ריק) הם הסמנטיקה של
src/export.py, וכאן נקבע רק הגוון שבו הם מוצגים, כך שכל טקסט יעמוד ביחס ניגודיות של 4.5:1 לפחות מול הרקע שלו.
כל צבע אחר בממשק נייטרלי: צבע = מצב של שדה, ולא קישוט.

היחסים נבדקים ב-tests/test_ui_contrast.py (חישוב WCAG מתוך ה-CSS עצמו), כדי ששינוי גוון לא יפיל טקסט
מתחת ל-4.5:1 בלי שישימו לב.
לתשומת לב: Streamlit עוטף טקסט של כפתור ב-<p> שיש לו צבע משלו, ולכן כל כלל צבע של כפתור
חייב להגיע יחד עם כלל "inherit" לתווית (סעיף 5), אחרת הצבע שנכתב כאן פשוט לא יופיע."""
import html

import streamlit as st

# ---------- אסימוני המצב (צבע = מצב של שדה, ולא קישוט) ----------
# ink = צבע הטקסט (נבדק מול fill ומול לבן), fill = רקע התג, line = מסגרת התג, dot = נקודת המצב (לא טקסט).
STATE_INK = {"green": "#276842", "orange": "#7E4E15", "yellow": "#5F5318", "confirmed": "#2F5E8E", "empty": "#5A655F"}
STATE_FILL = {"green": "#EAF4EE", "orange": "#FBEFDF", "yellow": "#F4EDD3", "confirmed": "#E6EEF8", "empty": "#F2F0EA"}
STATE_LINE = {"green": "#CFE5D7", "orange": "#F0D9B8", "yellow": "#E4D8A8", "confirmed": "#C9D9EC", "empty": "#E3E0D7"}
STATE_DOT = {"green": "#2E7D4F", "orange": "#B06A1E", "yellow": "#8A7A22", "confirmed": "#3E72A6", "empty": "#8E948F"}
STATE_LABEL = {"green": "ירוק", "orange": "לבדיקה", "yellow": "זהב", "confirmed": "אושר ידנית", "empty": "ריק"}
# גוון תג הסטטוס של רשומה שמורה (הסטטוסים של src/repo.py: ממתינה = יש תא לבדיקה)
STATUS_STATE = {"pending": "orange", "ready": "green", "approved": "confirmed"}
PAPER, INK, INK_3 = "#FFFFFF", "#1C2321", "#5A655F"
STATES = tuple(STATE_INK)


def table_cell_css(state: str | None) -> str:
    """צבע תא בטבלה (pandas Styler): ירוק = טקסט ירוק על לבן (המצב התקין, בלי רעש); כתום / זהב / כחול = תג עדין;
    ריק וכל השאר = טקסט נייטרלי על לבן."""
    if state not in STATE_INK:
        return f"color: {INK_3}; background-color: {PAPER}"
    fill = PAPER if state == "green" else STATE_FILL[state]
    return f"color: {STATE_INK[state]}; background-color: {fill}" + ("; font-weight: 500" if fill != PAPER else "")


def badge_cell_css(state: str | None) -> str:
    """תא "תג" בטבלה (עמודת הסטטוס): תמיד מילוי בגוון המצב + טקסט כהה, כך שהצבע מגיע תמיד עם מילה."""
    if state not in STATE_INK:
        return f"color: {INK_3}; background-color: {PAPER}"
    return f"color: {STATE_INK[state]}; background-color: {STATE_FILL[state]}; font-weight: 500"


def badge(state: str, text: str) -> str:
    """תג מצב: מילה על רקע בגוון המצב (צבע לעולם לא לבד)."""
    return f"<span class='badge {html.escape(state)}'>{html.escape(str(text))}</span>"


def dot(state: str, text: str | None = None) -> str:
    """נקודת מצב + מילה (לשורת שדה בכרטיס). הצבע מסומן גם במילה, כדי שלא יסתמך על צבע בלבד."""
    word = STATE_LABEL.get(state, state) if text is None else text
    return f"<span class='state {html.escape(state)}'><i class='dot'></i>{html.escape(str(word))}</span>"


def field_row(label: str, value: str | None, state: str, mono: bool = False, empty_text: str = "לא נמצא") -> str:
    """שורת שדה לקריאה בלבד: תווית, הערך כטקסט נקי בתוך תא לבן (לא שדה קלט מושתק), ונקודה + מילה של המצב."""
    shown = html.escape(str(value)) if value else f"<span class='ro-empty'>{html.escape(empty_text)}</span>"
    return (f"<div class='ro-field {html.escape(state)}'><div class='ro-label'>{html.escape(label)}</div>"
            f"<div class='ro-value{' mono' if mono else ''}'>{shown}</div>{dot(state)}</div>")


def status_pill(kind: str, text: str) -> str:
    """פס מצב קריא מעל כפתור אישור השורה (לא תג קטן): כתום כל עוד נשארו שדות לבדיקה, ירוק כשאין.
    גופן גוף רגיל; הניגודיות לפי אותם אסימוני מצב של src/export.py (נבדקת ב-tests/test_ui_contrast.py)."""
    return f"<div class='row-check {html.escape(kind)}'>{html.escape(text)}</div>"


def confirm_status(value) -> str:
    """שורת הסטטוס של ערך שאושר על ידי המשתמש בכרטיס הבדיקה: קו אחד ("✓ אושר: ..."), לא כפתור-שהוא-תג."""
    return f"<div class='confirm-status'>✓ אושר: {html.escape(str(value))}</div>"


def field_head(label: str, state: str) -> str:
    """ראש שדה שניתן לעריכה: התווית מימין, נקודת המצב + המילה משמאל, ומתחתיהן שדה הקלט."""
    return f"<div class='fld-head'><span class='ro-label'>{html.escape(label)}</span>{dot(state)}</div>"


def banner(title: str, subtitle: str | None = None, chips: str = "") -> str:
    """כרטיס פתיחה למסך: כותרת מודגשת, שורת הסבר אחת, ומתחתיהן שבבי המספרים (stat_chips).
    פס ההתקדמות נוסף אחריו באותו מיכל (.st-key-rv_banner), כך שהוא נראה מחובר לכרטיס."""
    sub = f"<div class='rv-sub'>{html.escape(subtitle)}</div>" if subtitle else ""
    return f"<div class='rv-banner'><div class='rv-title'>{html.escape(title)}</div>{sub}{chips}</div>"


def stat_chips(items) -> str:
    """שבבי מספר: לכל אחד תווית, מספר מודגש, והמשך אופציונלי ("מתוך 5"). items = (תווית, מספר, המשך, בולט)."""
    out = []
    for label, value, tail, strong in items:
        extra = f" {html.escape(str(tail))}" if tail else ""
        out.append(f"<span class='rv-chip{' accent' if strong else ''}'>{html.escape(str(label))} "
                   f"<b>{html.escape(str(value))}</b>{extra}</span>")
    return "<div class='rv-chips'>" + "".join(out) + "</div>"


def legend(items) -> str:
    """מקרא הצבעים: נקודה + מה זה אומר, לכל מצב. שורה אחת שקטה, תמיד באותו מקום (מתחת לטבלה),
    כך שהצבע לא נשאר לבד ואין צורך לזכור מה הוא אומר. items = רצף של (מצב, משמעות)."""
    cells = "".join(f"<span class='lg-item'>{dot(state, text)}</span>" for state, text in items)
    return f"<div class='legend'><span class='lg-title'>מה הצבעים אומרים</span>{cells}</div>"


def group_label(title: str, hint: str | None = None) -> str:
    """תווית קבוצת פקדים ("סינון שורות" מול "ספירת שדות"), כדי שיהיה ברור מה כל קבוצה עושה."""
    extra = f"<span class='gl-hint'>{html.escape(hint)}</span>" if hint else ""
    return f"<div class='group-label'><span class='gl-title'>{html.escape(title)}</span>{extra}</div>"


def section(title: str, hint: str | None = None) -> str:
    """כותרת מקטע: שורה אחת, משקל אחד, בלי אייקונים."""
    extra = f"<span class='sec-hint'>{html.escape(hint)}</span>" if hint else ""
    return f"<div class='sec'><span class='sec-title'>{html.escape(title)}</span>{extra}</div>"


def quiet(text: str) -> str:
    """שורה שקטה (עימוד, הערת עזר): טקסט קטן ונייטרלי, בלי מסגרת."""
    return f"<div class='quiet'>{text}</div>"


CSS = """
/* ============================================================
   1. אסימוני העיצוב
   ============================================================ */
:root {
  /* מרווחים */
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 24px; --sp-6: 32px;
  /* מדרג הגופן */
  --fs-hero: 1.55rem; --fs-page: 1.32rem; --fs-section: 1.02rem; --fs-body: 0.92rem; --fs-label: 0.8rem; --fs-cap: 0.78rem;
  --lh-tight: 1.25; --lh-body: 1.6;
  /* נייטרלי: טקסט, משטחים, קווים (ink-2 / ink-3 נבדקו ל-4.5:1 לפחות מול --wash, הרקע הכהה ביותר שיש) */
  --ink: #1C2321; --ink-2: #3D4945; --ink-3: #5A655F;
  --paper: #FFFFFF; --canvas: #F7F6F2; --wash: #F2F0EA;
  --line: #E3E0D7; --line-2: #CFCBBF;
  --accent: #2D5F6B; --accent-ink: #1F4A54; --accent-soft: #E7EFF0; --accent-line: #CFDFE1;
  /* כפתור ראשי: לבן על טורקיז. כל שלושת הגוונים נבדקו מול --on-accent: 7.09 / 9.22 / 4.99 ל-1.
     --ink-disabled נבדק מול --wash (4.79:1), הרקע של כפתור משני מושבת */
  --on-accent: #FFFFFF; --accent-hover: #244D58; --accent-muted: #4A7682; --ink-disabled: #656B65;
  --radius: 10px; --radius-sm: 8px; --radius-pill: 999px;
  --shadow: 0 1px 2px rgba(28, 35, 33, 0.04), 0 4px 14px rgba(31, 74, 84, 0.05);
  --shadow-lift: 0 2px 6px rgba(28, 35, 33, .05), 0 10px 30px rgba(31, 74, 84, .08);
  /* מצב השדה: הסמנטיקה של src/export.py. אין צבע מצב בשום מקום אחר בממשק */
  --green-ink: #276842; --green-fill: #EAF4EE; --green-line: #CFE5D7; --green-dot: #2E7D4F;
  --orange-ink: #7E4E15; --orange-fill: #FBEFDF; --orange-line: #F0D9B8; --orange-dot: #B06A1E;
  --yellow-ink: #5F5318; --yellow-fill: #F4EDD3; --yellow-line: #E4D8A8; --yellow-dot: #8A7A22;
  --confirmed-ink: #2F5E8E; --confirmed-fill: #E6EEF8; --confirmed-line: #C9D9EC; --confirmed-dot: #3E72A6;
  --empty-ink: #5A655F; --empty-fill: #F2F0EA; --empty-line: #E3E0D7; --empty-dot: #8E948F;
}

/* ============================================================
   2. בסיס: עברית מימין לשמאל, גופן אחד, מונוספייס רק לקודים
   ============================================================ */
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], .main, .block-container {direction: rtl; text-align: right;}
html, body, .stApp, button, input, textarea, [data-testid="stMarkdownContainer"] {font-family: 'Heebo', sans-serif;}
.stApp {background: var(--canvas);}
.block-container {max-width: 1560px; padding: var(--sp-2) var(--sp-6) var(--sp-5);}
[data-testid="stVerticalBlock"] {gap: var(--sp-2);}
[data-testid="stHeading"], [data-testid="stHeading"] *, h1, h2, h3, h4, h5,
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *,
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p {direction: rtl; text-align: right;}
[data-testid="stMarkdownContainer"] p {font-size: var(--fs-body); line-height: var(--lh-body); color: var(--ink);}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {color: var(--ink-3); font-size: var(--fs-cap);}
code {font-family: 'IBM Plex Mono', monospace !important; direction: ltr; unicode-bidi: embed; background: var(--wash); color: var(--ink);
      border-radius: var(--sp-1); padding: 1px 6px; font-size: 0.9em;}
/* הסרת הקישוט של Streamlit: סרגל, תפריט, כותרת, תחתית */
[data-testid="stToolbar"], [data-testid="stDeployButton"], .stDeployButton, #MainMenu, footer, header[data-testid="stHeader"] {display: none !important;}

/* ============================================================
   3. טיפוגרפיה של הממשק: כותרת הדף, כותרת מקטע, שורה שקטה
   ============================================================ */
/* באנר הפתיחה: שורת הכותרת הרשמית + הלוגו, בתוך כרטיס הפתיחה המאוחד (.st-key-hero_card, סעיף 6) שמכיל גם את
   ניווט המסכים מתחתיה - לא כרטיס נפרד משלה. מקום שמור ללוגו המשרד בצד הנגדי לטקסט (RTL: הטקסט מימין, הסמל משמאל).
   width: 100% + box-sizing מפורשים כדי שהריפוד לא יצמצם את הרוחב בפועל. שורות הטקסט ב-white-space: nowrap + ellipsis:
   בלי זה, hero-content (שכן ליד hero-badges קבועת-רוחב בתוך flex) יכול להתכווץ מתחת לרוחב התוכן הטבעי שלו ולשבור
   כל מילה לשורה/תו משלה - זה היה הבאג (טקסט "מרוסק" בצד ימין). */
.hero-banner {display: flex; align-items: center; justify-content: space-between; gap: var(--sp-5); flex-wrap: wrap;
      width: 100%; box-sizing: border-box; padding-bottom: var(--sp-3); margin-bottom: var(--sp-3); border-bottom: 1px solid var(--line);}
.hero-content {flex: 1 1 auto; min-width: 260px; overflow: hidden;}
.hero-eyebrow, .hero-title, .hero-subtitle {white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.hero-eyebrow {font-size: var(--fs-label); font-weight: 600; letter-spacing: .02em; color: var(--accent-ink); margin: 0 0 2px;}
.hero-title {font-size: var(--fs-hero); font-weight: 800; color: var(--ink); line-height: var(--lh-tight); margin: 0 0 6px;}
.hero-subtitle {font-size: var(--fs-cap); color: var(--ink-3);}
.hero-badges {display: flex; align-items: center; gap: var(--sp-2); flex-shrink: 0;}
.hero-logo {height: 52px; width: auto; max-width: 160px; object-fit: contain; display: block; flex-shrink: 0;}
/* נפילה רכה כש-assets/moh_logo.png חסר: תווית מקום, לא לוגו בפועל */
.hero-badge {display: flex; align-items: center; justify-content: center; min-width: 78px; height: 48px; padding: 0 var(--sp-2);
      border: 1.5px dashed var(--accent-line); border-radius: var(--radius-sm); background: var(--paper);
      font-size: var(--fs-cap); font-weight: 600; color: var(--accent-muted); text-align: center; line-height: 1.15; flex-shrink: 0;}
.sec {display: flex; align-items: baseline; gap: var(--sp-2); margin: var(--sp-1) 0 var(--sp-2);}
.sec-title {font-size: var(--fs-section); font-weight: 600; color: var(--ink);}
.sec-hint {font-size: var(--fs-cap); color: var(--ink-3);}
.col-label {font-size: var(--fs-label); font-weight: 700; letter-spacing: .02em; color: var(--ink-3); margin-bottom: var(--sp-1);}
/* תווית קבוצת פקדים: שורה שקטה אחת מעל הקבוצה (מה היא עושה), כדי שלא יתבלבלו בין סינון שורות לספירת שדות */
.group-label {display: flex; align-items: baseline; gap: var(--sp-2); margin: 0 0 var(--sp-1); flex-wrap: wrap;}
.group-label .gl-title {font-size: var(--fs-label); font-weight: 700; color: var(--ink-2);}
.group-label .gl-hint {font-size: var(--fs-cap); color: var(--ink-3);}
/* מקרא הצבעים: שורה אחת מתחת לטבלה, תמיד באותו מקום. נקודה + מילה, בלי מסגרות ובלי צבע רקע */
.legend {display: flex; align-items: center; gap: var(--sp-2) var(--sp-5); flex-wrap: wrap; background: var(--paper);
      border: 1px solid var(--line); border-radius: var(--radius); padding: 9px var(--sp-4); margin: var(--sp-1) 0 var(--sp-2);}
.legend .lg-title {font-size: var(--fs-cap); font-weight: 700; color: var(--ink-2); margin-inline-end: var(--sp-1);}
.legend .lg-item .state {font-size: var(--fs-label); white-space: nowrap;}
.quiet {font-size: var(--fs-cap); color: var(--ink-3); line-height: var(--lh-body);}
.quiet b {color: var(--ink-2); font-weight: 600;}
.counter {font-size: var(--fs-label); color: var(--ink-2); white-space: nowrap; text-align: center !important;}
.counter b {font-weight: 700; color: var(--ink);}
.counter span {display: block; font-size: var(--fs-cap); color: var(--ink-3);}

/* ============================================================
   4. תגי מצב, נקודות מצב, שורת שדה לקריאה בלבד, תגיות דגל
   ============================================================ */
.badge {flex: none; display: inline-flex; align-items: center; font-size: var(--fs-cap); font-weight: 500; padding: 3px 11px;
      border-radius: var(--radius-pill); border: 1px solid; white-space: nowrap;}
.badge.green {color: var(--green-ink); background: var(--green-fill); border-color: var(--green-line);}
.badge.orange {color: var(--orange-ink); background: var(--orange-fill); border-color: var(--orange-line);}
.badge.yellow {color: var(--yellow-ink); background: var(--yellow-fill); border-color: var(--yellow-line);}
.badge.confirmed {color: var(--confirmed-ink); background: var(--confirmed-fill); border-color: var(--confirmed-line);}
.badge.empty {color: var(--empty-ink); background: var(--empty-fill); border-color: var(--empty-line);}
.state {display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-cap); white-space: nowrap;}
.state .dot {width: 8px; height: 8px; border-radius: 50%; background: var(--empty-dot); flex: none;}
.state.green {color: var(--green-ink);} .state.green .dot {background: var(--green-dot);}
.state.orange {color: var(--orange-ink);} .state.orange .dot {background: var(--orange-dot);}
.state.yellow {color: var(--yellow-ink);} .state.yellow .dot {background: var(--yellow-dot);}
.state.confirmed {color: var(--confirmed-ink);} .state.confirmed .dot {background: var(--confirmed-dot);}
.state.empty {color: var(--empty-ink);}
/* שדה נעול: הערך נקרא כטקסט על משטח לבן, לא כשדה קלט מושתק */
.ro-field {background: var(--paper); border: 1px solid var(--line); border-right: 3px solid var(--empty-dot);
      border-radius: var(--radius-sm); padding: var(--sp-2) var(--sp-3); margin-bottom: var(--sp-2);}
.ro-field.green {border-right-color: var(--green-dot);} .ro-field.orange {border-right-color: var(--orange-dot);}
.ro-field.yellow {border-right-color: var(--yellow-dot);} .ro-field.confirmed {border-right-color: var(--confirmed-dot);}
.ro-label {font-size: var(--fs-cap); color: var(--ink-3); margin-bottom: 2px;}
.ro-value {font-size: var(--fs-body); font-weight: 500; color: var(--ink); line-height: var(--lh-tight); word-break: break-word;}
.ro-value.mono {font-family: 'IBM Plex Mono', monospace; direction: ltr; unicode-bidi: embed; text-align: right;}
.ro-empty {color: var(--ink-3); font-weight: 400;}
.ro-field .state {margin-top: var(--sp-1);}
.fld-head {display: flex; align-items: baseline; justify-content: space-between; gap: var(--sp-2); margin: 0 0 2px;}
.flag {display: inline-flex; align-items: center; gap: 6px; margin: 2px 0 2px 6px; padding: 2px 10px; border-radius: var(--radius-pill);
      color: var(--orange-ink); background: var(--orange-fill); border: 1px solid var(--orange-line); font-size: var(--fs-cap);}
/* פס מצב קריא מעל כפתור אישור השורה: גופן גוף (לא הערה קטנה), כך שהמצב ("נותרו N שדות לבדיקה" / "כל השדות נבדקו")
   בולט ולא נבלע כטקסט אפור קטן מתחת לכפתור */
.row-check {display: block; font-size: var(--fs-body); font-weight: 600; text-align: center; border-radius: var(--radius-sm);
      padding: 7px var(--sp-3); margin-bottom: var(--sp-2);}
.row-check.warn {color: var(--orange-ink); background: var(--orange-fill); border: 1px solid var(--orange-line);}
.row-check.ok {color: var(--green-ink); background: var(--green-fill); border: 1px solid var(--green-line);}
/* שורת סטטוס "אושר על ידי המשתמש" בכרטיס הבדיקה: קו אחד במקום כפתור-שהוא-תג, אותו גוון כמו תג "אושר ידנית" */
.confirm-status {display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-body); font-weight: 600;
      color: var(--confirmed-ink); background: var(--confirmed-fill); border: 1px solid var(--confirmed-line);
      border-radius: var(--radius-sm); padding: var(--sp-2) var(--sp-3); margin-bottom: var(--sp-2);}

/* ============================================================
   5. פקדים: כפתורים, שדות קלט, העלאה, הודעות
   ============================================================ */
/* ---------- כפתורים: הבורר הוא הכפתור עצמו, לא העוטף ----------
   כל כפתור ב-Streamlit נושא data-testid="stBaseButton-<סוג>" **על אלמנט ה-button**, והעוטף שונה לכל סוג:
   .stButton (st.button), .stDownloadButton, .stFormSubmitButton (st.form_submit_button), .stPopover.
   לכן כלל שנכתב לעוטף אחד פשוט לא חל על האחרים, וכך נשארה תווית "אישור · Enter"
   (stBaseButton-primaryFormSubmit, בתוך .stFormSubmitButton) כהה על הטורקיז הכהה: 2.26:1.
   מכאן כל כלל נכתב על הכפתור לפי ה-testid שלו, ועל התווית שבתוכו.
   שתי שכבות הגנה שאי אפשר לעקוף אותן:
   1. **כל** תווית בתוך **כל** כפתור יורשת את צבע הכפתור (הכלל הראשון כאן, ^= על כל המשפחה). Streamlit עוטף
      את התווית ב-<p> בתוך stMarkdownContainer, ולכלל הטיפוגרפיה של אותו <p> (סעיף 2) יש color משלו שגובר
      על צבע שנורש. "inherit" מחזיר כל תווית לצבע הכפתור, ולכן תווית לא יכולה "להישאר כהה" על רקע כהה.
   2. לכל סוג כפתור יש זוג צבעים מוצהר בכל חמשת המצבים (רגיל, מעבר עכבר, מיקוד, לחיצה, מושבת).
   popover מקבל data-testid משלו (stPopoverButton) ולכן מופיע בנפרד; הכפתורים של segmented_control
   מקבלים את גוון המצב בסעיף 6, וכאן רק המילה הנבחרת מקבלת לבן על טורקיז.
   הבדיקה: tests/test_ui_contrast.py פותרת את ה-CSS הזה לכל testid ולכל מצב ובודקת 4.5:1. */
button[data-testid^="stBaseButton-"] [data-testid="stMarkdownContainer"],
button[data-testid^="stBaseButton-"] [data-testid="stMarkdownContainer"] p,
button[data-testid^="stBaseButton-"] p, button[data-testid^="stBaseButton-"] div,
button[data-testid^="stBaseButton-"] span, button[data-testid="stPopoverButton"] [data-testid="stMarkdownContainer"],
button[data-testid="stPopoverButton"] [data-testid="stMarkdownContainer"] p,
button[data-testid="stPopoverButton"] p, button[data-testid="stPopoverButton"] div {color: inherit !important;
      font-weight: inherit !important;}
/* כפתור משני (וגם tertiary ו-popover): טקסט כהה על נייר */
button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"],
button[data-testid="stBaseButton-tertiary"], button[data-testid="stBaseButton-tertiaryFormSubmit"],
button[data-testid="stPopoverButton"] {border-radius: var(--radius-sm); font-weight: 500; border: 1px solid var(--line-2);
      background: var(--paper); color: var(--ink); transition: border-color .15s, background .15s;}
button[data-testid="stBaseButton-secondary"]:hover, button[data-testid="stBaseButton-secondaryFormSubmit"]:hover,
button[data-testid="stBaseButton-tertiary"]:hover, button[data-testid="stBaseButton-tertiaryFormSubmit"]:hover,
button[data-testid="stPopoverButton"]:hover {border-color: var(--accent); color: var(--accent); background: var(--paper);}
button[data-testid="stBaseButton-secondary"]:active, button[data-testid="stBaseButton-secondaryFormSubmit"]:active,
button[data-testid="stBaseButton-tertiary"]:active, button[data-testid="stBaseButton-tertiaryFormSubmit"]:active,
button[data-testid="stPopoverButton"]:active {border-color: var(--accent-ink); color: var(--accent-ink); background: var(--paper);}
button[data-testid="stBaseButton-secondary"]:focus-visible, button[data-testid="stBaseButton-secondaryFormSubmit"]:focus-visible,
button[data-testid="stBaseButton-tertiary"]:focus-visible, button[data-testid="stBaseButton-tertiaryFormSubmit"]:focus-visible,
button[data-testid="stPopoverButton"]:focus-visible {color: var(--ink); background: var(--paper);}
button[data-testid="stBaseButton-secondary"]:disabled, button[data-testid="stBaseButton-secondaryFormSubmit"]:disabled,
button[data-testid="stBaseButton-tertiary"]:disabled, button[data-testid="stBaseButton-tertiaryFormSubmit"]:disabled,
button[data-testid="stPopoverButton"]:disabled {background: var(--wash); color: var(--ink-disabled);
      border-color: var(--line); opacity: 1;}
/* גלולת segmented_control שאינה נבחרת (בורר המסך, והסינון המהיר שמקבל גוון מצב בסעיף 6) */
button[data-testid="stBaseButton-segmented_control"], button[data-testid="stBaseButton-pills"] {background: var(--wash);
      border: 1px solid transparent; border-radius: var(--radius-pill); color: var(--ink-2); font-weight: 500;}
button[data-testid="stBaseButton-segmented_control"]:hover, button[data-testid="stBaseButton-pills"]:hover,
button[data-testid="stBaseButton-segmented_control"]:active, button[data-testid="stBaseButton-pills"]:active {background: var(--accent-soft);
      color: var(--accent-ink);}
button[data-testid="stBaseButton-segmented_control"]:focus-visible, button[data-testid="stBaseButton-pills"]:focus-visible {background: var(--wash);
      color: var(--ink-2);}
button[data-testid="stBaseButton-segmented_control"]:disabled, button[data-testid="stBaseButton-pills"]:disabled {background: var(--wash);
      color: var(--ink-disabled); opacity: 1;}
/* כפתור ראשי ("חילוץ נתונים", "הורדת אקסל", "אישור שורה", "אישור · Enter" שבטופס) והמילה הנבחרת
   ב-segmented_control: לבן מודגש על טורקיז, בכל המצבים. הבוררים עם [kind="primary"] נשארים לגרסה של
   Streamlit שתחזיר את התכונה הזאת ל-DOM. opacity: 1 כדי שהיחס שנמדד יהיה היחס שרואים. */
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"],
button[data-testid="stBaseButton-segmented_controlActive"], button[data-testid="stBaseButton-pillsActive"],
button[kind="primary"], .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {background: var(--accent);
      border: 1px solid var(--accent); border-radius: var(--radius-sm); color: var(--on-accent) !important;
      font-weight: 700 !important; opacity: 1; transition: background .15s;}
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover,
button[data-testid="stBaseButton-segmented_controlActive"]:hover, button[data-testid="stBaseButton-pillsActive"]:hover,
button[kind="primary"]:hover, .stButton > button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {background: var(--accent-hover);
      border-color: var(--accent-hover); color: var(--on-accent) !important;}
button[data-testid="stBaseButton-primary"]:active, button[data-testid="stBaseButton-primaryFormSubmit"]:active,
button[data-testid="stBaseButton-segmented_controlActive"]:active, button[data-testid="stBaseButton-pillsActive"]:active,
button[kind="primary"]:active, .stButton > button[kind="primary"]:active {background: var(--accent-ink);
      border-color: var(--accent-ink); color: var(--on-accent) !important;}
button[data-testid="stBaseButton-primary"]:focus-visible, button[data-testid="stBaseButton-primaryFormSubmit"]:focus-visible,
button[data-testid="stBaseButton-segmented_controlActive"]:focus-visible, button[data-testid="stBaseButton-pillsActive"]:focus-visible,
button[kind="primary"]:focus-visible, .stButton > button[kind="primary"]:focus-visible {background: var(--accent);
      color: var(--on-accent) !important;}
/* מושבת: ראשי = לבן מודגש על טורקיז מעומעם (4.99:1). המצב גלוי בממשק: "אישור שורה" נעול כל עוד נשאר
   בשורה שדה לבדיקה, ו"הורדת אקסל" לפני שיש תוצאות. */
button[data-testid="stBaseButton-primary"]:disabled, button[data-testid="stBaseButton-primaryFormSubmit"]:disabled,
button[data-testid="stBaseButton-segmented_controlActive"]:disabled, button[data-testid="stBaseButton-pillsActive"]:disabled,
button[kind="primary"]:disabled, .stButton > button[kind="primary"]:disabled,
[data-testid="stBaseButton-primary"]:disabled, [data-testid="stBaseButton-primaryFormSubmit"]:disabled {background: var(--accent-muted);
      border-color: var(--accent-muted); color: var(--on-accent) !important; font-weight: 700 !important; opacity: 1;}
/* מיקוד מהמקלדת: טבעת מסגרת מחוץ לכפתור, כדי שתיראה גם על כפתור ראשי כהה (8.97:1 מול --canvas) */
button[data-testid^="stBaseButton-"]:focus-visible, button[data-testid="stPopoverButton"]:focus-visible {outline: 3px solid var(--accent-ink);
      outline-offset: 2px;}
[data-baseweb="input"], [data-baseweb="select"] > div {border-radius: var(--radius-sm);}
.stTextInput label p, .stSelectbox label p, .stMultiSelect label p, [data-testid="stDateInput"] label p, .stNumberInput label p,
[data-testid="stSlider"] label p {font-size: var(--fs-label) !important; color: var(--ink-2) !important;}
/* תווית עברית מעל פקד שבו Streamlit לא מאפשר placeholder: הטקסט האנגלי הריק מוסתר */
[data-testid="stDateInput"] input::placeholder {color: transparent;}
[data-testid="stFileUploaderDropzone"] {background: var(--accent-soft); border: 1.5px dashed var(--accent-line); border-radius: var(--radius);
      transition: border-color .15s ease, background .15s ease;}
[data-testid="stFileUploaderDropzone"]:hover {border-color: var(--accent); background: #DFEAEC;}
[data-testid="stFileUploaderDropzoneInstructions"] > div > span, [data-testid="stFileUploaderDropzoneInstructions"] small,
[data-testid="stFileUploaderDropzoneInstructions"] svg {display: none;}
[data-testid="stFileUploaderDropzoneInstructions"] > div::before {content: "גרירת קובץ PDF או תמונה לכאן (עד 25MB)"; font-size: 14px; color: var(--ink-2);}
[data-testid="stFileUploaderDropzone"] button, [data-testid="stFileUploaderDropzone"] button * {font-size: 0 !important;}
[data-testid="stFileUploaderDropzone"] button::after {content: "בחירת קובץ"; font-size: 13px !important;}
/* פס ההתקדמות: הממשק עברית, ולכן הפס מתמלא מהקצה הימני שמאלה. direction: rtl לבד אינו מספיק כאן:
   המילוי הוא div ברוחב 100% שמוזז ב-transform: translateX(value-100%), כלומר תמיד נגרר מהשמאל (כך בנוי
   הרכיב ב-Streamlit). לכן המסילה עצמה משוקפת (scaleX(-1)): אין בה טקסט (הכיתוב הוא אלמנט נפרד מעליה),
   והשיקוף מעביר את המילוי לצד הימני ומגדיל אותו שמאלה. */
[data-testid="stProgress"], [data-testid="stProgress"] [data-testid="stMarkdownContainer"] p {direction: rtl; text-align: right;}
[data-testid="stProgressBarTrack"] {transform: scaleX(-1); background: var(--wash);}
[data-testid="stProgressBarTrack"] > div {background: var(--accent) !important;}
[data-testid="stAlert"] {border-radius: var(--radius-sm);}
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {font-size: var(--fs-body);}
[data-testid="stExpander"] {border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--paper);}
[data-testid="stExpander"] summary p {font-size: var(--fs-label); color: var(--ink-2);}
[data-testid="stPopoverBody"] {direction: rtl; text-align: right;}

/* ============================================================
   6. משטחים: כרטיס פתיחה (כותרת+ניווט), כרטיס פעולה, פס מדדים, סרגל סינון, טבלה
   ============================================================ */
/* כרטיס הפתיחה המאוחד: הכותרת הרשמית והלוגו למעלה (.hero-banner), וניווט המסכים (segmented_control) מתחתיה
   באותו כרטיס - בלי פס טאבים צף ונפרד. הגלולות של הניווט כבר מעוצבות גלובלית (סעיף 5); כאן רק המיקום בתוך הכרטיס. */
.st-key-hero_card {background: linear-gradient(135deg, var(--paper) 0%, var(--accent-soft) 100%) !important;
      border: 1px solid var(--line) !important; border-right: 4px solid var(--accent) !important; border-radius: var(--radius) !important;
      box-shadow: var(--shadow-lift); padding: var(--sp-4) var(--sp-5) var(--sp-3) !important; margin-bottom: var(--sp-2);}
.st-key-hero_card [data-testid="stSegmentedControl"] {margin-top: -4px;}
.st-key-action_card {position: sticky; top: var(--sp-1); z-index: 100; background: var(--paper) !important; border: 1px solid var(--line) !important;
      border-radius: var(--radius) !important; padding: var(--sp-3) var(--sp-3) !important; box-shadow: var(--shadow);}
.st-key-action_card [data-testid="stFileUploaderDropzone"] {padding: 0 var(--sp-4); min-height: 44px; height: 44px;}
.st-key-action_card [data-testid="stFileUploaderDropzone"] button {min-height: 32px; height: 32px; padding: 0 var(--sp-3); border-radius: var(--radius-sm);}
.st-key-action_card .stButton > button, .st-key-action_card .stDownloadButton > button {height: 44px; min-height: 44px;}
.st-key-action_card [data-testid="stFileUploaderFile"] {margin-top: 2px;}
.kpis {display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); background: var(--paper); border: 1px solid var(--line);
      border-radius: var(--radius); box-shadow: var(--shadow); overflow: hidden; margin: 2px 0 var(--sp-2);}
.kpi {padding: var(--sp-2) var(--sp-4) 9px; min-width: 0; border-left: 1px solid var(--line); cursor: default;}
.kpi:last-child {border-left: none;}
.kpi .k-label {font-size: 0.74rem; font-weight: 500; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.kpi .k-value {font-size: 1.28rem; font-weight: 600; color: var(--tone); line-height: var(--lh-tight); white-space: nowrap; font-variant-numeric: tabular-nums;}
.kpi .k-value small {font-size: 0.8rem; font-weight: 500; color: var(--ink-3); margin-right: 3px;}
@media (max-width: 1100px) {.kpis {grid-template-columns: repeat(4, minmax(0, 1fr));} .kpi {border-bottom: 1px solid var(--line);}}
.st-key-toolbar {background: var(--paper) !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
      box-shadow: var(--shadow); padding: var(--sp-2) var(--sp-3) !important;}
/* מסנני הסטטוס בטבלת העיבוד: גלולות במילוי רך לפי המצב. הנבחרת: לבן על --*-ink (6.07 עד 7.67 ל-1) */
.st-key-status_filter [role="radiogroup"] {gap: 6px; flex-wrap: wrap;}
.st-key-status_filter button {--chip-bg: var(--wash); --chip-ink: var(--ink-2); --chip-on: var(--accent);
      border: 1px solid transparent !important; border-radius: var(--radius-pill) !important; background: var(--chip-bg) !important;
      color: var(--chip-ink) !important; padding: 5px var(--sp-4) !important; min-height: 2.1rem; box-shadow: none !important;
      transition: background .15s, color .15s;}
.st-key-status_filter button p {color: inherit !important; font-size: var(--fs-label); white-space: nowrap;}
/* הספירה בתוך הגלולה נבדלת במשקל בלבד: opacity: .8 הורידה את היחס ל-3.85 עד 4.12 ל-1 */
.st-key-status_filter button p strong {font-weight: 700;}
.st-key-status_filter button:nth-of-type(2) {--chip-bg: var(--green-fill); --chip-ink: var(--green-ink); --chip-on: var(--green-ink);}
.st-key-status_filter button:nth-of-type(3) {--chip-bg: var(--orange-fill); --chip-ink: var(--orange-ink); --chip-on: var(--orange-ink);}
.st-key-status_filter button:nth-of-type(4) {--chip-bg: var(--yellow-fill); --chip-ink: var(--yellow-ink); --chip-on: var(--yellow-ink);}
.st-key-status_filter button:nth-of-type(5) {--chip-bg: var(--paper); --chip-ink: var(--ink-3); --chip-on: var(--empty-ink); border: 1px dashed var(--line-2) !important;}
.st-key-status_filter button:hover {filter: brightness(0.97);}
/* הגלולה הנבחרת: Streamlit מסמן אותה אחרת בין גרסאות (data-selected, kind, ו-data-testid של הסוג הפעיל),
   ולכן שלושת הסימנים מכוסים. בלי זה פשוט לא רואים איזה סינון פעיל. */
.st-key-status_filter button[data-selected="true"], .st-key-status_filter button[kind="segmented_controlActive"],
.st-key-status_filter button[data-testid="stBaseButton-segmented_controlActive"] {background: var(--chip-on) !important;
      color: var(--paper) !important; border-color: var(--chip-on) !important;}
.st-key-focus_wrap {background: var(--accent-soft); border: 1px solid var(--accent-line); border-radius: var(--radius-pill);
      padding: 5px var(--sp-4) !important; width: fit-content; margin-inline-start: auto;}
.st-key-focus_wrap label p {font-size: var(--fs-label) !important; font-weight: 600 !important; color: var(--accent-ink) !important; white-space: nowrap;}
[data-testid="stDataFrame"] {border: 1px solid var(--line); border-radius: var(--radius); background: var(--paper); box-shadow: var(--shadow); overflow: hidden;}
/* הרשת מצוירת על canvas משמאל לימין (סדר העמודות כבר הפוך בקוד). בלי זה ה-canvas יורש RTL מהדף, ו-"939068 ; 944004" מתהפך */
[data-testid="stDataFrame"], [data-testid="stDataFrame"] canvas {direction: ltr;}

/* ============================================================
   7. מסך הרשומות: ארבעה כרטיסים (חיפוש וסינון, בדיקה, רשומות, ייצוא), באותו גוון מבטיח כמו הבאנר העליון
   ============================================================ */
/* אותו "שפת עיצוב" כמו פאנלי הפירוט (rec_detail, detail_panel): לבן, מסגרת דקה, קו עליון בגוון המותג, הצללה
   ומרווח אחיד - כדי שארבעת הכרטיסים יראו כקבוצה אחת ולא כערימת פקדים חופשיים */
.st-key-rec_top, .st-key-rec_review_card, .st-key-rec_table_card, .st-key-rec_export_card {
      background: var(--paper) !important; border: 1px solid var(--line) !important; border-top: 3px solid var(--accent) !important;
      border-radius: var(--radius) !important; box-shadow: var(--shadow); padding: var(--sp-3) var(--sp-4) var(--sp-4) !important;
      margin-bottom: var(--sp-2);}
.st-key-rec_counters {gap: 6px !important;}
/* המונים כקבוצה מפולחת אחת: גלולות באותו גובה, הנבחרת במילוי המותג */
.st-key-rec_counters .stButton > button {border-radius: var(--radius-pill); background: var(--wash); border-color: transparent;
      color: var(--ink-2); font-size: var(--fs-label); font-weight: 500; min-height: 2.2rem; padding: 0 var(--sp-4); white-space: nowrap;}
.st-key-rec_counters .stButton > button:hover {border-color: var(--accent-line); background: var(--accent-soft); color: var(--accent-ink);}
/* המונה שנבחר (type="primary"): הבורר לפי data-testid, כי kind אינו ב-DOM בגרסה הזאת */
.st-key-rec_counters .stButton > button[kind="primary"],
.st-key-rec_counters button[data-testid="stBaseButton-primary"] {background: var(--accent) !important;
      border-color: var(--accent) !important; color: var(--on-accent) !important;}
.st-key-rec_top .stTextInput input {font-size: var(--fs-body); height: 2.3rem;}
.st-key-rec_filters [data-testid="stExpander"] {border: 1px solid var(--line); background: var(--paper);}
.st-key-rec_filters [data-testid="stExpander"] summary p {font-weight: 500; color: var(--ink-2); font-size: var(--fs-label);}
.filter-badge {display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-cap); font-weight: 600; color: var(--accent-ink);
      background: var(--accent-soft); border: 1px solid var(--accent-line); border-radius: var(--radius-pill); padding: 1px 9px;}
.st-key-rec_pager {border-top: 1px solid var(--line); padding-top: var(--sp-2) !important; margin-top: 2px;}
.st-key-rec_pager [data-baseweb="input"], .st-key-rec_pager [data-baseweb="select"] > div {min-height: 2rem;}
.st-key-rec_pager .stNumberInput, .st-key-rec_pager .stSelectbox {max-width: 190px;}
[data-testid="stPopoverBody"] {min-width: 240px;}
/* כרטיס הייצוא: תג משנה שקט (כמה רשומות), ואז בחירת פורמט (גלולות) + כפתור ההורדה זה לצד זה, במרכז הכרטיס,
   ברוחב קריאה (לא נמתח לכל הכרטיס, והכפתור אינו "ענק" - גודל לפי התוכן) */
.st-key-rec_export_body {max-width: 480px; margin: 0 auto; text-align: center;}
/* תג משנה שקט: אותו גוון כמו "שורה שקטה על רקע בהיר" (ink-3 על wash, נבדק 4.5:1), לא הצהרה כהה ומודגשת */
.export-badge {display: inline-flex; align-items: center; gap: 4px; font-size: var(--fs-label); font-weight: 500;
      color: var(--ink-3); background: var(--wash); border: 1px solid var(--line); border-radius: var(--radius-pill);
      padding: 4px 14px; margin-bottom: var(--sp-3);}
.export-badge b {color: var(--ink-2); font-weight: 700;}
.st-key-rec_export_action {display: flex; align-items: center; justify-content: center; gap: var(--sp-3); flex-wrap: wrap;}
.st-key-rec_export_action [data-testid="stSegmentedControl"] {display: flex; justify-content: center;}
.st-key-rec_export_action .stDownloadButton {flex: none;}
.st-key-rec_export_action .stDownloadButton > button {padding-inline: var(--sp-5);}
/* כרטיס הרשומה: סרגל פעולות אחד בראש, ואז הכותרת והשדות */
.st-key-rec_detail {background: var(--paper) !important; border: 1px solid var(--line) !important; border-top: 3px solid var(--accent) !important;
      border-radius: var(--radius) !important; box-shadow: var(--shadow-lift); padding: var(--sp-4) var(--sp-5) var(--sp-5) !important;
      scroll-margin-top: 120px;}
.st-key-rec_actions .stButton > button {height: 38px; min-height: 38px; white-space: nowrap;}
.rec-head {display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; margin: var(--sp-2) 0 var(--sp-3);}
.rec-title {font-size: var(--fs-section); font-weight: 600; color: var(--ink);}
.rec-meta {font-size: var(--fs-cap); color: var(--ink-3);}
.st-key-rec_fields [data-testid="stExpander"] {border: 1px solid var(--line); border-radius: var(--radius-sm); margin: 0 0 var(--sp-3);}
.st-key-rec_fields [data-testid="stExpander"] summary p {font-size: var(--fs-cap);}
.st-key-rec_fields .stTextInput {margin-bottom: 2px;}

/* ============================================================
   8. פאנל הפירוט במסך העיבוד
   ============================================================ */
.st-key-detail_panel {background: var(--paper) !important; border: 1px solid var(--line) !important; border-top: 3px solid var(--accent) !important;
      border-radius: var(--radius) !important; box-shadow: var(--shadow-lift); padding: var(--sp-4) var(--sp-5) var(--sp-5) !important;
      scroll-margin-top: 140px;}
.panel-head {display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap;}
.panel-head .ph-eyebrow {font-size: var(--fs-cap); color: var(--ink-3);}
.panel-head .ph-title {font-size: var(--fs-section); font-weight: 600; color: var(--ink); line-height: var(--lh-tight);}
.panel-rule {height: 1px; background: var(--line); margin: var(--sp-1) 0 var(--sp-2);}
/* כפתור סגירת כרטיס הבדיקה: סמל קטן (✕) בפינה, לא פעולה ראשית - גובה נוח ללחיצה בלי רוחב מלא */
.st-key-close_detail button {min-height: 2.1rem; padding: 2px var(--sp-3); font-size: var(--fs-section); line-height: 1;}
/* הכרטיס המוביל (CTA) להתחלת הבדיקה המודרכת ממסך העיבוד: בולט אך לא "כתום-אזהרה" - גוון המותג */
.st-key-guided_cta {background: var(--accent-soft) !important; border: 1px solid var(--accent-line) !important;
      border-radius: var(--radius) !important; padding: var(--sp-3) var(--sp-4) !important; margin-bottom: var(--sp-2);}
.st-key-detail_actions {background: #FCFBF8 !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
      padding: var(--sp-3) var(--sp-4) var(--sp-4) !important; position: sticky; top: 128px; z-index: 5;}
.st-key-detail_actions [data-testid="stVerticalBlock"] {gap: var(--sp-2);}
.st-key-detail_actions [data-testid="stAlert"] > div {padding: var(--sp-2) var(--sp-3);}
.st-key-detail_actions [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {font-size: var(--fs-label);}
.st-key-detail_actions [data-baseweb="input"], .st-key-detail_actions [data-baseweb="base-input"],
.st-key-detail_actions .stTextInput input {background: var(--paper) !important;}
.st-key-detail_actions [data-baseweb="input"] {border: 1px solid var(--line-2);}
.st-key-detail_evidence [data-testid="stImage"] img, .st-key-detail_evidence [data-testid="stFullScreenFrame"] img {max-height: 560px;
      width: auto !important; max-width: 100%; object-fit: contain; border: 1px solid var(--line); border-radius: 6px;}
.st-key-detail_evidence [data-testid="stMarkdownContainer"] p {line-height: var(--lh-body);}
.st-key-detail_suggest .stButton > button {min-height: 2rem; padding: 2px var(--sp-4); border-radius: var(--radius-pill);
      background: var(--accent-soft); border-color: var(--accent-line); color: var(--accent-ink);}
.st-key-detail_suggest .stButton > button:hover {background: #DCE8EA;}

/* ============================================================
   8ב. בדיקה במבט אחד (review_screen.py): שורת הפתיחה מעל הטבלה, כרטיס התא, ולוח האיכות
   ============================================================ */
/* שורת ההתחלה של records_screen.py (לא review_screen.py): יושבת כבר בתוך כרטיס "בדיקה" (סעיף 7),
   ולכן בלי עיצוב כרטיס משלה - רק גובה אחיד לכפתורים */
.st-key-rev_bar .stButton > button {height: 38px; min-height: 38px; white-space: nowrap;}
.st-key-rv_card {background: var(--paper) !important; border: 1px solid var(--line) !important; border-top: 3px solid var(--accent) !important;
      border-radius: var(--radius) !important; box-shadow: var(--shadow-lift); padding: var(--sp-4) var(--sp-5) var(--sp-5) !important;}
.st-key-rv_actions {background: #FCFBF8 !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
      padding: var(--sp-3) var(--sp-4) var(--sp-4) !important;}
.st-key-rv_actions [data-baseweb="input"] {border: 1px solid var(--line-2); background: var(--paper) !important;}
.st-key-rv_actions .stTextInput input {font-size: var(--fs-section); height: 2.6rem; background: var(--paper) !important;}
.st-key-rv_actions [data-testid="stForm"] {border: none; padding: 0;}
/* "Press Enter to submit form" המובנה של Streamlit חופף את הערך המוקלד בשדה הבדיקה; Enter ממשיך לעבוד, רק הכיתוב מוסתר */
.st-key-rv_actions [data-testid="InputInstructions"], .st-key-detail_actions [data-testid="InputInstructions"] {display: none !important;}
.st-key-rv_chips .stButton > button {min-height: 2rem; padding: 2px var(--sp-4); border-radius: var(--radius-pill);
      background: var(--accent-soft); border-color: var(--accent-line); color: var(--accent-ink);}
.st-key-rv_chips .stButton > button:hover {background: #DCE8EA;}
/* באנר הבדיקה: כרטיס אחד עם כותרת, שורת הסבר, שבבי התקדמות ופס ההתקדמות צמוד לתחתית */
.st-key-rv_banner {background: var(--paper) !important; border: 1px solid var(--line) !important;
      border-top: 3px solid var(--accent) !important; border-radius: var(--radius) !important; box-shadow: var(--shadow);
      padding: var(--sp-3) var(--sp-4) var(--sp-2) !important; margin-bottom: var(--sp-2);}
.st-key-rv_banner [data-testid="stVerticalBlock"] {gap: var(--sp-1);}
.st-key-rv_banner [data-testid="stProgress"] {padding: 0; margin: 2px 0 0;}
.st-key-rv_banner [data-testid="stProgress"] [data-testid="stMarkdownContainer"] {display: none;}
.rv-banner .rv-title {font-size: var(--fs-page); font-weight: 700; color: var(--ink); line-height: var(--lh-tight);}
.rv-banner .rv-sub {font-size: var(--fs-body); color: var(--ink-2); line-height: var(--lh-body); margin-top: 2px;}
.rv-chips {display: flex; flex-wrap: wrap; gap: 6px var(--sp-2); margin: var(--sp-2) 0 var(--sp-1);}
.rv-chip {display: inline-flex; align-items: baseline; gap: 5px; background: var(--wash); border: 1px solid var(--line);
      border-radius: var(--radius-pill); padding: 3px var(--sp-3); font-size: var(--fs-label); color: var(--ink-3);
      white-space: nowrap;}
.rv-chip b {font-size: var(--fs-section); font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums;}
.rv-chip.accent {background: var(--accent-soft); border-color: var(--accent-line); color: var(--accent-ink);}
.rv-chip.accent b {color: var(--accent-ink);}
.rv-field {display: flex; align-items: center; gap: var(--sp-3); margin: 0 0 var(--sp-2);}
.rv-field .rv-name {font-size: var(--fs-section); font-weight: 700; color: var(--ink);}
.rv-none {font-size: var(--fs-cap); color: var(--ink-3);}
/* מסגרת האזור על העמוד המלא: גרפיקה, לא טקסט. המסגרת הכהה והטבעת הלבנה נראות גם על דיו וגם על נייר */
.pg-wrap .pg-mark {position: absolute; border: 3px solid var(--orange-dot); border-radius: 4px;
      background: rgba(176, 106, 30, 0.10); box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.75);}
/* מדדי סוף הבדיקה ולוח האיכות: מספר גדול מעל תווית שקטה */
.rv-metrics {display: flex; flex-wrap: wrap; gap: var(--sp-2); margin: var(--sp-2) 0;}
.rv-metrics > div {flex: 1 1 150px; background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius);
      padding: var(--sp-2) var(--sp-4) 9px;}
.rv-metrics > div > span {display: block; font-size: var(--fs-cap); color: var(--ink-3);}
.rv-metrics > div > b {font-size: 1.28rem; font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums;}
.rv-metrics > div.bad {border-color: var(--orange-line); background: var(--orange-fill);}
.rv-metrics > div.bad > span, .rv-metrics > div.bad > b {color: var(--orange-ink);}
.rv-metrics > div.ok > b {color: var(--green-ink);}

/* ============================================================
   9. מצבים ריקים והנחיות
   ============================================================ */
.placeholder {display: flex; align-items: baseline; gap: var(--sp-2); padding: 11px var(--sp-4); margin-bottom: var(--sp-2); color: var(--ink-3);
      background: var(--paper); border: 1px dashed var(--line-2); border-radius: var(--radius); font-size: var(--fs-label);}
.placeholder b {color: var(--ink); font-weight: 600; font-size: var(--fs-body);}
.empty-filter {background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); padding: var(--sp-5);
      text-align: center; color: var(--ink-3); font-size: var(--fs-body);}
.empty-filter b {display: block; color: var(--green-ink); font-size: var(--fs-section); margin-bottom: var(--sp-1);}
.empty-state {background: var(--paper); border: 1px dashed var(--line-2); border-radius: var(--radius); padding: var(--sp-6) var(--sp-5);
      text-align: center; color: var(--ink-3);}
.empty-state b {display: block; color: var(--ink); font-size: var(--fs-section); font-weight: 600; margin-bottom: 6px;}
.empty-state p {text-align: center !important; margin: 0; font-size: var(--fs-body);}
.st-key-secondary [data-testid="stExpander"] {border: 1px solid var(--line); border-radius: var(--radius); background: var(--paper);}
.st-key-secondary [data-testid="stExpander"] summary p {font-weight: 500; color: var(--ink-2);}
"""

FONTS = "@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');"


def inject() -> None:
    """בלוק עיצוב אחד לכל האפליקציה (נקרא פעם אחת ב-app.py; מסך הרשומות יורש אותו)."""
    st.markdown(f"<style>{FONTS}{CSS}</style>", unsafe_allow_html=True)
