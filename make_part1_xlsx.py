"""מייצא את תוצאות המעבר הראשון של חלק 1 (מהתצלום data/part1_snapshot.json) לאקסל. בלי קריאות API.
שימוש: python make_part1_xlsx.py [נתיב פלט]"""
import json
import sys

from src.cache import load_snapshot
from src.export import export_excel

TOTAL_PAGES = 26

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else r"outputs\part1.xlsx"
    snapshot = load_snapshot()
    pages = [{"page": p, "pass1": snapshot.get(p), "pass2": None} for p in range(1, TOTAL_PAGES + 1)]
    summary = export_excel(pages, out)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"saved: {out}")
