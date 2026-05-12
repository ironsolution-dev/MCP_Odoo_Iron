# ADR-010 — Compatibilidad dual Claude.ai + ChatGPT en GREEN

**Estado:** Vigente (NUEVO v2)
**Fecha:** 2026-05-12

## Contexto

Los actores usan tanto Claude.ai como ChatGPT. Forzar a usar solo uno reduciría adopción. Cada conector puede tener comportamientos ligeramente distintos respecto a headers, encoding y respuesta `streamable-http`.

## Decisión

El endpoint GREEN sirve a Claude.ai y ChatGPT en paralelo, sobre el mismo proceso y el mismo `token_registry`. Cualquier diferencia operativa (Bearer vs ruta opaca, headers de control) se resuelve dentro del `auth_middleware` sin clonar contenedores.

Cada actor configura SU conector personalizado con SU token; la presencia simultánea de Claude.ai y ChatGPT no introduce identidad cruzada.

## Consecuencias

- El servidor debe ser explícito sobre la fuente del request en `audit.jsonl` (`client_type: claude_connector | chatgpt_connector | curl | dev`).
- Cualquier divergencia en transporte se resuelve con tests específicos por conector.
- Cambios de comportamiento de un conector se pueden compensar en `auth_middleware` sin afectar al otro.

## Alternativas descartadas

- Dos contenedores (uno por conector): triplica operación, mismo proceso de auth de fondo.
- Soportar solo uno: dependencia operativa de la roadmap de ese vendor.
