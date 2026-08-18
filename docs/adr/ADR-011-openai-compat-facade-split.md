# ADR-011 — Split mecanico de openai_compat.py en facade + 4 modulos

**Estado:** Vigente (Fase A daily driver)
**Fecha:** 2026-08-18

## Contexto

`app/tools/openai_compat.py` llego a 680 lineas, muy por encima del limite de 300 lineas por archivo del repo (anti-sobreingeniería, `CLAUDE.md`). Mezclaba cuatro responsabilidades distintas: clasificacion de intent + formatters, el routing de lectura (`search`/`fetch`), el protocolo de escritura via JSON embebido, y los wrappers thin sobre las tools `odoo_*` de escritura. Seguir sumando funcionalidad (sec G1: `move_task_to_project`) sin partir el archivo lo habria dejado aun mas ilegible.

## Decision

Split puramente mecanico, sin cambiar comportamiento ni el API publico:

- `openai_formatters.py` — `_INTENTS`, `_classify`, `_name_of`, `_fmt_*`, `_full`, `_not_found`.
- `openai_search.py` — `_route`, `search`, `fetch` (READ path).
- `openai_write_dispatch.py` — protocolo JSON `action` de `search()`: `_try_parse_action`, `_help_write_response`, `_action_error`, `_execute_action`.
- `openai_write_ops.py` — wrappers thin sobre las tools `odoo_*` de escritura (`create_task`, `update_task`, `move_task_to_project`, etc).
- `openai_compat.py` queda como **facade**: reexporta el API publico identico via imports explicitos, sin logica propia.

Dependencias en una sola direccion (sin ciclos): `openai_formatters` (sin dependencias internas) ← `openai_write_ops` ← `openai_write_dispatch` ← `openai_search` ← `openai_compat` (facade).

## Consecuencias

- `odoo_mcp_remote.py` no requiere ningun cambio: sigue importando `openai_compat as OC` y usando `OC.search`, `OC.create_task`, etc.
- Cada modulo nuevo queda entre 148 y 257 lineas — bajo el limite.
- La suite de tests (68 tests en el momento del split) paso identica antes y despues: prueba de no-regresion del split mecanico.
- Nuevas acciones de escritura (ej. `move_task_to_project`, sec G1) se agregan tocando 2-3 archivos pequenos y enfocados en vez de un monolito.

## Alternativas descartadas

- Dejar el archivo crecer y declarar deuda: ya hay dos archivos con deuda declarada en este repo (`odoo_mcp_remote.py`, `openai_nl_parser.py`); sumar un tercero de 680+ lineas erosiona el limite como convencion real.
- Reescribir la logica en vez de solo mover codigo: mayor riesgo de regresion sin beneficio adicional en esta fase.
