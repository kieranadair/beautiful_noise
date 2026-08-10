from pathlib import Path
import streamlit as st

# User-facing copy (faq.md, tos.md) lives in content/. Resolved from this file's location rather
# than the working directory, so reads work no matter where `streamlit run` is invoked from.
CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"

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

# --- Image ingestion hardening (see security review / plan) ---------------
# Decode-time ceiling on pixel count. ~40 MP comfortably allows large phone
# photos and scans (a 12 MP iPhone shot is fine) while blocking decompression
# "pixel bombs" — small files that decode to enormous dimensions and exhaust
# memory. The final stored image is only 1200 px on its longest side, so this
# is purely a guard on the *input*, not a quality limit.
MAX_IMAGE_PIXELS = 40_000_000
# DPI used to rasterise the first page of an uploaded PDF. Clamped down at
# runtime if a page is large enough that rendering at this DPI would exceed
# MAX_IMAGE_PIXELS (see pdf_to_image_bytes).
PDF_RENDER_DPI = 150
# PIL .format values we accept. The file_uploader type= list is only an
# extension hint — PIL decodes by magic bytes, so this content-based allowlist
# is what actually constrains which codecs run on untrusted input.
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}

