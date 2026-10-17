"""שלב 2: מדידת תאריך ומרכזי על 10 עמודים של חלק 1 (מעבר 2 על gemini-3.8-flash עם גיבוי flash-lite, חיתוך אזור הקבלה).
שימוש: python run_step2_dates.py          (קורא ל-API! להריץ רק באישור)
         python run_step2_dates.py --report  (בלי API: רק מחשב מחדש את הדוח מהתשובות השמורות ב-outputs/step2_dates)

תקרת קריאות קשיחה (BudgetTracker): לכל היותר 12 ל-gemini-3.8-flash ו-25 ל-gemini-3.5-flash-lite; כל מודל אחר לא נקרא
(מדולג בלי בקשה). בהגעה לתקרה הריצה נעצרת מיד, נכתב דוח חלקי, ולא נשלחת אף בקשה נוספת.
בלי קריאה חוזרת של מעבר 2 על תוויות שם (retry_patient_labels=False): המדידה לא נוגעת בשמות, והקריאה החוזרת הייתה מכפילה
את הקריאות למודל החזק."""
import json
import sys
from collections import Counter
from pathlib import Path

from src import extractor
from src.privacy import is_production, safe_write_text
from src.assemble import page_rows
from src.evaluate import compare_page, load_barcodes, load_run, load_truth
from src.pipeline import process_page, render_model_summary, sum_stats
from src.quota import DailyQuotaExhausted

PDF = r"data\clean_part1.pdf"
OUT = Path("outputs/step2_dates")
PAGES = [3, 8, 11, 15, 17, 18, 19, 20, 22, 24]
STRONG = "gemini-3.8-flash"
LIMITS = {STRONG: 12, "gemini-3.5-flash-lite": 25}
FIELDS = ("date", "center")
NAMES = [("confident_ok", "ירוק נכון"), ("confident_wrong", "**ירוק שגוי**"), ("orange_ok", "כתום נכון"),
         ("orange_wrong", "כתום שגוי"), ("empty_flagged", "ריק מסומן"), ("empty_missed", "שגיאה בלי סימון (ריק)")]


class BudgetReached(BaseException):
    """BaseException כדי שלא ייתפס בשום מקום בצינור: עוצרים את הריצה כולה."""


class StrongModelNotFound(BaseException):
    """gemini-3.8-flash החזיר 404 (לא קיים / לא זמין): עוצרים מיד, בלי נפילה לגיבוי ובלי המשך לעמודים הבאים."""


class BudgetTracker:
    """עוטף את TRACKER: סופר כל בקשה שעומדת להישלח לפי מודל, ועוצר בתקרה. מודל שאינו ב-LIMITS מדולג בלי בקשה."""

    def __init__(self, inner, limits: dict[str, int]):
        self.inner, self.limits, self.count = inner, limits, Counter()

    def before_call(self, model: str) -> None:
        if model not in self.limits:
            raise DailyQuotaExhausted(model, "not_in_budget")
        if self.count[model] >= self.limits[model]:
            raise BudgetReached(f"{model}: {self.count[model]}/{self.limits[model]}")
        self.inner.before_call(model)         # מכסה יומית ומרווח בין קריאות, כרגיל
        self.count[model] += 1                # נספר רק אם הבקשה באמת נשלחת

    def mark_unavailable(self, model: str) -> None:
        """נקרא מ-extractor ברגע ש-404 התקבל, לפני הנפילה לגיבוי: עוצרים את הריצה מיד אם זה המודל החזק."""
        self.inner.mark_unavailable(model)
        if model == STRONG:
            raise StrongModelNotFound(model)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def snapshot(run: Path) -> dict:
    truth = load_truth()
    results, regions = load_run(run, PAGES)
    barcodes = load_barcodes(run, PAGES)
    out = {}
    for p in PAGES:
        if not results[p].get("ok"):
            out[p] = {"failed": True}
            continue
        cmp = compare_page(truth[p], page_rows(results[p], regions=regions.get(p), barcodes=barcodes.get(p)))
        out[p] = {f: {k: cmp[f].get(k) for k in ("category", "truth", "pred", "flags")} for f in FIELDS}
    return out


def report(after: dict, before: dict, tracker: BudgetTracker | None, stopped: str | None) -> str:
    lines = ["# Step 2: date and center on 10 pages of part 1 (3, 8, 11, 15, 17, 18, 19, 20, 22, 24)", ""]
    if stopped:
        lines += [f"**STOPPED: {stopped}. Report is partial.**", ""]
    for f in FIELDS:
        lines += [f"## {f}", "", "| category | before (v4b) | after |", "|---|---|---|"]
        for key, name in NAMES:
            b = sum(1 for p in PAGES if before.get(str(p), {}).get(f, {}).get("category") == key)
            a = sum(1 for p in PAGES if after.get(p, {}).get(f, {}).get("category") == key)
            lines.append(f"| {name} | {b} | {a} |")
        lines.append("")
    lines += ["## Changed cells", "", "| page | field | truth | before | after | category before -> after | flags after |", "|---|---|---|---|---|---|---|"]
    wrong_green = []
    for p in PAGES:
        for f in FIELDS:
            b = before.get(str(p), {}).get(f, {})
            a = after.get(p, {}).get(f, {})
            if not a:
                continue
            if (b.get("category"), b.get("pred")) != (a.get("category"), a.get("pred")):
                lines.append(f"| {p} | {f} | {a.get('truth')} | {b.get('pred') or '∅'} | {a.get('pred') or '∅'} | "
                             f"{b.get('category')} -> {a.get('category')} | {', '.join(a.get('flags') or [])} |")
            if a.get("category") == "confident_wrong":
                wrong_green.append((p, f, a.get("truth"), a.get("pred")))
    lines += ["", "## WRONG GREEN (must be none)", ""]
    lines += [f"- page {p} {f}: truth {t} read {r}" for p, f, t, r in wrong_green] or ["none"]
    if tracker:
        lines += ["", "## Calls", "", "| model | calls | limit |", "|---|---|---|"]
        lines += [f"| {m} | {tracker.count[m]} | {n} |" for m, n in LIMITS.items()]
    return "\n".join(lines) + "\n"


def per_page_models() -> list[str]:
    rows = []
    for p in PAGES:
        f = OUT / f"p{p}.json"
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            rows.append(f"page {p}: pass2 model={d.get('pass2_model')} fallback={d.get('pass2_fallback')} "
                        f"second_pass={d.get('second_pass')} reasons={d.get('reasons')}")
    return rows


def main(report_only: bool) -> None:
    if is_production():       # הדוח נבנה מקובצי p<N>.json, ו-PRIVACY_MODE=production לא כותב אותם
        print("PRIVACY_MODE=production: this measurement script needs the p<N>.json dumps; run it in dev mode.")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    before = json.loads((OUT / "before_v4b.json").read_text(encoding="utf-8"))
    tracker, stopped, stats = None, None, []
    if not report_only:
        tracker = BudgetTracker(extractor.TRACKER, LIMITS)
        extractor.TRACKER = tracker
        try:
            for p in PAGES:
                res = process_page(PDF, p, debug_dir=OUT, retry_patient_labels=False)
                safe_write_text(OUT / f"p{p}.json", json.dumps(res, ensure_ascii=False))
                stats += [res["stats"]["pass1"], res["stats"]["pass2"]]
                print(f"page {p:>2}: pass1_ok={res['pass1'].get('ok')} second_pass={res['second_pass']} "
                      f"pass2_model={res.get('pass2_model')} fallback={res.get('pass2_fallback')} "
                      f"calls so far={dict(tracker.count)}", flush=True)
        except BudgetReached as e:
            stopped = f"call limit {e}"
            print(f"!!! call limit reached ({e}). Stopping.", flush=True)
        except StrongModelNotFound as e:
            stopped = f"{e} returned 404 (not available); stopped before continuing to the other pages and before any fallback call"
            print(f"!!! {stopped}", flush=True)
        print(render_model_summary(sum_stats(*stats)))
    after = snapshot(OUT)
    text = report(after, before, tracker, stopped) + "\n## Pass 2 model per page\n\n" + "\n".join(per_page_models()) + "\n"
    (OUT / "report.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main("--report" in sys.argv)
