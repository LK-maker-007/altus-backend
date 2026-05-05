#!/bin/sh
# docker/entrypoint.sh
#
# WHY this script (not depends_on alone):
#   depends_on condition:service_healthy waits for the healthcheck to pass,
#   but the Django process still starts immediately after — and psycopg may
#   get a connection refused if postgres is still in init mode.
#   This script retries the DB connection before running migrations/server.
#
# WHY migrate here (not as a separate step):
#   In local dev, migrations must run before the server starts.
#   In production (EAS/fly.io), migrations run as a release command separately.
#   This entrypoint is dev-only.

set -e

echo "[entrypoint] Waiting for postgres..."
until python manage.py migrate --check >/dev/null 2>&1 || python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()
from django.db import connection
connection.ensure_connection()
print('DB ready')
" 2>/dev/null; do
    echo "[entrypoint] DB not ready — retrying in 2s..."
    sleep 2
done

echo "[entrypoint] Running migrations..."
python manage.py migrate --no-input

echo "[entrypoint] Starting: $*"
exec "$@"
