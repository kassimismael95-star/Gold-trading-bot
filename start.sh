#!/bin/sh
set -e

echo "Initializing BOSSMODE control plane..."

python -c "from app import initialize; initialize()"

echo "Starting Gunicorn..."

exec python -m gunicorn app:app --workers 2 --threads 4 --bind 0.0.0.0:$PORT
