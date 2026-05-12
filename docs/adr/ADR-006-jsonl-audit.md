# ADR-006 — Audit log JSONL primero, persistencia DB después

**Estado:** Vigente
**Fecha:** 2026-05-12

## Contexto

Necesitamos atribuir cada acción a un actor (rol, tool, modelo, acción, allowed/denied) con suficiente detalle para incidencias y compliance. Una solución completa con DB añade complejidad operativa para fase 1.

## Decisión

Audit log como JSONL append-only en `/opt/odoo-mcp-v2/logs/audit.jsonl`. Una línea por request, con campos definidos en sec 14.3 del Task Packet. Tokens, headers `Authorization` y argumentos sensibles redactados; `args_hash` (sha256) sustituye el contenido en claro.

Fase futura: pipeline a DB para queries históricas y dashboards.

## Consecuencias

- Cero infra adicional para arrancar.
- Rotación de log queda a cargo de operación (logrotate o equivalente).
- Auditoría no degrada performance perceptiblemente (append + fsync).
- `grep` / `jq` cubre las queries de hoy.

## Alternativas descartadas

- DB de inicio: sobreingeniería para fase 1, sin caso de uso que lo demande hoy.
- Logging estándar a stdout: pierde estructura, mezcla con logs del framework.
