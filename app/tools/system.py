"""Tools de sistema: identidad, healthcheck, validacion de etapas APL."""

from __future__ import annotations

import time
from typing import Any

from app.odoo_client import OdooClient
from app.token_registry import ActorEntry


_BOOT_TIME = time.time()


async def odoo_who_am_i(actor: ActorEntry, odoo: OdooClient) -> dict[str, Any]:
    """Identidad del actor. UID se obtiene por authenticate, no se hardcodea.
    NO incluye API Key ni token MCP en la respuesta."""
    uid = await odoo.authenticate(actor)
    creds = await odoo.get_credentials(actor)
    return {
        "actor": actor.actor,
        "role": actor.role,
        "display_name": actor.display_name,
        "odoo_uid": uid,
        "odoo_username": creds.username,  # username si, api_key NO
        "odoo_url": creds.url,
        "odoo_db": creds.db,
        "policy": actor.policy,
    }


async def odoo_health(actor: ActorEntry, odoo: OdooClient) -> dict[str, Any]:
    """Healthcheck minimo MCP + auth Odoo. NO toca tools de negocio."""
    uptime_seconds = int(time.time() - _BOOT_TIME)
    try:
        uid = await odoo.authenticate(actor)
        odoo_auth_ok = bool(uid)
    except Exception as e:  # noqa: BLE001 — healthcheck no propaga.
        return {
            "mcp_status": "up",
            "uptime_seconds": uptime_seconds,
            "odoo_auth_ok": False,
            "odoo_error_class": e.__class__.__name__,
        }
    try:
        version = await odoo.server_version(actor)
    except Exception as e:  # noqa: BLE001
        version = {"error": e.__class__.__name__}
    return {
        "mcp_status": "up",
        "uptime_seconds": uptime_seconds,
        "odoo_auth_ok": odoo_auth_ok,
        "odoo_uid": uid,
        "odoo_server_version": version,
    }


async def odoo_validate_apl_stages(actor: ActorEntry, odoo: OdooClient) -> dict[str, Any]:
    """Lista etapas de project.task.type del To Do personal del actor.
    Util para verificar que el nombre exacto de etapas APL coincide con Odoo
    antes de crear/mover tareas."""
    stages = await odoo.search_read(
        actor,
        "project.task.type",
        [("project_ids", "=", False)],  # etapas personales (sin proyecto)
        ["id", "name", "sequence", "fold"],
        limit=50,
        order="sequence asc",
    )
    return {
        "count": len(stages),
        "stages": stages,
        "notes": "Etapas APL 2.0 esperadas: Inbox, Hoy, Esta semana, Cuando pueda, En espera, Done, Cancelled. Verificar nombres exactos contra docs/APL_STAGES.md.",
    }
