# ADR-022 — client_type/user_agent en TODOS los eventos de audit, no solo en fallos

**Estado:** Vigente (ticket 807, 31-ago-2026)

## Contexto

`BearerMiddleware` ya calculaba `client_type` (Claude/ChatGPT/otro, vía
`AuthMiddleware.detect_client_type`) para grabarlo en el evento de audit
cuando el token fallaba (`denied_reason='invalid_token'`). El evento de
**éxito**, emitido desde `_audited()` en `app/odoo_mcp_remote.py`, no tenía
acceso a esa información — se generaba en otro punto del código, sin el
`user_agent` ni el `client_type` a mano — así que toda tool exitosa quedaba
en el audit sin saber si vino de Claude, ChatGPT u otro cliente.

## Decisión

`BearerMiddleware` guarda `(client_type, user_agent)` en un `ContextVar`
propio (`_client_info`), poblado en el mismo bloque de autenticación de
ADR-018, junto al `ContextVar` de actor ya existente. `_audited()` lo lee
de ahí y lo pasa a **todos** los eventos que emite — éxito y fallo por
igual. `app/audit.py` suma el campo `user_agent` a `Audit.emit()` de forma
aditiva (parámetro nuevo, no rompe firmas existentes).

`_audited()` lee `_client_info.get()` en la misma tarea que lo pobló,
porque `BearerMiddleware` es ASGI puro (no `BaseHTTPMiddleware`) y no
introduce el salto de task group que impide leer `_actor` directamente en
otros puntos del código (ver comentario en el propio `_audited()`).

## Consecuencias

- El JSONL de audit permite distinguir, para cualquier evento (éxito o
  denegado), qué cliente lo generó. Cubierto por
  `tests/test_mcp_audit_client_type.py`
  (`test_evento_de_exito_graba_client_type_y_user_agent_no_nulos`,
  `test_client_type_distingue_chatgpt_de_claude_por_user_agent`,
  `test_evento_de_fallo_auth_sigue_grabando_client_type_y_ahora_tambien_user_agent`).
- No se graba el token ni ningún header de autenticación en claro en el
  audit — solo `client_type` (categoría derivada) y `user_agent` (string
  de cliente, no secreto). Verificado por `julio-qa`.
- `Audit.emit()` es compatible hacia atrás: cualquier llamador que no pase
  `user_agent` sigue funcionando (queda `None`).

## Alternativas descartadas

- Calcular `client_type`/`user_agent` de nuevo dentro de `_audited()` a
  partir de los headers crudos: exigiría pasar los headers hasta ese punto
  (que no los tiene) o duplicar `detect_client_type()`; el `ContextVar`
  reutiliza el mismo cálculo ya hecho en el middleware, una sola vez por
  request.
- Meter `client_type`/`user_agent` como parámetros explícitos en la firma
  de cada tool: descartado por invasivo — habría que tocar las 49 tools
  para pasar un dato que es transversal a la request, no al dominio de
  cada tool.
