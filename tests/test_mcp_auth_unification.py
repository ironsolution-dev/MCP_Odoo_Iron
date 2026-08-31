"""Ticket 807 (ADR-018/019/020/021): GET y POST comparten el mismo pipeline
de autenticacion, el 401 lleva WWW-Authenticate, el discovery GET (restaurado
por cherry-pick de d0a2bfb) responde en vez de 404/406, y OPTIONS responde
CORS. Contra el servidor MCP real levantado en loopback (fixture `mcp_live`
en tests/fixtures_mcp_live.py) — sin tocar Odoo ni VPS82.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_get_con_token_valido_responde_discovery_no_404(mcp_live):
    """Antes del fix: GET /mcp/<token> caia en 404 porque la reescritura de
    path solo corria en la rama POST. Ahora responde 200 con el discovery
    JSON restaurado del commit de mayo (d0a2bfb)."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp/{mcp_live.token}",
                              headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.status_code != 404
    assert r.json()["result"]["name"] == "odoo-mcp-v2"


@pytest.mark.asyncio
async def test_get_token_invalido_401_con_www_authenticate(mcp_live):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp/token-que-no-existe",
                              headers={"Accept": "application/json"})
    assert r.status_code == 401
    assert r.status_code != 404
    assert "Bearer" in r.headers.get("www-authenticate", "")


@pytest.mark.asyncio
async def test_get_sin_token_401_nunca_404_ni_contenido_sin_auth(mcp_live):
    """Antes del fix: GET /mcp sin token pasaba derecho a FastMCP sin
    autenticar — superficie abierta. Ahora requiere token igual que POST."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp", headers={"Accept": "application/json"})
    assert r.status_code == 401
    assert r.status_code != 404
    assert "Bearer" in r.headers.get("www-authenticate", "")
    assert b"odoo-mcp-v2" not in r.content


@pytest.mark.asyncio
async def test_post_token_invalido_401_con_www_authenticate(mcp_live):
    """El 401 de POST tambien lleva WWW-Authenticate (ADR-019): es el mismo
    pipeline unificado, no un caso especial de GET."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{mcp_live.url}/mcp/token-que-no-existe",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
        )
    assert r.status_code == 401
    assert "Bearer" in r.headers.get("www-authenticate", "")


@pytest.mark.asyncio
async def test_options_responde_2xx_con_cors(mcp_live):
    async with httpx.AsyncClient() as client:
        r = await client.options(
            f"{mcp_live.url}/mcp/{mcp_live.token}",
            headers={"Origin": "https://claude.ai",
                     "Access-Control-Request-Method": "POST"},
        )
    assert 200 <= r.status_code < 300
    assert r.headers.get("access-control-allow-origin") == "https://claude.ai"
    assert "POST" in r.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_options_sin_token_no_requiere_auth(mcp_live):
    """El preflight del navegador no manda Authorization — no puede exigirse
    token en OPTIONS o el navegador nunca llega a mandar la request real."""
    async with httpx.AsyncClient() as client:
        r = await client.options(f"{mcp_live.url}/mcp",
                                  headers={"Origin": "https://claude.ai",
                                           "Access-Control-Request-Method": "GET"})
    assert 200 <= r.status_code < 300


@pytest.mark.asyncio
async def test_respuesta_real_lleva_access_control_allow_origin(mcp_live):
    """No solo el preflight: la respuesta real tambien debe ser legible desde
    el navegador (ADR-021)."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp/{mcp_live.token}",
                              headers={"Accept": "application/json",
                                       "Origin": "https://claude.ai"})
    assert r.headers.get("access-control-allow-origin") == "https://claude.ai"
