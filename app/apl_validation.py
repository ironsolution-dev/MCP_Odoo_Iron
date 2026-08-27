"""Validadores APL 2.0 de creacion/cierre de tarea (ticket 737, hallazgo F4).

Extraido de `app/schemas.py` (que paso de 300 lineas con el ticket 737,
limite duro del repo — ver CLAUDE.md "Convenciones de codigo"). Separacion
por responsabilidad, no por tamano arbitrario: este modulo es todo lo que
orquesta el contrato APL 2.0 de una tarea (titulo, descripcion, prioridad,
etiquetas, evidencia de cierre, motivo de cancelacion); `app/schemas.py`
se queda con lo generico (ValidationError base, validate_iso_date, el
contrato de escritura `TASK_FIELD_SPECS`) que no es privativo de APL 2.0
— `validate_iso_date` la usa tambien `app/tools/crm.py` y el contrato de
escritura, por ejemplo.

Como `app.apl_title` y `app.apl_labels` ya importaban `ValidationError`
desde `app.schemas`, moverse a este modulo elimina el import circular que
antes obligaba a `app.schemas.parse_and_validate_apl_task_input` a hacer
imports locales (dentro de la funcion) — aqui van arriba, normales.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.apl_labels import resolve_department, resolve_priority, resolve_task_type
from app.apl_title import normalize_apl_title
from app.schemas import ValidationError, validate_iso_date


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
    """
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
