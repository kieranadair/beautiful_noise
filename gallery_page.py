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
        _sel = st.pills("Shared with permission only", options=["rights_holder"], default=None, key="rights_holder_pills", format_func=lambda o: ":material/check_circle: Shared with permission only", label_visibility="collapsed")
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

    st.caption(":material/visibility: Click the eye to view poster details")
    st.space("small")

    for row_start in range(0, len(visible_posters), GALLERY_COLUMNS):
        cols = st.columns(GALLERY_COLUMNS, gap="large")
        for i, c in enumerate(cols):
            idx = row_start + i
            if idx < len(visible_posters):
                o = visible_posters[idx]
                with c.container():
                    st.image(o["URL"])
                    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                        if st.button(" ", type="tertiary", icon=":material/visibility:", key=f"view_{o['POSTER_ID']}", help="Click to view"): show_poster(o)
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

@st.dialog(":material/visibility:", width="large")
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
        st.page_link("contact_page.py", label="Submit a correction or request removal", icon=":material/edit:", query_params={"poster": poster["POSTER_ID"]})

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

poster_grid(all_posters, all_bands, all_venues, all_credits, months)
