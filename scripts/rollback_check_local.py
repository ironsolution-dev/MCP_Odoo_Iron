"""Prueba en local el procedimiento de vuelta atras del ticket 807: crea un
git worktree en un sha/tag anterior, levanta el servidor MCP ahi (con
fixtures locales, sin Odoo real) y confirma que responde igual que antes
del cambio. Es la prueba EJECUTADA, no solo la instruccion escrita — ver
docs/runbook.md seccion "Rollback (ticket 807)".

Uso:
    python scripts/rollback_check_local.py [<git-ref>]

Sin argumento usa `main` (la punta antes de la rama del ticket). Requiere
un Python con las dependencias del proyecto instaladas (mcp, uvicorn,
httpx, pyyaml) — el mismo venv que corre `pytest tests/`.

No toca VPS82, no toca Odoo real, no toca el arbol de trabajo actual: crea
un `git worktree` aparte a partir del ref pedido y lo borra al terminar.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _hash(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "main"
    resolved = subprocess.run(
        ["git", "rev-parse", ref], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    print(f"[1/4] Rollback check contra ref={ref} (sha={resolved})")

    worktree_dir = Path(tempfile.mkdtemp(prefix="odoo-mcp-rollback-"))
    worktree_dir.rmdir()  # git worktree add exige que no exista
    try:
        print(f"[2/4] git worktree add --detach {worktree_dir} {ref}")
        _run(["git", "worktree", "add", "--detach", str(worktree_dir), ref],
             cwd=REPO_ROOT)

        print("[3/4] Levantando servidor MCP en el worktree del sha anterior ...")
        ok = _smoke_test(worktree_dir)

        print("[4/4] Limpiando worktree ...")
        if ok:
            print("\nROLLBACK OK: el sha/tag anterior arranca y responde "
                  "correctamente (POST tools/list -> 200, token invalido -> 401).")
        return 0 if ok else 1
    finally:
        _run(["git", "worktree", "remove", "--force", str(worktree_dir)], cwd=REPO_ROOT)
        shutil.rmtree(worktree_dir, ignore_errors=True)


def _smoke_test(worktree_dir: Path) -> bool:
    import os

    sys.path.insert(0, str(worktree_dir))
    tmp = Path(tempfile.mkdtemp(prefix="odoo-mcp-rollback-cfg-"))
    token = "mcp_rollback_check_token_aaaaaaaaaaaaaaaaaaaa"

    import yaml

    actors = {
        "version": 1, "hash_algorithm": "sha256",
        "actors": {"willy": {
            "enabled": True, "role": "owner", "display_name": "Willy",
            "token_hash": _hash(token), "odoo_url_env": "ODOO_URL",
            "odoo_db_env": "ODOO_DB", "odoo_username_env": "ODOO_USERNAME_WILLY",
            "odoo_api_key_env": "ODOO_API_KEY_WILLY", "policy": "owner_policy",
        }},
    }
    policies = {
        "version": 1, "denylist_global": [], "field_allowlists": {},
        "policies": {"owner_policy": {
            "allowed_tools": ["odoo_who_am_i"], "model_rules": {},
            "rate_limit": {"requests_per_minute": 60, "writes_per_minute": 20},
        }},
    }
    (tmp / "actors.yaml").write_text(yaml.safe_dump(actors))
    (tmp / "policies.yaml").write_text(yaml.safe_dump(policies))
    os.environ["ACTORS_REGISTRY_PATH"] = str(tmp / "actors.yaml")
    os.environ["POLICIES_PATH"] = str(tmp / "policies.yaml")
    os.environ["AUDIT_LOG_PATH"] = str(tmp / "audit.jsonl")

    import app.odoo_mcp_remote as m
    print(f"      modulo cargado desde: {m.__file__}")
    m.load()

    inner = m.mcp.streamable_http_app()
    asgi_app = m.BearerMiddleware(inner)

    import uvicorn

    port = _free_port()
    config = uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        print("      FAIL: el servidor no levanto a tiempo")
        return False

    import httpx

    try:
        r = httpx.post(
            f"http://127.0.0.1:{port}/mcp/{token}",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
            timeout=10,
        )
        tools = r.json().get("result", {}).get("tools", []) if r.status_code == 200 else []
        print(f"      POST tools/list -> {r.status_code} ({len(tools)} tools)")

        r2 = httpx.post(
            f"http://127.0.0.1:{port}/mcp/token-invalido",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream",
                     "Content-Type": "application/json"},
            timeout=10,
        )
        print(f"      POST token invalido -> {r2.status_code}")

        return r.status_code == 200 and len(tools) > 0 and r2.status_code == 401
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        # No dejar el modulo del worktree contaminando sys.modules para
        # el resto del proceso (defensivo — este script termina despues).
        sys.path.remove(str(worktree_dir))


if __name__ == "__main__":
    sys.exit(main())
