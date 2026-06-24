# Multi-stage build: dependencies are compiled in the builder and only the
# resulting venv is copied into the runtime image — no pip, compilers, or build
# artifacts ship to production.

FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Runtime dependencies only — dev/test tooling (pytest, mypy, ruff) stays out of
# the image, keeping it small and shrinking the attack surface.
COPY requirements/production.txt requirements/production.txt
RUN pip install -r requirements/production.txt


FROM python:3.14-slim AS runtime

# slim over alpine: psycopg[binary] ships glibc wheels; musl would force a source
# build. libpq5 is the only runtime system lib; curl serves the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user (UID outside the system range) so a compromised process
# never has root inside the container. --no-log-init avoids a faillog disk-blowup
# with high UIDs (golang/go#13548).
RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid appgroup --no-log-init --no-create-home appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.production

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . .
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Probe real readiness (DB + Redis), not just process liveness.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health/ || exit 1

CMD ["gunicorn", "config.wsgi:application", "--config", "config/gunicorn.conf.py"]
