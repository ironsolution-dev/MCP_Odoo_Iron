"""Tests del token_registry y resolucion de actor."""

from __future__ import annotations

from app.token_registry import TokenRegistry


def test_valid_token_maps_actor(actors_yaml, token_willy):
    reg = TokenRegistry(actors_yaml)
    entry = reg.verify(token_willy)
    assert entry is not None
    assert entry.actor == "willy"
    assert entry.role == "owner"
    assert entry.policy == "owner_policy"


def test_invalid_token_denied(actors_yaml):
    reg = TokenRegistry(actors_yaml)
    assert reg.verify("mcp_invalid_token_xxxxxxxxxxxxxxxxxxxxxxxx") is None
    assert reg.verify("not_starting_with_prefix") is None
    assert reg.verify(None) is None
    assert reg.verify("") is None


def test_disabled_actor_denied(actors_yaml, token_disabled):
    reg = TokenRegistry(actors_yaml)
    assert reg.verify(token_disabled) is None


def test_each_actor_has_independent_creds_env(actors_yaml, token_willy, token_yuniesky, token_anet):
    reg = TokenRegistry(actors_yaml)
    willy = reg.verify(token_willy)
    yuniesky = reg.verify(token_yuniesky)
    anet = reg.verify(token_anet)

    assert willy.odoo_username_env == "ODOO_USERNAME_WILLY"
    assert yuniesky.odoo_username_env == "ODOO_USERNAME_YUNIESKY"
    assert anet.odoo_username_env == "ODOO_USERNAME_ANET"
    # Cada actor tiene SU propia var; no comparten.
    assert len({willy.odoo_api_key_env, yuniesky.odoo_api_key_env, anet.odoo_api_key_env}) == 3
