import streamlit as st


st.set_page_config(layout="wide", page_title="Beautiful Noise", page_icon=":material/music_note:", initial_sidebar_state="collapsed")

st.markdown("""<style>
[data-testid="stSidebar"] { display: none; }
span[data-baseweb="tag"] > span:first-child { max-width: none !important; overflow: visible !important; }
</style>""", unsafe_allow_html=True)

# Set up naviation
gallery = st.Page("gallery_page.py", title="Gallery")
upload  = st.Page("upload_page.py",  title="Upload")
contact = st.Page("contact_page.py", title="Contact")
terms_of_service = st.Page("terms_of_service.py", title="Terms of Service")
pg = st.navigation([gallery, upload, contact, terms_of_service])

# Logo
primary = st.get_option("theme.primaryColor")
secondary = st.get_option("theme.linkColor")
st.write(f':color[BEAUTIFUL]{{foreground={primary}}}NOISE :color[| NAARM GIG POSTER ARCHIVE]{{foreground={secondary}}}')

# Header content
st.title(f"I took a walk down :color[memory lane...]{{foreground={primary}}}")
text = """
**Beautiful Noise** is a living, community-driven archive of posters from Naarm's live music scene — it's aim is to capture and preserve the vibrancy, creativity, and magic behind this art.

Every week, new gig posters decorate this city's street — bold, strange, and beautiful - born from the same underground talent that fills the stages. They are the visual pulse of our scene. Passion over polish, community over algorithm, reflecting the talent and diversity of the bands they promote.

But posters are ephemeral by nature. Torn down, pasted over, forgotten once the music fades. Without care, this rich visual history will disappear — and with it, the memory of the culture it represents.

This project exists to change that. To pull these works off the street (and away from the mercy of the algorithm), and into an independent archive that endures. A place where the art that backs up the music is preserved, celebrated, and given the recognition it deserves — not just for now, but for everyone who comes after.
"""
st.write(text)

# Run pages
pg.run()

# Footer setion
st.space("small")
st.caption("By using Beautiful Noise, you agree to our [Terms of Service](/terms_of_service). Uploaded content remains © the original creator. Archive content is shared under CC BY-NC 4.0 — free to share with credit, no commercial use. Need something corrected or removed? [Submit a request](/contact_page).")
