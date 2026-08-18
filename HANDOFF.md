# HANDOFF — MCP Odoo v2 (Blue/Green)

> Documento operativo para retomar el ticket. **Última actualización:** 18 ago 2026 ~14:30 hrs.

## Estado actual (18 ago 2026 — Fase A "daily driver" aprobada por QA)

- **Ramas vivas:** `rescate/v0.3.5-prod-a-git` (rescató a git el código que vivía SOLO horneado en la imagen `odoo-mcp:multiuser-v0.3.5` de prod — meses de drift prod-vs-git, commit `3f9d55b`) → base de `feature/fase-a-daily-driver` (9 commits, HEAD `72778b3`).
- **Fase A construida:** G1 mover tarea entre proyectos con auditoría en chatter (`odoo_move_task_to_project`) · G2 contrato de escritura de tareas (alias `deadline`→`date_deadline`, validación agregada, split de `openai_compat.py` 680→5 módulos ≤300 líneas con facade) · G3 `user_ids` escribible con salvaguarda hr.employee activo · G4 Discuss (leer/postear canal con allowlist por policy en `config/policies.yaml`, adjuntos copiar-nunca-mover, límite 10MB) · G5 candado anti-drift (`Dockerfile` ARG `GIT_COMMIT`/`MCP_VERSION`, `odoo_health` los expone, `deploy_green.sh` exige working tree limpio + tag antes de construir).
- **QA:** 2 auditorías — rechazo con bug real (facade no reexportaba `move_task_to_project`, `AttributeError` en la tool standalone) → fix quirúrgico `72778b3` con test de no-regresión → re-QA aprobado. Suite 68→100 tests (101 colectados, 1 skip `requires_odoo`).
- **ADRs 011-015** y `docs/architecture.md`/`docs/security.md` ya actualizados por el builder en `docs/adr/`.
- **Qué falta para deploy:** (1) merge `feature/fase-a-daily-driver` → `main` (release/Infinity) · (2) build y tag `multiuser-v0.4.0` vía `scripts/deploy_green.sh` (exige tree limpio + tag, ADR-015) · (3) `config/policies.yaml` real del VPS con `discuss_channel_allowlist` poblado (Fase A solo trae `[53]` para Willy en el `.example`) · (4) correr `scripts/acceptance_fase_a_live.py --confirm` — mueve en vivo las tareas reales 653/654/655/657 (proyecto 3→12) y corre el deadline de la 655 — commiteado pero NO ejecutado, requiere OK explícito de Willy.

## Estado anterior (cierre definitivo de jornada 12 may 2026)

### ✅ Todo aplicado en VPS
- `https://mcp-v2.ovnisystem.com/mcp` — Up (healthy), commit `f7639fe` aplicado.
- SSL Let's Encrypt válido hasta ago 2026.
- BLUE `https://mcp.ovnisystem.com/mcp` — intocable, 9 tools funcionando.
- **11 commits** en `feature/v2-multiusuario`, todos en VPS.
- **PR #1 creado** en GitHub: `release/v0.2.0 → main` (NO mergear hasta QA Yuniesky+Anet + Result Packet).

### ✅ VPS al día — NO necesita redeploy al arrancar mañana
El VPS tiene commit `f7639fe` (CHANGELOG + HANDOFF). Próxima sesión arranca directo con QA.
```

### QA ejecutado hasta hoy
| Actor | Conector | Tool | Resultado |
|---|---|---|---|
| Willy | Claude.ai | `odoo_who_am_i` | ✅ actor=willy, uid=9, owner |
| Willy | Claude.ai | `odoo_my_tasks` | ✅ 5 tareas reales |
| Willy | Claude.ai | `odoo_list_projects` | ✅ 6 proyectos reales |
| Yuniesky | — | pendiente | ❌ |
| Anet | — | pendiente | ❌ |

### Campos inválidos en esta instancia de Odoo (descubiertos en QA)
| Campo | Modelo | Razón | Fix commit |
|---|---|---|---|
| `kanban_state` | `project.task` | Módulo kanban no habilitado | `bfec76d` |
| `stage_id` | `project.project` | Feature "Etapas" no habilitada | `c30f111` |

### Conectores validados
- **Claude.ai:** token en path `/mcp/<token>`. UI no tiene campo Bearer. Middleware ASGI reescribe path → `/mcp`. ✅ Funcionando.
- **ChatGPT:** `X-Api-Key` header. GET sin SSE → 200 discovery. Fix aplicado. Pendiente QA completo.

### Score ticket: 11.5/13 — Técnico completo. Falta QA Yuniesky+Anet y Result Packet.

### Para mañana — orden exacto (estimado 1h)
| # | Acción | Quién | Tiempo |
|---|---|---|---|
| 1 | Verificar `tail -5 /opt/odoo-mcp-v2/logs/audit.jsonl` tiene entries `allowed:true` | Willy en VPS | 2 min |
| 2 | Yuniesky conecta Claude.ai con URL `https://mcp-v2.ovnisystem.com/mcp/mcp_fyWMoN8drs06p3k7JV4QsuLU30n1HSuOlab_KalIcP4` | Yuniesky | 10 min |
| 3 | Yuniesky ejecuta `odoo_who_am_i` + `odoo_my_tasks` | Yuniesky | 5 min |
| 4 | Anet conecta Claude.ai con URL `https://mcp-v2.ovnisystem.com/mcp/mcp_NoEJYKVwozVWGzEOPfh-grSmz-Kmhf9FuG4kfb-F6OI` | Anet | 10 min |
| 5 | Anet ejecuta `odoo_who_am_i` | Anet | 2 min |
| 6 | Ejecutar `odoo_validate_apl_stages` → llenar `docs/APL_STAGES.md` | Willy/JuliO | 5 min |
| 7 | Llenar y firmar `docs/result-packet-template.md` | Willy | 20 min |
| 8 | Aprobar y mergear PR #1 en GitHub | Willy | 2 min |

### PR en GitHub
- **URL:** `https://github.com/ironsolution-dev/MCP_Odoo_Iron/pull/1`
- **Branch:** `release/v0.2.0 → main`
- **Estado:** Abierto. NO mergear hasta completar pasos 1-7 arriba.

---

## Estado anterior (cierre del paquete de ingeniería, 12 may 2026)

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

| # | Criterio | Estado | Notas |
|---|---|---|---|
| 1 | BLUE responde OK durante transición | ✅ | Verificado múltiples veces hoy |
| 2 | GREEN operativo con cert SSL válido | ✅ | mcp-v2.ovnisystem.com, cert Let's Encrypt ago 2026 |
| 3 | `odoo_who_am_i` retorna 3 actores | ✅ parcial | Willy ✅ live. Yuniesky+Anet pendientes |
| 4 | Credenciales independientes (no UID 9 hardcodeado) | ✅ | Tests + verificado live (uid 9/11/14) |
| 5 | Policy engine deny-by-default | ✅ | 12 tests + token inválido → 401 live |
| 6 | Tools tareas con read-after-write | ✅ código | odoo_my_tasks verified live |
| 7 | Tools calendario con validación | ✅ código | Pendiente prueba live |
| 8 | Tools proyecto campos básicos | ✅ | odoo_list_projects verified live |
| 9 | Allowlists hr.employee y res.partner | ✅ código | Pendiente prueba live |
| 10 | CRM read-only + notas | ✅ código | Pendiente prueba live |
| 11 | Audit JSONL con redacción | ✅ código | Fix P1 aplicado — pendiente verificación live |
| 12 | Rate limits | ✅ código | 4 tests verdes |
| 13 | Rollback + Result Packet firmado | ❌ | Pendiente QA completo + firma Willy+Daniel |

## Cómo retomar este trabajo

1. Leer `TASK_PACKET_v2_MCP_Odoo_APL_2_0_Multiusuario_BlueGreen.md` (repo padre).
2. Leer este HANDOFF.
3. Si el carril humano (W1-W8) está incompleto: arrancar por ahí.
4. Si Willy ya hizo el carril: arrancar deploy según sección "Cómo desplegar".
5. Tras QA exitosa: llenar `docs/result-packet-template.md` con outputs reales y archivar como `docs/result-packet-2026-05-12.md`.
