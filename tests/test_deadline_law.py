"""Tests R-08 (SPEC-127, ley de fechas 15-nov-2026): el conector no mueve un
date_deadline que ya existe. T-R08-01..14."""

from __future__ import annotations

import pytest
import yaml

from app.policy_engine import PolicyEngine
from app.schemas import (
    DEADLINE_LAW_POINTER, DeadlineLockedError, ValidationError, ensure_deadline_not_moved,
)
from app.token_registry import TokenRegistry
from app.tools import openai_write_ops
from app.tools.openai_write_dispatch import _execute_action, _help_write_response
from app.tools.tasks import odoo_update_task_apl

POINTER = "usa ley_fechas.py o la herramienta de reprogramar con nota"
CON_FECHA = "2026-11-20 00:00:00"


class FakeOdoo:
    def __init__(self, deadline=False, accessible=True):
        self.calls: list[tuple] = []
        self._deadline = deadline
        self._accessible = accessible

    async def authenticate(self, actor):
        return 42

    async def write(self, actor, model, ids, values):
        self.calls.append(("write", model, tuple(ids), values))
        return True

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, tuple(ids), list(fields)))
        if not self._accessible:
            return []
        return [{"id": ids[0], "name": "stub", "date_deadline": self._deadline}]


@pytest.fixture
def ctx(actors_yaml, policies_yaml, env_actors, token_willy):
    return TokenRegistry(actors_yaml).verify(token_willy), PolicyEngine(policies_yaml)


def _writes(odoo):
    return [c for c in odoo.calls if c[0] == "write"]


@pytest.mark.asyncio
async def test_t01_date_deadline_con_fecha_previa_se_rechaza(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    with pytest.raises(DeadlineLockedError) as exc:
        await odoo_update_task_apl(actor, odoo, pe, 1, {"date_deadline": "2026-11-27"})
    assert str(exc.value).startswith("deadline_locked:task:1:")
    assert POINTER in str(exc.value)
    assert _writes(odoo) == []


@pytest.mark.asyncio
async def test_t02_alias_deadline_tambien(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    with pytest.raises(DeadlineLockedError) as exc:
        await odoo_update_task_apl(actor, odoo, pe, 1, {"deadline": "2026-11-27"})
    assert str(exc.value).startswith("deadline_locked:task:1:")
    assert _writes(odoo) == []


@pytest.mark.asyncio
async def test_t03_misma_fecha_tambien_se_rechaza(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    with pytest.raises(DeadlineLockedError):
        await odoo_update_task_apl(actor, odoo, pe, 1, {"deadline": "2026-11-20"})
    assert _writes(odoo) == []


@pytest.mark.asyncio
async def test_t04_todo_o_nada_con_otros_campos(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    with pytest.raises(DeadlineLockedError):
        await odoo_update_task_apl(
            actor, odoo, pe, 1,
            {"name": "Nuevo", "priority": "1", "deadline": "2026-11-27"})
    assert _writes(odoo) == []


@pytest.mark.asyncio
async def test_t05_sin_fecha_primera_fecha_se_escribe(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=False)
    await odoo_update_task_apl(actor, odoo, pe, 1, {"deadline": "2026-11-27"})
    assert _writes(odoo) == [("write", "project.task", (1,), {"date_deadline": "2026-11-27"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("vacio", [None, ""])
async def test_t05b_sin_fecha_none_y_vacio(ctx, vacio):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=vacio)
    await odoo_update_task_apl(actor, odoo, pe, 1, {"deadline": "2026-11-27"})
    assert _writes(odoo) == [("write", "project.task", (1,), {"date_deadline": "2026-11-27"})]


@pytest.mark.asyncio
async def test_t06_otros_campos_sin_lectura_previa(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    await odoo_update_task_apl(actor, odoo, pe, 1, {"name": "Nuevo", "priority": "1"})
    assert [c[0] for c in odoo.calls] == ["write", "read"]
    assert _writes(odoo) == [("write", "project.task", (1,), {"name": "Nuevo", "priority": "1"})]


@pytest.mark.asyncio
async def test_t07_tarea_inaccesible_falla_cerrado(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(accessible=False)
    with pytest.raises(PermissionError) as exc:
        await odoo_update_task_apl(actor, odoo, pe, 1, {"deadline": "2026-11-27"})
    assert "task_not_accessible:1" in str(exc.value)
    assert not isinstance(exc.value, DeadlineLockedError)
    assert _writes(odoo) == []


def test_t08_jerarquia_de_la_excepcion():
    assert issubclass(DeadlineLockedError, PermissionError)
    assert not issubclass(DeadlineLockedError, ValueError)


@pytest.mark.asyncio
async def test_t09_update_task_openai_ops_rechaza(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    with pytest.raises(DeadlineLockedError):
        await openai_write_ops.update_task(
            actor, odoo, pe, id="task:1", changes={"deadline": "2026-11-27"})
    assert _writes(odoo) == []


@pytest.mark.asyncio
async def test_t10_search_json_devuelve_error_deadline_locked(ctx):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    out = await _execute_action(
        {"action": "update_task", "id": "task:1", "changes": {"deadline": "2026-11-27"}},
        actor, odoo, pe)
    res = out["results"][0]
    assert res["id"] == "error:deadline_locked"
    assert POINTER in res["text"]
    assert "acceso denegado" not in res["text"]
    assert "tipo invalido" not in res["text"]
    assert _writes(odoo) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"deadline": ""}, {"date_deadline": False}])
async def test_t11_vaciar_sigue_siendo_validation_error(ctx, changes):
    actor, pe = ctx
    odoo = FakeOdoo(deadline=CON_FECHA)
    with pytest.raises(ValidationError):
        await odoo_update_task_apl(actor, odoo, pe, 1, changes)
    assert odoo.calls == []


def test_t12_help_no_ofrece_mover_fecha():
    texto = str(_help_write_response())
    assert '"deadline":"YYYY-MM-DD"}}' not in texto.split("Mover tarea a otra etapa")[0].split(
        "Actualizar campos de tarea")[1]
    assert POINTER in texto


def test_t13_funcion_pura():
    for vacio in (False, None, ""):
        ensure_deadline_not_moved(1, vacio)
    for viva in ("2026-11-20 00:00:00", "2026-11-20"):
        with pytest.raises(DeadlineLockedError):
            ensure_deadline_not_moved(1, viva)
    assert POINTER in DEADLINE_LAW_POINTER


@pytest.mark.asyncio
async def test_t14_politica_denegada_va_antes_de_la_lectura(
        actors_yaml, env_actors, token_willy, tmp_path):
    path = tmp_path / "vacia.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1, "denylist_global": [], "field_allowlists": {},
        "policies": {"owner_policy": {"allowed_tools": [], "model_rules": {}}},
    }), encoding="utf-8")
    actor = TokenRegistry(actors_yaml).verify(token_willy)
    odoo = FakeOdoo(deadline=CON_FECHA)
    with pytest.raises(PermissionError) as exc:
        await odoo_update_task_apl(actor, odoo, PolicyEngine(path), 1, {"deadline": "2026-11-27"})
    assert not isinstance(exc.value, DeadlineLockedError)
    assert odoo.calls == []
