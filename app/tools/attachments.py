"""Tools de ir.attachment — lectura de adjuntos asociados a registros.

NO escribe, NO elimina. Devuelve metadatos suficientes para que el actor
pueda referenciar o descargar manualmente. La URL de descarga es relativa
a la instancia Odoo y requiere sesion autenticada en navegador del actor.
"""

from __future__ import annotations

from typing import Optional

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry


# Campos seguros para listar adjuntos. NO incluye `datas` (binario en base64,
# explota tokens del LLM). Si se necesita descargar, usar la URL devuelta.
ATTACHMENT_SAFE_FIELDS: list[str] = [
    "id", "name", "mimetype", "file_size", "create_date", "create_uid",
    "res_model", "res_id", "url", "type", "description",
]


def _ensure_policy(policy: PolicyEngine, actor: ActorEntry, tool: str) -> None:
    decision = policy.allows(actor.policy, tool, "ir.attachment", "read",
                              fields=ATTACHMENT_SAFE_FIELDS)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


async def odoo_list_attachments(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                 model: str, record_id: int, limit: int = 50) -> list[dict]:
    """Lista adjuntos (ir.attachment) asociados a un registro de cualquier modelo
    accesible para el actor. Devuelve metadatos + URL de descarga relativa.

    Args:
        model: por ejemplo 'project.task' o 'project.project'.
        record_id: ID del registro.
        limit: maximo de adjuntos a devolver.
    """
    _ensure_policy(policy, actor, "odoo_list_attachments")
    domain = [("res_model", "=", model), ("res_id", "=", record_id)]
    rows = await odoo.search_read(actor, "ir.attachment", domain,
                                   ATTACHMENT_SAFE_FIELDS, limit=limit,
                                   order="create_date desc")
    creds = await odoo.get_credentials(actor)
    base_url = creds.url.rstrip("/")
    for r in rows:
        if r.get("type") == "binary" and r.get("id"):
            r["download_url"] = f"{base_url}/web/content/{r['id']}?download=true"
    return rows


async def odoo_get_attachment(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                               attachment_id: int) -> dict:
    """Detalle de un adjunto por ID. No devuelve el binario, solo metadatos + URL."""
    _ensure_policy(policy, actor, "odoo_get_attachment")
    rows = await odoo.search_read(actor, "ir.attachment", [("id", "=", attachment_id)],
                                   ATTACHMENT_SAFE_FIELDS, limit=1)
    if not rows:
        return {"error": "attachment_not_found", "attachment_id": attachment_id}
    r = rows[0]
    creds = await odoo.get_credentials(actor)
    base_url = creds.url.rstrip("/")
    if r.get("type") == "binary":
        r["download_url"] = f"{base_url}/web/content/{r['id']}?download=true"
    return r
