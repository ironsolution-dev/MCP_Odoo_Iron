"""Tests G2 (Fase A daily driver): contrato de escritura de odoo_update_task_apl.

Fuente unica: app.schemas.TASK_FIELD_SPECS / TASK_FIELD_ALIASES. Cubre:
alias deadline->date_deadline, agregacion de multiples problemas en UN
ValidationError, project_id bloqueado con puntero a odoo_move_task_to_project,
y rechazo de deadline+date_deadline juntos.
"""

from __future__ import annotations

import pytest

from app.policy_engine import PolicyEngine
from app.schemas import ValidationError, validate_task_write_payload
from app.token_registry import TokenRegistry
from app.tools.tasks import odoo_update_task_apl


class FakeOdoo:
    def __init__(self):
        self.calls: list[tuple] = []
        self._uid = 42

    async def authenticate(self, actor):
        return self._uid

    async def write(self, actor, model, ids, values):
        self.calls.append(("write", model, tuple(ids), values))
        return True

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, tuple(ids), list(fields)))
        return [{"id": ids[0], "name": "stub"}]


# ---------------------------------------------------------------------------
# Alias deadline -> date_deadline
# ---------------------------------------------------------------------------

def test_alias_deadline_normalizes_to_date_deadline():
    normalized = validate_task_write_payload({"deadline": "2026-09-01"})
    assert normalized == {"date_deadline": "2026-09-01"}
    assert "deadline" not in normalized


@pytest.mark.asyncio
async def test_update_task_apl_writes_date_deadline_via_alias(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    await odoo_update_task_apl(actor, odoo, pe, task_id=1, changes={"deadline": "2026-09-01"})

    write_calls = [c for c in odoo.calls if c[0] == "write"]
    assert write_calls == [("write", "project.task", (1,), {"date_deadline": "2026-09-01"})]


# ---------------------------------------------------------------------------
# Doble clave: deadline + date_deadline a la vez -> rechazado
# ---------------------------------------------------------------------------

def test_deadline_and_date_deadline_together_rejected():
    with pytest.raises(ValidationError) as exc:
        validate_task_write_payload({"deadline": "2026-09-01", "date_deadline": "2026-09-02"})
    assert "use only one" in str(exc.value)


# ---------------------------------------------------------------------------
# project_id bloqueado, apunta a odoo_move_task_to_project
# ---------------------------------------------------------------------------

def test_project_id_blocked_points_to_move_task_to_project():
    with pytest.raises(ValidationError) as exc:
        validate_task_write_payload({"project_id": 12})
    assert "odoo_move_task_to_project" in str(exc.value)


@pytest.mark.asyncio
async def test_update_task_apl_rejects_project_id_zero_writes(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    with pytest.raises(ValidationError) as exc:
        await odoo_update_task_apl(actor, odoo, pe, task_id=1, changes={"project_id": 12})
    assert "odoo_move_task_to_project" in str(exc.value)
    assert odoo.calls == []


# ---------------------------------------------------------------------------
# Multiples problemas -> UN solo ValidationError con todos adentro
# ---------------------------------------------------------------------------

def test_multiple_problems_joined_in_single_validation_error():
    with pytest.raises(ValidationError) as exc:
        validate_task_write_payload({
            "priority": "9",             # invalido: no es 0-3
            "stage_id": "no-es-int",     # invalido: no es int
            "campo_inexistente": "x",    # invalido: no reconocido
        })
    msg = str(exc.value)
    assert "priority" in msg
    assert "stage_id" in msg
    assert "campo_inexistente" in msg
    assert "3 problema" in msg


def test_valid_payload_passes_all_kinds():
    normalized = validate_task_write_payload({
        "name": "Nuevo nombre",
        "description": "Descripcion actualizada",
        "priority": "1",
        "date_deadline": "2026-09-01",
        "stage_id": 7,
        "tag_ids": [1, 2, 3],
        "user_ids": [9],
    })
    assert normalized["priority"] == "1"
    assert normalized["stage_id"] == 7
    assert normalized["tag_ids"] == [1, 2, 3]


def test_empty_changes_rejected():
    with pytest.raises(ValidationError):
        validate_task_write_payload({})
