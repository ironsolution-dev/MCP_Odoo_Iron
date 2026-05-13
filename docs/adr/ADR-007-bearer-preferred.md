# ADR-007 — Bearer header preferido + fallback ruta opaca

**Estado:** Vigente
**Fecha:** 2026-05-12

## Contexto

Los conectores personalizados de Claude.ai y ChatGPT envían (idealmente) `Authorization: Bearer <token>`. Spike Fase 0 valida si ambos lo hacen tal cual; si alguno no lo soporta, se necesita un fallback.

## Decisión

- **Modo preferido:** `Authorization: Bearer <MCP_TOKEN>` enviado al path `https://mcp-v2.ovnisystem.com/mcp`.
- **Fallback:** segmento opaco en path `https://mcp-v2.ovnisystem.com/mcp/<opaque_token>`. Reglas del fallback:
  - El segmento es opaco — no es el actor name ni la API key.
  - El servidor redacta el segmento antes de loguear.
  - Resuelve al mismo `token_registry` por hash.
  - El mismo contenedor sirve ambos modos; no se clonan procesos.

## Consecuencias

- Compatibilidad simultánea Claude.ai + ChatGPT, independiente de qué soporte cada uno.
- Auditoría es consistente (mismo flujo de redacción y mapeo).
- Si un conector cambia comportamiento, basta editar config sin tocar servidor.

## Alternativas descartadas

- Solo Bearer: bloquea uno de los dos conectores si no lo soporta.
- Solo ruta opaca: degrada UX de configuración en conectores que sí soportan Bearer.
