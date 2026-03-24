import streamlit as st
DB    = st.secrets["connections"]["snowflake"]["database"]
SC    = st.secrets["connections"]["snowflake"]["schema"]
STAGE = st.secrets["app"]["stage"]
MODEL = st.secrets["app"]["model"]
PROMPT = """Extract the following from this gig poster:
- bands: every band, artist, or performer including support acts and DJs
- date: the event date in MM-DD format; do NOT provide year even if it is visible in the poster
- venue: venue name only
- event_name: specific festival or night name only; null if none"""

RESPONSE_FORMAT = {
    "type": "json",
    "schema": {
        "type": "object",
        "properties": {
            "bands":      {"type": "array", "items": {"type": "string"}},
            "date":       {"type": "string"},
            "venue":      {"type": "string"},
            "event_name": {"type": ["string", "null"]}
        },
        "required": ["bands", "date", "venue", "event_name"]
    }
}
VALIDATION_PROMPT = """Look at this image. Reply with a JSON object with a single key "valid" 
    set to true if this is a gig, concert, or event poster, or false if it is not."""

VALIDATION_FORMAT = {
    "type": "json",
    "schema": {
        "type": "object",
        "properties": {"valid": {"type": "boolean"}},
        "required": ["valid"]
    }
}
