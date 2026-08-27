"""Validadores de input genericos: error base y contrato de escritura.

Los validadores especificos de APL 2.0 (titulo/descripcion/prioridad de
tarea, evidencia de cierre, motivo de cancelacion) viven en
`app/apl_validation.py` (ticket 737, hallazgo F4 — este fichero paso de
300 lineas). Lo que queda aqui es generico, usado fuera del dominio APL
(`validate_iso_date` lo usa tambien `app/tools/crm.py`; el contrato de
escritura de `project.task` no es privativo de APL 2.0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


class ValidationError(ValueError):
    """Input no cumple contrato APL 2.0 / formato esperado."""


def validate_iso_date(value: str, field: str = "deadline") -> None:
    if not value or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise ValidationError(f"{field} debe ser ISO YYYY-MM-DD; recibido: {value!r}")


# ---------------------------------------------------------------------------
# Calendar event
# ---------------------------------------------------------------------------

def validate_calendar_event_dates(start: str, stop: str) -> None:
    """start y stop ISO datetime (YYYY-MM-DD HH:MM:SS); start < stop."""
    iso_dt = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")
    if not iso_dt.match(start or ""):
        raise ValidationError(f"start invalido: {start!r}")
    if not iso_dt.match(stop or ""):
        raise ValidationError(f"stop invalido: {stop!r}")
    if start >= stop:
        raise ValidationError(f"start ({start}) debe ser anterior a stop ({stop})")


# ---------------------------------------------------------------------------
# Contrato de escritura de tareas (odoo_update_task_apl) — sec G2
#
# Fuente unica de verdad de que campos son escribibles y con que forma.
# `TASK_FIELD_ALIASES` traduce nombres "humanos" al campo real de Odoo antes
# de validar. `project_id` esta deliberadamente BLOQUEADO aqui: reasignar
# proyecto es una operacion con verificacion de visibilidad propia
# (odoo_move_task_to_project, sec G1), no un campo mas del update generico.
# ---------------------------------------------------------------------------

# alias humano -> campo real de Odoo.
TASK_FIELD_ALIASES: dict[str, str] = {
    "deadline": "date_deadline",
}

_TASK_PRIORITY_CODES = {"0", "1", "2", "3"}

_MOVE_TASK_POINTER = (
    "project_id esta bloqueado en update_task/odoo_update_task_apl. "
    "Para mover una tarea a otro proyecto usa la tool odoo_move_task_to_project "
    "(o la accion move_task_to_project en el protocolo ChatGPT)."
)


@dataclass(frozen=True)
class TaskFieldSpec:
    kind: str  # "str" | "priority_code" | "iso_date" | "int" | "list_int" | "blocked"
    blocked_message: str = ""


TASK_FIELD_SPECS: dict[str, TaskFieldSpec] = {
    "name":          TaskFieldSpec(kind="str"),
    "description":   TaskFieldSpec(kind="str"),
    "priority":      TaskFieldSpec(kind="priority_code"),
    "date_deadline": TaskFieldSpec(kind="iso_date"),
    "stage_id":      TaskFieldSpec(kind="int"),
    "tag_ids":       TaskFieldSpec(kind="list_int"),
    "user_ids":      TaskFieldSpec(kind="list_int"),
    "project_id":    TaskFieldSpec(kind="blocked", blocked_message=_MOVE_TASK_POINTER),
}


def _validate_field_value(field: str, spec: TaskFieldSpec, value: object) -> Optional[str]:
    """Devuelve el mensaje de problema, o None si `value` cumple `spec`."""
    if spec.kind == "blocked":
        return spec.blocked_message
    if spec.kind == "str":
        if not isinstance(value, str) or not value.strip():
            return f"{field}: debe ser texto no vacio; recibido {value!r}"
        return None
    if spec.kind == "priority_code":
        if str(value) not in _TASK_PRIORITY_CODES:
            return (f"{field}: debe ser uno de {sorted(_TASK_PRIORITY_CODES)}; "
                    f"recibido {value!r}")
        return None
    if spec.kind == "iso_date":
        try:
            validate_iso_date(value, field=field)
        except ValidationError as exc:
            return str(exc)
        return None
    if spec.kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{field}: debe ser int; recibido {value!r}"
        return None
    if spec.kind == "list_int":
        is_list_of_ints = (
            isinstance(value, list)
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
        )
        if not is_list_of_ints:
            return f"{field}: debe ser lista de int; recibido {value!r}"
        return None
    return f"{field}: kind de validacion desconocido {spec.kind!r}"  # defensivo


def validate_task_write_payload(changes: dict) -> dict:
    """Normaliza alias (`TASK_FIELD_ALIASES`) y valida `changes` contra
    `TASK_FIELD_SPECS`. Junta TODOS los problemas encontrados en UN solo
    ValidationError (no falla-rapido-en-el-primero) para que el LLM pueda
    corregir todo de una vez.

    Devuelve el dict normalizado (claves ya traducidas a campos reales de
    Odoo) listo para `odoo.write`. No escribe nada; no conoce Odoo.
    """
    if not isinstance(changes, dict) or not changes:
        raise ValidationError("changes vacio o invalido; nada que actualizar")

    problems: list[str] = []

    # 1. Alias + su campo real no pueden llegar juntos (ambiguo: cual manda?).
    for alias, canonical in TASK_FIELD_ALIASES.items():
        if alias in changes and canonical in changes:
            problems.append(
                f"{alias}/{canonical}: use only one (llegaron los dos a la vez)"
            )

    # 2. Normalizar alias -> campo real.
    normalized: dict = {}
    for key, value in changes.items():
        real_key = TASK_FIELD_ALIASES.get(key, key)
        normalized[real_key] = value

    # 3. Validar cada campo normalizado contra TASK_FIELD_SPECS.
    for field, value in normalized.items():
        spec = TASK_FIELD_SPECS.get(field)
        if spec is None:
            problems.append(
                f"{field}: campo no reconocido. Validos: {sorted(TASK_FIELD_SPECS)}"
            )
            continue
        problem = _validate_field_value(field, spec, value)
        if problem:
            problems.append(problem)

    if problems:
        raise ValidationError(
            f"task write payload invalido ({len(problems)} problema(s)): "
            + "; ".join(problems)
        )

    return normalized
