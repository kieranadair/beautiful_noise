# Beautiful Noise

A Narrm/Melbourne gig poster archive. Upload gig posters, let AI extract the metadata, confirm the details, and browse the collection.

**Live at [www.beautifulnoise.melbourne](https://www.beautifulnoise.melbourne)**

Built with [Streamlit](https://streamlit.io/), [Neon](https://neon.com/) Postgres, [Cloudflare R2](https://developers.cloudflare.com/r2/) and the [Anthropic API](https://www.anthropic.com/api).

## How It Works

1. **Upload** a gig poster (image or PDF)
2. **AI extracts** bands, venue, date, and event name — see the in-app FAQ for how the image is handled
3. **Review and confirm** the details (with fuzzy-matched suggestions) — nothing is saved until a person confirms it
4. **Browse the archive** — filter by band, venue, poster credit, or date

Nothing is stored until step 3 completes: the image is sent for extraction from memory, so a rejected or abandoned upload leaves nothing behind.

## Stack

- **Front-end:** Streamlit (requires Python 3.13; see Setup)
- **Database:** Neon Postgres, via psycopg3
- **Image storage:** Cloudflare R2, served to browsers directly from a public custom domain so images never pass through the app host
- **AI:** Anthropic API (Claude Haiku 4.5), with structured outputs
- **Image processing:** Pillow, PyMuPDF (PDF support)
- **Fuzzy matching:** RapidFuzz

## Project structure

```
app.py          Entry point — theme, navigation, header, footer, error boundary
views/          One script per page (gallery, upload, poster_requests, terms)
core/           Everything that isn't UI
                  config.py   settings read from the environment
                  db.py       all Postgres and R2 access
                  ai.py       extraction prompt and Anthropic API call
                  utils.py    pure helpers (text, images, filtering)
content/        User-facing copy rendered at runtime (faq.md, tos.md)
sql/postgres/   Schema, view, roles — applied by apply.py, not dumped
static/         Served at /app/static/ when enableStaticServing is on
.streamlit/     Theme and server config
start.sh        Container entrypoint (checks config, launches Streamlit)
railway.json    Deployment config
```

Page URL slugs are pinned with `url_path` in `app.py`, so page files can be renamed without breaking links in the copy or URLs people have shared.

## Setup

Requires **Python 3.13** (`.python-version` pins it; Streamlit 1.61 needs 3.10+).

1. Clone the repo.
2. Create a virtual environment on 3.13 and install dependencies:
   ```
   python3.13 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. Create `.env` in the repo root (gitignored):
   ```
   NEON_APP_URL=postgresql://...-pooler.../neondb?sslmode=require
   NEON_ADMIN_URL=postgresql://...   # owner connection, local only
   R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com
   R2_BUCKET=beautiful-noise-posters
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   R2_PUBLIC_BASE=https://posters.beautifulnoise.melbourne
   ANTHROPIC_API_KEY=...
   ```
4. Run: `.venv/bin/streamlit run app.py`

There is no local or mocked database — the app always talks to live Neon.

To build a database from scratch, `.venv/bin/python sql/postgres/apply.py` creates the schema, the view and the application role, then verifies the privilege boundary by exercising it. See `sql/README.md`.

There is no linter configured, so run `pyflakes` before pushing:

```
.venv/bin/python -m pyflakes app.py core/*.py views/*.py
```

## Deployment

Hosted on [Railway](https://railway.com) as a single always-on container, with DNS through Cloudflare. Pushing to `main` triggers a rebuild and deploy.

`railway.json` sets the start command to `start.sh`, which checks the required environment variables are present and then `exec`s Streamlit on the port Railway assigns. The same variable names used in `.env` are set as Railway service variables — with the exception of `NEON_ADMIN_URL`, which is the database owner connection and is never given to the app.

## Content Licence

Archive content is shared under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Uploaders retain copyright. See the in-app Terms of Service for full details.
