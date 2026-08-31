# EVIDENCIA — Ticket 867 (Odoo APL, vence 5-sep-2026)

**Acotar CORS del MCP Odoo v2 a una allowlist de orígenes conocidos.**

Rama: `julio/867-cors-allowlist`
Base: `main` @ `0242689` (tag `multiuser-v0.4.6`, ticket 807 ya sellado)
Worktree: `/Users/willyhierro/Documents/Proyectos/Infinity/odoo_mcp/v2/odoo-mcp-v2-julio867`
Entorno de pruebas: `.venv` compartido del repo fuente
(`odoo-mcp-v2-source/.venv/bin/python`) ejecutado con `cwd` en este worktree
(pytest resuelve `app/` local por `tests/__init__.py`, verificado — ver
criterio 3). Todo local, sin VPS82/Odoo real/secretos (`FakeOdooClient` en
`tests/fixtures_mcp_live.py`, ya existente del ticket 807).

## Contexto leído antes de construir

- `docs/adr/ADR-021-cors-in-app.md` (versión previa al ticket): riesgo
  aceptado temporal — `Access-Control-Allow-Origin` reflejaba cualquier
  `Origin` sin comparar contra nada.
- `app/odoo_mcp_remote.py` (commit `c0bbcc3`, parte CORS del 807):
  `BearerMiddleware.__call__` líneas ~113-183, `_cors_send`, `_send_json`,
  `_send_preflight`.
- Patrón de config existente: `app/apl_labels.py` (`_DEFAULT_PATH` en
  `config/`, override opcional `APL_LABELS_PATH` solo para tests) — mismo
  mecanismo reutilizado para `app/cors_config.py` / `CORS_ALLOWLIST_PATH`.

## Cambios

- `config/cors_allowlist.yaml` (nuevo, committed a git — no es secreto):
  `allowed_origins: [https://claude.ai, https://chatgpt.com]`.
- `app/cors_config.py` (nuevo): `load_allowed_origins()` +
  `ALLOWED_ORIGINS` (frozenset cargado una vez al importar).
- `app/odoo_mcp_remote.py`: `_resolve_cors_origin()` nuevo (reemplaza
  `headers_raw.get(b'origin') or b'*'`); `_cors_send`, `_send_json`,
  `_send_preflight` ahora reciben `Optional[bytes]` y omiten las cabeceras
  CORS cuando es `None`.
- `docs/adr/ADR-021-cors-in-app.md`: riesgo marcado REMEDIADO con fecha y
  referencia al 867.
- `CHANGELOG.md`: entrada `[Unreleased]` (v0.4.6 sellada, no tocada).
- `tests/test_cors_allowlist.py` (nuevo, 11 tests): unidad de
  `cors_config.py` + integración contra el servidor real (`mcp_live`).

## Criterio de cierre → comando → resultado

### 1. Origen hostil → sin reflejo (preflight y respuesta real)

```
$ .venv/bin/python -m pytest tests/test_cors_allowlist.py -k hostil -v
tests/test_cors_allowlist.py::test_origen_hostil_preflight_sin_reflejo PASSED
tests/test_cors_allowlist.py::test_origen_hostil_respuesta_real_sin_reflejo_pero_no_bloquea PASSED
tests/test_cors_allowlist.py::test_origen_hostil_401_tambien_sin_reflejo PASSED
3 passed
```

Verificado contra el servidor real en loopback (uvicorn, `httpx.AsyncClient`,
no mocks) con `Origin: https://evil-attacker.example`:
- `OPTIONS` (preflight) → `2xx`, **sin** `access-control-allow-origin` ni
  `access-control-allow-methods`/`-headers` (antes: los reflejaba).
- `GET` con token válido → `200`, **sin** `access-control-allow-origin`
  (la respuesta se sirve igual — no hay `403`, tal como pide el ticket).
- `GET` con token inválido → `401`, **sin** `access-control-allow-origin`
  tampoco en el camino de error.

### 2. Orígenes listados funcionan (preflight y respuesta real)

```
$ .venv/bin/python -m pytest tests/test_cors_allowlist.py -k listado -v
tests/test_cors_allowlist.py::test_origen_listado_preflight_headers_correctos PASSED
tests/test_cors_allowlist.py::test_origen_listado_chatgpt_preflight_headers_correctos PASSED
tests/test_cors_allowlist.py::test_origen_listado_respuesta_real_headers_correctos PASSED
3 passed
```

`https://claude.ai` y `https://chatgpt.com` reciben
`Access-Control-Allow-Origin: <su-origen>` en preflight y en la respuesta
real; `access-control-allow-methods` incluye `POST`. Los tests existentes
del 807 (`tests/test_mcp_auth_unification.py::test_options_responde_2xx_con_cors`
y `::test_respuesta_real_lleva_access_control_allow_origin`), que ya usaban
`https://claude.ai`, se dejaron **sin tocar** — siguen en verde porque
`claude.ai` está en el arranque de la allowlist; no hubo que declarar
ningún ajuste por reflejo abierto asumido.

### 3. Suite completa verde (807 incluida)

```
$ cd odoo-mcp-v2-julio867 && .venv-compartido/bin/python -m pytest tests/ -v
...
190 passed, 1 skipped, 1 warning in 2.10s
```

El único skip es preexistente y ajeno al ticket:
`tests/test_blue_intact.py::test_blue_endpoint_still_responsive` —
`SKIPPED [1] tests/test_blue_intact.py:43: BLUE unreachable from this env:
HTTP Error 404: Not Found` (requiere red a BLUE real, no aplica en local).

Verificación de que la suite corrió contra el código del worktree (no el
paquete editable instalado, que apunta a `odoo-mcp-v2-source`):

```
$ .venv/bin/python -c "import app.cors_config as c; print(c.__file__)"
/Users/willyhierro/Documents/Proyectos/Infinity/odoo_mcp/v2/odoo-mcp-v2-julio867/app/cors_config.py
```

### 4. Regresión POST /mcp/\<token\> intacta byte a byte

```
$ .venv/bin/python -m pytest tests/test_mcp_regression_and_real_client.py -v
tests/test_mcp_regression_and_real_client.py::test_sdk_oficial_mcp_initialize_y_tools_list PASSED
tests/test_mcp_regression_and_real_client.py::test_regresion_post_mcp_token_mismos_codigos_y_49_tools PASSED
2 passed
```

`test_regresion_post_mcp_token_mismos_codigos_y_49_tools` (del ticket 807,
**sin modificar**) sigue verde: mismos códigos (200/401) y mismas 49 tools
listadas vía `POST /mcp/<token>` con Bearer en el path — el camino real de
Claude/Willy no cambió.

### 5. Regresión del camino sin `Origin` (CLI/curl — el camino de Willy)

```
$ .venv/bin/python -m pytest tests/test_cors_allowlist.py -k sin_header_origin -v
tests/test_cors_allowlist.py::test_sin_header_origin_identico_al_comportamiento_anterior PASSED
tests/test_cors_allowlist.py::test_sin_header_origin_preflight_tambien_identico PASSED
2 passed
```

Sin header `Origin`, tanto `GET` como `OPTIONS` siguen devolviendo
`Access-Control-Allow-Origin: *` — idéntico al comportamiento anterior al
ticket (`headers_raw.get(b'origin') or b'*'`). No se aplica allowlist
cuando no hay `Origin` que comparar (no hay navegador de por medio).

### 6. ADR-021 actualizado

`docs/adr/ADR-021-cors-in-app.md`: encabezado de estado y sección "Riesgo
aceptado" marcados **REMEDIADO (ticket 867, 31-ago-2026)**, con el
mecanismo nuevo documentado y referencia a `tests/test_cors_allowlist.py`.

### 7. CHANGELOG `[Unreleased]`

`CHANGELOG.md`: entrada `## [Unreleased] — ticket Odoo 867 (allowlist
explícita de orígenes CORS)` agregada **antes** de la entrada sellada
`[multiuser-v0.4.6]`, sin tocarla.

## Ronda 867b (QA aprobó el 867; observación convertida en ronda obligatoria)

QA aprobó los 6 criterios con evidencia en vivo, pero señaló que los 11
tests originales no cubrían las variantes adversarias que verificó a mano
contra el servidor real: el match de `_resolve_cors_origin` es **igualdad
exacta** sobre un `frozenset` de strings, y ningún test lo fijaba como
contrato explícito. Si mañana alguien "normaliza" el origen con `.lower()`
o mete un match por prefijo/sufijo, ningún test de la ronda original lo
hubiera detectado.

**No se tocó código de producción** — solo `tests/test_cors_allowlist.py`.

```
$ .venv/bin/python -m pytest tests/test_cors_allowlist.py -v
...
tests/test_cors_allowlist.py::test_origen_adversario_variante_de_claude_ai_sin_reflejo[subdominio-trampa] PASSED
tests/test_cors_allowlist.py::test_origen_adversario_variante_de_claude_ai_sin_reflejo[puerto-explicito] PASSED
tests/test_cors_allowlist.py::test_origen_adversario_variante_de_claude_ai_sin_reflejo[esquema-degradado-http] PASSED
tests/test_cors_allowlist.py::test_origen_adversario_variante_de_claude_ai_sin_reflejo[mayusculas] PASSED
tests/test_cors_allowlist.py::test_origen_adversario_variante_de_claude_ai_sin_reflejo[origin-null] PASSED
tests/test_cors_allowlist.py::test_origen_exacto_claude_ai_contraste_con_los_adversarios PASSED
...
17 passed, 1 warning in 0.74s
```

5 variantes adversarias añadidas (`https://claude.ai.evil.com`,
`https://claude.ai:443`, `http://claude.ai`, `HTTPS://CLAUDE.AI`,
`Origin: null`) — las 5 reciben respuesta `200` **sin**
`access-control-allow-origin`, igual que `HOSTILE_ORIGIN`. Más el caso
positivo de contraste: `https://claude.ai` exacto sigue reflejándose.

```
$ .venv/bin/python -m pytest tests/ -q
...
196 passed, 1 skipped, 1 warning in 2.40s
```

Mismo skip preexistente y ajeno (`test_blue_intact.py`, sin red a BLUE).
190 → 196 passed: los 6 tests nuevos de la ronda 867b, cero regresiones.

## Pendientes / limitaciones conocidas

- La allowlist arranca con solo 2 orígenes (`claude.ai`, `chatgpt.com`)
  por pedido del ticket. Agregar un tercero es editar
  `config/cors_allowlist.yaml` y redeploy — no hay UI ni endpoint de
  gestión (consistente con "CORS acoplado al ciclo de deploy", ya
  documentado en ADR-021 desde el 807).
- No se agregó `CORS_ALLOWLIST_PATH` a `scripts/validate_env.py` ni al
  README: sigue el mismo patrón que `APL_LABELS_PATH` (override opcional
  solo para tests/desarrollo, con default horneado en la imagen desde
  `config/`), que tampoco está documentado ahí. Si se decide que el
  override debe ser configurable en producción, es un cambio de alcance
  aparte.
- No se tocó `docs/security.md`: el archivo cubre secretos/policy engine,
  no CORS (el 807 tampoco lo tocó). El detalle de CORS vive en ADR-021,
  igual que antes.
