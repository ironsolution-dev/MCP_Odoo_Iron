# ADR-016 — Titulo APL 2.0 nuevo: regla estructural, no lista cerrada de verbos

**Estado:** Vigente (ticket 737, 27-ago-2026)

## Contexto

La guia APL 2.0 V2 v1.1 (sec 7 de la tabla de cambios) retira el formato de
titulo con corchetes `[APL 2.0][Px][Area][Tipo] resto` que el conector MCP
venia generando: la metadata va en etiquetas, no en el titulo. El nuevo
estandar humano es "verbo en infinitivo + que se entrega + contexto", sin
prefijos ni codigos (guia sec 3).

Decision del PM (Infinity, anotada en el ticket 737): compatibilidad
gradual. Se acepta titulo viejo CON corchetes y titulo nuevo SIN corchetes;
se normaliza el que llega y se avisa cuando aplica. No se rompe lo que ya
escribian personas o LLMs con el formato anterior.

Falta decidir como se valida el titulo NUEVO. Dos opciones:

1. Lista cerrada de verbos permitidos (Elaborar, Emitir, Revisar, Definir...
   segun la tabla de la guia sec 3).
2. Regla estructural: no vacio, no empieza con `[`, sin saltos de linea,
   longitud razonable (~140 caracteres).

## Decision

Regla **estructural** (opcion 2), implementada en `app/apl_title.py`
(`normalize_apl_title`). El backend valida ESTRUCTURA — no interpreta si
"Revisar contrato" es semanticamente mejor verbo que "Contrato revisado" o
"Tema contrato". La calidad del verbo (tabla de la guia sec 3: "Mal" vs
"Bien") queda a criterio del LLM/humano que redacta el ticket, no del
validador server-side.

Formato reconocido:

- **Legado**: `^\[APL\s*2\.0\]\[P[0-3]\]\[[^\]]+\]\[[^\]]+\]\s+\S.*$`
  (case-insensitive). Se extraen Px/Area/Tipo, se limpia el titulo
  (corchetes retirados), se marca `is_legacy=True` y se agrega un warning
  no bloqueante ("formato antiguo normalizado").
- **Nuevo**: cualquier texto que NO empiece con `[`, no vacio, sin `\n`/`\r`,
  `<= 140` caracteres. Se acepta tal cual, sin metadata legado.
- Un texto que empieza con `[` pero NO matchea el patron legado completo se
  **rechaza** (`ValidationError`): se asume formato legado mal formado, no
  un titulo nuevo valido con corchete suelto. Evita que un legado roto pase
  silenciosamente como si fuera texto libre.

Si el titulo legado trae Px/Area/Tipo que difieren de los campos del
payload (`priority`/`area`/`task_type`), manda el titulo y se agrega un
warning de conflicto por cada campo distinto (decision del PM anotada en el
ticket).

## Riesgo aceptado

Sin lista cerrada de verbos, un titulo estructuralmente valido puede seguir
siendo de baja calidad ("Tema banco", "Cosa por hacer"). El backend no
bloquea eso: la guia (DoR sec 9) y la revision humana/de Infinity son la
capa de calidad, no el validador. Se documenta como riesgo aceptado, no
como bug pendiente.

## Consecuencias

- `app/apl_title.py` es la unica fuente de verdad para reconocer/normalizar
  titulo APL 2.0; reemplaza el `APL_TITLE_PATTERN`/`validate_apl_title`
  anteriores en `app/schemas.py` (que solo aceptaban el formato legado y
  rechazaban cualquier titulo nuevo sin corchetes — contrato roto por la
  guia v1.1).
- `app/tools/openai_nl_parser.py` deja de envolver los titulos que genera
  en corchetes `[APL 2.0][Px][Area][Tipo]`: genera texto libre directamente
  (`_build_apl_title`).
- Ningun punto de entrada (system prompt, help de escritura, docstrings de
  tools) instruye al modelo a usar el formato con corchetes como el
  esperado; el legado sigue aceptandose por compatibilidad, no se promueve.

## Alternativas descartadas

- Lista cerrada de verbos: mas estricta, pero exige mantener y traducir una
  taxonomia de verbos en el backend que ya vive en la guia (sec 3) como
  sugerencia, no como contrato; duplicaria fuente de verdad.
- Rechazar el formato legado de inmediato: rompe compatibilidad con
  clientes/LLMs que aun generan el titulo viejo sin previo aviso — va contra
  la decision explicita del PM de compatibilidad gradual.
