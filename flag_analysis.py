"""ניתוח דגלים על הריצה השמורה v4b (בלי API ובלי שינוי כללים): לכל תא בדוח ההערכה: דגלים וקטגוריה.
טבלאות: לכל שדה ולכל צירוף דגלים, לכל דגל בודד, הצעות לירוק, והשפעתן. הדוח נכתב ל-outputs/flag_analysis_v4b.md.
שימוש: python flag_analysis.py [תיקיית ריצה]"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.assemble import page_rows
from src.evaluate import CATEGORIES, OVERALL_FIELDS, SEPARATE_FIELDS, compare_page, load_run, load_truth

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/clean_part1_v4b")
FIELDS = OVERALL_FIELDS + SEPARATE_FIELDS
ORANGE_CATS = ("orange_ok", "orange_wrong")
MIN_N = 3                      # הצעה לירוק רק לצירוף שנצפה לפחות כך (על חלק 1)


def flags_of(rows: list[dict], field: str) -> list[str]:
    if not rows:
        return []
    if field == "commitment":
        return sorted({f for r in rows for f in r["commitment_flags"]})
    return sorted(rows[0][field].flags)


def collect() -> list[dict]:
    truth = load_truth()
    pages = sorted(truth)
    results, regions = load_run(RUN, pages)
    cells = []
    for p in pages:
        rows = page_rows(results[p], regions=regions.get(p)) if results[p].get("ok") else []
        for field, info in compare_page(truth[p], rows).items():
            if info["category"] == "excluded":
                continue
            cells.append({"page": p, "field": field, "flags": flags_of(rows, field), "cat": info["category"],
                          "truth": info.get("truth", ""), "pred": info.get("pred", "")})
    return cells


def key(flags: list[str]) -> str:
    return " + ".join(flags) if flags else "(none)"


def table(rows: list[list], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def metrics(c: Counter) -> dict:
    n = sum(c[k] for k in CATEGORIES)
    green_ok = c["confident_ok"]
    return {"n": n, "green_ok": green_ok, "confident_wrong": c["confident_wrong"],
            "orange_ok": c["orange_ok"], "orange_wrong": c["orange_wrong"], "empty_flagged": c["empty_flagged"],
            "empty_missed": c["empty_missed"], "empty_ok": c["empty_ok"],
            "automation": (green_ok + c["orange_ok"]) / n if n else 0,
            "review": (c["orange_ok"] + c["orange_wrong"] + c["empty_flagged"]) / n if n else 0}


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def main() -> str:
    cells = collect()
    by_field: dict[str, list[dict]] = defaultdict(list)
    for c in cells:
        by_field[c["field"]].append(c)
    out = [f"# Flag analysis of {RUN} (part 1, dev set; report only, no rule was changed)\n",
           "Categories as in src/evaluate. A cell = one field of one page (names and id reported like every other field).\n"]

    # 1. סיכום אוטומציה וביקורת לכל שדה
    out.append("## 1. Per field: automation and review burden (current rules)\n")
    out.append("automation = (green_ok + orange_ok) / all cells. review burden = (orange_ok + orange_wrong + empty_flagged) / all cells. "
               "empty_missed = empty and not flagged (a silent miss).\n")
    rows = []
    for f in FIELDS:
        m = metrics(Counter(c["cat"] for c in by_field[f]))
        rows.append([f, m["n"], m["green_ok"], m["confident_wrong"], m["orange_ok"], m["orange_wrong"], m["empty_flagged"],
                     m["empty_missed"], pct(m["automation"]), pct(m["review"])])
    out.append(table(rows, ["field", "n", "green_ok", "confident_wrong", "orange_ok", "orange_wrong", "empty_flagged",
                            "empty_missed", "automation", "review burden"]))

    # 2. לכל שדה ולכל צירוף דגלים
    out.append("\n## 2. Per field and flag combination\n")
    combos: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for c in cells:
        combos[(c["field"], key(c["flags"]))][c["cat"]] += 1
    rows = []
    for (f, k), cnt in sorted(combos.items(), key=lambda x: (FIELDS.index(x[0][0]), -sum(x[1].values()))):
        rows.append([f, k, sum(cnt.values()), cnt["confident_ok"], cnt["confident_wrong"], cnt["orange_ok"],
                     cnt["orange_wrong"], cnt["empty_flagged"], cnt["empty_missed"]])
    out.append(table(rows, ["field", "flags", "n", "confident_ok", "confident_wrong", "orange_ok", "orange_wrong",
                            "empty_flagged", "empty_missed"]))

    # 3. לכל דגל בודד (תא נספר בכל דגל שיש בו)
    out.append("\n## 3. Per single flag (a cell counts under every flag it carries), over all fields\n")
    single: dict[str, Counter] = defaultdict(Counter)
    single_f: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for c in cells:
        for fl in c["flags"]:
            single[fl][c["cat"]] += 1
            single_f[(c["field"], fl)][c["cat"]] += 1
    rows = [[fl, sum(cnt[k] for k in CATEGORIES), cnt["orange_ok"], cnt["orange_wrong"], cnt["empty_flagged"]]
            for fl, cnt in sorted(single.items(), key=lambda x: -sum(x[1].values()))]
    out.append(table(rows, ["flag", "cells", "orange_ok", "orange_wrong", "empty_flagged"]))
    out.append("\nSame, per field:\n")
    rows = [[f, fl, sum(cnt[k] for k in CATEGORIES), cnt["orange_ok"], cnt["orange_wrong"], cnt["empty_flagged"]]
            for (f, fl), cnt in sorted(single_f.items(), key=lambda x: (FIELDS.index(x[0][0]), -sum(x[1].values())))]
    out.append(table(rows, ["field", "flag", "cells", "orange_ok", "orange_wrong", "empty_flagged"]))

    # 4. הצעות לירוק: צירופי (שדה, דגלים) בלי שגיאה, עם לפחות MIN_N תאים כתומים נכונים
    out.append(f"\n## 4. Proposals: (field, flag combination) that could turn green\n")
    out.append(f"Candidate = a combination with orange_wrong = 0 and at least {MIN_N} cells with a value that were all correct "
               "(orange_ok >= 3). 'Error bound' is the rule-of-three 95% upper bound on the true error rate, 3/n: with n cells and "
               "no error seen, the true error could still be up to that. This is tuned on part 1 only; part 2 is the honest test.\n")
    props = []
    for (f, k), cnt in combos.items():
        if k != "(none)" and cnt["orange_wrong"] == 0 and cnt["orange_ok"] >= MIN_N and not (cnt["empty_flagged"] or cnt["confident_wrong"] or cnt["empty_missed"]):
            props.append((f, k, cnt))
    props.sort(key=lambda x: (FIELDS.index(x[0]), -x[2]["orange_ok"]))
    rows = []
    for f, k, cnt in props:
        base = metrics(Counter(c["cat"] for c in by_field[f]))
        n_c = cnt["orange_ok"]
        new_green, new_cw = base["green_ok"] + n_c, base["confident_wrong"]
        review = base["review"] - n_c / base["n"]
        rows.append([f, k, n_c, f"{3 / n_c * 100:.0f}%", f"{base['green_ok']} -> {new_green}", f"{base['confident_wrong']} -> {new_cw}",
                     f"{pct(base['review'])} -> {pct(review)}", f"{pct(base['automation'])} (unchanged: orange_ok already counted)"])
    out.append(table(rows, ["field", "flag combination -> green", "cells moved", "error bound", "green_ok",
                            "confident_wrong", "review burden", "automation"]))
    if props:
        tot_n = sum(c["page"] is not None for c in cells)
        allc = Counter(); all_moved = Counter()
        for f, k, cnt in props:
            all_moved[f] += cnt["orange_ok"]
        green_ok_all = sum(metrics(Counter(c["cat"] for c in by_field[f]))["green_ok"] for f in FIELDS)
        cw_all = sum(metrics(Counter(c["cat"] for c in by_field[f]))["confident_wrong"] for f in FIELDS)
        rev_all = sum(metrics(Counter(c["cat"] for c in by_field[f]))["review"] * len(by_field[f]) for f in FIELDS)
        moved = sum(all_moved.values())
        out.append(f"\nAll proposals together: green_ok {green_ok_all} -> {green_ok_all + moved} of {len(cells)} cells, "
                   f"confident_wrong {cw_all} -> {cw_all} (no error among the moved cells on part 1), "
                   f"review burden {pct(rev_all / len(cells))} -> {pct((rev_all - moved) / len(cells))}.")

    # 5. כל הצירופים שנסגרים עם שגיאה אחת (לשקיפות): סף של מקסימום שגיאה אחת
    out.append("\n## 5. Near-misses: combinations with exactly one orange_wrong (shown for transparency, not proposed)\n")
    rows = []
    for (f, k), cnt in sorted(combos.items(), key=lambda x: FIELDS.index(x[0][0])):
        if k != "(none)" and cnt["orange_wrong"] == 1 and cnt["orange_ok"] >= MIN_N:
            wrong = next(c for c in by_field[f] if key(c["flags"]) == k and c["cat"] == "orange_wrong")
            rows.append([f, k, cnt["orange_ok"], cnt["orange_wrong"], f"page {wrong['page']}: truth {wrong['truth']} / read {wrong['pred']}"])
    out.append(table(rows, ["field", "flags", "orange_ok", "orange_wrong", "the wrong cell"]) if rows else "(none)")

    # 6. כל התאים הכתומים הלא נכונים (כל מה שירוק היה צריך להימנע ממנו)
    out.append("\n## 6. Every orange_wrong cell (these must never be turned green)\n")
    rows = [[c["page"], c["field"], key(c["flags"]), c["truth"], c["pred"]] for c in cells if c["cat"] == "orange_wrong"]
    out.append(table(rows, ["page", "field", "flags", "truth", "read"]))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = main()
    Path("outputs/flag_analysis_v4b.md").write_text(text, encoding="utf-8")
    print(text)
