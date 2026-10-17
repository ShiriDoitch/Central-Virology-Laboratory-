"""ממשק Streamlit: העלאת טפסי התחייבות, הצגת השדות בצבעים, פירוט ראיות לכל שדה, וייצוא לאקסל.
הפעלה: streamlit run app.py   (בלי שינוי כללים: כל ההחלטות ב-src/rules.py ו-src/senders.py)."""
import io
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from src.confirm import FIELD_REGION, field_crop, flag_chips_html, md_code, md_text, name_suggestions, override_key, set_override, zoom_html
from src.export import COLUMNS, CONFIRMED, FIELD_KEYS, GREEN, ORANGE, YELLOW, _readings, build_rows, build_workbook, pass2_issues, skip_reason
from src.intake import pdf_to_images, rotate_jpeg
from src.schema import PageExtraction
from src.upload import cleanup_stale_uploads, process_upload, to_pdf_bytes  # noqa: F401  (to_pdf_bytes: לשימוש חיצוני / בדיקות)

SAMPLE_DIR = Path("outputs/clean_part1_v4b")      # הריצה השמורה (בלי API)
SAMPLE_PDF = Path("data/clean_part1.pdf")         # עמודים נקיים, בלי סימון צהוב
TRUTH_PATH = Path("data/truth_part1.xlsx")
MAX_UPLOAD_MB = 25
GREEN_HEX, ORANGE_HEX = "#" + GREEN.fgColor.rgb[-6:], "#" + ORANGE.fgColor.rgb[-6:]
CONFIRMED_HEX = "#" + CONFIRMED.fgColor.rgb[-6:]      # שם שאושר על ידי המשתמש
YELLOW_HEX = "#" + YELLOW.fgColor.rgb[-6:]            # ערך בכתב יד, שתי קריאות מסכימות: מבט לאישור
# צבעי הביטחון בממשק (נקודה וצבע טקסט, לא מילוי תא). האקסל נשאר בצבעי src/export.py.
UI_TONE = {GREEN_HEX: "#2E7D4F", ORANGE_HEX: "#96621F", YELLOW_HEX: "#8A7A2E", CONFIRMED_HEX: "#3F6FA0"}
UI_DOT = {"green": "#2E7D4F", "orange": "#B8762E", "yellow": "#8A7A2E", "confirmed": "#3F6FA0"}
CODE_KEYS = ("id", "center", "commitment")           # שדות שהם קודים מילוליים: מוצגים במונוספייס
TITLES = dict(COLUMNS)
NAME_KEYS = ("first_name", "last_name")
NOT_READ_TEXT = "לא נקרא, יש להקליד"
YELLOW_TEXT = "נקרא בכתב יד בשתי קריאות עצמאיות שמסכימות, מספיק מבט לאישור"

# שמות הדגלים בעברית (תצוגה בלבד; הקודים נשארים בקוד ובאקסל)
FLAG_HE = {
    "handwritten": "כתב יד",
    "low_confidence": "ביטחון נמוך של המודל",
    "conflict": "סתירה בין קריאות",
    "invalid_format": "פורמט לא מזוהה",
    "invalid_date": "תאריך לא חוקי",
    "year_out_of_range": "שנה מחוץ לטווח",
    "receipt_before_sample": "קבלה לפני דגימה",
    "not_receipt_kind": "תאריך שאינו תאריך קבלה",
    "not_lab_received": "לא נרשם בקבלה של המעבדה",
    "non_digit": "מספר עם תווים שאינם ספרות",
    "no_commitment": "לא נמצא מספר התחייבות",
    "no_center_label": "מספר בלי תווית מרכזי",
    "center_mismatch": "מועמדי מרכזי שונים בין המעברים",
    "id_single_source": "ת\"ז נקראה במעבר אחד בלבד",
    "id_checksum_failed": "ספרת הביקורת של הת\"ז לא תקינה (הערך לא שונה)",
    "date_outside_window": "תאריך קבלה מחוץ לחלון (דגימה עד 14 יום אחרי השליחה/הדגימה, לא בעתיד, לא אחרי התוקף)",
    "date_single_source": "תאריך נקרא בקריאה אחת בלבד (בלי קריאה שנייה מחיתוך אזור הקבלה)",
    "id_not_israeli_format": "פורמט לא ישראלי (אותיות או יותר מ-9 ספרות), ספרת ביקורת לא נבדקה",
    "region_not_ok": "האזור שנחתך לא תקין",
    "handwritten_unconfirmed": "כתב יד בקריאה אחת, לא מאושר",
    "father_name": "שם האב (לא שם המטופל)",
    "name_label_unknown": "תווית השם לא מוכרת",
    "missing_required_field": "שדה חובה חסר",
    "unknown_sender": "גורם שולח לא מוכר",
    "patient_field_only": "מופיע רק בשדה המטופל",
    "fuzzy_match": "התאמה מקורבת לגורם מוכר",
    "name_label_missing": "שם מודפס בלי תווית מטופל (הצעה בלבד)",
    "date_kind_unclear": "סוג התאריך לא ברור",
    "commitment_mismatch": "קריאות שונות של מספר ההתחייבות",
    "commitment_single_source": "מספר התחייבות נקרא במעבר אחד בלבד",
    "weak_label": "תווית חלשה (\"מספר\")",
    "model_says_not_commitment_form": "המודל סימן: לא טופס התחייבות",
    "rotation_unresolved": "הסיבוב לא נפתר",
    "center_from_barcode_only": "המרכזי נקרא מהברקוד בלבד (המודל לא מצא), לבדיקה",
}


def he_flag(code: str, key: str | None = None) -> str:
    """שם הדגל בעברית. missing_required_field נקרא בשם השדה שבו לחצו (למשל "מספר מרכזי חסר"), לא בטקסט קבוע."""
    if code == "missing_required_field" and key in TITLES:
        return f"{TITLES[key]} חסר"
    return FLAG_HE.get(code, code)

@st.cache_resource(show_spinner=False)
def _startup_cleanup() -> int:
    """פעם אחת לכל תהליך שרת (לא בכל ריצה מחדש של הסקריפט): מוחק קובצי PDF זמניים שנשארו מריצה שקרסה (src/upload.py)."""
    return cleanup_stale_uploads()


st.set_page_config(page_title="חילוץ טפסי התחייבות", layout="wide")
_startup_cleanup()
st.markdown(
    """<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    /* כיוון וגופן: עברית מימין לשמאל, Heebo לכל הטקסט; מונוספייס רק לקודים (ת"ז, מרכזי, התחייבות, ברקוד) */
    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], .main, .block-container {direction: rtl; text-align: right;}
    html, body, .stApp, button, input, textarea, [data-testid="stMarkdownContainer"] {font-family: 'Heebo', sans-serif;}
    code {font-family: 'IBM Plex Mono', monospace !important; direction: ltr; unicode-bidi: embed; background: #F0EEE8; color: #1C2321; border-radius: 4px; padding: 1px 6px; font-size: 0.92em;}
    h1 {font-size: 1.9rem !important; font-weight: 600 !important; letter-spacing: 0 !important;}
    h5, h3 {font-weight: 600 !important;}
    [data-testid="stCaptionContainer"] {color: #5B6460;}
    /* מדדי סיכום: שורת מספרים שקטה עם קו עליון, בלי כרטיסים */
    [data-testid="stMetric"] {background: transparent; border: 0; border-top: 2px solid #D9D6CC; border-radius: 0; padding: 8px 2px 4px; direction: rtl;}
    [data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #5B6460;}
    [data-testid="stMetricValue"] {font-size: 1.6rem; font-weight: 600;}
    /* מקרא: נקודה + טקסט, בלי רקע צבעוני */
    .legend {display: flex; flex-wrap: wrap; gap: 6px 22px; margin: 10px 0 18px; font-size: 0.88rem; color: #2F3836;}
    .legend span {display: inline-flex; align-items: center; gap: 7px;}
    .dot {display: inline-block; width: 9px; height: 9px; border-radius: 50%; flex: none;}
    .dot.empty {border: 1.5px solid #9A9A92; background: transparent;}
    /* דגלים בפירוט: טקסט עם נקודת ענבר, בלי תווית צבועה */
    .flag {display: inline-flex; align-items: center; gap: 6px; margin: 2px 0 2px 14px; color: #96621F; font-size: 0.92rem;}
    .flag::before {content: ""; width: 8px; height: 8px; border-radius: 50%; background: #B8762E; flex: none;}
    /* כפתורים והעלאה בצבעי הנושא (טורקיז), לא ברירת המחדל של Streamlit */
    .stButton > button, .stDownloadButton > button {border-radius: 6px; font-weight: 500; border: 1px solid #CFCBBF; background: #FAFAF8;}
    .stButton > button:hover {border-color: #2D5F6B; color: #2D5F6B;}
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {background: #2D5F6B; border-color: #2D5F6B; color: #fff;}
    .stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {background: #244D58; border-color: #244D58; color: #fff;}
    [data-testid="stFileUploaderDropzone"] {background: #F0EEE8; border: 1px dashed #B9B5A8; border-radius: 6px;}
    [data-testid="stAlert"] {border-radius: 6px; border: 1px solid #D9D6CC;}
    [data-testid="stExpander"], [data-testid="stDataFrame"] {border: 1px solid #D9D6CC; border-radius: 6px;}
    /* בלי כפתור Deploy ובלי תפריט */
    [data-testid="stToolbar"], [data-testid="stDeployButton"], .stDeployButton, #MainMenu, footer {display:none !important;}
    /* העלאת קובץ בעברית */
    [data-testid="stFileUploaderDropzoneInstructions"] > div > span, [data-testid="stFileUploaderDropzoneInstructions"] small {display:none;}
    [data-testid="stFileUploaderDropzoneInstructions"] > div::before {content: "גררי לכאן קובץ PDF או תמונה (עד 25MB)"; font-size: 15px;}
    [data-testid="stFileUploaderDropzone"] button, [data-testid="stFileUploaderDropzone"] button * {font-size: 0 !important;}
    [data-testid="stFileUploaderDropzone"] button::after {content: "בחירת קובץ"; font-size: 14px !important;}
    </style>""",
    unsafe_allow_html=True,
)


# ---------- טעינה ועיבוד ----------

def load_sample() -> tuple[list[dict], dict[int, bytes]]:
    """טוען את הריצה השמורה של חלק 1 (בלי API) ואת תמונות העמודים הנקיים (עם הסיבוב שהוחל)."""
    pages, images = [], {}
    for f in sorted(SAMPLE_DIR.glob("p*.json"), key=lambda x: int(x.stem[1:])):
        res = json.loads(f.read_text(encoding="utf-8"))
        pages.append(res)
        img = pdf_to_images(str(SAMPLE_PDF), dpi=110, pages=[res["page"]])[0]
        applied = (res.get("rotation") or {}).get("applied")
        images[res["page"]] = rotate_jpeg(img, applied) if applied else img
    return pages, images


# ---------- תצוגה ----------

def table_data(pages: list[dict], overrides: dict | None = None):
    """טבלת התצוגה (עמודות בסדר הפוך כי הרשת מצוירת משמאל לימין) + צבעים + שורות הייצוא."""
    export_rows, records, colors = [], [], []
    for p in sorted(pages, key=lambda x: x["page"]):
        if skip_reason(p):
            continue
        for er in build_rows(p, overrides):
            export_rows.append((p, er))
            records.append({TITLES[k]: er.cells[k].shown for k in FIELD_KEYS})
            colors.append({TITLES[k]: (CONFIRMED_HEX if er.cells[k].confirmed else YELLOW_HEX if er.cells[k].yellow else
                                       ORANGE_HEX if er.cells[k].orange else (GREEN_HEX if er.cells[k].value else ""))
                           for k in FIELD_KEYS})
    cols = [TITLES[k] for k in reversed(FIELD_KEYS)]
    return pd.DataFrame(records, columns=cols), pd.DataFrame(colors, columns=cols), export_rows


def style(df: pd.DataFrame, colors: pd.DataFrame):
    """נקודה "●" לפני הערך וצבע טקסט לפי הסטטוס, בלי מילוי תא. תא ריק שסומן מציג "● —"; תא ריק בלי דגל נשאר ריק."""
    shown = df.where(colors == "", "● " + df.astype(str).replace("", "—"))
    return shown.style.apply(lambda _: colors.map(lambda c: f"color: {UI_TONE[c]}" if c in UI_TONE else ""), axis=None)


def per_field_counts(export_rows) -> pd.DataFrame:
    """לכל שדה: כמה ירוקים / כתומים (כולל ריק מסומן) / ריקים / מאושרים על ידי המשתמש."""
    rows = []
    for key in FIELD_KEYS:
        g = o = e = k = y = 0
        for _, er in export_rows:
            c = er.cells[key]
            if c.confirmed:
                k += 1
            elif c.yellow:
                y += 1
            elif c.orange:
                o += 1
            elif c.value:
                g += 1
            else:
                e += 1
        rows.append({"שדה": TITLES[key], "ירוק": g, "כתום": o, "צהוב": y, "ריק": e, "מאושר": k})
    return pd.DataFrame(rows)


def orange_correct(pages: list[dict]) -> tuple[int, int]:
    """מהתאים הכתומים שיש בהם ערך (בדוגמה מחלק 1): כמה תואמים לטבלת האמת. אותה השוואה כמו evaluate."""
    from src.assemble import page_rows
    from src.evaluate import compare_page, load_truth

    try:
        truth = load_truth(TRUTH_PATH)
    except Exception:
        return 0, 0
    ok = total = 0
    for p in pages:
        if skip_reason(p) or p["page"] not in truth:
            continue
        r2 = p.get("pass2") if (p.get("pass2") or {}).get("ok") else None
        for info in compare_page(truth[p["page"]], page_rows(p["pass1"], regions=r2, barcodes=p.get("barcodes"))).values():
            if info["category"] in ("orange_ok", "orange_wrong"):
                total += 1
                ok += info["category"] == "orange_ok"
    return ok, total


def crop_for(page_res: dict, key: str) -> bytes | None:
    """חיתוך האזור של השדה מהעמוד הנקי (None לתאריך ולשולח: אין אזור). בהעלאה: נוצר בעיבוד. בדוגמה: בפעם הראשונה שמבקשים."""
    region = FIELD_REGION.get(key)
    if not region:
        return None
    crops = st.session_state.setdefault("field_crops", {})
    token = (page_res["page"], region)
    if token not in crops and st.session_state.get("is_sample"):
        crops[token] = field_crop(str(SAMPLE_PDF), page_res, key)
    return crops.get(token)


def _choose(page: int, okey: str, value: str) -> None:
    """לחיצה על הצעה: הערך נשמר כערך הסופי (אישור משתמש) ומוצג גם בשדה ההקלדה."""
    set_override(st.session_state.setdefault("name_overrides", {}), page, okey, value)
    st.session_state[f"txt_{page}_{okey}"] = value


def _confirm_typed(page: int, okey: str) -> None:
    text = st.session_state.get(f"txt_{page}_{okey}", "")
    try:
        set_override(st.session_state.setdefault("name_overrides", {}), page, okey, text)
        st.session_state[f"txt_{page}_{okey}"] = st.session_state["name_overrides"].get((page, okey), "")
        st.session_state.pop(f"err_{page}_{okey}", None)
    except ValueError:
        st.session_state[f"err_{page}_{okey}"] = True      # ערך לא תקין לשדה: האישור הקודם לא משתנה


def _clear(page: int, okey: str) -> None:
    set_override(st.session_state.setdefault("name_overrides", {}), page, okey, None)
    st.session_state[f"txt_{page}_{okey}"] = ""
    st.session_state.pop(f"err_{page}_{okey}", None)


INPUT_HINTS = {"id": 'ספרות בלבד', "commitment": "ספרות בלבד", "center": "ספרות; כמה ערכים מופרדים ב-;", "date": "dd.mm.yyyy"}


def render_confirmation(page_res: dict, er, key: str) -> None:
    """אישור ערך על ידי המשתמש, לכל שדה: חיתוך האזור מהעמוד הנקי (עם הגדלה), הצעות כלחצנים (גם כשהתא ריק), הקלדה חופשית.
    ערך שהוקלד או נבחר נשמר כערך סופי ומיוצא כ"אושר על ידי המשתמש" (כחול). בלי אישור, שם בכתב יד נשאר כתום."""
    cell, page = er.cells[key], er.page
    okey = override_key(key, er.index)
    overrides = st.session_state.setdefault("name_overrides", {})
    crop = crop_for(page_res, key)
    if crop:
        zoom = st.slider("הגדלה", 100, 600, 200, 50, key=f"zoom_{page}_{FIELD_REGION[key]}", format="%d%%")
        st.markdown(zoom_html(crop, zoom), unsafe_allow_html=True)
        st.caption("האזור שממנו נקרא השדה, מהעמוד הנקי. ההגדלה בסרגל משנה את גודל התמונה, וגוללים בתוך המסגרת.")
    else:
        st.caption("אין חיתוך זמין לשדה הזה; העמוד המלא מוצג.")
    if cell.confirmed:
        st.success(f"אושר על ידי המשתמש: {md_text(cell.value)}")
    elif cell.yellow:
        st.info(YELLOW_TEXT)
    elif cell.orange:
        st.warning("לא בטוח (כתום): " + (", ".join(md_text(he_flag(f, key)) for f in cell.flags) or "—"))
    elif cell.value:
        st.info(f"ערך של המערכת: {md_text(cell.value)}")
    suggestions = name_suggestions(cell, key)
    if suggestions:
        st.markdown("**הצעות (לחצי כדי לאשר):**")
        if key == "id" and "id_checksum_failed" in cell.flags and not cell.confirmed:
            st.caption("אחרי הערך שנקרא: החלפת ספרה אחת בזוגות מבולבלים שעוברת את ספרת הביקורת. אין תיקון אוטומטי.")
        for i, sug in enumerate(suggestions):
            st.button(md_text(sug), key=f"sg_{page}_{okey}_{i}", on_click=_choose, args=(page, okey, sug))
    elif key in NAME_KEYS:
        st.warning(NOT_READ_TEXT)
    else:
        st.caption("אין הצעות לשדה הזה. אפשר להקליד ערך.")
    txt_key = f"txt_{page}_{okey}"
    st.session_state.setdefault(txt_key, overrides.get((page, okey), ""))
    st.text_input("או הקלדה ידנית" + (f" ({INPUT_HINTS[key]})" if key in INPUT_HINTS else ""), key=txt_key)
    if st.session_state.get(f"err_{page}_{okey}"):
        st.error("הערך לא תקין לשדה הזה, לא נשמר" + (f" ({INPUT_HINTS[key]})" if key in INPUT_HINTS else ""))
    c1, c2 = st.columns(2)
    c1.button("אשרי את הערך שהוקלד", key=f"ok_{page}_{okey}", on_click=_confirm_typed, args=(page, okey), type="primary")
    if cell.confirmed:
        c2.button("בטלי אישור", key=f"clr_{page}_{okey}", on_click=_clear, args=(page, okey))


def render_detail(page_res: dict, er, key: str, image: bytes | None) -> None:
    cell = er.cells[key]
    st.subheader(f"{TITLES[key]} · עמוד {er.page}")
    if crop_for(page_res, key) and image:
        render_confirmation(page_res, er, key)
        with st.expander("העמוד המלא"):
            st.image(image, caption=f"עמוד {er.page}", width="stretch")
    else:
        if image:
            st.image(image, caption=f"עמוד {er.page}", width="stretch")
        render_confirmation(page_res, er, key)
    code = md_code if key in CODE_KEYS else md_text       # קודים במונוספייס; שמות ופרוזה לא. כל טקסט מהטופס עובר escape
    st.markdown(f"**ערך:** {code(cell.value) if cell.value else '—'}" + (f"  \n**נקרא (raw):** {code(cell.raw)}" if not cell.value and cell.raw else ""))
    if cell.flags:
        st.markdown("**לבדיקה:** " + flag_chips_html(he_flag(f, key) for f in cell.flags), unsafe_allow_html=True)
    else:
        st.markdown("**לבדיקה:** אין")
    if cell.alternatives and key not in NAME_KEYS:
        label = "מועמדים שנמצאו (התא ריק)" if not cell.value else "חלופות"
        st.markdown(f"**{label}:** " + " | ".join(md_text(a) for a in cell.alternatives))
    if cell.hints:
        st.caption("רמזים: " + ", ".join(cell.hints))
    r1 = PageExtraction.model_validate(page_res["pass1"])
    p1, p2 = _readings(key, r1, page_res.get("pass2"))
    with st.expander("קריאות גולמיות של המודל"):
        st.text(f"מעבר ראשון: {p1 or '—'}\nמעבר שני: {p2 or '—'}")


# ---------- דף ----------

st.title("חילוץ טפסי התחייבות")
st.caption("המעבדה הווירולוגית המרכזית · שורה אחת לכל התחייבות · שדה כתום = לא בטוח, לבדיקה אנושית")

left, right = st.columns([3, 2])
with left:
    upload = st.file_uploader("העלאת טופס (PDF או תמונה)", type=["pdf", "png", "jpg", "jpeg"])
with right:
    st.write("")
    st.write("")
    c1, c2 = st.columns(2)
    run_clicked = c1.button("עבד", type="primary", disabled=upload is None, width="stretch")
    sample_clicked = c2.button("טען דוגמה מחלק 1", width="stretch")

progress_slot = st.empty()
if sample_clicked:
    try:
        st.session_state["pages"], st.session_state["images"] = load_sample()
        st.session_state["is_sample"] = True
        st.session_state["field_crops"], st.session_state["name_overrides"] = {}, {}
    except Exception as e:
        st.error(f"טעינת הדוגמה נכשלה ({type(e).__name__}). האם הריצה נמצאת ב-{SAMPLE_DIR}?")
if run_clicked and upload is not None:
    if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_MB}MB)")
    elif not os.getenv("GEMINI_API_KEY") and not Path(".env").exists():
        st.error("חסר GEMINI_API_KEY בקובץ .env")
    else:
        bar = progress_slot.progress(0.0, text="מתחיל")
        try:
            st.session_state["pages"], st.session_state["images"], st.session_state["field_crops"] = process_upload(
                upload.name, upload.getvalue(), bar)
            st.session_state["is_sample"] = False
            st.session_state["name_overrides"] = {}
        except Exception as e:
            st.error(f"העיבוד נכשל: {e}")

pages = st.session_state.get("pages")
images = st.session_state.get("images", {})
if not pages:
    st.info("העלי קובץ ולחצי \"עבד\", או לחצי \"טען דוגמה מחלק 1\".")
    st.stop()

overrides = st.session_state.setdefault("name_overrides", {})
df, colors, export_rows = table_data(pages, overrides)
skipped = [(p["page"], r) for p in sorted(pages, key=lambda x: x["page"]) if (r := skip_reason(p))]
fields = len(df) * len(FIELD_KEYS)
n_green = int((colors == GREEN_HEX).to_numpy().sum())
n_orange = int((colors == ORANGE_HEX).to_numpy().sum())
n_confirmed = int((colors == CONFIRMED_HEX).to_numpy().sum())
n_yellow = int((colors == YELLOW_HEX).to_numpy().sum())
n_empty = fields - n_green - n_orange - n_confirmed - n_yellow

orange_ok, orange_total = orange_correct(pages) if st.session_state.get("is_sample") else (0, 0)
m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
m1.metric("טפסים (התחייבויות)", len(df))
m2.metric("שדות ירוקים", n_green)
m3.metric("שדות כתומים", n_orange, help="כולל שדה ריק שסומן לבדיקה")
m4.metric("שדות ריקים", n_empty, help="לא נמצא, בלי דגל")
m7.metric("שדות צהובים", n_yellow, help=YELLOW_TEXT)
m6.metric("שדות שאושרו על ידי המשתמש", n_confirmed, help="ערך שהוקלד או נבחר ידנית; מיוצא באקסל בכחול")
m5.metric("מהכתומים, כמה נכונים", f"{orange_ok} מתוך {orange_total}" if orange_total else "—",
          help="נמדד מול טבלת האמת, רק בדוגמה מחלק 1 ורק בתאים כתומים שיש בהם ערך" if orange_total else "אין טבלת אמת לקובץ שהועלה")
issues = pass2_issues(pages)
if issues["fallback"]:
    st.warning("מעבר 2 נקרא במודל הגיבוי החלש (המודל החזק לא זמין או נכשל) בעמודים: "
               + ", ".join(map(str, issues["fallback"])) + ". הקריאות בעמודים האלה פחות אמינות, מומלץ לבדוק ידנית.")
if issues["quota"]:
    st.warning("מעבר 2 דולג בגלל מכסה יומית שנגמרה בעמודים: " + ", ".join(map(str, issues["quota"]))
               + ". יש רק קריאה אחת של העמוד בשדות האלה.")
if issues["failed"]:
    st.warning("מעבר 2 נכשל בעמודים: " + ", ".join(map(str, issues["failed"])) + ".")
st.dataframe(per_field_counts(export_rows), hide_index=True, width="stretch")
st.markdown(
    f"<div class='legend'><span><i class='dot' style='background:{UI_DOT['green']}'></i>ירוק: ערך בלי דגל</span>"
    f"<span><i class='dot' style='background:{UI_DOT['orange']}'></i>כתום: לבדיקה</span>"
    f"<span><i class='dot' style='background:{UI_DOT['yellow']}'></i>זהב (ת\"ז או שם): {YELLOW_TEXT}</span>"
    f"<span><i class='dot' style='background:{UI_DOT['confirmed']}'></i>כחול: ערך שאושר על ידי המשתמש</span>"
    f"<span><i class='dot empty'></i>ריק: לא נמצא</span></div>",
    unsafe_allow_html=True,
)

table_col, detail_col = st.columns([3, 2])
selected = None
with table_col:
    st.markdown("##### תוצאות (לחצי על תא כדי לראות ראיות)")
    try:
        event = st.dataframe(style(df, colors), width="stretch", hide_index=False, on_select="rerun",
                             selection_mode="single-cell", key="grid")
        cells = event.selection.cells
        if cells:
            row, col = cells[0]
            selected = (int(row), col if isinstance(col, str) else df.columns[int(col)])
            st.session_state["selected_cell"] = selected
        else:
            selected = st.session_state.get("selected_cell")
            if selected and selected[0] >= len(df):
                selected = None
    except Exception:                                   # גרסת Streamlit בלי בחירת תא: בחירה ידנית
        r_i = st.selectbox("שורה", range(len(df)), format_func=lambda i: f"שורה {i + 1} · עמוד {export_rows[i][1].page}")
        c_i = st.selectbox("שדה", list(df.columns))
        selected = (r_i, c_i)

with detail_col:
    if selected:
        row_i, col_name = selected
        key = next(k for k, t in COLUMNS if t == col_name)
        page_res, er = export_rows[row_i]
        render_detail(page_res, er, key, images.get(er.page))
    else:
        st.info("לחצי על תא בטבלה: יוצגו העמוד הסרוק, הדגלים והחלופות.")

st.markdown("##### עמודים שדולגו")
if skipped:
    for page, reason in skipped:
        st.write(f"עמוד {page}: {reason}")
else:
    st.caption("אין עמודים שדולגו.")

wb, _summary = build_workbook(pages, overrides)
buf = io.BytesIO()
wb.save(buf)
st.download_button("הורד אקסל", buf.getvalue(), file_name="commitments.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
