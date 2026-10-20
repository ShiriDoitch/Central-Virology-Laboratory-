"""מכין גרסה בלי הדגש צהוב של PDF, מקומית לגמרי (בלי שום קריאה למודל).

הרעיון: ערוץ האפור = min(R, G) לכל פיקסל.
- הדגשה צהובה: R ו-G גבוהים (והכחול הוא שנמוך) -> min(R,G) גבוה -> כמעט לבן.
- דיו שחור: כל הערוצים נמוכים -> נשאר כהה.
- דיו כחול: R ו-G נמוכים -> נשאר כהה.
כך הצהוב נעלם והכתב (שחור או כחול) נשמר. CLAUDE.md סעיף 6 ("הדגש הצהוב"): המערכת חייבת לעבוד גם עם וגם בלי צהוב,
והקובץ הזה נועד למדידה של "בלי צהוב" בלבד.

שימוש:
    python scripts/make_dehighlighted.py
    python scripts/make_dehighlighted.py <pdf קלט> <pdf פלט> [--dpi 200]
ברירת מחדל: data/eval_extra/forms.pdf -> data/eval_extra/forms_nohl.pdf
"""
import io
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "data" / "eval_extra" / "forms.pdf"
DEFAULT_OUT = ROOT / "data" / "eval_extra" / "forms_nohl.pdf"
DEFAULT_DPI = 200          # אותו DPI שבו הצינור מרנדר עמודים (src/intake.pdf_to_images)


def dehighlight_image(img: Image.Image) -> Image.Image:
    """תמונה -> תמונת אפור (mode "L") שבה כל פיקסל הוא min(R, G) של המקור."""
    r, g, _b = img.convert("RGB").split()
    return ImageChops.darker(r, g)


def render_pages(pdf_path: Path, dpi: int = DEFAULT_DPI, pages: list[int] | None = None) -> list[Image.Image]:
    """עמודי PDF -> תמונות PIL. pages = מספרי עמודים מבוססי 1; None = כל העמודים."""
    doc = pymupdf.open(pdf_path)
    try:
        idx = range(len(doc)) if pages is None else [p - 1 for p in pages]
        out = []
        for i in idx:
            png = doc[i].get_pixmap(dpi=dpi).tobytes("png")
            out.append(Image.open(io.BytesIO(png)).convert("RGB"))
        return out
    finally:
        doc.close()


def save_pdf(images: list[Image.Image], out_path: Path, dpi: int = DEFAULT_DPI) -> None:
    """שומר רשימת תמונות כ-PDF, עמוד לכל תמונה."""
    if not images:
        raise ValueError("no pages to save")
    first, rest = images[0], images[1:]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    first.save(out_path, "PDF", save_all=True, append_images=rest, resolution=dpi)


def dehighlight_pdf(in_path: Path, out_path: Path, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    pages = render_pages(in_path, dpi)
    cleaned = [dehighlight_image(img) for img in pages]
    save_pdf(cleaned, out_path, dpi)
    return cleaned


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    dpi = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--dpi=")), DEFAULT_DPI)
    in_path = Path(args[0]) if args else DEFAULT_IN
    out_path = Path(args[1]) if len(args) > 1 else DEFAULT_OUT
    if not in_path.exists():
        print(f"missing input PDF: {in_path}")
        return 1
    cleaned = dehighlight_pdf(in_path, out_path, dpi)
    for i, img in enumerate(cleaned, start=1):
        hist = img.histogram()
        total = sum(hist) or 1
        bright, dark = sum(hist[240:]) / total, sum(hist[:81]) / total
        print(f"page {i}: {img.size[0]}x{img.size[1]} near-white {bright:.1%} dark {dark:.1%}")
    print(f"saved: {out_path} ({len(cleaned)} pages, {dpi} DPI, grayscale min(R,G))")
    print("מדידה בלבד: אין להריץ את המודל על הקובץ הזה בלי אישור.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
