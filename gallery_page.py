import streamlit as st
from config import NAV_BTN_WIDTH
from db import get_session, get_all_posters
from utils import get_filtered_posters, get_poster_vars, month_range


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
    with c2: venue_filter = st.multiselect("Venues", options=all_venues)
    with c3: designer_filter = st.multiselect("Designers", options=all_designers)
    with c4: month_range_filter = st.select_slider("Dates", options=months, value=(months[0], months[-1]), format_func=month_fmt)

    filtered_posters = get_filtered_posters(all_posters, band_filter, venue_filter, designer_filter, month_range_filter)

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
                    if st.button(" ", type="tertiary", icon=":material/visibility:", key=f"view_{o['FILE_NAME']}"):
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
        if poster["BANDS"]:
            st.header(", ".join([b for b in poster["BANDS"]]))
        if poster["EVENT_NAME"]:
            st.subheader(poster["EVENT_NAME"])
        if poster["DATE"]:
            st.markdown(f"**Date:** {poster['DATE']:%d/%m/%Y}")
        if poster["VENUE_NAME"]:
            st.markdown(f"**Venue:** {poster['VENUE_NAME']}")
        if poster["DESIGNER_NAME"]:
            st.markdown(f"**Designer:** {poster['DESIGNER_NAME']}")

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

S = get_session()

if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", width=NAV_BTN_WIDTH):
    st.switch_page("upload_page.py")

st.divider()

# ---------------------------------------------------------------------------
# Data: poster cache, filter options, date range
# ---------------------------------------------------------------------------

all_posters = get_all_posters(S)
all_bands, all_venues, all_designers, date_min, date_max = get_poster_vars(all_posters)
months = month_range(date_min, date_max)

# ---------------------------------------------------------------------------
# Page heading + grid
# ---------------------------------------------------------------------------

primary = st.get_option("theme.primaryColor")
secondary = st.get_option("theme.secondaryBackgroundColor")
st.subheader(f'Browse :color[{len(all_posters)} posters]{{background={primary} foreground={secondary}}} by {len(all_designers)} artists for {len(all_bands)} bands at {len(all_venues)} venues')

poster_grid(all_posters, all_bands, all_venues, all_designers, months)
