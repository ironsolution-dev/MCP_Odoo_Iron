# Arquitectura — MCP Odoo v2 (Blue/Green)

## Topología de despliegue

```
                    ┌─────────────────────────────────────────────┐
                    │            VPS Infinity (82.25.90.203)      │
                    │                                             │
   Claude.ai ───┐   │   ┌───────────────┐   ┌──────────────────┐ │
   ChatGPT  ───┼──►│──►│ Traefik       │──►│ odoo-mcp (BLUE)  │ │
                │   │   │ Let's Encrypt │   │ port 8000        │ │
   (PROD)       │   │   │               │   │ INTOCABLE        │ │
                │   │   │               │   └──────────────────┘ │
                │   │   │   Host:       │   ┌──────────────────┐ │
                │   │   │   mcp.ovni... │──►│ odoo-mcp-v2      │ │
                │   │   │               │   │ (GREEN)          │ │
   Claude.ai ───┤   │   │   Host:       │   │ port 8000 int    │ │
   ChatGPT  ───┘   │   │   mcp-v2.ovni │   │ NUEVO            │ │
                    │   │               │   └──────────────────┘ │
   (TEST + DEV)     │   └───────────────┘            │           │
                    │                                ▼           │
                    └────────────────────────────────│───────────┘
                                                     │ XML-RPC
                                                     ▼
                          ┌──────────────────────────────────────┐
                          │ Odoo 19 Community                    │
                          │ https://odoo.ironsolution.us/        │
                          │ Odoo ACL / record rules authoritative│
                          └──────────────────────────────────────┘
```

## Pipeline interno del contenedor GREEN

```
[HTTPS POST mcp-v2.ovnisystem.com/mcp]
        │
        ▼
[Traefik] ── TLS terminator, Let's Encrypt
        │
        ▼
[FastMCP streamable-http] ── app/odoo_mcp_remote.py
        │
        ▼
[auth_middleware] ── extrae token Bearer o segmento opaco; detecta client_type
        │
        ▼
[token_registry] ── hash → ActorEntry (no token plano nunca)
        │
        ▼
[policy_engine] ── deny-by-default (denylist + tool + modelo + acción + campos)
        │
        ▼
[rate_limiter] ── sliding window 60s por actor
        │
        ▼
[tool funcional] ── app/tools/*.py
        │
        ▼
[odoo_client] ── XML-RPC execute_kw con creds del actor (NO sudo, NO genérico)
        │
        ▼
[audit] ── JSONL append + fsync + redacción
```

## Componentes

| Componente | Path | Responsabilidad |
|---|---|---|
| Entry point | [app/odoo_mcp_remote.py](app/odoo_mcp_remote.py) | Bootstrap FastMCP, registro tools, wrappers |
| Auth middleware | [app/auth_middleware.py](app/auth_middleware.py) | Token extract, policy, rate, audit en pipeline |
| Token registry | [app/token_registry.py](app/token_registry.py) | Hash → ActorEntry |
| Credentials resolver | [app/credentials_resolver.py](app/credentials_resolver.py) | Actor → OdooCredentials (sin exponer) |
| Policy engine | [app/policy_engine.py](app/policy_engine.py) | Decisión rol/tool/modelo/acción/campos |
| Audit | [app/audit.py](app/audit.py) | JSONL append + redacción + fsync |
| Rate limit | [app/rate_limit.py](app/rate_limit.py) | Sliding window 60s in-memory |
| Schemas | [app/schemas.py](app/schemas.py) | Validadores APL 2.0, fechas, evidencia |
| Odoo client | [app/odoo_client.py](app/odoo_client.py) | XML-RPC actor-aware con UID cache 5min |
| Tools | [app/tools/*.py](app/tools/) | Tools por dominio (tasks, projects, calendar, employees, crm, partners, system) |
| Discuss | [app/tools/discuss.py](app/tools/discuss.py) | Leer/postear canal (mail.message model=discuss.channel) + copiar adjunto hacia tarea (sec G4, ADR-013/014) |
| Task assignment | [app/tools/task_assignment.py](app/tools/task_assignment.py) | Salvaguarda: `user_ids` solo escribible si mapea a hr.employee activo (sec G3) |
| OpenAI compat | [app/tools/openai_search.py](app/tools/openai_search.py), [openai_write_dispatch.py](app/tools/openai_write_dispatch.py), [openai_write_ops.py](app/tools/openai_write_ops.py), [openai_formatters.py](app/tools/openai_formatters.py) | `search`/`fetch` + protocolo de escritura para ChatGPT chat-mode; `openai_compat.py` es el facade publico (ADR-011) |

## Flujo de auth

```
1. Request entra a FastMCP con Authorization: Bearer mcp_xxx
   (o fallback: path /mcp/<opaque>)

2. auth_middleware.authenticate(authorization_header, path, user_agent):
   a. extract_token() detecta fuente (bearer | path | none)
   b. detect_client_type() infiere claude_connector | chatgpt_connector | curl | dev
   c. registry.verify(token) → ActorEntry o None
   d. Si None → 401 invalid_token + audit denied

3. auth_middleware.authorize_tool(ctx, tool, model, action, fields):
   a. policy.allows(...) → PolicyDecision allow/deny
   b. Si deny → 403 + audit denied_reason
   c. rate_limiter.check(actor, action, limit) → RateLimitDecision
   d. Si deny → 429 + retry_after

4. Tool ejecuta con OdooClient. Si escribe: read-after-write.

5. auth_middleware.audit_success(...) emite linea JSONL con request_id,
   latency_ms, result_count, args_hash (no args en claro).
```

## Decisiones (ADRs)

Ver `docs/adr/`. Las decisiones centrales están cerradas:

- ADR-001 Refactor incremental, no greenfield.
- ADR-002 Un solo contenedor multiactor.
- ADR-003 MCP token ≠ Odoo API key.
- ADR-004 Odoo ACL + MCP policy engine (defensa en profundidad).
- ADR-005 Solo tools específicas + read-after-write.
- ADR-006 Audit JSONL.
- ADR-007 Bearer preferred + fallback ruta opaca.
- ADR-008 Blue/Green, BLUE intocable.
- ADR-009 `res.partner` read-only allowlist.
- ADR-010 Dual connector Claude.ai + ChatGPT.
- ADR-011 Split facade de `openai_compat.py` (Fase A, sec G1).
- ADR-012 Contrato de escritura de tareas: alias + validacion agregada (Fase A, sec G2).
- ADR-013 Allowlist de canales de Discuss por policy (Fase A, sec G4).
- ADR-014 Adjuntos de Discuss: copiar, nunca mover (Fase A, sec G4).
- ADR-015 Trazabilidad build↔git permanente (Fase A, sec G5).

## Limits operativos fase 1

| Métrica | Objetivo |
|---|---|
| p95 lectura simple | < 4s |
| p95 escritura | < 6s (incluye read-after-write) |
| Audit completeness | 100% requests |
| Secret leakage | 0 |
| Tests criticos | 100% pasando |

## Lo que NO está en alcance fase 1

- Reescritura completa del MCP.
- Cambio de framework.
- Modificación de BLUE.
- OAuth completo.
- Persistencia DB de auditoría (solo JSONL).
- Escritura en account.*, stock.*, purchase.order, sale.order, res.users, res.company, ir.*, hr.contract.
- Migración del conector productivo de Willy de BLUE a GREEN (sub-ticket separado).
