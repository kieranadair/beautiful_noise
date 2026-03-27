import streamlit as st
from config import NAV_BTN_WIDTH


# ---------------------------------------------------------------------------
# Navigation (two buttons side by side)
# ---------------------------------------------------------------------------

nav_left, nav_right, _ = st.columns([NAV_BTN_WIDTH, NAV_BTN_WIDTH, 1], gap="small", vertical_alignment="center")
with nav_left:
    if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", use_container_width=True):
        st.switch_page("upload_page.py")
with nav_right:
    if st.button("VIEW GALLERY", icon=":material/chevron_backward:", use_container_width=True):
        st.switch_page("gallery_page.py")

st.divider()

# ---------------------------------------------------------------------------
# Terms of Service content (rendered from tos.md)
# ---------------------------------------------------------------------------

st.write(open("tos.md").read())
