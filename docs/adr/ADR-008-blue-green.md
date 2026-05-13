# ADR-008 — Blue/Green durante transición; BLUE intocable

**Estado:** Vigente (NUEVO v2)
**Fecha:** 2026-05-12

## Contexto

BLUE (`mcp.ovnisystem.com`) está sirviendo a Willy en producción. Cualquier modificación in-place tiene riesgo de regresión sin rollback inmediato. La validación del multiactor requiere coexistencia con BLUE.

## Decisión

Despliegue Blue/Green:

- **BLUE intocable** hasta validación completa de GREEN con los 3 actores. Mismo contenedor `odoo-mcp`, mismo dominio, mismo proceso.
- **GREEN nuevo** en contenedor `odoo-mcp-v2`, subdominio `mcp-v2.ovnisystem.com`, mismo Traefik/Let's Encrypt.
- Ambos coexisten durante toda la fase de transición.
- La migración del conector productivo de Willy de BLUE a GREEN es **sub-ticket separado post-QA**, no parte de v2.

## Consecuencias

- Rollback de GREEN = `docker stop && docker rm` (BLUE intacto, conectores siguen apuntando ahí).
- Costo: dos contenedores corriendo durante la transición.
- Cero downtime para Willy durante todo el desarrollo.

## Alternativas descartadas

- In-place upgrade de BLUE: rollback complicado, riesgo alto sobre prod activo.
- Migración directa de BLUE a multiactor sin GREEN: misma objeción.
