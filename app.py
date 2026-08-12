import logging
import streamlit as st
from core.config import FAVICON, CONTENT_DIR, NAV_BTN_WIDTH


st.set_page_config(layout="wide", page_title="Beautiful Noise", page_icon=FAVICON)

# Multiselect tags truncate their label by default, but the gallery filters and upload form carry
# long band and venue names — let the tags size to their content instead.
st.html(
    "<style>"
    'span[data-baseweb="tag"] > span:first-child{max-width:none!important;overflow:visible!important;}'
    "</style>"
)

# Set up navigation. position="hidden" drops the nav widget outright — nothing else in the app
# writes to the sidebar, so no sidebar renders at all and each page supplies its own nav buttons.
# url_path pins each slug to what it was before the files moved into views/. Without it the slug
# is inferred from the filename, so renaming would silently break every /poster_requests and
# /terms_of_service link in the copy — and any URL a visitor has already shared.
gallery = st.Page("views/gallery.py", title="Gallery")
upload  = st.Page("views/upload.py",  title="Upload", url_path="upload_page")
requests_page = st.Page("views/poster_requests.py", title="Poster Requests", url_path="poster_requests")
terms_of_service = st.Page("views/terms.py", title="Terms of Service", url_path="terms_of_service")
pg = st.navigation([gallery, upload, requests_page, terms_of_service], position="hidden")

# Global header — CTA and wordmark, rendered above whichever page runs below. The pages read
# theme.linkColor for themselves where they need it; only the wordmark needs primaryColor here.
primary = st.get_option("theme.primaryColor")

if st.button("ARCHIVE A POSTER", type="primary", icon=":material/add:", width=NAV_BTN_WIDTH):
    st.switch_page("views/upload.py")

st.title(f":color[BEAUTIFUL]{{foreground={primary}}} NOISE")

# Run pages.
#
# Wrapped so a crash inside a page shows our own words rather than Streamlit's built-in notice,
# which mentions redacted error messages and Streamlit Cloud — neither of which means anything to
# someone here to look at gig posters. The exception propagates out of pg.run(), so catching it
# here covers every page without touching any of them.
#
# logging.exception is the load-bearing half: --client.showErrorDetails=none means the browser
# shows nothing diagnostic, so the traceback has to reach the Railway logs or the error is simply
# lost. Never replace this with a bare message.
try:
    pg.run()
except Exception:
    logging.exception("Unhandled error while running page: %s", getattr(pg, "title", "unknown"))
    st.error(
        "Oh no. This app has encountered an error. If it continues, please "
        "[message us on Instagram](https://www.instagram.com/beautifulnoise.melbourne) "
        "so we can investigate.",
        icon=":material/error:",
    )

# FAQ (light, conversational help — opens a dialog from the footer)
@st.dialog("Frequently Asked Questions", width="large")
def show_faq():
    st.write((CONTENT_DIR / "faq.md").read_text(encoding="utf-8"))

# Footer section — flows with the page. Deliberately NOT in st.bottom: st.bottom pins to the
# viewport, and the terms/licensing notice doesn't need to follow the reader down a long gallery.
st.space("small")
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    if st.button("Learn more about Beautiful Noise", icon=":material/help:", type="tertiary"):
        show_faq()
    st.caption("By using Beautiful Noise, you agree to our [Terms of Service](/terms_of_service). Uploaded content remains © the original creator. Archive content is shared under CC BY-NC 4.0 — free to share with credit, no commercial use. Need something corrected or removed? [Submit a request](/poster_requests).")

# Maker credit, on its own line at the very bottom — the usual spot for one. Deliberately "Made
# by" rather than a © line: the caption above already assigns copyright to uploaders, and a second
# © against a different name would muddy that.
st.caption("Made by Kieran Adair")
