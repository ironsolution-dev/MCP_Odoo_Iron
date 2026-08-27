"""Tests ticket 737: normalizacion dual de titulo (ADR-016).

Compatibilidad gradual (decision del PM anotada en el ticket): se acepta
titulo legado CON corchetes y titulo nuevo SIN corchetes; se normaliza y se
avisa cuando aplica. Cubre el criterio de aceptacion 1 y 2 del diseno.
"""

from __future__ import annotations

import pytest

from app.apl_title import normalize_apl_title
from app.schemas import ValidationError


# ---------------------------------------------------------------------------
# Formato legado
# ---------------------------------------------------------------------------

def test_legado_completo_se_normaliza_y_extrae_metadata():
    result = normalize_apl_title(
        "[APL 2.0][P0][RRHH][Documentacion] Emitir memorandum"
    )
    assert result.clean_title == "Emitir memorandum"
    assert result.priority == "P0"
    assert result.area == "RRHH"
    assert result.task_type == "Documentacion"
    assert result.is_legacy is True
    assert result.warning is not None
    assert "normalizado" in result.warning.lower()


def test_legado_es_case_insensitive_en_el_prefijo():
    result = normalize_apl_title(
        "[apl 2.0][P1][Tecnologia][Entregable] Configurar servidor"
    )
    assert result.is_legacy is True
    assert result.clean_title == "Configurar servidor"


def test_legado_sin_texto_tras_los_corchetes_falla():
    with pytest.raises(ValidationError):
        normalize_apl_title("[APL 2.0][P1][Area][Tipo]   ")


# ---------------------------------------------------------------------------
# Formato nuevo (ADR-016 — regla estructural, no lista cerrada de verbos)
# ---------------------------------------------------------------------------

def test_nuevo_titulo_sin_corchetes_se_acepta_intacto():
    result = normalize_apl_title("Emitir memorandum a Ana Perez por tardanzas")
    assert result.clean_title == "Emitir memorandum a Ana Perez por tardanzas"
    assert result.priority is None
    assert result.area is None
    assert result.task_type is None
    assert result.is_legacy is False
    assert result.warning is None


def test_nuevo_titulo_cualquier_verbo_es_valido_no_lista_cerrada():
    """ADR-016: el backend valida ESTRUCTURA, no el verbo. Un titulo que no
    empieza con uno de los verbos sugeridos por la guia sigue siendo valido."""
    result = normalize_apl_title("Reunion con proveedor de insumos")
    assert result.is_legacy is False
    assert result.clean_title == "Reunion con proveedor de insumos"


def test_nuevo_titulo_140_caracteres_limite():
    exactly_140 = "a" * 140
    result = normalize_apl_title(exactly_140)
    assert result.clean_title == exactly_140

    too_long = "a" * 141
    with pytest.raises(ValidationError):
        normalize_apl_title(too_long)


def test_nuevo_titulo_con_salto_de_linea_falla():
    with pytest.raises(ValidationError):
        normalize_apl_title("Primera linea\nSegunda linea")


# ---------------------------------------------------------------------------
# Rechazo: ni legado ni nuevo (sin regresion)
# ---------------------------------------------------------------------------

def test_titulo_vacio_falla():
    with pytest.raises(ValidationError):
        normalize_apl_title("")
    with pytest.raises(ValidationError):
        normalize_apl_title("   ")


def test_titulo_con_corchete_mal_formado_falla_no_se_interpreta_como_nuevo():
    """Empieza con '[' pero no matchea el patron legado completo: se
    rechaza en vez de aceptarse como titulo nuevo (evita que un legado roto
    pase silenciosamente)."""
    for bad in [
        "[APL 2.0] sin prioridad ni area ni tipo",
        "[APL 2.0][P1] sin area ni tipo",
        "[P1][Area][Tipo] sin tag APL 2.0",
        "[algo suelto]",
    ]:
        with pytest.raises(ValidationError):
            normalize_apl_title(bad)
