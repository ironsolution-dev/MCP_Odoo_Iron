# ADR-017 — El mapa de etiquetas APL 2.0 vive en la imagen versionada

**Estado:** Vigente (ticket 737, 27-ago-2026)

## Contexto

Ningun tool del conector escribia `tag_ids` al crear una tarea: las 3
etiquetas canonicas (Prioridad, Departamento, Tipo) que exige la guia APL
2.0 V2 v1.1 (sec 4) no se asignaban nunca. Ademas, los IDs reales de esas
etiquetas viven en `project.tags` de Odoo (27 etiquetas totales el
27-ago-2026, 8 de ellas ruido) y pueden cambiar si alguien las edita en el
admin de Odoo.

Se necesita una fuente unica de esos IDs, consumida por
`app/schemas.py`/`app/apl_labels.py` en cada creacion de tarea, con dos
requisitos duros:

1. El MCP **asigna** etiquetas existentes, **nunca las crea** (evita que un
   payload con `area="Marketing Digital"` genere una etiqueta nueva de
   ruido en Odoo).
2. El mapeo debe poder auditarse y versionarse: no es aceptable un valor
   hardcodeado en 3 sitios distintos del codigo (justo el patron
   anti-Frankenstack que rompio la voz de Infinity el 25-jul-2026).

Dos opciones de donde vive el mapeo:

1. Volumen montado en el VPS (como `secrets/actors.yaml`,
   `secrets/policies.yaml`): editable en caliente, fuera de git.
2. Fichero versionado en el repo (`config/apl_labels.yaml`), horneado en la
   imagen Docker.

## Decision

**Opcion 2**: `config/apl_labels.yaml` vive en el repo, se copia a la
imagen (`Dockerfile COPY config/ ./config/`) y se carga UNA VEZ al importar
`app/apl_labels.py` (import time, antes de que arranque uvicorn). No es un
secreto: son IDs numericos de etiquetas de un modulo de proyectos interno,
sin credenciales ni PII. `APL_LABELS_PATH` (variable de entorno opcional)
permite apuntar a otro fichero solo para tests/desarrollo local — en
produccion no se define, se usa el default horneado.

Cambiar un ID (porque alguien lo edito en Odoo, o porque se agrega una
etiqueta canonica nueva) es: editar `config/apl_labels.yaml` → commit →
`scripts/deploy_green.sh` (rebuild + redeploy). Nunca una edicion en
caliente del contenedor corriendo — misma disciplina que el resto del
codigo versionado (ver "Contrato de construccion — anti-Frankenstack",
regla 1: "en git, o no existe").

**Pre-flight obligatorio:** antes de cada mezcla a `main` que toque este
fichero, releer los IDs en vivo contra Odoo (`project.tags.search_read`,
solo lectura) y confirmar que coinciden. Verificado el 27-ago-2026 (UID 29):
los 19 IDs de `config/apl_labels.yaml` (4 prioridad + 8 departamento + 7
tipo) coinciden exactamente con lo leido en produccion.

**Re-verificado 27-ago-2026 12:59 -05 (ronda 2, ticket 737, hallazgo F5 de
julio-qa):** `project.tags.search_read` en vivo via XML-RPC solo lectura
(uid 9, credenciales de Willy resueltas en memoria dentro del contenedor
`odoo-mcp-v2`, nunca impresas). 27 etiquetas totales en Odoo (8 de ruido:
V1/V2/V3/V/alta/"sorpote ti"/"incidencia de acceeso"/analisis), igual que
en el pre-flight anterior. Los 19 IDs canonicos siguen exactos:
prioridad P0=1/P1=2/P2=3/P3=4; departamento Comercial=5/
Contabilidad-Finanzas=6/Marketing=7/Staff Profesionales Salud=8/
Tecnologia=9/RR.HH=10/Operaciones=14/Gerencia=20; tipo Recurrente=11/
Entregable=12/Proyecto=13/Handover=15/Decision=16/Documentacion=25/
Gestion=27. Sin drift.

## Consecuencias

- `app/apl_labels.py` (`resolve_priority`, `resolve_department`,
  `resolve_task_type`) es la UNICA funcion que traduce prioridad/area/tipo
  a `tag_id`. Ningun tool ni prompt hardcodea un ID de etiqueta fuera de
  este modulo y su config.
- Si `area`/`task_type` no matchea ningun nombre canonico ni sinonimo
  conocido (normalizado sin acentos/mayusculas), se devuelve `tag_id=None`
  + warning legible. La tarea se crea igual, sin esa etiqueta — nunca se
  llama `project.tags.create`.
- Un cambio de ID requiere rebuild+deploy, no es instantaneo. Aceptado:
  las etiquetas canonicas no cambian con frecuencia (la guia v1.1 ya fijo
  la lista final el 27-ago-2026); el pre-flight en vivo es la salvaguarda
  contra que el fichero quede desactualizado silenciosamente.

## Alternativas descartadas

- Volumen de secretos (opcion 1): monta complejidad de gestion de secretos
  (permisos, rotacion, `.creds` 600) sobre un dato que no es secreto;
  ademas permite editar el mapeo sin pasar por git, perdiendo trazabilidad
  de quien cambio que ID y cuando.
- Consultar `project.tags` en vivo en cada creacion de tarea (sin cache):
  descartado por latencia (una llamada XML-RPC extra por creacion) y porque
  no resuelve el problema real (segue faltando el paso "asignar, no crear"
  y la normalizacion de sinonimos); el pre-flight manual en vivo ya cubre
  el riesgo de desincronizacion sin pagar ese costo en cada request.
