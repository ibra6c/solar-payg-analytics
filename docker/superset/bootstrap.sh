#!/bin/bash
# Initialise Superset metadata and start the web server.
set -euo pipefail

superset db upgrade

superset fab create-admin \
    --username "${SUPERSET_ADMIN_USER}" \
    --password "${SUPERSET_ADMIN_PASSWORD}" \
    --firstname Admin --lastname User \
    --email admin@example.com || true   # already exists on restart

superset init

exec gunicorn \
    --bind 0.0.0.0:8088 \
    --workers 2 --worker-class gthread --threads 8 \
    --timeout 120 \
    "superset.app:create_app()"
