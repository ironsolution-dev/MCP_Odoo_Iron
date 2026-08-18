"""Validadores de input. Reglas APL 2.0 (sec 3.5 Task Packet).

Regla: si falta un dato APL 2.0 obligatorio, NO crear la tarea. Devolver
ValidationError con el campo faltante para que el LLM lo complete o pida al
humano.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


class ValidationError(ValueError):
    """Input no cumple contrato APL 2.0 / formato esperado."""


# ---------------------------------------------------------------------------
# APL 2.0 — Tarea
# ---------------------------------------------------------------------------

# Formato titulo APL 2.0:
#   [APL 2.0][P0/P1/P2/P3][Area][Tipo] Verbo + entregable + contexto
APL_TITLE_PATTERN = re.compile(
    r"^\[APL\s*2\.0\]\[P[0-3]\]\[[^\]]+\]\[[^\]]+\]\s+\S+",
    re.IGNORECASE,
)

# Campos obligatorios en el cuerpo de la tarea (sec 3.5).
APL_BODY_REQUIRED_FIELDS = (
    "objetivo",
    "entregable",
    "responsable",
    "fecha limite",
    "criterio de cierre",
    "evidencia requerida",
    "riesgo si no se cierra",
    "siguiente accion",
)


@dataclass(frozen=True)
class APLTaskInput:
    title: str
    description: str
    deadline: str  # ISO YYYY-MM-DD
    priority: str  # P0|P1|P2|P3
    area: str
    task_type: str


def validate_apl_title(title: str) -> None:
    if not title or not title.strip():
        raise ValidationError("title vacio")
    if not APL_TITLE_PATTERN.match(title.strip()):
        raise ValidationError(
            "title no cumple formato APL 2.0. Formato: "
            "[APL 2.0][P0/P1/P2/P3][Area][Tipo] Verbo + entregable + contexto"
        )


def validate_apl_description(description: str) -> None:
    if not description or not description.strip():
        raise ValidationError("description vacia")
    lower = description.lower()
    missing = [field for field in APL_BODY_REQUIRED_FIELDS if field not in lower]
    if missing:
        raise ValidationError(
            f"description APL 2.0 incompleta. Faltan campos: {missing}"
        )


def validate_iso_date(value: str, field: str = "deadline") -> None:
    if not value or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise ValidationError(f"{field} debe ser ISO YYYY-MM-DD; recibido: {value!r}")


def validate_priority(value: str) -> None:
    if value not in {"P0", "P1", "P2", "P3"}:
        raise ValidationError(f"priority debe ser P0|P1|P2|P3; recibido: {value!r}")


def validate_apl_task_input(payload: dict) -> APLTaskInput:
    """Valida un payload completo de creacion de tarea APL 2.0.
    Levanta ValidationError con todos los problemas encontrados."""
    required = ["title", "description", "deadline", "priority", "area", "task_type"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise ValidationError(f"faltan campos APL 2.0: {missing}")

    validate_apl_title(payload["title"])
    validate_apl_description(payload["description"])
    validate_iso_date(payload["deadline"], field="deadline")
    validate_priority(payload["priority"])

    return APLTaskInput(
        title=payload["title"].strip(),
        description=payload["description"].strip(),
        deadline=payload["deadline"],
        priority=payload["priority"],
        area=str(payload["area"]).strip(),
        task_type=str(payload["task_type"]).strip(),
    )


# ---------------------------------------------------------------------------
# Cierre de tarea — evidencia obligatoria
# ---------------------------------------------------------------------------

EVIDENCE_MIN_LENGTH = 20  # APL: "no cerrar sin evidencia". 20 chars minimo.


def validate_evidence(evidence: str) -> str:
    if not evidence or not evidence.strip():
        raise ValidationError("evidencia obligatoria al cerrar (APL 2.0)")
    cleaned = evidence.strip()
    if len(cleaned) < EVIDENCE_MIN_LENGTH:
        raise ValidationError(
            f"evidencia demasiado corta ({len(cleaned)} chars). "
            f"Minimo {EVIDENCE_MIN_LENGTH} chars descriptivos."
        )
    return cleaned


def validate_cancel_reason(reason: str) -> str:
    if not reason or not reason.strip():
        raise ValidationError("motivo de cancelacion obligatorio (APL 2.0)")
    return reason.strip()


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
