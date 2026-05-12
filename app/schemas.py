"""Validadores de input. Reglas APL 2.0 (sec 3.5 Task Packet).

Regla: si falta un dato APL 2.0 obligatorio, NO crear la tarea. Devolver
ValidationError con el campo faltante para que el LLM lo complete o pida al
humano.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


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
