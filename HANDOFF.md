# HANDOFF — MCP Odoo v2 (Blue/Green)

> Documento operativo para retomar el ticket. **Última actualización:** 13 may 2026 ~21:40 hrs.

## Estado actual (cierre extendido 13 may 2026 ~22:20 UTC — Yuniesky escribiendo en Odoo desde ChatGPT)

### GREEN operativo en producción con paridad total Yuniesky/Willy
- `https://mcp-v2.ovnisystem.com/mcp` — Up (healthy), imagen `odoo-mcp:multiuser-v0.3.1`.
- BLUE `https://mcp.ovnisystem.com/mcp` — intocable.
- 16 commits en `feature/v2-multiusuario`. Últimos 5 (hoy): `0552f91` (normalizer Odoo), `954ae9a` (adapter search/fetch), `092dd4c` (formato OpenAI estricto), `80f1842` (8 write tools + Yuniesky owner-equivalent), `ebf33de` (JSON action protocol).
- Tests local: **110/110 verde**.

### Hito final del día: Yuniesky en ChatGPT crea tareas en Odoo

Verificado en producción 22:16:27 UTC. Yuniesky en ChatGPT envió un query `search({"action":"create_task",...})` y el MCP creó `task:128` en proyecto "Gerente de Operaciones" (project_id=3). Audit log confirma. Visible en Odoo web.

Protocolo definitivo para ChatGPT chat-mode:
- **Read**: `search("mis tareas")` / `fetch("task:42")`.
- **Write**: `search("{...JSON con action...}")`. Acciones: create_task, create_todo, update_task, move_task, close_task, cancel_task, create_project, create_event.

Si el modelo escribe "crea tarea" sin JSON, recibe un help_response con template y reintenta con el formato correcto.

### Hito del día (13 may): ChatGPT chat-mode funciona end-to-end

Antes de hoy, ChatGPT en modo chat estándar **no descubría** las 30 tools custom. Solo invocaba 1-2 esporádicamente y la mayoría de queries devolvían alucinaciones tipo "no tengo acceso a tu Odoo".

Diagnóstico real (con audit logs + XML-RPC directo): ChatGPT chat-mode tiene un patrón fijo de discovery — solo busca tools llamadas `search` y `fetch` (es el contrato de OpenAI para connectors MCP en chat mode, orientado a Deep Research).

Solución: **adapter** (`app/tools/openai_compat.py`, 260 LOC) que expone esos 2 nombres con la firma esperada por OpenAI y enruta internamente al toolset existente. Las 30 tools nativas siguen disponibles para Claude.ai sin cambios.

Adicionalmente, **el formato del response también es estricto**: ChatGPT ignora silenciosamente respuestas con keys extras o `url: null`. Por eso `search()` devuelve sólo `{"results": [{id, title, text, url}]}` con `url: ""` (string vacío). Cualquier key adicional (ej. `intent`) hace que ChatGPT trate la respuesta como vacía.

### QA ejecutado hasta hoy
| Actor | Conector | Capacidad | Resultado |
|---|---|---|---|
| Willy | Claude.ai | las 30 tools odoo_* directas | ✅ |
| Yuniesky | ChatGPT chat-mode | search("mis tareas") | ✅ 5 tareas reales |
| Yuniesky | ChatGPT chat-mode | search("proyectos") | ✅ 6 proyectos reales |
| Yuniesky | ChatGPT chat-mode | search("empleados") | ✅ 17 empleados (nombres, cargos, dept, email) |
| Yuniesky | ChatGPT chat-mode | fetch("task:N") | ✅ detalle completo |
| Yuniesky | ChatGPT (BLUE) | tools BLUE originales | ✅ |
| Anet | — | pendiente | ⚠️ |

### Cómo activar el conector en ChatGPT chat-mode (operativo, no obvio)

ChatGPT en modo chat estándar requiere **activar explícitamente** el conector POR mensaje:
1. Chat **nuevo** (no continuar uno donde el modelo ya decidió "no tengo tools").
2. Modelo: **GPT-5** o **Thinking** (NO "Instant" — ese ignora connectors).
3. En el composer click en `+` → seleccionar **"Odoo APL 2.0 V2"** → el chip queda **dentro del input** (no como sugerencia abajo).
4. Recién entonces escribir el prompt y enviar.

Si el chip aparece abajo con `+` al lado, **no está activo** — el modelo responderá que "no veo el conector". Esto es comportamiento de la UI de ChatGPT, no del MCP.

### Campos inválidos en esta instancia de Odoo (descubiertos en QA)
| Campo | Modelo | Razón | Fix commit |
|---|---|---|---|
| `kanban_state` | `project.task` | Módulo kanban no habilitado | `bfec76d` |
| `stage_id` | `project.project` | Feature "Etapas" no habilitada | `c30f111` |

### Conectores validados
- **Claude.ai:** token en path `/mcp/<token>`. UI no tiene campo Bearer. Middleware ASGI reescribe path → `/mcp`. ✅ Funcionando.
- **ChatGPT:** `X-Api-Key` header. GET sin SSE → 200 discovery. Fix aplicado. Pendiente QA completo.

### Score ticket: 12/13 criterios técnicos ✅. Pendiente QA manual Yuniesky+Anet y Result Packet.

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
