"""Fuente unica de IDs de etiquetas APL 2.0 (ticket 737, ADR-017).

Carga `config/apl_labels.yaml` UNA VEZ al importar el modulo (se hornea en
la imagen; `APL_LABELS_PATH` permite apuntar a otro fichero solo para
tests/desarrollo). Resuelve prioridad -> (tag_id, estrella) y
departamento/tipo -> tag_id | None + warning.

Regla dura (sec 0 hallazgos del diseno): el MCP ASIGNA las etiquetas
canonicas, NUNCA las crea. Si `area`/`task_type` no matchea ningun nombre
canonico ni sinonimo conocido, se devuelve `tag_id=None` + warning legible;
no se llama `project.tags.create` en ningun punto de este modulo ni de sus
consumidores.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "apl_labels.yaml"


def _normalize_key(value: str) -> str:
    """minusculas, sin acentos, espacios colapsados. Usado para matchear
    nombre canonico o sinonimo sin importar acentos/mayusculas del payload."""
    nfkd = unicodedata.normalize("NFKD", value.strip().lower())
    sin_acentos = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return " ".join(sin_acentos.split())


def _build_lookup(canonical_ids: dict[str, int], synonyms: dict[str, str]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for name, tag_id in canonical_ids.items():
        lookup[_normalize_key(name)] = tag_id
    for synonym, canonical_name in synonyms.items():
        tag_id = canonical_ids.get(canonical_name)
        if tag_id is not None:
            lookup[_normalize_key(synonym)] = tag_id
    return lookup


@dataclass(frozen=True)
class LabelMap:
    version: int
    priority_tag_ids: dict[str, int]
    priority_star_codes: dict[str, str]
    department_tag_ids: dict[str, int]
    task_type_tag_ids: dict[str, int]
    department_synonyms: dict[str, str]
    task_type_synonyms: dict[str, str]
    role_department_names: dict[str, str]
    department_lookup: dict[str, int] = field(default_factory=dict)
    task_type_lookup: dict[str, int] = field(default_factory=dict)


def _resolve_path(path: Optional[Path]) -> Path:
    if path is not None:
        return path
    env_path = os.environ.get("APL_LABELS_PATH")
    return Path(env_path) if env_path else _DEFAULT_PATH


def load_label_map(path: Optional[Path] = None) -> LabelMap:
    resolved = _resolve_path(path)
    with resolved.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    department_tag_ids = raw["department_tag_ids"]
    task_type_tag_ids = raw["task_type_tag_ids"]
    department_synonyms = raw.get("department_synonyms", {})
    task_type_synonyms = raw.get("task_type_synonyms", {})
    role_department_names = raw.get("role_department_tag_ids", {})

    return LabelMap(
        version=raw.get("version", 1),
        priority_tag_ids=raw["priority_tag_ids"],
        priority_star_codes=raw["priority_star_codes"],
        department_tag_ids=department_tag_ids,
        task_type_tag_ids=task_type_tag_ids,
        department_synonyms=department_synonyms,
        task_type_synonyms=task_type_synonyms,
        role_department_names=role_department_names,
        department_lookup=_build_lookup(department_tag_ids, department_synonyms),
        task_type_lookup=_build_lookup(task_type_tag_ids, task_type_synonyms),
    )


# Cargado una vez al boot (import time) — fuente unica en todo el proceso.
LABELS = load_label_map()

_DEFAULT_STAR = "1"  # defensivo: priority ya viene validada por schemas.validate_priority


def resolve_priority(priority: str) -> tuple[Optional[int], str]:
    """P0..P3 -> (tag_id de prioridad, codigo de estrella para Odoo)."""
    tag_id = LABELS.priority_tag_ids.get(priority)
    star = LABELS.priority_star_codes.get(priority, _DEFAULT_STAR)
    return tag_id, star


def resolve_department(area: str) -> tuple[Optional[int], Optional[str]]:
    """area -> (tag_id, warning). NUNCA crea: si no matchea, tag_id=None y
    el warning explica por que no se asigno etiqueta de departamento."""
    if not area or not area.strip():
        return None, "area vacia: no se asigno etiqueta de departamento"
    tag_id = LABELS.department_lookup.get(_normalize_key(area))
    if tag_id is None:
        return None, (
            f"area '{area}' no mapea a ningun departamento canonico ni "
            "sinonimo conocido: no se asigno etiqueta de departamento"
        )
    return tag_id, None


def resolve_task_type(task_type: str) -> tuple[Optional[int], Optional[str]]:
    """task_type -> (tag_id, warning). Mismo contrato que resolve_department."""
    if not task_type or not task_type.strip():
        return None, "task_type vacio: no se asigno etiqueta de tipo"
    tag_id = LABELS.task_type_lookup.get(_normalize_key(task_type))
    if tag_id is None:
        return None, (
            f"task_type '{task_type}' no mapea a ningun tipo canonico ni "
            "sinonimo conocido: no se asigno etiqueta de tipo"
        )
    return tag_id, None


def resolve_department_name_for_role(role: Optional[str]) -> Optional[str]:
    """rol del actor (ActorEntry.role) -> nombre CANONICO de departamento,
    o None si el rol no esta en `role_department_tag_ids` (ticket 737, F2).

    Solo resuelve el NOMBRE — el id lo sigue resolviendo unicamente
    `resolve_department()` contra `department_tag_ids` (fuente unica de
    IDs, ADR-017); esta funcion no repite ningun numero. El caller tipico
    (openai_nl_parser.create_todo) usa el nombre como `area` y deja que
    `resolve_department` (via `parse_and_validate_apl_task_input`) genere
    el tag_id + el warning si hiciera falta."""
    if not role or not role.strip():
        return None
    return LABELS.role_department_names.get(role.strip())
