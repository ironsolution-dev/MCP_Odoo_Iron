"""Fixtures del servidor MCP real levantado en un socket de loopback
(ticket 807). Separadas de conftest.py para no pasar el limite de 300
lineas/archivo del repo (ver CLAUDE.md) — se registran como plugin via
`pytest_plugins` en tests/conftest.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
import yaml


def _hash(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


class FakeOdooCredentials:
    """Credenciales falsas para tests que suben el servidor MCP completo
    (ticket 807) — nunca se conecta a Odoo real ni a VPS82."""
    username = "smoke@test"
    url = "https://odoo.test/"
    db = "odoo_test"


class FakeOdooClient:
    """Doble de OdooClient para tests end-to-end del transporte HTTP. Solo
    implementa lo que `odoo_who_am_i` necesita — suficiente para probar
    auth/CORS/audit sin tocar Odoo real (ticket 807)."""

    async def authenticate(self, actor):
        return 42

    async def get_credentials(self, actor):
        return FakeOdooCredentials()


@pytest.fixture(scope="session")
def mcp_live_server(tmp_path_factory):
    """Levanta el servidor MCP real (BearerMiddleware + FastMCP) sobre un
    socket de loopback real, UNA sola vez para toda la sesion de tests.

    Por que socket real y por que session-scoped: `StreamableHTTPSessionManager`
    de FastMCP es un singleton por proceso — su `.run()` solo se puede invocar
    UNA vez por instancia (RuntimeError si se reintenta), y `app.odoo_mcp_remote.mcp`
    es un singleton de modulo con las 49 tools ya registradas via decorador en
    import time. Un socket real (uvicorn en background) es ademas lo que exige
    el criterio de aceptacion "cliente MCP con el SDK oficial contra el servidor
    levantado localmente": ese cliente solo habla HTTP/SSE contra una URL, no
    contra un ASGI app in-process.

    OdooClient es un doble (FakeOdooClient) — nada de red a Odoo real ni a
    VPS82 (ticket 807, criterio "todo local con stubs/fixtures").
    """
    import app.odoo_mcp_remote as remote

    tmp = tmp_path_factory.mktemp("mcp_live_server")
    token = "mcp_live_server_test_token_zzzzzzzzzzzzzz"

    actors = {
        "version": 1, "hash_algorithm": "sha256",
        "actors": {
            "willy": {
                "enabled": True, "role": "owner", "display_name": "Willy Hierro",
                "token_hash": _hash(token), "odoo_url_env": "ODOO_URL",
                "odoo_db_env": "ODOO_DB", "odoo_username_env": "ODOO_USERNAME_WILLY",
                "odoo_api_key_env": "ODOO_API_KEY_WILLY", "policy": "owner_policy",
            },
        },
    }
    policies = {
        "version": 1, "denylist_global": [], "field_allowlists": {},
        "policies": {
            "owner_policy": {
                # rate_limit alto: esta sesion sirve a decenas de tests, no es
                # un policy real de produccion.
                "allowed_tools": ["odoo_who_am_i"], "model_rules": {},
                "rate_limit": {"requests_per_minute": 600, "writes_per_minute": 200},
            },
        },
    }
    actors_path, policies_path, audit_path = (
        tmp / "actors.yaml", tmp / "policies.yaml", tmp / "audit.jsonl")
    actors_path.write_text(yaml.safe_dump(actors))
    policies_path.write_text(yaml.safe_dump(policies))

    os.environ["ACTORS_REGISTRY_PATH"] = str(actors_path)
    os.environ["POLICIES_PATH"] = str(policies_path)
    os.environ["AUDIT_LOG_PATH"] = str(audit_path)

    remote.load()
    remote._odoo = FakeOdooClient()

    inner = remote.mcp.streamable_http_app()
    asgi_app = remote.BearerMiddleware(inner)

    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

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
        raise RuntimeError("servidor MCP local (ticket 807) no levanto a tiempo")

    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", token=token, audit_path=audit_path)

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def mcp_live(mcp_live_server):
    """Version function-scoped de `mcp_live_server`: trunca el audit log
    antes de cada test para que cada uno lea solo sus propias entradas del
    log JSONL compartido por la sesion."""
    mcp_live_server.audit_path.write_text("")
    return mcp_live_server
