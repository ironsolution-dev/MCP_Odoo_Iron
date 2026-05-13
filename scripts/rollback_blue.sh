#!/usr/bin/env bash
# Restaurar BLUE desde el ultimo snapshot conocido en /opt/odoo-mcp-v2/backups/.
# IMPROBABLE — solo usar si BLUE fue modificado por error pese al mandato de no tocarlo.
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/opt/odoo-mcp-v2/backups}"
LATEST_BACKUP="$(ls -1d "${BACKUP_ROOT}"/*/ 2>/dev/null | tail -1 || true)"

if [ -z "${LATEST_BACKUP}" ]; then
  echo "FAIL no hay backups en ${BACKUP_ROOT}"
  exit 1
fi

echo "Restaurando BLUE desde: ${LATEST_BACKUP}"

if [ ! -s "${LATEST_BACKUP}/blue.tar" ]; then
  echo "FAIL ${LATEST_BACKUP}/blue.tar ausente"
  exit 1
fi

echo "[1/3] docker load ..."
docker load -i "${LATEST_BACKUP}/blue.tar"

echo "[2/3] Stop+rm BLUE actual ..."
docker stop odoo-mcp 2>/dev/null || true
docker rm odoo-mcp 2>/dev/null || true

echo "[3/3] Run BLUE restaurado ..."
docker run -d \
  --name odoo-mcp \
  --restart unless-stopped \
  --network proxy \
  --env-file /root/.env.odoo \
  --label "traefik.enable=true" \
  --label "traefik.http.routers.odoomcp.entrypoints=websecure" \
  --label "traefik.http.routers.odoomcp.rule=Host(\`mcp.ovnisystem.com\`)" \
  --label "traefik.http.routers.odoomcp.tls=true" \
  --label "traefik.http.routers.odoomcp.tls.certresolver=letsencrypt" \
  --label "traefik.http.services.odoomcp.loadbalancer.server.port=8000" \
  odoo-mcp:latest

sleep 5
echo "Validando ..."
curl -fsS -X POST https://mcp.ovnisystem.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | head -c 200 && echo "" && echo "BLUE restaurado."
