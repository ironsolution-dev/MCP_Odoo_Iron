#!/usr/bin/env bash
# Verifica que la Fase 0 esta cerrada antes de pasar a Fase 1.
# Comprueba existencia de evidencias del baseline + plantillas de docs llenadas.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

errors=0
warn=0

check_file() {
  local path="$1"
  local label="${2:-$path}"
  if [ -s "${path}" ]; then
    echo "  OK   ${label}"
  else
    echo "  FAIL ${label} (vacio o ausente)"
    errors=$((errors + 1))
  fi
}

check_template_filled() {
  local path="$1"
  if [ ! -f "${path}" ]; then
    echo "  FAIL ${path} (no existe)"
    errors=$((errors + 1))
    return
  fi
  if grep -q "TODO_WILLY" "${path}"; then
    echo "  WARN ${path} contiene marcadores TODO_WILLY pendientes"
    warn=$((warn + 1))
  else
    echo "  OK   ${path}"
  fi
}

echo "[Fase 0] Verificando baseline ..."
check_file docs/baseline/diagnostico.md
check_file docs/baseline/blue_health.txt "docs/baseline/blue_health.txt (output curl BLUE)"
check_file docs/baseline/docker_inspect_blue.json
check_file docs/baseline/docker_logs_blue.txt
check_file docs/baseline/git_vs_container_diff.md
check_template_filled docs/baseline/connectors_auth_spike.md
check_template_filled docs/baseline/actor_odoo_permissions.md
check_template_filled docs/APL_STAGES.md

echo ""
echo "[Fase 0] Verificando subdominio GREEN ..."
if curl -sf -I https://mcp-v2.ovnisystem.com 2>/dev/null | head -1 | grep -qE "200|405"; then
  echo "  OK   https://mcp-v2.ovnisystem.com responde"
else
  echo "  WARN https://mcp-v2.ovnisystem.com no responde aun (DNS o cert pendiente)"
  warn=$((warn + 1))
fi

echo ""
echo "[Fase 0] Verificando BLUE intacto ..."
if curl -sf -X POST https://mcp.ovnisystem.com/mcp \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    -o /dev/null 2>/dev/null; then
  echo "  OK   BLUE sigue respondiendo"
else
  echo "  FAIL BLUE no responde (CRITICO)"
  errors=$((errors + 1))
fi

echo ""
if [ "${errors}" -eq 0 ] && [ "${warn}" -eq 0 ]; then
  echo "FASE 0: OK"
  exit 0
elif [ "${errors}" -eq 0 ]; then
  echo "FASE 0: OK con ${warn} warning(s) (pendientes de carril humano Willy)"
  exit 0
else
  echo "FASE 0: FAIL (${errors} error(es), ${warn} warning(s))"
  exit 1
fi
