"""Tests ticket 737, hallazgo F2 (QA ronda 1, RECHAZO):
`app/tools/openai_nl_parser.py` hardcodeaba area="Personal" y
task_type="Test" en create_todo, y task_type="Ejecucion" en create_task —
ninguno de los 3 mapea a una etiqueta canonica de config/apl_labels.yaml,
asi que TODA tarea creada por el parser NL nacia con warning y sin esa
etiqueta.

Decision del PM (ronda 2): task_type fijo "Entregable" en ambas acciones;
el departamento de create_todo ya no se inventa, se deriva del ROL del
actor via `app.apl_labels.resolve_department_name_for_role`
(role_department_tag_ids, ADR-017). Rol sin mapeo -> sin departamento +
warning explicito (nunca crea una etiqueta nueva).
"""

from __future__ import annotations

import pytest

from app.apl_labels import resolve_department, resolve_task_type
from app.apl_validation import parse_and_validate_apl_task_input
from app.token_registry import ActorEntry, TokenRegistry
from app.tools.openai_nl_parser import try_parse


def _actor_with_role(role: str) -> ActorEntry:
    """Actor sintetico para probar un rol que no existe en actors.yaml
    (caso 'rol desconocido'), sin pasar por TokenRegistry."""
    return ActorEntry(
        actor="fantasma",
        role=role,
        display_name="Actor Fantasma",
        odoo_url_env="ODOO_URL",
        odoo_db_env="ODOO_DB",
        odoo_username_env="ODOO_USERNAME_FANTASMA",
        odoo_api_key_env="ODOO_API_KEY_FANTASMA",
        policy="operations_policy",
        enabled=True,
    )


# ---------------------------------------------------------------------------
# create_todo: task_type ya no es "Test" (no mapeaba)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_todo_task_type_es_entregable(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    actor = reg.verify(token_willy)  # role=owner

    result = await try_parse("crea un todo 'Revisar backups semanales'", actor, odoo=None, policy=None)
    assert result is not None
    assert result["action"] == "create_todo"
    assert result["task_type"] == "Entregable"
    assert result["task_type"] != "Test"

    # Y de verdad mapea (a diferencia de "Test", que siempre daba warning).
    tag_id, warning = resolve_task_type(result["task_type"])
    assert tag_id == 12
    assert warning is None


# ---------------------------------------------------------------------------
# create_todo: area por rol del actor, ya no "Personal"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_todo_area_por_rol_owner_es_gerencia(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    actor = reg.verify(token_willy)  # role=owner
    assert actor.role == "owner"

    result = await try_parse("crea un pendiente 'Consolidar reporte contable mensual'", actor, odoo=None, policy=None)
    assert result["area"] == "Gerencia"
    assert result["area"] != "Personal"

    tag_id, warning = resolve_department(result["area"])
    assert tag_id == 20
    assert warning is None


@pytest.mark.asyncio
async def test_create_todo_area_por_rol_operations_es_operaciones(
    actors_yaml, policies_yaml, env_actors, token_yuniesky,
):
    reg = TokenRegistry(actors_yaml)
    actor = reg.verify(token_yuniesky)  # role=operations
    assert actor.role == "operations"

    result = await try_parse("agrega un recordatorio 'Revisar stock'", actor, odoo=None, policy=None)
    assert result["area"] == "Operaciones"

    tag_id, warning = resolve_department(result["area"])
    assert tag_id == 14
    assert warning is None


@pytest.mark.asyncio
async def test_create_todo_area_por_rol_medical_direction(
    actors_yaml, policies_yaml, env_actors, token_anet,
):
    reg = TokenRegistry(actors_yaml)
    actor = reg.verify(token_anet)  # role=medical_direction
    assert actor.role == "medical_direction"

    result = await try_parse("crea un todo 'Validar protocolo clinico'", actor, odoo=None, policy=None)
    assert result["area"] == "Staff Profesionales Salud"

    tag_id, warning = resolve_department(result["area"])
    assert tag_id == 8
    assert warning is None


@pytest.mark.asyncio
async def test_create_todo_rol_desconocido_sin_departamento_y_warning():
    """Rol que no existe en role_department_tag_ids: NO se inventa un
    departamento. El parser pasa el rol crudo como area para que
    resolve_department (dentro de parse_and_validate_apl_task_input)
    genere un warning explicito con el nombre del rol — nunca silencioso."""
    actor = _actor_with_role("rol_que_no_existe")

    result = await try_parse("crea un todo 'Tarea de prueba'", actor, odoo=None, policy=None)
    assert result["area"] == "rol_que_no_existe"

    tag_id, warning = resolve_department(result["area"])
    assert tag_id is None
    assert warning is not None
    assert "rol_que_no_existe" in warning

    # End-to-end: parse_and_validate_apl_task_input debe reflejar el mismo
    # warning y NO abortar la creacion (sigue siendo un warning, no un error).
    parsed = parse_and_validate_apl_task_input({
        "title": result["title"],
        "description": result["description"],
        "deadline": result["deadline"],
        "priority": result["priority"],
        "area": result["area"],
        "task_type": result["task_type"],
    })
    assert any("rol_que_no_existe" in w for w in parsed.warnings)


# ---------------------------------------------------------------------------
# create_task: task_type ya no es "Ejecucion" (no mapeaba)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_task_type_es_entregable(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    actor = reg.verify(token_willy)

    result = await try_parse(
        "crea una tarea 'Migrar dominio' en proyecto 7", actor, odoo=None, policy=None,
    )
    assert result is not None
    assert result["action"] == "create_task"
    assert result["task_type"] == "Entregable"
    assert result["task_type"] != "Ejecucion"

    tag_id, warning = resolve_task_type(result["task_type"])
    assert tag_id == 12
    assert warning is None

    # area de create_task no cambio de diseno (ya mapeaba bien) — sigue
    # "Operaciones", solo se corrigio el task_type.
    assert result["area"] == "Operaciones"
