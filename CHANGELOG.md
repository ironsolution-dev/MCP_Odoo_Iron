# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [0.1.0] — 2026-05-12 (paquete de ingenieria listo para deploy)

### Added

#### Auth y multiusuario
- `app/token_registry.py` — registry hash-based sha256.
- `app/credentials_resolver.py` — env-var-based con `MissingCredentialError` y `__repr__` redactado.
- `app/odoo_client.py` — XML-RPC actor-aware con UID cache TTL 5min. Sin `execute_kw` público, sin `sudo`, sin UID hardcodeado.
- `app/auth_middleware.py` — pipeline auth → policy → rate → audit.
- `app/policy_engine.py` — deny-by-default con denylist global y field allowlists.
- `app/audit.py` — JSONL append-only con redacción y `args_hash`.
- `app/rate_limit.py` — sliding window 60s in-memory por actor.
- `app/schemas.py` — validadores APL 2.0, evidencia, fechas.

#### Tools (30 totales)
- `app/tools/system.py` — `odoo_who_am_i`, `odoo_health`, `odoo_validate_apl_stages`.
- `app/tools/tasks.py` — 9 tools BLUE migradas + 2 nuevas (project tasks) + aliases temporales.
- `app/tools/projects.py` — 5 tools (`list`, `get`, `create`, `update_basic`, `project_tasks`).
- `app/tools/calendar.py` — 3 tools con validación de fechas.
- `app/tools/employees.py` — 3 tools read-only con allowlist.
- `app/tools/crm.py` — 4 tools (read leads + notas/actividades sin cambio etapa/monto).
- `app/tools/partners.py` — 3 tools read-only con allowlist (NUEVO v2).

#### Entry point + deploy
- `app/odoo_mcp_remote.py` — FastMCP streamable-http con TOOL_REGISTRY y wrappers middleware.
- `Dockerfile` Python 3.12-slim + user no-root + healthcheck.
- `scripts/deploy_green.sh` build + run + Traefik labels + smoke curl.
- `scripts/rollback_blue.sh` (improbable, documentado).
- `scripts/smoke_test_mcp.py` con redacción de tokens en output.
- `scripts/snapshot_blue.sh` snapshot completo BLUE pre-cambio.
- `scripts/verify_phase_0.sh` validación DoD Fase 0.
- `scripts/generate_mcp_token.py` emite token + hash una sola vez.
- `scripts/validate_env.py` falla rápido si faltan envs.

#### Config (sin secretos)
- `config/actors.yaml.example` 3 actores (willy/yuniesky/anet) con `token_hash` placeholder.
- `config/policies.yaml.example` 3 policies + denylist global + field allowlists.

#### Tests (66 totales, 100% verdes)
- `tests/test_auth.py` (4) — token registry.
- `tests/test_credentials_and_uid.py` (7) — sin UID 9 hardcodeado, env vars por actor, `MissingCredentialError`, repr redactado, who_am_i sin secretos.
- `tests/test_policy_engine.py` (12) — denylist, allowlists, deny-by-default por las 5 capas.
- `tests/test_tasks_apl.py` (10) — APL 2.0 obligatorio, evidencia obligatoria, no generic execute, no sudo, aliases BLUE, read-after-write.
- `tests/test_new_domains.py` (17) — projects, calendar, employees, crm, partners.
- `tests/test_audit.py` (6) — JSONL, redacción, no secret in logs, args_hash.
- `tests/test_rate_limit.py` (4) — sliding window, pools independientes, isolation por actor.
- `tests/test_auth_middleware.py` (7) — extracción Bearer/path, client_type detection, deny flows.
- `tests/test_blue_intact.py` (1, marker `requires_blue`) — `test_blue_endpoint_still_responsive`.

#### Docs
- `docs/architecture.md` — topología, pipeline interno, decisiones.
- `docs/security.md` — identidades, política de secretos, capas, audit, rotación.
- `docs/runbook.md` — snapshot, DNS+cert, provisioning actores, deploy, smoke, rollback, troubleshooting, rotación tokens.
- `docs/qa-checklist.md` — matriz QA por actor con criterios verificables.
- `docs/APL_STAGES.md` — plantilla para etapas reales Odoo (a llenar por Willy).
- `docs/baseline/*.template.md` — diagnóstico, diff Git/contenedor, spike conectores, permisos Odoo por actor.
- `docs/adr/ADR-001..010.md` — decisiones cerradas v2.
- `docs/result-packet-template.md` — plantilla del Result Packet final.
- `README.md`, `HANDOFF.md`, `CLAUDE.md` (del repo v2).

### Security
- Cero secretos en Git, logs o output de tests.
- Test `test_no_secret_in_logs` verifica audit.
- Test `test_no_hardcoded_uid_9` y `test_no_hardcoded_willy_username` verifican código.
- Test `test_no_generic_execute_tool` verifica que no exista tool genérica.
- Test `test_no_sudo_or_privilege_escalation_in_odoo_client`.

### Pendientes operativos (carril humano de Willy)
- W1 Snapshot BLUE en VPS via `scripts/snapshot_blue.sh`.
- W2 Verificar usuarios Yuniesky/Anet activos en Odoo.
- W3 Crear API keys Odoo para Yuniesky/Anet.
- W4 Ejecutar `generate_mcp_token.py` 3 veces, pegar hashes en `actors.yaml` real.
- W5 Spike Bearer en Claude.ai y ChatGPT (`docs/baseline/connectors_auth_spike.md`).
- W6 Validar etapas APL 2.0 reales (`docs/APL_STAGES.md`).
- W7 Provisionar DNS `mcp-v2.ovnisystem.com` y emisión cert Let's Encrypt.
- W8 QA manual con 3 actores en GREEN.
