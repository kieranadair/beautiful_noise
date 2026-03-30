import streamlit as st
from config import NAV_BTN_WIDTH
from db import get_session, get_all_posters
from utils import get_filtered_posters, get_poster_vars, month_range

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

# ---------------------------------------------------------------------------
# Fragment: poster grid (filters, thumbnails, pagination)
# ---------------------------------------------------------------------------

@st.fragment
def poster_grid(all_posters, all_bands, all_venues, all_designers, months):

    # --- Filters (all client-side on cached data) ---
    month_fmt = lambda d: d.strftime("%b %Y")
    c1, c2, c3, c4 = st.columns(4)
    with c1: band_filter  = st.multiselect("Bands", options=all_bands)
    with c2: designer_filter = st.multiselect("Designers", options=all_designers)
    with c3: venue_filter = st.multiselect("Venues", options=all_venues)
    with c4: month_range_filter = st.select_slider("Dates", options=months, value=(months[0], months[-1]), format_func=month_fmt)

    filtered_posters = get_filtered_posters(all_posters, band_filter, venue_filter, designer_filter, month_range_filter)

    poster_param = st.query_params.get("poster")
    if poster_param:
        st.query_params.clear()
        match = next((p for p in all_posters if str(p["POSTER_ID"]) == poster_param), None)
        if match:
            show_poster(match)

    st.divider()

    # --- Empty state ---
    if not filtered_posters:
        st.info("No posters match your filters." if (band_filter or venue_filter or designer_filter or month_range_filter) else "No posters uploaded yet.")
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
                    if st.button(" ", type="tertiary", icon=":material/visibility:", key=f"view_{o['POSTER_ID']}"):
                        show_poster(o)
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

@st.fragment
@st.dialog(":material/visibility:", width="large")
def show_poster(poster):
    left, right = st.columns([1, 1])
    with left:
        st.image(poster["URL"])
    with right:
        st.header(", ".join([b for b in poster["BANDS"]]))
        if poster["EVENT_NAME"]:
            st.subheader(poster["EVENT_NAME"])
        st.write(f"**Designer:** {poster['DESIGNER_NAME']}")
        st.write(f"**Date:** {poster['DATE']:%d %B %Y}")
        st.write(f"**Venue:** {poster['VENUE_NAME']}")
        st.caption(f"Poster ID: {poster['POSTER_ID']}")
        st.code(f"https://beautifulnoise.streamlit.app/?poster={poster['POSTER_ID']}", language=None, width="content")
        st.page_link("contact_page.py", label="Submit a correction or request", icon=":material/edit:")
        st.space(size="small")
        if poster["UPLOAD_TYPE"] == "COMMUNITY":
            st.warning("This poster was uploaded by a community member for its historical and cultural value. If you are the rights holder and would like it removed, please [submit a request](/contact).", icon=":material/info:")

# ---------------------------------------------------------------------------
# Data: poster cache, filter options, date range
# ---------------------------------------------------------------------------

S = get_session()

all_posters = get_all_posters(S)
all_bands, all_venues, all_designers, date_min, date_max = get_poster_vars(all_posters)
months = month_range(date_min, date_max)

# ---------------------------------------------------------------------------
# Page heading + grid
# ---------------------------------------------------------------------------

primary = st.get_option("theme.primaryColor")
secondary = st.get_option("theme.secondaryBackgroundColor")
st.subheader(f'Browse :color[{len(all_posters)} posters]{{background={primary} foreground={secondary}}} for {len(all_bands)} bands by {len(all_designers)} designers at {len(all_venues)} venues')

poster_grid(all_posters, all_bands, all_venues, all_designers, months)
