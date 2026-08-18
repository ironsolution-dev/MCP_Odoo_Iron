"""Tests G5 (Fase A daily driver): trazabilidad build<->git en odoo_health.

git_commit/mcp_version vienen de env vars inyectadas en build time
(Dockerfile ARG->ENV, ver scripts/deploy_green.sh). Sin build real (ej. este
mismo test) deben caer a 'unknown' — esa es la senal legible de que algo no
paso por deploy_green.sh.
"""

from __future__ import annotations

import pytest

from app.tools.system import odoo_health


class FakeOdooOk:
    async def authenticate(self, actor):
        return 9

    async def server_version(self, actor):
        return {"server_version": "19.0"}


class FakeOdooAuthFails:
    async def authenticate(self, actor):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_health_reports_unknown_build_identity_without_env(monkeypatch):
    monkeypatch.delenv("MCP_GIT_COMMIT", raising=False)
    monkeypatch.delenv("MCP_VERSION", raising=False)
    result = await odoo_health(actor=None, odoo=FakeOdooOk())
    assert result["git_commit"] == "unknown"
    assert result["mcp_version"] == "unknown"


@pytest.mark.asyncio
async def test_health_reflects_build_time_env_vars(monkeypatch):
    monkeypatch.setenv("MCP_GIT_COMMIT", "abc1234")
    monkeypatch.setenv("MCP_VERSION", "multiuser-v0.4.0")
    result = await odoo_health(actor=None, odoo=FakeOdooOk())
    assert result["git_commit"] == "abc1234"
    assert result["mcp_version"] == "multiuser-v0.4.0"


@pytest.mark.asyncio
async def test_health_reports_build_identity_even_when_odoo_auth_fails(monkeypatch):
    """El anti-drift debe verse INCLUSO cuando Odoo esta caido — es lo primero
    que se quiere saber al diagnosticar un despliegue roto."""
    monkeypatch.setenv("MCP_GIT_COMMIT", "deadbeef")
    monkeypatch.setenv("MCP_VERSION", "multiuser-v0.4.0")
    result = await odoo_health(actor=None, odoo=FakeOdooAuthFails())
    assert result["odoo_auth_ok"] is False
    assert result["git_commit"] == "deadbeef"
    assert result["mcp_version"] == "multiuser-v0.4.0"
