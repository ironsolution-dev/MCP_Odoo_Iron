"""Tools de project.project."""

from __future__ import annotations

from typing import Optional

from app.odoo_client import OdooClient, extract_write_id
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry


PROJECT_SAFE_FIELDS: list[str] = [
    "id", "name", "description", "user_id", "partner_id",
    "date_start", "date", "active",
    # stage_id excluido: feature "Etapas de proyecto" no habilitada en esta instancia
]

PROJECT_WRITABLE_FIELDS: set[str] = {"name", "description", "user_id"}


def _ensure(policy: PolicyEngine, actor: ActorEntry, tool: str, action: str,
            fields: Optional[list[str]] = None) -> None:
    decision = policy.allows(actor.policy, tool, "project.project", action, fields=fields)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


async def odoo_list_projects(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                             limit: int = 50, offset: int = 0) -> list[dict]:
    _ensure(policy, actor, "odoo_list_projects", "read", fields=PROJECT_SAFE_FIELDS)
    return await odoo.search_read(actor, "project.project", [("active", "=", True)],
                                  PROJECT_SAFE_FIELDS, limit=limit, offset=offset,
                                  order="name asc")


async def odoo_get_project(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                           project_id: int) -> Optional[dict]:
    _ensure(policy, actor, "odoo_get_project", "read", fields=PROJECT_SAFE_FIELDS)
    result = await odoo.read(actor, "project.project", [project_id], PROJECT_SAFE_FIELDS)
    return result[0] if result else None


async def odoo_create_project(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                              name: str, description: Optional[str] = None,
                              user_id: Optional[int] = None) -> dict:
    _ensure(policy, actor, "odoo_create_project", "create",
            fields=["name", "description", "user_id"])
    if not name or not name.strip():
        raise ValueError("name vacio")
    values: dict = {"name": name.strip()}
    if description:
        values["description"] = description
    if user_id:
        values["user_id"] = user_id
    raw_result = await odoo.create(actor, "project.project", values)
    new_id = extract_write_id(raw_result, context="odoo_create_project:create")
    created = await odoo.read(actor, "project.project", [new_id], PROJECT_SAFE_FIELDS)
    return created[0] if created else {"id": new_id, "warning": "read-after-write empty"}


async def odoo_update_project_basic(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                    project_id: int, changes: dict) -> dict:
    invalid = [k for k in changes if k not in PROJECT_WRITABLE_FIELDS]
    if invalid:
        raise PermissionError(f"fields_not_writable:{invalid}")
    _ensure(policy, actor, "odoo_update_project_basic", "write", fields=list(changes.keys()))
    await odoo.write(actor, "project.project", [project_id], changes)
    after = await odoo.read(actor, "project.project", [project_id], PROJECT_SAFE_FIELDS)
    return after[0] if after else {"id": project_id, "warning": "read-after-write empty"}


async def odoo_project_tasks(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                             project_id: int, limit: int = 100) -> list[dict]:
    decision = policy.allows(actor.policy, "odoo_project_tasks", "project.task", "read")
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)
    # Verificar visibilidad del proyecto
    visible = await odoo.search_read(actor, "project.project", [("id", "=", project_id)],
                                     ["id"], limit=1)
    if not visible:
        raise PermissionError(f"project_not_accessible:{project_id}")
    task_fields = ["id", "name", "stage_id", "user_ids", "date_deadline", "priority", "state"]
    return await odoo.search_read(actor, "project.task", [("project_id", "=", project_id)],
                                  task_fields, limit=limit, order="stage_id asc, priority desc")
