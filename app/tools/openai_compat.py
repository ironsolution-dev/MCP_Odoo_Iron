"""Adapter ChatGPT chat-mode: tools `search(query)` y `fetch(id)`.

Motivacion (verificado 13-may-2026 con audit.jsonl + screenshots de Yuniesky):
ChatGPT en modo chat estandar solo descubre tools cuyo nombre matchea el patron
`search` + `fetch` que OpenAI documenta para connectors MCP. Tools con nombres
custom (`odoo_my_tasks`, `odoo_list_projects`, ...) son INVISIBLES para el modelo
incluso con el conector activo. Claude.ai en cambio implementa MCP completo y
ve las 30 tools sin filtro.

FACADE (split mecanico, Fase A daily driver, sec 1): este modulo ya no
contiene logica propia. Es un punto de entrada unico que reexporta el API
publico identico al que existia antes del split, repartido en:

- openai_formatters.py — clasificacion de intent + formatters dict->OpenAI.
- openai_search.py     — `search()` / `fetch()` y el routing READ.
- openai_write_dispatch.py — protocolo JSON action de `search()`.
- openai_write_ops.py  — wrappers thin sobre las tools odoo_* de escritura.

Las 30 tools nativas SIGUEN registradas para Claude.ai. Esto NO las reemplaza.
No agrega capacidad nueva: solo expone la existente con nombres que ChatGPT
puede descubrir. Sec 4.1 ADR-010 (dual connector Claude.ai+ChatGPT).
"""

from __future__ import annotations

from app.tools.openai_formatters import (  # noqa: F401
    _INTENTS,
    _classify,
    _fmt_employee,
    _fmt_event,
    _fmt_identity,
    _fmt_lead,
    _fmt_partner,
    _fmt_project,
    _fmt_task,
    _full,
    _name_of,
    _not_found,
)
from app.tools.openai_search import fetch, search  # noqa: F401
from app.tools.openai_write_dispatch import (  # noqa: F401
    _VALID_ACTIONS,
    _WRITE_VERB_RE,
    _action_error,
    _execute_action,
    _help_write_response,
    _try_parse_action,
)
from app.tools.openai_write_ops import (  # noqa: F401
    _parse_id,
    cancel_task,
    close_task,
    create_event,
    create_project,
    create_task,
    create_todo,
    move_task,
    move_task_to_project,
    update_task,
)
