#| export
import json
from io import BytesIO
from snowflake.snowpark.functions import ai_complete, to_file, lit, col
from core.config import STAGE, MODEL
from snowflake.snowpark import Session


PROMPT_BASE = """Look at this image and do two things:

1. Determine whether this is a gig, concert, or music event poster. Set is_valid to true if it is, false if not.

2. If it is a valid poster, extract:
   - headliners: the headlining band(s) or artist(s) — typically displayed largest or at the top of the billing. If there is no clear hierarchy, put ALL bands/artists/performers here
   - supports: support acts, openers, and DJs — typically displayed smaller or lower on the billing. Leave empty if there is no clear hierarchy
   - date: the event date in MM-DD format; do NOT provide year even if visible
   - venue: pick from this list if the venue matches: [{venues}]. If no match, return the venue name as written on the poster
   - event_name: specific festival or night name only; null if none

If it is not a valid poster, return empty values for the remaining fields."""


def _build_prompt(venue_list: list[str]) -> str:
    return PROMPT_BASE.format(venues=", ".join(venue_list) if venue_list else "")


RESPONSE_FORMAT = {
    "type": "json",
    "schema": {
        "type": "object",
        "properties": {
            "is_valid":   {"type": "boolean"},
            "headliners": {"type": "array", "items": {"type": "string"}},
            "supports":   {"type": "array", "items": {"type": "string"}},
            "date":       {"type": "string"},
            "venue":      {"type": "string"},
            "event_name": {"type": ["string", "null"]}
        },
        "required": ["is_valid", "headliners", "supports", "date", "venue", "event_name"]
    }
}


def run_extraction(S: Session, stage_filename: str, venue_list: list[str] | None = None) -> dict:
    """Call AI_COMPLETE on a staged poster image, log raw result to POSTERS_RAW atomically,
    and return parsed dict. The write-then-read pattern is intentional — ai_complete()
    executes server-side, so the result is captured by writing to table first, then
    reading back by file_name (UUID, guaranteed unique)."""
    prompt = _build_prompt(venue_list or [])
    S.range(1).select(
        lit(stage_filename).alias("FILE_NAME"),
        ai_complete(MODEL, prompt, to_file(f"@{STAGE}/{stage_filename}"),
                    response_format=RESPONSE_FORMAT).alias("AI_COMPLETE")
    ).write.mode("append").save_as_table("POSTERS_RAW")
    
    row = S.table("POSTERS_RAW").filter(col("FILE_NAME") == stage_filename).first()
    return json.loads(row["AI_COMPLETE"])


def is_valid_poster(result: dict) -> bool:
    """Returns True if the AI determined the image is a valid gig/event poster.
    Checks the is_valid field from the AI extraction result."""
    return bool(result.get("is_valid", False))


def parse_extraction(result: dict) -> tuple[list[str], list[str], str, str, str | None]:
    """Unwrap raw AI result into (headliners, supports, date, venue, event_name) tuple with safe defaults.
    Returns empty list/string for missing fields, None for absent event_name.
    If headliners is empty but supports has values, promotes all supports to headliners."""
    headliners = result.get("headliners", [])
    supports = result.get("supports", [])
    if not headliners and supports:
        headliners, supports = supports, []
    return (
        headliners,
        supports,
        result.get("date", ""),
        result.get("venue", ""),
        result.get("event_name")
    )
