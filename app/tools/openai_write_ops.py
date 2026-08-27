"""Write tools — expuestos con nombres simples para que ChatGPT chat-mode los
descubra mas alla del patron search/fetch. Cada uno es un wrapper thin sobre
la tool odoo_* nativa correspondiente. Mantienen APL 2.0 (titulo + 8 campos
emoji en descripcion, resueltos via app.apl_validation.parse_and_validate_apl_task_input)
+ read-after-write.

Extraido de openai_compat.py (split mecanico, Fase A daily driver, sec 1).
Sin logica nueva. Consumido por openai_write_dispatch.py (protocolo JSON
action de search()) y re-exportado por odoo_mcp_remote.py para las tools
FastMCP `create_task`, `create_todo`, etc.
"""

from __future__ import annotations

from typing import Any

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry
from app.tools import calendar as cal, projects as prj, tasks as tsk
from app.tools.openai_formatters import _full


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

    APL 2.0 exige:
    - title: verbo + entregable + contexto, sin corchetes ni prefijos
      (el formato legado con prefijos entre corchetes de version anterior
      tambien se acepta y se normaliza automaticamente — ver ADR-016)
    - description: 8 campos con encabezado emoji (Responsable, Objetivo,
      Entregable, Fecha límite, Criterio de cierre, Evidencia requerida,
      Riesgo si no se cierra, Siguiente acción)
    - deadline: YYYY-MM-DD
    - area: departamento que EJECUTA (ej. "Operaciones", "Tecnologia")
    - task_type: tipo de ticket (ej. "Entregable", "Gestion")
    - priority: P0/P1/P2/P3 (default P2)

    Las 3 etiquetas canonicas (prioridad, departamento, tipo) se resuelven
    desde `app.apl_labels` (fuente unica de IDs); si area/task_type no
    matchea ningun nombre conocido, la tarea se crea sin esa etiqueta y el
    aviso viaja en la respuesta. Si el titulo o la descripcion no cumplen
    APL 2.0, retorna error con detalles para que el LLM corrija el payload.
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

    Mismos campos obligatorios que `create_task` pero sin project_id.
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

    Campos permitidos: name, description, priority, date_deadline (alias:
    `deadline`), stage_id, tag_ids, user_ids. NO enviar `deadline` y
    `date_deadline` a la vez (ambiguo, se rechaza). `project_id` NO es
    editable aqui: usa move_task_to_project para reasignar proyecto.
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


async def move_task_to_project(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                               id: Any, new_project_id: int) -> dict:
    """Mueve una tarea a otro proyecto (reasigna project_id). Distinto de
    move_task, que solo cambia de etapa dentro del mismo proyecto."""
    task_id = _parse_id(id, "task")
    result = await tsk.odoo_move_task_to_project(actor, odoo, policy, task_id, new_project_id)
    return _full(result["task"], "task") if result.get("moved") else {"error": "move_failed",
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
