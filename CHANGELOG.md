# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [0.3.1] — 2026-05-13 (Yuniesky owner-equivalent + ChatGPT escribiendo en Odoo)

### Hito tecnico

**ChatGPT chat-mode ahora puede ESCRIBIR en Odoo via el protocolo JSON action.**

Verificacion en produccion 22:16:27 UTC: Yuniesky en ChatGPT envio
`search({"action":"create_task","project_id":3,...})` y el servidor MCP creo
`task:128` en el proyecto "Gerente de Operaciones" con titulo APL 2.0
valido, deadline 2026-05-15 y descripcion con 8 campos. Audit log confirmo
`result_count:1` con `tool:"search"`. Visible en Odoo web.

### Added

#### Fase 1: Yuniesky con owner-equivalent privileges (commit `80f1842`)
- `config/actors.yaml.example`: yuniesky.policy = owner_policy (antes
  operations_policy). Razon: Yuniesky no tiene Claude.ai, por tanto su
  UX en ChatGPT debe igualar a la de Willy en Claude.ai. role queda como
  "operations" solo para audit log; los permisos efectivos son owner.
- En produccion: `/opt/odoo-mcp-v2/secrets/actors.yaml` editado via sed.

#### Fase 2: 8 write tools en openai_compat.py (commit `80f1842`)
- `create_task(project_id, title, description, deadline, area, task_type, priority="P2")` -> odoo_create_project_task_apl
- `create_todo(title, description, deadline, area, task_type, priority="P2")` -> odoo_create_my_todo_apl
- `update_task(id, changes)` -> odoo_update_task_apl (acepta "task:42" o "42")
- `move_task(id, stage_id)` -> odoo_move_task
- `close_task(id, evidence, done_stage_id)` -> odoo_mark_task_done
- `cancel_task(id, reason, cancelled_stage_id)` -> odoo_cancel_task
- `create_project(name, description, user_id)` -> odoo_create_project
- `create_event(name, start, stop, description, location, partner_ids, allday)` -> odoo_create_calendar_event

Cada wrapper: valida APL 2.0 (6 campos obligatorios) + read-after-write +
devuelve formato OpenAI compat con id compuesto. Helper `_parse_id()` acepta
"task:42", "42" int o "42" str.

#### Fase 3: search() con JSON action protocol (commit `ebf33de`)

ChatGPT chat-mode no descubre las 8 write tools individualmente (verificado
con audit log: cero invocaciones a create_task antes de Fase 3). Solucion:
sobrecargar search() para detectar JSON embebido con clave "action" y
enrutar a la write tool correspondiente.

Tres paths en search():
1. **JSON action** (write): query contiene `{"action":"...","..."}` -> ejecuta.
2. **Verbos sin JSON** (educacion): query tiene "crea/actualiza/cierra/..."
   pero no JSON -> devuelve help_response con template del formato JSON
   para que el modelo aprenda y reintente.
3. **Read** (default): comportamiento original (clasificacion por intent).

Acciones soportadas: create_task, create_todo, update_task, move_task,
close_task, cancel_task, create_project, create_event.

Manejo de errores estructurado: KeyError (falta campo) -> error:missing_field,
ValueError -> error:invalid_value, PermissionError -> error:permission,
Exception generica -> error:execution. Cada error vuelve como item dentro
de `results` (sin keys extras a nivel raiz, compatible con OpenAI strict spec).

Instructions del FastMCP actualizadas con ejemplo embebido del formato JSON
y lista de acciones validas — el modelo de ChatGPT aprende el protocolo
desde la connect.

### Tests

- 110/110 verde (87 + 13 fase 2 + 10 fase 3).
- Cobertura: parse_id (4), write tools individuales (8), JSON action exec
  (4), help response (2), invalid action/missing field (2), backward compat
  read path (1).

### QA produccion verificado 13-may-2026 22:16 UTC

| Capacidad | Yuniesky ChatGPT | Evidencia |
|---|---|---|
| search lectura entidades | ✅ | audit 22:08, result_count 5-6 |
| fetch drill-down | ✅ | audit 22:08:47, 3 fetch consecutivos |
| **create_task via JSON action** | ✅ | **task:128 creado, audit 22:16:27** |

### Estado de deploy

- VPS GREEN corriendo `odoo-mcp:multiuser-v0.3.1` (commit `ebf33de`).
- `/opt/odoo-mcp-v2/secrets/actors.yaml` actualizado (yuniesky -> owner_policy).
- `/opt/odoo-mcp-v2/secrets/policies.yaml` actualizado con los 8 write tools.
- BLUE intocable, Willy lo conserva como fallback.

### Limitaciones operativas (no son bugs)

- **El modelo de ChatGPT debe enviar JSON valido en el query.** Si Yuniesky
  pide "crea tarea X" sin JSON, ChatGPT recibe el template help y debe
  reintentar con el formato correcto. En practica funciona bien con prompts
  estructurados como los que dimos en el QA.
- **APL 2.0 estricto:** title debe matchear regex `[APL 2.0][P0-3][Area][Tipo]` y description debe tener los 8 campos. Si falta algo, el servidor
  devuelve ValidationError estructurada y ChatGPT puede corregir.

## [0.2.2] — 2026-05-13 (adapter ChatGPT chat-mode + normalizer + audit mejorado)

### Added

#### Adapter `search` + `fetch` para ChatGPT chat-mode (commit `954ae9a`)
- **Diagnostico:** ChatGPT en modo chat estandar solo descubre tools cuyo nombre matchea el patron `search(query)` + `fetch(id)` que OpenAI documenta para connectors MCP. Tools custom (`odoo_my_tasks`, etc.) son **invisibles** para el modelo. Verificado con Yuniesky: el explorador de tools del conector solo devolvio `{"finite": true}` sin nombres invocables.
- `app/tools/openai_compat.py` (260 LOC): adapter con clasificacion por intent (regex sobre query) y enrutado a las tools nativas. Sin nueva capacidad — solo nueva ruta de entrada.
- `search(query)` enruta a `odoo_my_tasks`/`odoo_my_tasks_overdue`/`odoo_list_projects`/`odoo_list_employees`/`odoo_list_partners`/`odoo_list_crm_leads`/`odoo_list_calendar_events` segun keywords.
- `fetch(id)` recibe id compuesto `<kind>:<num>` (task/project/employee/partner/lead) y enruta a la tool `get_*`.
- Las 30 tools nativas siguen registradas — Claude.ai sigue viendo todo sin filtro.
- 18 tests nuevos (`tests/test_openai_compat.py`) cubriendo clasificacion, routing, formato, fetch por kind, errores estructurados.
- Imagen: `odoo-mcp:multiuser-v0.2.1` deployada en VPS.

#### Normalizer de respuestas Odoo (commit `0552f91`)
- `app/odoo_client.py` `_normalize_record()`: limpia respuestas crudas antes de devolverlas a las tools.
- Odoo `False` (sentinel de null) → Python `None`.
- many2one `[id, "Display Name"]` → `{"id": id, "name": "Display Name"}`.
- HTML en `description`/`note`/`body`/`comment`/`summary` → texto plano, max 800 chars.
- Aplicado transparente en `search_read()` y `read()`. Sin cambios en las tools.
- Beneficio: ChatGPT y Claude.ai parsean respuestas sin ambiguedad. Sin esto, ChatGPT recibia 11 tareas pero respondia "no devolvio resultados utilizables" porque su parser se confundia con HTML + tuplas + `false`.

### Fixed

#### Formato OpenAI search spec estricto (commit `092dd4c`)
- **Diagnostico:** despues de aplicar el adapter, Yuniesky en ChatGPT recibia respuestas (audit log confirmaba 3 invocaciones `search` exitosas) pero el modelo respondia "no veo herramientas". Test directo XML-RPC confirmo que Yuniesky con UID 11 ve 17 empleados, 1510 contactos, 81 eventos, 6 proyectos. El ACL Odoo no era el problema.
- Causa: ChatGPT chat-mode tiene un parser estricto que ignora respuestas con keys extras o tipos no esperados.
- `app/tools/openai_compat.py`:
  - `url: None` → `url: ""` en todos los formatters (spec: string vacio, no null).
  - Quitar key `intent` del response de search (era informativo nuestro, confundia al parser).
  - `permission_denied` ahora viene como item dentro de `results` con id `error:permission` en lugar de keys extras a nivel raiz.
- Resultado: Yuniesky en ChatGPT lista los 17 empleados reales con nombres, cargos, departamentos y emails correctos. Sin alucinacion.
- Imagen: `odoo-mcp:multiuser-v0.2.2` deployada en VPS.

#### Audit log: count interno para search/fetch (commit `092dd4c`)
- `_audited()` ahora inspecciona dicts con key `results` y cuenta items del array.
- Antes: `result_count: 1` siempre para dicts (no se podia diagnosticar si la respuesta era vacia o llena).
- Ahora: `result_count: 17` (numero real de items en search/fetch).
- Para `list`s y otros dicts el comportamiento es el anterior.

### QA ejecutado (13 may 2026)

| Actor | Conector | Capacidad | Resultado |
|---|---|---|---|
| Willy | Claude.ai | las 30 tools odoo_* | ✅ |
| Yuniesky | ChatGPT chat-mode | search("mis tareas") | ✅ 5 tareas reales |
| Yuniesky | ChatGPT chat-mode | search("proyectos") | ✅ 6 proyectos reales |
| Yuniesky | ChatGPT chat-mode | search("empleados") | ✅ 17 empleados reales con cargos/departamentos/emails |
| Yuniesky | ChatGPT chat-mode | fetch("task:N") | ✅ detalle completo |
| Anet | — | pendiente | ⚠️ |

### Limitaciones documentadas (no son bugs)

- **ChatGPT chat-mode no auto-invoca tools custom:** solo `search`/`fetch`. Por eso este adapter existe.
- **ChatGPT a veces racionaliza array vacio como "no tengo herramienta":** comportamiento del modelo, no del servidor. Mitigado con format estricto.
- **operations_policy no incluye `odoo_get_employee`/`odoo_get_partner`/`odoo_search_employee`/`odoo_search_partner`:** Yuniesky no puede hacer drill-down a empleados/partners individuales por diseño conservador. Activable con 4 lineas en `config/policies.yaml.example` + redeploy si se requiere.

### Estado de deploy al cierre del 13 may 2026

- VPS GREEN corriendo `odoo-mcp:multiuser-v0.2.2` (commit `092dd4c`).
- BLUE intocable en `mcp.ovnisystem.com` (Willy lo usa como fallback en ChatGPT).
- Tests local: 87/87 verde.
- 3 commits empujados a `feature/v2-multiusuario` hoy: `0552f91`, `954ae9a`, `092dd4c`.

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

### Pendiente para cierre formal

- Redeploy VPS con último commit (`65deb9d`) para docstrings y tool_search fix.
- QA Yuniesky y Anet (pendiente conectores individuales).
- Audit success verificado en VPS live.
- `docs/APL_STAGES.md` con etapas reales.
- Result Packet firmado por Willy + Daniel.
- PR `feature/v2-multiusuario` → `main`.

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
