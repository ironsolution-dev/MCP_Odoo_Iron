# Runbook operativo — MCP Odoo v2 GREEN

> Para Willy. Comandos copy-paste, evidencias esperadas y rollback.

---

## 0. Snapshot BLUE (antes de cualquier cambio)

```bash
ssh root@82.25.90.203
cd /opt/odoo-mcp-v2 || mkdir -p /opt/odoo-mcp-v2 && cd /opt/odoo-mcp-v2
bash <path_repo>/scripts/snapshot_blue.sh
```

Esperado: directorio `/opt/odoo-mcp-v2/backups/<TS>/` con `docker_inspect_blue.json`, `docker_logs_blue.txt`, `app/`, `blue.tar`, `blue_health.txt`.

---

## 1. Provisionar subdominio GREEN

### 1.1 DNS

Crear registro A:

```
mcp-v2.ovnisystem.com.  A  82.25.90.203
```

Verificar resolución:

```bash
dig +short mcp-v2.ovnisystem.com
# Debe retornar 82.25.90.203
```

### 1.2 Container hello-world temporal para emitir cert

```bash
docker run -d \
  --name odoo-mcp-v2-hello \
  --network proxy \
  --label "traefik.enable=true" \
  --label "traefik.http.routers.odoomcpv2hello.entrypoints=websecure" \
  --label "traefik.http.routers.odoomcpv2hello.rule=Host(\`mcp-v2.ovnisystem.com\`)" \
  --label "traefik.http.routers.odoomcpv2hello.tls=true" \
  --label "traefik.http.routers.odoomcpv2hello.tls.certresolver=letsencrypt" \
  --label "traefik.http.services.odoomcpv2hello.loadbalancer.server.port=80" \
  nginx:alpine
```

Esperar ~30s para que Let's Encrypt emita y validar:

```bash
curl -I https://mcp-v2.ovnisystem.com
# Esperado: HTTP/2 200, header strict-transport-security, cert valido
```

Si funciona, **detener y borrar el hello-world** (deja DNS y cert listos):

```bash
docker stop odoo-mcp-v2-hello && docker rm odoo-mcp-v2-hello
```

---

## 2. Provisionar actores (token MCP + API key Odoo)

Para cada actor (Willy/Yuniesky/Anet):

### 2.1 Crear API key Odoo

Login del actor en Odoo → Preferencias → Cuenta → Seguridad → Nueva API Key. Guardar **una vez** en gestor seguro.

### 2.2 Generar token MCP

En cualquier máquina:

```bash
python scripts/generate_mcp_token.py --actor willy
# Output:
#   Actor: willy
#   MCP_TOKEN (copy ONCE, never log): mcp_XXXXX
#   token_hash (paste in actors.yaml): sha256:YYYYY
```

Guardar `MCP_TOKEN` en gestor seguro del actor (será el valor del Bearer en su conector).
Pegar `token_hash` en `/opt/odoo-mcp-v2/secrets/actors.yaml` campo `actors.<actor>.token_hash`.

Repetir 3 veces (willy, yuniesky, anet).

### 2.3 Componer secrets en VPS

```bash
sudo mkdir -p /opt/odoo-mcp-v2/secrets
sudo cp config/actors.yaml.example /opt/odoo-mcp-v2/secrets/actors.yaml
sudo cp config/policies.yaml.example /opt/odoo-mcp-v2/secrets/policies.yaml
sudo chown root:docker /opt/odoo-mcp-v2/secrets/*.yaml
sudo chmod 0640 /opt/odoo-mcp-v2/secrets/*.yaml

# Editar actors.yaml y reemplazar los 3 token_hash con los reales del paso 2.2
sudo nano /opt/odoo-mcp-v2/secrets/actors.yaml
```

### 2.4 `.env.v2` del contenedor

```bash
sudo nano /opt/odoo-mcp-v2/secrets/.env.v2
```

Contenido:

```
ODOO_URL=https://odoo.ironsolution.us/
ODOO_DB=odoo_db
ODOO_USERNAME_WILLY=<login_willy>
ODOO_API_KEY_WILLY=<api_key_willy>
ODOO_USERNAME_YUNIESKY=<login_yuniesky>
ODOO_API_KEY_YUNIESKY=<api_key_yuniesky>
ODOO_USERNAME_ANET=<login_anet>
ODOO_API_KEY_ANET=<api_key_anet>
```

Permisos: `chmod 0640`, owner root, group docker.

---

## 3. Deploy GREEN

```bash
cd /opt/odoo-mcp-v2/repo  # o donde clonaste el repo v2
bash scripts/deploy_green.sh
```

Esperado: contenedor `odoo-mcp-v2` corriendo, `curl https://mcp-v2.ovnisystem.com/mcp` responde con `tools/list`.

---

## 4. Smoke test (lo ejecuta Willy desde su máquina)

```bash
export MCP_TOKEN_WILLY="mcp_..."
export MCP_TOKEN_YUNIESKY="mcp_..."
export MCP_TOKEN_ANET="mcp_..."
python scripts/smoke_test_mcp.py
# Esperado: ALL OK
```

---

## 5. Healthcheck rutinario

```bash
curl -s https://mcp-v2.ovnisystem.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer ${MCP_TOKEN_WILLY}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"odoo_health","arguments":{}}}'

# Validar audit log
tail -n 5 /opt/odoo-mcp-v2/logs/audit.jsonl

# Validar no hay leak de secretos
tail -n 100 /opt/odoo-mcp-v2/logs/audit.jsonl | grep -E "(Bearer|api_key|MCP_TOKEN)" && echo LEAK || echo CLEAN
```

---

## 6. Rollback GREEN

```bash
docker stop odoo-mcp-v2
docker rm odoo-mcp-v2
# BLUE intacto. Los conectores productivos siguen apuntando a mcp.ovnisystem.com.
```

## 7. Rollback BLUE (improbable; solo si por error se modificó)

```bash
bash scripts/rollback_blue.sh
```

Restaura desde último snapshot en `/opt/odoo-mcp-v2/backups/`.

---

## 7.1 Rollback de código (ticket 807 — auth GET/POST unificada + CORS + discovery)

Si el cambio del ticket 807 (unificación de auth GET/POST, discovery GET,
`WWW-Authenticate`, CORS, `client_type`/`user_agent` en el audit) causa un
problema en GREEN, el rollback es de código, no de datos: volver al sha/tag
anterior (`main` antes de la rama `julio/807-mcp-agnostico`, o el tag
`multiuser-v0.4.5` si ya se re-taggeó y desplegó tras este ticket) y
redesplegar GREEN con `scripts/deploy_green.sh` apuntando a ese ref.

Antes de redesplegar, **probar en local** que el sha/tag anterior arranca y
responde igual que antes — no asumirlo:

```bash
python scripts/rollback_check_local.py main      # o el tag: multiuser-v0.4.5
```

Crea un `git worktree` aparte en ese ref, levanta el servidor MCP ahí con
actores/policies de prueba (nunca Odoo real), hace `POST /mcp/<token>
tools/list` (espera 200 + N tools) y `POST /mcp/<token-inválido>` (espera
401), y borra el worktree al terminar. No toca el árbol de trabajo actual
ni VPS82. Probado el 31-ago-2026 contra `main` (sha `d5a798b`): `200` con
49 tools y `401` — ver `EVIDENCIA-807.md`.

Si el smoke test pasa, seguir con el rollback real de GREEN (contenedor):
igual que la sección 6, pero re-buildeando la imagen desde el sha/tag
anterior antes de `docker run`.

---

## 8. Rotación de token MCP

1. Generar nuevo token: `python scripts/generate_mcp_token.py --actor <actor>`.
2. Reemplazar `token_hash` en `/opt/odoo-mcp-v2/secrets/actors.yaml`.
3. Entregar nuevo `MCP_TOKEN` al actor por canal seguro.
4. Re-restart no es estrictamente necesario si el registry se recarga; reiniciar contenedor por seguridad.
5. Auditar accesos previos en `audit.jsonl` por si hubo uso del token comprometido.

---

## 9. Troubleshooting rápido

| Síntoma | Diagnóstico | Acción |
|---|---|---|
| `401 invalid_token` en GREEN | Hash en `actors.yaml` no coincide con `MCP_TOKEN` enviado | Regenerar y actualizar |
| `403 tool_not_allowed` | Tool no incluida en `policy.allowed_tools` del rol | Revisar `policies.yaml` |
| `403 action_not_allowed:project.project:create` | Policy del rol no permite crear proyectos | Esperado para `operations`/`medical_direction` |
| `AccessError` de Odoo | ACL de Odoo deniega antes de llegar a policy MCP | Revisar permisos del user Odoo del actor |
| Cert SSL no emite | DNS no propagado o labels Traefik mal | Ver paso 1 |
| Audit log no escribe | Permisos `/opt/odoo-mcp-v2/logs/` o volumen no montado | `ls -la` y revisar `docker inspect` |
