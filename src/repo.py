"""שכבת הנתונים (SQLite, ספרייה סטנדרטית). כל ה-SQL של המערכת נמצא כאן; app.py ושאר המודולים קוראים לפונקציות בלבד.

ערך סופי של שדה נשמר בעמודות של records (ומרכזי ב-record_centers); מה שהמערכת קראה, הצבע והדגלים נשמרים ב-field_states.
סטטוס: pending (יש תא כתום / צהוב / ריק) | ready (כל התאים ירוקים או מאושרים) | approved (אושר ידנית; לא נדרס בעיבוד חוזר).
כל שינוי נרשם ב-audit_log. הדגלים נשמרים כקודים (מחרוזות מ-rules.py)."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"
FIELDS = ("first_name", "last_name", "id", "center", "date", "sender", "commitment")
# שדה -> עמודה ב-records (מרכזי יושב בטבלה נפרדת)
FIELD_COLUMN = {"first_name": "first_name", "last_name": "last_name", "id": "national_id", "date": "receipt_date",
                "sender": "sender", "commitment": "commitment_no"}
CENTER_SEP = " ; "
STATUSES = ("pending", "ready", "approved")
OK_COLORS = ("green", "confirmed")          # צבעים שלא דורשים בדיקה אנושית

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    page_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    commitment_no TEXT,
    first_name TEXT,
    last_name TEXT,
    national_id TEXT,
    receipt_date TEXT,
    sender TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'approved')),
    version INTEGER NOT NULL DEFAULT 1,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (upload_id, page_no, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_records_status ON records(status);
CREATE INDEX IF NOT EXISTS idx_records_upload ON records(upload_id);
CREATE TABLE IF NOT EXISTS record_centers (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    center_no TEXT NOT NULL,
    PRIMARY KEY (record_id, position)
);
CREATE INDEX IF NOT EXISTS idx_centers_no ON record_centers(center_no);
CREATE TABLE IF NOT EXISTS field_states (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    machine_value TEXT,
    color TEXT NOT NULL,
    flags_json TEXT NOT NULL DEFAULT '[]',
    alternatives_json TEXT NOT NULL DEFAULT '[]',
    human_edited INTEGER NOT NULL DEFAULT 0,
    cell_confirmed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (record_id, field)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER,
    field TEXT,
    action TEXT NOT NULL,
    old TEXT,
    new TEXT,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_record ON audit_log(record_id);
"""


class RecordLocked(Exception):
    """ניסיון לשנות רשומה מאושרת (קודם צריך לבטל אישור)."""


class StaleVersion(Exception):
    """הרשומה השתנתה מאז שנטענה (expected_version לא תואם)."""


def db_path() -> Path:
    return Path(os.getenv("APP_DB_PATH") or DEFAULT_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """פותח חיבור (ויוצר את הקובץ והסכמה אם חסרים). path=":memory:" לבדיקות."""
    path = str(path) if path is not None else str(db_path())
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _audit(conn, record_id, field, action, old=None, new=None) -> None:
    conn.execute("INSERT INTO audit_log (record_id, field, action, old, new, at) VALUES (?,?,?,?,?,?)",
                 (record_id, field, action, old, new, _now()))


# ---------- uploads ----------

def find_upload(conn, sha256: str) -> dict | None:
    row = conn.execute("SELECT * FROM uploads WHERE sha256 = ?", (sha256,)).fetchone()
    return dict(row) if row else None


def create_upload(conn, filename: str, sha256: str, page_count: int) -> int:
    with conn:
        cur = conn.execute("INSERT INTO uploads (filename, sha256, page_count, created_at) VALUES (?,?,?,?)",
                           (filename, sha256, page_count, _now()))
    return cur.lastrowid


def complete_upload(conn, upload_id: int) -> None:
    with conn:
        conn.execute("UPDATE uploads SET completed_at = ? WHERE id = ?", (_now(), upload_id))


def list_uploads(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT u.*, (SELECT COUNT(*) FROM records r WHERE r.upload_id = u.id) AS record_count "
        "FROM uploads u ORDER BY u.id DESC")]


# ---------- כתיבת תוצאות מכונה ----------

def derive_status(colors) -> str:
    """ready רק כשכל התאים ירוקים או מאושרים; אחרת pending. (approved נקבע ידנית בלבד.)"""
    return "ready" if all(c in OK_COLORS for c in colors) else "pending"


def _split_centers(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(";") if p.strip()]


def _write_final(conn, record_id: int, field: str, value: str | None) -> None:
    if field == "center":
        conn.execute("DELETE FROM record_centers WHERE record_id = ?", (record_id,))
        conn.executemany("INSERT INTO record_centers (record_id, position, center_no) VALUES (?,?,?)",
                         [(record_id, i, c) for i, c in enumerate(_split_centers(value))])
    else:
        conn.execute(f"UPDATE records SET {FIELD_COLUMN[field]} = ? WHERE id = ?", (value or None, record_id))


def _final_value(conn, record_id: int, field: str) -> str | None:
    if field == "center":
        rows = conn.execute("SELECT center_no FROM record_centers WHERE record_id = ? ORDER BY position", (record_id,))
        return CENTER_SEP.join(r[0] for r in rows) or None
    return conn.execute(f"SELECT {FIELD_COLUMN[field]} FROM records WHERE id = ?", (record_id,)).fetchone()[0]


def _recompute_status(conn, record_id: int) -> str:
    colors = [r[0] for r in conn.execute("SELECT color FROM field_states WHERE record_id = ?", (record_id,))]
    return derive_status(colors)


def save_machine_record(conn, upload_id: int, page_no: int, ordinal: int, fields: dict[str, dict]) -> tuple[int, str]:
    """שומר (או מעדכן) רשומה שהמערכת חילצה. fields[שדה] = {"value", "color", "flags", "alternatives"}.
    רשומה חדשה: נוצרת. קיימת מאושרת: לא נוגעים ("skipped_approved"). קיימת אחרת: ערכי המכונה מתעדכנים, אבל תא שהמשתמש
    אישר או תיקן (cell_confirmed) שומר את הערך והצבע שלו. מחזיר (record_id, "created" | "updated" | "skipped_approved")."""
    with conn:
        row = conn.execute("SELECT id, status FROM records WHERE upload_id=? AND page_no=? AND ordinal=?",
                           (upload_id, page_no, ordinal)).fetchone()
        now = _now()
        if row is None:
            cur = conn.execute("INSERT INTO records (upload_id, page_no, ordinal, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                               (upload_id, page_no, ordinal, "pending", now, now))
            rid, outcome = cur.lastrowid, "created"
            _audit(conn, rid, None, "create")
        else:
            rid, outcome = row["id"], "updated"
            if row["status"] == "approved":
                return rid, "skipped_approved"
        for field in FIELDS:
            f = fields[field]
            old = conn.execute("SELECT * FROM field_states WHERE record_id=? AND field=?", (rid, field)).fetchone()
            kept = bool(old and old["cell_confirmed"])                      # תיקון / אישור אנושי לא נדרס
            conn.execute(
                "INSERT INTO field_states (record_id, field, machine_value, color, flags_json, alternatives_json, human_edited, cell_confirmed) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(record_id, field) DO UPDATE SET machine_value=excluded.machine_value, "
                "flags_json=excluded.flags_json, alternatives_json=excluded.alternatives_json, "
                "color=CASE WHEN field_states.cell_confirmed THEN field_states.color ELSE excluded.color END",
                (rid, field, f.get("value"), f["color"], json.dumps(f.get("flags") or [], ensure_ascii=False),
                 json.dumps(f.get("alternatives") or [], ensure_ascii=False), 0, 0))
            if not kept:
                prev = _final_value(conn, rid, field) if old else None
                _write_final(conn, rid, field, f.get("value"))
                if old and prev != (f.get("value") or None):
                    _audit(conn, rid, field, "machine_update", prev, f.get("value"))
        status = _recompute_status(conn, rid)
        conn.execute("UPDATE records SET status=?, version=version+1, updated_at=? WHERE id=?", (status, now, rid))
    return rid, outcome


def prune_page_records(conn, upload_id: int, page_no: int, keep_ordinals: int) -> int:
    """אחרי עיבוד חוזר של עמוד: מוחק רשומות עודפות (ordinal >= keep_ordinals) שאינן מאושרות ובלי תיקון אנושי. מחזיר כמה נמחקו."""
    deleted = 0
    with conn:
        rows = conn.execute("SELECT id, status FROM records WHERE upload_id=? AND page_no=? AND ordinal>=?",
                            (upload_id, page_no, keep_ordinals)).fetchall()
        for r in rows:
            touched = conn.execute("SELECT 1 FROM field_states WHERE record_id=? AND cell_confirmed=1", (r["id"],)).fetchone()
            if r["status"] != "approved" and not touched:
                conn.execute("DELETE FROM records WHERE id=?", (r["id"],))
                _audit(conn, r["id"], None, "delete")
                deleted += 1
    return deleted


# ---------- תיקון ואישור ----------

def _load(conn, record_id: int, expected_version: int | None):
    rec = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    if rec is None:
        raise KeyError(f"record {record_id} not found")
    if rec["status"] == "approved":
        raise RecordLocked(f"record {record_id} is approved")
    if expected_version is not None and rec["version"] != expected_version:
        raise StaleVersion(f"record {record_id} changed (version {rec['version']}, expected {expected_version})")
    return rec


def _touch(conn, record_id: int) -> None:
    conn.execute("UPDATE records SET status=?, version=version+1, updated_at=? WHERE id=?",
                 (_recompute_status(conn, record_id), _now(), record_id))


def edit_field(conn, record_id: int, field: str, value: str, *, expected_version: int | None = None) -> None:
    """הערך שהמשתמש הקליד או בחר: ערך סופי, מאושר (צבע confirmed). ערך זהה להצעת המכונה = אישור בלבד (human_edited=0)."""
    if field not in FIELDS:
        raise ValueError(f"unknown field {field!r}")
    value = (value or "").strip()
    if not value:
        raise ValueError("empty value; use revert_field")
    with conn:
        st0 = conn.execute("SELECT cell_confirmed FROM field_states WHERE record_id=? AND field=?", (record_id, field)).fetchone()
        if st0 and st0["cell_confirmed"] and _final_value(conn, record_id, field) == value:
            return                      # אישור חוזר של אותו ערך (לחיצה כפולה): בלי גרסה חדשה, בלי audit, בלי שגיאה (גם אם הגרסה התיישנה)
        _load(conn, record_id, expected_version)
        st = conn.execute("SELECT machine_value FROM field_states WHERE record_id=? AND field=?", (record_id, field)).fetchone()
        old = _final_value(conn, record_id, field)
        edited = int(value != (st["machine_value"] or ""))
        _write_final(conn, record_id, field, value)
        conn.execute("UPDATE field_states SET human_edited=?, cell_confirmed=1, color='confirmed' WHERE record_id=? AND field=?",
                     (edited, record_id, field))
        _audit(conn, record_id, field, "edit" if edited else "confirm", old, value)
        _touch(conn, record_id)


def revert_field(conn, record_id: int, field: str, *, color: str | None = None, expected_version: int | None = None) -> None:
    """ביטול אישור / תיקון: חוזרים לערך המכונה. color = הצבע שהמכונה נתנה (הקורא שמחשב אותו מתוצאת העמוד מעביר אותו; בלעדיו
    הצבע נגזר מהדגלים והערך השמורים: דגל = orange, ערך = green, אחרת empty; צהוב אינו ניתן לשחזור מכאן)."""
    with conn:
        _load(conn, record_id, expected_version)
        st = conn.execute("SELECT machine_value, flags_json FROM field_states WHERE record_id=? AND field=?", (record_id, field)).fetchone()
        if color is None:
            color = "orange" if json.loads(st["flags_json"]) else ("green" if st["machine_value"] else "empty")
        old = _final_value(conn, record_id, field)
        _write_final(conn, record_id, field, st["machine_value"])
        conn.execute("UPDATE field_states SET human_edited=0, cell_confirmed=0, color=? WHERE record_id=? AND field=?",
                     (color, record_id, field))
        _audit(conn, record_id, field, "revert", old, st["machine_value"])
        _touch(conn, record_id)


def approve_record(conn, record_id: int, *, expected_version: int | None = None) -> None:
    with conn:
        rec = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if rec is None:
            raise KeyError(f"record {record_id} not found")
        if expected_version is not None and rec["version"] != expected_version:
            raise StaleVersion(f"record {record_id} changed")
        if rec["status"] == "approved":
            return
        conn.execute("UPDATE records SET status='approved', reviewed_at=?, version=version+1, updated_at=? WHERE id=?",
                     (_now(), _now(), record_id))
        _audit(conn, record_id, None, "approve", rec["status"], "approved")


def unapprove_record(conn, record_id: int) -> None:
    with conn:
        rec = conn.execute("SELECT status FROM records WHERE id=?", (record_id,)).fetchone()
        if rec is None:
            raise KeyError(f"record {record_id} not found")
        if rec["status"] != "approved":
            return
        conn.execute("UPDATE records SET status=?, reviewed_at=NULL, version=version+1, updated_at=? WHERE id=?",
                     (_recompute_status(conn, record_id), _now(), record_id))
        _audit(conn, record_id, None, "unapprove", "approved", None)


# ---------- קריאה, חיפוש, סינון ----------

# תאריך dd.mm.yyyy -> yyyymmdd להשוואה בטווח
_DATE_KEY = "(substr(r.receipt_date,7,4) || substr(r.receipt_date,4,2) || substr(r.receipt_date,1,2))"
SORT_COLUMNS = {"upload": "u.created_at", "id": "r.id", "page": ("r.upload_id", "r.page_no", "r.ordinal"), "first_name": "r.first_name", "last_name": "r.last_name",
                "national_id": "r.national_id", "date": _DATE_KEY, "sender": "r.sender", "commitment": "r.commitment_no",
                "status": "r.status", "updated": "r.updated_at"}


def _where(search: str | None, statuses, senders, date_from: str | None, date_to: str | None, upload_id: int | None,
           uploaded_from: str | None = None, uploaded_before: str | None = None):
    """date_from / date_to בפורמט dd.mm.yyyy (כולל). uploaded_from (כולל) / uploaded_before (לא כולל): חותמות זמן ISO ב-UTC
    של שעת ההעלאה (uploads.created_at); ההמרה מתאריכים מקומיים נעשית בשכבת השירות."""
    where, args = [], []
    if uploaded_from:
        where.append("u.created_at >= ?")
        args.append(uploaded_from)
    if uploaded_before:
        where.append("u.created_at < ?")
        args.append(uploaded_before)
    if upload_id is not None:
        where.append("r.upload_id = ?")
        args.append(upload_id)
    if statuses:
        where.append(f"r.status IN ({','.join('?' * len(statuses))})")
        args += list(statuses)
    if senders:
        where.append(f"r.sender IN ({','.join('?' * len(senders))})")
        args += list(senders)

    def key(d):
        return d[6:10] + d[3:5] + d[0:2]
    if date_from:
        where.append(f"{_DATE_KEY} >= ?")
        args.append(key(date_from))
    if date_to:
        where.append(f"{_DATE_KEY} <= ?")
        args.append(key(date_to))
    if search and search.strip():
        like = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(r.first_name LIKE ? ESCAPE '\\' OR r.last_name LIKE ? ESCAPE '\\' OR (r.first_name || ' ' || r.last_name) LIKE ? ESCAPE '\\' "
                     "OR r.national_id LIKE ? ESCAPE '\\' OR r.commitment_no LIKE ? ESCAPE '\\' "
                     "OR EXISTS (SELECT 1 FROM record_centers c WHERE c.record_id = r.id AND c.center_no LIKE ? ESCAPE '\\'))")
        args += [like] * 6
    return (" WHERE " + " AND ".join(where)) if where else "", args


def _hydrate(conn, rows) -> list[dict]:
    out = []
    for r in rows:
        d = dict(r)
        d["center"] = _final_value(conn, d["id"], "center")
        out.append(d)
    return out


def search_records(conn, *, search: str | None = None, statuses=None, senders=None, date_from: str | None = None,
                   date_to: str | None = None, upload_id: int | None = None, sort: str = "page", descending: bool = False,
                   limit: int | None = 50, offset: int = 0, uploaded_from: str | None = None,
                   uploaded_before: str | None = None) -> tuple[list[dict], int]:
    """מחזיר (שורות העמוד, סך כל ההתאמות). limit=None = הכול (לייצוא)."""
    where, args = _where(search, statuses, senders, date_from, date_to, upload_id, uploaded_from, uploaded_before)
    total = conn.execute(f"SELECT COUNT(*) FROM records r JOIN uploads u ON u.id = r.upload_id{where}", args).fetchone()[0]
    order = SORT_COLUMNS.get(sort, SORT_COLUMNS["page"])
    order = (order,) if isinstance(order, str) else order
    direction = "DESC" if descending else "ASC"
    order_sql = ", ".join(f"{c} {direction}" for c in order) + f", r.id {direction}"
    sql = (f"SELECT r.*, u.created_at AS upload_at, u.filename AS upload_filename FROM records r "
           f"JOIN uploads u ON u.id = r.upload_id{where} ORDER BY {order_sql}")
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        args = [*args, int(limit), int(offset)]
    return _hydrate(conn, conn.execute(sql, args).fetchall()), total


def get_record(conn, record_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    if row is None:
        return None
    d = _hydrate(conn, [row])[0]
    d["fields"] = {r["field"]: {"machine_value": r["machine_value"], "color": r["color"], "flags": json.loads(r["flags_json"]),
                                "alternatives": json.loads(r["alternatives_json"]), "human_edited": bool(r["human_edited"]),
                                "cell_confirmed": bool(r["cell_confirmed"])}
                   for r in conn.execute("SELECT * FROM field_states WHERE record_id=?", (record_id,))}
    return d


def find_record(conn, upload_id: int, page_no: int, ordinal: int) -> int | None:
    row = conn.execute("SELECT id FROM records WHERE upload_id=? AND page_no=? AND ordinal=?", (upload_id, page_no, ordinal)).fetchone()
    return row[0] if row else None


def page_records(conn, upload_id: int, page_no: int) -> list[dict]:
    return _hydrate(conn, conn.execute("SELECT * FROM records WHERE upload_id=? AND page_no=? ORDER BY ordinal", (upload_id, page_no)))


def list_senders(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT sender FROM records WHERE sender IS NOT NULL AND sender != '' ORDER BY sender")]


def status_counts(conn, upload_id: int | None = None) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    q, args = "SELECT status, COUNT(*) FROM records", []
    if upload_id is not None:
        q, args = q + " WHERE upload_id = ?", [upload_id]
    for status, n in conn.execute(q + " GROUP BY status", args):
        out[status] = n
    return out


def audit_entries(conn, record_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM audit_log WHERE record_id=? ORDER BY id", (record_id,))]
