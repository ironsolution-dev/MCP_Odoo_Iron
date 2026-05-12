"""Tools de project.task — refactor actor-aware de las 9 tools BLUE + nuevas
para tareas de proyecto. Todas las de escritura hacen read-after-write."""

from __future__ import annotations

from typing import Any, Optional

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.schemas import (
    ValidationError,
    validate_apl_task_input,
    validate_cancel_reason,
    validate_evidence,
)
from app.token_registry import ActorEntry


# Campos seguros para devolver al LLM en lecturas/responses.
TASK_SAFE_FIELDS: list[str] = [
    "id", "name", "description", "priority", "stage_id", "state",
    "project_id", "user_ids", "create_date", "write_date", "date_deadline",
    "date_assign", "tag_ids", "kanban_state",
]

TASK_WRITABLE_FIELDS_BASIC: set[str] = {
    "name", "description", "priority", "date_deadline",
    "stage_id", "tag_ids",
}


def _ensure_policy(policy: PolicyEngine, actor: ActorEntry, tool: str, model: str,
                   action: str, fields: Optional[list[str]] = None) -> None:
    decision = policy.allows(actor.policy, tool, model, action, fields=fields)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


# ---------------------------------------------------------------------------
# Lecturas To Do personal (alias BLUE: odoo_personal_*)
# ---------------------------------------------------------------------------

async def odoo_my_tasks(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                        limit: int = 50) -> list[dict]:
    """Lista To Do personal del actor (sin project_id, donde el actor figura como asignado)."""
    _ensure_policy(policy, actor, "odoo_my_tasks", "project.task", "read", fields=TASK_SAFE_FIELDS)
    uid = await odoo.authenticate(actor)
    domain = [("project_id", "=", False), ("user_ids", "in", [uid])]
    return await odoo.search_read(actor, "project.task", domain, TASK_SAFE_FIELDS,
                                  limit=limit, order="date_deadline asc, priority desc")


async def odoo_my_tasks_today(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                              stage_today_id: int, limit: int = 50) -> list[dict]:
    """Tareas en etapa Hoy del actor. `stage_today_id` se resuelve desde
    docs/APL_STAGES.md (Willy lo llena tras Fase 0)."""
    _ensure_policy(policy, actor, "odoo_my_tasks_today", "project.task", "read", fields=TASK_SAFE_FIELDS)
    uid = await odoo.authenticate(actor)
    domain = [("project_id", "=", False), ("user_ids", "in", [uid]),
              ("stage_id", "=", stage_today_id)]
    return await odoo.search_read(actor, "project.task", domain, TASK_SAFE_FIELDS,
                                  limit=limit, order="priority desc")


async def odoo_my_tasks_overdue(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                today_iso: str, limit: int = 50) -> list[dict]:
    """Tareas vencidas (deadline < today) del actor, sin cerrar."""
    _ensure_policy(policy, actor, "odoo_my_tasks_overdue", "project.task", "read", fields=TASK_SAFE_FIELDS)
    uid = await odoo.authenticate(actor)
    domain = [
        ("project_id", "=", False),
        ("user_ids", "in", [uid]),
        ("date_deadline", "<", today_iso),
        ("state", "not in", ["1_done", "1_canceled"]),
    ]
    return await odoo.search_read(actor, "project.task", domain, TASK_SAFE_FIELDS,
                                  limit=limit, order="date_deadline asc")


# ---------------------------------------------------------------------------
# Escritura — APL 2.0 obligatorio
# ---------------------------------------------------------------------------

async def odoo_create_my_todo_apl(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                  payload: dict) -> dict:
    """Crea un To Do personal con APL 2.0 obligatorio. Read-after-write."""
    _ensure_policy(policy, actor, "odoo_create_my_todo_apl", "project.task", "create")
    apl = validate_apl_task_input(payload)

    uid = await odoo.authenticate(actor)
    values = {
        "name": apl.title,
        "description": apl.description,
        "priority": "0" if apl.priority == "P3" else ("1" if apl.priority == "P2" else "2"),
        "date_deadline": apl.deadline,
        "project_id": False,
        "user_ids": [(6, 0, [uid])],
    }
    new_id = await odoo.create(actor, "project.task", values)
    created = await odoo.read(actor, "project.task", [new_id], TASK_SAFE_FIELDS)
    return created[0] if created else {"id": new_id, "warning": "read-after-write returned empty"}


async def odoo_create_project_task_apl(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                       project_id: int, payload: dict) -> dict:
    """Crea tarea APL 2.0 dentro de un proyecto. El proyecto DEBE ser visible
    por el actor (Odoo ACL filtra)."""
    _ensure_policy(policy, actor, "odoo_create_project_task_apl", "project.task", "create")
    apl = validate_apl_task_input(payload)

    # Verifica que el proyecto es visible — si no, Odoo retorna []
    visible = await odoo.search_read(actor, "project.project", [("id", "=", project_id)],
                                     ["id"], limit=1)
    if not visible:
        raise PermissionError(f"project_not_accessible:{project_id}")

    uid = await odoo.authenticate(actor)
    values = {
        "name": apl.title,
        "description": apl.description,
        "priority": "0" if apl.priority == "P3" else ("1" if apl.priority == "P2" else "2"),
        "date_deadline": apl.deadline,
        "project_id": project_id,
        "user_ids": [(6, 0, [uid])],
    }
    new_id = await odoo.create(actor, "project.task", values)
    created = await odoo.read(actor, "project.task", [new_id], TASK_SAFE_FIELDS)
    return created[0] if created else {"id": new_id, "warning": "read-after-write returned empty"}


async def odoo_update_task_apl(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                               task_id: int, changes: dict) -> dict:
    """Actualiza campos permitidos de una tarea. Read-after-write."""
    invalid = [k for k in changes if k not in TASK_WRITABLE_FIELDS_BASIC]
    if invalid:
        raise PermissionError(f"fields_not_writable:{invalid}")
    _ensure_policy(policy, actor, "odoo_update_task_apl", "project.task", "write")

    await odoo.write(actor, "project.task", [task_id], changes)
    after = await odoo.read(actor, "project.task", [task_id], TASK_SAFE_FIELDS)
    return after[0] if after else {"id": task_id, "warning": "read-after-write returned empty"}


async def odoo_move_task(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                         task_id: int, stage_id: int) -> dict:
    """Mueve la tarea a otra etapa. Read-after-write."""
    _ensure_policy(policy, actor, "odoo_move_task", "project.task", "write")
    await odoo.write(actor, "project.task", [task_id], {"stage_id": stage_id})
    after = await odoo.read(actor, "project.task", [task_id], TASK_SAFE_FIELDS)
    return after[0] if after else {"id": task_id, "warning": "read-after-write returned empty"}


async def odoo_mark_task_done(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                              task_id: int, evidence: str, done_stage_id: int) -> dict:
    """Cierra una tarea exigiendo evidencia (APL 2.0: no cerrar sin evidencia).
    Read-after-write y verificacion de estado final."""
    cleaned_evidence = validate_evidence(evidence)
    _ensure_policy(policy, actor, "odoo_mark_task_done", "project.task", "write")

    # Post evidencia como mensaje primero (queda en el chatter)
    await odoo.call(actor, "project.task", "message_post", [[task_id]],
                    {"body": f"[Evidencia de cierre]\n{cleaned_evidence}"})
    # Mover a Done stage + state
    await odoo.write(actor, "project.task", [task_id],
                     {"stage_id": done_stage_id, "state": "1_done"})

    after = await odoo.read(actor, "project.task", [task_id],
                            TASK_SAFE_FIELDS + ["state"])
    return {
        "task": after[0] if after else {"id": task_id},
        "evidence_recorded": True,
        "evidence_length": len(cleaned_evidence),
    }


async def odoo_cancel_task(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                           task_id: int, reason: str, cancelled_stage_id: int) -> dict:
    """Cancela una tarea registrando el motivo en el chatter."""
    cleaned_reason = validate_cancel_reason(reason)
    _ensure_policy(policy, actor, "odoo_cancel_task", "project.task", "write")

    await odoo.call(actor, "project.task", "message_post", [[task_id]],
                    {"body": f"[Motivo de cancelacion]\n{cleaned_reason}"})
    await odoo.write(actor, "project.task", [task_id],
                     {"stage_id": cancelled_stage_id, "state": "1_canceled"})

    after = await odoo.read(actor, "project.task", [task_id],
                            TASK_SAFE_FIELDS + ["state"])
    return {
        "task": after[0] if after else {"id": task_id},
        "cancel_reason_recorded": True,
    }


# ---------------------------------------------------------------------------
# Aliases temporales (compatibilidad BLUE) — sec 12.7 Task Packet
# ---------------------------------------------------------------------------

odoo_personal_tasks = odoo_my_tasks
odoo_personal_tasks_today = odoo_my_tasks_today
odoo_personal_tasks_overdue = odoo_my_tasks_overdue
odoo_create_personal_task = odoo_create_my_todo_apl
odoo_move_personal_task = odoo_move_task


# Marcador defensivo: no exponer execute_kw / execute genericos
def __safety_no_generic_execute_in_this_module() -> Any:
    """No tocar. Existe para que test_no_generic_execute_tool grep falle si
    accidentalmente alguien agrega una tool execute_kw aqui."""
    return None
