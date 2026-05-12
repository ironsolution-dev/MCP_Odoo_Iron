# Diff Git vs contenedor BLUE

> Generado en Fase 0. Compara el repo Git de origen del MCP BLUE actual contra `/app/` real dentro del contenedor en producción.

## Procedimiento (lo ejecuta Willy)

```bash
# 1. Snapshot /app del contenedor
TS=$(date +%Y%m%d_%H%M%S)
docker cp odoo-mcp:/app /tmp/odoo-mcp-blue-app-$TS
ls /tmp/odoo-mcp-blue-app-$TS

# 2. Si existe un repo Git de origen del BLUE, comparar
# (sustituir GIT_PATH por el path real del repo BLUE)
diff -r GIT_PATH/ /tmp/odoo-mcp-blue-app-$TS/ > /tmp/blue_diff.txt || true
cat /tmp/blue_diff.txt
```

## Resultado

TODO_WILLY: pegar resumen del diff. Si no hay repo Git de origen, indicar "BLUE construido directo sobre VPS sin repo intermedio".

## Archivos clave a revisar (sec 3.3 Task Packet)

| Archivo | Esperado | Diferencia? |
|---|---|---|
| `/app/odoo_mcp_remote.py` | Entry point FastMCP | TODO_WILLY |
| `/app/odoo_mcp_server.py` | OdooClient + tools APL 2.0 | TODO_WILLY |
| `/app/.env.odoo` | Redundante (no usar) | TODO_WILLY |
| `/app/.venv` | Python 3.12 venv | TODO_WILLY |

## Conclusión

TODO_WILLY: una linea — "Git refleja el contenedor" / "Hay drift en X archivos" / "No hay repo Git BLUE".
