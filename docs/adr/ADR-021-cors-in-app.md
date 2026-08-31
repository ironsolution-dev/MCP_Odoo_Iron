# ADR-021 — CORS se resuelve en la app, no en Traefik

**Estado:** Vigente, con riesgo aceptado TEMPORALMENTE (ticket 807, 31-ago-2026)

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

## Riesgo aceptado (hallazgo de julio-qa)

`Access-Control-Allow-Origin` **no** está acotado: el código toma el
`Origin` del request (`headers_raw.get(b'origin') or b'*'`) y lo refleja
tal cual, sin compararlo contra ninguna allowlist de orígenes permitidos.
Verificado contra el servidor real con un origen arbitrario no confiable
(`https://claude.ai` en los tests, pero el código no distingue ese valor
de cualquier otro `Origin` que llegue — no hay lógica de comparación, solo
eco): cualquier origen, hostil o no, recibe
`Access-Control-Allow-Origin: <su-propio-origin>` de vuelta.

Esto **no abre el vector clásico de robo de cookies de sesión**: la
autenticación es Bearer/`X-Api-Key` en header, nunca cookie, y la respuesta
no lleva `Access-Control-Allow-Credentials: true` — un script en un origen
hostil no puede leer una sesión de navegador ajena porque no hay sesión de
navegador que leer. Pero sí es superficie sin control: cualquier página
web, si consigue o roba un token MCP válido por otra vía, podría llamar al
conector desde el navegador de una víctima y leer la respuesta
`fetch()`-eada, porque el origen nunca se valida.

**Riesgo aceptado TEMPORALMENTE.** Remediación: allowlist explícita de
orígenes permitidos (reemplazar el eco por una comparación contra una
lista en config, con `Access-Control-Allow-Origin` ausente o `null` para
orígenes no listados) — ticket Odoo APL 867. Debe cerrarse **antes** de
servir a cualquier cliente MCP real desde navegador; hoy los tres actores
(Willy/Claude, Willy/ChatGPT, automatizaciones) no llaman desde un
navegador, por eso el riesgo se acepta para este cierre y no bloquea el
ticket 807.

## Consecuencias

- `OPTIONS /mcp/*` responde `2xx` sin exigir token, con
  `Access-Control-Allow-Methods/Headers` acotados. Cubierto por
  `test_options_responde_2xx_con_cors`, `test_options_sin_token_no_requiere_auth`.
- La respuesta real (`GET`/`POST`) también lleva
  `Access-Control-Allow-Origin`, no solo el preflight. Cubierto por
  `test_respuesta_real_lleva_access_control_allow_origin`.
- `Access-Control-Allow-Origin` refleja cualquier origen sin allowlist —
  ver "Riesgo aceptado" arriba. Ticket 867 (vence antes de exponer un
  cliente de navegador) es dueño de cerrarlo.
- CORS queda acoplado al ciclo de deploy de la app (rebuild+redeploy),
  no editable en caliente en Traefik — misma disciplina que el resto del
  código versionado.

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
