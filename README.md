# MCP Odoo APL 2.0 — Multiusuario (v2 Blue/Green)

Servidor MCP FastMCP que expone Odoo 19 Community a Claude.ai y ChatGPT como conector personalizado, con identidad por actor, policy engine RBAC, auditoría JSONL y guardrails APL 2.0.

> **Identidad operativa:** JuliO I/O.
> **Estrategia de despliegue:** Blue/Green. BLUE (`mcp.ovnisystem.com`) intocable; GREEN (`mcp-v2.ovnisystem.com`) endpoint nuevo multiactor.
> **Fuente de verdad operativa:** `TASK_PACKET_v2_MCP_Odoo_APL_2_0_Multiusuario_BlueGreen.md` en el repo padre de JuliO I/O.

---

## Estado v0.1.0

- Multiusuario para Willy (owner), Yuniesky (operations), Anet (medical_direction).
- Token registry hash-based.
- Policy engine deny-by-default.
- Allowlists estrictas para `hr.employee` y `res.partner`.
- Audit JSONL con redacción.
- 9 tools BLUE migradas a actor-aware + nuevos dominios (projects, calendar, employees, crm, partners).

## Quick start (desarrollo local)

```bash
# 1. Crear venv y dependencias
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Tests
pytest tests/ -v

# 3. Generar token para un actor (ejecutar 1 vez por actor)
python scripts/generate_mcp_token.py --actor willy

# 4. Validar variables de entorno
python scripts/validate_env.py
```

## Deploy (lo ejecuta Willy en VPS)

Ver `docs/runbook.md`. Pasos resumidos:

1. `bash scripts/snapshot_blue.sh` — snapshot completo BLUE antes de tocar nada.
2. Pegar hashes de tokens en `/opt/odoo-mcp-v2/secrets/actors.yaml`.
3. Crear `/opt/odoo-mcp-v2/secrets/.env.v2` con credenciales Odoo de los 3 actores (ver `docs/runbook.md`).
4. `bash scripts/deploy_green.sh` — build + run GREEN container con Traefik labels.
5. `python scripts/smoke_test_mcp.py` con `MCP_TOKEN_*` exportados.
6. QA manual con los 3 actores (ver `docs/qa-checklist.md`).

## Variables de entorno requeridas

| Var | Uso |
|---|---|
| `ODOO_URL` | URL de Odoo (`https://odoo.ironsolution.us/`) |
| `ODOO_DB` | Database name (`odoo_db`) |
| `ODOO_USERNAME_WILLY` / `_YUNIESKY` / `_ANET` | Login Odoo de cada actor |
| `ODOO_API_KEY_WILLY` / `_YUNIESKY` / `_ANET` | API Key Odoo de cada actor (NUNCA en logs/prompts) |
| `ACTORS_REGISTRY_PATH` | Ruta a `actors.yaml` real (no el `.example`) |
| `POLICIES_PATH` | Ruta a `policies.yaml` real |
| `AUDIT_LOG_PATH` | Ruta a `audit.jsonl` (default `/opt/odoo-mcp-v2/logs/audit.jsonl`) |

## Política de secretos

- Cero secretos en Git, logs, README, prompts, output de tests.
- `MCP_TOKEN` ≠ `ODOO_API_KEY`.
- Tokens MCP se guardan como hash (sha256).
- Headers `Authorization` redactados en logs.

Ver `docs/security.md` para detalle completo.

## Documentación

- `docs/architecture.md` — topología, diagrama interno, flujo auth.
- `docs/security.md` — secret handling, policy engine, denylist, audit.
- `docs/runbook.md` — deploy, rollback, healthcheck, troubleshooting.
- `docs/qa-checklist.md` — matriz QA por actor.
- `docs/APL_STAGES.md` — etapas APL 2.0 reales en Odoo.
- `docs/adr/` — ADRs 001-015 (011-015: Fase A daily driver, 18-ago-2026); 016-017: ticket 737 — alineacion con la guia APL 2.0 V2 v1.1 (titulo dual legado/nuevo, fuente unica de IDs de etiquetas), 27-ago-2026.
- `HANDOFF.md` — estado operativo, pendientes, contacto.
- `CHANGELOG.md` — cambios versionados.
