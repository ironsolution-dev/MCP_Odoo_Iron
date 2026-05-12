"""Entry point MCP Odoo v2 — multiusuario Bearer auth + policy engine.

Usa mcp 1.27.0 (mcp.server.fastmcp.FastMCP) + uvicorn directo.
El middleware Bearer intercepta Authorization header via streamable_http_app()
y pasa el actor al ContextVar que cada tool lee.
"""
from __future__ import annotations

import os
import uvicorn
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.audit import Audit
from app.auth_middleware import AuthMiddleware
from app.credentials_resolver import CredentialsResolver
from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.rate_limit import RateLimiter
from app.token_registry import ActorEntry, TokenRegistry
from app.tools import system as S, tasks as T, projects as P
from app.tools import calendar as C, employees as E, crm as CR, partners as PA

# ---------------------------------------------------------------------------
# ContextVar: pasa el actor desde middleware a cada tool
# ---------------------------------------------------------------------------
_actor: ContextVar[Optional[ActorEntry]] = ContextVar('actor', default=None)

# Globals inicializados en load() antes de arrancar uvicorn
_registry: Optional[TokenRegistry] = None
_policy: Optional[PolicyEngine] = None
_odoo: Optional[OdooClient] = None
_mw: Optional[AuthMiddleware] = None


def load() -> None:
    global _registry, _policy, _odoo, _mw
    _registry = TokenRegistry(Path(os.environ['ACTORS_REGISTRY_PATH']))
    _policy   = PolicyEngine(Path(os.environ['POLICIES_PATH']))
    _audit    = Audit(Path(os.environ['AUDIT_LOG_PATH']))
    _odoo     = OdooClient(CredentialsResolver())
    _mw       = AuthMiddleware(_registry, _policy, RateLimiter(), _audit)


# ---------------------------------------------------------------------------
# Middleware Bearer
# ---------------------------------------------------------------------------
class BearerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, req: Request, call_next):
        if not req.url.path.startswith('/mcp'):
            return await call_next(req)

        # GET sin Accept: text/event-stream — ChatGPT preflight/discovery.
        # FastMCP devolveria 406; interceptamos y retornamos 200 JSON basico.
        if req.method == 'GET':
            accept = req.headers.get('accept', '')
            if 'text/event-stream' not in accept:
                return JSONResponse(
                    {'jsonrpc': '2.0', 'result': {'name': 'odoo-mcp-v2', 'version': '0.1.0'}},
                    status_code=200,
                )
            # SSE legitimo — pasa sin auth (Claude.ai abre el stream antes del tool call)
            return await call_next(req)

        # POST — requiere autenticacion.
        # Acepta Authorization: Bearer (Claude.ai) o X-Api-Key (ChatGPT API key mode).
        auth      = req.headers.get('authorization', '')
        x_api_key = req.headers.get('x-api-key', '') or req.headers.get('X-Api-Key', '')
        ua        = req.headers.get('user-agent', '')
        token, src = AuthMiddleware.extract_token(auth, str(req.url.path), x_api_key)
        actor = _registry.verify(token) if _registry else None

        if not actor:
            if _mw:
                _mw.audit.emit(
                    allowed=False,
                    denied_reason='invalid_token',
                    client_type=AuthMiddleware.detect_client_type(ua, src),
                )
            return JSONResponse(
                {'jsonrpc': '2.0', 'id': None,
                 'error': {'code': -32001, 'message': 'Unauthorized: invalid_token'}},
                status_code=401,
            )

        tok = _actor.set(actor)
        try:
            return await call_next(req)
        finally:
            _actor.reset(tok)


def _a() -> ActorEntry:
    a = _actor.get()
    if not a:
        raise PermissionError('no_authenticated_actor')
    return a


# ---------------------------------------------------------------------------
# FastMCP + registro de tools
# ---------------------------------------------------------------------------
mcp = FastMCP('odoo-mcp-v2', stateless_http=True, json_response=True,
              host='0.0.0.0', port=8000)


@mcp.tool()
async def odoo_who_am_i(ctx: Context) -> dict:
    return await S.odoo_who_am_i(_a(), _odoo)

@mcp.tool()
async def odoo_health(ctx: Context) -> dict:
    return await S.odoo_health(_a(), _odoo)

@mcp.tool()
async def odoo_validate_apl_stages(ctx: Context) -> dict:
    return await S.odoo_validate_apl_stages(_a(), _odoo)

@mcp.tool()
async def odoo_my_tasks(ctx: Context, limit: int = 50) -> list:
    return await T.odoo_my_tasks(_a(), _odoo, _policy, limit=limit)

@mcp.tool()
async def odoo_my_tasks_today(ctx: Context, stage_today_id: int, limit: int = 50) -> list:
    return await T.odoo_my_tasks_today(_a(), _odoo, _policy, stage_today_id, limit=limit)

@mcp.tool()
async def odoo_my_tasks_overdue(ctx: Context, today_iso: str, limit: int = 50) -> list:
    return await T.odoo_my_tasks_overdue(_a(), _odoo, _policy, today_iso, limit=limit)

@mcp.tool()
async def odoo_create_my_todo_apl(ctx: Context, payload: dict) -> dict:
    return await T.odoo_create_my_todo_apl(_a(), _odoo, _policy, payload)

@mcp.tool()
async def odoo_create_project_task_apl(ctx: Context, project_id: int, payload: dict) -> dict:
    return await T.odoo_create_project_task_apl(_a(), _odoo, _policy, project_id, payload)

@mcp.tool()
async def odoo_update_task_apl(ctx: Context, task_id: int, changes: dict) -> dict:
    return await T.odoo_update_task_apl(_a(), _odoo, _policy, task_id, changes)

@mcp.tool()
async def odoo_move_task(ctx: Context, task_id: int, stage_id: int) -> dict:
    return await T.odoo_move_task(_a(), _odoo, _policy, task_id, stage_id)

@mcp.tool()
async def odoo_mark_task_done(ctx: Context, task_id: int, evidence: str, done_stage_id: int) -> dict:
    return await T.odoo_mark_task_done(_a(), _odoo, _policy, task_id, evidence, done_stage_id)

@mcp.tool()
async def odoo_cancel_task(ctx: Context, task_id: int, reason: str, cancelled_stage_id: int) -> dict:
    return await T.odoo_cancel_task(_a(), _odoo, _policy, task_id, reason, cancelled_stage_id)

@mcp.tool()
async def odoo_list_projects(ctx: Context, limit: int = 50) -> list:
    return await P.odoo_list_projects(_a(), _odoo, _policy, limit=limit)

@mcp.tool()
async def odoo_get_project(ctx: Context, project_id: int) -> dict:
    return await P.odoo_get_project(_a(), _odoo, _policy, project_id)

@mcp.tool()
async def odoo_create_project(ctx: Context, name: str, description: str = None,
                               user_id: int = None) -> dict:
    return await P.odoo_create_project(_a(), _odoo, _policy, name, description, user_id)

@mcp.tool()
async def odoo_update_project_basic(ctx: Context, project_id: int, changes: dict) -> dict:
    return await P.odoo_update_project_basic(_a(), _odoo, _policy, project_id, changes)

@mcp.tool()
async def odoo_project_tasks(ctx: Context, project_id: int, limit: int = 100) -> list:
    return await P.odoo_project_tasks(_a(), _odoo, _policy, project_id, limit=limit)

@mcp.tool()
async def odoo_list_calendar_events(ctx: Context, start_after: str, end_before: str,
                                    limit: int = 100) -> list:
    return await C.odoo_list_calendar_events(_a(), _odoo, _policy, start_after, end_before,
                                              limit=limit)

@mcp.tool()
async def odoo_create_calendar_event(ctx: Context, name: str, start: str, stop: str,
                                     description: str = None, location: str = None,
                                     partner_ids: list = None, allday: bool = False) -> dict:
    return await C.odoo_create_calendar_event(_a(), _odoo, _policy, name, start, stop,
                                               description, location, partner_ids, allday)

@mcp.tool()
async def odoo_update_calendar_event(ctx: Context, event_id: int, changes: dict) -> dict:
    return await C.odoo_update_calendar_event(_a(), _odoo, _policy, event_id, changes)

@mcp.tool()
async def odoo_list_employees(ctx: Context, department_id: int = None, limit: int = 50) -> list:
    return await E.odoo_list_employees(_a(), _odoo, _policy, department_id=department_id,
                                        limit=limit)

@mcp.tool()
async def odoo_get_employee(ctx: Context, employee_id: int) -> dict:
    return await E.odoo_get_employee(_a(), _odoo, _policy, employee_id)

@mcp.tool()
async def odoo_search_employee(ctx: Context, query: str, limit: int = 20) -> list:
    return await E.odoo_search_employee(_a(), _odoo, _policy, query, limit=limit)

@mcp.tool()
async def odoo_list_crm_leads(ctx: Context, stage_id: int = None, limit: int = 50) -> list:
    return await CR.odoo_list_crm_leads(_a(), _odoo, _policy, stage_id=stage_id, limit=limit)

@mcp.tool()
async def odoo_get_crm_lead(ctx: Context, lead_id: int) -> dict:
    return await CR.odoo_get_crm_lead(_a(), _odoo, _policy, lead_id)

@mcp.tool()
async def odoo_add_crm_note(ctx: Context, lead_id: int, body: str) -> dict:
    return await CR.odoo_add_crm_note(_a(), _odoo, _policy, lead_id, body)

@mcp.tool()
async def odoo_create_crm_activity(ctx: Context, lead_id: int, summary: str, deadline: str,
                                    activity_type_id: int, user_id: int = None,
                                    note: str = None) -> dict:
    return await CR.odoo_create_crm_activity(_a(), _odoo, _policy, lead_id, summary, deadline,
                                              activity_type_id, user_id, note)

@mcp.tool()
async def odoo_list_partners(ctx: Context, only_companies: bool = False, limit: int = 50) -> list:
    return await PA.odoo_list_partners(_a(), _odoo, _policy, only_companies=only_companies,
                                        limit=limit)

@mcp.tool()
async def odoo_get_partner(ctx: Context, partner_id: int) -> dict:
    return await PA.odoo_get_partner(_a(), _odoo, _policy, partner_id)

@mcp.tool()
async def odoo_search_partner(ctx: Context, query: str, limit: int = 20) -> list:
    return await PA.odoo_search_partner(_a(), _odoo, _policy, query, limit=limit)

# Aliases BLUE — compatibilidad con conectores que usan nombres originales
odoo_personal_tasks  = odoo_my_tasks
odoo_test_connection = odoo_who_am_i

# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    load()
    app = mcp.streamable_http_app()
    app.add_middleware(BearerMiddleware)
    uvicorn.run(app, host='0.0.0.0', port=8000)
