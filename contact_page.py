import streamlit as st
from config import NAV_BTN_WIDTH
from db import get_session, get_all_posters, save_request
from utils import get_poster_vars, normalise, poster_has

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
# Data: session, poster cache, filter options
# ---------------------------------------------------------------------------

S = get_session()
all_posters = get_all_posters(S)
all_bands, all_venues, all_designers, _, _ = get_poster_vars(all_posters)

# ---------------------------------------------------------------------------
# Constants & lookup maps
# ---------------------------------------------------------------------------

poster_labels = {f"{p['POSTER_ID']} — {', '.join(p['BANDS'][:2])} — {p['VENUE_NAME']} — {p['DATE']:%d %b %Y}": p for p in all_posters}

REQUEST_TYPES = {
    "Authorise and/or provide designer attribution to a community upload": "ATTRIBUTION",
    "Request a poster takedown": "TAKEDOWN",
    "Correct a band, venue or designer's name": "CORRECTION",
}

ENTITY_TYPES = {"Band": "BAND", "Venue": "VENUE", "Designer": "DESIGNER"}

GRID_COLUMNS = 5

def poster_picker(labels, key="default", help_text="Search by poster id, band, venue and date"):
    selected = st.multiselect("Which poster(s)?", options=labels, help=help_text, key=f"picker_{key}")
    if selected:
        preview = [labels[s] for s in selected]
        cols = st.columns(GRID_COLUMNS, gap="large")
        for i, p in enumerate(preview):
            with cols[i % GRID_COLUMNS]:
                st.image(p["URL"])
                st.caption(f"ID: {p['POSTER_ID']}")
    return selected

# ---------------------------------------------------------------------------
# Page heading
# ---------------------------------------------------------------------------

st.subheader("Submit a request")
st.write("Use this form to submit corrections, attribution requests, or takedown notices. All requests are reviewed by an admin before any changes are made.")

request_label = st.radio("What would you like to do?", options=REQUEST_TYPES.keys(), index=None)
request_type = REQUEST_TYPES.get(request_label)

# ---------------------------------------------------------------------------
# "TAKEDOWN" flow
# ---------------------------------------------------------------------------

if request_type == "TAKEDOWN":

    st.info("This will permanently remove the selected poster(s) from the archive. If you'd prefer to keep them listed with proper credit, consider submitting an attribution request instead.")

    selected_posters = poster_picker(poster_labels, key="takedown")

    permission = st.checkbox("I am the rights holder of these posters", disabled=not selected_posters)

    notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help")

    submit = st.button("Submit request", type="primary", icon=":material/send:")

    if submit and not selected_posters: st.error("Please select at least one poster.")
    elif submit and not permission: st.error("You must be a rights holder to submit a takedown request.")
    elif submit:
        save_request(S, request_type="TAKEDOWN", entity_type="POSTER", scope="SPECIFIC", poster_ids=[poster_labels[s]["POSTER_ID"] for s in selected_posters], current_value=None, requested_value=None, notes=notes.strip() if notes and notes.strip() else None)
        st.success("Request submitted. It will be reviewed by an admin.")

# ---------------------------------------------------------------------------
# "ATTRIBUTION" flow
# ---------------------------------------------------------------------------

if request_type == "ATTRIBUTION":

    st.info("Community members may upload posters they believe have cultural value to the archive, though these may sometimes miss details like the correct designer attribution. If you are a rights holder to a poster, use this form to authorise us to remove the community upload flag and correct the designer attribution if needed.")

    community_labels = {l: p for l, p in poster_labels.items() if p["UPLOAD_TYPE"] == "COMMUNITY"}

    selected_posters = poster_picker(community_labels, key="attribution")

    if selected_posters:
        selected_data = [community_labels[s] for s in selected_posters]
        designers = [p["DESIGNER_NAME"] for p in selected_data]
        unknown_count = designers.count("UNKNOWN")
        named_designers = sorted(set(d for d in designers if d != "UNKNOWN"))

        if unknown_count == len(selected_data):
            st.warning(f"All {unknown_count} selected poster(s) are attributed to an UNKNOWN designer.")
        elif unknown_count:
            st.warning(f"{unknown_count} of {len(selected_data)} selected poster(s) are attributed to an UNKNOWN designer. The rest are attributed to: {', '.join(named_designers)}.")
        else:
            st.info(f"Selected poster(s) are attributed to: {', '.join(named_designers)}.")

    designer_name = st.selectbox("Correct designer name (optional)", options=all_designers, index=None, accept_new_options=True, disabled=not selected_posters, placeholder="Select existing or type a new name")

    permission = st.checkbox("I am the rights holder of these posters", disabled=not selected_posters)

    notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help")

    submit = st.button("Submit request", type="primary", icon=":material/send:")

    if submit and not selected_posters: st.error("Please select at least one poster.")
    elif submit and not permission: st.error("You must be a rights holder to submit an attribution request.")
    elif submit:
        save_request(S, request_type="ATTRIBUTION", entity_type="DESIGNER", scope="SPECIFIC", poster_ids=[community_labels[s]["POSTER_ID"] for s in selected_posters], current_value=None, requested_value=normalise(designer_name) if designer_name else None, notes=notes.strip() if notes and notes.strip() else None)
        st.success("Request submitted. It will be reviewed by an admin.")

# ---------------------------------------------------------------------------
# "CORRECTION" flow
# ---------------------------------------------------------------------------

if request_type == "CORRECTION":
    st.info("Use this form to correct a misspelled or incorrect band, venue, or designer name. You can apply the correction to all posters or just specific ones.")

    entity_label = st.radio("What needs correcting?", options=ENTITY_TYPES.keys())
    entity_type = ENTITY_TYPES.get(entity_label)
    entity_options = {"BAND": all_bands, "VENUE": all_venues, "DESIGNER": [d for d in all_designers if d != "UNKNOWN"]}.get(entity_type, [])

    current_value = st.selectbox(f"Which {entity_label.lower()}?", options=entity_options, index=None)

    if current_value:
        count = sum(1 for p in all_posters if poster_has(p, entity_type, current_value))
        st.info(f"There {'is' if count == 1 else 'are'} {count} poster{'s' if count != 1 else ''} with this {entity_label.lower()} in the archive.")

        scope_label = st.radio("How should this be applied?", options=["Change all instances in the archive", "Only change specific posters"])

        if scope_label == "Only change specific posters":
            relevant_labels = {l: p for l, p in poster_labels.items() if poster_has(p, entity_type, current_value)}
            selected_posters = poster_picker(relevant_labels, key="correction")

        corrected_value = st.selectbox("What should it be changed to?", options=[o for o in entity_options if o != current_value], index=None, accept_new_options=True, placeholder="Select existing or type a new name")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help")

        submit = st.button("Submit request", type="primary", icon=":material/send:")

        scope = "GLOBAL" if scope_label == "Change all instances in the archive" else "SPECIFIC"
        poster_ids = [relevant_labels[s]["POSTER_ID"] for s in selected_posters] if scope == "SPECIFIC" and selected_posters else None

        if submit and not corrected_value: st.error("Please enter a corrected value.")
        elif submit and scope == "SPECIFIC" and not poster_ids: st.error("Please select at least one poster.")
        elif submit:
            save_request(S, request_type="CORRECTION", entity_type=entity_type, scope=scope, poster_ids=poster_ids, current_value=normalise(current_value), requested_value=normalise(corrected_value), notes=notes.strip() if notes and notes.strip() else None)
            st.success("Request submitted. It will be reviewed by an admin.")
