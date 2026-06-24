#!/bin/sh

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
