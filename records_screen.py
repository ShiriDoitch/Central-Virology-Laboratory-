"""מסך הרשומות (Streamlit): כל מה ששמור במסד הנתונים. חיפוש, סינון (סטטוס, גורם שולח, טווח תאריכים, העלאה), מיון, עימוד,
תיקון ואישור של רשומה. קורא רק לפונקציות של src/service.py; בלי SQL. הייצוא מהמסך נוסף בשלב 5."""
from datetime import date

import pandas as pd
import streamlit as st

from src import service
from src.export import COLUMNS, FIELD_KEYS
from src.privacy import log_server_error

TITLES = dict(COLUMNS)
STATUS_HE = {"pending": "ממתינה", "ready": "מוכנה", "approved": "אושרה"}
COLOR_HE = {"green": "ירוק", "orange": "לבדיקה", "yellow": "זהב", "confirmed": "אושר ידנית", "empty": "ריק"}
SORT_HE = {"page": "סדר במסמך", "updated": "עודכן לאחרונה", "last_name": "שם משפחה", "first_name": "שם פרטי", "national_id": 'ת"ז',
           "date": "תאריך קבלה", "sender": "גורם שולח", "commitment": "מס' התחייבות", "status": "סטטוס"}
PAGE_SIZES = (25, 50, 100)
COLUMN_OF = {"first_name": "first_name", "last_name": "last_name", "id": "national_id", "center": "center", "date": "receipt_date",
             "sender": "sender", "commitment": "commitment_no"}


def _fmt(d: date | None) -> str | None:
    return d.strftime("%d.%m.%Y") if d else None


def read_filter(options: dict) -> service.RecordFilter:
    """ווידג'טי הסינון. מחזיר את אובייקט הסינון (גם לייצוא)."""
    uploads = {u["id"]: u for u in options["uploads"]}
    with st.container(border=True, key="rec_filters"):
        c1, c2, c3 = st.columns([2.2, 1.6, 1.6])
        search = c1.text_input("חיפוש", key="rec_search", placeholder="שם, ת\"ז, מס' התחייבות או מרכזי")
        statuses = c2.multiselect("סטטוס", list(STATUS_HE), key="rec_status", format_func=lambda s: STATUS_HE[s])
        senders = c3.multiselect("גורם שולח", options["senders"], key="rec_sender")
        d1, d2, d3, d4 = st.columns([1.4, 1.4, 1.6, 1.2])
        rng = d1.date_input("טווח תאריך קבלה", value=(), key="rec_dates", format="DD.MM.YYYY")
        upload_id = d2.selectbox("קובץ", [None, *uploads], key="rec_upload",
                                 format_func=lambda i: "כל הקבצים" if i is None else uploads[i]["filename"])
        sort = d3.selectbox("מיון", list(SORT_HE), key="rec_sort", format_func=lambda k: SORT_HE[k])
        desc = d4.toggle("יורד", key="rec_desc")
    start, end = (rng + (None, None))[:2] if isinstance(rng, tuple) and rng else (None, None)
    return service.RecordFilter(search=search, statuses=statuses, senders=senders, date_from=_fmt(start), date_to=_fmt(end or start),
                                upload_id=upload_id, sort=sort, descending=desc)


def _table(rows: list[dict]) -> pd.DataFrame:
    cols = [TITLES[k] for k in reversed(FIELD_KEYS)] + ["סטטוס", "עמוד"]      # הגריד מצויר משמאל לימין: הראשון בקריאה הוא הימני
    data = [{**{TITLES[k]: r[COLUMN_OF[k]] or "" for k in FIELD_KEYS}, "סטטוס": STATUS_HE[r["status"]], "עמוד": r["page_no"]} for r in rows]
    return pd.DataFrame(data, columns=cols)


def _do(action, *args) -> bool:
    """מריץ פעולת כתיבה ומציג שגיאה ידידותית. True אם הצליחה."""
    try:
        action(*args)
        return True
    except service.RecordLocked:
        st.session_state["rec_msg"] = ("error", "הרשומה מאושרת ולכן נעולה. בטלי אישור כדי לתקן.")
    except service.StaleVersion:
        st.session_state["rec_msg"] = ("error", "הרשומה השתנתה מאז שנטענה. הנתונים רועננו, נסי שוב.")
    except ValueError:
        st.session_state["rec_msg"] = ("error", "הערך לא תקין לשדה הזה, לא נשמר.")
    except Exception as e:
        log_server_error("records_screen", e)
        st.session_state["rec_msg"] = ("error", "הפעולה נכשלה (פרטים במסוף השרת).")
    return False


def _save_edits(rid: int, version: int, current: dict) -> None:
    """שומר את השדות שהשתנו בטופס. גרסה צפויה רק לכתיבה הראשונה (הבאות מקדמות אותה בעצמן).
    callbacks פותחים חיבור משלהם: חיבור SQLite לא עובר בין threads של ריצות הסקריפט."""
    conn = service.open_connection()
    changed = [(k, (st.session_state.get(f"rec_in_{rid}_{k}") or "").strip()) for k in FIELD_KEYS]
    changed = [(k, v) for k, v in changed if v and v != (current.get(k) or "")]
    if not changed:
        st.session_state["rec_msg"] = ("info", "לא בוצע שינוי.")
        return
    for i, (k, v) in enumerate(changed):
        if not _do(service.edit_record_field, conn, rid, k, v, version if i == 0 else None):
            _forget_inputs(rid)
            return
    _forget_inputs(rid)
    st.session_state["rec_msg"] = ("success", f"נשמרו {len(changed)} תיקונים.")


def _forget_inputs(rid: int) -> None:
    """אחרי שינוי: שדות הקלט של הרשומה נטענים מחדש מהמסד (ערך מנורמל, צבע חדש)."""
    for k in FIELD_KEYS:
        st.session_state.pop(f"rec_in_{rid}_{k}", None)


def _approve(rid: int) -> None:
    conn = service.open_connection()
    if _do(service.approve_row, conn, rid):
        _forget_inputs(rid)
        st.session_state["rec_msg"] = ("success", "הרשומה אושרה.")


def _unapprove(rid: int) -> None:
    conn = service.open_connection()
    if _do(service.unapprove_row, conn, rid):
        _forget_inputs(rid)
        st.session_state["rec_msg"] = ("success", "אישור הרשומה בוטל.")


def _revert(rid: int, key: str) -> None:
    conn = service.open_connection()
    if _do(service.revert_record_field, conn, rid, key):
        _forget_inputs(rid)
        st.session_state["rec_msg"] = ("success", "הערך הוחזר להצעת המערכת.")


def render_detail(conn, rid: int, he_flag) -> None:
    rec = service.record_detail(conn, rid)
    if rec is None:
        st.info("הרשומה לא נמצאה (ייתכן שנמחקה בעיבוד חוזר).")
        return
    locked = rec["status"] == "approved"
    with st.container(border=True, key="rec_detail"):
        head, btn = st.columns([4, 1.6], vertical_alignment="center")
        head.markdown(f"**רשומה {rec['id']}** · עמוד {rec['page_no']} · שורה {rec['ordinal'] + 1} · סטטוס: **{STATUS_HE[rec['status']]}**")
        if locked:
            btn.button("בטלי אישור", key=f"rec_unappr_{rid}", on_click=_unapprove, args=(rid,), width="stretch")
        else:
            btn.button("אשרי רשומה", key=f"rec_appr_{rid}", on_click=_approve, args=(rid,), type="primary", width="stretch")
        if locked:
            st.caption("הרשומה מאושרת ונעולה לשינוי; עיבוד חוזר של הקובץ לא ידרוס אותה.")
        cols = st.columns(2)
        for i, key in enumerate(FIELD_KEYS):
            fs = rec["fields"][key]
            with cols[i % 2]:
                shown = rec[COLUMN_OF[key]] or ""
                st.session_state.setdefault(f"rec_in_{rid}_{key}", shown)
                st.text_input(f"{TITLES[key]}  ·  {COLOR_HE.get(fs['color'], fs['color'])}", key=f"rec_in_{rid}_{key}", disabled=locked)
                notes = [he_flag(f, key) for f in fs["flags"]]
                if notes:
                    st.caption("לבדיקה: " + " · ".join(notes))
                if fs["alternatives"]:
                    st.caption("חלופות: " + " | ".join(fs["alternatives"]))
                if fs["cell_confirmed"] and not locked:
                    st.button("החזירי להצעת המערכת", key=f"rec_rv_{rid}_{key}", on_click=_revert, args=(rid, key))
        current = {k: rec[COLUMN_OF[k]] for k in FIELD_KEYS}
        st.button("שמרי תיקונים", key=f"rec_save_{rid}", on_click=_save_edits, args=(rid, rec["version"], current), disabled=locked,
                  type="primary")
        with st.expander("יומן שינויים"):
            if rec["audit"]:
                st.dataframe(pd.DataFrame(rec["audit"])[["at", "field", "action", "old", "new"]], hide_index=True, width="stretch")
            else:
                st.caption("אין שינויים.")


def render(db, he_flag) -> None:
    """db = פונקציה שמחזירה חיבור; he_flag = שם דגל בעברית (מוגדר ב-app.py)."""
    conn = db()
    options = service.filter_options(conn)
    counts = options["counts"]
    st.caption(f"במסד הנתונים · ממתינות: {counts['pending']} · מוכנות: {counts['ready']} · אושרו: {counts['approved']}")
    if not any(counts.values()):
        st.markdown("<div class='empty-state'><b>אין עדיין רשומות</b><p>עבדי קובץ במסך \"עיבוד\" והרשומות יישמרו כאן.</p></div>",
                    unsafe_allow_html=True)
        return
    flt = read_filter(options)
    size = st.session_state.get("rec_size", PAGE_SIZES[1])
    _rows, total = service.query(conn, flt, limit=1, offset=0)
    pages_n = max(1, -(-total // size))
    sig = (flt.search, tuple(flt.statuses), tuple(flt.senders), flt.date_from, flt.date_to, flt.upload_id, flt.sort, flt.descending, size)
    if st.session_state.get("_rec_sig") != sig:                       # סינון חדש: חוזרים לעמוד הראשון
        st.session_state["_rec_sig"], st.session_state["rec_page"] = sig, 1
    bar_l, bar_m, bar_r = st.columns([2, 1.2, 1.2], vertical_alignment="center")
    page = bar_m.number_input("עמוד", 1, pages_n, key="rec_page")
    bar_r.selectbox("שורות בעמוד", PAGE_SIZES, index=PAGE_SIZES.index(size), key="rec_size")
    rows, total = service.query(conn, flt, limit=size, offset=(int(page) - 1) * size)
    bar_l.markdown(f"<div class='counter'><b>{total}</b> רשומות מתאימות<span>עמוד {int(page)} מתוך {pages_n}</span></div>", unsafe_allow_html=True)
    msg = st.session_state.pop("rec_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    if not rows:
        st.markdown("<div class='empty-filter'><b>אין רשומות להצגה</b>אין רשומות שמתאימות לחיפוש או לסינון.</div>", unsafe_allow_html=True)
        return
    selected_id = None
    try:
        event = st.dataframe(_table(rows), width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row",
                             key=f"rec_grid_{abs(hash(sig))}", height=min(520, 40 + 40 * len(rows)))
        if event.selection.rows:
            selected_id = rows[event.selection.rows[0]]["id"]
    except Exception:                                                  # גרסת Streamlit בלי בחירת שורה
        selected_id = st.selectbox("רשומה", [r["id"] for r in rows], format_func=lambda i: f"רשומה {i}")
    if not selected_id and st.session_state.get("rec_open") in {r["id"] for r in rows}:    # פתיחה ישירה (קישור פנימי / בדיקות)
        selected_id = st.session_state["rec_open"]
    if selected_id:
        render_detail(conn, selected_id, he_flag)
    else:
        st.caption("בחרי שורה בטבלה כדי לתקן או לאשר אותה.")
