"""Tests del hotfix extract_write_id (ticket 737, ronda 2, hallazgo F1).

F1 era BLOQUEANTE: el contenedor odoo-mcp-v2 en VPS82 corria
odoo-mcp:multiuser-v0.4.3 con `OdooWriteResultError` + `extract_write_id`
en app/odoo_client.py, que NO existia en git (drift de produccion, sec
Anti-Frankenstack regla 1 "en git o no existe"). Rescatado en la rama
rescate/multiuser-v0.4.3 y fusionado aqui.

Esta suite cubre dos cosas separadas:
1. `extract_write_id` en si (unitario: int/list/dict/anidado/errores).
2. Que los create() de app/tools/tasks.py sigan pasando por el
   normalizador (grep-test: si alguien vuelve a escribir
   `new_id = await odoo.create(...)` directo, sin extract_write_id, el
   test falla ANTES de que se repita el incidente 20-ago-2026 — TypeError
   despues de que el registro ya quedo creado en Odoo).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.odoo_client import OdooWriteResultError, extract_write_id


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Unitarios de extract_write_id
# ---------------------------------------------------------------------------

def test_extract_write_id_de_int_directo():
    """create()/write() estandar sobre XML-RPC: retorno ya es int."""
    assert extract_write_id(302644) == 302644


def test_extract_write_id_de_lista():
    """message_post/action_done via odoo.call: retorno es recordset
    marshallado como lista de ids (el caso real del incidente 20-ago)."""
    assert extract_write_id([302644]) == 302644


def test_extract_write_id_de_lista_anidada():
    """Un solo nivel de anidamiento tambien se resuelve (recursion)."""
    assert extract_write_id([[302644]]) == 302644


def test_extract_write_id_de_tupla():
    assert extract_write_id((302644,)) == 302644


def test_extract_write_id_de_dict_con_id():
    assert extract_write_id({"id": 302644, "name": "irrelevante"}) == 302644


def test_extract_write_id_rechaza_bool():
    """bool es subclase de int en Python pero NUNCA es un id valido de Odoo
    (create() jamas devuelve True/False; solo una escritura fallida podria
    parecerlo). Debe fallar ruidoso, no colarse como 1/0."""
    with pytest.raises(OdooWriteResultError):
        extract_write_id(True)
    with pytest.raises(OdooWriteResultError):
        extract_write_id(False)


def test_extract_write_id_rechaza_lista_vacia():
    with pytest.raises(OdooWriteResultError):
        extract_write_id([])


def test_extract_write_id_rechaza_dict_sin_id():
    with pytest.raises(OdooWriteResultError):
        extract_write_id({"name": "sin id"})


def test_extract_write_id_rechaza_tipo_no_soportado():
    """string, None, float u otro tipo inesperado -> falla ruidoso, nunca
    None en silencio (sec Anti-Frankenstack regla 4: el fallo se ve)."""
    with pytest.raises(OdooWriteResultError):
        extract_write_id(None)
    with pytest.raises(OdooWriteResultError):
        extract_write_id("302644")
    with pytest.raises(OdooWriteResultError):
        extract_write_id(3.14)


def test_extract_write_id_incluye_contexto_en_el_mensaje():
    """El contexto ayuda a diagnosticar CUAL create() revento sin tener que
    adivinar por el traceback."""
    with pytest.raises(OdooWriteResultError) as exc:
        extract_write_id(None, context="odoo_create_my_todo_apl:create")
    assert "odoo_create_my_todo_apl:create" in str(exc.value)


# ---------------------------------------------------------------------------
# Grep-test: create() en tasks.py DEBE pasar por extract_write_id
# ---------------------------------------------------------------------------

def test_create_en_tasks_py_pasa_por_extract_write_id():
    """Guardia anti-regresion del hallazgo F1. Cada `await odoo.create(`
    en app/tools/tasks.py debe estar seguido, en las 2 lineas siguientes,
    por una llamada a `extract_write_id(` que consume su resultado —
    nunca `new_id = await odoo.create(...)` directo (ese fue el bug real
    que produccion ya habia parchado sin que git se enterara)."""
    path = REPO_ROOT / "app" / "tools" / "tasks.py"
    lines = path.read_text(encoding="utf-8").splitlines()

    create_call_re = re.compile(r"await\s+odoo\.create\(")
    direct_assign_re = re.compile(r"^\s*new_id\s*=\s*await\s+odoo\.create\(")

    create_call_lines = [i for i, line in enumerate(lines) if create_call_re.search(line)]
    assert create_call_lines, f"no se encontro ningun await odoo.create( en {path}"

    for idx in create_call_lines:
        assert not direct_assign_re.match(lines[idx]), (
            f"{path}:{idx + 1} asigna new_id directo desde odoo.create() "
            "sin pasar por extract_write_id (regresion del hallazgo F1 / "
            "incidente 20-ago-2026)"
        )
        window = "\n".join(lines[idx: idx + 3])
        assert "extract_write_id(" in window, (
            f"{path}:{idx + 1} — await odoo.create(...) sin extract_write_id "
            "en las 2 lineas siguientes (regresion del hallazgo F1)"
        )


def test_tasks_py_importa_extract_write_id_de_odoo_client():
    path = REPO_ROOT / "app" / "tools" / "tasks.py"
    text = path.read_text(encoding="utf-8")
    assert re.search(r"from app\.odoo_client import[^\n]*extract_write_id", text), (
        f"{path} no importa extract_write_id desde app.odoo_client"
    )
