"""ההגדלה בפאנל אישור השם משנה באמת את רוחב התמונה (בפיקסלים) בתוך מיכל נגלל."""
import re

from src.confirm import ZOOM_BASE_PX, zoom_html


def width_of(html: str) -> int:
    return int(re.search(r'<img[^>]*style="width:(\d+)px', html).group(1))


def test_zoom_scales_the_pixel_width_and_is_scrollable():
    jpeg = b"\xff\xd8not-a-real-image"
    w = {z: width_of(zoom_html(jpeg, z)) for z in (100, 200, 400, 600)}
    assert w == {100: ZOOM_BASE_PX, 200: 2 * ZOOM_BASE_PX, 400: 4 * ZOOM_BASE_PX, 600: 6 * ZOOM_BASE_PX}
    html = zoom_html(jpeg, 200)
    assert "overflow:auto" in html and "max-width:none" in html and "max-height" in html     # נגלל, לא מוגבל לעמודה


def test_default_zoom_in_the_app_is_at_least_2x():
    src = open("evidence_view.py", encoding="utf-8")   # הרכיב המשותף למסך העיבוד ולכרטיס הרשומה.read()
    assert re.search(r'st\.slider\("הגדלה", 100, 600, (\d+)', src) and int(re.search(r'st\.slider\("הגדלה", 100, 600, (\d+)', src).group(1)) >= 200
    assert "zoom_html(crop, zoom)" in src
