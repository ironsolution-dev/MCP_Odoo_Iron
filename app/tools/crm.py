"""Tools de CRM (crm.lead + mail.message + mail.activity).
Fase 1: read-only en crm.lead; notas y actividades permitidas; NO cambia etapa/monto."""

from __future__ import annotations

from typing import Optional

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.schemas import ValidationError, validate_iso_date
from app.token_registry import ActorEntry


CRM_LEAD_SAFE_FIELDS: list[str] = [
    "id", "name", "partner_id", "email_from", "phone",
    "stage_id", "user_id", "team_id", "create_date", "write_date",
    "type", "tag_ids", "active",
]


def _ensure(policy: PolicyEngine, actor: ActorEntry, tool: str, model: str, action: str,
            fields: Optional[list[str]] = None) -> None:
    decision = policy.allows(actor.policy, tool, model, action, fields=fields)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------

async def odoo_list_crm_leads(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                              stage_id: Optional[int] = None,
                              limit: int = 50, offset: int = 0) -> list[dict]:
    _ensure(policy, actor, "odoo_list_crm_leads", "crm.lead", "read", fields=CRM_LEAD_SAFE_FIELDS)
    domain: list = [("active", "=", True)]
    if stage_id:
        domain.append(("stage_id", "=", stage_id))
    return await odoo.search_read(actor, "crm.lead", domain, CRM_LEAD_SAFE_FIELDS,
                                  limit=limit, offset=offset, order="create_date desc")


async def odoo_get_crm_lead(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                            lead_id: int) -> Optional[dict]:
    _ensure(policy, actor, "odoo_get_crm_lead", "crm.lead", "read", fields=CRM_LEAD_SAFE_FIELDS)
    result = await odoo.read(actor, "crm.lead", [lead_id], CRM_LEAD_SAFE_FIELDS)
    return result[0] if result else None


# ---------------------------------------------------------------------------
# Notas (mail.message)
# ---------------------------------------------------------------------------

async def odoo_add_crm_note(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                            lead_id: int, body: str) -> dict:
    """Posta una nota interna en el chatter del lead. NO modifica etapa, monto ni
    asignacion. Usa message_post con type='comment' subtype=note."""
    _ensure(policy, actor, "odoo_add_crm_note", "mail.message", "create")
    if not body or not body.strip():
        raise ValidationError("body de nota vacio")
    # Verificar lead visible/ existente
    lead = await odoo.read(actor, "crm.lead", [lead_id], ["id", "name"])
    if not lead:
        raise PermissionError(f"crm_lead_not_accessible:{lead_id}")

    await odoo.call(
        actor, "crm.lead", "message_post", [[lead_id]],
        {"body": body.strip(), "message_type": "comment",
         "subtype_xmlid": "mail.mt_note"},
    )
    return {"lead_id": lead_id, "lead_name": lead[0]["name"], "note_posted": True}


# ---------------------------------------------------------------------------
# Actividades (mail.activity)
# ---------------------------------------------------------------------------

async def odoo_create_crm_activity(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                   lead_id: int, summary: str, deadline: str,
                                   activity_type_id: int,
                                   user_id: Optional[int] = None,
                                   note: Optional[str] = None) -> dict:
    """Crea una actividad sobre el lead (llamada, email, tarea programada, etc.).
    deadline: ISO YYYY-MM-DD."""
    _ensure(policy, actor, "odoo_create_crm_activity", "mail.activity", "create")
    if not summary or not summary.strip():
        raise ValidationError("summary vacio")
    validate_iso_date(deadline, field="deadline")

    # Resolver res_model_id de crm.lead
    model_ref = await odoo.search_read(actor, "ir.model", [("model", "=", "crm.lead")],
                                       ["id"], limit=1)
    if not model_ref:
        raise RuntimeError("no se encontro ir.model crm.lead")

    uid = await odoo.authenticate(actor)
    values = {
        "res_model_id": model_ref[0]["id"],
        "res_id": lead_id,
        "activity_type_id": activity_type_id,
        "summary": summary.strip(),
        "date_deadline": deadline,
        "user_id": user_id or uid,
    }
    if note:
        values["note"] = note

    new_id = await odoo.create(actor, "mail.activity", values)
    after = await odoo.read(actor, "mail.activity", [new_id],
                            ["id", "summary", "date_deadline", "user_id",
                             "activity_type_id", "res_id"])
    return after[0] if after else {"id": new_id, "warning": "read-after-write empty"}
