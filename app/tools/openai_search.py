"""Routing READ (`_route`) + tools publicas `search`/`fetch` compatibles con
ChatGPT chat-mode. `search()` tambien es la puerta de entrada al protocolo de
escritura (JSON action, ver openai_write_dispatch.py) y al parser NL.

Extraido de openai_compat.py (split mecanico, Fase A daily driver, sec 1).
Sin logica nueva.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry
from app.tools import (
    calendar as cal,
    crm,
    employees as emp,
    partners as par,
    projects as prj,
    system as sys_tools,
    tasks as tsk,
)
from app.tools import openai_nl_parser as nl_parser
from app.tools.openai_formatters import (
    _classify,
    _fmt_employee,
    _fmt_event,
    _fmt_identity,
    _fmt_lead,
    _fmt_partner,
    _fmt_project,
    _fmt_task,
    _full,
    _not_found,
)
from app.tools.openai_write_dispatch import (
    _WRITE_VERB_RE,
    _execute_action,
    _help_write_response,
    _try_parse_action,
)


# ---------------------------------------------------------------------------
# Routing: intent -> coroutine que devuelve list[dict] formateados
# ---------------------------------------------------------------------------

async def _route(intent: str, actor: ActorEntry, odoo: OdooClient,
                 policy: PolicyEngine) -> list[dict]:
    if intent == "identity":
        info = await sys_tools.odoo_who_am_i(actor, odoo)
        return [_fmt_identity(info)]
    if intent == "tasks_overdue":
        rows = await tsk.odoo_my_tasks_overdue(
            actor, odoo, policy, today_iso=date.today().isoformat(), limit=20,
        )
        return [_fmt_task(r) for r in rows]
    if intent == "tasks_my":
        rows = await tsk.odoo_my_tasks(actor, odoo, policy, limit=20)
        return [_fmt_task(r) for r in rows]
    if intent == "projects":
        rows = await prj.odoo_list_projects(actor, odoo, policy, limit=20)
        return [_fmt_project(r) for r in rows]
    if intent == "employees":
        rows = await emp.odoo_list_employees(actor, odoo, policy, limit=20)
        return [_fmt_employee(r) for r in rows]
    if intent == "partners":
        rows = await par.odoo_list_partners(actor, odoo, policy, limit=20)
        return [_fmt_partner(r) for r in rows]
    if intent == "crm_leads":
        rows = await crm.odoo_list_crm_leads(actor, odoo, policy, limit=20)
        return [_fmt_lead(r) for r in rows]
    if intent == "calendar_events":
        # Ventana amplia: 7 dias atras a 30 adelante (cubre eventos en curso).
        # El filtro user_id/partner_ids dentro de odoo_list_calendar_events
        # ya restringe a eventos del actor; ampliamos el rango temporal.
        start = (date.today() - timedelta(days=7)).isoformat()
        end = (date.today() + timedelta(days=30)).isoformat()
        rows = await cal.odoo_list_calendar_events(
            actor, odoo, policy, start, end, limit=20,
        )
        return [_fmt_event(r) for r in rows]
    # default: overview con tareas + proyectos. Cada bloque tolera Permission.
    results: list[dict] = []
    try:
        rows = await tsk.odoo_my_tasks(actor, odoo, policy, limit=10)
        results.extend(_fmt_task(r) for r in rows)
    except PermissionError:
        pass
    try:
        rows = await prj.odoo_list_projects(actor, odoo, policy, limit=10)
        results.extend(_fmt_project(r) for r in rows)
    except PermissionError:
        pass
    return results


# ---------------------------------------------------------------------------
# Public: search / fetch
# ---------------------------------------------------------------------------

async def search(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                 query: str) -> dict:
    """Busca entidades Odoo segun el query (ChatGPT chat-mode compatible).

    Modo READ (default): query natural -> retorna entidades.
    Modo WRITE: query contiene JSON con clave "action" -> ejecuta accion.

    Acciones soportadas via JSON action (envia el JSON dentro del query):
    create_task, create_todo, update_task, move_task, close_task,
    cancel_task, create_project, create_event.

    Si el query tiene verbos de escritura pero NO JSON, devuelve un template
    con el formato correcto para que el modelo aprenda.

    Devuelve {"results": [...]} con ids "<kind>:<num>" o "error:..." / "help:...".
    """
    q = query or ""

    # Path 1: JSON action embebido -> ejecutar.
    action_payload = _try_parse_action(q)
    if action_payload:
        return await _execute_action(action_payload, actor, odoo, policy)

    # Path 2: verbos de escritura sin JSON -> intentar parser NL antes de help.
    # Fase 4 (13-may-2026): ChatGPT chat-mode no reintenta con JSON tras help.
    # El servidor extrae intent+campos del lenguaje natural y ejecuta directo.
    if _WRITE_VERB_RE.search(q):
        nl_payload = await nl_parser.try_parse(q, actor, odoo, policy)
        if nl_payload:
            return await _execute_action(nl_payload, actor, odoo, policy)
        return _help_write_response()

    # Path 3: lectura normal por intent.
    intent = _classify(q)
    try:
        results = await _route(intent, actor, odoo, policy)
    except PermissionError as exc:
        return {"results": [{"id": "error:permission",
                              "title": "Acceso denegado",
                              "text": f"El actor {actor.actor} no tiene permiso "
                                      f"para esta consulta ({intent}). Detalle: {exc}",
                              "url": ""}]}
    return {"results": results}


async def fetch(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                id: str) -> dict:
    """Obtiene detalle de un registro por id compuesto `<kind>:<num>`.

    Kinds soportados: task, project, employee, partner, lead.
    """
    if not id or ":" not in id:
        return {"id": id, "error": "invalid_id_format",
                "expected": "<kind>:<num> (ej. task:42, project:7)"}
    kind, _, num_str = id.partition(":")
    try:
        rid = int(num_str)
    except ValueError:
        return {"id": id, "error": "invalid_numeric_id"}

    try:
        if kind == "task":
            rec = await tsk.odoo_get_task(actor, odoo, policy, rid)
            return _full(rec, "task") if rec.get("id") else _not_found(id, rec)
        if kind == "project":
            rec = await prj.odoo_get_project(actor, odoo, policy, rid)
            return _full(rec, "project") if rec else _not_found(id, None)
        if kind == "employee":
            rec = await emp.odoo_get_employee(actor, odoo, policy, rid)
            return _full(rec, "employee") if rec else _not_found(id, None)
        if kind == "partner":
            rec = await par.odoo_get_partner(actor, odoo, policy, rid)
            return _full(rec, "partner") if rec else _not_found(id, None)
        if kind == "lead":
            rec = await crm.odoo_get_crm_lead(actor, odoo, policy, rid)
            return _full(rec, "lead") if rec else _not_found(id, None)
    except PermissionError as exc:
        return {"id": id, "error": "permission_denied", "detail": str(exc)}

    return {"id": id, "error": "unknown_kind", "kind": kind,
            "supported": ["task", "project", "employee", "partner", "lead"]}
