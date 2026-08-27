# CLAUDE.md — repo odoo-mcp v2

> Instrucciones específicas del proyecto MCP Odoo v2. Para reglas operativas globales de JuliO I/O ver el repo padre.

## Identidad operativa

JuliO I/O — fábrica técnica IronSolution. Modo refactor incremental Blue/Green.

## Fuente de verdad

`TASK_PACKET_v2_MCP_Odoo_APL_2_0_Multiusuario_BlueGreen.md` en el repo padre (`../`). Decisiones cerradas en sec 4.1; ADRs en `docs/adr/`.

## Anti-drift (sec 2.2 Task Packet — resumen)

- NO reescribir el servidor completo; refactor incremental.
- NO cambiar FastMCP por otro framework.
- NO tocar el contenedor BLUE (`odoo-mcp`) ni el dominio `mcp.ovnisystem.com`.
- NO crear tool genérica `execute_kw` / `execute` / `raw_call`.
- NO hardcodear UID 9 ni username de Willy.
- NO usar `sudo` en llamadas Odoo.
- NO escribir en `account.move`, `account.payment`, `res.users`, `res.company`, `ir.*`, `stock.*`, `purchase.order`, `sale.order`, `hr.contract` (denylist global).
- NO loguear `Authorization`, MCP tokens, Odoo API keys, contenido `.env`.
- NO crear archivos fuera de `app/`, `config/`, `scripts/`, `tests/`, `docs/` y root del repo.
- NO modificar tests para que pasen (corregir el código, no el test).

## Convenciones de código

- Python 3.12, async/await en tools y middleware.
- Type hints obligatorios en funciones públicas.
- Tools de escritura: **siempre** `policy.allows()` → `odoo.<op>` → read-after-write → return.
- Comentarios solo cuando el "por qué" no es obvio del nombre.
- 300 líneas máximo por archivo (anti-sobreingeniería).

### Excepción declarada: `app/tools/tasks.py` (ticket 737, ronda 2, hallazgo F4)

`app/tools/tasks.py` quedó en 314 líneas tras fusionar el rescate de
`extract_write_id` (F1) + el contrato APL 2.0 (`parse_and_validate_apl_task_input`,
`tag_ids`, `priority_star`) en `odoo_create_my_todo_apl` /
`odoo_create_project_task_apl`. `app/schemas.py` (que también superaba las
300 líneas) sí se partió — los validadores APL 2.0 se movieron a
`app/apl_validation.py`, limpio porque eran una responsabilidad separable
(contrato de payload) de lo genérico que se quedó en `schemas.py`
(`ValidationError`, `validate_iso_date`, contrato de escritura).

`tasks.py` no se partió: agrupa las 9 tools BLUE migradas + las nuevas de
`project.task`, todas bajo el mismo dominio y la misma convención
"función async por tool, prefijo `odoo_`" de esta sección. Partirlo por
lectura/escritura (`task_reads.py`/`task_writes.py`) exigía tocar el
registro de tools en `app/tools/__init__.py` y las policies por actor
(`allowed_tools`) para un archivo que está 14 líneas (4.6%) sobre el
límite — riesgo desproporcionado al beneficio para un hallazgo MENOR.
Deuda declarada: si `tasks.py` gana otra tool de escritura, se revisita
el split lectura/escritura en un ticket aparte.

## Estructura de tools

Una función async por tool, prefijo `odoo_`, firma `(actor, odoo, policy, ...kwargs) -> dict`. Registrar en `app/tools/__init__.py` para discovery automático desde `odoo_mcp_remote.py`.

## Tests

`pytest tests/ -v`. Mocks de Odoo en `conftest.py`. Tests live se marcan con `@pytest.mark.requires_blue` / `@pytest.mark.requires_odoo`.

## Comunicación

Siempre en español. Reportes de fase: Objetivo → Contexto → Plan → Ejecución → Validación → Riesgos → Siguiente paso.
