import streamlit as st
from config import NAV_BTN_WIDTH
from db import get_session, get_all_posters, save_request
from utils import get_poster_vars, normalise

if st.button("BROWSE THE ARCHIVE", type="primary", icon=":material/arrow_back:", width=NAV_BTN_WIDTH):
    st.switch_page("gallery_page.py")

st.divider()

S = get_session()
all_posters = get_all_posters(S)
all_bands, all_venues, all_designers, _, _ = get_poster_vars(all_posters)

poster_labels = {f"#{p['POSTER_ID']} — {', '.join(p['BANDS'][:2])} — {p['VENUE_NAME']} — {p['DATE']:%d %b %Y}": p["POSTER_ID"] for p in all_posters}

REQUEST_TYPES = {
    "Correct a band name, venue, or designer": "CORRECTION",
    "Request designer attribution": "ATTRIBUTION",
    "Request a poster takedown": "TAKEDOWN",
    "Report a missing band from a lineup": "MISSING_BAND",
}

ENTITY_TYPES = {"Band": "BAND", "Venue": "VENUE", "Designer": "DESIGNER"}

st.subheader("Submit a request")
st.write("Use this form to submit corrections, attribution requests, or takedown notices. All requests are reviewed by an admin before any changes are made.")

request_label = st.radio("What would you like to do?", options=REQUEST_TYPES.keys(), index=None)

if request_label:
    request_type = REQUEST_TYPES[request_label]

    with st.form("request_form"):
        scope = "SPECIFIC"
        poster_ids = None
        entity_type = "POSTER"
        current_value = None
        requested_value = None
        notes = None

        if request_type == "CORRECTION":
            entity_label = st.radio("What needs correcting?", options=ENTITY_TYPES.keys())
            entity_type = ENTITY_TYPES[entity_label]
            options_map = {"BAND": all_bands, "VENUE": all_venues, "DESIGNER": all_designers}
            current_value = st.selectbox("Current value", options=options_map[entity_type])
            requested_value = st.text_input("Corrected value")
            apply_all = st.checkbox("Apply to all posters with this value", value=True)
            if apply_all:
                scope = "GLOBAL"
            else:
                if current_value:
                    if entity_type == "BAND":
                        relevant = [l for l, p in poster_labels.items() if current_value in next((po["BANDS"] for po in all_posters if po["POSTER_ID"] == p), [])]
                    elif entity_type == "VENUE":
                        relevant = [l for l, p in poster_labels.items() if next((po["VENUE_NAME"] for po in all_posters if po["POSTER_ID"] == p), None) == current_value]
                    else:
                        relevant = [l for l, p in poster_labels.items() if next((po["DESIGNER_NAME"] for po in all_posters if po["POSTER_ID"] == p), None) == current_value]
                    selected = st.multiselect("Which posters?", options=relevant)
                    poster_ids = [poster_labels[s] for s in selected]

        elif request_type == "ATTRIBUTION":
            entity_type = "DESIGNER"
            unknown_labels = {l: pid for l, pid in poster_labels.items() if next((p["DESIGNER_NAME"] for p in all_posters if p["POSTER_ID"] == pid), None) == "UNKNOWN"}
            if not unknown_labels:
                st.info("All posters currently have a designer attributed.")
            selected = st.multiselect("Which poster(s)?", options=unknown_labels.keys())
            poster_ids = [unknown_labels[s] for s in selected]
            requested_value = st.text_input("Designer name")

        elif request_type == "TAKEDOWN":
            selected = st.multiselect("Which poster(s)?", options=poster_labels.keys())
            poster_ids = [poster_labels[s] for s in selected]

        elif request_type == "MISSING_BAND":
            entity_type = "BAND"
            selected = st.multiselect("Which poster(s)?", options=poster_labels.keys())
            poster_ids = [poster_labels[s] for s in selected]
            requested_value = st.text_input("Band name to add")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help")

        submitted = st.form_submit_button("Submit request", type="primary", icon=":material/send:")

        if submitted:
            if request_type == "CORRECTION" and not requested_value:
                st.error("Please enter a corrected value.")
            elif request_type == "ATTRIBUTION" and not requested_value:
                st.error("Please enter the designer name.")
            elif request_type == "ATTRIBUTION" and not poster_ids:
                st.error("Please select at least one poster.")
            elif request_type == "MISSING_BAND" and not requested_value:
                st.error("Please enter the band name.")
            elif request_type == "MISSING_BAND" and not poster_ids:
                st.error("Please select at least one poster.")
            elif request_type == "TAKEDOWN" and not poster_ids:
                st.error("Please select at least one poster.")
            elif scope == "SPECIFIC" and request_type == "CORRECTION" and not poster_ids:
                st.error("Please select at least one poster, or apply to all.")
            else:
                save_request(
                    S,
                    request_type=request_type,
                    entity_type=entity_type,
                    scope=scope,
                    poster_ids=poster_ids if poster_ids else None,
                    current_value=normalise(current_value) if current_value else None,
                    requested_value=normalise(requested_value) if requested_value else None,
                    notes=notes.strip() if notes and notes.strip() else None,
                )
                st.success("Request submitted. It will be reviewed by an admin.")
