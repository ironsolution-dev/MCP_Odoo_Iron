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

### Claude.ai custom connector

- ¿Envía header `Authorization: Bearer <token>`?
  TODO_WILLY: sí / no
- ¿Permite configurar el valor del token en la UI del conector?
  TODO_WILLY: sí / no — describir dónde
- ¿Lo modifica antes de enviarlo (prefijos, mayúsculas)?
  TODO_WILLY: pegar header recibido (redactado)
- ¿Funciona con ruta `/mcp` directa?
  TODO_WILLY: sí / no

### ChatGPT custom connector ("Odoo APL 2.0")

- ¿Envía header `Authorization: Bearer <token>`?
  TODO_WILLY: sí / no
- ¿Permite configurar el valor del token?
  TODO_WILLY: sí / no
- ¿Lo modifica?
  TODO_WILLY: pegar header recibido (redactado)
- ¿Funciona con ruta `/mcp`?
  TODO_WILLY: sí / no

## Decisión

Según resultados, marcar UNA opción:

- [ ] **Bearer puro en ambos** → producción usa solo `Authorization: Bearer`.
- [ ] **Bearer en uno + fallback ruta opaca en otro** → mismo contenedor sirve ambos modos; indicar cuál usa fallback.
- [ ] **Fallback ruta opaca en ambos** → URL `https://mcp-v2.ovnisystem.com/mcp/<opaque_token>`. El segmento es opaco (NO el actor name); el servidor lo redacta de logs.

## Notas operativas

- El segmento de fallback nunca contiene la Odoo API Key.
- Independientemente del modo: el server redacta `Authorization` y el segmento de ruta antes de loguear.
- Mapeo a `token_registry` es idéntico: ambos modos resuelven al mismo hash.
