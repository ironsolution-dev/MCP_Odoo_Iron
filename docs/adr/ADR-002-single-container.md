# ADR-002 — Un solo contenedor multiactor (estado final)

**Estado:** Vigente
**Fecha:** 2026-05-12

## Contexto

Tres actores (Willy, Yuniesky, Anet) necesitan acceder al MCP con identidad propia y permisos diferenciados.

## Decisión

Un único contenedor GREEN (`odoo-mcp-v2`) sirve a los tres actores. La identidad se resuelve por token MCP en cada request. No se clonan contenedores por usuario.

## Consecuencias

- Menor superficie operativa (un proceso, un endpoint, una imagen).
- El `token_registry` es la única autoridad de mapeo token → actor.
- La aislación se garantiza por `credentials_resolver` (cada actor usa su user Odoo + API Key) y `policy_engine` (deny-by-default por rol).

## Alternativas descartadas

- Un contenedor por actor: explosión de mantenimiento, mismo problema de auth de todas formas.
