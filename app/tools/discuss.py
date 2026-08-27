"""Tools de Discuss (sec G4, Fase A daily driver): leer/postear mensajes de
un canal y copiar un adjunto de un mensaje hacia una tarea.

Discuss NO es un modelo propio de Odoo: los mensajes de un canal viven en
`mail.message` con `model='discuss.channel'` y `res_id=<channel_id>`.

Fase 1: solo canales EXPLICITAMENTE allowlisted por policy
(`policy.discuss_channel_allowed`); ausencia de allowlist = deny para todos
los canales, sin excepcion. `odoo_attach_discuss_attachment_to_task` SIEMPRE
copia, nunca mueve: el adjunto y el mensaje origen quedan intactos.
"""

from __future__ import annotations

from typing import Optional

from app.odoo_client import OdooClient, extract_write_id
from app.policy_engine import PolicyEngine
from app.schemas import ValidationError
from app.token_registry import ActorEntry


DISCUSS_MESSAGE_SAFE_FIELDS: list[str] = [
    "id", "body", "author_id", "date", "message_type", "attachment_ids",
]

# Metadatos de ir.attachment que se leen ANTES del binario (para poder negar
# por tamano sin gastar el round-trip de traer `datas`).
ATTACHMENT_META_FIELDS: list[str] = [
    "id", "name", "mimetype", "file_size", "res_model", "res_id",
]

DEFAULT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _ensure_policy(policy: PolicyEngine, actor: ActorEntry, tool: str, model: str,
                   action: str, fields: Optional[list[str]] = None) -> None:
    decision = policy.allows(actor.policy, tool, model, action, fields=fields)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


def _ensure_channel_allowed(policy: PolicyEngine, actor: ActorEntry, channel_id: int) -> None:
    decision = policy.discuss_channel_allowed(actor.policy, channel_id)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


# ---------------------------------------------------------------------------
# Lectura / escritura de mensajes
# ---------------------------------------------------------------------------

async def odoo_read_discuss_channel(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                    channel_id: int, limit: int = 50) -> list[dict]:
    """Lee mensajes de un canal de Discuss (mail.message, model=discuss.channel).
    Solo canales explicitamente allowlisted por policy — un canal fuera de la
    lista se deniega aunque el ID exista y sea alcanzable en Odoo."""
    _ensure_policy(policy, actor, "odoo_read_discuss_channel", "mail.message", "read",
                  fields=DISCUSS_MESSAGE_SAFE_FIELDS)
    _ensure_channel_allowed(policy, actor, channel_id)
    domain = [("model", "=", "discuss.channel"), ("res_id", "=", channel_id)]
    return await odoo.search_read(actor, "mail.message", domain, DISCUSS_MESSAGE_SAFE_FIELDS,
                                  limit=limit, order="date desc")


async def odoo_post_discuss_message(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                    channel_id: int, body: str) -> dict:
    """Posta un mensaje de texto plano en un canal de Discuss allowlisted.
    El id que retorna `message_post` se usa para el read-after-write.

    OJO: `message_post` NO es create/write — es un metodo custom, y su
    retorno via XML-RPC llega como lista de ids (`[302644]`), no como int
    (a diferencia de `odoo.create`). `int()` directo sobre eso revienta
    DESPUES de que el mensaje ya quedo posteado en Odoo: el falso negativo
    mas caro que hay, porque el reflejo de reintentar duplica el mensaje.
    `extract_write_id` normaliza list/dict/int de forma unica (sec G4,
    incidente 20-ago-2026: 3 TypeError en produccion, mensaje entregado
    las 3 veces)."""
    _ensure_policy(policy, actor, "odoo_post_discuss_message", "mail.message", "create")
    _ensure_channel_allowed(policy, actor, channel_id)
    if not body or not body.strip():
        raise ValidationError("body vacio")

    raw_result = await odoo.call(actor, "discuss.channel", "message_post", [[channel_id]],
                                 {"body": body.strip(), "message_type": "comment"})
    new_id = extract_write_id(raw_result, context="odoo_post_discuss_message:message_post")
    after = await odoo.read(actor, "mail.message", [new_id], DISCUSS_MESSAGE_SAFE_FIELDS)
    return after[0] if after else {"id": new_id, "warning": "read-after-write returned empty"}


# ---------------------------------------------------------------------------
# Copiar adjunto de un canal hacia una tarea — COPIA, nunca mueve
# ---------------------------------------------------------------------------

async def odoo_attach_discuss_attachment_to_task(actor: ActorEntry, odoo: OdooClient,
                                                  policy: PolicyEngine, channel_id: int,
                                                  attachment_id: int, task_id: int) -> dict:
    """Copia un adjunto de un mensaje de Discuss hacia una tarea. NUNCA mueve
    el original: crea un ir.attachment NUEVO en la tarea; el adjunto y el
    mensaje fuente del canal quedan intactos.

    Orden de verificacion (cada paso corta antes del siguiente si falla):
    1. El attachment DEBE pertenecer a un mail.message de ESE canal
       allowlisted (verificado server-side, no se confia en el channel_id
       que manda el cliente sin cruzarlo contra Odoo).
    2. Metadatos + `file_size` se leen y validan ANTES de pedir `datas`
       (el binario) — evita gastar ancho de banda/tokens en un adjunto que
       de todas formas se va a rechazar por tamano.
    3. La tarea destino debe ser visible para el actor.
    4. Solo entonces se lee el binario y se crea la copia.
    """
    _ensure_policy(policy, actor, "odoo_attach_discuss_attachment_to_task",
                  "mail.message", "read")
    _ensure_channel_allowed(policy, actor, channel_id)

    # 1. Pertenencia al canal — via el mail.message que lo adjunta.
    owning_messages = await odoo.search_read(
        actor, "mail.message",
        [("model", "=", "discuss.channel"), ("res_id", "=", channel_id),
         ("attachment_ids", "in", [attachment_id])],
        ["id"], limit=1,
    )
    if not owning_messages:
        raise PermissionError(f"attachment_not_in_channel:{attachment_id}:{channel_id}")

    # 2. Metadatos + tamano ANTES del binario.
    _ensure_policy(policy, actor, "odoo_attach_discuss_attachment_to_task",
                  "ir.attachment", "read", fields=ATTACHMENT_META_FIELDS)
    meta = await odoo.search_read(actor, "ir.attachment", [("id", "=", attachment_id)],
                                  ATTACHMENT_META_FIELDS, limit=1)
    if not meta:
        raise PermissionError(f"attachment_not_accessible:{attachment_id}")
    info = meta[0]
    max_bytes = policy.attachment_max_bytes(actor.policy)
    file_size = info.get("file_size") or 0
    if file_size > max_bytes:
        raise ValidationError(f"attachment_too_large:{file_size}>{max_bytes}")

    # 3. Tarea destino visible.
    task_visible = await odoo.search_read(actor, "project.task", [("id", "=", task_id)],
                                          ["id"], limit=1)
    if not task_visible:
        raise PermissionError(f"task_not_accessible:{task_id}")

    # 4. Recien ahora se lee el binario y se crea la COPIA (original intacto).
    _ensure_policy(policy, actor, "odoo_attach_discuss_attachment_to_task",
                  "ir.attachment", "create")
    full = await odoo.read(actor, "ir.attachment", [attachment_id], ["datas"])
    if not full:
        raise PermissionError(f"attachment_not_accessible:{attachment_id}")

    raw_result = await odoo.create(actor, "ir.attachment", {
        "name": info.get("name") or f"adjunto_{attachment_id}",
        "mimetype": info.get("mimetype"),
        "datas": full[0].get("datas"),
        "res_model": "project.task",
        "res_id": task_id,
    })
    new_id = extract_write_id(raw_result, context="odoo_attach_discuss_attachment_to_task:create")
    after = await odoo.read(actor, "ir.attachment", [new_id], ATTACHMENT_META_FIELDS)
    return {
        "attachment": after[0] if after else {"id": new_id},
        "copied": True,
        "source_channel_id": channel_id,
        "source_attachment_id": attachment_id,
        "task_id": task_id,
    }
