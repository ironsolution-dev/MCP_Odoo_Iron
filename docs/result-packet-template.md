# Result Packet — MCP Odoo APL 2.0 Multiusuario v2 (Blue/Green)

> Plantilla a llenar al cierre del ticket por Willy con apoyo de JuliO.

## 1. Resumen ejecutivo

- **Branch principal:** `feature/v2-audit-deploy` (mergeado a `develop`).
- **Commits:** TODO — pegar hashes principales.
- **Fecha de cierre:** 12 may 2026 HH:MM.
- **Responsable técnico:** JuliO I/O (Claude Code Opus 4.7).
- **Responsable humano:** Willy Hierro.
- **Revisión final:** Willy + Daniel.

## 2. Objetivo ejecutado

Refactor del MCP Odoo APL 2.0 desde monousuario Willy hacia multiusuario (Willy, Yuniesky, Anet) con identidad por actor, token registry hash-based, policy engine deny-by-default, allowlists, audit JSONL, rate limits, y soporte extendido a 7 modelos Odoo (project.task, project.project, calendar.event, hr.employee, crm.lead, res.partner, mail.{message,activity}). Desplegado en `mcp-v2.ovnisystem.com` con BLUE intacto en `mcp.ovnisystem.com`.

## 3. Archivos creados/modificados

```
app/         13 archivos (entry point + middleware + 7 tool modules + 4 helpers)
config/      2 archivos .example (actors, policies)
scripts/     7 scripts (snapshot, deploy, rollback, smoke, generate_token,
             validate_env, verify_phase_0)
tests/       8 archivos de tests (66 tests verdes)
docs/        13 archivos (architecture, security, runbook, qa-checklist,
             APL_STAGES, baseline/, adr/ x10, result-packet)
+ Dockerfile, pyproject.toml, README, HANDOFF, CHANGELOG, CLAUDE.md
```

## 4. Cambios funcionales

- Multiusuario en `mcp-v2.ovnisystem.com` para 3 actores.
- Tools BLUE (9) migradas a actor-aware con aliases.
- Tools nuevas (21): 3 system, 9 tasks (incluyendo 6 nuevas), 5 projects, 3 calendar, 3 employees, 4 crm, 3 partners.
- APL 2.0 obligatorio en creación de tareas; evidencia obligatoria en cierre.
- Read-after-write en TODAS las tools de escritura.
- Dual-connector: Claude.ai + ChatGPT en paralelo.

## 5. Cambios de seguridad

- Token registry hash-based (sha256) en `actors.yaml` (real, no commitado).
- Credentials resolver vía env vars; `OdooCredentials.__repr__` redacta api_key.
- Policy engine deny-by-default con denylist global (12 modelos prohibidos).
- Allowlists estrictas `hr.employee` y `res.partner` (NUEVO v2).
- Audit JSONL con redacción de tokens/headers y `args_hash` en lugar de args.
- Rate limits sliding window 60s por actor.
- Validación APL 2.0 + evidencia + fechas calendar.
- NO `execute_kw` genérico, NO `sudo`, NO hardcoded UID.

## 6. Pruebas ejecutadas

### Automatizadas

```bash
pytest tests/ -v
# Esperado: 66 passed (incluye test_blue_endpoint_still_responsive con marker requires_blue)
```

TODO_WILLY: pegar output último.

### Smoke GREEN

```bash
python scripts/smoke_test_mcp.py
# Esperado: ALL OK con [ok] willy / yuniesky / anet
```

TODO_WILLY: pegar output.

## 7. Evidencia de audit log

Líneas de muestra (con secretos redactados, sacadas tras QA con los 3 actores):

```json
TODO_WILLY: pegar 4-5 lineas reales de /opt/odoo-mcp-v2/logs/audit.jsonl
```

Patrones esperados:
- Success: `{"actor":"willy","tool":"odoo_who_am_i","allowed":true,...}`
- Denied policy: `{"actor":"yuniesky","tool":"odoo_create_project","allowed":false,"denied_reason":"tool_not_allowed:..."}`
- Denied rate: `{...,"denied_reason":"requests_per_minute_exceeded"}`
- Args hash: `{...,"args_hash":"sha256:..."}` sin args en claro.

## 8. Validación por actor (de qa-checklist.md)

- **Willy:** ⬜ aprobado / ⬜ rechazado — tools probadas: TODO
- **Yuniesky:** ⬜ aprobado / ⬜ rechazado — tools probadas: TODO
- **Anet:** ⬜ aprobado / ⬜ rechazado — tools probadas: TODO

## 9. BLUE intacto

- Curl final a `mcp.ovnisystem.com/mcp`: ⬜ HTTP 200 ✅ / ⬜ falla
- Output `odoo_test_connection` BLUE: TODO_WILLY pegar línea redactada.

## 10. Definition of Done — 13 criterios (sec 5.6)

1. ⬜ BLUE responde OK durante toda la transición.
2. ⬜ GREEN operativo con cert SSL válido.
3. ⬜ `odoo_who_am_i` retorna actor + UID Odoo + rol para los 3 actores.
4. ⬜ Los 3 actores autenticados con credenciales Odoo independientes (no UID 9 hardcodeado).
5. ⬜ Policy engine deny-by-default valida acceso por actor/rol/modelo/acción/campos.
6. ⬜ Tools de tareas funcionan con read-after-write verificable.
7. ⬜ Tools de calendario funcionan con validación de fechas.
8. ⬜ Tools de proyecto con escritura limitada a campos básicos.
9. ⬜ Allowlists `hr.employee` y `res.partner` respetadas (verificadas en QA).
10. ⬜ CRM read-only + notas/actividades sin cambiar etapa/monto.
11. ⬜ Auditoría JSONL registra success y denied con redacción.
12. ⬜ Rate limits aplicados sin bloquear uso legítimo.
13. ⬜ Rollback documentado y ensayado; Result Packet firmado por Willy.

## 11. Riesgos residuales

- `xmlrpc.client` síncrono envuelto en `asyncio.to_thread`. Si concurrencia crece > 50 RPS, considerar reemplazo por `httpx` con JSON-RPC.
- Audit JSONL en disco sin rotación automática; programar `logrotate` post-deploy.
- Rate limits in-memory: si se escala a múltiples réplicas, mover a Redis.

## 12. Pendientes (post-cierre como sub-tickets)

- [P1] Migrar conector productivo de Willy de BLUE a GREEN tras 1 semana de estabilidad.
- [P2] Persistencia DB del audit log.
- [P2] Tools de escritura CRM avanzada (etapa, monto) con guardrails.
- [P2] Tools de escritura `res.partner` con allowlist de campos editables.
- [P3] OAuth completo para conectores que lo soporten.
- [P3] Panel administrativo web para gestionar actores y tokens.
- [P3] Logrotate para `audit.jsonl`.

## 13. Rollback

- Comando ensayado: `bash scripts/rollback_blue.sh` — TODO_WILLY: ⬜ ensayado / ⬜ no requerido.
- Imagen anterior disponible: `odoo-mcp:pre-multiuser-<timestamp>` en VPS.
- Tar de snapshot: `/opt/odoo-mcp-v2/backups/<timestamp>/blue.tar`.

## 14. Aprobación humana

- **Willy:** ⬜ pendiente / ⬜ aprobado — Firma: ____
- **Daniel:** ⬜ pendiente / ⬜ aprobado — Firma: ____

---

**Fin del Result Packet.**
