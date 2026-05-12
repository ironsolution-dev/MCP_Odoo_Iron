# Permisos Odoo reales por actor

> Fase 0. Llenar antes de Fase 5 (tools de nuevos dominios). Define qué puede tocar cada actor en Odoo via su propio user, lo cual es la primera fuente de verdad de permisos (el MCP es la segunda capa).

## Procedimiento

Como admin Odoo, abrir Configuración → Usuarios → cada actor. Anotar grupos asignados, compañías visibles, y validar que la API Key del actor funciona con un curl XML-RPC mínimo.

## Actor 1 — Willy (owner)

- **Login Odoo:** TODO_WILLY (ej. `willy@ironsolution.us`)
- **API Key activa:** TODO_WILLY (sí/no, fecha creación)
- **Grupos asignados:** TODO_WILLY (lista)
- **Compañías visibles:** TODO_WILLY
- **Acceso a `project.project`:** TODO_WILLY (Lectura / Edición / Creación)
- **Acceso a `project.task`:** TODO_WILLY
- **Acceso a `calendar.event`:** TODO_WILLY
- **Acceso a `hr.employee`:** TODO_WILLY (Lectura sí/no, qué subset)
- **Acceso a `crm.lead`:** TODO_WILLY
- **Acceso a `res.partner`:** TODO_WILLY

## Actor 2 — Yuniesky (operations)

- **Login Odoo:** TODO_WILLY
- **API Key activa:** TODO_WILLY (sí/no, fecha)
- **Grupos asignados:** TODO_WILLY
- **Compañías visibles:** TODO_WILLY
- **Acceso a `project.project`:** TODO_WILLY (esperado: lectura)
- **Acceso a `project.task`:** TODO_WILLY (esperado: crear/editar en proyectos visibles)
- **Acceso a `calendar.event`:** TODO_WILLY (esperado: crear/editar)
- **Acceso a `hr.employee`:** TODO_WILLY (esperado: lectura allowlist)
- **Acceso a `crm.lead`:** TODO_WILLY (esperado: sin acceso fase 1)
- **Acceso a `res.partner`:** TODO_WILLY (esperado: lectura allowlist)

## Actor 3 — Anet (medical_direction)

- **Login Odoo:** TODO_WILLY
- **API Key activa:** TODO_WILLY (sí/no, fecha)
- **Grupos asignados:** TODO_WILLY
- **Compañías visibles:** TODO_WILLY
- **Acceso a `project.project`:** TODO_WILLY
- **Acceso a `project.task`:** TODO_WILLY
- **Acceso a `calendar.event`:** TODO_WILLY
- **Acceso a `hr.employee`:** TODO_WILLY
- **Acceso a `crm.lead`:** TODO_WILLY (esperado: lectura + notas/actividades)
- **Acceso a `res.partner`:** TODO_WILLY

## Validación curl por actor

```bash
# Sustituir ODOO_USERNAME y ODOO_API_KEY por los del actor
curl -s -X POST https://odoo.ironsolution.us/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","method":"call",
    "params":{"service":"common","method":"authenticate",
              "args":["odoo_db","ODOO_USERNAME","ODOO_API_KEY",{}]}
  }'
# Debe retornar un uid (entero). Si retorna false, la API key no es válida.
```

## Notas

- Si un actor tiene MENOS permisos que los esperados en el Task Packet, el MCP propaga el `AccessError` con `denied_reason: odoo_acl_denied`. No bypass.
- Si un actor tiene MÁS permisos que los esperados (ej. Yuniesky con acceso a `account.move`), la policy MCP igual deniega (denylist global, sec 8.6).
