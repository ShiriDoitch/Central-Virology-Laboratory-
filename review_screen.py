"""מסך "בדיקה במבט אחד" (Streamlit): עובר תא-תא על כל מה שהמערכת לא בטוחה בו, עם הטופס המקורי לצד הערך,
כדי שבודקת לא תצטרך לחפש בטבלה. התור וההתקדמות ב-src/guided_review.py; הכתיבה עוברת באותן פונקציות של
src/service.py שמסך הרשומות משתמש בהן, ולכן יומן השינויים, הגרסה והסטטוס ממשיכים לעבוד בדיוק כמו קודם.

אין כאן קריאות מודל, אין כלל חילוץ ואין סף: הערכים, הצבעים, הדגלים והחלופות נקראים מהמסד כפי ש-src/rules.py
החליט. תא ריק נשאר ריק: אין מילוי אוטומטי של הצעה לתוך שדה הקלט, כי הצעה בשם בכתב יד שגויה ברוב המקרים
(CLAUDE.md סעיף 16). ההצעות מוצגות כלחצנים, והלחיצה היא אישור מפורש של המשתמשת."""
import time

import streamlit as st

import evidence_view
from src import guided_review, service
from src import ui_theme as ui
from src.confirm import FIELD_REGION, INPUT_HINTS, NOT_VERIFIED_NOTE, flag_chips_html, md_text
from src.export import COLUMNS
from src.privacy import log_server_error

TITLES = dict(COLUMNS)
TITLE = "בדיקה במבט אחד"
SUBTITLE = "כל תא שהמערכת לא בטוחה בו, אחד אחרי השני, עם הטופס המקורי"
PROGRESS_LABEL = "התקדמות בתור"
SESSION = "rv_session"                    # אובייקט ReviewSession ב-session_state; קיומו = מסך הבדיקה פעיל
FULL_PAGE_KEY = "rv_full_page"            # מתג "העמוד המלא": מפתח אחד לכל הבדיקה, כדי שהבחירה לא תתאפס בכל תא
INPUT_LABEL = "הערך הנכון"                # גם ה-aria-label שהמיקוד האוטומטי מחפש
CODE_KEYS = ("id", "center", "commitment")
NOT_FOUND = "לא נמצא"
EMPTY_HINT = "התא ריק: יש להקליד את מה שכתוב בטופס, או לדלג אם אין ערך בטופס."


# ---------- פתיחה וסגירה ----------

def active() -> bool:
    return isinstance(st.session_state.get(SESSION), guided_review.ReviewSession)


def session() -> guided_review.ReviewSession | None:
    return st.session_state.get(SESSION) if active() else None


def start(flt) -> None:
    """בונה את התור מהרשומות שבסינון הפעיל ופותח את המסך. נקרא כ-callback של כפתור, ולכן פותח חיבור משלו."""
    try:
        items = service.review_queue(service.open_connection(), flt or service.RecordFilter())
    except Exception as e:
        log_server_error("review queue", e)
        st.session_state["rv_msg"] = ("error", "בניית תור הבדיקה נכשלה (פרטים במסוף השרת).")
        return
    st.session_state[SESSION] = guided_review.ReviewSession(items=items, started_at=time.monotonic())
    st.session_state.pop("rv_msg", None)


def _close() -> None:
    sess = session()
    if sess:
        sess.closed = True


def _reopen() -> None:
    sess = session()
    if sess:
        sess.closed = False


def _exit() -> None:
    st.session_state.pop(SESSION, None)
    st.session_state.pop("rv_msg", None)


def _skip() -> None:
    sess = session()
    if sess:
        sess.skip()


def _back() -> None:
    sess = session()
    if sess:
        sess.back()


# ---------- כתיבה (אישור או תיקון של תא) ----------

def _input_key(item: guided_review.ReviewItem) -> str:
    return f"rv_in_{item.record_id}_{item.field}"


def _apply(item: guided_review.ReviewItem, text: str | None) -> None:
    """מה שהמשתמשת אישרה או תיקנה, דרך אותו נתיב של מסך הרשומות: ערך זהה להצעת המערכת נרשם כ"אישור",
    ערך שונה נרשם כ"תיקון" (src/repo.edit_field), ובשני המקרים התא נעשה "אושר על ידי המשתמשת" (כחול)
    והסטטוס של הרשומה מחושב מחדש לפי הכללים הקיימים. ערך לא תקין לשדה: הודעה, ושום דבר לא נכתב."""
    sess = session()
    if sess is None:
        return
    value = (text or "").strip()
    if not value:
        st.session_state["rv_msg"] = ("warning", EMPTY_HINT)
        return
    hint = f" ({INPUT_HINTS[item.field]})" if item.field in INPUT_HINTS else ""
    try:
        service.edit_record_field(service.open_connection(), item.record_id, item.field, value)
    except service.RecordLocked:
        st.session_state["rv_msg"] = ("error", "הרשומה מאושרת ולכן נעולה. לתיקון יש לבטל את אישור הרשומה במסך הרשומות.")
        return
    except ValueError:
        st.session_state["rv_msg"] = ("error", f"הערך לא תקין ל{TITLES[item.field]}, לא נשמר{hint}.")
        return
    except Exception as e:
        log_server_error("review apply", e)
        st.session_state["rv_msg"] = ("error", "השמירה נכשלה (פרטים במסוף השרת).")
        return
    sess.record_action(item)
    sess.advance()


def _submit(item: guided_review.ReviewItem) -> None:
    """Enter בשדה הקלט (או לחיצה על כפתור האישור של הטופס)."""
    _apply(item, st.session_state.get(_input_key(item)))


def _choose(item: guided_review.ReviewItem, value: str) -> None:
    """לחיצה על אחת ההצעות = אישור הערך הזה."""
    st.session_state[_input_key(item)] = value
    _apply(item, value)


# ---------- המסך ----------

def render(db, he_flag) -> None:
    """המסך כולו (נקרא במקום טבלת הרשומות כל עוד הבדיקה פעילה)."""
    sess = session()
    if sess is None:
        return
    item = None if (sess.closed or sess.done) else sess.current
    _render_banner(sess, item)
    msg = st.session_state.pop("rv_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    if not sess.items:
        _render_nothing_to_review()
        return
    if sess.closed or sess.done:
        _render_summary(sess)
        return
    _render_cell(db(), sess, he_flag)


def _render_nothing_to_review() -> None:
    st.markdown("<div class='empty-filter'><b>אין תאים לבדיקה</b>כל השדות של הרשומות שבסינון הפעיל ירוקים או אושרו. "
                "אפשר לאשר אותן באישור הקבוצתי, או לשנות את הסינון.</div>", unsafe_allow_html=True)
    st.button("חזרה לרשומות", key="rv_exit_empty", on_click=_exit, type="primary")


def _render_summary(sess: guided_review.ReviewSession) -> None:
    """סוף הבדיקה: רק מה שנמדד בפועל (טפסים, תאים, זמן, שניות לתא). בלי הערכות של "זמן שנחסך"."""
    s = sess.summary(time.monotonic())
    per_cell = f"{s['per_cell']:.1f}" if s["per_cell"] is not None else "—"
    left = sess.remaining()
    st.markdown("<div class='empty-filter'><b>" + ("הבדיקה הסתיימה" if sess.done else "הבדיקה נעצרה") + "</b>"
                + (f"נשארו {left} תאים בתור (תא שדולג חוזר בבדיקה הבאה)." if left else "כל תאי התור נבדקו.")
                + "</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='rv-metrics'>"
                f"<div><span>טפסים שנבדקו</span><b>{s['records']}</b></div>"
                f"<div><span>תאים שאושרו או תוקנו</span><b>{s['cells']}</b></div>"
                f"<div><span>תאים שדולגו</span><b>{s['skips']}</b></div>"
                f"<div><span>זמן הבדיקה</span><b>{guided_review.duration_he(s['seconds'])}</b></div>"
                f"<div><span>שניות לתא</span><b>{per_cell}</b></div></div>", unsafe_allow_html=True)
    st.caption("המספרים נמדדו בבדיקה הזאת בלבד: כמה תאים נגעת בהם וכמה זמן זה לקח.")
    back, again = st.columns([1, 1])
    back.button("חזרה לרשומות", key="rv_exit", on_click=_exit, type="primary", width="stretch")
    if not sess.done:
        again.button("המשך הבדיקה", key="rv_resume", on_click=_reopen, width="stretch")


def _render_banner(sess: guided_review.ReviewSession, item) -> None:
    """כרטיס הפתיחה של המסך: כותרת, שורת הסבר, שבבי ההתקדמות ופס ההתקדמות שמחובר לכרטיס.
    אותו כרטיס מוצג גם בסיכום ובמצב "אין מה לבדוק", אז בלי שבבים ובלי פס (item = None)."""
    with st.container(key="rv_banner"):
        chips = ui.stat_chips(progress_chips(sess, item)) if item is not None else ""
        st.markdown(ui.banner(TITLE, SUBTITLE, chips), unsafe_allow_html=True)
        if item is not None:
            total = len(sess.items)
            st.progress(min(1.0, sess.pos / total) if total else 0.0, text=PROGRESS_LABEL)


def progress_chips(sess: guided_review.ReviewSession, item) -> list[tuple]:
    """מה שמוצג בשבבים: אותם מספרים של guided_review.progress, בלי טקסט נוסף. "נשארו" מודגש, כי זה
    המספר שהבודקת עוקבת אחריו."""
    p = sess.progress()
    return [("טופס", p["record_i"], f"מתוך {p['records']}", False),
            ("תא", p["cell_i"], f"מתוך {p['cells']}", False),
            ("נשארו", p["remaining"], "תאים", True),
            ("עמוד", int(item.page_no), "בקובץ", False)]


def _render_cell(conn, sess: guided_review.ReviewSession, he_flag) -> None:
    item = sess.current
    record = service.record_detail(conn, item.record_id)
    if record is None:                        # הרשומה נמחקה בעיבוד חוזר בזמן הבדיקה: ממשיכים לתא הבא
        sess.advance()
        st.rerun()
    state = record["fields"].get(item.field) or {}
    with st.container(border=True, key="rv_card"):
        ev_col, act_col = st.columns([1.3, 1], gap="large")       # RTL: הטופס מימין, הפעולה משמאל
        with ev_col:
            with st.container(key="rv_evidence"):
                _render_evidence(conn, record, item)
        with act_col:
            with st.container(key="rv_actions"):
                _render_actions(sess, record, item, state, he_flag)
    _focus_input(item)


def _render_evidence(conn, record: dict, item) -> None:
    """הטופס המקורי: החיתוך של האזור שממנו נקרא השדה, או העמוד המלא עם מסגרת סביב האזור."""
    st.markdown("<div class='col-label'>הטופס המקורי</div>", unsafe_allow_html=True)
    try:
        image, crop, fractions = service.review_cell_image(conn, record, item.field)
    except Exception as e:
        log_server_error("review_cell_image", e)
        image, crop, fractions = None, None, None
    if image is None:
        st.info(service.IMAGE_MISSING_TEXT + ". אפשר לאשר או לתקן את הערך גם בלי התמונה.")
        return
    st.toggle("הצגת העמוד המלא", key=FULL_PAGE_KEY, help="העמוד כולו, עם מסגרת סביב האזור של השדה")
    zoom_key = f"rv_zoom_{item.record_id}_{item.field}"
    note = NOT_VERIFIED_NOTE if (not fractions and FIELD_REGION.get(item.field)) else None
    if st.session_state.get(FULL_PAGE_KEY) or not crop:
        evidence_view.render_page_region(image, fractions, record["page_no"], zoom_key=zoom_key + "_full", no_region_note=note)
    else:
        evidence_view.render_crop_and_page(crop, None, record["page_no"], zoom_key=zoom_key, no_crop_note=note)


def _render_actions(sess: guided_review.ReviewSession, record: dict, item, state: dict, he_flag) -> None:
    """מה המערכת קראה, למה זה לבדיקה, ההצעות, ושדה ההקלדה (Enter מאשר)."""
    key = item.field
    value = service.record_value(record, key)
    color = state.get("color") if state.get("color") in ui.STATES else "empty"
    st.markdown(f"<div class='rv-field'><span class='rv-name'>{TITLES[key]}</span>"
                f"{ui.badge(color, ui.STATE_LABEL.get(color, color))}</div>", unsafe_allow_html=True)
    st.markdown(ui.field_row("מה המערכת קראה", value, color, mono=key in CODE_KEYS, empty_text=NOT_FOUND),
                unsafe_allow_html=True)
    notes = [he_flag(f, key) for f in state.get("flags") or []]
    st.markdown("<div class='col-label'>למה זה לבדיקה</div>"
                + (flag_chips_html(notes) if notes else "<span class='rv-none'>אין דגל; התא ריק ולא נמצא ערך.</span>"),
                unsafe_allow_html=True)
    alts = [a for a in (state.get("alternatives") or []) if a and a != value]
    if alts:
        st.markdown("<div class='col-label'>קריאות אחרות (לחיצה מאשרת)</div>", unsafe_allow_html=True)
        with st.container(horizontal=True, gap="small", key="rv_chips"):
            for i, alt in enumerate(alts):
                st.button(md_text(alt), key=f"rv_alt_{i}", on_click=_choose, args=(item, alt))
    in_key = _input_key(item)
    st.session_state.setdefault(in_key, value or "")
    with st.form(key=f"rv_form_{item.record_id}_{key}", border=False, clear_on_submit=False):
        st.text_input(INPUT_LABEL, key=in_key, placeholder=INPUT_HINTS.get(key, "כפי שכתוב בטופס"))
        st.form_submit_button("אישור · Enter", type="primary", width="stretch", on_click=_submit, args=(item,))
    skip_col, back_col, end_col = st.columns(3)
    skip_col.button("דילוג", key="rv_skip", on_click=_skip, width="stretch", help="התא חוזר בסוף הבדיקה")
    back_col.button("חזרה", key="rv_back", on_click=_back, width="stretch", disabled=sess.pos == 0, help="התא הקודם")
    end_col.button("סיום", key="rv_end", on_click=_close, width="stretch")


def focus_script(marker: str, label: str = INPUT_LABEL) -> str:
    """סקריפט המיקוד האוטומטי. סטטי לגמרי חוץ מהסמן (מספרים בלבד), שנחוץ כדי שהדפדפן יריץ אותו מחדש בכל תא."""
    return ("<script>/* " + marker + " */ setTimeout(function () { try { var el = "
            "document.querySelector('input[aria-label=\"" + label + "\"]'); "
            "if (el && document.activeElement !== el) { el.focus(); el.select(); } } catch (e) {} }, 120);</script>")


def _focus_input(item) -> None:
    """ניסיון למקד את שדה הקלט, כדי שהבדיקה תהיה Enter-Enter בלי עכבר. אם הדפדפן או הפריסה לא מאפשרים,
    פשוט לא קורה כלום והמיקוד נעשה ב-Tab (הבדיקה לא תלויה בזה)."""
    try:
        st.html(focus_script(f"{item.record_id}:{item.field}"), unsafe_allow_javascript=True)
    except Exception:                      # גרסת Streamlit בלי התמיכה: ממשיכים בלי מיקוד אוטומטי
        pass
