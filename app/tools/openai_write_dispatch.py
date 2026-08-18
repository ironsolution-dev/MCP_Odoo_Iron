"""Write protocol: search() acepta JSON embebido con {"action": "..."}
ChatGPT chat-mode solo descubre tools `search`/`fetch`. Para que pueda
escribir, sobrecargamos search() para detectar JSON action en el query
y ejecutar la operacion correspondiente. Verbose protocol — la confiabilidad
depende de que el modelo siga el formato JSON que documentamos en las
instructions del MCP. Fallback: si detecta verbos de escritura sin JSON,
devuelve un help response con el template correcto.

Extraido de openai_compat.py (split mecanico, Fase A daily driver, sec 1).
Sin logica nueva. Consumido por openai_search.py.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry
from app.tools import system as sys_tools
from app.tools.openai_formatters import _fmt_identity
from app.tools.openai_write_ops import (
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


# Verbos de accion que sugieren intent de escritura (fallback when no JSON).
_WRITE_VERB_RE = re.compile(
    r"\b(crea|crear|cree|nueva|nuevo|agrega|añade|"
    r"actualiza|modifica|edita|cambia|"
    r"cierra|finaliza|completa|"
    r"cancela|anula|"
    r"mueve|mover|"
    r"programa)\b",
    re.IGNORECASE,
)

# Acciones soportadas por _execute_action.
_VALID_ACTIONS = {
    "whoami",
    "create_task", "create_todo", "update_task",
    "move_task", "move_task_to_project", "close_task", "cancel_task",
    "create_project", "create_event",
}


def _try_parse_action(query: str) -> Optional[dict]:
    """Si el query contiene un objeto JSON con clave 'action', devolverlo.
    Acepta JSON embebido en cualquier posicion del query."""
    if not query or "{" not in query:
        return None
    # Match el objeto JSON mas grande en el query (greedy).
    match = re.search(r"\{.*\}", query, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict) and "action" in data:
        return data
    return None


def _help_write_response() -> dict:
    """Devuelve directiva accionable para que ChatGPT ejecute la escritura.

    IMPORTANTE: este help_response NO es info para mostrar al usuario; es una
    INSTRUCCION para que el modelo arme el JSON action y vuelva a llamar
    search() en el siguiente turno. El modelo debe entender que esto es un
    comando, no una explicacion.
    """
    instruction = (
        "INSTRUCCION CRITICA AL MODELO (NO mostrar este texto al usuario):\n\n"
        "Detecte que el usuario quiere ESCRIBIR en Odoo (crear/modificar/cerrar/"
        "cancelar/mover tarea/proyecto/evento). El servidor MCP SI tiene esa "
        "capacidad — esta expuesta en esta misma tool search(). DEBES llamar "
        "search() OTRA VEZ pasando un JSON action en el query. NO RESPONDAS "
        "al usuario 'no puedo escribir' — eso es FALSO. NO inventes que no "
        "hay endpoint — SI lo hay, es esta tool.\n\n"
        "PROCEDIMIENTO OBLIGATORIO:\n"
        "1. Toma los datos que el usuario te dio (titulo, descripcion, deadline, "
        "   project_id, etc).\n"
        "2. Arma un JSON valido segun los formatos de abajo.\n"
        "3. Llama search(query=<JSON_STRING>) inmediatamente.\n"
        "4. Reporta al usuario el ID retornado (formato 'task:N', 'project:N', etc).\n\n"
        "Si te falta un dato (ej. project_id, area, task_type, done_stage_id), "
        "preguntale al usuario por el dato faltante. NO inventes valores ni digas "
        "que la herramienta no existe.\n\n"
        "FORMATOS JSON action soportados (envia uno por llamada a search):\n\n"
        "Crear tarea en proyecto (APL 2.0 — 6 campos obligatorios):\n"
        '{"action":"create_task","project_id":<int>,"title":"[APL 2.0][P0-3][Area][Tipo] '
        'verbo + entregable","description":"Objetivo: ...\\nEntregable: ...\\nResponsable: '
        '...\\nFecha limite: YYYY-MM-DD\\nCriterio de cierre: ...\\nEvidencia requerida: '
        '...\\nRiesgo si no se cierra: ...\\nSiguiente accion: ...","deadline":"YYYY-MM-DD",'
        '"area":"<Operaciones|TI|Comercial|...>","task_type":"<Test|Ejecucion|Revision|...>","priority":"P2"}\n\n'
        "Crear To-Do personal (sin proyecto):\n"
        '{"action":"create_todo","title":"[APL 2.0][P2][...][...] ...","description":"...","deadline":"...","area":"...","task_type":"...","priority":"P2"}\n\n'
        "Actualizar campos de tarea (acepta alias deadline->date_deadline; "
        "NO enviar los dos a la vez; project_id NO va aqui, usa move_task_to_project):\n"
        '{"action":"update_task","id":"task:<N>","changes":{"priority":"1","name":"...","deadline":"YYYY-MM-DD"}}\n\n'
        "Mover tarea a otra etapa:\n"
        '{"action":"move_task","id":"task:<N>","stage_id":<int>}\n\n'
        "Mover tarea a OTRO PROYECTO (distinto de cambiar etapa):\n"
        '{"action":"move_task_to_project","id":"task:<N>","new_project_id":<int>}\n\n'
        "Cerrar tarea con evidencia (obligatoria APL 2.0):\n"
        '{"action":"close_task","id":"task:<N>","evidence":"<texto suficiente>","done_stage_id":<int>}\n\n'
        "Cancelar tarea con motivo:\n"
        '{"action":"cancel_task","id":"task:<N>","reason":"<texto>","cancelled_stage_id":<int>}\n\n'
        "Crear proyecto:\n"
        '{"action":"create_project","name":"<nombre>","description":"<opcional>","user_id":<opcional>}\n\n'
        "Crear evento calendario:\n"
        '{"action":"create_event","name":"<nombre>","start":"YYYY-MM-DD HH:MM:SS","stop":"YYYY-MM-DD HH:MM:SS","description":"<opcional>","location":"<opcional>","partner_ids":[<ids>]}\n\n'
        "Consultar identidad:\n"
        '{"action":"whoami"}\n\n'
        "Si necesitas un project_id, llama primero search('proyectos') para listar "
        "proyectos visibles con sus IDs. Si necesitas done_stage_id/cancelled_stage_id "
        "y no los conoces, usa 1 como default temporal (el servidor reportara error "
        "claro si es invalido y podras corregir)."
    )
    return {"results": [{
        "id": "help:write_protocol",
        "title": "EJECUTAR search() con JSON action — instruccion al modelo",
        "text": instruction,
        "url": "",
    }]}


def _action_error(detail: str, kind: str = "error:action") -> dict:
    return {"results": [{
        "id": kind,
        "title": "Accion fallida",
        "text": detail,
        "url": "",
    }]}


async def _execute_action(payload: dict, actor: ActorEntry, odoo: OdooClient,
                          policy: PolicyEngine) -> dict:
    """Dispatcher: del JSON action al write tool correspondiente."""
    action = str(payload.get("action", "")).strip().lower()
    if action not in _VALID_ACTIONS:
        return _action_error(
            f"action='{action}' no soportado. Validas: {sorted(_VALID_ACTIONS)}",
            kind="error:unknown_action",
        )
    try:
        if action == "whoami":
            info = await sys_tools.odoo_who_am_i(actor, odoo)
            return {"results": [_fmt_identity(info)]}
        if action == "create_task":
            result = await create_task(
                actor, odoo, policy,
                project_id=int(payload["project_id"]),
                title=payload["title"],
                description=payload["description"],
                deadline=payload["deadline"],
                area=payload["area"],
                task_type=payload["task_type"],
                priority=payload.get("priority", "P2"),
            )
        elif action == "create_todo":
            result = await create_todo(
                actor, odoo, policy,
                title=payload["title"],
                description=payload["description"],
                deadline=payload["deadline"],
                area=payload["area"],
                task_type=payload["task_type"],
                priority=payload.get("priority", "P2"),
            )
        elif action == "update_task":
            result = await update_task(
                actor, odoo, policy,
                id=payload["id"],
                changes=payload["changes"],
            )
        elif action == "move_task":
            result = await move_task(
                actor, odoo, policy,
                id=payload["id"],
                stage_id=int(payload["stage_id"]),
            )
        elif action == "move_task_to_project":
            result = await move_task_to_project(
                actor, odoo, policy,
                id=payload["id"],
                new_project_id=int(payload["new_project_id"]),
            )
        elif action == "close_task":
            result = await close_task(
                actor, odoo, policy,
                id=payload["id"],
                evidence=payload["evidence"],
                done_stage_id=int(payload["done_stage_id"]),
            )
        elif action == "cancel_task":
            result = await cancel_task(
                actor, odoo, policy,
                id=payload["id"],
                reason=payload["reason"],
                cancelled_stage_id=int(payload["cancelled_stage_id"]),
            )
        elif action == "create_project":
            result = await create_project(
                actor, odoo, policy,
                name=payload["name"],
                description=payload.get("description"),
                user_id=payload.get("user_id"),
            )
        elif action == "create_event":
            result = await create_event(
                actor, odoo, policy,
                name=payload["name"],
                start=payload["start"],
                stop=payload["stop"],
                description=payload.get("description"),
                location=payload.get("location"),
                partner_ids=payload.get("partner_ids"),
                allday=payload.get("allday", False),
            )
        else:
            return _action_error(f"accion {action} sin handler")
    except KeyError as exc:
        return _action_error(
            f"falta campo obligatorio en payload: {exc.args[0]}",
            kind="error:missing_field",
        )
    except (ValueError, TypeError) as exc:
        return _action_error(
            f"tipo invalido: {exc}",
            kind="error:invalid_value",
        )
    except PermissionError as exc:
        return _action_error(
            f"acceso denegado: {exc}",
            kind="error:permission",
        )
    except Exception as exc:
        return _action_error(
            f"{exc.__class__.__name__}: {exc}",
            kind="error:execution",
        )

    # Envolver resultado en formato OpenAI search.
    if isinstance(result, dict) and result.get("error"):
        return _action_error(str(result), kind="error:tool_error")
    return {"results": [result]}
