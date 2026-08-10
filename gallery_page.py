import streamlit as st
from config import NAV_BTN_WIDTH
from db import get_session, get_all_posters
from utils import get_filtered_posters, get_poster_vars, month_range, md_escape

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", width=NAV_BTN_WIDTH):
    st.switch_page("upload_page.py")

st.divider()

# ---------------------------------------------------------------------------
# Constants & session state
# ---------------------------------------------------------------------------

GALLERY_COLUMNS = 5
ss = st.session_state
if "limit" not in ss: ss["limit"] = (GALLERY_COLUMNS * 3)

RIGHTS_HOLDER_HELP = (
    "The uploader told us they made this poster or hold the rights to it. If that's not the "
    "case, please submit a request to have it corrected or removed."
)

COMMUNITY_HELP = (
    "Shared by a community member for its historical value — the creator hasn't signed off on "
    "it. If that's you, you can authorise it (to have it shown as shared with your permission) "
    "or request its removal."
)

# Explainer for the community-vs-rights-holder distinction — parked here for the FAQ, since the
# gallery filter surfaces only a short label.
COMMUNITY_UPLOAD_EXPLAINER = (
    "Posters shared by community members for their historical value, rather than by the rights "
    "holder directly."
)

# ---------------------------------------------------------------------------
# Poster deep-linking (?poster=<id>)
# ---------------------------------------------------------------------------
# A single source of truth drives the detail dialog: the `poster` query param. Clicking a poster
# sets it; arriving on a shared link already has it. Both paths then run the same code, so the
# dialog can't get out of step with the URL. `poster` already means "this poster" app-wide —
# show_poster() passes it to the contact page, which reads it to preselect (contact_page.py).

def clear_poster_param() -> None:
    """Drop ?poster= so closing the dialog resets the URL, ready for the next poster."""
    if "poster" in st.query_params:
        del st.query_params["poster"]

def poster_label(poster: dict) -> str:
    """Accessible label for the invisible overlay button. CSS hides it visually, but screen
    readers still announce it, so it must be escaped like any other widget label."""
    names = poster["HEADLINERS"] or poster["BANDS"]
    return f"View {md_escape(', '.join(names))} at {md_escape(poster['VENUE_NAME'])}"

# ---------------------------------------------------------------------------
# Fragment: poster grid (filters, thumbnails, pagination)
# ---------------------------------------------------------------------------

@st.fragment
def poster_grid(all_posters, all_bands, all_venues, all_credits, months):

    # --- Filters (all client-side on cached data) ---
    month_fmt = lambda d: d.strftime("%b %Y")
    c1, c2, c3, c4 = st.columns(4)
    with c1: band_filter  = st.multiselect("Bands", options=all_bands)
    with c2: credit_filter = st.multiselect("Poster By", options=all_credits)
    with c3: venue_filter = st.multiselect("Venues", options=all_venues)
    with c4: month_range_filter = st.select_slider("Dates", options=months, value=(months[0], months[-1]), format_func=month_fmt)
    headline_only = st.toggle("Headline shows only", disabled=not band_filter) if band_filter else False
    # Rights-holder filter — an opt-in single-select pill. Off by default (everything shows);
    # selecting it hides community uploads so only rights-holder-shared posters remain. The label
    # is hidden (fuller explanation lives in the FAQ — see COMMUNITY_UPLOAD_EXPLAINER). Streamlit
    # pills have no per-widget colour, so we scope CSS to the keyed container
    # (`.st-key-rights-holder-filter`): the unselected pill is a muted grey (lighter than the page
    # background, so it recedes) and the selected pill keeps the theme red but dimmed via opacity —
    # Streamlit tags the selected button's testid ...Active.
    with st.container(key="rights-holder-filter"):
        _sel = st.pills("Shared with creator's permission", options=["rights_holder"], default=None, key="rights_holder_pills", format_func=lambda o: ":material/check_circle: Shared with creator's permission", label_visibility="collapsed")
    show_community = _sel is None
    st.html(
        "<style>"
        ".st-key-rights-holder-filter [data-testid='stBaseButton-pills']{background:#f7f7f7!important;border-color:#e9e9e9!important;color:#b0b0b0!important;}"
        ".st-key-rights-holder-filter [data-testid='stBaseButton-pills']:hover{background:#efefef!important;border-color:#e0e0e0!important;}"
        ".st-key-rights-holder-filter [data-testid$='Active']{opacity:0.7!important;}"
        "</style>"
    )

    filtered_posters = get_filtered_posters(all_posters, band_filter, venue_filter, credit_filter, month_range_filter, headline_only, show_community)

    st.divider()

    # --- Empty state ---
    if not filtered_posters:
        st.info("No posters match your filters." if (band_filter or venue_filter or credit_filter or month_range_filter or not show_community) else "No posters uploaded yet.")
        st.stop()

    # --- Thumbnail grid ---
    visible_posters = filtered_posters[:ss["limit"]]

    # Make the poster itself the click target. Each card is a keyed container (Streamlit turns
    # `key` into an `st-key-<key>` class) holding the image plus a full-bleed transparent button
    # laid over it. One attribute selector styles every card, so this stays a single CSS block
    # rather than one rule per poster. A *button* — not a link — is what makes this work: a click
    # is an ordinary rerun, so it never navigates, never starts a fresh session, and never loses
    # pagination or filter state. Any href-based approach reloads the app and drops both.
    primary = st.get_option("theme.primaryColor")
    st.html(
        "<style>"
        '[class*="st-key-poster-card-"]{position:relative;cursor:pointer;}'
        # The button's element wrapper is what carries the flow height, so position that (not just
        # the <button>) to keep the card's height equal to the image's.
        '[class*="st-key-poster-card-"] [data-testid="stElementContainer"]:has(button)'
        "{position:absolute;inset:0;z-index:2;margin:0;}"
        '[class*="st-key-poster-card-"] button{width:100%;height:100%;opacity:0;cursor:pointer;}'
        # Hover affordance — the actual fix for "clicking this is confusing".
        '[class*="st-key-poster-card-"] [data-testid="stImage"]{transition:filter .15s ease;}'
        '[class*="st-key-poster-card-"]:hover [data-testid="stImage"]{filter:brightness(0.88);}'
        # Focus ring goes on the card: the button itself is transparent, so its own ring is invisible.
        f'[class*="st-key-poster-card-"]:has(button:focus-visible)'
        f"{{outline:3px solid {primary};outline-offset:3px;}}"
        "</style>"
    )

    for row_start in range(0, len(visible_posters), GALLERY_COLUMNS):
        cols = st.columns(GALLERY_COLUMNS, gap="medium")
        for i, c in enumerate(cols):
            idx = row_start + i
            if idx < len(visible_posters):
                o = visible_posters[idx]
                with c.container():
                    with st.container(key=f"poster-card-{o['POSTER_ID']}"):
                        st.image(o["URL"])
                        # Falls back to a visible text button under the poster if the CSS above
                        # ever stops matching — degraded, but still fully usable.
                        if st.button(poster_label(o), key=f"view_{o['POSTER_ID']}", type="tertiary"):
                            st.query_params["poster"] = str(o["POSTER_ID"])
                            st.rerun()
                    # Outside the keyed card, so it can never sit over the button's hit area.
                    if o["UPLOAD_TYPE"] == "RIGHTS_HOLDER":
                        st.markdown(":material/check_circle:")
        st.space("small")

    # --- Pagination ---
    if ss["limit"] < len(filtered_posters):
        st.space("small")
        if st.button("Load more", type="primary", icon=":material/expand_more:", width=NAV_BTN_WIDTH):
            ss["limit"] += (GALLERY_COLUMNS * 3)
            st.rerun(scope="fragment")

# ---------------------------------------------------------------------------
# Fragment: poster detail dialog
# ---------------------------------------------------------------------------

@st.dialog("Poster details", width="large", icon=":material/visibility:", on_dismiss=clear_poster_param)
def show_poster(poster):
    left, right = st.columns([1, 1])
    with left:
        st.image(poster["URL"])
    with right:
        headliners = poster["HEADLINERS"] if poster["HEADLINERS"] else poster["BANDS"]
        supports = poster["SUPPORTS"] if poster["HEADLINERS"] else []
        st.header(", ".join(md_escape(h) for h in headliners))
        if supports: st.subheader(", ".join(md_escape(s) for s in supports))
        if poster["EVENT_NAME"]: st.subheader(md_escape(poster["EVENT_NAME"]))
        st.write(f"**Poster By:** {', '.join(md_escape(c) for c in poster['CREDITS']) if poster['CREDITS'] else '*UNKNOWN*'}")
        st.write(f"**Date:** {poster['DATE'].strftime('%d %B %Y').upper()}")
        st.write(f"**Venue:** {md_escape(poster['VENUE_NAME'])}")
        if poster["UPLOAD_TYPE"] == "RIGHTS_HOLDER": st.badge("Shared with creator's permission", icon=":material/check_circle:", color="green", help=RIGHTS_HOLDER_HELP)
        else: st.badge("Community upload", icon=":material/groups:", color="grey", help=COMMUNITY_HELP)
        st.caption(f"Poster ID: {poster['POSTER_ID']}")
        st.space(size="medium")
        contact_label = "Authorise, submit a correction or request removal" if poster["UPLOAD_TYPE"] == "COMMUNITY" else "Submit a correction or request removal"
        st.page_link("contact_page.py", label=contact_label, icon=":material/edit:", query_params={"poster": poster["POSTER_ID"]})

# ---------------------------------------------------------------------------
# Data: poster cache, filter options, date range
# ---------------------------------------------------------------------------

S = get_session()

all_posters = get_all_posters(S)
all_bands, all_venues, all_credits, date_min, date_max = get_poster_vars(all_posters)
months = month_range(date_min, date_max)

# ---------------------------------------------------------------------------
# Page heading + grid
# ---------------------------------------------------------------------------

primary = st.get_option("theme.primaryColor")
secondary = st.get_option("theme.secondaryBackgroundColor")
st.subheader(f'Browse :color[{len(all_posters)} posters]{{background={primary} foreground={secondary}}} for {len(all_bands)} bands by {len(all_credits)} creators at {len(all_venues)} venues')

# Open the detail dialog whenever ?poster=<id> is set — whether a click put it there or someone
# followed a shared link. Runs outside the fragment so it survives fragment-scoped reruns.
# Query params are always strings, hence the str() comparison.
if (requested_poster := st.query_params.get("poster")):
    match = next((p for p in all_posters if str(p["POSTER_ID"]) == requested_poster), None)
    if match:
        show_poster(match)
    else:
        # Hand-edited or stale id (e.g. the poster has since been taken down) — drop it and
        # render the gallery as normal rather than erroring.
        clear_poster_param()

poster_grid(all_posters, all_bands, all_venues, all_credits, months)
