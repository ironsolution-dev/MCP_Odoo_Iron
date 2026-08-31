# ADR-018 — GET y POST comparten un único pipeline de autenticación

**Estado:** Vigente (ticket 807, 31-ago-2026)

## Contexto

`BearerMiddleware` (`app/odoo_mcp_remote.py`) solo autenticaba en la rama
`POST`: extraía el token (Bearer, `X-Api-Key` o path opaco), verificaba el
actor y reescribía `/mcp/<token>` → `/mcp` únicamente ahí. La rama `GET`
pasaba directo a FastMCP sin pasar por ninguno de esos pasos. Dos huecos
concretos:

1. `GET /mcp/<token>` devolvía `404`: la reescritura de path que traduce
   `/mcp/<token>` a `/mcp` solo corría en la rama POST, así que FastMCP
   nunca veía una ruta registrada.
2. `GET /mcp` (sin token en el path) pasaba sin autenticar — el token en
   header (Bearer/`X-Api-Key`) tampoco se validaba en esta rama.

Ambos son el mismo síntoma: la autenticación estaba acoplada al verbo
HTTP en vez de al recurso.

## Decisión

Un solo bloque de autenticación, compartido por `GET` y `POST` (`OPTIONS`
se resuelve aparte, ver ADR-021): extrae token → `_registry.verify()` →
si no hay actor, `401` con `WWW-Authenticate` (ADR-019) → si el token vino
en el path, reescribe `/mcp/<token>` → `/mcp` — todo esto **antes** de
bifurcar por método. Solo después de autenticar se decide qué responder en
`GET` (discovery o SSE, ADR-020) vs `POST` (FastMCP).

El pipeline de auth "fantasma" en `AuthMiddleware.authenticate()` (cubierto
por `test_auth_middleware.py` pero nunca invocado desde este path vivo) no
se tocó: consolidarlo con `BearerMiddleware` es un cambio más grande, fuera
del alcance de este ticket — queda declarado como deuda en el ticket Odoo
864.

## Consecuencias

- `GET /mcp/<token>` y `GET /mcp` responden `200` (discovery, autenticado)
  o `401` (token inválido o ausente) — nunca `404` ni contenido sin
  autenticar. Cubierto por `tests/test_mcp_auth_unification.py`
  (`test_get_con_token_valido_responde_discovery_no_404`,
  `test_get_sin_token_401_nunca_404_ni_contenido_sin_auth`).
- `POST /mcp/<token>` no cambia de comportamiento observable: mismos
  códigos, mismas 49 tools (regresión en
  `tests/test_mcp_regression_and_real_client.py`).
- Sigue habiendo dos implementaciones de autenticación en el repo
  (`BearerMiddleware` viva y `AuthMiddleware.authenticate()` sin usar) —
  riesgo de que alguien las confunda o edite la que no corre. Mitigado por
  el comentario explícito en el código y por el ticket 864.

## Alternativas descartadas

- Duplicar la extracción/verificación de token en la rama GET tal cual
  estaba en POST: descartado por ser exactamente el patrón que causó el
  drift original (dos copias del mismo chequeo divergiendo con el tiempo).
- Consolidar `AuthMiddleware.authenticate()` como pipeline único en este
  mismo ticket: descartado por alcance — el diseño del 29-ago-2026 lo dejó
  explícitamente fuera para no mezclar el fix de auth GET/POST con una
  refactorización mayor del middleware.
