"""Smoke tests post-deploy contra el endpoint v2.

Lee MCP_TOKEN_WILLY / MCP_TOKEN_YUNIESKY / MCP_TOKEN_ANET del entorno (NUNCA
de argumentos en linea de comando para evitar dejarlos en bash history).

Uso:
    export MCP_TOKEN_WILLY=mcp_xxx
    export MCP_TOKEN_YUNIESKY=mcp_yyy
    export MCP_TOKEN_ANET=mcp_zzz
    python scripts/smoke_test_mcp.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any


ENDPOINT = os.environ.get("MCP_V2_ENDPOINT", "https://mcp-v2.ovnisystem.com/mcp")


def _redact(token: str) -> str:
    if not token:
        return "<empty>"
    if len(token) <= 12:
        return "<redacted>"
    return token[:6] + "..." + token[-4:]


def call(token: str, tool: str, args: dict[str, Any] = None, timeout: int = 30) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    failures: list[str] = []
    for actor in ("WILLY", "YUNIESKY", "ANET"):
        token = os.environ.get(f"MCP_TOKEN_{actor}")
        if not token:
            print(f"[skip] MCP_TOKEN_{actor} not set")
            continue

        try:
            r = call(token, "odoo_who_am_i")
            res = r.get("result") or {}
            actor_returned = res.get("actor")
            uid = res.get("odoo_uid")
            role = res.get("role")
            # NO imprimir el token bajo ninguna circunstancia.
            print(f"[ok]   {actor.lower():9s}  actor={actor_returned}  uid={uid}  role={role}  token={_redact(token)}")
            if not actor_returned or not uid:
                failures.append(actor)
        except Exception as e:  # noqa: BLE001
            print(f"[fail] {actor.lower():9s}  {e.__class__.__name__}: {str(e)[:120]}")
            failures.append(actor)

    if failures:
        print(f"\nFAIL: {failures}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
