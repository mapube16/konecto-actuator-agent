#!/bin/sh
# Populate SQLite + ChromaDB on container start if the volume is empty, then serve.
# ingest.py is idempotent (drop & recreate), so running it every boot is safe; we guard
# on actuators.db so a warm volume skips the ~one-time embedding cost.
set -e

if [ ! -f /app/data/actuators.db ]; then
  echo "[entrypoint] data volume empty — running ingest.py..."
  python scripts/ingest.py
else
  echo "[entrypoint] actuators.db present — skipping ingest"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
