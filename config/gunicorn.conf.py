import multiprocessing
import os

bind = "0.0.0.0:8000"

# gthread (not sync): the SSE slot-stream endpoint holds a worker for the life of
# the connection. Threads let one stalled stream block a thread, not a whole worker.
workers = multiprocessing.cpu_count() + 1
worker_class = "gthread"
threads = 4
worker_connections = 1000

timeout = 30
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = "info"

access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" '
    "rid=%({x-request-id}o)s dur_s=%(L)s"
)

proc_name = "yali-api"

# Trust X-Forwarded-* only from the known nginx IP, so the IP throttle can't be
# spoofed by a forged header.
forwarded_allow_ips = os.environ.get("NGINX_PROXY_IP", "127.0.0.1")
