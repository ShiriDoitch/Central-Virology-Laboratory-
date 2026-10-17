"""מעבד עמודים נבחרים: מעבר ראשון (עם זיהוי וסיבוב עמוד מסובב) -> מעבר שני רק כשצריך.
שומר חיתוכים ו-boxes ב-outputs/second_pass_v2/, מדפיס לכל עמוד את ההחלטות מול טבלת האמת, וסיכום עלות
(קריאות API וכישלונות מכסה) לעמוד, לריצה ולפי מודל.
שימוש: python run_second_pass.py 14,22,21,24,26,5 [--force]   (--force = מעבר שני גם כשאפשר לדלג)
הריצה הראשונה המאושרת של v2: ששת העמודים האלה, ורק אחרי שמסתכלים על התוצאה, כל חלק 1."""
import json
import sys
from pathlib import Path

from src import extractor
from src.privacy import safe_write_text
from src.assemble import page_rows
from src.evaluate import load_truth
from src.extractor import DAILY_QUOTA_MSG
from src.pipeline import process_page, render_model_summary, summarize_by_model, sum_stats

PDF = r"data\samples_part1.pdf"
OUT = Path("outputs/second_pass_v2")
DEFAULT_PAGES = "14,22,21,24,26,5"
FIELDS = [("first_name", "first_name"), ("last_name", "last_name"), ("id", "id"), ("center", "center"),
          ("date", "date"), ("sender", "sender")]


def _dec(d) -> str:
    text = repr(d.value) if d.value else "∅"
    if d.flags:
        text += f" [{','.join(d.flags)}]"
    if d.alternatives:
        text += f" alt={d.alternatives}"
    return text


def _cost(s: dict) -> str:
    return (f"calls={s.get('api_calls', 0)} quota_429={s.get('quota_failures', 0)} 503={s.get('unavailable', 0)} "
            f"404={s.get('not_found', 0)} timeouts={s.get('timeouts', 0)} other={s.get('other_errors', 0)}")


def show(res: dict, truth: dict) -> None:
    p = res["page"]
    t = truth[p][0]
    rot = res["rotation"]
    print(f"\n=== page {p} === second_pass={res['second_pass']} reasons={res['reasons']}")
    print(f"rotation:  local_axis={rot['local_axis']} model_reported={rot['reported']} applied={rot['applied']} "
          f"attempts={rot['attempts']} flags={res['page_flags']}")
    rows = page_rows(res["pass1"], regions=res["pass2"], barcodes=res.get("barcodes"))
    if not rows:
        print("rows:      (none: failed page or not a commitment form)")
    else:
        row = rows[0]
        for key, truth_key in FIELDS:
            print(f"{key:<10} truth={t[truth_key]!r:<28} -> {_dec(row[key])}")
        print(f"{'commitment':<10} truth={t['commitment']!r:<28} -> {[(r['commitment'], r['commitment_flags']) for r in rows]}")
    r2 = res["pass2"]
    if r2 and r2.get("ok"):
        print(f"pass2:     model={r2['model']} patient.region_ok={r2['patient']['region_ok']} barcode.region_ok={r2['barcode']['region_ok']}")
    elif r2:
        print(f"pass2:     FAILED {r2.get('error')} {r2.get('model_errors')}")
    s = res["stats"]
    print(f"cost:      pass1 {_cost(s['pass1'])} | pass2 {_cost(s['pass2'])}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    pages = [int(x) for x in (args[0] if args else DEFAULT_PAGES).split(",")]
    OUT.mkdir(parents=True, exist_ok=True)
    truth = load_truth()
    results = []
    for p in pages:  # מרווחים בין קריאות מנוהלים ב-src/quota.py
        res = process_page(PDF, p, force_second_pass=force, debug_dir=OUT)
        results.append(res)
        show(res, truth)
        safe_write_text(OUT / f"p{p}.json", json.dumps(res, ensure_ascii=False, indent=1))
        print(f"quota:     {extractor.TRACKER.report([*extractor.model_chain(), *extractor.region_model_chain()])}")
        if str(res["pass1"].get("error", "")).startswith(DAILY_QUOTA_MSG):
            print(f"!!! {res['pass1']['error']} (מעבר ראשון). עוצרים; אפשר להמשיך מחר.")
            break
        if res["second_pass"] == "daily_quota_exhausted":
            print("!!! מכסה יומית נגמרה לכל המודלים החזקים: המעבר השני לא ירוץ היום (לא נשלחה אף בקשה).")
    total = sum_stats(*(s for r in results for s in r["stats"].values()))
    print("\n" + render_model_summary(total))
    summary = {"pages": len(pages), "total": total, "per_page_calls": round(total.get("api_calls", 0) / len(pages), 2),
               "by_model": summarize_by_model(total),
               "second_pass_skipped": [r["page"] for r in results if r["second_pass"] == "skipped"],
               "rotated": {r["page"]: r["rotation"]["applied"] for r in results if r["rotation"]["applied"]},
               "by_page": {r["page"]: sum_stats(*r["stats"].values()) for r in results}}
    (OUT / "stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nRUN TOTAL: {_cost(total)} | per page: {summary['per_page_calls']} calls | "
          f"skipped pass2: {summary['second_pass_skipped']} | rotated: {summary['rotated']}")
