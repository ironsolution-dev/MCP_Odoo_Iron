# EVIDENCIA-807 — Conector MCP Odoo v2 agnóstico de LLM (retrocompat)

Ticket 807. Diseño aprobado por `julio-architect` (ADR-018 a ADR-022, los
ADR en sí los escribe `julio-docs` tras QA). Implementado por `julio-builder`
en rama `julio/807-mcp-agnostico`, worktree separado de
`odoo-mcp-v2-source`. **No se desplegó nada** — el gate antes de mover
tráfico lo corre `release`/Infinity después de QA.

## Rama y commits

```
$ git branch --show-current
julio/807-mcp-agnostico

$ git log --oneline d5a798b..HEAD
e60e933 docs(runbook): rollback de codigo probado en local para ticket 807
456fe0b test(mcp): cobertura end-to-end del ticket 807 (auth unificado, CORS, audit, cliente oficial)
c0bbcc3 fix(mcp): unificar auth GET/POST, restaurar discovery GET, WWW-Authenticate y CORS (ticket 807)
```

Base: `main` @ `d5a798b` (punta antes de esta rama).

## Decisiones aplicadas (para que julio-docs redacte ADR-018..022)

1. **ADR-018 (unificar auth GET/POST)**: `BearerMiddleware` en
   `app/odoo_mcp_remote.py` extrae token/verifica actor/detecta
   client_type en UN solo bloque compartido por GET y POST, en vez de que
   solo POST autenticara. Cierra a la vez el 404 de `GET /mcp/<token>`
   (la reescritura de path antes solo corría en la rama POST) y el hueco
   de `GET /mcp` sin autenticar. El pipeline "fantasma" en
   `AuthMiddleware.authenticate()` (testeado en `test_auth_middleware.py`
   pero nunca invocado desde este path vivo) **no se tocó** — su
   consolidación queda para otro ticket, tal como pidió el diseño.
2. **ADR-019 (WWW-Authenticate, no OAuth completo)**: el 401 (GET y POST)
   ahora lleva `WWW-Authenticate: Bearer realm="odoo-mcp-v2",
   error="invalid_token"`. No se implementó OAuth ni `/.well-known` — fuera
   de alcance según el diseño.
3. **ADR-020 (discovery GET por cherry-pick)**: `git cherry-pick d0a2bfb`
   (commit de mayo, soporte ChatGPT), resuelto a mano porque la clase
   `BearerMiddleware` cambió de `BaseHTTPMiddleware` a ASGI puro desde
   entonces. Preservada la semántica original (GET sin
   `Accept: text/event-stream` → JSON `{"name":"odoo-mcp-v2",...}` en vez
   de 404/406) pero ahora **detrás** del pipeline de auth unificado (ADR-018)
   — el original de mayo respondía sin autenticar, lo que habría reabierto
   el hueco de seguridad.
4. **ADR-021 (CORS en la app)**: `OPTIONS /mcp/*` responde 2xx sin exigir
   token (el preflight del navegador no manda `Authorization`) con
   `Access-Control-Allow-Methods/Headers` **acotados** a lo que el
   protocolo MCP usa — `Access-Control-Allow-Origin` NO está acotado:
   refleja cualquier `Origin` del request, sin allowlist, en el preflight
   y en las respuestas reales (GET/POST). Riesgo aceptado temporalmente,
   remediación en ticket APL 867 (allowlist de orígenes) — ver ADR-021.
5. **Causa de proceso (client_type solo en fallos)**: `BearerMiddleware`
   guarda `(client_type, user_agent)` en un `ContextVar` propio
   (`_client_info`) además del actor; `_audited()` lo adjunta a **todos**
   los eventos del audit, éxito incluido. `app/audit.py` suma el campo
   `user_agent` a `Audit.emit()` (aditivo).

## Criterios de aceptación

### 1. Cliente MCP genérico REAL (SDK oficial, no ChatGPT)

```
$ pytest tests/test_mcp_regression_and_real_client.py::test_sdk_oficial_mcp_initialize_y_tools_list -v
tests/test_mcp_regression_and_real_client.py::test_sdk_oficial_mcp_initialize_y_tools_list PASSED
```

Usa `mcp.client.streamable_http.streamable_http_client` + `mcp.ClientSession`
(paquete `mcp==1.27.1`, el mismo SDK oficial que usa el servidor) contra un
servidor MCP real levantado en `127.0.0.1` vía `uvicorn` en background
(fixture `mcp_live_server`, `tests/fixtures_mcp_live.py`). `initialize()`
devuelve `serverInfo.name == "odoo-mcp-v2"`; `list_tools()` devuelve 49
tools con los nombres exactos esperados.

### 2. Regresión POST /mcp/\<token\> — mismos códigos, mismas 49 tools

```
$ pytest tests/test_mcp_regression_and_real_client.py::test_regresion_post_mcp_token_mismos_codigos_y_49_tools -v
tests/test_mcp_regression_and_real_client.py::test_regresion_post_mcp_token_mismos_codigos_y_49_tools PASSED
```

`POST /mcp/<token>` con Bearer en el path (el camino actual de Claude/Willy)
sigue devolviendo `200` con exactamente 49 tools (snapshot exacto de
nombres, no solo el conteo) y `401` con token inválido — automatizado, no
"a ojo".

### 3. GET autenticado → discovery; GET inválido → 401 WWW-Authenticate; GET sin token → 401 (nunca 404)

```
$ pytest tests/test_mcp_auth_unification.py -v
test_get_con_token_valido_responde_discovery_no_404 PASSED
test_get_token_invalido_401_con_www_authenticate PASSED
test_get_sin_token_401_nunca_404_ni_contenido_sin_auth PASSED
test_post_token_invalido_401_con_www_authenticate PASSED
test_options_responde_2xx_con_cors PASSED
test_options_sin_token_no_requiere_auth PASSED
test_respuesta_real_lleva_access_control_allow_origin PASSED
7 passed
```

### 4. OPTIONS /mcp/\* → 2xx con CORS

Cubierto por `test_options_responde_2xx_con_cors` y
`test_options_sin_token_no_requiere_auth` (arriba). Confirmado manualmente
además contra el servidor real:

```
$ python - <<'EOF'  # smoke manual, servidor real en 127.0.0.1
OPTIONS 204 {'access-control-allow-origin': 'https://example.com',
             'access-control-allow-methods': 'GET, POST, OPTIONS',
             'access-control-allow-headers': 'Authorization, Content-Type, X-Api-Key, Accept, Mcp-Session-Id, Mcp-Protocol-Version',
             'access-control-max-age': '86400'}
EOF
```

### 5. Audit: evento de éxito graba client_type y user_agent no nulos

```
$ pytest tests/test_mcp_audit_client_type.py -v
test_evento_de_exito_graba_client_type_y_user_agent_no_nulos PASSED
test_client_type_distingue_chatgpt_de_claude_por_user_agent PASSED
test_evento_de_fallo_auth_sigue_grabando_client_type_y_ahora_tambien_user_agent PASSED
3 passed
```

Línea real del audit JSONL capturada en el smoke manual (antes de mover
las pruebas a pytest):

```json
{"request_id": "532af6b6-...", "timestamp": "2026-08-31T14:22:26Z",
 "actor": "smoke", "role": "owner", "client_type": "claude_connector",
 "user_agent": "claude-ai-mcp-client/1.0", "tool": "odoo_who_am_i",
 "allowed": true, "latency_ms": 0, "result_count": 1}
```

### 6. Suite existente del repo completa en verde

```
$ pytest tests/ -q
........................................................................ [ 40%]
.s...................................................................... [ 80%]
....................................                                     [100%]
179 passed, 1 skipped, 1 warning in 2.19s
```

179 = 167 preexistentes + 12 nuevos de este ticket. El 1 skipped es
preexistente (marker `requires_odoo`, ajeno a este ticket). Repetido 3
veces seguidas sin flakiness (tiempos: 1.93s / 1.94s / 2.00s).

### 7. Rollback PROBADO (no solo escrito)

```
$ python scripts/rollback_check_local.py main
[1/4] Rollback check contra ref=main (sha=d5a798b327a896ad7488497babf77aa4822d6675)
[2/4] git worktree add --detach /var/folders/.../odoo-mcp-rollback-2iiqe6ba main
[3/4] Levantando servidor MCP en el worktree del sha anterior ...
      modulo cargado desde: /var/folders/.../odoo-mcp-rollback-2iiqe6ba/app/odoo_mcp_remote.py
      POST tools/list -> 200 (49 tools)
      POST token invalido -> 401
[4/4] Limpiando worktree ...

ROLLBACK OK: el sha/tag anterior arranca y responde correctamente (POST tools/list -> 200, token invalido -> 401).
```

Worktree temporal creado y borrado por el propio script (`git worktree
list` antes y después confirma que no queda huérfano). Documentado en
`docs/runbook.md` sección "7.1 Rollback de código (ticket 807)".

### 8. Todo local con stubs/fixtures — nada de VPS82/Odoo real/secretos

Ningún test ni script de este ticket importa `CredentialsResolver` con
credenciales reales ni abre conexión XML-RPC. `OdooClient` se reemplaza
por `FakeOdooClient` (`tests/fixtures_mcp_live.py`) con `authenticate()` y
`get_credentials()` en memoria. Los tokens MCP usados son literales de
prueba (`mcp_live_server_test_token_...`) generados con el mismo hash
sha256 que usa `TokenRegistry`, nunca los reales de `.creds`/vault.

## Pendientes / limitaciones conocidas

- **No incluido (fuera de alcance por diseño):** OAuth completo,
  endpoints `/.well-known/*` (ADR-019). Consolidación del pipeline de auth
  "fantasma" en `AuthMiddleware.authenticate()`/`authorize_tool()` (sigue
  sin usarse desde el path vivo — mismo estado que antes de este ticket):
  declarado como deuda en ticket Odoo 864 (ver ADR-018).
- **CORS sin allowlist de orígenes (ADR-021):** `Access-Control-Allow-Origin`
  refleja cualquier `Origin`, sin comparar contra una lista permitida.
  Riesgo aceptado temporalmente porque hoy ningún cliente real llama desde
  navegador; remediación en ticket Odoo APL 867, debe cerrarse ANTES de
  servir un cliente MCP de navegador.
- **Deuda preexistente que este ticket no resuelve:** `app/odoo_mcp_remote.py`
  ya estaba declarado sobre el límite de 300 líneas/archivo (528 líneas,
  ticket Odoo 803, vence 11-sep-2026). Los cambios de este ticket lo
  llevaron a 623 líneas — sigue bajo el mismo ticket de deuda declarada;
  no se abrió una excepción nueva porque no es una violación nueva, es la
  misma ya trazada creciendo dentro de su alcance.
- **Rate limit de las fixtures de test** (`600 req/min`) es artificialmente
  alto porque una sola sesión de servidor sirve a ~15 tests; no es un
  valor de producción, no toca `config/policies.yaml.example`.
- **`docs/adr/ADR-018.md` a `ADR-022.md`** redactados por `julio-docs` tras
  QA, según el mandato de este ticket — ver `docs/adr/`.

## Cómo probarlo (para julio-qa)

```bash
cd ~/Documents/Proyectos/Infinity/odoo_mcp/v2/odoo-mcp-v2-julio807
git branch --show-current   # julio/807-mcp-agnostico

# Usar el venv ya provisto en el arbol compartido (mismas deps, mcp==1.27.1):
VENV=~/Documents/Proyectos/Infinity/odoo_mcp/v2/odoo-mcp-v2-source/.venv
$VENV/bin/python -m pytest tests/ -v

# Rollback probado:
$VENV/bin/python scripts/rollback_check_local.py main
```
