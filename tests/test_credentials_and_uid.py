"""Tests criticos sec 14.1 Task Packet: no hardcodeo UID 9, cada actor usa sus creds."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.credentials_resolver import CredentialsResolver, MissingCredentialError
from app.odoo_client import OdooClient
from app.token_registry import TokenRegistry
from app.tools.system import odoo_who_am_i


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_no_hardcoded_uid_9():
    """Ningun archivo bajo app/ contiene `uid = 9`, `UID = 9` ni similares hardcodeos."""
    forbidden = re.compile(r"\bUID\s*=\s*9\b|\buid\s*=\s*9\b", re.IGNORECASE)
    violations: list[str] = []
    for path in (REPO_ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if forbidden.search(line):
                # Ignorar comentarios que hablen del hardcode prohibido
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped}")
    assert not violations, f"Hardcoded UID detectado: {violations}"


def test_no_hardcoded_willy_username():
    """Ningun archivo bajo app/ contiene login literal de Willy."""
    suspects = ["willy@ironsolution", "willy.hierro", "Willy Hierro"]
    # `Willy Hierro` aparece legitimamente como display_name por defecto del ACTOR yaml.
    # Lo permitimos solo en token_registry como type hint / docstring.
    violations: list[str] = []
    for path in (REPO_ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in suspects[:2]:  # solo los logins/emails reales
            if needle in text:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {needle!r}")
    assert not violations, f"Username/email de Willy hardcodeado: {violations}"


def test_credentials_resolver_uses_actor_env_vars(actors_yaml, env_actors, token_willy, token_yuniesky, token_anet):
    reg = TokenRegistry(actors_yaml)
    resolver = CredentialsResolver()

    creds_willy = resolver.resolve(reg.verify(token_willy))
    creds_yuniesky = resolver.resolve(reg.verify(token_yuniesky))
    creds_anet = resolver.resolve(reg.verify(token_anet))

    # Cada actor resuelve a sus propias creds, no comparten.
    assert creds_willy.username == "willy@test"
    assert creds_yuniesky.username == "yuniesky@test"
    assert creds_anet.username == "anet@test"

    assert creds_willy.api_key != creds_yuniesky.api_key
    assert creds_willy.api_key != creds_anet.api_key
    assert creds_yuniesky.api_key != creds_anet.api_key


def test_missing_env_var_raises_clear_error(actors_yaml, monkeypatch, token_willy):
    reg = TokenRegistry(actors_yaml)
    resolver = CredentialsResolver()
    # Asegurar que NO esta la env de Willy
    monkeypatch.delenv("ODOO_API_KEY_WILLY", raising=False)
    monkeypatch.setenv("ODOO_URL", "https://x")
    monkeypatch.setenv("ODOO_DB", "x")
    monkeypatch.setenv("ODOO_USERNAME_WILLY", "x")
    with pytest.raises(MissingCredentialError) as exc:
        resolver.resolve(reg.verify(token_willy))
    assert "willy" in str(exc.value)
    assert "ODOO_API_KEY_WILLY" in str(exc.value)


def test_credentials_repr_redacts_api_key(actors_yaml, env_actors, token_willy):
    reg = TokenRegistry(actors_yaml)
    resolver = CredentialsResolver()
    creds = resolver.resolve(reg.verify(token_willy))
    rep = repr(creds)
    assert "willy_api_key_fake" not in rep
    assert "redacted" in rep.lower()


@pytest.mark.asyncio
async def test_actor_uses_own_odoo_credentials(actors_yaml, env_actors, token_willy, token_yuniesky, monkeypatch):
    """Verifica que authenticate llama a Odoo con las creds del actor correspondiente."""
    reg = TokenRegistry(actors_yaml)

    captured: list[tuple[str, str, str]] = []

    class FakeCommonProxy:
        def __init__(self, *_args, **_kwargs):
            pass

        def authenticate(self, db, username, api_key, _ctx):
            captured.append((db, username, api_key))
            return {"willy@test": 101, "yuniesky@test": 202, "anet@test": 303}[username]

    monkeypatch.setattr("xmlrpc.client.ServerProxy", FakeCommonProxy)

    client = OdooClient()

    uid_willy = await client.authenticate(reg.verify(token_willy))
    uid_yun = await client.authenticate(reg.verify(token_yuniesky))

    assert uid_willy == 101
    assert uid_yun == 202

    # Cada call a authenticate uso las creds del actor correspondiente.
    assert captured[0] == ("odoo_test", "willy@test", "willy_api_key_fake")
    assert captured[1] == ("odoo_test", "yuniesky@test", "yuniesky_api_key_fake")


@pytest.mark.asyncio
async def test_who_am_i_returns_actor_uid_without_secrets(actors_yaml, env_actors, token_willy, monkeypatch):
    reg = TokenRegistry(actors_yaml)

    class FakeProxy:
        def __init__(self, *_args, **_kwargs):
            pass

        def authenticate(self, _db, _user, _key, _ctx):
            return 101

    monkeypatch.setattr("xmlrpc.client.ServerProxy", FakeProxy)

    client = OdooClient()
    result = await odoo_who_am_i(reg.verify(token_willy), client)

    assert result["actor"] == "willy"
    assert result["odoo_uid"] == 101
    assert result["role"] == "owner"
    # Sin secretos
    assert "api_key" not in result
    assert "token" not in result
    assert "willy_api_key_fake" not in repr(result)
