"""Tests del policy_engine. Cubre los 5 chequeos:
denylist global / policy desconocida / tool no permitida / modelo no declarado /
accion no permitida / campos fuera de allowlist.
"""

from __future__ import annotations

from app.policy_engine import PolicyEngine


def test_policy_denies_unknown_model(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    d = pe.allows("owner_policy", "odoo_who_am_i", "unknown.model", "read")
    assert not d.allowed
    assert d.denied_reason.startswith("unknown_model:")


def test_policy_denies_unknown_tool(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    d = pe.allows("owner_policy", "odoo_nonexistent_tool", "project.task", "read")
    assert not d.allowed
    assert d.denied_reason.startswith("tool_not_allowed:")


def test_policy_denies_unknown_policy(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    d = pe.allows("ghost_policy", "odoo_who_am_i", "project.task", "read")
    assert not d.allowed
    assert d.denied_reason.startswith("unknown_policy:")


def test_hr_employee_field_allowlist(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    ok = pe.allows("owner_policy", "odoo_list_employees", "hr.employee", "read",
                   fields=["id", "name", "work_email"])
    assert ok.allowed

    bad = pe.allows("owner_policy", "odoo_list_employees", "hr.employee", "read",
                    fields=["id", "wage", "bank_account_id"])
    assert not bad.allowed
    assert "fields_not_allowed" in bad.denied_reason


def test_partner_field_allowlist(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    ok = pe.allows("owner_policy", "odoo_list_partners", "res.partner", "read",
                   fields=["id", "name", "email", "phone"])
    assert ok.allowed

    bad = pe.allows("owner_policy", "odoo_list_partners", "res.partner", "read",
                    fields=["id", "vat", "street", "credit"])
    assert not bad.allowed
    assert "fields_not_allowed" in bad.denied_reason


def test_denylist_blocks_account_move(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    # account.move::write esta en denylist global. Incluso para owner.
    d = pe.allows("owner_policy", "odoo_who_am_i", "account.move", "write")
    assert not d.allowed
    assert d.denied_reason.startswith("globally_denied:account.move:write")


def test_denylist_blocks_res_users_write_for_all_roles(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    for role in ("owner_policy", "operations_policy", "medical_direction_policy"):
        d = pe.allows(role, "odoo_who_am_i", "res.users", "write")
        assert not d.allowed, role
        assert "globally_denied:res.users:write" in d.denied_reason, role


def test_operations_cannot_create_project(policies_yaml):
    """Yuniesky NO puede crear proyectos (solo Willy)."""
    pe = PolicyEngine(policies_yaml)
    # Asumimos tool no presente en operations_policy
    d = pe.allows("operations_policy", "odoo_create_project", "project.project", "create")
    assert not d.allowed


def test_medical_direction_can_read_crm_but_not_write(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    ok = pe.allows("medical_direction_policy", "odoo_list_crm_leads", "crm.lead", "read")
    assert ok.allowed
    bad = pe.allows("medical_direction_policy", "odoo_list_crm_leads", "crm.lead", "write")
    assert not bad.allowed


def test_filter_fields_strips_forbidden(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    filtered = pe.filter_fields("res.partner", ["id", "name", "vat", "credit", "email"])
    # Solo deben quedar los que estan en allowlist
    assert "vat" not in filtered
    assert "credit" not in filtered
    assert "id" in filtered
    assert "name" in filtered
    assert "email" in filtered


def test_rate_limit_returns_role_limits(policies_yaml):
    pe = PolicyEngine(policies_yaml)
    rl_owner = pe.rate_limit("owner_policy")
    rl_ops = pe.rate_limit("operations_policy")
    assert rl_owner.requests_per_minute >= rl_ops.requests_per_minute


def test_unlink_denied_everywhere_in_phase_1(policies_yaml):
    """En fase 1 ningun modelo permite unlink desde MCP tools."""
    pe = PolicyEngine(policies_yaml)
    for model in ("project.task", "calendar.event", "project.project",
                  "crm.lead", "res.partner", "hr.employee"):
        d = pe.allows("owner_policy", "odoo_who_am_i", model, "unlink")
        assert not d.allowed, model
