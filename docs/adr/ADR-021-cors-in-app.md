# ADR-021 — CORS se resuelve en la app, no en Traefik

**Estado:** Vigente. Riesgo aceptado temporal (ticket 807, 31-ago-2026)
**remediado** por allowlist explícita de orígenes (ticket 867, 31-ago-2026).

## Contexto

Un cliente MCP desde navegador necesita que el servidor responda al
preflight `OPTIONS` y que la respuesta real lleve
`Access-Control-Allow-Origin` — si no, el navegador bloquea la respuesta
aunque el servidor la haya procesado bien. El conector corre detrás de
Traefik (VPS82); CORS podría resolverse ahí (middleware de Traefik) o en
la propia app (`BearerMiddleware`).

## Decisión

CORS se resuelve **en la app**, no en Traefik: `BearerMiddleware` responde
`OPTIONS /mcp*` con `204` sin exigir token (el preflight del navegador no
manda `Authorization`) y envuelve el `send` de las respuestas reales
(`GET`/`POST`) para inyectar `Access-Control-Allow-Origin` también ahí, no
solo en el preflight. Se prefiere la app porque el resto de la
autenticación/autorización ya vive ahí (ADR-018/019) y mantener CORS junto
a esa lógica evita que una capa de infraestructura fuera del repo decida
sobre un aspecto de seguridad del protocolo.

`Access-Control-Allow-Methods` y `Access-Control-Allow-Headers` sí están
acotados a constantes fijas (`_CORS_ALLOW_METHODS`/`_CORS_ALLOW_HEADERS`
en `app/odoo_mcp_remote.py`) — los métodos y headers que el protocolo MCP
realmente usa (`GET, POST, OPTIONS`; `Authorization, Content-Type,
X-Api-Key, Accept, Mcp-Session-Id, Mcp-Protocol-Version`), no una
allowlist abierta.

## Riesgo aceptado (hallazgo de julio-qa) — REMEDIADO (ticket 867, 31-ago-2026)

Al cierre del ticket 807, `Access-Control-Allow-Origin` **no** estaba
acotado: el código tomaba el `Origin` del request
(`headers_raw.get(b'origin') or b'*'`) y lo reflejaba tal cual, sin
compararlo contra ninguna allowlist de orígenes permitidos. Verificado
contra el servidor real con un origen arbitrario no confiable
(`https://claude.ai` en los tests, pero el código no distinguía ese valor
de cualquier otro `Origin` que llegara — no había lógica de comparación,
solo eco): cualquier origen, hostil o no, recibía
`Access-Control-Allow-Origin: <su-propio-origin>` de vuelta.

Esto **no abría el vector clásico de robo de cookies de sesión**: la
autenticación es Bearer/`X-Api-Key` en header, nunca cookie, y la respuesta
no lleva `Access-Control-Allow-Credentials: true` — un script en un origen
hostil no podía leer una sesión de navegador ajena porque no había sesión de
navegador que leer. Pero sí era superficie sin control: cualquier página
web, si conseguía o robaba un token MCP válido por otra vía, podía llamar al
conector desde el navegador de una víctima y leer la respuesta
`fetch()`-eada, porque el origen nunca se validaba.

**Remediado en el ticket 867 (31-ago-2026).** `BearerMiddleware`
(`app/odoo_mcp_remote.py::_resolve_cors_origin`) ahora compara el `Origin`
recibido contra `ALLOWED_ORIGINS` — fuente única en
`app/cors_config.py`/`config/cors_allowlist.yaml`, arrancada con
`https://claude.ai` y `https://chatgpt.com`:

- Origen en la allowlist → se refleja, igual que antes, pero solo para
  estos orígenes.
- Origen **no** listado (hostil o no) → la respuesta se sirve igual (no
  hay `403`; el servidor no puede distinguir un navegador de un script),
  pero **sin ninguna cabecera CORS** — un navegador del origen no listado
  no puede leerla vía `fetch()`/`XHR`.
- Sin header `Origin` (CLI/curl, el camino de Willy) → comportamiento
  idéntico al anterior a este ticket (`Access-Control-Allow-Origin: *`):
  no hay navegador de por medio, así que no hay allowlist que aplicar.

Cubierto por `tests/test_cors_allowlist.py` (allowlist unitaria +
integración contra el servidor real: origen listado, origen hostil,
ausencia de `Origin`).

## Consecuencias

- `OPTIONS /mcp/*` responde `2xx` sin exigir token, con
  `Access-Control-Allow-Methods/Headers` acotados. Cubierto por
  `test_options_responde_2xx_con_cors`, `test_options_sin_token_no_requiere_auth`.
- La respuesta real (`GET`/`POST`) también lleva
  `Access-Control-Allow-Origin` cuando el origen está en la allowlist, no
  solo el preflight. Cubierto por
  `test_respuesta_real_lleva_access_control_allow_origin`.
- `Access-Control-Allow-Origin` ya **no** refleja cualquier origen: solo
  los de `config/cors_allowlist.yaml` (ticket 867, remediado — ver arriba).
- CORS queda acoplado al ciclo de deploy de la app (rebuild+redeploy),
  no editable en caliente en Traefik — misma disciplina que el resto del
  código versionado. La allowlist de orígenes sigue el mismo patrón:
  fichero en `config/` horneado en la imagen, `CORS_ALLOWLIST_PATH` solo
  para overrides de test/desarrollo (igual que `APL_LABELS_PATH`).

## Alternativas descartadas

- Resolver CORS en Traefik (middleware `headers` con `accessControlAllowOriginList`):
  descartado para este ticket porque mezclar la decisión de seguridad
  (qué orígenes confiar) con infraestructura fuera del repo dificulta
  auditarla junto al resto de la autenticación; se revisita si Traefik ya
  tiene una allowlist de orígenes para otros servicios que convenga
  reutilizar.
- Cerrar la allowlist de orígenes en este mismo ticket: descartado por
  alcance — el diseño del 29-ago-2026 fijó el ticket 807 para unificar
  auth GET/POST y restaurar discovery; la allowlist de CORS es un cambio
  de política de seguridad independiente, con su propio ticket (867) y su
  propia decisión de qué orígenes son válidos.
