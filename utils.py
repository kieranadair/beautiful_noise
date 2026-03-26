from datetime import date
from io import BytesIO
from rapidfuzz import process
from PIL import Image
import fitz
def normalise(s):
    """Normalise a string for DB storage: strip, uppercase, None if empty/null."""
    if not s or s.strip().upper() == "NULL":
        return None
    return s.strip().upper()
def fuzzy_match(value: str, existing: list[str], threshold: int = 80) -> str:
    """Return closest match from `existing` if score >= threshold, else original value."""
    if not value or not existing:
        return value
    match = process.extractOne(value, existing, score_cutoff=threshold)
    return match[0] if match else value
def infer_date(mm_dd: str) -> date:
    """Infer full date from MM-DD string by picking the year closest to today."""
    if not mm_dd:
        return date.today()
    try:
        today = date.today()
        candidates = [date.fromisoformat(f"{today.year + i}-{mm_dd}") for i in (-1, 0, 1)]
        return min(candidates, key=lambda d: abs((d - today).days))
    except ValueError:
        return date.today()
def preprocess_image(file: BytesIO, format: str = "JPEG", max_dim: int = 1200, max_bytes: int = 800_000) -> BytesIO:
    """Resize and compress a file-like image to JPEG for web display and AI extraction."""
    img = Image.open(file)

    if img.mode != "RGB":
        img = img.convert("RGB")

    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim))
    
    buf = BytesIO()

    for quality in (95, 85, 75, 60, 45):
        buf.seek(0)
        buf.truncate()
        img.save(buf, format=format, quality=quality)
        if buf.tell() <= max_bytes:
            break
    
    return buf
def pdf_to_image_bytes(file) -> BytesIO:
    """Convert first page of a PDF to JPEG bytes. Returns a BytesIO object."""
    with fitz.open(stream=file, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=150)
        return BytesIO(pix.tobytes("jpeg"))
def get_filtered_posters(all_posters, band_filter=None, venue_filter=None, designer_filter=None, month_range=None):
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
def get_poster_vars(all_posters):
    all_bands = sorted(set([band for o in all_posters for band in o["BANDS"]]))
    all_venues = sorted(set([o["VENUE_NAME"] for o in all_posters]))
    all_designers = sorted(set([o["DESIGNER_NAME"] for o in all_posters]))
    date_min = min([o["DATE"] for o in all_posters])
    date_max = max([o["DATE"] for o in all_posters])
    return all_bands, all_venues, all_designers, date_min, date_max
def prepare_review_defaults(bands, date_str, venue, event_name, all_bands, all_venues):
    """Normalise, fuzzy-match, and infer date from raw AI extraction values.
    
    Returns matched_bands, matched_venue, event_name, inferred_date.
    """
    normed_bands = [n for b in bands if (n := normalise(b))]
    matched_bands = [fuzzy_match(b, all_bands, threshold=90) for b in normed_bands]

    inferred_date = infer_date(date_str)
    
    normed_venue = normalise(venue)
    matched_venue = fuzzy_match(normed_venue, all_venues, threshold=80) if normed_venue else None
    
    normed_event_name = normalise(event_name)
    
    return matched_bands, inferred_date, matched_venue, normed_event_name
def prepare_save_data(bands, event_date, venue, event_name, designer_name):
    """Normalise raw form values into a clean dict ready for save_poster()."""
    return {
        "bands": [n for b in bands if (n := normalise(b))],
        "event_date": event_date,
        "venue": normalise(venue) or "",
        "event_name": normalise(event_name),
        "designer_name": normalise(designer_name)
    }
def check_duplicate_md5(md5_hash, all_posters):
    """Check if an MD5 hash matches any existing poster. Returns True if duplicate found."""
    return any(p["MD5_HASH"] == md5_hash for p in all_posters)
def check_semantic_duplicate(bands, venue, event_date, all_posters):
    """Check if a poster with the same bands, venue, and date already exists.
    Returns True if duplicate found."""
    check = (frozenset(b.upper() for b in bands), venue.upper(), event_date)
    return any(
        (frozenset(p["BANDS"]), p["VENUE_NAME"], p["DATE"]) == check
        for p in all_posters
    )
def month_range(start, end):
    """List of first-of-month dates from start to end (inclusive)."""
    months = []
    d = start.replace(day=1)
    end = end.replace(day=1)
    while d <= end:
        months.append(d)
        if d.month == 12: d = date(d.year + 1, 1, 1)
        else: d = date(d.year, d.month + 1, 1)
    return months
