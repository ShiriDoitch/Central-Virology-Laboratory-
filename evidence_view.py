"""רכיב התצוגה המשותף של חיתוך השדה (Streamlit): מסך העיבוד (app.render_evidence) וכרטיס הרשומה (records_screen) מציגים בו את
אותו חיתוך באותה צורה: סרגל הגדלה, מסגרת נגללת, והעמוד המלא. הלוגיקה של החיתוך עצמו משותפת ב-src/confirm.py (review_crop)."""
import streamlit as st

from src.confirm import zoom_html

CROP_CAPTION = "האזור שממנו נקרא השדה, מהעמוד הנקי. ההגדלה בסרגל משנה את גודל התמונה, וגוללים בתוך המסגרת."


def render_crop_and_page(crop: bytes | None, image: bytes | None, page: int, zoom_key: str) -> None:
    """crop = חיתוך השדה (או None), image = העמוד המלא (או None). יש חיתוך: סרגל הגדלה והעמוד המלא בתוך מרחיב. אין חיתוך: העמוד המלא."""
    if crop:
        zoom = st.slider("הגדלה", 100, 600, 200, 50, key=zoom_key, format="%d%%")
        st.markdown(zoom_html(crop, zoom), unsafe_allow_html=True)
        st.caption(CROP_CAPTION)
    else:
        st.caption("אין חיתוך זמין לשדה הזה; העמוד המלא מוצג.")
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
