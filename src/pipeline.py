"""עיבוד עמוד אחד: מעבר ראשון -> (אם צריך) חיתוך מוגדל + מעבר שני. כולל ספירת קריאות API לעמוד."""
import io
import re
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from . import extractor
from .cache import cache_key, cached_extract, cached_regions, store_result
from .crop import (COMMITMENT_MIN_AREA, ENLARGE_RETRY, choose_box, edges_touching_ink, expand_receipt_fractions, is_valid_box,
                   receipt_region_fractions, region_fractions)
from .barcode import decode_pdf_page
from .extractor import DAILY_QUOTA_MSG
from .intake import pdf_to_images, render_region, rotate_jpeg
from .orientation import text_axis
from .privacy import is_production
from .rules import apply_field_validity, commitment_numbers, decide_center, decide_id, patient_labels_missing
from .schema import Box, PageExtraction

COLORS = {"patient": "red", "barcode": "blue", "commitment": "green", "receipt": "purple"}
F_ROTATION_UNRESOLVED = "rotation_unresolved"


def plan_rotation(local_axis: str, reported: str) -> list[int]:
    """איזה סיבוב לנסות (מעלות עם כיוון השעון). הגלאי המקומי (src/orientation.py) קובע את הציר, ודיווח המודל
    (rotation_degrees) קובע את הכיוון. דיווח הסיבוב של המודל הקטן לא אמין (בחלק 1 הוא פספס 5 מתוך 6 עמודים
    מסובבים), ולכן הוא לא מספיק לבדו.
    - ציר אנכי: הכיוון מהדיווח אם הוא 90/270, אחרת ניחוש 90.
    - ציר אופקי: רק אם המודל דיווח 180. דיווח 90/270 על עמוד אופקי מתעלמים ממנו.
    - אין מידע מקומי (עמוד כמעט ריק): סומכים על המודל."""
    r = int(reported)
    if local_axis == "vertical":
        return [r] if r in (90, 270) else [90]
    if local_axis == "horizontal":
        return [180] if r == 180 else []
    return [r] if r else []


def pass1_needs_retry(r1: dict) -> bool:
    """המעבר הראשון קבע "לא טופס התחייבות" (is_commitment_form=false) אבל בעמוד יש מספר בן 6 ספרות ומעלה עם תווית,
    או מספר בכתב יד (גם ת"ז): הקביעה חשודה (ההחלטה לא יציבה בין הרצות), ולכן ניסיון חוזר אחד. תוצאה שכבר נוסתה
    מחדש (retried) לא מנסים שוב."""
    if not r1.get("ok") or r1.get("is_commitment_form", True) or r1.get("retried"):
        return False
    page = PageExtraction.model_validate(r1)
    long_labeled = any(n.label and n.label.strip() and len(re.sub(r"\D", "", n.value)) >= 6 for n in page.numbers)
    handwritten = any(n.source == "handwritten" for n in [*page.numbers, *page.id_numbers])
    return long_labeled or handwritten


def needs_second_pass(page: PageExtraction) -> tuple[bool, list[str]]:
    """מעבר שני רק כשצריך: אם המעבר הראשון מצא ת"ז ומרכזי בתווית ברורה (לא כתב יד, בלי סתירה, בלי דגל)
    מדלגים. מחזיר (צריך, סיבות); בסיבות: מה לא היה ודאי."""
    reasons = []
    for field, decision in (("id", decide_id(page.id_numbers, numbers=page.numbers)),
                            ("center", decide_center(page.numbers))):
        if decision.flags:
            reasons.append(f"{field}:{','.join(decision.flags)}")
        elif decision.value is None:
            reasons.append(f"{field}:missing")
    if page.commitment_box is not None and commitment_numbers(page.numbers):
        reasons.append("commitment:unverified")     # מספר התחייבות שנקרא פעם אחת: קריאה שנייה מחיתוך מוגדל
    if page.receipt_box is not None and is_valid_box(page.receipt_box, COMMITMENT_MIN_AREA):
        reasons.append("date:unverified")           # תאריך קבלה שנקרא פעם אחת: קריאה שנייה מחיתוך אזור הקבלה
    return bool(reasons), reasons


def sum_stats(*stats: dict | None) -> dict:
    """מחבר מילוני סטטיסטיקה (api_calls, quota_failures, ...)."""
    total: Counter = Counter()
    for s in stats:
        total.update(s or {})
    return dict(total)


MODEL_KINDS = ("ok", "429", "503", "404", "timeout", "other")


def summarize_by_model(stats: dict) -> dict[str, dict[str, int]]:
    """מפרק סטטיסטיקה מצטברת לפי מודל: {model: {calls, ok, 429, 503, 404, timeout, other}}.
    המפתחות במקור: "calls:<model>", "ok:<model>", "429:<model>" וכו'."""
    out: dict[str, dict[str, int]] = {}
    for key, n in stats.items():
        prefix, _, model = key.partition(":")
        if not model or prefix not in ("calls", *MODEL_KINDS):
            continue
        row = out.setdefault(model, {"calls": 0, **{k: 0 for k in MODEL_KINDS}})
        row[prefix] += n
    return dict(sorted(out.items()))


def render_model_summary(stats: dict) -> str:
    """סיכום קריאות API לפי מודל, לסוף כל ריצה."""
    rows = summarize_by_model(stats)
    if not rows:
        return "API calls by model: none (everything came from cache)"
    lines = [f"{'model':<26} {'calls':>5} {'ok':>4} {'429':>4} {'503':>4} {'404':>4} {'timeout':>7} {'other':>5}"]
    total = {"calls": 0, **{k: 0 for k in MODEL_KINDS}}
    for model, r in rows.items():
        lines.append(f"{model:<26} {r['calls']:>5} {r['ok']:>4} {r['429']:>4} {r['503']:>4} {r['404']:>4} "
                     f"{r['timeout']:>7} {r['other']:>5}")
        for k in total:
            total[k] += r[k]
    lines.append(f"{'TOTAL':<26} {total['calls']:>5} {total['ok']:>4} {total['429']:>4} {total['503']:>4} "
                 f"{total['404']:>4} {total['timeout']:>7} {total['other']:>5}")
    return "\n".join(lines)


def save_debug_images(out_dir: Path, page: int, page_jpeg: bytes, crops: dict[str, bytes], boxes: dict) -> None:
    """שומר את החיתוכים ותמונת עמוד עם ה-boxes מצוירים (לבדיקה ויזואלית). ב-production: לא שומר כלום."""
    if is_production():
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, data in crops.items():
        (out_dir / f"p{page}_{kind}.jpg").write_bytes(data)
    img = Image.open(io.BytesIO(page_jpeg)).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for kind, b in boxes.items():
        x0, y0, x1, y1 = b["fractions"]
        draw.rectangle((x0 * w, y0 * h, x1 * w, y1 * h), outline=COLORS[kind], width=8)
    img.thumbnail((900, 1300))
    img.save(out_dir / f"p{page}_boxes.jpg", quality=85)


def process_page(pdf_path: str, page: int, force_second_pass: bool = False,
                 debug_dir: Path | None = None, retry_patient_labels: bool = True) -> dict:
    """עמוד אחד תחת תקציב זמן כולל (extractor.page_budget, ברירת מחדל 180 שניות, PAGE_BUDGET_S). חריגה: error_code="page_timeout" בתוצאת
    העמוד (ובכשל המעבר הראשון גם ב-pass1), והעיבוד של שאר העמודים ממשיך. פרטים על שאר התוצאה: _process_page."""
    with extractor.page_budget() as budget:
        out = _process_page(pdf_path, page, force_second_pass, debug_dir, retry_patient_labels)
    if budget.exceeded or (out.get("pass2") or {}).get("error_code") == "page_timeout":
        out["error_code"] = "page_timeout"
    return out


def _process_page(pdf_path: str, page: int, force_second_pass: bool = False,
                  debug_dir: Path | None = None, retry_patient_labels: bool = True) -> dict:
    """מחזיר {page, pass1, pass2, boxes, second_pass, reasons, stats}.
    second_pass = run | skipped | failed | daily_quota_exhausted | not_possible (המעבר הראשון נכשל).
    המעבר השני עולה לכל היותר קריאה חזקה אחת לעמוד (ראו extract_regions).
    stats = קריאות API בפועל לכל מעבר (עמוד שנטען מהמטמון = 0 קריאות).
    pass2_model = המודל שענה במעבר השני (None אם לא רץ), pass2_fallback = True אם ענה מודל הגיבוי (החלש).
    retry_patient_labels=False: בלי קריאה חוזרת של מעבר 2 כשחסרה תווית שם (לחיסכון בקריאות במדידות שלא נוגעות בשמות)."""
    images = pdf_to_images(pdf_path, pages=[page])
    barcodes = decode_pdf_page(pdf_path, page)     # קורא שני מקומי למרכזי (בלי API); None אם הפענוח נכשל
    r1, hit1 = cached_extract(images)
    stats1 = [] if hit1 else [r1.get("stats", {})]
    rotation = {"local_axis": "unknown", "reported": "0", "applied": None, "attempts": 0, "unresolved": False}
    page_flags: list[str] = []
    out = {"page": page, "pass1": r1, "pass2": None, "boxes": {}, "second_pass": "not_possible", "reasons": [],
           "barcodes": barcodes, "pass2_model": None, "pass2_fallback": False,
           "rotation": rotation, "page_flags": page_flags,
           "stats": {"pass1": sum_stats(*stats1), "pass2": {}}}
    if not r1.get("ok"):
        if r1.get("error_code"):
            out["error_code"] = r1["error_code"]
        return out

    # סיבוב: זיהוי ציר מקומי + כיוון מדיווח המודל. בדרך כלל קריאה קטנה אחת (מעבר ראשון על העמוד המסובב);
    # חריג: אם הכיוון היה ניחוש והתברר הפוך (העמוד המסובב מדווח 180), עוד קריאה אחת בכיוון ההפוך.
    axis, _score = text_axis(images[0])
    reported = r1.get("rotation_degrees", "0")
    rotation.update(local_axis=axis, reported=reported)
    plan = plan_rotation(axis, reported)
    if plan:
        deg = plan[0]
        guessed_direction = not (axis == "vertical" and int(reported) in (90, 270))
        accepted = None
        for attempt in (1, 2):
            rotated = [rotate_jpeg(images[0], deg)]
            r_try, hit_try = cached_extract(rotated)
            rotation["attempts"] = attempt
            if not hit_try:
                stats1.append(r_try.get("stats", {}))
            if not r_try.get("ok"):
                break
            reported_try = r_try.get("rotation_degrees", "0")
            if reported_try == "0":
                accepted = (r_try, rotated, deg)
                break
            if attempt == 1 and deg in (90, 270) and (
                    (guessed_direction and reported_try == "180")
                    or text_axis(rotated[0])[0] == "horizontal"):
                # הכיוון התברר כשגוי: הטקסט אופקי אבל הפוך (הגלאי המקומי לא מבדיל בין הכיוונים, והמודל מדווח
                # גם 90/270 על עמוד הפוך), ולכן מנסים פעם אחת את הכיוון ההפוך
                deg = 270 if deg == 90 else 90
                continue
            break
        if accepted:
            r1, images, rotation["applied"] = accepted
            out["pass1"] = r1
        else:
            rotation["unresolved"] = True
            page_flags.append(F_ROTATION_UNRESOLVED)
        out["stats"]["pass1"] = sum_stats(*stats1)

    if pass1_needs_retry(r1):
        # ניסיון חוזר אחד, בלי קריאה מהמטמון (נספר במכסה). נשמר במטמון עם retried=true, כך שהרצה חוזרת לא מנסה שוב.
        # אם גם הניסיון החוזר אומר "לא טופס": מדלגים כמו קודם.
        retry = extractor.extract(images)
        stats1.append(retry.get("stats", {}))
        if retry.get("ok"):
            r1 = {**retry, "retried": True}
            store_result(cache_key(images), r1)
            out["pass1"] = r1
        out["stats"]["pass1"] = sum_stats(*stats1)
        out["pass1_retried"] = True

    needed, reasons = needs_second_pass(PageExtraction.model_validate(r1))
    out["reasons"] = reasons
    if not needed and not force_second_pass:
        out["second_pass"] = "skipped"
        return out

    crops: dict[str, bytes] = {}
    for kind in ("patient", "barcode"):
        raw = r1.get(f"{kind}_box")
        box, fallback = choose_box(kind, Box(**raw) if raw else None)
        fractions = region_fractions(kind, box)
        crops[kind] = render_region(pdf_path, page, fractions, rotation=rotation["applied"] or 0)
        out["boxes"][kind] = {"raw": raw, "used": box.model_dump(), "fallback": fallback,
                              "fractions": [round(x, 3) for x in fractions]}
    raw_c = r1.get("commitment_box")
    if raw_c and is_valid_box(Box(**raw_c), COMMITMENT_MIN_AREA):          # בלי box תקין: אין חיתוך ואין אימות
        cbox = Box(**raw_c)
        cfr = region_fractions("commitment", cbox)
        crops["commitment"] = render_region(pdf_path, page, cfr, rotation=rotation["applied"] or 0)
        out["boxes"]["commitment"] = {"raw": raw_c, "used": cbox.model_dump(), "fallback": False,
                                      "fractions": [round(x, 3) for x in cfr]}
    raw_rc = r1.get("receipt_box")
    if raw_rc and is_valid_box(Box(**raw_rc), COMMITMENT_MIN_AREA):         # חותמת "התקבל" או מרכזי בכתב יד עם התאריך
        rbox = Box(**raw_rc)
        rfr = receipt_region_fractions(rbox)
        rcrop = render_region(pdf_path, page, rfr, rotation=rotation["applied"] or 0)
        touching = edges_touching_ink(rcrop)                                 # דיו שנוגע בקצה: הכתב נחתך, מרחיבים פעם אחת
        expanded = sorted(touching)
        if touching:
            rfr = expand_receipt_fractions(rfr, touching)
            rcrop = render_region(pdf_path, page, rfr, rotation=rotation["applied"] or 0)
        crops["receipt"] = rcrop
        out["boxes"]["receipt"] = {"raw": raw_rc, "used": rbox.model_dump(), "fallback": False,
                                   "fractions": [round(x, 3) for x in rfr], "expanded_sides": expanded}
    if debug_dir:
        save_debug_images(debug_dir, page, images[0], crops, out["boxes"])

    r2, hit2 = cached_regions(crops)
    stats2 = [] if hit2 else [r2.get("stats", {})]
    if retry_patient_labels and r2.get("ok") and patient_labels_missing(r2):
        # חסרה תווית שם פרטי/משפחה: החיתוך חשוד. הרצועה מוגדלת פי 1.5 ושולחים שוב, פעם אחת בלבד
        wide = region_fractions("patient", choose_box("patient", Box(**r1["patient_box"]) if r1.get("patient_box") else None)[0],
                                enlarge=ENLARGE_RETRY)
        retry_crops = {**crops, "patient": render_region(pdf_path, page, wide, rotation=rotation["applied"] or 0)}
        r2b, hit2b = cached_regions(retry_crops)
        if not hit2b:
            stats2.append(r2b.get("stats", {}))
        out["boxes"]["patient"]["retry_fractions"] = [round(x, 3) for x in wide]
        if r2b.get("ok"):
            r2, crops = r2b, retry_crops
            if debug_dir:
                save_debug_images(debug_dir, page, images[0], crops, out["boxes"])
    out["pass2_model"] = r2.get("model") if r2.get("ok") else None
    out["pass2_fallback"] = bool(r2.get("ok") and r2.get("fallback"))
    if r2.get("ok") and "patient" in r2:
        r2 = apply_field_validity(r2)                 # תקינות לפי שדה: לפי התוויות שנראו בחיתוך הסופי
    out["pass2"] = r2
    if r2.get("ok"):
        out["second_pass"] = "run"
    elif str(r2.get("error", "")).startswith(DAILY_QUOTA_MSG):
        out["second_pass"] = "daily_quota_exhausted"       # לא נשלחה אף בקשה; הקריאה הראשונה בלבד נשארת
    else:
        out["second_pass"] = "failed"
    out["stats"]["pass2"] = sum_stats(*stats2)
    return out
