"""ממשק Streamlit: העלאת טפסי התחייבות, הצגת השדות בצבעים, פירוט ראיות לכל שדה, וייצוא לאקסל.
הפעלה: streamlit run app.py   (בלי שינוי כללים: כל ההחלטות ב-src/rules.py ו-src/senders.py)."""
import io
import html
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from src.confirm import FIELD_REGION, field_crop, flag_chips_html, md_code, md_text, name_suggestions, normalize_override, override_key, set_override, zoom_html
from src.export import COLUMNS, CONFIRMED, FIELD_KEYS, GREEN, ORANGE, YELLOW, _readings, build_rows, build_workbook, pass2_issues, skip_reason
import evidence_view
import records_screen
from src import service
from src import ui_theme as ui
from src.intake import pdf_to_images, rotate_jpeg
from src.schema import PageExtraction
from src.privacy import GENERIC_ERROR_HE, log_server_error
from src.review import filter_counts, next_attention_cell, row_masks, visible_rows
from src.upload import UploadRejected, cleanup_stale_uploads, process_upload, to_pdf_bytes  # noqa: F401  (to_pdf_bytes: לשימוש חיצוני / בדיקות)

SAMPLE_DIR = Path("outputs/clean_part1_v4b")      # הריצה השמורה (בלי API)
SAMPLE_PDF = Path("data/clean_part1.pdf")         # עמודים נקיים, בלי סימון צהוב
TRUTH_PATH = Path("data/truth_part1.xlsx")
MAX_UPLOAD_MB = 25
GREEN_HEX, ORANGE_HEX = "#" + GREEN.fgColor.rgb[-6:], "#" + ORANGE.fgColor.rgb[-6:]
CONFIRMED_HEX = "#" + CONFIRMED.fgColor.rgb[-6:]      # שם שאושר על ידי המשתמש
YELLOW_HEX = "#" + YELLOW.fgColor.rgb[-6:]            # ערך בכתב יד, שתי קריאות מסכימות: מבט לאישור
# הצבעים עצמם ב-src/ui_theme.py (מקום אחד לעיצוב). כאן רק המיפוי מצבע המילוי של האקסל (src/export.py) לשם המצב.
HEX_STATE = {GREEN_HEX: "green", ORANGE_HEX: "orange", YELLOW_HEX: "yellow", CONFIRMED_HEX: "confirmed"}
UI_DOT = {**ui.STATE_DOT, "ink": ui.INK}              # צבע המספר בפס המדדים
TABLE_H = 520                                        # גובה מרבי של הטבלה ברוחב מלא (גלילה פנימית); כרטיס הבדיקה נפתח מתחתיה
# סינון מהיר: מפתח -> תווית. "תקין" = שורה בלי אף שדה לבדיקה (ירוק או מאושר בלבד); הלוגיקה ב-src/review.py
FILTERS = {"all": "הכול", "green": "תקין", "orange": "לבדיקה", "yellow": "זהב", "empty": "ריק"}     # הצבע בא מרקע הכפתור, בלי אייקונים
FOCUS_LABEL = "מצב פוקוס לבורנטית (הצג חריגים בלבד)"
ROW_H = 40                                           # גובה שורה בטבלה: מרווח נוח לקריאה
# רוחב מינימלי לעמודה בפיקסלים. הרשת מחלקת את הרוחב הפנוי באופן יחסי, ולכן הסכום (כ-720) קטן מרוחב הטבלה גם במסך מחשב נייד:
# הרשת מצוירת משמאל לימין, וגלילה אופקית הייתה מסתירה דווקא את העמודות הימניות (עמוד, שם פרטי).
COL_WIDTH = {"first_name": 96, "last_name": 104, "id": 120, "center": 150, "date": 108, "sender": 170, "commitment": 120}
PAGE_COL_W = 64
PAGE_COL = "עמוד"                                   # עמודת עמוד המקור בטבלה (לא שדה נתונים)
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
    "id_length": "אורך ת\"ז לא תקין (צריך 5 עד 9 ספרות), הערך לא שונה",
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
    "center_barcode_extra": "הברקוד מכיל מרכזיים נוספים שהמודל לא קרא, לבדיקה",
    "not_recognized_as_form": "המודל לא זיהה טופס התחייבות, אבל יש סימני טופס: כל השדות לבדיקה",
}


def db():
    """חיבור חדש למסד הנתונים (SQLite זול לפתיחה, ואובייקט שלא בשימוש נסגר מיד). ה-SQL כולו ב-src/repo.py."""
    return service.open_connection()


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
ui.inject()


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
    for (p, _er), rec, col in zip(export_rows, records, colors):
        rec[PAGE_COL], col[PAGE_COL] = p["page"], ""         # עמוד המקור של השורה: עמודה ללא צבע סטטוס
    cols = [TITLES[k] for k in reversed(FIELD_KEYS)] + [PAGE_COL]      # הגריד מצויר LTR: העמודה האחרונה ברשימה היא הימנית ביותר
    return pd.DataFrame(records, columns=cols), pd.DataFrame(colors, columns=cols), export_rows


def style(df: pd.DataFrame, colors: pd.DataFrame):
    """צבע לפי הסטטוס, בלי נקודות: ירוק = טקסט ירוק; כתום / זהב / כחול = טקסט בגוון כהה על רקע בהיר (תג).
    תא ריק שסומן מציג "—" על רקע הסטטוס; תא ריק בלי דגל נשאר ריק."""
    text = df.astype(str)
    shown = text.where((colors == "") | (text != ""), "—")

    def css(c: str) -> str:
        return ui.table_cell_css(HEX_STATE.get(c))     # עמודת העמוד ותא ריק בלי דגל: טקסט נייטרלי על רקע לבן

    return shown.style.apply(lambda _: colors.map(css), axis=None)


def grid_config(columns) -> dict:
    """רוחב ויישור לכל עמודה: הכול מיושר לימין (RTL), עמודת העמוד צרה וממורכזת."""
    by_title = {t: k for k, t in COLUMNS}
    cfg = {}
    for col in columns:
        if col == PAGE_COL:
            cfg[col] = st.column_config.TextColumn(PAGE_COL, width=PAGE_COL_W, alignment="center")
        else:
            cfg[col] = st.column_config.TextColumn(col, width=COL_WIDTH.get(by_title.get(col)), alignment="right")
    return cfg


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


def _page_result(page: int) -> dict | None:
    return next((p for p in st.session_state.get("pages") or [] if p["page"] == page), None)


def _apply(page: int, okey: str, value: str | None) -> bool:
    """אישור / ביטול אישור של תא: קודם מאומת ונשמר במסד הנתונים (אם יש העלאה שמורה), ורק אז מתעדכן מצב הסשן.
    שורה מאושרת נעולה: מציג הודעה ולא משנה כלום. ערך לא תקין לשדה: ValueError (האישור הקודם נשאר)."""
    overrides = st.session_state.setdefault("name_overrides", {})
    prev = overrides.get((page, okey))
    set_override(overrides, page, okey, value)
    upload_id = st.session_state.get("upload_id")
    if upload_id and not st.session_state.get("is_sample"):
        try:
            service.save_override(db(), upload_id, page, okey, overrides.get((page, okey)), _page_result(page))
        except service.RecordLocked:
            if prev is None:
                overrides.pop((page, okey), None)
            else:
                overrides[(page, okey)] = prev
            st.session_state[f"locked_{page}"] = True
            return False
        except Exception as e:
            log_server_error("save_override", e)
            st.session_state["db_error"] = True
    st.session_state.pop(f"locked_{page}", None)
    return True


def _choose(page: int, okey: str, value: str) -> None:
    """לחיצה על הצעה: הערך נשמר כערך הסופי (אישור משתמש) ומוצג גם בשדה ההקלדה."""
    if value and value == saved_confirmed_value(page, okey):
        return
    if _apply(page, okey, value):
        st.session_state[f"txt_{page}_{okey}"] = value
        st.session_state[f"done_{page}_{okey}"] = st.session_state["name_overrides"].get((page, okey))


def saved_confirmed_value(page: int, okey: str) -> str | None:
    """הערך המאושר של התא לפי הרשומה השמורה במסד (לא רק לפי הסשן). בדוגמה או בלי מסד: לפי האישורים בסשן."""
    upload_id = st.session_state.get("upload_id")
    if upload_id and not st.session_state.get("is_sample"):
        try:
            return service.confirmed_value(db(), upload_id, page, okey)
        except Exception as e:
            log_server_error("confirmed_value", e)
    return st.session_state.get("name_overrides", {}).get((page, okey))


def _normalized(key: str, text: str | None) -> str | None:
    return normalize_override(key, text)


def already_confirmed(page: int, okey: str, text: str | None) -> bool:
    """הטקסט שהוקלד (אחרי נרמול) זהה לערך המאושר השמור, או שזה עתה אושר בריצה הזו (דגל done: הכפתור ננעל מיד, גם אם הקריאה
    מהמסד מתעכבת). דגל done נחשב רק כל עוד יש ערך מאושר שמור: אישור שבוטל (גם ממסך הרשומות) משחרר את הכפתור."""
    typed = _normalized(okey.split("#")[0], text)
    if not typed:
        return False
    saved = saved_confirmed_value(page, okey)
    return typed == saved or (saved is not None and typed == st.session_state.get(f"done_{page}_{okey}"))


def _confirm_typed(page: int, okey: str) -> None:
    text = st.session_state.get(f"txt_{page}_{okey}", "")
    if already_confirmed(page, okey, text):
        return                                        # לחיצה כפולה: הערך כבר אושר, לא עושים כלום (ובלי הודעת שגיאה)
    try:
        if _apply(page, okey, text):
            st.session_state[f"txt_{page}_{okey}"] = st.session_state["name_overrides"].get((page, okey), "")
            st.session_state[f"done_{page}_{okey}"] = st.session_state["name_overrides"].get((page, okey))   # נעילה עד סוף הריצה
        st.session_state.pop(f"err_{page}_{okey}", None)
    except ValueError:
        st.session_state[f"err_{page}_{okey}"] = True      # ערך לא תקין לשדה: האישור הקודם לא משתנה


def _clear(page: int, okey: str) -> None:
    st.session_state.pop(f"done_{page}_{okey}", None)
    if _apply(page, okey, None):
        st.session_state[f"txt_{page}_{okey}"] = ""
    st.session_state.pop(f"err_{page}_{okey}", None)


def _approve_row(record_id: int) -> None:
    service.approve_row(db(), record_id)


def _unapprove_row(record_id: int) -> None:
    service.unapprove_row(db(), record_id)


STATUS_HE = {"pending": "ממתינה לבדיקה", "ready": "מוכנה לאישור", "approved": "אושרה"}


INPUT_HINTS = {"id": 'ספרות בלבד', "commitment": "ספרות בלבד", "center": "ספרות; כמה ערכים מופרדים ב-;", "date": "dd.mm.yyyy"}




def cell_status(cell) -> tuple[str, str]:
    """מחלקת ה-CSS ותווית הסטטוס של תא (אותו סדר עדיפויות כמו בטבלה ובאקסל)."""
    if cell.confirmed:
        return "confirmed", "אושר על ידי המשתמש"
    if cell.yellow:
        return "yellow", "שתי קריאות מסכימות"
    if cell.orange:
        return "orange", "לבדיקה"
    if cell.value:
        return "green", "בלי דגל"
    return "empty", "לא נמצא"


# ---------- בחירה (הסינון עצמו ב-src/review.py) ----------

def _select(cell) -> None:
    st.session_state["selected_cell"] = tuple(cell) if cell else None
    st.session_state["_scroll_to_detail"] = bool(cell)


# ---------- כרטיס הבדיקה (מתחת לטבלה) ----------

def render_evidence(page_res: dict, er, key: str, image: bytes | None) -> None:
    """צד הראיות: חיתוך האזור מהעמוד הנקי (עם הגדלה) או העמוד המלא, הערך, הדגלים, החלופות והקריאות הגולמיות."""
    cell = er.cells[key]
    crop = crop_for(page_res, key)
    state, _label = cell_status(cell)
    st.markdown("<div class='col-label'>ראיות מהטופס</div>", unsafe_allow_html=True)
    code = md_code if key in CODE_KEYS else md_text       # קודים במונוספייס; שמות ופרוזה לא. כל טקסט מהטופס עובר escape
    # הערך כטקסט נקי בתוך תא, באותה צורה שבה מוצג שדה נעול בכרטיס הרשומה (src/ui_theme.py)
    st.markdown(ui.field_row(TITLES[key], cell.value, state, mono=key in CODE_KEYS), unsafe_allow_html=True)
    if not cell.value and cell.raw:
        st.markdown(f"**נקרא (raw):** {code(cell.raw)}")
    if cell.flags:
        st.markdown("**לבדיקה:** " + flag_chips_html(he_flag(f, key) for f in cell.flags), unsafe_allow_html=True)
    else:
        st.markdown("**לבדיקה:** אין")
    if cell.alternatives and key not in NAME_KEYS:
        label = "מועמדים שנמצאו (התא ריק)" if not cell.value else "חלופות"
        st.markdown(f"**{label}:** " + " | ".join(md_text(a) for a in cell.alternatives))
    if cell.hints:
        st.caption("רמזים: " + ", ".join(cell.hints))
    evidence_view.render_crop_and_page(crop, image, er.page, zoom_key=f"zoom_{er.page}_{FIELD_REGION.get(key)}")      # רכיב משותף עם כרטיס הרשומה
    r1 = PageExtraction.model_validate(page_res["pass1"])
    p1, p2 = _readings(key, r1, page_res.get("pass2"))
    with st.expander("קריאות גולמיות של המודל"):
        st.text(f"מעבר ראשון: {p1 or '—'}\nמעבר שני: {p2 or '—'}")


def render_confirmation(page_res: dict, er, key: str, locked: bool = False) -> None:
    """צד הפעולות: מצב הערך, הצעות כלחצנים (גם כשהתא ריק), הקלדה חופשית וכפתורי האישור.
    ערך שהוקלד או נבחר נשמר כערך סופי ומיוצא כ"אושר על ידי המשתמש" (כחול). בלי אישור, שם בכתב יד נשאר כתום."""
    cell, page = er.cells[key], er.page
    okey = override_key(key, er.index)
    overrides = st.session_state.setdefault("name_overrides", {})
    st.markdown("<div class='col-label'>אישור הערך</div>", unsafe_allow_html=True)
    if locked or st.session_state.get(f"locked_{page}"):
        st.warning("השורה אושרה ולכן נעולה לשינוי. כדי לתקן, בטלי קודם את אישור השורה (למעלה).")
        locked = True
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
        with st.container(horizontal=True, gap="small", key="detail_suggest"):
            for i, sug in enumerate(suggestions):
                st.button(md_text(sug), key=f"sg_{page}_{okey}_{i}", on_click=_choose, args=(page, okey, sug),
                          disabled=locked or sug == saved_confirmed_value(page, okey))
    elif key in NAME_KEYS:
        st.warning(NOT_READ_TEXT)
    else:
        st.caption("אין הצעות לשדה הזה. אפשר להקליד ערך.")
    txt_key = f"txt_{page}_{okey}"
    st.session_state.setdefault(txt_key, overrides.get((page, okey), ""))
    st.text_input("או הקלדה ידנית" + (f" ({INPUT_HINTS[key]})" if key in INPUT_HINTS else ""), key=txt_key, disabled=locked)
    if st.session_state.get(f"err_{page}_{okey}"):
        st.error("הערך לא תקין לשדה הזה, לא נשמר" + (f" ({INPUT_HINTS[key]})" if key in INPUT_HINTS else ""))
    ok_slot, clear_slot = st.columns([3, 2]) if cell.confirmed else (st.container(), None)
    already = already_confirmed(page, okey, st.session_state.get(txt_key))
    ok_slot.button("הערך אושר" if already else "אשרי את הערך שהוקלד", key=f"ok_{page}_{okey}", on_click=_confirm_typed, args=(page, okey),
                   type="secondary" if already else "primary", width="stretch", disabled=locked or already,
                   help="הערך שהוקלד זהה לערך השמור. שני את הטקסט כדי לאשר ערך אחר." if already else None)
    if clear_slot is not None:                           # פעולה משנית: כפתור שקט לצד הכפתור הראשי
        clear_slot.button("בטלי אישור", key=f"clr_{page}_{okey}", on_click=_clear, args=(page, okey), width="stretch", disabled=locked)


def render_detail(page_res: dict, er, key: str, image: bytes | None, row_i: int, n_rows: int, nxt, hidden: bool) -> None:
    """כרטיס הבדיקה ברוחב מלא: כותרת עם ניווט, ואז ראיות (מימין) ופעולות האישור (משמאל) זו לצד זו, בלי חפיפה."""
    cls, label = cell_status(er.cells[key])
    head, nav_next, nav_close = st.columns([6, 1.5, 0.9], vertical_alignment="center")
    head.markdown(
        f"<div class='panel-head'><div><div class='ph-eyebrow'>עמוד {int(er.page)} · שורה {row_i + 1} מתוך {n_rows}"
        f"{' · מוסתרת בסינון הנוכחי' if hidden else ''}</div><div class='ph-title'>{html.escape(TITLES[key])}</div></div>"
        f"{ui.badge(cls, label)}</div>",
        unsafe_allow_html=True,
    )
    nav_next.button("לבדיקה הבאה ←", key="next_cell", on_click=_select, args=(nxt,), disabled=nxt is None, width="stretch",
                    help="התא הבא שדורש בדיקה (כתום, צהוב או ריק)")
    nav_close.button("סגירה", key="close_detail", on_click=_select, args=(None,), width="stretch")
    info = None
    if st.session_state.get("upload_id") and not st.session_state.get("is_sample"):
        try:
            info = service.row_info(db(), st.session_state["upload_id"], er.page, er.index)
        except Exception as e:
            log_server_error("row_info", e)
    if info:
        st_col, btn_col = st.columns([4, 1.6], vertical_alignment="center")
        st_col.markdown(f"<div class='rec-head'><span class='rec-meta'>סטטוס השורה</span>"
                        f"{ui.badge(ui.STATUS_STATE[info['status']], STATUS_HE[info['status']])}</div>", unsafe_allow_html=True)
        if info["status"] == "approved":
            btn_col.button("בטלי אישור שורה", key=f"unappr_{info['id']}", on_click=_unapprove_row, args=(info["id"],), width="stretch")
        else:
            btn_col.button("אשרי שורה", key=f"appr_{info['id']}", on_click=_approve_row, args=(info["id"],), type="primary", width="stretch",
                           help="מסמן את כל השורה כבדוקה. שורה מאושרת נעולה ולא נדרסת בעיבוד חוזר.")
    st.markdown("<div class='panel-rule'></div>", unsafe_allow_html=True)
    ev_col, act_col = st.columns([1.45, 1], gap="large")       # RTL: הראיות מימין, האישור משמאל
    with ev_col:
        with st.container(key="detail_evidence"):
            render_evidence(page_res, er, key, image)
    with act_col:
        with st.container(key="detail_actions"):
            render_confirmation(page_res, er, key, locked=bool(info and info["status"] == "approved"))


def kpi_cards(items) -> str:
    """פס מדדים אחד, קומפקטי: (תווית, ערך, הערה, צבע, הסבר). ההערה וההסבר בטולטיפ. רק מספרים וטקסט קבוע."""
    out = []
    for label, value, note, tone, tip in items:
        title = html.escape(" · ".join(x for x in (tip or label, note) if x), quote=True)
        out.append(f"<div class='kpi' style='--tone:{tone}' title='{title}'><div class='k-label'>{html.escape(label)}</div>"
                   f"<div class='k-value'>{value}</div></div>")
    return "<div class='kpis'>" + "".join(out) + "</div>"


def share(n: int, total: int) -> str:
    return f"{round(100 * n / total)}% מהשדות" if total else "—"


# ---------- דף ----------

st.markdown(
    "<div class='lab-header'><div class='title'>חילוץ טפסי התחייבות</div>"
    "<div class='org'>המעבדה המרכזית לנגיפים</div>"
    "<div class='hint'>שורה אחת לכל התחייבות · כתום = לבדיקה אנושית</div></div>",
    unsafe_allow_html=True,
)

_goto = st.session_state.pop("_goto_records", None)
if _goto:                                              # קובץ שכבר עובד: עוברים למסך הרשומות, מסוננות לקובץ הזה
    st.session_state["view"], st.session_state["rec_upload"] = "records", _goto
VIEWS = {"process": "עיבוד ובדיקה", "records": "רשומות שמורות"}
st.segmented_control("מסך", list(VIEWS), default="process", key="view", format_func=VIEWS.get, label_visibility="collapsed")
_notice = st.session_state.pop("_notice", None)
if _notice:
    st.info(_notice)

if st.session_state.get("view") == "records":   # מסך הרשומות לא מכיל העלאה ולא פעולות עיבוד: הן שייכות למסך העיבוד בלבד
    records_screen.render(db, he_flag)
    st.stop()

with st.container(border=True, key="action_card"):         # כרטיס פעולה אחד: העלאה, עיבוד, דוגמה והורדת אקסל (נדבק לראש המסך בגלילה)
    up_col, run_col, sample_col, dl_col = st.columns([4.4, 1, 1.4, 1.2], vertical_alignment="center", gap="small")
    with up_col:
        upload = st.file_uploader("העלאת טופס (PDF או תמונה)", type=["pdf", "png", "jpg", "jpeg"], label_visibility="collapsed")
    run_clicked = run_col.button("עבד", type="primary", disabled=upload is None, width="stretch")
    sample_clicked = sample_col.button("טען דוגמה מחלק 1", width="stretch")
    download_slot = dl_col.empty()
    download_slot.button("הורד אקסל", disabled=True, width="stretch", key="dl_disabled", help="זמין אחרי שיש תוצאות")

progress_slot = st.empty()
if sample_clicked:
    try:
        st.session_state["pages"], st.session_state["images"] = load_sample()
        st.session_state["is_sample"] = True
        st.session_state["upload_id"] = None                 # הדוגמה היא לדמו בלבד ואינה נשמרת במסד הנתונים
        st.session_state["field_crops"], st.session_state["name_overrides"] = {}, {}
    except Exception as e:
        log_server_error("load_sample", e)
        st.error("טעינת הדוגמה נכשלה. פרטים במסוף השרת.")
if run_clicked and upload is not None:
    if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_MB}MB)")
    elif not os.getenv("GEMINI_API_KEY") and not Path(".env").exists():
        st.error("חסר GEMINI_API_KEY בקובץ .env")
    else:
        data = upload.getvalue()
        try:
            existing = service.find_completed_upload(db(), data)
        except Exception as e:
            log_server_error("find_completed_upload", e)
            existing = None
        if existing:       # אותו קובץ (sha256) כבר עובד: פותחים את הרשומות השמורות במקום לעבד שוב (בלי קריאות API)
            st.session_state.update(upload_id=existing["id"], pages=None, images={}, field_crops={}, name_overrides={}, is_sample=False)
            st.session_state["_notice"] = f"הקובץ \"{existing['filename']}\" כבר עובד בעבר ({existing['record_count']} רשומות). הרשומות השמורות נטענו; לא בוצע עיבוד מחדש."
            st.session_state["_goto_records"] = existing["id"]
            st.rerun()
        else:
            bar = progress_slot.progress(0.0, text="מתחיל")
            store = service.Persister(db(), upload.name, data)
            try:
                st.session_state["pages"], st.session_state["images"], st.session_state["field_crops"] = process_upload(
                    upload.name, data, bar, store=store)
                st.session_state["is_sample"] = False
                st.session_state["upload_id"] = store.upload_id
                st.session_state["name_overrides"] = service.load_overrides(db(), store.upload_id) if store.upload_id else {}
                if store.incomplete_pages:
                    st.warning("העיבוד של עמודים " + ", ".join(map(str, store.incomplete_pages)) + " חרג מהזמן המוקצב לעמוד ולא הושלם. "
                               "שאר העמודים עובדו. כדי להמשיך, העלי שוב את אותו קובץ.")
                if store.errors:
                    st.warning(f"השמירה למסד הנתונים נכשלה ב-{store.errors} עמודים (פרטים במסוף השרת). התוצאות מוצגות אך לא נשמרו במלואן.")
            except UploadRejected as e:                      # הודעה שכתבנו בעצמנו (למשל יותר מדי עמודים), בלי טקסט מהקובץ
                st.error(str(e))
            except Exception as e:
                log_server_error("process_upload", e)         # הפרטים האמיתיים רק במסוף השרת
                st.error(GENERIC_ERROR_HE)

pages = st.session_state.get("pages")
images = st.session_state.get("images", {})
if not pages:
    st.markdown("<div class='empty-state'><b>אין עדיין תוצאות</b>"
                "<p>העלי קובץ ולחצי \"עבד\", או לחצי \"טען דוגמה מחלק 1\".</p></div>", unsafe_allow_html=True)
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
st.markdown(kpi_cards([                                     # סדר מימין לשמאל: כמות, ואז מהבטוח אל מה שדורש עבודה
    ("טפסים", str(len(df)), f"{fields} שדות · {len(skipped)} עמודים דולגו", UI_DOT["ink"], "התחייבויות (שורות בטבלה)"),
    ("שדות ירוקים", str(n_green), share(n_green, fields), UI_DOT["green"], "נקרא בלי דגל"),
    ("שדות צהובים", str(n_yellow), share(n_yellow, fields), UI_DOT["yellow"], YELLOW_TEXT),
    ("שדות כתומים", str(n_orange), share(n_orange, fields), UI_DOT["orange"], "כולל שדה ריק שסומן לבדיקה"),
    ("שדות ריקים", str(n_empty), "לא נמצא, בלי דגל", UI_DOT["empty"], "לא נמצא, בלי דגל"),
    ("אושרו ידנית", str(n_confirmed), "מיוצא באקסל בכחול", UI_DOT["confirmed"], "ערך שהוקלד או נבחר ידנית; מיוצא באקסל בכחול"),
    ("כתומים שנכונים", f"{orange_ok}<small>/ {orange_total}</small>" if orange_total else "—",
     "מול טבלת האמת" if orange_total else "אין טבלת אמת לקובץ",
     UI_DOT["orange"], "נמדד מול טבלת האמת, רק בדוגמה מחלק 1 ורק בתאים כתומים שיש בהם ערך" if orange_total else "אין טבלת אמת לקובץ שהועלה"),
]), unsafe_allow_html=True)
if st.session_state.pop("db_error", False):
    st.warning("שמירת השינוי האחרון למסד הנתונים נכשלה (פרטים במסוף השרת). השינוי מוצג כאן אך לא נשמר.")
if st.session_state.get("upload_id") and not st.session_state.get("is_sample"):
    try:
        sc = service.status_counts(db(), st.session_state["upload_id"])
        st.caption(f"שמור במסד הנתונים · ממתינות לבדיקה: {sc['pending']} · מוכנות לאישור: {sc['ready']} · אושרו: {sc['approved']}")
    except Exception as e:
        log_server_error("status_counts", e)
issues = pass2_issues(pages)
if issues["fallback"]:
    st.warning("מעבר 2 נקרא במודל הגיבוי החלש (המודל החזק לא זמין או נכשל) בעמודים: "
               + ", ".join(map(str, issues["fallback"])) + ". הקריאות בעמודים האלה פחות אמינות, מומלץ לבדוק ידנית.")
if issues["claude"]:
    st.warning("מעבר 2 נקרא ב-Claude (גיבוי אחרון: כל מפתחות Gemini נכשלו) בעמודים: "
               + ", ".join(map(str, issues["claude"])) + ". מומלץ לבדוק ידנית.")
if issues["claude_pass1"]:
    st.warning("הקריאה הראשונה נעשתה ב-Claude (גיבוי אחרון, Gemini לא זמין) בעמודים: "
               + ", ".join(map(str, issues["claude_pass1"])) + ".")
if issues["quota"]:
    st.warning("מעבר 2 דולג בגלל מכסה יומית שנגמרה בעמודים: " + ", ".join(map(str, issues["quota"]))
               + ". יש רק קריאה אחת של העמוד בשדות האלה.")
if issues["failed"]:
    st.warning("מעבר 2 נכשל בעמודים: " + ", ".join(map(str, issues["failed"])) + ".")
wb, _summary = build_workbook(pages, overrides)
buf = io.BytesIO()
wb.save(buf)
download_slot.download_button("הורד אקסל", buf.getvalue(), file_name="commitments.xlsx", key="dl_xlsx", width="stretch",
                              mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

# ---------- סרגל אחד: מסננים מהירים, מונה, מצב פוקוס ----------
masks = row_masks(colors)
with st.container(key="toolbar"):
    f_col, count_col, focus_col = st.columns([3.1, 1.2, 1.7], vertical_alignment="center", gap="medium")
    with focus_col:                                          # קודם הפוקוס: המספרים על כפתורי הסינון תלויים בו
        with st.container(key="focus_wrap"):
            focus = st.toggle(FOCUS_LABEL, key="focus_mode")
    counts = filter_counts(colors, focus)
    with f_col:
        status_filter = st.segmented_control("סינון מהיר לפי סטטוס", list(FILTERS), default="all", key="status_filter",
                                             label_visibility="collapsed",
                                             format_func=lambda k: f"{FILTERS[k]}\u2002**{counts[k]}**") or "all"
    count_slot = count_col.empty()

show = visible_rows(colors, status_filter, focus)            # במצב פוקוס: רק שורות עם שדה כתום / צהוב / ריק, אף פעם לא שורה תקינה
view, view_colors = df[show], colors[show]
count_slot.markdown(f"<div class='counter'><b>{len(view)}</b> מתוך {len(df)} שורות<span>{int(masks['attention'].sum())} דורשות בדיקה</span></div>",
                    unsafe_allow_html=True)

# ---------- הטבלה ברוחב מלא ----------
# selected_cell נשמר תמיד כ(אינדקס שורה בטבלה המלאה, שם עמודה), כך שהבחירה נשמרת גם כשהסינון משתנה.
grid_key = f"grid_{status_filter}_{int(bool(focus))}"      # מפתח חדש לכל סינון: הבחירה של הרשת מתאפסת כשהשורות משתנות
selected = None
if view.empty:
    st.markdown("<div class='empty-filter'><b>אין שורות להצגה</b>"
                + ("אין חריגים בסינון הזה: כל השורות תקינות או מאושרות." if focus else "אין שורות שמתאימות לסינון.") + "</div>",
                unsafe_allow_html=True)
    selected = st.session_state.get("selected_cell")
else:
    try:
        event = st.dataframe(style(view, view_colors), width="stretch", hide_index=True, on_select="rerun", column_config=grid_config(view.columns),
                             selection_mode="single-cell", key=grid_key, row_height=ROW_H, height=min(TABLE_H, 40 + ROW_H * len(view)))
        cells = event.selection.cells
        sig = (grid_key, tuple(tuple(c) for c in cells)) if cells else None
        if cells and sig != st.session_state.get("_grid_sig"):      # לחיצה חדשה בטבלה (לא בחירה ישנה שנשארה ברשת)
            st.session_state["_grid_sig"] = sig
            row, col = cells[0]
            col = col if isinstance(col, str) else view.columns[int(col)]
            if col != PAGE_COL:                         # לחיצה על עמודת העמוד: נשארת הבחירה הקודמת
                _select((int(view.index[int(row)]), col))
        elif not cells:
            st.session_state["_grid_sig"] = None
        selected = st.session_state.get("selected_cell")
    except Exception:                                   # גרסת Streamlit בלי בחירת תא: בחירה ידנית
        r_i = st.selectbox("שורה", list(view.index), format_func=lambda i: f"שורה {i + 1} · עמוד {export_rows[i][1].page}")
        c_i = st.selectbox("שדה", [c for c in df.columns if c != PAGE_COL])
        selected = (int(r_i), c_i)
if selected and (selected[0] >= len(df) or selected[1] not in TITLES.values()):
    selected = None

# ---------- כרטיס הבדיקה: מתחת לטבלה, ברוחב מלא ----------
if selected:
    row_i, col_name = selected
    key = next(k for k, t in COLUMNS if t == col_name)
    page_res, er = export_rows[row_i]
    order = list(view.index) if not view.empty else list(df.index)
    nxt = next_attention_cell(colors, order, (row_i, col_name))
    with st.container(key="detail_panel"):
        render_detail(page_res, er, key, images.get(er.page), row_i, len(df), nxt, hidden=row_i not in view.index)
    if st.session_state.pop("_scroll_to_detail", False):     # בחירה חדשה: גלילה עדינה אל כרטיס הבדיקה
        st.html("<script>setTimeout(function(){var el=document.querySelector('.st-key-detail_panel');"
                "if(el){el.scrollIntoView({behavior:'smooth',block:'start'});}},120);</script>", unsafe_allow_javascript=True)
else:
    first = next_attention_cell(colors, list(view.index), None) if not view.empty else None
    tip, go = st.columns([5, 1.2], vertical_alignment="center")
    tip.markdown("<div class='placeholder'><b>בחרי תא בטבלה</b>"
                 "<span>כרטיס הבדיקה ייפתח כאן: האזור הסרוק, הדגלים, ההצעות וכפתורי האישור.</span></div>", unsafe_allow_html=True)
    go.button("התחילי מהחריג הראשון", key="first_cell", on_click=_select, args=(first,), disabled=first is None, type="primary", width="stretch")

with st.container(key="secondary"):                         # אזורים משניים: סגורים כברירת מחדל
    with st.expander("פירוט לפי שדה", expanded=False):
        st.dataframe(per_field_counts(export_rows), hide_index=True, width="stretch")
    with st.expander(f"עמודים שדולגו ({len(skipped)})", expanded=bool(skipped)):   # יש עמוד שדולג: פתוח, לא מוסתר
        if skipped:
            for page, reason in skipped:
                st.write(f"עמוד {page}: {reason}")
        else:
            st.caption("אין עמודים שדולגו.")
