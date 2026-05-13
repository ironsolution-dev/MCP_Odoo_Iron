"""Rate limit in-memory simple por actor (todos los modos hoy: requests/min y writes/min).
Sliding window de 60s sin dependencias externas.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from app.policy_engine import RateLimit


_WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float = 0.0
    denied_reason: Optional[str] = None


@dataclass
class _ActorBucket:
    requests: deque = field(default_factory=deque)
    writes: deque = field(default_factory=deque)


class RateLimiter:
    """Sliding window por actor. Solo proceso unico (in-memory).
    Si se escala a varias replicas se reemplaza por Redis/etcd."""

    def __init__(self):
        self._buckets: dict[str, _ActorBucket] = {}

    def _bucket(self, actor: str) -> _ActorBucket:
        bucket = self._buckets.get(actor)
        if bucket is None:
            bucket = _ActorBucket()
            self._buckets[actor] = bucket
        return bucket

    def _evict(self, dq: deque, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        while dq and dq[0] < cutoff:
            dq.popleft()

    def check(self, actor: str, action: str, limit: RateLimit) -> RateLimitDecision:
        """action: 'read' o 'write'. Lectura cuenta en requests; escritura en
        ambos pools (writes y requests)."""
        now = time.monotonic()
        bucket = self._bucket(actor)
        self._evict(bucket.requests, now)
        self._evict(bucket.writes, now)

        if len(bucket.requests) >= limit.requests_per_minute:
            retry = _WINDOW_SECONDS - (now - bucket.requests[0])
            return RateLimitDecision(False, max(retry, 0.0), "requests_per_minute_exceeded")

        if action in ("write", "create", "unlink") and len(bucket.writes) >= limit.writes_per_minute:
            retry = _WINDOW_SECONDS - (now - bucket.writes[0])
            return RateLimitDecision(False, max(retry, 0.0), "writes_per_minute_exceeded")

        bucket.requests.append(now)
        if action in ("write", "create", "unlink"):
            bucket.writes.append(now)
        return RateLimitDecision(True)

    def reset(self, actor: Optional[str] = None) -> None:
        if actor is None:
            self._buckets.clear()
        else:
            self._buckets.pop(actor, None)
