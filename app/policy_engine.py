"""Policy engine deny-by-default. Valida (rol, tool, modelo, accion, campos)
contra `policies.yaml`. Implementa denylist global, field allowlists y reglas
de tool/modelo por policy.

Regla: si CUALQUIER chequeo falla → denegar. No hay fallbacks ni excepciones.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    denied_reason: Optional[str] = None


@dataclass(frozen=True)
class RateLimit:
    requests_per_minute: int
    writes_per_minute: int


class PolicyEngine:
    def __init__(self, yaml_path: Path):
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self.denylist: list[dict] = data.get("denylist_global", []) or []
        self.field_allowlists: dict[str, list[str]] = data.get("field_allowlists", {}) or {}
        self.policies: dict[str, dict] = data.get("policies", {}) or {}

    # ------------------------------------------------------------------
    # Decision core
    # ------------------------------------------------------------------

    def allows(
        self,
        policy_name: str,
        tool: str,
        model: str,
        action: str,
        fields: Optional[list[str]] = None,
    ) -> PolicyDecision:
        # 1. Denylist global — aplica a todos los actores.
        for rule in self.denylist:
            if rule.get("model") == model and action in (rule.get("actions") or []):
                return PolicyDecision(False, f"globally_denied:{model}:{action}")

        # 2. La policy debe existir.
        policy = self.policies.get(policy_name)
        if not policy:
            return PolicyDecision(False, f"unknown_policy:{policy_name}")

        # 3. Tool debe estar declarada en allowed_tools del rol.
        allowed_tools = policy.get("allowed_tools") or []
        if tool not in allowed_tools:
            return PolicyDecision(False, f"tool_not_allowed:{tool}")

        # 4. Modelo + accion deben estar declarados.
        model_rules = policy.get("model_rules") or {}
        rule = model_rules.get(model)
        if not rule:
            return PolicyDecision(False, f"unknown_model:{model}")
        if not rule.get(action, False):
            return PolicyDecision(False, f"action_not_allowed:{model}:{action}")

        # 5. Campos: si hay allowlist para el modelo, ningun campo solicitado
        #    puede caer fuera de ella.
        if fields and model in self.field_allowlists:
            allowed_fields = set(self.field_allowlists[model])
            invalid = [f for f in fields if f not in allowed_fields]
            if invalid:
                return PolicyDecision(False, f"fields_not_allowed:{model}:{invalid}")

        return PolicyDecision(True)

    # ------------------------------------------------------------------
    # Helpers para tools
    # ------------------------------------------------------------------

    def filter_fields(self, model: str, fields: list[str]) -> list[str]:
        """Filtra campos contra la allowlist del modelo. Usar al construir queries
        para limitar lo que se le pide a Odoo, ademas de la validacion en allows()."""
        allowed = self.field_allowlists.get(model)
        if allowed is None:
            return list(fields)
        allowed_set = set(allowed)
        return [f for f in fields if f in allowed_set]

    def rate_limit(self, policy_name: str) -> RateLimit:
        """Limites del rol; defaults conservadores si no estan declarados."""
        policy = self.policies.get(policy_name) or {}
        rl = policy.get("rate_limit") or {}
        return RateLimit(
            requests_per_minute=int(rl.get("requests_per_minute", 30)),
            writes_per_minute=int(rl.get("writes_per_minute", 10)),
        )

    # ------------------------------------------------------------------
    # Discuss (sec G4) — canales de mail.message(model=discuss.channel)
    # ------------------------------------------------------------------

    def discuss_channel_allowed(self, policy_name: str, channel_id: int) -> PolicyDecision:
        """Allowlist de canales de Discuss por policy. AUSENCIA de la clave
        (o lista vacia) = deny para TODOS los canales — deny-by-default, sin
        excepcion implicita para ningun rol."""
        policy = self.policies.get(policy_name)
        if not policy:
            return PolicyDecision(False, f"unknown_policy:{policy_name}")
        allowlist = policy.get("discuss_channel_allowlist") or []
        if channel_id not in allowlist:
            return PolicyDecision(False, f"discuss_channel_not_allowed:{channel_id}")
        return PolicyDecision(True)

    def attachment_max_bytes(self, policy_name: str) -> int:
        """Limite de tamano (bytes) para copiar adjuntos de Discuss hacia una
        tarea. Default conservador (10 MB, espeja discuss.DEFAULT_ATTACHMENT_MAX_BYTES)
        si la policy no lo declara explicitamente."""
        policy = self.policies.get(policy_name) or {}
        return int(policy.get("discuss_attachment_max_bytes", 10 * 1024 * 1024))
