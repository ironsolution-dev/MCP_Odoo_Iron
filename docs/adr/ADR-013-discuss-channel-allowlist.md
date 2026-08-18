# ADR-013 — Allowlist de canales de Discuss por policy, en config

**Estado:** Vigente (Fase A daily driver, sec G4)
**Fecha:** 2026-08-18

## Contexto

Discuss no es un modelo propio de Odoo: los mensajes de un canal viven en `mail.message` con `model='discuss.channel'` y `res_id=<channel_id>`. El policy engine ya filtra por modelo/accion/campos (ADR-004), pero eso no alcanza para Discuss: `mail.message` es un modelo compartido por CRM (`odoo_add_crm_note`), tareas y canales — permitir `read`/`create` sobre `mail.message` no dice nada sobre **cual canal** especifico deberia ser visible. Sin un chequeo adicional, cualquier actor con acceso a `mail.message` podria leer o postear en canales que no le corresponden (ej. un canal de Contabilidad).

## Decision

`PolicyEngine.discuss_channel_allowed(policy_name, channel_id) -> PolicyDecision`: cada policy declara opcionalmente `discuss_channel_allowlist: [ids]` en `config/policies.yaml`. **Ausencia de la clave (o lista vacia) = deny para todos los canales**, sin excepcion implicita para ningun rol — deny-by-default, igual que el resto del policy engine.

Las 3 tools de `app/tools/discuss.py` hacen un **doble chequeo**: `policy.allows(modelo, accion)` (igual que cualquier otra tool) **y** `policy.discuss_channel_allowed(policy, channel_id)` antes de tocar Odoo.

En Fase A, `config/policies.yaml.example` solo declara `discuss_channel_allowlist: [53]` en `owner_policy` (Willy). `operations_policy` y `medical_direction_policy` no declaran la clave: quedan denegadas por defecto para Discuss completo, sin necesidad de un flag `deny: true` explicito.

## Consecuencias

- Agregar un canal nuevo es un cambio de config (`config/policies.yaml`), no de codigo.
- Un actor cuya policy no declara ningun canal recibe `discuss_channel_not_allowed:<id>` de forma identica sin importar si el canal existe en Odoo — no se filtra informacion sobre canales ajenos por la forma del error.
- `PermissionError` de esta capa queda visible en `audit.jsonl` con el mismo mecanismo que cualquier otro `denied_reason` (sec ADR-006).

## Alternativas descartadas

- Un unico flag global `discuss_enabled: true/false` por policy sin lista de canales: mas simple pero no permite dar acceso a UN canal sin exponer todos los que existan en Odoo.
- Validar el canal contra las membresias reales del usuario en Odoo (`discuss.channel.member`) en vez de una allowlist en config: mas fiel al modelo de Odoo pero depende de que las membresias esten bien mantenidas alla; en Fase A se prefiere una fuente explicita y auditable en el propio MCP.
