"""Tests del audit log (sec 14.1 Task Packet)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.audit import Audit, redact_header


@pytest.fixture
def audit(tmp_path: Path) -> Audit:
    return Audit(tmp_path / "audit.jsonl")


def _read_lines(audit: Audit) -> list[dict]:
    return [json.loads(line) for line in audit.log_path.read_text().splitlines() if line.strip()]


def test_audit_log_success(audit: Audit):
    rid = audit.emit(
        actor="willy", role="owner", client_type="claude_connector",
        tool="odoo_who_am_i", model="res.users", action="read",
        allowed=True, latency_ms=120, result_count=1, odoo_uid=9,
    )
    entries = _read_lines(audit)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["request_id"] == rid
    assert entry["actor"] == "willy"
    assert entry["allowed"] is True
    assert entry["latency_ms"] == 120


def test_audit_log_denied(audit: Audit):
    audit.emit(
        actor="yuniesky", role="operations", client_type="chatgpt_connector",
        tool="odoo_list_crm_leads", model="crm.lead", action="read",
        allowed=False, denied_reason="tool_not_allowed:odoo_list_crm_leads",
    )
    entries = _read_lines(audit)
    assert entries[0]["allowed"] is False
    assert entries[0]["denied_reason"].startswith("tool_not_allowed")


def test_no_secret_in_logs(audit: Audit):
    """Even with explicit secret-like keys in args/extra, they get redacted."""
    audit.emit(
        actor="willy", role="owner", tool="odoo_who_am_i",
        model="res.users", action="read", allowed=True,
        args={"include_meta": True, "api_key": "secret_should_redact",
              "nested": {"token": "shhh_redact_me_too", "harmless": "fine"}},
        extra={"Authorization": "Bearer mcp_test_token_abc", "client": "test"},
    )
    raw = audit.log_path.read_text()
    # No deben aparecer los valores literales de secretos.
    assert "secret_should_redact" not in raw
    assert "shhh_redact_me_too" not in raw
    assert "mcp_test_token_abc" not in raw
    # En cambio, debe aparecer args_hash
    assert "args_hash" in raw
    # Bearer del header debe quedar redacted dentro de extra
    entries = _read_lines(audit)
    assert entries[0].get("extra", {}).get("Authorization") == "<redacted>"


def test_audit_args_hash_replaces_args(audit: Audit):
    audit.emit(
        actor="willy", tool="x", model="m", action="read", allowed=True,
        args={"q": "search-string"},
    )
    line = audit.log_path.read_text()
    assert "search-string" not in line
    assert "args_hash" in line


def test_redact_header_safe():
    assert redact_header("") == ""
    assert redact_header("Bearer abc") == "<redacted>"  # corto
    redacted = redact_header("Bearer mcp_abcdef12345678xxxxxxx")
    assert "mcp_abcd" not in redacted or "..." in redacted
    assert "<redacted>" in redacted or "..." in redacted


def test_audit_no_known_secret_pattern_leaks(audit: Audit, tmp_path: Path):
    """Grep estilo CI: el archivo de audit no debe contener strings que parezcan tokens."""
    audit.emit(actor="x", tool="y", model="m", action="read", allowed=True,
               args={"any": "thing"})
    raw = audit.log_path.read_text()
    forbidden_patterns = [
        re.compile(r"\bmcp_[A-Za-z0-9_-]{30,}"),
        re.compile(r"\bapi_key=[^,\s]+"),
        re.compile(r"\bMCP_TOKEN\s*=\s*[^,\s]+"),
    ]
    for pat in forbidden_patterns:
        assert pat.search(raw) is None, f"Pattern leaked: {pat.pattern}"
