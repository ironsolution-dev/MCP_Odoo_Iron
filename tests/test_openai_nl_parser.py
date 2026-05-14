"""Tests del parser de lenguaje natural (Fase 4 — server-side NL writes).

Verifica que las heuristicas regex extraen action+campos correctamente
de queries naturales en español que ChatGPT chat-mode envia.
"""

from __future__ import annotations

import pytest

from app.tools import openai_nl_parser as nl


class FakeOdoo:
    """Mock minimo: solo necesitamos search_read para resolver project name->id."""

    def __init__(self, projects: list[dict] | None = None):
        self.projects = projects or []

    async def search_read(self, actor, model, domain, fields, limit=50,
                          offset=0, order=None):
        if model != "project.project":
            return []
        # filtra por name ilike si aparece en domain
        for d in domain:
            if d[0] == "name" and d[1] == "ilike":
                needle = d[2].lower()
                return [p for p in self.projects if needle in p["name"].lower()][:limit]
        return self.projects[:limit]


@pytest.fixture
def actor_stub():
    class A:
        actor = "yuniesky"
    return A()


@pytest.fixture
def policy_stub():
    return None  # parser no usa policy directamente


@pytest.fixture
def odoo_stub():
    return FakeOdoo(projects=[
        {"id": 3, "name": "Gerente de Operaciones"},
        {"id": 7, "name": "Mia Salud Comercial"},
    ])


# ---------------------------------------------------------------------------
# WHOAMI
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_whoami_quien_soy(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse("quien soy?", actor_stub, odoo_stub, policy_stub)
    assert p == {"action": "whoami"}


@pytest.mark.asyncio
async def test_whoami_mis_datos(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse("dame mis datos por favor", actor_stub, odoo_stub, policy_stub)
    assert p["action"] == "whoami"


# ---------------------------------------------------------------------------
# CLOSE TASK
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_task_full(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        "cierra tarea 128 con evidencia: termine el QA y validacion completa",
        actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "close_task"
    assert p["id"] == "task:128"
    assert "termine el QA" in p["evidence"]
    assert p["done_stage_id"] == 1


@pytest.mark.asyncio
async def test_close_task_alt_verb(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        "finaliza task:42 evidencia revisado por daniel y aprobado",
        actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "close_task"
    assert p["id"] == "task:42"


@pytest.mark.asyncio
async def test_close_task_evidence_with_dots_preserved(actor_stub, odoo_stub, policy_stub):
    """Bug fix v0.3.5: evidencia con puntos internos (versiones, URLs, etc.)
    no debe truncarse en el primer punto literal.

    Verificado en QA 13-may-2026: evidencia con "v0.3.4" se cortaba a
    "Auditoria final v0" (18 chars), fallando validacion de minimo 20 chars.
    """
    p = await nl.try_parse(
        "cierra tarea 150 con evidencia: Auditoria final v0.3.4 ejecutada "
        "con exito. Conector ChatGPT Willy operativo end-to-end. Partners "
        "fix verificado. Cierre 13-may-2026.",
        actor_stub, odoo_stub, policy_stub,
    )
    assert p is not None, "parser debe extraer evidencia con puntos internos"
    assert p["action"] == "close_task"
    assert p["id"] == "task:150"
    # La evidencia debe contener al menos 'v0.3.4' (que tiene un punto)
    assert "v0.3.4" in p["evidence"], f"evidencia truncada: {p['evidence']!r}"
    assert len(p["evidence"]) >= 50, (
        f"evidencia demasiado corta ({len(p['evidence'])} chars): {p['evidence']!r}"
    )


@pytest.mark.asyncio
async def test_cancel_task_reason_with_dots_preserved(actor_stub, odoo_stub, policy_stub):
    """Mismo bug fix v0.3.5 aplicado a motivo de cancelacion."""
    p = await nl.try_parse(
        "cancela tarea 99 motivo: cliente cambio de plan v2.0 y ya no aplica al alcance original",
        actor_stub, odoo_stub, policy_stub,
    )
    assert p is not None
    assert p["action"] == "cancel_task"
    assert "v2.0" in p["reason"]
    assert "alcance original" in p["reason"]


@pytest.mark.asyncio
async def test_close_task_missing_evidence_returns_none(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse("cierra tarea 128", actor_stub, odoo_stub, policy_stub)
    assert p is None  # ambiguo -> help


# ---------------------------------------------------------------------------
# CANCEL TASK
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_task(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        "cancela tarea 99 motivo: ya no aplica al cliente",
        actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "cancel_task"
    assert p["id"] == "task:99"
    assert "ya no aplica" in p["reason"]


# ---------------------------------------------------------------------------
# MOVE TASK
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_task(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        "mueve tarea 50 a etapa 7", actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "move_task"
    assert p["id"] == "task:50"
    assert p["stage_id"] == 7


# ---------------------------------------------------------------------------
# UPDATE TASK (prioridad)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_priority_alta(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        "actualiza tarea 88 prioridad alta", actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "update_task"
    assert p["id"] == "task:88"
    assert p["changes"]["priority"] == "2"


@pytest.mark.asyncio
async def test_update_priority_p2(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        "modifica task:88 priority p2", actor_stub, odoo_stub, policy_stub,
    )
    assert p["changes"]["priority"] == "1"


# ---------------------------------------------------------------------------
# CREATE PROJECT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_project_quoted(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        'crea proyecto "Lanzamiento Q3"', actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "create_project"
    assert p["name"] == "Lanzamiento Q3"


# ---------------------------------------------------------------------------
# CREATE TODO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_todo_quoted(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        'crea todo "Llamar a Daniel mañana"', actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "create_todo"
    assert "Llamar a Daniel mañana" in p["title"]
    assert p["title"].startswith("[APL 2.0][P2][Personal][Test]")
    # description debe incluir los 8 campos APL 2.0
    for k in ("Objetivo:", "Entregable:", "Responsable:", "Fecha limite:",
              "Criterio de cierre:", "Evidencia requerida:",
              "Riesgo si no se cierra:", "Siguiente accion:"):
        assert k in p["description"]


@pytest.mark.asyncio
async def test_create_todo_with_deadline(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        'crea pendiente "Revisar reporte" deadline: 2026-06-30',
        actor_stub, odoo_stub, policy_stub,
    )
    assert p["deadline"] == "2026-06-30"


# ---------------------------------------------------------------------------
# CREATE TASK (proyecto)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_project_numeric(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse(
        'crea tarea "Smoke test backend" en proyecto 3',
        actor_stub, odoo_stub, policy_stub,
    )
    assert p["action"] == "create_task"
    assert p["project_id"] == 3
    assert "Smoke test backend" in p["title"]
    assert p["title"].startswith("[APL 2.0][P2][Operaciones][Ejecucion]")


@pytest.mark.asyncio
async def test_create_task_project_by_name(actor_stub, odoo_stub, policy_stub):
    """Resuelve project name -> id via odoo.search_read."""
    p = await nl.try_parse(
        'crea ticket "Validar release" en proyecto Gerente de Operaciones',
        actor_stub, odoo_stub, policy_stub,
    )
    assert p is not None
    assert p["action"] == "create_task"
    assert p["project_id"] == 3
    assert "Validar release" in p["title"]


@pytest.mark.asyncio
async def test_create_task_no_project_returns_none(actor_stub, odoo_stub, policy_stub):
    """Sin project_id no podemos crear -> fall back a help."""
    p = await nl.try_parse(
        'crea tarea "Algo importante"', actor_stub, odoo_stub, policy_stub,
    )
    assert p is None


# ---------------------------------------------------------------------------
# Builders (unit puros)
# ---------------------------------------------------------------------------

def test_build_apl_title_wraps_if_not_compliant():
    out = nl._build_apl_title("smoke test")
    assert out.startswith("[APL 2.0][P2][Operaciones][Ejecucion]")
    assert "smoke test" in out


def test_build_apl_title_keeps_compliant():
    src = "[APL 2.0][P1][TI][Despliegue] Subir hotfix v0.3.3"
    assert nl._build_apl_title(src) == src


def test_build_apl_description_contains_all_fields():
    d = nl._build_apl_description("crear backup", "2026-05-20")
    for k in ("Objetivo", "Entregable", "Responsable", "Fecha limite",
              "Criterio de cierre", "Evidencia requerida",
              "Riesgo si no se cierra", "Siguiente accion"):
        assert k in d
    assert "2026-05-20" in d


# ---------------------------------------------------------------------------
# Queries que NO deben matchear (ambiguos / lectura pura)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pure_read_returns_none(actor_stub, odoo_stub, policy_stub):
    """search('mis tareas') no debe activar parser de escritura."""
    p = await nl.try_parse("mis tareas pendientes", actor_stub, odoo_stub, policy_stub)
    assert p is None


@pytest.mark.asyncio
async def test_empty_query_returns_none(actor_stub, odoo_stub, policy_stub):
    p = await nl.try_parse("", actor_stub, odoo_stub, policy_stub)
    assert p is None
