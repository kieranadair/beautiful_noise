import json
from datetime import date
import streamlit as st
from core.config import NAV_BTN_WIDTH
from core.db import get_all_posters, save_request
from core.utils import get_poster_vars, normalise, poster_has, md_escape

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

if st.button("BACK TO GALLERY", icon=":material/chevron_backward:", width=NAV_BTN_WIDTH):
    st.switch_page("views/gallery.py")

st.divider()

# ---------------------------------------------------------------------------
# Data: session, poster cache, filter options
# ---------------------------------------------------------------------------

ss = st.session_state

# Widget-generation counter, the same idiom views/upload.py uses for its uploader. Every widget on
# this page derives its key from it, so bumping it once discards the whole form at a stroke.
#
# This is what makes submission behave the same however the visitor arrived. The poster selectbox
# used to carry no key at all, and Streamlit hashes a keyless widget's arguments — `index`
# included — into its element ID. Arriving from a gallery share link set `index` to a number;
# st.query_params.clear() on submit made it None again, which changed the ID, which silently threw
# the selection away and collapsed the entire form. Arriving without the link left `index` None
# throughout, so nothing reset and a fully populated form sat under the confirmation. Same code,
# two different outcomes, decided by the URL.
#
# Bound once per run rather than re-read at each use: a mid-run change would leave widgets
# disagreeing about which generation they belong to.
form_key = ss.setdefault("request_form_key", 0)

all_posters = get_all_posters()
# The venue list is deliberately dropped. Corrections type the new value as free text now, so the
# only readers left are LINEUP_EDIT (bands) and the authorisation flow (credits).
all_bands, _, all_credits, _, _ = get_poster_vars(all_posters)

# ---------------------------------------------------------------------------
# Constants & lookup maps
# ---------------------------------------------------------------------------

poster_labels = {f"{p['POSTER_ID']} — {', '.join(p['BANDS'][:2])} — {', '.join(p['VENUES'])} — {p['DATE']:%d %b %Y}": p for p in all_posters}

REQUEST_TYPES = {
    "Authorise a community upload (I'm the rights holder)": "ATTRIBUTION",
    "Request a poster takedown": "TAKEDOWN",
    "Correct a band, venue, poster credit or event name": "CORRECTION",
    "Correct the date on a poster": "DATE_CORRECTION",
    "Add/remove a band from a lineup, or change the headliner/support ordering": "LINEUP_EDIT",
}

ENTITY_TYPES = {"Band": "BAND", "Venue": "VENUE", "Poster credit": "CREDIT", "Event name": "EVENT"}

# Sentinel offered alongside a poster's existing credits so "add another" is reachable from the
# same picker as "correct this one". Lower case on purpose: every stored value goes through
# normalise() and is upper case, so this can never collide with a real credit.
ADD_CREDIT = "(add a new poster credit)"

# Bounds for the date correction. st.date_input otherwise defaults to ±10 years around the value
# it is given, which for an archive is the wrong shape entirely: a poster the scanner read as 2026
# could only be corrected to 2016–2036, so the one case most needing correction — a misread year —
# was the case it refused. Posters advertise gigs a little ahead, hence the future headroom.
DATE_MIN = date(1950, 1, 1)
DATE_MAX = date(date.today().year + 2, 12, 31)

# Shared tail for every submission-success banner. We don't collect contact
# details (no email/PII), so this sets expectations: review is manual and the
# only way to see the outcome is to check the gallery.
REVIEW_NOTICE = "Requests are reviewed by hand (usually within a few days) and approved changes appear in the gallery automatically. We don't collect contact details, so check back in the gallery to see the update."

GRID_COLUMNS = 5

def finish_request(message: str) -> None:
    """Record the confirmation, discard the form, and rerun.

    Bumping the generation counter is what actually clears the page — st.rerun() on its own
    re-renders the same widgets with the same keys and the same values, which is why a submitted
    form used to stay filled in and re-submittable."""
    ss["request_submitted"] = f"{message} {REVIEW_NOTICE}"
    ss["request_form_key"] = ss.get("request_form_key", 0) + 1
    st.query_params.clear()
    st.rerun()

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
st.write("Use this form to submit corrections, attribution requests, or takedown notices. There's no sign-in and we don't collect contact details — every request is reviewed by hand before any change is made, and approved changes appear in the gallery automatically.")

poster_param = st.query_params.get("poster")
default_index = None
if poster_param:
    for i, label in enumerate(poster_labels):
        if label.startswith(f"{poster_param} —"):
            default_index = i
            break

primary_label = st.selectbox("Which poster is this about?", options=poster_labels.keys(), index=default_index, help="Search by poster id, band, venue and date", key=f"primary_poster_{form_key}")
primary_poster = poster_labels.get(primary_label)

if primary_poster:
    # Widget keys inside this block carry the poster id as well as the generation counter.
    # Streamlit ignores `default`, `value` and `options` once a widget has a key
    # (key_as_main_identity), so a key that named only the generation would hand the previously
    # selected poster's lineup, credits and date to the poster now on screen — stale values,
    # silently, with the right poster pictured above them.
    pk = f"{form_key}_{primary_poster['POSTER_ID']}"

    with st.container(border=True):
        img_col, detail_col = st.columns([1, 2], gap="large")
        with img_col:
            st.image(primary_poster["URL"])
        with detail_col:
            st.write(f"**Headliners:** {', '.join(md_escape(x) for x in primary_poster['HEADLINERS'])}")
            st.write(f"**Supports:** {', '.join(md_escape(x) for x in primary_poster['SUPPORTS']) if primary_poster['SUPPORTS'] else ''}")
            st.write(f"**Event:** {md_escape(primary_poster['EVENT_NAME']) if primary_poster['EVENT_NAME'] else ''}")
            st.write(f"**{'Venues' if len(primary_poster['VENUES']) > 1 else 'Venue'}:** {', '.join(md_escape(v) for v in primary_poster['VENUES'])}")
            st.write(f"**Date:** {primary_poster['DATE']:%d %B %Y}")
            st.write(f"**Poster By:** {', '.join(md_escape(x) for x in primary_poster['CREDITS']) if primary_poster['CREDITS'] else 'Unknown'}")
            # Type and ID are ordinary rows like every other field. They were a yellow
            # st.warning and a small st.caption, borrowed from the gallery modal where a
            # badge earns its emphasis — here it read as a problem with the poster rather
            # than a description of it, and the caption made the ID look like a footnote
            # when it's the thing a request is filed against. Type now shows for both
            # upload kinds: a field that appears only sometimes is the inconsistency.
            upload_label = "Community Upload" if primary_poster["UPLOAD_TYPE"] == "COMMUNITY" else "Shared with creator's permission"
            st.write(f"**Type:** {upload_label}")
            st.write(f"**ID:** {primary_poster['POSTER_ID']}")

    # -------------------------------------------------------------------
    # Step 2: Select an action
    # -------------------------------------------------------------------

    request_label = st.radio("What would you like to do?", options=REQUEST_TYPES.keys(), index=None, key=f"request_type_{form_key}")
    request_type = REQUEST_TYPES.get(request_label)

    # -------------------------------------------------------------------
    # "TAKEDOWN" flow
    # -------------------------------------------------------------------

    if request_type == "TAKEDOWN":

        st.info("This will permanently remove the selected poster(s) from the archive. If you'd prefer to keep them listed with proper credit, consider submitting an attribution request instead.", icon=":material/info:")

        additional_labels = {l: p for l, p in poster_labels.items() if l != primary_label}
        add_more = st.checkbox("Add additional posters to this request", key=f"takedown_more_{form_key}")
        extra_selected = poster_picker(additional_labels, key=f"takedown_{pk}", pinned=[primary_poster]) if add_more else []

        all_ids = [primary_poster["POSTER_ID"]] + [poster_labels[s]["POSTER_ID"] for s in extra_selected]

        permission = st.checkbox(f"I am the rights holder of {'these posters' if len(all_ids) > 1 else 'this poster'}", key=f"takedown_rights_{form_key}")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key=f"takedown_notes_{form_key}")

        submit = st.button("Submit request", type="primary", icon=":material/send:", key=f"takedown_submit_{form_key}")

        if submit and not permission: st.error("You must be a rights holder to submit a takedown request.")
        elif submit:
            save_request(request_type="TAKEDOWN", entity_type="POSTER", scope="SPECIFIC", poster_ids=all_ids, current_value=None, requested_value=None, notes=notes.strip() if notes and notes.strip() else None)
            finish_request("Takedown request submitted.")

    # -------------------------------------------------------------------
    # "ATTRIBUTION" flow
    # -------------------------------------------------------------------

    if request_type == "ATTRIBUTION":

        # Only a community upload has anything to authorise. The extras picker below has always
        # filtered to COMMUNITY; the poster chosen at the top of the page never was, so an
        # already-authorised poster could be authorised a second time.
        if primary_poster["UPLOAD_TYPE"] != "COMMUNITY":
            st.info("This poster is already shown as shared with the creator's permission, so there's nothing to authorise here. If the poster credits need changing, use \"Correct a band, venue, poster credit or event name\" instead.", icon=":material/info:")

        else:
            st.info("Community members may upload posters they believe have cultural value to the archive. If you are a rights holder, use this form to have your poster shown as shared with your permission. Attribution is the point of this flow, so at least one poster credit is required — the credits below apply to every poster in the request.", icon=":material/info:")

            additional_labels = {l: p for l, p in poster_labels.items() if l != primary_label and p["UPLOAD_TYPE"] == "COMMUNITY"}
            add_more = st.checkbox("Add additional posters to this request", key=f"attribution_more_{form_key}")
            extra_selected = poster_picker(additional_labels, key=f"attribution_{pk}", pinned=[primary_poster]) if add_more else []

            all_selected = [primary_poster] + [poster_labels[s] for s in extra_selected]
            all_ids = [p["POSTER_ID"] for p in all_selected]

            # Pre-filled from whatever the poster already carries, so an existing credit is amended
            # rather than retyped. Same control and label as the upload form's "Poster By".
            credits = st.multiselect("Poster By", options=all_credits, default=sorted(primary_poster["CREDITS"]), accept_new_options=True, help="Designers, photographers, illustrators — anyone credited on the poster.", key=f"attribution_credits_{pk}")

            permission = st.checkbox(f"I am the rights holder of {'these posters' if len(all_ids) > 1 else 'this poster'}", key=f"attribution_rights_{form_key}")

            notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key=f"attribution_notes_{form_key}")

            submit = st.button("Submit request", type="primary", icon=":material/send:", key=f"attribution_submit_{form_key}")

            if submit:
                credits_n = sorted({n for c in credits if (n := normalise(c))})
                if not permission:
                    st.error("You must be a rights holder to submit an attribution request.")
                elif not credits_n:
                    # The same rule the upload form applies to rights-holder uploads
                    # (views/upload.py). Flipping a poster to "shared with creator's permission"
                    # without recording who made it defeats the purpose of the flip.
                    st.error("Authorised uploads require at least one poster credit — please add who made the poster.")
                else:
                    # entity_type stays DESIGNER: it is what marks this request as the upload-type
                    # flip rather than an ordinary credit correction. JSON in the value columns
                    # follows the LINEUP_EDIT precedent below.
                    save_request(request_type="ATTRIBUTION", entity_type="DESIGNER", scope="SPECIFIC", poster_ids=all_ids, current_value=json.dumps(sorted(primary_poster["CREDITS"])), requested_value=json.dumps(credits_n), notes=notes.strip() if notes and notes.strip() else None)
                    finish_request("Attribution request submitted.")

    # -------------------------------------------------------------------
    # "CORRECTION" flow
    # -------------------------------------------------------------------

    if request_type == "CORRECTION":
        st.info("Use this form to correct a misspelled or incorrect band, venue, poster credit, or event name. You can apply the correction to all posters or just specific ones.", icon=":material/info:")

        poster_bands = sorted(primary_poster["BANDS"])
        poster_venues = sorted(primary_poster["VENUES"])
        poster_credits = sorted(primary_poster["CREDITS"])

        # index=None to match the action radio above it. Defaulting to "Band" rendered the band
        # fields the instant CORRECTION was picked, as though a choice had already been made.
        entity_label = st.radio("What needs correcting?", options=ENTITY_TYPES.keys(), index=None, key=f"correction_entity_{form_key}")
        entity_type = ENTITY_TYPES.get(entity_label)

        if entity_type == "EVENT":
            current_value = primary_poster.get("EVENT_NAME") or ""
            st.write(f"Current event name: **{md_escape(current_value)}**" if current_value else "This poster has no event name set.")

            corrected_value = st.text_input("Correct event name", placeholder="Enter the correct event name", key=f"correction_event_{pk}")

            notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key=f"correction_event_notes_{form_key}")

            submit = st.button("Submit request", type="primary", icon=":material/send:", key=f"correction_event_submit_{form_key}")

            if submit and not normalise(corrected_value): st.error("Please enter a corrected value.")
            elif submit and normalise(corrected_value) == normalise(current_value): st.error("The corrected value is the same as the current one.")
            elif submit:
                save_request(request_type="CORRECTION", entity_type="EVENT", scope="SPECIFIC", poster_ids=[primary_poster["POSTER_ID"]], current_value=normalise(current_value), requested_value=normalise(corrected_value), notes=notes.strip() if notes and notes.strip() else None)
                finish_request("Correction request submitted.")

        elif entity_type:
            # BAND, VENUE and CREDIT are all multi-valued on a poster, so each needs a "which one?"
            # picker. VENUE used to be shown as fixed text because a poster could only have one; a
            # day-party poster can name several.
            scoped_options = {"BAND": poster_bands, "VENUE": poster_venues, "CREDIT": poster_credits}[entity_type]

            # CREDIT is the only one of the three a poster can legitimately have none of — bands
            # and venues are required at upload. With no options the picker rendered empty,
            # `current_value` stayed None and every field below it was unreachable, so a missing
            # credit could never be added. Adding is offered whether or not credits already exist.
            can_add = entity_type == "CREDIT"

            if can_add and not scoped_options:
                st.write("This poster has no poster credit yet.")
                current_value, adding = None, True
            else:
                picked = st.selectbox(f"Which {entity_label.lower()}?", options=scoped_options + ([ADD_CREDIT] if can_add else []), index=None, key=f"correction_target_{pk}")
                adding = picked == ADD_CREDIT
                current_value = None if adding else picked

            if adding or current_value:
                # Applying an addition to other posters makes no sense — it is this poster's
                # missing credit, not a name shared across the archive — so scope stays SPECIFIC
                # and the scope picker never renders.
                scope, poster_ids = "SPECIFIC", [primary_poster["POSTER_ID"]]

                if not adding:
                    additional_count = sum(1 for p in all_posters if poster_has(p, entity_type, current_value)) - 1
                    scope_options = ["Only change this poster", f"Select additional posters that mention {current_value}", f"Change all posters that mention {current_value}"]
                    # Defined unconditionally: it used to be built only inside the branch that
                    # renders the picker, while the code computing poster_ids read it whenever a
                    # selection existed. Correct only by luck.
                    relevant_labels = {l: p for l, p in poster_labels.items() if poster_has(p, entity_type, current_value) and l != primary_label}
                    selected_posters = []

                    if additional_count > 0:
                        st.info(f"There {'is' if additional_count == 1 else 'are'} {additional_count} additional poster{'s' if additional_count != 1 else ''} with **{md_escape(current_value)}** in the archive.")

                        scope_label = st.radio("How should this be applied?", options=scope_options, key=f"correction_scope_{pk}")

                        if scope_label == scope_options[2]:
                            matching = [p for p in poster_labels.values() if poster_has(p, entity_type, current_value)]
                            preview_cols = st.columns(GRID_COLUMNS, gap="large")
                            for i, p in enumerate(matching):
                                with preview_cols[i % GRID_COLUMNS]:
                                    st.image(p["URL"])
                                    st.caption(f"ID: {p['POSTER_ID']}")
                            scope, poster_ids = "GLOBAL", None

                        elif scope_label == scope_options[1]:
                            selected_posters = poster_picker(relevant_labels, key=f"correction_{pk}", pinned=[primary_poster])
                            poster_ids = ([primary_poster["POSTER_ID"]] + [relevant_labels[s]["POSTER_ID"] for s in selected_posters]) if selected_posters else None

                if adding:
                    corrected_value = st.text_input("Poster credit to add", placeholder="Designer, photographer or illustrator", key=f"correction_add_{pk}")
                else:
                    corrected_value = st.text_input(f"What should **{md_escape(current_value)}** be changed to?", placeholder="Enter the correct name", key=f"correction_value_{pk}")

                notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key=f"correction_notes_{form_key}")

                submit = st.button("Submit request", type="primary", icon=":material/send:", key=f"correction_submit_{form_key}")

                if submit:
                    requested = normalise(corrected_value)
                    if not requested:
                        st.error("Please enter a corrected value." if not adding else "Please enter a poster credit.")
                    elif requested == current_value:
                        st.error("The corrected value is the same as the current one.")
                    elif scope == "SPECIFIC" and not poster_ids:
                        st.error("Please select at least one poster.")
                    else:
                        save_request(request_type="CORRECTION", entity_type=entity_type, scope=scope, poster_ids=poster_ids, current_value=current_value, requested_value=requested, notes=notes.strip() if notes and notes.strip() else None)
                        finish_request("Correction request submitted.")

    # -------------------------------------------------------------------
    # "DATE_CORRECTION" flow
    # -------------------------------------------------------------------

    if request_type == "DATE_CORRECTION":
        st.info("Use this form to correct the date on this poster.", icon=":material/info:")

        current_date = primary_poster.get("DATE")
        st.write(f"Current date: **{current_date:%d %B %Y}**" if current_date else "This poster has no date set.")

        corrected_date = st.date_input("Correct date", value=current_date, format="DD/MM/YYYY", min_value=DATE_MIN, max_value=DATE_MAX, key=f"date_value_{pk}")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key=f"date_notes_{form_key}")

        submit = st.button("Submit request", type="primary", icon=":material/send:", key=f"date_submit_{form_key}")

        if submit and corrected_date == current_date: st.error("The corrected date is the same as the current date.")
        elif submit:
            save_request(request_type="CORRECTION", entity_type="DATE", scope="SPECIFIC", poster_ids=[primary_poster["POSTER_ID"]], current_value=str(current_date) if current_date else None, requested_value=str(corrected_date), notes=notes.strip() if notes and notes.strip() else None)
            finish_request("Date correction submitted.")

    # -------------------------------------------------------------------
    # "LINEUP_EDIT" flow
    # -------------------------------------------------------------------

    if request_type == "LINEUP_EDIT":
        st.info("Use this form to add or remove bands from a lineup, or adjust which bands are headliners vs support acts.", icon=":material/info:")

        # Every known band, plus this poster's own, so a band not yet attached to any other poster
        # is still selectable.
        all_options = sorted(set(all_bands) | set(primary_poster["BANDS"]))

        headliners = st.multiselect("Headliners", options=all_options, default=sorted(primary_poster["HEADLINERS"]), accept_new_options=True, key=f"le_headliners_{pk}")
        supports = st.multiselect("Support Acts", options=all_options, default=sorted(primary_poster["SUPPORTS"]), accept_new_options=True, key=f"le_supports_{pk}")

        notes = st.text_area("Notes (optional)", placeholder="Any extra context that might help", key=f"le_notes_{form_key}")

        submit = st.button("Submit request", type="primary", icon=":material/send:", key=f"le_submit_{form_key}")

        if submit:
            headliners_n = [normalise(b) for b in headliners]
            supports_n = [normalise(b) for b in supports]
            overlap = set(headliners_n) & set(supports_n)

            if overlap:
                st.error(f"These bands appear in both lists: {', '.join(md_escape(b) for b in sorted(overlap))}. Please fix before submitting.")
            elif not headliners_n:
                st.error("At least one band must be a headliner.")
            elif len(headliners_n) != len(set(headliners_n)):
                st.error("Duplicate bands found in headliners.")
            elif len(supports_n) != len(set(supports_n)):
                st.error("Duplicate bands found in supports.")
            else:
                requested = json.dumps({"headliners": sorted(headliners_n), "supports": sorted(supports_n)})
                current = json.dumps({"headliners": sorted(primary_poster["HEADLINERS"]), "supports": sorted(primary_poster["SUPPORTS"])})
                save_request(request_type="CORRECTION", entity_type="BILLING", scope="SPECIFIC", poster_ids=[primary_poster["POSTER_ID"]], current_value=current, requested_value=requested, notes=notes.strip() if notes and notes.strip() else None)
                finish_request("Lineup edit request submitted.")

# ---------------------------------------------------------------------------
# Submission confirmation
# ---------------------------------------------------------------------------
# Rendered last, so it lands below the form the reader just submitted rather than at the
# top of the page. It used to be near the page heading, which meant the confirmation for an
# action taken at the bottom of a long form appeared off-screen above it, reading as though
# nothing happened.
#
# finish_request() has already bumped the generation counter by the time this draws, so the form
# above really is empty — the same clean slate whether the visitor arrived from a share link or
# picked a poster by hand.
#
# pop() rather than read: it shows once, then clears, so it doesn't reappear on the next
# unrelated rerun.
if "request_submitted" in ss:
    st.success(ss.pop("request_submitted"), icon=":material/check_circle:")
