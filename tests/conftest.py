"""Fixtures compartidas. Construyen un actors.yaml temporal con hashes reales
y una policy minima para evitar Odoo live."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml


def _hash(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


@pytest.fixture
def token_willy() -> str:
    return "mcp_willy_test_token_aaaaaaaaaaaaaaaaaaaa"


@pytest.fixture
def token_yuniesky() -> str:
    return "mcp_yuniesky_test_token_bbbbbbbbbbbbbbbb"


@pytest.fixture
def token_anet() -> str:
    return "mcp_anet_test_token_cccccccccccccccccccc"


@pytest.fixture
def token_disabled() -> str:
    return "mcp_disabled_test_token_dddddddddddddddd"


@pytest.fixture
def actors_yaml(tmp_path: Path, token_willy, token_yuniesky, token_anet, token_disabled) -> Path:
    data = {
        "version": 1,
        "hash_algorithm": "sha256",
        "actors": {
            "willy": {
                "enabled": True,
                "role": "owner",
                "display_name": "Willy Hierro",
                "token_hash": _hash(token_willy),
                "odoo_url_env": "ODOO_URL",
                "odoo_db_env": "ODOO_DB",
                "odoo_username_env": "ODOO_USERNAME_WILLY",
                "odoo_api_key_env": "ODOO_API_KEY_WILLY",
                "policy": "owner_policy",
            },
            "yuniesky": {
                "enabled": True,
                "role": "operations",
                "display_name": "Yuniesky",
                "token_hash": _hash(token_yuniesky),
                "odoo_url_env": "ODOO_URL",
                "odoo_db_env": "ODOO_DB",
                "odoo_username_env": "ODOO_USERNAME_YUNIESKY",
                "odoo_api_key_env": "ODOO_API_KEY_YUNIESKY",
                "policy": "operations_policy",
            },
            "anet": {
                "enabled": True,
                "role": "medical_direction",
                "display_name": "Anet",
                "token_hash": _hash(token_anet),
                "odoo_url_env": "ODOO_URL",
                "odoo_db_env": "ODOO_DB",
                "odoo_username_env": "ODOO_USERNAME_ANET",
                "odoo_api_key_env": "ODOO_API_KEY_ANET",
                "policy": "medical_direction_policy",
            },
            "ex_actor": {
                "enabled": False,
                "role": "operations",
                "display_name": "Ex Empleado",
                "token_hash": _hash(token_disabled),
                "odoo_url_env": "ODOO_URL",
                "odoo_db_env": "ODOO_DB",
                "odoo_username_env": "ODOO_USERNAME_EX",
                "odoo_api_key_env": "ODOO_API_KEY_EX",
                "policy": "operations_policy",
            },
        },
    }
    path = tmp_path / "actors.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)
    return path


@pytest.fixture
def policies_yaml(tmp_path: Path) -> Path:
    """Policies minimas para tests de policy_engine."""
    data = {
        "version": 1,
        "denylist_global": [
            {"model": "res.users", "actions": ["write", "create", "unlink"]},
            {"model": "account.move", "actions": ["write", "create", "unlink"]},
            {"model": "hr.contract", "actions": ["read", "write", "create", "unlink"]},
        ],
        "field_allowlists": {
            "hr.employee": [
                "id", "name", "work_email", "work_phone", "mobile_phone",
                "department_id", "job_id", "parent_id", "user_id", "active",
            ],
            "res.partner": [
                "id", "name", "display_name", "email", "phone", "mobile",
                "is_company", "parent_id", "function", "city", "country_id",
                "category_id", "user_id", "active", "customer_rank", "supplier_rank",
            ],
        },
        "policies": {
            "owner_policy": {
                "allowed_tools": [
                    "odoo_who_am_i", "odoo_health", "odoo_validate_apl_stages",
                    "odoo_my_tasks", "odoo_my_tasks_today", "odoo_my_tasks_overdue",
                    "odoo_create_my_todo_apl", "odoo_create_project_task_apl",
                    "odoo_update_task_apl", "odoo_move_task",
                    "odoo_mark_task_done", "odoo_cancel_task",
                    "odoo_list_projects", "odoo_get_project", "odoo_create_project",
                    "odoo_update_project_basic", "odoo_project_tasks",
                    "odoo_list_calendar_events", "odoo_create_calendar_event",
                    "odoo_update_calendar_event",
                    "odoo_list_employees", "odoo_get_employee", "odoo_search_employee",
                    "odoo_list_crm_leads", "odoo_get_crm_lead",
                    "odoo_add_crm_note", "odoo_create_crm_activity",
                    "odoo_list_partners", "odoo_get_partner", "odoo_search_partner",
                ],
                "model_rules": {
                    "project.task":    {"read": True,  "create": True,  "write": True,  "unlink": False},
                    "project.project": {"read": True,  "create": True,  "write": True,  "unlink": False},
                    "calendar.event":  {"read": True,  "create": True,  "write": True,  "unlink": False},
                    "hr.employee":     {"read": True,  "create": False, "write": False, "unlink": False},
                    "res.partner":     {"read": True,  "create": False, "write": False, "unlink": False},
                    "crm.lead":        {"read": True,  "create": False, "write": False, "unlink": False},
                    "mail.message":    {"read": True,  "create": True,  "write": False, "unlink": False},
                },
                "rate_limit": {"requests_per_minute": 60, "writes_per_minute": 20},
            },
            "operations_policy": {
                "allowed_tools": [
                    "odoo_who_am_i", "odoo_health",
                    "odoo_my_tasks", "odoo_my_tasks_today", "odoo_my_tasks_overdue",
                    "odoo_create_my_todo_apl", "odoo_create_project_task_apl",
                    "odoo_update_task_apl", "odoo_move_task",
                    "odoo_mark_task_done", "odoo_cancel_task",
                    "odoo_list_projects", "odoo_get_project", "odoo_project_tasks",
                    "odoo_list_calendar_events", "odoo_create_calendar_event",
                    "odoo_update_calendar_event",
                    "odoo_list_employees", "odoo_list_partners",
                ],
                "model_rules": {
                    "project.task":    {"read": True,  "create": True,  "write": True,  "unlink": False},
                    "project.project": {"read": True,  "create": False, "write": False, "unlink": False},
                    "calendar.event":  {"read": True,  "create": True,  "write": True,  "unlink": False},
                    "hr.employee":     {"read": True,  "create": False, "write": False, "unlink": False},
                    "res.partner":     {"read": True,  "create": False, "write": False, "unlink": False},
                    "crm.lead":        {"read": False, "create": False, "write": False, "unlink": False},
                },
                "rate_limit": {"requests_per_minute": 40, "writes_per_minute": 15},
            },
            "medical_direction_policy": {
                "allowed_tools": [
                    "odoo_who_am_i", "odoo_health",
                    "odoo_my_tasks", "odoo_my_tasks_today", "odoo_my_tasks_overdue",
                    "odoo_create_my_todo_apl", "odoo_create_project_task_apl",
                    "odoo_update_task_apl", "odoo_move_task",
                    "odoo_mark_task_done", "odoo_cancel_task",
                    "odoo_list_projects", "odoo_get_project", "odoo_project_tasks",
                    "odoo_list_calendar_events", "odoo_create_calendar_event",
                    "odoo_update_calendar_event",
                    "odoo_list_employees",
                    "odoo_list_crm_leads", "odoo_get_crm_lead", "odoo_add_crm_note",
                    "odoo_list_partners", "odoo_get_partner",
                ],
                "model_rules": {
                    "project.task":    {"read": True,  "create": True,  "write": True,  "unlink": False},
                    "calendar.event":  {"read": True,  "create": True,  "write": True,  "unlink": False},
                    "crm.lead":        {"read": True,  "create": False, "write": False, "unlink": False},
                    "res.partner":     {"read": True,  "create": False, "write": False, "unlink": False},
                    "mail.message":    {"read": True,  "create": True,  "write": False, "unlink": False},
                },
                "rate_limit": {"requests_per_minute": 40, "writes_per_minute": 15},
            },
        },
    }
    path = tmp_path / "policies.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)
    return path


@pytest.fixture
def env_actors(monkeypatch):
    """Set env vars Odoo para los 3 actores con valores fake."""
    monkeypatch.setenv("ODOO_URL", "https://odoo.test/")
    monkeypatch.setenv("ODOO_DB", "odoo_test")
    monkeypatch.setenv("ODOO_USERNAME_WILLY", "willy@test")
    monkeypatch.setenv("ODOO_API_KEY_WILLY", "willy_api_key_fake")
    monkeypatch.setenv("ODOO_USERNAME_YUNIESKY", "yuniesky@test")
    monkeypatch.setenv("ODOO_API_KEY_YUNIESKY", "yuniesky_api_key_fake")
    monkeypatch.setenv("ODOO_USERNAME_ANET", "anet@test")
    monkeypatch.setenv("ODOO_API_KEY_ANET", "anet_api_key_fake")
