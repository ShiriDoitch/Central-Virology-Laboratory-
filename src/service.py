"""שכבת שירות בין הצינור / הממשק לבין src/repo.py: ממירה שורות ייצוא (ExportRow) לרשומות מסד נתונים ובחזרה.
אין כאן SQL ואין Streamlit. כל כשל כתיבה נרשם בשרת (בלי PII) ולא מפיל עיבוד שכבר רץ."""
import hashlib

from . import repo
from .export import FIELD_KEYS, NAME_KEYS, Cell, build_rows
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
