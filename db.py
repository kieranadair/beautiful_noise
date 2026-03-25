import streamlit as st
from snowflake.snowpark import Session
from snowflake.snowpark.functions import col, when_not_matched, lit, call_builtin, parse_json
from config import DB, SC, STAGE
import json, uuid, hashlib
from io import BytesIO
def _check_session(S):
    """Checks whether the cached resource is still valid — if it returns False"""
    try:
        S.range(1).collect()
        return True
    except:
        return False
@st.cache_resource(validate=_check_session)
def get_session():
    S = Session.builder.configs(st.secrets["connections"]["snowflake"]).create()
    S.sql(f"USE SCHEMA {DB}.{SC}").collect()
    return S
def get_or_insert(S, table, match_col, match_val):
    id_col = f"{table[:-1]}_ID"
    source = S.create_dataframe([[match_val]], schema=[match_col])
    target = S.table(table)
    target.merge(source, target[match_col] == source[match_col],
                 [when_not_matched().insert({match_col: source[match_col]})])
    return target.filter(col(match_col) == match_val).select(id_col).collect()[0][0]
def save_poster(S, file_name, bands, event_date, venue, event_name, designer_name, md5_hash):
    venue_id = get_or_insert(S, "VENUES", "VENUE_NAME", venue)
    designer_id = get_or_insert(S, "DESIGNERS", "DESIGNER_NAME", designer_name)
    band_ids = [get_or_insert(S, "BANDS", "BAND_NAME", b) for b in bands]
    S.create_dataframe([[event_name, str(event_date), venue_id]],
                       schema=["event_name", "date", "venue_id"]) \
     .write.save_as_table("EVENTS", mode="append", column_order="name")
    event_id = S.table("EVENTS").filter(
        (col("VENUE_ID") == venue_id) & (col("DATE") == str(event_date))
    ).select("EVENT_ID").collect()[-1][0]
    S.create_dataframe([[file_name, event_id, designer_id, md5_hash]], schema=["file_name", "event_id", "designer_id", "md5_hash"]) \
     .write.save_as_table("POSTERS", mode="append", column_order="name")
    if band_ids:
        S.create_dataframe([[event_id, bid] for bid in band_ids],
                           schema=["event_id", "band_id"]) \
         .write.save_as_table("BANDS_EVENTS", mode="append", column_order="name")
@st.cache_data
def get_all_posters(_S):
    posters = _S.table("POSTER_GALLERY_V").with_column("URL", call_builtin("GET_PRESIGNED_URL", lit(f"@{STAGE}"), col("FILE_NAME"), 604800)).sort(col("UPLOADED_AT").desc()).collect()
    poster_data = [{**o.as_dict(), "BANDS": json.loads(o["BANDS"])} for o in posters]
    return poster_data
#| export
def upload_to_stage(S, file: BytesIO, suffix: str = ".jpg") -> str:
    """Upload file bytes to @POSTERS stage with a UUID filename. Returns the stage target path."""
    filename = f"{uuid.uuid4()}{suffix}"
    result = S.file.put_stream(file, f"@{STAGE}/{filename}", auto_compress=False)
    return result.target
def log_processed(S, file_name, bands, date, venue, event_name, matched_bands, inferred_date, matched_venue, normed_event_name):
    """Log post-processed AI extraction results to POSTERS_PROCESSED for audit purposes."""
    S.create_dataframe(
        [[file_name, json.dumps(bands), json.dumps(matched_bands), venue, matched_venue, date, inferred_date, event_name, normed_event_name]],
        schema=["file_name", "bands", "matched_bands", "venue", "matched_venue", "date", "inferred_date", "event_name", "normed_event_name"]
    ).with_column("bands", parse_json(col("bands"))) \
     .with_column("matched_bands", parse_json(col("matched_bands"))) \
     .write.save_as_table("POSTERS_PROCESSED", mode="append", column_order="name")
