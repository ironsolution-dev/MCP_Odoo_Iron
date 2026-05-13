# QA Checklist — MCP Odoo v2 GREEN

> Lo ejecuta Willy + cada actor al cierre del deploy.

## 0. Pre-condiciones

- [ ] BLUE `mcp.ovnisystem.com` responde 200 (intacto).
- [ ] GREEN `mcp-v2.ovnisystem.com` responde 200 con cert SSL válido.
- [ ] `actors.yaml` real poblado con los 3 hashes en VPS.
- [ ] `.env.v2` con credenciales Odoo de los 3 actores.
- [ ] `audit.jsonl` existe y es writable por el contenedor.

## 1. Tests automatizados

```bash
cd <repo_root>
source .venv/bin/activate
pytest tests/ -v
# Esperado: 66/66 pasando (sin marker requires_blue corre 65; con marker 66)
```

- [ ] 100% tests pasando (excluido `requires_blue` cuando no hay acceso).
- [ ] `grep -E "(mcp_[A-Za-z0-9_-]{30,}|api_key|MCP_TOKEN)" tests/` retorna 0 matches.

## 2. Smoke test contra GREEN

```bash
export MCP_TOKEN_WILLY=mcp_xxx
export MCP_TOKEN_YUNIESKY=mcp_yyy
export MCP_TOKEN_ANET=mcp_zzz
python scripts/smoke_test_mcp.py
```

- [ ] `[ok] willy   actor=willy uid=<int> role=owner`
- [ ] `[ok] yuniesky actor=yuniesky uid=<int> role=operations`
- [ ] `[ok] anet     actor=anet uid=<int> role=medical_direction`
- [ ] `ALL OK` al final
- [ ] El output **no** contiene tokens completos (solo redactados)

## 3. QA manual por actor

### Willy (owner) — desde Claude.ai y desde ChatGPT

- [ ] `odoo_who_am_i` → retorna `actor=willy, role=owner`, UID real, sin API key visible.
- [ ] `odoo_my_tasks` → lista To Do personal de Willy.
- [ ] `odoo_create_my_todo_apl` con título y descripción APL 2.0 → tarea creada en Odoo + read-after-write retorna el record.
- [ ] `odoo_create_my_todo_apl` con descripción incompleta → falla con `ValidationError` informativo.
- [ ] `odoo_mark_task_done` con evidencia "ok" (< 20 chars) → falla.
- [ ] `odoo_mark_task_done` con evidencia descriptiva → cierra tarea + posta evidencia en chatter.
- [ ] `odoo_list_calendar_events` rango próxima semana → lista eventos.
- [ ] `odoo_create_calendar_event` con start>stop → falla con ValidationError.
- [ ] `odoo_create_calendar_event` válido → evento creado + read-after-write.
- [ ] `odoo_list_projects` → proyectos visibles por Willy.
- [ ] `odoo_create_project` "Proyecto QA v2" → creado + read-after-write.
- [ ] `odoo_list_employees` → solo allowlist (verificar que NO incluye wage, bank_account_id, contract_*, identification).
- [ ] `odoo_list_partners` → solo allowlist (verificar que NO incluye vat, street, credit, comment).
- [ ] `odoo_list_crm_leads` → leads visibles.
- [ ] `odoo_add_crm_note` en un lead → nota posteada SIN modificar etapa/monto.

### Yuniesky (operations) — desde su Claude.ai o ChatGPT

- [ ] `odoo_who_am_i` → `actor=yuniesky, role=operations`, UID propio (diferente al de Willy).
- [ ] `odoo_my_tasks` → tareas de Yuniesky, no las de Willy.
- [ ] `odoo_list_projects` → proyectos visibles para Yuniesky.
- [ ] `odoo_create_project_task_apl` en proyecto visible → tarea creada.
- [ ] `odoo_create_project_task_apl` en project_id no visible → falla con `project_not_accessible`.
- [ ] `odoo_create_project` (Yuniesky NO debe poder) → falla con `tool_not_allowed`.
- [ ] `odoo_list_crm_leads` → falla (no permitido para operations).
- [ ] `odoo_create_calendar_event` válido → creado.
- [ ] `odoo_list_employees` → allowlist respetada.

### Anet (medical_direction) — desde su Claude.ai o ChatGPT

- [ ] `odoo_who_am_i` → `actor=anet, role=medical_direction`, UID propio.
- [ ] `odoo_my_tasks` → tareas de Anet.
- [ ] `odoo_list_calendar_events` → eventos visibles.
- [ ] `odoo_create_calendar_event` → creado.
- [ ] `odoo_list_crm_leads` → leads visibles para medical_direction.
- [ ] `odoo_add_crm_note` → nota posteada sin cambio de etapa.
- [ ] `odoo_list_projects` → proyectos visibles.
- [ ] `odoo_list_partners` → allowlist respetada.
- [ ] `odoo_get_employee` → datos allowlist.

## 4. Validación de audit

```bash
tail -n 30 /opt/odoo-mcp-v2/logs/audit.jsonl
```

- [ ] Cada llamada de tool aparece en audit con `request_id`, `actor`, `role`, `tool`, `model`, `action`, `allowed`, `latency_ms`.
- [ ] Hay al menos 1 entry `allowed=false` por cada actor que intentó algo denegado.
- [ ] NO aparecen valores literales de tokens / api keys / Authorization:

```bash
grep -E "(mcp_[A-Za-z0-9_-]{30,}|Bearer mcp_|api_key=|password=)" /opt/odoo-mcp-v2/logs/audit.jsonl \
  && echo "LEAK" || echo "CLEAN"
# Esperado: CLEAN
```

## 5. BLUE intacto

```bash
curl -s -X POST https://mcp.ovnisystem.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | head -c 200
```

- [ ] Responde 200 con lista de tools.
- [ ] El conector productivo de Willy en Claude.ai sigue funcionando contra BLUE.

## 6. Rollback ensayado

- [ ] `docker stop odoo-mcp-v2 && docker rm odoo-mcp-v2` ejecuta limpio.
- [ ] BLUE sigue intacto tras el stop.
- [ ] Re-deploy con `bash scripts/deploy_green.sh` levanta GREEN de nuevo.

## 7. Resultado

- [ ] **APROBADO** — Result Packet firmado, ticket cerrado.
- [ ] **RECHAZADO** — listar fallos abajo, abrir sub-tickets.

### Fallos detectados

TODO_QA: pegar errores con request_id, actor, tool, denied_reason, latency.

### Aprobación

- Willy: ___ pendiente / ___ aprobado — Firma: ____
- Daniel: ___ pendiente / ___ aprobado — Firma: ____
