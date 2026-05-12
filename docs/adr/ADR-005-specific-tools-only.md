# ADR-005 — Escritura solo con tools específicas + read-after-write

**Estado:** Vigente
**Fecha:** 2026-05-12

## Contexto

Una tool genérica tipo `execute_kw(model, method, args, kwargs)` daría al LLM acceso raw al ORM de Odoo. Cualquier prompt injection podría llamar `account.move.create` o `res.users.write`.

## Decisión

- No se expone ninguna tool genérica: prohibido `execute_kw`, `execute`, `raw_call`, `admin_*`, `sudo_*`.
- Cada operación de escritura es una tool específica con validación de input, policy check y read-after-write.
- Read-after-write: tras `create` / `write`, releer el registro afectado y devolver el estado real desde Odoo (no asumir éxito).

## Consecuencias

- Añadir una nueva operación requiere una tool nueva + entrada en policy. No hay atajos.
- El LLM no puede confabular "lo creé exitosamente"; recibe el record real.
- Superficie de ataque acotada a las ~30 tools del catálogo.

## Alternativas descartadas

- Una tool `execute_kw` con filtros: cualquier whitelist se vuelve frágil y propensa a bypass.
