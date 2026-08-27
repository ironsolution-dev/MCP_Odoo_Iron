"""Normalizacion dual de titulo APL 2.0 (ticket 737, ADR-016).

Acepta dos formatos de entrada:

- **Legado** — `[APL 2.0][Px][Area][Tipo] resto`: se reconoce via regex, se
  extraen Px/Area/Tipo y se limpia el titulo (corchetes retirados). Marca
  `is_legacy=True` y devuelve un warning de compatibilidad (decision del PM
  anotada en el ticket 737: aceptar el titulo viejo, normalizar, avisar —
  nunca romper lo que ya escribia gente/LLMs).
- **Nuevo** — cualquier texto que NO empiece con "[": regla ESTRUCTURAL, no
  lista cerrada de verbos (ADR-016). Debe ser no vacio, sin saltos de linea,
  <= 140 caracteres. La calidad del verbo (ver guia APL 2.0 V2 v1.1 sec 3)
  queda a criterio del LLM/humano — riesgo aceptado y documentado en el ADR.

Un texto que empieza con "[" pero no matchea el patron legado completo se
rechaza (probable formato legado mal formado, no un titulo nuevo valido).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.schemas import ValidationError

_LEGACY_TITLE_RE = re.compile(
    r"^\[APL\s*2\.0\]\[(P[0-3])\]\[([^\]]+)\]\[([^\]]+)\]\s+(\S.*)$",
    re.IGNORECASE,
)

MAX_TITLE_LENGTH = 140


@dataclass(frozen=True)
class NormalizedTitle:
    clean_title: str
    priority: Optional[str]    # "P0".."P3" si viene del titulo legado; si no, None
    area: Optional[str]
    task_type: Optional[str]
    is_legacy: bool
    warning: Optional[str] = None


def normalize_apl_title(title: str) -> NormalizedTitle:
    """Devuelve el titulo normalizado + metadata legado, o levanta
    ValidationError si no cumple NINGUN formato (legado ni nuevo)."""
    if not title or not title.strip():
        raise ValidationError("title vacio")
    raw = title.strip()

    legacy_match = _LEGACY_TITLE_RE.match(raw)
    if legacy_match:
        priority, area, task_type, rest = legacy_match.groups()
        clean = rest.strip()
        if not clean:
            raise ValidationError("title legado sin texto tras los corchetes")
        return NormalizedTitle(
            clean_title=clean,
            priority=priority.upper(),
            area=area.strip(),
            task_type=task_type.strip(),
            is_legacy=True,
            warning=(
                "formato antiguo normalizado: se retiraron los corchetes "
                "[APL 2.0][Px][Area][Tipo] del titulo (ver ticket 737)"
            ),
        )

    if raw.startswith("["):
        raise ValidationError(
            "title no cumple ningun formato APL 2.0 valido: empieza con '[' "
            "pero no matchea el patron legado completo "
            "[APL 2.0][Px][Area][Tipo] resto"
        )
    if "\n" in raw or "\r" in raw:
        raise ValidationError("title no puede tener saltos de linea")
    if len(raw) > MAX_TITLE_LENGTH:
        raise ValidationError(
            f"title excede {MAX_TITLE_LENGTH} caracteres (recibido {len(raw)})"
        )

    return NormalizedTitle(
        clean_title=raw,
        priority=None,
        area=None,
        task_type=None,
        is_legacy=False,
        warning=None,
    )
