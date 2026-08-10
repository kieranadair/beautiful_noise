import hashlib
from pathlib import Path
from io import BytesIO
import streamlit as st
from core.config import STAGE, NAV_BTN_WIDTH
from core.db import get_session, get_all_posters, save_poster, upload_to_stage, log_processed
from core.ai import run_extraction, is_valid_poster, parse_extraction
from core.utils import normalise, fuzzy_match, infer_date, preprocess_image, pdf_to_image_bytes, ImageRejected, get_poster_vars, prepare_review_defaults, prepare_save_data, check_duplicate_md5, check_semantic_duplicate

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

if st.button("VIEW GALLERY", icon=":material/chevron_backward:", width=NAV_BTN_WIDTH):
    st.switch_page("views/gallery.py")

st.divider()

# ---------------------------------------------------------------------------
# Helpers & session state
# ---------------------------------------------------------------------------

def reset_upload():
    for k in ("result", "saved"):
        ss.pop(k, None)
    ss["upload_key"] += 1

ss = st.session_state
if "upload_key" not in ss: ss["upload_key"] = 0

# ---------------------------------------------------------------------------
# Data: session, poster cache, and filter options (needed for form dropdowns
# and duplicate detection — runs on every page load but is cached)
# ---------------------------------------------------------------------------

S = get_session()
all_posters = get_all_posters(S)
all_bands, all_venues, all_credits, date_min, date_max = get_poster_vars(all_posters)

# ---------------------------------------------------------------------------
# Page heading
# ---------------------------------------------------------------------------

st.subheader("Upload a poster to get started")

left, right = st.columns(2, gap="large")

# ---------------------------------------------------------------------------
# LEFT COLUMN: file uploader, review form, post-save actions
# ---------------------------------------------------------------------------

with left:

    # --- File uploader ---
    # The label carries the upload guidance. Keeping it in the widget's own label (rather than a
    # caption underneath) attaches the note to the thing it describes and keeps it accessible,
    # with the practical tip in help= so it's there for anyone who wants it without adding a
    # second line of page copy.
    img = st.file_uploader(
        ":material/document_scanner: Scans and original files make the best archive copies.",
        type=["jpg", "jpeg", "png", "webp", "pdf"],
        key=f"uploader_{ss['upload_key']}",
        help="Photos of posters out in the wild are welcome too — just try to get them flat and square-on.",
        disabled="result" in ss,
    )

    if "upload_error" in ss:
        st.error(ss.pop("upload_error"))

    # --- Review form (pre-filled by AI extraction, editable by user) ---
    has_result = "result" in ss
    r = ss.get("result", {})
    form_disabled = not has_result or ss.get("saved", False)

    band_options = sorted(set(all_bands + r.get("matched_headliners", []) + r.get("matched_supports", [])))
    venue_options = sorted(set(all_venues + r.get("matched_venues", [])))

    with st.form(f"poster_details_{ss['upload_key']}"):
        st.subheader("Poster Details")
        if has_result and not ss.get("saved"):
            st.info("Form populated — check before submitting")
        headliners = st.multiselect("Headliners", options=band_options, default=r.get("matched_headliners", []), accept_new_options=True, disabled=form_disabled)
        supports = st.multiselect("Support Acts", options=band_options, default=r.get("matched_supports", []), accept_new_options=True, disabled=form_disabled)
        event_date = st.date_input("Event Date", value=r.get("inferred_date"), format="DD/MM/YYYY", disabled=form_disabled, help="A poster can only be filed under one date. If it lists several — a tour, or a multi-day event — we record the earliest.")
        venues = st.multiselect("Venue", options=venue_options, default=r.get("matched_venues", []), accept_new_options=True, disabled=form_disabled, help="Most posters name one. Add more only if the event genuinely spans several — a day party across a few rooms.")
        event_name = st.text_input("Event Name", value=r.get("normed_event_name", ""), placeholder="Leave empty if not a named event", disabled=form_disabled)
        credits = st.multiselect("Poster By", options=all_credits, accept_new_options=True, disabled=form_disabled, help="Designers, photographers, illustrators — anyone credited on the poster. Leave empty if unknown.")
        no_credits_confirmed = st.checkbox("I don't know who made this poster", disabled=form_disabled)
        upload_type = st.radio("Upload type", options=["I created this poster or have the creator's permission to share it", "I'm sharing this for its historical value to the community — I don't hold the rights"], index=None, disabled=form_disabled)
        st.caption("By uploading, you agree to the [Terms of Service](/terms_of_service)")
        submitted = st.form_submit_button("Save Poster", type="primary", disabled=form_disabled, icon=":material/check:")

    # --- Form validation (all errors shown at once) ---
    if submitted:
        errors = []
        if not upload_type:
            errors.append("Please select an upload type before saving.")
        if not headliners and not supports:
            errors.append("Please add at least one band or artist.")
        elif not headliners:
            errors.append("At least one band must be a headliner.")
        if not venues:
            errors.append("Please add at least one venue.")
        if upload_type and not credits:
            if upload_type.startswith("I created"):
                errors.append("Authorised uploads require at least one poster credit — please add who made the poster.")
            elif not no_credits_confirmed:
                errors.append("Did you mean to submit without poster credits? If so, tick 'I don't know who made this poster' to confirm.")
        for e in errors:
            st.error(e)

    # --- Save: semantic duplicate check then persist ---
    if submitted and not errors:
        all_bands_merged = headliners + supports
        if check_semantic_duplicate(all_bands_merged, venues, event_date, all_posters):
            ss["upload_error"] = "A poster with these bands, venues, and date already exists."
            reset_upload()
            st.rerun()
        else:
            with st.spinner("Saving to archive... Please don't close this page."):
                upload_type_val = "RIGHTS_HOLDER" if upload_type.startswith("I created") else "COMMUNITY"
                try:
                    save_poster(S=S, file_name=r["target"], md5_hash=r["md5_hash"], upload_type=upload_type_val, **prepare_save_data(headliners, supports, event_date, venues, event_name, credits))
                finally:
                    # Clear even when save_poster raises. Its writes are MERGEs that can land
                    # before a later step fails, so a failed save does not mean nothing was
                    # written — and if the cache still predates that write, both dedup checks
                    # (MD5 and semantic) run against a list that can't see it. That is exactly
                    # how a duplicate poster got in: the save succeeded, the line after it threw,
                    # the cache was never cleared, and the re-upload sailed through.
                    get_all_posters.clear()
                ss["saved"] = True
                st.rerun()

    # --- Post-save success actions ---
    if ss.get("saved"):
        st.success("Poster saved! Thanks for contributing to the archive.")
        if st.button("Upload another poster", type="primary", icon=":material/add:", width="stretch"):
            ss.pop("processed_img", None)
            reset_upload()
            st.rerun()
        if st.button("View it in the gallery", width="stretch", icon=":material/chevron_backward:"):
            ss.pop("processed_img", None)
            reset_upload()
            st.switch_page("views/gallery.py")

# ---------------------------------------------------------------------------
# RIGHT COLUMN: image processing pipeline + preview
# ---------------------------------------------------------------------------

with right:

    # --- Stage 1 & 2: process image + AI extraction (runs once per upload) ---
    if img and "result" not in ss:
        with st.status("Hold tight while we analyse this poster...", expanded=True) as status:

            # Preprocess: PDF conversion, resize, compress. Bad/malicious/oversized files
            # raise ImageRejected — surface its safe message via the existing upload_error
            # path (no stack trace) and reset.
            st.write("Uploading image...")
            suffix = Path(img.name).suffix.lower()
            try:
                if suffix == ".pdf":
                    img = pdf_to_image_bytes(img)
                ss["processed_img"] = preprocess_image(img)
            except ImageRejected as e:
                ss["upload_error"] = str(e)
                reset_upload()
                st.rerun()

            # MD5 duplicate check (before uploading to stage)
            md5_hash = hashlib.md5(ss["processed_img"].getvalue(), usedforsecurity=False).hexdigest()
            if check_duplicate_md5(md5_hash, all_posters):
                ss["upload_error"] = "This poster has already been uploaded."
                reset_upload()
                st.rerun()

            # Upload to stage + AI extraction
            target = upload_to_stage(S, ss["processed_img"])

            st.write("Scanning the band names...")
            result = run_extraction(S, target, venue_list=all_venues)
            if not is_valid_poster(result):
                ss["upload_error"] = "That doesn't look like a gig poster — please try again."
                ss["upload_key"] += 1
                st.rerun()

            # Fuzzy match + log post-processing audit trail
            st.write("Populating upload form...")
            headliners_raw, supports_raw, date_str, venues_raw, event_name = parse_extraction(result)
            matched_headliners, matched_supports, inferred_date, matched_venues, normed_event_name = prepare_review_defaults(headliners_raw, supports_raw, date_str, venues_raw, event_name, all_bands, all_venues)
            log_processed(S, target, headliners_raw + supports_raw, date_str, venues_raw, event_name, matched_headliners + matched_supports, inferred_date, matched_venues, normed_event_name)

            # Store result in session state to populate review form
            ss["result"] = {
                "target": target,
                "md5_hash": md5_hash,
                "matched_headliners": matched_headliners,
                "matched_supports": matched_supports,
                "inferred_date": inferred_date,
                "matched_venues": matched_venues,
                "normed_event_name": normed_event_name,
            }

            status.update(label="Analysis complete!", state="complete", expanded=False)
            st.rerun()

    # --- Image preview (persists after rejection so user sees what was rejected) ---
    if "processed_img" in ss:
        st.image(ss["processed_img"])
        if "result" not in ss:
            ss.pop("processed_img", None)
