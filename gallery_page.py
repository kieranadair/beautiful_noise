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

COMMUNITY_HELP = (
    "This was submitted as a community upload. If you are the rights holder and would "
    "like it removed or amended, please submit a correction or request."
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
    with c2: credit_filter = st.multiselect("Poster by", options=all_credits)
    with c3: venue_filter = st.multiselect("Venues", options=all_venues)
    with c4: month_range_filter = st.select_slider("Dates", options=months, value=(months[0], months[-1]), format_func=month_fmt)
    headline_only = st.toggle("Headline shows only", disabled=not band_filter) if band_filter else False
    # Community filter — a single-select pill acting as a show/hide toggle.
    # Streamlit pills have no per-widget colour and no stable "selected" CSS hook, so we
    # colour it ourselves: wrap it in a keyed container (exposed as `.st-key-community-filter`)
    # and inject scoped CSS whose greys follow the Python on/off state. Off = lighter than the
    # page background so the control recedes; on = a slightly darker muted grey. A visible
    # label gives the `help` tooltip its (?) anchor; the pill itself stays icon-only.
    with st.container(key="community-filter"):
        _sel = st.pills("Show community uploads", options=["community"], default="community", key="community_pills", format_func=lambda o: ":material/groups:", help="Shared by community members for historic value without permission from rights holder")
    show_community = _sel is not None
    _bg, _bd, _fg = ("#e3e3e3", "#d0d0d0", "#444444") if show_community else ("#f7f7f7", "#e9e9e9", "#b0b0b0")
    st.html(
        "<style>"
        f".st-key-community-filter [data-testid='stBaseButton-pills']{{background:{_bg}!important;border-color:{_bd}!important;color:{_fg}!important;}}"
        f".st-key-community-filter [data-testid='stBaseButton-pills']:hover{{background:{_bd}!important;border-color:{_bd}!important;color:{_fg}!important;}}"
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
                        if st.button(" ", type="tertiary", icon=":material/visibility:", key=f"view_{o['POSTER_ID']}"): show_poster(o)
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
        st.header(", ".join(headliners))
        if supports: st.subheader(", ".join(supports))
        if poster["EVENT_NAME"]: st.subheader(poster["EVENT_NAME"])
        st.write(f"**Poster by:** {', '.join(poster['CREDITS']) if poster['CREDITS'] else '*UNKNOWN*'}")
        st.write(f"**Date:** {poster['DATE'].strftime('%d %B %Y').upper()}")
        st.write(f"**Venue:** {poster['VENUE_NAME']}")
        st.caption(f"Poster ID: {poster['POSTER_ID']}")
        st.space(size="medium")
        st.page_link("contact_page.py", label="Submit a correction or request removal", icon=":material/edit:", query_params={"poster": poster["POSTER_ID"]})
        if poster["UPLOAD_TYPE"] == "COMMUNITY": st.badge("Community upload", icon=":material/groups:", color="yellow", help=COMMUNITY_HELP)

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
