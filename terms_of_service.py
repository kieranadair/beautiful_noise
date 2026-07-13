import streamlit as st


# ---------------------------------------------------------------------------
# Terms of Service content (rendered from tos.md)
# ---------------------------------------------------------------------------

st.write(open("tos.md").read())
