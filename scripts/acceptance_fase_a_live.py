"""Test de aceptacion PM — Fase A daily driver (sec 7).

Extiende el patron de scripts/smoke_test_mcp.py. Lee MCP_TOKEN_WILLY del
entorno (NUNCA de argumentos en linea de comando para evitar dejarlo en bash
history). Mueve las tareas reales 653/654/655/657 del proyecto 3 al proyecto
12 via `move_task_to_project`, y corre la fecha de la tarea 655 usando la
clave alias `deadline` (sec G2) via `update_task`.

Este script ESCRIBE en Odoo de produccion. Esta commiteado para que quede
en git (contrato anti-Frankenstack: "en git o no existe"), pero NO se ejecuta
como parte de ningun pipeline ni de la suite de pytest. Solo lo ejecuta
QA/Infinity con OK EXPLICITO de Willy, pasando --confirm.

Uso:
    export MCP_TOKEN_WILLY=mcp_xxx
    python scripts/acceptance_fase_a_live.py --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date, timedelta
from typing import Any


ENDPOINT = os.environ.get("MCP_V2_ENDPOINT", "https://mcp-v2.ovnisystem.com/mcp")

TASK_IDS = [653, 654, 655, 657]
SOURCE_PROJECT_ID = 3
TARGET_PROJECT_ID = 12
DEADLINE_TASK_ID = 655
# Fecha calculada en runtime (no hardcodeada): +30 dias desde hoy. El script
# imprime la fecha exacta que va a usar antes de escribir nada.
NEW_DEADLINE = (date.today() + timedelta(days=30)).isoformat()


def _redact(token: str) -> str:
    if not token:
        return "<empty>"
    if len(token) <= 12:
        return "<redacted>"
    return token[:6] + "..." + token[-4:]


def call(token: str, tool: str, args: dict[str, Any] = None, timeout: int = 30) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args or {}},
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _check_error(tool: str, response: dict) -> Any:
    if "error" in response:
        raise RuntimeError(f"{tool} devolvio error JSON-RPC: {response['error']}")
    result = response.get("result")
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(f"{tool} devolvio error de tool: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Confirmacion explicita obligatoria. Sin esta flag el script NO escribe nada.",
    )
    args = parser.parse_args()

    token = os.environ.get("MCP_TOKEN_WILLY")
    if not token:
        print("[fail] MCP_TOKEN_WILLY no esta en el entorno. Exportalo antes de correr.")
        return 1

    print("ESTE SCRIPT ESCRIBE EN ODOO DE PRODUCCION:")
    print(f"  - Mueve las tareas {TASK_IDS} del proyecto {SOURCE_PROJECT_ID} "
          f"al proyecto {TARGET_PROJECT_ID} (odoo_move_task_to_project).")
    print(f"  - Cambia el deadline de la tarea {DEADLINE_TASK_ID} a {NEW_DEADLINE} "
          f"usando el alias 'deadline' (update_task).")
    print(f"  - Endpoint: {ENDPOINT}  Token: {_redact(token)}")
    if not args.confirm:
        print("\n[abort] Falta --confirm. Solo QA/Infinity con OK explicito de Willy "
              "debe pasar esta flag. Nada se escribio.")
        return 1

    failures: list[str] = []

    print(f"\n[1/2] Moviendo tareas {TASK_IDS}: proyecto {SOURCE_PROJECT_ID} -> "
          f"{TARGET_PROJECT_ID} via move_task_to_project ...")
    for task_id in TASK_IDS:
        try:
            resp = call(token, "move_task_to_project",
                       {"id": f"task:{task_id}", "new_project_id": TARGET_PROJECT_ID})
            result = _check_error("move_task_to_project", resp)
            print(f"  [ok]   task:{task_id} movida. metadata id={result.get('id')}")
        except Exception as e:  # noqa: BLE001
            print(f"  [fail] task:{task_id}  {e.__class__.__name__}: {str(e)[:200]}")
            failures.append(f"move_task_to_project:{task_id}")

    print(f"\n[2/2] Corriendo deadline de task:{DEADLINE_TASK_ID} a {NEW_DEADLINE} "
          f"(clave 'deadline') via update_task ...")
    try:
        resp = call(token, "update_task",
                   {"id": f"task:{DEADLINE_TASK_ID}", "changes": {"deadline": NEW_DEADLINE}})
        result = _check_error("update_task", resp)
        print(f"  [ok]   task:{DEADLINE_TASK_ID} deadline actualizado. metadata id={result.get('id')}")
    except Exception as e:  # noqa: BLE001
        print(f"  [fail] task:{DEADLINE_TASK_ID}  {e.__class__.__name__}: {str(e)[:200]}")
        failures.append(f"update_task:{DEADLINE_TASK_ID}")

    if failures:
        print(f"\nFAIL: {failures}")
        return 1
    print("\nALL OK — aceptacion PM Fase A completa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
