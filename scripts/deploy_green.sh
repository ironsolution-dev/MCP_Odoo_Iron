#!/usr/bin/env bash
# Build + deploy GREEN container `odoo-mcp-v2` en `mcp-v2.ovnisystem.com`.
# Pre-requisitos: snapshot BLUE hecho, DNS+cert listo, /opt/odoo-mcp-v2/secrets/ poblado.
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${1:-multiuser-v0.1.0}"
SECRETS_DIR="${SECRETS_DIR:-/opt/odoo-mcp-v2/secrets}"
LOGS_DIR="${LOGS_DIR:-/opt/odoo-mcp-v2/logs}"

echo "[1/5] Verificando precondiciones ..."
for f in "${SECRETS_DIR}/.env.v2" "${SECRETS_DIR}/actors.yaml" "${SECRETS_DIR}/policies.yaml"; do
  if [ ! -s "${f}" ]; then
    echo "  FAIL ${f} ausente o vacio"
    exit 1
  fi
done
mkdir -p "${LOGS_DIR}"
touch "${LOGS_DIR}/audit.jsonl"

echo "[2/5] Build imagen odoo-mcp:${VERSION} ..."
docker build -t "odoo-mcp:${VERSION}" .

echo "[3/5] Stop+rm GREEN existente si hay ..."
docker stop odoo-mcp-v2 2>/dev/null || true
docker rm odoo-mcp-v2 2>/dev/null || true

echo "[4/5] Run GREEN ..."
docker run -d \
  --name odoo-mcp-v2 \
  --restart unless-stopped \
  --network proxy \
  --env-file "${SECRETS_DIR}/.env.v2" \
  -e ACTORS_REGISTRY_PATH="/opt/odoo-mcp-v2/secrets/actors.yaml" \
  -e POLICIES_PATH="/opt/odoo-mcp-v2/secrets/policies.yaml" \
  -e AUDIT_LOG_PATH="/opt/odoo-mcp-v2/logs/audit.jsonl" \
  -v "${LOGS_DIR}:/opt/odoo-mcp-v2/logs" \
  -v "${SECRETS_DIR}:/opt/odoo-mcp-v2/secrets:ro" \
  --label "traefik.enable=true" \
  --label "traefik.http.routers.odoomcpv2.entrypoints=websecure" \
  --label "traefik.http.routers.odoomcpv2.rule=Host(\`mcp-v2.ovnisystem.com\`)" \
  --label "traefik.http.routers.odoomcpv2.tls=true" \
  --label "traefik.http.routers.odoomcpv2.tls.certresolver=letsencrypt" \
  --label "traefik.http.services.odoomcpv2.loadbalancer.server.port=8000" \
  "odoo-mcp:${VERSION}"

echo "[5/5] Esperando arranque y verificando ..."
sleep 6
if ! docker ps --filter name=odoo-mcp-v2 --format '{{.Status}}' | grep -q "Up"; then
  echo "  FAIL odoo-mcp-v2 no esta Up"
  docker logs --tail 100 odoo-mcp-v2 || true
  exit 1
fi

# Smoke curl al endpoint publico
if curl -fsS -X POST https://mcp-v2.ovnisystem.com/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    -o /tmp/green_health.txt 2>/dev/null; then
  echo "  OK GREEN responde en mcp-v2.ovnisystem.com"
  head -c 200 /tmp/green_health.txt
  echo ""
else
  echo "  WARN GREEN no responde via Traefik aun (DNS/cert pueden tardar). Container Up."
fi

echo ""
echo "GREEN deployado. Siguiente paso: ejecutar smoke_test_mcp.py con tokens reales."
