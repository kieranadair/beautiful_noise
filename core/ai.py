import base64
import json
import os
from io import BytesIO

import anthropic

from core.config import IMG_FORMAT, MAX_OUTPUT_TOKENS, MODEL


class ExtractionUnavailable(Exception):
    """The AI scan couldn't run. Carries a message that is safe to show a visitor
    verbatim — never the raw API error, which can name internal detail."""


# Shown when we've hit a spend cap or rate limit.
QUOTA_MESSAGE = "Poster scanning is paused right now — please try again a bit later."
GENERIC_MESSAGE = "Poster scanning is unavailable right now — please try again in a few minutes."


def _client() -> anthropic.Anthropic:
    """Build the client on first use rather than at import.

    A missing API key should break uploads, not the whole site. Browsing an archive of
    posters does not need the model, so a misconfigured key degrades one page instead of
    taking the gallery down with it — the opposite trade-off to the database URL, which
    core/config.py requires at startup because nothing works without it.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ExtractionUnavailable(GENERIC_MESSAGE)
    return anthropic.Anthropic()


PROMPT_BASE = """Look at this image and do two things:

1. Determine whether this is a gig, concert, or music event poster. Set is_valid to true if it is, false if not.

2. If it is a valid poster, extract:
   - headliners: the headlining band(s) or artist(s) — typically displayed largest or at the top of the billing. If there is no clear hierarchy, put ALL bands/artists/performers here
   - supports: support acts, openers, and DJs — typically displayed smaller or lower on the billing. Leave empty if there is no clear hierarchy
   - date: the event date in MM-DD format; do NOT provide year even if visible. If the poster
     lists several dates (a tour, or a multi-day event), return the EARLIEST one
   - venues: the venue(s) the event is at. Pick from this list where a venue matches:
     [{venues}]. For any that don't match, return the name as written on the poster. Usually
     one, but a day party or crawl can span several — return every venue named
   - event_name: specific festival or night name only; null if none

If it is not a valid poster, return empty values for the remaining fields."""


def _build_prompt(venue_list: list[str]) -> str:
    """Interpolate the known venue list into the prompt.

    Venues get two chances at recognition: named here so the model can match against them
    directly, and fuzzy-matched afterwards in core/utils.py. Bands only get the second
    pass — listing ~200 band names on every call would be costly and would invite the
    model to force a lineup onto names it recognises.

    NOTE: this list is unbounded. It now comes from the `venues` table rather than only
    venues attached to a poster, so it grows with the archive. At a dozen venues it is
    ~50 tokens and irrelevant, and it stays fine into the hundreds — but if this ever
    reaches thousands, cap or cluster it rather than sending the lot.
    """
    return PROMPT_BASE.format(venues=", ".join(venue_list) if venue_list else "")


# Structured outputs constrain the response to this shape, so the result is guaranteed
# parseable. Two differences from the Cortex version this replaces: every object needs
# additionalProperties: false, and a nullable field must use anyOf — the type-union form
# {"type": ["string", "null"]} is not in the supported JSON Schema subset.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_valid":   {"type": "boolean"},
        "headliners": {"type": "array", "items": {"type": "string"}},
        "supports":   {"type": "array", "items": {"type": "string"}},
        "date":       {"type": "string"},
        "venues":     {"type": "array", "items": {"type": "string"}},
        "event_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["is_valid", "headliners", "supports", "date", "venues", "event_name"],
    "additionalProperties": False,
}


def run_extraction(image: BytesIO, venue_list: list[str] | None = None) -> dict:
    """Extract poster metadata from image bytes. Returns the parsed result.

    Takes bytes directly, so extraction happens BEFORE the image is stored — a rejected
    or non-poster upload never reaches R2. Cortex forced the opposite order because
    AI_COMPLETE read from a stage, which is also why the old version had to write the
    result to a table and read it back: the call executed server-side inside a SELECT.
    Here the response simply comes back.

    No thinking configuration: Haiku 4.5 does not accept the `effort` parameter, and this
    is a bounded extraction task that does not want extended reasoning.
    """
    prompt = _build_prompt(venue_list or [])
    b64 = base64.standard_b64encode(image.getvalue()).decode()

    # Only the API call is wrapped. A failure here is ours, not the visitor's, and is
    # worth turning into a calm sentence. The json.loads below is deliberately left bare:
    # structured outputs guarantee valid JSON, so a failure there is a bug in this app and
    # burying it under "try again later" would hide it.
    try:
        response = _client().messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": f"image/{IMG_FORMAT.lower()}",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
        )
    except anthropic.RateLimitError as e:
        raise ExtractionUnavailable(QUOTA_MESSAGE) from e
    except anthropic.APIStatusError as e:
        # Typed exceptions, not string matching. The Snowflake version had to grep the
        # error text for "quota"/"budget"/"exceeded" because Cortex published no stable
        # code for a spend cap; the SDK exposes real classes and an error type, so the
        # visitor-facing message is now reliable rather than best-effort.
        billing = (e.type or "") in {"billing_error", "permission_error"}
        raise ExtractionUnavailable(QUOTA_MESSAGE if billing else GENERIC_MESSAGE) from e
    except anthropic.APIConnectionError as e:
        raise ExtractionUnavailable(GENERIC_MESSAGE) from e

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def is_valid_poster(result: dict) -> bool:
    """Returns True if the AI determined the image is a valid gig/event poster."""
    return bool(result.get("is_valid", False))


def parse_extraction(result: dict) -> tuple[list[str], list[str], str, list[str], str | None]:
    """Unwrap raw AI result into (headliners, supports, date, venues, event_name) with safe
    defaults. Returns empty list/string for missing fields, None for absent event_name.
    If headliners is empty but supports has values, promotes all supports to headliners.
    venues is a list — most posters name one, but a day party can span several."""
    headliners = result.get("headliners", [])
    supports = result.get("supports", [])
    if not headliners and supports:
        headliners, supports = supports, []
    return (
        headliners,
        supports,
        result.get("date", ""),
        result.get("venues", []),
        result.get("event_name"),
    )
