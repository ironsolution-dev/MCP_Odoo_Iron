"""Tests ticket 737: fuente unica de IDs de etiquetas APL 2.0 (ADR-017).

Cubre: resolucion canonica, sinonimos, normalizacion sin acentos/mayusculas,
"no mapea -> None + warning, nunca crea etiqueta", y el candado de contenido
que impide que `project.tags` reciba un `create` en cualquier parte de `app/`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.apl_labels import (
    LABELS,
    load_label_map,
    resolve_department,
    resolve_priority,
    resolve_task_type,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Prioridad: estrellas correctas y P0 != P1 (bug 1 del diseno)
# ---------------------------------------------------------------------------

def test_resolve_priority_star_codes_p0_and_p1_distintos():
    """Bug 1 del diseno: P0 y P1 NO deben compartir estrella."""
    tag_p0, star_p0 = resolve_priority("P0")
    tag_p1, star_p1 = resolve_priority("P1")
    assert star_p0 == "3"
    assert star_p1 == "2"
    assert star_p0 != star_p1
    assert tag_p0 == 1
    assert tag_p1 == 2


@pytest.mark.parametrize("code,expected_tag,expected_star", [
    ("P0", 1, "3"),
    ("P1", 2, "2"),
    ("P2", 3, "1"),
    ("P3", 4, "0"),
])
def test_resolve_priority_todas_las_estrellas(code, expected_tag, expected_star):
    tag_id, star = resolve_priority(code)
    assert tag_id == expected_tag
    assert star == expected_star


# ---------------------------------------------------------------------------
# Departamento: canonico + sinonimos + normalizacion
# ---------------------------------------------------------------------------

def test_resolve_department_canonico():
    tag_id, warning = resolve_department("Tecnologia")
    assert tag_id == 9
    assert warning is None


def test_resolve_department_sinonimo_infra():
    tag_id, warning = resolve_department("Infra")
    assert tag_id == 9
    assert warning is None


def test_resolve_department_sinonimo_legal():
    tag_id, warning = resolve_department("Legal")
    assert tag_id == 20
    assert warning is None


def test_resolve_department_normaliza_acentos_y_mayusculas():
    tag_id, warning = resolve_department("TECNOLOGÍA")
    assert tag_id == 9
    assert warning is None
    tag_id2, _ = resolve_department("rr.hh")
    assert tag_id2 == 10


def test_resolve_department_no_mapea_no_crea_devuelve_warning():
    tag_id, warning = resolve_department("Departamento Inexistente XYZ")
    assert tag_id is None
    assert warning is not None
    assert "Departamento Inexistente XYZ" in warning


# ---------------------------------------------------------------------------
# Tipo de tarea: canonico + sinonimos
# ---------------------------------------------------------------------------

def test_resolve_task_type_canonico():
    tag_id, warning = resolve_task_type("Entregable")
    assert tag_id == 12
    assert warning is None


def test_resolve_task_type_sinonimo_bug():
    tag_id, warning = resolve_task_type("Bug")
    assert tag_id == 12
    assert warning is None


def test_resolve_task_type_no_mapea_devuelve_warning_sin_crear():
    tag_id, warning = resolve_task_type("Tipo Fantasma")
    assert tag_id is None
    assert warning is not None
    assert "Tipo Fantasma" in warning


def test_resolve_task_type_vacio():
    tag_id, warning = resolve_department("")
    assert tag_id is None
    assert warning is not None


# ---------------------------------------------------------------------------
# Carga del fichero: fuente unica, override opcional via APL_LABELS_PATH
# ---------------------------------------------------------------------------

def test_load_label_map_default_coincide_con_labels_global():
    reloaded = load_label_map()
    assert reloaded.department_tag_ids == LABELS.department_tag_ids
    assert reloaded.task_type_tag_ids == LABELS.task_type_tag_ids
    assert reloaded.priority_star_codes == LABELS.priority_star_codes


def test_load_label_map_ids_completos_conocidos():
    """Valores congelados del pre-flight en vivo (27-ago-2026, UID 29)."""
    assert LABELS.priority_tag_ids == {"P0": 1, "P1": 2, "P2": 3, "P3": 4}
    assert LABELS.department_tag_ids["Operaciones"] == 14
    assert LABELS.department_tag_ids["Gerencia"] == 20
    assert LABELS.task_type_tag_ids["Documentacion"] == 25
    assert LABELS.task_type_tag_ids["Gestion"] == 27


# ---------------------------------------------------------------------------
# Candado de contenido: jamas un create sobre project.tags en app/
# ---------------------------------------------------------------------------

def test_no_create_sobre_project_tags_en_app():
    """El MCP asigna etiquetas, nunca las crea (sec 0 hallazgos del diseno
    ticket 737). Falla si aparece un `odoo.create(actor, "project.tags", ...)`
    en cualquier fichero bajo app/."""
    forbidden = re.compile(r"\.create\(\s*actor\s*,\s*[\"']project\.tags[\"']")
    offenders = [
        str(path) for path in (REPO_ROOT / "app").rglob("*.py")
        if forbidden.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"create() sobre project.tags encontrado en: {offenders}"
