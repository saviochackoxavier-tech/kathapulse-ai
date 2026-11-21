"""Sliding-window rate limiting — the in-app backstop.

The edge (nginx ``limit_req``, Cloudflare rate-limiting rules) is the first and
best line: it absorbs floods before they cost anything. This module exists for
the case the edge is misconfigured, missing (a direct container run, a hospital
LAN deploy) or bypassed, and for the fact that nginx's ``limit_req`` is a leaky
bucket, not a sliding window: it can let a burst through at a boundary.

Properties
----------
* **Sliding window, not fixed buckets.** Every admission records a timestamp;
  the window is pruned on read, so there is no burst-at-the-minute-boundary
  artefact.
* **Memory only.** Counters are a dict of deques in this process, discarded with
  it. No file, no Redis, no identifier beyond the client IP the socket already
  gave us. That keeps the DPDP story intact: this is not a log.
* **Off by default.** ``KATHA_RATE_LIMIT_PER_MIN=0`` means the edge owns the
  budget, which is the intended production shape. Set it to a positive integer
  to turn the backstop on (30 matches the documented proxy rule).
* **Bounded.** A flood of unique source addresses cannot grow the table without
  limit; the coldest client is evicted once ``MAX_TRACKED_CLIENTS`` is reached.
"""

from __future__ import annotations

import os
import time
from collections import Counter, deque

ENV_VAR = "KATHA_RATE_LIMIT_PER_MIN"
DEFAULT_LIMIT = 0  # the edge enforces 30/min; this is an optional backstop
MAX_TRACKED_CLIENTS = 4096
WINDOW_SECONDS = 60.0


def limit_per_minute() -> int:
    """Configured limit, re-read per request so a restart is not needed."""
    raw = os.environ.get(ENV_VAR, str(DEFAULT_LIMIT)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_LIMIT
    # A nonsense or hostile value must not disable protection silently, and a
    # huge one must not turn into an unbounded queue.
    return max(0, min(value, 6000))


class SlidingWindowLimiter:
    """Per-key admission decisions inside a rolling window."""

    def __init__(
        self, window_seconds: float = WINDOW_SECONDS, max_clients: int = MAX_TRACKED_CLIENTS
    ) -> None:
        self._window = window_seconds
        self._max_clients = max_clients
        self._hits: dict[str, deque[float]] = {}

    # -- introspection (aggregate counts only) -----------------------------
    def tracked_clients(self) -> int:
        return len(self._hits)

    def clear(self) -> None:
        """Drop every counter. Used by tests and by a graceful shutdown."""
        self._hits.clear()

    # -- the decision ------------------------------------------------------
    def _evict_coldest(self) -> None:
        # Evict the client whose newest hit is oldest; O(n) but only on overflow.
        if not self._hits:
            return
        oldest_key = min(self._hits, key=lambda key: self._hits[key][-1] if self._hits[key] else 0.0)
        self._hits.pop(oldest_key, None)

    def hit(
        self, key: str, limit: int, now: float | None = None
    ) -> tuple[bool, int]:
        """Record one request; return ``(allowed, retry_after_seconds)``."""
        if limit <= 0:
            return True, 0

        moment = time.monotonic() if now is None else now
        cutoff = moment - self._window
        bucket = self._hits.get(key)

        if bucket is None:
            if len(self._hits) >= self._max_clients:
                self._evict_coldest()
            bucket = self._hits[key] = deque()

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            # When the oldest hit leaves the window, a slot frees up.
            retry_after = max(1, int(bucket[0] + self._window - moment) + 1)
            return False, retry_after

        bucket.append(moment)
        return True, 0

    def snapshot(self) -> dict[str, int]:
        """Aggregate stats for diagnostics: client count and window length."""
        depth = Counter(len(bucket) for bucket in self._hits.values())
        return {
            "clients": len(self._hits),
            "window_seconds": int(self._window),
            "busiest": max(depth) if depth else 0,
        }


LIMITER = SlidingWindowLimiter()
