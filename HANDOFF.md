# HANDOFF — MCP Odoo v2 (Blue/Green)

> Documento operativo para retomar el ticket en cualquier momento. Refleja estado real al cierre de Fase 8.

## Estado actual (cierre del paquete de ingeniería, 12 may 2026)

- Repo v2 completo con estructura sec 16.1 del Task Packet.
- 8 fases del Task Packet ejecutadas localmente.
- 66/66 tests pasando (incluye `test_blue_endpoint_still_responsive` ✅).
- Cero secretos en Git ni en tests.
- Sin hardcoding de UID ni de username de Willy.
- Sin tool genérica `execute_kw`.
- Read-after-write en todas las tools de escritura.

## Lo que sí está hecho (entregable local)

### Código + tests
- 13 módulos en `app/` (auth pipeline + 7 tool modules + odoo_client + schemas + entry point).
- 30 tools en 7 dominios (system, tasks, projects, calendar, employees, crm, partners).
- 8 archivos de tests, 66 tests verdes.
- Dockerfile y 7 scripts (snapshot, deploy, rollback, smoke, generate_token, validate_env, verify_phase_0).
- Configs sin secretos: `actors.yaml.example`, `policies.yaml.example`.

### Documentación
- `README`, `HANDOFF`, `CLAUDE.md` del repo, `CHANGELOG`.
- `docs/architecture.md`, `docs/security.md`, `docs/runbook.md`, `docs/qa-checklist.md`.
- `docs/APL_STAGES.md` (plantilla con TODO_WILLY).
- `docs/baseline/*.template.md` (4 plantillas con TODO_WILLY).
- `docs/adr/ADR-001..010.md` (10 ADRs).
- `docs/result-packet-template.md`.

## Lo que NO se ha hecho aún (carril humano de Willy + deploy)

| # | Tarea | Bloquea |
|---|---|---|
| W1 | Ejecutar `scripts/snapshot_blue.sh` en VPS root@82.25.90.203 | Deploy GREEN |
| W2 | Verificar usuarios Yuniesky/Anet activos en Odoo (Configuración → Usuarios) | QA |
| W3 | Crear API keys Odoo para Yuniesky y Anet (Preferencias → Seguridad) | Deploy GREEN |
| W4 | Ejecutar `python scripts/generate_mcp_token.py --actor {willy,yuniesky,anet}` 3 veces. Guardar tokens planos en gestor seguro de cada actor. Pegar `token_hash` en `/opt/odoo-mcp-v2/secrets/actors.yaml` (no el `.example`) | Deploy GREEN |
| W5 | Spike Bearer en Claude.ai + ChatGPT — llenar `docs/baseline/connectors_auth_spike.md` | Decisión final de auth |
| W6 | Validar etapas APL 2.0 reales vía MCP BLUE — llenar `docs/APL_STAGES.md` | Tools de etapa |
| W7 | Provisionar DNS `mcp-v2.ovnisystem.com → 82.25.90.203` y dejar Traefik con cert Let's Encrypt válido (ver `docs/runbook.md` sec 1) | Deploy GREEN |
| W8 | QA manual con 3 actores en GREEN — completar `docs/qa-checklist.md` | Cierre Result Packet |

## Cómo desplegar (instrucciones para Willy en otra sesión)

```bash
ssh root@82.25.90.203

# Pre-requisitos del VPS
mkdir -p /opt/odoo-mcp-v2/{repo,backups,logs,secrets}
cd /opt/odoo-mcp-v2

# 1) Clonar / copiar este repo a /opt/odoo-mcp-v2/repo (vía git pull, scp, rsync).
# 2) Poblar secrets:
cp /opt/odoo-mcp-v2/repo/config/actors.yaml.example /opt/odoo-mcp-v2/secrets/actors.yaml
cp /opt/odoo-mcp-v2/repo/config/policies.yaml.example /opt/odoo-mcp-v2/secrets/policies.yaml
# Editar actors.yaml con los 3 token_hash (W4)
# Crear /opt/odoo-mcp-v2/secrets/.env.v2 con ODOO_URL/DB y las 6 vars de los 3 actores
chmod 0640 /opt/odoo-mcp-v2/secrets/*
chown -R root:docker /opt/odoo-mcp-v2/secrets

# 3) Snapshot BLUE (W1)
cd /opt/odoo-mcp-v2/repo
bash scripts/snapshot_blue.sh

# 4) Deploy GREEN
bash scripts/deploy_green.sh

# 5) Smoke test desde tu maquina
export MCP_TOKEN_WILLY=...   # los 3 tokens planos
export MCP_TOKEN_YUNIESKY=...
export MCP_TOKEN_ANET=...
python scripts/smoke_test_mcp.py

# 6) QA manual segun docs/qa-checklist.md
```

## Decisiones tomadas

- Repo vive local + va a GitHub + va a VPS. Willy decide el remote final.
- JuliO desarrolló todo local; Willy despliega en otra sesión.
- Las 8 fases del Task Packet completas como paquete de ingeniería.
- BLUE intocable durante toda la transición.
- Conector productivo de Willy NO se migra hoy; sub-ticket P1 post-validación.

## Contactos / ownership

- **Responsable técnico:** JuliO I/O (Claude Code Opus 4.7).
- **Responsable humano:** Willy Hierro (sistemas@ironsolution.us).
- **Revisión final:** Willy + Daniel.

## Estado de los criterios de cierre (13 DoD del Task Packet sec 5.6)

| # | Criterio | Estado local | Bloqueado por |
|---|---|---|---|
| 1 | BLUE responde OK durante transición | ✅ verificado (`test_blue_endpoint_still_responsive`) | — |
| 2 | GREEN operativo con cert SSL | ⏳ pendiente W7 + deploy | W1, W3, W4, W7 |
| 3 | `odoo_who_am_i` retorna 3 actores | ⏳ pendiente smoke real | deploy |
| 4 | Credenciales independientes (no UID 9 hardcodeado) | ✅ verificado (tests + grep) | — |
| 5 | Policy engine deny-by-default | ✅ verificado (12 tests) | — |
| 6 | Tools tareas con read-after-write | ✅ verificado | — |
| 7 | Tools calendario con validación | ✅ verificado | — |
| 8 | Tools proyecto campos básicos | ✅ verificado | — |
| 9 | Allowlists hr.employee y res.partner | ✅ verificado | — |
| 10 | CRM read-only + notas | ✅ verificado | — |
| 11 | Audit JSONL con redacción | ✅ verificado | — |
| 12 | Rate limits | ✅ verificado | — |
| 13 | Rollback ensayado + Result Packet firmado | ⏳ ensayo + firma en deploy | W8 |

## Cómo retomar este trabajo

1. Leer `TASK_PACKET_v2_MCP_Odoo_APL_2_0_Multiusuario_BlueGreen.md` (repo padre).
2. Leer este HANDOFF.
3. Si el carril humano (W1-W8) está incompleto: arrancar por ahí.
4. Si Willy ya hizo el carril: arrancar deploy según sección "Cómo desplegar".
5. Tras QA exitosa: llenar `docs/result-packet-template.md` con outputs reales y archivar como `docs/result-packet-2026-05-12.md`.
