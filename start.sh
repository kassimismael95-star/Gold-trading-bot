#!/bin/bash

set -e

echo "Starting Gold Scalper AI - Matrix Control"

if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL is not set."
  exit 1
fi

if [ -z "$SECRET_KEY" ]; then
  echo "ERROR: SECRET_KEY is not set."
  exit 1
fi

if [ -z "$WORKER_SHARED_SECRET" ]; then
  echo "ERROR: WORKER_SHARED_SECRET is not set."
  exit 1
fi

echo "Running database migrations..."
python -m database.migrations

echo "Starting Gunicorn server..."
exec gunicorn "app:app" \
  --bind "0.0.0.0:${PORT:-5000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${WEB_THREADS:-4}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
