"""A small in-process rate limiter and concurrency gate.

Deliberately dependency-free, with one consequence worth stating plainly:
**the counters are per worker process, not per service.** Running gunicorn with
N workers means a client can make up to ``N * OPENMP_RATE_LIMIT`` requests per
window, because each worker sees only its own share of the traffic. The same
applies to the concurrency gate.

That makes this a backstop, not the primary control. The shipped nginx config
enforces the real per-client limit in one place in front of all the workers
(``limit_req``); a multi-host deployment needs a shared store such as Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string (usually a client IP)."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit for ``key``.

        Returns ``(allowed, retry_after_seconds)``; ``retry_after`` is 0 when
        the request is allowed.
        """
        if self.limit <= 0:  # limiting disabled
            return True, 0

        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(hits[0] + self.window - now) + 1)
            hits.append(now)
            if len(self._hits) > 10_000:
                self._evict(cutoff)
            return True, 0

    def _evict(self, cutoff: float) -> None:
        """Drop keys with no recent activity. Caller holds the lock."""
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


class ConcurrencyGate:
    """Bounds how many compilations run at once, failing fast when saturated."""

    def __init__(self, limit: int) -> None:
        self._semaphore = threading.BoundedSemaphore(limit)
        self.limit = limit

    @contextmanager
    def slot(self, timeout: float = 0.0) -> Iterator[bool]:
        acquired = self._semaphore.acquire(blocking=timeout > 0, timeout=timeout or None)
        try:
            yield acquired
        finally:
            if acquired:
                self._semaphore.release()
