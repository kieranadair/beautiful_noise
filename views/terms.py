import streamlit as st
from core.config import NAV_BTN_WIDTH, CONTENT_DIR


# ---------------------------------------------------------------------------
# Navigation (two buttons side by side)
# ---------------------------------------------------------------------------

if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", width=NAV_BTN_WIDTH):
    st.switch_page("views/upload.py")
if st.button("VIEW GALLERY", icon=":material/chevron_backward:", width=NAV_BTN_WIDTH):
    st.switch_page("views/gallery.py")

st.divider()

# ---------------------------------------------------------------------------
# Terms of Service content (rendered from tos.md)
# ---------------------------------------------------------------------------

st.write((CONTENT_DIR / "tos.md").read_text(encoding="utf-8"))
