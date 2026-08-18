"""Clasificacion de intent + formatters Odoo dict -> OpenAI search result.

Extraido de openai_compat.py (split mecanico, Fase A daily driver, sec 1).
Sin logica nueva: mismas funciones, mismo comportamiento. Consumido por
openai_search.py (READ path) y openai_write_ops.py (envoltura de resultados
de escritura).
"""

from __future__ import annotations

import re
from typing import Any


# Patrones de intent en orden de precedencia. El primero que matchea decide.
# "tasks_overdue" antes que "tasks_my" porque "tareas vencidas" matchea ambos.
_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    # Identity primero — frases cortas que matchean otros intents (ej. "soy")
    ("identity",        re.compile(r"\b(quien soy|who am i|mi identidad|mis datos|mi rol|mi policy|identidad odoo)\b", re.I)),
    ("tasks_overdue",   re.compile(r"\b(vencid|overdue|atrasad|retras)", re.I)),
    ("tasks_my",        re.compile(r"\b(mis tareas|tarea|todo|to.?do|pendient|asignad)", re.I)),
    ("projects",        re.compile(r"\b(proyecto|project)", re.I)),
    ("employees",       re.compile(r"\b(empleado|equipo|colega|colabora|staff|personal|team)", re.I)),
    ("partners",        re.compile(r"\b(contacto|cliente|partner|proveedor|empresa)", re.I)),
    ("crm_leads",       re.compile(r"\b(lead|oportunidad|crm|prospect)", re.I)),
    ("calendar_events", re.compile(r"\b(evento|calendar|reuni|cita|agenda|meeting)", re.I)),
]


def _classify(query: str) -> str:
    """Devuelve el intent matched o 'default' (overview)."""
    if not query:
        return "default"
    for kind, pattern in _INTENTS:
        if pattern.search(query):
            return kind
    return "default"


# ---------------------------------------------------------------------------
# Formatters Odoo dict -> OpenAI search result {id, title, text, url}
# ---------------------------------------------------------------------------

def _name_of(m2o: Any) -> str:
    """Extrae name de un many2one normalizado por OdooClient ({id, name})."""
    if isinstance(m2o, dict):
        return m2o.get("name") or ""
    return ""


def _fmt_task(r: dict) -> dict:
    project = _name_of(r.get("project_id")) or "Personal"
    deadline = r.get("date_deadline") or "sin fecha"
    return {
        "id": f"task:{r.get('id')}",
        "title": r.get("name") or "(sin titulo)",
        "text": f"Proyecto: {project} | Deadline: {deadline} | "
                f"{(r.get('description') or '')[:200]}",
        "url": "",
    }


def _fmt_project(r: dict) -> dict:
    return {
        "id": f"project:{r.get('id')}",
        "title": r.get("name") or "(sin nombre)",
        "text": (r.get("description") or "")[:300],
        "url": "",
    }


def _fmt_employee(r: dict) -> dict:
    return {
        "id": f"employee:{r.get('id')}",
        "title": r.get("name") or "(sin nombre)",
        "text": f"{_name_of(r.get('job_id'))} | {_name_of(r.get('department_id'))} | "
                f"{r.get('work_email') or ''}",
        "url": "",
    }


def _fmt_partner(r: dict) -> dict:
    return {
        "id": f"partner:{r.get('id')}",
        "title": r.get("display_name") or r.get("name") or "(sin nombre)",
        "text": f"{r.get('email') or ''} | {r.get('phone') or ''} | "
                f"{r.get('city') or ''}",
        "url": "",
    }


def _fmt_lead(r: dict) -> dict:
    return {
        "id": f"lead:{r.get('id')}",
        "title": r.get("name") or "(sin titulo)",
        "text": f"Etapa: {_name_of(r.get('stage_id')) or 'sin'} | "
                f"{r.get('email_from') or ''} | {r.get('phone') or ''}",
        "url": "",
    }


def _fmt_event(r: dict) -> dict:
    return {
        "id": f"event:{r.get('id')}",
        "title": r.get("name") or "(sin titulo)",
        "text": f"{r.get('start') or ''} -> {r.get('stop') or ''} | "
                f"{r.get('location') or ''}",
        "url": "",
    }


def _fmt_identity(info: dict) -> dict:
    """Identidad del actor formato OpenAI search."""
    return {
        "id": f"identity:{info.get('actor', 'unknown')}",
        "title": f"Identidad: {info.get('display_name') or info.get('actor')}",
        "text": (
            f"Actor MCP: {info.get('actor')} | "
            f"Rol: {info.get('role')} | "
            f"Policy efectiva: {info.get('policy')} | "
            f"UID Odoo: {info.get('odoo_uid')} | "
            f"Username Odoo: {info.get('odoo_username')} | "
            f"Odoo: {info.get('odoo_db')} @ {info.get('odoo_url')}"
        ),
        "url": "",
    }


def _full(rec: dict, kind: str) -> dict:
    title_map = {
        "task": rec.get("name"),
        "project": rec.get("name"),
        "employee": rec.get("name"),
        "partner": rec.get("display_name") or rec.get("name"),
        "lead": rec.get("name"),
    }
    return {
        "id": f"{kind}:{rec.get('id')}",
        "title": title_map.get(kind) or "",
        "text": rec.get("description") or "",
        "url": "",
        "metadata": rec,
    }


def _not_found(id: str, rec: Any) -> dict:
    err = (rec or {}).get("error") if isinstance(rec, dict) else None
    return {"id": id, "error": err or "not_found"}
