"""Resuelve credenciales Odoo de un actor desde variables de entorno.
NUNCA expone las credenciales fuera del proceso, ni las imprime/loguea."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.token_registry import ActorEntry


class MissingCredentialError(RuntimeError):
    """Falta una env var requerida para un actor."""


@dataclass(frozen=True)
class OdooCredentials:
    url: str
    db: str
    username: str
    api_key: str  # NUNCA loguear, NUNCA exponer en responses

    def __repr__(self) -> str:  # noqa: D401 — defensa anti-leak en logs.
        return f"OdooCredentials(url={self.url!r}, db={self.db!r}, username={self.username!r}, api_key=<redacted>)"


class CredentialsResolver:
    def resolve(self, actor: ActorEntry) -> OdooCredentials:
        env = os.environ
        try:
            return OdooCredentials(
                url=env[actor.odoo_url_env],
                db=env[actor.odoo_db_env],
                username=env[actor.odoo_username_env],
                api_key=env[actor.odoo_api_key_env],
            )
        except KeyError as e:
            missing = e.args[0]
            raise MissingCredentialError(
                f"actor={actor.actor!r} missing env var: {missing}"
            ) from None
