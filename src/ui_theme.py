"""העיצוב של הממשק במקום אחד: אסימוני עיצוב (מרווחים, מדרג גופן, צבעים נייטרליים), בלוק CSS אחד שמוזרק פעם אחת ב-app.py,
ועזרי HTML קטנים (תג מצב, נקודה + מילה, ערך לקריאה בלבד).

תצוגה בלבד. אין כאן שום כלל חילוץ או החלטה: צבעי המצב (ירוק / כתום / צהוב / אושר ידנית / ריק) הם הסמנטיקה של
src/export.py, וכאן נקבע רק הגוון שבו הם מוצגים, כך שכל טקסט יעמוד ביחס ניגודיות של 4.5:1 לפחות מול הרקע שלו.
כל צבע אחר בממשק נייטרלי: צבע = מצב של שדה, ולא קישוט."""
import html

import streamlit as st

# ---------- אסימוני המצב (צבע = מצב של שדה, ולא קישוט) ----------
# ink = צבע הטקסט (נבדק מול fill ומול לבן), fill = רקע התג, line = מסגרת התג, dot = נקודת המצב (לא טקסט).
STATE_INK = {"green": "#276842", "orange": "#7E4E15", "yellow": "#5F5318", "confirmed": "#2F5E8E", "empty": "#5A655F"}
STATE_FILL = {"green": "#EAF4EE", "orange": "#FBEFDF", "yellow": "#F4EDD3", "confirmed": "#E6EEF8", "empty": "#F2F0EA"}
STATE_LINE = {"green": "#CFE5D7", "orange": "#F0D9B8", "yellow": "#E4D8A8", "confirmed": "#C9D9EC", "empty": "#E3E0D7"}
STATE_DOT = {"green": "#2E7D4F", "orange": "#B06A1E", "yellow": "#8A7A22", "confirmed": "#3E72A6", "empty": "#8E948F"}
STATE_LABEL = {"green": "ירוק", "orange": "לבדיקה", "yellow": "זהב", "confirmed": "אושר ידנית", "empty": "ריק"}
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
  --fs-page: 1.32rem; --fs-section: 1.02rem; --fs-body: 0.92rem; --fs-label: 0.8rem; --fs-cap: 0.78rem;
  --lh-tight: 1.25; --lh-body: 1.6;
  /* נייטרלי: טקסט, משטחים, קווים (ink-2 / ink-3 נבדקו ל-4.5:1 לפחות מול --wash, הרקע הכהה ביותר שיש) */
  --ink: #1C2321; --ink-2: #3D4945; --ink-3: #5A655F;
  --paper: #FFFFFF; --canvas: #F7F6F2; --wash: #F2F0EA;
  --line: #E3E0D7; --line-2: #CFCBBF;
  --accent: #2D5F6B; --accent-ink: #1F4A54; --accent-soft: #E7EFF0; --accent-line: #CFDFE1;
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
.block-container {max-width: 1560px; padding: var(--sp-4) var(--sp-6) var(--sp-6);}
[data-testid="stVerticalBlock"] {gap: var(--sp-3);}
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
.lab-header {display: flex; align-items: baseline; gap: var(--sp-3); flex-wrap: wrap; border-right: 3px solid var(--accent);
      padding: 0 var(--sp-3) 0 0; margin: 0 0 var(--sp-2);}
.lab-header .title {font-size: var(--fs-page); font-weight: 700; color: var(--ink); line-height: var(--lh-tight);}
.lab-header .org {font-size: var(--fs-label); font-weight: 500; color: var(--accent);}
.lab-header .hint {font-size: var(--fs-cap); color: var(--ink-3); margin-inline-start: auto;}
.sec {display: flex; align-items: baseline; gap: var(--sp-2); margin: var(--sp-1) 0 var(--sp-2);}
.sec-title {font-size: var(--fs-section); font-weight: 600; color: var(--ink);}
.sec-hint {font-size: var(--fs-cap); color: var(--ink-3);}
.col-label {font-size: var(--fs-label); font-weight: 700; letter-spacing: .02em; color: var(--ink-3); margin-bottom: var(--sp-1);}
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
.flag {display: inline-flex; align-items: center; gap: 6px; margin: 2px 0 2px 6px; padding: 2px 10px; border-radius: var(--radius-pill);
      color: var(--orange-ink); background: var(--orange-fill); border: 1px solid var(--orange-line); font-size: var(--fs-cap);}

/* ============================================================
   5. פקדים: כפתורים, שדות קלט, העלאה, הודעות
   ============================================================ */
.stButton > button, .stDownloadButton > button {border-radius: var(--radius-sm); font-weight: 500; border: 1px solid var(--line-2);
      background: var(--paper); color: var(--ink); transition: border-color .15s, background .15s;}
.stButton > button:hover, .stDownloadButton > button:hover {border-color: var(--accent); color: var(--accent);}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {background: var(--accent); border-color: var(--accent); color: #fff;}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {background: #244D58; border-color: #244D58; color: #fff;}
.stButton > button:disabled, .stDownloadButton > button:disabled {background: var(--wash); color: #767C76; border-color: var(--line);}
[data-baseweb="input"], [data-baseweb="select"] > div {border-radius: var(--radius-sm);}
.stTextInput label p, .stSelectbox label p, .stMultiSelect label p, [data-testid="stDateInput"] label p, .stNumberInput label p,
[data-testid="stSlider"] label p {font-size: var(--fs-label) !important; color: var(--ink-2) !important;}
/* תווית עברית מעל פקד שבו Streamlit לא מאפשר placeholder: הטקסט האנגלי הריק מוסתר */
[data-testid="stDateInput"] input::placeholder {color: transparent;}
[data-testid="stFileUploaderDropzone"] {background: var(--wash); border: 1px dashed var(--line-2); border-radius: var(--radius-sm);}
[data-testid="stFileUploaderDropzoneInstructions"] > div > span, [data-testid="stFileUploaderDropzoneInstructions"] small,
[data-testid="stFileUploaderDropzoneInstructions"] svg {display: none;}
[data-testid="stFileUploaderDropzoneInstructions"] > div::before {content: "גררי לכאן קובץ PDF או תמונה (עד 25MB)"; font-size: 14px; color: var(--ink-2);}
[data-testid="stFileUploaderDropzone"] button, [data-testid="stFileUploaderDropzone"] button * {font-size: 0 !important;}
[data-testid="stFileUploaderDropzone"] button::after {content: "בחירת קובץ"; font-size: 13px !important;}
[data-testid="stAlert"] {border-radius: var(--radius-sm);}
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {font-size: var(--fs-body);}
[data-testid="stExpander"] {border: 1px solid var(--line); border-radius: var(--radius-sm); background: var(--paper);}
[data-testid="stExpander"] summary p {font-size: var(--fs-label); color: var(--ink-2);}
[data-testid="stPopoverBody"] {direction: rtl; text-align: right;}

/* ============================================================
   6. משטחים: כרטיס פעולה, פס מדדים, סרגל סינון, טבלה
   ============================================================ */
.st-key-action_card {position: sticky; top: var(--sp-1); z-index: 100; background: var(--paper) !important; border: 1px solid var(--line) !important;
      border-radius: var(--radius) !important; padding: var(--sp-2) var(--sp-2) !important; box-shadow: var(--shadow);}
.st-key-action_card [data-testid="stFileUploaderDropzone"] {padding: 0 var(--sp-3); min-height: 40px; height: 40px;}
.st-key-action_card [data-testid="stFileUploaderDropzone"] button {min-height: 30px; height: 30px; padding: 0 var(--sp-3);}
.st-key-action_card .stButton > button, .st-key-action_card .stDownloadButton > button {height: 40px; min-height: 40px;}
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
/* מסנני הסטטוס בטבלת העיבוד: גלולות במילוי רך לפי המצב */
.st-key-status_filter [role="radiogroup"] {gap: 6px; flex-wrap: wrap;}
.st-key-status_filter button {--chip-bg: var(--wash); --chip-ink: var(--ink-2); --chip-on: var(--accent);
      border: 1px solid transparent !important; border-radius: var(--radius-pill) !important; background: var(--chip-bg) !important;
      color: var(--chip-ink) !important; padding: 5px var(--sp-4) !important; min-height: 2.1rem; box-shadow: none !important;
      transition: background .15s, color .15s;}
.st-key-status_filter button p {color: inherit !important; font-size: var(--fs-label); white-space: nowrap;}
.st-key-status_filter button p strong {font-weight: 700; opacity: .8;}
.st-key-status_filter button:nth-of-type(2) {--chip-bg: var(--green-fill); --chip-ink: var(--green-ink); --chip-on: var(--green-dot);}
.st-key-status_filter button:nth-of-type(3) {--chip-bg: var(--orange-fill); --chip-ink: var(--orange-ink); --chip-on: var(--orange-dot);}
.st-key-status_filter button:nth-of-type(4) {--chip-bg: var(--yellow-fill); --chip-ink: var(--yellow-ink); --chip-on: var(--yellow-dot);}
.st-key-status_filter button:nth-of-type(5) {--chip-bg: var(--paper); --chip-ink: var(--ink-3); --chip-on: var(--empty-dot); border: 1px dashed var(--line-2) !important;}
.st-key-status_filter button:hover {filter: brightness(0.97);}
.st-key-status_filter button[data-selected="true"] {background: var(--chip-on) !important; color: var(--paper) !important; border-color: var(--chip-on) !important;}
.st-key-status_filter button[data-selected="true"] p strong {opacity: 1;}
.st-key-focus_wrap {background: var(--accent-soft); border: 1px solid var(--accent-line); border-radius: var(--radius-pill);
      padding: 5px var(--sp-4) !important; width: fit-content; margin-inline-start: auto;}
.st-key-focus_wrap label p {font-size: var(--fs-label) !important; font-weight: 600 !important; color: var(--accent-ink) !important; white-space: nowrap;}
[data-testid="stDataFrame"] {border: 1px solid var(--line); border-radius: var(--radius); background: var(--paper); box-shadow: var(--shadow); overflow: hidden;}
/* הרשת מצוירת על canvas משמאל לימין (סדר העמודות כבר הפוך בקוד). בלי זה ה-canvas יורש RTL מהדף, ו-"939068 ; 944004" מתהפך */
[data-testid="stDataFrame"], [data-testid="stDataFrame"] canvas {direction: ltr;}

/* ============================================================
   7. מסך הרשומות: פס המונים, חיפוש, סינון מתקדם, שורת העימוד
   ============================================================ */
.st-key-rec_top {background: var(--paper) !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
      box-shadow: var(--shadow); padding: var(--sp-3) var(--sp-3) var(--sp-2) !important;}
.st-key-rec_counters {gap: 6px !important;}
/* המונים כקבוצה מפולחת אחת: גלולות באותו גובה, הנבחרת במילוי המותג */
.st-key-rec_counters .stButton > button {border-radius: var(--radius-pill); background: var(--wash); border-color: transparent;
      color: var(--ink-2); font-size: var(--fs-label); font-weight: 500; min-height: 2.2rem; padding: 0 var(--sp-4); white-space: nowrap;}
.st-key-rec_counters .stButton > button:hover {border-color: var(--accent-line); background: var(--accent-soft); color: var(--accent-ink);}
.st-key-rec_counters .stButton > button[kind="primary"] {background: var(--accent); border-color: var(--accent); color: var(--paper);}
.st-key-rec_top .stTextInput input {font-size: var(--fs-body); height: 2.3rem;}
.st-key-rec_filters [data-testid="stExpander"] {border: 1px solid var(--line); background: var(--paper);}
.st-key-rec_filters [data-testid="stExpander"] summary p {font-weight: 500; color: var(--ink-2); font-size: var(--fs-label);}
.filter-badge {display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-cap); font-weight: 600; color: var(--accent-ink);
      background: var(--accent-soft); border: 1px solid var(--accent-line); border-radius: var(--radius-pill); padding: 1px 9px;}
.st-key-rec_pager {border-top: 1px solid var(--line); padding-top: var(--sp-2) !important; margin-top: 2px;}
.st-key-rec_pager [data-baseweb="input"], .st-key-rec_pager [data-baseweb="select"] > div {min-height: 2rem;}
.st-key-rec_pager .stNumberInput, .st-key-rec_pager .stSelectbox {max-width: 190px;}
.st-key-rec_export .stDownloadButton > button {min-height: 2rem;}
/* כרטיס הרשומה: סרגל פעולות אחד בראש, ואז הכותרת והשדות */
.st-key-rec_detail {background: var(--paper) !important; border: 1px solid var(--line) !important; border-top: 3px solid var(--accent) !important;
      border-radius: var(--radius) !important; box-shadow: var(--shadow-lift); padding: var(--sp-4) var(--sp-5) var(--sp-5) !important;
      scroll-margin-top: 120px;}
.st-key-rec_actions .stButton > button {height: 38px; min-height: 38px; white-space: nowrap;}
.st-key-rec_head {display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap;}
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
