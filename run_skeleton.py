"""שלד: עמוד אחד מה-PDF -> Gemini -> JSON מודפס. שימוש: python run_skeleton.py [מספר עמוד]"""
import json
import sys

from src.extractor import extract
from src.intake import pdf_to_images

PDF = r"data\samples_part1.pdf"

if __name__ == "__main__":
    page = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    images = pdf_to_images(PDF, pages=[page])
    result = extract(images)
    print(json.dumps(result, ensure_ascii=False, indent=2))
