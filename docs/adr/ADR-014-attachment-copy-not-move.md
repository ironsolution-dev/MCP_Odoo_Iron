# ADR-014 — Adjuntos de Discuss: copiar, nunca mover; origen verificado server-side

**Estado:** Vigente (Fase A daily driver, sec G4)
**Fecha:** 2026-08-18

## Contexto

`odoo_attach_discuss_attachment_to_task` permite llevar un adjunto que alguien compartio en un canal de Discuss hacia una tarea. Dos riesgos si se implementa ingenuo:

1. **Mover** el adjunto (reasignar `res_model`/`res_id` del original) rompe el historial del canal: el mensaje original queda con un link roto y cualquier otro lector del canal pierde el archivo.
2. **Confiar en el `channel_id` que manda el cliente** sin cruzarlo contra Odoo permite un ataque trivial: pedir un `attachment_id` que en realidad vive en OTRO canal (uno no allowlisted) pasando un `channel_id` allowlisted, para exfiltrar un adjunto ajeno.

Ademas, copiar el binario completo (`datas`) de un adjunto arbitrario sin limite de tamano puede saturar el proceso o el contexto en escenarios de error.

## Decision

`odoo_attach_discuss_attachment_to_task` (sec `app/tools/discuss.py`) sigue un orden estricto donde cada paso corta el flujo si falla:

1. **Pertenencia verificada server-side**: se busca un `mail.message` con `model=discuss.channel`, `res_id=<channel_id>` (ya validado contra la allowlist, ADR-013) que tenga `attachment_id` en `attachment_ids`. Si no existe ese cruce, se deniega aunque el `attachment_id` sea real en Odoo.
2. **Tamano ANTES que binario**: se leen metadatos (`file_size` incluido) y se compara contra `PolicyEngine.attachment_max_bytes(policy)` (default 10 MB, `DEFAULT_ATTACHMENT_MAX_BYTES`) **antes** de pedir el campo `datas`. Un adjunto demasiado grande nunca llega a generar el round-trip del binario.
3. **Tarea destino visible** para el actor.
4. Solo entonces se lee `datas` y se hace `create` de un `ir.attachment` **nuevo** con `res_model='project.task'`, `res_id=<task_id>`. El adjunto y el mensaje origen no se tocan: nunca hay `write` ni `unlink` sobre el original.

## Consecuencias

- El historial del canal de Discuss queda siempre intacto, sin importar cuantas tareas terminen con una copia del mismo archivo.
- Un intento de exfiltrar un adjunto de un canal no allowlisted disfrazandolo con un `channel_id` allowlisted falla en el paso 1, con `attachment_not_in_channel:<id>:<channel_id>`.
- El limite de tamano es configurable por policy (`discuss_attachment_max_bytes`), no hardcodeado — pero tiene un default conservador si una policy lo omite.

## Alternativas descartadas

- Mover el adjunto (reasignar `res_id`): mas simple pero destruye el historial del canal, inaceptable.
- Confiar en el `channel_id` del cliente sin verificar la pertenencia real: vector de exfiltracion cross-canal.
- Validar tamano leyendo el binario primero y descartandolo si excede el limite: desperdicia ancho de banda/latencia en el caso que se va a rechazar de todas formas.
