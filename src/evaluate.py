"""השוואת פלט המערכת לטבלת האמת, לכל שדה בנפרד. קורא ממטמון בלבד (בלי קריאות API).
שימוש: python -m src.evaluate [תיקיית ריצה מלאה]"""
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from .assemble import PENDING_FIELDS, page_rows
from .cache import cached_extract, load_snapshot
from .intake import pdf_to_images
from .rules import F_NO_COMMITMENT, H_TWO_READS, Decision, split_multi

TRUTH_PATH = Path("data/truth_part1.xlsx")
PDF_PATH = r"data\samples_part1.pdf"
REPORT_PATH = Path("outputs/eval_report.md")

TRUTH_COLS = ["file_page", "sender", "first_name", "last_name", "id", "center", "date",
              "commitment", "center_where", "date_where", "commitment_label", "notes", "check"]
# שדות בדיוק הכולל. שמות ות"ז מדווחים בנפרד (CLAUDE.md סעיף 16).
OVERALL_FIELDS = ["date", "center", "sender", "commitment"]
SEPARATE_FIELDS = ["id", "first_name", "last_name"]
F_ONLY_HANDWRITTEN = ["handwritten"]       # + הרמז two_readings_agree (ת"ז ושמות בלבד) = "צהוב" בתצוגה (תת-קבוצה של הכתום)
CATEGORIES = ["confident_ok", "confident_wrong", "orange_ok", "orange_wrong", "empty_ok", "empty_missed",
              "empty_flagged"]
# עמודת "לבדיקה" בטבלת האמת -> שם שדה (שדה לא ודאי בטבלה לא נמדד כשגיאה)
CHECK_TO_FIELD = {'ת"ז': "id", "שם פרטי": "first_name", "שם משפחה": "last_name", "תאריך קבלה": "date",
                  "מספר מרכזי": "center", "מספר התחייבות": "commitment", "גורם שולח": "sender"}


def load_truth(path: Path = TRUTH_PATH) -> dict[int, list[dict]]:
    """מחזיר {מספר עמוד: [שורות אמת]}."""
    df = pd.read_excel(path, sheet_name=0, dtype=str, header=0)
    df.columns = TRUTH_COLS
    out: dict[int, list[dict]] = {}
    for rec in df.to_dict("records"):
        rec = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in rec.items()}
        if not rec["file_page"]:
            continue
        page = int(re.findall(r"\d+", rec["file_page"])[-1])
        out.setdefault(page, []).append(rec)
    return out


def norm_value(field: str, v: str | None) -> str:
    if not v:
        return ""
    v = str(v).strip()
    if field == "id":
        return re.sub(r"\D", "", v).lstrip("0")  # אפסים מובילים לא נחשבים הבדל
    if field in ("center", "commitment"):
        return re.sub(r"\s+", "", v)
    if field == "sender":
        return re.sub(r"[\s\"'״׳.\-]", "", v)
    return v


def classify(correct: bool, has_value: bool, flagged: bool) -> str:
    """ריק + מסומן לבדיקה (תאריך שאי אפשר להמיר, סתירה) = empty_flagged: לא שגיאה ולא נכון."""
    if flagged and not has_value:
        return "empty_flagged"
    if flagged:
        return "orange_ok" if correct else "orange_wrong"
    if not has_value:
        return "empty_ok" if correct else "empty_missed"
    return "confident_ok" if correct else "confident_wrong"


def compare_page(truth_rows: list[dict], pred_rows: list[dict]) -> dict[str, dict]:
    """מחזיר לכל שדה: truth, pred (לתצוגה), category."""
    out = {}
    excluded = {CHECK_TO_FIELD.get(r["check"]) for r in truth_rows if r["check"]}
    for field in OVERALL_FIELDS + SEPARATE_FIELDS:
        if field in excluded:
            out[field] = {"category": "excluded"}
            continue
        if field == "commitment":
            truth = {norm_value(field, r["commitment"]) for r in truth_rows if r["commitment"]}
            pred = {norm_value(field, r["commitment"]) for r in pred_rows if r["commitment"]}
            flagged = any(f != F_NO_COMMITMENT for r in pred_rows for f in r["commitment_flags"])
            flags, hints = sorted({f for r in pred_rows for f in r["commitment_flags"]}), []
        elif field == "center":
            truth = {norm_value(field, v) for v in split_multi(truth_rows[0]["center"])}
            dec: Decision = pred_rows[0]["center"] if pred_rows else Decision()
            pred = {norm_value(field, v) for v in split_multi(dec.value)}
            flagged = dec.uncertain
            flags, hints = list(dec.flags), list(dec.hints)
        else:
            truth = {norm_value(field, truth_rows[0][field])} - {""}
            dec = pred_rows[0][field] if pred_rows else Decision()
            pred = {norm_value(field, dec.value)} - {""}
            flagged = dec.uncertain
            flags, hints = list(dec.flags), list(dec.hints)
        out[field] = {
            "truth": " ; ".join(sorted(truth)), "pred": " ; ".join(sorted(pred)),
            "category": classify(truth == pred, bool(pred), flagged),
            "flags": flags, "only_handwritten": bool(pred) and flags == F_ONLY_HANDWRITTEN and H_TWO_READS in hints,
        }
    return out


def load_results(pages: list[int]) -> dict[int, dict]:
    """תוצאות מהמטמון בלבד; אם אין, מהתצלום של חלק 1 (מפתח המטמון השתנה מאז). עמוד חסר: ok=False."""
    snapshot = load_snapshot()
    results = {}
    for p in pages:
        images = pdf_to_images(PDF_PATH, pages=[p])
        result, hit = cached_extract(images, lambda _imgs: {"ok": False, "error": "not in cache"})
        results[p] = result if hit or p not in snapshot else snapshot[p]
    return results


def load_barcodes(run_dir: Path, pages: list[int]) -> dict[int, list[dict] | None]:
    """הברקודים שנשמרו בריצה (p<N>.json, מפתח "barcodes"); עמוד בלי מפתח (ריצה ישנה): None."""
    import json
    out = {}
    for p in pages:
        f = Path(run_dir) / f"p{p}.json"
        out[p] = json.loads(f.read_text(encoding="utf-8")).get("barcodes") if f.exists() else None
    return out


def load_run(run_dir: Path, pages: list[int]) -> tuple[dict[int, dict], dict[int, dict | None]]:
    """תוצאות ריצה מלאה (p<N>.json של process_page): המעבר הראשון (אחרי סיבוב) והמעבר השני, לכל עמוד."""
    import json
    results, regions = {}, {}
    for p in pages:
        f = Path(run_dir) / f"p{p}.json"
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        results[p] = data.get("pass1") or {"ok": False, "error": "no run file"}
        r2 = data.get("pass2")
        regions[p] = r2 if r2 and r2.get("ok") else None
    return results, regions


def evaluate(pages: list[int] | None = None, run_dir: Path | None = None) -> dict:
    """run_dir = תיקיית ריצה מלאה (שני מעברים); בלעדיה: מעבר ראשון בלבד מהמטמון."""
    truth = load_truth()
    pages = pages or sorted(truth)
    if run_dir:
        results, regions = load_run(run_dir, pages)
        barcodes = load_barcodes(run_dir, pages)
    else:
        results, regions, barcodes = load_results(pages), {}, {}
    counts: dict[str, Counter] = {f: Counter() for f in OVERALL_FIELDS + SEPARATE_FIELDS}
    errors, failed = [], []
    for p in pages:
        if not results[p].get("ok"):
            failed.append(p)
            continue
        cmp = compare_page(truth[p], page_rows(results[p], regions=regions.get(p), barcodes=barcodes.get(p)))
        for field, info in cmp.items():
            counts[field][info["category"]] += 1
            if info.get("only_handwritten"):             # צהוב: נספר גם בכתום, ובנפרד כאן
                counts[field]["yellow_ok" if info["category"] == "orange_ok" else "yellow_wrong"] += 1
            if info["category"] in ("confident_wrong", "orange_wrong", "empty_missed"):
                errors.append((p, field, info["truth"], info["pred"], info["category"]))
    return {"counts": counts, "errors": errors, "failed": failed, "evaluated": len(pages) - len(failed)}


def _row(field: str, c: Counter) -> str:
    n = sum(c[k] for k in CATEGORIES)
    ok = c["confident_ok"] + c["orange_ok"] + c["empty_ok"]
    confident = c["confident_ok"] + c["confident_wrong"]
    prec = f"{c['confident_ok']}/{confident}" if confident else "-"
    acc = f"{100 * ok / n:.0f}%" if n else "-"
    pending = " (not implemented)" if field in PENDING_FIELDS else ""
    return (f"| {field}{pending} | {n} | {acc} | {c['confident_ok']} | {c['confident_wrong']} | {c['orange_ok']} | "
            f"{c['orange_wrong']} | {c['empty_ok']} | {c['empty_missed']} | {c['empty_flagged']} | "
            f"{c['excluded']} | {prec} |")


def render(report: dict) -> str:
    head = ("| field | n | accuracy | confident ok | **confident WRONG** | orange ok | orange wrong | empty ok | "
            "empty missed | empty flagged | excluded | confident precision |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    lines = [f"# Evaluation report (part 1, dev set)\n",
             f"Pages evaluated: {report['evaluated']}; failed/missing: {report['failed'] or 'none'}\n",
             "## Overall fields (names and ID reported separately, CLAUDE.md section 16)\n", head]
    lines += [_row(f, report["counts"][f]) for f in OVERALL_FIELDS]
    lines += ["", "## Reported separately (fake names/IDs)\n", head]
    lines += [_row(f, report["counts"][f]) for f in SEPARATE_FIELDS]
    lines += ["", "## Yellow display tier (id / names only: value + only the `handwritten` flag + two independent readings agree; a subset of orange ok / orange wrong, counted separately)\n",
              "| field | yellow ok | yellow wrong |", "|---|---|---|"]
    lines += [f"| {f} | {report['counts'][f]['yellow_ok']} | {report['counts'][f]['yellow_wrong']} |" for f in OVERALL_FIELDS + SEPARATE_FIELDS]
    lines += ["", "**confident WRONG** = errors that were not marked orange (the metric to minimize).",
              "**empty flagged** = empty value marked for review (unconvertible date, conflict): not an error, "
              "not counted as correct.",
              "", "## Errors\n", "| page | field | truth | predicted | category |", "|---|---|---|---|---|"]
    lines += [f"| {p} | {f} | {t} | {pr} | {c} |" for p, f, t, pr, c in report["errors"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else None      # python -m src.evaluate [תיקיית ריצה מלאה]
    out = run / "eval_report.md" if run else REPORT_PATH
    text = render(evaluate(run_dir=run))
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"saved: {out}")
