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

COMMUNITY_HELP = (
    "This was submitted as a community upload. If you are the rights holder and would "
    "like it removed or amended, please submit a correction or request."
)

# Explainer for what a community upload is — parked here for a future FAQ page, since the
# gallery filter no longer surfaces it as a tooltip.
COMMUNITY_UPLOAD_EXPLAINER = (
    "These are posters submitted by members of the community for historic value, but not "
    "explicitly shared by the rights holder."
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
    # Community filter — a single-select pill acting as a show/hide toggle. The label is
    # hidden (a fuller explanation will live on a future FAQ page — see
    # COMMUNITY_UPLOAD_EXPLAINER). Streamlit pills have no per-widget colour, so we scope CSS
    # to the keyed container (`.st-key-community-filter`): the unselected pill is a muted grey
    # (lighter than the page background, so it recedes) and the selected pill keeps the theme
    # red but dimmed via opacity — Streamlit tags the selected button's testid ...Active.
    with st.container(key="community-filter"):
        _sel = st.pills("Show community uploads", options=["community"], default="community", key="community_pills", format_func=lambda o: ":material/groups: Show community uploads", label_visibility="collapsed")
    show_community = _sel is not None
    st.html(
        "<style>"
        ".st-key-community-filter [data-testid='stBaseButton-pills']{background:#f7f7f7!important;border-color:#e9e9e9!important;color:#b0b0b0!important;}"
        ".st-key-community-filter [data-testid='stBaseButton-pills']:hover{background:#efefef!important;border-color:#e0e0e0!important;}"
        ".st-key-community-filter [data-testid$='Active']{opacity:0.7!important;}"
        "</style>"
    )

    filtered_posters = get_filtered_posters(all_posters, band_filter, venue_filter, credit_filter, month_range_filter, headline_only, show_community)

    st.divider()

    # --- Empty state ---
    if not filtered_posters:
        st.info("No posters match your filters." if (band_filter or venue_filter or credit_filter or month_range_filter) else "No posters uploaded yet.")
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
                        if o["UPLOAD_TYPE"] == "COMMUNITY":
                            st.markdown(":material/groups:")
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
        if poster["UPLOAD_TYPE"] == "COMMUNITY": st.badge("Community upload", icon=":material/groups:", color="yellow", help=COMMUNITY_HELP)
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
