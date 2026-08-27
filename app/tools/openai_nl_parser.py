"""Parser de lenguaje natural ES -> JSON action para `search()`.

Motivacion (Fase 4, 13-may-2026): ChatGPT chat-mode recibe `_help_write_response()`
y NO reintenta con JSON action — se rinde y devuelve markdown al usuario diciendo
"no puedo escribir". Confirmado en audit.jsonl: latency_ms=0, result_count=1
repetidos sin entries con `model: project.task`.

Solucion: mover la inteligencia al servidor. Cuando llega un query con verbos
de escritura SIN JSON, intentamos extraer la accion + campos via heuristicas
regex. Si extraemos suficiente, ejecutamos directo. Si no, caemos al help.

Mantiene APL 2.0 obligatorio: auto-genera titulo estructurado y descripcion
con los 8 campos requeridos cuando el usuario solo da el nucleo del titulo.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

from app.apl_description import render_apl_description
from app.apl_labels import resolve_priority
from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry


# ---------------------------------------------------------------------------
# Regex de extraccion
# ---------------------------------------------------------------------------

# Texto entre comillas simples o dobles (titulo del usuario).
_QUOTED_RE = re.compile(r"['\"“”‘’]([^'\"“”‘’]{2,200})['\"“”‘’]")

# task:42 | tarea 42 | ticket 42 | id 42
_TASK_ID_RE = re.compile(
    r"\btask:(\d+)\b|\b(?:tarea|ticket|task)\s+(?:id\s*=?\s*)?(\d+)\b",
    re.IGNORECASE,
)

# proyecto 3 | proyecto id=3 | proyecto "Gerente de Operaciones" | proyecto Gerente de Operaciones
_PROJECT_NUM_RE = re.compile(
    r"\b(?:proyecto|project)\s+(?:id\s*=?\s*)?(\d+)\b",
    re.IGNORECASE,
)
_PROJECT_NAME_RE = re.compile(
    r"\b(?:en\s+(?:el\s+)?)?(?:proyecto|project)\s+"
    r"['\"“”]?([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9 \-_]{1,60}?)"
    r"['\"“”]?(?=\s*(?:etapa|stage|backlog|to.?do|con|para|el|deadline|prioridad|$|\n|,|\.))",
    re.IGNORECASE,
)

# etapa 5 | stage 5
_STAGE_REF_RE = re.compile(r"\b(?:etapa|stage)\s+(?:id\s*=?\s*)?(\d+)\b", re.IGNORECASE)

# evidencia: ... | evidencia ...
# Bug fix v0.3.5: el lookahead NO debe terminar en `\.` literal porque
# rompe con evidencias que contienen puntos internos (v0.3.4, URLs,
# abreviaciones tipo "Dr.", fechas, etc.). Verificado QA 13-may-2026:
# evidencia "Auditoria final v0.3.4 ejecutada..." quedaba cortada a
# "Auditoria final v0" (18 chars < 20 minimo del validador).
# Ahora terminamos solo en keywords explícitos o fin de línea/string.
_EVIDENCE_RE = re.compile(
    r"\bevidencia[:\s]+(.{10,500}?)(?=\s*(?:done_stage|stage_id|$|\n))",
    re.IGNORECASE | re.DOTALL,
)

# motivo: ... | razon: ...
# Bug fix v0.3.5: mismo motivo que evidencia — no cortar en punto literal.
_REASON_RE = re.compile(
    r"\b(?:motivo|raz[oó]n)[:\s]+(.{3,500}?)(?=\s*(?:cancelled|stage_id|$|\n))",
    re.IGNORECASE | re.DOTALL,
)

# deadline YYYY-MM-DD | fecha limite YYYY-MM-DD | para el YYYY-MM-DD
_DEADLINE_RE = re.compile(
    r"\b(?:deadline|fecha\s*l[ií]mite|para\s+el|el\s+d[ií]a|vence)[:\s]+(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

# prioridad alta | priority p2 | importancia media
_PRIORITY_RE = re.compile(
    r"\b(?:prioridad|priority|importancia)[:\s]+(p[0-3]|alta|media|baja|normal)\b",
    re.IGNORECASE,
)
# Palabra extraida del NL -> codigo canonico P0-P3. La estrella real sale de
# app.apl_labels.resolve_priority (fuente unica, ticket 737): antes este
# modulo tenia su propio dict de estrellas duplicado con el mismo bug de
# tasks.py (P0 y P1 compartian '2'); ahora solo mapea a P0-P3 y delega.
_PRIORITY_WORD_TO_CODE = {
    "p0": "P0", "p1": "P1", "p2": "P2", "p3": "P3",
    "alta": "P1", "media": "P2", "normal": "P2", "baja": "P3",
}

# Verbos por accion (para detectar intent).
_RE_CLOSE = re.compile(
    r"\b(cierra|cerrar|finaliza|finalizar|completa|completar|"
    r"marca\s+como\s+(?:hech|terminad|complet))",
    re.IGNORECASE,
)
_RE_CANCEL = re.compile(r"\b(cancela|cancelar|anula|anular|descarta)", re.IGNORECASE)
_RE_MOVE = re.compile(
    r"\b(mueve|mover|cambia\s+(?:etapa|stage)|pasa\s+(?:a|al))",
    re.IGNORECASE,
)
_RE_UPDATE = re.compile(
    r"\b(actualiza|actualizar|modifica|modificar|edita|editar|"
    r"cambia(?!\s+(?:etapa|stage)))",
    re.IGNORECASE,
)
_RE_CREATE_PROJECT = re.compile(
    r"\b(crea|crear|nuev[oa]|registra)\s+(?:un\s+)?proyecto", re.IGNORECASE,
)
_RE_CREATE_TODO = re.compile(
    r"\b(crea|crear|nuev[oa]|agrega|añade|registra)\s+(?:un\s+|una\s+)?"
    r"(to.?do|pendiente|recordatorio)",
    re.IGNORECASE,
)
_RE_CREATE_TASK = re.compile(
    r"\b(crea|crear|nuev[oa]|agrega|añade|registra)\s+(?:una?\s+)?"
    r"(tarea|ticket|task)",
    re.IGNORECASE,
)
_RE_WHOAMI = re.compile(
    r"\b(quien\s+soy|who\s+am\s+i|mi\s+identidad|mis\s+datos|mi\s+rol|mi\s+policy)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Builders APL 2.0
# ---------------------------------------------------------------------------

def _build_apl_title(title_core: str) -> str:
    """Limpia el titulo extraido del NL. Ticket 737 / ADR-016: el formato
    nuevo es texto estructural sin prefijos — ya NO se envuelve en
    `[APL 2.0][Px][Area][Tipo]` (ese formato queda legado, sec 7 de la guia
    APL 2.0 V2 v1.1). `app.apl_title.normalize_apl_title` sigue aceptando
    un titulo legado completo si el usuario lo escribio asi."""
    if not title_core:
        return ""
    return title_core.strip().strip("\"'“”‘’")


def _build_apl_description(title_core: str, deadline: str,
                            extra_context: str = "") -> str:
    """Genera descripcion APL 2.0 con los 8 campos obligatorios via el
    escritor unico `app.apl_description.render_apl_description` (ticket 737)
    en vez de reimplementar el formato.

    Usa el titulo como semilla para Objetivo/Entregable y placeholders
    descriptivos para el resto. El usuario puede editar luego."""
    core = (title_core or "tarea").strip()
    return render_apl_description(
        responsable="actor activo (ver who_am_i)",
        objetivo=core,
        entregable=f"ejecucion y validacion de '{core}'",
        fecha_limite=deadline,
        criterio_de_cierre="tarea ejecutada y verificada en sistema",
        evidencia_requerida="captura, link o validacion en chatter",
        riesgo_si_no_se_cierra="bloqueo de flujo operativo dependiente",
        siguiente_accion="validar y reportar al responsable",
        dependencias=extra_context or None,
    )


# ---------------------------------------------------------------------------
# Extractores
# ---------------------------------------------------------------------------

def _extract_task_id(query: str) -> Optional[int]:
    m = _TASK_ID_RE.search(query)
    if not m:
        return None
    for g in m.groups():
        if g:
            return int(g)
    return None


def _extract_title_core(query: str, after_keywords: tuple[str, ...]) -> Optional[str]:
    """Extrae nucleo del titulo. Prefiere texto entrecomillado.
    Si no, toma lo que sigue al keyword hasta separadores comunes."""
    qm = _QUOTED_RE.search(query)
    if qm:
        cand = qm.group(1).strip()
        if cand and len(cand) >= 2:
            return cand
    for kw in after_keywords:
        pattern = re.compile(
            rf"\b{kw}\s+(?:de\s+|llamad[oa]\s+|titulad[oa]\s+)?"
            rf"(.+?)(?=\s+(?:en|del|para|con|el|la|los|las|proyecto|etapa|"
            rf"deadline|fecha|prioridad|$|\n|,|\.|;))",
            re.IGNORECASE,
        )
        m = pattern.search(query)
        if m:
            cand = m.group(1).strip().strip("\"'“”‘’")
            # Evitar capturar pronombres/articulos sueltos
            if cand and len(cand) >= 2 and cand.lower() not in {
                "de", "un", "una", "el", "la", "los", "las", "mi", "su",
                "prueba", "test",
            }:
                return cand
    return None


async def _resolve_project_id(query: str, actor: ActorEntry,
                               odoo: OdooClient) -> Optional[int]:
    """Resuelve project_id desde el query.
    Acepta forma numerica ('proyecto 3') o por nombre ('proyecto Gerente...')."""
    m = _PROJECT_NUM_RE.search(query)
    if m:
        return int(m.group(1))
    m = _PROJECT_NAME_RE.search(query)
    if m:
        name = m.group(1).strip().strip("\"'“”‘’")
        if not name or len(name) < 3:
            return None
        try:
            rows = await odoo.search_read(
                actor, "project.project",
                [("name", "ilike", name)],
                ["id", "name"], limit=1,
            )
            if rows:
                return int(rows[0]["id"])
        except Exception:
            return None
    return None


def _extract_priority_change(query: str) -> Optional[str]:
    """Extrae la estrella de prioridad (para `update_task`) desde la
    palabra en el query. Delega el codigo -> estrella a
    `app.apl_labels.resolve_priority` (fuente unica, ticket 737)."""
    m = _PRIORITY_RE.search(query)
    if not m:
        return None
    code = _PRIORITY_WORD_TO_CODE.get(m.group(1).lower())
    if not code:
        return None
    _, star = resolve_priority(code)
    return star


def _extract_deadline(query: str, default_iso: str) -> str:
    m = _DEADLINE_RE.search(query)
    if m:
        return m.group(1)
    return default_iso


# ---------------------------------------------------------------------------
# Public: try_parse
# ---------------------------------------------------------------------------

async def try_parse(query: str, actor: ActorEntry, odoo: OdooClient,
                     policy: PolicyEngine) -> Optional[dict]:
    """Intenta parsear query natural a un payload action dict.

    Devuelve dict {action, ...} si extrajo suficientes campos para ejecutar.
    Devuelve None si el query es ambiguo o le faltan datos minimos (en cuyo
    caso el caller deberia devolver `_help_write_response()` para que el
    modelo aprenda el formato JSON).

    Acciones soportadas en NL:
    - whoami
    - close_task (necesita task_id + evidencia)
    - cancel_task (necesita task_id + motivo)
    - move_task (necesita task_id + stage)
    - update_task (solo cambio de prioridad por ahora)
    - create_project (necesita nombre)
    - create_todo (necesita titulo)
    - create_task (necesita project_id + titulo)
    """
    if not query or not query.strip():
        return None

    q = query.strip()
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()

    # WHOAMI — precedencia alta, query corto
    if _RE_WHOAMI.search(q):
        return {"action": "whoami"}

    # CLOSE TASK
    if _RE_CLOSE.search(q):
        tid = _extract_task_id(q)
        ev = _EVIDENCE_RE.search(q)
        if tid and ev:
            return {
                "action": "close_task",
                "id": f"task:{tid}",
                "evidence": ev.group(1).strip().rstrip(",.;"),
                "done_stage_id": 1,
            }
        return None  # ambiguo -> help

    # CANCEL TASK
    if _RE_CANCEL.search(q):
        tid = _extract_task_id(q)
        rs = _REASON_RE.search(q)
        if tid and rs:
            return {
                "action": "cancel_task",
                "id": f"task:{tid}",
                "reason": rs.group(1).strip().rstrip(",.;"),
                "cancelled_stage_id": 1,
            }
        return None

    # MOVE TASK
    if _RE_MOVE.search(q):
        tid = _extract_task_id(q)
        sm = _STAGE_REF_RE.search(q)
        if tid and sm:
            return {
                "action": "move_task",
                "id": f"task:{tid}",
                "stage_id": int(sm.group(1)),
            }
        return None

    # UPDATE TASK (solo prioridad por ahora)
    if _RE_UPDATE.search(q):
        tid = _extract_task_id(q)
        new_pri = _extract_priority_change(q)
        if tid and new_pri:
            return {
                "action": "update_task",
                "id": f"task:{tid}",
                "changes": {"priority": new_pri},
            }
        return None

    # CREATE PROJECT
    if _RE_CREATE_PROJECT.search(q):
        name = _extract_title_core(q, ("proyecto", "project"))
        if name:
            return {"action": "create_project", "name": name}
        return None

    # CREATE TODO (sin proyecto). Importante: orden antes que create_task
    # porque 'todo' es mas especifico.
    if _RE_CREATE_TODO.search(q):
        title_core = _extract_title_core(q, ("todo", "to-do", "pendiente", "recordatorio"))
        if title_core:
            deadline = _extract_deadline(q, tomorrow)
            return {
                "action": "create_todo",
                "title": _build_apl_title(title_core),
                "description": _build_apl_description(title_core, deadline),
                "deadline": deadline,
                "area": "Personal",
                "task_type": "Test",
                "priority": "P2",
            }
        return None

    # CREATE TASK (en proyecto)
    if _RE_CREATE_TASK.search(q):
        pid = await _resolve_project_id(q, actor, odoo)
        title_core = _extract_title_core(q, ("tarea", "ticket", "task"))
        if not pid or not title_core:
            return None  # faltan datos minimos
        deadline = _extract_deadline(q, tomorrow)
        return {
            "action": "create_task",
            "project_id": pid,
            "title": _build_apl_title(title_core),
            "description": _build_apl_description(title_core, deadline),
            "deadline": deadline,
            "area": "Operaciones",
            "task_type": "Ejecucion",
            "priority": "P2",
        }

    return None
