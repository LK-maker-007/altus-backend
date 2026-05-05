# Dockerfile — Yali Backend (Development)
#
# WHY python:3.14-slim (not alpine):
#   psycopg[binary] ships pre-compiled .so wheels for glibc (slim/bookworm).
#   Alpine uses musl libc — the binary wheel is incompatible and the source
#   build requires libpq-dev, pg_config, and a C compiler, adding ~200MB.
#   slim gives us a clean glibc base at ~130MB vs alpine's complexity.
#
# WHY not a multi-stage build here:
#   This is a dev image — we want editable installs and fast rebuilds.
#   Production EAS/fly.io deployment uses a separate production Dockerfile.
#
# WHY PYTHONDONTWRITEBYTECODE + PYTHONUNBUFFERED:
#   Standard Django/Gunicorn Docker best practice.
#   DONTWRITEBYTECODE: no .pyc files in the container layer.
#   UNBUFFERED: stdout/stderr flush immediately to `docker compose logs`.
#
# WHY non-root user (UID 10001):
#   Containers that run as root are a privilege escalation vector.
#   If application code is exploited, the attacker has full root inside the
#   container and a much easier path to the host kernel.
#   Source: Docker official best practices — https://docs.docker.com/build/building/best-practices/#user
#           OWASP Docker Security Cheat Sheet — https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html
#   UID/GID 10001: high number avoids conflicts with system users (0-999 reserved).
#   --no-log-init: prevents /var/log/faillog disk exhaustion — Go archive/tar bug
#   documented in Docker official docs (github.com/golang/go/issues/13548).
#   pip install runs as root (before USER) — writing to site-packages requires
#   root. Switching to USER only after installation is the documented pattern.

FROM python:3.14-slim

# System deps: only what psycopg[binary] needs at runtime (libpq shared lib)
# and what health checks / scripts need.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root group and user.
# --no-log-init: Docker official requirement — prevents disk exhaustion via
#   /var/log/faillog when using high UIDs (golang/go#13548).
# --no-create-home: no home directory needed for the app user.
# Explicit GID/UID 10001: deterministic across rebuilds; avoids system user conflicts.
RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid appgroup --no-log-init --no-create-home appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.development

WORKDIR /app

# Install requirements first (Docker cache layer — invalidated only on requirements change)
# Must run as root — pip writes to /usr/local/lib/python3.14/site-packages.
# Switching USER before this would require --user flag + PATH changes.
COPY requirements/production.txt requirements/production.txt
COPY requirements/development.txt requirements/development.txt
RUN pip install --no-cache-dir -r requirements/development.txt

# Copy source — invalidated on any source change
COPY . .

# Transfer /app ownership to appuser so the process can read source files.
# The bind-mount in docker-compose.yml (.:/app) will overlay this at runtime,
# but the base image permissions must be correct for non-bind-mounted runs.
RUN chown -R appuser:appgroup /app

# Drop privileges — all subsequent RUN, CMD, ENTRYPOINT run as appuser.
# Source: Docker official best practices §USER
USER appuser

# Default command — overridden per-service in docker-compose.yml
# WHY gunicorn not runserver:
#   runserver is single-threaded, no process management, not safe for production.
#   Gunicorn is the Django-recommended WSGI server (Django deployment docs §gunicorn).
#   Worker count and timeout are configured in config/gunicorn.conf.py.
#   Source: Google Principal Architect review §MISSING "No Gunicorn in Production"
CMD ["gunicorn", "config.wsgi:application", "--config", "config/gunicorn.conf.py"]
