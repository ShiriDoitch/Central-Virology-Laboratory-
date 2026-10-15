"""בדיקת שינוי כלל המרכזי על כל הריצות השמורות: שומר תמונת מצב של כל תא (7 שדות) ומשווה לפני/אחרי.
שימוש: python check_center_change.py snapshot <קובץ>   |   python check_center_change.py diff <לפני> <אחרי>"""
import json
import sys
from pathlib import Path

from src.assemble import page_rows
from src.evaluate import compare_page, load_barcodes, load_run, load_truth

RUNS = {"v4b": Path("outputs/clean_part1_v4b"), "claude": Path("outputs/clean_part1_claude")}
GOOD = ("confident_ok", "orange_ok", "empty_ok")
RANK = {"confident_ok": 0, "orange_ok": 1, "empty_ok": 1, "empty_flagged": 2, "empty_missed": 3, "orange_wrong": 3, "confident_wrong": 4, "excluded": -1}


def snapshot() -> dict:
    truth = load_truth()
    out = {}
    for name, run in RUNS.items():
        pages = sorted(truth)
        results, regions = load_run(run, pages)
        barcodes = load_barcodes(run, pages)
        for p in pages:
            rows = page_rows(results[p], regions=regions.get(p), barcodes=barcodes.get(p)) if results[p].get("ok") else []
            for f, info in compare_page(truth[p], rows).items():
                out[f"{name}|{p}|{f}"] = {"category": info["category"], "truth": info.get("truth", ""), "pred": info.get("pred", ""),
                                          "flags": info.get("flags", [])}
    return out


def diff(a: dict, b: dict) -> None:
    changed = {k: (a[k], b[k]) for k in a if a[k] != b[k]}
    print(f"cells compared: {len(a)}; changed: {len(changed)}")
    for k, (x, y) in changed.items():
        run, p, f = k.split("|")
        worse = RANK[y["category"]] > RANK[x["category"]] or (x["category"] in GOOD and y["category"] not in GOOD)
        print(f"{'REGRESSION' if worse else 'change    '} {run} p{p} {f}: truth={x['truth']!r}\n"
              f"      before: {x['category']} {x['pred']!r} {x['flags']}\n      after:  {y['category']} {y['pred']!r} {y['flags']}")
    for run in RUNS:
        cw = lambda s: sum(1 for k, v in s.items() if k.startswith(run + "|") and v["category"] == "confident_wrong")
        print(f"{run}: confident_wrong {cw(a)} -> {cw(b)}")
    regress = [k for k, (x, y) in changed.items() if RANK[y["category"]] > RANK[x["category"]] or (x["category"] in GOOD and y["category"] not in GOOD)]
    print("regressions:", len(regress))


if __name__ == "__main__":
    if sys.argv[1] == "snapshot":
        Path(sys.argv[2]).write_text(json.dumps(snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        diff(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")), json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")))
