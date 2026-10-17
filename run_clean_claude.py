"""ניסוי: חלק 1 על העמודים הנקיים עם Claude בשני המעברים (אותו process_page, אותן הנחיות/סכמות/כללים).
הפלט ב-outputs/clean_part1_claude (פורמט זהה ל-clean_part1_v4b, כך ש-python -m src.evaluate עובד עליו).
מטמון נפרד (data/cache/anthropic), מטמוני Gemini לא נוגעים. תקרת תקציב קשיחה: ANTHROPIC_BUDGET_USD (ברירת מחדל 2).
שימוש: python run_clean_claude.py [עמודים, למשל 1-3 או 5,7 או all]
המפתח ANTHROPIC_API_KEY נטען מ-.env ולא נכתב לשום קובץ או פלט."""
import json
import os
import sys
from collections import Counter
from pathlib import Path

os.environ["EXTRACT_PROVIDER"] = "anthropic"          # חייב להיות לפני טעינת ההגדרות; ברירת המחדל בקובץ נשארת gemini

from src import extractor
from src.privacy import safe_write_text                                # noqa: E402
from src.pipeline import process_page, sum_stats         # noqa: E402
from run_part1 import parse_pages                        # noqa: E402

PDF = r"data\clean_part1.pdf"
OUT = Path("outputs/clean_part1_claude")


def main(spec: str) -> None:
    import pymupdf
    with pymupdf.open(PDF) as doc:
        total = len(doc)
    OUT.mkdir(parents=True, exist_ok=True)
    extractor.SPEND.reset()
    stats: list[dict] = []
    stopped = None
    for p in parse_pages(spec, total):
        res = process_page(PDF, p, force_second_pass=True, debug_dir=OUT)
        safe_write_text(OUT / f"p{p}.json", json.dumps(res, ensure_ascii=False))
        stats += [res["stats"]["pass1"], res["stats"]["pass2"]]
        budget_hit = any(r and r.get("budget_exceeded") for r in (res["pass1"], res["pass2"]))
        print(f"page {p:>2}: pass1_ok={res['pass1'].get('ok')} second_pass={res['second_pass']} "
              f"spend=${extractor.SPEND.usd:.3f}", flush=True)
        if budget_hit:
            stopped = p
            print(f"!!! תקרת התקציב (${extractor.SPEND.limit_usd:.2f}) הושגה בעמוד {p}. עוצרים ומדווחים.")
            break
    total_stats = Counter(sum_stats(*stats))
    summary = {"pages_run_until": stopped or "done", "calls": total_stats["api_calls"],
               "failures": sum(total_stats[k] for k in ("quota_failures", "unavailable", "not_found", "timeouts", "other_errors")),
               "failure_breakdown": {k: total_stats[k] for k in ("quota_failures", "unavailable", "not_found", "timeouts", "other_errors")},
               "input_tokens": extractor.SPEND.input_tokens, "output_tokens": extractor.SPEND.output_tokens,
               "estimated_usd": round(extractor.SPEND.usd, 4), "limit_usd": extractor.SPEND.limit_usd}
    (OUT / "run_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
