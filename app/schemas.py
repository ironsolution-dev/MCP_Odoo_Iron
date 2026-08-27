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

# Campos obligatorios en el cuerpo de la tarea (sec 3.5). Sin cambio de
# logica en el ticket 737: sigue siendo un chequeo de subcadena sin tilde,
# por eso `app.apl_description.render_apl_description` escribe los
# encabezados igual (con emoji, sin tilde) para no romper este contrato.
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
class ParsedAPLTask:
    """Resultado de `parse_and_validate_apl_task_input` (ticket 737): titulo
    ya normalizado (legado o nuevo), prioridad canonica, codigo de estrella
    listo para Odoo, tag_ids resueltos (sin duplicar, sin None) y warnings
    no bloqueantes (formato antiguo normalizado, conflicto titulo/payload,
    area o task_type que no mapeo a ninguna etiqueta)."""
    title: str
    description: str
    deadline: str  # ISO YYYY-MM-DD
    priority: str  # P0|P1|P2|P3 canonico, ya resuelto de titulo o payload
    priority_star: str  # "0".."3", listo para el campo priority de Odoo
    tag_ids: list[int]
    warnings: list[str]


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


def parse_and_validate_apl_task_input(payload: dict) -> ParsedAPLTask:
    """Valida y normaliza un payload de creacion de tarea APL 2.0 (ticket 737).

    Orquesta, en orden: `app.apl_title.normalize_apl_title` (formato dual
    legado/nuevo, ADR-016) + `app.apl_labels.resolve_priority/
    resolve_department/resolve_task_type` (fuente unica de IDs, ADR-017) +
    `validate_apl_description` (sin cambio de logica). Nunca crea etiquetas:
    si `area`/`task_type` no mapea, el tag correspondiente se omite y queda
    un warning no bloqueante.

    Si el titulo es legado y trae Px/Area/Tipo que difieren del payload,
    manda el titulo (asi lo anoto el PM en el ticket) y se agrega un warning
    de conflicto por cada campo distinto.

    Import local de `app.apl_title`/`app.apl_labels` para evitar import
    circular: ambos modulos importan `ValidationError` de aqui.
    """
    from app.apl_labels import resolve_department, resolve_priority, resolve_task_type
    from app.apl_title import normalize_apl_title

    required = ["title", "description", "deadline", "priority", "area", "task_type"]
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise ValidationError(f"faltan campos APL 2.0: {missing}")

    validate_apl_description(payload["description"])
    validate_iso_date(payload["deadline"], field="deadline")
    validate_priority(payload["priority"])

    norm_title = normalize_apl_title(payload["title"])
    warnings: list[str] = []
    if norm_title.warning:
        warnings.append(norm_title.warning)

    final_priority = str(payload["priority"]).strip().upper()
    final_area = str(payload["area"]).strip()
    final_task_type = str(payload["task_type"]).strip()

    if norm_title.is_legacy:
        if norm_title.priority and norm_title.priority != final_priority:
            warnings.append(
                f"conflicto de prioridad: titulo legado trae {norm_title.priority}, "
                f"payload trae {final_priority}; manda el titulo"
            )
            final_priority = norm_title.priority
        if norm_title.area and norm_title.area != final_area:
            warnings.append(
                f"conflicto de area: titulo legado trae '{norm_title.area}', "
                f"payload trae '{final_area}'; manda el titulo"
            )
            final_area = norm_title.area
        if norm_title.task_type and norm_title.task_type != final_task_type:
            warnings.append(
                f"conflicto de task_type: titulo legado trae '{norm_title.task_type}', "
                f"payload trae '{final_task_type}'; manda el titulo"
            )
            final_task_type = norm_title.task_type

    validate_priority(final_priority)
    priority_tag_id, priority_star = resolve_priority(final_priority)

    dept_tag_id, dept_warning = resolve_department(final_area)
    if dept_warning:
        warnings.append(dept_warning)

    type_tag_id, type_warning = resolve_task_type(final_task_type)
    if type_warning:
        warnings.append(type_warning)

    tag_ids = [tid for tid in (priority_tag_id, dept_tag_id, type_tag_id) if tid is not None]

    return ParsedAPLTask(
        title=norm_title.clean_title,
        description=payload["description"].strip(),
        deadline=payload["deadline"],
        priority=final_priority,
        priority_star=priority_star,
        tag_ids=tag_ids,
        warnings=warnings,
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
