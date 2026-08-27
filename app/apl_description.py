"""Escritor unico de la descripcion APL 2.0 (ticket 737).

Orden y encabezados fijos por la guia APL 2.0 V2 v1.1 (sec 5): 8 campos con
emoji, mas 🔗 Dependencias opcional. Los tres puntos de entrada del servidor
(system prompt/help de escritura, parser NL) INVOCAN este escritor en vez de
reimplementar el formato — una sola fuente de verdad para como se ve una
descripcion APL 2.0.

Las etiquetas de campo se escriben sin tilde ("Fecha limite", "Siguiente
accion") a proposito: `app.schemas.validate_apl_description` busca esas
mismas subcadenas sin tilde (APL_BODY_REQUIRED_FIELDS) y su logica NO cambia
en este ticket — la descripcion generada aqui debe seguir pasando esa
validacion tal cual. El emoji es decorativo y no interfiere con el chequeo.
"""

from __future__ import annotations

from typing import Optional


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
    el orden de la guia APL 2.0 V2 v1.1 sec 5."""
    lines = [
        f"👤 Responsable: {responsable}",
        f"🎯 Objetivo: {objetivo}",
        f"📦 Entregable: {entregable}",
        f"📅 Fecha limite: {fecha_limite}",
        f"✅ Criterio de cierre: {criterio_de_cierre}",
        f"📎 Evidencia requerida: {evidencia_requerida}",
        f"⚠️ Riesgo si no se cierra: {riesgo_si_no_se_cierra}",
        f"▶️ Siguiente accion: {siguiente_accion}",
    ]
    if dependencias:
        lines.append(f"🔗 Dependencias: {dependencias}")
    return "\n".join(lines)
