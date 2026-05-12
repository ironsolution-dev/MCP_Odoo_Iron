#!/usr/bin/env bash
# Snapshot completo del contenedor BLUE (odoo-mcp) antes de cualquier cambio en v2.
# Ejecutar en VPS Infinity como root.
set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/opt/odoo-mcp-v2/backups/${TS}"
mkdir -p "${BACKUP_DIR}"

echo "[1/6] docker inspect odoo-mcp ..."
docker inspect odoo-mcp > "${BACKUP_DIR}/docker_inspect_blue.json"

echo "[2/6] docker logs (tail 500) ..."
docker logs --tail 500 odoo-mcp > "${BACKUP_DIR}/docker_logs_blue.txt" 2>&1

echo "[3/6] docker cp /app ..."
docker cp odoo-mcp:/app "${BACKUP_DIR}/app"

echo "[4/6] docker commit ..."
docker commit odoo-mcp "odoo-mcp:pre-multiuser-${TS}"

echo "[5/6] docker save ..."
docker save odoo-mcp:latest -o "${BACKUP_DIR}/blue.tar"

echo "[6/6] curl health BLUE ..."
curl -s -X POST https://mcp.ovnisystem.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | head -c 500 > "${BACKUP_DIR}/blue_health.txt" || echo "WARN: curl BLUE failed"

echo ""
echo "BLUE snapshot complete: ${BACKUP_DIR}"
ls -lh "${BACKUP_DIR}"
echo ""
echo "Siguiente paso: revisar archivos arriba, copiar a docs/baseline/ del repo y commitear (sin secretos)."
