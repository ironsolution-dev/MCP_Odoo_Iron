"""Tests Fase 5: projects, calendar, employees, crm, partners.
Cubre policy checks, read-after-write, validaciones y allowlists.
"""

from __future__ import annotations

import pytest

from app.policy_engine import PolicyEngine
from app.schemas import ValidationError
from app.token_registry import TokenRegistry
from app.tools.calendar import (
    odoo_create_calendar_event,
    odoo_list_calendar_events,
    odoo_update_calendar_event,
)
from app.tools.crm import odoo_add_crm_note, odoo_create_crm_activity, odoo_list_crm_leads
from app.tools.employees import odoo_get_employee, odoo_list_employees, odoo_search_employee
from app.tools.partners import odoo_get_partner, odoo_list_partners, odoo_search_partner
from app.tools.projects import (
    odoo_create_project,
    odoo_list_projects,
    odoo_project_tasks,
    odoo_update_project_basic,
)


class FakeOdoo:
    def __init__(self, search_read_returns: dict = None, read_returns: dict = None):
        self.calls: list[tuple] = []
        self.search_read_returns = search_read_returns or {}
        self.read_returns = read_returns or {}
        self._uid = 42

    async def authenticate(self, actor):
        return self._uid

    async def search_read(self, actor, model, domain, fields, limit=50, offset=0, order=None):
        self.calls.append(("search_read", model, domain, list(fields)))
        return self.search_read_returns.get(model, [])

    async def read(self, actor, model, ids, fields):
        self.calls.append(("read", model, ids, list(fields)))
        # Defecto: retorna stub con id
        return self.read_returns.get(model, [{"id": ids[0], "name": f"stub_{model}"}])

    async def create(self, actor, model, values):
        self.calls.append(("create", model, values))
        return 999

    async def write(self, actor, model, ids, values):
        self.calls.append(("write", model, ids, values))
        return True

    async def call(self, actor, model, method, args, kwargs=None):
        self.calls.append(("call", model, method, args, kwargs))
        return True


# ---------------------------------------------------------------------------
# projects.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_projects_create_does_read_after_write(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    result = await odoo_create_project(actor, odoo, pe, name="Proyecto MCP v2")
    ops = [c[0] for c in odoo.calls]
    assert ops.index("create") < ops.index("read"), "no read-after-write"
    assert result["id"] == 999


@pytest.mark.asyncio
async def test_projects_operations_cannot_create(actors_yaml, policies_yaml, env_actors, token_yuniesky):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_yuniesky)

    with pytest.raises(PermissionError):
        await odoo_create_project(actor, odoo, pe, name="X")


@pytest.mark.asyncio
async def test_project_tasks_requires_visible_project(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(search_read_returns={"project.project": []})  # no visible
    actor = reg.verify(token_willy)
    with pytest.raises(PermissionError) as exc:
        await odoo_project_tasks(actor, odoo, pe, project_id=1)
    assert "project_not_accessible" in str(exc.value)


@pytest.mark.asyncio
async def test_project_update_rejects_unknown_fields(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)
    with pytest.raises(PermissionError) as exc:
        await odoo_update_project_basic(actor, odoo, pe, project_id=1,
                                         changes={"name": "ok", "analytic_account_id": 5})
    assert "fields_not_writable" in str(exc.value)


# ---------------------------------------------------------------------------
# calendar.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_event_validates_dates(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    # start despues de stop
    with pytest.raises(ValidationError):
        await odoo_create_calendar_event(actor, odoo, pe,
                                          name="Reu",
                                          start="2026-05-12 16:00:00",
                                          stop="2026-05-12 15:00:00")
    # Formato invalido
    with pytest.raises(ValidationError):
        await odoo_create_calendar_event(actor, odoo, pe, name="Reu",
                                          start="not-a-date", stop="2026-05-12 15:00:00")


@pytest.mark.asyncio
async def test_calendar_event_create_ok(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)

    result = await odoo_create_calendar_event(actor, odoo, pe,
                                               name="Daily standup",
                                               start="2026-05-12 09:00:00",
                                               stop="2026-05-12 09:30:00")
    assert result["id"] == 999


# ---------------------------------------------------------------------------
# employees.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_employees_list_uses_allowlist_fields_only(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)
    await odoo_list_employees(actor, odoo, pe)
    call = next(c for c in odoo.calls if c[0] == "search_read" and c[1] == "hr.employee")
    fields = call[3]
    # NUNCA campos prohibidos
    for forbidden in ("wage", "bank_account_id", "identification_id", "private_email"):
        assert forbidden not in fields


@pytest.mark.asyncio
async def test_employees_search_empty_query_returns_empty(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)
    result = await odoo_search_employee(actor, odoo, pe, query="")
    assert result == []


# ---------------------------------------------------------------------------
# crm.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crm_add_note_does_not_change_stage_or_amount(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(read_returns={"crm.lead": [{"id": 1, "name": "lead test"}]})
    actor = reg.verify(token_willy)

    result = await odoo_add_crm_note(actor, odoo, pe, lead_id=1, body="Cliente llamo a las 14h.")
    assert result["note_posted"] is True
    # Verifica NO se llamo write a crm.lead
    writes_to_lead = [c for c in odoo.calls if c[0] == "write" and c[1] == "crm.lead"]
    assert writes_to_lead == []


@pytest.mark.asyncio
async def test_crm_note_requires_body(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(read_returns={"crm.lead": [{"id": 1, "name": "lead"}]})
    actor = reg.verify(token_willy)
    with pytest.raises(ValidationError):
        await odoo_add_crm_note(actor, odoo, pe, lead_id=1, body="")


@pytest.mark.asyncio
async def test_crm_note_lead_not_accessible(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo(read_returns={"crm.lead": []})  # lead no existe / no visible
    actor = reg.verify(token_willy)
    with pytest.raises(PermissionError) as exc:
        await odoo_add_crm_note(actor, odoo, pe, lead_id=999, body="nota")
    assert "crm_lead_not_accessible" in str(exc.value)


@pytest.mark.asyncio
async def test_crm_list_denied_for_operations(actors_yaml, policies_yaml, env_actors, token_yuniesky):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_yuniesky)
    # operations_policy NO incluye odoo_list_crm_leads
    with pytest.raises(PermissionError):
        await odoo_list_crm_leads(actor, odoo, pe)


# ---------------------------------------------------------------------------
# partners.py
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partners_list_uses_allowlist_fields(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)
    await odoo_list_partners(actor, odoo, pe)
    call = next(c for c in odoo.calls if c[0] == "search_read" and c[1] == "res.partner")
    fields = call[3]
    for forbidden in ("vat", "street", "credit", "debit", "comment", "bank_ids", "total_invoiced"):
        assert forbidden not in fields


@pytest.mark.asyncio
async def test_partners_search_does_not_query_vat(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)
    await odoo_search_partner(actor, odoo, pe, query="alguien")
    call = next(c for c in odoo.calls if c[0] == "search_read" and c[1] == "res.partner")
    domain = call[2]
    # Aplanar y revisar
    flat = " ".join(str(x) for x in domain)
    assert "vat" not in flat
    assert "ref" not in flat
    assert "street" not in flat


@pytest.mark.asyncio
async def test_partners_empty_query_returns_empty(actors_yaml, policies_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    pe = PolicyEngine(policies_yaml)
    odoo = FakeOdoo()
    actor = reg.verify(token_willy)
    result = await odoo_search_partner(actor, odoo, pe, query="   ")
    assert result == []
