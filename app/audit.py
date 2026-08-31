"""Audit log JSONL append-only. Una linea por request.
Redacta tokens, headers Authorization y argumentos sensibles.
Sustituye `args` por `args_hash` sha256 para evitar leaks.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional


# Claves de campos que NUNCA deben aparecer en claro en el log.
_REDACT_KEYS = {
    "authorization", "api_key", "mcp_token", "password",
    "token", "secret", "credentials", "bearer",
}


def _hash_args(args: Any) -> str:
    payload = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _scrub(value: Any) -> Any:
    """Camina recursivamente value y reemplaza valores asociados a claves sospechosas
    por '<redacted>'. No modifica el original."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _REDACT_KEYS:
                out[k] = "<redacted>"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class Audit:
    """Log JSONL append-only con fsync por linea.
    Ver sec 14.3 Task Packet para campos obligatorios."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        *,
        actor: Optional[str] = None,
        role: Optional[str] = None,
        client_type: Optional[str] = None,
        user_agent: Optional[str] = None,
        tool: Optional[str] = None,
        model: Optional[str] = None,
        action: Optional[str] = None,
        allowed: Optional[bool] = None,
        denied_reason: Optional[str] = None,
        latency_ms: Optional[int] = None,
        result_count: Optional[int] = None,
        odoo_uid: Optional[int] = None,
        error_class: Optional[str] = None,
        args: Optional[dict] = None,
        request_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> str:
        rid = request_id or str(uuid.uuid4())
        entry: dict[str, Any] = {
            "request_id": rid,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "actor": actor,
            "role": role,
            "client_type": client_type,
            "user_agent": user_agent,
            "tool": tool,
            "model": model,
            "action": action,
            "allowed": allowed,
            "denied_reason": denied_reason,
            "latency_ms": latency_ms,
            "result_count": result_count,
            "odoo_uid": odoo_uid,
            "error_class": error_class,
        }
        if args is not None:
            entry["args_hash"] = _hash_args(args)
        if extra:
            entry["extra"] = _scrub(extra)

        # Eliminar claves None para mantener log limpio
        entry = {k: v for k, v in entry.items() if v is not None}

        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        return rid


def redact_header(header_value: str) -> str:
    """Para incluir info de Authorization sin filtrar el token completo."""
    if not header_value:
        return ""
    if len(header_value) <= 16:
        return "<redacted>"
    return header_value[:8] + "..." + header_value[-4:]
