import streamlit as st
from config import NAV_BTN_WIDTH


# ---------------------------------------------------------------------------
# Navigation (two buttons side by side)
# ---------------------------------------------------------------------------

if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", width=NAV_BTN_WIDTH):
    st.switch_page("upload_page.py")
if st.button("VIEW GALLERY", icon=":material/chevron_backward:", width=NAV_BTN_WIDTH):
    st.switch_page("gallery_page.py")

st.divider()

# ---------------------------------------------------------------------------
# Terms of Service content (rendered from tos.md)
# ---------------------------------------------------------------------------

st.write(open("tos.md").read())
