"""Tests sec 14.1: APL 2.0 obligatorio, evidencia al cerrar, no generic execute.

Ticket 737 cambia el contrato de `validate_apl_task_input` (retirado) por
`parse_and_validate_apl_task_input` (app/schemas.py): el titulo ahora acepta
formato legado Y nuevo (ADR-016, ya no rechaza texto sin corchetes), y el
resultado trae tag_ids/priority_star/warnings en vez de solo validar. Los
tests de esta seccion se actualizan para probar el contrato nuevo; el
formato dual en si se cubre a fondo en test_apl_title_normalization.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.policy_engine import PolicyEngine
from app.schemas import (
    ValidationError,
    parse_and_validate_apl_task_input,
    validate_apl_description,
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

VALID_APL_DESCRIPTION = (
    "objetivo entregable responsable fecha limite criterio de cierre "
    "evidencia requerida riesgo si no se cierra siguiente accion"
)


# ---------------------------------------------------------------------------
# Validacion APL 2.0
# ---------------------------------------------------------------------------

def test_create_my_todo_apl_requires_fields():
    """Falta cualquiera de los campos APL 2.0 -> ValidationError."""
    with pytest.raises(ValidationError):
        parse_and_validate_apl_task_input({})

    payload_missing_priority = {
        "title": "[APL 2.0][P1][Operaciones][Implementacion] Algo",
        "description": VALID_APL_DESCRIPTION,
        "deadline": "2026-05-13",
        "area": "Operaciones",
        "task_type": "Implementacion",
    }
    with pytest.raises(ValidationError) as exc:
        parse_and_validate_apl_task_input(payload_missing_priority)
    assert "priority" in str(exc.value)


def test_apl_title_dual_format_ticket_737():
    """Contrato nuevo (ticket 737, ADR-016): titulo SIN corchetes es valido
    (antes se rechazaba); titulo que empieza con '[' pero no matchea el
    patron legado completo sigue rechazado (sin regresion)."""
    base = {
        "description": VALID_APL_DESCRIPTION,
        "deadline": "2026-05-13",
        "priority": "P1",
        "area": "Operaciones",
        "task_type": "Entregable",
    }

    # Antes rechazado, ahora VALIDO: formato nuevo, verbo libre (ADR-016).
    nuevo = parse_and_validate_apl_task_input({**base, "title": "Revisar contrato de proveedor"})
    assert nuevo.title == "Revisar contrato de proveedor"
    assert nuevo.priority == "P1"
    assert not nuevo.warnings

    # Sigue rechazado: vacio, o corchetes mal formados (legado roto).
    for bad_title in ["[APL 2.0] sin prioridad", "[APL 2.0][P1] sin area",
                       "[P1][Area][Tipo] sin tag APL", ""]:
        with pytest.raises(ValidationError):
            parse_and_validate_apl_task_input({**base, "title": bad_title})

    # Legado completo sigue aceptado, normalizado, con warning.
    legado = parse_and_validate_apl_task_input(
        {**base, "title": "[APL 2.0][P1][Operaciones][Entregable] Crear endpoint"})
    assert legado.title == "Crear endpoint"
    assert legado.priority == "P1"
    assert legado.warnings  # aviso de formato antiguo normalizado


def test_apl_description_must_have_all_fields():
    """validate_apl_description (sin cambio de logica en el ticket 737):
    sigue exigiendo los 8 campos por subcadena, con o sin emoji."""
    with pytest.raises(ValidationError) as exc:
        validate_apl_description(
            "objetivo entregable responsable fecha limite criterio de "
            "cierre evidencia requerida riesgo si no se cierra"
        )
    assert "siguiente accion" in str(exc.value).lower()

    # Con emoji tambien pasa (mismo chequeo de subcadena, insensible a decoracion).
    validate_apl_description(
        "🎯 Objetivo: x\n📦 Entregable: x\n👤 Responsable: x\n"
        "📅 Fecha limite: x\n✅ Criterio de cierre: x\n"
        "📎 Evidencia requerida: x\n⚠️ Riesgo si no se cierra: x\n"
        "▶️ Siguiente accion: x"
    )


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


# ---------------------------------------------------------------------------
# Ticket 737 — criterios de aceptacion end-to-end (titulo legado -> tag_ids,
# estrellas P0 != P1, area sin mapeo no crea etiqueta)
# ---------------------------------------------------------------------------

def _create_values(odoo: "FakeOdoo") -> dict:
    """Extrae el dict `values` del primer create() sobre project.task."""
    for op, args, values in odoo.calls:
        if op == "create" and args[0] == "project.task":
            return values
    raise AssertionError("no hubo create() sobre project.task")


@pytest.mark.asyncio
async def test_legacy_title_normalizado_resuelve_tag_ids_reales(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    """Criterio de aceptacion 1 del diseno: titulo legado
    [APL 2.0][P0][RRHH][Documentacion] -> name sin corchetes,
    tag_ids = {1, 10, 25} (P0, RR.HH, Documentacion), priority '3',
    warning de formato antiguo normalizado."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    payload = {
        "title": "[APL 2.0][P0][RRHH][Documentacion] Emitir memorandum",
        "description": VALID_APL_DESCRIPTION,
        "deadline": "2026-09-01",
        "priority": "P0",
        "area": "RRHH",
        "task_type": "Documentacion",
    }
    result = await odoo_create_my_todo_apl(actor, odoo, pe, payload)

    values = _create_values(odoo)
    assert values["name"] == "Emitir memorandum"
    assert values["priority"] == "3"
    assert set(values["tag_ids"][0][2]) == {1, 10, 25}
    assert result["warnings"]
    assert any("normalizado" in w.lower() for w in result["warnings"])


@pytest.mark.asyncio
async def test_estrellas_p0_y_p1_distintas_en_creacion(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    """Criterio de aceptacion 5: P0 -> '3' y P1 -> '2' por separado (antes
    ambas quedaban en '2', bug 1 del diseno)."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    actor = reg.verify(token_willy)

    base = {
        "description": VALID_APL_DESCRIPTION,
        "deadline": "2026-09-01",
        "area": "Tecnologia",
        "task_type": "Entregable",
    }

    odoo_p0 = FakeOdoo()
    await odoo_create_my_todo_apl(
        actor, odoo_p0, pe, {**base, "title": "Resolver incidente critico", "priority": "P0"})
    assert _create_values(odoo_p0)["priority"] == "3"

    odoo_p1 = FakeOdoo()
    await odoo_create_my_todo_apl(
        actor, odoo_p1, pe, {**base, "title": "Resolver incidente de la semana", "priority": "P1"})
    assert _create_values(odoo_p1)["priority"] == "2"


@pytest.mark.asyncio
async def test_area_sin_mapeo_no_crea_etiqueta_y_avisa(
    actors_yaml, policies_yaml, env_actors, token_willy,
):
    """Criterio de aceptacion 4: area que no mapea -> se crea la tarea SIN
    ese tag, con warning literal, y CERO create() sobre project.tags
    (espia todas las llamadas de FakeOdoo)."""
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    payload = {
        "title": "Coordinar con area fantasma",
        "description": VALID_APL_DESCRIPTION,
        "deadline": "2026-09-01",
        "priority": "P2",
        "area": "Departamento Que No Existe",
        "task_type": "Entregable",
    }
    result = await odoo_create_my_todo_apl(actor, odoo, pe, payload)

    values = _create_values(odoo)
    # Solo prioridad (3) + tipo (12) resolvieron; el departamento fantasma no.
    assert set(values["tag_ids"][0][2]) == {3, 12}
    assert any("Departamento Que No Existe" in w for w in result["warnings"])
    assert not any(op == "create" and args[0] == "project.tags" for op, args, _ in odoo.calls)
