# Spike Bearer auth — Claude.ai + ChatGPT connectors

> Fase 0, obligatorio. Determina si los conectores envían `Authorization: Bearer <token>` o requieren fallback con ruta opaca.

## Procedimiento

Crear un contenedor "echo" temporal en el VPS que imprima los headers de cada request entrante, exponerlo en `mcp-v2.ovnisystem.com` con Traefik y configurar un conector personalizado en Claude.ai apuntando a él. Repetir con ChatGPT.

### Echo server mínimo (Python)

```python
# scripts/echo_headers.py — solo para spike, no commitear con secretos
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else ""
        # IMPORTANTE: redactar el value del header Authorization antes de mostrar
        headers = {}
        for k, v in self.headers.items():
            if k.lower() == "authorization":
                headers[k] = v[:12] + "..." + v[-4:] if len(v) > 16 else "REDACTED"
            else:
                headers[k] = v
        print(json.dumps({"path": self.path, "headers": headers, "body_preview": body[:200]}, indent=2))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')


HTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
```

## Resultados

### Claude.ai custom connector — VALIDADO 12 may 2026

- **Envía `Authorization: Bearer`?** NO. La UI del conector personalizado (BETA) solo tiene campo URL + OAuth. No hay campo para Bearer token.
- **Mecanismo de auth utilizado:** Token en path opaco — `https://mcp-v2.ovnisystem.com/mcp/<token>`
- **UI:** Settings → Integrations → Add custom integration → campo "URL del servidor MCP remoto"
- **Token en path:** El servidor reescribe `/mcp/<token>` → `/mcp` en el scope ASGI antes de FastMCP (BearerMiddleware ASGI puro).
- **Tools descubiertas:** 30 ✅
- **QA `odoo_who_am_i`:** actor=willy, uid=9, role=owner, policy=owner_policy ✅
- **Fecha validación:** 12 mayo 2026

### ChatGPT custom connector — VALIDADO 12 may 2026

- **Envía `Authorization: Bearer`?** NO en modo API Key. Envía `X-Api-Key: <token>`.
- **Modo de auth configurado:** API Key (en la UI de configuración del GPT → Actions → Authentication → API Key)
- **Header enviado:** `X-Api-Key: <mcp_token>`
- **GET /mcp sin Accept: text/event-stream:** retornaba 406 de FastMCP → corregido con intercepción en middleware que retorna 200 JSON discovery.
- **Status:** Fix implementado en commit `d0a2bfb`. Pendiente validación QA manual completa con token de Yuniesky/Anet.

## Decisión

✅ **Fallback ruta opaca para Claude.ai + X-Api-Key para ChatGPT** — un solo contenedor sirve ambos modos:

- Claude.ai → URL con token en path → middleware extrae token, reescribe path a `/mcp`
- ChatGPT → `X-Api-Key: <token>` header → middleware extrae de header, path permanece `/mcp`
- Bearer header también soportado (modo preferido si algún cliente lo habilita en el futuro)

Un solo contenedor `odoo-mcp-v2`, sin clones por conector. ADR-002 y ADR-007 vigentes.

## Notas operativas

- El segmento de fallback nunca contiene la Odoo API Key.
- Independientemente del modo: el server redacta `Authorization` y el segmento de ruta antes de loguear.
- Mapeo a `token_registry` es idéntico: ambos modos resuelven al mismo hash.
