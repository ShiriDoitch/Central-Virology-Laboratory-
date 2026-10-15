"""ייצוא לאקסל. שורה אחת לכל התחייבות; תא עם דגל כתום; גיליונות: ראשי, audit, סיכום, דולגו.
הגנה מנוסחאות: ערך שמתחיל ב-= + - @ מקבל גרש בהתחלה (בכל הגיליונות)."""
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .assemble import page_rows
from .rules import COMMITMENT_LABEL_WORDS, F_HANDWRITTEN, H_TWO_READS, Decision, effective_date_kind, is_center_label
from .schema import PageExtraction

# (מפתח שדה, כותרת עמודה) לפי סעיף 1
COLUMNS = [
    ("first_name", "שם פרטי"),
    ("last_name", "שם משפחה"),
    ("id", 'ת"ז'),
    ("center", "מרכזי"),
    ("date", "תאריך קבלה"),
    ("sender", "גורם שולח"),
    ("commitment", "מס' התחייבות"),
]
FIELD_KEYS = [k for k, _ in COLUMNS]
ORANGE = PatternFill("solid", fgColor="FFB366")
GREEN = PatternFill("solid", fgColor="C6EFCE")      # ערך בלי דגל
YELLOW = PatternFill("solid", fgColor="FFF2CC")     # ערך שהדגל היחיד שלו handwritten: מבט לאישור (לא כתום, לא ירוק)
CONFIRMED = PatternFill("solid", fgColor="BDD7EE")  # שם שהמשתמש הקליד או בחר (אושר ידנית): לא כתום, לא ירוק
NAME_KEYS = ("first_name", "last_name")             # שמות: כלל התצוגה display_name_cell חל עליהם גם בלי אישור
COMMITMENT_ROW_KEY = "commitment#{}"                # אישור התחייבות הוא לפי שורה (לעמוד כמה התחייבויות); שאר השדות לפי עמוד
CONFIRMED_FLAG = "confirmed_by_user"
NOT_READ_NOTE = "לא נקרא, יש להקליד"
YELLOW_NOTE = "נקרא בכתב יד בשתי קריאות עצמאיות שמסכימות, מספיק מבט לאישור"
HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")
TEXT_KEYS = {"id", "center", "commitment"}      # עמודות שנכתבות כטקסט (number_format "@"): אפס מוביל לא נעלם באקסל
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def protect(value):
    """הגנה מהזרקת נוסחאות: מחרוזת שמתחילה ב-= + - @ מקבלת גרש בהתחלה."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


@dataclass
class Cell:
    value: str | None = None
    raw: str | None = None
    flags: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    confirmed: bool = False          # הערך הוקלד/נבחר על ידי המשתמש
    original: str | None = None      # מה שהמערכת הציעה לפני האישור (להערה ול-audit)

    @property
    def yellow(self) -> bool:
        """ערך שהדגל היחיד שלו handwritten ושקיימות לו שתי קריאות עצמאיות מסכימות (רמז two_readings_agree: רק ת"ז ושמות,
        מעבר ראשון + מעבר שני), שלא אושר ידנית: מבט לאישור. שדה שנקרא במעבר אחד (תאריך, מרכזי...) לעולם אינו צהוב."""
        return bool(self.value) and self.flags == [F_HANDWRITTEN] and H_TWO_READS in self.hints and not self.confirmed

    @property
    def orange(self) -> bool:
        return bool(self.flags) and not self.confirmed and not self.yellow

    @property
    def shown(self) -> str:
        """הערך; בתא ריק מסומן: ה-raw אם קיים."""
        if self.value:
            return self.value
        return self.raw if (self.flags and self.raw) else ""


@dataclass
class ExportRow:
    page: int
    cells: dict[str, Cell]
    index: int = 0       # מספר השורה בתוך העמוד (לאישור התחייבות לפי שורה)


def _from_decision(d: Decision) -> Cell:
    return Cell(d.value, d.raw, list(d.flags), list(d.hints), list(d.alternatives))


def _dedupe_keep(items: list[str]) -> list[str]:
    return list(dict.fromkeys(x for x in items if x))


def display_name_cell(cell: Cell) -> Cell:
    """כלל התצוגה והייצוא של שם שלא אושר על ידי המשתמש (rules.py ו-evaluate.py לא משתנים):
    - שם בלי דגל (מודפס, ברור): נשאר ירוק.
    - ערך שהדגל היחיד שלו הוא "handwritten" ויש לו שתי קריאות עצמאיות מסכימות (רמז two_readings_agree): מוצג בתא, צהוב
      (Cell.yellow), לעולם לא ירוק. ערך עם הדגל הזה בלי הרמז (קריאה אחת) מוצג ריק וכתום, כמו כל דגל אחר.
    - כל ערך עם דגל אחר (region_not_ok, father_name, name_label_unknown, name_label_missing, handwritten_unconfirmed,
      conflict, low_confidence ...): התא ריק וכתום.
    - הצעות (alternatives, ולכן גם הלחצנים והטקסט בהערה): רק כששתי קריאות עצמאיות מסכימות (two_readings_agree). קריאה
      בודדת של כתב יד לא קריא היא רעש, ולכן אינה מוצגת כהצעה: התא ריק וכתום, בלי הצעות ("לא נקרא, יש להקליד")."""
    agree = H_TWO_READS in cell.hints
    alternatives = list(cell.alternatives) if agree else []
    if cell.value and (not cell.flags or (set(cell.flags) == {F_HANDWRITTEN} and agree)):
        return replace(cell, alternatives=alternatives)
    return Cell(None, None, list(cell.flags), list(cell.hints), _dedupe_keep([cell.value, *alternatives]) if agree else [])


def build_rows(page_result: dict, overrides: dict | None = None) -> list[ExportRow]:
    """שורות ייצוא לעמוד: {"page", "pass1", "pass2"(אופציונלי)}.
    overrides = {(עמוד, שדה): ערך שהמשתמש הקליד או בחר}; שדה = אחד מ-FIELD_KEYS, או "commitment#<שורה>" להתחייבות. ערך כזה
    הוא הערך הסופי של התא, מסומן כמאושר (כחול, לא כתום); ערך ריק לא נחשב. בלי אישור משתמש, שם בכתב יד לא נהיה ירוק
    על סמך המודל לבדו."""
    rows = page_rows(page_result["pass1"], regions=page_result.get("pass2"), barcodes=page_result.get("barcodes"))
    out = []
    for row_index, r in enumerate(rows):
        cells = {k: _from_decision(r[k]) for k in FIELD_KEYS if k != "commitment"}
        for k in FIELD_KEYS:
            if k in NAME_KEYS or k == "commitment":
                continue
            typed = ((overrides or {}).get((page_result["page"], k)) or "").strip()
            if typed:       # שדה שאינו שם: ההצעה המקורית נשמרת להערה
                old = cells[k]
                cells[k] = Cell(typed, typed, [], [], list(old.alternatives), confirmed=True, original=old.value or old.raw)
        for k in NAME_KEYS:
            typed = ((overrides or {}).get((page_result["page"], k)) or "").strip()
            old = cells[k]
            shown = display_name_cell(old)
            if typed:       # ההצעה המקורית נשמרת רק אם שתי קריאות הסכימו עליה
                cells[k] = Cell(typed, typed, [], [], list(shown.alternatives), confirmed=True,
                                original=(old.value or old.raw) if (H_TWO_READS in old.hints or not old.flags) else None)   # ירוק או שתי קריאות
            else:
                cells[k] = shown
        cells["commitment"] = Cell(r["commitment"], r["commitment"], list(r["commitment_flags"]),
                                   alternatives=list(r.get("commitment_alternatives", [])))
        typed = ((overrides or {}).get((page_result["page"], COMMITMENT_ROW_KEY.format(row_index))) or "").strip()
        if typed:
            old = cells["commitment"]
            cells["commitment"] = Cell(typed, typed, [], [], list(old.alternatives), confirmed=True, original=old.value or old.raw)
        out.append(ExportRow(page_result["page"], cells, row_index))
    return out


def skip_reason(page_result: dict) -> str | None:
    """למה עמוד לא נכנס לגיליון הראשי (None = נכנס)."""
    r1 = page_result.get("pass1")
    if not r1:
        return "אין תוצאת חילוץ לעמוד"
    if not r1.get("ok"):
        return f"החילוץ נכשל: {r1.get('error', 'unknown')}"
    if not build_rows(page_result):
        return "המודל סימן: לא טופס התחייבות (ולא נמצא מספר התחייבות)"
    return None


# ---------- audit ----------

def _readings(key: str, r1: PageExtraction, r2: dict | None) -> tuple[str, str]:
    """הקריאות הגולמיות של שדה במעבר הראשון ובשני (טקסט לתצוגה)."""
    def nums(items, pred):
        return "; ".join(f"{n.value} [{n.label or '-'}, {n.source}]" for n in items if pred(n))

    p2_ok = bool(r2 and r2.get("ok"))
    p1 = p2 = ""
    if key in ("first_name", "last_name"):
        f = getattr(r1, key)
        p1 = f"{f.value} ({f.source}, conf {f.confidence})" if f.value else ""
        if p2_ok:
            g = r2["patient"][key]
            p2 = f"{g['value']} ({g['source']}, conf {g['confidence']}) alt={g['alternatives']}" if g["value"] else ""
    elif key == "id":
        p1 = nums(r1.id_numbers, lambda n: True)
        if p2_ok:
            g = r2["patient"]["id_number"]
            p2 = f"{g['value']} ({g['source']}) alt={g['alternatives']}" if g["value"] else ""
    elif key == "center":
        p1 = nums(r1.numbers, lambda n: is_center_label(n.label) or (not n.label and len(n.value.strip()) == 6))
        if p2_ok:
            c = r2["barcode"]["central_number"]
            items = [f"{n['value']} [{n['label'] or '-'}, {n['orientation']}]" for n in r2["barcode"]["numbers"]]
            p2 = f"central={c['value']}; " + "; ".join(items)
    elif key == "date":
        p1 = "; ".join(f"{d.value} [{d.kind}→{effective_date_kind(d)}, {d.source}, {d.evidence or '-'}]" for d in r1.dates)
        if p2_ok and (r2.get("receipt") or {}).get("region_ok"):
            g = r2["receipt"]["date"]
            c = r2["receipt"]["central_number"]
            p2 = (f"{g['value']} ({g['source']}, conf {g['confidence']}) alt={g['alternatives']}" if g["value"] else "(תאריך לא נקרא)")                 + (f"; מרכזי בחיתוך: {c['value']}" if c.get("value") else "")
    elif key == "sender":
        p1 = "; ".join(f"{m.text} [{m.where}/{m.role}]" for m in r1.sender_mentions)
    elif key == "commitment":
        p1 = nums(r1.numbers, lambda n: n.label and any(w in n.label for w in COMMITMENT_LABEL_WORDS))
        if p2_ok:
            g = (r2.get("commitment") or {})
            v = (g.get("number") or {}).get("value")
            p2 = f"{v} (region_ok={g.get('region_ok')})" if v else f"(לא נקרא; region_ok={g.get('region_ok')})"
    return p1, p2


def _rotation_text(page_result: dict) -> str | None:
    """תיאור הסיבוב לעמוד: ציר מקומי, מה שהמודל דיווח, ומה הוחל."""
    r = page_result.get("rotation")
    if not r:
        return None
    applied = f"סובב {r['applied']}°" if r.get("applied") else "לא סובב"
    return f"ציר מקומי: {r.get('local_axis')}; דיווח המודל: {r.get('reported')}; {applied}"


def _pass2_status(page_result: dict) -> str:
    r2 = page_result.get("pass2")
    status = page_result.get("second_pass")
    if status == "skipped":
        return "דולג: " + ", ".join(page_result.get("reasons") or [])
    if status == "daily_quota_exhausted":
        return "מכסה יומית נגמרה"
    if r2 is None:
        return "לא רץ"
    if not r2.get("ok"):
        return "נכשל"
    return "רץ בגיבוי (מודל חלש)" if page_result.get("pass2_fallback") else "רץ"


def pass2_issues(pages: list[dict]) -> dict[str, list[int]]:
    """עמודים שהמעבר השני בהם לא רץ במודל המועדף: fallback = ענה מודל הגיבוי (החלש), quota = דולג כי נגמרה המכסה היומית
    (אף מודל לא ענה), failed = נכשל מסיבה אחרת. לאזהרה בולטת במסך התוצאות."""
    out: dict[str, list[int]] = {"fallback": [], "quota": [], "failed": []}
    for p in sorted(pages, key=lambda x: x["page"]):
        if p.get("pass2_fallback"):
            out["fallback"].append(p["page"])
        elif p.get("second_pass") == "daily_quota_exhausted":
            out["quota"].append(p["page"])
        elif p.get("second_pass") == "failed":
            out["failed"].append(p["page"])
    return out


# ---------- סיכום ----------

def summarize(pages: list[dict], rows: list[ExportRow], skipped: list[tuple[int, str]]) -> dict:
    by_field = {k: Counter() for k in FIELD_KEYS}
    flags: Counter = Counter()
    for row in rows:
        for k, c in row.cells.items():
            if c.confirmed:
                kind = "confirmed"
            elif c.yellow:
                kind = "yellow"
            elif c.value and not c.flags:
                kind = "green"
            elif c.value:
                kind = "orange"
            elif c.flags:
                kind = "empty_flagged"
            else:
                kind = "empty"
            by_field[k][kind] += 1
            flags.update(c.flags)
    total = Counter()
    for c in by_field.values():
        total.update(c)
    second = Counter()
    api = Counter()
    for p in pages:
        flags.update(p.get("page_flags") or [])              # דגלי עמוד (למשל rotation_unresolved)
        second[_pass2_status(p).split(":")[0]] += 1
        for s in (p.get("stats") or {}).values():
            api.update(s or {})
    return {"pages": len(pages), "rows": len(rows), "skipped": len(skipped), "fields_total": len(rows) * len(FIELD_KEYS),
            "totals": dict(total), "by_field": {k: dict(v) for k, v in by_field.items()}, "flags": dict(flags),
            "second_pass": dict(second), "api": dict(api)}


# ---------- כתיבת האקסל ----------

def _put(ws, row: int, col: int, value, bold=False, fill=None, wrap=False):
    c = ws.cell(row=row, column=col, value=protect(value))
    if bold:
        c.font = Font(bold=True)
    if fill:
        c.fill = fill
    if wrap:
        c.alignment = Alignment(wrap_text=True, vertical="top")
    return c


def _header(ws, titles: list[str], widths: list[int]):
    for i, (t, w) in enumerate(zip(titles, widths), start=1):
        _put(ws, 1, i, t, bold=True, fill=HEADER_FILL)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def build_workbook(pages: list[dict], overrides: dict | None = None) -> tuple[Workbook, dict]:
    """pages = [{"page": n, "pass1": r1, "pass2": r2|None, "second_pass": ..., "reasons": [...], "stats": {...}}].
    overrides = אישורי משתמש לשמות (ראו build_rows)."""
    pages = sorted(pages, key=lambda p: p["page"])
    wb = Workbook()
    main = wb.active
    main.title = "תוצאות"
    main.sheet_view.rightToLeft = True
    _header(main, [t for _, t in COLUMNS], [16, 18, 16, 22, 16, 30, 20])

    audit = wb.create_sheet("audit")
    _header(audit, ["שורה בגיליון", "עמוד", "שדה", "ערך סופי", "raw", "דגלים", "רמזים", "חלופות", "מעבר ראשון: מודל",
                    "מעבר ראשון: קריאות", "מעבר שני: סטטוס", "מעבר שני: מודל", "מעבר שני: קריאות", "סיבוב", "דגלי עמוד"],
            [10, 8, 14, 22, 18, 28, 22, 22, 22, 60, 26, 20, 60, 28, 22])

    rows: list[ExportRow] = []
    skipped: list[tuple[int, str]] = []
    out_row = audit_row = 1
    for p in pages:
        reason = skip_reason(p)
        if reason:
            skipped.append((p["page"], reason))
            continue
        r1 = PageExtraction.model_validate(p["pass1"])
        r2 = p.get("pass2")
        for er in build_rows(p, overrides):
            rows.append(er)
            out_row += 1
            for col, (key, _title) in enumerate(COLUMNS, start=1):
                cell = er.cells[key]
                fill = (CONFIRMED if cell.confirmed else YELLOW if cell.yellow else ORANGE if cell.orange
                        else (GREEN if cell.value else None))  # ריק בלי דגל: לבן
                x = _put(main, out_row, col, cell.shown or None, fill=fill)
                if key in TEXT_KEYS:
                    x.number_format = "@"
                if cell.confirmed:
                    note = "אושר על ידי המשתמש" + (f"\nהצעת המערכת: {cell.original}" if cell.original else "")
                    if cell.alternatives:
                        note += f"\nחלופות: {' | '.join(cell.alternatives)}"
                    x.comment = Comment(note, "system", width=260, height=90)
                elif cell.yellow:
                    note = YELLOW_NOTE
                    if cell.alternatives:
                        note += f"\nחלופות: {' | '.join(cell.alternatives)}"
                    x.comment = Comment(note, "system", width=260, height=90)
                elif cell.orange:
                    note = f"דגלים: {', '.join(cell.flags)}"
                    if key in NAME_KEYS and not cell.value and not cell.alternatives:
                        note = NOT_READ_NOTE + "\n" + note
                    if cell.alternatives:
                        note += f"\nחלופות: {' | '.join(cell.alternatives)}"
                    if not cell.value and cell.raw:
                        note += f"\nraw: {cell.raw}"
                    x.comment = Comment(note, "system", width=260, height=90)
                audit_row += 1
                p1, p2 = _readings(key, r1, r2)
                values = [out_row, p["page"], key, cell.value, cell.raw, CONFIRMED_FLAG if cell.confirmed else ", ".join(cell.flags), ", ".join(cell.hints),
                          " | ".join(cell.alternatives), p["pass1"].get("model"), p1, _pass2_status(p),
                          (r2 or {}).get("model") if r2 and r2.get("ok") else None, p2,
                          _rotation_text(p), ", ".join(p.get("page_flags") or [])]
                for c_i, v in enumerate(values, start=1):
                    _put(audit, audit_row, c_i, v, fill=CONFIRMED if (c_i == 4 and cell.confirmed) else (YELLOW if (c_i == 4 and cell.yellow) else (ORANGE if (c_i == 4 and cell.orange) else None)))

    summary = summarize(pages, rows, skipped)
    _write_summary(wb.create_sheet("סיכום"), summary)
    _write_skipped(wb.create_sheet("דולגו"), skipped)
    return wb, summary


def _write_summary(ws, s: dict) -> None:
    ws.sheet_view.rightToLeft = True
    ws.column_dimensions["A"].width = 34
    for col in "BCDEF":
        ws.column_dimensions[col].width = 16
    ws.column_dimensions["B"].width = 60
    _put(ws, 1, 1, "מקרא (גיליון תוצאות)", bold=True, fill=HEADER_FILL)
    _put(ws, 1, 2, None, fill=HEADER_FILL)
    for i, (fill, text) in enumerate([(GREEN, "ירוק בהיר: ערך בלי דגל"),
                                      (ORANGE, "כתום: דגל לבדיקה (ערך, או תא ריק מסומן; הדגלים בהערת התא)"),
                                      (None, "לבן: תא ריק בלי דגל (לא נמצא)"),
                                      (CONFIRMED, "כחול: ערך שאושר על ידי המשתמש (הוקלד או נבחר)"),
                                      (YELLOW, "צהוב בהיר: ת\"ז או שם שנקראו בכתב יד בשתי קריאות עצמאיות שמסכימות, מספיק מבט לאישור")], start=2):
        _put(ws, i, 1, None, fill=fill)
        _put(ws, i, 2, text)
    r = 8
    for label, value in [("עמודים שנבדקו", s["pages"]), ("שורות (התחייבויות)", s["rows"]), ("עמודים שדולגו", s["skipped"]),
                         ("שדות בסך הכול", s["fields_total"]), ("שדות ירוקים (ערך, בלי דגל)", s["totals"].get("green", 0)),
                         ("שדות שאושרו על ידי המשתמש", s["totals"].get("confirmed", 0)),
                         ("שדות צהובים (ת\"ז / שם בכתב יד, שתי קריאות מסכימות)", s["totals"].get("yellow", 0)),
                         ("שדות כתומים (ערך עם דגל)", s["totals"].get("orange", 0)),
                         ("שדות ריקים, מסומנים לבדיקה", s["totals"].get("empty_flagged", 0)),
                         ("שדות ריקים (בלי דגל)", s["totals"].get("empty", 0))]:
        _put(ws, r, 1, label, bold=True)
        _put(ws, r, 2, value)
        r += 1
    r += 1
    for i, t in enumerate(["שדה", "ירוק", "כתום", "ריק מסומן", "ריק", "מאושר ע\"י משתמש", "צהוב"], start=1):
        _put(ws, r, i, t, bold=True, fill=HEADER_FILL)
    for key, title in COLUMNS:
        r += 1
        b = s["by_field"][key]
        for i, v in enumerate([title, b.get("green", 0), b.get("orange", 0), b.get("empty_flagged", 0), b.get("empty", 0),
                               b.get("confirmed", 0), b.get("yellow", 0)], start=1):
            _put(ws, r, i, v)
    r += 2
    _put(ws, r, 1, "שכיחות דגלים", bold=True, fill=HEADER_FILL)
    _put(ws, r, 2, "מספר", bold=True, fill=HEADER_FILL)
    for flag, n in sorted(s["flags"].items(), key=lambda x: -x[1]):
        r += 1
        _put(ws, r, 1, flag)
        _put(ws, r, 2, n)
    r += 2
    _put(ws, r, 1, "מעבר שני", bold=True, fill=HEADER_FILL)
    _put(ws, r, 2, "עמודים", bold=True, fill=HEADER_FILL)
    for status, n in s["second_pass"].items():
        r += 1
        _put(ws, r, 1, status)
        _put(ws, r, 2, n)
    if s["api"]:
        r += 2
        _put(ws, r, 1, "קריאות API", bold=True, fill=HEADER_FILL)
        _put(ws, r, 2, "מספר", bold=True, fill=HEADER_FILL)
        for name, n in s["api"].items():
            if not name.startswith("calls:"):
                r += 1
                _put(ws, r, 1, name)
                _put(ws, r, 2, n)
        if s["pages"]:
            r += 1
            _put(ws, r, 1, "קריאות API לעמוד (ממוצע)")
            _put(ws, r, 2, round(s["api"].get("api_calls", 0) / s["pages"], 2))


def _write_skipped(ws, skipped: list[tuple[int, str]]) -> None:
    ws.sheet_view.rightToLeft = True
    _header(ws, ["עמוד", "סיבה"], [8, 70])
    for i, (page, reason) in enumerate(skipped, start=2):
        _put(ws, i, 1, page)
        _put(ws, i, 2, reason)


def export_excel(pages: list[dict], path: str | Path, overrides: dict | None = None) -> dict:
    """כותב את האקסל ל-path ומחזיר את נתוני הסיכום. overrides = אישורי משתמש לשמות."""
    wb, summary = build_workbook(pages, overrides)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return summary
