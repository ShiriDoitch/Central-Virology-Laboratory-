"""מדידה על סט הערכה נוסף וקטן: data/eval_extra/forms.pdf (6 עמודים), מול טבלת אמת ידנית ב-CSV.

מדידה בלבד. אין לשנות שום כלל, סף או קובץ הגדרות בעקבות הסט הזה (CLAUDE.md סעיף 9: כיוונון על חלק 1 בלבד).
הסט הזה אינו חלק 2 ואינו נוגע בו.

שימוש:
    python scripts/eval_extra.py                 # דוח בלבד, בלי אף קריאה למודל (מהתשובות השמורות ב-outputs/eval_extra)
    python scripts/eval_extra.py --run           # מריץ את הצינור על 6 העמודים (קורא ל-API! רק באישור)
    python scripts/eval_extra.py --truth=<path>  # קובץ אמת אחר
מטמון: במצב dev (ברירת המחדל) תשובות המודל נשמרות ב-data/cache, ולכן הרצה חוזרת של --run לא עולה קריאות.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import extractor                                                      # noqa: E402
from src.assemble import page_rows                                             # noqa: E402
from src.evaluate import compare_page, load_barcodes, load_run                 # noqa: E402
from src.pipeline import process_page, render_model_summary, sum_stats         # noqa: E402
from src.privacy import is_production, safe_write_text                         # noqa: E402
from src.rules import split_multi                                              # noqa: E402
from run_step2_dates import BudgetReached, BudgetTracker                       # noqa: E402

PDF = ROOT / "data" / "eval_extra" / "forms.pdf"
TRUTH = ROOT / "data" / "eval_extra" / "truth.csv"
TRUTH_TEMPLATE = ROOT / "data" / "eval_extra" / "truth_template.csv"
OUT = ROOT / "outputs" / "eval_extra"
PAGES = [1, 2, 3, 4, 5, 6]
ROTATED_PAGES = [5, 6]            # לפי המפתחת: צילומי מסך מסובבים של מסך מערכת

# תקרת קריאות קשיחה: בהגעה לתקרה הריצה נעצרת מיד ולא נשלחת אף בקשה נוספת.
LIMITS = {"gemini-3.5-flash-lite": 16, "gemini-3.1-flash-lite": 6, "gemini-3.6-flash": 14}

CSV_COLS = ["page", "first_name", "last_name", "id", "center", "receipt_date", "sender", "commitment"]
# עמודת ה-CSV -> שם השדה בקוד (receipt_date הוא "תאריך קבלת דגימה")
CSV_TO_FIELD = {"first_name": "first_name", "last_name": "last_name", "id": "id", "center": "center",
                "receipt_date": "date", "sender": "sender", "commitment": "commitment"}
MAIN_FIELDS = ["date", "center", "sender", "commitment"]
ID_FIELD = ["id"]
NAME_FIELDS = ["first_name", "last_name"]                # מדווחים בנפרד מת"ז (CLAUDE.md סעיף 16)
ALL_FIELDS = MAIN_FIELDS + ID_FIELD + NAME_FIELDS
# ארבע הקבוצות המבוקשות, מעל הקטגוריות של src/evaluate.py
BUCKETS = [("exact", ["confident_ok", "orange_ok"]), ("WRONG-GREEN", ["confident_wrong"]),
           ("wrong-orange", ["orange_wrong"]), ("empty", ["empty_ok", "empty_missed", "empty_flagged"])]
DETAIL = ["confident_ok", "confident_wrong", "orange_ok", "orange_wrong", "empty_ok", "empty_missed", "empty_flagged"]


def load_truth_csv(path: Path) -> dict[int, list[dict]]:
    """CSV ידני -> {עמוד: [שורות אמת]} בפורמט ש-compare_page מצפה לו.
    כמה מספרי התחייבות בתא אחד (מופרדים ב-;) -> שורה לכל התחייבות, עם אותם פרטי מטופל."""
    import csv
    out: dict[int, list[dict]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in CSV_COLS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
        for raw in reader:
            cells = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in raw.items()}
            if not cells.get("page"):
                continue
            page = int(cells["page"])
            base = {field: cells.get(col) for col, field in CSV_TO_FIELD.items()}
            base["check"] = None                   # אין שדות מוחרגים בסט הזה
            commitments = split_multi(base["commitment"]) or [None]
            out[page] = [{**base, "commitment": c} for c in commitments]
    return out


def truth_filled(rows: list[dict]) -> bool:
    """שורת אמת שכל התאים בה ריקים = עדיין לא מולאה ביד."""
    return any(r[f] for r in rows for f in ALL_FIELDS)


def truth_path(argv: list[str]) -> Path:
    for a in argv:
        if a.startswith("--truth="):
            return Path(a.split("=", 1)[1])
    return TRUTH if TRUTH.exists() else TRUTH_TEMPLATE


def run_pages(tracker: BudgetTracker) -> tuple[str | None, list[dict]]:
    """מריץ את הצינור הרגיל על 6 העמודים ושומר p<N>.json לכל עמוד. מחזיר (סיבת עצירה, סטטיסטיקות)."""
    OUT.mkdir(parents=True, exist_ok=True)
    stopped, stats = None, []
    try:
        for p in PAGES:
            res = process_page(str(PDF), p, debug_dir=OUT)
            safe_write_text(OUT / f"p{p}.json", json.dumps(res, ensure_ascii=False))
            stats += [res["stats"]["pass1"], res["stats"]["pass2"]]
            rot = res.get("rotation") or {}
            print(f"page {p}: pass1_ok={bool(res['pass1'].get('ok'))} second_pass={res['second_pass']} "
                  f"pass2_model={res.get('pass2_model')} rotation_applied={rot.get('applied')} "
                  f"calls={dict(tracker.count)}", flush=True)
    except BudgetReached as e:
        stopped = f"call limit {e}"
        print(f"STOPPED: {stopped}", flush=True)
    return stopped, stats


def cells(truth: dict[int, list[dict]], pages: list[int]) -> dict[int, dict | None]:
    """{עמוד: השוואה לכל שדה}. עמוד שנכשל או שאין לו ריצה: None."""
    results, regions = load_run(OUT, pages)
    barcodes = load_barcodes(OUT, pages)
    out: dict[int, dict | None] = {}
    for p in pages:
        if not results[p].get("ok"):
            out[p] = None
            continue
        rows = page_rows(results[p], regions=regions.get(p), barcodes=barcodes.get(p))
        out[p] = compare_page(truth[p], rows)
    return out


def meta(pages: list[int]) -> dict[int, dict]:
    out = {}
    for p in pages:
        f = OUT / f"p{p}.json"
        out[p] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return out


def bucket_table(cmp: dict[int, dict | None], fields: list[str], pages: list[int]) -> list[str]:
    lines = ["| field | n | " + " | ".join(name for name, _ in BUCKETS) + " |", "|---|---|" + "---|" * len(BUCKETS)]
    for f in fields:
        c = Counter(cmp[p][f]["category"] for p in pages if cmp.get(p))
        n = sum(c[k] for k in DETAIL)
        lines.append(f"| {f} | {n} | " + " | ".join(str(sum(c[k] for k in keys)) for _, keys in BUCKETS) + " |")
    return lines


def detail_table(cmp: dict[int, dict | None], pages: list[int]) -> list[str]:
    lines = ["| field | " + " | ".join(DETAIL) + " |", "|---|" + "---|" * len(DETAIL)]
    for f in ALL_FIELDS:
        c = Counter(cmp[p][f]["category"] for p in pages if cmp.get(p))
        lines.append(f"| {f} | " + " | ".join(str(c[k]) for k in DETAIL) + " |")
    return lines


def rotation_table(info: dict[int, dict], pages: list[int]) -> list[str]:
    """זיהוי הכיוון לכל עמוד. "straight after rotation" = המעבר הראשון שנבחר דיווח rotation_degrees=0,
    כלומר המערכת מצאה את העמוד ישר (זו הראיה של המערכת עצמה, לא טבלת אמת)."""
    lines = ["| page | expected | local axis | model reported | rotation applied | attempts | unresolved | "
             "straight after rotation |", "|---|---|---|---|---|---|---|---|"]
    for p in pages:
        m = info.get(p) or {}
        rot = m.get("rotation") or {}
        p1 = m.get("pass1") or {}
        straight = p1.get("rotation_degrees") == "0" if p1.get("ok") else None
        expected = "rotated" if p in ROTATED_PAGES else "upright"
        lines.append(f"| {p} | {expected} | {rot.get('local_axis')} | {rot.get('reported')} | {rot.get('applied')} | "
                     f"{rot.get('attempts')} | {rot.get('unresolved')} | {straight} |")
    return lines


def build_report(truth: dict[int, list[dict]], pages: list[int], stopped: str | None, source: Path) -> str:
    cmp = cells(truth, pages)
    info = meta(pages)
    done = [p for p in pages if cmp.get(p)]
    lines = ["# Extra evaluation set (6 pages, measurement only)", "",
             f"Truth file: {source}  |  PDF: {PDF.name}  |  pages evaluated: {done or 'none'}", ""]
    if stopped:
        lines += [f"**STOPPED: {stopped}. Report is partial.**", ""]
    missing = [p for p in pages if not cmp.get(p)]
    if missing:
        lines += [f"**No usable run for pages: {missing}** (run: python scripts/eval_extra.py --run)", ""]
    lines += ["## Main fields", ""] + bucket_table(cmp, MAIN_FIELDS, done)
    lines += ["", "## ID (reported separately, CLAUDE.md section 16)", ""] + bucket_table(cmp, ID_FIELD, done)
    lines += ["", "## Names (reported separately from ID)", ""] + bucket_table(cmp, NAME_FIELDS, done)
    lines += ["", "exact = correct value (green or orange)  |  WRONG-GREEN = wrong and not flagged (the metric to "
              "minimize)  |  wrong-orange = wrong but flagged  |  empty = no value (correct empty, missed error, or "
              "flagged empty)", "", "## Full category breakdown", ""] + detail_table(cmp, done)
    wrong_green = [(p, f, cmp[p][f]["truth"], cmp[p][f]["pred"]) for p in done for f in ALL_FIELDS
                   if cmp[p][f]["category"] == "confident_wrong"]
    lines += ["", "## WRONG GREEN (every case)", ""]
    lines += [f"- **page {p} {f}: truth {t!r} read {r!r}**" for p, f, t, r in wrong_green] or ["none"]
    lines += ["", "## Orientation detection", ""] + rotation_table(info, pages)
    lines += ["", "## Every cell that is not exact", "", "| page | field | truth | pred | category | flags |",
              "|---|---|---|---|---|---|"]
    for p in pages:
        if not cmp.get(p):
            lines.append(f"| {p} | (no run / page failed) | | | | |")
            continue
        for f in ALL_FIELDS:
            c = cmp[p][f]
            if c["category"] not in ("confident_ok", "orange_ok"):
                lines.append(f"| {p} | {f} | {c['truth']} | {c['pred']} | {c['category']} | "
                             f"{', '.join(c.get('flags') or [])} |")
    lines += ["", "## Page status", "", "| page | pass 1 model | commitment form | quality | second pass | "
              "pass 2 model | Claude fallback |", "|---|---|---|---|---|---|---|"]
    for p in pages:
        m = info.get(p) or {}
        p1 = m.get("pass1") or {}
        claude = p1.get("provider") == "anthropic" or (m.get("pass2") or {}).get("provider") == "anthropic"
        lines.append(f"| {p} | {p1.get('model')} | {p1.get('is_commitment_form')} | {p1.get('page_quality')} | "
                     f"{m.get('second_pass')} | {m.get('pass2_model')} | {claude} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if is_production():
        print("PRIVACY_MODE=production: this script needs the p<N>.json dumps and the cache; run in dev mode.")
        return 1
    if not PDF.exists():
        print(f"missing PDF: {PDF}\nהעתיקי את הקובץ לשם (6 עמודים) ואז הריצי שוב.")
        return 1
    source = truth_path(argv)
    if not source.exists():
        print(f"missing truth file: {source}")
        return 1
    truth = load_truth_csv(source)
    missing_pages = [p for p in PAGES if p not in truth]
    if missing_pages:
        print(f"{source.name}: missing rows for pages {missing_pages}")
        return 1
    empty = [p for p in PAGES if not truth_filled(truth[p])]
    if empty:
        print(f"אזהרה: בטבלת האמת {source.name} העמודים {empty} ריקים לגמרי (עוד לא מולאו ביד). "
              "כל תא ריק נמדד כאמת ריקה.")
    if "--run" in argv:
        tracker = BudgetTracker(extractor.TRACKER, LIMITS)
        extractor.TRACKER = tracker
        stopped, stats = run_pages(tracker)
        print(render_model_summary(sum_stats(*stats)))
        print(f"calls this run: {dict(tracker.count)}  (hard limits: {LIMITS})")
    else:
        stopped = None
        print("report only: no model call was made. להרצה אמיתית: python scripts/eval_extra.py --run")
    text = build_report(truth, PAGES, stopped, source)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"saved: {OUT / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
