# ADR-020 — Discovery GET restaurado por cherry-pick, ahora detrás de auth

**Estado:** Vigente (ticket 807, 31-ago-2026)

## Contexto

El commit `d0a2bfb` (12-may-2026, soporte ChatGPT) hacía que
`BearerMiddleware` interceptara `GET /mcp` sin `Accept:
text/event-stream` y devolviera un JSON de discovery
(`{"name":"odoo-mcp-v2",...}`) en vez de dejar que FastMCP respondiera
`406`. El rescate de drift del 18-ago-2026 (`3f9d55b`) trajo desde
producción una versión de `BearerMiddleware` que había perdido ese
handler: `GET` sin SSE volvía a caer en el `406` genérico de FastMCP (o en
`404` para `/mcp/<token>`, ver ADR-018).

Recuperar el comportamiento de `d0a2bfb` no fue un cherry-pick limpio: la
clase `BearerMiddleware` cambió de `BaseHTTPMiddleware` (Starlette) a ASGI
puro entre mayo y ahora, así que se resolvió a mano.

## Decisión

Se restaura la semántica de discovery de `d0a2bfb` (GET sin
`Accept: text/event-stream` → `200` JSON con `name`/`version`, en vez de
`406`/`404`) **con una divergencia intencional respecto al original**: en
mayo ese handler respondía **antes** de cualquier autenticación; aquí
responde **después** del pipeline de auth unificado (ADR-018). Un GET sin
token válido ahora recibe `401`, no el discovery.

Se declara explícitamente porque un cherry-pick que preserva el
comportamiento original tal cual habría reabierto el hueco de seguridad
que este mismo ticket cierra (GET sin autenticar, ver ADR-018).

## Consecuencias

- Un cliente MCP que hace `GET /mcp` o `GET /mcp/<token>` con `Accept:
  application/json` (no streaming) y token válido recibe el discovery
  JSON — mismo contrato que ChatGPT esperaba desde mayo. Cubierto por
  `test_get_con_token_valido_responde_discovery_no_404`.
- El mismo GET sin token válido recibe `401`, nunca el discovery ni
  `404` — cubierto por `test_get_sin_token_401_nunca_404_ni_contenido_sin_auth`.
- `GET` con `Accept: text/event-stream` (Claude.ai abriendo el stream MCP)
  sigue yendo a FastMCP sin cambios, autenticado por el mismo pipeline.
- Cualquier futuro cherry-pick de commits de mayo sobre esta clase debe
  revisarse a mano: la migración a ASGI puro invalida un merge automático.

## Alternativas descartadas

- Reescribir el handler de discovery desde cero en vez de cherry-pickear:
  descartado porque el commit de mayo ya define el contrato exacto que
  ChatGPT espera (`serverInfo.name`); reescribirlo arriesgaba divergir del
  formato real sin necesidad.
- Preservar el comportamiento original de `d0a2bfb` sin autenticar (para
  minimizar el diff respecto al commit de mayo): descartado — es
  exactamente el hueco de seguridad que ADR-018 cierra para `GET`; no
  tiene sentido cerrarlo en el pipeline principal y reabrirlo en discovery.
