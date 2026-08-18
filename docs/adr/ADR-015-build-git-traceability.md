# ADR-015 — Trazabilidad build<->git permanente

**Estado:** Vigente (Fase A daily driver, sec G5 — cierre anti-drift)
**Fecha:** 2026-08-18

## Contexto

Antes de esta fase, un contenedor `odoo-mcp-v2` corriendo no tenia forma de decir de que commit/version salio. Si un deploy quedaba a medio camino (working tree sucio, tag equivocado, build viejo re-etiquetado), no habia senal en caliente — solo se descubria comparando manualmente codigo fuente contra comportamiento observado. Esto es exactamente el patron de "arriba != funcionando" que ya costo incidentes en otra infraestructura del grupo (ver hallazgos de infra 22-jul en el cerebro de Infinity).

## Decision

- `Dockerfile`: `ARG GIT_COMMIT=unknown`, `ARG MCP_VERSION=unknown` -> `ENV MCP_GIT_COMMIT`, `ENV MCP_VERSION`.
- `app/tools/system.py::odoo_health()` expone `git_commit`/`mcp_version` en la respuesta, en **ambas** ramas (Odoo autenticando OK y Odoo fallando) — es justo cuando algo esta roto que mas se necesita saber que build es.
- `scripts/deploy_green.sh` agrega una precondicion bloqueante ANTES de construir la imagen:
  - `git status --porcelain` debe estar vacio (si no, `FAIL` con el listado de lo sucio).
  - `git tag --points-at HEAD` debe incluir `${VERSION}` (si no, `FAIL` con instruccion de como taguear).
  - El `docker build` pasa `--build-arg GIT_COMMIT=$(git rev-parse HEAD) --build-arg MCP_VERSION=${VERSION}`.

Version objetivo de este cierre: `multiuser-v0.4.0` (default del script).

## Consecuencias

- `curl .../odoo_health` (o la tool MCP equivalente) dice en una sola llamada si lo que esta corriendo es lo que se penso desplegar.
- Es estructuralmente imposible etiquetar una imagen con una version cuyo codigo no coincide con el tag de git en ese commit exacto — el script se niega a construir.
- `unknown` en `git_commit`/`mcp_version` en un ambiente real (no pytest local) es en si misma una alerta: significa que la imagen no paso por `deploy_green.sh`.

## Alternativas descartadas

- Version solo en un archivo de texto dentro de la imagen (ej. `VERSION.txt`) sin verificacion de tag: no impide construir con working tree sucio, solo documenta despues del hecho.
- Verificar la version en un healthcheck externo separado: mas piezas moviendose; exponerlo en la misma tool `odoo_health` que ya se usa para diagnostico reutiliza infraestructura existente.
