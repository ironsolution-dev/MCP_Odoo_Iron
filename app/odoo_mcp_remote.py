"""Entry point FastMCP — registra tools, configura middleware y arranca
servidor streamable-http en puerto 8000.

Las tools del paquete `app.tools.*` se envuelven con auth_middleware al
registrarlas: cada llamada pasa por authenticate -> authorize_tool -> tool
-> audit.

Variables de entorno requeridas: ver scripts/validate_env.py.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.audit import Audit
from app.auth_middleware import (
    AuthContext,
    AuthError,
    AuthMiddleware,
    DeniedByPolicy,
    DeniedByRateLimit,
    now_ms,
)
from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.rate_limit import RateLimiter
from app.token_registry import TokenRegistry
from app.tools import calendar as calendar_tools
from app.tools import crm as crm_tools
from app.tools import employees as employee_tools
from app.tools import partners as partner_tools
from app.tools import projects as project_tools
from app.tools import system as system_tools
from app.tools import tasks as task_tools


# ---------------------------------------------------------------------------
# Tool registry — declaracion centralizada de (tool_name, callable, model, action)
# ---------------------------------------------------------------------------

ToolFn = Callable[..., Awaitable[Any]]


# (tool_name, callable, model, action)
TOOL_REGISTRY: list[tuple[str, ToolFn, str, str]] = [
    # System
    ("odoo_who_am_i", system_tools.odoo_who_am_i, "res.users", "read"),
    ("odoo_health", system_tools.odoo_health, "res.users", "read"),
    ("odoo_validate_apl_stages", system_tools.odoo_validate_apl_stages,
     "project.task.type", "read"),
    # Tasks
    ("odoo_my_tasks", task_tools.odoo_my_tasks, "project.task", "read"),
    ("odoo_my_tasks_today", task_tools.odoo_my_tasks_today, "project.task", "read"),
    ("odoo_my_tasks_overdue", task_tools.odoo_my_tasks_overdue, "project.task", "read"),
    ("odoo_create_my_todo_apl", task_tools.odoo_create_my_todo_apl, "project.task", "create"),
    ("odoo_create_project_task_apl", task_tools.odoo_create_project_task_apl,
     "project.task", "create"),
    ("odoo_update_task_apl", task_tools.odoo_update_task_apl, "project.task", "write"),
    ("odoo_move_task", task_tools.odoo_move_task, "project.task", "write"),
    ("odoo_mark_task_done", task_tools.odoo_mark_task_done, "project.task", "write"),
    ("odoo_cancel_task", task_tools.odoo_cancel_task, "project.task", "write"),
    # Projects
    ("odoo_list_projects", project_tools.odoo_list_projects, "project.project", "read"),
    ("odoo_get_project", project_tools.odoo_get_project, "project.project", "read"),
    ("odoo_create_project", project_tools.odoo_create_project, "project.project", "create"),
    ("odoo_update_project_basic", project_tools.odoo_update_project_basic,
     "project.project", "write"),
    ("odoo_project_tasks", project_tools.odoo_project_tasks, "project.task", "read"),
    # Calendar
    ("odoo_list_calendar_events", calendar_tools.odoo_list_calendar_events,
     "calendar.event", "read"),
    ("odoo_create_calendar_event", calendar_tools.odoo_create_calendar_event,
     "calendar.event", "create"),
    ("odoo_update_calendar_event", calendar_tools.odoo_update_calendar_event,
     "calendar.event", "write"),
    # Employees
    ("odoo_list_employees", employee_tools.odoo_list_employees, "hr.employee", "read"),
    ("odoo_get_employee", employee_tools.odoo_get_employee, "hr.employee", "read"),
    ("odoo_search_employee", employee_tools.odoo_search_employee, "hr.employee", "read"),
    # CRM
    ("odoo_list_crm_leads", crm_tools.odoo_list_crm_leads, "crm.lead", "read"),
    ("odoo_get_crm_lead", crm_tools.odoo_get_crm_lead, "crm.lead", "read"),
    ("odoo_add_crm_note", crm_tools.odoo_add_crm_note, "mail.message", "create"),
    ("odoo_create_crm_activity", crm_tools.odoo_create_crm_activity, "mail.activity", "create"),
    # Partners
    ("odoo_list_partners", partner_tools.odoo_list_partners, "res.partner", "read"),
    ("odoo_get_partner", partner_tools.odoo_get_partner, "res.partner", "read"),
    ("odoo_search_partner", partner_tools.odoo_search_partner, "res.partner", "read"),
]


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def _load_components() -> tuple[TokenRegistry, PolicyEngine, AuthMiddleware, OdooClient]:
    actors_path = Path(os.environ["ACTORS_REGISTRY_PATH"])
    policies_path = Path(os.environ["POLICIES_PATH"])
    audit_path = Path(os.environ["AUDIT_LOG_PATH"])

    registry = TokenRegistry(actors_path)
    policy = PolicyEngine(policies_path)
    audit = Audit(audit_path)
    rate_limiter = RateLimiter()
    middleware = AuthMiddleware(registry, policy, rate_limiter, audit)
    odoo = OdooClient()
    return registry, policy, middleware, odoo


def _make_wrapped_tool(
    name: str,
    fn: ToolFn,
    model: str,
    action: str,
    middleware: AuthMiddleware,
    policy: PolicyEngine,
    odoo: OdooClient,
):
    """Envuelve una tool con auth/policy/audit. La firma final para FastMCP
    es (request_context, **kwargs). El request_context se inyecta por FastMCP."""

    async def wrapper(request_context: Any, **kwargs: Any) -> Any:
        # FastMCP entrega headers y path en request_context.request.* (segun
        # version). Aqui asumimos atributos: authorization, path, user_agent,
        # request_id.
        rctx = getattr(request_context, "request", request_context)
        ctx = middleware.authenticate(
            authorization_header=getattr(rctx, "authorization", None),
            path=getattr(rctx, "path", None),
            user_agent=getattr(rctx, "user_agent", None),
            request_id=getattr(rctx, "request_id", None),
        )
        try:
            middleware.authorize_tool(ctx, name, model, action)
        except (DeniedByPolicy, DeniedByRateLimit) as e:
            return {"error": "denied", "denied_reason": e.reason}

        start = now_ms()
        try:
            result = await fn(ctx.actor, odoo, policy, **kwargs)
        except Exception as e:  # noqa: BLE001
            middleware.audit_error(ctx, name, model, action, now_ms() - start,
                                    error_class=e.__class__.__name__, args=kwargs)
            return {"error": "exception", "class": e.__class__.__name__,
                    "message": str(e)[:200]}

        latency = now_ms() - start
        result_count = len(result) if isinstance(result, list) else 1
        middleware.audit_success(ctx, name, model, action, latency_ms=latency,
                                  result_count=result_count, args=kwargs)
        return result

    wrapper.__name__ = name
    return wrapper


def build_server():
    """Construye el FastMCP server con todas las tools registradas.
    Se invoca desde main(); separado para tests/imports."""
    from fastmcp import FastMCP  # import diferido para no requerir fastmcp en tests

    _registry, policy, middleware, odoo = _load_components()
    server = FastMCP("odoo-mcp-v2")

    for name, fn, model, action in TOOL_REGISTRY:
        wrapped = _make_wrapped_tool(name, fn, model, action, middleware, policy, odoo)
        server.tool(name=name)(wrapped)

    return server


def main():
    # Validar env vars antes de arrancar.
    from scripts.validate_env import main as _validate
    if _validate() != 0:
        raise SystemExit(1)

    server = build_server()
    server.run(transport="streamable-http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
