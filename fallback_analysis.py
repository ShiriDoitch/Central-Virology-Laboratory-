"""דוח בלבד (בלי API, בלי שינוי כללים): כל תא שהוא empty_flagged ב-v4b (Gemini), ומה Claude עשה באותו תא
(מילא נכון / מילא שגוי / השאיר ריק), בריצה outputs/clean_part1_claude. מציע טריגר לשלב גיבוי ומעריך עלות.
הדוח נכתב ל-outputs/fallback_analysis.md."""
from collections import Counter, defaultdict
from pathlib import Path

from src.assemble import page_rows
from src.evaluate import OVERALL_FIELDS, SEPARATE_FIELDS, compare_page, load_run, load_truth

GEMINI, CLAUDE = Path("outputs/clean_part1_v4b"), Path("outputs/clean_part1_claude")
FIELDS = OVERALL_FIELDS + SEPARATE_FIELDS
COST_PER_PAGE = 0.07            # דולר לעמוד (שני מעברים, Claude Sonnet 5.5), כפי שמדדנו: 1.82 / 26


def cells(run: Path, truth: dict) -> dict[tuple[int, str], dict]:
    pages = sorted(truth)
    results, regions = load_run(run, pages)
    out = {}
    for p in pages:
        rows = page_rows(results[p], regions=regions.get(p)) if results[p].get("ok") else []
        for f, info in compare_page(truth[p], rows).items():
            out[(p, f)] = info
    return out


def fate(info: dict) -> str:
    if not info["pred"]:
        return "left empty"
    return "correct" if info["category"].endswith("_ok") else "WRONG"


def tier(info: dict) -> str:
    """איך Claude היה מוצג: ירוק (בלי דגל), צהוב (רק handwritten), כתום."""
    if info["category"].startswith("confident"):
        return "green"
    return "yellow" if info.get("only_handwritten") else "orange"


def table(rows, header):
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(str(x) for x in r) + " |" for r in rows])


def main() -> str:
    truth = load_truth()
    g, c = cells(GEMINI, truth), cells(CLAUDE, truth)
    flagged = [(p, f) for (p, f), i in sorted(g.items()) if i["category"] == "empty_flagged"]
    out = ["# Fallback pass analysis (report only; no API calls, nothing was run)\n",
           f"Cells that are empty_flagged in v4b (Gemini): {len(flagged)}. For each: what Claude (outputs/clean_part1_claude) did on the same cell.\n"]

    rows = []
    for p, f in flagged:
        gi, ci = g[(p, f)], c[(p, f)]
        rows.append([p, f, gi["truth"], ",".join(gi.get("flags", [])) or "-", ci["pred"] or "∅", fate(ci),
                     tier(ci) if ci["pred"] else ci["category"]])
    out += ["## 1. Every v4b empty_flagged cell\n",
            table(rows, ["page", "field", "truth", "v4b flags", "Claude read", "Claude result", "how Claude's cell would show"])]

    by_field: dict[str, Counter] = defaultdict(Counter)
    for p, f in flagged:
        by_field[f][fate(c[(p, f)])] += 1
    rows = [[f, sum(by_field[f].values()), by_field[f]["correct"], by_field[f]["WRONG"], by_field[f]["left empty"]]
            for f in FIELDS if by_field[f]]
    tot = Counter()
    for f in by_field:
        tot.update(by_field[f])
    rows.append(["**all fields**", sum(tot.values()), tot["correct"], tot["WRONG"], tot["left empty"]])
    non_names = Counter()
    for f in FIELDS:
        if f not in ("first_name", "last_name"):
            non_names.update(by_field[f])
    rows.append(["**all except names**", sum(non_names.values()), non_names["correct"], non_names["WRONG"], non_names["left empty"]])
    out += ["\n## 2. Summary per field\n", table(rows, ["field", "v4b empty_flagged", "Claude correct", "Claude WRONG", "Claude left empty"])]

    # טריגרים לפי עמוד
    page_cells: dict[int, list[str]] = defaultdict(list)
    for p, f in flagged:
        page_cells[p].append(f)
    key_fields = ("date", "center", "sender", "commitment", "id")
    triggers = {
        "T1: page has >= 1 empty_flagged cell in a non-name field": lambda fl: any(f in key_fields for f in fl),
        "T2: page has >= 2 empty_flagged cells in non-name fields": lambda fl: sum(f in key_fields for f in fl) >= 2,
        "T3: page has >= 1 empty_flagged in center, commitment or id (the hard numeric fields)": lambda fl: any(f in ("center", "commitment", "id") for f in fl),
        "T4: any empty_flagged cell at all (names included)": lambda fl: bool(fl),
        "T5: T1 without pages whose only such cell is a commitment flagged no_commitment (truth usually has none)": None,
        "T6: a non-name empty_flagged cell whose flags show disagreement (conflict, commitment_mismatch, invalid_date, invalid_format)": None,
    }
    page_flags: dict[int, list[tuple[str, list[str]]]] = defaultdict(list)
    for p, f in flagged:
        page_flags[p].append((f, g[(p, f)].get("flags", [])))
    DISAGREE = {"conflict", "commitment_mismatch", "invalid_date", "invalid_format"}      # המודל קרא משהו, אבל הקריאות לא מסכימות

    def not_just_no_commitment(fl):
        return any(f in key_fields and not (f == "commitment" and "no_commitment" in flags) for f, flags in fl)

    out.append("\n## 3. Candidate triggers for a Claude-only-when-needed fallback pass\n")
    out.append(f"Cost = triggered pages x ${COST_PER_PAGE:.2f} (measured: both passes, about 3.4 calls per page). The full run on 26 pages cost $1.82. "
               "'Fixed' = empty_flagged cells on the triggered pages that Claude read correctly; 'wrong' = cells Claude filled with a wrong value "
               "(it would show orange or yellow, never green: 0 confident_wrong in the Claude run).\n")
    rows = []
    for name, rule in triggers.items():
        if name.startswith("T5"):
            pages = sorted(p for p, fl in page_flags.items() if not_just_no_commitment(fl))
        elif name.startswith("T6"):
            pages = sorted(p for p, fl in page_flags.items() if any(f in key_fields and DISAGREE & set(flags) for f, flags in fl))
        else:
            pages = sorted(p for p, fl in page_cells.items() if rule(fl))
        fixed = wrong = empty = 0
        for p in pages:
            for f in page_cells[p]:
                if f in ("first_name", "last_name") and "names" not in name:
                    continue
                r = fate(c[(p, f)])
                fixed += r == "correct"; wrong += r == "WRONG"; empty += r == "left empty"
        rows.append([name, len(pages), f"{len(pages)}/26", f"${len(pages) * COST_PER_PAGE:.2f}", fixed, wrong, empty,
                     f"${len(pages) * COST_PER_PAGE / fixed:.2f}" if fixed else "-"])
    out.append(table(rows, ["trigger", "pages", "share of 26", "cost", "cells fixed", "cells wrong", "left empty", "cost per fixed cell"]))
    out.append("\nPer page (non-name empty_flagged fields, and whether Claude fixed them):\n")
    rows = []
    for p in sorted(page_cells):
        nn = [f for f in page_cells[p] if f in key_fields]
        if nn:
            rows.append([p, ", ".join(f"{f}:{fate(c[(p, f)])}" for f in nn)])
    out.append(table(rows, ["page", "non-name empty_flagged fields: Claude result"]))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    text = main()
    Path("outputs/fallback_analysis.md").write_text(text, encoding="utf-8")
    print(text)
