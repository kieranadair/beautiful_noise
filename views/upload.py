import hashlib
import uuid
from pathlib import Path
from io import BytesIO
import streamlit as st
from core.config import NAV_BTN_WIDTH, MODEL
from core.db import get_all_posters, get_vocabulary, save_poster, upload_poster, log_extraction, delete_poster_file, clear_caches
from core.ai import run_extraction, is_valid_poster, parse_extraction, ExtractionUnavailable
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
    bump_upload_key()

def bump_upload_key():
    """Advance the uploader's key so Streamlit discards the previous file_uploader's state.
    Reads defensively: `ss["upload_key"] += 1` raises if session state has been cleared, and this
    runs on the error paths, where an extra exception would bury the real one."""
    ss["upload_key"] = ss.get("upload_key", 0) + 1

ss = st.session_state
# Bound once per run, not re-read at each use. Both the uploader and the form derive their widget
# keys from it, so a mid-run change would leave them disagreeing — and re-reading session state
# for a value we already have is what turned a lost session into a hard KeyError here once.
upload_key = ss.setdefault("upload_key", 0)

# ---------------------------------------------------------------------------
# Data: session, poster cache, and filter options (needed for form dropdowns
# and duplicate detection — runs on every page load but is cached)
# ---------------------------------------------------------------------------

all_posters = get_all_posters()
# Vocabulary comes from the dimension tables, NOT from the posters. A name only reaches
# POSTER_GALLERY_V once it is attached to a saved poster, so deriving it from all_posters
# would hide every name that isn't — which on the old Snowflake database was 24 of 185
# bands. all_posters is still needed below, for the two duplicate checks.
all_bands, all_venues, all_credits = get_vocabulary()

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
        key=f"uploader_{upload_key}",
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

    with st.form(f"poster_details_{upload_key}"):
        st.subheader("Poster Details")
        if has_result and not ss.get("saved"):
            st.info("Form populated — check before submitting")
        headliners = st.multiselect("Headliners", options=band_options, default=r.get("matched_headliners", []), accept_new_options=True, disabled=form_disabled)
        supports = st.multiselect("Support Acts", options=band_options, default=r.get("matched_supports", []), accept_new_options=True, disabled=form_disabled)
        event_date = st.date_input("Event Date", value=r.get("inferred_date"), format="DD/MM/YYYY", disabled=form_disabled, help="If a poster lists several dates, we take the first.")
        venues = st.multiselect("Venue", options=venue_options, default=r.get("matched_venues", []), accept_new_options=True, disabled=form_disabled)
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
                # Store the image only now, a moment before the row that points at it.
                # Everything before this point is reversible by doing nothing.
                target = upload_poster(ss["processed_img"], r["scan_id"])
                try:
                    save_poster(file_name=target, scan_id=r["scan_id"], md5_hash=r["md5_hash"], upload_type=upload_type_val, **prepare_save_data(headliners, supports, event_date, venues, event_name, credits))
                except Exception:
                    # save_poster runs in one transaction, so a failure means nothing was
                    # written and this object is definitely orphaned. This is the only
                    # window in which an orphan can exist, and it is about a second wide.
                    delete_poster_file(target)
                    raise
                finally:
                    # Belt and braces now, rather than load-bearing as it once was. Under
                    # Snowflake each MERGE was its own statement, so a failure part-way
                    # through left rows behind — and if the cache still predated them, both
                    # dedup checks ran against a list that couldn't see them. That is exactly
                    # how a duplicate poster got in. A single transaction removes the
                    # partial-write state that made this necessary.
                    clear_caches()
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

            # The scan's identity, generated before the call so the extraction row, the
            # eventual R2 key and the poster all agree on one id.
            scan_id = str(uuid.uuid4())

            st.write("Scanning the band names...")
            # Scan BEFORE storing. The API takes bytes, so nothing has to be uploaded first —
            # which means a non-poster or a failed scan never leaves an object in R2. Cortex
            # forced the opposite order because AI_COMPLETE read from a stage.
            #
            # The scan can be capped (spend limit) or briefly unavailable. Both are our
            # problem, not the visitor's, so they get a plain sentence via the same
            # upload_error path as a rejected image rather than a stack trace.
            try:
                result = run_extraction(ss["processed_img"], venue_list=all_venues)
            except ExtractionUnavailable as e:
                ss["upload_error"] = str(e)
                reset_upload()
                st.rerun()
            # Fuzzy match, then log the scan exactly once — valid or not. A rejected scan
            # is as much a data point as a successful one; it just carries no `matched`.
            valid = is_valid_poster(result)
            matched = None
            if valid:
                st.write("Populating upload form...")
                headliners_raw, supports_raw, date_str, venues_raw, event_name = parse_extraction(result)
                matched_headliners, matched_supports, inferred_date, matched_venues, normed_event_name = prepare_review_defaults(headliners_raw, supports_raw, date_str, venues_raw, event_name, all_bands, all_venues)
                matched = {
                    "headliners": matched_headliners,
                    "supports": matched_supports,
                    "venues": matched_venues,
                    "event_name": normed_event_name,
                    # isoformat because the column is jsonb and date isn't JSON-native.
                    "inferred_date": inferred_date.isoformat(),
                }
            log_extraction(scan_id, MODEL, valid, result, matched)

            if not valid:
                ss["upload_error"] = "That doesn't look like a gig poster — please try again."
                bump_upload_key()
                st.rerun()

            # Note what is NOT here: nothing has been written to R2. Storage happens at
            # save time, so an abandoned review leaves no orphaned object — only an
            # extraction row, which is exactly the trace worth keeping.
            ss["result"] = {
                "scan_id": scan_id,
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
