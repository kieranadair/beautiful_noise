import streamlit as st
from snowflake.snowpark import Session
from snowflake.snowpark.functions import col, when_not_matched, lit, call_builtin, parse_json
from config import DB, SC, STAGE, IMG_FORMAT
import json, uuid, functools
from io import BytesIO

@st.cache_resource(show_spinner="Connecting to poster database")
def get_session() -> Session:
    """Create and cache a Snowpark session. Cached via @st.cache_resource — returns
    the same session object on every call until cleared by _reconnect()."""
    S = Session.builder.configs(st.secrets["connections"]["snowflake"]).create()
    S.use_schema(f"{DB}.{SC}")
    return S

def _reconnect() -> Session:
    """Clear the cached session and create a fresh one. Called by with_retry on failure."""
    get_session.clear()
    return get_session()

def with_retry(fn):
    """Decorator for DB functions whose first arg is a Session. On any exception,
    reconnects and retries once with a fresh session. All db.py functions that
    touch Snowflake should be decorated with this."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            S = _reconnect()
            new_args = (S,) + args[1:]
            return fn(*new_args, **kwargs)
    return wrapper

@with_retry
def get_or_insert(S: Session, table: str, match_col: str, match_val: str) -> int:
    """MERGE-based upsert for dimension tables (VENUES, BANDS, DESIGNERS).
    Returns the ID of the existing or newly inserted row. Idempotent — safe to retry."""
    id_col = f"{table[:-1]}_ID"
    source = S.create_dataframe([[match_val]], schema=[match_col])
    target = S.table(table)
    target.merge(source, target[match_col] == source[match_col],
                 [when_not_matched().insert({match_col: source[match_col]})])
    return target.filter(col(match_col) == match_val).select(id_col).collect()[0][0]

@with_retry
def get_or_insert_event(S: Session, event_name: str | None, event_date, venue_id: int) -> int:
    """MERGE-based upsert for EVENTS. Uses equal_null() for NULL-safe matching on
    event_name — named events dedup on (name, date, venue_id), unnamed events
    (NULL event_name) match any existing unnamed event at the same venue/date.
    Returns the event_id."""

    source = S.create_dataframe(
        [[event_name, event_date, venue_id]],
        schema=["EVENT_NAME", "DATE", "VENUE_ID"]
    )
    target = S.table("EVENTS")
    target.merge(
        source,
        target["EVENT_NAME"].equal_null(source["EVENT_NAME"]) &
        (target["DATE"] == source["DATE"]) &
        (target["VENUE_ID"] == source["VENUE_ID"]),
        [when_not_matched().insert({
            "EVENT_NAME": source["EVENT_NAME"],
            "DATE": source["DATE"],
            "VENUE_ID": source["VENUE_ID"],
        })]
    )
    return target.filter(
        col("EVENT_NAME").equal_null(lit(event_name)) &
        (col("DATE") == event_date) &
        (col("VENUE_ID") == venue_id)
    ).select("EVENT_ID").collect()[0][0]

@with_retry
def save_poster(S: Session, file_name: str, bands: list[str], event_date, venue: str, event_name: str | None, designer_name: str, md5_hash: str, upload_type: str) -> None:
    """Orchestrates the full poster save: upserts dimensions (venue, designer, bands),
    upserts the event, then appends to POSTERS and BANDS_EVENTS. Re-fetches the session
    from cache before the raw appends to pick up any reconnect from inner retries."""
    venue_id = get_or_insert(S, "VENUES", "VENUE_NAME", venue)
    designer_id = get_or_insert(S, "DESIGNERS", "DESIGNER_NAME", designer_name)
    band_ids = [get_or_insert(S, "BANDS", "BAND_NAME", b) for b in bands]
    event_id = get_or_insert_event(S, event_name, event_date, venue_id)
    S = get_session()
    S.create_dataframe([[file_name, event_id, designer_id, md5_hash, upload_type]], schema=["file_name", "event_id", "designer_id", "md5_hash", "upload_type"]) \
     .write.save_as_table("POSTERS", mode="append", column_order="name")
    if band_ids:
        S.create_dataframe([[event_id, bid] for bid in band_ids],
                           schema=["event_id", "band_id"]) \
         .write.save_as_table("BANDS_EVENTS", mode="append", column_order="name")

@st.cache_data(show_spinner="Downloading poster data")
@with_retry
def get_all_posters(_S: Session) -> list[dict]:
    """Fetch all posters from POSTER_GALLERY_V with presigned image URLs (7-day TTL).
    Returns list[dict] with BANDS parsed from VARIANT to Python list. Cached by
    @st.cache_data — cleared after each upload via .clear(). Decorator order is
    intentional: cache on outside skips DB call when warm, retry on inside protects
    the actual Snowflake query on cache misses."""
    posters = _S.table("POSTER_GALLERY_V").with_column("URL", call_builtin("GET_PRESIGNED_URL", lit(f"@{STAGE}"), col("FILE_NAME"), 604800)).sort(col("UPLOADED_AT").desc()).collect()
    poster_data = [{**o.as_dict(), "BANDS": json.loads(o["BANDS"])} for o in posters]
    return poster_data

@with_retry
def upload_to_stage(S, file: BytesIO) -> str:
    """Upload file bytes to @POSTERS stage with a UUID filename. Returns the stage target path."""
    filename = f"{uuid.uuid4()}.{IMG_FORMAT.lower()}"
    result = S.file.put_stream(file, f"@{STAGE}/{filename}", auto_compress=False)
    return result.target

@with_retry
def log_processed(S: Session, file_name: str, bands: list[str], date: str, venue: str, event_name: str | None, matched_bands: list[str], inferred_date, matched_venue: str | None, normed_event_name: str | None) -> None:
    """Log post-processed AI extraction results to POSTERS_PROCESSED for audit.
    Stores both raw AI values and post-fuzzy-match values. Join with POSTERS_RAW
    on file_name to isolate errors to LLM vs post-processing."""
    S.create_dataframe(
        [[file_name, json.dumps(bands), json.dumps(matched_bands), venue, matched_venue, date, inferred_date, event_name, normed_event_name]],
        schema=["file_name", "bands", "matched_bands", "venue", "matched_venue", "date", "inferred_date", "event_name", "normed_event_name"]
    ).with_column("bands", parse_json(col("bands"))) \
     .with_column("matched_bands", parse_json(col("matched_bands"))) \
     .write.save_as_table("POSTERS_PROCESSED", mode="append", column_order="name")

@with_retry
def save_request(S: Session, request_type: str, entity_type: str, scope: str, poster_ids: list[int] | None, current_value: str | None, requested_value: str | None, notes: str | None) -> None:
    S.create_dataframe(
        [[request_type, entity_type, scope, json.dumps(poster_ids) if poster_ids else None, current_value, requested_value, notes]],
        schema=["request_type", "entity_type", "scope", "poster_ids", "current_value", "requested_value", "notes"]
    ).with_column("poster_ids", parse_json(col("poster_ids"))) \
     .write.save_as_table("REQUESTS", mode="append", column_order="name")
