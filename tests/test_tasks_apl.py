"""Tests sec 14.1: APL 2.0 obligatorio, evidencia al cerrar, no generic execute."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.policy_engine import PolicyEngine
from app.schemas import (
    ValidationError,
    validate_apl_task_input,
    validate_evidence,
)
from app.token_registry import TokenRegistry
from app.tools import tasks as tasks_mod
from app.tools.tasks import (
    odoo_cancel_task,
    odoo_create_my_todo_apl,
    odoo_mark_task_done,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Validacion APL 2.0
# ---------------------------------------------------------------------------

def test_create_my_todo_apl_requires_fields():
    """Falta cualquiera de los campos APL 2.0 -> ValidationError."""
    with pytest.raises(ValidationError):
        validate_apl_task_input({})

    payload_missing_priority = {
        "title": "[APL 2.0][P1][Operaciones][Implementacion] Algo",
        "description": "objetivo entregable responsable fecha limite criterio de cierre evidencia requerida riesgo si no se cierra siguiente accion",
        "deadline": "2026-05-13",
        "area": "Operaciones",
        "task_type": "Implementacion",
    }
    with pytest.raises(ValidationError) as exc:
        validate_apl_task_input(payload_missing_priority)
    assert "priority" in str(exc.value)


def test_apl_title_format_strict():
    """Titulos sin formato APL 2.0 -> ValidationError."""
    valid_desc = "objetivo entregable responsable fecha limite criterio de cierre evidencia requerida riesgo si no se cierra siguiente accion"
    base = {
        "description": valid_desc,
        "deadline": "2026-05-13",
        "priority": "P1",
        "area": "Op",
        "task_type": "Implementacion",
    }
    for bad_title in ["sin formato", "[APL 2.0] sin prioridad", "[APL 2.0][P1] sin area",
                      "[P1][Area][Tipo] sin tag APL", ""]:
        with pytest.raises(ValidationError):
            validate_apl_task_input({**base, "title": bad_title})

    good = {**base, "title": "[APL 2.0][P1][Operaciones][Implementacion] Crear endpoint"}
    apl = validate_apl_task_input(good)
    assert apl.priority == "P1"


def test_apl_description_must_have_all_fields():
    title = "[APL 2.0][P1][Op][Implementacion] Algo"
    base = {"title": title, "deadline": "2026-05-13", "priority": "P1",
            "area": "Op", "task_type": "Implementacion"}
    # Descripcion sin "siguiente accion"
    with pytest.raises(ValidationError) as exc:
        validate_apl_task_input({**base,
            "description": "objetivo entregable responsable fecha limite criterio de cierre evidencia requerida riesgo si no se cierra"})
    assert "siguiente accion" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Evidencia al cerrar
# ---------------------------------------------------------------------------

def test_close_task_requires_evidence():
    with pytest.raises(ValidationError):
        validate_evidence("")
    with pytest.raises(ValidationError):
        validate_evidence("   ")
    with pytest.raises(ValidationError):
        validate_evidence("ok")  # demasiado corta
    cleaned = validate_evidence("Endpoint deploy verificado con curl 200 a /health")
    assert "verificado" in cleaned


# ---------------------------------------------------------------------------
# Tools BLUE migradas — aliases mantenidos
# ---------------------------------------------------------------------------

def test_blue_aliases_present():
    assert tasks_mod.odoo_personal_tasks is tasks_mod.odoo_my_tasks
    assert tasks_mod.odoo_personal_tasks_today is tasks_mod.odoo_my_tasks_today
    assert tasks_mod.odoo_personal_tasks_overdue is tasks_mod.odoo_my_tasks_overdue
    assert tasks_mod.odoo_create_personal_task is tasks_mod.odoo_create_my_todo_apl
    assert tasks_mod.odoo_move_personal_task is tasks_mod.odoo_move_task


# ---------------------------------------------------------------------------
# No generic execute / sudo / raw_call
# ---------------------------------------------------------------------------

def test_no_generic_execute_tool():
    """Ninguna tool pblica con nombre execute_kw / execute / raw_call / sudo / admin."""
    forbidden = re.compile(
        r"^\s*async\s+def\s+(odoo_execute|odoo_execute_kw|odoo_raw_call|odoo_sudo|odoo_admin)",
        re.MULTILINE,
    )
    for path in (REPO_ROOT / "app" / "tools").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        m = forbidden.search(text)
        assert m is None, f"Tool generica prohibida en {path}: {m.group(0)}"


def test_no_sudo_or_privilege_escalation_in_odoo_client():
    odoo_client = (REPO_ROOT / "app" / "odoo_client.py").read_text(encoding="utf-8")
    assert ".sudo(" not in odoo_client
    assert "su_id" not in odoo_client


# ---------------------------------------------------------------------------
# Read-after-write y policy ejecuta antes de Odoo
# ---------------------------------------------------------------------------

class FakeOdoo:
    """Doble de OdooClient. Captura llamadas para asserts."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._uid = 42

    async def authenticate(self, actor):  # noqa: D401
        return self._uid

    async def search_read(self, actor, model, domain, fields, limit=50, offset=0, order=None):
        self.calls.append(("search_read", (model, tuple(domain), tuple(fields)),
                           {"limit": limit, "offset": offset, "order": order}))
        if model == "project.project":
            return [{"id": domain[0][2]}]  # proyecto visible por id
        return []

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", (model, tuple(ids), tuple(fields)), {}))
        return [{"id": ids[0], "name": "stub"}]

    async def create(self, actor, model, values):
        self.calls.append(("create", (model,), values))
        return 999

    async def write(self, actor, model, ids, values):
        self.calls.append(("write", (model, tuple(ids)), values))
        return True

    async def call(self, actor, model, method, args, kwargs=None):
        self.calls.append(("call", (model, method), {"args": args, "kwargs": kwargs}))
        return True


@pytest.mark.asyncio
async def test_create_todo_does_read_after_write(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()

    payload = {
        "title": "[APL 2.0][P1][Operaciones][Implementacion] Configurar Traefik GREEN",
        "description": (
            "Objetivo: provisionar mcp-v2.\n"
            "Entregable: subdominio operativo.\n"
            "Responsable: Willy.\n"
            "Fecha limite: 2026-05-12.\n"
            "Criterio de cierre: curl 200.\n"
            "Evidencia requerida: log Traefik + curl.\n"
            "Riesgo si no se cierra: no se puede desplegar GREEN.\n"
            "Siguiente accion: ejecutar deploy_green.sh."
        ),
        "deadline": "2026-05-12",
        "priority": "P1",
        "area": "Operaciones",
        "task_type": "Implementacion",
    }
    actor = reg.verify(token_willy)
    result = await odoo_create_my_todo_apl(actor, odoo, pe, payload)

    ops = [c[0] for c in odoo.calls]
    assert "create" in ops
    assert ops.index("read") > ops.index("create"), "read-after-write violado"
    assert result["id"] == 999


@pytest.mark.asyncio
async def test_mark_task_done_requires_evidence_via_policy(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    with pytest.raises(ValidationError):
        await odoo_mark_task_done(actor, odoo, pe, task_id=1, evidence="", done_stage_id=7)

    # Con evidencia adecuada SI se ejecuta
    result = await odoo_mark_task_done(actor, odoo, pe, task_id=1,
                                       evidence="Curl al endpoint /health retorna 200 con todos los actores",
                                       done_stage_id=7)
    assert result["evidence_recorded"] is True
    # Debe haber registrado en chatter (message_post)
    calls_method = [c[1][1] for c in odoo.calls if c[0] == "call"]
    assert "message_post" in calls_method


@pytest.mark.asyncio
async def test_cancel_task_requires_reason(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    with pytest.raises(ValidationError):
        await odoo_cancel_task(actor, odoo, pe, task_id=1, reason="", cancelled_stage_id=8)
