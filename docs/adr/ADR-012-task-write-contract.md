# ADR-012 — Contrato de escritura de tareas: alias + validacion agregada

**Estado:** Vigente (Fase A daily driver, sec G2)
**Fecha:** 2026-08-18

## Contexto

`odoo_update_task_apl` validaba los campos permitidos con un `set` plano (`TASK_WRITABLE_FIELDS_BASIC`) y fallaba-rapido en el primer problema, sin validar tipos/formato de los valores. Dos gaps concretos:

1. Los LLMs que arman el payload usan indistintamente `deadline` (lenguaje natural) y `date_deadline` (campo real de Odoo); sin alias, la mitad de los intentos fallan por nombre de campo.
2. Fallar en el primer problema obliga a N round-trips para corregir N errores — costoso en latencia y en tokens del LLM que reintenta a ciegas.

Ademas, `project_id` **nunca** debe entrar por este update generico: reasignar proyecto necesita verificar visibilidad del proyecto destino y dejar rastro en el chatter (sec G1, `odoo_move_task_to_project`) — mezclarlo con un `write` generico se salta esa auditoria.

## Decision

Fuente unica en `app/schemas.py`:

- `TASK_FIELD_ALIASES = {"deadline": "date_deadline"}`.
- `TASK_FIELD_SPECS`: un `TaskFieldSpec(kind=...)` por campo escribible (`str`, `priority_code`, `iso_date`, `int`, `list_int`), con `project_id` marcado `kind="blocked"` y un `blocked_message` que apunta explicitamente a `odoo_move_task_to_project`.
- `validate_task_write_payload(changes) -> dict`: normaliza el alias, rechaza que `deadline` y `date_deadline` lleguen juntos (ambiguo), valida cada campo contra su spec, y junta **todos** los problemas encontrados en un solo `ValidationError` en vez de fallar-rapido.

`odoo_update_task_apl` (sec `app/tools/tasks.py`) pasa a llamar esta funcion antes del chequeo de policy. Se retira `TASK_WRITABLE_FIELDS_BASIC`: mantenerlo junto a `TASK_FIELD_SPECS` habria sido dos fuentes de verdad para la misma pregunta ("que campos son escribibles").

## Consecuencias

- Un LLM que manda `{"deadline": "...", "priority": "9", "stage_id": "x"}` recibe un unico error con los tres problemas listados, no tres intentos fallidos consecutivos.
- `project_id` queda bloqueado con un mensaje accionable, no un `KeyError`/`fields_not_writable` generico.
- Cualquier tool nueva que necesite escribir `project.task` reutiliza el mismo contrato en vez de inventar su propio set de campos permitidos.

## Alternativas descartadas

- Seguir fallando-rapido: mas simple pero peor UX para el LLM (multiples round-trips).
- Permitir `project_id` en el update generico con un chequeo de visibilidad inline: duplica logica que ya vive en `odoo_move_task_to_project` y pierde el registro en el chatter.
