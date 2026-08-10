import streamlit as st


st.set_page_config(layout="wide", page_title="Beautiful Noise", page_icon=":material/music_note:")

# Multiselect tags truncate their label by default, but the gallery filters and upload form carry
# long band and venue names — let the tags size to their content instead.
st.html(
    "<style>"
    'span[data-baseweb="tag"] > span:first-child{max-width:none!important;overflow:visible!important;}'
    "</style>"
)

# Set up navigation. position="hidden" drops the nav widget outright — nothing else in the app
# writes to the sidebar, so no sidebar renders at all and each page supplies its own nav buttons.
gallery = st.Page("gallery_page.py", title="Gallery")
upload  = st.Page("upload_page.py",  title="Upload")
contact = st.Page("contact_page.py", title="Contact")
terms_of_service = st.Page("terms_of_service.py", title="Terms of Service")
pg = st.navigation([gallery, upload, contact, terms_of_service], position="hidden")

# Logo
primary = st.get_option("theme.primaryColor")
secondary = st.get_option("theme.linkColor")
st.write(f':color[BEAUTIFUL]{{foreground={primary}}}NOISE :color[| GIG POSTER ARCHIVE]{{foreground={secondary}}}')

# Header content
st.title(f"I took a walk down :color[memory lane...]{{foreground={primary}}}")
text = """
**Beautiful Noise** is a living, community-driven archive of posters from Narrm's live music scene — its aim is to capture and preserve the vibrancy, creativity, and magic behind this art.

Every week, new gig posters decorate this city's streets — bold, strange, and beautiful — born from the same underground talent that fills its stages. They are the visual pulse of our scene, and reflect the talent and diversity of the bands they promote.

But posters are ephemeral by nature. Torn down, pasted over, lost to time once the show's over. Without care, this rich visual history will disappear — and with it, the memory of the culture it represents.

This project exists to change that. To pull these works off the street (and away from the mercy of the algorithm) and into an independent archive that endures. A place where this art can be preserved, celebrated, and given the recognition it deserves — not just for now, but for everyone who comes after.
"""
st.write(text)

# Run pages
pg.run()

# FAQ (light, conversational help — opens a dialog from the footer)
@st.dialog("Frequently Asked Questions", width="large")
def show_faq():
    st.write(open("faq.md").read())

# Footer section — flows with the page. Deliberately NOT in st.bottom: st.bottom pins to the
# viewport, and the terms/licensing notice doesn't need to follow the reader down a long gallery.
st.space("small")
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    if st.button("Learn more about Beautiful Noise", icon=":material/help:", type="tertiary"):
        show_faq()
    st.caption("By using Beautiful Noise, you agree to our [Terms of Service](/terms_of_service). Uploaded content remains © the original creator. Archive content is shared under CC BY-NC 4.0 — free to share with credit, no commercial use. Need something corrected or removed? [Submit a request](/contact_page).")

# --- TEMPORARY: soft-launch notice -----------------------------------------------------------
# Pinned to the viewport with st.bottom so it stays visible while browsing — this is the one
# thing in the app that genuinely benefits from following the reader. Remove this whole block
# (and nothing else) once the archive is out of its launch period, ~September 2026.
with st.bottom:
    st.info(
        "**Beautiful Noise has just launched.** The archive is new and still finding its feet, so "
        "you may hit the odd rough edge. Spotted a bug, or got a suggestion? "
        "[Message us on Instagram](https://www.instagram.com/beautifulnoise.melbourne) — we'd love to hear from you.",
        icon=":material/rocket_launch:",
    )
