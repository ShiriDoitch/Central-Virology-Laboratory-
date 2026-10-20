"""requirements.txt: הקובץ שעל פיו מתקינים על מחשב נקי (21.10.2026, מבדיקת התקנה בסביבה חדשה).
1. ASCII בלבד: pip קורא את הקובץ בקידוד המקומי של המערכת (cp1255 בעברית), ולכן הערה בעברית
   מפילה את ההתקנה ב-UnicodeDecodeError. זה קרה בפועל בבדיקה.
2. כל ספרייה שמיובאת ישירות בקוד מוצהרת בקובץ (גם כשהיא מגיעה כתלות של ספרייה אחרת)."""
import re
from pathlib import Path

REQ = Path("requirements.txt")
# שם המודול שמיובא -> השם ב-requirements (בלי גרסה)
DIRECT_IMPORTS = {"numpy": "numpy", "httpx": "httpx", "pymupdf": "pymupdf", "PIL": "pillow", "cv2": "opencv-python",
                  "pydantic": "pydantic", "pandas": "pandas", "openpyxl": "openpyxl", "streamlit": "streamlit",
                  "dotenv": "python-dotenv", "pytest": "pytest", "zxingcpp": "zxing-cpp", "google": "google-genai"}


def declared() -> set[str]:
    names = set()
    for line in REQ.read_text(encoding="ascii").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower())
    return names


def test_requirements_is_ascii_so_pip_can_read_it_in_any_locale():
    REQ.read_bytes().decode("ascii")                 # נכשל על כל תו עברי


def test_every_directly_imported_library_is_declared():
    missing = {mod: pkg for mod, pkg in DIRECT_IMPORTS.items() if pkg not in declared()}
    assert not missing


def test_the_modules_in_the_map_really_are_imported_in_the_code():
    """המיפוי לא מתיישן: כל שם מודול בו אכן מיובא במקור (אחרת מוחקים אותו מהמיפוי)."""
    sources = "\n".join(p.read_text(encoding="utf-8") for p in [*Path("src").glob("*.py"), Path("app.py"),
                                                                Path("records_screen.py"), *Path("tests").glob("*.py")])
    unused = [m for m in DIRECT_IMPORTS if not re.search(rf"^\s*(import|from) {re.escape(m)}\b", sources, re.M)]
    assert unused == []
