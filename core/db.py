"""All Postgres and R2 access.

Every function here talks to Neon (via a pooled bn_app connection) or to Cloudflare R2.
Nothing else in the app opens a connection or an S3 client.

Two invariants worth stating up front, because breaking either fails quietly:

  1. Rows come back with UPPERCASE keys. core/utils.py and every page index posters as
     p["BANDS"], p["MD5_HASH"], p["UPLOAD_TYPE"]. psycopg returns lowercase column names,
     so upper_dict_row bridges the two. Drop it and p["BANDS"] raises KeyError — but only
     on whichever page you happen to open first.

  2. Identifiers are composed with psycopg.sql, values are always parameters. No SQL is
     ever built by string formatting with user data. Band, venue, credit and event names
     are free text from anonymous uploaders; %s placeholders bind them as data literals,
     which is what keeps injection closed.
"""

import uuid
from io import BytesIO

import boto3
import psycopg
import streamlit as st
from psycopg import sql
from psycopg_pool import ConnectionPool

from core.config import (
    DATABASE_URL,
    IMG_FORMAT,
    R2_ACCESS_KEY_ID,
    R2_BUCKET,
    R2_ENDPOINT,
    R2_PUBLIC_BASE,
    R2_SECRET_ACCESS_KEY,
)

# The gallery list is small and cheap to fetch, so this TTL is about freshness rather
# than cost. Uploads clear the cache outright, so it only fires when the database changed
# without the app doing it — which is exactly how corrections and takedowns are applied
# (by hand, as the owner role). An hour means those appear without a redeploy.
POSTER_CACHE_TTL = 60 * 60


def upper_dict_row(cursor):
    """psycopg row factory returning dicts with UPPERCASE keys — see invariant 1."""
    names = [c.name.upper() for c in cursor.description]

    def make_row(values):
        return dict(zip(names, values))

    return make_row


@st.cache_resource(show_spinner="Connecting to the archive...")
def get_pool() -> ConnectionPool:
    """Connection pool for the app role, cached for the life of the server process.

    min_size=0 and a short max_idle are NOT tuning — they are load-bearing. Neon suspends
    compute after 5 minutes with no active connection, and the Railway container is
    always-on. A pool holding even one idle connection keeps the database awake around
    the clock: ~183 CU-hours/month against a 100 CU-hour free allowance, with no error to
    notice — just a throttle, or a bill. This is the same shape as the Snowflake incident
    where a proactive health-check ping kept the warehouse resumed overnight.

    The cost is roughly half a second of cold start on the first query after a quiet
    spell, which lands behind @st.cache_data and the spinner above.

    `check` replaces the old with_retry decorator: the pool validates a connection before
    handing it out and transparently replaces a dead one, so callers no longer need to
    reconnect-and-retry by hand.
    """
    pool = ConnectionPool(
        DATABASE_URL,
        min_size=0,
        max_size=4,
        max_idle=30,
        check=ConnectionPool.check_connection,
        open=False,
    )
    pool.open()
    return pool


@st.cache_resource(show_spinner=False)
def get_r2():
    """S3-compatible client for Cloudflare R2. region_name must be the literal 'auto'."""
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def clear_caches() -> None:
    """Drop both cached reads. Call after any write that should be visible immediately."""
    get_all_posters.clear()
    get_vocabulary.clear()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@st.cache_data(ttl=POSTER_CACHE_TTL, show_spinner="Downloading poster data")
def get_all_posters() -> list[dict]:
    """Every poster, from the pre-joined gallery view, newest first.

    The array columns arrive as real Python lists — psycopg adapts Postgres text[]
    natively. The Snowflake version had to json.loads() each one, and forgetting a column
    there failed silently rather than loudly: strings are iterable, so every join/in/set
    over an unparsed array quietly operated on single characters. That whole class of bug
    is gone with the VARIANT columns that caused it.

    URLs are plain strings against R2's public custom domain. There is nothing to expire,
    so this cache can never outlive its links the way presigned URLs could.
    """
    with get_pool().connection() as conn, conn.cursor(row_factory=upper_dict_row) as cur:
        cur.execute("select * from poster_gallery_v order by uploaded_at desc")
        posters = cur.fetchall()

    for p in posters:
        p["URL"] = f"{R2_PUBLIC_BASE}/{p['FILE_NAME']}"
    return posters


@st.cache_data(ttl=POSTER_CACHE_TTL, show_spinner=False)
def get_vocabulary() -> tuple[list[str], list[str], list[str]]:
    """Every known band, venue and credit name — (bands, venues, credits), each sorted.

    Read from the dimension tables directly, NOT from the gallery view. That distinction
    is the whole point: a name only reaches the view once it is attached to a saved
    poster, so deriving the vocabulary from posters makes every unattached name invisible
    to fuzzy matching and to the extraction prompt. That is not hypothetical — the
    Snowflake database held 185 bands of which only 161 were on a poster.

    Used by the upload page only. The gallery and contact pages deliberately keep taking
    their filter options from the posters themselves, via get_poster_vars(): offering a
    filter for a band with no posters is a dead end.
    """
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("select band_name from bands order by band_name")
        bands = [r[0] for r in cur.fetchall()]
        cur.execute("select venue_name from venues order by venue_name")
        venues = [r[0] for r in cur.fetchall()]
        cur.execute("select credit_name from credits order by credit_name")
        credits = [r[0] for r in cur.fetchall()]
    return bands, venues, credits


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def _get_or_insert(cur, table: str, col: str, value: str) -> int:
    """Upsert a dimension row and return its id. Idempotent.

    Two statements, because of a collision between two things that each look right alone:

      - `on conflict do nothing` returns NO ROW on the conflict path, which for a
        dimension table is the *common* path. So RETURNING alone gives an id on first
        insert and None every time after — hence the fallback SELECT.

      - The usual fix for that is `do update set col = excluded.col`, a no-op write purely
        to make RETURNING fire. But `ON CONFLICT DO UPDATE` requires the **UPDATE**
        privilege, which bn_app deliberately does not have, and Postgres checks privileges
        against the statement rather than the path actually taken — so it fails every
        time, conflict or not.

    Given the choice between granting UPDATE to a role that must never rewrite rows and
    paying one extra SELECT on a cached, low-frequency write path, the SELECT wins easily.

    Side effect either way: the identity sequence advances even when the insert is
    discarded, so ids have gaps. Harmless; don't read meaning into id continuity.
    """
    id_col = sql.Identifier(f"{table[:-1]}_id")
    ident = {"table": sql.Identifier(table), "col": sql.Identifier(col), "id_col": id_col}

    cur.execute(
        sql.SQL(
            "insert into {table} ({col}) values (%s) "
            "on conflict ({col}) do nothing returning {id_col}"
        ).format(**ident),
        (value,),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        sql.SQL("select {id_col} from {table} where {col} = %s").format(**ident),
        (value,),
    )
    return cur.fetchone()[0]


def _get_or_insert_event(cur, event_name: str | None, event_date, venue_id: int) -> int:
    """Upsert an event and return its id.

    Conflict target is the named constraint rather than a column list, because
    events_natural_key is declared UNIQUE NULLS NOT DISTINCT — most gigs have no event
    name, and under normal SQL semantics NULL != NULL would let every unnamed gig at the
    same venue and date insert as a separate event. Since band_events is keyed on
    event_id, that would split one gig's lineup across duplicates, silently.

    The Snowflake version hand-rolled this with equal_null() in application code. Here the
    database enforces it.
    """
    cur.execute(
        "insert into events (event_name, date, venue_id) values (%s, %s, %s) "
        "on conflict on constraint events_natural_key do nothing "
        "returning event_id",
        (event_name, event_date, venue_id),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # `is not distinct from` is the SELECT-side counterpart of NULLS NOT DISTINCT: plain
    # `=` would never match the NULL event_name that most gigs have, so this lookup would
    # return nothing for exactly the rows the constraint just deduplicated.
    cur.execute(
        "select event_id from events "
        "where event_name is not distinct from %s and date = %s and venue_id = %s",
        (event_name, event_date, venue_id),
    )
    return cur.fetchone()[0]


def save_poster(
    file_name: str,
    scan_id: str,
    bands: list[str],
    headliners: list[str],
    event_date,
    venues: list[str],
    event_name: str | None,
    credits: list[str],
    md5_hash: str,
    upload_type: str,
) -> None:
    """Persist a reviewed poster. All of it, or none of it.

    Runs in a single transaction: the connection context manager commits on a clean exit
    and rolls back on any exception. The Snowflake version could not do this — each MERGE
    was its own statement, so a failure part-way left dimension rows and possibly a poster
    behind, which is how a duplicate poster once slipped past both dedup checks.

    venues may name several places (a day party across a few rooms). They are NOT
    interchangeable: venues[0] becomes the event's venue_id, which is what distinguishes
    one unnamed gig from another. Every venue including the first is also linked to the
    poster via poster_venues, so that junction is the single list to read for display.

    headliners is the subset of bands that are headliners; all others are supports.
    credits is a flat list and may be empty.
    """
    headliner_set = set(headliners)

    with get_pool().connection() as conn, conn.cursor() as cur:
        venue_ids = [_get_or_insert(cur, "venues", "venue_name", v) for v in venues]
        band_ids = [
            (_get_or_insert(cur, "bands", "band_name", b), b in headliner_set) for b in bands
        ]
        credit_ids = [_get_or_insert(cur, "credits", "credit_name", c) for c in credits]

        event_id = _get_or_insert_event(cur, event_name, event_date, venue_ids[0])

        # RETURNING gives us poster_id straight away. The Snowflake version had to
        # re-query by file_name afterwards, because MERGE returns no row.
        cur.execute(
            "insert into posters (file_name, scan_id, event_id, md5_hash, upload_type) "
            "values (%s, %s, %s, %s, %s) "
            "on conflict (file_name) do nothing returning poster_id",
            (file_name, scan_id, event_id, md5_hash, upload_type),
        )
        row = cur.fetchone()
        if row:
            poster_id = row[0]
        else:
            # Only reachable on a retry of the same upload — file_name is a fresh UUID.
            cur.execute("select poster_id from posters where file_name = %s", (file_name,))
            poster_id = cur.fetchone()[0]

        if band_ids:
            cur.executemany(
                "insert into band_events (event_id, band_id, is_headliner) "
                "values (%s, %s, %s) on conflict do nothing",
                [(event_id, band_id, is_hl) for band_id, is_hl in band_ids],
            )

        cur.executemany(
            "insert into poster_venues (poster_id, venue_id) values (%s, %s) "
            "on conflict do nothing",
            [(poster_id, venue_id) for venue_id in venue_ids],
        )

        if credit_ids:
            cur.executemany(
                "insert into poster_credits (poster_id, credit_id) values (%s, %s) "
                "on conflict do nothing",
                [(poster_id, credit_id) for credit_id in credit_ids],
            )


def upload_poster(file: BytesIO, scan_id: str) -> str:
    """Store poster bytes in R2, keyed off the scan that produced them. Returns the key.

    Called at SAVE time, not at scan time. Nothing reaches storage until a human has
    confirmed the poster, so a rejected scan or an abandoned review cannot leave an
    orphaned object behind — which is what Snowflake's CLEANUP_ORPHANED_STAGE_FILES task
    existed to sweep up. There is no equivalent here because there is nothing to sweep.

    ContentType is set explicitly. Without it R2 serves application/octet-stream and the
    browser downloads the file instead of rendering it — the object is fine, the gallery
    just shows nothing.
    """
    filename = f"{scan_id}.{IMG_FORMAT.lower()}"
    get_r2().put_object(
        Bucket=R2_BUCKET,
        Key=filename,
        Body=file.getvalue(),
        ContentType=f"image/{IMG_FORMAT.lower()}",
    )
    return filename


def delete_poster_file(file_name: str) -> None:
    """Remove an object from R2. Used to clean up after a failed save."""
    get_r2().delete_object(Bucket=R2_BUCKET, Key=file_name)


# ---------------------------------------------------------------------------
# Extraction log and contact-form submissions
#
# Both name their columns in the INSERT, which makes positional mismatch impossible. The
# Snowflake versions passed column subsets in a different order than the table and relied
# on column_order="name" to stay correct.
# ---------------------------------------------------------------------------

def log_extraction(
    scan_id: str,
    model: str,
    is_valid: bool,
    raw: dict,
    matched: dict | None = None,
) -> None:
    """Record one AI scan, written as soon as the model responds.

    Called for EVERY scan, including ones the model rejects and ones the user abandons —
    which is the point. The outcome is deliberately not a column here: it isn't known yet,
    and bn_app has no UPDATE to set it later. It is derived instead, which means it cannot
    drift from reality:

        rejected  : is_valid = false
        saved     : a poster row references this scan_id
        abandoned : is_valid = true, and no poster references it

    `model` is recorded per row so a model change doesn't quietly blend two generations
    into one meaningless accuracy average.
    """
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into extractions (scan_id, model, is_valid, raw, matched) "
            "values (%s, %s, %s, %s, %s)",
            (
                scan_id,
                model,
                is_valid,
                psycopg.types.json.Jsonb(raw),
                psycopg.types.json.Jsonb(matched) if matched is not None else None,
            ),
        )


def save_request(
    request_type: str,
    entity_type: str,
    scope: str,
    poster_ids: list[int] | None,
    current_value: str | None,
    requested_value: str | None,
    notes: str | None,
) -> None:
    """Store a contact-page submission. Nothing processes these automatically."""
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into requests "
            "(request_type, entity_type, scope, poster_ids, "
            " current_value, requested_value, notes) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (request_type, entity_type, scope, poster_ids,
             current_value, requested_value, notes),
        )
