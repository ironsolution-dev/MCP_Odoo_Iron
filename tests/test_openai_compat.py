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
from app.tools.openai_compat import _classify, fetch, search


class FakeOdoo:
    """Mock minimo: mismas firmas que OdooClient, devuelve datos canned."""

    def __init__(self, search_read_returns: dict | None = None,
                 read_returns: dict | None = None):
        self.calls: list[tuple] = []
        self.search_read_returns = search_read_returns or {}
        self.read_returns = read_returns or {}

    async def authenticate(self, actor):
        return 42

    async def search_read(self, actor, model, domain, fields, limit=50, offset=0, order=None):
        self.calls.append(("search_read", model, domain))
        return self.search_read_returns.get(model, [])

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, ids))
        return self.read_returns.get(model, [{"id": ids[0], "name": f"stub_{model}"}])

    async def create(self, actor, model, values):
        raise AssertionError("search/fetch no debe crear")

    async def write(self, actor, model, ids, values):
        raise AssertionError("search/fetch no debe escribir")

    async def call(self, actor, model, method, args, kwargs=None):
        raise AssertionError("search/fetch no debe llamar metodos arbitrarios")


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
    assert out["intent"] == "tasks_my"
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
    assert out["intent"] == "projects"
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
    assert out["intent"] == "default"
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
    assert out["error"] == "permission_denied"
    assert out["results"] == []


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
