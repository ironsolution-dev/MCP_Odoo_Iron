"""Tests del adapter ChatGPT chat-mode (search + fetch).

Verifica:
- Routing por intent (mis tareas -> my_tasks, proyectos -> list_projects, etc).
- Formato OpenAI-compatible {results: [{id, title, text, url}]}.
- ids con prefijo "<kind>:<num>" parseables por fetch().
- fetch() routea segun kind y maneja kind invalido / id mal formado.
- PermissionError se traduce a payload {error: permission_denied}.
"""

from __future__ import annotations

import pytest

from app.policy_engine import PolicyEngine
from app.token_registry import TokenRegistry
from app.tools.openai_compat import (
    _classify, _parse_id, cancel_task, close_task, create_event,
    create_project, create_task, create_todo, fetch, move_task, search,
    update_task,
)


class FakeOdoo:
    """Mock minimo: mismas firmas que OdooClient, devuelve datos canned."""

    def __init__(self, search_read_returns: dict | None = None,
                 read_returns: dict | None = None,
                 create_returns: int = 999,
                 strict_no_write: bool = False):
        self.calls: list[tuple] = []
        self.search_read_returns = search_read_returns or {}
        self.read_returns = read_returns or {}
        self.create_returns = create_returns
        self.strict_no_write = strict_no_write

    async def authenticate(self, actor):
        return 42

    async def search_read(self, actor, model, domain, fields, limit=50, offset=0, order=None):
        self.calls.append(("search_read", model, domain))
        return self.search_read_returns.get(model, [])

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, ids))
        return self.read_returns.get(model, [{"id": ids[0], "name": f"stub_{model}"}])

    async def create(self, actor, model, values):
        if self.strict_no_write:
            raise AssertionError("read tool no debe crear")
        self.calls.append(("create", model, values))
        return self.create_returns

    async def write(self, actor, model, ids, values):
        if self.strict_no_write:
            raise AssertionError("read tool no debe escribir")
        self.calls.append(("write", model, ids, values))
        return True

    async def call(self, actor, model, method, args, kwargs=None):
        self.calls.append(("call", model, method, args))
        return True


# ---------------------------------------------------------------------------
# _classify (unit test puro, sin actor)
# ---------------------------------------------------------------------------

def test_classify_mis_tareas():
    assert _classify("lista mis tareas") == "tasks_my"
    assert _classify("muestrame las tareas") == "tasks_my"
    assert _classify("que tareas tengo pendientes") == "tasks_my"


def test_classify_overdue_precedence_over_tasks():
    # "tareas vencidas" matchea tanto overdue como tasks_my; overdue gana.
    assert _classify("tareas vencidas") == "tasks_overdue"
    assert _classify("tengo algo atrasado") == "tasks_overdue"


def test_classify_projects():
    assert _classify("lista de proyectos") == "projects"
    assert _classify("mis projects de Odoo") == "projects"


def test_classify_employees():
    assert _classify("muestrame el equipo") == "employees"
    assert _classify("empleados del departamento") == "employees"


def test_classify_partners():
    assert _classify("contactos de la empresa") == "partners"
    assert _classify("buscar cliente") == "partners"


def test_classify_crm():
    assert _classify("leads abiertos en CRM") == "crm_leads"
    assert _classify("oportunidades de venta") == "crm_leads"


def test_classify_calendar():
    assert _classify("eventos de mi calendario") == "calendar_events"
    assert _classify("reuniones esta semana") == "calendar_events"


def test_classify_default_when_no_match():
    assert _classify("hola que tal") == "default"
    assert _classify("") == "default"


# ---------------------------------------------------------------------------
# search() routing end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_mis_tareas_calls_my_tasks(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(search_read_returns={
        "project.task": [{"id": 7, "name": "Tarea X", "description": "lorem",
                          "project_id": False, "date_deadline": "2026-05-20"}],
    })
    actor = reg.verify(token_willy)
    out = await search(actor, odoo, pe, "lista mis tareas")
    assert len(out["results"]) == 1
    assert out["results"][0]["id"] == "task:7"
    assert out["results"][0]["title"] == "Tarea X"


@pytest.mark.asyncio
async def test_search_projects_returns_project_ids(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(search_read_returns={
        "project.project": [{"id": 3, "name": "Mia Salud", "description": "Proyecto X"}],
    })
    actor = reg.verify(token_willy)
    out = await search(actor, odoo, pe, "lista de proyectos")
    assert out["results"][0]["id"] == "project:3"
    assert out["results"][0]["title"] == "Mia Salud"


@pytest.mark.asyncio
async def test_search_default_returns_overview(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(search_read_returns={
        "project.task":    [{"id": 1, "name": "T1", "project_id": False}],
        "project.project": [{"id": 2, "name": "P1"}],
    })
    actor = reg.verify(token_willy)
    out = await search(actor, odoo, pe, "que hay")
    ids = [r["id"] for r in out["results"]]
    assert "task:1" in ids and "project:2" in ids


@pytest.mark.asyncio
async def test_search_returns_openai_format(actors_yaml, policies_yaml, env_actors, token_willy):
    """Cada result debe tener id, title, text, url segun spec OpenAI."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(search_read_returns={
        "project.task": [{"id": 5, "name": "X", "project_id": False}],
    })
    actor = reg.verify(token_willy)
    out = await search(actor, odoo, pe, "mis tareas")
    r = out["results"][0]
    assert set(["id", "title", "text", "url"]).issubset(r.keys())


@pytest.mark.asyncio
async def test_search_permission_error_returns_structured(actors_yaml, policies_yaml, env_actors, token_yuniesky):
    """Yuniesky NO tiene acceso a crm.lead. search('leads') debe devolver error claro."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_yuniesky)
    out = await search(actor, odoo, pe, "leads de CRM")
    # Permission denied ahora se devuelve como un item de error dentro de results
    # (OpenAI spec estricto: solo key `results`). El title indica el problema.
    assert len(out["results"]) == 1
    assert "denegado" in out["results"][0]["title"].lower() or \
           out["results"][0]["id"].startswith("error:")


# ---------------------------------------------------------------------------
# fetch() routing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_task_routes_correctly(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(search_read_returns={
        "project.task": [{"id": 42, "name": "Detalle", "description": "Cuerpo"}],
    })
    actor = reg.verify(token_willy)
    out = await fetch(actor, odoo, pe, "task:42")
    assert out["id"] == "task:42"
    assert out["title"] == "Detalle"
    assert out["text"] == "Cuerpo"
    assert "metadata" in out


@pytest.mark.asyncio
async def test_fetch_invalid_id_format(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    actor = reg.verify(token_willy)
    out = await fetch(actor, FakeOdoo(), pe, "not-a-valid-id")
    assert out["error"] == "invalid_id_format"


@pytest.mark.asyncio
async def test_fetch_invalid_numeric_id(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    actor = reg.verify(token_willy)
    out = await fetch(actor, FakeOdoo(), pe, "task:not-a-number")
    assert out["error"] == "invalid_numeric_id"


@pytest.mark.asyncio
async def test_fetch_unknown_kind(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    actor = reg.verify(token_willy)
    out = await fetch(actor, FakeOdoo(), pe, "alien:99")
    assert out["error"] == "unknown_kind"
    assert "task" in out["supported"]


@pytest.mark.asyncio
async def test_fetch_permission_error_structured(actors_yaml, policies_yaml, env_actors, token_yuniesky):
    """Yuniesky NO tiene acceso a crm.lead — fetch('lead:1') debe devolver error claro."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    actor = reg.verify(token_yuniesky)
    out = await fetch(actor, FakeOdoo(), pe, "lead:1")
    assert out["error"] == "permission_denied"


# ---------------------------------------------------------------------------
# Write tools (Fase 2 — 13-may-2026)
# ---------------------------------------------------------------------------

def test_parse_id_accepts_int():
    assert _parse_id(42, "task") == 42

def test_parse_id_accepts_compound():
    assert _parse_id("task:42", "task") == 42

def test_parse_id_accepts_plain_str():
    assert _parse_id("42", "task") == 42

def test_parse_id_rejects_wrong_kind():
    with pytest.raises(ValueError):
        _parse_id("project:7", "task")


# Payload APL 2.0 minimo valido — title 6+ chars y description con 8 campos.
_VALID_APL_DESC = (
    "Objetivo: validar adapter\n"
    "Entregable: tests verdes\n"
    "Responsable: willy\n"
    "Fecha limite: 2026-05-20\n"
    "Criterio de cierre: 100% tests pass\n"
    "Evidencia requerida: pytest output\n"
    "Riesgo si no se cierra: feature incompleta\n"
    "Siguiente accion: deploy"
)


@pytest.mark.asyncio
async def test_create_task_routes_to_apl_create(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        search_read_returns={"project.project": [{"id": 1}]},  # project visible
        read_returns={"project.task": [{"id": 999, "name": "Tarea X", "description": "desc"}]},
        create_returns=999,
    )
    actor = reg.verify(token_willy)
    out = await create_task(actor, odoo, pe,
                             project_id=1,
                             title="[APL 2.0][P2][Operaciones][Ejecucion] Crear tarea de prueba",
                             description=_VALID_APL_DESC,
                             deadline="2026-05-20",
                             area="Operaciones",
                             task_type="ejecucion")
    assert out["id"] == "task:999"
    ops = [c[0] for c in odoo.calls]
    assert "create" in ops and "read" in ops, "create+read-after-write esperado"


@pytest.mark.asyncio
async def test_create_todo_routes_to_my_todo_apl(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"project.task": [{"id": 555, "name": "Personal", "description": "x"}]},
        create_returns=555,
    )
    actor = reg.verify(token_willy)
    out = await create_todo(actor, odoo, pe, title="[APL 2.0][P2][Personal][Revision] Revisar pendientes",
                             description=_VALID_APL_DESC,
                             deadline="2026-05-20",
                             area="Personal",
                             task_type="revision")
    assert out["id"] == "task:555"


@pytest.mark.asyncio
async def test_update_task_accepts_compound_id(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"project.task": [{"id": 42, "name": "T", "description": "d"}]},
    )
    actor = reg.verify(token_willy)
    out = await update_task(actor, odoo, pe, id="task:42",
                             changes={"name": "Nuevo nombre"})
    assert out["id"] == "task:42"
    ops = [c[0] for c in odoo.calls]
    assert "write" in ops


@pytest.mark.asyncio
async def test_move_task_calls_write_stage(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"project.task": [{"id": 10, "name": "T", "description": "d"}]},
    )
    actor = reg.verify(token_willy)
    out = await move_task(actor, odoo, pe, id=10, stage_id=3)
    assert out["id"] == "task:10"
    # write recibe {stage_id: 3}
    write_calls = [c for c in odoo.calls if c[0] == "write"]
    assert write_calls and write_calls[0][3] == {"stage_id": 3}


@pytest.mark.asyncio
async def test_close_task_requires_evidence_via_chatter(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"project.task": [{"id": 5, "name": "T", "state": "1_done"}]},
    )
    actor = reg.verify(token_willy)
    out = await close_task(actor, odoo, pe, id="task:5",
                            evidence="Entregue PR aprobado y mergeado",
                            done_stage_id=7)
    assert out["closed"] is True
    assert out["evidence_recorded"] is True
    # message_post (chatter) + write
    methods = [c for c in odoo.calls if c[0] == "call"]
    assert any("message_post" in c[2] for c in methods)


@pytest.mark.asyncio
async def test_cancel_task_records_reason(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"project.task": [{"id": 5, "name": "T", "state": "1_canceled"}]},
    )
    actor = reg.verify(token_willy)
    out = await cancel_task(actor, odoo, pe, id="task:5",
                             reason="Cliente cambio prioridad",
                             cancelled_stage_id=8)
    assert out["cancelled"] is True
    assert out["cancel_reason_recorded"] is True


@pytest.mark.asyncio
async def test_create_project_routes_correctly(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"project.project": [{"id": 100, "name": "Nuevo Proy"}]},
        create_returns=100,
    )
    actor = reg.verify(token_willy)
    out = await create_project(actor, odoo, pe, name="Nuevo Proy",
                                description="X", user_id=9)
    assert out["id"] == "project:100"


@pytest.mark.asyncio
async def test_create_event_returns_event_id(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        read_returns={"calendar.event": [{"id": 77, "name": "Reunion", "start": "2026-05-14 10:00:00", "stop": "2026-05-14 11:00:00"}]},
        create_returns=77,
    )
    actor = reg.verify(token_willy)
    out = await create_event(actor, odoo, pe, name="Reunion",
                              start="2026-05-14 10:00:00",
                              stop="2026-05-14 11:00:00")
    assert out["id"] == "event:77"


@pytest.mark.asyncio
async def test_write_tools_blocked_for_operations_policy_on_crm(actors_yaml, policies_yaml, env_actors, token_yuniesky):
    """En el fixture de tests Yuniesky sigue siendo operations_policy.
    Las write tools sobre project.task SI deben funcionar (operations tiene
    create/write en project.task). Este test verifica que el routing va por
    policy correctamente."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(
        search_read_returns={"project.project": [{"id": 1}]},
        read_returns={"project.task": [{"id": 1, "name": "T", "description": "d"}]},
        create_returns=1,
    )
    actor = reg.verify(token_yuniesky)
    out = await create_task(actor, odoo, pe,
                             project_id=1,
                             title="[APL 2.0][P2][Operaciones][Ejecucion] Tarea Operations",
                             description=_VALID_APL_DESC,
                             deadline="2026-05-20",
                             area="Operaciones",
                             task_type="ejecucion")
    assert out["id"] == "task:1"
