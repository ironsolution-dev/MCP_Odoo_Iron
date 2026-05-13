# Etapas APL 2.0 reales en Odoo

> Fase 0. Generado contra Odoo BLUE para evitar mismatches al crear/mover tareas. **Es source of truth para tools que mueven `project.task` entre etapas.**

## Procedimiento (lo ejecuta Willy)

```bash
# Vía MCP BLUE actual, llamar odoo_personal_stages:
curl -s -X POST https://mcp.ovnisystem.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer <MCP_TOKEN_BLUE>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"odoo_personal_stages","arguments":{}}}'
```

## Resultado

TODO_WILLY: pegar lista exacta de etapas. Esperado algo similar a:

| ID | Nombre (literal) | Función operativa |
|---|---|---|
| TODO_WILLY | Inbox | Nuevas, sin clasificar |
| TODO_WILLY | Hoy | Foco del día |
| TODO_WILLY | Esta semana | Próximas 7 días |
| TODO_WILLY | Cuando pueda | Backlog |
| TODO_WILLY | En espera | Bloqueada |
| TODO_WILLY | Done | Cerradas con evidencia |
| TODO_WILLY | Cancelled | Canceladas con motivo |

## Validación en v2

- El test `test_validate_apl_stages` lee este documento y verifica que `tools/system.py::odoo_validate_apl_stages` retorna los mismos nombres exactos.
- Cualquier desalineación en nombres causa falla del test → bloquea el deploy.

## Notas APL 2.0 (sec 3.5 Task Packet)

- No crear tareas ambiguas.
- No cerrar sin evidencia.
- No afirmar que algo se hizo sin releer Odoo.
- Si falta prioridad, área, tipo o fecha → inferir y avisar la suposición.

### Título APL 2.0

```
[APL 2.0][P0/P1/P2/P3][Área][Tipo] Verbo + entregable + contexto
```

### Descripción obligatoria

```
- Objetivo
- Entregable
- Responsable
- Fecha límite
- Criterio de cierre
- Evidencia requerida
- Riesgo si no se cierra
- Siguiente acción
```
