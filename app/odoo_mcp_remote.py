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
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

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
# Middleware ASGI puro — permite reescribir el path antes de FastMCP
# ---------------------------------------------------------------------------
_JSON_401 = (
    b'{"jsonrpc":"2.0","id":null,'
    b'"error":{"code":-32001,"message":"Unauthorized: invalid_token"}}'
)
_JSON_DISCOVERY = (
    b'{"jsonrpc":"2.0","result":{"name":"odoo-mcp-v2","version":"0.1.0"}}'
)


class BearerMiddleware:
    """Middleware ASGI que:
    1. Extrae token de Bearer header, X-Api-Key o path opaco /mcp/<token>.
    2. Reescribe /mcp/<token> → /mcp para que FastMCP lo procese correctamente.
    3. Devuelve 401 si el token no es válido en requests POST.
    4. Devuelve 200 JSON discovery para GET sin Accept: text/event-stream.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path   = scope.get('path', '')
        method = scope.get('method', '')

        if not path.startswith('/mcp'):
            await self.app(scope, receive, send)
            return

        headers_raw = dict(scope.get('headers', []))
        auth      = headers_raw.get(b'authorization', b'').decode()
        x_api_key = headers_raw.get(b'x-api-key', b'').decode()
        ua        = headers_raw.get(b'user-agent', b'').decode()
        accept    = headers_raw.get(b'accept', b'').decode()

        # --- GET: discovery / SSE ---
        if method == 'GET':
            if 'text/event-stream' not in accept:
                # ChatGPT preflight — devolver 200 JSON sin llegar a FastMCP
                await self._send_json(send, 200, _JSON_DISCOVERY)
                return
            # SSE legítimo (Claude.ai) — pasar sin auth
            await self.app(scope, receive, send)
            return

        # --- POST: requiere autenticacion ---
        token, src = AuthMiddleware.extract_token(auth, path, x_api_key)
        actor = _registry.verify(token) if _registry else None

        if not actor:
            if _mw:
                _mw.audit.emit(
                    allowed=False,
                    denied_reason='invalid_token',
                    client_type=AuthMiddleware.detect_client_type(ua, src),
                )
            await self._send_json(send, 401, _JSON_401)
            return

        # Si el token vino en el path (/mcp/<token>), reescribir → /mcp
        # para que FastMCP lo procese en su endpoint registrado.
        if src == 'path' and path != '/mcp':
            scope = {**scope, 'path': '/mcp', 'raw_path': b'/mcp'}

        tok = _actor.set(actor)
        try:
            await self.app(scope, receive, send)
        finally:
            _actor.reset(tok)

    @staticmethod
    async def _send_json(send: Send, status: int, body: bytes) -> None:
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json'),
                                (b'content-length', str(len(body)).encode())]})
        await send({'type': 'http.response.body', 'body': body, 'more_body': False})


from app.auth_middleware import now_ms


def _a() -> ActorEntry:
    a = _actor.get()
    if not a:
        raise PermissionError('no_authenticated_actor')
    return a


async def _audited(coro, tool_name: str, actor: Optional[ActorEntry] = None):
    """Ejecuta coro y emite audit entry de success o error con latencia.

    actor debe pasarse explicitamente desde el scope de la tool (@mcp.tool),
    donde el ContextVar si es accesible. No leer _actor.get() aqui: Starlette
    BaseHTTPMiddleware ejecuta call_next en un task group separado de anyio y
    la copia del ContextVar puede no propagarse a este scope.
    """
    start = now_ms()
    try:
        result = await coro
        if _mw and actor:
            _mw.audit.emit(
                actor=actor.actor,
                role=actor.role,
                tool=tool_name,
                allowed=True,
                latency_ms=now_ms() - start,
                result_count=len(result) if isinstance(result, list) else 1,
            )
        return result
    except Exception as exc:
        is_denied = isinstance(exc, PermissionError)
        if _mw and actor:
            _mw.audit.emit(
                actor=actor.actor,
                role=actor.role,
                tool=tool_name,
                allowed=not is_denied,
                denied_reason=str(exc)[:120] if is_denied else None,
                error_class=None if is_denied else exc.__class__.__name__,
                latency_ms=now_ms() - start,
            )
        raise


# ---------------------------------------------------------------------------
# FastMCP + registro de tools
# ---------------------------------------------------------------------------
mcp = FastMCP('odoo-mcp-v2', stateless_http=True, json_response=True,
              host='0.0.0.0', port=8000)


@mcp.tool()
async def odoo_who_am_i(ctx: Context) -> dict:
    a = _a(); return await _audited(S.odoo_who_am_i(a, _odoo), 'odoo_who_am_i', a)

@mcp.tool()
async def odoo_health(ctx: Context) -> dict:
    a = _a(); return await _audited(S.odoo_health(a, _odoo), 'odoo_health', a)

@mcp.tool()
async def odoo_validate_apl_stages(ctx: Context) -> dict:
    a = _a(); return await _audited(S.odoo_validate_apl_stages(a, _odoo), 'odoo_validate_apl_stages', a)

@mcp.tool()
async def odoo_my_tasks(ctx: Context, limit: int = 50) -> list:
    a = _a(); return await _audited(T.odoo_my_tasks(a, _odoo, _policy, limit=limit), 'odoo_my_tasks', a)

@mcp.tool()
async def odoo_my_tasks_today(ctx: Context, stage_today_id: int, limit: int = 50) -> list:
    a = _a(); return await _audited(T.odoo_my_tasks_today(a, _odoo, _policy, stage_today_id, limit=limit), 'odoo_my_tasks_today', a)

@mcp.tool()
async def odoo_my_tasks_overdue(ctx: Context, today_iso: str, limit: int = 50) -> list:
    a = _a(); return await _audited(T.odoo_my_tasks_overdue(a, _odoo, _policy, today_iso, limit=limit), 'odoo_my_tasks_overdue', a)

@mcp.tool()
async def odoo_create_my_todo_apl(ctx: Context, payload: dict) -> dict:
    a = _a(); return await _audited(T.odoo_create_my_todo_apl(a, _odoo, _policy, payload), 'odoo_create_my_todo_apl', a)

@mcp.tool()
async def odoo_create_project_task_apl(ctx: Context, project_id: int, payload: dict) -> dict:
    a = _a(); return await _audited(T.odoo_create_project_task_apl(a, _odoo, _policy, project_id, payload), 'odoo_create_project_task_apl', a)

@mcp.tool()
async def odoo_update_task_apl(ctx: Context, task_id: int, changes: dict) -> dict:
    a = _a(); return await _audited(T.odoo_update_task_apl(a, _odoo, _policy, task_id, changes), 'odoo_update_task_apl', a)

@mcp.tool()
async def odoo_move_task(ctx: Context, task_id: int, stage_id: int) -> dict:
    a = _a(); return await _audited(T.odoo_move_task(a, _odoo, _policy, task_id, stage_id), 'odoo_move_task', a)

@mcp.tool()
async def odoo_mark_task_done(ctx: Context, task_id: int, evidence: str, done_stage_id: int) -> dict:
    a = _a(); return await _audited(T.odoo_mark_task_done(a, _odoo, _policy, task_id, evidence, done_stage_id), 'odoo_mark_task_done', a)

@mcp.tool()
async def odoo_cancel_task(ctx: Context, task_id: int, reason: str, cancelled_stage_id: int) -> dict:
    a = _a(); return await _audited(T.odoo_cancel_task(a, _odoo, _policy, task_id, reason, cancelled_stage_id), 'odoo_cancel_task', a)

@mcp.tool()
async def odoo_list_projects(ctx: Context, limit: int = 50) -> list:
    a = _a(); return await _audited(P.odoo_list_projects(a, _odoo, _policy, limit=limit), 'odoo_list_projects', a)

@mcp.tool()
async def odoo_get_project(ctx: Context, project_id: int) -> dict:
    a = _a(); return await _audited(P.odoo_get_project(a, _odoo, _policy, project_id), 'odoo_get_project', a)

@mcp.tool()
async def odoo_create_project(ctx: Context, name: str, description: str = None,
                               user_id: int = None) -> dict:
    a = _a(); return await _audited(P.odoo_create_project(a, _odoo, _policy, name, description, user_id), 'odoo_create_project', a)

@mcp.tool()
async def odoo_update_project_basic(ctx: Context, project_id: int, changes: dict) -> dict:
    a = _a(); return await _audited(P.odoo_update_project_basic(a, _odoo, _policy, project_id, changes), 'odoo_update_project_basic', a)

@mcp.tool()
async def odoo_project_tasks(ctx: Context, project_id: int, limit: int = 100) -> list:
    a = _a(); return await _audited(P.odoo_project_tasks(a, _odoo, _policy, project_id, limit=limit), 'odoo_project_tasks', a)

@mcp.tool()
async def odoo_list_calendar_events(ctx: Context, start_after: str, end_before: str,
                                    limit: int = 100) -> list:
    a = _a(); return await _audited(C.odoo_list_calendar_events(a, _odoo, _policy, start_after, end_before, limit=limit), 'odoo_list_calendar_events', a)

@mcp.tool()
async def odoo_create_calendar_event(ctx: Context, name: str, start: str, stop: str,
                                     description: str = None, location: str = None,
                                     partner_ids: list = None, allday: bool = False) -> dict:
    a = _a(); return await _audited(C.odoo_create_calendar_event(a, _odoo, _policy, name, start, stop,
                                               description, location, partner_ids, allday), 'odoo_create_calendar_event', a)

@mcp.tool()
async def odoo_update_calendar_event(ctx: Context, event_id: int, changes: dict) -> dict:
    a = _a(); return await _audited(C.odoo_update_calendar_event(a, _odoo, _policy, event_id, changes), 'odoo_update_calendar_event', a)

@mcp.tool()
async def odoo_list_employees(ctx: Context, department_id: int = None, limit: int = 50) -> list:
    a = _a(); return await _audited(E.odoo_list_employees(a, _odoo, _policy, department_id=department_id, limit=limit), 'odoo_list_employees', a)

@mcp.tool()
async def odoo_get_employee(ctx: Context, employee_id: int) -> dict:
    a = _a(); return await _audited(E.odoo_get_employee(a, _odoo, _policy, employee_id), 'odoo_get_employee', a)

@mcp.tool()
async def odoo_search_employee(ctx: Context, query: str, limit: int = 20) -> list:
    a = _a(); return await _audited(E.odoo_search_employee(a, _odoo, _policy, query, limit=limit), 'odoo_search_employee', a)

@mcp.tool()
async def odoo_list_crm_leads(ctx: Context, stage_id: int = None, limit: int = 50) -> list:
    a = _a(); return await _audited(CR.odoo_list_crm_leads(a, _odoo, _policy, stage_id=stage_id, limit=limit), 'odoo_list_crm_leads', a)

@mcp.tool()
async def odoo_get_crm_lead(ctx: Context, lead_id: int) -> dict:
    a = _a(); return await _audited(CR.odoo_get_crm_lead(a, _odoo, _policy, lead_id), 'odoo_get_crm_lead', a)

@mcp.tool()
async def odoo_add_crm_note(ctx: Context, lead_id: int, body: str) -> dict:
    a = _a(); return await _audited(CR.odoo_add_crm_note(a, _odoo, _policy, lead_id, body), 'odoo_add_crm_note', a)

@mcp.tool()
async def odoo_create_crm_activity(ctx: Context, lead_id: int, summary: str, deadline: str,
                                    activity_type_id: int, user_id: int = None,
                                    note: str = None) -> dict:
    a = _a(); return await _audited(CR.odoo_create_crm_activity(a, _odoo, _policy, lead_id, summary,
                                              deadline, activity_type_id, user_id, note), 'odoo_create_crm_activity', a)

@mcp.tool()
async def odoo_list_partners(ctx: Context, only_companies: bool = False, limit: int = 50) -> list:
    a = _a(); return await _audited(PA.odoo_list_partners(a, _odoo, _policy, only_companies=only_companies, limit=limit), 'odoo_list_partners', a)

@mcp.tool()
async def odoo_get_partner(ctx: Context, partner_id: int) -> dict:
    a = _a(); return await _audited(PA.odoo_get_partner(a, _odoo, _policy, partner_id), 'odoo_get_partner', a)

@mcp.tool()
async def odoo_search_partner(ctx: Context, query: str, limit: int = 20) -> list:
    a = _a(); return await _audited(PA.odoo_search_partner(a, _odoo, _policy, query, limit=limit), 'odoo_search_partner', a)

# Aliases BLUE — compatibilidad con conectores que usan nombres originales
odoo_personal_tasks  = odoo_my_tasks
odoo_test_connection = odoo_who_am_i

# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    load()
    # BearerMiddleware es ASGI puro: wrapping directo, no add_middleware()
    # Esto permite reescribir scope['path'] antes de que FastMCP lo procese.
    inner = mcp.streamable_http_app()
    app   = BearerMiddleware(inner)
    uvicorn.run(app, host='0.0.0.0', port=8000)
