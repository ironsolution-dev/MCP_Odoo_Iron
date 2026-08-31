"""Ticket 867 (ADR-021 remediado): allowlist explicita de origenes CORS.

Antes de este ticket, `BearerMiddleware` reflejaba CUALQUIER `Origin`
recibido sin comparar contra nada (riesgo aceptado temporal, hallado por
julio-qa en el ticket 807 con un origen hostil). Ahora:

- Origen en la allowlist (`config/cors_allowlist.yaml`) -> se refleja,
  igual que antes, pero SOLO para estos origenes.
- Origen hostil (no listado) -> la respuesta se sirve igual (no hay 403),
  pero SIN ninguna cabecera CORS: un navegador no puede leerla via
  fetch()/XHR.
- Sin header `Origin` (CLI/curl, el camino de Willy) -> comportamiento
  identico al anterior a este ticket (`Access-Control-Allow-Origin: *`) —
  regresion critica si cambia.

Contra el servidor MCP real levantado en loopback (fixture `mcp_live` en
tests/fixtures_mcp_live.py), igual que tests/test_mcp_auth_unification.py.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from app.cors_config import ALLOWED_ORIGINS, load_allowed_origins

HOSTILE_ORIGIN = "https://evil-attacker.example"


# ---------------------------------------------------------------------------
# Unidad: app/cors_config.py (fuente unica)
# ---------------------------------------------------------------------------

def test_config_committed_incluye_claude_y_chatgpt():
    """El arranque pedido por el ticket 867: claude.ai y chatgpt.com."""
    assert "https://claude.ai" in ALLOWED_ORIGINS
    assert "https://chatgpt.com" in ALLOWED_ORIGINS


def test_load_allowed_origins_respeta_path_explicito(tmp_path: Path):
    """Mismo mecanismo que app.apl_labels.load_label_map: un path explicito
    (o CORS_ALLOWLIST_PATH en runtime) permite apuntar a otro fichero sin
    tocar el committed a git — usado por tests/desarrollo."""
    custom = tmp_path / "cors_allowlist.yaml"
    custom.write_text(yaml.safe_dump({
        "version": 1,
        "allowed_origins": ["https://solo-este.example"],
    }))
    origins = load_allowed_origins(custom)
    assert origins == frozenset({"https://solo-este.example"})


def test_load_allowed_origins_sin_clave_no_revienta(tmp_path: Path):
    custom = tmp_path / "vacio.yaml"
    custom.write_text(yaml.safe_dump({"version": 1}))
    assert load_allowed_origins(custom) == frozenset()


# ---------------------------------------------------------------------------
# Integracion: BearerMiddleware contra el servidor real
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_origen_listado_preflight_headers_correctos(mcp_live):
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
async def test_origen_listado_chatgpt_preflight_headers_correctos(mcp_live):
    """chatgpt.com es el segundo origen del arranque pedido por el ticket."""
    async with httpx.AsyncClient() as client:
        r = await client.options(
            f"{mcp_live.url}/mcp/{mcp_live.token}",
            headers={"Origin": "https://chatgpt.com",
                     "Access-Control-Request-Method": "POST"},
        )
    assert 200 <= r.status_code < 300
    assert r.headers.get("access-control-allow-origin") == "https://chatgpt.com"


@pytest.mark.asyncio
async def test_origen_listado_respuesta_real_headers_correctos(mcp_live):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp/{mcp_live.token}",
                              headers={"Accept": "application/json",
                                       "Origin": "https://claude.ai"})
    assert r.headers.get("access-control-allow-origin") == "https://claude.ai"


@pytest.mark.asyncio
async def test_origen_hostil_preflight_sin_reflejo(mcp_live):
    """El hallazgo del QA del 807: un origen hostil arbitrario ya NO recibe
    Access-Control-Allow-Origin. El preflight sigue respondiendo 2xx (no
    403) — solo faltan las cabeceras que le dirian al navegador que puede
    leer la respuesta real."""
    async with httpx.AsyncClient() as client:
        r = await client.options(
            f"{mcp_live.url}/mcp/{mcp_live.token}",
            headers={"Origin": HOSTILE_ORIGIN,
                     "Access-Control-Request-Method": "POST"},
        )
    assert 200 <= r.status_code < 300
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-methods" not in r.headers
    assert "access-control-allow-headers" not in r.headers


@pytest.mark.asyncio
async def test_origen_hostil_respuesta_real_sin_reflejo_pero_no_bloquea(mcp_live):
    """Sin allowlist: no hay 403 ni bloqueo server-side (el servidor no
    puede saber si el llamador es un navegador o un script) — solo se le
    niega la cabecera CORS que un navegador necesitaria para leer la
    respuesta via fetch()."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp/{mcp_live.token}",
                              headers={"Accept": "application/json",
                                       "Origin": HOSTILE_ORIGIN})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.asyncio
async def test_origen_hostil_401_tambien_sin_reflejo(mcp_live):
    """El origen hostil tampoco recibe la cabecera en el camino de error
    (401 por token invalido) — el allowlist aplica antes de saber si el
    token es valido."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp/token-que-no-existe",
                              headers={"Accept": "application/json",
                                       "Origin": HOSTILE_ORIGIN})
    assert r.status_code == 401
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.asyncio
async def test_sin_header_origin_identico_al_comportamiento_anterior(mcp_live):
    """Regresion critica (ticket 867): CLI/curl -- el camino de Willy -- no
    manda Origin. Antes de este ticket el codigo hacia
    `headers_raw.get(b'origin') or b'*'`, asi que la respuesta SIEMPRE
    llevaba `Access-Control-Allow-Origin: *` aunque no hubiera navegador de
    por medio. Ese comportamiento no debe cambiar: no hay allowlist que
    aplicar cuando no hay Origin que comparar."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{mcp_live.url}/mcp/{mcp_live.token}",
                              headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_sin_header_origin_preflight_tambien_identico(mcp_live):
    async with httpx.AsyncClient() as client:
        r = await client.options(
            f"{mcp_live.url}/mcp/{mcp_live.token}",
            headers={"Access-Control-Request-Method": "POST"},
        )
    assert 200 <= r.status_code < 300
    assert r.headers.get("access-control-allow-origin") == "*"
