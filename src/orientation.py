"""זיהוי מקומי (בלי API) של עמוד שהטקסט בו אנכי (מסובב 90 או 270 מעלות), לפי מבנה שורות הטקסט.

בטקסט אופקי פרופיל השורות (סכום פיקסלים כהים בכל שורה) משתנה חזק, כי יש שורות ורווחים ביניהן, ופרופיל העמודות
כמעט אחיד. בטקסט אנכי זה הפוך. הציון = log(cv שורות / cv עמודות), אחרי הסרת קווים ארוכים (טבלאות, מסגרות) וחיתוך
שוליים. ציון חיובי = שורות אופקיות, שלילי = אנכיות.

מגבלות: מזהה רק את ציר הטקסט (אופקי/אנכי), לא את הכיוון (0 מול 180, או 90 מול 270). את הכיוון קובע דיווח
rotation_degrees של המודל, או ניסוי (ראו pipeline). נבדק על חלק 1: מזהה את כל ששת העמודים המסובבים (3, 11, 14, 22, 23, 25)
בלי אף אזעקת שווא; הרווח בין המסובב הקרוב ביותר (-0.06) ליושר הנמוך ביותר (+0.39) הוא רחב."""
import cv2
import numpy as np

AXIS_THRESHOLD = 0.3         # מתחת לזה = טקסט אנכי
MIN_INK_FRACTION = 0.002     # פחות מזה: עמוד כמעט ריק, אין מספיק מידע
MAX_SIDE = 1200


def _line_structure_score(bw: np.ndarray) -> float:
    h, w = bw.shape
    core = bw[int(h * 0.04):int(h * 0.96), int(w * 0.04):int(w * 0.96)]

    def cv_of(profile: np.ndarray) -> float:
        m = float(profile.mean())
        return float(profile.std()) / m if m > 0 else 0.0

    row = cv2.GaussianBlur(core.sum(axis=1).astype(np.float32).reshape(-1, 1), (1, 0), 2).ravel()
    col = cv2.GaussianBlur(core.sum(axis=0).astype(np.float32).reshape(1, -1), (0, 1), 2).ravel()
    return float(np.log((cv_of(row) + 1e-6) / (cv_of(col) + 1e-6)))


def _binarize_without_long_lines(gray: np.ndarray) -> np.ndarray:
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    h, w = bw.shape
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 6), 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 6))))
    return cv2.bitwise_and(bw, cv2.bitwise_not(cv2.bitwise_or(horiz, vert)))


def text_axis(image: bytes) -> tuple[str, float]:
    """מחזיר ("horizontal" | "vertical" | "unknown", ציון). unknown = אין מספיק תוכן או שהתמונה לא נקראה."""
    gray = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None or gray.size == 0:
        return "unknown", 0.0
    scale = MAX_SIDE / max(gray.shape)
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    bw = _binarize_without_long_lines(gray)
    if (bw > 0).mean() < MIN_INK_FRACTION:
        return "unknown", 0.0
    score = _line_structure_score(bw)
    return ("vertical" if score < AXIS_THRESHOLD else "horizontal"), score
