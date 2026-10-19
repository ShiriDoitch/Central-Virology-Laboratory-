"""שכבת שירות בין הצינור / הממשק לבין src/repo.py: ממירה שורות ייצוא (ExportRow) לרשומות מסד נתונים ובחזרה.
אין כאן SQL ואין Streamlit. כל כשל כתיבה נרשם בשרת (בלי PII) ולא מפיל עיבוד שכבר רץ."""
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import db_export, repo
from .confirm import normalize_override
from .export import FIELD_KEYS, Cell, build_rows
from .privacy import log_server_error


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cell_color(cell: Cell) -> str:
    """אותם סדרי עדיפויות כמו בטבלה ובאקסל: confirmed > yellow > orange (דגל, גם בתא ריק) > green (ערך) > empty."""
    if cell.confirmed:
        return "confirmed"
    if cell.yellow:
        return "yellow"
    if cell.orange:
        return "orange"
    return "green" if cell.value else "empty"


def machine_fields(cells: dict[str, Cell]) -> dict[str, dict]:
    """מה שהמערכת קבעה לכל שדה (בלי אישורי משתמש): ערך מוצג, צבע, דגלים כקודים, חלופות."""
    return {k: {"value": cells[k].value or None, "color": cell_color(cells[k]), "flags": list(cells[k].flags),
                "alternatives": list(cells[k].alternatives)} for k in FIELD_KEYS}


def machine_rows(page_result: dict):
    """שורות הייצוא של עמוד לפי המכונה בלבד (בלי overrides)."""
    return build_rows(page_result)


class Persister:
    """שומר לפי עמוד תוך כדי העיבוד (כך שהתקדמות לא אובדת אם הריצה נפסקת באמצע)."""

    def __init__(self, conn, filename: str, data: bytes):
        self.conn, self.filename, self.sha = conn, filename, sha256_of(data)
        self.upload_id: int | None = None
        self.errors = 0
        self.counts = {"created": 0, "updated": 0, "skipped_approved": 0}

    def start(self, page_count: int) -> int:
        existing = repo.find_upload(self.conn, self.sha)
        self.upload_id = existing["id"] if existing else repo.create_upload(self.conn, self.filename, self.sha, page_count)
        return self.upload_id

    def page(self, page_result: dict) -> None:
        try:
            rows = machine_rows(page_result) if (page_result.get("pass1") or {}).get("ok") else []
            for er in rows:
                _rid, outcome = repo.save_machine_record(self.conn, self.upload_id, page_result["page"], er.index, machine_fields(er.cells))
                self.counts[outcome] += 1
            if rows:
                repo.prune_page_records(self.conn, self.upload_id, page_result["page"], len(rows))
        except Exception as e:                      # כשל כתיבה לא מפיל את העיבוד; הפרטים רק במסוף
            self.errors += 1
            log_server_error(f"persist page {page_result.get('page')}", e)

    def finish(self) -> None:
        if self.upload_id is not None and not self.errors:
            repo.complete_upload(self.conn, self.upload_id)


def find_completed_upload(conn, data: bytes) -> dict | None:
    """אותו קובץ (sha256) שכבר עובד עד הסוף: פותחים את הרשומות הקיימות במקום לעבד שוב. העלאה שנקטעה (completed_at ריק) תעובד שוב,
    ורשומות מאושרות או מתוקנות בה לא נדרסות."""
    up = repo.find_upload(conn, sha256_of(data))
    if not (up and up["completed_at"]):
        return None
    return {**up, "record_count": sum(repo.status_counts(conn, up["id"]).values())}


def open_connection():
    return repo.connect()


# ---------- תיקונים ואישורים (שלב 3) ----------

RecordLocked = repo.RecordLocked
StaleVersion = repo.StaleVersion
COMMITMENT_PREFIX = "commitment#"


def _targets(conn, upload_id: int, page: int, okey: str) -> tuple[str, list[dict]]:
    """(שדה, רשומות) שמושפעות ממפתח אישור של הממשק: התחייבות לפי שורה, כל שדה אחר חל על כל השורות בעמוד."""
    recs = repo.page_records(conn, upload_id, page)
    if okey.startswith(COMMITMENT_PREFIX):
        ordinal = int(okey[len(COMMITMENT_PREFIX):])
        return "commitment", [r for r in recs if r["ordinal"] == ordinal]
    if okey not in FIELD_KEYS:
        raise ValueError(f"unknown field {okey!r}")
    return okey, recs


def save_override(conn, upload_id: int, page: int, okey: str, value: str | None, page_result: dict) -> int:
    """כותב לאחר תיקון / אישור / ביטול אישור של תא בממשק. value=None מחזיר לערך המכונה (הצבע שלה מחושב מחדש מתוצאת העמוד).
    אם אחת הרשומות מאושרת: RecordLocked ושום דבר לא נכתב. מחזיר כמה רשומות עודכנו."""
    field, recs = _targets(conn, upload_id, page, okey)
    if any(r["status"] == "approved" for r in recs):
        raise RecordLocked(f"page {page}: a row is approved")
    machine = {er.index: er for er in machine_rows(page_result)}
    for r in recs:
        if value:
            repo.edit_field(conn, r["id"], field, value)
        else:
            repo.revert_field(conn, r["id"], field, color=cell_color(machine[r["ordinal"]].cells[field]))
    return len(recs)


def load_overrides(conn, upload_id: int) -> dict:
    """אישורי המשתמש השמורים, בצורה שהממשק משתמש בה: {(עמוד, שדה | "commitment#<שורה>"): ערך}."""
    out: dict = {}
    for r in repo.search_records(conn, upload_id=upload_id, limit=None)[0]:
        full = repo.get_record(conn, r["id"])
        for field, st in full["fields"].items():
            if st["cell_confirmed"]:
                key = f"{COMMITMENT_PREFIX}{r['ordinal']}" if field == "commitment" else field
                out[(r["page_no"], key)] = full["center"] if field == "center" else full[repo.FIELD_COLUMN[field]]
    return out


def row_info(conn, upload_id: int, page: int, ordinal: int) -> dict | None:
    rid = repo.find_record(conn, upload_id, page, ordinal)
    rec = repo.get_record(conn, rid) if rid else None
    return {"id": rid, "status": rec["status"], "version": rec["version"]} if rec else None


def approve_row(conn, record_id: int) -> None:
    repo.approve_record(conn, record_id)


def unapprove_row(conn, record_id: int) -> None:
    repo.unapprove_record(conn, record_id)


def status_counts(conn, upload_id: int | None = None) -> dict[str, int]:
    return repo.status_counts(conn, upload_id)


# ---------- מסך הרשומות (שלב 4) ----------

@dataclass
class RecordFilter:
    """מסנני מסך הרשומות; גם הייצוא משתמש באותו אובייקט (מה שרואים הוא מה שמיוצא). תאריכים בפורמט dd.mm.yyyy."""
    search: str = ""
    statuses: list[str] = field(default_factory=list)
    senders: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    upload_id: int | None = None
    sort: str = "page"
    descending: bool = False
    uploaded_from: str | None = None     # תאריך העלאה (dd.mm.yyyy, שעון מקומי, כולל)
    uploaded_to: str | None = None


WORK_QUEUE = ["pending", "ready"]          # ברירת המחדל במסך הרשומות: מה שעדיין דורש עבודה (בלי מאושרות)


def local_day_start_utc(ddmmyyyy: str, plus_days: int = 0) -> str:
    """חצות מקומי של התאריך (ועוד plus_days) כחותמת ISO ב-UTC, באותו פורמט שבו נשמר uploads.created_at (להשוואת מחרוזות)."""
    local_midnight = datetime.strptime(ddmmyyyy, "%d.%m.%Y") + timedelta(days=plus_days)
    return local_midnight.astimezone(timezone.utc).isoformat(timespec="seconds")


def upload_time_label(iso_utc: str | None) -> str:
    """זמן ההעלאה לתצוגה (שעון מקומי): dd.mm.yyyy HH:MM."""
    if not iso_utc:
        return ""
    return datetime.fromisoformat(iso_utc).astimezone().strftime("%d.%m.%Y %H:%M")


def _search_args(flt: RecordFilter) -> dict:
    return dict(search=flt.search, statuses=flt.statuses, senders=flt.senders, date_from=flt.date_from, date_to=flt.date_to,
                upload_id=flt.upload_id, sort=flt.sort, descending=flt.descending,
                uploaded_from=local_day_start_utc(flt.uploaded_from) if flt.uploaded_from else None,
                uploaded_before=local_day_start_utc(flt.uploaded_to, 1) if flt.uploaded_to else None)


def query(conn, flt: RecordFilter, limit: int | None = 50, offset: int = 0) -> tuple[list[dict], int]:
    return repo.search_records(conn, limit=limit, offset=offset, **_search_args(flt))


def ordered_ids(conn, flt: RecordFilter) -> list[tuple[int, str]]:
    """(מזהה, סטטוס) של כל הרשומות שמתאימות לסינון, בסדר המיון הנוכחי (קל: בלי שאילתת מרכזיים לכל שורה)."""
    rows, _ = repo.search_records(conn, limit=None, light=True, **_search_args(flt))
    return [(r["id"], r["status"]) for r in rows]


def pick_next_pending(items: list[tuple[int, str]], current_id: int | None) -> int | None:
    """הרשומה הממתינה (pending) הבאה אחרי current_id ברשימה הממוינת, עם חזרה להתחלה. None אם אין אחרת. אם current_id לא ברשימה:
    הראשונה הממתינה."""
    ids = [i for i, _ in items]
    start = ids.index(current_id) + 1 if current_id in ids else 0
    for i, status in items[start:] + items[:start]:
        if status == "pending" and i != current_id:
            return i
    return None


def next_pending_id(conn, flt: RecordFilter, current_id: int | None) -> int | None:
    """הבאה בתור: בסדר המיון והסינון הנוכחיים, בלי סינון הסטטוס (כדי שאפשר יהיה להגיע לממתינה גם כשהטבלה מציגה רק מוכנות)."""
    from dataclasses import replace
    return pick_next_pending(ordered_ids(conn, replace(flt, statuses=[])), current_id)


def position_in(conn, flt: RecordFilter, record_id: int) -> int | None:
    """אינדקס (מ-0) של הרשומה ברשימה הממוינת של הסינון, או None אם אינה בו. לחישוב מספר העמוד."""
    ids = [i for i, _ in ordered_ids(conn, flt)]
    return ids.index(record_id) if record_id in ids else None


def record_detail(conn, record_id: int) -> dict | None:
    rec = repo.get_record(conn, record_id)
    if rec:
        rec["audit"] = repo.audit_entries(conn, record_id)
    return rec


def edit_record_field(conn, record_id: int, key: str, text: str, expected_version: int | None = None) -> None:
    """תיקון מהמסך: מנורמל ומאומת לשדה (כמו בכרטיס הבדיקה). ערך לא תקין: ValueError ושום דבר לא נכתב."""
    if key not in FIELD_KEYS:
        raise ValueError(f"unknown field {key!r}")
    value = normalize_override(key, text)
    if not value:
        raise ValueError(f"invalid value for {key}")
    repo.edit_field(conn, record_id, key, value, expected_version=expected_version)


def revert_record_field(conn, record_id: int, key: str, expected_version: int | None = None) -> None:
    repo.revert_field(conn, record_id, key, expected_version=expected_version)


def filter_options(conn) -> dict:
    return {"senders": repo.list_senders(conn), "uploads": repo.list_uploads(conn), "counts": repo.status_counts(conn)}


# ---------- ייצוא מהמסד (שלב 5) ----------

def export_records(conn, flt: RecordFilter, fmt: str) -> tuple[bytes, str, str]:
    """כל הרשומות שמתאימות לסינון (לא רק העמוד המוצג) -> (תוכן, mime, שם קובץ). fmt = xlsx | csv | json."""
    if fmt not in db_export.BUILDERS:
        raise ValueError(f"unknown format {fmt!r}")
    rows, _total = query(conn, flt, limit=None)
    recs = [repo.get_record(conn, r["id"]) for r in rows]
    names = {u["id"]: u["filename"] for u in repo.list_uploads(conn)}
    mime, ext = db_export.FORMATS[fmt]
    return db_export.BUILDERS[fmt](recs, names), mime, f"records.{ext}"


def confirmed_value(conn, upload_id: int, page: int, okey: str) -> str | None:
    """הערך שכבר אושר ושמור במסד לתא של הממשק (לפי עמוד / שורת התחייבות), או None אם התא לא מאושר. שדה ברמת עמוד עם כמה שורות:
    מאושר רק כשכל השורות אושרו לאותו ערך. משמש לנעילת כפתור האישור כשהטקסט שהוקלד זהה לערך השמור."""
    field, recs = _targets(conn, upload_id, page, okey)
    values = set()
    for r in recs:
        full = repo.get_record(conn, r["id"])
        if not full["fields"][field]["cell_confirmed"]:
            return None
        values.add(full["center"] if field == "center" else full[repo.FIELD_COLUMN[field]])
    return values.pop() if len(values) == 1 else None
