# ADR-009 — `res.partner` read-only con allowlist (sin VAT/financieros)

**Estado:** Vigente (NUEVO v2)
**Fecha:** 2026-05-12

## Contexto

Los actores necesitan consultar contactos para tareas y CRM, pero `res.partner` contiene campos sensibles: `vat` (identificación fiscal), `bank_ids`, `credit`, `debit`, `total_invoiced`, `street`, `street2`, `zip`, `comment`, `ref`, `property_*`. Exponerlos al LLM por defecto sería filtrar datos fiscales y de direcciones particulares.

## Decisión

Fase 1: `res.partner` es **read-only** con allowlist estricta de campos seguros (sec 8.4 Task Packet):

```
id, name, display_name, email, phone, mobile, is_company, parent_id,
function, city, country_id, category_id, user_id, active,
customer_rank, supplier_rank
```

Cualquier campo no listado se filtra antes de retornar al LLM.

Tools: `odoo_list_partners`, `odoo_get_partner`, `odoo_search_partner`. Search no admite filtros por `vat` / `ref`.

## Consecuencias

- El LLM nunca recibe direcciones completas, identificación fiscal, bancos ni saldos.
- Escritura/edición de contactos queda fuera de alcance fase 1 (se hace en Odoo directo).
- Caso de uso de CRM ("crear partner desde llamada") queda para fase futura.

## Alternativas descartadas

- Exponer `res.partner` completo: viola política de mínimo privilegio.
- No exponer `res.partner`: bloquea casos legítimos de búsqueda y referencias en tareas.
