#!/usr/bin/env bash
# Starts the Sidequest API. Used as Render's start command (see render.yaml).
#
# With LITESTREAM_BUCKET set, the SQLite databases are continuously backed up to
# an S3-compatible bucket (Cloudflare R2) by Litestream:
#   1. restore each database from the bucket (skipped if there's no backup yet)
#   2. run uvicorn under `litestream replicate`, which uploads every change
#      within ~1 second and does a final sync when Render stops the server.
# Without it, uvicorn just runs on its own (fine on a paid plan with a disk).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
APP="uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips '*'"

if [ -z "${LITESTREAM_BUCKET:-}" ]; then
  echo "LITESTREAM_BUCKET not set - starting without backups"
  eval exec "$APP"
fi

export DATABASE_PATH="${DATABASE_PATH:-data/sidequest.db}"
export LIBRARY_PATH="${LIBRARY_PATH:-data/quest_library.db}"
export HISTORY_PATH="${HISTORY_PATH:-data/user_history.db}"
export LITESTREAM_REGION="${LITESTREAM_REGION:-auto}"
export LITESTREAM_PREFIX="${LITESTREAM_PREFIX:-sidequest}"
: "${LITESTREAM_ENDPOINT:?set LITESTREAM_ENDPOINT, e.g. https://<account-id>.r2.cloudflarestorage.com}"
: "${LITESTREAM_ACCESS_KEY_ID:?set LITESTREAM_ACCESS_KEY_ID}"
: "${LITESTREAM_SECRET_ACCESS_KEY:?set LITESTREAM_SECRET_ACCESS_KEY}"

LITESTREAM="bin/litestream"
[ -x "$LITESTREAM" ] || LITESTREAM="$(command -v litestream)"

for db in "$DATABASE_PATH" "$LIBRARY_PATH" "$HISTORY_PATH"; do
  mkdir -p "$(dirname "$db")"
  # -if-db-not-exists: keep a database that's already on disk (paid plan with a disk)
  # -if-replica-exists: first ever start, nothing backed up yet -> start empty
  # Any other failure (wrong keys, bucket unreachable) stops the start, so an
  # empty database never replaces your backups.
  if ! timeout 90 "$LITESTREAM" restore -config litestream.yml -if-db-not-exists -if-replica-exists "$db"; then
    echo "ERROR: couldn't restore $db from bucket '$LITESTREAM_BUCKET' at $LITESTREAM_ENDPOINT." >&2
    echo "Check the LITESTREAM_* settings. Not starting, so an empty database can't replace your backups." >&2
    exit 1
  fi
done

exec "$LITESTREAM" replicate -config litestream.yml -exec "$APP"
