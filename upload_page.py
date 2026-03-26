import hashlib
from pathlib import Path
from io import BytesIO
import streamlit as st
from config import STAGE
from db import get_session, get_all_posters, save_poster, upload_to_stage, log_processed
from ai import run_extraction, is_valid_poster, parse_extraction
from utils import normalise, fuzzy_match, infer_date, preprocess_image, pdf_to_image_bytes, get_poster_vars, prepare_review_defaults, prepare_save_data, check_duplicate_md5, check_semantic_duplicate
UPLOAD_CSS = """<style>
span[data-baseweb="tag"] > span:first-child { max-width: none !important; overflow: visible !important; }
</style>
"""
def reset_upload():
    for k in ("result", "saved"):
        ss.pop(k, None)
    ss["upload_key"] += 1


ss = st.session_state
if "upload_key" not in ss: ss["upload_key"] = 0

st.markdown(UPLOAD_CSS, unsafe_allow_html=True)

# CTA Section
h_cols = st.columns(5)
with h_cols[0]:
    if st.button("VIEW GALLERY", use_container_width=True, icon=":material/chevron_backward:"):
        st.switch_page("gallery_page.py")

st.divider()

S = get_session()
all_posters = get_all_posters(S)
all_bands, all_venues, all_designers, date_min, date_max = get_poster_vars(all_posters)

st.subheader("Upload a poster to get started")

left, right = st.columns(2, gap="large")

with left:
    img = st.file_uploader("Upload a gig poster", type=["jpg", "jpeg", "png", "webp", "pdf"], key=f"uploader_{ss['upload_key']}", label_visibility="collapsed", disabled="result" in ss)
    
    if "upload_error" in ss:
        st.error(ss.pop("upload_error"))

    # Stage 3: review form
    has_result = "result" in ss
    r = ss.get("result", {})
    form_disabled = not has_result or ss.get("saved", False)

    band_options = sorted(set(all_bands + r.get("matched_bands", [])))
    venue_options = sorted(set(all_venues + ([r["matched_venue"]] if r.get("matched_venue") else [])))

    with st.form(f"poster_details_{ss['upload_key']}"):
        st.subheader("Poster Details")
        bands = st.multiselect("Bands / Artists", options=band_options, default=r.get("matched_bands", []), accept_new_options=True, disabled=form_disabled)
        event_date = st.date_input("Event Date", value=r.get("inferred_date"), format="DD/MM/YYYY", disabled=form_disabled)
        venue = st.selectbox("Venue", options=venue_options, index=venue_options.index(r["matched_venue"]) if r.get("matched_venue") in venue_options else None, accept_new_options=True, disabled=form_disabled)
        event_name = st.text_input("Event Name", value=r.get("normed_event_name", ""), placeholder="Leave empty if not a named event", disabled=form_disabled)
        designer_name = st.selectbox("Designer", options=sorted(set(all_designers + ["UNKNOWN"])), index=None, accept_new_options=True, disabled=form_disabled)
        permission = st.checkbox("I have the right to share this poster and agree to the [Terms of Service](/terms_of_service)", disabled=form_disabled)
        submitted = st.form_submit_button("Save Poster ✓", type="primary", disabled=form_disabled)

    if submitted and not permission:
        st.error("Please confirm you have permission before saving.")
    elif submitted and (not bands or not venue):
       st.error("Please ensure both the bands and venues are filled in.")
    elif submitted and not designer_name:
        st.warning("Please select or enter a designer. If unknown, choose 'UNKNOWN' from the list.")

    elif submitted:
        if check_semantic_duplicate(bands, venue, event_date, all_posters):
            ss["upload_error"] = "A poster with these bands, venue, and date already exists."
            reset_upload()
            st.rerun()
        else:
            with st.spinner("Saving... Please don't close this page."):
                save_poster(S=S, file_name=r["target"], md5_hash=r["md5_hash"], **prepare_save_data(bands, event_date, venue, event_name, designer_name))
                get_all_posters.clear()
                ss["saved"] = True
                st.rerun()

    if ss.get("saved"):
        st.success("Poster saved! Thanks for contributing to the archive.")
        if st.button("Upload another poster", type="primary", icon=":material/add:", width="stretch"):
            ss.pop("processed_img", None)
            reset_upload()
            st.rerun()
        if st.button("View it in the gallery", width="stretch", icon=":material/chevron_backward:"):
            ss.pop("processed_img", None)
            reset_upload()
            st.switch_page("gallery_page.py")


# Image preview
with right:
    
    # Stage 1 & 2: process image + AI extraction (runs once per upload)
    if img and "result" not in ss:
        with st.status("Hold tight while we analyse this poster...", expanded=True) as status:
            st.write("Processing image...")
            if Path(img.name).suffix.lower() == ".pdf":
                img = pdf_to_image_bytes(img)
            ss["processed_img"] = preprocess_image(img, "JPEG")
            md5_hash = hashlib.md5(ss["processed_img"].getvalue(), usedforsecurity=False).hexdigest()
            if check_duplicate_md5(md5_hash, all_posters):
                ss["upload_error"] = "This poster has already been uploaded."
                ss["upload_key"] += 1
                st.rerun()
            target = upload_to_stage(S, ss["processed_img"], ".jpg")

            st.write("Analysing image...")
            result = run_extraction(S, target)
            if not is_valid_poster(result):
                ss["upload_error"] = "That doesn't look like a gig poster — please try again."
                ss["upload_key"] += 1
                st.rerun()

            st.write("Getting suggestions from database...")
            bands, date_str, venue, event_name = parse_extraction(result)
            matched_bands, inferred_date, matched_venue, normed_event_name = prepare_review_defaults(bands, date_str, venue, event_name, all_bands, all_venues)
            log_processed(S, target, bands, date_str, venue, event_name, matched_bands, inferred_date, matched_venue, normed_event_name)

            ss["result"] = {
                "target": target,
                "md5_hash": md5_hash,
                "matched_bands": matched_bands,
                "inferred_date": inferred_date,
                "matched_venue": matched_venue,
                "normed_event_name": normed_event_name,
            }

            status.update(label="Analysis complete!", state="complete", expanded=False)
            st.rerun()
    
    if "processed_img" in ss:
        st.image(ss["processed_img"])
        if "result" not in ss:
            ss.pop("processed_img", None)
