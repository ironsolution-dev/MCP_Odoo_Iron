"""Escritor unico de la descripcion APL 2.0 (ticket 737).

Orden y encabezados fijos por la guia APL 2.0 V2 v1.1 (sec 5): 8 campos con
emoji, mas 🔗 Dependencias opcional. Los tres puntos de entrada del servidor
(system prompt/help de escritura, parser NL) INVOCAN este escritor en vez de
reimplementar el formato — una sola fuente de verdad para como se ve una
descripcion APL 2.0.

Ronda 3 (ticket 737, hallazgo D1): las etiquetas de campo se escriben TAL
CUAL las tiene la guia (con tilde: "Fecha límite", "Siguiente acción") — ya
no hay motivo para evitarlas. Antes este modulo las escribia sin tilde a
proposito porque `app.apl_validation.validate_apl_description` solo
reconocia la forma sin tilde y rechazaba en produccion el formato canonico
de la propia guia (ver tareas 805/806 del sandbox 32). El fix real fue
volver ese validador tolerante a tilde/mayuscula/emoji via
`app.apl_labels.normalize_apl_key` — el mismo normalizador que ya usaban
`area`/`task_type`; este modulo tambien lo reutiliza (hallazgo D2, abajo)
en vez de reimplementar su propio "accent folding".
"""

from __future__ import annotations

from typing import Optional

from app.apl_labels import normalize_apl_key

# Orden fijo por la guia APL 2.0 V2 v1.1 (sec 5): (field_id, emoji, nombre
# canonico con tilde). Fuente unica — de aqui derivan:
#   - `render_apl_description` (abajo): arma cada linea "emoji nombre: valor".
#   - `app.apl_validation.APL_BODY_REQUIRED_FIELDS`: el nombre canonico que
#     se muestra en el error cuando falta un campo (ronda 3, con tilde).
#   - `normalize_apl_description` (abajo): reconoce estos mismos nombres,
#     con o sin tilde/emoji/mayuscula, para parsear una descripcion legado.
APL_DESCRIPTION_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("responsable", "👤", "Responsable"),
    ("objetivo", "🎯", "Objetivo"),
    ("entregable", "📦", "Entregable"),
    ("fecha_limite", "📅", "Fecha límite"),
    ("criterio_de_cierre", "✅", "Criterio de cierre"),
    ("evidencia_requerida", "📎", "Evidencia requerida"),
    ("riesgo_si_no_se_cierra", "⚠️", "Riesgo si no se cierra"),
    ("siguiente_accion", "▶️", "Siguiente acción"),
)

# Campo opcional (sec 5 de la guia): se agrega solo si viene informado, no
# cuenta para decidir si una descripcion "ya esta en formato emoji".
APL_DEPENDENCIAS_FIELD: tuple[str, str, str] = ("dependencias", "🔗", "Dependencias")

_ALL_FIELDS = APL_DESCRIPTION_FIELDS + (APL_DEPENDENCIAS_FIELD,)
_EMOJI_BY_FIELD = {field_id: emoji for field_id, emoji, _label in _ALL_FIELDS}
_NORMALIZED_LABEL_BY_FIELD = {
    field_id: normalize_apl_key(label) for field_id, _emoji, label in _ALL_FIELDS
}


def render_apl_description(
    responsable: str,
    objetivo: str,
    entregable: str,
    fecha_limite: str,
    criterio_de_cierre: str,
    evidencia_requerida: str,
    riesgo_si_no_se_cierra: str,
    siguiente_accion: str,
    dependencias: Optional[str] = None,
) -> str:
    """Renderiza los 8 campos obligatorios (+ 🔗 Dependencias opcional) en
    el orden y con los encabezados exactos de la guia APL 2.0 V2 v1.1 sec 5."""
    values = {
        "responsable": responsable,
        "objetivo": objetivo,
        "entregable": entregable,
        "fecha_limite": fecha_limite,
        "criterio_de_cierre": criterio_de_cierre,
        "evidencia_requerida": evidencia_requerida,
        "riesgo_si_no_se_cierra": riesgo_si_no_se_cierra,
        "siguiente_accion": siguiente_accion,
    }
    lines = [
        f"{emoji} {label}: {values[field_id]}"
        for field_id, emoji, label in APL_DESCRIPTION_FIELDS
    ]
    if dependencias:
        dep_id, dep_emoji, dep_label = APL_DEPENDENCIAS_FIELD
        lines.append(f"{dep_emoji} {dep_label}: {dependencias}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Normalizacion de descripcion legado -> formato guia (ticket 737, D2)
# ---------------------------------------------------------------------------

_NORMALIZED_WARNING = "descripcion normalizada al formato APL 2.0 v1.1"


def _match_field_header(line: str) -> Optional[tuple[str, str]]:
    """Si `line` es un encabezado 'algo: resto' que matchea un campo APL 2.0
    conocido (con o sin emoji, con o sin tilde, cualquier mayuscula/minuscula),
    devuelve (field_id, resto_de_la_linea). Si no matchea ninguno, None.

    Usa `normalize_apl_key` (misma fuente que area/task_type y que
    `app.apl_validation.validate_apl_description`) sobre la parte anterior a
    ':' — el emoji, si lo hay, no afecta el match porque solo se compara el
    SUFIJO normalizado contra el nombre canonico."""
    if ":" not in line:
        return None
    label_part, _, rest = line.partition(":")
    normalized_label = normalize_apl_key(label_part)
    if not normalized_label:
        return None
    for field_id, _emoji, _label in _ALL_FIELDS:
        canonical = _NORMALIZED_LABEL_BY_FIELD[field_id]
        if normalized_label == canonical or normalized_label.endswith(" " + canonical):
            return field_id, rest.strip()
    return None


def _extract_legacy_fields(description: str) -> Optional[dict[str, str]]:
    """Parsea una descripcion linea por linea buscando encabezados de campo
    APL 2.0 (con o sin emoji/tilde). Devuelve {field_id: valor} con el valor
    de la primera ocurrencia de cada campo (el texto entre su encabezado y el
    siguiente encabezado reconocido, o el fin de la descripcion). None si no
    se reconocio ningun encabezado."""
    lines = description.splitlines()
    headers: list[tuple[int, str, str]] = []  # (indice_linea, field_id, resto_1ra_linea)
    for idx, line in enumerate(lines):
        match = _match_field_header(line)
        if match:
            field_id, rest = match
            headers.append((idx, field_id, rest))
    if not headers:
        return None

    fields: dict[str, str] = {}
    for pos, (idx, field_id, first_rest) in enumerate(headers):
        end_idx = headers[pos + 1][0] if pos + 1 < len(headers) else len(lines)
        continuation = [l.strip() for l in lines[idx + 1:end_idx]]
        value = " ".join([first_rest, *continuation])
        value = " ".join(value.split())  # colapsa espacios/saltos internos
        if field_id not in fields:
            fields[field_id] = value
    return fields


def _is_already_emoji_format(description: str) -> bool:
    """True si los 8 campos obligatorios aparecen cada uno con SU emoji
    canonico exacto como prefijo del encabezado (con o sin tilde/mayuscula
    en el nombre — solo el emoji tiene que calzar exacto). 'Dependencias' no
    cuenta: es opcional y no decide el formato."""
    found_emoji: dict[str, bool] = {}
    for line in description.splitlines():
        match = _match_field_header(line)
        if not match:
            continue
        field_id, _rest = match
        label_part = line.split(":", 1)[0].strip()
        found_emoji[field_id] = label_part.startswith(_EMOJI_BY_FIELD[field_id])
    return all(found_emoji.get(field_id) for field_id, _e, _l in APL_DESCRIPTION_FIELDS)


def normalize_apl_description(description: str) -> tuple[str, Optional[str]]:
    """Normaliza una descripcion APL 2.0 al formato canonico de la guia
    (ticket 737, ronda 3, hallazgo D2).

    - Si ya trae los 8 encabezados con su emoji canonico -> se devuelve tal
      cual (nunca se toca lo que ya esta bien).
    - Si viene en formato legado ("Label: valor" por linea, con o sin
      emoji/tilde/mayuscula, en cualquier orden) y se pudieron extraer los 8
      campos obligatorios -> se reconstruye via `render_apl_description`
      (el mismo escritor unico que usa el resto del servidor), conservando
      'Dependencias' si vino informada.
    - Si no se pudo identificar TODOS los campos obligatorios -> se devuelve
      intacta; es `app.apl_validation.validate_apl_description` quien debe
      reportar el/los campos faltantes con su nombre canonico. Este
      normalizador no valida, solo reescribe cuando puede hacerlo completo.

    Devuelve (description_final, warning). `warning` es None si no hubo
    cambio (ya emoji, o no se pudo parsear como legado completo)."""
    stripped = description.strip()
    if not stripped or _is_already_emoji_format(stripped):
        return stripped, None

    fields = _extract_legacy_fields(stripped)
    required_ids = [field_id for field_id, _e, _l in APL_DESCRIPTION_FIELDS]
    if fields is None or any(not fields.get(field_id) for field_id in required_ids):
        return stripped, None  # incompleto: que lo reporte el validador

    rendered = render_apl_description(
        responsable=fields["responsable"],
        objetivo=fields["objetivo"],
        entregable=fields["entregable"],
        fecha_limite=fields["fecha_limite"],
        criterio_de_cierre=fields["criterio_de_cierre"],
        evidencia_requerida=fields["evidencia_requerida"],
        riesgo_si_no_se_cierra=fields["riesgo_si_no_se_cierra"],
        siguiente_accion=fields["siguiente_accion"],
        dependencias=fields.get("dependencias") or None,
    )
    if rendered == stripped:
        return rendered, None
    return rendered, _NORMALIZED_WARNING
