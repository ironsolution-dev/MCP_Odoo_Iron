"""Tools read-only para res.partner con allowlist estricta (sec 8.4).
NUEVO v2. Sin VAT/financieros/direcciones."""

from __future__ import annotations

from typing import Optional

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.token_registry import ActorEntry


PARTNER_SAFE_FIELDS: list[str] = [
    "id", "name", "display_name", "email", "phone", "mobile",
    "is_company", "parent_id", "function", "city", "country_id",
    "category_id", "user_id", "active", "customer_rank", "supplier_rank",
]


def _ensure(policy: PolicyEngine, actor: ActorEntry, tool: str) -> None:
    decision = policy.allows(actor.policy, tool, "res.partner", "read",
                             fields=PARTNER_SAFE_FIELDS)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


async def odoo_list_partners(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                             only_companies: bool = False,
                             limit: int = 50, offset: int = 0) -> list[dict]:
    _ensure(policy, actor, "odoo_list_partners")
    domain: list = [("active", "=", True)]
    if only_companies:
        domain.append(("is_company", "=", True))
    return await odoo.search_read(actor, "res.partner", domain, PARTNER_SAFE_FIELDS,
                                  limit=limit, offset=offset, order="name asc")


async def odoo_get_partner(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                           partner_id: int) -> Optional[dict]:
    _ensure(policy, actor, "odoo_get_partner")
    result = await odoo.read(actor, "res.partner", [partner_id], PARTNER_SAFE_FIELDS)
    return result[0] if result else None


async def odoo_search_partner(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                              query: str, limit: int = 20) -> list[dict]:
    """Busqueda por name/email/phone/mobile. NO admite filtros por vat/ref/street."""
    _ensure(policy, actor, "odoo_search_partner")
    if not query or not query.strip():
        return []
    q = query.strip()
    domain = [
        "|", "|", "|",
        ("name", "ilike", q),
        ("email", "ilike", q),
        ("phone", "ilike", q),
        ("mobile", "ilike", q),
    ]
    return await odoo.search_read(actor, "res.partner", domain, PARTNER_SAFE_FIELDS,
                                  limit=limit, order="name asc")
