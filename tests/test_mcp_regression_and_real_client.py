"""Ticket 807 — dos criterios de aceptacion contra el servidor MCP real
levantado localmente (fixture `mcp_live`, ver tests/fixtures_mcp_live.py):

1. Un cliente MCP generico REAL (SDK oficial `mcp`, no ChatGPT): initialize()
   + tools/list().
2. Regresion del camino POST /mcp/<token> de Claude/Willy: mismos codigos,
   mismas 49 tools listadas, antes y despues del cambio de auth/CORS/audit.

Todo local con OdooClient falso (tests/fixtures_mcp_live.FakeOdooClient) —
nunca toca Odoo real ni VPS82.
"""

from __future__ import annotations

import httpx
import pytest

# Snapshot de las 49 tools registradas en app/odoo_mcp_remote.py (grep
# "@mcp.tool()" + nombre de funcion). Si este set cambia sin que el ticket
# lo pida, esta prueba lo revienta — es la regresion "mismas tools, 49".
EXPECTED_TOOL_NAMES = {
    "cancel_task", "close_task", "create_event", "create_project", "create_task",
    "create_todo", "fetch", "move_task", "move_task_to_project",
    "odoo_add_crm_note", "odoo_attach_discuss_attachment_to_task", "odoo_cancel_task",
    "odoo_create_calendar_event", "odoo_create_crm_activity", "odoo_create_my_todo_apl",
    "odoo_create_project", "odoo_create_project_task_apl", "odoo_get_attachment",
    "odoo_get_crm_lead", "odoo_get_employee", "odoo_get_partner", "odoo_get_project",
    "odoo_get_task", "odoo_health", "odoo_list_attachments", "odoo_list_calendar_events",
    "odoo_list_crm_leads", "odoo_list_employees", "odoo_list_partners",
    "odoo_list_projects", "odoo_mark_task_done", "odoo_move_task",
    "odoo_move_task_to_project", "odoo_my_tasks", "odoo_my_tasks_overdue",
    "odoo_my_tasks_today", "odoo_post_discuss_message", "odoo_project_tasks",
    "odoo_read_discuss_channel", "odoo_search_employee", "odoo_search_partner",
    "odoo_task_subtasks", "odoo_update_calendar_event", "odoo_update_project_basic",
    "odoo_update_task_apl", "odoo_validate_apl_stages", "odoo_who_am_i",
    "search", "update_task",
}


@pytest.mark.asyncio
async def test_sdk_oficial_mcp_initialize_y_tools_list(mcp_live):
    """Criterio de aceptacion: cliente MCP generico REAL (SDK oficial, no
    ChatGPT) hace initialize + tools/list en verde contra el servidor local."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = f"{mcp_live.url}/mcp/{mcp_live.token}"
    async with streamable_http_client(url) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            init_result = await session.initialize()
            assert init_result.serverInfo.name == "odoo-mcp-v2"

            tools_result = await session.list_tools()
            names = {t.name for t in tools_result.tools}
            assert len(names) == 49
            assert names == EXPECTED_TOOL_NAMES


@pytest.mark.asyncio
async def test_regresion_post_mcp_token_mismos_codigos_y_49_tools(mcp_live):
    """Regresion del camino actual de Claude/Willy: POST /mcp/<token> con
    Bearer en el path (como usa el conector de Claude.ai hoy) debe seguir
    devolviendo exactamente las mismas 49 tools tras unificar el pipeline
    de auth con GET y agregar CORS/audit — nada de esto debia tocar el
    contrato POST que ya funcionaba."""
    async with httpx.AsyncClient() as client:
        # tools/list valido -> 200, 49 tools (idéntico a antes del ticket).
        r = await client.post(
            f"{mcp_live.url}/mcp/{mcp_live.token}",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
        )
        assert r.status_code == 200
        tools = r.json()["result"]["tools"]
        assert len(tools) == 49
        assert {t["name"] for t in tools} == EXPECTED_TOOL_NAMES

        # Token invalido -> 401 (idéntico codigo a antes; WWW-Authenticate es
        # aditivo, no cambia el codigo que el conector de Claude ya maneja).
        r = await client.post(
            f"{mcp_live.url}/mcp/token-invalido",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
        )
        assert r.status_code == 401
