# ADR-019 — WWW-Authenticate sí, OAuth completo no

**Estado:** Vigente (ticket 807, 31-ago-2026)

## Contexto

El `401` que devuelve el conector ante un token inválido no llevaba
`WWW-Authenticate`, lo que dificulta que un cliente MCP genérico (no
Claude.ai/ChatGPT, que ya conocen el token de antemano) distinga "sin
autenticar" de cualquier otro error 401 sin inspeccionar el cuerpo. La
especificación MCP moderna (y el flujo de descubrimiento de auth de OAuth
2.0) usa ese header para señalizarlo.

Los tres actores reales de este conector (Willy/Claude, Willy/ChatGPT,
automatizaciones internas) usan un **secreto pre-compartido** (token MCP
emitido por `TokenRegistry`/`generate_mcp_token.py`), no un flujo OAuth con
usuario final autorizando en un navegador. No hay hoy un cliente que
necesite descubrir un authorization server.

## Decisión

Se agrega `WWW-Authenticate: Bearer realm="odoo-mcp-v2",
error="invalid_token"` a **todo** `401` (GET y POST, mismo pipeline de
ADR-018). No se implementa OAuth 2.0 completo ni los endpoints
`/.well-known/oauth-authorization-server` / `/.well-known/oauth-protected-resource`
que ese flujo requiere — quedan fuera de alcance por diseño (Task Packet,
sec 4.1, decisión del 29-ago-2026).

## Consecuencias

- Un cliente MCP que sepa leer `WWW-Authenticate` obtiene una señal
  estándar de "reintenta con Bearer", sin necesitar los endpoints de
  descubrimiento OAuth. Cubierto por
  `test_get_token_invalido_401_con_www_authenticate` y
  `test_post_token_invalido_401_con_www_authenticate`.
- Un cliente que sí implemente descubrimiento OAuth automático (esperando
  `/.well-known/oauth-protected-resource`) no lo encontrará — seguirá
  necesitando que el token se le entregue por fuera (igual que hoy).
- Si en el futuro se necesita autorización de usuario final vía navegador
  (en vez de tokens pre-compartidos entregados por Infinity), esto se
  revisita como un ticket propio con su propio ADR — no es una extensión
  incremental de `WWW-Authenticate`.

## Alternativas descartadas

- Implementar OAuth 2.0 completo (authorization server + `/.well-known/*`)
  en este ticket: descartado por alcance y porque no hay un caso de uso
  real hoy — los tres actores ya tienen el secreto pre-compartido; añadir
  un authorization server sería superficie nueva sin consumidor.
- No tocar `WWW-Authenticate` en absoluto: descartado porque el costo de
  agregarlo es mínimo (un header) y mejora la interoperabilidad con
  clientes MCP genéricos sin comprometerse a OAuth.
