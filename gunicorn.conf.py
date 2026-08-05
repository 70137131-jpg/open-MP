"""Gunicorn settings for the compiler service.

Sync workers on purpose: every request blocks on a subprocess, and the
executor's rlimit plumbing uses ``preexec_fn``, which is only safe in a
process-per-request model. Concurrency is bounded by the app's own gate
(``OPENMP_MAX_CONCURRENT_JOBS``) rather than by a thread pool.
"""

from __future__ import annotations

import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

workers = int(os.environ.get("WEB_CONCURRENCY", min(4, multiprocessing.cpu_count() * 2 + 1)))
worker_class = "sync"
threads = 1

# Must exceed the longest job (MPI run timeout + compile timeout) or gunicorn
# will kill a worker mid-compilation.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically: compilers leak little, but this bounds any
# slow growth in a long-lived deployment.
max_requests = 500
max_requests_jitter = 50

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("OPENMP_LOG_LEVEL", "info").lower()
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'

# Render/Heroku style proxies terminate TLS in front of us.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")
