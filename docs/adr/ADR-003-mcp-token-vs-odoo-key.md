# ADR-003 — MCP token separado de Odoo API Key

**Estado:** Vigente
**Fecha:** 2026-05-12

## Contexto

El conector LLM debe identificarse al MCP, y el MCP debe autenticarse a Odoo. Si el LLM viera la Odoo API Key, una fuga del prompt comprometería Odoo directamente.

## Decisión

Dos identidades disjuntas:

- **MCP token:** vive en el conector y se envía como `Authorization: Bearer` (o ruta opaca fallback). Identifica al actor MCP. Se almacena como hash sha256 en `actors.yaml`.
- **Odoo API Key:** vive como variable de entorno del contenedor (`ODOO_API_KEY_<ACTOR>`). Nunca sale del proceso; nunca aparece en logs ni en respuestas a tools.

## Consecuencias

- Fuga del MCP token: rotación en `actors.yaml` sin tocar Odoo.
- Fuga de Odoo API Key: rotación en Odoo + redeploy GREEN. El conector LLM no se ve afectado.
- Auditoría registra actor (no token).

## Alternativas descartadas

- Usar la Odoo API Key como token MCP: dos canales para la misma credencial = doble superficie de fuga.
