#!/usr/bin/env bash
# Container entrypoint for Railway (and any other container host — Fly, Render, a plain VPS).
#
# This used to decode a base64 blob into .streamlit/secrets.toml before starting, because
# Streamlit reads secrets only from a file on disk: root-level keys are mirrored into env
# vars, but nested tables like [connections.snowflake] are not, so there was no way to pass
# Snowflake credentials as ordinary variables.
#
# Nothing needs a nested table any more. Every setting is a flat environment variable read
# by core/config.py, so the blob, the decode, the chmod and the TOML validation are all
# gone. This script now does exactly two things: check the app can start, and start it.

set -euo pipefail

# Fail before Streamlit boots rather than on the first page load. core/config.py raises on
# a missing value anyway, but a one-line message in the deploy log beats a traceback —
# especially since --client.showErrorDetails=none means the browser shows nothing useful.
missing=()
for var in NEON_APP_URL R2_ENDPOINT R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_PUBLIC_BASE; do
  [ -z "${!var:-}" ] && missing+=("$var")
done

if [ ${#missing[@]} -gt 0 ]; then
  echo "FATAL: missing required environment variable(s): ${missing[*]}" >&2
  echo "       Set them under Service -> Variables. NEON_ADMIN_URL must NOT be set here:" >&2
  echo "       it is the database owner and the app must never hold it." >&2
  exit 1
fi

# Deliberately a warning, not a failure. A missing key breaks poster scanning; it does not
# break browsing an archive of posters, and taking the gallery down over it would be the
# wrong trade. core/ai.py turns this into a calm message on the upload page.
if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "WARNING: OPENROUTER_API_KEY is unset — uploads will not be able to scan posters." >&2
fi

# `exec` replaces this shell with Streamlit so it becomes PID 1 and receives SIGTERM directly.
# Without it the shell holds PID 1, swallows the signal, and every deploy waits for the platform's
# kill timeout before the container dies.
exec streamlit run app.py \
  --server.port="${PORT:-8501}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.fileWatcherType=none \
  --browser.gatherUsageStats=false \
  --client.showErrorDetails=none
