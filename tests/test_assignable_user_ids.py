"""Tests G3 (Fase A daily driver): user_ids escribible con salvaguarda.

_validate_assignable_user_ids verifica CADA uid contra hr.employee activo
antes de permitir escribir. El policy check de la tool sigue siendo
project.task/write — nunca se toca res.users. No se modifica
test_policy_engine.py.
"""

from __future__ import annotations

import pytest

from app.policy_engine import PolicyEngine
from app.schemas import ValidationError
from app.token_registry import TokenRegistry
from app.tools.task_assignment import _validate_assignable_user_ids
from app.tools.tasks import odoo_update_task_apl


class FakeOdoo:
    def __init__(self, employees: list[dict] = None):
        self.calls: list[tuple] = []
        self._employees = employees or []
        self._uid = 42

    async def authenticate(self, actor):
        return self._uid

    async def search_read(self, actor, model, domain, fields, limit=50, offset=0, order=None):
        self.calls.append(("search_read", model, domain, list(fields)))
        if model == "hr.employee":
            return self._employees
        return []

    async def write(self, actor, model, ids, values):
        self.calls.append(("write", model, tuple(ids), values))
        return True

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, tuple(ids), list(fields)))
        return [{"id": ids[0], "name": "stub"}]


def _emp(emp_id: int, user_id: int, name: str = "Empleado") -> dict:
    """Simula el shape que OdooClient normaliza: many2one -> {id, name}."""
    return {"id": emp_id, "user_id": {"id": user_id, "name": name}}


# ---------------------------------------------------------------------------
# _validate_assignable_user_ids directo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_valid_translates_to_command_6_0():
    odoo = FakeOdoo(employees=[_emp(1, 9), _emp(2, 10)])
    result = await _validate_assignable_user_ids(odoo, actor=None, uids=[9, 10])
    assert result == [(6, 0, [9, 10])]


@pytest.mark.asyncio
async def test_invalid_uid_lists_all_invalid_not_just_first():
    # 9 es empleado activo; 10 y 11 NO mapean a ningun hr.employee activo.
    odoo = FakeOdoo(employees=[_emp(1, 9)])
    with pytest.raises(ValidationError) as exc:
        await _validate_assignable_user_ids(odoo, actor=None, uids=[9, 10, 11])
    msg = str(exc.value)
    assert "10" in msg
    assert "11" in msg
    assert "9" not in msg.split(":")[0]  # 9 no deberia aparecer como invalido


@pytest.mark.asyncio
async def test_empty_uids_returns_empty_command():
    odoo = FakeOdoo()
    result = await _validate_assignable_user_ids(odoo, actor=None, uids=[])
    assert result == [(6, 0, [])]
    # No debio consultar hr.employee para una lista vacia.
    assert odoo.calls == []


@pytest.mark.asyncio
async def test_validate_assignable_user_ids_never_touches_res_users():
    odoo = FakeOdoo(employees=[_emp(1, 9)])
    await _validate_assignable_user_ids(odoo, actor=None, uids=[9])
    models_queried = {c[1] for c in odoo.calls}
    assert "res.users" not in models_queried
    assert models_queried == {"hr.employee"}


# ---------------------------------------------------------------------------
# Integracion via odoo_update_task_apl
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_task_apl_writes_valid_user_ids(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(employees=[_emp(1, 9)])
    actor = reg.verify(token_willy)

    await odoo_update_task_apl(actor, odoo, pe, task_id=1, changes={"user_ids": [9]})

    write_calls = [c for c in odoo.calls if c[0] == "write"]
    assert write_calls == [("write", "project.task", (1,), {"user_ids": [(6, 0, [9])]})]


@pytest.mark.asyncio
async def test_update_task_apl_rejects_invalid_user_ids_zero_write(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(employees=[])  # ningun uid mapea a empleado activo
    actor = reg.verify(token_willy)

    with pytest.raises(ValidationError) as exc:
        await odoo_update_task_apl(actor, odoo, pe, task_id=1, changes={"user_ids": [9, 10]})
    msg = str(exc.value)
    assert "9" in msg and "10" in msg

    write_calls = [c for c in odoo.calls if c[0] == "write"]
    assert write_calls == []


# ---------------------------------------------------------------------------
# Denegacion por policy sigue evaluando project.task/write, no res.users
# (no se modifica test_policy_engine.py; esto solo confirma el contrato
# desde el lado de tasks.py)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_task_apl_policy_denial_checks_project_task_not_res_users(
    actors_yaml, policies_yaml, env_actors, token_yuniesky,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(employees=[_emp(1, 9)])
    actor = reg.verify(token_yuniesky)

    decision = pe.allows(actor.policy, "odoo_update_task_apl", "project.task", "write")
    assert decision.allowed  # operations_policy si puede escribir project.task

    # La salvaguarda de user_ids nunca pasa por res.users.
    await odoo_update_task_apl(actor, odoo, pe, task_id=1, changes={"user_ids": [9]})
    models_queried = {c[1] for c in odoo.calls}
    assert "res.users" not in models_queried
