from datetime import date
from io import BytesIO
from rapidfuzz import process
from PIL import Image
import fitz
from config import IMG_FORMAT

def normalise(s: str | None) -> str | None:
    """Normalise a string for DB storage: strip, uppercase, None if empty/null."""
    if not s or s.strip().upper() == "NULL":
        return None
    return s.strip().upper()

def fuzzy_match(value: str | None, existing: list[str], threshold: int = 80) -> str | None:
    """Return closest match from `existing` if score >= threshold, else original value.
    Uses rapidfuzz for fast approximate string matching."""
    if not value or not existing:
        return value
    match = process.extractOne(value, existing, score_cutoff=threshold)
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
    for web display and AI extraction. Steps down quality until file fits under max_bytes."""
    img = Image.open(file)

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

def pdf_to_image_bytes(file: BytesIO) -> BytesIO:
    """Convert first page of a PDF to JPEG bytes at 150 DPI. Returns a BytesIO object."""
    with fitz.open(stream=file, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=150)
        return BytesIO(pix.tobytes(IMG_FORMAT))

def get_filtered_posters(all_posters: list[dict], band_filter: list[str] | None = None, venue_filter: list[str] | None = None, designer_filter: list[str] | None = None, month_range: tuple | None = None) -> list[dict]:
    """Filter cached poster list in Python by bands, venues, designers, and/or month range.
    All filtering is done client-side on the cached result, not in Snowflake."""
    posters = all_posters
    if band_filter:
        band_set = set(band_filter)
        posters = [p for p in posters if any(b in band_set for b in p["BANDS"])]
    if venue_filter:
        venue_set = set(venue_filter)
        posters = [p for p in posters if p["VENUE_NAME"] in venue_set]
    if designer_filter:
        designer_set = set(designer_filter)
        posters = [p for p in posters if p["DESIGNER_NAME"] in designer_set]
    if month_range:
        posters = [p for p in posters if month_range[0] <= p["DATE"].replace(day=1) <= month_range[1]]
    return posters

def get_poster_vars(all_posters: list[dict]) -> tuple[list[str], list[str], list[str], date, date]:
    """Extract sorted unique bands, venues, designers, and date range from cached poster data.
    Used to populate filter options and form dropdowns."""
    all_bands = sorted(set(band for o in all_posters for band in o["BANDS"]))
    all_venues = sorted(set(o["VENUE_NAME"] for o in all_posters))
    all_designers = sorted(set(o["DESIGNER_NAME"] for o in all_posters))
    date_min = min(o["DATE"] for o in all_posters)
    date_max = max(o["DATE"] for o in all_posters)
    return all_bands, all_venues, all_designers, date_min, date_max

def prepare_review_defaults(bands: list[str], date_str: str, venue: str, event_name: str | None, all_bands: list[str], all_venues: list[str]) -> tuple[list[str], date, str | None, str | None]:
    """Normalise, fuzzy-match, and infer date from raw AI extraction values.
    Returns (matched_bands, inferred_date, matched_venue, normed_event_name)."""
    normed_bands = [n for b in bands if (n := normalise(b))]
    matched_bands = [fuzzy_match(b, all_bands, threshold=90) for b in normed_bands]

    inferred_date = infer_date(date_str)
    
    normed_venue = normalise(venue)
    matched_venue = fuzzy_match(normed_venue, all_venues, threshold=80) if normed_venue else None
    
    normed_event_name = normalise(event_name)
    
    return matched_bands, inferred_date, matched_venue, normed_event_name

def prepare_save_data(bands: list[str], event_date, venue: str, event_name: str, designer_name: str) -> dict:
    """Normalise raw form values into a clean dict ready for save_poster().
    Applies normalise() to all text fields; passes event_date through as-is."""
    return {
        "bands": [n for b in bands if (n := normalise(b))],
        "event_date": event_date,
        "venue": normalise(venue) or "",
        "event_name": normalise(event_name),
        "designer_name": normalise(designer_name)
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
