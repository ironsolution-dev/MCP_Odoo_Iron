"""Fuente unica de origenes CORS permitidos (ticket 867, ADR-021 remediado).

Carga `config/cors_allowlist.yaml` UNA VEZ al importar el modulo (se hornea
en la imagen; `CORS_ALLOWLIST_PATH` permite apuntar a otro fichero solo para
tests/desarrollo — mismo patron que `app/apl_labels.py` con `APL_LABELS_PATH`).

Antes del ticket 867, `BearerMiddleware` (app/odoo_mcp_remote.py) reflejaba
CUALQUIER `Origin` recibido sin comparar contra nada (riesgo aceptado
temporal en ADR-021, hallado por julio-qa en el ticket 807). Ahora solo los
origenes de esta lista reciben `Access-Control-Allow-Origin`; el resto no
recibe ninguna cabecera CORS (la request se procesa igual — no es un 403,
es que el navegador del origen no listado no puede leer la respuesta).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "cors_allowlist.yaml"


def _resolve_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return path
    env_path = os.environ.get("CORS_ALLOWLIST_PATH")
    return Path(env_path) if env_path else _DEFAULT_PATH


def load_allowed_origins(path: Optional[Path] = None) -> frozenset[str]:
    resolved = _resolve_path(path)
    with resolved.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    origins = raw.get("allowed_origins") or []
    return frozenset(origins)


ALLOWED_ORIGINS: frozenset[str] = load_allowed_origins()
