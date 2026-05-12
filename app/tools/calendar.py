"""Tools de calendar.event."""

from __future__ import annotations

from typing import Optional

from app.odoo_client import OdooClient
from app.policy_engine import PolicyEngine
from app.schemas import validate_calendar_event_dates
from app.token_registry import ActorEntry


EVENT_SAFE_FIELDS: list[str] = [
    "id", "name", "description", "start", "stop", "allday",
    "duration", "location", "user_id", "partner_ids", "categ_ids",
    "show_as", "privacy",
]

EVENT_WRITABLE_FIELDS: set[str] = {
    "name", "description", "start", "stop", "location",
    "duration", "allday", "partner_ids",
}


def _ensure(policy: PolicyEngine, actor: ActorEntry, tool: str, action: str,
            fields: Optional[list[str]] = None) -> None:
    decision = policy.allows(actor.policy, tool, "calendar.event", action, fields=fields)
    if not decision.allowed:
        raise PermissionError(decision.denied_reason)


async def odoo_list_calendar_events(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                    start_after: str, end_before: str,
                                    limit: int = 100) -> list[dict]:
    """Lista eventos en rango [start_after, end_before]. Limita a eventos del actor."""
    _ensure(policy, actor, "odoo_list_calendar_events", "read", fields=EVENT_SAFE_FIELDS)
    uid = await odoo.authenticate(actor)
    domain = [
        "&", "&",
        ("start", ">=", start_after),
        ("stop", "<=", end_before),
        "|", ("user_id", "=", uid), ("partner_ids", "in", [uid]),
    ]
    return await odoo.search_read(actor, "calendar.event", domain, EVENT_SAFE_FIELDS,
                                  limit=limit, order="start asc")


async def odoo_create_calendar_event(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                     name: str, start: str, stop: str,
                                     description: Optional[str] = None,
                                     location: Optional[str] = None,
                                     partner_ids: Optional[list[int]] = None,
                                     allday: bool = False) -> dict:
    _ensure(policy, actor, "odoo_create_calendar_event", "create")
    if not name or not name.strip():
        raise ValueError("name vacio")
    validate_calendar_event_dates(start, stop)

    uid = await odoo.authenticate(actor)
    values: dict = {
        "name": name.strip(),
        "start": start,
        "stop": stop,
        "user_id": uid,
        "allday": allday,
    }
    if description:
        values["description"] = description
    if location:
        values["location"] = location
    if partner_ids:
        values["partner_ids"] = [(6, 0, partner_ids)]

    new_id = await odoo.create(actor, "calendar.event", values)
    created = await odoo.read(actor, "calendar.event", [new_id], EVENT_SAFE_FIELDS)
    return created[0] if created else {"id": new_id, "warning": "read-after-write empty"}


async def odoo_update_calendar_event(actor: ActorEntry, odoo: OdooClient, policy: PolicyEngine,
                                     event_id: int, changes: dict) -> dict:
    invalid = [k for k in changes if k not in EVENT_WRITABLE_FIELDS]
    if invalid:
        raise PermissionError(f"fields_not_writable:{invalid}")
    _ensure(policy, actor, "odoo_update_calendar_event", "write")
    # Si actualiza fechas, validar coherencia
    if "start" in changes and "stop" in changes:
        validate_calendar_event_dates(changes["start"], changes["stop"])

    await odoo.write(actor, "calendar.event", [event_id], changes)
    after = await odoo.read(actor, "calendar.event", [event_id], EVENT_SAFE_FIELDS)
    return after[0] if after else {"id": event_id, "warning": "read-after-write empty"}
