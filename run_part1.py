"""מריץ עמודים מחלק 1 דרך המודל (עם מטמון) ומדפיס שורת סטטוס לכל עמוד.
שימוש: python run_part1.py 1-3   |   python run_part1.py all   |   python run_part1.py 5,7,9"""
import sys
import time

import pymupdf

from src.cache import cached_extract
from src.extractor import DAILY_QUOTA_MSG
from src.intake import pdf_to_images
from src.pipeline import render_model_summary, sum_stats

PDF = r"data\samples_part1.pdf"


def parse_pages(spec: str, total: int) -> list[int]:
    if spec == "all":
        return list(range(1, total + 1))
    pages: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages += range(int(a), int(b) + 1)
        else:
            pages.append(int(part))
    return pages


if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "1"
    with pymupdf.open(PDF) as doc:
        total = len(doc)
    pages = parse_pages(spec, total)
    ok_count = 0
    all_stats: list[dict] = []
    for p in pages:  # מרווח בין קריאות מנוהל ב-src/quota.py
        t = time.time()
        images = pdf_to_images(PDF, pages=[p])
        result, from_cache = cached_extract(images)
        ok_count += bool(result.get("ok"))
        if not from_cache:
            all_stats.append(result.get("stats", {}))
        if result.get("ok"):
            skipped = result.get("model_errors") or {}
            status = (f"ok model={result['model']} commitment_form={result['is_commitment_form']} "
                      f"quality={result['page_quality']}" + (f" failed_before={skipped}" if skipped else ""))
        else:
            status = f"FAILED errors={result.get('model_errors')}"
        print(f"page {p:>2}: {'cache' if from_cache else 'api  '} {time.time() - t:5.1f}s {status}", flush=True)
        if str(result.get("error", "")).startswith(DAILY_QUOTA_MSG):
            print(f"!!! {result['error']}. עוצרים; הריצה תמשיך מכאן מחר (המטמון שומר את מה שהצליח).")
            break
    print(f"done: {ok_count}/{len(pages)} ok")
    print(render_model_summary(sum_stats(*all_stats)))
