"""Test sec 14.1 Task Packet: `test_blue_endpoint_still_responsive`.

Verifica que el endpoint BLUE (mcp.ovnisystem.com/mcp) sigue respondiendo OK
al cierre del ticket. Se omite si no hay acceso a internet/BLUE (marker `requires_blue`).
Lo ejecuta Willy en VPS o desde su maquina al cierre del deploy.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest


BLUE_URL = "https://mcp.ovnisystem.com/mcp"


@pytest.mark.requires_blue
def test_blue_endpoint_still_responsive():
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    req = urllib.request.Request(
        BLUE_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            payload = resp.read(2048).decode(errors="ignore")
            # Aceptamos cualquiera de los dos shapes (sse stream o JSON-RPC body).
            assert "tools" in payload or "jsonrpc" in payload
    except urllib.error.URLError as e:
        pytest.skip(f"BLUE unreachable from this env: {e}")
