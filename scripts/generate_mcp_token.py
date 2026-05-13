"""Genera un token MCP plano (mostrado una sola vez) y su hash sha256
para pegar en actors.yaml.

- El token plano NO se guarda en disco, NO se loguea, NO se devuelve por API.
- Se imprime UNA VEZ en stdout para que el operador lo copie a su gestor seguro.
- En actors.yaml solo vive el hash.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys


def generate() -> tuple[str, str]:
    token = "mcp_" + secrets.token_urlsafe(32)
    token_hash = "sha256:" + hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an MCP token + its sha256 hash. Token is shown ONCE."
    )
    parser.add_argument("--actor", required=True, help="willy | yuniesky | anet")
    args = parser.parse_args()

    token, token_hash = generate()

    print(f"Actor:    {args.actor}")
    print(f"MCP_TOKEN (copy ONCE, never log):   {token}")
    print(f"token_hash (paste in actors.yaml):  {token_hash}")
    print()
    print("Reglas:")
    print("  - No pegar MCP_TOKEN en repos, prompts ni logs.")
    print("  - Guardar MCP_TOKEN en gestor seguro del actor.")
    print("  - Pegar token_hash en actors.yaml campo actors." + args.actor + ".token_hash")
    return 0


if __name__ == "__main__":
    sys.exit(main())
