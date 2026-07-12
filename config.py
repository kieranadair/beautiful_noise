import streamlit as st

DB    = st.secrets["connections"]["snowflake"]["database"]
SC    = st.secrets["connections"]["snowflake"]["schema"]
STAGE = st.secrets["app"]["stage"]
# Cortex model for AI_COMPLETE extraction (ai.py). Kept in code, not secrets, so a
# model change (e.g. a Cortex deprecation) ships via a normal git push/redeploy
# rather than a manual Streamlit Cloud secrets edit. Must be a multimodal (image-
# capable) model. llama4-scout was deprecated 2026-07-08; llama4-maverick is its
# cheapest same-family successor.
MODEL = "llama4-maverick"
IMG_FORMAT = "JPEG"
NAV_BTN_WIDTH = 220

