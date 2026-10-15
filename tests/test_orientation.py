import cv2
import numpy as np
import pytest

from src.orientation import AXIS_THRESHOLD, text_axis


def text_like_page(seed=0, width=900, height=1200, lines=40, rotate=0):
    """עמוד סינתטי עם שורות טקסט (מקטעים כהים באורכים אקראיים), ואופציונלית מסובב."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width), 255, np.uint8)
    y = 90
    for _ in range(lines):
        x = int(width * 0.08)
        while x < width * 0.9:
            seg = int(rng.integers(15, 90))
            cv2.rectangle(img, (x, y), (min(x + seg, int(width * 0.92)), y + 9), 0, -1)
            x += seg + int(rng.integers(8, 22))
        y += 26
        if y > height - 90:
            break
    if rotate == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif rotate == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif rotate == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_horizontal_text_is_detected(seed):
    axis, score = text_axis(text_like_page(seed))
    assert axis == "horizontal" and score > AXIS_THRESHOLD


@pytest.mark.parametrize("rotate", [90, 270])
def test_rotated_90_270_is_detected_as_vertical(rotate):
    axis, score = text_axis(text_like_page(3, rotate=rotate))
    assert axis == "vertical" and score < AXIS_THRESHOLD


def test_upside_down_page_is_still_horizontal_axis():
    """הציר בלבד: 180 מעלות לא מזוהה כאן (נקבע לפי דיווח המודל)."""
    assert text_axis(text_like_page(4, rotate=180))[0] == "horizontal"


def test_axis_does_not_depend_on_page_size_scale():
    small = text_axis(text_like_page(5, width=450, height=600, lines=20))
    assert small[0] == "horizontal"


def test_long_table_lines_do_not_fool_the_detector():
    """קווי טבלה אנכיים ארוכים בעמוד אופקי לא הופכים אותו לאנכי."""
    rng_img = cv2.imdecode(np.frombuffer(text_like_page(6), np.uint8), cv2.IMREAD_GRAYSCALE)
    for x in (150, 450, 750):
        cv2.line(rng_img, (x, 60), (x, 1140), 0, 3)
    ok, buf = cv2.imencode(".jpg", rng_img)
    assert text_axis(buf.tobytes())[0] == "horizontal"


def test_blank_or_unreadable_image_is_unknown():
    blank = cv2.imencode(".jpg", np.full((600, 450), 255, np.uint8))[1].tobytes()
    assert text_axis(blank) == ("unknown", 0.0)
    assert text_axis(b"not an image") == ("unknown", 0.0)
