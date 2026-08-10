import json
import streamlit as st
from core.config import NAV_BTN_WIDTH
from core.db import get_session, get_all_posters
from core.utils import get_filtered_posters, get_poster_vars, month_range, md_escape

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", width=NAV_BTN_WIDTH):
    st.switch_page("views/upload.py")

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
# show_poster() passes it to the contact page, which reads it to preselect (views/contact.py).

def clear_poster_param() -> None:
    """Drop ?poster= so closing the dialog resets the URL, ready for the next poster."""
    if "poster" in st.query_params:
        del st.query_params["poster"]

def poster_label(poster: dict) -> str:
    """Accessible label for the invisible overlay button. CSS hides it visually, but screen
    readers still announce it, so it must be escaped like any other widget label."""
    names = poster["HEADLINERS"] or poster["BANDS"]
    return f"View {md_escape(', '.join(names))} at {md_escape(poster['VENUE_NAME'])}"

COPY_LABEL = "Share poster"

def copy_link_button(url: str, poster_id) -> None:
    """One-click 'copy to clipboard' button for a poster's share URL.

    Streamlit has no native clipboard action, so this is the sanctioned escape hatch: st.html with
    inline JS (see CLAUDE.md). It can't be an st.button — the Clipboard API only works inside the
    user-gesture that triggered it, and a Streamlit button's handler runs on the *rerun* after the
    click, by which point the gesture is gone and the write is blocked.

    Both interpolated values go through json.dumps, so they land as JS string literals rather than
    as concatenated source. The values here are app-generated (st.context.url and an integer id),
    but building JS by raw f-string is a habit worth not forming.
    """
    btn_id = f"bn-share-{poster_id}"
    st.html(
        # Styled to read as a link, not a button — it sits directly above the contact page_link
        # and should match its weight and size. Font size is pinned to 1rem (== theme
        # baseFontSize) rather than inherited: `font: inherit` picked up a much larger size from
        # whatever wrapper st.html lands in, and rendered at roughly heading scale.
        "<style>"
        ".bn-share{display:inline-flex;align-items:center;gap:.5rem;font-family:inherit;"
        "font-size:1rem;font-weight:400;line-height:1.6;color:inherit;background:transparent;"
        "border:none;padding:0;margin:0;cursor:pointer;}"
        ".bn-share svg{width:1.15em;height:1.15em;flex:none;}"
        ".bn-share:hover{opacity:.7;}"
        "</style>"
        f"<button class='bn-share' id='{btn_id}' type='button'>"
        "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor'"
        " stroke-width='2' stroke-linecap='round' aria-hidden='true'>"
        "<path d='M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5'/>"
        "<path d='M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.5-1.5'/></svg>"
        f"<span aria-live='polite'>{COPY_LABEL}</span></button>"
        "<script>(function(){"
        f"var b=document.getElementById({json.dumps(btn_id)}),u={json.dumps(url)},"
        f"L={json.dumps(COPY_LABEL)};"
        "if(!b||b.dataset.bound)return;b.dataset.bound='1';"
        "var s=b.querySelector('span');"
        "b.addEventListener('click',function(){"
        "var done=function(ok){s.textContent=ok?'Link copied':'Copy failed';"
        "setTimeout(function(){s.textContent=L;},2000);};"
        "if(navigator.clipboard&&window.isSecureContext){"
        "navigator.clipboard.writeText(u).then(function(){done(true);},function(){done(false);});"
        "return;}"
        # Fallback for non-secure contexts (e.g. plain-http local runs), where the Clipboard API
        # is unavailable. Deprecated, but still widely supported.
        "try{var t=document.createElement('textarea');t.value=u;t.style.position='fixed';"
        "t.style.opacity='0';document.body.appendChild(t);t.select();"
        "var ok=document.execCommand('copy');document.body.removeChild(t);done(ok);}"
        "catch(e){done(false);}"
        "});})();</script>",
        unsafe_allow_javascript=True,
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
    # The overlay is targeted via its OWN keyed container (`poster-hit-`), never by matching on
    # Streamlit's internal DOM. An earlier version positioned
    # `[data-testid="stElementContainer"]:has(button)` and broke the whole grid: st.image renders
    # its own fullscreen button, so that selector caught the *image's* wrapper too, pulled it out
    # of flow, and collapsed every card to zero height. Keyed containers are a documented,
    # stable hook — internal testids are not, so nothing load-bearing should depend on them.
    primary = st.get_option("theme.primaryColor")
    st.html(
        "<style>"
        '[class*="st-key-poster-card-"]{position:relative;cursor:pointer;}'
        # Hit layer fills the card and sits above the image (including its fullscreen control,
        # which would otherwise swallow clicks near the top-right corner).
        '[class*="st-key-poster-hit-"]{position:absolute;inset:0;z-index:10;}'
        # Streamlit nests the button in wrapper divs; each needs full height for the click target
        # to reach the bottom of the poster rather than just the top few pixels.
        '[class*="st-key-poster-hit-"] > div,'
        '[class*="st-key-poster-hit-"] [data-testid="stElementContainer"],'
        '[class*="st-key-poster-hit-"] [data-testid="stButton"]{height:100%;}'
        '[class*="st-key-poster-hit-"] button'
        "{width:100%;height:100%;opacity:0;cursor:pointer;border:none;}"
        # Hover affordance — the actual fix for "clicking this is confusing".
        '[class*="st-key-poster-card-"] [data-testid="stImage"]{transition:filter .15s ease;}'
        '[class*="st-key-poster-card-"]:hover [data-testid="stImage"]{filter:brightness(0.88);}'
        # Focus ring goes on the card: the button itself is transparent, so its own ring is
        # invisible. Purely cosmetic — if :has() ever fails here, layout is unaffected.
        f'[class*="st-key-poster-card-"]:has(button:focus-visible)'
        f"{{outline:3px solid {primary};outline-offset:3px;}}"
        "</style>"
    )

    st.caption(":material/ads_click: Click any poster to view its details")
    st.space("small")

    for row_start in range(0, len(visible_posters), GALLERY_COLUMNS):
        cols = st.columns(GALLERY_COLUMNS, gap="medium")
        for i, c in enumerate(cols):
            idx = row_start + i
            if idx < len(visible_posters):
                o = visible_posters[idx]
                # gap="xxsmall" pulls the rights-holder tick up close to the poster it describes;
                # the container's default "small" (1rem) left them looking unrelated.
                with c.container(gap="xxsmall"):
                    with st.container(key=f"poster-card-{o['POSTER_ID']}"):
                        st.image(o["URL"])
                        # Own keyed container so the CSS can position the hit layer without
                        # guessing at Streamlit's internals. If the CSS ever stops matching this
                        # degrades to a visible text button under the poster — still usable.
                        with st.container(key=f"poster-hit-{o['POSTER_ID']}"):
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

@st.dialog("Poster details", width="large", on_dismiss=clear_poster_param)
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
        # Both badges are grey: they label provenance, not status. Green read as a success signal
        # and gave rights-holder posters an endorsement the archive doesn't intend.
        if poster["UPLOAD_TYPE"] == "RIGHTS_HOLDER": st.badge("Shared with creator's permission", icon=":material/check_circle:", color="grey", help=RIGHTS_HOLDER_HELP)
        else: st.badge("Community upload", icon=":material/groups:", color="grey", help=COMMUNITY_HELP)
        # The two actions sit together as a pair, separated from the metadata above them.
        st.space(size="medium")
        copy_link_button(f"{st.context.url}?poster={poster['POSTER_ID']}", poster["POSTER_ID"])
        contact_label = "Authorise, submit a correction or request removal" if poster["UPLOAD_TYPE"] == "COMMUNITY" else "Submit a correction or request removal"
        st.page_link("views/contact.py", label=contact_label, icon=":material/edit:", query_params={"poster": poster["POSTER_ID"]})

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
