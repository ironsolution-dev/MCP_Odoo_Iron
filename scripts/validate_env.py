"""Valida que las variables de entorno requeridas para arrancar GREEN existen.
Falla con codigo 1 y mensaje claro si falta alguna. NO imprime los valores.

Uso (en startup del contenedor o pre-deploy):
    python scripts/validate_env.py
"""

from __future__ import annotations

import os
import sys


REQUIRED_BASE = [
    "ODOO_URL",
    "ODOO_DB",
    "ACTORS_REGISTRY_PATH",
    "POLICIES_PATH",
    "AUDIT_LOG_PATH",
]

REQUIRED_PER_ACTOR = [
    ("WILLY", ["ODOO_USERNAME_WILLY", "ODOO_API_KEY_WILLY"]),
    ("YUNIESKY", ["ODOO_USERNAME_YUNIESKY", "ODOO_API_KEY_YUNIESKY"]),
    ("ANET", ["ODOO_USERNAME_ANET", "ODOO_API_KEY_ANET"]),
]


def main() -> int:
    missing: list[str] = []

    for var in REQUIRED_BASE:
        if not os.environ.get(var):
            missing.append(var)

    for _actor, vars_ in REQUIRED_PER_ACTOR:
        for var in vars_:
            if not os.environ.get(var):
                missing.append(var)

    if missing:
        print("FAIL: faltan variables de entorno requeridas:", file=sys.stderr)
        for var in missing:
            print(f"  - {var}", file=sys.stderr)
        print(
            "\nPista: revisar /opt/odoo-mcp-v2/secrets/.env.v2 y --env-file en el docker run.",
            file=sys.stderr,
        )
        return 1

    print("OK: todas las variables requeridas estan presentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
