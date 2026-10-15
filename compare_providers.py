"""השוואת שתי ריצות מלאות על חלק 1 (למשל v4b של Gemini מול Claude), לכל שדה ב-7 הקטגוריות של src.evaluate.
קורא רק קבצי ריצה שמורים (בלי API). שימוש: python compare_providers.py [ריצה A] [ריצה B]
ברירת מחדל: outputs/clean_part1_v4b (Gemini) מול outputs/clean_part1_claude. הדוח נכתב ל-outputs/compare_gemini_vs_claude.md"""
import json
import sys
from collections import Counter
from pathlib import Path

from src.assemble import page_rows
from src.evaluate import CATEGORIES, OVERALL_FIELDS, SEPARATE_FIELDS, compare_page, load_run, load_truth

FIELDS = OVERALL_FIELDS + SEPARATE_FIELDS
CORRECT = ("confident_ok", "orange_ok", "empty_ok")
COST_KEYS = ("quota_failures", "unavailable", "not_found", "timeouts", "other_errors")


def run_cells(run_dir: Path, truth: dict) -> dict[tuple[int, str], dict]:
    pages = sorted(truth)
    results, regions = load_run(run_dir, pages)
    cells: dict[tuple[int, str], dict] = {}
    for p in pages:
        if not results[p].get("ok"):
            for f in FIELDS:
                cells[(p, f)] = {"category": "failed_page", "truth": "", "pred": ""}
            continue
        for f, info in compare_page(truth[p], page_rows(results[p], regions=regions.get(p))).items():
            cells[(p, f)] = info
    return cells


def run_cost(run_dir: Path, pages: list[int]) -> Counter:
    total: Counter = Counter()
    for p in pages:
        f = run_dir / f"p{p}.json"
        if f.exists():
            for part in json.loads(f.read_text(encoding="utf-8")).get("stats", {}).values():
                total.update({k: v for k, v in part.items() if isinstance(v, int)})
    return total


def main(a: Path, b: Path, name_a: str, name_b: str) -> str:
    truth = load_truth()
    ca, cb = run_cells(a, truth), run_cells(b, truth)
    lines = [f"# {name_a} vs {name_b}: part 1 (clean pages), 7 categories per field\n",
             "Each cell is `A / B` = " + f"{name_a} / {name_b}. confident_wrong = error not marked orange (to minimize).\n",
             "| field | " + " | ".join(CATEGORIES) + " | excluded | accuracy A / B |",
             "|---|" + "---|" * (len(CATEGORIES) + 2)]
    for f in FIELDS:
        row = [f]
        acc = []
        for c in CATEGORIES:
            row.append(f"{sum(1 for p in truth if ca[(p, f)]['category'] == c)} / {sum(1 for p in truth if cb[(p, f)]['category'] == c)}")
        row.append(f"{sum(1 for p in truth if ca[(p, f)]['category'] == 'excluded')} / {sum(1 for p in truth if cb[(p, f)]['category'] == 'excluded')}")
        for cells in (ca, cb):
            n = sum(1 for p in truth if cells[(p, f)]["category"] in CATEGORIES)
            ok = sum(1 for p in truth if cells[(p, f)]["category"] in CORRECT)
            acc.append(f"{100 * ok / n:.0f}%" if n else "-")
        row.append(" / ".join(acc))
        lines.append("| " + " | ".join(row) + " |")

    only_b, only_a = [], []
    for p in sorted(truth):
        for f in FIELDS:
            x, y = ca[(p, f)], cb[(p, f)]
            xo, yo = x["category"] in CORRECT, y["category"] in CORRECT
            if x["category"] == "excluded" or y["category"] == "excluded":
                continue
            line = (f"| {p} | {f} | {x.get('truth', '')} | {x.get('pred', '') or '∅'} ({x['category']}) | "
                    f"{y.get('pred', '') or '∅'} ({y['category']}) |")
            if yo and not xo:
                only_b.append(line)
            elif xo and not yo:
                only_a.append(line)
    head = f"| page | field | truth | {name_a} | {name_b} |\n|---|---|---|---|---|"
    lines += [f"\n## Cells where {name_b} is correct and {name_a} is not ({len(only_b)})\n", head, *only_b,
              f"\n## Cells where {name_a} is correct and {name_b} is not ({len(only_a)})\n", head, *only_a]

    cost = {}
    for name, d in ((name_a, a), (name_b, b)):
        cost[name] = run_cost(d, sorted(truth))
    summary_b = b / "run_summary.json"
    lines += ["\n## Cost\n", "| run | calls | failures | input tokens | output tokens | est. cost USD |", "|---|---|---|---|---|---|"]
    for name, d in ((name_a, a), (name_b, b)):
        c = cost[name]
        fails = sum(c[k] for k in COST_KEYS)
        if name == name_b and summary_b.exists():
            s = json.loads(summary_b.read_text(encoding="utf-8"))
            lines.append(f"| {name} | {s['calls']} | {s['failures']} | {s['input_tokens']} | {s['output_tokens']} | {s['estimated_usd']} |")
        else:
            lines.append(f"| {name} | {c['api_calls']} | {fails} | n/a (not recorded) | n/a | n/a |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    a = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/clean_part1_v4b")
    b = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("outputs/clean_part1_claude")
    text = main(a, b, "Gemini v4b" if "v4b" in a.name else a.name, "Claude" if "claude" in b.name else b.name)
    out = Path("outputs/compare_gemini_vs_claude.md")
    out.write_text(text, encoding="utf-8")
    print(text)
