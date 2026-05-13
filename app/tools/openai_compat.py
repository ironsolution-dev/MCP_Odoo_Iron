"""Adapter ChatGPT chat-mode: tools `search(query)` y `fetch(id)`.

Motivacion (verificado 13-may-2026 con audit.jsonl + screenshots de Yuniesky):
ChatGPT en modo chat estandar solo descubre tools cuyo nombre matchea el patron
`search` + `fetch` que OpenAI documenta para connectors MCP. Tools con nombres
custom (`odoo_my_tasks`, `odoo_list_projects`, ...) son INVISIBLES para el modelo
incluso con el conector activo. Claude.ai en cambio implementa MCP completo y
ve las 30 tools sin filtro.

Este modulo expone solo 2 tools compatibles:
- `search(query)`: enruta segun keywords del query a la tool especifica del
  dominio (my_tasks / list_projects / list_employees / etc.).
- `fetch(id)`: id compuesto `<kind>:<num>` (ej. `task:42`, `project:7`). Enruta
  a la tool `get_*` del dominio.

Las 30 tools nativas SIGUEN registradas para Claude.ai. Esto NO las reemplaza.
No agrega capacidad nueva: solo expone la existente con nombres que ChatGPT
puede descubrir. Sec 4.1 ADR-010 (dual connector Claude.ai+ChatGPT).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry
from app.tools import (
    calendar as cal,
    crm,
    employees as emp,
    partners as par,
    projects as prj,
    tasks as tsk,
)


# Patrones de intent en orden de precedencia. El primero que matchea decide.
# "tasks_overdue" antes que "tasks_my" porque "tareas vencidas" matchea ambos.
_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("tasks_overdue",   re.compile(r"\b(vencid|overdue|atrasad|retras)", re.I)),
    ("tasks_my",        re.compile(r"\b(mis tareas|tarea|todo|to.?do|pendient|asignad)", re.I)),
    ("projects",        re.compile(r"\b(proyecto|project)", re.I)),
    ("employees",       re.compile(r"\b(empleado|equipo|colega|colabora|staff|personal|team)", re.I)),
    ("partners",        re.compile(r"\b(contacto|cliente|partner|proveedor)", re.I)),
    ("crm_leads",       re.compile(r"\b(lead|oportunidad|crm|prospect)", re.I)),
    ("calendar_events", re.compile(r"\b(evento|calendar|reuni|cita|agenda|meeting)", re.I)),
]


def _classify(query: str) -> str:
    """Devuelve el intent matched o 'default' (overview)."""
    if not query:
        return "default"
    for kind, pattern in _INTENTS:
        if pattern.search(query):
            return kind
    return "default"


# ---------------------------------------------------------------------------
# Formatters Odoo dict -> OpenAI search result {id, title, text, url}
# ---------------------------------------------------------------------------

def _name_of(m2o: Any) -> str:
    """Extrae name de un many2one normalizado por OdooClient ({id, name})."""
    if isinstance(m2o, dict):
        return m2o.get("name") or ""
    return ""


def _fmt_task(r: dict) -> dict:
    project = _name_of(r.get("project_id")) or "Personal"
    deadline = r.get("date_deadline") or "sin fecha"
    return {
        "id": f"task:{r.get('id')}",
        "title": r.get("name") or "(sin titulo)",
        "text": f"Proyecto: {project} | Deadline: {deadline} | "
                f"{(r.get('description') or '')[:200]}",
        "url": "",
    }


def _fmt_project(r: dict) -> dict:
    return {
        "id": f"project:{r.get('id')}",
        "title": r.get("name") or "(sin nombre)",
        "text": (r.get("description") or "")[:300],
        "url": "",
    }


def _fmt_employee(r: dict) -> dict:
    return {
        "id": f"employee:{r.get('id')}",
        "title": r.get("name") or "(sin nombre)",
        "text": f"{_name_of(r.get('job_id'))} | {_name_of(r.get('department_id'))} | "
                f"{r.get('work_email') or ''}",
        "url": "",
    }


def _fmt_partner(r: dict) -> dict:
    return {
        "id": f"partner:{r.get('id')}",
        "title": r.get("display_name") or r.get("name") or "(sin nombre)",
        "text": f"{r.get('email') or ''} | {r.get('phone') or ''} | "
                f"{r.get('city') or ''}",
        "url": "",
    }


def _fmt_lead(r: dict) -> dict:
    return {
        "id": f"lead:{r.get('id')}",
        "title": r.get("name") or "(sin titulo)",
        "text": f"Etapa: {_name_of(r.get('stage_id')) or 'sin'} | "
                f"{r.get('email_from') or ''} | {r.get('phone') or ''}",
        "url": "",
    }


def _fmt_event(r: dict) -> dict:
    return {
        "id": f"event:{r.get('id')}",
        "title": r.get("name") or "(sin titulo)",
        "text": f"{r.get('start') or ''} -> {r.get('stop') or ''} | "
                f"{r.get('location') or ''}",
        "url": "",
    }


# ---------------------------------------------------------------------------
# Routing: intent -> coroutine que devuelve list[dict] formateados
# ---------------------------------------------------------------------------

async def _route(intent: str, actor: ActorEntry, odoo: OdooClient,
                 policy: PolicyEngine) -> list[dict]:
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
        today = date.today().isoformat()
        in_two_weeks = (date.today() + timedelta(days=14)).isoformat()
        rows = await cal.odoo_list_calendar_events(
            actor, odoo, policy, today, in_two_weeks, limit=20,
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

    Devuelve {"results": [...]} con ids "<kind>:<num>". Cada result tiene
    id, title, text, url (segun spec OpenAI search/fetch).
    """
    intent = _classify(query or "")
    try:
        results = await _route(intent, actor, odoo, policy)
    except PermissionError as exc:
        # Mantener estructura minima compatible con OpenAI ChatGPT search spec.
        # ChatGPT parece ignorar respuestas con keys extra. Solo `results`.
        return {"results": [{"id": "error:permission",
                              "title": "Acceso denegado",
                              "text": f"El actor {actor.actor} no tiene permiso "
                                      f"para esta consulta ({intent}). Detalle: {exc}",
                              "url": ""}]}
    # OpenAI spec estricto: solo `results`. Sin extras como `intent` que pueden
    # confundir al parser de ChatGPT.
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


def _full(rec: dict, kind: str) -> dict:
    title_map = {
        "task": rec.get("name"),
        "project": rec.get("name"),
        "employee": rec.get("name"),
        "partner": rec.get("display_name") or rec.get("name"),
        "lead": rec.get("name"),
    }
    return {
        "id": f"{kind}:{rec.get('id')}",
        "title": title_map.get(kind) or "",
        "text": rec.get("description") or "",
        "url": "",
        "metadata": rec,
    }


def _not_found(id: str, rec: Any) -> dict:
    err = (rec or {}).get("error") if isinstance(rec, dict) else None
    return {"id": id, "error": err or "not_found"}
