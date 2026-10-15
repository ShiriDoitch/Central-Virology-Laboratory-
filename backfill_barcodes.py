"""מוסיף את מפתח "barcodes" ל-p<N>.json של ריצה שמורה (פענוח מקומי מה-PDF הנקי, בלי API; לא נוגע בשאר המפתחות).
שימוש: python backfill_barcodes.py <תיקיית ריצה> <pdf>"""
import json
import sys
from pathlib import Path

from src.barcode import decode_pdf_page

run, pdf = Path(sys.argv[1]), sys.argv[2]
for f in sorted(run.glob("p*.json"), key=lambda x: int(x.stem[1:])):
    data = json.loads(f.read_text(encoding="utf-8"))
    data["barcodes"] = decode_pdf_page(pdf, data["page"])
    f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f.name, len(data["barcodes"] or []), "barcodes")
