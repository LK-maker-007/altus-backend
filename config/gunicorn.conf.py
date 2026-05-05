"""
config/gunicorn.conf.py

Gunicorn production configuration for the Yali API.

WHY Gunicorn not runserver:
  Django's runserver is a single-threaded development server with no process
  management, no graceful shutdown, and no request queuing. It is explicitly
  documented as unsuitable for production in Django's deployment guide.
  Gunicorn is the industry-standard WSGI server for Django production deployments.
  Source: docs.djangoproject.com/en/stable/howto/deployment/wsgi/gunicorn/
          Google Principal Architect review §MISSING "No Gunicorn in Production"

WHY sync worker class (not gthread/gevent):
  Django views in this codebase are synchronous and CPU-bound at the ORM layer.
  Async workers (gevent/eventlet) add complexity and are only beneficial for
  I/O-bound views with many concurrent long-lived connections. PgBouncer handles
  connection pooling — sync workers + PgBouncer is the canonical Django pattern.
  Source: Gunicorn docs §worker-types; CONN_MAX_AGE=0 in base.py

WHY workers = 2 x CPU + 1:
  Gunicorn's recommended formula for CPU-bound synchronous workers.
  Allows one worker per CPU to be processing while the other is doing I/O.
  Source: docs.gunicorn.org/en/stable/design.html#how-many-workers

WHY timeout = 30:
  Requests taking > 30s are killed. Prevents zombie workers under load.
  Django's ORM queries should never take > 5s in normal operation.
  30s gives headroom for R2 uploads and Twilio calls.

WHY graceful_timeout = 30:
  Time for workers to finish in-flight requests after receiving SIGTERM.
  Allows ongoing requests to complete before the worker is killed on deploy.
  Source: Twelve-Factor App §IX disposability.
"""

import multiprocessing

# ── Binding ────────────────────────────────────────────────────────────────────
bind = "0.0.0.0:8000"

# ── Workers ────────────────────────────────────────────────────────────────────
# WHY gthread not sync (audit §Critical §SSE Worker Starvation):
#   FacilitySlotStreamView uses StreamingHttpResponse with time.sleep(25).
#   A sync worker is entirely blocked for the sleep duration — N concurrent
#   SSE clients = N workers occupied = zero capacity for all other requests.
#   gthread (Gunicorn threaded sync worker) gives each worker `threads` OS
#   threads: SSE connections block one thread, others handle HTTP normally.
#   With 5 workers x 4 threads = 20 concurrent-request capacity; 9 SSE
#   connections consume 9 threads, 11 remain for all other endpoints.
#   PgBouncer transaction mode still works correctly — CONN_MAX_AGE=0 is
#   set at the Django settings layer, not the Gunicorn layer.
#   Source: Gunicorn docs §worker-types §gthread; audit §Critical §SSE.
workers = multiprocessing.cpu_count() + 1  # fewer workers — each is multithreaded
worker_class = "gthread"
threads = 4  # threads per worker: 4 is the Gunicorn-recommended safe default
worker_connections = 1000  # ignored for gthread; kept for future async migration

# ── Timeouts ───────────────────────────────────────────────────────────────────
timeout = 30  # Kill worker if request exceeds 30s
graceful_timeout = 30  # Wait 30s for in-flight requests on SIGTERM
keepalive = 5  # Keep-alive connections for 5s (nginx upstream)

# ── Logging ────────────────────────────────────────────────────────────────────
accesslog = "-"  # stdout → Docker log collector
errorlog = "-"  # stderr → Docker log collector
loglevel = "info"

# WHY access_log_format with X-Request-ID:
#   RequestIdMiddleware sets X-Request-ID on every response. Including it in
#   the access log links each HTTP request to its structlog trace — essential
#   for debugging production issues across Gunicorn + Django logs.
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" rid=%(T)s'
)

# ── Process naming ─────────────────────────────────────────────────────────────
proc_name = "yali-api"

# ── Security ───────────────────────────────────────────────────────────────────
# WHY NGINX_PROXY_IP not "*" (audit §Significant §forwarded_allow_ips):
#   With forwarded_allow_ips="*", any client can spoof X-Forwarded-For by sending
#   a fabricated header — Gunicorn unconditionally trusts it. This defeats the
#   IP-based TokenRefreshRateThrottle: an attacker rotates the spoofed header
#   value, bypassing the 5/minute rate limit with zero friction.
#   The correct value is the private IP of the upstream nginx/load-balancer only.
#   NGINX_PROXY_IP is set via env var (default: 127.0.0.1 for local dev with
#   nginx on the same host). Production: set NGINX_PROXY_IP in the .env to the
#   actual nginx private IP (e.g. "10.0.0.5").
#   Source: Gunicorn docs §forwarded-allow-ips; audit §Significant §forwarded_allow_ips.
import os  # noqa: E402

forwarded_allow_ips = os.environ.get("NGINX_PROXY_IP", "127.0.0.1")
