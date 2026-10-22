"""רכיב התצוגה המשותף של חיתוך השדה (Streamlit): מסך העיבוד (app.render_evidence) וכרטיס הרשומה (records_screen) מציגים בו את
אותו חיתוך באותה צורה: סרגל הגדלה, מסגרת נגללת, והעמוד המלא. הלוגיקה של החיתוך עצמו משותפת ב-src/confirm.py (review_crop)."""
import streamlit as st

from src.confirm import region_zoom_html, zoom_html

CROP_CAPTION = "האזור שממנו נקרא השדה, מהעמוד הנקי. ההגדלה בסרגל משנה את גודל התמונה, וגוללים בתוך המסגרת."


NO_CROP_CAPTION = "אין חיתוך זמין לשדה הזה; העמוד המלא מוצג."


def render_crop_and_page(crop: bytes | None, image: bytes | None, page: int, zoom_key: str, no_crop_note: str | None = None) -> None:
    """crop = חיתוך השדה (או None), image = העמוד המלא (או None). יש חיתוך: סרגל הגדלה והעמוד המלא בתוך מרחיב. אין חיתוך: העמוד המלא,
    עם הערה (no_crop_note: לשדה שיש לו מושג אזור אבל אין אימות מקומי לערך; בלי הערה: ההודעה הכללית, לשדה בלי מושג אזור כלל)."""
    if crop:
        zoom = st.slider("הגדלה", 100, 600, 200, 50, key=zoom_key, format="%d%%")
        st.markdown(zoom_html(crop, zoom), unsafe_allow_html=True)
        st.caption(CROP_CAPTION)
    else:
        st.caption(no_crop_note or NO_CROP_CAPTION)
        if image:
            st.image(image, caption=f"עמוד {page}", width="stretch")
    if crop and image:
        with st.expander("העמוד המלא"):
            st.image(image, caption=f"עמוד {page}", width="stretch")


def render_zoomable_page(image: bytes, zoom_key: str, caption: str = "העמוד כפי שנקרא (סובב לפי הצורך). ההגדלה בסרגל משנה את גודל התמונה.") -> None:
    """העמוד המלא עם סרגל הגדלה ומסגרת נגללת (כרטיס הרשומה)."""
    zoom = st.slider("הגדלת העמוד", 100, 600, 100, 50, key=zoom_key, format="%d%%")
    st.markdown(zoom_html(image, zoom, base_px=720, box_height_px=520), unsafe_allow_html=True)
    st.caption(caption)


PAGE_REGION_CAPTION = "העמוד המלא; המסגרת מסמנת את האזור שממנו נקרא השדה."


def render_page_region(image: bytes, fractions: tuple | list | None, page: int, zoom_key: str, no_region_note: str | None = None) -> None:
    """העמוד המלא עם מסגרת סביב האזור של השדה (מסך הבדיקה המונחית). בלי אזור מאומת: העמוד בלי סימון, עם הערה
    (no_region_note: לשדה שיש לו מושג אזור אבל אין אימות מקומי; בלי הערה: ההודעה הכללית)."""
    zoom = st.slider("הגדלת העמוד", 100, 600, 100, 50, key=zoom_key, format="%d%%")
    st.markdown(region_zoom_html(image, zoom, fractions, box_height_px=520), unsafe_allow_html=True)
    st.caption(f"עמוד {page} · " + (PAGE_REGION_CAPTION if fractions else (no_region_note or "אין אזור שמור לשדה הזה, מוצג העמוד כולו.")))
