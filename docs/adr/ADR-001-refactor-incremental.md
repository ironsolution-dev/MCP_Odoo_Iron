# ADR-001 — Refactor incremental sobre MCP operativo (no greenfield)

**Estado:** Vigente
**Fecha:** 2026-05-12

## Contexto

El MCP Odoo APL 2.0 está operativo en BLUE (`mcp.ovnisystem.com`) sirviendo a Willy desde Claude.ai y ChatGPT. Funciona; no hay incidentes.

## Decisión

Refactor incremental sobre la estructura validada (FastMCP, transporte streamable-http, Traefik, etc.). No reescritura desde cero.

## Consecuencias

- El conocimiento operativo del baseline se preserva.
- Tools BLUE se migran 1:1 a actor-aware con aliases hasta QA aprobada.
- El riesgo de regresión queda acotado a las capas nuevas (auth, policy, audit).

## Alternativas descartadas

- Reescritura completa: riesgo alto, sin valor incremental, plazo no lo permite.
