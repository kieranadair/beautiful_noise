
# Beautiful Noise

A Melbourne gig poster archive. Upload gig posters, let AI extract the metadata, confirm the details, and browse the collection.

Built with [Streamlit](https://streamlit.io/) and [Snowflake](https://www.snowflake.com/).

## How It Works

1. **Upload** a gig poster (image or PDF)
2. **AI extracts** bands, venue, date, and event name (powered by Snowflake Cortex)
3. **Review and confirm** the details (with fuzzy-matched suggestions)
4. **Browse the archive** — filter by band, venue, designer, or date

## Stack

- **Front-end:** Streamlit
- **Database & AI:** Snowflake (Cortex `AI_COMPLETE` with Llama 4 Scout)
- **Image processing:** Pillow, PyMuPDF (PDF support)
- **Fuzzy matching:** RapidFuzz

## Setup

1. Clone the repo
2. Copy your Snowflake credentials into `.streamlit/secrets.toml`:
   ```toml
   [connections.snowflake]
   account = "..."
   user = "..."
   password = "..."
   warehouse = "COMPUTE_WH"
   ```
3. Install dependencies: `pip install -r requirements.txt`
4. Run: `streamlit run app.py`

## Content Licence

Archive content is shared under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Uploaders retain copyright. See the in-app Terms of Service for full details.
