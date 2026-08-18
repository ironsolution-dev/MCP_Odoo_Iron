"""Salvaguarda de asignacion: valida `user_ids` contra hr.employee activo
antes de escribir project.task (sec G3, Fase A daily driver).

Extraido de tasks.py (split mecanico) para mantener tasks.py <=300 lineas
tras sumar G1+G2+G3 sobre el mismo modulo. Sin logica nueva respecto a la
version original inline.
"""

from __future__ import annotations

from app.odoo_client import OdooClient
from app.schemas import ValidationError
from app.token_registry import ActorEntry


async def _validate_assignable_user_ids(odoo: OdooClient, actor: ActorEntry,
                                        uids: list[int]) -> list:
    """Verifica que CADA uid en `uids` mapea a un hr.employee activo antes de
    permitir asignar la tarea. Cero escritura si algun uid es invalido — el
    ValidationError lista TODOS los invalidos de una vez, no solo el primero.

    El policy check de la tool que llama sigue siendo project.task/write;
    esto es una salvaguarda adicional de integridad de datos, NUNCA una
    consulta o escritura contra res.users.
    """
    if not uids:
        return [(6, 0, [])]
    employees = await odoo.search_read(
        actor, "hr.employee", [("user_id", "in", uids), ("active", "=", True)],
        ["id", "user_id"], limit=len(uids) + 1,
    )
    assignable: set = set()
    for emp in employees:
        user = emp.get("user_id")
        if isinstance(user, dict) and user.get("id") is not None:
            assignable.add(user["id"])
    invalid = [uid for uid in uids if uid not in assignable]
    if invalid:
        raise ValidationError(
            f"user_ids invalidos (no mapean a hr.employee activo): {invalid}"
        )
    return [(6, 0, list(uids))]
