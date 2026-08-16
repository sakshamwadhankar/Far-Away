"""
backend/neuralflow/serve/ratelimit.py

A simple per-deployment token bucket, in-process and in-memory.

Deliberately not persisted: this is a local desktop backend, not a multi-node
service, so a process restart resetting every bucket to full is the right
behavior, not a bug to work around. Configurable per deployment via
Deployment.rate_limit_per_minute (default 60).
"""

from __future__ import annotations

import time


class TokenBucket:
    """Classic token bucket: refills continuously, burst up to `capacity`."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = max(1, capacity)
        self.refill_per_second = max(0.0, refill_per_second)
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def try_consume(self) -> bool:
        """Attempt to take one token. Returns False if the bucket is empty."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(
            self.capacity, self._tokens + elapsed * self.refill_per_second
        )

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class RateLimiter:
    """Owns one TokenBucket per deployment_id, created lazily on first use."""

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def check(self, deployment_id: str, rate_limit_per_minute: int) -> bool:
        """
        Consume one token for `deployment_id`. Returns False if the deployment
        has exceeded its per-minute rate.

        The bucket's capacity/refill are re-derived from `rate_limit_per_minute`
        on every call rather than cached at creation, so rotating a deployment's
        configured rate takes effect on the very next request.
        """
        bucket = self._buckets.get(deployment_id)
        if bucket is None or bucket.capacity != max(1, rate_limit_per_minute):
            bucket = TokenBucket(
                capacity=rate_limit_per_minute,
                refill_per_second=rate_limit_per_minute / 60.0,
            )
            self._buckets[deployment_id] = bucket
        return bucket.try_consume()

    def reset(self, deployment_id: str) -> None:
        """Drop a deployment's bucket, e.g. after it is deleted."""
        self._buckets.pop(deployment_id, None)
