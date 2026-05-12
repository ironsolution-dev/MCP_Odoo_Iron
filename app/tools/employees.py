"""Tools read-only para hr.employee con allowlist estricta (sec 8.3)."""

from __future__ import annotations

from typing import Optional

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry


EMPLOYEE_SAFE_FIELDS: list[str] = [
    "id", "name", "work_email", "work_phone", "mobile_phone",
    "department_id", "job_id", "parent_id", "user_id", "active",
]


def _ensure(policy: PolicyEngine, actor: ActorEntry, tool: str) -> None:
    decision = policy.allows(actor.policy, tool, "hr.employee", "read",
                             fields=EMPLOYEE_SAFE_FIELDS)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


async def odoo_list_employees(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                              department_id: Optional[int] = None,
                              limit: int = 50, offset: int = 0) -> list[dict]:
    _ensure(policy, actor, "odoo_list_employees")
    domain: list = [("active", "=", True)]
    if department_id:
        domain.append(("department_id", "=", department_id))
    return await odoo.search_read(actor, "hr.employee", domain, EMPLOYEE_SAFE_FIELDS,
                                  limit=limit, offset=offset, order="name asc")


async def odoo_get_employee(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                            employee_id: int) -> Optional[dict]:
    _ensure(policy, actor, "odoo_get_employee")
    result = await odoo.read(actor, "hr.employee", [employee_id], EMPLOYEE_SAFE_FIELDS)
    return result[0] if result else None


async def odoo_search_employee(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                               query: str, limit: int = 20) -> list[dict]:
    _ensure(policy, actor, "odoo_search_employee")
    if not query or not query.strip():
        return []
    q = query.strip()
    domain = ["|", ("name", "ilike", q), ("work_email", "ilike", q)]
    return await odoo.search_read(actor, "hr.employee", domain, EMPLOYEE_SAFE_FIELDS,
                                  limit=limit, order="name asc")
