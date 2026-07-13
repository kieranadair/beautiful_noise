import re
from datetime import date
from io import BytesIO
from rapidfuzz import process, fuzz
from PIL import Image
import fitz
from config import IMG_FORMAT, MAX_IMAGE_PIXELS, PDF_RENDER_DPI, ALLOWED_IMAGE_FORMATS

# Decode-time backstop: PIL raises DecompressionBombError once an image exceeds
# 2x this during actual decode. We also check img.size up front (see
# _guard_pixels) to reject *before* the expensive decode; this catches crafted
# headers that under-report their true dimensions.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageRejected(Exception):
    """Raised when an uploaded file is malformed, too large, or an unexpected
    format. The message is safe to show the user verbatim (no internals)."""


def _guard_pixels(size: tuple[int, int]) -> None:
    """Reject an image whose pixel count exceeds MAX_IMAGE_PIXELS before we
    decode it. Called with img.size (read from the header, no full decode)."""
    w, h = size
    if w * h > MAX_IMAGE_PIXELS:
        raise ImageRejected("That image is too large to process. Please upload a smaller poster.")

def normalise(s: str | None) -> str | None:
    """Normalise a string for DB storage: strip, uppercase, None if empty/null."""
    if not s or s.strip().upper() == "NULL":
        return None
    return s.strip().upper()

# Standard-markdown metacharacters that respond to backslash escaping: links/images
# ([ ] ( ) !), emphasis (* _), code (`), heading/blockquote (# >), tables (|), strikethrough
# (~), LaTeX ($), braces ({ }), and the escape char itself (\). Deliberately excludes . - +
# (only markdown-significant at line start; escaping them mangles common names like "BLINK-182").
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#!|>~$])")
# Streamlit renders two things OUTSIDE standard CommonMark that backslashes DON'T neutralise
# (confirmed via live render check): GFM autolinking of bare http/https/www URLs, and its own
# ':directive:' tokens (:material/…:, :emoji:, :red[…]). We break those token patterns with a
# zero-width space — invisible on screen, and only ever inserted into display copies.
_ZWSP = "​"
_URL_SCHEME = re.compile(r"(?i)(https?|www)")

def md_escape(s: str | None) -> str | None:
    """Make user-supplied text render LITERALLY in Streamlit's markdown sinks (st.write/header/
    subheader/markdown/info/error and widget labels): backslash-escape standard markdown chars,
    then zero-width-space-break bare URLs and ':directives:' that ignore backslashes.
    Output-encoding only — apply at the render sink, NEVER to stored or compared values, and never
    strip at input: real band names contain these chars (e.g. "!!!", "SUNN O)))"). None/empty pass through."""
    if not s:
        return s
    s = _MD_SPECIAL.sub(r"\\\1", str(s))
    s = s.replace(":", ":" + _ZWSP)
    s = _URL_SCHEME.sub(r"\1" + _ZWSP, s)
    return s

def fuzzy_match(value: str | None, existing: list[str], threshold: int = 80) -> str | None:
    """Return closest match from `existing` if score >= threshold, else original value.
    Uses rapidfuzz for fast approximate string matching."""
    if not value or not existing:
        return value
    match = process.extractOne(value, existing, scorer=fuzz.token_set_ratio, score_cutoff=threshold)
    return match[0] if match else value

def infer_date(mm_dd: str) -> date:
    """Infer full date from MM-DD string by picking the year closest to today.
    Returns today's date if input is empty or unparseable."""
    if not mm_dd:
        return date.today()
    try:
        today = date.today()
        candidates = [date.fromisoformat(f"{today.year + i}-{mm_dd}") for i in (-1, 0, 1)]
        return min(candidates, key=lambda d: abs((d - today).days))
    except ValueError:
        return date.today()

def preprocess_image(file: BytesIO, max_dim: int = 1200, max_bytes: int = 800_000) -> BytesIO:
    """Resize and compress a file-like image to the pipeline format (IMG_FORMAT from config)
    for web display and AI extraction. Steps down quality until file fits under max_bytes.
    Rejects unexpected formats and oversized images before decoding — raises ImageRejected
    (safe-to-display message) on any bad/unreadable input."""
    try:
        img = Image.open(file)
        # Content-based format allowlist. PIL decodes by magic bytes regardless of the
        # uploaded file's extension, so this — not the file_uploader type= list — is what
        # actually constrains which codecs run on untrusted input.
        if img.format not in ALLOWED_IMAGE_FORMATS:
            raise ImageRejected("That image format isn't supported. Please upload a JPG, PNG, or WEBP.")
        # Reject pixel bombs from the header, before convert()/thumbnail() force a full decode.
        _guard_pixels(img.size)

        if img.mode != "RGB":
            img = img.convert("RGB")

        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))

        buf = BytesIO()

        for quality in (95, 85, 75, 60, 45):
            buf.seek(0)
            buf.truncate()
            img.save(buf, format=IMG_FORMAT, quality=quality)
            if buf.tell() <= max_bytes:
                break

        return buf
    except ImageRejected:
        raise
    except Exception:
        # Anything else (DecompressionBombError, a codec crash on crafted input, a
        # truncated file) becomes a friendly rejection — never a leaked stack trace.
        raise ImageRejected("We couldn't process that image. Please try a different file.")

def pdf_to_image_bytes(file: BytesIO, dpi: int = PDF_RENDER_DPI) -> BytesIO:
    """Convert the first page of a PDF to JPEG bytes. Renders at `dpi`, but clamps the DPI
    down if the page is large enough that rendering would exceed MAX_IMAGE_PIXELS — a PDF
    MediaBox can be arbitrarily large, so a fixed DPI is a memory-exhaustion vector.
    Raises ImageRejected (safe-to-display message) on any unreadable/empty PDF."""
    try:
        with fitz.open(stream=file, filetype="pdf") as doc:
            if doc.page_count < 1:
                raise ImageRejected("That PDF has no pages.")
            page = doc[0]
            # Projected pixmap size at the requested DPI (page.rect is in points, 72/in).
            projected = (page.rect.width / 72 * dpi) * (page.rect.height / 72 * dpi)
            if projected > MAX_IMAGE_PIXELS:
                # Scale DPI so the rendered pixmap lands just under the ceiling. Floor at 1
                # (get_pixmap needs dpi >= 1); an absurdly large page rendering small is the
                # right trade-off vs. OOM. A page so vast that even 1 DPI exceeds the ceiling
                # falls to the generic except below as ImageRejected.
                dpi = max(1, int(dpi * (MAX_IMAGE_PIXELS / projected) ** 0.5))
            pix = page.get_pixmap(dpi=dpi)
            return BytesIO(pix.tobytes(IMG_FORMAT))
    except ImageRejected:
        raise
    except Exception:
        raise ImageRejected("We couldn't read that PDF. Please try exporting it as an image.")

def get_filtered_posters(all_posters: list[dict], band_filter: list[str] | None = None, venue_filter: list[str] | None = None, credit_filter: list[str] | None = None, month_range: tuple | None = None, headline_only: bool = False, show_community: bool = True) -> list[dict]:
    """Filter cached poster list in Python by bands, venues, credits, month range, and headliner flag.
    When headline_only is True and bands are filtered, only matches bands that appear as headliners.
    When show_community is False, community-uploaded posters are excluded.
    All filtering is done client-side on the cached result, not in Snowflake."""
    posters = all_posters
    if band_filter:
        band_set = set(band_filter)
        if headline_only:
            posters = [p for p in posters if any(b in band_set for b in p["HEADLINERS"])]
        else:
            posters = [p for p in posters if any(b in band_set for b in p["BANDS"])]
    if venue_filter:
        venue_set = set(venue_filter)
        posters = [p for p in posters if p["VENUE_NAME"] in venue_set]
    if credit_filter:
        credit_set = set(credit_filter)
        posters = [p for p in posters if any(c in credit_set for c in p["CREDITS"])]
    if month_range:
        posters = [p for p in posters if month_range[0] <= p["DATE"].replace(day=1) <= month_range[1]]
    if not show_community:
        posters = [p for p in posters if p["UPLOAD_TYPE"] != "COMMUNITY"]
    return posters

def get_poster_vars(all_posters: list[dict]) -> tuple[list[str], list[str], list[str], date, date]:
    """Extract sorted unique bands, venues, credits, and date range from cached poster data.
    Used to populate filter options and form dropdowns."""
    all_bands = sorted(set(band for o in all_posters for band in o["BANDS"]))
    all_venues = sorted(set(o["VENUE_NAME"] for o in all_posters))
    all_credits = sorted(set(c for o in all_posters for c in o["CREDITS"]))
    date_min = min(o["DATE"] for o in all_posters)
    date_max = max(o["DATE"] for o in all_posters)
    return all_bands, all_venues, all_credits, date_min, date_max

def prepare_review_defaults(headliners: list[str], supports: list[str], date_str: str, venue: str, event_name: str | None, all_bands: list[str], all_venues: list[str]) -> tuple[list[str], list[str], date, str | None, str | None]:
    """Normalise, fuzzy-match, and infer date from raw AI extraction values.
    Returns (matched_headliners, matched_supports, inferred_date, matched_venue, normed_event_name)."""
    normed_headliners = [n for b in headliners if (n := normalise(b))]
    matched_headliners = [fuzzy_match(b, all_bands, threshold=90) for b in normed_headliners]
    normed_supports = [n for b in supports if (n := normalise(b))]
    matched_supports = [fuzzy_match(b, all_bands, threshold=90) for b in normed_supports]

    inferred_date = infer_date(date_str)
    
    normed_venue = normalise(venue)
    matched_venue = fuzzy_match(normed_venue, all_venues, threshold=80) if normed_venue else None
    
    normed_event_name = normalise(event_name)
    
    return matched_headliners, matched_supports, inferred_date, matched_venue, normed_event_name

def prepare_save_data(headliners: list[str], supports: list[str], event_date, venue: str, event_name: str, credits: list[str]) -> dict:
    """Normalise raw form values into a clean dict ready for save_poster().
    Applies normalise() to all text fields; passes event_date through as-is.
    bands is the merged headliners + supports list; headliners preserved for IS_HEADLINER flag.
    credits is normalised the same way as bands — a flat list, may be empty."""
    normed_headliners = [n for b in headliners if (n := normalise(b))]
    normed_supports = [n for b in supports if (n := normalise(b))]
    normed_credits = [n for c in credits if (n := normalise(c))]
    return {
        "bands": normed_headliners + normed_supports,
        "headliners": normed_headliners,
        "event_date": event_date,
        "venue": normalise(venue) or "",
        "event_name": normalise(event_name),
        "credits": normed_credits
    }

def check_duplicate_md5(md5_hash: str, all_posters: list[dict]) -> bool:
    """Check if an MD5 hash matches any existing poster. Returns True if duplicate found.
    Runs against cached poster data — no Snowflake call."""
    return any(p["MD5_HASH"] == md5_hash for p in all_posters)

def check_semantic_duplicate(bands: list[str], venue: str, event_date, all_posters: list[dict]) -> bool:
    """Check if a poster with the same bands, venue, and date already exists.
    Compares frozenset(bands), venue, and date. Runs against cached poster data — no Snowflake call.
    Returns True if duplicate found."""
    check = (frozenset(b.upper() for b in bands), venue.upper(), event_date)
    return any(
        (frozenset(p["BANDS"]), p["VENUE_NAME"], p["DATE"]) == check
        for p in all_posters
    )

def month_range(start: date, end: date) -> list[date]:
    """List of first-of-month dates from start to end (inclusive).
    Used to populate the date slider in the gallery."""
    months = []
    d = start.replace(day=1)
    end = end.replace(day=1)
    while d <= end:
        months.append(d)
        if d.month == 12: d = date(d.year + 1, 1, 1)
        else: d = date(d.year, d.month + 1, 1)
    return months

def poster_has(p: dict, entity_type: str, value: str) -> bool:
    """Check if a poster matches an entity value by type. Works with cached poster dicts.
    BAND and CREDIT are multi-valued (membership); VENUE is scalar (equality)."""
    if entity_type in ("BAND", "CREDIT"): return value in p[{"BAND": "BANDS", "CREDIT": "CREDITS"}[entity_type]]
    return p[{"VENUE": "VENUE_NAME"}[entity_type]] == value
