# ADR-004 — Odoo ACL primero + MCP policy engine como segunda capa

**Estado:** Vigente
**Fecha:** 2026-05-12

## Contexto

Odoo ya tiene un sistema de ACL maduro (grupos, record rules, field-level security). Duplicarlo en el MCP sería redundante y propenso a drift.

## Decisión

La autoridad de permisos es Odoo. El MCP **no eleva, no salta, no suplanta** la ACL.

El `policy_engine` del MCP es una capa adicional que impide que un LLM use tools/modelos/acciones/campos que no corresponden al rol, **independientemente de si Odoo lo permitiría**. Sirve para limitar el contrato del MCP, no para gestionar permisos generales del usuario.

Regla:

```
allow = odoo_allows(actor, model, action, record)
      AND mcp_policy_allows(actor, role, tool, model, action, fields)
      AND input_validation_passes(tool, payload)
```

Si cualquier término es falso → deny.

## Consecuencias

- Si Odoo cambia permisos, no hay que tocar el MCP.
- Si el MCP añade una tool nueva sin policy, queda denegada por defecto.
- Las allowlists (`hr.employee`, `res.partner`) viven en el MCP porque limitan campos visibles al LLM (defensa en profundidad), aunque Odoo permita leer más.

## Alternativas descartadas

- Solo Odoo ACL: el LLM tendría acceso a cualquier tool que el usuario puede ejecutar; muy permisivo.
- Solo MCP policy: duplicaría reglas de Odoo y eventualmente quedaría desactualizado.
