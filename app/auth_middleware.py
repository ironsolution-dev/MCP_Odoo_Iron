"""Pipeline de autenticacion + policy + rate limit + audit para cada request MCP.
Las tools no llaman aqui directamente; se invocan desde el entry point que
envuelve la tool con este middleware.

Reglas:
- Extrae token de Authorization Bearer o del segmento opaco en URL (fallback).
- Redacta token al loguear.
- Rechaza con 401 si no mapea a actor; con 429 si rate limit excede; con 403
  si policy deny.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from app.audit import Audit
from app.policy_engine import PolicyEngine, RateLimit
from app.rate_limit import RateLimiter
from app.token_registry import ActorEntry, TokenRegistry


_BEARER_RE = re.compile(r"^Bearer\s+(\S+)$", re.IGNORECASE)
# Fallback: path con /mcp/<opaque_token>
_PATH_TOKEN_RE = re.compile(r"^/mcp/(\S+?)/?$")


@dataclass(frozen=True)
class AuthContext:
    actor: ActorEntry
    client_type: str
    request_id: str


class AuthError(Exception):
    """Para que el entry point traduzca a 401."""


class DeniedByPolicy(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class DeniedByRateLimit(Exception):
    def __init__(self, reason: str, retry_after: float):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class AuthMiddleware:
    """Glue entre headers/path → actor + checks. NO loguea valores de token."""

    def __init__(
        self,
        registry: TokenRegistry,
        policy: PolicyEngine,
        rate_limiter: RateLimiter,
        audit: Audit,
    ):
        self.registry = registry
        self.policy = policy
        self.rate_limiter = rate_limiter
        self.audit = audit

    # ------------------------------------------------------------------
    # Extraccion
    # ------------------------------------------------------------------

    @staticmethod
    def extract_token(
        authorization_header: Optional[str], path: Optional[str]
    ) -> tuple[Optional[str], str]:
        """Retorna (token, source) donde source ∈ {bearer, path, none}."""
        if authorization_header:
            m = _BEARER_RE.match(authorization_header.strip())
            if m:
                return m.group(1), "bearer"
        if path:
            m = _PATH_TOKEN_RE.match(path)
            if m:
                return m.group(1), "path"
        return None, "none"

    @staticmethod
    def detect_client_type(user_agent: Optional[str], source: str) -> str:
        ua = (user_agent or "").lower()
        if "claude" in ua:
            return "claude_connector"
        if "chatgpt" in ua or "openai" in ua:
            return "chatgpt_connector"
        if "curl" in ua:
            return "curl"
        if source == "path":
            return "opaque_path"
        return "dev"

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def authenticate(
        self,
        authorization_header: Optional[str],
        path: Optional[str],
        user_agent: Optional[str],
        request_id: Optional[str] = None,
    ) -> AuthContext:
        token, source = self.extract_token(authorization_header, path)
        client_type = self.detect_client_type(user_agent, source)
        actor = self.registry.verify(token)
        if actor is None:
            self.audit.emit(
                client_type=client_type, allowed=False,
                denied_reason="invalid_token", request_id=request_id,
            )
            raise AuthError("invalid_token")
        return AuthContext(actor=actor, client_type=client_type,
                            request_id=request_id or "")

    def authorize_tool(
        self,
        ctx: AuthContext,
        tool: str,
        model: str,
        action: str,
        fields: Optional[list[str]] = None,
    ) -> None:
        # Policy check
        decision = self.policy.allows(ctx.actor.policy, tool, model, action, fields=fields)
        if not decision.allowed:
            self.audit.emit(
                request_id=ctx.request_id, actor=ctx.actor.actor, role=ctx.actor.role,
                client_type=ctx.client_type, tool=tool, model=model, action=action,
                allowed=False, denied_reason=decision.denied_reason,
            )
            raise DeniedByPolicy(decision.denied_reason)
        # Rate limit
        rl = self.policy.rate_limit(ctx.actor.policy)
        rl_decision = self.rate_limiter.check(ctx.actor.actor, action, rl)
        if not rl_decision.allowed:
            self.audit.emit(
                request_id=ctx.request_id, actor=ctx.actor.actor, role=ctx.actor.role,
                client_type=ctx.client_type, tool=tool, model=model, action=action,
                allowed=False, denied_reason=rl_decision.denied_reason,
            )
            raise DeniedByRateLimit(rl_decision.denied_reason, rl_decision.retry_after_seconds)

    def audit_success(
        self,
        ctx: AuthContext,
        tool: str,
        model: str,
        action: str,
        latency_ms: int,
        result_count: int = 0,
        odoo_uid: Optional[int] = None,
        args: Optional[dict] = None,
    ) -> None:
        self.audit.emit(
            request_id=ctx.request_id, actor=ctx.actor.actor, role=ctx.actor.role,
            client_type=ctx.client_type, tool=tool, model=model, action=action,
            allowed=True, latency_ms=latency_ms, result_count=result_count,
            odoo_uid=odoo_uid, args=args,
        )

    def audit_error(
        self,
        ctx: AuthContext,
        tool: str,
        model: str,
        action: str,
        latency_ms: int,
        error_class: str,
        args: Optional[dict] = None,
    ) -> None:
        self.audit.emit(
            request_id=ctx.request_id, actor=ctx.actor.actor, role=ctx.actor.role,
            client_type=ctx.client_type, tool=tool, model=model, action=action,
            allowed=True, error_class=error_class, latency_ms=latency_ms, args=args,
        )


def now_ms() -> int:
    return int(time.monotonic() * 1000)
