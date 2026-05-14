# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [0.3.5] — 2026-05-14 (Fix parser NL: evidencia/motivo con puntos internos)

### Bug identificado durante auditoría final 13-may-2026 ~01:39 UTC

Willy en ChatGPT ejecutó auditoría final post-v0.3.4. Paso 7 (cierre con
evidencia) falló con error del servidor:
`ValueError: evidencia demasiado corta (18 chars). Minimo 20 chars.`

La evidencia enviada tenía ~130 chars (`"Auditoria final v0.3.4 ejecutada
con exito. Conector ChatGPT Willy operativo end-to-end. Partners fix
verificado. Cierre 13-may-2026."`), pero el parser NL la cortó a 18 chars
(`"Auditoria final v0"`) — exactamente hasta el primer punto literal en
`v0.3.4`.

### Causa raíz

El regex `_EVIDENCE_RE` (y `_REASON_RE`) en `app/tools/openai_nl_parser.py`
usaba lookahead `(?=...|\.|...)` que terminaba la captura en cualquier
punto literal. Esto rompía con evidencias que contienen:
- Números de versión (`v0.3.4`, `v1.2`)
- URLs (`mcp-v2.ovnisystem.com`)
- Abreviaciones (`Dr.`, `Sr.`, `etc.`)
- Fechas con punto separador

### Changed

- `app/tools/openai_nl_parser.py`:
  - `_EVIDENCE_RE`: lookahead reducido a `(?=\s*(?:done_stage|stage_id|$|\n))`.
    Ya no termina en punto literal. Captura completa hasta keyword o fin.
  - `_REASON_RE`: mismo fix aplicado por simetría.
  - Comentario explicativo del bug fix.

### Added

- `tests/test_openai_nl_parser.py`:
  - `test_close_task_evidence_with_dots_preserved`: regression test con
    la frase exacta que falló en producción (incluye `v0.3.4`).
  - `test_cancel_task_reason_with_dots_preserved`: simétrico para motivo.

### Verificación post-fix

- Tests local: **137/137 verde** (135 previos + 2 regression nuevos).
- En producción post-deploy: `cierra tarea N con evidencia: texto con
  v0.3.4 puntos.` debe ejecutar OK.

---

## [0.3.4] — 2026-05-13 (Fix bug servidor: campo 'mobile' inválido en res.partner)

### Bug identificado durante QA tri-canal 13-may-2026

Claude.ai reportó con precisión técnica:
`ValueError: Invalid field 'mobile' on 'res.partner'` (reproducible 2/2)

Causa: `PARTNER_SAFE_FIELDS` en `app/tools/partners.py` incluía el campo
`mobile`, pero en esta instancia Odoo 17/18/19 Community `res.partner` no
expone ese campo. Probablemente fue removido en versiones recientes o
nunca estuvo en Community.

Síntoma colateral: ChatGPT chat-mode venía retornando `partners=0` desde
mediodía (Yuniesky 12 may, Yuniesky 13 may QA tri-canal 10/10). El adapter
`openai_compat.py` capturaba la excepción Odoo Fault y devolvía
`results: []` vacío, ocultando el bug. Claude.ai en cambio propagó el
error textualmente, permitiendo el diagnóstico.

### Changed

- `app/tools/partners.py`:
  - `PARTNER_SAFE_FIELDS`: removido `mobile` (sigue habiendo `phone`).
  - `odoo_search_partner`: removida cláusula `("mobile", "ilike", q)` del
    domain. Ahora busca por name/email/phone.
  - Docstring y comentario explicativo agregados para evitar regresiones.
- `config/policies.yaml.example`: removida línea `- mobile` de
  field_allowlists.res.partner. Comentario inline explicando el motivo.
- `tests/conftest.py`: removido `"mobile"` del allowlist test de partners.

### Verificación post-fix

- Tests local: **135/135 verde**.
- Post-deploy: en ChatGPT `search("contactos")` debe retornar >0; en
  Claude `odoo_list_partners()` debe retornar lista sin error.

### Pendiente colateral (no incluido en este fix)

El adapter `openai_compat.py` debería propagar errores del servidor en
vez de retornar `results: []` vacío cuando hay Fault de Odoo. Ahora mismo
oculta bugs reales en ChatGPT chat-mode. Refactor del exception handling
queda para una próxima iteración.

---

## [0.3.3] — 2026-05-13 (Fase 4: parser de lenguaje natural server-side)

### Hito tecnico

**search() ahora entiende lenguaje natural ES para escritura.** ChatGPT
chat-mode ya no necesita construir JSON action — basta con que invoque
`search("crea tarea X en proyecto Y")` y el servidor extrae intent + campos
via regex, auto-genera el payload APL 2.0 compliant y ejecuta directo.

### Motivacion (verificado en audit 13-may-2026 22:18-22:44 UTC)

Tras desplegar v0.3.2 con instructions directivas, Yuniesky en ChatGPT envio
22+ search/fetch pero **0 entries con `action: create_*`**. Patron repetido:
`latency_ms: 0, result_count: 1` (firma de `_help_write_response()`). ChatGPT
recibia la guia con el template JSON y NO reintentaba — devolvia markdown al
usuario "no puedo escribir desde esta sesion". Confirmado: el modelo se rinde
aunque el servidor exponga la capacidad.

Conclusion: la inteligencia debe vivir en el servidor, no en el modelo.

### Added

- `app/tools/openai_nl_parser.py` (~270 LOC) — modulo nuevo con regex+heuristicas
  que parsean queries ES naturales a payloads `{"action": ...}` listos para
  `_execute_action()`. Soporta:
  - **whoami**: "quien soy", "mi identidad", "mis datos", "mi rol"
  - **close_task**: "cierra/finaliza tarea N con evidencia: ..." (extrae id +
    evidencia desde el lenguaje natural, default `done_stage_id=1`)
  - **cancel_task**: "cancela tarea N motivo: ..."
  - **move_task**: "mueve tarea N a etapa M"
  - **update_task**: "actualiza tarea N prioridad alta/media/baja/P0-P3"
  - **create_project**: "crea proyecto 'Nombre'"
  - **create_todo**: "crea todo/pendiente 'titulo' [deadline: YYYY-MM-DD]"
  - **create_task**: "crea tarea 'titulo' en proyecto N" o "...en proyecto
    Nombre" (resuelve name->id via `odoo.search_read('project.project',...)`)
- Builders APL 2.0 auto-fill: `_build_apl_title()` envuelve titulos naturales
  con `[APL 2.0][P2][Area][Tipo]`; `_build_apl_description()` genera los 8
  campos obligatorios usando el titulo como semilla. El usuario edita despues.
- `tests/test_openai_nl_parser.py` — 20 tests nuevos cubriendo cada accion +
  builders + queries que NO deben matchear (lectura pura, vacios).

### Changed

- `app/tools/openai_compat.py::search()` — el Path 2 (verbos de escritura sin
  JSON) ahora primero llama `nl_parser.try_parse()`. Si extrae payload valido,
  ejecuta con `_execute_action()` directo. Solo si el query es ambiguo o le
  faltan datos minimos, cae al `_help_write_response()` anterior.

### Result

Yuniesky en ChatGPT puede ahora:
- `search("crea tarea 'Smoke test' en proyecto Gerente de Operaciones")` ->
  task creado, project_id resuelto por name, titulo y descripcion APL 2.0
  auto-rellenados, deadline = mañana.
- `search("cierra tarea 128 con evidencia: termine el QA")` -> tarea cerrada
  con la evidencia capturada del lenguaje natural.
- `search("quien soy")` -> identidad sin necesidad de JSON.

Tests: **135/135 verde** (110 previos + 20 nuevos del parser + 5 que faltaban).

### Files

- `app/tools/openai_nl_parser.py` (nuevo)
- `app/tools/openai_compat.py` (modificado, +5 LOC)
- `tests/test_openai_nl_parser.py` (nuevo)
- `CHANGELOG.md` (este entry)

---

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
