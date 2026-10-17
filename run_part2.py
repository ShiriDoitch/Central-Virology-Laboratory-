"""מדידה על חלק 2 (out-of-sample): שני מעברים, כללי ההחלטה הנוכחיים, בלי שינוי כללים.
שימוש: python run_part2.py            (קורא ל-API! רק באישור)
        python run_part2.py --report   (בלי API: דוח מהתשובות השמורות ב-outputs/part2_eval)
תקרות: 18 קריאות ל-gemini-3.8-flash, 60 ל-gemini-3.5-flash-lite, עצירה מיידית ב-404 של החזק ואחרי 3 עמודים רצופים שנכשלו."""
import json
import sys
from collections import Counter
from pathlib import Path

from src import extractor
from src.assemble import page_rows
from src.evaluate import CATEGORIES, compare_page, load_barcodes, load_run, load_truth
from src.pipeline import process_page, render_model_summary, sum_stats
from src.privacy import is_production, safe_write_text
from run_step2_dates import BudgetReached, BudgetTracker, StrongModelNotFound

PDF = r"data\clean_part2.pdf"
TRUTH = Path("data/truth_part2.xlsx")
OUT = Path("outputs/part2_eval")
PAGES = list(range(1, 23))
WEAK_GROUP = [19, 20, 21, 22]
LIMITS = {"gemini-3.8-flash": 18, "gemini-3.5-flash-lite": 60}
FIELDS = ["date", "center", "sender", "commitment", "id", "first_name", "last_name"]
COLS = [("confident_ok", "ירוק נכון"), ("confident_wrong", "**ירוק שגוי**"), ("orange_ok", "כתום נכון"),
        ("orange_wrong", "כתום שגוי"), ("empty_flagged", "ריק מסומן"), ("empty_missed", "שגיאה בלי סימון (ריק)"),
        ("empty_ok", "ריק נכון")]
MAX_CONSECUTIVE_FAILURES = 3


def cells(pages):
    truth = load_truth(TRUTH)
    results, regions = load_run(OUT, pages)
    barcodes = load_barcodes(OUT, pages)
    out = {}
    for p in pages:
        if not results[p].get("ok"):
            out[p] = None
            continue
        out[p] = compare_page(truth[p], page_rows(results[p], regions=regions.get(p), barcodes=barcodes.get(p)))
    return out


def table(cmp, pages):
    lines = ["| שדה | n | " + " | ".join(n for _, n in COLS) + " |", "|---|---|" + "---|" * len(COLS)]
    for f in FIELDS:
        c = Counter(cmp[p][f]["category"] for p in pages if cmp.get(p))
        lines.append(f"| {f} | {sum(c.values())} | " + " | ".join(str(c[k]) for k, _ in COLS) + " |")
    return lines


def build_report(stopped, tracker):
    cmp = cells(PAGES)
    meta = {}
    for p in PAGES:
        f = OUT / f"p{p}.json"
        meta[p] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    lines = ["# Part 2: out-of-sample measurement (22 pages)", ""]
    if stopped:
        lines += [f"**STOPPED: {stopped}. Report is partial.**", ""]
    lines += ["## Pass 2 model per page", "", "| page | pass 1 ok | pass 2 ran | pass 2 model | fell back to weak |", "|---|---|---|---|---|"]
    for p in PAGES:
        m = meta[p]
        lines.append(f"| {p} | {(m.get('pass1') or {}).get('ok')} | {m.get('second_pass')} | {m.get('pass2_model')} | {m.get('pass2_fallback')} |")
    strong = [p for p in PAGES if meta[p].get("pass2_model") and not meta[p].get("pass2_fallback")]
    weak = [p for p in PAGES if meta[p].get("pass2_fallback")]
    none = [p for p in PAGES if not meta[p].get("pass2_model")]
    lines += ["", f"- pages answered by strong model in pass 2: {strong}", f"- pages on weak fallback: {weak}",
              f"- pages without a pass 2 result: {none}", f"- pages 19-22 on weak fallback: {[p for p in WEAK_GROUP if p in weak]}", ""]
    g1 = [p for p in PAGES if p not in WEAK_GROUP]
    lines += ["## All 22 pages", ""] + table(cmp, PAGES)
    lines += ["", "## Pages 1-18 (pass 2 normally on the strong model)", ""] + table(cmp, g1)
    lines += ["", "## Pages 19-22 (separate: expected strong-model quota exhausted -> weak fallback)", ""] + table(cmp, WEAK_GROUP)
    wg = [(p, f, c[f]["truth"], c[f]["pred"]) for p, c in cmp.items() if c for f in FIELDS if c[f]["category"] == "confident_wrong"]
    lines += ["", "## WRONG GREEN", ""] + ([f"- **page {p} {f}: truth {t!r} read {r!r}**" for p, f, t, r in wg] or ["none"])
    lines += ["", "## All cells that are not correct", "", "| page | field | truth | pred | category | flags |", "|---|---|---|---|---|---|"]
    for p in PAGES:
        if not cmp.get(p):
            lines.append(f"| {p} | (page failed) | | | | |")
            continue
        for f in FIELDS:
            c = cmp[p][f]
            if c["category"] not in ("confident_ok", "orange_ok", "empty_ok"):
                lines.append(f"| {p} | {f} | {c['truth']} | {c['pred']} | {c['category']} | {', '.join(c.get('flags') or [])} |")
    if tracker:
        lines += ["", "## Calls", "", "| model | calls | limit |", "|---|---|---|"]
        lines += [f"| {m} | {tracker.count[m]} | {n} |" for m, n in LIMITS.items()]
    return "\n".join(lines) + "\n"


def main(report_only):
    if is_production():
        print("PRIVACY_MODE=production: needs p<N>.json dumps; run in dev mode.")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    tracker, stopped, stats, fails = None, None, [], 0
    if not report_only:
        tracker = BudgetTracker(extractor.TRACKER, LIMITS)
        extractor.TRACKER = tracker
        try:
            for p in PAGES:
                res = process_page(PDF, p, debug_dir=OUT)
                safe_write_text(OUT / f"p{p}.json", json.dumps(res, ensure_ascii=False))
                stats += [res["stats"]["pass1"], res["stats"]["pass2"]]
                ok = bool(res["pass1"].get("ok"))
                fails = 0 if ok else fails + 1
                print(f"page {p:>2}: pass1_ok={ok} second_pass={res['second_pass']} pass2_model={res.get('pass2_model')} "
                      f"fallback={res.get('pass2_fallback')} calls={dict(tracker.count)}", flush=True)
                if fails >= MAX_CONSECUTIVE_FAILURES:
                    stopped = f"{fails} consecutive page failures (last page {p})"
                    break
        except BudgetReached as e:
            stopped = f"call limit {e}"
        except StrongModelNotFound as e:
            stopped = f"{e} returned 404"
        if stopped:
            print(f"!!! {stopped}", flush=True)
        print(render_model_summary(sum_stats(*stats)))
    text = build_report(stopped, tracker)
    (OUT / "report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main("--report" in sys.argv)
