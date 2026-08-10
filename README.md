# Beautiful Noise

A Narrm/Melbourne gig poster archive. Upload gig posters, let AI extract the metadata, confirm the details, and browse the collection.

**Live at [www.beautifulnoise.melbourne](https://www.beautifulnoise.melbourne)**

Built with [Streamlit](https://streamlit.io/) and [Snowflake](https://www.snowflake.com/).

## How It Works

1. **Upload** a gig poster (image or PDF)
2. **AI extracts** bands, venue, date, and event name (powered by Snowflake Cortex, running inside the Snowflake account — see the in-app FAQ)
3. **Review and confirm** the details (with fuzzy-matched suggestions) — nothing is saved until a person confirms it
4. **Browse the archive** — filter by band, venue, poster credit, or date

## Stack

- **Front-end:** Streamlit (requires Python 3.10+)
- **Database & AI:** Snowflake (Cortex `AI_COMPLETE` with a multimodal model, set in `core/config.py`)
- **Image processing:** Pillow, PyMuPDF (PDF support)
- **Fuzzy matching:** RapidFuzz

## Project structure

```
app.py          Entry point — theme, navigation, header and footer
views/          One script per page (gallery, upload, contact, terms)
core/           Everything that isn't UI
                  config.py   settings read from secrets
                  db.py       all Snowflake/Snowpark access
                  ai.py       Cortex extraction prompt and call
                  utils.py    pure helpers (text, images, filtering)
content/        User-facing copy rendered at runtime (faq.md, tos.md)
static/         Served at /app/static/ when enableStaticServing is on
sql/            Committed DDL — a record of the schema, not migrations
.streamlit/     Theme and server config
start.sh        Container entrypoint (writes secrets, launches Streamlit)
railway.json    Deployment config
```

Page URL slugs are pinned with `url_path` in `app.py`, so page files can be renamed without breaking links in the copy or URLs people have shared.

## Setup

Requires **Python 3.10+** (Streamlit 1.61 dropped 3.9).

1. Clone the repo
2. Create `.streamlit/secrets.toml` (gitignored). The app authenticates with an RSA key pair, not a password — MFA on the account breaks non-interactive password auth:
   ```toml
   [connections.snowflake]
   account = "..."
   user = "..."
   role = "..."
   warehouse = "..."
   database = "..."
   schema = "..."
   private_key = """-----BEGIN ENCRYPTED PRIVATE KEY-----
   ..."""
   private_key_passphrase = "..."

   [app]
   stage = "..."
   ```
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `streamlit run app.py`

There is no local or mocked Snowflake — the app always talks to the live instance for both data and AI extraction.

## Deployment

Hosted on [Railway](https://railway.com) as a single always-on container, with DNS through Cloudflare. Pushing to `main` triggers a rebuild and deploy.

`railway.json` sets the start command to `start.sh`, which reconstructs `.streamlit/secrets.toml` from a base64-encoded environment variable and then launches Streamlit on the port Railway assigns. The indirection exists because Streamlit reads secrets only from a file on disk — nested tables such as `[connections.snowflake]` are not exposed as environment variables, so they can't simply be set individually.

## Content Licence

Archive content is shared under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Uploaders retain copyright. See the in-app Terms of Service for full details.
