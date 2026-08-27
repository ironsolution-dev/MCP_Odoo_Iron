"""Tests ticket 737, ronda 3 (hallazgos D1/D2, tareas 805/806 sandbox 32).

D1: `validate_apl_description` exigia los encabezados SIN tilde ("fecha
limite", "siguiente accion") y rechazaba el formato canonico de la guia
APL 2.0 V2 v1.1 sec 5 ("📅 Fecha límite", "▶️ Siguiente acción") — el
mismo formato que el servidor le pide usar al usuario. Se separa de
test_tasks_apl.py (que ya cubre el contrato general de
parse_and_validate_apl_task_input) porque este archivo es, especificamente,
la cobertura a fondo del contrato de FORMATO de la descripcion —
responsabilidad separable, mismo criterio que saco `app/apl_validation.py`
de `app/schemas.py` en la ronda 1 (hallazgo F4).

D2: si la descripcion llega por el payload JSON en formato legado (sin
encabezados emoji), se normaliza al formato de la guia via el escritor
unico `app.apl_description.render_apl_description` antes de guardarse.
"""

from __future__ import annotations

import pytest

from app.apl_description import normalize_apl_description, render_apl_description
from app.apl_validation import parse_and_validate_apl_task_input, validate_apl_description
from app.schemas import ValidationError

# Formato legado original (sin emoji, sin tilde) — el que aceptaba el
# validador antes del ticket 737. Sigue siendo valido (sin regresion).
VALID_DESCRIPTION_SIN_EMOJI_SIN_TILDE = (
    "objetivo entregable responsable fecha limite criterio de cierre "
    "evidencia requerida riesgo si no se cierra siguiente accion"
)


# ---------------------------------------------------------------------------
# D1 — validate_apl_description: tolerante a tilde/mayuscula/emoji
# ---------------------------------------------------------------------------

def test_missing_field_muestra_nombre_canonico_con_tilde():
    """Reproduce D1 al reves: si falta un campo, el error debe listar
    'Fecha límite' (con tilde, nombre de la guia), no 'fecha limite' ni la
    clave interna 'fecha_limite'."""
    incompleta = (
        "👤 Responsable: x\n🎯 Objetivo: x\n📦 Entregable: x\n"
        "✅ Criterio de cierre: x\n📎 Evidencia requerida: x\n"
        "⚠️ Riesgo si no se cierra: x\n▶️ Siguiente acción: x"
        # falta Fecha límite
    )
    with pytest.raises(ValidationError) as exc:
        validate_apl_description(incompleta)
    msg = str(exc.value)
    assert "Fecha límite" in msg
    assert "fecha_limite" not in msg


@pytest.mark.parametrize("description", [
    # Formato canonico de la guia APL 2.0 V2 v1.1 sec 5: emoji + tilde.
    # Caso EXACTO que produccion mandaba y que el validador viejo
    # rechazaba (tareas 805/806 del sandbox 32).
    pytest.param(
        "👤 Responsable: x\n🎯 Objetivo: x\n📦 Entregable: x\n"
        "📅 Fecha límite: x\n✅ Criterio de cierre: x\n"
        "📎 Evidencia requerida: x\n⚠️ Riesgo si no se cierra: x\n"
        "▶️ Siguiente acción: x",
        id="emoji_con_tilde_guia_v1.1",
    ),
    # Emoji sin tilde (formato que este mismo servidor generaba antes de
    # D1/D2 — sigue aceptandose, sin regresion).
    pytest.param(
        "👤 Responsable: x\n🎯 Objetivo: x\n📦 Entregable: x\n"
        "📅 Fecha limite: x\n✅ Criterio de cierre: x\n"
        "📎 Evidencia requerida: x\n⚠️ Riesgo si no se cierra: x\n"
        "▶️ Siguiente accion: x",
        id="emoji_sin_tilde",
    ),
    # Sin emoji, con tilde.
    pytest.param(
        "Responsable: x. Objetivo: x. Entregable: x. Fecha límite: x. "
        "Criterio de cierre: x. Evidencia requerida: x. "
        "Riesgo si no se cierra: x. Siguiente acción: x.",
        id="sin_emoji_con_tilde",
    ),
    # Sin emoji, sin tilde (contrato original, sin regresion).
    pytest.param(VALID_DESCRIPTION_SIN_EMOJI_SIN_TILDE, id="sin_emoji_sin_tilde"),
    # Mayusculas sueltas, sin emoji, con tilde — insensible a mayus/minus.
    pytest.param(
        "RESPONSABLE: x OBJETIVO: x ENTREGABLE: x FECHA LÍMITE: x "
        "CRITERIO DE CIERRE: x EVIDENCIA REQUERIDA: x "
        "RIESGO SI NO SE CIERRA: x SIGUIENTE ACCIÓN: x",
        id="mayusculas_con_tilde",
    ),
])
def test_acepta_con_y_sin_tilde_mayuscula_emoji(description):
    """Las 5 variantes que produccion realmente manda deben pasar sin
    excepcion — el chequeo es insensible a tilde/mayuscula/decoracion emoji."""
    validate_apl_description(description)  # no debe lanzar


# ---------------------------------------------------------------------------
# D2 — normalize_apl_description: legado -> formato guia
# ---------------------------------------------------------------------------

def test_normalize_legado_a_emoji():
    """Descripcion sin encabezados emoji (formato legado por payload JSON)
    se reescribe al formato de la guia via el escritor unico
    render_apl_description, con warning no bloqueante."""
    legado = (
        "Responsable: Willy.\n"
        "Objetivo: provisionar mcp-v2.\n"
        "Entregable: subdominio operativo.\n"
        "Fecha limite: 2026-05-12.\n"
        "Criterio de cierre: curl 200.\n"
        "Evidencia requerida: log Traefik + curl.\n"
        "Riesgo si no se cierra: no se puede desplegar GREEN.\n"
        "Siguiente accion: ejecutar deploy_green.sh."
    )
    normalizado, warning = normalize_apl_description(legado)
    assert warning == "descripcion normalizada al formato APL 2.0 v1.1"
    assert normalizado == render_apl_description(
        responsable="Willy.",
        objetivo="provisionar mcp-v2.",
        entregable="subdominio operativo.",
        fecha_limite="2026-05-12.",
        criterio_de_cierre="curl 200.",
        evidencia_requerida="log Traefik + curl.",
        riesgo_si_no_se_cierra="no se puede desplegar GREEN.",
        siguiente_accion="ejecutar deploy_green.sh.",
    )
    validate_apl_description(normalizado)  # queda valida tras normalizar


def test_normalize_ya_emoji_queda_intacta():
    """Si la descripcion YA esta en formato emoji canonico, no se toca
    (ni se re-renderiza) y no hay warning."""
    ya_emoji = render_apl_description(
        responsable="Willy", objetivo="x", entregable="x",
        fecha_limite="2026-05-12", criterio_de_cierre="x",
        evidencia_requerida="x", riesgo_si_no_se_cierra="x",
        siguiente_accion="x",
    )
    normalizado, warning = normalize_apl_description(ya_emoji)
    assert normalizado == ya_emoji
    assert warning is None


def test_normalize_conserva_dependencias():
    """Si el legado trae 'Dependencias', se conserva como campo opcional
    🔗 en la posicion que le corresponde en el escritor unico."""
    legado_con_dep = (
        "Objetivo: x\nEntregable: x\nResponsable: x\nFecha limite: x\n"
        "Criterio de cierre: x\nEvidencia requerida: x\n"
        "Riesgo si no se cierra: x\nSiguiente accion: x\n"
        "Dependencias: bloqueado por ticket 736."
    )
    normalizado, warning = normalize_apl_description(legado_con_dep)
    assert warning == "descripcion normalizada al formato APL 2.0 v1.1"
    assert "🔗 Dependencias: bloqueado por ticket 736." in normalizado
    assert normalizado.splitlines()[-1].startswith("🔗 Dependencias:")


def test_normalize_incompleta_no_se_toca():
    """Si falta un campo obligatorio, el normalizador NO reescribe — deja
    que validate_apl_description reporte el campo faltante."""
    incompleta = "Objetivo: x\nEntregable: x\nResponsable: x"
    normalizado, warning = normalize_apl_description(incompleta)
    assert normalizado == incompleta
    assert warning is None
    with pytest.raises(ValidationError):
        validate_apl_description(normalizado)


def test_parse_and_validate_normaliza_descripcion_legado_json():
    """Integracion D2: un payload JSON con description legado (sin
    encabezados emoji, camino real de escritura directa) llega normalizado
    en ParsedAPLTask.description y el warning queda registrado."""
    payload = {
        "title": "Configurar Traefik GREEN",
        "description": (
            "Objetivo: provisionar mcp-v2.\n"
            "Entregable: subdominio operativo.\n"
            "Responsable: Willy.\n"
            "Fecha limite: 2026-05-12.\n"
            "Criterio de cierre: curl 200.\n"
            "Evidencia requerida: log Traefik + curl.\n"
            "Riesgo si no se cierra: no se puede desplegar GREEN.\n"
            "Siguiente accion: ejecutar deploy_green.sh."
        ),
        "deadline": "2026-05-12",
        "priority": "P1",
        "area": "Operaciones",
        "task_type": "Implementacion",
    }
    apl = parse_and_validate_apl_task_input(payload)
    assert apl.description.startswith("👤 Responsable:")
    assert "🔗 Dependencias" not in apl.description  # no vino en el legado
    assert "descripcion normalizada al formato APL 2.0 v1.1" in apl.warnings
