"""Ticket 807 (causa de proceso): antes solo los fallos de auth grababan
client_type en el audit — los exitos iban con null porque _audited() no
tenia forma de leerlo. Ahora BearerMiddleware guarda (client_type,
user_agent) en un ContextVar propio y _audited() lo adjunta a TODOS los
eventos, exito incluido. Contra el servidor MCP real (fixture `mcp_live`).
"""

from __future__ import annotations

import json

import httpx
import pytest


async def _call_who_am_i(base_url, token, user_agent):
    async with httpx.AsyncClient() as client:
        return await client.post(
            f"{base_url}/mcp/{token}",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "odoo_who_am_i", "arguments": {}}},
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json",
                     "User-Agent": user_agent},
        )


def _read_audit(audit_path):
    return [json.loads(l) for l in audit_path.read_text().strip().splitlines()]


@pytest.mark.asyncio
async def test_evento_de_exito_graba_client_type_y_user_agent_no_nulos(mcp_live):
    r = await _call_who_am_i(mcp_live.url, mcp_live.token, "claude-ai-mcp-client/1.0")
    assert r.status_code == 200

    entries = _read_audit(mcp_live.audit_path)
    success = [e for e in entries if e.get("tool") == "odoo_who_am_i" and e.get("allowed")]
    assert len(success) == 1, entries
    entry = success[0]
    assert entry.get("client_type") is not None
    assert entry.get("client_type") == "claude_connector"
    assert entry.get("user_agent") is not None
    assert entry.get("user_agent") == "claude-ai-mcp-client/1.0"


@pytest.mark.asyncio
async def test_client_type_distingue_chatgpt_de_claude_por_user_agent(mcp_live):
    r = await _call_who_am_i(mcp_live.url, mcp_live.token, "ChatGPT-User/1.0")
    assert r.status_code == 200

    entries = _read_audit(mcp_live.audit_path)
    success = [e for e in entries if e.get("tool") == "odoo_who_am_i" and e.get("allowed")]
    assert success[-1]["client_type"] == "chatgpt_connector"
    assert success[-1]["user_agent"] == "ChatGPT-User/1.0"


@pytest.mark.asyncio
async def test_evento_de_fallo_auth_sigue_grabando_client_type_y_ahora_tambien_user_agent(mcp_live):
    """Regresion: los fallos ya grababan client_type antes del ticket 807.
    Verifica que seguir grabandolo no se rompio al agregar user_agent."""
    async with httpx.AsyncClient() as client:
        await client.get(f"{mcp_live.url}/mcp/token-invalido",
                          headers={"Accept": "application/json", "User-Agent": "curl/8.0"})

    entries = _read_audit(mcp_live.audit_path)
    denied = [e for e in entries if e.get("denied_reason") == "invalid_token"]
    assert len(denied) == 1
    assert denied[0]["client_type"] == "curl"
    assert denied[0]["user_agent"] == "curl/8.0"
