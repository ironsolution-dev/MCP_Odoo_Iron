# Seguridad — MCP Odoo v2

## Identidades

Tres identidades disjuntas (ADR-003):

| Identidad | Quién la posee | Dónde vive | Regla |
|---|---|---|---|
| **MCP token** | Conector del actor (Claude.ai/ChatGPT) | Configuración del conector | Identifica al actor MCP. Se almacena como hash sha256 en `actors.yaml`. NO es credencial Odoo. |
| **Odoo API Key** | Servidor MCP (env var del contenedor) | `/opt/odoo-mcp-v2/secrets/.env.v2` | NUNCA al modelo, NUNCA al repo, NUNCA en logs |
| **Odoo username** | Servidor MCP | env var del contenedor | Login real del actor en Odoo |

## Política de secretos (RNF-01)

**Cero secretos** en Git, logs, README, prompts, output de tests.

- `MCP_TOKEN` ≠ `ODOO_API_KEY`.
- Tokens MCP se guardan como hash sha256 (`actors.yaml`).
- Headers `Authorization` y `Bearer` redactados en logs (`audit.redact_header`).
- Argumentos sensibles sustituidos por `args_hash` en audit (`audit._hash_args`).
- `OdooCredentials.__repr__` enmascara api_key.
- `generate_mcp_token.py` imprime el token plano UNA SOLA VEZ; no persiste.
- `validate_env.py` falla rápido si faltan envs; no imprime valores.

### Verificación

```bash
# Repo: no debe contener secretos.
git grep -E "(mcp_[A-Za-z0-9_-]{30,}|api_key\s*=|password\s*=)" -- . || echo "CLEAN"

# Audit log: no debe contener secretos.
grep -E "(Bearer|api_key|MCP_TOKEN)" /opt/odoo-mcp-v2/logs/audit.jsonl || echo "CLEAN"
```

## Modelo de permisos

### Capas (ADR-004)

```
allow = odoo_allows(actor, model, action, record)
      AND mcp_policy_allows(actor, role, tool, model, action, fields)
      AND input_validation_passes(tool, payload)
```

Si cualquier término es falso → **deny**.

### Capa 1: Odoo ACL

Autoridad de permisos. El MCP NO eleva, NO salta, NO suplanta. Si Odoo retorna `AccessError`, el MCP lo propaga con `denied_reason: odoo_acl_denied` y NO intenta bypass (sin `sudo`, sin context manipulation).

### Capa 2: MCP policy engine

`config/policies.yaml`. Deny-by-default. Tres policies (`owner_policy`, `operations_policy`, `medical_direction_policy`). Cada una declara:

- `allowed_tools`: lista finita de tools por rol.
- `model_rules`: `{read, create, write, unlink}` por modelo.
- `rate_limit`: `requests_per_minute`, `writes_per_minute`.

Una **denylist global** se aplica a TODOS los roles (sec 8.6 Task Packet):

- `res.users`, `res.company`, `ir.config_parameter`, `ir.module.module`
- `account.move`, `account.payment`
- `stock.quant`, `stock.picking`, `purchase.order`, `sale.order`
- `hr.contract` (ningún acceso)

### Capa 3: Validación de input

`app/schemas.py`. Reglas APL 2.0:

- Título APL 2.0 obligatorio (`[APL 2.0][P0/P1/P2/P3][Area][Tipo] Verbo + entregable + contexto`).
- Descripción APL 2.0 obligatoria (8 campos: Objetivo, Entregable, Responsable, Fecha límite, Criterio de cierre, Evidencia requerida, Riesgo si no se cierra, Siguiente acción).
- `mark_task_done` requiere `evidence` de ≥ 20 caracteres.
- `cancel_task` requiere `reason` no vacío.
- `calendar.event` requiere `start < stop` con formato ISO.

## Allowlists de campos

### `hr.employee` (sec 8.3)

Permitidos: `id, name, work_email, work_phone, mobile_phone, department_id, job_id, parent_id, user_id, active`.
Prohibidos: wage, contract_*, identification_*, private_*, bank_*, birthday, emergency_*.

### `res.partner` (sec 8.4, ADR-009)

Permitidos: `id, name, display_name, email, phone, mobile, is_company, parent_id, function, city, country_id, category_id, user_id, active, customer_rank, supplier_rank`.
Prohibidos: vat, street, street2, zip, bank_ids, credit, debit, total_invoiced, comment, ref, property_*.

`odoo_search_partner` NO admite filtros por `vat` / `ref` / `street`.

### `mail.message` / `ir.attachment` — Discuss (sec G4, ADR-013/014)

Permitidos `mail.message`: `id, body, author_id, date, message_type, attachment_ids`.
Permitidos `ir.attachment`: `id, name, mimetype, file_size, create_date, create_uid, res_model, res_id, url, type, description` (compartido por `attachments.py` y `discuss.py`). **NO incluye `datas`**: el binario nunca viaja al LLM, solo se usa internamente para copiar un adjunto hacia una tarea.

## Allowlist de canales de Discuss (sec G4, ADR-013)

Cada policy declara opcionalmente `discuss_channel_allowlist: [ids]` en `config/policies.yaml`. **Ausencia de la clave = deny para TODOS los canales**, sin excepcion implicita. Las tools de `app/tools/discuss.py` hacen doble chequeo: `policy.allows(modelo, accion)` + `policy.discuss_channel_allowed(policy, channel_id)`.

En Fase A solo `owner_policy` declara `discuss_channel_allowlist: [53]` (canal Contabilidad). `operations_policy` y `medical_direction_policy` quedan denegadas para Discuss por defecto.

Un canal fuera de la allowlist se deniega con `discuss_channel_not_allowed:<id>` **aunque el ID exista y sea alcanzable en Odoo** — el error no distingue "no existe" de "no autorizado".

## Adjuntos: copiar, nunca mover (sec G4, ADR-014)

`odoo_attach_discuss_attachment_to_task` **SIEMPRE copia**, nunca mueve el adjunto original. Orden de verificacion (cada paso corta el flujo si falla):

1. El `attachment_id` DEBE pertenecer a un `mail.message` de ESE canal allowlisted — verificado server-side cruzando contra Odoo, no se confia en el `channel_id` que manda el cliente.
2. `file_size` se valida contra `policy.attachment_max_bytes(policy)` (default 10 MB, `discuss_attachment_max_bytes` en config) **ANTES** de pedir el campo `datas` (el binario).
3. La tarea destino debe ser visible para el actor.
4. Solo entonces se lee el binario y se crea un `ir.attachment` **nuevo** en la tarea. El adjunto y el mensaje origen quedan intactos: nunca hay `write` ni `unlink` sobre el original.

## Tools prohibidas (sec 9.9)

Bajo NINGUNA circunstancia:

- `odoo_execute_kw`, `odoo_execute`, `odoo_raw_call`
- `odoo_admin_*`, `odoo_sudo_*`

Test `test_no_generic_execute_tool` los detecta por grep en `app/tools/*.py`.

## Audit log

JSONL append-only en `/opt/odoo-mcp-v2/logs/audit.jsonl`. Campos obligatorios (sec 14.3):

```json
{
  "request_id": "uuid",
  "timestamp": "2026-05-12T...Z",
  "actor": "willy|yuniesky|anet",
  "role": "owner|operations|medical_direction",
  "client_type": "claude_connector|chatgpt_connector|curl|dev",
  "tool": "odoo_create_project_task_apl",
  "model": "project.task",
  "action": "create",
  "allowed": true,
  "denied_reason": null,
  "latency_ms": 1240,
  "result_count": 1,
  "args_hash": "sha256:...",
  "odoo_uid": 9,
  "error_class": null
}
```

## Rate limits

Sliding window 60s in-memory por actor.

Defaults (sec 8.x):

| Rol | requests/min | writes/min |
|---|---|---|
| owner | 60 | 20 |
| operations | 40 | 15 |
| medical_direction | 40 | 15 |

Si excede → response `denied:requests_per_minute_exceeded` con `retry_after`. NO afecta otros actores.

## Rotación de tokens

1. `python scripts/generate_mcp_token.py --actor <actor>` (en máquina segura).
2. Reemplazar `token_hash` en `/opt/odoo-mcp-v2/secrets/actors.yaml`.
3. Distribuir nuevo `MCP_TOKEN` al actor por canal seguro (no Slack/email plain).
4. Restart del contenedor (recarga registry).
5. Revisar `audit.jsonl` por uso del token anterior si se sospecha exposición.

## Lo que NUNCA hace el MCP

- `sudo(...)` en llamadas Odoo.
- Manipulación de contexto para escalar privilegios.
- Hardcodeo de UID o login de ningún actor.
- Exponer Odoo API Key al LLM ni en responses.
- Loguear `Authorization`, MCP token, Odoo API key, contenido `.env`.
- Crear tool genérica `execute_kw`.
- Modificar infraestructura del Odoo de producción.
