# Diagnostico baseline BLUE — `docs/baseline/diagnostico.md`

> **Documento operativo Fase 0.** Lo llena Willy con outputs reales del VPS antes de Fase 1.

## 1. Qué existe operativo

- Contenedor: `odoo-mcp` en VPS Infinity (`82.25.90.203`), red `proxy`.
- URL pública: `https://mcp.ovnisystem.com/mcp` (Traefik + Let's Encrypt).
- Imagen: `odoo-mcp:latest`.
- Proceso interno: `python3 odoo_mcp_remote.py` (FastMCP, transporte `streamable-http`, puerto 8000).
- Credenciales: `/root/.env.odoo` en host VPS (no commitear).
- Odoo backend: `https://odoo.ironsolution.us/` DB `odoo_db` (Odoo 19 Community).

## 2. Tools BLUE actuales (9 — sec 3.4 del Task Packet)

`odoo_test_connection`, `odoo_personal_stages`, `odoo_personal_tasks`, `odoo_personal_tasks_today`, `odoo_personal_tasks_overdue`, `odoo_create_personal_task`, `odoo_move_personal_task`, `odoo_mark_task_done`, `odoo_cancel_task`.

## 3. Qué difiere entre Git y contenedor

> Llenar tras ejecutar `docs/baseline/git_vs_container_diff.md`.

TODO_WILLY: pegar resumen del diff Git vs `/app` del contenedor.

## 4. Qué NO se toca

- Contenedor `odoo-mcp` (BLUE) y su imagen.
- Dominio `mcp.ovnisystem.com`.
- Conectores productivos actuales en Claude.ai y ChatGPT.
- Infraestructura Odoo de producción.

## 5. Plan de rollback

Ante cualquier problema:

1. GREEN no afecta a BLUE — basta con `docker stop odoo-mcp-v2 && docker rm odoo-mcp-v2`.
2. Si por error se modificó BLUE: `bash scripts/rollback_blue.sh` desde último snapshot en `/opt/odoo-mcp-v2/backups/<TS>/`.
3. Si Traefik perdió config: revisar labels en `docker inspect odoo-mcp` snapshot.

## 6. Primera rama de trabajo

`feature/v2-baseline-spike` — sin tocar lógica de tools.
