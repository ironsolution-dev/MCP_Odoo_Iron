"""Registry de tokens MCP. Verifica que el hash sha256 del token coincida con
algun actor habilitado en `actors.yaml`. NO almacena ni loguea tokens en claro.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class ActorEntry:
    actor: str
    role: str
    display_name: str
    odoo_url_env: str
    odoo_db_env: str
    odoo_username_env: str
    odoo_api_key_env: str
    policy: str
    enabled: bool


def _hash(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


class TokenRegistry:
    """Mapea token MCP plano → ActorEntry vía hash sha256.

    El YAML guarda solo hashes. El token plano nunca toca el disco después de
    `generate_mcp_token.py`. La verificación se hace en memoria por comparación
    de hash.
    """

    def __init__(self, yaml_path: Path):
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if data.get("hash_algorithm", "sha256") != "sha256":
            raise ValueError(
                f"Unsupported hash_algorithm: {data.get('hash_algorithm')}. Only sha256."
            )

        self._by_hash: dict[str, ActorEntry] = {}
        actors_cfg = data.get("actors") or {}
        for name, cfg in actors_cfg.items():
            if not cfg.get("enabled", True):
                continue
            self._by_hash[cfg["token_hash"]] = ActorEntry(
                actor=name,
                role=cfg["role"],
                display_name=cfg["display_name"],
                odoo_url_env=cfg["odoo_url_env"],
                odoo_db_env=cfg["odoo_db_env"],
                odoo_username_env=cfg["odoo_username_env"],
                odoo_api_key_env=cfg["odoo_api_key_env"],
                policy=cfg["policy"],
                enabled=True,
            )

    def verify(self, token: Optional[str]) -> Optional[ActorEntry]:
        """Retorna ActorEntry si el token mapea a un actor habilitado, None si no."""
        if not token or not token.startswith("mcp_"):
            return None
        return self._by_hash.get(_hash(token))

    def actors(self) -> list[ActorEntry]:
        return list(self._by_hash.values())
