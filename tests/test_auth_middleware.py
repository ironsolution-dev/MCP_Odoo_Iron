"""Tests del auth_middleware: extraccion, deteccion de client_type, deny flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.audit import Audit
from app.auth_middleware import (
    AuthError,
    AuthMiddleware,
    DeniedByPolicy,
    DeniedByRateLimit,
)
from app.policy_engine import PolicyEngine
from app.rate_limit import RateLimiter
from app.token_registry import TokenRegistry


@pytest.fixture
def middleware(actors_yaml, policies_yaml, tmp_path: Path):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    audit = Audit(tmp_path / "audit.jsonl")
    return AuthMiddleware(reg, pe, RateLimiter(), audit), audit


def test_extract_bearer_token(middleware):
    mw, _ = middleware
    token, source = mw.extract_token("Bearer mcp_xxx", path=None)
    assert token == "mcp_xxx"
    assert source == "bearer"


def test_extract_path_token(middleware):
    mw, _ = middleware
    token, source = mw.extract_token(None, path="/mcp/opaque_segment_here/")
    assert token == "opaque_segment_here"
    assert source == "path"


def test_extract_none(middleware):
    mw, _ = middleware
    token, source = mw.extract_token(None, path="/mcp")
    assert token is None
    assert source == "none"


def test_detect_client_type(middleware):
    mw, _ = middleware
    assert mw.detect_client_type("ClaudeBot/1.0", "bearer") == "claude_connector"
    assert mw.detect_client_type("ChatGPT-User/1.0", "bearer") == "chatgpt_connector"
    assert mw.detect_client_type("curl/8.0", "bearer") == "curl"
    assert mw.detect_client_type(None, "path") == "opaque_path"


def test_invalid_token_raises_auth_error_and_audits(middleware):
    mw, audit = middleware
    with pytest.raises(AuthError):
        mw.authenticate("Bearer mcp_nonexistent_token_zzzzzzz", path=None,
                        user_agent="curl/8.0", request_id="r1")
    entries = [json.loads(l) for l in audit.log_path.read_text().splitlines() if l.strip()]
    assert entries
    assert entries[-1]["denied_reason"] == "invalid_token"
    assert entries[-1]["allowed"] is False


def test_policy_deny_propagates_and_audits(middleware, token_yuniesky):
    mw, audit = middleware
    ctx = mw.authenticate(f"Bearer {token_yuniesky}", path=None,
                          user_agent="ClaudeBot/1.0", request_id="r2")
    # operations_policy NO tiene odoo_list_crm_leads -> deny
    with pytest.raises(DeniedByPolicy) as exc:
        mw.authorize_tool(ctx, "odoo_list_crm_leads", "crm.lead", "read")
    assert "tool_not_allowed" in exc.value.reason
    entries = [json.loads(l) for l in audit.log_path.read_text().splitlines() if l.strip()]
    assert entries[-1]["denied_reason"].startswith("tool_not_allowed")


def test_rate_limit_kicks_in(middleware, monkeypatch, token_willy):
    mw, audit = middleware
    # Forzar limites super bajos en la policy mockeando rate_limit()
    from app.policy_engine import RateLimit
    monkeypatch.setattr(mw.policy, "rate_limit", lambda _name: RateLimit(2, 2))

    ctx = mw.authenticate(f"Bearer {token_willy}", path=None,
                          user_agent="curl/8.0", request_id="r3")
    mw.authorize_tool(ctx, "odoo_my_tasks", "project.task", "read")
    mw.authorize_tool(ctx, "odoo_my_tasks", "project.task", "read")
    with pytest.raises(DeniedByRateLimit) as exc:
        mw.authorize_tool(ctx, "odoo_my_tasks", "project.task", "read")
    assert exc.value.retry_after > 0
