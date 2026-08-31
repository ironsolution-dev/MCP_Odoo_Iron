# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

> Nota: entre `0.2.0` (12-may-2026) y `0.4.5` (27-ago-2026) el repo tageó `multiuser-v0.3.5` a
> `multiuser-v0.4.4` sin entrada aquí — historial real en `git log`/`git tag` y en `HANDOFF.md`
> (Fase A "daily driver", 18-ago-2026). Este changelog retoma desde `0.4.5`.

## [multiuser-v0.4.6] — 2026-08-31 — ticket Odoo 807 (conector MCP agnóstico de LLM, retrocompat)

Rama `julio/807-mcp-agnostico` (base `main` @ `d5a798b`), aprobada por
`julio-qa` y autorizada por `julio-release` el 31-ago-2026 (merge `c425c16`).
Desplegada a VPS82 el 31-ago-2026 con gate de Willy.

### Fixed

- **GET /mcp/\<token\> devolvía 404**: la reescritura de path `/mcp/<token>` →
  `/mcp` solo corría en la rama POST de `BearerMiddleware`. Ahora GET y POST
  comparten un único pipeline de autenticación (ADR-018).
- **GET /mcp sin token pasaba sin autenticar**: cualquier cliente podía leer
  discovery/SSE sin Bearer/`X-Api-Key`. Cerrado por el mismo pipeline
  unificado (ADR-018).
- **Discovery GET perdido en el rescate de drift del 18-ago**: restaurado
  por cherry-pick de `d0a2bfb` (mayo, soporte ChatGPT), ahora detrás de
  autenticación — divergencia intencional respecto al original, que
  respondía sin auth (ADR-020).
- **Audit sin `client_type`/`user_agent` en eventos de éxito**: solo los
  fallos de auth los grababan. Ahora todo evento (éxito y fallo) los lleva,
  vía `ContextVar` compartido entre `BearerMiddleware` y `_audited()`
  (ADR-022).

### Added

- `WWW-Authenticate: Bearer realm="odoo-mcp-v2", error="invalid_token"` en
  todo `401` (GET y POST) — sin implementar OAuth completo ni
  `/.well-known/*`, fuera de alcance (ADR-019).
- CORS resuelto en la app: `OPTIONS /mcp/*` responde `2xx` sin exigir token;
  las respuestas reales (GET/POST) llevan `Access-Control-Allow-Origin`
  (ADR-021).
- `scripts/rollback_check_local.py` — rollback de código probado en local
  (worktree temporal, no toca VPS82) antes de redesplegar GREEN.
- 12 tests nuevos (`test_mcp_auth_unification.py`,
  `test_mcp_audit_client_type.py`, `test_mcp_regression_and_real_client.py`
  con SDK oficial `mcp==1.27.1`) + regresión completa: 179 passed, 1 skipped.
- ADR-018 a ADR-022.

### Deuda declarada (no resuelta en este ticket)

- **CORS sin allowlist de orígenes (ticket Odoo APL 867, vence antes de
  servir cualquier cliente MCP de navegador):** `Access-Control-Allow-Origin`
  refleja cualquier `Origin` del request sin compararlo contra una lista
  permitida — verificado en `app/odoo_mcp_remote.py` y en
  `tests/test_mcp_auth_unification.py`. Sin `Access-Control-Allow-Credentials`
  no hay vector de robo de cookie de sesión, pero es superficie sin
  allowlist. Riesgo aceptado temporalmente porque hoy ningún actor real
  llama desde navegador (ver ADR-021, sección "Riesgo aceptado").
- **Pipeline de auth "fantasma" (ticket Odoo 864):**
  `AuthMiddleware.authenticate()`/`authorize_tool()` sigue sin usarse desde
  el path vivo (cubierto solo por `test_auth_middleware.py`) — mismo estado
  que antes de este ticket, consolidación fuera de alcance (ver ADR-018).

---

## [0.4.5] — 2026-08-27 (ticket Odoo 737 — MCP alineado con la Guía APL 2.0 V2 v1.1)

Cierre de 3 rondas de QA (`julio-qa`) sobre `feature/ticket-737-apl-v11` → `main`, commit `9ff29cf`.
Desplegado en producción (`mcp-v2.ovnisystem.com`, VPS82) tras aceptación en vivo.

### Added

- `app/apl_title.py` — `normalize_apl_title()`: título legado `[APL 2.0][Px][Área][Tipo] …` se
  normaliza a verbo + entregable (formato de la guía humana); título nuevo valida estructura.
  Insensible a tildes/mayúsculas desde la ronda 3 (D1).
- `app/apl_labels.py` — fuente única de IDs de etiquetas (`config/apl_labels.yaml`, horneado en
  la imagen): resuelve prioridad→estrella y departamento/tipo→`tag_id`; **nunca crea** etiquetas
  en Odoo (ADR-017).
- `app/apl_description.py` — `render_apl_description()`: escritor único de la descripción de
  ocho campos con encabezados emoji 👤🎯📦📅✅📎⚠️▶️; normaliza descripción legado (sin
  encabezados/emoji) al formato de la guía (D2, ronda 3).
- `app/apl_validation.py` — validadores APL 2.0 extraídos de `app/schemas.py` (que superaba 300
  líneas).
- `config/apl_labels.yaml` — mapa canónico de prioridad/departamento/tipo con sinónimos.
- ADR-016 (título dual legado/nuevo) y ADR-017 (etiquetas: fuente única versionada en la imagen).
- 167 tests (`pytest tests/ -v`, verde). Incluye tildes/mayúscula/emoji y normalización
  legado→guía (ronda 3).

### Fixed

- **Estrellas de prioridad:** `app/tools/tasks.py` asignaba la misma estrella a P0 y P1
  (`"0" if P3 else ("1" if P2 else "2")`). Corregido a P0→3, P1→2, P2→1, P3→0.
- Ninguna tool de escritura asignaba `tag_ids` al crear tarea/todo — ahora escribe las 3
  etiquetas canónicas (`[(6,0,tag_ids)]`).
- System prompt, help de escritura (`_help_write_response`) y docstrings de
  `openai_write_ops.py`/`openai_nl_parser.py` describían un formato que ya no exigía el
  validador (6 campos sin emoji, o campos inventados «Resultado/Pasos/…») — reescritos para
  coincidir con el contrato real.
- Drift de producción rescatado a git: el contenedor en VPS82 corría
  `odoo-mcp:multiuser-v0.4.3` (`MCP_GIT_COMMIT=c48b283…`) que no existía en ningún commit de
  `main`. Extraído del contenedor, comparado por sha256 y traído a git (tag `multiuser-v0.4.3`
  ahora apunta al commit `2fa2539`, distinto del hash real horneado en la imagen que corrió en
  prod — ver "Deuda conocida" abajo).

### Cómo validar

```text
odoo_create_project_task_apl(project_id=32, title="[APL 2.0][P1][Tecnología][Entregable] Validación con tildes", ...)
```
Proyecto 32 = sandbox. Aceptación en vivo real: tarea 808 (título con tildes, `tag_ids={2,9,12}`,
`priority=2`), cancelada tras validar; evidencia en el chatter del ticket Odoo 737 (mensajes
317703 y 317707).

### Rollback probado

`deploy_green.sh` con el tag anterior (`multiuser-v0.4.4`) → `docker stop/rm` del contenedor
`0.4.5` → `deploy_green.sh multiuser-v0.4.4` → `odoo_health` confirma `mcp_version`/`git_commit`
del tag anterior → redeploy de `multiuser-v0.4.5`. Evidencia en el chatter del ticket 737.

### Deuda conocida (ticket Odoo 809, vence 3-sep-2026; no resuelta en este cierre)

El tag de git `multiuser-v0.4.3` (commit `2fa2539`, mensaje "Imagen odoo-mcp:multiuser-v0.4.3
corriendo en VPS82, rescatada a git 27-ago-2026") **no coincide** con el `MCP_GIT_COMMIT` real
horneado en la imagen que corrió en producción (`c48b283…`, que nunca existió en git — era un
build a mano fuera de `deploy_green.sh`). El rescate reconstruyó el código correcto, pero el tag
histórico `multiuser-v0.4.3` en el repo no es bit-a-bit trazable al build que realmente corrió.
No bloquea nada hoy (v0.4.3 quedó superado por v0.4.4/v0.4.5), pero rompe la garantía de
trazabilidad build↔git de ADR-015 para esa versión puntual. Pendiente: ticket para
re-documentar/retaguear `multiuser-v0.4.3` como "reconstruido, no bit-exacto" o retirarlo del
listado de tags válidos — dueño y fecha a definir por `julio-triage`.

---

## [0.2.0] — 2026-05-12 (deploy en produccion + QA parcial Willy/Claude.ai)

### Fixed

#### Compatibilidad conectores (commits post-deploy)
- **P0 Claude.ai (path token):** `BearerMiddleware` convertido de `BaseHTTPMiddleware` a middleware ASGI puro. Permite reescribir `scope['path']` de `/mcp/<token>` → `/mcp` antes de FastMCP. Sin este fix, Claude.ai obtenía HTTP 404 con el token en el path. (commit `0246596`)
- **P0 ChatGPT (X-Api-Key):** `auth_middleware.extract_token()` acepta header `X-Api-Key` como segundo canal de autenticación (prioridad: Bearer > X-Api-Key > path). GET `/mcp` sin `Accept: text/event-stream` retorna 200 JSON discovery en vez de 406. (commit `d0a2bfb`)
- **P1 audit success:** `_audited()` no registraba success porque `_actor.get()` retornaba None dentro del task group de anyio creado por `call_next`. Fix: actor capturado explícitamente en scope de cada `@mcp.tool()` y pasado como parámetro. (commit `63c0c3e`)
- **mcp 1.27.0:** Dockerfile usaba `fastmcp` (terceros). VPS tenía `mcp==1.27.0` (SDK oficial). Entry point reescrito con `mcp.server.fastmcp.FastMCP` + `streamable_http_app()` + ContextVar. Healthcheck cambiado de `curl /health` a TCP socket Python. (commit `387d349`)
- **kanban_state eliminado de `TASK_SAFE_FIELDS`:** Campo no disponible en Odoo 19 Community sin módulo kanban. Causaba `ValueError: Invalid field` en `project.task`. (commit `bfec76d`)
- **stage_id eliminado de `PROJECT_SAFE_FIELDS`:** Feature "Etapas de proyecto" no habilitada en esta instancia. Causaba error 403 en `project.project`. El `stage_id` de `project.task` en `odoo_project_tasks` NO se modifica (campo válido). (commit `c30f111`)

### Added

#### Deploy VPS Infinity (12 may 2026)
- GREEN `odoo-mcp-v2` desplegado en `https://mcp-v2.ovnisystem.com/mcp`.
- SSL Let's Encrypt emitido y válido hasta ago 2026.
- Snapshot BLUE en `/opt/odoo-mcp-v2/backups/20260512_192156/`.
- Secrets en `/opt/odoo-mcp-v2/secrets/` (actors.yaml, policies.yaml, .env.v2).
- Audit log en `/opt/odoo-mcp-v2/logs/audit.jsonl`.

#### Docstrings en 30 tools
- Todas las funciones `@mcp.tool()` ahora tienen docstring en español.
- Corrige fallo de `tool_search` semántico de Claude.ai que no encontraba tools sin descripción. (commit `65deb9d`)

#### Connectors auth spike documentado
- `docs/baseline/connectors_auth_spike.md` completado con resultados reales.
- Claude.ai: token en path `/mcp/<token>` (no soporte Bearer en UI). Middleware ASGI reescribe path.
- ChatGPT: `X-Api-Key` header en modo API Key. GET sin SSE → 200 JSON discovery.
- ADR-007 y ADR-010 validados en producción.

### QA ejecutado (Willy / Claude.ai) — 12 may 2026

| Tool | Resultado |
|---|---|
| `odoo_who_am_i` | ✅ actor=willy, uid=9, role=owner, policy=owner_policy |
| `odoo_my_tasks` | ✅ 5 tareas personales reales |
| `odoo_list_projects` | ✅ 6 proyectos reales con tareas anidadas |

### Ejecutado al final de jornada (post-QA parcial)

- ✅ VPS redeployado con commit `f7639fe` — todos los fixes aplicados en producción.
- ✅ PR #1 creado en GitHub: `release/v0.2.0 → main` (pendiente aprobación post-QA completo).
- ✅ QA Willy/Claude.ai: `odoo_who_am_i`, `odoo_my_tasks`, `odoo_list_projects` verificados con datos reales de Odoo.

### Pendiente para cierre formal (mañana ~1h)

- ⏳ Verificar `audit.jsonl` tiene entries `allowed:true` post-redeploy.
- ⏳ QA Yuniesky y Anet (conectores individuales Claude.ai).
- ⏳ `docs/APL_STAGES.md` con etapas reales (via `odoo_validate_apl_stages`).
- ⏳ Result Packet firmado por Willy.
- ⏳ Merge PR #1 → main.

---

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
