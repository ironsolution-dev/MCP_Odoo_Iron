"""Test de aceptacion PM — ticket 737 (criterio de aceptacion 10 del diseno).

Extiende el patron de scripts/acceptance_fase_a_live.py. Lee MCP_TOKEN_WILLY
del entorno (NUNCA de argumentos en linea de comando para evitar dejarlo en
bash history). Crea 4 tareas de prueba en un PROYECTO SANDBOX (obligatorio
pasar --project-id: este script NO asume cual proyecto es seguro para
escribir), cubriendo las 4 combinaciones cliente x formato de titulo:

  (a) Claude nuevo   — tool nativa `create_task`, titulo SIN corchetes.
  (b) Claude legado  — tool nativa `create_task`, titulo CON corchetes
                        [APL 2.0][Px][Area][Tipo] (formato anterior).
  (c) ChatGPT nuevo  — protocolo `search()` con JSON {"action":"create_task",...},
                        titulo SIN corchetes.
  (d) ChatGPT legado — protocolo `search()` con JSON action, titulo CON
                        corchetes.

Para cada una: lee de vuelta (`odoo_get_task`) y verifica titulo limpio,
tag_ids EXACTOS (prioridad + departamento + tipo resueltos por
app.apl_labels), priority (estrella), y que la description tenga los 8
campos. Al final cancela las 4 tareas de prueba con motivo explicito y
imprime los IDs para documentarlos en el ticket 737 — este script NO las
deja huerfanas en el sandbox.

Este script ESCRIBE en Odoo de produccion (aunque sea en un proyecto
sandbox). Esta commiteado para que quede en git (contrato anti-Frankenstack:
"en git o no existe"), pero NO se ejecuta como parte de ningun pipeline ni
de la suite de pytest. Solo lo ejecuta QA/Infinity con OK EXPLICITO de
Willy, pasando --confirm, contra GREEN (mcp-v2.ovnisystem.com).

Uso:
    export MCP_TOKEN_WILLY=mcp_xxx
    python scripts/acceptance_ticket_737_live.py --project-id <ID_SANDBOX> --confirm
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

DEADLINE = (date.today() + timedelta(days=7)).isoformat()

APL_DESCRIPTION = (
    "👤 Responsable: Willy Hierro (prueba de aceptacion ticket 737)\n"
    "🎯 Objetivo: verificar en vivo el contrato dual titulo + etiquetas del MCP v2.\n"
    "📦 Entregable: tarea de prueba creada, leida y cancelada con evidencia en el chatter.\n"
    f"📅 Fecha limite: {DEADLINE}\n"
    "✅ Criterio de cierre: la tarea se lee de vuelta con titulo, tag_ids y priority correctos.\n"
    "📎 Evidencia requerida: salida de este script (acceptance_ticket_737_live.py).\n"
    "⚠️ Riesgo si no se cierra: el ticket 737 no puede darse por aceptado en vivo.\n"
    "▶️ Siguiente accion: cancelar esta tarea de prueba apenas se verifique."
)

# Las 4 combinaciones cliente x formato de titulo (criterio de aceptacion 10).
SCENARIOS = [
    {
        "label": "a) Claude nuevo (tool nativa, titulo sin corchetes)",
        "client": "claude",
        "title": "Verificar contrato APL 2.0 v2 via Claude formato nuevo",
        "legacy": False,
    },
    {
        "label": "b) Claude legado (tool nativa, titulo con corchetes)",
        "client": "claude",
        "title": "[APL 2.0][P1][Tecnologia][Entregable] Verificar contrato APL 2.0 v2 via Claude formato legado",
        "legacy": True,
    },
    {
        "label": "c) ChatGPT nuevo (search() JSON action, titulo sin corchetes)",
        "client": "chatgpt",
        "title": "Verificar contrato APL 2.0 v2 via ChatGPT formato nuevo",
        "legacy": False,
    },
    {
        "label": "d) ChatGPT legado (search() JSON action, titulo con corchetes)",
        "client": "chatgpt",
        "title": "[APL 2.0][P1][Tecnologia][Entregable] Verificar contrato APL 2.0 v2 via ChatGPT formato legado",
        "legacy": True,
    },
]

# Tag_ids esperados para P1 + Tecnologia + Entregable (config/apl_labels.yaml,
# verificado en vivo el 27-ago-2026, UID 29). Si Odoo cambio estos IDs desde
# entonces, este script fallara con un mensaje claro (no en silencio).
EXPECTED_TAG_IDS = {2, 9, 12}  # P1, Tecnologia, Entregable


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


def _create_via_claude(token: str, project_id: int, scenario: dict) -> dict:
    """Tool nativa create_task (lo que ve Claude.ai)."""
    resp = call(token, "create_task", {
        "project_id": project_id,
        "title": scenario["title"],
        "description": APL_DESCRIPTION,
        "deadline": DEADLINE,
        "area": "Tecnologia",
        "task_type": "Entregable",
        "priority": "P1",
    })
    return _check_error("create_task", resp)


def _create_via_chatgpt(token: str, project_id: int, scenario: dict) -> dict:
    """Protocolo search() con JSON action (lo que ve ChatGPT chat-mode)."""
    action_payload = {
        "action": "create_task",
        "project_id": project_id,
        "title": scenario["title"],
        "description": APL_DESCRIPTION,
        "deadline": DEADLINE,
        "area": "Tecnologia",
        "task_type": "Entregable",
        "priority": "P1",
    }
    resp = call(token, "search", {"query": json.dumps(action_payload, ensure_ascii=False)})
    result = _check_error("search", resp)
    results = (result or {}).get("results") or []
    if not results:
        raise RuntimeError(f"search() no devolvio results: {result}")
    first = results[0]
    if str(first.get("id", "")).startswith("error"):
        raise RuntimeError(f"search() devolvio error: {first}")
    return first.get("metadata") or first


def _extract_task_id(created: dict) -> int:
    raw_id = created.get("id")
    if isinstance(raw_id, int):
        return raw_id
    if isinstance(raw_id, str) and ":" in raw_id:
        return int(raw_id.split(":")[-1])
    if isinstance(raw_id, str) and raw_id.isdigit():
        return int(raw_id)
    raise RuntimeError(f"no pude extraer task_id de la respuesta de creacion: {created}")


def _verify(token: str, task_id: int, expected_title: str) -> list[str]:
    """Lee de vuelta y compara contra lo esperado. Devuelve lista de problemas
    (vacia si todo OK) — no levanta excepcion para poder seguir con las
    demas verificaciones y reportar todo junto."""
    problems: list[str] = []
    resp = call(token, "odoo_get_task", {"task_id": task_id})
    task = _check_error("odoo_get_task", resp)
    if task.get("error"):
        return [f"odoo_get_task devolvio error: {task}"]

    name = task.get("name", "")
    # Titulo legado: el servidor retira los corchetes; comparamos contra la
    # parte posterior al ultimo "] " (mismo criterio que app.apl_title).
    expected_clean = expected_title
    if expected_title.startswith("[") and "] " in expected_title:
        expected_clean = expected_title.rsplit("] ", 1)[-1]
    if name != expected_clean:
        problems.append(f"titulo esperado {expected_clean!r}, obtenido {name!r}")
    if name.startswith("["):
        problems.append(f"titulo NO deberia tener corchetes tras normalizar: {name!r}")

    tag_field = task.get("tag_ids")
    tag_ids = set()
    if isinstance(tag_field, list):
        for t in tag_field:
            if isinstance(t, (list, tuple)) and t:
                tag_ids.add(t[0])
            elif isinstance(t, int):
                tag_ids.add(t)
    if tag_ids != EXPECTED_TAG_IDS:
        problems.append(f"tag_ids esperados {EXPECTED_TAG_IDS}, obtenidos {tag_ids}")

    if task.get("priority") != "2":  # P1 -> estrella '2'
        problems.append(f"priority esperada '2' (P1), obtenida {task.get('priority')!r}")

    description = task.get("description") or ""
    required_substrings = [
        "responsable", "objetivo", "entregable", "fecha limite",
        "criterio de cierre", "evidencia requerida",
        "riesgo si no se cierra", "siguiente accion",
    ]
    missing = [s for s in required_substrings if s not in description.lower()]
    if missing:
        problems.append(f"description sin estos campos: {missing}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id", type=int, required=True,
        help="ID del proyecto SANDBOX donde crear las 4 tareas de prueba. "
             "Obligatorio: este script no asume cual proyecto es seguro.",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Confirmacion explicita obligatoria. Sin esta flag el script NO escribe nada.",
    )
    args = parser.parse_args()

    token = os.environ.get("MCP_TOKEN_WILLY")
    if not token:
        print("[fail] MCP_TOKEN_WILLY no esta en el entorno. Exportalo antes de correr.")
        return 1

    print("ESTE SCRIPT ESCRIBE EN ODOO DE PRODUCCION (proyecto sandbox):")
    print(f"  - Crea 4 tareas de prueba en el proyecto {args.project_id} "
          "(Claude nuevo/legado, ChatGPT nuevo/legado).")
    print("  - Lee cada una de vuelta y verifica titulo, tag_ids, priority, 8 campos.")
    print("  - Cancela las 4 al final con motivo explicito (no quedan huerfanas).")
    print(f"  - Endpoint: {ENDPOINT}  Token: {_redact(token)}")
    if not args.confirm:
        print("\n[abort] Falta --confirm. Solo QA/Infinity con OK explicito de Willy "
              "debe pasar esta flag. Nada se escribio.")
        return 1

    failures: list[str] = []
    created_ids: list[tuple[str, int]] = []

    for scenario in SCENARIOS:
        label = scenario["label"]
        print(f"\n[crear] {label} ...")
        try:
            if scenario["client"] == "claude":
                created = _create_via_claude(token, args.project_id, scenario)
            else:
                created = _create_via_chatgpt(token, args.project_id, scenario)
            task_id = _extract_task_id(created)
            created_ids.append((label, task_id))
            print(f"  [ok] task_id={task_id}")

            problems = _verify(token, task_id, scenario["title"])
            if problems:
                print(f"  [fail] verificacion: {problems}")
                failures.append(f"{label}: {problems}")
            else:
                print("  [ok] verificacion: titulo, tag_ids, priority y 8 campos correctos")
        except Exception as e:  # noqa: BLE001
            print(f"  [fail] {e.__class__.__name__}: {str(e)[:300]}")
            failures.append(f"{label}: {e}")

    print(f"\n[cancelar] {len(created_ids)} tarea(s) de prueba ...")
    for label, task_id in created_ids:
        try:
            resp = call(token, "cancel_task", {
                "id": f"task:{task_id}",
                "reason": "Tarea de prueba del script de aceptacion ticket 737, cancelada tras verificar",
                "cancelled_stage_id": 1,
            })
            _check_error("cancel_task", resp)
            print(f"  [ok] task:{task_id} cancelada ({label})")
        except Exception as e:  # noqa: BLE001
            print(f"  [fail] no se pudo cancelar task:{task_id} ({label}): {e}")
            failures.append(f"cancel_task:{task_id}")

    print("\nIDs de tareas de prueba creadas/canceladas (documentar en ticket 737):")
    for label, task_id in created_ids:
        print(f"  - {label}: task:{task_id}")

    if failures:
        print(f"\nFAIL: {failures}")
        return 1
    print("\nALL OK — aceptacion PM ticket 737 completa en vivo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
