import base64
import json
import os
from io import BytesIO

import openai

from core.config import (
    IMG_FORMAT,
    MAX_OUTPUT_TOKENS,
    MODEL,
    OPENROUTER_BASE_URL,
    OPENROUTER_PROVIDER,
)


class ExtractionUnavailable(Exception):
    """The AI scan couldn't run. Carries a message that is safe to show a visitor
    verbatim — never the raw API error, which can name internal detail."""


# Shown when we've hit a spend cap or rate limit.
QUOTA_MESSAGE = "Poster scanning is paused right now — please try again a bit later."
GENERIC_MESSAGE = "Poster scanning is unavailable right now — please try again in a few minutes."


def _client() -> openai.OpenAI:
    """Build the client on first use rather than at import.

    A missing API key should break uploads, not the whole site. Browsing an archive of
    posters does not need the model, so a misconfigured key degrades one page instead of
    taking the gallery down with it — the opposite trade-off to the database URL, which
    core/config.py requires at startup because nothing works without it.

    OpenRouter speaks the OpenAI wire format, so this is the OpenAI SDK pointed at a
    different base URL. Using the SDK rather than raw HTTP is deliberate: it gives typed
    exception classes, which is what makes the visitor-facing message below reliable
    instead of a guess parsed out of an error string.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ExtractionUnavailable(GENERIC_MESSAGE)
    return openai.OpenAI(api_key=key, base_url=OPENROUTER_BASE_URL)


PROMPT_BASE = """Look at this image and do two things:

1. Determine whether this is a gig, concert, or music event poster. Set is_valid to true if it is, false if not.

2. If it is a valid poster, extract:
   - headliners: the headlining band(s) or artist(s) — typically displayed largest or at the top of the billing. If there is no clear hierarchy, put ALL bands/artists/performers here
   - supports: support acts, openers, and DJs — typically displayed smaller or lower on the billing. Leave empty if there is no clear hierarchy
   - month and day: the event date, as two numbers. Do NOT provide the year even if it is
     visible. This is an Australian archive and posters use Australian conventions, so a
     numeric date is DAY first: "1.5.25" and "1/5/25" both mean the 1st of May — month=5,
     day=1 — NOT the 5th of January. A written date like "MAY 1" is unambiguous; read it
     as given. If the poster lists several dates (a tour, or a multi-day event), return
     the EARLIEST one. If no date is shown, return null for both
   - venues: the venue(s) the event is at. Pick from this list where a venue matches:
     [{venues}]. For any that don't match, return the name as written on the poster. Usually
     one, but a day party or crawl can span several — return every venue named
   - event_name: the name of a festival, club night or recurring event (for example
     "DIY ON HIGH"); null if none. A single launch, album launch, EP launch, tour or
     anniversary show is NOT an event name — those describe a band's own headline show,
     so return null for them

If it is not a valid poster, return empty values for the remaining fields."""


def _build_prompt(venue_list: list[str]) -> str:
    """Interpolate the known venue list into the prompt.

    Venues get two chances at recognition: named here so the model can match against them
    directly, and fuzzy-matched afterwards in core/utils.py. Bands only get the second
    pass — listing ~200 band names on every call would be costly and would invite the
    model to force a lineup onto names it recognises.

    Removing this list was benchmarked on 2026-08-17 and made venue extraction slightly
    worse, so it earns its place — though note the model often returns the name as printed
    ("The Curtin Hotel") and lets the fuzzy matcher canonicalise it, rather than picking
    off this list directly.

    NOTE: this list is unbounded. It now comes from the `venues` table rather than only
    venues attached to a poster, so it grows with the archive. At a dozen venues it is
    ~50 tokens and irrelevant, and it stays fine into the hundreds — but if this ever
    reaches thousands, cap or cluster it rather than sending the lot.
    """
    return PROMPT_BASE.format(venues=", ".join(venue_list) if venue_list else "")


# Structured outputs constrain the response to this shape, so the result is guaranteed
# parseable. Every object needs additionalProperties: false and must list every property
# in `required` — that is what OpenAI-compatible strict mode enforces, and OpenRouter
# passes it through to the upstream host.
#
# The date is two integers rather than one "MM-DD" string, and that is load-bearing.
# A string date is the ONLY field the schema cannot constrain: there is no `pattern` in
# the supported subset, and `format: "date"` would demand the year the prompt deliberately
# refuses — so the ordering was enforced by prose alone, on precisely the field where
# Australian posters print the opposite order to the format we asked for. Worse, the
# failure was silent in both directions: infer_date caught the ValueError from
# "2026-15-06" and returned today, while "01-05" for the 1st of May parsed cleanly as
# the 5th of January. Two integers make a transposition impossible to express rather
# than merely discouraged. Do not "simplify" this back to a single string.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_valid":   {"type": "boolean"},
        "headliners": {"type": "array", "items": {"type": "string"}},
        "supports":   {"type": "array", "items": {"type": "string"}},
        # Nullable, not 0-as-sentinel: a poster with no printed date is genuinely absent,
        # and a sentinel would be indistinguishable from a misread.
        "month":      {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "day":        {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "venues":     {"type": "array", "items": {"type": "string"}},
        "event_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["is_valid", "headliners", "supports", "month", "day", "venues", "event_name"],
    "additionalProperties": False,
}


def run_extraction(image: BytesIO, venue_list: list[str] | None = None) -> dict:
    """Extract poster metadata from image bytes. Returns the parsed result.

    Takes bytes directly, so extraction happens BEFORE the image is stored — a rejected
    or non-poster upload never reaches R2. Cortex forced the opposite order because
    AI_COMPLETE read from a stage, which is also why the old version had to write the
    result to a table and read it back: the call executed server-side inside a SELECT.
    Here the response simply comes back.

    Temperature is deliberately not set. Maverick is a Mixture-of-Experts model served in
    batches, so expert routing varies with whatever else is in the batch — greedy decoding
    was measured to produce exactly the same run-to-run variation as the default, on the
    same posters. There is no setting that makes this reproducible, and it does not matter
    here: the aggregate correction load is stable, only which poster is the awkward one
    moves, and a human confirms every extraction before it is saved.
    """
    prompt = _build_prompt(venue_list or [])
    b64 = base64.standard_b64encode(image.getvalue()).decode()

    # Only the API call is wrapped. A failure here is ours, not the visitor's, and is
    # worth turning into a calm sentence. The json.loads below is deliberately left bare:
    # structured outputs guarantee valid JSON, so a failure there is a bug in this app and
    # burying it under "try again later" would hide it.
    try:
        response = _client().chat.completions.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/{IMG_FORMAT.lower()};base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            response_format={"type": "json_schema", "json_schema": {
                "name": "poster_extraction", "strict": True, "schema": RESPONSE_SCHEMA}},
            # OpenRouter-specific routing controls, passed through untouched by the SDK.
            extra_body={"provider": OPENROUTER_PROVIDER},
        )
    except openai.RateLimitError as e:
        raise ExtractionUnavailable(QUOTA_MESSAGE) from e
    except openai.APIStatusError as e:
        # Typed exceptions, not string matching. The Snowflake version had to grep the
        # error text for "quota"/"budget"/"exceeded" because Cortex published no stable
        # code for a spend cap; here 402 is OpenRouter's "out of credits", which is the
        # one case a visitor should be told to come back later rather than "broken".
        raise ExtractionUnavailable(
            QUOTA_MESSAGE if e.status_code == 402 else GENERIC_MESSAGE
        ) from e
    except openai.APIConnectionError as e:
        raise ExtractionUnavailable(GENERIC_MESSAGE) from e

    return json.loads(response.choices[0].message.content)


def is_valid_poster(result: dict) -> bool:
    """Returns True if the AI determined the image is a valid gig/event poster."""
    return bool(result.get("is_valid", False))


def parse_extraction(
    result: dict,
) -> tuple[list[str], list[str], int | None, int | None, list[str], str | None]:
    """Unwrap raw AI result into (headliners, supports, month, day, venues, event_name)
    with safe defaults. Returns empty list for missing lists, None for an absent
    event_name and for an absent month/day.
    If headliners is empty but supports has values, promotes all supports to headliners.
    venues is a list — most posters name one, but a day party can span several."""
    headliners = result.get("headliners", [])
    supports = result.get("supports", [])
    if not headliners and supports:
        headliners, supports = supports, []
    # isinstance rather than truthiness: the schema permits null, and a bare falsy check
    # would also swallow a legitimate 0 from a provider that ignores the schema.
    month, day = result.get("month"), result.get("day")
    return (
        headliners,
        supports,
        month if isinstance(month, int) else None,
        day if isinstance(day, int) else None,
        result.get("venues", []),
        result.get("event_name"),
    )
