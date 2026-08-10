#!/usr/bin/env bash
# Container entrypoint for Railway (and any other container host — Fly, Render, a plain VPS).
#
# Why this script exists at all: Streamlit reads secrets *only* from .streamlit/secrets.toml on
# disk. Root-level secrets are mirrored into environment variables, but nested tables like
# [connections.snowflake] are not — so there is no way to hand Snowflake credentials to this app
# as ordinary env vars. Instead the whole secrets file travels as one base64 blob and is written
# to disk here, before Streamlit starts.
#
# Base64 rather than raw text because the Snowflake private key is a multi-line PEM, and most
# platform secret UIs mangle newlines. Base64 is *encoding, not encryption* — the value of
# STREAMLIT_SECRETS_B64 is exactly as sensitive as secrets.toml itself.

set -euo pipefail

if [ -z "${STREAMLIT_SECRETS_B64:-}" ]; then
  echo "FATAL: STREAMLIT_SECRETS_B64 is unset — app cannot authenticate to Snowflake." >&2
  exit 1
fi

mkdir -p .streamlit
printf '%s' "$STREAMLIT_SECRETS_B64" | base64 -d > .streamlit/secrets.toml
chmod 600 .streamlit/secrets.toml

# Fail loudly now rather than serving a broken app: a truncated or mis-pasted blob decodes to
# something that isn't valid TOML, and Streamlit would only complain on the first page load.
if ! grep -q '^\[connections.snowflake\]' .streamlit/secrets.toml; then
  echo "FATAL: decoded secrets.toml has no [connections.snowflake] block — bad or truncated blob." >&2
  exit 1
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
