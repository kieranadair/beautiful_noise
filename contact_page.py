import json
import streamlit as st
from config import NAV_BTN_WIDTH
from db import get_session, get_all_posters, save_request
from utils import get_poster_vars, normalise, poster_has, md_escape

# ---------------------------------------------------------------------------
# Navigation (two buttons side by side)
# ---------------------------------------------------------------------------

if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", width=NAV_BTN_WIDTH):
    st.switch_page("upload_page.py")
if st.button("VIEW GALLERY", icon=":material/chevron_backward:", width=NAV_BTN_WIDTH):
    st.switch_page("gallery_page.py")

st.divider()

# ---------------------------------------------------------------------------
# Data: session, poster cache, filter options
# ---------------------------------------------------------------------------

S = get_session()
all_posters = get_all_posters(S)
all_bands, all_venues, all_credits, _, _ = get_poster_vars(all_posters)

# ---------------------------------------------------------------------------
# Constants & lookup maps
# ---------------------------------------------------------------------------

poster_labels = {f"{p['POSTER_ID']} — {', '.join(p['BANDS'][:2])} — {p['VENUE_NAME']} — {p['DATE']:%d %b %Y}": p for p in all_posters}

REQUEST_TYPES = {
    "Authorise a community upload (I'm the rights holder)": "ATTRIBUTION",
    "Request a poster takedown": "TAKEDOWN",
    "Correct a band, venue, poster credit or event name": "CORRECTION",
    "Correct the date on a poster": "DATE_CORRECTION",
    "Add/remove a band from a lineup, or change the headliner/support ordering": "LINEUP_EDIT",
}

ENTITY_TYPES = {"Band": "BAND", "Venue": "VENUE", "Poster credit": "CREDIT", "Event name": "EVENT"}

GRID_COLUMNS = 5

def poster_picker(labels, key="default", help_text="Search by poster id, band, venue and date", pinned=None):
    selected = st.multiselect("Which poster(s)?", options=labels, help=help_text, key=f"picker_{key}")
    preview = (pinned or []) + [labels[s] for s in selected]
    if preview:
        cols = st.columns(GRID_COLUMNS, gap="large")
        for i, p in enumerate(preview):
            with cols[i % GRID_COLUMNS]:
                st.image(p["URL"])
                st.caption(f"ID: {p['POSTER_ID']}")
    return selected

# ---------------------------------------------------------------------------
# Step 1: Select a poster
# ---------------------------------------------------------------------------

st.subheader("Submit a request")
st.write("Use this form to submit corrections, attribution requests, or takedown notices. All requests are reviewed by an admin before any changes are made.")

if "request_submitted" in st.session_state:
    st.success(st.session_state.pop("request_submitted"))

poster_param = st.query_params.get("poster")
default_index = None
if poster_param:
    for i, label in enumerate(poster_labels):
        if label.startswith(f"{poster_param} —"):
            default_index = i
            break

primary_label = st.selectbox("Which poster is this about?", options=poster_labels.keys(), index=default_index, help="Search by poster id, band, venue and date")
primary_poster = poster_labels.get(primary_label)

if primary_poster:
    with st.container(border=True):
        img_col, detail_col = st.columns([1, 2], gap="large")
        with img_col:
            st.image(primary_poster["URL"])
        with detail_col:
            st.write(f"**Headliners:** {', '.join(md_escape(x) for x in primary_poster['HEADLINERS'])}")
            st.write(f"**Supports:** {', '.join(md_escape(x) for x in primary_poster['SUPPORTS']) if primary_poster['SUPPORTS'] else ''}")
            st.write(f"**Event:** {md_escape(primary_poster['EVENT_NAME']) if primary_poster['EVENT_NAME'] else ''}")
            st.write(f"**Venue:** {md_escape(primary_poster['VENUE_NAME'])}")
            st.write(f"**Date:** {primary_poster['DATE']:%d %B %Y}")
            st.write(f"**Poster By:** {', '.join(md_escape(x) for x in primary_poster['CREDITS']) if primary_poster['CREDITS'] else 'Unknown'}")
            if primary_poster["UPLOAD_TYPE"] == "COMMUNITY":
                st.warning("Community upload")
            st.caption(f"ID: {primary_poster['POSTER_ID']}")

    # -------------------------------------------------------------------
    # Step 2: Select an action
    # -------------------------------------------------------------------

    request_label = st.radio("What would you like to do?", options=REQUEST_TYPES.keys(), index=None)
    request_type = REQUEST_TYPES.get(request_label)

    # -------------------------------------------------------------------
    # "TAKEDOWN" flow
    # -------------------------------------------------------------------

    if request_type == "TAKEDOWN":

        st.info("This will permanently remove the selected poster(s) from the archive. If you'd prefer to keep them listed with proper credit, consider submitting an attribution request instead.", icon=":material/info:")

        additional_labels = {l: p for l, p in poster_labels.items() if l != primary_label}
        add_more = st.checkbox("Add additional posters to this request", key="takedown_more")
        extra_selected = poster_picker(additional_labels, key="takedown", pinned=[primary_poster]) if add_more else []

        all_ids = [primary_poster["POSTER_ID"]] + [poster_labels[s]["POSTER_ID"] for s in extra_selected]

        permission = st.checkbox("I am the rights holder of these posters")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key="takedown_notes")

        submit = st.button("Submit request", type="primary", icon=":material/send:", key="takedown_submit")

        if submit and not permission: st.error("You must be a rights holder to submit a takedown request.")
        elif submit:
            save_request(S, request_type="TAKEDOWN", entity_type="POSTER", scope="SPECIFIC", poster_ids=all_ids, current_value=None, requested_value=None, notes=notes.strip() if notes and notes.strip() else None)
            st.session_state["request_submitted"] = "Takedown request submitted. It will be reviewed by an admin."
            st.query_params.clear()
            st.rerun()

    # -------------------------------------------------------------------
    # "ATTRIBUTION" flow
    # -------------------------------------------------------------------

    if request_type == "ATTRIBUTION":

        st.info("Community members may upload posters they believe have cultural value to the archive. If you are a rights holder, use this form to authorise us to remove the community upload flag. To correct or add poster credits (designer, photographer, etc.), use the \"Correct a band, venue, poster credit or event name\" option instead.", icon=":material/info:")

        additional_labels = {l: p for l, p in poster_labels.items() if l != primary_label and p["UPLOAD_TYPE"] == "COMMUNITY"}
        add_more = st.checkbox("Add additional posters to this request", key="attribution_more")
        extra_selected = poster_picker(additional_labels, key="attribution", pinned=[primary_poster]) if add_more else []

        all_selected = [primary_poster] + [poster_labels[s] for s in extra_selected]
        all_ids = [p["POSTER_ID"] for p in all_selected]

        permission = st.checkbox("I am the rights holder of these posters")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key="attribution_notes")

        submit = st.button("Submit request", type="primary", icon=":material/send:", key="attribution_submit")

        if submit and not permission: st.error("You must be a rights holder to submit an attribution request.")
        elif submit:
            save_request(S, request_type="ATTRIBUTION", entity_type="DESIGNER", scope="SPECIFIC", poster_ids=all_ids, current_value=None, requested_value=None, notes=notes.strip() if notes and notes.strip() else None)
            st.session_state["request_submitted"] = "Attribution request submitted. It will be reviewed by an admin."
            st.query_params.clear()
            st.rerun()

    # -------------------------------------------------------------------
    # "CORRECTION" flow
    # -------------------------------------------------------------------

    if request_type == "CORRECTION":
        st.info("Use this form to correct a misspelled or incorrect band, venue, poster credit, or event name. You can apply the correction to all posters or just specific ones.", icon=":material/info:")

        poster_bands = sorted(primary_poster["BANDS"])
        poster_venue = [primary_poster["VENUE_NAME"]]
        poster_credits = sorted(primary_poster["CREDITS"])
        poster_event = [primary_poster["EVENT_NAME"]] if primary_poster.get("EVENT_NAME") else []

        entity_label = st.radio("What needs correcting?", options=ENTITY_TYPES.keys())
        entity_type = ENTITY_TYPES.get(entity_label)
        scoped_options = {"BAND": poster_bands, "VENUE": poster_venue, "CREDIT": poster_credits, "EVENT": poster_event}.get(entity_type, [])
        full_options = {"BAND": all_bands, "VENUE": all_venues, "CREDIT": all_credits, "EVENT": []}.get(entity_type, [])

        if entity_type == "EVENT":
            current_value = primary_poster.get("EVENT_NAME") or ""
            st.write(f"Current event name: **{md_escape(current_value)}**" if current_value else "This poster has no event name set.")

            corrected_value = st.text_input("Correct event name", placeholder="Enter the correct event name")

            notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key="correction_notes")

            submit = st.button("Submit request", type="primary", icon=":material/send:", key="correction_submit")

            if submit and not corrected_value: st.error("Please enter a corrected value.")
            elif submit:
                save_request(S, request_type="CORRECTION", entity_type="EVENT", scope="SPECIFIC", poster_ids=[primary_poster["POSTER_ID"]], current_value=normalise(current_value) if current_value else None, requested_value=normalise(corrected_value), notes=notes.strip() if notes and notes.strip() else None)
                st.session_state["request_submitted"] = "Correction request submitted. It will be reviewed by an admin."
                st.query_params.clear()
                st.rerun()

        else:
            if entity_type in ("BAND", "CREDIT"):
                current_value = st.selectbox(f"Which {entity_label.lower()}?", options=scoped_options, index=None)
            else:
                current_value = scoped_options[0] if scoped_options else None
                st.write(f"**{entity_label}:** {md_escape(current_value)}")

            if current_value:
                additional_count = sum(1 for p in all_posters if poster_has(p, entity_type, current_value)) - 1

                if additional_count > 0:
                    st.info(f"There {'is' if additional_count == 1 else 'are'} {additional_count} additional poster{'s' if additional_count != 1 else ''} with **{md_escape(current_value)}** in the archive.")

                    scope_options = ["Only change this poster", f"Select additional posters that mention {current_value}", f"Change all posters that mention {current_value}"]
                    scope_label = st.radio("How should this be applied?", options=scope_options)

                    if len(scope_options) > 2 and scope_label == scope_options[2]:
                        matching_labels = {l: p for l, p in poster_labels.items() if poster_has(p, entity_type, current_value)}
                        if matching_labels:
                            preview = list(matching_labels.values())
                            preview_cols = st.columns(GRID_COLUMNS, gap="large")
                            for i, p in enumerate(preview):
                                with preview_cols[i % GRID_COLUMNS]:
                                    st.image(p["URL"])
                                    st.caption(f"ID: {p['POSTER_ID']}")

                    selected_posters = []
                    if scope_label == scope_options[1]:
                        relevant_labels = {l: p for l, p in poster_labels.items() if poster_has(p, entity_type, current_value) and l != primary_label}
                        selected_posters = poster_picker(relevant_labels, key="correction", pinned=[primary_poster])
                else:
                    scope_label = None

                corrected_value = st.selectbox(f"What should **{md_escape(current_value)}** be changed to?", options=[o for o in full_options if o != current_value], index=None, accept_new_options=True, placeholder="Select existing or type a new name")

                notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key="correction_notes")

                submit = st.button("Submit request", type="primary", icon=":material/send:", key="correction_submit")

                if additional_count > 0 and scope_label == scope_options[0]:
                    scope = "SPECIFIC"
                    poster_ids = [primary_poster["POSTER_ID"]]
                elif additional_count > 0 and len(scope_options) > 2 and scope_label == scope_options[2]:
                    scope = "GLOBAL"
                    poster_ids = None
                elif additional_count > 0:
                    scope = "SPECIFIC"
                    poster_ids = ([primary_poster["POSTER_ID"]] + [relevant_labels[s]["POSTER_ID"] for s in selected_posters]) if selected_posters else None
                else:
                    scope = "SPECIFIC"
                    poster_ids = [primary_poster["POSTER_ID"]]

                if submit and not corrected_value: st.error("Please enter a corrected value.")
                elif submit and scope == "SPECIFIC" and not poster_ids: st.error("Please select at least one poster.")
                elif submit:
                    save_request(S, request_type="CORRECTION", entity_type=entity_type, scope=scope, poster_ids=poster_ids, current_value=normalise(current_value), requested_value=normalise(corrected_value), notes=notes.strip() if notes and notes.strip() else None)
                    st.session_state["request_submitted"] = "Correction request submitted. It will be reviewed by an admin."
                    st.query_params.clear()
                    st.rerun()


    # -------------------------------------------------------------------
    # "DATE_CORRECTION" flow
    # -------------------------------------------------------------------

    if request_type == "DATE_CORRECTION":
        st.info("Use this form to correct the date on this poster.", icon=":material/info:")

        current_date = primary_poster.get("DATE")
        st.write(f"Current date: **{current_date:%d %B %Y}**" if current_date else "This poster has no date set.")

        corrected_date = st.date_input("Correct date", value=current_date, format="DD/MM/YYYY")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key="date_notes")

        submit = st.button("Submit request", type="primary", icon=":material/send:", key="date_submit")

        if submit and corrected_date == current_date: st.error("The corrected date is the same as the current date.")
        elif submit:
            save_request(S, request_type="CORRECTION", entity_type="DATE", scope="SPECIFIC", poster_ids=[primary_poster["POSTER_ID"]], current_value=str(current_date) if current_date else None, requested_value=str(corrected_date), notes=notes.strip() if notes and notes.strip() else None)
            st.session_state["request_submitted"] = "Date correction submitted. It will be reviewed by an admin."
            st.query_params.clear()
            st.rerun()

    # -------------------------------------------------------------------
    # "LINEUP_EDIT" flow
    # -------------------------------------------------------------------
    
    if request_type == "LINEUP_EDIT":
        st.info(
            "Use this form to add or remove bands from a lineup, or adjust which bands are headliners vs support acts.",
            icon=":material/info:"
        )
    
        # Combine all known bands + current poster bands
        all_options = sorted(set(all_bands) | set(primary_poster["BANDS"]))
    
        headliners = st.multiselect(
            "Headliners",
            options=all_options,
            default=sorted(primary_poster["HEADLINERS"]),
            accept_new_options=True,
            key="le_headliners"
        )
    
        supports = st.multiselect(
            "Support Acts",
            options=all_options,
            default=sorted(primary_poster["SUPPORTS"]),
            accept_new_options=True,
            key="le_supports"
        )
    
        notes = st.text_area(
            "Notes (optional)",
            placeholder="Any extra context that might help",
            key="le_notes"
        )
    
        submit = st.button(
            "Submit request",
            type="primary",
            icon=":material/send:",
            key="le_submit"
        )
    
        if submit:
            # Normalise input
            headliners_n = [normalise(b) for b in headliners]
            supports_n = [normalise(b) for b in supports]
    
            overlap = set(headliners_n) & set(supports_n)
    
            if overlap:
                st.error(f"These bands appear in both lists: {', '.join(md_escape(b) for b in sorted(overlap))}. Please fix before submitting.")
    
            elif not headliners_n:
                st.error("At least one band must be a headliner.")
    
            else:
                # Deduplicate within each list
                if len(headliners_n) != len(set(headliners_n)):
                    st.error("Duplicate bands found in headliners.")
                elif len(supports_n) != len(set(supports_n)):
                    st.error("Duplicate bands found in supports.")
                else:
                    requested = json.dumps({
                        "headliners": sorted(headliners_n),
                        "supports": sorted(supports_n)
                    })
    
                    current = json.dumps({
                        "headliners": sorted(primary_poster["HEADLINERS"]),
                        "supports": sorted(primary_poster["SUPPORTS"])
                    })
    
                    save_request(
                        S,
                        request_type="CORRECTION",
                        entity_type="BILLING",
                        scope="SPECIFIC",
                        poster_ids=[primary_poster["POSTER_ID"]],
                        current_value=current,
                        requested_value=requested,
                        notes=notes.strip() if notes and notes.strip() else None
                    )
    
                    st.session_state["request_submitted"] = "Lineup edit request submitted. It will be reviewed by an admin."
                    st.query_params.clear()
                    st.rerun()