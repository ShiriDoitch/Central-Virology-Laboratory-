"""מסך הרשומות (Streamlit): כל מה ששמור במסד הנתונים. חיפוש, סינון (סטטוס, גורם שולח, טווח תאריכים, העלאה), מיון, עימוד,
תיקון ואישור של רשומה, ייצוא של הסינון הפעיל. קורא רק לפונקציות של src/service.py; בלי SQL.
תור עבודה: ברירת המחדל מציגה רק רשומות ממתינות ומוכנות (לא מאושרות); מונים לחיצים בראש המסך; "הבאה בתור" בכרטיס הרשומה."""
from dataclasses import replace
from datetime import date

import pandas as pd
import streamlit as st

import evidence_view
import review_screen
from src import guided_review, service, ui_text
from src import ui_theme as ui
from src.confirm import flag_chips_html, md_text
from src.export import COLUMNS, FIELD_KEYS, skip_reason
from src.privacy import log_server_error

TITLES = dict(COLUMNS)
STATUS_HE = {"pending": "ממתינה", "ready": "מוכנה", "approved": "אושרה"}
STATUS_STATE = ui.STATUS_STATE                    # גוון תג הסטטוס: src/ui_theme.py
COLOR_HE = ui.STATE_LABEL
SORT_HE = {"page": "סדר במסמך", "upload": "זמן העלאה", "updated": "עודכן לאחרונה", "last_name": "שם משפחה", "first_name": "שם פרטי", "national_id": 'ת"ז',
           "date": "תאריך קבלת דגימה", "sender": "גורם שולח", "commitment": "מס' התחייבות", "status": "סטטוס"}
PAGE_SIZES = (25, 50, 100)
UPLOAD_COL, STATUS_COL, PAGE_COL = "הועלה", "סטטוס", "עמוד"
COLUMN_OF = {"first_name": "first_name", "last_name": "last_name", "id": "national_id", "center": "center", "date": "receipt_date",
             "sender": "sender", "commitment": "commitment_no"}
# שדות הטבלה בסדר הקריאה (מימין לשמאל). הרשת מצוירת LTR, ולכן הרשימה נבנית הפוך (סוף הרשימה = העמודה הימנית).
TABLE_FIELDS = ("commitment", "first_name", "last_name", "id", "center", "sender", "date")
CODE_KEYS = ("id", "center", "commitment")           # קודים: יישור וקריאה כמספר, לא כטקסט עברי
# רוחב מינימלי בפיקסלים (הרשת מחלקת את הרוחב הפנוי באופן יחסי). עמודות המידע הצדדי (עמוד, הועלה) צרות, כדי שעשר עמודות ייכנסו.
WIDE_KEYS = {"center": 150, "commitment": 130, "id": 118, "sender": 148, "date": 132, "last_name": 100, "first_name": 92}
META_WIDTH = {PAGE_COL: 54, STATUS_COL: 88, UPLOAD_COL: 116}


def _fmt(d: date | None) -> str | None:
    return d.strftime("%d.%m.%Y") if d else None


def _set_statuses(statuses: list[str]) -> None:
    st.session_state["rec_status"] = list(statuses)


COUNTER_STYLE = {"pending": "ממתינות", "ready": "מוכנות", "approved": "אושרו"}


def render_top(counts: dict) -> str:
    """ראש המסך: תיבת חיפוש אחת בולטת, ולצידה המונים כקבוצה מפולחת (כל מונה מסנן לפי הסטטוס שלו).
    המספר נשאר בסוף התווית, כך שהתווית מספרת גם מה הסטטוס וגם כמה יש."""
    total = sum(counts.values())
    queue = counts["pending"] + counts["ready"]
    search_col, counter_col = st.columns([2, 3.3], vertical_alignment="bottom")
    search = search_col.text_input("חיפוש בכל הרשומות", key="rec_search", placeholder="שם, ת\"ז, מס' התחייבות או מרכזי")
    with counter_col:
        st.markdown("<div class='ro-label'>תצוגה לפי סטטוס</div>", unsafe_allow_html=True)
        current = list(st.session_state.get("rec_status") or [])
        with st.container(horizontal=True, gap="small", key="rec_counters"):
            for label, key, statuses, n in (("תור עבודה", "queue", list(service.WORK_QUEUE), queue),
                                            (COUNTER_STYLE["pending"], "pending", ["pending"], counts["pending"]),
                                            (COUNTER_STYLE["ready"], "ready", ["ready"], counts["ready"]),
                                            (COUNTER_STYLE["approved"], "approved", ["approved"], counts["approved"]),
                                            ("הכול", "all", list(STATUS_HE), total)):
                st.button(f"{label}  {n}", key=f"rec_cnt_{key}", on_click=_set_statuses, args=(statuses,),
                          type="primary" if sorted(current) == sorted(statuses) else "secondary")
    return search


def _active_filters() -> list[str]:
    """אילו מסננים (מלבד החיפוש והסטטוס שבראש המסך) פעילים כרגע, לפי מצב הפקדים: לתג שעל "סינון מתקדם"."""
    on = []
    for key, label in (("rec_sender", "גורם שולח"), ("rec_dates", "תאריך קבלת דגימה"), ("rec_upl_dates", "תאריך העלאה"), ("rec_upload", "קובץ")):
        if st.session_state.get(key):
            on.append(label)
    if (st.session_state.get("rec_sort") or "page") != "page" or st.session_state.get("rec_desc"):
        on.append("מיון")
    return on


def read_filter(options: dict, search: str) -> service.RecordFilter:
    """ווידג'טי הסינון, מקופלים ב"סינון מתקדם" (הסטטוס והחיפוש בראש המסך). מחזיר את אובייקט הסינון (גם לייצוא)."""
    uploads = {u["id"]: u for u in options["uploads"]}
    st.session_state.setdefault("rec_status", list(service.WORK_QUEUE))        # ברירת מחדל: מה שעדיין דורש עבודה
    active = _active_filters()
    label = "סינון מתקדם" + (f"  ·  **{len(active)} מסננים פעילים**" if active else "")
    with st.container(key="rec_filters"):
        with st.expander(label, expanded=False):
            if active:
                st.markdown(f"<span class='filter-badge'>פעיל: {' · '.join(active)}</span>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns([1.5, 1.5, 1.5, 1.1])
            statuses = c1.multiselect("סטטוס", list(STATUS_HE), key="rec_status", format_func=lambda s: STATUS_HE[s],
                                      placeholder="הכול")
            senders = c2.multiselect("גורם שולח", options["senders"], key="rec_sender", placeholder="כל הגורמים")
            upload_id = c3.selectbox("קובץ", [None, *uploads], key="rec_upload",
                                     format_func=lambda i: "כל הקבצים" if i is None else uploads[i]["filename"])
            sort = c4.selectbox("מיון", list(SORT_HE), key="rec_sort", format_func=lambda k: SORT_HE[k])
            d1, d2, d3 = st.columns([1.6, 1.6, 1.1])
            rng = d1.date_input("טווח תאריך קבלת דגימה (יום.חודש.שנה)", value=(), key="rec_dates", format="DD.MM.YYYY")
            upl = d2.date_input("טווח תאריך העלאה (יום.חודש.שנה)", value=(), key="rec_upl_dates", format="DD.MM.YYYY")
            with d3:
                st.markdown("<div class='ro-label'>כיוון המיון</div>", unsafe_allow_html=True)
                desc = st.toggle("מהסוף להתחלה", key="rec_desc")
    start, end = (rng + (None, None))[:2] if isinstance(rng, tuple) and rng else (None, None)
    u_start, u_end = (upl + (None, None))[:2] if isinstance(upl, tuple) and upl else (None, None)
    return service.RecordFilter(search=search, statuses=statuses, senders=senders, date_from=_fmt(start), date_to=_fmt(end or start),
                                upload_id=upload_id, sort=sort, descending=desc, uploaded_from=_fmt(u_start), uploaded_to=_fmt(u_end or u_start))


def _table(rows: list[dict]) -> pd.DataFrame:
    """עמודות הטבלה בסדר הקריאה: מס' התחייבות, שם פרטי, שם משפחה, ת"ז, מרכזי, גורם שולח, תאריך קבלת דגימה, עמוד, סטטוס, הועלה.
    הרשת מצוירת LTR, ולכן סדר הרשימה הפוך לסדר הקריאה (סוף הרשימה = העמודה הימנית)."""
    cols = [UPLOAD_COL, STATUS_COL, PAGE_COL] + [TITLES[k] for k in reversed(TABLE_FIELDS)]
    data = [{**{TITLES[k]: r[COLUMN_OF[k]] or "" for k in TABLE_FIELDS}, UPLOAD_COL: service.upload_time_label(r.get("upload_at")),
             STATUS_COL: STATUS_HE[r["status"]], PAGE_COL: r["page_no"]} for r in rows]
    return pd.DataFrame(data, columns=cols)


def _styled(df: pd.DataFrame, rows: list[dict]):
    """עמודת הסטטוס כתג: מילה + גוון המצב (צבע לעולם לא לבד). שאר העמודות נייטרליות."""
    states = [ui.badge_cell_css(STATUS_STATE.get(r["status"])) for r in rows]
    return df.style.apply(lambda col: states if col.name == STATUS_COL else [""] * len(col), axis=0)


def _table_config(df: pd.DataFrame) -> dict:
    """יישור ורוחב: הכול לימין (עברית), הסטטוס ועמוד המקור ממורכזים וצרים, קודים ברוחב קבוע."""
    width_of = {TITLES[k]: w for k, w in WIDE_KEYS.items()}
    cfg = {STATUS_COL: st.column_config.TextColumn(STATUS_COL, width=META_WIDTH[STATUS_COL], alignment="center"),
           UPLOAD_COL: st.column_config.TextColumn(UPLOAD_COL, width=META_WIDTH[UPLOAD_COL], alignment="right"),
           PAGE_COL: st.column_config.NumberColumn(PAGE_COL, width=META_WIDTH[PAGE_COL], format="%d", help="עמוד המקור במסמך")}
    for col in df.columns:
        cfg.setdefault(col, st.column_config.TextColumn(col, width=width_of.get(col), alignment="right"))
    return cfg


def _do(action, *args) -> bool:
    """מריץ פעולת כתיבה ומציג שגיאה ידידותית. True אם הצליחה."""
    try:
        action(*args)
        return True
    except service.RecordLocked:
        st.session_state["rec_msg"] = ("error", "הרשומה מאושרת ולכן נעולה. לתיקון יש לבטל את האישור.")
    except service.StaleVersion:
        st.session_state["rec_msg"] = ("error", "הרשומה השתנתה מאז שנטענה. הנתונים רועננו, יש לנסות שוב.")
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
    """אחרי שינוי: שדות הקלט של הרשומה נטענים מחדש מהמסד (ערך מנורמל, צבע חדש). הרשומה נשארת פתוחה (rec_open) גם אם הסינון
    הפעיל כבר לא כולל אותה (למשל אושרה בתור העבודה), ובחירת השורה בטבלה מתאפסת (אינדקס ישן היה מצביע על שורה אחרת)."""
    for k in FIELD_KEYS:
        st.session_state.pop(f"rec_in_{rid}_{k}", None)
    _pin(rid)


def _pin(rid: int) -> None:
    st.session_state["rec_open"] = rid
    st.session_state["_rec_gen"] = st.session_state.get("_rec_gen", 0) + 1


def _close_detail() -> None:
    st.session_state.pop("rec_open", None)
    st.session_state["_rec_gen"] = st.session_state.get("_rec_gen", 0) + 1


def _open_neighbor(current_id: int, back: bool = False) -> None:
    """פותח את הרשומה הממתינה הבאה (או הקודמת) בסדר המיון והסינון הנוכחיים, עם חזרה להתחלה, ועובר לעמוד הטבלה שלה.
    אם סינון הסטטוס הפעיל מסתיר רשומות ממתינות, מוסיפים אליו "ממתינה" כדי שהיא תהיה גלויה בטבלה."""
    conn = service.open_connection()
    flt = st.session_state.get("_rec_flt") or service.RecordFilter()
    if back:      # אחורה = אותה בחירה על הרשימה ההפוכה (בלי סינון סטטוס, כמו next_pending_id)
        nxt = service.pick_next_pending(list(reversed(service.ordered_ids(conn, replace(flt, statuses=[])))), current_id)
    else:
        nxt = service.next_pending_id(conn, flt, current_id)
    if nxt is None:
        st.session_state["rec_msg"] = ("info", "אין רשומות ממתינות נוספות בסינון הנוכחי.")
        return
    if flt.statuses and "pending" not in flt.statuses:
        flt = replace(flt, statuses=[*flt.statuses, "pending"])
        st.session_state["rec_status"] = list(flt.statuses)
    pos = service.position_in(conn, flt, nxt)
    if pos is not None:
        st.session_state["_rec_goto_page"] = pos // st.session_state.get("rec_size", PAGE_SIZES[1]) + 1
    _pin(nxt)


def _open_next(current_id: int) -> None:
    _open_neighbor(current_id)


def _open_prev(current_id: int) -> None:
    _open_neighbor(current_id, back=True)


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


# ---------- בדיקה במבט אחד: פתיחת הבדיקה, אישור קבוצתי ----------

def _bulk_approve(flt: service.RecordFilter) -> None:
    """מאשר את כל הרשומות הבטוחות שבסינון. הרשימה נבנית מחדש בשירות, ולכן המספר שהוצג אינו קובע מה מאושר."""
    conn = service.open_connection()
    try:
        n = service.approve_safe_records(conn, flt)
    except Exception as e:
        log_server_error("approve_safe_records", e)
        st.session_state["rec_msg"] = ("error", "האישור הקבוצתי נכשל (פרטים במסוף השרת).")
        return
    st.session_state["rec_bulk_ok"] = False                     # התיבה חוזרת למצב לא מסומן
    st.session_state["_rec_gen"] = st.session_state.get("_rec_gen", 0) + 1
    st.session_state["rec_msg"] = (("success", f"אושרו {n} רשומות בטוחות.") if n else
                                   ("info", "לא נמצאו רשומות בטוחות לאישור בסינון הפעיל."))


def render_bulk_approve(flt: service.RecordFilter, safe: int) -> None:
    """אישור קבוצתי: קודם המספר, ואז תיבת סימון וכפתור. רשומה שיש בה תא לבדיקה לא נכללת לעולם."""
    with st.popover(f"אישור כל הרשומות הבטוחות  {safe}", disabled=safe == 0):
        st.markdown(ui.quiet(f"<b>{safe}</b> רשומות שבהן כל שבעת השדות ירוקים בלי דגל או אושרו על ידך. "
                             "רשומה שיש בה תא לבדיקה (כתום, זהב או ריק) אינה נכללת, וגם לא רשומה שכבר אושרה."),
                    unsafe_allow_html=True)
        ok = st.checkbox("המספר נבדק ואפשר לאשר", key="rec_bulk_ok")
        st.button("אישור הרשומות", key="rec_bulk_go", on_click=_bulk_approve, args=(flt,), type="primary",
                  disabled=not ok, width="stretch")
        st.caption("כל אישור ניתן לביטול ברשומה עצמה (\"ביטול אישור\").")


def render_review_bar(conn, flt: service.RecordFilter) -> None:
    """שורה אחת מעל הטבלה: התחלת בדיקה מונחית על הרשומות שבסינון, ואישור קבוצתי של הרשומות הבטוחות."""
    try:
        counts = service.review_counts(conn, flt)
    except Exception as e:
        log_server_error("review_counts", e)
        return
    with st.container(key="rev_bar"):
        start_col, info_col, bulk_col = st.columns([1.3, 2.4, 1.7], vertical_alignment="center")
        start_col.button("התחלת בדיקה", key="rev_start", on_click=review_screen.start, args=(flt,), type="primary",
                         width="stretch", disabled=counts["cells"] == 0,
                         help="עוברים תא-תא על כל מה שסומן לבדיקה, עם הטופס המקורי לצד הערך")
        info_col.markdown(ui.quiet(f"<b>{counts['cells']}</b> תאים לבדיקה ב-<b>{counts['records']}</b> טפסים · "
                                   f"<b>{counts['safe']}</b> רשומות בטוחות לאישור"), unsafe_allow_html=True)
        with bulk_col:
            render_bulk_approve(flt, counts["safe"])


def _open_record(rid: int) -> None:
    _pin(rid)


def render_quality_panel(conn) -> None:
    """איכות המערכת בשימוש, מתוך מה שכבר שמור (מצבי השדות ויומן השינויים): כמה תאים המכונה שמרה כירוקים,
    כמה מהם תוקנו בפועל (אמור להיות 0), וכמה תאים נבדקו. בלי שום מספר מוערך."""
    try:
        q = service.quality_stats(conn)
        bad = service.green_edited_cells(conn) if q["green_edited"] else []
    except Exception as e:
        log_server_error("quality_stats", e)
        return
    with st.expander("איכות המערכת בשימוש", expanded=bool(bad)):
        tone = "bad" if q["green_edited"] else "ok"
        st.markdown(f"<div class='rv-metrics'>"
                    f"<div><span>תאים שהמערכת שמרה כירוקים</span><b>{q['green']}</b></div>"
                    f"<div class='{tone}'><span>מהם שתוקנו ידנית (צריך 0)</span><b>{q['green_edited']}</b></div>"
                    f"<div><span>תאים שנבדקו</span><b>{q['reviewed']}</b></div>"
                    f"<div><span>אושרו בלי שינוי</span><b>{q['confirmed_unchanged']}</b></div>"
                    f"<div><span>תוקנו</span><b>{q['corrected']}</b></div></div>", unsafe_allow_html=True)
        st.caption("נמדד מכל מה ששמור במסד: \"ירוק\" = המערכת קראה ערך ולא סימנה אותו לבדיקה. ירוק שתוקן ידנית "
                   "הוא המקרה החמור, כי שם המערכת הייתה בטוחה וטעתה, ולכן הוא מוצג בנפרד.")
        if bad:
            st.error(f"{q['green_edited']} תאים שהמערכת שמרה כירוקים תוקנו ידנית. כדאי לבדוק אותם: "
                     "ייתכן שצריך לסמן את השדה הזה לבדיקה גם בפעם הבאה.")
            for c in bad:
                label = f"רשומה {int(c['record_id'])} · עמוד {int(c['page_no'])} · {TITLES.get(c['field'], c['field'])}"
                st.button(f"פתיחת {label}", key=f"rec_gw_{c['record_id']}_{c['field']}", on_click=_open_record,
                          args=(int(c["record_id"]),))


def pending_fields(rec: dict) -> list[str]:
    """שמות השדות שמונעים אישור של הרשומה: ערך שסומן לבדיקה (כתום) ושלא אושר. תא **ריק אינו מונע** (שדה
    יכול באמת לא להופיע בטופס), וגם תא צהוב לא (שתי קריאות עצמאיות שמסכימות: מבט מספיק)."""
    return [TITLES[k] for k, fs in (rec.get("fields") or {}).items() if guided_review.blocks_approval(fs)]


def render_field_notes(fs: dict, key: str, he_flag) -> None:
    """דגלים וחלופות של שדה, מקופלים. נפתח מעצמו רק בשדה שסומן לבדיקה (כתום), כדי שהכרטיס יישאר שקט."""
    notes = [he_flag(f, key) for f in fs["flags"]]
    alts = list(fs["alternatives"] or [])
    if not notes and not alts:
        return
    with st.expander(f"דגלים וחלופות ({len(notes) + len(alts)})", expanded=fs["color"] == "orange"):
        if notes:
            st.markdown("**לבדיקה:** " + flag_chips_html(notes), unsafe_allow_html=True)
        if alts:
            st.markdown("**חלופות:** " + " | ".join(md_text(a) for a in alts))


def _images(conn, rec: dict):
    """תמונת העמוד השמורה וחיתוכי השדות; כשל בקריאה (קובץ פגום) נחשב כתמונה חסרה ולא מפיל את הכרטיס."""
    try:
        return service.record_images(conn, rec)
    except Exception as e:
        log_server_error("record_images", e)
        return None, {}


def render_detail(conn, rid: int, he_flag) -> None:
    rec = service.record_detail(conn, rid)
    if rec is None:
        st.info("הרשומה לא נמצאה (ייתכן שנמחקה בעיבוד חוזר).")
        st.session_state.pop("rec_open", None)
        return
    locked = rec["status"] == "approved"
    with st.container(border=True, key="rec_detail"):
        with st.container(key="rec_actions"):          # סרגל פעולות אחד: אישור (ראשי), ניווט בתור, סגירה
            appr, prev_b, next_b, close_b = st.columns(4, vertical_alignment="center")
            if locked:
                appr.button("ביטול אישור", key=f"rec_unappr_{rid}", on_click=_unapprove, args=(rid,), width="stretch")
            else:
                pending = pending_fields(rec)
                with appr:
                    st.button("אישור רשומה", key=f"rec_appr_{rid}", on_click=_approve, args=(rid,), type="primary",
                              width="stretch", disabled=bool(pending),
                              help=("יש לאשר או לתקן קודם: " + ", ".join(pending)) if pending
                              else "מסמן את הרשומה כבדוקה. רשומה מאושרת נעולה ולא נדרסת בעיבוד חוזר.")
                    if pending:
                        st.caption(ui_text.pending_hint(len(pending)))
            prev_b.button("← הממתינה הקודמת", key=f"rec_prev_{rid}", on_click=_open_prev, args=(rid,), width="stretch",
                          help="הרשומה הממתינה הקודמת בסדר המיון והסינון הנוכחיים")
            next_b.button("הממתינה הבאה →", key=f"rec_next_{rid}", on_click=_open_next, args=(rid,), width="stretch",
                          help="הרשומה הממתינה הבאה בסדר המיון והסינון הנוכחיים")
            close_b.button("סגירה", key=f"rec_close_{rid}", on_click=_close_detail, width="stretch")
        st.markdown(
            f"<div class='rec-head'><span class='rec-title'>רשומה {int(rec['id'])}</span>"
            f"{ui.badge(STATUS_STATE[rec['status']], STATUS_HE[rec['status']])}"
            f"<span class='rec-meta'>עמוד {int(rec['page_no'])} · שורה {int(rec['ordinal']) + 1}"
            + (" · נעולה לשינוי; עיבוד חוזר של הקובץ לא ידרוס אותה" if locked else "") + "</span></div>",
            unsafe_allow_html=True)
        image, crops = _images(conn, rec)
        if image is None:
            st.info(service.IMAGE_MISSING_TEXT)                              # עריכה ואישור ממשיכים לעבוד גם בלי תמונה
        else:
            with st.expander("העמוד המקורי", expanded=True):
                evidence_view.render_zoomable_page(image, zoom_key=f"rec_pagezoom_{rid}")
        with st.container(key="rec_fields"):
            cols = st.columns(2, gap="medium")
            for i, key in enumerate(FIELD_KEYS):
                fs = rec["fields"][key]
                state = fs["color"] if fs["color"] in ui.STATES else "empty"
                with cols[i % 2]:
                    shown = rec[COLUMN_OF[key]] or ""
                    if locked:                         # רשומה נעולה: הערך נקרא כטקסט, לא כשדה קלט מושתק
                        st.markdown(ui.field_row(TITLES[key], shown, state, mono=key in CODE_KEYS), unsafe_allow_html=True)
                    else:
                        st.session_state.setdefault(f"rec_in_{rid}_{key}", shown)
                        st.markdown(ui.field_head(TITLES[key], state), unsafe_allow_html=True)
                        st.text_input(TITLES[key], key=f"rec_in_{rid}_{key}", label_visibility="collapsed")
                    render_field_notes(fs, key, he_flag)
                    if crops.get(key):
                        with st.expander("האזור בטופס"):
                            evidence_view.render_crop_and_page(crops[key], None, rec["page_no"], zoom_key=f"rec_zoom_{rid}_{key}")
                    if fs["cell_confirmed"] and not locked:
                        st.button("החזרה להצעת המערכת", key=f"rec_rv_{rid}_{key}", on_click=_revert, args=(rid, key))
        if not locked:
            current = {k: rec[COLUMN_OF[k]] for k in FIELD_KEYS}
            st.button("שמירת תיקונים", key=f"rec_save_{rid}", on_click=_save_edits, args=(rid, rec["version"], current), type="primary")
        with st.expander("יומן שינויים"):
            if rec["audit"]:
                st.dataframe(pd.DataFrame(rec["audit"])[["at", "field", "action", "old", "new"]], hide_index=True, width="stretch")
            else:
                st.caption("אין שינויים.")


def render_export(conn, flt: service.RecordFilter, total: int) -> None:
    """ייצוא כל הרשומות שבסינון, מקובץ בתפריט אחד (Excel / CSV / JSON)."""
    with st.popover("ייצוא · כל הרשומות בסינון", disabled=total == 0):
        st.markdown(ui.quiet(f"<b>{total}</b> רשומות מתאימות לסינון הפעיל. בחירת פורמט:"), unsafe_allow_html=True)
        for fmt, label in (("xlsx", "Excel"), ("csv", "CSV"), ("json", "JSON")):
            try:
                data, mime, name = service.export_records(conn, flt, fmt)
                st.download_button(label, data, file_name=name, mime=mime, key=f"rec_dl_{fmt}", disabled=total == 0, width="stretch")
            except Exception as e:
                log_server_error("export_records", e)
                st.caption(f"ייצוא {label} נכשל")


WIPE_SESSION_KEYS = ("rec_open", "selected_cell", "upload_id", "pages", "images", "field_crops", "name_overrides", "_rec_flt", "_rec_sig",
                     "rec_page", "_rec_goto_page")


def _wipe_all() -> None:
    """מוחק לצמיתות את כל הנתונים (מסד + תמונות) ומנקה גם את תוצאות הסשן הנוכחי שבזיכרון."""
    try:
        counts = service.delete_all_data(service.open_connection())
    except Exception as e:
        log_server_error("delete_all_data", e)
        st.session_state["rec_wipe_msg"] = ("error", "המחיקה נכשלה (פרטים במסוף השרת). לא נמחק הכול, יש לנסות שוב.")
        return
    for key in WIPE_SESSION_KEYS:
        st.session_state.pop(key, None)
    st.session_state["_rec_gen"] = st.session_state.get("_rec_gen", 0) + 1
    st.session_state["rec_wipe_ok"] = False
    st.session_state["rec_wipe_msg"] = ("success", f"הנתונים נמחקו לצמיתות: {counts['records']} רשומות, {counts['uploads']} העלאות, "
                                                   f"{counts['audit_log']} רשומות ביומן ו-{counts['images']} תמונות עמוד.")


def render_data_management() -> None:
    """אזור קטן ומקופל בתחתית המסך, רחוק מכפתורי הפעולה הרגילים: מחיקת כל הנתונים. דורש תיבת סימון וכפתור."""
    st.divider()
    with st.expander("ניהול נתונים", expanded=False):
        st.warning("המחיקה סופית ואינה ניתנת לשחזור. נמחקים כל הרשומות, יומן השינויים, ההעלאות וכל תמונות העמודים השמורות. "
                   "קבצים שכבר הורדת (Excel / CSV / JSON) לא מושפעים.")
        confirmed = st.checkbox("אישור: המחיקה סופית ואינה ניתנת לשחזור", key="rec_wipe_ok")
        st.button("מחיקת כל הנתונים", key="rec_wipe_all", on_click=_wipe_all, disabled=not confirmed)


def skipped_pages(pages: list[dict] | None = None) -> list[tuple[int, str]]:
    """עמודים מהעיבוד הנוכחי שלא נכנסו לרשומות, עם הסיבה. ברירת המחדל: העמודים שבמצב הסשן."""
    pages = st.session_state.get("pages") if pages is None else pages
    return [(p["page"], reason) for p in sorted(pages or [], key=lambda x: x["page"]) if (reason := skip_reason(p))]


def render_skipped(pages: list[dict] | None = None) -> None:
    """עמוד שלא נכנס לרשומות לא נעלם: הוא מוצג כאן במפורש (לא בתוך expander סגור), כדי שאפשר יהיה לפתוח
    את הקובץ ולבדוק אותו ידנית. עמוד עם סימני טופס כבר אינו מגיע לכאן אלא נכנס כרשומה כתומה (assemble.page_rows)."""
    rows = skipped_pages(pages)
    if not rows:
        return
    st.warning(f"**{len(rows)} עמודים לא נכנסו לרשומות** (לא זוהו כטופס התחייבות). יש לבדוק אותם בקובץ המקור:")
    for page, reason in rows:
        st.markdown(f"- **עמוד {page}**: {reason}")


def render(db, he_flag) -> None:
    """מסך הרשומות; ניהול הנתונים (מחיקה מלאה) תמיד בתחתית."""
    msg = st.session_state.pop("rec_wipe_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    if review_screen.active():            # בדיקה מונחית פעילה: היא תופסת את המסך (בלי טבלה ובלי מחיקת נתונים לידה)
        review_screen.render(db, he_flag)
        return
    render_skipped()
    _render_main(db, he_flag)
    render_data_management()


def _render_main(db, he_flag) -> None:
    """db = פונקציה שמחזירה חיבור; he_flag = שם דגל בעברית (מוגדר ב-app.py)."""
    conn = db()
    options = service.filter_options(conn)
    counts = options["counts"]
    if not any(counts.values()):
        st.markdown("<div class='empty-state'><b>אין עדיין רשומות</b><p>עיבוד קובץ במסך \"עיבוד\" ישמור את הרשומות כאן.</p></div>",
                    unsafe_allow_html=True)
        return
    with st.container(key="rec_top"):
        search = render_top(counts)
        flt = read_filter(options, search)
    st.session_state["_rec_flt"] = flt                                  # לשימוש ה-callbacks (הבאה בתור) ולמבחנים
    render_review_bar(conn, flt)
    render_quality_panel(conn)
    size = st.session_state.get("rec_size", PAGE_SIZES[1])
    _rows, total = service.query(conn, flt, limit=1, offset=0)
    pages_n = max(1, -(-total // size))
    sig = (flt.search, tuple(flt.statuses), tuple(flt.senders), flt.date_from, flt.date_to, flt.upload_id, flt.sort, flt.descending,
           flt.uploaded_from, flt.uploaded_to, size)
    if st.session_state.get("_rec_sig") != sig:                       # סינון חדש: חוזרים לעמוד הראשון
        st.session_state["_rec_sig"], st.session_state["rec_page"] = sig, 1
    goto = st.session_state.pop("_rec_goto_page", None)               # "הבאה בתור": קופצים לעמוד של הרשומה הנפתחת
    if goto:
        st.session_state["rec_page"] = int(goto)
    # פקדי העימוד מוצגים מתחת לטבלה, אך הערך נדרש לשאילתה שלפניה: נקרא מהמצב ומוגבל לטווח לפני יצירת הפקד
    page = min(max(1, int(st.session_state.get("rec_page", 1))), pages_n)
    st.session_state["rec_page"] = page
    rows, total = service.query(conn, flt, limit=size, offset=(page - 1) * size)
    msg = st.session_state.pop("rec_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    selected_id = None
    if not rows:
        st.markdown("<div class='empty-filter'><b>אין רשומות להצגה</b>אין רשומות שמתאימות לחיפוש או לסינון.</div>", unsafe_allow_html=True)
    else:
        try:      # מפתח הרשת כולל עמוד וגל פעולות: בחירה ישנה (אינדקס) לא עוברת לשורה אחרת אחרי החלפת עמוד / אישור / "הבאה בתור"
            table = _table(rows)
            event = st.dataframe(_styled(table, rows), width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row",
                                 column_config=_table_config(table),
                                 key=f"rec_grid_{abs(hash(sig))}_{page}_{st.session_state.get('_rec_gen', 0)}",
                                 height=min(520, 40 + 40 * len(rows)))
            if event.selection.rows:
                selected_id = rows[event.selection.rows[0]]["id"]
                st.session_state["rec_open"] = selected_id
        except Exception:                                                  # גרסת Streamlit בלי בחירת שורה
            selected_id = st.selectbox("רשומה", [r["id"] for r in rows], format_func=lambda i: f"רשומה {i}")
    # שורה שקטה אחת מתחת לטבלה: מה מוצג, עימוד וייצוא
    with st.container(key="rec_pager"):
        info_col, page_col, size_col, exp_col = st.columns([1.7, 1, 1, 1.5], vertical_alignment="center")
        info_col.markdown(ui.quiet(f"<b>{total}</b> רשומות מתאימות · עמוד {page} מתוך {pages_n}"), unsafe_allow_html=True)
        page_col.number_input("עמוד", 1, pages_n, key="rec_page")
        size_col.selectbox("שורות בעמוד", PAGE_SIZES, index=PAGE_SIZES.index(size), key="rec_size")
        with exp_col:
            render_export(conn, flt, total)
    if not selected_id:
        selected_id = st.session_state.get("rec_open")                  # רשומה שנפתחה (הבאה בתור / אחרי אישור), גם אם הסינון מסתיר אותה
    if selected_id:
        render_detail(conn, selected_id, he_flag)
    else:
        st.caption("בחירת שורה בטבלה פותחת אותה לתיקון ולאישור.")
