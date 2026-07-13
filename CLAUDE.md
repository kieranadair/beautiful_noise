# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Beautiful Noise — a Melbourne gig poster archive. Users upload gig posters, an LLM (Snowflake Cortex `AI_COMPLETE` with a multimodal model — currently `llama4-maverick`) extracts bands/venue/date/event metadata, the user reviews AI-suggested (fuzzy-matched) details, and confirmed posters are browsable in a filterable gallery. Deployed on Streamlit Community Cloud, backed by Snowflake (database + Cortex AI + file stage).

Stack: Streamlit (UI), Snowflake (database + Cortex AI + file stage), RapidFuzz (fuzzy matching), Pillow/PyMuPDF (image/PDF processing).

## Developer context

The developer is a beginner/intermediate programmer using this project to learn better coding practices and data engineering. When suggesting changes, reviewing code, or introducing new concepts: explain the *why* behind recommendations, not just the *what*. Use concrete examples and highlight transferable principles — treat this as a teaching relationship, not just ticket execution.

## Running the app

```
pip install -r requirements.txt
streamlit run app.py
```

Requires `.streamlit/secrets.toml` (gitignored, present locally) with a `[connections.snowflake]` block (account, user, role, warehouse, database, schema, key-pair auth fields `private_key`/`private_key_passphrase`) and an `[app]` block with `stage`. **This single secrets file is used for both local dev and production** — Streamlit Community Cloud copies its contents into its own secrets manager for the deployed app. There is no local/mocked Snowflake — the app always talks to the live Snowflake instance for both data and AI extraction. (The Cortex `model` is no longer a secret — it's a hardcoded constant in `config.py` so a model swap ships via git push, not a manual Cloud-secrets edit; a leftover `[app] model` key in secrets is ignored.)

There is no test suite, linter, or CI config in this repo — verify changes by running the app and exercising the relevant flow in the browser.

## Detailed context files

`.context/*.md` (gitignored, local reference only) has deep documentation beyond what's below — load the relevant one before working in that area:

| File | When to load |
|---|---|
| `.context/schema.md` | Writing queries, changing schema, working with roles/grants |
| `.context/upload-flow.md` | Touching `ai.py`, `upload_page.py`, or the extraction/validation pipeline |
| `.context/gallery.md` | Modifying `gallery_page.py`, filtering, poster dialog |
| `.context/contact-page.md` | Working on `contact_page.py` or any of its request flows |
| `.context/session-management.md` | Debugging connections, changing `db.py`, caching, retry logic |
| `.context/admin-app.md` | Working on `admin.py`, mutation handlers, staging, push-to-prod |
| `.context/data-flow.md` | Understanding function call chains, Snowpark interactions, table write/read paths |
| `.context/error-handling.md` | Exception flows, retry logic, failure recovery, orphan cleanup, debugging |
| `.context/performance.md` | Caching strategy, query patterns, warehouse wake-up, scaling limits |
| `.context/legal.md` | ToS, licensing, robots.txt |

These are a snapshot in time and can drift from the actual code — e.g. `schema.md`/`contact-page.md` describe a standalone `MISSING_BAND` request flow that isn't in the current `contact_page.py` (it was folded into the `LINEUP_EDIT` flow, entity_type `BILLING`). Treat `.context/` as a fast-orientation aid, not ground truth — check the actual source for anything load-bearing.

## Architecture — community app (this repo)

Flat, single-directory Streamlit multipage app. `app.py` is the entry point; it sets page config/theme and registers pages via `st.navigation` — `gallery_page.py` (browse/filter), `upload_page.py` (upload + AI review + save), `contact_page.py` (correction/takedown/attribution requests), `terms_of_service.py`.

Module responsibilities (each page imports from these — keep logic there, not duplicated in pages):
- `config.py` — reads `st.secrets` into module-level constants (`DB`, `SC`, `STAGE`, `MODEL`, `IMG_FORMAT`, `NAV_BTN_WIDTH`).
- `db.py` — all Snowflake/Snowpark access. `get_session()` builds a key-pair-authenticated session (RSA, bypasses MFA — see below), cached with `@st.cache_resource`. Every function that touches Snowflake is wrapped in `@with_retry`, which on any exception clears the cached session, reconnects, and retries once. Writes are MERGE-based upserts (`get_or_insert`, `get_or_insert_event`) so they're idempotent and safe to retry. `get_all_posters` is `@st.cache_data`-cached (no TTL) and must be explicitly `.clear()`-ed after any write that should be reflected in the gallery.
- `ai.py` — builds the extraction prompt (including the current venue list, so the model can match against known venues) and calls `ai_complete()` server-side in Snowflake. Uses a write-then-read pattern: the AI result is written to `POSTERS_RAW` first (since `ai_complete` executes server-side inside a `select()`), then read back by the poster's UUID filename.
- `utils.py` — pure functions with no Snowflake/Streamlit dependency: string normalisation, RapidFuzz-based fuzzy matching, date inference from AI-extracted `MM-DD` strings (picks whichever of last/this/next year is closest to today), image preprocessing (with content-format allowlisting + pixel-bomb guards, raising `ImageRejected` on bad input), PDF-to-JPEG conversion (DPI clamped to a pixel ceiling), and client-side filtering/deduplication over the cached poster list.

Data flow for an upload: image/PDF → `pdf_to_image_bytes` (PDF only) → `preprocess_image` (rejects malformed/oversized/unexpected-format files via `ImageRejected`) → MD5 dedup check against cached posters → `upload_to_stage` (Snowflake stage) → `run_extraction` (AI_COMPLETE, logged to `POSTERS_RAW`) → `prepare_review_defaults` (normalise + fuzzy-match against existing bands/venues + infer full date) → logged to `POSTERS_PROCESSED` for audit → user reviews/edits in a form (multiselects: Headliners, Support Acts, Credits) → semantic duplicate check (same bands+venue+date) → `save_poster` (upserts VENUES/BANDS/CREDITS/EVENTS, MERGEs POSTERS and BANDS_EVENTS with `IS_HEADLINER` per band, re-fetches poster_id and MERGEs POSTER_CREDITS) → `get_all_posters` cache cleared.

The gallery page uses `@st.fragment` for the filter/grid section so pagination and filter changes don't rerun the whole page, and `@st.dialog` for the poster detail modal. The contact page is a multi-branch request form (ATTRIBUTION, TAKEDOWN, CORRECTION [band/venue/credit/event], DATE_CORRECTION, LINEUP_EDIT) that writes structured rows to `REQUESTS` via `save_request` — no automated processing happens here, requests are reviewed/applied manually via the admin app. Note CORRECTION/`CREDIT` requests are submittable but not yet approvable in `admin.py` (fast-follow); ATTRIBUTION deliberately still carries `entity_type=DESIGNER` for the upload-type flip.

## Data model (Snowflake: `BEAUTIFUL_NOISE.DATA`)

Dimension tables `VENUES`, `BANDS`, `CREDITS` (upserted via MERGE, all-caps text) → `EVENTS` (dedups on name+date+venue via `equal_null`-safe MERGE) → `POSTERS` (one row per upload, FK to event, `md5_hash`, `upload_type` ∈ {RIGHTS_HOLDER, COMMUNITY}) → `BANDS_EVENTS` junction (`is_headliner` flag) and `POSTER_CREDITS` junction (many-to-many, poster↔credit, no role). `POSTER_GALLERY_V` pre-joins everything with `ARRAY_AGG` into `BANDS`/`HEADLINERS`/`SUPPORTS`/`CREDITS` arrays — this is what `get_all_posters()` queries. `POSTERS_RAW`/`POSTERS_PROCESSED` are audit trails (raw LLM output vs. post-fuzzy-match), joinable on `file_name`. `REQUESTS` holds contact-page submissions for manual admin review. Full column list and grants: `.context/schema.md`.

**UI wording:** the credits concept is surfaced to users as **"Poster by"** (gallery filter, upload field, poster detail byline) and **"Poster credit"** (contact correction form). Code and DB identifiers stay `credit`/`CREDITS`/`CREDIT` — the rename is display-only.

**Credits vs. legacy designer:** as of 2026-07-12 posters carry a multi-valued `CREDITS` list (designers, photographers, illustrators — flat, optional, like `BANDS`). The old single-designer model (`DESIGNERS` table, `POSTERS.DESIGNER_ID`, `POSTER_GALLERY_V.DESIGNER_NAME`) is **still present but frozen** — new uploads no longer write `DESIGNER_ID` (stays DEFAULT 1/UNKNOWN). It's kept only so the un-migrated `admin.py` keeps loading; dropping it and rewriting admin.py's designer handlers is a pending fast-follow (see memory `project-credits-migration`).

**`POSTER_GALLERY_V` uses a CTE** to pre-aggregate `CREDITS` per poster before the join — required because BANDS/HEADLINERS/SUPPORTS use non-`DISTINCT` `ARRAY_AGG`, so a naive credits join would fan out and duplicate those arrays. Preserve the CTE structure if rebuilding.

**Rebuilding `POSTER_GALLERY_V` drops its grants** (`CREATE OR REPLACE VIEW`) — always re-run `GRANT SELECT ON VIEW ... TO ROLE BEAUTIFUL_NOISE_APP` (and `... TO ROLE BEAUTIFUL_NOISE_ADMIN`) after replacing it, or the deployed app breaks.

## Admin app & staging (outside this repo)

`admin.py` is a separate single-file app deployed as Streamlit-in-Snowflake (`BEAUTIFUL_NOISE.DATA.ADMIN_REVIEW`) — gitignored, not part of this deploy. It reviews/approves/rejects `REQUESTS` rows and applies the resulting mutations. It operates against `BEAUTIFUL_NOISE.STAGING`, a zero-copy clone of `DATA`, by default, with a "Push to Production" action to replay approved mutations against real `DATA` tables. See `.context/admin-app.md` for the full mutation-handler reference and `.context/data-flow.md` for write paths. The SiS runtime is an older Streamlit version (no `use_container_width`, no `st.rerun()` — use `st.experimental_rerun()`, no `:material/` icon syntax) — don't assume feature parity with this repo's Streamlit version when touching `admin.py`.

## Snowflake access for schema/DDL work

There is **no working local Snowflake CLI connection** in this environment. A SnowSQL config exists at `~/.snowsql/config` with a saved connection (account `HEPCWGZ-QM48128`, user `kieranadair`) but it points at an **expired free-trial account** — it fails with "Your free trial has ended and all of your virtual warehouses have been suspended." Do not assume this connection works; verify before relying on it.

`.streamlit/secrets.toml` holds the app's runtime credential (service account `BN_APP_SVC`, RSA key-pair auth, role `BEAUTIFUL_NOISE_APP`). Connect directly with `snowflake-snowpark-python` + `cryptography` (same PEM→DER pattern as `get_session()` in `db.py`) via a throwaway script — there's no MCP or CLI wired up, so this is the only working path.

**As of 2026-07-12, `BEAUTIFUL_NOISE_APP` was temporarily granted ownership of the `BEAUTIFUL_NOISE.DATA` and `.STAGING` schemas** (normally it's least-privilege — `SELECT`+`INSERT` only) so DDL work can happen through this one credential without minting new ones. This means schema/DDL changes are currently possible through `secrets.toml` directly. **This is meant to be temporary** — it should be reverted to least-privilege once active schema work winds down (revert script covers this; see memory `project-snowflake-temp-ddl-privileges`). If a session finds this grant still active a while after schema work seems to have concluded, flag it to the user rather than assuming it's fine to leave.

## API currency — verify before assuming

This app leans on fairly new Streamlit and Snowflake Cortex surface (`st.dialog`, `st.fragment`, `accept_new_options=True`, `st.space`, `AI_COMPLETE` with structured `response_format`, Snowpark `equal_null`/MERGE patterns). Training-data knowledge of fast-moving APIs like these can be stale or wrong by the time you're reading this. Before using or changing an API you're not fully certain about — especially anything touching `st.*` widgets, Snowpark DataFrame methods, or Cortex functions — use WebSearch/WebFetch to check the current docs (`docs.streamlit.io`, `docs.snowflake.com`) rather than relying on memory. This matters more here than in a typical repo because the developer is learning from these changes, so a subtly-wrong API call teaches the wrong thing as much as it breaks the app.

## Key design decisions

- **Cheap multimodal Cortex model** for extraction (currently `llama4-maverick`, set in `config.py`) — a budget vision model is plenty for this simple structured-extraction task; premium models (Claude/GPT-4.1) aren't worth several× the cost here. Must be image-capable (the call passes `to_file()`); any AI_COMPLETE model supports `response_format`. `llama4-scout` was the original choice but was deprecated 2026-07-08.
- **Snowpark DataFrame API** over raw SQL in `db.py` — don't use `S.sql()` unless there's no Snowpark equivalent (the one exception in this repo's scope is stage-file `REMOVE`, which has no DataFrame API).
- User always confirms/edits AI extractions before saving — nothing is auto-committed from the LLM.
- **All text stored UPPER CASE** in the DB (`normalise()` in `utils.py`).
- **Escape user-controlled text at every Streamlit markdown sink** (`st.write`/`header`/`subheader`/`markdown`/`info`/`error` and widget *labels* — not plain-text widget *options*) with `md_escape()` from `utils.py`. Uploads are anonymous and band/venue/event/credit names are free text (typed or LLM-extracted), so unescaped names inject live links, tracking-pixel images, and layout defacement into the gallery/contact pages. Output-encode at the sink — **never** strip at input, since real names legitimately contain markdown chars (`!!!`, `SUNN O)))`). HTML/JS is already safe (`unsafe_allow_html` stays off for user data); this closes the markdown-syntax gap.
- **Never build SQL via `S.sql()` + f-strings.** All DB access goes through the Snowpark DataFrame API (`create_dataframe`/`merge`/`col()==value`/`lit()`), which escapes values as data literals — this is what keeps SQL injection closed given the free-text inputs. `S.sql()` with interpolated user text would reopen it.
- No third-party UI component packages — native Streamlit only (or `st.html` with inline JS).
- **RSA key-pair authentication** (not password) for the service account — required because MFA enforcement on the Snowflake account breaks non-interactive password auth from Streamlit Cloud. See `.context/session-management.md` for the PEM→DER conversion details in `get_session()`.
- Reactive reconnection only (`@with_retry`), no proactive session health-check pings — a previous proactive-ping approach kept the warehouse alive overnight and burned ~$14/day in idle credits.
- Filtering, pagination, and duplicate detection all run in Python over the `@st.cache_data`-cached poster list — no per-interaction Snowflake round-trips.
