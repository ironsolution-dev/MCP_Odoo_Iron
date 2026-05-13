"""Tests del rate limiter."""

from __future__ import annotations

from app.policy_engine import RateLimit
from app.rate_limit import RateLimiter


def test_rate_limit_blocks_excess():
    rl = RateLimiter()
    limit = RateLimit(requests_per_minute=3, writes_per_minute=2)
    actor = "test"
    for _ in range(3):
        d = rl.check(actor, "read", limit)
        assert d.allowed
    blocked = rl.check(actor, "read", limit)
    assert not blocked.allowed
    assert blocked.denied_reason == "requests_per_minute_exceeded"


def test_rate_limit_writes_pool_independent():
    rl = RateLimiter()
    limit = RateLimit(requests_per_minute=100, writes_per_minute=2)
    actor = "test"
    assert rl.check(actor, "create", limit).allowed
    assert rl.check(actor, "create", limit).allowed
    # Tercera escritura excede writes_per_minute
    blocked = rl.check(actor, "create", limit)
    assert not blocked.allowed
    assert blocked.denied_reason == "writes_per_minute_exceeded"
    # Pero lecturas siguen pasando
    assert rl.check(actor, "read", limit).allowed


def test_rate_limit_per_actor_isolated():
    rl = RateLimiter()
    limit = RateLimit(requests_per_minute=2, writes_per_minute=2)
    assert rl.check("willy", "read", limit).allowed
    assert rl.check("willy", "read", limit).allowed
    # Willy bloqueado
    assert not rl.check("willy", "read", limit).allowed
    # Yuniesky NO afectado
    assert rl.check("yuniesky", "read", limit).allowed


def test_rate_limit_reset():
    rl = RateLimiter()
    limit = RateLimit(requests_per_minute=1, writes_per_minute=1)
    rl.check("willy", "read", limit)
    assert not rl.check("willy", "read", limit).allowed
    rl.reset("willy")
    assert rl.check("willy", "read", limit).allowed
