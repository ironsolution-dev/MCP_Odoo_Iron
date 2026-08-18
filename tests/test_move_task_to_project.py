"""Tests G1 (Fase A daily driver): odoo_move_task_to_project.

Cubre: exito con chatter [MOVIMIENTO], denegacion por policy (cero writes),
proyecto destino invalido (cero writes), tarea origen inaccesible (cero
writes), y el facade `openai_compat.move_task_to_project` (gap de reexport
detectado por julio-qa en el rechazo de Fase A: el facade solo reexportaba
8 de las 9 funciones de escritura de openai_write_ops.py — la tool MCP
standalone registrada en odoo_mcp_remote.py pasa por este facade y crasheaba
con AttributeError en toda invocacion). project_id permanece BLOQUEADO en
el update generico (sec G2) — esta es la UNICA via para reasignar proyecto.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.policy_engine import PolicyEngine
from app.schemas import TASK_FIELD_SPECS
from app.token_registry import ActorEntry, TokenRegistry
from app.tools import openai_compat
from app.tools.tasks import odoo_move_task_to_project


class FakeOdoo:
    """Doble de OdooClient. Devuelve resultados configurables por modelo."""

    def __init__(self, search_read_returns: dict = None, read_returns: dict = None):
        self.calls: list[tuple] = []
        self.search_read_returns = search_read_returns or {}
        self.read_returns = read_returns or {}
        self._uid = 42

    async def authenticate(self, actor):
        return self._uid

    async def search_read(self, actor, model, domain, fields, limit=50, offset=0, order=None):
        self.calls.append(("search_read", model, domain, list(fields)))
        return self.search_read_returns.get(model, [])

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, tuple(ids), list(fields)))
        return self.read_returns.get(model, [{"id": ids[0]}])

    async def write(self, actor, model, ids, values):
        self.calls.append(("write", model, tuple(ids), values))
        return True

    async def call(self, actor, model, method, args, kwargs=None):
        self.calls.append(("call", model, method, args, kwargs))
        return True


def _write_calls(odoo: FakeOdoo) -> list[tuple]:
    return [c for c in odoo.calls if c[0] in ("write", "call")]


# ---------------------------------------------------------------------------
# Exito
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_task_to_project_success_posts_movimiento_chatter(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={
            "project.task": [{"id": 42, "name": "Migrar reportes",
                               "project_id": {"id": 3, "name": "Operaciones"}}],
        },
        search_read_returns={"project.project": [{"id": 12, "name": "Comercial"}]},
    )
    actor = reg.verify(token_willy)

    result = await odoo_move_task_to_project(actor, odoo, pe, task_id=42, new_project_id=12)

    assert result["moved"] is True
    assert result["from_project"] == "Operaciones"
    assert result["to_project"] == "Comercial"

    chatter_calls = [c for c in odoo.calls if c[0] == "call" and c[2] == "message_post"]
    assert len(chatter_calls) == 1
    body = chatter_calls[0][4]["body"]
    assert "[MOVIMIENTO]" in body
    assert "Operaciones" in body and "Comercial" in body

    # El chatter se posteo ANTES del write (auditoria antes del cambio).
    ops = [c[0] for c in odoo.calls]
    assert ops.index("call") < ops.index("write")

    write_calls = [c for c in odoo.calls if c[0] == "write"]
    assert write_calls == [("write", "project.task", (42,), {"project_id": 12})]


# ---------------------------------------------------------------------------
# Denegacion por policy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_task_to_project_denied_by_policy_zero_writes(tmp_path: Path):
    """Actor cuya policy NO declara la tool -> PermissionError, cero llamadas Odoo."""
    restricted_yaml = {
        "version": 1,
        "denylist_global": [],
        "field_allowlists": {},
        "policies": {
            "restricted_policy": {
                "allowed_tools": ["odoo_who_am_i"],  # sin odoo_move_task_to_project
                "model_rules": {
                    "project.task": {"read": True, "create": False, "write": True, "unlink": False},
                },
                "rate_limit": {"requests_per_minute": 10, "writes_per_minute": 5},
            },
        },
    }
    path = tmp_path / "restricted_policies.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(restricted_yaml, f)
    pe = PolicyEngine(path)

    actor = ActorEntry(
        actor="restricted", role="restricted", display_name="Restringido",
        odoo_url_env="ODOO_URL", odoo_db_env="ODOO_DB",
        odoo_username_env="ODOO_USERNAME_X", odoo_api_key_env="ODOO_API_KEY_X",
        policy="restricted_policy", enabled=True,
    )
    odoo = FakeOdoo()

    with pytest.raises(PermissionError) as exc:
        await odoo_move_task_to_project(actor, odoo, pe, task_id=1, new_project_id=2)
    assert "tool_not_allowed" in str(exc.value)
    assert odoo.calls == []


# ---------------------------------------------------------------------------
# Proyecto destino invalido
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_task_to_project_invalid_target_zero_writes(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"project.task": [{"id": 42, "name": "X", "project_id": False}]},
        search_read_returns={"project.project": []},  # destino no visible/no existe
    )
    actor = reg.verify(token_willy)

    with pytest.raises(PermissionError) as exc:
        await odoo_move_task_to_project(actor, odoo, pe, task_id=42, new_project_id=999)
    assert "project_not_accessible:999" in str(exc.value)
    assert _write_calls(odoo) == []


# ---------------------------------------------------------------------------
# Tarea origen inaccesible (hallazgo menor QA, rechazo Fase A)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_task_to_project_task_not_accessible_zero_writes(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    """read() de la tarea origen devuelve vacio (no existe / sin visibilidad)
    -> PermissionError task_not_accessible, cero writes. El chequeo ocurre
    ANTES de resolver el proyecto destino: search_read de project.project
    tampoco debe dispararse."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(read_returns={"project.task": []})
    actor = reg.verify(token_willy)

    with pytest.raises(PermissionError) as exc:
        await odoo_move_task_to_project(actor, odoo, pe, task_id=999, new_project_id=12)
    assert "task_not_accessible:999" in str(exc.value)
    assert _write_calls(odoo) == []
    assert not any(c[0] == "search_read" for c in odoo.calls)


# ---------------------------------------------------------------------------
# Facade openai_compat — gap de reexport (rechazo Fase A, julio-qa)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_task_to_project_reachable_via_openai_compat_facade(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    """La tool MCP standalone `move_task_to_project` (odoo_mcp_remote.py)
    llama `OC.move_task_to_project`, es decir openai_compat.move_task_to_project.
    Este test invoca ESA ruta exacta (no la tasks.py nativa) para que un
    reexport faltante en el facade rompa aqui, no en produccion via
    AttributeError como reprodujo julio-qa."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={
            "project.task": [{"id": 42, "name": "Migrar reportes",
                               "project_id": {"id": 3, "name": "Operaciones"}}],
        },
        search_read_returns={"project.project": [{"id": 12, "name": "Comercial"}]},
    )
    actor = reg.verify(token_willy)

    result = await openai_compat.move_task_to_project(actor, odoo, pe, id="task:42",
                                                       new_project_id=12)

    assert result["id"] == "task:42"
    assert result["metadata"]["name"] == "Migrar reportes"
    write_calls = [c for c in odoo.calls if c[0] == "write"]
    assert write_calls == [("write", "project.task", (42,), {"project_id": 12})]


# ---------------------------------------------------------------------------
# Contrato: project_id sigue bloqueado en el update generico (sec G2)
# ---------------------------------------------------------------------------

def test_project_id_not_in_generic_task_update_fields():
    assert TASK_FIELD_SPECS["project_id"].kind == "blocked"
    assert "odoo_move_task_to_project" in TASK_FIELD_SPECS["project_id"].blocked_message
