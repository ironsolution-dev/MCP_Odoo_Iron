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

import json
import re
from datetime import date, timedelta
from typing import Any, Optional

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
# Write protocol: search() acepta JSON embebido con {"action": "..."}
# ChatGPT chat-mode solo descubre tools `search`/`fetch`. Para que pueda
# escribir, sobrecargamos search() para detectar JSON action en el query
# y ejecutar la operacion correspondiente. Verbose protocol — la confiabilidad
# depende de que el modelo siga el formato JSON que documentamos en las
# instructions del MCP. Fallback: si detecta verbos de escritura sin JSON,
# devuelve un help response con el template correcto.
# ---------------------------------------------------------------------------

# Verbos de accion que sugieren intent de escritura (fallback when no JSON).
_WRITE_VERB_RE = re.compile(
    r"\b(crea|crear|cree|nueva|nuevo|agrega|añade|"
    r"actualiza|modifica|edita|cambia|"
    r"cierra|finaliza|completa|"
    r"cancela|anula|"
    r"mueve|mover|"
    r"programa)\b",
    re.IGNORECASE,
)

# Acciones soportadas por _execute_action.
_VALID_ACTIONS = {
    "create_task", "create_todo", "update_task",
    "move_task", "close_task", "cancel_task",
    "create_project", "create_event",
}


def _try_parse_action(query: str) -> Optional[dict]:
    """Si el query contiene un objeto JSON con clave 'action', devolverlo.
    Acepta JSON embebido en cualquier posicion del query."""
    if not query or "{" not in query:
        return None
    # Match el objeto JSON mas grande en el query (greedy).
    match = re.search(r"\{.*\}", query, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict) and "action" in data:
        return data
    return None


def _help_write_response() -> dict:
    """Devuelve template para que ChatGPT aprenda el formato JSON action."""
    examples = (
        "ACCIONES soportadas por search() (envia JSON en el query):\n\n"
        '{"action":"create_task","project_id":3,"title":"[APL 2.0][P2][Area][Tipo] '
        'Verbo + entregable + contexto","description":"Objetivo: ...\\nEntregable: '
        '...\\nResponsable: ...\\nFecha limite: ...\\nCriterio de cierre: '
        '...\\nEvidencia requerida: ...\\nRiesgo si no se cierra: ...\\nSiguiente '
        'accion: ...","deadline":"2026-05-15","area":"Operaciones","task_type":"Test","priority":"P2"}\n\n'
        '{"action":"create_todo", ...mismos campos que create_task sin project_id}\n\n'
        '{"action":"update_task","id":"task:42","changes":{"name":"...","priority":"P1"}}\n\n'
        '{"action":"move_task","id":"task:42","stage_id":5}\n\n'
        '{"action":"close_task","id":"task:42","evidence":"...texto...","done_stage_id":7}\n\n'
        '{"action":"cancel_task","id":"task:42","reason":"...texto...","cancelled_stage_id":8}\n\n'
        '{"action":"create_project","name":"Nombre","description":"...","user_id":9}\n\n'
        '{"action":"create_event","name":"Reunion","start":"2026-05-14 10:00:00","stop":"2026-05-14 11:00:00"}'
    )
    return {"results": [{
        "id": "help:write_protocol",
        "title": "Para escribir en Odoo, envia search() con JSON action",
        "text": examples,
        "url": "",
    }]}


def _action_error(detail: str, kind: str = "error:action") -> dict:
    return {"results": [{
        "id": kind,
        "title": "Accion fallida",
        "text": detail,
        "url": "",
    }]}


async def _execute_action(payload: dict, actor: ActorEntry, odoo: OdooClient,
                          policy: PolicyEngine) -> dict:
    """Dispatcher: del JSON action al write tool correspondiente."""
    action = str(payload.get("action", "")).strip().lower()
    if action not in _VALID_ACTIONS:
        return _action_error(
            f"action='{action}' no soportado. Validas: {sorted(_VALID_ACTIONS)}",
            kind="error:unknown_action",
        )
    try:
        if action == "create_task":
            result = await create_task(
                actor, odoo, policy,
                project_id=int(payload["project_id"]),
                title=payload["title"],
                description=payload["description"],
                deadline=payload["deadline"],
                area=payload["area"],
                task_type=payload["task_type"],
                priority=payload.get("priority", "P2"),
            )
        elif action == "create_todo":
            result = await create_todo(
                actor, odoo, policy,
                title=payload["title"],
                description=payload["description"],
                deadline=payload["deadline"],
                area=payload["area"],
                task_type=payload["task_type"],
                priority=payload.get("priority", "P2"),
            )
        elif action == "update_task":
            result = await update_task(
                actor, odoo, policy,
                id=payload["id"],
                changes=payload["changes"],
            )
        elif action == "move_task":
            result = await move_task(
                actor, odoo, policy,
                id=payload["id"],
                stage_id=int(payload["stage_id"]),
            )
        elif action == "close_task":
            result = await close_task(
                actor, odoo, policy,
                id=payload["id"],
                evidence=payload["evidence"],
                done_stage_id=int(payload["done_stage_id"]),
            )
        elif action == "cancel_task":
            result = await cancel_task(
                actor, odoo, policy,
                id=payload["id"],
                reason=payload["reason"],
                cancelled_stage_id=int(payload["cancelled_stage_id"]),
            )
        elif action == "create_project":
            result = await create_project(
                actor, odoo, policy,
                name=payload["name"],
                description=payload.get("description"),
                user_id=payload.get("user_id"),
            )
        elif action == "create_event":
            result = await create_event(
                actor, odoo, policy,
                name=payload["name"],
                start=payload["start"],
                stop=payload["stop"],
                description=payload.get("description"),
                location=payload.get("location"),
                partner_ids=payload.get("partner_ids"),
                allday=payload.get("allday", False),
            )
        else:
            return _action_error(f"accion {action} sin handler")
    except KeyError as exc:
        return _action_error(
            f"falta campo obligatorio en payload: {exc.args[0]}",
            kind="error:missing_field",
        )
    except (ValueError, TypeError) as exc:
        return _action_error(
            f"tipo invalido: {exc}",
            kind="error:invalid_value",
        )
    except PermissionError as exc:
        return _action_error(
            f"acceso denegado: {exc}",
            kind="error:permission",
        )
    except Exception as exc:
        return _action_error(
            f"{exc.__class__.__name__}: {exc}",
            kind="error:execution",
        )

    # Envolver resultado en formato OpenAI search.
    if isinstance(result, dict) and result.get("error"):
        return _action_error(str(result), kind="error:tool_error")
    return {"results": [result]}


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

    # Path 2: verbos de escritura sin JSON -> guiar al modelo.
    if _WRITE_VERB_RE.search(q):
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


# ---------------------------------------------------------------------------
# Write tools — expuestos con nombres simples para que ChatGPT chat-mode los
# descubra mas alla del patron search/fetch. Cada uno es un wrapper thin sobre
# la tool odoo_* nativa correspondiente. Mantienen APL 2.0 (titulo + 8 campos
# en descripcion) + read-after-write.
# ---------------------------------------------------------------------------


def _parse_id(raw_id: Any, expected_kind: str) -> int:
    """Acepta `task:42`, `42`, o `42` int. Valida kind si viene compuesto."""
    if isinstance(raw_id, int):
        return raw_id
    if isinstance(raw_id, str):
        s = raw_id.strip()
        if ":" in s:
            kind, _, num = s.partition(":")
            if kind != expected_kind:
                raise ValueError(f"expected {expected_kind} id, got kind '{kind}'")
            return int(num)
        return int(s)
    raise ValueError(f"invalid id type: {type(raw_id).__name__}")


async def create_task(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                      project_id: int, title: str, description: str,
                      deadline: str, area: str, task_type: str,
                      priority: str = "P2") -> dict:
    """Crea una tarea APL 2.0 dentro de un proyecto.

    APL 2.0 exige 6 campos obligatorios:
    - title: titulo estructurado (6+ chars)
    - description: descripcion con 8 campos clave (Objetivo, Resultado, Pasos,
      Dependencias, Riesgos, Validacion, Plazo, Notas)
    - deadline: YYYY-MM-DD
    - area: dominio funcional (ej. "Operaciones", "TI")
    - task_type: tipo de trabajo (ej. "ejecucion", "revision")
    - priority: P1/P2/P3 (default P2)

    Si el titulo o la descripcion no cumplen APL 2.0, retorna error con
    detalles para que el LLM corrija el payload.
    """
    payload = {
        "title": title, "description": description,
        "priority": priority, "deadline": deadline,
        "area": area, "task_type": task_type,
    }
    result = await tsk.odoo_create_project_task_apl(actor, odoo, policy,
                                                     project_id, payload)
    return _full(result, "task") if result.get("id") else {"error": "create_failed",
                                                            "detail": result}


async def create_todo(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                      title: str, description: str,
                      deadline: str, area: str, task_type: str,
                      priority: str = "P2") -> dict:
    """Crea un To-Do personal APL 2.0 (sin proyecto asignado).

    Mismos 6 campos obligatorios que `create_task` pero sin project_id.
    """
    payload = {
        "title": title, "description": description,
        "priority": priority, "deadline": deadline,
        "area": area, "task_type": task_type,
    }
    result = await tsk.odoo_create_my_todo_apl(actor, odoo, policy, payload)
    return _full(result, "task") if result.get("id") else {"error": "create_failed",
                                                            "detail": result}


async def update_task(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                      id: Any, changes: dict) -> dict:
    """Actualiza campos editables de una tarea. id puede ser `task:42` o `42`.

    Campos permitidos: name, description, priority, date_deadline, stage_id, tag_ids.
    """
    task_id = _parse_id(id, "task")
    result = await tsk.odoo_update_task_apl(actor, odoo, policy, task_id, changes)
    return _full(result, "task") if result.get("id") else {"error": "update_failed",
                                                            "detail": result}


async def move_task(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                    id: Any, stage_id: int) -> dict:
    """Mueve una tarea a otra etapa del flujo APL 2.0."""
    task_id = _parse_id(id, "task")
    result = await tsk.odoo_move_task(actor, odoo, policy, task_id, stage_id)
    return _full(result, "task") if result.get("id") else {"error": "move_failed",
                                                            "detail": result}


async def close_task(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                     id: Any, evidence: str, done_stage_id: int) -> dict:
    """Cierra una tarea con evidencia obligatoria. La evidencia queda en el
    chatter de la tarea. APL 2.0 prohibe cerrar sin evidencia."""
    task_id = _parse_id(id, "task")
    result = await tsk.odoo_mark_task_done(actor, odoo, policy, task_id,
                                            evidence, done_stage_id)
    return {"id": f"task:{task_id}", "closed": True, "evidence_recorded": True,
            "metadata": result}


async def cancel_task(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                      id: Any, reason: str, cancelled_stage_id: int) -> dict:
    """Cancela una tarea registrando el motivo en el chatter."""
    task_id = _parse_id(id, "task")
    result = await tsk.odoo_cancel_task(actor, odoo, policy, task_id, reason,
                                         cancelled_stage_id)
    return {"id": f"task:{task_id}", "cancelled": True,
            "cancel_reason_recorded": True, "metadata": result}


async def create_project(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                         name: str, description: str = None,
                         user_id: int = None) -> dict:
    """Crea un proyecto nuevo en Odoo con campos basicos."""
    result = await prj.odoo_create_project(actor, odoo, policy, name,
                                            description, user_id)
    return _full(result, "project") if result.get("id") else {"error": "create_failed",
                                                              "detail": result}


async def create_event(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                       name: str, start: str, stop: str,
                       description: str = None, location: str = None,
                       partner_ids: list = None, allday: bool = False) -> dict:
    """Crea un evento de calendario. start y stop en formato ISO (YYYY-MM-DD HH:MM:SS)."""
    result = await cal.odoo_create_calendar_event(actor, odoo, policy, name,
                                                   start, stop, description,
                                                   location, partner_ids, allday)
    return {"id": f"event:{result.get('id')}",
            "title": result.get('name') or name,
            "text": f"{start} -> {stop}",
            "metadata": result} if result.get("id") else {"error": "create_failed",
                                                          "detail": result}
